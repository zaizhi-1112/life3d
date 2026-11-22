// 代码生成的树和小船，替换原来棱角很硬的多面体模型。
// 树：几团柔和起伏的树冠，下暗上亮的渐变；船：有弧线的木船体、内侧木色、坐板、桅杆、帆和船灯。
// 输出和 world.js 的 assembleProp 同一种结构：顶点色网格（材质名 paint），可发光的船灯（材质名 glow）。
import * as THREE from "three";
import { mergeGeometries, mergeVertices } from "three/addons/utils/BufferGeometryUtils.js";

function rng(seed) { let s = (seed * 9301 + 49297) % 233280 || 1; return () => (s = (s * 16807) % 2147483647) / 2147483647; }
const tmp = new THREE.Color();

function paint(geometry, colorAt) {
  const pos = geometry.attributes.position, colors = new Float32Array(pos.count * 3), v = new THREE.Vector3();
  for (let i = 0; i < pos.count; i++) { v.fromBufferAttribute(pos, i); colorAt(v, tmp); tmp.toArray(colors, i * 3); }
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  return geometry;
}
function clean(geometry) {
  const g = geometry.index ? geometry : geometry;
  for (const key of Object.keys(g.attributes)) if (!["position", "normal", "color"].includes(key)) g.deleteAttribute(key);
  return g;
}
function lumpy(radius, sx, sy, sz, seed, detail = 2) {
  const base = new THREE.IcosahedronGeometry(radius, detail); base.deleteAttribute("normal"); base.deleteAttribute("uv");
  const g = mergeVertices(base), p = g.attributes.position, v = new THREE.Vector3();  // 共享顶点，法线才能平滑
  const r = rng(seed), a = r() * 6, b = r() * 6, c = r() * 6;
  for (let i = 0; i < p.count; i++) {
    v.fromBufferAttribute(p, i).normalize();
    const n = 1 + 0.12 * Math.sin(v.x * 3.1 + a) * Math.cos(v.y * 2.7 + b) + 0.08 * Math.sin(v.z * 4.3 + c + v.x * 2);
    v.multiplyScalar(radius * n); v.x *= sx; v.y *= sy; v.z *= sz;
    p.setXYZ(i, v.x, v.y, v.z);
  }
  g.computeVertexNormals();
  return g;
}

const PALETTES = {
  tree_round: { dark: "#2a4226", mid: "#4f7638", light: "#a6c464", bark: "#5e4030" },
  tree_round_b: { dark: "#3a5530", mid: "#7f9e48", light: "#d6dc86", bark: "#d9cfbf" },
  tree_autumn: { dark: "#6e2c16", mid: "#c25a26", light: "#f2b24e", bark: "#4f382b" },
  tree_pine: { dark: "#24403a", mid: "#3f6650", light: "#7fa27a", bark: "#5a3f30" },
};

function trunk(height, base, top, seed, bark) {
  const r = rng(seed + 7), parts = [];
  const t = new THREE.CylinderGeometry(top, base, height, 9, 4); t.translate(0, height / 2, 0);
  const p = t.attributes.position;
  for (let i = 0; i < p.count; i++) { const y = p.getY(i) / height; p.setX(i, p.getX(i) + Math.sin(y * 2.4) * 0.06 * height * 0.2); }
  t.computeVertexNormals(); parts.push(t);
  for (let k = 0; k < 3; k++) {
    const len = height * (0.32 + r() * 0.18), br = new THREE.CylinderGeometry(top * 0.45, top * 0.8, len, 6);
    br.translate(0, len / 2, 0); br.rotateZ((r() - 0.5) * 1.3); br.rotateY(r() * 6.28); br.translate(0, height * (0.62 + r() * 0.25), 0);
    parts.push(br);
  }
  const g = mergeGeometries(parts.map(x => x.toNonIndexed()));
  const dark = new THREE.Color(bark).multiplyScalar(0.65), light = new THREE.Color(bark);
  return paint(clean(g), (v, c) => c.copy(dark).lerp(light, Math.min(1, v.y / height)));
}

// 叶片贴图：一小簇尖叶，白色带透明边，靠顶点色上色
let leafTexture = null;
function leaves() {
  if (leafTexture) return leafTexture;
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const x = c.getContext("2d"), r = rng(5);
  for (let i = 0; i < 9; i++) {
    const cx = 64 + (r() - 0.5) * 70, cy = 64 + (r() - 0.5) * 70, a = r() * Math.PI * 2, len = 22 + r() * 14, w = 9 + r() * 5;
    x.save(); x.translate(cx, cy); x.rotate(a);
    const g = x.createLinearGradient(-len, 0, len, 0); g.addColorStop(0, "#d9d9d9"); g.addColorStop(0.5, "#ffffff"); g.addColorStop(1, "#cfcfcf");
    x.fillStyle = g; x.beginPath(); x.moveTo(-len, 0); x.quadraticCurveTo(0, -w, len, 0); x.quadraticCurveTo(0, w, -len, 0); x.fill();
    x.strokeStyle = "rgba(150,150,150,.55)"; x.lineWidth = 1.2; x.beginPath(); x.moveTo(-len * 0.9, 0); x.lineTo(len * 0.9, 0); x.stroke();
    x.restore();
  }
  leafTexture = new THREE.CanvasTexture(c); leafTexture.colorSpace = THREE.SRGBColorSpace; leafTexture.anisotropy = 4;
  return leafTexture;
}

