import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

// ---------- 岛的形状：外圈低、中央是展台平台 ----------
const ISLAND = 60, PLATEAU = 9, TOP = 6;
const height = (r) => r <= PLATEAU ? TOP : r >= ISLAND ? 0 : TOP * Math.pow(1 - (r - PLATEAU) / (ISLAND - PLATEAU), 1.35);
const PATH_OUTER = 53, PATH_INNER = 11.5, TURNS = 2.2, PATH_START = Math.PI * 0.85;

const PALETTE = {
  cool: new THREE.Color("#86a4ff"), warm: new THREE.Color("#ffb35c"), none: new THREE.Color("#6b6478"),
  stone: "#d9c7a7", ground: "#bba98a", gate: "#a6553f", resin: "#efe6d6",
  roofs: ["#b8775a", "#7f9a7c", "#9c88b5", "#c9a161", "#6f8ca6", "#b0675f"],
};

const stage = document.getElementById("stage");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
stage.appendChild(renderer.domElement);

const labels = new CSS2DRenderer();
labels.setSize(innerWidth, innerHeight);
labels.domElement.className = "label-layer";
document.body.appendChild(labels.domElement);

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2("#76607f", 0.0052);
const camera = new THREE.PerspectiveCamera(42, innerWidth / innerHeight, 0.1, 1200);
camera.position.set(0, 95, 128);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 3, 0);
controls.enableDamping = true;
controls.maxPolarAngle = Math.PI * 0.47;
controls.minDistance = 4;
controls.maxDistance = 220;

// ---------- 天空、海、星、光 ----------
function sky() {
  const material = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: { sun: { value: new THREE.Vector3(-0.72, 0.1, -0.68).normalize() } },
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
    const u = Math.random() * Math.PI * 2, v = 0.25 + Math.random() * 0.75;
    const r = 560, cy = Math.sqrt(1 - v * v);
    points.push(Math.cos(u) * cy * r, v * r, Math.sin(u) * cy * r);
  }
  stars.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
  scene.add(new THREE.Points(stars, new THREE.PointsMaterial({ color: "#fff4e6", size: 1.4, sizeAttenuation: false, transparent: true, opacity: 0.75, fog: false })));

  const sea = new THREE.Mesh(new THREE.CircleGeometry(900, 64),
    new THREE.MeshStandardMaterial({ color: "#2c2c4c", roughness: 0.22, metalness: 0.15 }));
  sea.rotation.x = -Math.PI / 2;
  sea.position.y = -0.35;
  scene.add(sea);

  scene.add(new THREE.HemisphereLight("#9a95d6", "#4a3a35", 0.75));
  const sunLight = new THREE.DirectionalLight("#ffbf94", 2.1);
  sunLight.position.set(-70, 34, -62);
  sunLight.castShadow = true;
  sunLight.shadow.mapSize.set(2048, 2048);
  Object.assign(sunLight.shadow.camera, { left: -70, right: 70, top: 70, bottom: -70, near: 1, far: 260 });
  sunLight.shadow.bias = -0.0004;
  scene.add(sunLight);
}

