import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { distantGeometry } from "./exhibit-detail.js";
import { miniature } from "./island-scenes.js";
import { workbenchPanel, objectCard, readOnly } from "./island-panels.js";
import { assetPanel } from "./asset-manager.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { createOcean } from "./ocean.js";
import { sound, soundToggle } from "./sound.js";

// ---------- 岛的形状：外圈低、中央是展台平台 ----------
const ISLAND = 60, PLATEAU = 9, TOP = 6, BEACH = 4.5;
const PATH_OUTER = 53, PATH_INNER = 11.5, TURNS = 2.2, PATH_START = Math.PI * 0.85;
const UP = new THREE.Vector3(0, 1, 0);

function baseHeight(r) {
  if (r <= PLATEAU) return TOP;
  if (r >= ISLAND) return -(r - ISLAND) * 0.55;
  return TOP * Math.pow(1 - (r - PLATEAU) / (ISLAND - PLATEAU), 1.35);
}
function bumps(x, z) {
  return Math.sin(x * 0.21) * Math.cos(z * 0.17) * 0.22 + Math.sin(x * 0.07 + z * 0.09) * 0.3;
}
const terraces=[],gardens=[];
function naturalGround(x, z) {
  const r = Math.hypot(x, z);
  let y = baseHeight(r);
  if (r > PLATEAU + 1.5 && r < ISLAND - 2) y += bumps(x, z) * Math.min(1, (r - PLATEAU - 1.5) / 6, (ISLAND - 2 - r) / 4);
  return y;
}

function ground(x,z) {
  const natural=naturalGround(x,z);
  let level=natural;
  for(const plaza of terraces){
    const distance=Math.hypot(x-plaza.x,z-plaza.z);
    if(distance<4.8){level=THREE.MathUtils.lerp(plaza.y,natural,THREE.MathUtils.smoothstep(distance,3.55,4.8));break;}
  }
  let nearestLevel=level,weight=0;
  for(const plot of gardens){
    const distance=Math.hypot(x-plot.x,z-plot.z),edge=plot.radius+plot.feather;
    if(distance>=edge)continue;
    const strength=1-THREE.MathUtils.smoothstep(distance,plot.radius+.22,edge);
    if(strength>weight){weight=strength;nearestLevel=plot.y;if(strength===1)break;}
  }
  return THREE.MathUtils.lerp(level,nearestLevel,weight);
}
const LAYOUT=Object.freeze({
  era:{offset:2.6,height:1.6,radius:1.40}, moment:{offset:1.6,height:.60,radius:.73},
  sign:{offset:1.6,height:.60,radius:.43}, coast:{offset:2.25,height:1.20,radius:1.48},
  gallery:{offset:1.95,height:1.16,radius:1.1}, entrance:{offset:2.18,height:1.38,radius:1.14},
  home:{offset:6.15,radius:1.65}, mailbox:{offset:2.65,radius:.42},
  month:{offset:1.38,radius:.27}, plazaRadius:3.5, stoneLip:.075
});
const pathStone=new THREE.MeshStandardMaterial({color:"#d9c9ab",roughness:.92});

const PALETTE = {
  cool: new THREE.Color("#86a4ff"), warm: new THREE.Color("#ffb35c"), none: new THREE.Color("#6b6478"),
  gate: "#a6553f", resin: "#efe6d6",
  roofs: ["#b8775a", "#7f9a7c", "#9c88b5", "#c9a161", "#6f8ca6", "#b0675f", "#8f7a6a"],
};

let seed = 7;
const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;

// ---------- 渲染器 ----------
const stage = document.getElementById("stage");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 1.45));
renderer.setSize(innerWidth, innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.domElement.tabIndex=-1;
stage.appendChild(renderer.domElement);

const labels = new CSS2DRenderer();
labels.setSize(innerWidth, innerHeight);
labels.domElement.className = "label-layer";
document.body.appendChild(labels.domElement);
const guideLayer=document.createElementNS("http://www.w3.org/2000/svg","svg");
guideLayer.setAttribute("aria-hidden","true");guideLayer.classList.add("stage-guides");
labels.domElement.append(guideLayer);
const stageGuides=new WeakMap();

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2("#76607f", 0.0035);
const camera = new THREE.PerspectiveCamera(42, innerWidth / innerHeight, 0.05, 1200);
camera.position.set(0, 95, 128);
renderer.shadowMap.autoUpdate = false;
renderer.shadowMap.needsUpdate = true;
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 3, 0);
controls.enableDamping = true;
controls.maxPolarAngle = Math.PI * 0.47;
controls.minDistance = 4;
controls.maxDistance = 410;

// ---------- 素材 ----------
const assets = {};
const simplerProps = new WeakMap(), foliageBatches = [];
const ASSET_NAMES = ["tree_round", "tree_round_b", "tree_autumn", "tree_pine", "rock_a", "rock_b", "grass", "flowers",
  "cottage", "cottage_small", "lantern", "bench", "fence", "boat", "pier"];
// 一丛花的 24 瓣、长椅的木条在文件里是独立网格。载入时合并同类表面，
// 保留原来的顶点颜色；只有可单独改色的屋顶、亮窗和灯罩各自留一层。
function assembleProp(source, name) {
  const surfaces=new Map(), result=new THREE.Group();
  source.updateMatrixWorld(true);
  source.traverse(mesh=>{
    if(!mesh.isMesh) return;
    const material=mesh.material;
    const kind=["roof","glow","window"].includes(material.name)?material.name:"paint";
    const g=mesh.geometry.index ? mesh.geometry.toNonIndexed() : mesh.geometry.clone();
    g.applyMatrix4(mesh.matrixWorld);
    for(const key of Object.keys(g.attributes)) if(key!=="position"&&key!=="normal") g.deleteAttribute(key);
    if(!g.attributes.normal)g.computeVertexNormals();
    if(kind==="paint"){
      const array=new Float32Array(g.attributes.position.count*3);
      for(let i=0;i<array.length;i+=3)material.color.toArray(array,i);
      g.setAttribute("color",new THREE.BufferAttribute(array,3));
    }
    if(!surfaces.has(kind)){
      const finish=kind==="paint"?new THREE.MeshLambertMaterial({vertexColors:true}):material.clone();
      finish.name=kind;surfaces.set(kind,{finish,parts:[]});
    }
    surfaces.get(kind).parts.push(g);
  });
  for(const {finish,parts} of surfaces.values()){
    const mesh=new THREE.Mesh(mergeGeometries(parts),finish);
    if(name==="grass"||name==="flowers") {
      const selected=parts.filter((_,i)=>i%3===0);
      simplerProps.set(mesh.geometry,mergeGeometries(selected));
    } else if(name.startsWith("tree_") || name.startsWith("cottage")) {
      const reduced=distantGeometry(mesh.geometry,4,80);
      if(reduced) simplerProps.set(mesh.geometry,reduced);
    }
    for(const geometry of parts) geometry.dispose();
    mesh.castShadow=mesh.receiveShadow=true;
    result.add(mesh);
  }
  return result;
}
async function loadAssets() {
  const loader=new GLTFLoader();
  await Promise.all(ASSET_NAMES.map(async name=>{
    const gltf=await loader.loadAsync(`/assets/${name}.glb`);
    assets[name]=assembleProp(gltf.scene,name);
  }));
}
function place(name, pos, rotY = 0, scale = 1) {
  const obj = assets[name].clone(true);
  obj.position.copy(pos);
  obj.rotation.y = rotY;
  obj.scale.setScalar(scale);
  scene.add(obj);
  return obj;
}
// 同一种东西摆很多份时用实例化，几百棵树也只算几次绘制
// tint: { 材质名: i => 颜色 }。名为 glow 的玻璃改成不受光照的亮色，每份可以不同颜色。
function scatterInstances(name, items, { shadow = true, tint = {} } = {}) {
  if (!items.length) return;
  const src = assets[name];
  src.updateMatrixWorld(true);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3();
  src.traverse((mesh) => {
    if (!mesh.isMesh) return;
    const colorOf = tint[mesh.material.name];
    let material = mesh.material;
    if (colorOf && mesh.material.name === "glow") material = new THREE.MeshBasicMaterial({ color: "#ffffff" });
    else if (colorOf) { material = mesh.material.clone(); material.color.set("#ffffff"); }
    const inst = new THREE.InstancedMesh(mesh.geometry, material, items.length);
    const matrices=[];
    items.forEach((it, i) => {
      q.setFromAxisAngle(UP, it.rotY);
      s.setScalar(it.scale);
      m.compose(it.pos, q, s).multiply(mesh.matrixWorld);
      inst.setMatrixAt(i, m);
      matrices.push(m.clone());
      if (colorOf) inst.setColorAt(i, new THREE.Color(colorOf(i)));
    });
    inst.castShadow = shadow;
    inst.receiveShadow = true;
    scene.add(inst);
    const farGeometry=simplerProps.get(mesh.geometry);
    if(farGeometry && !colorOf) {
      const far=new THREE.InstancedMesh(farGeometry,material,items.length);
      far.castShadow=shadow;far.receiveShadow=false;scene.add(far);
      inst.frustumCulled=far.frustumCulled=false;
      foliageBatches.push({close:inst,far,items,matrices,radius:name.startsWith("home-")?19:name==="flowers"||name==="grass"?22:35});
    }
  });
}
const lastFoliagePosition=new THREE.Vector3(Infinity,0,0);
function refreshDetails() {
  updateFoliage();
  for(const d of detailedModels)d.mesh.geometry=camera.position.distanceToSquared(d.group.position)>32**2?d.far:d.near;
}
function updateFoliage() {
  if(camera.position.distanceToSquared(lastFoliagePosition)<.7) return;
  lastFoliagePosition.copy(camera.position);
  for(const {close,far,items,matrices,radius} of foliageBatches) {
    let nearby=0,distant=0;
    for(let i=0;i<items.length;i++) {
      if(camera.position.distanceToSquared(items[i].pos)<radius*radius) close.setMatrixAt(nearby++,matrices[i]);
      else far.setMatrixAt(distant++,matrices[i]);
    }
    close.count=nearby;far.count=distant;
    close.visible=nearby>0;far.visible=distant>0;
    close.instanceMatrix.needsUpdate=far.instanceMatrix.needsUpdate=true;
  }
}

// ---------- 天空、海、星、光 ----------
const SUN_DIR = new THREE.Vector3(-0.72, 0.1, -0.68).normalize();
let ocean = null;
function sky() {
  const material = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: { sun: { value: SUN_DIR } },
    vertexShader: `varying vec3 vDir; void main(){ vDir = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.); }`,
    fragmentShader: `
      uniform vec3 sun; varying vec3 vDir;
      void main(){
        float y = clamp(vDir.y, -0.2, 1.0);
        vec3 horizon = vec3(0.96,0.64,0.50), mid = vec3(0.42,0.35,0.58), top = vec3(0.10,0.09,0.19);
        vec3 c = mix(horizon, mid, smoothstep(0.0, 0.22, y));
        c = mix(c, top, smoothstep(0.18, 0.75, y));
        c = mix(vec3(0.28,0.22,0.33), c, smoothstep(-0.2, 0.02, vDir.y));
        float g = pow(max(dot(normalize(vDir), sun), 0.), 18.);
        c += vec3(1.0,0.62,0.38) * g * 0.75;
        gl_FragColor = vec4(c, 1.);
      }`,
  });
  scene.add(new THREE.Mesh(new THREE.SphereGeometry(600, 48, 24), material));

  const stars = new THREE.BufferGeometry(), points = [];
  for (let i = 0; i < 1400; i++) {
    const u = rand() * Math.PI * 2, v = 0.25 + rand() * 0.75, r = 560, cy = Math.sqrt(1 - v * v);
    points.push(Math.cos(u) * cy * r, v * r, Math.sin(u) * cy * r);
  }
  stars.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
  scene.add(new THREE.Points(stars, new THREE.PointsMaterial({ color: "#fff4e6", size: 1.4, sizeAttenuation: false, transparent: true, opacity: 0.75, fog: false })));

  // 会动的海：代码生成的波浪，靠岸一圈白沫，见 ocean.js
  ocean = createOcean({ shore: ISLAND - 0.5, shoreWidth: 6 });
  scene.add(ocean.group);

  scene.add(new THREE.HemisphereLight("#efe0f3", "#baa287", 1.65));
  const sunLight = new THREE.DirectionalLight("#ffbf94", 2.1);
  sunLight.position.copy(SUN_DIR).multiplyScalar(95).setY(34);
  sunLight.castShadow = true;
  sunLight.shadow.mapSize.set(2048, 2048);
  Object.assign(sunLight.shadow.camera, { left: -70, right: 70, top: 70, bottom: -70, near: 1, far: 260 });
  sunLight.shadow.bias = -0.0004;
  sunLight.shadow.normalBias = 0.03;
  scene.add(sunLight);
}

// ---------- 地形：沙滩、草坡、平台 ----------
// Small level pads need finer terrain triangles than the open meadow. Shared edge
// midpoints keep the surrounding coarse mesh watertight without refining the entire island.
function refineExhibitGround(geometry) {
  const patches=gardens.filter(plot=>plot.exhibit);
  if(!patches.length)return;
  const points=Array.from(geometry.attributes.position.array);
  let triangles=Array.from(geometry.index.array);
  for(let pass=0;pass<2;pass++){
    const edges=new Map(),next=[];
    function midpoint(a,b){
      const key=Math.min(a,b)*1000000+Math.max(a,b);
      if(edges.has(key))return edges.get(key);
      const x=(points[a*3]+points[b*3])*.5,z=(points[a*3+2]+points[b*3+2])*.5;
      const near=patches.some(p=>(p.x-x)**2+(p.z-z)**2<(p.radius+.85)**2);
      const index=near?points.length/3:-1;
      if(near)points.push(x,0,z);
      edges.set(key,index);return index;
    }
    for(let i=0;i<triangles.length;i+=3){
      const a=triangles[i],b=triangles[i+1],c=triangles[i+2];
      const ab=midpoint(a,b),bc=midpoint(b,c),ca=midpoint(c,a);
      if(ab<0 && bc<0 && ca<0){next.push(a,b,c);continue;}
      if(ab>=0 && bc>=0 && ca>=0){next.push(a,ab,ca,ab,b,bc,ca,bc,c,ab,bc,ca);continue;}
      // A fan lets the two sides of a partially refined edge use identical vertices.
      const rim=[a];if(ab>=0)rim.push(ab);rim.push(b);if(bc>=0)rim.push(bc);rim.push(c);if(ca>=0)rim.push(ca);
      const center=points.length/3;
      points.push((points[a*3]+points[b*3]+points[c*3])/3,0,(points[a*3+2]+points[b*3+2]+points[c*3+2])/3);
      for(let j=0;j<rim.length;j++)next.push(center,rim[j],rim[(j+1)%rim.length]);
    }
    triangles=next;
  }
  geometry.deleteAttribute("normal");geometry.deleteAttribute("uv");
  geometry.setAttribute("position",new THREE.Float32BufferAttribute(points,3));geometry.setIndex(triangles);
}
const walkSurfaces=[];
function island() {
  const size = 136, seg = 144;
  const geometry = new THREE.PlaneGeometry(size, size, seg, seg);
  geometry.rotateX(-Math.PI / 2);refineExhibitGround(geometry);
  const p = geometry.attributes.position, colors = [];
  const sand = new THREE.Color("#d8c39a"), grassA = new THREE.Color("#8d9b67"), grassB = new THREE.Color("#a3a571"), dirt = new THREE.Color("#b49c78"), stone = new THREE.Color("#cdbfa6");
  const c = new THREE.Color();
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i), z = p.getZ(i), r = Math.hypot(x, z);
    p.setY(i, ground(x, z));
    const n = 0.5 + 0.5 * Math.sin(x * 0.13 + Math.cos(z * 0.11) * 2.0);
    c.copy(grassA).lerp(grassB, n);
    if (r > ISLAND - BEACH) c.lerp(sand, THREE.MathUtils.smoothstep(r, ISLAND - BEACH, ISLAND - BEACH + 2.5));
    if (r < PLATEAU + 2.2) c.lerp(stone, THREE.MathUtils.smoothstep(PLATEAU + 2.2 - r, 0, 1.5));
    const d = pathDistance(x, z);
    if (d < 2.2) c.lerp(dirt, (1 - THREE.MathUtils.smoothstep(d, 0.9, 2.2)) * 0.6);
    colors.push(c.r, c.g, c.b);
  }
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  geometry.computeVertexNormals();
  const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.97 }));
  mesh.receiveShadow = true;
  walkSurfaces.push(mesh);scene.add(mesh);
}