// 阔叶树：几团叶簇，每团由许多叶片卡组成，法线朝外像一个球，所以光影柔和、轮廓却是一片片叶子
function broadleaf(kind, seed, { height = 1.7, spread = 1.0, tall = 1.0, clumps = 4 } = {}) {
  const pal = PALETTES[kind], r = rng(seed);
  const dark = new THREE.Color(pal.dark), mid = new THREE.Color(pal.mid), light = new THREE.Color(pal.light);
  const centers = [];
  for (let i = 0; i < clumps; i++) {
    const a = (i / clumps) * Math.PI * 2 + r() * 0.8, ring = i === 0 ? 0 : 0.55 * spread;
    centers.push({ c: new THREE.Vector3(Math.cos(a) * ring, height + 0.75 * tall + (i === 0 ? 0.35 * tall : (r() - 0.4) * 0.45 * tall), Math.sin(a) * ring),
      rad: (i === 0 ? 0.95 : 0.72 + r() * 0.2) * spread });
  }
  const top = centers[0].c.y + centers[0].rad * tall, bottom = height + 0.1;
  const cards = [], cores = [];
  const pos = [], nrm = [], col = [], uv = [], idx = [];
  const q = new THREE.Quaternion(), e = new THREE.Euler(), v = new THREE.Vector3(), n = new THREE.Vector3();
  const shade = (p, out) => {
    const h = THREE.MathUtils.clamp((p.y - bottom) / (top - bottom), 0, 1);
    const sun = THREE.MathUtils.clamp(h * 0.7 + out * 0.45 + (-p.x - p.z) * 0.06, 0, 1);
    return tmp.copy(dark).lerp(mid, Math.min(1, sun * 1.5)).lerp(light, Math.max(0, sun - 0.6) * 1.6);
  };
  let k = 0;
  for (const { c, rad } of centers) {
    const count = Math.round(70 * rad * rad + 20);
    for (let i = 0; i < count; i++) {
      // 卡片中心落在椭球表面附近，外层多、里层少
      v.set(r() * 2 - 1, r() * 2 - 1, r() * 2 - 1).normalize().multiplyScalar(rad * (0.7 + r() * 0.35));
      v.y *= 0.85 * tall;
      const center = v.clone().add(c), size = (0.34 + r() * 0.16) * spread;
      q.setFromEuler(e.set(r() * 6.28, r() * 6.28, r() * 6.28));
      const hue = (r() - 0.5) * 0.04, light2 = (r() - 0.5) * 0.06;
      for (const [cx, cy, u, w] of [[-1, -1, 0, 0], [1, -1, 1, 0], [1, 1, 1, 1], [-1, 1, 0, 1]]) {
        const p = new THREE.Vector3(cx * size / 2, cy * size / 2, 0).applyQuaternion(q).add(center);
        pos.push(p.x, p.y, p.z);
        n.copy(p).sub(c).normalize(); n.y = n.y * 0.8 + 0.2; n.normalize();
        nrm.push(n.x, n.y, n.z);
        shade(p, Math.min(1, p.clone().sub(c).length() / rad)).offsetHSL(hue, 0, light2).toArray(col, col.length);
        uv.push(u, w);
      }
      idx.push(k, k + 1, k + 2, k, k + 2, k + 3); k += 4;
    }
    const core = lumpy(rad * 0.55, 1, 0.8 * tall, 1, seed + k, 1); core.translate(c.x, c.y, c.z);
    paint(core, (p, cc) => cc.copy(dark).lerp(mid, THREE.MathUtils.clamp((p.y - bottom) / (top - bottom), 0, 1) * 0.35));
    core.setAttribute("uv", new THREE.Float32BufferAttribute(new Float32Array(core.attributes.position.count * 2).fill(0.5), 2));
    cores.push(core.toNonIndexed());
  }
  const leavesGeo = new THREE.BufferGeometry();
  leavesGeo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  leavesGeo.setAttribute("normal", new THREE.Float32BufferAttribute(nrm, 3));
  leavesGeo.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  leavesGeo.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  leavesGeo.setIndex(idx);
  cards.push(leavesGeo.toNonIndexed());
  const crown = mergeGeometries([...cards, ...cores]);
  const bark = trunk(height + 0.55 * tall, 0.2, 0.09, seed, pal.bark);
  return { crown, bark };
}