function island() {
  const profile = [];
  for (let i = 0; i <= 80; i++) {
    const r = (i / 80) * ISLAND;
    profile.push(new THREE.Vector2(r, height(r)));
  }
  profile.push(new THREE.Vector2(ISLAND + 2.5, -2.5));
  const geometry = new THREE.LatheGeometry(profile.reverse(), 160);
  const p = geometry.attributes.position;
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i), z = p.getZ(i), r = Math.hypot(x, z);
    if (r > PLATEAU + 1.5 && r < ISLAND - 1) {
      const n = Math.sin(x * 0.21) * Math.cos(z * 0.17) * 0.32 + Math.sin(x * 0.07 + z * 0.09) * 0.4;
      p.setY(i, p.getY(i) + n * Math.min(1, (r - PLATEAU - 1.5) / 6));
    }
  }
  geometry.computeVertexNormals();
  const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: PALETTE.ground, roughness: 0.96 }));
  mesh.receiveShadow = true;
  scene.add(mesh);

  // 零散的低矮灌木，让坡面不空
  const bush = new THREE.IcosahedronGeometry(1, 0);
  const bushMat = new THREE.MeshStandardMaterial({ color: "#7b8a68", roughness: 1, flatShading: true });
  const bushes = new THREE.InstancedMesh(bush, bushMat, 260);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3();
  let seed = 7;
  const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < 260; i++) {
    const r = PLATEAU + 3 + rand() * (ISLAND - PLATEAU - 6), a = rand() * Math.PI * 2;
    const k = 0.35 + rand() * 0.8;
    s.set(k, k * (0.6 + rand() * 0.5), k);
    q.setFromEuler(new THREE.Euler(0, rand() * 6, 0));
    m.compose(new THREE.Vector3(Math.cos(a) * r, height(r) + k * 0.25, Math.sin(a) * r), q, s);
    bushes.setMatrixAt(i, m);
  }
  bushes.castShadow = true;
  scene.add(bushes);
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

function pathPoint(t) {
  const r = PATH_OUTER - (PATH_OUTER - PATH_INNER) * t;
  const a = PATH_START + t * TURNS * Math.PI * 2;
  return new THREE.Vector3(Math.cos(a) * r, height(r) + 0.06, Math.sin(a) * r);
}
function pathFrame(t) {
  const p = pathPoint(t), ahead = pathPoint(Math.min(1, t + 0.002)), back = pathPoint(Math.max(0, t - 0.002));
  const tangent = ahead.sub(back).normalize();
  const side = new THREE.Vector3().crossVectors(tangent, new THREE.Vector3(0, 1, 0)).normalize();
  // side 指向远离岛心的一侧
  if (side.dot(new THREE.Vector3(p.x, 0, p.z)) < 0) side.negate();
  return { p, tangent, side };
}

function path() {
  const steps = 900, width = 0.85, positions = [], index = [];
  for (let i = 0; i <= steps; i++) {
    const { p, side } = pathFrame(i / steps);
    for (const k of [-1, 1]) {
      const v = p.clone().addScaledVector(side, k * width);
      v.y = height(Math.hypot(v.x, v.z)) + 0.12;
      positions.push(v.x, v.y, v.z);
    }
    if (i < steps) { const a = i * 2; index.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
  }
  // 最后一段直通平台
  const end = pathPoint(1), dir = new THREE.Vector3(-end.x, 0, -end.z).normalize();
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(index);
  geometry.computeVertexNormals();
  const material = new THREE.MeshStandardMaterial({ color: PALETTE.stone, roughness: 0.9, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2 });
  const ribbon = new THREE.Mesh(geometry, material);
  ribbon.receiveShadow = true;
  scene.add(ribbon);
  const spur = new THREE.Mesh(new THREE.BoxGeometry(1.7, 0.1, PATH_INNER - PLATEAU + 1.2), material);
  const mid = end.clone().addScaledVector(dir, (PATH_INNER - PLATEAU) / 2 + 0.3);
  spur.position.set(mid.x, TOP + 0.02, mid.z);
  spur.lookAt(new THREE.Vector3(0, TOP + 0.02, 0));
  spur.receiveShadow = true;
  scene.add(spur);
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
const lanterns = [];

function lanternsFor(months, emotions) {
  const byMonth = new Map(emotions.map((e) => [e.month, e]));
  const peak = Math.max(...emotions.map((e) => e.pos + e.neg), 1);
  const postGeo = new THREE.CylinderGeometry(0.05, 0.07, 1.7, 6);
  const postMat = new THREE.MeshStandardMaterial({ color: "#3b302c", roughness: 0.8 });
  const headGeo = new THREE.SphereGeometry(0.2, 16, 12);
  months.forEach((month, i) => {
    const t = i / (months.length - 1);
    const { p, side } = pathFrame(t);
    const e = byMonth.get(month);
    const total = e ? e.pos + e.neg : 0;
    const ratio = total ? e.pos / total : 0.5;
    const color = e ? PALETTE.cool.clone().lerp(PALETTE.warm, THREE.MathUtils.smoothstep(ratio, 0.3, 0.8)) : PALETTE.none;
    const group = new THREE.Group();
    const base = p.clone().addScaledVector(side, 1.45);
    base.y = height(Math.hypot(base.x, base.z));
    group.position.copy(base);
    const post = new THREE.Mesh(postGeo, postMat);
    post.position.y = 0.85;
    post.castShadow = true;
    const head = new THREE.Mesh(headGeo, new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: e ? 2.2 : 0.3 }));
    head.position.y = 1.8;
    const size = e ? 1.2 + 2.6 * Math.sqrt(total / peak) : 0.6;
    const halo = glow(color, size, e ? 0.85 : 0.25);
    halo.position.y = 1.8;
    group.add(post, head, halo);
    const text = e ? `这个月聊天里开心的片段 ${e.pos} 处，难受的 ${e.neg} 处。` : "这个月还没有整理到记录。";
    group.userData.pick = { kicker: "月灯", title: month.replace("-", " 年 ") + " 月", text, aside: e ? "灯越暖，这个月越偏开心；光越大，这个月的事越多。" : "第二批记录整理完后会补上。" };
    group.userData.phase = i * 0.7;
    lanterns.push({ halo, head, base: size, phase: i * 0.7 });
    pickables.push(group);
    scene.add(group);
  });
}