// ---------- 时间小路 ----------
function monthsBetween(start, end) {
  const out = [];
  let [y, m] = start.split("-").map(Number);
  const [ey, em] = end.split("-").map(Number);
  while (y < ey || (y === ey && m <= em)) {
    out.push(`${y}-${String(m).padStart(2, "0")}`);
    if (++m > 12) { m = 1; y++; }
  }
  return out;
}
function monthIndex(months,date) {
  const month=String(date||"").slice(0,7),index=months.indexOf(month);
  return index<0?(month>months[months.length-1]?months.length-1:0):index;
}
function pathPoint(t) {
  const r = PATH_OUTER - (PATH_OUTER - PATH_INNER) * t;
  const a = PATH_START + t * TURNS * Math.PI * 2;
  const x = Math.cos(a) * r, z = Math.sin(a) * r;
  return new THREE.Vector3(x, ground(x, z) + 0.06, z);
}
function pathFrame(t) {
  const p = pathPoint(t), ahead = pathPoint(Math.min(1, t + 0.002)), back = pathPoint(Math.max(0, t - 0.002));
  const tangent = ahead.sub(back).setY(0).normalize();
  const side = new THREE.Vector3().crossVectors(tangent, UP).normalize();
  if (side.dot(new THREE.Vector3(p.x, 0, p.z)) < 0) side.negate(); // side 指向岛外
  return { p, tangent, side, t };
}
const PATH_SAMPLES = [];
for (let i = 0; i <= 600; i++) PATH_SAMPLES.push(pathPoint(i / 600));
{ // 终点直通平台
  const end = PATH_SAMPLES[PATH_SAMPLES.length - 1];
  for (let k = 1; k <= 6; k++) { const f = 1 - k * 0.07; PATH_SAMPLES.push(new THREE.Vector3(end.x * f, TOP, end.z * f)); }
}
const walkingLanes=[{points:PATH_SAMPLES.slice(),halfWidth:.82}];
function pavementGap(x,z) {
  let gap=Infinity;
  for(const lane of walkingLanes) {
    let best=Infinity;
    for(let i=1;i<lane.points.length;i++){
      const a=lane.points[i-1],b=lane.points[i],dx=b.x-a.x,dz=b.z-a.z;
      const k=THREE.MathUtils.clamp(((x-a.x)*dx+(z-a.z)*dz)/(dx*dx+dz*dz||1),0,1);
      best=Math.min(best,(x-a.x-k*dx)**2+(z-a.z-k*dz)**2);
    }
    gap=Math.min(gap,Math.sqrt(best)-lane.halfWidth);
  }
  return gap;
}
function pathDistance(x, z) {
  let best = Infinity;
  for (const s of PATH_SAMPLES) { const d = (s.x - x) ** 2 + (s.z - z) ** 2; if (d < best) best = d; }
  return Math.sqrt(best);
}

function path() {
  // 小路是一块块踏石，比一条带子更像走出来的路
  const stones = [];
  const total = 870;
  for (let i = 0; i <= total; i++) {
    const t = i / total;
    const { p, side, tangent } = pathFrame(t);
    for (const off of [-0.38,0.38]) {
      const jitter = (rand() - 0.5) * 0.18;
      const pos = p.clone().addScaledVector(side, off + jitter).addScaledVector(tangent, (rand() - 0.5) * 0.2);
      pos.y = ground(pos.x, pos.z) + 0.02;
      stones.push({ pos, rotY: rand() * Math.PI, scale: 0.42 + rand() * 0.16 });
    }
  }
  const end = pathPoint(1);
  for (let k = 0; k < 12; k++) {
    const f = 1 - k * 0.022;
    for (const off of [-0.4, 0.4]) {
      const dir = new THREE.Vector3(-end.z, 0, end.x).normalize();
      const pos = new THREE.Vector3(end.x * f, 0, end.z * f).addScaledVector(dir, off);
      pos.y = ground(pos.x, pos.z) + 0.02;
      stones.push({ pos, rotY: rand() * Math.PI, scale: 0.45 });
    }
  }
  function steppingLine(points,width){
    walkingLanes.push({points:points.map(frame=>frame.p),halfWidth:width+.32});
    for(let i=0;i<points.length;i++) {
      const {p,side}=points[i];
      for(const off of [-width,width]){
        const pos=p.clone().addScaledVector(side,off);pos.y=ground(pos.x,pos.z)+.025;
        stones.push({pos,rotY:(i*.74)%Math.PI,scale:.48});
      }
      PATH_SAMPLES.push(p);
    }
  }
  const beachEntry=pathPoint(0),junction=arcFrame(coastRadius,coastAngle).p;
  const direction=junction.clone().sub(beachEntry).setY(0).normalize(),sidewalk=new THREE.Vector3(-direction.z,0,direction.x);
  steppingLine(Array.from({length:23},(_,i)=>({p:beachEntry.clone().lerp(junction,i/22),side:sidewalk})),.32);
  steppingLine(Array.from({length:74},(_,i)=>arcFrame(coastRadius,coastAngle-i*.5/coastRadius,-1)),.33);
  steppingLine(Array.from({length:7},(_,i)=>{const f=arcFrame(coastRadius+i*.51,coastAngle);return {p:f.p,side:f.tangent};}),.33);
  steppingLine(Array.from({length:120},(_,i)=>arcFrame(galleryRadius,i/119*Math.PI*2)),.29);
  const geo = new THREE.CylinderGeometry(0.62, 0.68, 0.12, 7);
  const mat = pathStone;
  const inst = new THREE.InstancedMesh(geo, mat, stones.length);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3();
  inst.receiveShadow=true;scene.add(inst);
  return ()=>{
    stones.forEach((st,i)=>{
      st.pos.y=ground(st.pos.x,st.pos.z)+.02;
      q.setFromAxisAngle(UP,st.rotY);s.set(st.scale,1,st.scale*.8);
      inst.setMatrixAt(i,m.compose(st.pos,q,s));
    });
    inst.instanceMatrix.needsUpdate=true;
  };
}

function glowTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d"), grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.25, "rgba(255,255,255,.45)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}
const GLOW = glowTexture();
function glow(color, size, opacity = 0.9) {
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color, transparent: true, opacity, depthWrite: false, blending: THREE.AdditiveBlending, fog: false }));
  sprite.scale.setScalar(size);
  return sprite;
}

const pickables = [];
let lanternGlow;
const namedObjects = new Map(), tagRecords = [], cards = new Map();
let currentWorld = {}, portal, renderWorld, clock, pausedAt = 0;
const cleanCardText = text => String(text ?? "").replace(/\s*\[k:[^\]]*\]/g,"").trim();
function cardData(item, fallback) {
  const key = item?.card_id;
  if(key && cards.has(key)) return cards.get(key);
  const source = {...fallback, ...item?.card};
  const data = Object.fromEntries(["kicker","title","text","aside"].map(k=>[k,cleanCardText(source[k])]));
  if(key) { data.id=key; cards.set(key,data); }
  if(item?.photo_url) data.photo_url=item.photo_url;
  return data;
}
function coreCard(key, fallback) { return cardData({card_id:key,card:currentWorld.cards?.[key]},fallback); }
function register(obj, data, id, tagHeight, category) {
  obj.userData.pick=data;
  if(!pickables.includes(obj)) pickables.push(obj);
  if(id) namedObjects.set(id,obj);
  if(data.id && !namedObjects.has(data.id)) namedObjects.set(data.id,obj);
  if(!category) return;
  const el=document.createElement("div");
  el.className="tag "+(category==="era"?"era-tag":"person");
  el.textContent=data.title;
  const label=new CSS2DObject(el);
  label.position.y=tagHeight;
  obj.add(label);
  tagRecords.push({el,label,obj,data,category});
  if(category==="era"){
    const line=document.createElementNS("http://www.w3.org/2000/svg","line");
    guideLayer.append(line);stageGuides.set(el,line);
  }
}
const colliders = [];
const reservedSites=[];
const routeMeters=[0];
for(let i=1;i<=600;i++) routeMeters.push(routeMeters[i-1]+Math.hypot(PATH_SAMPLES[i].x-PATH_SAMPLES[i-1].x,PATH_SAMPLES[i].z-PATH_SAMPLES[i-1].z));
const routeLength=routeMeters.at(-1);
function routeAt(t) {
  const index=THREE.MathUtils.clamp(t,0,1)*600, i=Math.floor(index);
  return THREE.MathUtils.lerp(routeMeters[i],routeMeters[Math.min(600,i+1)],index-i);
}
function routeFrame(distance) {
  let lo=0,hi=600;
  while(hi-lo>1) {const mid=(lo+hi)>>1;if(routeMeters[mid]<=distance)lo=mid;else hi=mid;}
  return pathFrame((lo+THREE.MathUtils.clamp((distance-routeMeters[lo])/(routeMeters[hi]-routeMeters[lo]),0,1))/600);
}
function arcFrame(radius,angle,clockwise=1) {
  const side=new THREE.Vector3(Math.cos(angle),0,Math.sin(angle));
  const p=side.clone().multiplyScalar(radius);p.y=ground(p.x,p.z);
  return {p,side,tangent:new THREE.Vector3(-side.z*clockwise,0,side.x*clockwise)};
}
const coastAngle=PATH_START-.18, coastRadius=55.1, galleryRadius=9.22;
function routeSite(kind,frameAt,anchor,side,{start=0,end=routeLength,step=.48,ownPlaza=null,radius=LAYOUT[kind].radius,offset=LAYOUT[kind].offset}={}) {
  for(let tick=0;tick<2*Math.ceil((end-start)/step)+3;tick++){
    const d=anchor+(tick%2?1:-1)*Math.ceil(tick/2)*step;
    if(d<start || d>end) continue;
    const frame=frameAt(d), pos=frame.p.clone().addScaledVector(frame.side,side*offset);
    if(pavementGap(pos.x,pos.z)<radius+.012)continue;
    if(kind==="home" && (Math.hypot(pos.x,pos.z)<13 || pathDistance(pos.x,pos.z)<5 || blocksSculptureView(pos.x,pos.z,radius)))continue;
    if(terraces.some(g=>g!==ownPlaza && Math.hypot(g.x-pos.x,g.z-pos.z)<LAYOUT.plazaRadius+radius+.08))continue;
    if(colliders.some(c=>Math.hypot(c.x-pos.x,c.z-pos.z)<(c.space||c.r)+radius+.1)) continue;
    pos.y=ground(pos.x,pos.z);
    const face=Math.atan2(frame.p.x-pos.x,frame.p.z-pos.z);
    const site={pos,face,radius,kind,look:frame.p,offset,side,d};
    reservedSites.push(site);
    if(kind==="moment" || kind==="coast")gardens.push({x:pos.x,z:pos.z,y:pos.y,radius,feather:.67,exhibit:true});
    colliders.push({x:pos.x,z:pos.z,r:radius,space:radius,site});
    return site;
  }
  throw new Error("步道没有足够的间距 "+kind);
}
const sculptureViews = [];
function blocksSculptureView(x,z,radius) {
  return sculptureViews.some(({origin,front}) => {
    const dx=x-origin.x,dz=z-origin.z;
    const along=THREE.MathUtils.clamp(dx*front.x+dz*front.z,0,5.6);
    const clearance=radius+.62+along*.29;
    return (dx-along*front.x)**2+(dz-along*front.z)**2 < clearance**2;
  });
}

function recolor(obj, name, color, emissive) {
  obj.traverse((m) => {
    if (!m.isMesh || m.material.name !== name) return;
    m.material = m.material.clone();
    m.material.color.set(color);
    if (emissive !== undefined) { m.material.emissive.set(color); m.material.emissiveIntensity = emissive; }
  });
}

// 看不见的点选块：批量绘制的东西靠它被点到、挂标签
const PROXY_MAT = new THREE.MeshBasicMaterial({ visible: false });
function proxy(pos, w, h, pick) {
  const box = new THREE.Mesh(new THREE.BoxGeometry(w, h, w), PROXY_MAT);
  box.position.copy(pos).setY(pos.y + h / 2);
  box.userData.pick = pick;
  box.userData.proxy = true;
  scene.add(box);
  pickables.push(box);
  return box;
}

function lanternsFor(months, emotions) {
  const byMonth = new Map(emotions.map((e) => [e.month, e]));
  const peak = Math.max(...emotions.map((e) => e.pos + e.neg), 1);
  const items = [], colors = [], lights=[];
  months.forEach((month, i) => {
    const t = i / Math.max(1,months.length - 1);
    const site=routeSite("month",routeFrame,routeAt(t),1);
    const {side}=routeFrame(site.d);
    const e = byMonth.get(month);
    const total = e ? e.pos + e.neg : 0;
    const ratio = total ? e.pos / total : 0.5;
    const hasData = e?.has_data ?? (total > 0);
    const color = hasData ? PALETTE.cool.clone().lerp(PALETTE.warm, THREE.MathUtils.smoothstep(ratio, 0.3, 0.8)) : PALETTE.none;
    const base=site.pos;
    // 灯臂朝向小路
    const rotY = Math.atan2(-side.z, side.x) + Math.PI;
    items.push({ pos: base, rotY, scale: 1 });
    colors.push(hasData ? color.clone().multiplyScalar(1.6) : PALETTE.none);
    const size = hasData ? 1.2 + 2.6 * Math.sqrt(total / peak) : 0.6;
    const offset=new THREE.Vector3(.3,1.38,0).applyAxisAngle(UP,rotY).add(base);
    lights.push({offset,color,size,alpha:hasData?.85:.2});
    const text = e ? `这个月聊天里开心的片段 ${e.pos} 处，难受的 ${e.neg} 处。` : "这个月还没有整理到记录。";
    const card = cardData(e, { kicker: "月灯", title: month.replace("-", " 年 ") + " 月", text, aside: e ? "灯越暖，这个月越偏开心；光越大，这个月的事越多。" : "有新的记录时会补上。" });
    register(proxy(base,.85,1.9,card),card,"month-"+month);

  });
  const geometry=new THREE.InstancedBufferGeometry().copy(new THREE.PlaneGeometry(1,1));
  geometry.instanceCount=lights.length;
  geometry.setAttribute("offset",new THREE.InstancedBufferAttribute(new Float32Array(lights.flatMap(l=>l.offset.toArray())),3));
  geometry.setAttribute("tint",new THREE.InstancedBufferAttribute(new Float32Array(lights.flatMap(l=>l.color.toArray())),3));
  geometry.setAttribute("radius",new THREE.InstancedBufferAttribute(new Float32Array(lights.map(l=>l.size)),1));
  geometry.setAttribute("strength",new THREE.InstancedBufferAttribute(new Float32Array(lights.map(l=>l.alpha)),1));
  lanternGlow=new THREE.ShaderMaterial({
    uniforms:{time:{value:0},glowMap:{value:GLOW}},transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,
    vertexShader:`attribute vec3 offset,tint;attribute float radius,strength;uniform float time;
      varying vec2 tex;varying vec3 shade;varying float opacity;
      void main(){tex=uv;shade=tint;opacity=strength;vec4 eye=viewMatrix*vec4(offset,1.);
      eye.xy+=position.xy*radius*(.94+.06*sin(time*1.3+offset.x*.3));gl_Position=projectionMatrix*eye;}`,
    fragmentShader:`uniform sampler2D glowMap;varying vec2 tex;varying vec3 shade;varying float opacity;
      void main(){gl_FragColor=vec4(shade,opacity*texture2D(glowMap,tex).a);
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
      }`
  });
  const halos=new THREE.Mesh(geometry,lanternGlow);halos.frustumCulled=false;scene.add(halos);
  scatterInstances("lantern", items, { tint: { glow: (i) => colors[i] } });
}