// 松树：一层层下垂的锥形，边缘有起伏，尖上颜色浅
function pine(seed) {
  const pal = PALETTES.tree_pine, r = rng(seed), tiers = [];
  const levels = 5, base = 1.0;
  for (let i = 0; i < levels; i++) {
    const k = i / (levels - 1), rad = 1.25 * (1 - k * 0.72), h = 1.15 - k * 0.35;
    const g = new THREE.ConeGeometry(rad, h, 14, 2, false);
    const p = g.attributes.position;
    for (let j = 0; j < p.count; j++) {
      const x = p.getX(j), z = p.getZ(j), y = p.getY(j), a = Math.atan2(z, x);
      if (y < -h / 2 + 0.01) { const wob = 1 + 0.1 * Math.sin(a * 7 + i * 2 + seed); p.setXYZ(j, x * wob, y - 0.08 * Math.sin(a * 5 + i), z * wob); }
    }
    g.computeVertexNormals();
    g.translate(0, base + 0.6 + i * 0.62 + h / 2, 0); g.rotateY(r() * 6.28);
    tiers.push(g.toNonIndexed());
  }
  const crown = mergeGeometries(tiers);
  const dark = new THREE.Color(pal.dark), mid = new THREE.Color(pal.mid), light = new THREE.Color(pal.light);
  paint(clean(crown), (v, c) => {
    const out = Math.min(1, Math.hypot(v.x, v.z) / 1.2), h = THREE.MathUtils.clamp((v.y - 1.4) / 3.6, 0, 1);
    c.copy(dark).lerp(mid, out * 0.8 + h * 0.4).lerp(light, Math.max(0, h - 0.6) * 1.5 + Math.max(0, out - 0.85) * 1.2);
  });
  return [trunk(base + 0.9, 0.16, 0.08, seed, pal.bark), crown];
}

const leafMaterial = () => {
  const m = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.88, map: leaves(), alphaTest: 0.45, side: THREE.DoubleSide });
  // 叶片两面都按「朝外」打光：不让背面翻转法线，否则一半叶子会发黑
  const begin = THREE.ShaderChunk.normal_fragment_begin.replace(/normal\s*=\s*normal\s*\*\s*faceDirection\s*;|normal\s*\*=\s*faceDirection\s*;/g, "");
  m.onBeforeCompile = shader => { shader.fragmentShader = shader.fragmentShader.replace("#include <normal_fragment_begin>", begin); };
  m.customProgramCacheKey = () => "leaf-cards";
  m.name = "paint"; return m;
};
const solidMaterial = () => { const m = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.9 }); m.name = "paint"; return m; };

export function buildTree(kind, seed = 1) {
  const group = new THREE.Group();
  const add = (geometry, material) => { const mesh = new THREE.Mesh(geometry, material); mesh.castShadow = mesh.receiveShadow = true; group.add(mesh); };
  if (kind === "tree_pine") {
    const [bark, crown] = pine(seed);
    add(mergeGeometries([bark, crown.index ? crown.toNonIndexed() : crown]), solidMaterial());
    return group;
  }
  const shape = kind === "tree_round_b" ? { height: 2.0, spread: 0.85, tall: 1.45, clumps: 4 }
    : kind === "tree_autumn" ? { height: 1.5, spread: 1.15, tall: 1.0, clumps: 5 }
    : { height: 1.55, spread: 1.2, tall: 1.05, clumps: 5 };
  const { crown, bark } = broadleaf(kind, seed, shape);
  add(bark, solidMaterial());
  add(crown, leafMaterial());
  return group;
}

// ---------- 小船 ----------
function hullGeometry(L, W, D) {
  // 沿船长取截面：船头尖、船尾略方，截面是 U 形
  const segs = 24, around = 12, verts = [], index = [];
  for (let i = 0; i <= segs; i++) {
    const t = i / segs, x = -L / 2 + t * L;
    const bow = Math.pow(Math.sin(Math.PI * Math.min(1, t * 0.92 + 0.04)), 0.55);
    const half = W / 2 * bow * (t < 0.15 ? 0.75 + t * 1.6 : 1);
    const depth = D * (0.55 + 0.45 * bow), sheer = D * 0.35 * Math.pow(Math.abs(t - 0.5) * 2, 2.2);
    for (let j = 0; j <= around; j++) {
      const a = Math.PI * j / around;  // 0 → π：从左舷沿到右舷沿
      const y = sheer - depth * Math.sin(a), z = -half * Math.cos(a) * (0.85 + 0.15 * Math.sin(a));
      verts.push(x, y, z);
    }
  }
  for (let i = 0; i < segs; i++) for (let j = 0; j < around; j++) {
    const a = i * (around + 1) + j, b = a + around + 1;
    index.push(a, b, a + 1, b, b + 1, a + 1);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3)); g.setIndex(index); g.computeVertexNormals();
  return { geometry: g, segs, around };
}