function gates(months, eras) {
  const post = new THREE.BoxGeometry(0.28, 2.9, 0.28);
  const beam = new THREE.BoxGeometry(3.6, 0.26, 0.36);
  const mat = new THREE.MeshStandardMaterial({ color: PALETTE.gate, roughness: 0.7 });
  const out = [];
  eras.forEach((era) => {
    const i = Math.max(0, months.indexOf(era.start) < 0 ? (era.start < months[0] ? 0 : months.length - 1) : months.indexOf(era.start));
    const t = Math.min(1, (i + 0.35) / (months.length - 1));
    const { p, side, tangent } = pathFrame(t);
    const group = new THREE.Group();
    group.position.copy(p);
    group.lookAt(p.clone().add(tangent));
    for (const k of [-1, 1]) {
      const m = new THREE.Mesh(post, mat);
      m.position.set(k * 1.45, 1.45, 0);
      m.castShadow = true;
      group.add(m);
    }
    const top = new THREE.Mesh(beam, mat);
    top.position.y = 2.85;
    top.castShadow = true;
    group.add(top);
    const tag = document.createElement("div");
    tag.className = "tag era-tag";
    tag.innerHTML = `<em>${era.period.split("–")[0].trim()}</em>${era.title}`;
    const label = new CSS2DObject(tag);
    label.position.y = 3.6;
    group.add(label);
    group.userData.pick = { kicker: era.period, title: era.title, text: era.text, aside: "人生时间线 · 来自聊天记录整理" };
    pickables.push(group);
    scene.add(group);
    out.push({ t, era });
  });
  return out;
}