const gateSightlines=[];
function planPlazas(months,eras) {
  let previous=1.5;
  return eras.map(era=>{
    const index=monthIndex(months,era.start);
    const d=Math.max(previous+8,routeAt(Math.min(.992,(index+.35)/Math.max(1,months.length-1))));
    previous=d;
    const {p,t}=routeFrame(d);
    const plaza={x:p.x,z:p.z,y:naturalGround(p.x,p.z)};
    terraces.push(plaza);
    return {era,plaza,d,t};
  });
}
function banner(title) {
  const canvas=document.createElement("canvas");canvas.width=768;canvas.height=188;
  const ctx=canvas.getContext("2d");ctx.fillStyle="#f3e0af";ctx.fillRect(0,0,768,188);
  ctx.strokeStyle="#ac7954";ctx.lineWidth=3;ctx.setLineDash([6,6]);ctx.strokeRect(10,10,748,168);
  ctx.setLineDash([]);ctx.fillStyle="#563a30";ctx.textAlign="center";ctx.textBaseline="middle";
  const lines=title.split(/[，、]/);if(lines.length===1 && title.length>10)lines.splice(0,1,title.slice(0,Math.ceil(title.length/2)),title.slice(Math.ceil(title.length/2)));
  const size=Math.min(58,Math.floor(694/Math.max(...lines.map(l=>l.length))));
  ctx.font="600 "+size+"px system-ui";lines.forEach((line,i)=>ctx.fillText(line,384,94+(i-(lines.length-1)/2)*64));
  const map=new THREE.CanvasTexture(canvas);map.colorSpace=THREE.SRGBColorSpace;
  return new THREE.MeshStandardMaterial({map,roughness:1});
}
function gates(marks) {
  const timber=new THREE.MeshStandardMaterial({color:"#906746",roughness:.92});
  const bark=new THREE.MeshStandardMaterial({color:"#755039",roughness:.9});
  const rings=new THREE.MeshStandardMaterial({color:"#c5af8d",roughness:.92});
  const post=new THREE.CylinderGeometry(.105,.145,2.92,11);
  const paving=new THREE.CylinderGeometry(LAYOUT.plazaRadius,LAYOUT.plazaRadius+.025,.12,64);
  const border=new THREE.RingGeometry(3.22,3.29,72);
  const lanterns=[];
  for(const mark of marks){
    const {era,d,plaza}=mark,{p,tangent,side}=routeFrame(d);
    p.y=plaza.y+.065;
    const floor=new THREE.Mesh(paving,pathStone);floor.position.copy(p).y-=.035;floor.receiveShadow=true;walkSurfaces.push(floor);scene.add(floor);
    const rim=new THREE.Mesh(border,rings);rim.rotation.x=-Math.PI/2;rim.position.copy(p).y+=.028;scene.add(rim);
    const group=new THREE.Group();group.position.copy(p).addScaledVector(tangent,-1.3);group.lookAt(group.position.clone().add(tangent));
    const upright=1.37;
    for(const sign of [-1,1]){
      const pole=new THREE.Mesh(post,timber);pole.position.set(sign*upright,1.43,0);group.add(pole);
      const cap=new THREE.Mesh(new THREE.CylinderGeometry(.15,.15,.11,11),bark);cap.position.set(sign*upright,2.9,0);group.add(cap);
      const world=group.position.clone().addScaledVector(side,sign*upright);colliders.push({x:world.x,z:world.z,r:.15});
      const lampPos=p.clone().addScaledVector(tangent,sign*2.45).addScaledVector(side,sign*1.97);
      lampPos.y=plaza.y+.10;
      lanterns.push({pos:lampPos,rotY:Math.atan2(p.x-lampPos.x,p.z-lampPos.z)-Math.PI/2,scale:1.13});
      colliders.push({x:lampPos.x,z:lampPos.z,r:.28});
    }
    const cord=new THREE.Mesh(new THREE.CylinderGeometry(.035,.035,upright*2,8),bark);
    cord.rotation.z=Math.PI/2;cord.position.y=2.68;group.add(cord);
    const cloth=new THREE.Mesh(new THREE.PlaneGeometry(2.36,.59),banner(era.card?.title||era.title));
    cloth.position.set(0,2.41,-.045);
    const reverse=cloth.clone();reverse.position.z-=.012;reverse.rotation.y=Math.PI;group.add(cloth,reverse);
    group.userData.updateTitle=title=>{
      const previous=cloth.material;
      cloth.material=reverse.material=banner(title);previous.map.dispose();previous.dispose();
    };
    group.traverse(m=>{if(m.isMesh)m.castShadow=true;});
    const opening=new THREE.Mesh(new THREE.BoxGeometry(2.55,2.8,.24),PROXY_MAT);
    opening.position.y=1.4;group.add(opening);
    const data=cardData(era,{kicker:era.period,title:era.title,text:era.text,aside:"人生时间线"});
    register(group,data,"era-"+era.start,3.22,"era");
    namedObjects.set("scene-"+era.start,group);group.userData.front=tangent.clone().negate();scene.add(group);
    group.updateWorldMatrix(true,true);
    const boxes=group.children.filter(m=>m.isMesh && m!==opening).map(m=>{
      m.geometry.computeBoundingBox();return m.geometry.boundingBox.clone().applyMatrix4(m.matrix).expandByScalar(.06);
    });
    gateSightlines.push({position:p,inverse:group.matrixWorld.clone().invert(),boxes});
    Object.assign(mark,{group,model:group});
  }
  scatterInstances("lantern",lanterns,{tint:{glow:()=>"#ffc783"}});
}
function batchMiniatures(kind,entries) {
  if(!entries.length)return;
  const mesh=miniature(kind),batch=new THREE.InstancedMesh(mesh.geometry,mesh.material,entries.length);
  const transform=new THREE.Object3D();
  entries.forEach(({pos,rotY,scale},i)=>{
    transform.position.copy(pos);transform.rotation.y=rotY;transform.scale.setScalar(scale);
    transform.updateMatrix();batch.setMatrixAt(i,transform.matrix);
  });
  batch.castShadow=batch.receiveShadow=true;scene.add(batch);
}
const HOUSE_SIZE={
  "home-common":{height:1.76,radius:1.58,offset:6.15},
  "home-pink":{height:2.86,radius:2.18,offset:7.05},
  "home-family":{height:3.04,radius:2.86,offset:7.8},
  special:{height:2.22,radius:1.86,offset:6.65},
};
const HOUSE_FRONT={"home-pink":-25,"home-studio":64};
const householdModels=new Map(),housesOnIsland=new Map();
function houseFallback(style,entries) {
  const kind=style==="home-pink"?"cottage_small":"cottage";
  const scale=style==="home-family"?1.35:style==="home-pink"?1.12:.91;
  scatterInstances(kind,entries.map(entry=>({...entry,scale:entry.scale*scale})),{tint:{roof:()=>style==="home-pink"?"#cb8c95":"#966e55"}});
}
async function houseModel(asset,entries,dimensions) {
  const source=(await new GLTFLoader().loadAsync(asset.model)).scene;
  const normalized=new THREE.Group();normalized.add(source);
  source.rotation.y+=(Number(asset.yaw??HOUSE_FRONT[asset.style])||0)*Math.PI/180;
  const box=new THREE.Box3().setFromObject(normalized,true),size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3());
  const scale=Math.min(dimensions.height/size.y,(dimensions.radius*2-.22)/Math.hypot(size.x,size.z));
  source.scale.multiplyScalar(scale);source.position.add(new THREE.Vector3(-center.x,-box.min.y,-center.z).multiplyScalar(scale));
  normalized.updateWorldMatrix(true,true);assets[asset.style]=normalized;
  normalized.traverse(m=>{if(m.isMesh){const far=distantGeometry(m.geometry,8,550);if(far)simplerProps.set(m.geometry,far);}});
  const foundations=new THREE.InstancedMesh(sculptureGeo,pathStone,entries.length),transform=new THREE.Object3D();
  foundations.receiveShadow=true;
  entries.forEach((entry,i)=>{
    const w=size.x*scale*entry.scale,h=size.y*scale*entry.scale,depth=size.z*scale*entry.scale;
    const diameter=Math.hypot(w,depth)+.11;
    const levels=supportLevels(entry.pos.x,entry.pos.z,diameter,diameter,.055);
    transform.position.set(entry.pos.x,levels.bottom,entry.pos.z);
    transform.scale.set(diameter,levels.top-levels.bottom,diameter);
    transform.updateMatrix();foundations.setMatrixAt(i,transform.matrix);entry.pos.y=levels.top;
    const proxy=entry.marker;proxy.geometry.dispose();proxy.geometry=new THREE.BoxGeometry(w,h,depth);
    proxy.position.set(entry.pos.x,levels.top+h/2,entry.pos.z);proxy.rotation.y=entry.rotY;
    proxy.userData.focusExtent=Math.max(w,h,depth);proxy.userData.houseReady=true;entry.status="ready";
  });
  scene.add(foundations);scatterInstances(asset.style,entries);
  lastFoliagePosition.set(Infinity,0,0);renderer.shadowMap.needsUpdate=true;tryFocusHash();
}
function homes(months,people) {
  const mail=[],groups=new Map(),known=new Map((currentWorld.houses||[]).map(asset=>[asset.style,asset]));
  const hasAssignments=people.some(p=>Object.hasOwn(p,"house_style"));
  const maxWeight=Math.max(1,...people.map(p=>p.weight));
  people.forEach((person,i)=>{
    const legacyHome=Number(person.layer)===1 || (person.layer==null && i<30);
    const style=hasAssignments?person.house_style:legacyHome?"home-common":null;
    if(!style){mail.push(person);return;}
    const key=person.home_group||person.id;
    if(!groups.has(key))groups.set(key,{style,key,people:[]});
    groups.get(key).people.push(person);
  });
  const dateAnchor=p=>routeAt(Math.min(.995,(monthIndex(months,p.from)+.35)/Math.max(1,months.length-1)));
  const personData=p=>cardData(p,{kicker:[p.from,p.to].filter(Boolean).join(" — "),title:p.name,text:p.line,aside:""});
  const front=face=>new THREE.Vector3(Math.sin(face),0,Math.cos(face));
  const models=new Map(),mailItems=[];
  const ordered=[...groups.values()].sort((a,b)=>Number(b.key==="family")-Number(a.key==="family")||Number(a.style==="home-common")-Number(b.style==="home-common"));
  for(const home of ordered){
    const {style,key}=home,family=key==="family";
    const dimensions=HOUSE_SIZE[style]||HOUSE_SIZE.special;
    const first=home.people[0],scale=style==="home-common"?.90+.14*Math.sqrt(first.weight/maxWeight):1;
    const site=routeSite("home",routeFrame,dateAnchor(first),-1,{radius:dimensions.radius*scale,offset:dimensions.offset});
    gardens.push({x:site.pos.x,z:site.pos.z,y:site.pos.y,radius:site.radius,feather:1.05});
    const data=family?{title:"一家人的家",action:"people-group",group:key}:personData(first);
    const marker=proxy(site.pos,1.9*scale,dimensions.height,data);
    marker.userData.houseStyle=style;marker.userData.front=front(site.face);marker.userData.houseExpected=!!known.get(style)?.model;
    register(marker,data,family?"house-"+key:first.id,dimensions.height*.63,"person");
    if(!namedObjects.has("house-"+style))namedObjects.set("house-"+style,marker);
    if(family){
      const sideways=new THREE.Vector3(marker.userData.front.z,0,-marker.userData.front.x);
      home.people.forEach((member,i)=>{
        const pos=site.pos.clone().addScaledVector(marker.userData.front,dimensions.radius*.78+.36)
          .addScaledVector(sideways,(i-(home.people.length-1)/2)*.79);
        pos.y=ground(pos.x,pos.z);
        mailItems.push({pos,rotY:site.face,scale:.91});
        const card=personData(member),door=proxy(pos,.66,.91,card);door.userData.front=marker.userData.front;
        register(door,card,member.id,.76,"person");
      });
    }
    const entry={pos:site.pos.clone(),rotY:site.face,scale,marker,status:"fallback"};
    housesOnIsland.set(key,{...home,site,entry});
    if(!models.has(style))models.set(style,[]);models.get(style).push(entry);
  }
  for(const [i,person] of mail.entries()){
    const site=routeSite("mailbox",routeFrame,dateAnchor(person),i%2?1:-1);
    mailItems.push({pos:site.pos,rotY:site.face,scale:.85});
    const data=personData(person),marker=proxy(site.pos,.74,.9,data);
    marker.userData.front=front(site.face);register(marker,data,person.id,.7,"person");
  }
  batchMiniatures("mailbox",mailItems);
  for(const [style,entries] of models){
    const asset=known.get(style);
    if(!asset?.model){houseFallback(style,entries);continue;}
    householdModels.set(style,"loading");
    houseModel(asset,entries,HOUSE_SIZE[style]||HOUSE_SIZE.special).then(()=>{
      householdModels.set(style,"ready");
    }).catch(()=>{
      householdModels.set(style,"failed");houseFallback(style,entries);for(const e of entries)e.marker.userData.houseReady=true;tryFocusHash();
    });
  }
}

// ---------- 树林、石头、花草 ----------
function nature() {
  const blocked = (x, z, pad) => colliders.some((c) => (c.x - x) ** 2 + (c.z - z) ** 2 < ((c.space||c.r) + pad) ** 2);
  const groves = (x, z) => Math.sin(x * 0.09 + 1.3) * Math.cos(z * 0.08 - 0.7) + 0.35 * Math.sin((x + z) * 0.05);
  const pick = (count, { minR, maxR, pathPad, pad, accept }) => {
    const out = [];
    for (let tries = 0; out.length < count && tries < count * 40; tries++) {
      const r = Math.sqrt(minR * minR + rand() * (maxR * maxR - minR * minR)), a = rand() * Math.PI * 2;
      const x = Math.cos(a) * r, z = Math.sin(a) * r;
      if (accept && !accept(x, z, r)) continue;
      if (pathDistance(x,z)<pathPad || blocked(x,z,pad) || terraces.some(g=>Math.hypot(x-g.x,z-g.z)<LAYOUT.plazaRadius+pad)) continue;
      out.push(new THREE.Vector3(x, ground(x, z), z));
    }
    return out;
  };
  const treeKinds = ["tree_round", "tree_round_b", "tree_autumn", "tree_pine"];
  const crownRadius=2.2*Math.max(...treeKinds.map(name=>{
    const box=new THREE.Box3().setFromObject(assets[name]);
    return Math.max(Math.abs(box.min.x),Math.abs(box.max.x),Math.abs(box.min.z),Math.abs(box.max.z));
  }));
  const trees = pick(175, { minR: PLATEAU + 3, maxR: ISLAND - BEACH - 1, pathPad: 3.25, pad: crownRadius, accept: (x, z) => !blocksSculptureView(x,z,crownRadius) && (groves(x, z) > 0.15 || rand() < 0.08) });
  const byKind = Object.fromEntries(treeKinds.map((k) => [k, []]));
  for (const pos of trees) {
    const kind = groves(pos.x, pos.z) > 0.7 ? (rand() < 0.6 ? "tree_pine" : "tree_round_b") : treeKinds[Math.floor(rand() * (rand() < 0.3 ? 4 : 2))];
    const scale = 1.1 + rand() * 1.1;
    pos.y -= 0.05;
    byKind[kind].push({ pos, rotY: rand() * 6.3, scale });
    colliders.push({ x: pos.x, z: pos.z, r: 0.22 * scale });
  }
  for (const k of treeKinds) scatterInstances(k, byKind[k]);

  const rocks = pick(70, { minR: PLATEAU + 2, maxR: ISLAND + 1, pathPad: 1.8, pad: 0.8 });
  const rockItems = { rock_a: [], rock_b: [] };
  for (const pos of rocks) {
    const scale = 0.5 + rand() * 1.4;
    (rand() < 0.5 ? rockItems.rock_a : rockItems.rock_b).push({ pos, rotY: rand() * 6.3, scale });
    if (scale > 1) colliders.push({ x: pos.x, z: pos.z, r: 0.45 * scale });
  }
  scatterInstances("rock_a", rockItems.rock_a);
  scatterInstances("rock_b", rockItems.rock_b);

  const patchRadius=(kind,scale)=>{
    const {min,max}=new THREE.Box3().setFromObject(assets[kind]);
    return scale*Math.hypot(Math.max(Math.abs(min.x),Math.abs(max.x)),Math.max(Math.abs(min.z),Math.abs(max.z)));
  };
  const grass = pick(580, { minR: PLATEAU + 1.5, maxR: ISLAND - BEACH + 1, pathPad: 1.1, pad: patchRadius("grass",1.8) });
  scatterInstances("grass", grass.map((pos) => ({ pos, rotY: rand() * 6.3, scale: 0.8 + rand() * 1.0 })), { shadow: false });
  const flowerRadius=patchRadius("flowers",1.8);
  const flowers = pick(132, { minR: PLATEAU + 1.5, maxR: ISLAND - BEACH, pathPad: 1.2, pad: flowerRadius, accept: (x, z) => groves(x, z) < 0 });
  // 平台外沿一圈花
  for (let i = 0; i < 52; i++) {
    const a = (i / 52) * Math.PI * 2 + rand() * 0.05, r = PLATEAU + 0.9 + rand() * 0.8;
    const x = Math.cos(a) * r, z = Math.sin(a) * r;
    if (pathDistance(x, z) > 1.4 && !blocked(x,z,flowerRadius)) flowers.push(new THREE.Vector3(x, ground(x, z), z));
  }
  scatterInstances("flowers", flowers.map((pos) => ({ pos, rotY: rand() * 6.3, scale: 1 + rand() * 0.8 })), { shadow: false });
}