export function buildBoat() {
  const group = new THREE.Group();
  const L = 1.95, W = 0.74, D = 0.32;
  const body = new THREE.Group(); body.position.y = 0.2; group.add(body);  // 吃水：水面在船舷下方
  const { geometry } = hullGeometry(L, W, D);
  const red = new THREE.Color("#9c4a36"), cream = new THREE.Color("#efe3c8"), blue = new THREE.Color("#4f6f8f");
  paint(geometry, (v, c) => { const y = v.y; if (y > 0.05) c.copy(blue); else if (y > -0.02) c.copy(cream); else if (y > -0.18) c.copy(cream).lerp(red, 0.15); else c.copy(red); });
  const outside = new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.FrontSide }); outside.name = "paint";
  const inside = new THREE.MeshLambertMaterial({ color: "#b98a5e", side: THREE.BackSide }); inside.name = "wood";
  const shell = new THREE.Mesh(geometry, outside), inner = new THREE.Mesh(geometry, inside);
  shell.castShadow = true; body.add(shell, inner);
  // 船舷：沿两侧边缘的木条
  const wood = new THREE.MeshLambertMaterial({ color: "#6f4a33" }); wood.name = "trim";
  const pos = geometry.attributes.position, per = 13;
  for (const j of [0, 12]) {
    const pts = []; for (let i = 0; i <= 24; i++) { const k = i * per + j; pts.push(new THREE.Vector3(pos.getX(k), pos.getY(k) + 0.015, pos.getZ(k))); }
    const rail = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 40, 0.03, 5), wood); rail.castShadow = true; body.add(rail);
  }
  for (const x of [-0.38, 0.3]) { const seat = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.04, W * 0.86), wood); seat.position.set(x, -0.1, 0); body.add(seat); }
  // 桅杆、帆、船灯
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.035, 1.1, 8), wood); mast.position.set(0.35, 0.6, 0); group.add(mast);
  const sailShape = new THREE.Shape(); sailShape.moveTo(0, 0); sailShape.quadraticCurveTo(-0.3, 0.4, -0.04, 0.82); sailShape.lineTo(-0.78, 0.04); sailShape.lineTo(0, 0);
  const sailGeo = new THREE.ShapeGeometry(sailShape, 12), sp = sailGeo.attributes.position;
  for (let i = 0; i < sp.count; i++) sp.setZ(i, Math.sin(Math.min(1, -sp.getX(i) / 0.78) * Math.PI) * 0.1);
  sailGeo.computeVertexNormals();
  const canvas = new THREE.MeshLambertMaterial({ color: "#f3e7cf", side: THREE.DoubleSide }); canvas.name = "sail";
  const sail = new THREE.Mesh(sailGeo, canvas); sail.position.set(0.32, 0.26, 0.02); sail.castShadow = true; group.add(sail);
  const boom = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.85, 6), wood); boom.rotation.z = Math.PI / 2; boom.position.set(-0.07, 0.28, 0.02); group.add(boom);
  const glow = new THREE.MeshStandardMaterial({ color: "#ffd9a0", emissive: "#ffb85c", emissiveIntensity: 2.2 }); glow.name = "glow";
  const lamp = new THREE.Mesh(new THREE.BoxGeometry(0.09, 0.12, 0.09), glow); lamp.position.set(0.35, 1.08, 0); group.add(lamp);
  const cap = new THREE.Mesh(new THREE.ConeGeometry(0.08, 0.06, 4), wood); cap.position.set(0.35, 1.17, 0); cap.rotation.y = Math.PI / 4; group.add(cap);
  // 船里随手放的一对桨
  for (const s of [-1, 1]) { const oar = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 1.1, 5), wood); oar.rotation.z = Math.PI / 2 - 0.06; oar.rotation.y = s * 0.12; oar.position.set(-0.05, -0.04, s * 0.18); body.add(oar); }
  const holder = new THREE.Group(); holder.add(group);
  return holder;
}

// 把新模型缩放到和旧模型差不多的大小，保持摆放和点选范围不变
export function fitLike(model, reference, axis = "y") {
  const a = new THREE.Box3().setFromObject(reference).getSize(new THREE.Vector3());
  const b = new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3());
  const k = axis === "length" ? Math.max(a.x, a.z) / Math.max(b.x, b.z) : a.y / b.y;
  if (Number.isFinite(k) && k > 0) model.scale.setScalar(k);
  return model;
}