const houses = [];
function homes(months, people) {
  const used = new Map();
  const maxW = Math.max(...people.map((p) => p.weight), 1);
  people.forEach((person, n) => {
    let i = months.indexOf(person.from);
    if (i < 0) i = person.from < months[0] ? 0 : months.length - 1;
    const slot = used.get(i) || 0;
    used.set(i, slot + 1);
    const t = Math.min(0.985, (i + slot * 0.55 + 0.2) / (months.length - 1));
    const { p, side, tangent } = pathFrame(t);
    const pos = p.clone().addScaledVector(side, -(3.2 + (slot % 2) * 1.6));
    pos.y = height(Math.hypot(pos.x, pos.z));
    const k = 0.75 + 0.7 * Math.sqrt(person.weight / maxW);
    const group = new THREE.Group();
    group.position.copy(pos);
    group.lookAt(p.x, pos.y, p.z);
    const wall = new THREE.Mesh(new THREE.BoxGeometry(1.2 * k, 0.95 * k, 1.0 * k), new THREE.MeshStandardMaterial({ color: "#e8dcc6", roughness: 0.9 }));
    wall.position.y = 0.475 * k;
    const roof = new THREE.Mesh(new THREE.ConeGeometry(0.98 * k, 0.75 * k, 4), new THREE.MeshStandardMaterial({ color: PALETTE.roofs[n % PALETTE.roofs.length], roughness: 0.8, flatShading: true }));
    roof.rotation.y = Math.PI / 4;
    roof.position.y = 0.95 * k + 0.37 * k;
    const window = new THREE.Mesh(new THREE.PlaneGeometry(0.3 * k, 0.3 * k), new THREE.MeshStandardMaterial({ color: "#ffd08a", emissive: "#ffb85e", emissiveIntensity: 1.8 }));
    window.position.set(0, 0.52 * k, 0.501 * k);
    for (const m of [wall, roof]) { m.castShadow = true; m.receiveShadow = true; }
    group.add(wall, roof, window);
    const tag = document.createElement("div");
    tag.className = "tag person";
    tag.textContent = person.name.replace(/（.*?）/g, "");
    const label = new CSS2DObject(tag);
    label.position.y = 1.9 * k;
    group.add(label);
    group.userData.pick = { kicker: person.from + (person.to ? " — " + person.to : ""), title: person.name, text: person.line || "关系小传还在写。", aside: "路边亮着窗的小屋，是聊得最多的 30 个人。" };
    houses.push({ group, tag });
    pickables.push(group);
    scene.add(group);
  });
}

// ---------- 中央展台 ----------
const resin = new THREE.MeshStandardMaterial({ color: PALETTE.resin, roughness: 0.55, metalness: 0 });
let flameLight, flame, flameGlow;

function hall(exhibits) {
  const floor = new THREE.Mesh(new THREE.CylinderGeometry(8.4, 8.7, 0.3, 72), new THREE.MeshStandardMaterial({ color: "#e4d6bd", roughness: 0.85 }));
  floor.position.y = TOP + 0.15;
  floor.receiveShadow = true;
  scene.add(floor);
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
  candle.userData.pick = { kicker: "2026-11", title: "二十三", text: "从 2022 年夏天开始的路，走到这里。外圈每盏灯是一个月，路边的小屋是一路上遇见的人，这一圈展台放每天打印出来的小东西。", aside: "" };
  pickables.push(candle);

  const count = Math.max(8, exhibits.length + 2);
  const pedestalGeo = new THREE.CylinderGeometry(0.58, 0.66, 1.05, 40);
  const pedestalMat = new THREE.MeshStandardMaterial({ color: "#d9c9ad", roughness: 0.75 });
  for (let i = 0; i < count; i++) {
    const a = Math.PI / 2 + ((i + 0.5) / count) * Math.PI * 2;
    const x = Math.cos(a) * 5.3, z = Math.sin(a) * 5.3;
    const group = new THREE.Group();
    group.position.set(x, TOP + 0.3, z);
    const pedestal = new THREE.Mesh(pedestalGeo, pedestalMat);
    pedestal.position.y = 0.525;
    pedestal.castShadow = pedestal.receiveShadow = true;
    group.add(pedestal);
    const item = exhibits[i];
    if (item && item.model) {
      loadExhibit(item, group);
    } else {
      const halo = new THREE.Mesh(new THREE.TorusGeometry(0.34, 0.025, 8, 48), new THREE.MeshStandardMaterial({ color: "#ffd9a0", emissive: "#ffb766", emissiveIntensity: 1.4 }));
      halo.rotation.x = Math.PI / 2;
      halo.position.y = 1.08;
      group.add(halo);
    }
    const tag = document.createElement("div");
    tag.className = "tag";
    tag.textContent = item ? item.title : "留给明天";
    const label = new CSS2DObject(tag);
    label.position.y = item && item.model ? 2.75 : 1.45;
    group.add(label);
    group.userData.pick = item
      ? { kicker: [item.date || "样品", item.source === "aholo" ? "积分精雕" : "今日小物"].join(" · "), title: item.title, text: item.summary || "", aside: item.model ? item.reason || "" : "模型还没做好，做好后会自己出现在这里。" }
      : { kicker: "空展台", title: "留给明天", text: "之后每天打印的小物，会一件件摆到这里。", aside: "" };
    pickables.push(group);
    scene.add(group);
  }
}