// ---------- 海边：栈桥和灯船 ----------
const boats = [];
function shore(circles) {
  const a = PATH_START - 0.18;
  const dir = new THREE.Vector3(Math.cos(a), 0, Math.sin(a));
  const start = dir.clone().multiplyScalar(ISLAND - 3.2);
  start.y = 0.05;
  const rot = Math.atan2(dir.x, dir.z);
  for (let k = 0; k < 3; k++) place("pier", start.clone().addScaledVector(dir, k * 2.24), rot, 1);
  const tip = start.clone().addScaledVector(dir, 6.6);
  const l = place("lantern", tip.clone().setY(0.33), rot, 1);
  recolor(l, "glow", "#ffcf8a", 3);
  const halo = glow("#ffcf8a", 2.4, 0.8);
  halo.position.set(0.3, 1.38, 0);
  l.add(halo);
  const spots = [[2.2,1.6],[4.6,-1.8],[11,4],[16,-6],[9,-11]];
  const count=Math.max(spots.length,circles.length);
  const groupItems=[];
  for(let i=0;i<count;i++) {
    let pos,heading=rot+1.2+i*.8;
    if(i<spots.length) {
      const [along,across]=spots[i];
      pos=tip.clone().addScaledVector(dir,along-4).addScaledVector(new THREE.Vector3(-dir.z,0,dir.x),across);
    } else {
      const j=i-spots.length, angle=a+.30+(j%64)/64*(Math.PI*2-.65);
      const r=ISLAND+5.8+Math.floor(j/64)*3+(j%3)*.68;
      pos=new THREE.Vector3(r*Math.cos(angle),0,r*Math.sin(angle));heading=-angle+1.2;
    }
    pos.y=-.34;
    const circle=circles[i], isBoat=i<3;
    const scale=i<12?1.4:1;
    if(isBoat) {
      const boat=place("boat",pos,heading,scale);
      recolor(boat,"glow","#ffd9a0",2.6);
      const h=glow("#ffcf8a",1.8,.75);h.position.set(.35,1.08,0);boat.add(h);
      boats.push({obj:boat,y:pos.y,phase:i*1.7});
    } else {groupItems.push({pos,rotY:heading,scale});}
    const data=cardData(circle,{kicker:circle?.type||"海岸",title:circle?.name||"码头灯船",text:circle?.role||"灯船停在栈桥边。",aside:[circle?.from,circle?.to].filter(Boolean).join(" — ")});
    register(proxy(pos,1.7*scale,1.25*scale,data),data,circle?.id||"boat-"+i);
  }
  scatterInstances("boat",groupItems,{shadow:false,tint:{glow:()=>"#ffdc98"}});
}
function momentSites(months,moments) {
  return moments.map((item,index)=>{
    const date=item.date||"",month=monthIndex(months,date);
    const t=Math.min(.998,(month+(Number(date.slice(8,10))||14)/32)/Math.max(1,months.length-1));
    const data=cardData(item,{kicker:date,title:item.title,text:item.text,aside:"路边的片段"});
    return {item,index,t,data};
  });
}
function wayside(sites) {
  const signs=[];
  for(const {item,index,data,sculpture,site} of sites){
    if(sculpture)continue;
    signs.push({pos:site.pos,rotY:site.face,scale:1});
    const marker=proxy(site.pos,.83,.7,data);
    marker.userData.front=new THREE.Vector3(Math.sin(site.face),0,Math.cos(site.face));
    register(marker,data,item.id||"moment-"+index,.61,"moment");namedObjects.set("moment-"+index,marker);
  }
  batchMiniatures("waysign",signs);
}

// ---------- 中央展台 ----------
const resin = new THREE.MeshStandardMaterial({ color: PALETTE.resin, roughness: 0.55, metalness: 0 });
// 从步道上看过每个方向后，转动模型本身，保留正面的标志性细节。
const PAINTED_FRONT={
  "sc-broadcast-mic":-135, "sc-delivery-crate":156, "sc-lectern-notes":135,
  "sc-bookend-fox":60, "sc-lunch-satchel":-32, "sc-parking-guide":90,
  "sc-vanishing-frame":-43,
};
const unpaintedClay=new THREE.MeshStandardMaterial({color:"#bea88e",roughness:.89});
let flameLight, flame, flameGlow;
const pedestals = new Map(), flashes = [], detailedModels=new Set(), assetGroups=new Map();

function hall() {
  const floor = new THREE.Mesh(new THREE.CylinderGeometry(8.4, 8.7, 0.3, 72), new THREE.MeshStandardMaterial({ color: "#cdbd9d", roughness: 0.85 }));
  floor.position.y = TOP + 0.15;
  floor.receiveShadow=true;walkSurfaces.push(floor);
  scene.add(floor);
  const inlay = new THREE.Mesh(new THREE.RingGeometry(6.6, 6.75, 96), new THREE.MeshStandardMaterial({ color: "#b98a5a", roughness: 0.5, metalness: 0.4 }));
  inlay.rotation.x = -Math.PI / 2;
  inlay.position.y = TOP + 0.305;
  scene.add(inlay);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(8.45, 0.07, 8, 120), new THREE.MeshStandardMaterial({ color: "#b98a5a", roughness: 0.5, metalness: 0.4 }));
  ring.rotation.x = Math.PI / 2;
  ring.position.y = TOP + 0.31;
  scene.add(ring);

  // 生日蜡烛：岛的中心
  const candle = new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.46, 3.2, 40), new THREE.MeshStandardMaterial({ color: "#f4ece0", roughness: 0.45 }));
  candle.position.y = TOP + 0.3 + 1.6;
  candle.castShadow = true;
  const wick = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.22, 6), new THREE.MeshStandardMaterial({ color: "#2a2220" }));
  wick.position.y = TOP + 0.3 + 3.3;
  flame = new THREE.Mesh(new THREE.SphereGeometry(0.16, 20, 14), new THREE.MeshStandardMaterial({ color: "#ffd890", emissive: "#ffb347", emissiveIntensity: 3.2 }));
  flame.scale.set(1, 2.1, 1);
  flame.position.y = TOP + 0.3 + 3.62;
  flameGlow = glow("#ffb661", 3.4, 0.9);
  flameGlow.position.copy(flame.position);
  flameLight = new THREE.PointLight("#ffb46a", 26, 22, 1.6);
  flameLight.position.copy(flame.position);
  const fill = new THREE.SpotLight("#ffe6c8", 60, 40, Math.PI / 5, 0.8, 1.2);
  fill.position.set(0, TOP + 12, 16);
  fill.target.position.set(0, TOP, 0);
  scene.add(candle, wick, flame, flameGlow, flameLight, fill, fill.target);
  // 蜡烛立在工坊屋顶，灯下的小门朝向展台入口。
  candle.scale.y=.48; candle.position.y=TOP+3.75;
  for(const obj of [wick,flame,flameGlow,flameLight]) obj.position.y+=1.04;
  const candleData=coreCard("core:candle",{kicker:"2026-11",title:"二十三",text:"从 2022 年夏天开始的路，走到这里。",aside:""});
  register(candle,candleData,"candle");
  portal=miniature("workshop");portal.position.set(0,TOP+.3,0);scene.add(portal);
  const door = readOnly
    ? {title: "今日小物", kicker: "小岛工坊", text: "从当天的记录里挑出一个念头，把它做成桌面摆件。模型经过检查和切片，打印出来的小物就摆进岛上的展台。"}
    : {title: "今日小物", action: "workbench"};
  register(portal,door,"workshop",3.05,"portal");
  portal.userData.front=new THREE.Vector3(0,0,1);
  colliders.push({x:0,z:0,r:1.13});

  // 长椅：在展台外圈，面朝中心
  for (let i = 0; i < 4; i++) {
    const a = Math.PI / 4 + (i / 4) * Math.PI * 2;
    const pos = new THREE.Vector3(Math.cos(a) * 7.6, TOP + 0.3, Math.sin(a) * 7.6);
    const id = "prop-bench-" + i;
    const group = new THREE.Group(); group.position.copy(pos);
    const bench = place("bench", new THREE.Vector3(), Math.atan2(-pos.x, -pos.z) + Math.PI, 1);
    bench.removeFromParent(); group.add(bench); scene.add(group);
    const collider = { x: pos.x, z: pos.z, r: 0.7 }; colliders.push(collider);
    Object.assign(group.userData, { home: pos.clone(), baseRadius: 0.7, collider });
    const data = { kicker: "展台外圈", title: "长椅", text: "展台外的长椅，坐下来看看今天的小物。", aside: "" };
    register(group, data, id);
    assetGroups.set(id, { group, item: { id, title: "长椅", stage: "展台外圈" }, kind: "prop" });
  }

}

const pedestalGeo = new THREE.CylinderGeometry(.58,.66,1.05,32);
const pedestalMat = new THREE.MeshStandardMaterial({color:"#d9c9ad",roughness:.75});
const emptyGeo=new THREE.TorusGeometry(.34,.025,8,36);
const brass=new THREE.MeshStandardMaterial({color:"#ffd9a0",emissive:"#ffb766",emissiveIntensity:1});
const gallerySlots=[];
let galleryRings=0;
// 每日小物排成面朝工坊门口的弧：从左到右按日期，前排摆满后绕到工坊背后，再往平台外圈排。
const SLOT_RADII=[4.35,5.95], SLOT_STEP=1.75;
function slotRadius(ring){return ring<SLOT_RADII.length?SLOT_RADII[ring]:10.3+(ring-SLOT_RADII.length)*SLOT_STEP;}
function slotPosition(index,total=index+1) {
  while(gallerySlots.length<=index) {
    const ring=galleryRings++, radius=slotRadius(ring), capacity=Math.floor(Math.PI*2*radius/SLOT_STEP), step=Math.PI*2/capacity;
    // 首次打开时让已有的几件居中对着门口；之后新来的接在右边。
    const start=ring===0?Math.PI/2+Math.min(total-1,capacity-1)/2*step:THREE.MathUtils.degToRad(170);
    for(let i=0;i<capacity;i++) {
      const angle=start-i*step;
      const x=Math.cos(angle)*radius,z=Math.sin(angle)*radius;
      // 最外一圈让开四张长椅与平台入口，近距离仍然能走到每个座前。
      if(colliders.some(c=>(c.x-x)**2+(c.z-z)**2<((c.space||c.r)+.80)**2))continue;
      if(radius>8.55 && pathDistance(x,z)<1.45) continue;
      gallerySlots.push(new THREE.Vector3(x,ground(x,z)+(radius<8.55?.3:.02),z));
    }
  }
  return gallerySlots[index];
}
function replaceContent(group) {
  const old=group.userData.model;
  if(!old) return;
  group.remove(old);
  if(!old.userData.shared) old.traverse(o=>{
    if(!o.isMesh) return;
    const detail=o.userData.detail;
    if(detail){detail.near.dispose();detail.far.dispose();detailedModels.delete(detail);}
    else o.geometry.dispose();
  });
  group.userData.model=null;
}
function finishedSurface(x,z) {
  let paving=0;
  if(Math.hypot(x,z)<8.55)paving=.30;
  else if(terraces.some(g=>Math.hypot(x-g.x,z-g.z)<LAYOUT.plazaRadius))paving=.09;
  return ground(x,z)+paving;
}
function supportLevels(x,z,width,depth,lip) {
  const levels=[];
  for(let i=0;i<16;i++) {
    const a=i*Math.PI/8,px=x+.5*width*Math.cos(a),pz=z+.5*depth*Math.sin(a);
    levels.push(finishedSurface(px,pz));
  }
  return {top:Math.max(...levels)+lip,bottom:Math.min(...levels)-.08};
}
function loadModel(item,group,floor,height,yaw=0) {
  const ticket=Symbol();group.userData.ticket=ticket;group.userData.ready=false;group.userData.failed=false;
  const ready=object=>{
    if(group.userData.ticket!==ticket) {object.traverse(o=>{if(o.isMesh)o.geometry.dispose();});return;}
    let textured=false;
    object.traverse(o=>{
      if(!o.isMesh) return;
      if((Array.isArray(o.material)?o.material:[o.material]).some(m=>m.map?.isTexture))textured=true;
      if(!group.userData.plinth)o.material=resin;
      else if(!o.material.map && !o.material.vertexColors && o.material.color?.getHex()===0xffffff && o.material.metalness>=.95)o.material=unpaintedClay;
      o.castShadow=true;o.receiveShadow=true;
      const far=distantGeometry(o.geometry);
      if(far){
        const detail={group,mesh:o,near:o.geometry,far};
        o.userData.detail=detail;detailedModels.add(detail);
      }
    });
    const orient=new THREE.Group();orient.rotation.y=yaw+(textured?(PAINTED_FRONT[item.id]||0)*Math.PI/180:0);
    if(!textured && item.id==="sc-keyboard-step")object.rotateX(THREE.MathUtils.degToRad(18));
    orient.add(object);
    const box=new THREE.Box3().setFromObject(orient,true),size=box.getSize(new THREE.Vector3());
    const rules=group.userData.site, c=box.getCenter(new THREE.Vector3());
    let radial=0;
    if(rules){
      const vertex=new THREE.Vector3();
      orient.traverse(mesh=>{
        if(!mesh.isMesh)return;
        const positions=mesh.geometry.attributes.position;
        for(let i=0;i<positions.count;i++){
          vertex.fromBufferAttribute(positions,i).applyMatrix4(mesh.matrixWorld);
          radial=Math.max(radial,(vertex.x-c.x)**2+(vertex.z-c.z)**2);
        }
      });
      radial=Math.sqrt(radial);
    }
    const k=rules?Math.min(height/Math.max(size.y,.00001),(rules.radius-.07)/Math.max(radial,.00001)):height/Math.max(size.y,size.x*.8,size.z*.8,.00001);
    const vertical=rules?height/Math.max(size.y,.00001):k;
    orient.scale.set(k,vertical,k);
    box.min.multiply(orient.scale);box.max.multiply(orient.scale);c.multiply(orient.scale);
    group.userData.modelHeight=size.y*vertical;
    group.userData.reshape=vertical/k;
    let restingHeight=floor;
    if(group.userData.plinth){
      // 用展示版实测的水平包围盒支撑所有着地点。石座向下延到最低一侧的坡面。
      group.userData.plinthWidth=Math.max(.46,radial*k*2+.14);
      restingHeight=seatPlinth(group);
    }
    group.userData.restingHeight=restingHeight;
    orient.position.set(-c.x,restingHeight-box.min.y,-c.z);
    replaceContent(group);group.userData.model=orient;group.add(orient);group.userData.ready=true;
    if(!textured && ["sc-lantern-niche","sc-birthday-cloche"].includes(item.id)){
      group.updateMatrixWorld(true);
      const probe=group.position.clone().addScaledVector(group.userData.front,.09);
      const probeHeight=height*(item.id==="sc-birthday-cloche"?.53:.28);
      probe.y+=restingHeight+probeHeight;
      const hit=new THREE.Raycaster(probe,new THREE.Vector3(0,-1,0),0,probeHeight+.04).intersectObject(orient,true)[0];
      if(hit){
        const local=group.worldToLocal(hit.point.clone());
        const lamp=new THREE.Mesh(new THREE.SphereGeometry(.083,14,9),
          new THREE.MeshStandardMaterial({color:"#ffb557",emissive:"#ef9b38",emissiveIntensity:1.25}));
        lamp.scale.y=.63;lamp.position.copy(local);lamp.position.y+=.022;
        const light=glow("#ffb65a",.47,.66);light.position.copy(lamp.position);light.position.y+=.03;
        group.add(lamp,light);
      }
    }
    // 先用近景网格确定脚点和台面，再切换远景几何。
    if(camera.position.distanceToSquared(group.position)>32**2)
      object.traverse(o=>{if(o.userData.detail)o.geometry=o.userData.detail.far;});
    renderer.shadowMap.needsUpdate=true;tryFocusHash();
  };
  const fail=()=>{if(group.userData.ticket===ticket){group.userData.failed=true;tryFocusHash();}};
  const url=item.model;
  if(item.format==="glb") new GLTFLoader().load(url,g=>ready(g.scene),undefined,fail);
  else new STLLoader().load(url,geo=>{geo.computeVertexNormals();const mesh=new THREE.Mesh(geo,resin);mesh.rotation.x=-Math.PI/2;ready(mesh);},undefined,fail);
}
const datedExhibit=i=>/^\d{4}-\d{2}-\d{2}$/.test(i.date||"");
function placeExhibits(items,refresh=false) {
  // 样品排在弧的起点，之后按日期接下去，明天那件落在最新一件旁边。
  const real=items.filter(i=>i.model).sort((a,b)=>(datedExhibit(a)-datedExhibit(b))||String(a.date).localeCompare(String(b.date))||a.id.localeCompare(b.id)), byId=new Map(real.map(i=>[i.id,i]));
  const occupied=new Set();
  for(const group of pedestals.values()) if(byId.has(group.userData.itemId)) occupied.add(group.userData.itemId);
  const newcomers=real.filter(i=>!occupied.has(i.id));
  const previous=new Set([...pedestals.values()].map(g=>g.userData.itemId).filter(Boolean));
  const count=Math.max(real.length+1,pedestals.size);
  for(let i=0;i<count;i++) {
    let group=pedestals.get(i);
    if(!group) {
      group=new THREE.Group();group.position.copy(slotPosition(i,count));
      const base=new THREE.Mesh(pedestalGeo,pedestalMat);base.position.y=.525;base.castShadow=base.receiveShadow=true;group.add(base);scene.add(group);
      const collider={x:group.position.x,z:group.position.z,r:.67};colliders.push(collider);pedestals.set(i,group);
      Object.assign(group.userData,{collider,baseRadius:.67,home:group.position.clone(),homeFront:new THREE.Vector3(group.position.x,0,group.position.z).normalize()});
    }
    const old=group.userData.itemId;
    const item=byId.get(old)||newcomers.shift();
    const signature=item?[item.id,item.model,item.format,item.model_revision||""].join("|"):"empty";
    if (old && old!==item?.id) namedObjects.delete(old);
    group.userData.itemId=item?.id;
    for(const [key,entry] of assetGroups)if(entry.group===group && key!==item?.id)assetGroups.delete(key);
    if(item)assetGroups.set(item.id,{group,item,kind:"exhibit"});
    const data=item?cardData(item,{kicker:item.date||"今日小物",title:item.title,text:item.summary,aside:item.reason}):coreCard("core:empty",{kicker:"空展台",title:"留给明天",text:"下一件小物会摆到这里。",aside:""});
    if(item?.card) Object.assign(data,item.card);
    if(item?.photo_url) data.photo_url=item.photo_url;else delete data.photo_url;
    if(!group.userData.pick) register(group,data,item?.id,2.7,"exhibit");
    else { group.userData.pick=data; if(item) namedObjects.set(item.id,group); const t=tagRecords.find(t=>t.obj===group);t.data=data;t.el.textContent=data.title;t.label.position.y=item?2.7:1.55; }
    if(group.userData.signature===signature && !group.userData.failed) continue;
    group.userData.signature=signature;group.userData.ticket=null;replaceContent(group);
    if(item) {
      loadModel(item,group,1.05,1.48,Math.atan2(group.position.x,group.position.z));
      if(refresh&&!previous.has(item.id)) {
        const light=glow("#ffc176",3.6,1);light.position.y=1.65;group.add(light);flashes.push({group,light,start:performance.now()});
      }
    } else {
      const ring=new THREE.Mesh(emptyGeo,brass);ring.userData.shared=true;ring.rotation.x=Math.PI/2;ring.position.y=1.08;group.userData.model=ring;group.add(ring);
    }
  }
}
const sculptureGeo=new THREE.CylinderGeometry(.485,.5,1,28).translate(0,.5,0);
const sculptureMat=pathStone;
// 石座跟着展品所在的坡面和缩放重新落地，返回模型在组内的台面高度。
function seatPlinth(group) {
  const s=group.scale.x||1,width=group.userData.plinthWidth,plinth=group.userData.plinth;
  const site=supportLevels(group.position.x,group.position.z,width*s,width*s,LAYOUT.stoneLip*s);
  const bottom=(site.bottom-group.position.y)/s,top=(site.top-group.position.y)/s;
  plinth.scale.set(width,top-bottom,width);plinth.position.y=bottom;
  syncPlinth(group);
  return top;
}
const HIDDEN_MATRIX=new THREE.Matrix4().makeScale(0,0,0);
function syncPlinth(group) {
  const {plinth, footBatch, footIndex} = group.userData;
  plinth.updateWorldMatrix(true,false);
  footBatch.setMatrixAt(footIndex,group.visible?plinth.matrixWorld:HIDDEN_MATRIX);
  footBatch.instanceMatrix.needsUpdate=true;
}
function sculptures(list, sites) {
  
  const footBatch=new THREE.InstancedMesh(sculptureGeo,sculptureMat,list.length);
  footBatch.castShadow=footBatch.receiveShadow=true;
  footBatch.frustumCulled=false;
  scene.add(footBatch);
  const byMoment=new Map();
  for(const entry of sites)for(const key of [entry.item.id,entry.item.card_id,entry.item.card_id?.replace(/^moment:/,"")])if(key)byMoment.set(key,entry);
  const endAngle=PATH_START+TURNS*Math.PI*2;
  const gallery=d=>arcFrame(galleryRadius,d/galleryRadius);
  const coast=d=>arcFrame(coastRadius,coastAngle-d/coastRadius,-1);
  const endOut=new THREE.Vector3(Math.cos(endAngle),0,Math.sin(endAngle));
  const entryLane=d=>({p:endOut.clone().multiplyScalar(d),side:new THREE.Vector3(-endOut.z,0,endOut.x)});
  const occupied=new Map();
  const entrance=list.filter(i=>i.placement?.zone==="entrance");
  for(const item of list){
    const pl=item.placement||{},slot=Number(pl.slot)||0;
    let site;
    if(pl.zone==="era") {
      const mark=eraMarks.find(m=>m.era.start===pl.era);
      site=routeSite("era",routeFrame,mark.d,slot%2?1:-1,{ownPlaza:mark.plaza,start:mark.d-.1,end:mark.d+.1});
    } else if(pl.zone==="coast"){
      site=routeSite("coast",coast,6.4+slot*4.65,1,{start:1,end:44});
    } else if(pl.zone==="gallery"){
      site=routeSite("gallery",gallery,(endAngle+(.9+slot*Math.PI*.5))*galleryRadius,-1,{start:endAngle*galleryRadius,end:(endAngle+Math.PI*2+1)*galleryRadius});
    } else if(pl.zone==="entrance"){
      site=routeSite("entrance",entryLane,6.85,entrance.indexOf(item)%2?1:-1,{start:5.6,end:8.0});
    }
    if(site)occupied.set(item.id,site);
  }
  const linked=new Set(list.filter(i=>i.placement?.zone==="moment").map(i=>byMoment.get(i.placement.moment_id)));
  const timeline=[...sites].sort((a,b)=>a.item.date.localeCompare(b.item.date)||a.index-b.index);
  let boundary=routeLength;
  for(let i=timeline.length-1;i>=0;i--){
    const entry=timeline[i],ideal=.90*routeAt(entry.t)+.10*routeLength*(i+.5)/timeline.length;
    const site=routeSite(linked.has(entry)?"moment":"sign",routeFrame,Math.min(ideal,boundary),i%2?1:-1,{start:0,end:boundary});
    entry.site=site;boundary=site.d-1.36;
  }
  const placed=[];
  list.forEach((item,i)=>{
    const pl=item.placement||{};
    const moment=pl.zone==="moment"?byMoment.get(pl.moment_id):null;
    const site=moment?.site||occupied.get(item.id);
    if(!site)throw new Error("缺少摆件位置 "+item.id);
    const pos=site.pos,look=site.look,h=LAYOUT[site.kind].height;
    const group=new THREE.Group();group.position.copy(pos);group.userData.site=site;
    const plinth=new THREE.Mesh(sculptureGeo,PROXY_MAT);plinth.scale.set(1.1,.24,1.1);
    Object.assign(group.userData,{plinth,footBatch,footIndex:i,expectsModel:true});
    group.add(plinth);scene.add(group);syncPlinth(group);
    const collider=colliders.find(c=>c.site===site);
    Object.assign(group.userData,{collider,baseRadius:collider?.r??LAYOUT[site.kind].radius,home:pos.clone()});
    assetGroups.set(item.id,{group,item,kind:"sculpture"});
    const facing=Math.atan2(look.x-pos.x,look.z-pos.z);
    group.userData.front=new THREE.Vector3(Math.sin(facing),0,Math.cos(facing));
    if(Number.isFinite(pl.cameraYaw) && !Object.hasOwn(PAINTED_FRONT,item.id)){
      group.userData.front.applyAxisAngle(UP,THREE.MathUtils.degToRad(pl.cameraYaw));
      group.userData.fixedFront=true;
    }
    group.userData.homeFront=group.userData.front.clone();
    sculptureViews.push({origin:pos,front:group.userData.front});
    const data=cardData(item,{kicker:item.stage,title:item.title,text:item.description||"为这座岛做的摆件。",aside:""});
    register(group,data,item.id,h+.28,"moment");
    if(moment) {
      group.userData.linkedCard=moment.data;
      if(!moment.sculpture) {
        moment.sculpture=group;
        namedObjects.set("moment-"+moment.index,group);
        namedObjects.set(moment.data.id,group);
        if(moment.item.id) namedObjects.set(moment.item.id,group);
      }
      // 等精雕到齐前，日期卡和路标仍在原来的位置。
      const marker=miniature("waysign");
      marker.position.y=.24;marker.userData.shared=true;
      group.userData.model=marker;group.add(marker);
    }
    placed.push({item,group,height:h,angle:facing+(Number(pl.yaw)||0)*Math.PI/180});
  });
  // 由近到远分批加载，避免新摆件集中解码带来的首屏停顿。
  let ix=0;
  function next() {
    for(let n=0;n<3 && ix<placed.length;n++,ix++) { const {item,group,height,angle}=placed[ix];loadModel(item,group,.4,height,angle); }
    if(ix<placed.length)setTimeout(next,100);
  }
  next();
}


// ---------- 布置：每日小物和 Aholo 精雕的自由摆放 ----------
// 只存与系统摆放不同的件；位置是世界坐标，朝向是相对默认朝向的角度。
let layoutItems={}, arranging=false, selectedAsset=null, draggingAsset=null, layoutHistory=[], saveTimer=0, saveGeneration=0;
const selectionRing=new THREE.Mesh(new THREE.RingGeometry(.86,1,72),
  new THREE.MeshBasicMaterial({color:"#ffcf8a",transparent:true,opacity:.92,depthWrite:false,side:THREE.DoubleSide,fog:false}));
selectionRing.rotation.x=-Math.PI/2;selectionRing.visible=false;selectionRing.renderOrder=4;scene.add(selectionRing);
const dragPlane=new THREE.Plane(new THREE.Vector3(0,1,0),0), dragHit=new THREE.Vector3(), dragOffset=new THREE.Vector3();
const PRINTED=/实物|接单|打印中|已打印|完工/;
function assetFloor(a,x,z){return a.kind==="sculpture"?ground(x,z):finishedSurface(x,z);}
// 装饰：Blender 生成的免费模型，可以从资产面板随时放到岛上，和展品一样拖动、转向、缩放、收起、删除。
const DECOR = [["tree_round","圆树",.9],["tree_autumn","秋树",.9],["tree_pine","松树",.8],["rock_a","石头",.6],["flowers","花丛",.5],
  ["grass","草丛",.4],["lantern","提灯",.35],["bench","长椅",.7],["fence","栅栏",.6],["boat","小船",1],["cottage_small","小木屋",1.4]];