function fit(object, group) {
  const box = new THREE.Box3().setFromObject(object);
  const size = box.getSize(new THREE.Vector3());
  const k = 1.45 / Math.max(size.y, size.x * 0.85, size.z * 0.85);
  object.scale.multiplyScalar(k);
  const fitted = new THREE.Box3().setFromObject(object);
  const center = fitted.getCenter(new THREE.Vector3());
  object.position.x -= center.x;
  object.position.z -= center.z;
  object.position.y += 1.05 - fitted.min.y;
  const holder = new THREE.Group();
  holder.add(object);
  holder.rotation.y = Math.atan2(group.position.x, group.position.z);
  group.add(holder);
}

function loadExhibit(item, group) {
  const url = `/models/${item.id}`;
  const done = (object) => {
    object.traverse((m) => { if (m.isMesh) { m.material = resin; m.castShadow = true; m.receiveShadow = true; } });
    fit(object, group);
  };
  if (item.format === "glb") {
    new GLTFLoader().load(url, (gltf) => done(gltf.scene), undefined, () => {});
  } else {
    new STLLoader().load(url, (geometry) => {
      geometry.computeVertexNormals();
      const mesh = new THREE.Mesh(geometry, resin);
      mesh.rotation.x = -Math.PI / 2; // 打印文件是 Z 朝上
      const wrap = new THREE.Group();
      wrap.add(mesh);
      done(wrap);
    }, undefined, () => {});
  }
}

// ---------- 镜头 ----------
const VIEWS = {
  overview: { pos: [0, 95, 128], target: [0, 3, 0] },
  hall: { pos: [0, TOP + 5.5, 15.5], target: [0, TOP + 1.6, 0] },
};
let tween = null, walk = null, eraMarks = [];
const eraBox = document.getElementById("era");