const DECOR_INFO = new Map(DECOR.map(([name,label,r])=>[name,{label,r}]));
function spawnDecor(id,name,x,z){
  if(assetGroups.has(id) || !assets[name] || !DECOR_INFO.has(name))return null;
  const info=DECOR_INFO.get(name),group=new THREE.Group();
  group.position.set(x,finishedSurface(x,z),z);
  const obj=place(name,new THREE.Vector3(),0,1);obj.removeFromParent();group.add(obj);scene.add(group);
  const collider={x,z,r:info.r};colliders.push(collider);
  Object.assign(group.userData,{home:new THREE.Vector3(x,0,z),baseRadius:info.r,collider});
  const data={kicker:"装饰",title:info.label,text:"从资产面板放上岛的装饰，可以随时拖动、转向或收起。",aside:""};
  register(group,data,id);
  assetGroups.set(id,{group,item:{id,title:info.label,stage:"装饰",asset:name},kind:"deco"});
  return group;
}
function removeDecor(id){
  const a=assetGroups.get(id);if(!a || a.kind!=="deco")return;
  rememberLayout();
  a.group.removeFromParent();assetGroups.delete(id);
  const i=pickables.indexOf(a.group);if(i>=0)pickables.splice(i,1);
  const c=colliders.indexOf(a.group.userData.collider);if(c>=0)colliders.splice(c,1);
  delete layoutItems[id];if(selectedAsset===id)selectAsset(null);
  queueSave();assetUI.refresh();
}
function assetRadius(a){return a.group.userData.baseRadius*(a.group.scale.x||1);}
function assetState(id){
  const a=assetGroups.get(id),e=layoutItems[id]||{};
  return {yaw:e.yaw||0,scale:e.scale||1,hidden:!!e.hidden,moved:Object.keys(e).length>0,
    x:e.x??a.group.userData.home.x,z:e.z??a.group.userData.home.z};
}
function applyAsset(id){
  const a=assetGroups.get(id);if(!a)return;
  const g=a.group,u=g.userData,st=assetState(id),yaw=THREE.MathUtils.degToRad(st.yaw);
  g.position.set(st.x,assetFloor(a,st.x,st.z),st.z);
  g.rotation.y=yaw;g.scale.setScalar(st.scale);g.visible=!st.hidden;
  if(u.homeFront)u.front=u.homeFront.clone().applyAxisAngle(UP,yaw);
  if(u.collider){u.collider.x=st.x;u.collider.z=st.z;u.collider.r=st.hidden?0:u.baseRadius*st.scale;if("space" in u.collider)u.collider.space=u.collider.r;}
  if(u.plinth){
    if(u.plinthWidth && !st.hidden){
      const top=seatPlinth(g);
      if(u.model && u.restingHeight!=null){u.model.position.y+=top-u.restingHeight;u.restingHeight=top;}
    } else syncPlinth(g);
  }
  g.updateMatrixWorld(true);
  if(id===selectedAsset)updateRing();
  renderer.shadowMap.needsUpdate=true;
}
function spotProblem(id,x,z){
  const a=assetGroups.get(id),r=assetRadius(a),own=a.group.userData.collider;
  if(Math.hypot(x,z)>ISLAND-1.6)return "太靠海边了";
  if(pavementGap(x,z)<r*.75)return "压到小路了";
  if(colliders.some(c=>c!==own && c.r>0 && Math.hypot(c.x-x,c.z-z)<c.r+r*.8))return "和旁边的东西挤在一起";
  return "";
}
function updateRing(){
  const a=assetGroups.get(selectedAsset);
  if(!arranging || !a || !a.group.visible){selectionRing.visible=false;return;}
  const g=a.group,r=assetRadius(a)*1.28;
  selectionRing.visible=true;selectionRing.scale.setScalar(r);
  selectionRing.position.set(g.position.x,assetFloor(a,g.position.x,g.position.z)+.06,g.position.z);
  const problem=spotProblem(selectedAsset,g.position.x,g.position.z);
  selectionRing.material.color.set(problem?"#ff8a78":"#ffcf8a");
  assetUI.problem(problem);
}
function rememberLayout(){layoutHistory.push(JSON.stringify(layoutItems));if(layoutHistory.length>60)layoutHistory.shift();}
function setEntry(id,patch){
  const a=assetGroups.get(id);if(!a)return;
  const e={...layoutItems[id],...patch};
  for(const k of Object.keys(e))if(e[k]===undefined)delete e[k];
  if(e.yaw!==undefined){e.yaw=((e.yaw+540)%360)-180;if(Math.abs(e.yaw)<.5)delete e.yaw;}
  if(e.scale!==undefined && Math.abs(e.scale-1)<.005)delete e.scale;
  if(!e.hidden)delete e.hidden;
  if(a.kind!=="deco" && e.x!==undefined && Math.hypot(e.x-a.group.userData.home.x,e.z-a.group.userData.home.z)<.02){delete e.x;delete e.z;}
  if(Object.keys(e).length)layoutItems[id]=e;else delete layoutItems[id];
  applyAsset(id);
}
function queueSave(){
  clearTimeout(saveTimer);assetUI.saving("waiting");
  saveTimer=setTimeout(saveLayout,450);
}
async function saveLayout(){
  const generation=++saveGeneration;
  assetUI.saving("saving");
  try{
    const r=await fetch("/api/layout",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({items:layoutItems}),signal:AbortSignal.timeout(6000)});
    const body=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(body.error||"没有保存成功");
    if(generation===saveGeneration)assetUI.saving("saved");
  }catch(err){
    if(generation===saveGeneration)assetUI.saving("error",err.name==="TimeoutError"?"本机服务没有回应，稍后自动重试":err.message);
    clearTimeout(saveTimer);saveTimer=setTimeout(saveLayout,5000);
  }
}
function commit(id,patch){rememberLayout();setEntry(id,patch);queueSave();assetUI.refresh();}
function undoLayout(){
  const previous=layoutHistory.pop();if(!previous)return;
  const before=layoutItems;layoutItems=JSON.parse(previous);
  for(const [id,e] of Object.entries(layoutItems))if(id.startsWith("deco-") && !assetGroups.has(id))spawnDecor(id,e.asset,e.x,e.z);
  for(const id of Object.keys(before))if(id.startsWith("deco-") && !layoutItems[id] && assetGroups.has(id)){
    const a=assetGroups.get(id);a.group.removeFromParent();assetGroups.delete(id);
    const i=pickables.indexOf(a.group);if(i>=0)pickables.splice(i,1);
    const c=colliders.indexOf(a.group.userData.collider);if(c>=0)colliders.splice(c,1);
  }
  for(const id of new Set([...Object.keys(before),...Object.keys(layoutItems)]))applyAsset(id);
  queueSave();assetUI.refresh();assetUI.show(selectedAsset);
}
function applyLayout(layout){
  layoutItems=Object.fromEntries(Object.entries(layout?.items||{}).filter(([,v])=>v && typeof v==="object"));
  for(const [id,e] of Object.entries(layoutItems))if(id.startsWith("deco-") && e.asset && Number.isFinite(e.x))spawnDecor(id,e.asset,e.x,e.z);
  for(const id of Object.keys(layoutItems))applyAsset(id);
}
function freeSpotNear(id,center){
  const a=assetGroups.get(id),r=a.group.userData.baseRadius;
  for(let ring=0;ring<40;ring++)for(let k=0;k<Math.max(1,ring*6);k++){
    const angle=k/Math.max(1,ring*6)*Math.PI*2+ring*.37,x=center.x+Math.cos(angle)*ring*.45,z=center.z+Math.sin(angle)*ring*.45;
    if(Math.hypot(x,z)>ISLAND-2)continue;
    if(pavementGap(x,z)<r+.1)continue;
    if(colliders.some(c=>c!==a.group.userData.collider && c.r>0 && Math.hypot(c.x-x,c.z-z)<c.r+r+.15))continue;
    return {x,z};
  }
  return {x:center.x,z:center.z};
}
function focusAsset(id){
  const a=assetGroups.get(id);if(!a||!a.group.visible)return;
  housePortrait=null;leaveWalk();stopFly();mode="orbit";controls.enabled=true;lens(false);
  const g=a.group,target=g.position.clone();target.y+=1.1*(g.scale.x||1);
  const away=camera.position.clone().sub(controls.target);away.y=0;
  if(away.lengthSq()<.01)away.set(0,0,1);
  away.normalize().multiplyScalar(6.4+assetRadius(a)*2.2);away.y=4.2;
  // 面板盖住右侧时，把展品让到画面左边的空处。
  const panelWidth=arranging&&innerWidth>720?document.getElementById("assets").getBoundingClientRect().width+22:0;
  const right=new THREE.Vector3(away.z,0,-away.x).normalize();
  const halfWidth=away.length()*Math.tan(THREE.MathUtils.degToRad(camera.fov/2))*camera.aspect;
  const lookAt=target.clone().addScaledVector(right,halfWidth*panelWidth/innerWidth);
  tween={from:camera.position.clone(),to:lookAt.clone().add(away),fromT:controls.target.clone(),toT:lookAt,start:performance.now(),dur:1100};
  setPressed(null);
}
function selectAsset(id,{focus=false}={}){
  selectedAsset=id&&assetGroups.has(id)?id:null;
  updateRing();assetUI.show(selectedAsset);
  if(focus&&selectedAsset)focusAsset(selectedAsset);
}
function assetList(){
  return [...assetGroups].map(([id,{item,kind}])=>{
    const st=assetState(id);
    const printed=kind==="exhibit" && (PRINTED.test(item.print_state||"") || !!item.photo_url);
    return {id,kind,printed,hidden:st.hidden,moved:st.moved,title:cards.get(item.card_id)?.title||item.title||"未命名",
      sub:kind==="exhibit"?(item.date||"样品"):(item.stage||"世界精雕"),yaw:st.yaw,scale:st.scale};
  });
}
function addDecor(name){
  const id="deco-"+name+"-"+Math.random().toString(36).slice(2,8);
  const center=controls.target.clone();
  const tmp={x:center.x,z:center.z};
  if(!spawnDecor(id,name,tmp.x,tmp.z))return;
  const spot=freeSpotNear(id,center);
  commit(id,{asset:name,x:spot.x,z:spot.z});
  sound.place();selectAsset(id,{focus:true});assetUI.show(id);
}
if(readOnly)document.getElementById("open-assets").hidden=true;
const assetUI=assetPanel({
  list:assetList,
  open(){
    arranging=true;card.close();leaveWalk();stopFly();document.body.classList.add("arranging");
    if(selectedAsset)updateRing();
  },
  close(){arranging=false;draggingAsset=null;controls.enabled=mode==="orbit";selectionRing.visible=false;document.body.classList.remove("arranging");},
  select(id){selectAsset(id,{focus:true});},
  change(id,patch){
    if(patch.reset){
      const deco=assetGroups.get(id)?.kind==="deco";
      commit(id,deco?{yaw:undefined,scale:undefined,hidden:undefined}:{x:undefined,z:undefined,yaw:undefined,scale:undefined,hidden:undefined});return;
    }
    if(patch.hidden===true)sound.store();
    if(patch.hidden===false)sound.place();
    if(patch.hidden===false && !assetGroups.get(id).group.visible){
      const ground0=controls.target.clone(),spot=freeSpotNear(id,ground0);
      commit(id,{hidden:undefined,x:spot.x,z:spot.z});focusAsset(id);return;
    }
    commit(id,patch);
  },
  preview(id,patch){setEntry(id,patch);},
  begin(){rememberLayout();},
  finish(){queueSave();assetUI.refresh();},
  undo:undoLayout,
  canUndo:()=>layoutHistory.length>0,
  decor:DECOR.map(([name,label])=>({name,label})),
  add:addDecor,
  remove:removeDecor,
});
function groundUnderPointer(event,y){
  pointer.set((event.clientX/innerWidth)*2-1,-(event.clientY/innerHeight)*2+1);
  ray.setFromCamera(pointer,camera);dragPlane.constant=-y;
  return ray.ray.intersectPlane(dragPlane,dragHit)?dragHit.clone():null;
}
// 本机自检：展品在屏幕上的位置和当前摆放。
window.__assetProbe=id=>{
  const a=assetGroups.get(id);if(!a)return null;
  const v=a.group.position.clone();v.y+=(a.group.userData.restingHeight??1)*a.group.scale.x+.3;v.project(camera);
  return {x:(v.x+1)*innerWidth/2,y:(1-v.y)*innerHeight/2,visible:a.group.visible,pos:a.group.position.toArray(),entry:layoutItems[id]||null,selected:selectedAsset===id};
};
window.__assetIds=()=>[...assetGroups.keys()];
window.__assetProblems=()=>[...assetGroups].map(([id,a])=>[id,a.item.title,a.group.visible?spotProblem(id,a.group.position.x,a.group.position.z):""]).filter(r=>r[2]);
window.__assetDump=()=>[...assetGroups].map(([id,a])=>({id,kind:a.kind,title:a.item.title,stage:a.item.stage,zone:a.item.placement?.zone,site:a.group.userData.site?.kind,
  hx:+a.group.userData.home.x.toFixed(3),hz:+a.group.userData.home.z.toFixed(3),front:+Math.atan2(a.group.userData.homeFront?.x??0,a.group.userData.homeFront?.z??1).toFixed(4),
  lx:a.group.userData.site?.look?.x,lz:a.group.userData.site?.look?.z,
  x:+a.group.position.x.toFixed(2),z:+a.group.position.z.toFixed(2),r:+(a.group.userData.baseRadius||0).toFixed(2),h:+(a.group.userData.modelHeight||0).toFixed(2)}));
window.__view=(pos,target)=>{tween=null;stopFly();leaveWalk();mode="orbit";lens(false);camera.position.fromArray(pos);controls.target.fromArray(target);controls.update();refreshDetails();};
function assetOf(obj){for(const [id,a] of assetGroups)if(a.group===obj)return id;return null;}

// ---------- 镜头：第三人称 ----------
const VIEWS = {
  overview: { pos: [0, 95, 128], target: [0, 3, 0] },
  hall: { pos: [0, TOP + 5.5, 15.5], target: [0, TOP + 1.6, 0] },
};
let mode = "orbit"; // orbit | fly | walk
let tween = null, fly = null, eraMarks = [];
const eraBox = document.getElementById("era");
const hint = document.getElementById("hint");
const walkHint = hint.textContent;

function setPressed(name) {
  document.querySelectorAll(".views [data-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === name)));
}
function overviewView() {
  const aspect=innerWidth/innerHeight;
  const portrait=aspect<1;
  return {pos:portrait?[0,127,108]:[0,98,135],target:[0,1,0]};
}
function lens(overview) {
  const widen=overview?Math.max(1,1.20/camera.aspect):1;
  camera.fov=THREE.MathUtils.radToDeg(2*Math.atan(Math.tan(THREE.MathUtils.degToRad(21))*widen));
  camera.updateProjectionMatrix();
}
function flyTo(name) {
  housePortrait=null;leaveWalk();
  fly = null;
  mode = "orbit";
  controls.enabled = true;
  controls.minDistance=4;lens(name==="overview");
  const v = name === "overview" ? overviewView() : VIEWS[name];
  tween = { from: camera.position.clone(), to: new THREE.Vector3(...v.pos), fromT: controls.target.clone(), toT: new THREE.Vector3(...v.target), start: performance.now(), dur: 1800 };
  setPressed(name);
}
function startFly() {
  sound.whoosh();
  housePortrait=null;lens(false);leaveWalk();
  tween = null;
  fly = { progress:0, shown:-1 };
  mode = "fly";
  controls.enabled = false;
  setPressed("fly");
}
function stopFly() {
  if (mode !== "fly") return;
  fly = null;
  mode = "orbit";
  controls.enabled = true;
  eraBox.classList.remove("on");
  setPressed(null);
}
const ease = (x) => x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
function showEra(era) {
  const period=document.createElement("small"),title=document.createElement("strong");
  const fields=cards.get(era.card_id)||era.card;
  period.textContent=fields?.kicker||era.period;title.textContent=fields?.title||era.title;eraBox.replaceChildren(period,title);
  eraBox.classList.add("on");
  clearTimeout(showEra.timer);
  showEra.timer = setTimeout(() => eraBox.classList.remove("on"), 4200);
}

// ---------- 第一人称走动 ----------
const keys = new Set();
const walk = { yaw: 0, pitch: 0, pos: new THREE.Vector3(), lastEra: -1 };
const EYE = 1.6;
function enterWalk() {
  housePortrait=null;lens(false);stopFly();
  tween = null;
  mode = "walk";
  controls.enabled = false;
  setPressed("walk");
  // 从展台附近进入则站在展台外圈，否则从小路起点开始
  const nearHall = camera.position.length() < 30;
  if (nearHall) {
    walk.pos.set(0, 0, 8.2);
    walk.yaw = 0;
  } else {
    const { p, tangent } = pathFrame(0.002);
    walk.pos.copy(p).addScaledVector(tangent, -1.5);
    walk.yaw = Math.atan2(-tangent.x, -tangent.z);
  }
  walk.pos.y=ground(walk.pos.x,walk.pos.z)+(nearHall?.3:0);
  walk.pitch = -0.05;
  walk.lastEra = -1;
  hint.hidden = false;
  document.body.classList.add("walking");
  lockPointer();
}
function lockPointer() {
  try {
    if (managingPeople || workbench.active() || card.active()) return;
    const r = renderer.domElement.requestPointerLock?.();
    if (r && r.catch) r.catch(() => {}); // 有些内嵌窗口不允许锁鼠标，就退回按住拖动看
  } catch { /* 同上 */ }
}
function leaveWalk() {
  if (mode !== "walk") return;
  mode = "orbit";
  hint.hidden = true;
  document.body.classList.remove("walking");
  if (document.pointerLockElement) document.exitPointerLock();
  const forward = new THREE.Vector3(-Math.sin(walk.yaw), 0, -Math.cos(walk.yaw));
  controls.target.copy(camera.position).addScaledVector(forward, 6);
  controls.enabled = true;
  setPressed(null);
}
let retainWalkOnUnlock = false;
document.addEventListener("pointerlockchange", () => {
  const locked = document.pointerLockElement === renderer.domElement;
  const wasLocked = document.body.classList.contains("locked");
  document.body.classList.toggle("locked", locked);
  if(wasLocked && !locked && !retainWalkOnUnlock && mode==="walk") leaveWalk();
  retainWalkOnUnlock = false;
});
let dragged = false;
document.addEventListener("mousemove", (e) => {
  if (mode !== "walk" || managingPeople || card.active() || workbench.active()) return;
  const locked = document.pointerLockElement === renderer.domElement;
  if (!locked && !(e.buttons & 1)) return;
  if (!locked) dragged = true;
  walk.yaw -= e.movementX * 0.0022;
  walk.pitch = THREE.MathUtils.clamp(walk.pitch - e.movementY * 0.0022, -1.2, 1.2);
});
addEventListener("keydown", (e) => {
  if(arranging && !e.target.closest?.("input,textarea,select")){
    if((e.metaKey||e.ctrlKey) && e.code==="KeyZ"){e.preventDefault();undoLayout();return;}
    if(selectedAsset){
      const st=assetState(selectedAsset);
      if(e.code==="KeyQ"||e.code==="KeyE"){commit(selectedAsset,{yaw:st.yaw+(e.code==="KeyQ"?15:-15)});return;}
      if(e.code==="BracketLeft"||e.code==="BracketRight"){commit(selectedAsset,{scale:THREE.MathUtils.clamp(+(st.scale+(e.code==="BracketLeft"?-.1:.1)).toFixed(2),.6,1.6)});return;}
      if(e.code==="Escape"){selectAsset(null);return;}
    }
  }
  if (managingPeople || workbench.active() || card.active() || e.target.closest?.("input,textarea,button,dialog")) return;
  keys.add(e.code);
  if (mode === "walk" && e.code === "KeyE" && !e.repeat) activate(nearPortal() ? portal : pickCenter());
  if (e.code === "Escape" && mode === "walk" && !document.pointerLockElement) leaveWalk();
  if(mode==="walk" && e.code.startsWith("Arrow")) e.preventDefault();
});
addEventListener("keyup", (e) => keys.delete(e.code));
addEventListener("blur", () => keys.clear());

function blockedAt(x, z) {
  if (Math.hypot(x, z) > ISLAND - 0.6) return true; // 不下海（栈桥除外）
  return colliders.some((c) => (c.x - x) ** 2 + (c.z - z) ** 2 < (c.r + 0.28) ** 2);
}
function onPier(x, z) {
  const a = PATH_START - 0.18, dir = [Math.cos(a), Math.sin(a)];
  const along = x * dir[0] + z * dir[1], across = -x * dir[1] + z * dir[0];
  return along > ISLAND - 4 && along < ISLAND + 4.2 && Math.abs(across) < 0.5;
}
function updateWalk(dt) {
  if(card.active()) return;
  const speed = (keys.has("ShiftLeft") || keys.has("ShiftRight") ? 7.5 : 3.6) * dt;
  const f = (keys.has("KeyW") || keys.has("ArrowUp") ? 1 : 0) - (keys.has("KeyS") || keys.has("ArrowDown") ? 1 : 0);
  const s = (keys.has("KeyD") ? 1 : 0) - (keys.has("KeyA") ? 1 : 0);
  walk.yaw += ((keys.has("ArrowLeft") || keys.has("KeyQ") ? 1 : 0) - (keys.has("ArrowRight") ? 1 : 0)) * 1.8 * dt; // 左右转头
  if (f || s) {
    sound.step(keys.has("ShiftLeft") || keys.has("ShiftRight"));
    const forward = new THREE.Vector3(-Math.sin(walk.yaw), 0, -Math.cos(walk.yaw));
    const right = new THREE.Vector3(-forward.z, 0, forward.x);
    const step = forward.multiplyScalar(f).add(right.multiplyScalar(s)).normalize().multiplyScalar(speed);
    // 分轴尝试，撞到东西时能贴着滑过去
    const nx = walk.pos.x + step.x, nz = walk.pos.z + step.z;
    const ok = (x, z) => onPier(x, z) || !blockedAt(x, z);
    if (ok(nx, nz)) { walk.pos.x = nx; walk.pos.z = nz; }
    else if (ok(nx, walk.pos.z)) walk.pos.x = nx;
    else if (ok(walk.pos.x, nz)) walk.pos.z = nz;
  }
  const gy = onPier(walk.pos.x, walk.pos.z) && Math.hypot(walk.pos.x, walk.pos.z) > ISLAND - 3 ? 0.36 : ground(walk.pos.x, walk.pos.z) + (Math.hypot(walk.pos.x, walk.pos.z) <= 8.6 ? 0.3 : 0);
  walk.pos.y += (gy - walk.pos.y) * Math.min(1, dt * 12);
  const bob = (f || s) ? Math.sin(performance.now() * 0.011) * 0.035 : 0;
  camera.position.set(walk.pos.x, walk.pos.y + EYE + bob, walk.pos.z);
  camera.rotation.set(walk.pitch, walk.yaw, 0, "YXZ");
  const nextHint=nearPortal()?"按 E 打开今日小物":walkHint;
  if(hint.textContent!==nextHint){hint.textContent=nextHint;hint.classList.toggle("action",nextHint!==walkHint);}
  // 走过人生阶段门时浮出阶段名
  eraMarks.forEach((m, i) => {
    const p = pathPoint(m.t);
    if (i !== walk.lastEra && (p.x - walk.pos.x) ** 2 + (p.z - walk.pos.z) ** 2 < 6) { walk.lastEra = i; showEra(m.era); }
  });
}

function updateCamera(now, dt) {
  if (tween) {
    const k = ease(Math.min(1, (now - tween.start) / tween.dur));
    camera.position.lerpVectors(tween.from, tween.to, k);
    controls.target.lerpVectors(tween.fromT, tween.toT, k);
    if (k >= 1) tween = null;
  }
  if (mode === "fly" && fly) {
    const nearest=Math.min(...eraMarks.map(mark=>Math.abs(mark.t-fly.progress)),1);
    const speed=THREE.MathUtils.lerp(.29,1,THREE.MathUtils.smoothstep(nearest,.002,.030));
    fly.progress=Math.min(1,fly.progress+dt*speed/44);
    const u=fly.progress, t=u*.995;
    const { p, side, tangent } = pathFrame(t);
    const eye = p.clone().addScaledVector(tangent, -4.2).addScaledVector(side, 0.6);
    eye.y = Math.max(eye.y, ground(eye.x, eye.z)) + 2.4;
    const look = pathPoint(Math.min(1, t + 0.025));
    look.y += 1.2;
    camera.position.copy(eye);
    controls.target.copy(look);
    camera.lookAt(controls.target);
    const current = eraMarks.filter((m) => m.t <= t + 0.01).pop();
    const idx = current ? eraMarks.indexOf(current) : -1;
    if (idx !== fly.shown && current) { fly.shown = idx; showEra(current.era); }
    if (u >= 1) { stopFly(); flyTo("hall"); }
  }
  if (mode === "walk") updateWalk(dt);
}

// ---------- 点选 ----------
function releasePointer() {
  keys.clear();
  if(document.pointerLockElement===renderer.domElement) {
    retainWalkOnUnlock = true;
    document.exitPointerLock();
  }
}
const card=objectCard({release:releasePointer,changed(data) {
  for(const tag of tagRecords.filter(t=>t.data===data)){
    if(tag.el.textContent!==data.title)tag.obj.userData.updateTitle?.(data.title);
    tag.el.textContent=data.title;
  }
}});
async function refreshExhibits() {
  try {
    const r=await fetch("/data/world.json",{cache:"no-store"});
    if(!r.ok) throw new Error();
    const world=await r.json();placeExhibits(world.exhibits||[],true);
    for(const id of Object.keys(layoutItems))applyAsset(id);
    assetUI.refresh();
  } catch {
    const box=document.getElementById("era");box.textContent="展台暂时未更新，刷新小岛可重试。";box.classList.add("on");
    clearTimeout(showEra.timer);showEra.timer=setTimeout(()=>box.classList.remove("on"),4600);
  }
}
let managingPeople=false;
function pauseWorld(){card.close();releasePointer();pausedAt=performance.now();renderer.setAnimationLoop(null);}
function resumeWorld(){if(mode==="walk")renderer.domElement.focus({preventScroll:true});if(tween)tween.start+=performance.now()-pausedAt;clock?.getDelta();if(renderWorld) renderer.setAnimationLoop(renderWorld);}
addEventListener("people-manager-open",()=>{managingPeople=true;pauseWorld();});
addEventListener("people-manager-close",()=>{managingPeople=false;if(!workbench.active())resumeWorld();});
addEventListener("person-card-saved",({detail})=>{
  const key=String(detail?.id||""),obj=namedObjects.get(key)||namedObjects.get("person:"+key);
  if(!obj || !detail?.card)return;
  const data=obj.userData.pick;Object.assign(data,detail.card);
  for(const r of tagRecords)if(r.obj===obj){r.data=data;r.el.textContent=data.title;}
});
const workbench=workbenchPanel({
  pause:pauseWorld,resume(){if(!managingPeople)resumeWorld();},refresh:refreshExhibits,
});
function nearPortal() {
  return !readOnly && portal && Math.hypot(walk.pos.x-portal.position.x,walk.pos.z-(portal.position.z+.85))<=2;
}
const ray = new THREE.Raycaster(), pointer = new THREE.Vector2();
let down = null;
function shown(o){for(;o;o=o.parent)if(!o.visible)return false;return true;}
function firstShown(hits){return hits.find(h=>shown(h.object));}
function resolvePick(hit) {
  let o = hit && hit.object;
  while (o && !o.userData.pick) o = o.parent;
  return o;
}
function pickAt(event) {
  pointer.set((event.clientX / innerWidth) * 2 - 1, -(event.clientY / innerHeight) * 2 + 1);
  ray.setFromCamera(pointer, camera);
  ray.far = Infinity;
  return resolvePick(firstShown(ray.intersectObjects(pickables, true)));
}
function pickCenter() {
  ray.setFromCamera(new THREE.Vector2(0, 0), camera);
  ray.far = 7;
  const o = resolvePick(firstShown(ray.intersectObjects(pickables, true)));
  ray.far = Infinity;
  return o;
}
function activate(o) {
  if(!o) {card.close();return;}
  const d=o.userData.pick;
  if(d?.action==="people-group")window.dispatchEvent(new CustomEvent("people-manager-request",{detail:{group:d.group}}));
  else if(d?.action==="workbench") {
    if(mode!=="walk" || nearPortal()) workbench.open();
  }
  else {card.open(d,o.userData.linkedCard,o.userData.failed);sound.open();}
}
renderer.domElement.addEventListener("pointerdown", (e) => {
  if(arranging && e.button===0 && selectedAsset){
    const id=assetOf(pickAt(e));
    if(id===selectedAsset){
      const g=assetGroups.get(id).group,hit=groundUnderPointer(e,g.position.y);
      if(hit){
        draggingAsset={id,moved:false};dragOffset.set(g.position.x-hit.x,0,g.position.z-hit.z);sound.pick();
        controls.enabled=false;rememberLayout();renderer.domElement.setPointerCapture(e.pointerId);
        document.body.classList.add("dragging-asset");
      }
    }
  }
  down = [e.clientX, e.clientY];
  dragged = false;
  if (mode === "fly") stopFly();
  tween = null;
});
renderer.domElement.addEventListener("pointermove",(e)=>{
  if(!draggingAsset)return;
  const g=assetGroups.get(draggingAsset.id).group,hit=groundUnderPointer(e,g.position.y);
  if(!hit)return;
  let x=hit.x+dragOffset.x,z=hit.z+dragOffset.z;
  const r=Math.hypot(x,z),limit=ISLAND-1.6;if(r>limit){x*=limit/r;z*=limit/r;}
  draggingAsset.moved=true;setEntry(draggingAsset.id,{x,z});
});
renderer.domElement.addEventListener("pointerup", (e) => {
  if(draggingAsset){
    const {moved}=draggingAsset;draggingAsset=null;controls.enabled=true;document.body.classList.remove("dragging-asset");
    if(moved){queueSave();assetUI.refresh();down=null;sound.drop();return;}
    layoutHistory.pop();
  }
  if(arranging && mode!=="walk"){
    if(!down || Math.hypot(e.clientX-down[0],e.clientY-down[1])>5)return;
    const id=assetOf(pickAt(e));selectAsset(id);return;
  }
  if (mode === "walk") {
    if (!dragged) {
      const target=document.pointerLockElement ? pickCenter() : pickAt(e);
      if(target && camera.position.distanceTo(target.position)<8) activate(target);
      else {card.close();lockPointer();}
    }
    return;
  }
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
  activate(pickAt(e));
});
let hovered = null, lastHover = 0;
renderer.domElement.addEventListener("pointermove", (e) => {
  if (mode !== "orbit" || e.buttons || e.timeStamp-lastHover<65) return;
  lastHover=e.timeStamp;
  hovered = pickAt(e);
  renderer.domElement.style.cursor = hovered ? "pointer" : "";
});
document.querySelectorAll(".views [data-view]").forEach((b) => b.addEventListener("click", (e) => {
  e.currentTarget.blur();
  card.close();
  const v = b.dataset.view;
  if (v === "fly") startFly();
  else if (v === "walk") enterWalk();
  else flyTo(v);
}));
addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
  labels.setSize(innerWidth, innerHeight);
  if(document.querySelector('[data-view="overview"]').getAttribute('aria-pressed')==="true") flyTo("overview");
});

// ---------- 启动 ----------
function thisMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