function flyTo(name) {
  walk = null;
  const v = VIEWS[name];
  tween = { from: camera.position.clone(), to: new THREE.Vector3(...v.pos), fromT: controls.target.clone(), toT: new THREE.Vector3(...v.target), start: performance.now(), dur: 1800 };
  setPressed(name);
}
function startWalk() {
  tween = null;
  walk = { start: performance.now(), dur: 52000, shown: -1 };
  controls.enabled = false;
  setPressed("walk");
}
function stopWalk() {
  if (!walk) return;
  walk = null;
  controls.enabled = true;
  eraBox.classList.remove("on");
  setPressed(null);
}
function setPressed(name) {
  document.querySelectorAll(".views button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === name)));
}
const ease = (x) => x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;

function updateCamera(now) {
  if (tween) {
    const k = ease(Math.min(1, (now - tween.start) / tween.dur));
    camera.position.lerpVectors(tween.from, tween.to, k);
    controls.target.lerpVectors(tween.fromT, tween.toT, k);
    if (k >= 1) tween = null;
  }
  if (walk) {
    const u = Math.min(1, (now - walk.start) / walk.dur);
    const t = u * 0.995;
    const { p, side, tangent } = pathFrame(t);
    const eye = p.clone().addScaledVector(tangent, -4.2).addScaledVector(side, 0.6);
    eye.y = Math.max(eye.y, height(Math.hypot(eye.x, eye.z))) + 2.4;
    const look = pathPoint(Math.min(1, t + 0.025));
    look.y += 1.2;
    camera.position.lerp(eye, 0.08);
    controls.target.lerp(look, 0.08);
    const current = eraMarks.filter((m) => m.t <= t + 0.01).pop();
    const idx = current ? eraMarks.indexOf(current) : -1;
    if (idx !== walk.shown && current) {
      walk.shown = idx;
      eraBox.innerHTML = `<small>${current.era.period}</small><strong>${current.era.title}</strong>`;
      eraBox.classList.add("on");
      clearTimeout(walk.hide);
      walk.hide = setTimeout(() => eraBox.classList.remove("on"), 4200);
    }
    if (u >= 1) { stopWalk(); flyTo("hall"); }
  }
}

// ---------- 点选 ----------
const card = document.getElementById("card");
const ray = new THREE.Raycaster(), pointer = new THREE.Vector2();
let down = null;
function pickAt(event) {
  pointer.set((event.clientX / innerWidth) * 2 - 1, -(event.clientY / innerHeight) * 2 + 1);
  ray.setFromCamera(pointer, camera);
  const hit = ray.intersectObjects(pickables, true)[0];
  let o = hit && hit.object;
  while (o && !o.userData.pick) o = o.parent;
  return o;
}
renderer.domElement.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; stopWalk(); tween = null; });
renderer.domElement.addEventListener("pointerup", (e) => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
  const o = pickAt(e);
  if (!o) { card.hidden = true; return; }
  const d = o.userData.pick;
  document.getElementById("card-kicker").textContent = d.kicker || "";
  document.getElementById("card-title").textContent = d.title || "";
  document.getElementById("card-text").textContent = d.text || "";
  document.getElementById("card-aside").textContent = d.aside || "";
  card.hidden = false;
});
let hovered = null;
renderer.domElement.addEventListener("pointermove", (e) => {
  const o = pickAt(e);
  hovered = o;
  renderer.domElement.style.cursor = o ? "pointer" : "";
});
card.querySelector(".close").addEventListener("click", () => { card.hidden = true; });
document.querySelectorAll(".views button").forEach((b) => b.addEventListener("click", () => {
  if (b.dataset.view === "walk") startWalk(); else { stopWalk(); flyTo(b.dataset.view); }
}));
addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
  labels.setSize(innerWidth, innerHeight);
});

// ---------- 启动 ----------
function thisMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

async function main() {
  const world = await fetch("/data/world.json").then((r) => r.json());
  const months = monthsBetween(world.start, thisMonth());
  sky();
  island();
  path();
  lanternsFor(months, world.emotions);
  eraMarks = gates(months, world.eras);
  homes(months, world.people);
  const exhibits = [...world.exhibits].sort((a, b) => (b.model ? 1 : 0) - (a.model ? 1 : 0));
  hall(exhibits);
  document.getElementById("loading").classList.add("done");
  const clock = new THREE.Clock();
  renderer.setAnimationLoop((now) => {
    const t = clock.getElapsedTime();
    updateCamera(now);
    controls.update();
    for (const l of lanterns) l.halo.scale.setScalar(l.base * (0.94 + 0.06 * Math.sin(t * 1.3 + l.phase)));
    const f = 1 + 0.08 * Math.sin(t * 9.1) + 0.05 * Math.sin(t * 13.7);
    flame.scale.set(1, 2.1 * f, 1);
    flameLight.intensity = 26 * f;
    flameGlow.scale.setScalar(3.4 * f);
    for (const h of houses) {
      const near = camera.position.distanceTo(h.group.position) < 16;
      h.tag.classList.toggle("show", near || hovered === h.group);
    }
    renderer.render(scene, camera);
    labels.render(scene, camera);
  });
}
main().catch(() => {
  document.getElementById("loading").textContent = "世界数据还没生成：先运行 tools/build_world_data.py";
});