const layoutTemp=new THREE.Vector3();
let lastLabel=0,lastFocusHash=null,housePortrait=null;
controls.addEventListener("start",()=>{housePortrait=null;});
function layoutTags(now) {
  if(now-lastLabel<50) return false;
  lastLabel=now;
  const overview=mode==="orbit" && camera.position.distanceTo(controls.target)>92;
  document.body.classList.toggle("island-overview",overview);
  const candidates=[], atDoor=mode==="walk"&&nearPortal(), reading=card.active();
  for(const record of tagRecords) {
    const {el,obj,category,label}=record;
    if(!obj.visible){el.classList.remove("show");continue;}
    if((overview && category!=="era") || (atDoor && obj!==portal)){el.classList.remove("show");continue;}
    if(category==="portal")label.position.set(0,atDoor?1.72:3.05,atDoor?.84:0);
    if(!overview)el.style.translate="";
    label.getWorldPosition(layoutTemp);
    const distance=layoutTemp.distanceTo(camera.position);
    const homePortrait=mode==="orbit" && !!housePortrait;
    const near=!homePortrait && !(reading && ["person","moment","exhibit"].includes(category)) && (overview || obj===hovered ||
      (category==="era" ? distance>10 && distance<46 : distance<({exhibit:obj.userData.itemId?13:6,person:10,moment:5,portal:mode==="walk"?7:17}[category]||9)));
    if(!near){el.classList.remove("show");continue;}
    layoutTemp.project(camera);
    if(Math.abs(layoutTemp.z)>1 || (!overview && (Math.abs(layoutTemp.x)>1 || Math.abs(layoutTemp.y)>1))) {el.classList.remove("show");continue;}
    const x=(layoutTemp.x+1)*innerWidth/2,y=(1-layoutTemp.y)*innerHeight/2;
    const width=el.offsetWidth||Math.min(320,el.textContent.length*14+22), height=el.offsetHeight||27;
    candidates.push({el,x,y,key:record.data.id||record.data.title,w:width+10,h:height+6,rank:(obj===hovered?0:category==="portal"?1:category==="era"?3:2),distance});
  }
  guideLayer.style.display=overview?"":"none";
  if(overview){
    const move=(b,x,y)=>{
      const dx=x-b.x,dy=y-b.y,line=stageGuides.get(b.el);
      b.el.style.translate=dx.toFixed(1)+"px "+dy.toFixed(1)+"px";b.el.classList.add("show");
      if(!line)return;
      const shifted=Math.hypot(dx,dy)>Math.max(22,b.h*.75);
      line.style.display=shifted?"":"none";
      if(shifted){
        const edge=Math.min(1,(b.w/2-5)/Math.max(.001,Math.abs(dx)),(b.h/2-3)/Math.max(.001,Math.abs(dy)));
        line.setAttribute("x1",b.x);line.setAttribute("y1",b.y);
        line.setAttribute("x2",x-dx*edge);line.setAttribute("y2",y-dy*edge);
      }
    };
    const half=innerWidth/2,ordered=candidates.sort((a,b)=>a.x-b.x);
    if(innerWidth<610 && innerHeight>620 && ordered.length===8){
      const edge=[];
      for(let i=0;i<32;i++){
        const angle=i*Math.PI/16;
        layoutTemp.set(ISLAND*Math.cos(angle),0,ISLAND*Math.sin(angle)).project(camera);
        edge.push((1-layoutTemp.y)*innerHeight/2);
      }
      const top=Math.min(...edge)-10,bottom=Math.max(...edge)+10;
      const group=[...ordered].sort((a,b)=>a.y-b.y);
      for(const [above,items] of [[true,group.slice(0,4)],[false,group.slice(4)]]){
        items.sort((a,b)=>a.x-b.x);
        for(let col=0;col<2;col++){
          const pair=items.slice(2*col,2*col+2).sort((a,b)=>a.y-b.y);
          const ys=above?[top-pair[1].h-pair[0].h/2-6,top-pair[1].h/2]:[bottom+pair[0].h/2,bottom+pair[0].h+pair[1].h/2+6];
          pair.forEach((b,i)=>move(b,half*(col+.5),THREE.MathUtils.clamp(ys[i],128,innerHeight-28)));
        }
      }
      return true;
    }
    for(let col=0;col<2;col++) {
      const column=ordered.slice(col*4,col*4+4).sort((a,b)=>a.y-b.y);
      const center=half*(col+.5),low=Math.min(innerHeight*.30,110),high=innerHeight-105;
      const ys=column.map(b=>THREE.MathUtils.clamp(b.y,low,high));
      for(let i=1;i<ys.length;i++)ys[i]=Math.max(ys[i],ys[i-1]+(column[i].h+column[i-1].h)/2+5);
      if(ys.at(-1)>high){ys[ys.length-1]=high;for(let i=ys.length-2;i>=0;i--)ys[i]=Math.min(ys[i],ys[i+1]-(column[i].h+column[i+1].h)/2-5);}
      column.forEach((b,i)=>{
        const left=col*half+b.w/2+5,right=(col+1)*half-b.w/2-5;
        const x=left>right?center:THREE.MathUtils.clamp(b.x,left,right);
        move(b,x,ys[i]);
      });
    }
    return true;
  }
  const panels=[document.querySelector(".views"),document.querySelector(".mark")];
  if(reading)panels.push(document.getElementById("card"));
  if(arranging)panels.push(document.getElementById("assets"));
  if(eraBox.classList.contains("on"))panels.push(eraBox);
  if(!hint.hidden)panels.push(hint);
  const occupied=panels.map(panel=>{
    const r=panel.getBoundingClientRect();
    return {x:r.x+r.width/2,y:r.y+r.height/2,w:r.width+14,h:r.height+10};
  });
  const shown=new Set(),limit=Math.max(3, Math.min(8,Math.floor(innerWidth/170)));
  for(const b of candidates.sort((a,b)=>a.rank-b.rank||a.distance-b.distance)) {
    const inside=b.x-b.w/2>=4 && b.x+b.w/2<innerWidth-4 && b.y-b.h/2>=3 && b.y+b.h/2<innerHeight-3;
    const show=inside && shown.size<limit && !shown.has(b.key) && !occupied.some(r=>Math.abs(b.x-r.x)*2<b.w+r.w && Math.abs(b.y-r.y)*2<b.h+r.h);
    b.el.classList.toggle("show",show);if(show){occupied.push(b);shown.add(b.key);}
  }
  return true;
}
// 私人展品的本机深链接，也可从交接截图回到同一件作品。
function tryFocusHash() {
  const id=new URLSearchParams(location.hash.slice(1)).get("object");
  if(!id || location.hash===lastFocusHash || !clock) return;
  const obj=namedObjects.get(id);
  if(!obj || (obj.userData.houseExpected && !obj.userData.houseReady) || ((obj.userData.expectsModel||obj.userData.ticket) && !obj.userData.ready && !obj.userData.failed)) return;
  lastFocusHash=location.hash;housePortrait=id.startsWith("house-")?obj:null;card.close();lens(false);leaveWalk();stopFly();tween=null;mode="orbit";controls.enabled=true;
  const site=obj.userData.site;
  const at=obj.getWorldPosition(new THREE.Vector3()), high=site?.kind?obj.userData.plinth.position.y+obj.userData.plinth.scale.y+obj.userData.modelHeight*.47:obj.userData.proxy?0:id.startsWith("era-")?1.75:1.05;
  at.y+=high;
  if(id.startsWith("scene-")){
    const mark=eraMarks.find(e=>e.model===obj);
    if(mark) {const gate=pathPoint(mark.t);at.x=THREE.MathUtils.lerp(at.x,gate.x,.35);at.z=THREE.MathUtils.lerp(at.z,gate.z,.35);}
  }
  const front=obj.userData.front||new THREE.Vector3(.35,0,1).normalize();
  const spacing=site?Math.max(2.25,LAYOUT[site.kind].height*2.55):obj.userData.focusExtent?Math.max(4.0,obj.userData.focusExtent*2.05/Math.min(1,camera.aspect)):id.startsWith("scene-")?10:id==="workshop"?6:4.8;
  controls.minDistance=site?1.35:4;
  const origin=obj.getWorldPosition(new THREE.Vector3());
  let direction=front,low=Infinity;
  const hashArgs=new URLSearchParams(location.hash.slice(1));
  const inspectPose=new URLSearchParams(location.search).has("measure") && hashArgs.has("yaw");
  const angles=inspectPose?[(Number(hashArgs.get("yaw"))||0)*Math.PI/180]:obj.userData.houseStyle?[0]:obj.userData.fixedFront?[0]:obj.userData.expectsModel?[0,.30,-.30]:[0,.37,-.37,.73,-.73,1.1,-1.1,1.56,-1.56,2.15,-2.15,Math.PI];
  for(const angle of angles){
    const v=front.clone().applyAxisAngle(UP,angle);
    let penalty=Math.abs(angle)*.2;
    for(const c of colliders){
      const dx=c.x-origin.x,dz=c.z-origin.z,along=dx*v.x+dz*v.z;
      if(along<.7 || along>spacing+.5)continue;
      const side=Math.abs(dx*v.z-dz*v.x);
      penalty+=Math.max(0,c.r+.42-side)*(1+along/spacing);
    }
    if(penalty<low){direction=v;low=penalty;}
  }
  camera.position.copy(at).addScaledVector(direction,spacing);camera.position.y+=spacing*.50;
  if(obj.userData.expectsModel) {
    const nearby=gateSightlines.filter(g=>g.position.distanceToSquared(origin)<11**2);
    const obstruction=(eye,forward)=>{
      let blocked=0;
      const side=new THREE.Vector3(forward.z,0,-forward.x);
      for(const gate of nearby) {
        const localEye=eye.clone().applyMatrix4(gate.inverse);
        if(gate.boxes.some(box=>box.distanceToPoint(localEye)<.78)) blocked+=5;
        for(const [x,y] of [[0,0],[-1.24,0],[1.24,0],[-.65,.48],[.65,.48],[0,.78],[0,-.65]]) {
          const target=at.clone().addScaledVector(side,x);target.y+=y;target.applyMatrix4(gate.inverse);
          const line=target.clone().sub(localEye),length=line.length();
          const ray=new THREE.Ray(localEye,line.normalize()),hit=new THREE.Vector3();
          if(gate.boxes.some(box=>box.containsPoint(localEye) || (ray.intersectBox(box,hit) && hit.distanceTo(localEye)<length))) blocked++;
        }
      }
      return blocked;
    };
    if(!inspectPose && nearby.length && obstruction(camera.position,direction)) {
      let best=Infinity;
      for(const angle of [0,.27,-.27,.50,-.50,.76,-.76])for(const reach of [spacing,spacing*.82,spacing*.69])for(const lift of [0,.72,1.42]) {
        const v=front.clone().applyAxisAngle(UP,angle),eye=at.clone().addScaledVector(v,reach);
        eye.y+=reach*.50+lift;
        const score=obstruction(eye,v)*20 + Math.abs(angle)*1.2 + (spacing-reach)*.38 + lift*.65;
        if(score<best){best=score;camera.position.copy(eye);}
      }
    }
  }
  controls.target.copy(at);controls.update();refreshDetails();setPressed(null);
  if(obj!==portal && !id.startsWith("house-") && !obj.userData.pick?.action)card.open(obj.userData.pick,obj.userData.linkedCard,obj.userData.failed);
  document.body.dataset.focusedObject=id;
}
addEventListener("hashchange",()=>{lastFocusHash=null;tryFocusHash();});

async function main() {
  const [world] = await Promise.all([fetch("/data/world.json",{cache:"no-store"}).then(r=>{if(!r.ok)throw new Error("world.json");return r.json();}), loadAssets()]);
  currentWorld=world;
  const months=monthsBetween(world.start,world.end||thisMonth());
  eraMarks=planPlazas(months,world.eras);
  sky();const finishPaving=path();gates(eraMarks);
  const sites=momentSites(months,world.moments||[]);
  hall();sculptures(world.sculptures||[],sites);applyLayout(world.layout);placeExhibits(world.exhibits||[]);
  applyLayout(world.layout);
  wayside(sites);lanternsFor(months,world.emotions);homes(months,world.people);finishPaving();island();shore(world.circles||[]);nature();
  lens(true);const view=overviewView();camera.position.fromArray(view.pos);controls.target.fromArray(view.target);controls.update();
  clock=new THREE.Clock();tryFocusHash();
  sound.ambient("sea");soundToggle();
  document.addEventListener("click",e=>{
    const b=e.target.closest?.("button, a.palace-link");if(!b)return;
    if(b.closest(".card") && b.classList.contains("close"))sound.close();
    else if(b.closest(".views,.assets,.card,#workbench,.people"))sound.tap();
  },true);
  const loading=document.getElementById("loading");
  loading.setAttribute("aria-hidden","true");
  loading.addEventListener("transitionend",()=>{loading.hidden=true;},{once:true});
  loading.classList.add("done");
  const measure=new URLSearchParams(location.search).has("measure");
  const namedSculptures=()=>(world.sculptures||[]).filter(v=>namedObjects.get(v.id)?.userData.ready).length;
  if(measure) {
    window.__worldPlinthAudit=()=>{
      const pads=(world.sculptures||[]).map(({id})=>({id,g:namedObjects.get(id)})).filter(p=>p.g?.userData.ready);
      const conflicts=[];
      let minimum=Infinity;
      for(let i=0;i<pads.length;i++)for(let j=i+1;j<pads.length;j++) {
        const a=pads[i].g,b=pads[j].g,sa=a.userData.plinth.scale,sb=b.userData.plinth.scale;
        const gap=Math.hypot(a.position.x-b.position.x,a.position.z-b.position.z)-(sa.x+sb.x)/2;
        minimum=Math.min(minimum,gap);
        if(gap<.04)conflicts.push([pads[i].id,pads[j].id]);
      }
      const dailyConflicts=[];
      for(const [i,daily] of pedestals)for(const {id,g} of pads){
        const gap=Math.hypot(daily.position.x-g.position.x,daily.position.z-g.position.z)-.66-g.userData.plinth.scale.x/2;
        if(gap<.04)dailyConflicts.push([i,id]);
      }
      return {pedestals:pads.length,minimumMeters:Number.isFinite(minimum)?minimum:null,conflicts,dailyConflicts};
    };
    window.__worldLayoutAudit=()=>{
      const counts={},heightRanges={},footprints={},material={textured:0,vertexColor:0,plain:0,dailyResin:0,farMissingUV:0};
      for(const s of reservedSites){counts[s.kind]=(counts[s.kind]||0)+1;}
      for(const item of world.sculptures||[]){
        const obj=namedObjects.get(item.id),site=obj?.userData.site,model=obj?.userData.model;if(!site||!obj.userData.ready)continue;
        const size={y:obj.userData.modelHeight};
        (heightRanges[site.kind]??=[]).push(Number(size.y.toFixed(2)));
        footprints[item.id]={height:+size.y.toFixed(2),reshape:+obj.userData.reshape.toFixed(2),offset:site.offset,side:site.side,kind:site.kind};
        const modes=new Set();
        model.traverse(m=>{if(!m.isMesh)return;
          for(const mat of Array.isArray(m.material)?m.material:[m.material]){
            if(mat.map?.isTexture){modes.add("textured");if(m.userData.detail && !m.userData.detail.far.attributes.uv)material.farMissingUV++;}
            else modes.add(mat.vertexColors?"vertexColor":"plain");
          }
        });
        for(const mode of modes)material[mode]++;
      }
      for(const g of pedestals.values()){if(g.userData.ready && g.userData.model){let resinOnly=true;g.userData.model.traverse(m=>{if(m.isMesh&&m.material!==resin)resinOnly=false;});if(resinOnly)material.dailyResin++;}}
      const homes=reservedSites.filter(s=>s.kind==="home");
      const pavedClearance=Math.min(...(world.sculptures||[]).map(item=>{
        const group=namedObjects.get(item.id);
        return group?.userData.ready?pavementGap(group.position.x,group.position.z)-group.userData.plinth.scale.x/2:Infinity;
      }));
      const houses=Object.fromEntries([...new Set([...housesOnIsland.values()].map(h=>h.style))].map(style=>[style,[...housesOnIsland.values()].filter(h=>h.style===style).length]));
      return {counts,material,footprints,heightRanges,pavedClearance,houses,houseModels:Object.fromEntries(householdModels),residents:[...housesOnIsland.values()].reduce((sum,h)=>sum+h.people.length,0),plazas:terraces.length,stageLamps:terraces.length*2,
        minimumHouseSetback:Math.min(...homes.map(s=>pathDistance(s.pos.x,s.pos.z))),
        accessiblePeople:world.people.filter(p=>namedObjects.get(p.id)?.userData.pick?.id===p.card_id).length,
        accessibleMoments:world.moments.filter((p,i)=>!!namedObjects.get("moment-"+i)?.userData.pick).length};
    };
    window.__worldPlinthConflicts=()=>window.__worldPlinthAudit().conflicts;
    window.__worldStoneRim=id=>{
      const g=namedObjects.get(id),pad=g?.userData.plinth;if(!pad)return null;
      const top=g.position.y+pad.position.y+pad.scale.y,analytic=[],actual=[],down=new THREE.Vector3(0,-1,0);
      for(let i=0;i<16;i++){
        const a=i*Math.PI/8,x=g.position.x+pad.scale.x*.49*Math.cos(a),z=g.position.z+pad.scale.x*.49*Math.sin(a);
        const surface=new THREE.Raycaster(new THREE.Vector3(x,20,z),down).intersectObjects(walkSurfaces)[0]?.point.y;
        analytic.push(top-finishedSurface(x,z));actual.push(top-surface);
      }
      return {height:g.userData.modelHeight,analytic:[Math.min(...analytic),Math.max(...analytic)],terrain:[Math.min(...actual),Math.max(...actual)]};
    };
  }
  const samples=[];
  let previousView;
  let elapsed=0,frames=0,lastSample=0,fps=null,lastLevel=0,slowSamples=0;
  renderWorld=now=>{
    const delta=clock.getDelta(),dt=Math.min(delta,.1);
    frames++;elapsed+=dt;
    if(now-lastSample>=1500){
      const gap=now-lastSample;
      fps=frames*1000/gap;
      if(measure) {
        const view=document.querySelector(".views [aria-pressed=true]")?.dataset.view;
        const foreground=document.visibilityState==="visible";
        if(!foreground || tween || gap>2500 || previousView!==view) samples.length=0;
        else {samples.push({frames,gap});if(samples.length>4)samples.shift();}
        previousView=view;
        const measuredFrames=samples.reduce((sum,sample)=>sum+sample.frames,0);
        const measuredTime=samples.reduce((sum,sample)=>sum+sample.gap,0);
        renderer.domElement.dataset.renderSample=JSON.stringify({
          view,frames,milliseconds:Math.round(gap),fps:Number(fps.toFixed(1)),draws:renderer.info.render.calls,
          triangles:renderer.info.render.triangles,pixelRatio:renderer.getPixelRatio(),width:innerWidth,height:innerHeight,
          sculptures:namedSculptures(),foreground,samples:samples.length,measuredFrames,millisecondsTotal:Math.round(measuredTime),
          meanFps:measuredTime?Number((1000*measuredFrames/measuredTime).toFixed(1)):null,
        });
      }
      frames=0;lastSample=now;
      if(document.visibilityState==="visible" && gap<2200 && fps<49)slowSamples++;else slowSamples=0;
      if(slowSamples>=2 && renderer.getPixelRatio()>1){
        renderer.setPixelRatio(Math.max(1,renderer.getPixelRatio()-.25));slowSamples=0;
      }
    }
    updateCamera(now,dt);
    if(mode==="orbit")controls.update();
    lanternGlow.uniforms.time.value=elapsed;
    ocean.update(elapsed);
    for(const b of boats){const p=b.obj.position,tl=ocean.tilt(p.x,p.z);p.y=ocean.height(p.x,p.z)+.02;b.obj.rotation.x=tl.x*.8;b.obj.rotation.z=tl.z*.8;}
    const f=1+.08*Math.sin(elapsed*9.1)+.05*Math.sin(elapsed*13.7);flame.scale.set(1,2.1*f,1);flameLight.intensity=26*f;flameGlow.scale.setScalar(3.4*f);
    for(let i=flashes.length-1;i>=0;i--){
      const e=flashes[i],t=(now-e.start)/2400;
      if(t>1){e.group.remove(e.light);e.light.material.dispose();flashes.splice(i,1);}
      else e.light.material.opacity=(1-t)*(.65+.35*Math.cos(t*11));
    }
    if(now-lastLevel>180){
      refreshDetails();
      lastLevel=now;
    }
    renderer.render(scene,camera);if(layoutTags(now))labels.render(scene,camera);
  };
  renderer.setAnimationLoop(managingPeople||workbench.active()?null:renderWorld);
  window.__worldStats=()=>({...renderer.info.render,geometries:renderer.info.memory.geometries,fps,mode,camera:camera.position.toArray(),heading:camera.quaternion.toArray(),paused:managingPeople||workbench.active(),rings:galleryRings,pedestals:pedestals.size,models:[...pedestals.values()].filter(g=>g.userData.ready).length,sculptures:namedSculptures(),expectedSculptures:world.sculptures?.length||0});
}
main().catch((err) => {
  console.error(err);
  if(new URLSearchParams(location.search).has("measure"))stage.dataset.loadError=String(err.message);
  document.getElementById("loading").textContent = "世界没能加载：先运行 tools/build_world_data.py，再刷新";
});
