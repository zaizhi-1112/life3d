// 记忆宫殿：同一批资产（每日小物、打印出来的实物、世界精雕、家具摆设）摆进小屋或花园。
// 场景全部由代码生成；摆放只写本机 data/palace.json，规则见 AGENTS.md「记忆宫殿」。
// 平时只能看和点；打开「资产管理」才进入布置模式，可以拖动物件和家具。
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { workbenchPanel, readOnly } from "./island-panels.js";
import { FURNITURE, buildFurniture, kit, mat, resin } from "./palace-furniture.js";
import { createOcean } from "./ocean.js";
import { sound, soundToggle } from "./sound.js";

const $ = id => document.getElementById(id);
const WORKBENCH = "http://127.0.0.1:17868";
const DEG = Math.PI / 180;
const params = new URLSearchParams(location.search);
const EYE = 1.62;

// ---------- 渲染器 ----------
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: params.has("capture") });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
$("stage").append(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(40, innerWidth / innerHeight, 0.05, 2400);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.08; controls.screenSpacePanning = false;
addEventListener("resize", () => { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight); });

function gradientTexture(stops, { stars = 0, sun = null, sea = null, w = 512, h = 512 } = {}) {
  const canvas = document.createElement("canvas"); canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext("2d"), g = ctx.createLinearGradient(0, 0, 0, h);
  for (const [at, color] of stops) g.addColorStop(at, color);
  ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
  let seed = 7; const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < stars; i++) { ctx.fillStyle = `rgba(255,244,220,${0.25 + rand() * 0.6})`; ctx.fillRect(rand() * w, rand() * h * 0.55, 1.4, 1.4); }
  if (sun) {
    const s = ctx.createRadialGradient(sun.x * w, sun.y * h, 0, sun.x * w, sun.y * h, sun.r * w);
    s.addColorStop(0, sun.color); s.addColorStop(0.35, sun.color + "aa"); s.addColorStop(1, sun.color + "00");
    ctx.fillStyle = s; ctx.fillRect(0, 0, w, h);
  }
  if (sea) {
    const sg = ctx.createLinearGradient(0, sea.y * h, 0, h); sg.addColorStop(0, sea.top); sg.addColorStop(1, sea.bottom);
    ctx.fillStyle = sg; ctx.fillRect(0, sea.y * h, w, h);
    ctx.fillStyle = "rgba(255,210,150,.35)";
    for (let i = 0; i < 14; i++) ctx.fillRect(w * (0.42 + rand() * 0.2), sea.y * h + 4 + i * 5, w * (0.04 + rand() * 0.1), 1.5);
  }
  const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}
function nightTime() { const h = new Date().getHours(); return h >= 18 || h < 6; }

// 只朝里的一面墙：从外面看自动透明，俯瞰像娃娃屋，走进去又是完整的房间。
function innerWall(root, w, h, x, z, ry, color, holes = []) {
  const shape = new THREE.Shape([new THREE.Vector2(-w / 2, 0), new THREE.Vector2(w / 2, 0), new THREE.Vector2(w / 2, h), new THREE.Vector2(-w / 2, h)]);
  for (const [hx, hy, hw, hh] of holes) shape.holes.push(new THREE.Path([new THREE.Vector2(hx - hw / 2, hy), new THREE.Vector2(hx + hw / 2, hy), new THREE.Vector2(hx + hw / 2, hy + hh), new THREE.Vector2(hx - hw / 2, hy + hh)].reverse()));
  const mesh = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshStandardMaterial({ color, roughness: 0.92 }));
  mesh.position.set(x, 0, z); mesh.rotation.y = ry; mesh.receiveShadow = true; mesh.castShadow = true;
  root.add(mesh);
  return mesh;
}

// ---------- 场景一：小屋（18 × 13 米） ----------
const ROOM = { W: 18, D: 13, H: 3.8 };
function buildRoomShell(night) {
  const root = new THREE.Group(), floors = [], k = kit(root, floors);
  const { W, D, H } = ROOM, back = -D / 2, left = -W / 2;
  for (let i = 0; i < 26; i++) {
    const tone = ["#b4835c", "#a97955", "#bb8b63", "#a3734f"][i % 4];
    k.box(W, 0.12, D / 26 - 0.008, tone, 0, -0.06, back + (i + 0.5) * D / 26, { surface: true, shadow: false });
  }
  const windows = [[-1.4, 1.0, 2.8, 1.7], [4.6, 1.0, 2.8, 1.7]];
  innerWall(root, W, H, 0, back, 0, "#eadccb", windows);
  innerWall(root, D, H, left, 0, Math.PI / 2, "#e4d5c2", [[-1.0, 1.0, 2.4, 1.7]]);
  innerWall(root, D, H, -left, 0, -Math.PI / 2, "#e4d5c2", [[0, 0, 1.4, 2.4]]);
  innerWall(root, W, H, 0, -back, Math.PI, "#eadccb", [[0, 0, 1.6, 2.5]]);
  const ceiling = new THREE.Mesh(new THREE.PlaneGeometry(W, D), new THREE.MeshStandardMaterial({ color: "#efe4d4", roughness: 0.95 }));
  ceiling.rotation.x = Math.PI / 2; ceiling.position.y = H; root.add(ceiling);
  for (let i = -3; i <= 3; i++) {
    const beam = new THREE.Mesh(new THREE.PlaneGeometry(0.22, D), mat("#9a6b4a"));
    beam.rotation.x = Math.PI / 2; beam.position.set(i * 2.6, H - 0.01, 0); root.add(beam);
  }
  // 护墙板（朝里的窄条）
  for (const [w, x, z, ry] of [[W, 0, back, 0], [D, left, 0, Math.PI / 2], [D, -left, 0, -Math.PI / 2], [W, 0, -back, Math.PI]]) {
    const inward = new THREE.Vector3(0, 0, 1).applyAxisAngle(new THREE.Vector3(0, 1, 0), ry);
    const band = innerWall(root, w, 0.95, x, z, ry, "#c9a98c"); band.castShadow = false; band.position.addScaledVector(inward, 0.004);
    const rail = innerWall(root, w, 0.05, x, z, ry, "#6e4a35"); rail.castShadow = false; rail.position.y = 0.95; rail.position.addScaledVector(inward, 0.008);
  }
  // 窗框、窗外的海
  const sky = night
    ? gradientTexture([[0, "#1d1a35"], [0.45, "#4a3a63"], [0.62, "#c3767a"], [1, "#2a2440"]], { stars: 90, sun: { x: 0.68, y: 0.6, r: 0.18, color: "#ffb37a" }, sea: { y: 0.64, top: "#594a73", bottom: "#231f36" } })
    : gradientTexture([[0, "#7fa3c9"], [0.5, "#f2c49b"], [0.64, "#ffd9a8"], [1, "#6f88a5"]], { sun: { x: 0.62, y: 0.55, r: 0.22, color: "#fff0c8" }, sea: { y: 0.64, top: "#86a1bd", bottom: "#46617d" } });
  const view = new THREE.Mesh(new THREE.PlaneGeometry(22, 8), new THREE.MeshBasicMaterial({ map: sky, fog: false }));
  view.position.set(1.6, 2.0, back - 3.2); root.add(view); view.userData.insideOnly = true;
  const side = new THREE.Mesh(new THREE.PlaneGeometry(14, 7), new THREE.MeshBasicMaterial({ map: sky, fog: false }));
  side.position.set(left - 3, 2.0, 0); side.rotation.y = Math.PI / 2; root.add(side); side.userData.insideOnly = true;
  view.visible = side.visible = false;
  const frame = (x, z, ry, w, y0, h) => {
    const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = ry; root.add(g);
    const fk = kit(g, floors);
    for (const [bw, bh, bx, by] of [[w + 0.2, 0.1, 0, y0 + h + 0.05], [w + 0.2, 0.1, 0, y0 - 0.05], [0.1, h, -w / 2 - 0.05, y0 + h / 2], [0.1, h, w / 2 + 0.05, y0 + h / 2], [0.05, h, 0, y0 + h / 2], [w, 0.05, 0, y0 + h * 0.6]])
      fk.box(bw, bh, 0.1, "#f3ece0", bx, by, 0.02, { shadow: false });
    fk.box(w + 0.36, 0.06, 0.34, "#9a6b4a", 0, y0 - 0.02, 0.16, { surface: true });
  };
  for (const [x, y0, w, h] of windows) frame(x, back, 0, w, y0, h);
  frame(left, -1.0, Math.PI / 2, 2.4, 1.0, 1.7);
  // 墙上两幅小画
  const art = gradientTexture([[0, "#3a3256"], [0.55, "#d98a6c"], [0.56, "#6f8f72"], [1, "#3c5a4c"]], { w: 128, h: 96, sun: { x: 0.5, y: 0.5, r: 0.2, color: "#ffd59a" } });
  for (const [x, z, ry] of [[left + 0.02, 3.6, Math.PI / 2], [-6.0, back + 0.02, 0]]) {
    const g = new THREE.Group(); g.position.set(x, 2.75, z); g.rotation.y = ry; root.add(g);
    g.add(new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.9, 0.04), mat("#6e4a35")));
    const p = new THREE.Mesh(new THREE.PlaneGeometry(1.06, 0.76), new THREE.MeshStandardMaterial({ map: art, roughness: 0.9 })); p.position.z = 0.025; g.add(p);
  }
  // 吊灯
  for (const [x, z] of [[0.6, 0.6], [-6.2, 3.4]]) {
    const cord = new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.004, 1.0), mat("#4a3a30")); cord.position.set(x, H - 0.5, z); root.add(cord);
    const shade = new THREE.Mesh(new THREE.SphereGeometry(0.28, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2), mat("#f4d9ac", { emissive: "#ffc77d", glow: night ? 0.9 : 0.2 }));
    shade.position.set(x, H - 1.05, z); root.add(shade);
  }
  // 窗光里的浮尘
  const dust = new THREE.BufferGeometry(), pts = [];
  for (let i = 0; i < 260; i++) pts.push(-4 + Math.random() * 11, 0.3 + Math.random() * 3, back + 0.3 + Math.random() * 5);
  dust.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  const motes = new THREE.Points(dust, new THREE.PointsMaterial({ color: "#ffe2b8", size: 0.025, transparent: true, opacity: night ? 0.35 : 0.6, depthWrite: false, blending: THREE.AdditiveBlending }));
  root.add(motes);

  const lights = [new THREE.HemisphereLight(night ? "#9a90c2" : "#c9d4ee", "#5a4436", night ? 0.85 : 1.1)];
  const sun = new THREE.DirectionalLight(night ? "#ff9e7a" : "#ffd2a0", night ? 1.0 : 2.6);
  sun.position.set(4, 5.5, back - 9); sun.target.position.set(0, 0, 2);
  sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -11, right: 11, top: 9, bottom: -9, near: 1, far: 30 });
  sun.shadow.bias = -0.0006; sun.shadow.normalBias = 0.02;
  lights.push(sun, sun.target);
  for (const [x, z, power] of [[0.6, 0.6, night ? 10 : 3], [-6.2, 3.4, night ? 7 : 2]]) { const l = new THREE.PointLight("#ffc98a", power, 9, 2); l.position.set(x, H - 1.2, z); lights.push(l); }
  const fill = new THREE.DirectionalLight("#cdb8e8", night ? 0.35 : 0.6); fill.position.set(8, 7, 9); lights.push(fill);
  lights.forEach(l => root.add(l));
  return {
    root, floors, view: [6, 7], background: night ? "#1b1828" : "#2a2536", fog: null,
    clamp: p => { p.x = Math.max(left + 0.2, Math.min(-left - 0.2, p.x)); p.z = Math.max(back + 0.15, Math.min(-back - 0.2, p.z)); },
    walkable: p => Math.abs(p.x) < -left - 0.35 && Math.abs(p.z) < -back - 0.35,
    camera: { pos: [14.5, 11.5, 16.5], target: [0, 0.8, -0.6], min: 4, max: 36, polar: [0.2, 1.38] },
    fp: { pos: [3.2, 5.7], yaw: 0.45 },
    base: { daily: 0.34, sculpture: 0.6 },
    insideOnly: [view, side],
    update: () => { for (const v of [view, side]) v.visible = !!fp; const a = motes.geometry.attributes.position; for (let i = 1; i < a.array.length; i += 3) { a.array[i] += 0.0016; if (a.array[i] > 3.4) a.array[i] = 0.3; } a.needsUpdate = true; },
  };
}

const ROOM_FURNITURE = [
  ["f-bookcase-a", "bookcase", -8.72, -3.6, 90], ["f-bookcase-b", "bookcase", -8.72, 1.2, 90],
  ["f-wallshelf-a", "wallshelf", -5.6, -6.28, 0], ["f-desk", "desk", -1.4, -5.95, 0], ["f-vitrine", "vitrine", 1.6, -6.12, 0],
  ["f-cabinet", "cabinet", 4.6, -6.2, 0], ["f-printer", "printer", 7.85, -5.55, -40],
  ["f-pedestal-a", "pedestal", 8.3, -2.6, -90], ["f-pedestal-b", "pedestal", 8.3, -0.4, -90], ["f-pedestal-c", "pedestal", 8.3, 1.8, -90],
  ["f-rug", "rug", 0.6, 0.6, 0], ["f-coffee", "coffee", 0.6, 0.6, 0], ["f-sofa", "sofa", 0.6, 3.75, 180],
  ["f-armchair-a", "armchair", -2.6, 0.9, 75], ["f-armchair-b", "armchair", 3.8, 0.6, -75],
  ["f-armchair-c", "armchair", -6.5, 3.0, 40], ["f-sidetable", "sidetable", -7.5, 4.2, 0], ["f-floorlamp", "floorlamp", -8.2, 5.6, 0],
  ["f-plant-a", "plant", 8.2, 5.6, 0], ["f-plant-b", "plant", -3.4, -6.0, 0], ["f-plant-c", "plant", 6.4, -6.0, 0],
];

// ---------- 场景二：花园（海上的一座圆形花园，半径 20 米） ----------
const GARDEN_R = 20;
function gardenPath(t) { return new THREE.Vector3(Math.sin(t * Math.PI * 1.35) * 4.2, 0, 16.5 - t * 29); }
let ocean = null;
function buildGardenShell(night) {
  const root = new THREE.Group(), floors = [], k = kit(root, floors), R = GARDEN_R;
  const lawnGeo = new THREE.CircleGeometry(R, 96); lawnGeo.rotateX(-Math.PI / 2);
  const colors = [], c = new THREE.Color(), pos = lawnGeo.attributes.position;
  for (let i = 0; i < pos.count; i++) { const x = pos.getX(i), z = pos.getZ(i); c.set("#7f9a69").offsetHSL(0.012 * Math.sin(x * 0.5 + z * 0.3), 0, 0.035 * Math.sin(x * 0.3) * Math.cos(z * 0.4)); colors.push(c.r, c.g, c.b); }
  lawnGeo.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  k.add(lawnGeo, "#fff", 0, 0, 0, { surface: true, shadow: false, material: new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.95 }) });
  k.cyl(R + 0.2, R - 1.2, 1.4, "#d9c39a", 0, -0.71, 0, { seg: 96, shadow: false });
  k.cyl(R + 1.6, R + 0.2, 0.5, "#e2cfa7", 0, -0.45, 0, { seg: 96, shadow: false });
  for (let t = 0; t <= 1.001; t += 0.022) {
    const p = gardenPath(t);
    const s = k.cyl(0.4 + (t * 37 % 1) * 0.08, 0.44, 0.06, ["#cfc6b6", "#c4baa8", "#d6cebf"][Math.round(t * 70) % 3], p.x, 0.03, p.z, { seg: 9, shadow: false, surface: true });
    s.scale.z = 0.8; s.rotation.y = t * 9;
  }
  const pickets = new THREE.InstancedMesh(new THREE.BoxGeometry(0.08, 0.55, 0.05), mat("#e8dcc6"), 320);
  const m4 = new THREE.Matrix4(); let n = 0;
  for (let i = 0; i < 340 && n < 320; i++) {
    const ang = i / 340 * Math.PI * 2, x = Math.cos(ang) * (R - 0.5), z = Math.sin(ang) * (R - 0.5);
    if (z > R - 3 && Math.abs(x) < 1.6) continue;
    m4.makeRotationY(-ang + Math.PI / 2).setPosition(x, 0.275, z); pickets.setMatrixAt(n++, m4);
  }
  pickets.count = n; pickets.castShadow = true; root.add(pickets);
  const pond = k.add(new THREE.CircleGeometry(2.4, 40).rotateX(-Math.PI / 2), "#8fb0c2", -9, 0.015, -3,
    { material: new THREE.MeshStandardMaterial({ color: "#8fb0c2", roughness: 0.2, emissive: "#3e5a72", emissiveIntensity: 0.35 }), shadow: false });
  pond.scale.set(1.3, 1, 0.85);
  for (const [x, z] of [[-11.2, -1.8], [-7.2, -4.6], [-10.2, -5]]) k.ball(0.28, "#a9a294", x, 0.08, z, { detail: 0 });
  ocean = createOcean({ shore: R + 1.2, shoreWidth: 4, level: -0.25, size: 360, segments: 220, calm: 0.75 });
  root.add(ocean.group);
  const skyTex = night
    ? gradientTexture([[0, "#151329"], [0.38, "#3e3360"], [0.5, "#b56d78"], [0.56, "#f0a272"], [1, "#2b2338"]], { stars: 160 })
    : gradientTexture([[0, "#6f8fc0"], [0.4, "#b9b8d6"], [0.5, "#f5c39a"], [0.56, "#ffd6a5"], [1, "#a8a0b8"]]);
  root.add(new THREE.Mesh(new THREE.SphereGeometry(900, 32, 16), new THREE.MeshBasicMaterial({ map: skyTex, side: THREE.BackSide, fog: false })));
  const lights = [new THREE.HemisphereLight(night ? "#a89cd0" : "#d6dcf2", "#6a6446", night ? 1.0 : 1.4)];
  const sun = new THREE.DirectionalLight(night ? "#ff9a72" : "#ffd4a3", night ? 1.4 : 2.8);
  sun.position.set(-12, 11, -20); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -24, right: 24, top: 24, bottom: -24, near: 1, far: 70 });
  sun.shadow.bias = -0.0006; sun.shadow.normalBias = 0.03;
  lights.push(sun);
  const fill = new THREE.DirectionalLight("#c7b6e6", 0.5); fill.position.set(14, 10, 18); lights.push(fill);
  lights.forEach(x => root.add(x));
  return {
    root, floors, background: night ? "#1f1b30" : "#bfb3c8", fog: new THREE.Fog(night ? "#2b2440" : "#c9b6c4", 60, 260),
    facing: p => {
      let best = null, d = Infinity;
      for (let t = 0; t <= 1; t += 0.01) { const s = gardenPath(t), dd = Math.hypot(s.x - p.x, s.z - p.z); if (dd < d) { d = dd; best = s; } }
      return d < 0.4 ? [0, 30] : [best.x, best.z];
    },
    clamp: p => { const r = Math.hypot(p.x, p.z); if (r > R - 0.9) { p.x *= (R - 0.9) / r; p.z *= (R - 0.9) / r; } },
    walkable: p => Math.hypot(p.x, p.z) < R - 0.8 || (p.z > 0 && Math.abs(p.x) < 1.4 && Math.hypot(p.x, p.z) < R + 1),
    camera: { pos: [18, 15, 26], target: [0, 0.5, -0.5], min: 5, max: 70, polar: [0.25, 1.4] },
    fp: { pos: [0, 19.5], yaw: 0 },
    base: { daily: 0.5, sculpture: 0.85 },
    update: t => ocean.update(t),
  };
}

function gardenFurniture(count) {
  const list = [["f-arch", "arch", 0, GARDEN_R - 0.5, 0], ["f-pergola", "pergola", 0, -13.6, 0],
    ["f-bench-a", "bench", 7.2, -3.5, -110], ["f-bench-b", "bench", -6.2, 6.8, 120]];
  const n = Math.max(8, Math.min(40, count)), span = Math.min(0.86, 0.05 * n + 0.3);
  for (let i = 0; i < n; i++) {
    const t = 0.06 + (n === 1 ? 0 : i * span / (n - 1)), p = gardenPath(t), q = gardenPath(t + 0.01);
    const side = i % 2 ? 1 : -1, nrm = new THREE.Vector3(q.z - p.z, 0, -(q.x - p.x)).normalize().multiplyScalar(1.6 * side);
    const at = p.clone().add(nrm);
    list.push([`f-gplinth-${i}`, "gplinth", +at.x.toFixed(2), +at.z.toFixed(2), 0]);
  }
  [0.12, 0.3, 0.48, 0.66, 0.84, 0.97].forEach((t, i) => {
    const p = gardenPath(t), at = p.clone().add(new THREE.Vector3(i % 2 ? -0.85 : 0.85, 0, 0));
    list.push([`f-lantern-${i}`, "lantern", +at.x.toFixed(2), +at.z.toFixed(2), 0]);
  });
  for (let i = 0; i < 16; i++) {
    const a = i / 16 * Math.PI * 2 + 0.2, r = 12.5 + (i % 2) * 1.6, x = Math.cos(a) * r, z = Math.sin(a) * r;
    if (Math.abs(x) < 5.5 && z > 6) continue;
    if (Math.hypot(x + 9, z + 3) < 4) continue;
    list.push([`f-bed-${i}`, "flowerbed", +x.toFixed(2), +z.toFixed(2), 0]);
  }
  for (let i = 0; i < 12; i++) {
    const a = i / 12 * Math.PI * 2 + 0.45, r = 17.3, x = Math.cos(a) * r, z = Math.sin(a) * r;
    if (Math.abs(x) < 4 && z > 10) continue;
    list.push([`f-tree-${i}`, "tree", +x.toFixed(2), +z.toFixed(2), i * 31 % 360]);
  }
  return list;
}

// ---------- 资产 ----------
const PRINTED = new Set(["finished", "printed", "submitted"]);
function worldAssets(world) {
  const cards = world.cards || {};
  const daily = world.exhibits.map(e => {
    const card = cards[e.card_id] || {};
    return { id: e.id, kind: "daily", item: e, title: card.title || e.title, date: e.date || "",
      sub: e.date || (e.source === "sample" ? "样品" : "早期作品"),
      printed: Boolean(e.photo_url) || PRINTED.has(e.status), photo: e.photo_url || "",
      printNote: e.photo_url ? "实物已到手" : e.status === "submitted" ? "打印机已接单" : PRINTED.has(e.status) ? "已打印" : "还没打印",
      text: card.text || e.summary || "", aside: card.aside || e.reason || "" };
  });
  const sculptures = world.sculptures.map(s => {
    const card = cards[s.card_id] || {};
    return { id: s.id, kind: "sculpture", item: s, title: card.title || s.title, sub: s.stage || "世界精雕", date: "",
      printed: false, photo: "", text: card.text || s.description || "", aside: card.aside || "", stage: s.stage || "", zone: s.placement?.zone || "" };
  });
  daily.sort((a, b) => (b.date || "0").localeCompare(a.date || "0") || a.title.localeCompare(b.title, "zh"));
  return [...daily, ...sculptures];
}
function representatives(list, n) {
  const order = { entrance: 0, hall: 1, plaza: 2, shore: 3, wayside: 4 };
  const sorted = [...list].sort((a, b) => (order[a.zone] ?? 5) - (order[b.zone] ?? 5) || a.title.localeCompare(b.title, "zh"));
  const picked = [], stages = new Set();
  for (const a of sorted) if (picked.length < n && !stages.has(a.stage)) { picked.push(a); stages.add(a.stage); }
  for (const a of sorted) if (picked.length < n && !picked.includes(a)) picked.push(a);
  return picked;
}
function recommend(list) {
  const daily = list.filter(a => a.kind === "daily"), n = daily.length, printed = daily.filter(a => a.printed).length;
  const night = nightTime();
  if (n <= 30) return { scene: "room", reason: `你有 ${n} 件小物，其中 ${printed} 件已经打印成实物，放进小屋的展示墙和陈列柜刚好${night ? "；天黑了，屋里亮着灯" : ""}。` };
  if (n <= 60) return { scene: "garden", reason: `小物攒到 ${n} 件，小屋放不下了，搬到海上的花园，沿小路一件件摆开。` };
  return { scene: "garden", reason: `已经有 ${n} 件小物，花园也快满了，建议回小岛沿时间小路看。`, island: true };
}

// ---------- 物件模型 ----------
const gltf = new GLTFLoader(), stl = new STLLoader(), textures = new THREE.TextureLoader();
const itemGroups = new Map(), loaded = new Map();
function normalized(object, daily) {
  object.traverse(o => { if (!o.isMesh) return; if (daily) o.material = resin; o.castShadow = true; o.receiveShadow = true; });
  const holder = new THREE.Group(); holder.add(object);
  const box = new THREE.Box3().setFromObject(holder), size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
  const k = 1 / Math.max(size.y, size.x * 0.8, size.z * 0.8, 1e-5);
  object.position.set(-c.x * k, -box.min.y * k, -c.z * k); object.scale.multiplyScalar(k);
  holder.userData.halfWidth = size.x * k / 2; holder.userData.halfDepth = size.z * k / 2;
  return holder;
}
function loadAsset(a) {
  if (!loaded.has(a.id)) loaded.set(a.id, new Promise((resolve, reject) => {
    const url = a.item.model;
    if (url.includes("format=stl")) stl.load(url, geo => { geo.computeVertexNormals(); const m = new THREE.Mesh(geo, resin); m.rotation.x = -Math.PI / 2; resolve(normalized(m, true)); }, undefined, reject);
    else gltf.load(url, g => resolve(normalized(g.scene, a.kind === "daily")), undefined, reject);
  }));
  return loaded.get(a.id);
}
function plaqueTexture(text) {
  const canvas = document.createElement("canvas"); canvas.width = 256; canvas.height = 72;
  const ctx = canvas.getContext("2d"), g = ctx.createLinearGradient(0, 0, 0, 72);
  g.addColorStop(0, "#e8c27d"); g.addColorStop(1, "#b98a4a"); ctx.fillStyle = g; ctx.fillRect(0, 0, 256, 72);
  ctx.fillStyle = "#4a3320"; ctx.font = "34px 'Songti SC', serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(text, 128, 38);
  const t = new THREE.CanvasTexture(canvas); t.colorSpace = THREE.SRGBColorSpace; return t;
}
// 打印过的作品成对出现：数码模型旁边立一张实物照片，前面一块「实物」铜牌。
function addTwin(group, a, model) {
  const w = model.userData.halfWidth;
  if (a.photo) {
    const frame = new THREE.Group();
    const wood = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.62, 0.04), mat("#6e4a35")); wood.position.y = 0.33; wood.castShadow = true;
    const photoMat = new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.6 });
    const photo = new THREE.Mesh(new THREE.PlaneGeometry(0.42, 0.54), photoMat); photo.position.set(0, 0.33, 0.022);
    textures.load(a.photo, t => {
      t.colorSpace = THREE.SRGBColorSpace; photoMat.map = t; photoMat.needsUpdate = true;
      const r = t.image.width / t.image.height, [pw, ph] = r >= 0.78 ? [0.42, 0.42 / r] : [0.54 * r, 0.54];
      photo.scale.set(pw / 0.42, ph / 0.54, 1); wood.scale.set((pw + 0.08) / 0.5, (ph + 0.08) / 0.62, 1);
      wood.position.y = photo.position.y = 0.06 + (ph + 0.08) / 2;
    });
    const leg = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.5, 0.04), mat("#6e4a35")); leg.position.set(0, 0.24, -0.12); leg.rotation.x = 0.35;
    frame.add(wood, photo, leg); frame.position.set(w + 0.32, 0, -0.08); frame.rotation.y = -0.35; frame.scale.setScalar(0.85);
    group.add(frame);
  }
  const plaque = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.12, 0.03), [mat("#b98a4a"), mat("#b98a4a"), mat("#b98a4a"), mat("#b98a4a"),
    new THREE.MeshStandardMaterial({ map: plaqueTexture(a.date ? "实物 · " + a.date.slice(5) : "实物"), metalness: 0.5, roughness: 0.4 }), mat("#b98a4a")]);
  plaque.position.set(0, 0.07, Math.max(0.42, model.userData.halfDepth + 0.14)); plaque.rotation.x = -0.5; plaque.castShadow = true;
  group.add(plaque);
}
const ringGeo = new THREE.RingGeometry(0.62, 0.7, 48).rotateX(-Math.PI / 2);
function ringFor(group, radius = 1) {
  const ring = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: "#ffb766", transparent: true, opacity: 0.9, depthWrite: false }));
  ring.position.y = 0.015; ring.visible = false; ring.scale.setScalar(radius); ring.userData.isRing = true;
  group.userData.ring = ring; group.add(ring);
}
function itemGroup(a) {
  if (itemGroups.has(a.id)) return itemGroups.get(a.id);
  const group = new THREE.Group(); group.userData.assetId = a.id;
  ringFor(group);
  const lift = new THREE.Group(); group.add(lift); group.userData.lift = lift;
  const placeholder = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.32, 0.6, 12), mat("#d9cfc0", { opacity: 0.35 }));
  placeholder.position.y = 0.3; lift.add(placeholder);
  loadAsset(a).then(model => {
    lift.remove(placeholder); placeholder.geometry.dispose();
    lift.add(model); group.userData.model = model;
    if (a.printed) addTwin(lift, a, model);
    pop(group);
  }).catch(() => { placeholder.material = mat("#c97a6a", { opacity: 0.4 }); });
  itemGroups.set(a.id, group);
  return group;
}

// ---------- 动效 ----------
const anims = [];
function pop(group, delay = 0) {
  const lift = group.userData.lift || group;
  lift.scale.setScalar(0.001);
  anims.push({ t0: performance.now() + delay, dur: 420, step: s => { const k = s < 1 ? 1 + 2.4 * Math.pow(s - 1, 3) + 1.4 * Math.pow(s - 1, 2) : 1; lift.scale.setScalar(Math.max(0.001, k)); } });
}
function bounce(group) {
  const lift = group.userData.lift || group, base = 0;
  anims.push({ t0: performance.now(), dur: 380, step: s => {
    const w = Math.sin(s * Math.PI) * (1 - s);
    if (group.userData.lift) lift.position.y = base + Math.abs(Math.sin(s * Math.PI * 2)) * (1 - s) * 0.18;
    lift.scale.set(1 + w * 0.06, 1 - w * 0.08, 1 + w * 0.06);
  } });
}
function fadeScene(then) {
  const veil = $("veil"); veil.classList.add("on"); sound.whoosh();
  setTimeout(() => { then(); requestAnimationFrame(() => veil.classList.remove("on")); }, 380);
}

// ---------- 状态 ----------
let world = null, worldList = [], assets = [], byId = new Map(), env = null, current = "room", choice = "auto";
let saved = { room: {}, garden: {} }, defaults = {}, selected = null, undoStack = [], arranging = false;
const furnitureGroups = new Map();
const content = new THREE.Group(); scene.add(content);
const items = new THREE.Group(); scene.add(items);
let surfaces = [], furnitureList = [];

function furnitureDefs(name) { return name === "garden" ? gardenFurniture(worldList.filter(a => a.kind === "daily").length - 1) : ROOM_FURNITURE; }
function furnitureAssets(name) {
  const defs = furnitureDefs(name).map(([id, type, x, z, yaw]) => ({ id, type, home: { x, z, yaw } }));
  for (const [id, e] of Object.entries(saved[name])) if (id.startsWith("f-") && e.type && FURNITURE[e.type] && !defs.some(d => d.id === id)) defs.push({ id, type: e.type, home: { x: e.x, z: e.z, yaw: e.yaw || 0 }, spawned: true });
  return defs.map((d, i) => ({ ...d, kind: "furniture", title: FURNITURE[d.type].title, sub: name === "garden" ? "花园摆设" : "小屋家具", seed: i, printed: false, text: "", aside: "" }));
}
function entryOf(id) {
  const own = saved[current][id], a = byId.get(id);
  if (a?.kind === "furniture") return { x: a.home.x, y: 0, z: a.home.z, yaw: a.home.yaw, scale: 1, hidden: false, ...own };
  return own ? { ...defaults[id], ...own } : defaults[id] || { hidden: true };
}
function groupOf(id) { return byId.get(id)?.kind === "furniture" ? furnitureGroups.get(id) : itemGroups.get(id); }
function applyEntry(id) {
  const a = byId.get(id), e = entryOf(id);
  if (a.kind === "furniture") {
    const g = furnitureGroups.get(id);
    g.visible = !e.hidden; g.position.set(e.x, 0, e.z); g.rotation.y = (e.yaw || 0) * DEG; g.scale.setScalar(e.scale || 1);
    g.updateMatrixWorld(true);
    return;
  }
  const group = itemGroup(a);
  if (e.hidden || e.x === undefined) { group.removeFromParent(); return; }
  group.position.set(e.x, e.y, e.z); group.rotation.y = (e.yaw || 0) * DEG;
  group.scale.setScalar(env.base[a.kind] * (e.scale || 1));
  if (!group.parent) { items.add(group); if (group.userData.model) pop(group, Math.random() * 200); }
}
function refreshSurfaces() { surfaces = [...env.floors, ...[...furnitureGroups.values()].filter(g => g.visible).flatMap(g => g.userData.surfaces)]; }

// 默认摆放：最新一件当主角，已打印的进陈列柜，其余按日期上展示墙和书架，精雕挑代表件上展台。
const FACE_OUT = new Set(["bookcase", "wallshelf", "vitrine", "desk", "cabinet"]);
function slotsOf(kind) {
  const out = [];
  for (const [id, g] of furnitureGroups) {
    if (!g.visible) continue;
    const local = g.userData.info.slots?.[kind];
    if (!local) continue;
    for (const p of local) { const w = g.localToWorld(new THREE.Vector3(...p)); out.push({ x: w.x, y: w.y, z: w.z, yaw: g.rotation.y / DEG, owner: id, front: FACE_OUT.has(kind) }); }
  }
  return out;
}
function facingYaw(x, z) {
  const [vx, vz] = env.facing ? env.facing({ x, z }) : env.view;
  return Math.round(Math.atan2(vx - x, vz - z) / DEG);
}
function arrange(name) {
  const out = {}, daily = worldList.filter(a => a.kind === "daily"), sculpt = worldList.filter(a => a.kind === "sculpture");
  const put = (a, s, scale = 1) => { out[a.id] = { x: +s.x.toFixed(3), y: +s.y.toFixed(3), z: +s.z.toFixed(3), yaw: s.front ? Math.round(s.yaw) : facingYaw(s.x, s.z), scale, hidden: false }; };
  const free = list => list.filter(s => !Object.values(out).some(o => Math.hypot(o.x - s.x, o.z - s.z) < 0.2 && Math.abs(o.y - s.y) < 0.1));
  const take = (pool, list, scale) => { list.forEach(a => { const s = pool.shift(); if (s) put(a, s, scale); }); return list.filter(a => !out[a.id]); };
  const featured = daily.find(a => a.date) || daily[0];
  const feat = slotsOf("featured");
  if (featured && feat[0]) put(featured, feat[0], 1.45);
  const rest = daily.filter(a => a !== featured);
  if (name === "room") {
    const printed = rest.filter(a => a.printed), others = rest.filter(a => !a.printed).reverse();
    const left = take([...slotsOf("vitrine"), ...slotsOf("desk")], printed, 1);
    take(free([...slotsOf("wallshelf"), ...slotsOf("bookcase"), ...slotsOf("desk"), ...slotsOf("cabinet")]), [...left, ...others], 1);
    const reps = representatives(sculpt, 8), ped = slotsOf("pedestal"), cab = free(slotsOf("cabinet"));
    const np = ped.length, nc = cab.length;
    take(ped, reps.slice(0, np), 1.1);
    take(cab, reps.slice(np, np + nc), 0.78);
    take(slotsOf("side"), reps.slice(np + nc), 0.7);
  } else {
    take(slotsOf("gplinth"), [...rest].reverse(), 1);
    take(slotsOf("bed"), representatives(sculpt, slotsOf("bed").length), 1.1);
  }
  for (const a of worldList) out[a.id] ||= { hidden: true };
  return out;
}

// ---------- 保存 ----------
let saveTimer = null;
function status(text) { $("shelf-status").textContent = text; }
function queueSave() {
  clearTimeout(saveTimer); status("正在保存…");
  saveTimer = setTimeout(async () => {
    try {
      const response = await fetch("/api/palace", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ room: current, items: saved[current] }) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error);
      status("已保存在本机");
    } catch (error) { status((error.message || "没能保存") + " 摆放还在页面上，5 秒后再试。"); setTimeout(queueSave, 5000); }
  }, 450);
}
function snapshot() { undoStack.push({ room: current, items: JSON.stringify(saved[current]) }); if (undoStack.length > 60) undoStack.shift(); $("undo").disabled = false; }
function writeEntry(id, patch) {
  const base = entryOf(id), a = byId.get(id);
  const e = { x: base.x, y: base.y, z: base.z, yaw: base.yaw || 0, scale: base.scale || 1, hidden: false, ...patch };
  if (a.kind === "furniture") { delete e.y; if (a.spawned) e.type = a.type; }
  for (const key of Object.keys(e)) if (e[key] === undefined) delete e[key];
  saved[current][id] = e;
}
function commit(id, patch) { snapshot(); writeEntry(id, patch); applyEntry(id); if (byId.get(id).kind === "furniture") refreshSurfaces(); queueSave(); refreshShelf(); }

// 家具上的东西跟着家具走
function carriedBy(id) {
  const g = furnitureGroups.get(id), [hw, hd] = g.userData.info.half || [0.5, 0.5], out = [];
  if (g.userData.info.flat) return out;
  g.updateMatrixWorld(true);
  for (const child of items.children) {
    if (child.position.y < 0.03) continue;
    const local = g.worldToLocal(child.position.clone());
    if (Math.abs(local.x) <= hw + 0.1 && Math.abs(local.z) <= hd + 0.15 && local.y > 0) out.push({ id: child.userData.assetId, local, yaw: child.rotation.y - g.rotation.y });
  }
  return out;
}
function moveCarried(id, carried) {
  if (!carried?.length) return;
  const g = furnitureGroups.get(id); g.updateMatrixWorld(true);
  for (const c of carried) { const it = itemGroups.get(c.id); it.position.copy(g.localToWorld(c.local.clone())); it.rotation.y = g.rotation.y + c.yaw; }
}
function saveCarried(carried) {
  for (const c of carried || []) { const it = itemGroups.get(c.id); writeEntry(c.id, { x: +it.position.x.toFixed(3), y: +it.position.y.toFixed(3), z: +it.position.z.toFixed(3), yaw: Math.round((((it.rotation.y / DEG) + 540) % 360) - 180) }); }
}

function freeSpot(a) {
  const taken = [...items.children].map(g => g.position);
  const prefer = a.kind === "sculpture" ? ["pedestal", "cabinet", "bed", "side", "bench", "gplinth"] : ["wallshelf", "vitrine", "desk", "bookcase", "gplinth", "bench", "cabinet"];
  for (const s of prefer.flatMap(slotsOf)) if (!taken.some(p => Math.hypot(p.x - s.x, p.z - s.z) < 0.4 && Math.abs(p.y - s.y) < 0.3)) return { x: s.x, y: s.y, z: s.z, yaw: s.front ? Math.round(s.yaw) : facingYaw(s.x, s.z) };
  const c = controls.target;
  for (let r = 0.6; r < 12; r += 0.5) for (let k = 0; k < 16; k++) {
    const p = { x: c.x + Math.cos(k / 16 * Math.PI * 2) * r, y: 0, z: c.z + Math.sin(k / 16 * Math.PI * 2) * r };
    if (env.walkable(p) && !blocked(p.x, p.z, 0.2) && !taken.some(t => Math.hypot(t.x - p.x, t.z - p.z) < 0.8)) return { ...p, yaw: facingYaw(p.x, p.z) };
  }
  return { x: 0, y: 0, z: 0, yaw: 0 };
}
function freeFloor() {
  const c = fp ? new THREE.Vector3(fp.x - Math.sin(fp.yaw) * 2.5, 0, fp.z - Math.cos(fp.yaw) * 2.5) : controls.target;
  for (let r = 0; r < 12; r += 0.5) for (let k = 0; k < Math.max(1, r * 8); k++) {
    const p = { x: c.x + Math.cos(k / Math.max(1, r * 8) * Math.PI * 2) * r, z: c.z + Math.sin(k / Math.max(1, r * 8) * Math.PI * 2) * r };
    if (env.walkable(p) && !blocked(p.x, p.z, 0.9)) return p;
  }
  return { x: c.x, z: c.z };
}

// ---------- 场景切换 ----------
function setScene(name, { fly = true } = {}) {
  current = name; content.clear(); furnitureGroups.clear();
  for (const g of itemGroups.values()) g.removeFromParent();
  if (fp) leaveWalk(false);
  env = name === "garden" ? buildGardenShell(nightTime()) : buildRoomShell(nightTime());
  content.add(env.root);
  scene.background = new THREE.Color(env.background); scene.fog = env.fog;
  furnitureList = furnitureAssets(name);
  assets = [...worldList, ...furnitureList]; byId = new Map(assets.map(a => [a.id, a]));
  for (const f of furnitureList) {
    const g = buildFurniture(f.type, nightTime(), f.seed); g.userData.assetId = f.id;
    const [hw, hd] = g.userData.info.half || [0.5, 0.5]; ringFor(g, Math.max(hw, hd) / 0.62 + 0.25);
    furnitureGroups.set(f.id, g); content.add(g); applyEntry(f.id);
  }
  refreshSurfaces();
  defaults = arrange(name);
  for (const a of worldList) applyEntry(a.id);
  const cam = env.camera;
  const narrow = camera.aspect < 1 ? Math.min(2.3, 0.9 / camera.aspect) : 1;
  const target = new THREE.Vector3(...cam.target), start = new THREE.Vector3(...cam.pos).sub(target).multiplyScalar(narrow).add(target);
  controls.minDistance = cam.min; controls.maxDistance = cam.max * narrow;
  controls.minPolarAngle = cam.polar[0]; controls.maxPolarAngle = cam.polar[1];
  flyTo(start, target, fly ? 1100 : 0);
  select(null); renderer.shadowMap.needsUpdate = true;
  undoStack = undoStack.filter(u => u.room === name); $("undo").disabled = !undoStack.length;
  sound.ambient(name === "garden" ? "garden" : "room");
  renderAdd(); showReason(); refreshShelf();
}
let flight = null;
function flyTo(pos, target, ms) {
  if (!ms) { camera.position.copy(pos); controls.target.copy(target); controls.update(); return; }
  flight = { from: camera.position.clone(), to: pos, a: controls.target.clone(), b: target, t0: performance.now(), ms };
}
function showReason() {
  const rec = recommend(worldList), first = !Object.keys(saved[current]).length;
  let text = choice === "auto" ? rec.reason : current === "room" ? "你选了小屋。" : "你选了花园。";
  if (first) text += " 第一次进来，已经按日期和打印情况替你摆好了。";
  $("scene-reason").textContent = text;
  for (const b of document.querySelectorAll("[data-scene]")) b.setAttribute("aria-pressed", String(b.dataset.scene === choice));
}
async function choose(next) {
  choice = next;
  const target = next === "auto" ? recommend(worldList).scene : next;
  if (target !== current || !env) fadeScene(() => setScene(target)); else showReason();
  if (readOnly) return;
  try { await fetch("/api/palace", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scene: next }) }); } catch { /* 下次再记 */ }
}

// ---------- 第一人称 ----------
let fp = null;
const keys = new Set();
function blocked(x, z, pad = 0.28) {
  if (!env.walkable({ x, z })) return true;
  for (const [, g] of furnitureGroups) {
    if (!g.visible || g.userData.info.walkable) continue;
    const [hw, hd] = g.userData.info.half || [0.4, 0.4], s = g.scale.x;
    const dx = x - g.position.x, dz = z - g.position.z, c = Math.cos(g.rotation.y), sn = Math.sin(g.rotation.y);
    const lx = dx * c - dz * sn, lz = dx * sn + dz * c;
    if (Math.abs(lx) < hw * s + pad && Math.abs(lz) < hd * s + pad) return true;
  }
  return false;
}
const walkHint = () => arranging ? "WASD 走 · 拖空白处看四周 · 拖物件或家具换位置 · Shift 跑" : "WASD 走 · 拖动看四周 · ←→ 转头 · Shift 跑 · 点物件看故事";
const orbitHint = () => arranging ? "拖动物件或家具换位置 · Q / E 转向 · ⌘Z 撤销" : readOnly ? "点物件看它的故事 · 拖动转视角 · 「走进去」逛一圈" : "点物件看它的故事 · 拖动转视角 · 打开「资产管理」才能布置";
function enterWalk() {
  const [x, z] = env.fp.pos;
  fp = { x, z, yaw: env.fp.yaw, pitch: -0.1 };
  controls.enabled = false; flight = null;
  $("walk").textContent = "俯瞰"; $("walk").setAttribute("aria-pressed", "true");
  document.body.classList.add("walking"); $("hint").textContent = walkHint();
  sound.whoosh();
}
function leaveWalk(fly = true) {
  if (!fp) return;
  fp = null; controls.enabled = true;
  $("walk").textContent = "走进去"; $("walk").setAttribute("aria-pressed", "false");
  document.body.classList.remove("walking"); $("hint").textContent = orbitHint();
  if (fly && env) { const cam = env.camera; camera.rotation.set(0, 0, 0); flyTo(new THREE.Vector3(...cam.pos), new THREE.Vector3(...cam.target), 900); }
}
function updateWalk(dt) {
  const run = keys.has("ShiftLeft") || keys.has("ShiftRight"), speed = (run ? 5.5 : 2.6) * dt;
  const f = (keys.has("KeyW") || keys.has("ArrowUp") ? 1 : 0) - (keys.has("KeyS") || keys.has("ArrowDown") ? 1 : 0);
  const s = (keys.has("KeyD") ? 1 : 0) - (keys.has("KeyA") ? 1 : 0);
  fp.yaw += ((keys.has("ArrowLeft") ? 1 : 0) - (keys.has("ArrowRight") ? 1 : 0)) * 1.8 * dt;
  if (f || s) {
    const fx = -Math.sin(fp.yaw), fz = -Math.cos(fp.yaw), rx = -fz, rz = fx;
    let mx = fx * f + rx * s, mz = fz * f + rz * s; const len = Math.hypot(mx, mz); mx *= speed / len; mz *= speed / len;
    if (!blocked(fp.x + mx, fp.z + mz)) { fp.x += mx; fp.z += mz; }
    else if (!blocked(fp.x + mx, fp.z)) fp.x += mx;
    else if (!blocked(fp.x, fp.z + mz)) fp.z += mz;
    sound.step(run);
  }
  const bob = (f || s) ? Math.sin(performance.now() * 0.011) * 0.03 : 0;
  camera.position.set(fp.x, EYE + bob, fp.z);
  camera.rotation.set(fp.pitch, fp.yaw, 0, "YXZ");
}

// ---------- 选中、卡片、资产面板 ----------
function select(id, { focus = false } = {}) {
  if (selected) { const r = groupOf(selected)?.userData.ring; if (r) r.visible = false; }
  selected = id;
  const detail = $("shelf-detail");
  if (!id || !byId.has(id)) { selected = null; detail.hidden = true; refreshShelf(); return; }
  const group = groupOf(id), e = entryOf(id), a = byId.get(id);
  if (group?.userData.ring && arranging) group.userData.ring.visible = true;
  detail.hidden = !arranging;
  $("detail-title").textContent = a.title + (a.kind === "furniture" ? " · " + a.sub : "");
  $("detail-yaw").value = String(Math.round(((e.yaw || 0) + 540) % 360 - 180));
  $("detail-scale").value = String(Math.round((e.scale || 1) * 100));
  $("detail-remove").hidden = !a.spawned;
  if (focus && group && (group.parent === items || (a.kind === "furniture" && group.visible)) && !fp) {
    const t = group.position.clone(); t.y += 0.4;
    const offset = camera.position.clone().sub(controls.target).setLength(Math.min(a.kind === "furniture" ? 9 : 6, camera.position.distanceTo(controls.target)));
    flyTo(t.clone().add(offset), t, 700);
  }
  refreshShelf();
}
function openCard(id) {
  const a = byId.get(id);
  if (a.kind === "furniture") return;
  $("card-kicker").textContent = a.kind === "daily" ? (a.date || a.sub) : a.sub;
  $("card-title").textContent = a.title;
  const twin = $("card-twin"); twin.replaceChildren();
  const chips = a.kind === "daily" ? ["Aholo 数码模型", a.printNote] : ["Aholo 世界精雕"];
  chips.forEach((t, i) => { const s = document.createElement("span"); s.textContent = t; if (i === 1 && a.printed) s.className = "real"; twin.append(s); });
  const photo = $("card-photo");
  if (a.photo) { photo.src = a.photo; photo.hidden = false; } else { photo.hidden = true; photo.removeAttribute("src"); }
  $("card-text").textContent = a.text; $("card-aside").textContent = a.aside;
  const link = $("card-open"); link.hidden = !(a.kind === "daily" && a.date); if (a.date) link.href = WORKBENCH + "/?day=" + a.date;
  $("card-store").hidden = !arranging;
  const card = $("card"); card.hidden = true; void card.offsetWidth; card.hidden = false;
  sound.open();
}

let filter = "all";
const isStored = a => entryOf(a.id).hidden || (a.kind !== "furniture" && entryOf(a.id).x === undefined);
const FILTERS = {
  all: () => true, daily: a => a.kind === "daily", printed: a => a.printed, sculpture: a => a.kind === "sculpture",
  furniture: a => a.kind === "furniture", stored: isStored,
};
function refreshShelf() {
  if ($("shelf").hidden) return;
  for (const b of document.querySelectorAll("[data-filter]")) {
    b.querySelector("span").textContent = assets.filter(FILTERS[b.dataset.filter]).length;
    b.setAttribute("aria-pressed", String(b.dataset.filter === filter));
  }
  $("shelf-add").hidden = filter !== "furniture";
  const q = $("shelf-search").value.trim();
  const rows = assets.filter(FILTERS[filter]).filter(a => !q || a.title.includes(q) || a.sub.includes(q));
  $("shelf-list").replaceChildren(...rows.map((a, i) => {
    const stored = isStored(a);
    const row = document.createElement("div"); row.className = "asset-row"; row.setAttribute("aria-current", String(a.id === selected));
    row.style.animationDelay = Math.min(i, 20) * 12 + "ms";
    const pick = document.createElement("button"); pick.type = "button"; pick.className = "asset-pick";
    const name = document.createElement("strong"); name.textContent = a.title;
    const meta = document.createElement("small");
    meta.textContent = a.kind === "daily" ? a.sub + " · " + a.printNote : a.kind === "furniture" ? a.sub + (a.spawned ? " · 你添加的" : "") : "Aholo · " + a.sub;
    pick.append(name, meta);
    if (a.printed) { const badge = document.createElement("em"); badge.textContent = "实物"; pick.append(badge); }
    pick.addEventListener("click", () => { if (!stored) { select(a.id, { focus: true }); openCard(a.id); } });
    pick.disabled = stored;
    const act = document.createElement("button"); act.type = "button"; act.textContent = stored ? "摆进来" : "收起";
    act.addEventListener("click", () => stored ? bringIn(a) : storeAway(a.id));
    row.append(pick, act);
    return row;
  }));
}
function bringIn(a) {
  if (a.kind === "furniture") { const p = freeFloor(); commit(a.id, { hidden: false, x: +p.x.toFixed(3), z: +p.z.toFixed(3) }); pop(furnitureGroups.get(a.id)); }
  else {
    const d = defaults[a.id];
    const spot = d && !d.hidden && ![...items.children].some(g => g.position.distanceTo(new THREE.Vector3(d.x, d.y, d.z)) < 0.3) ? d : freeSpot(a);
    commit(a.id, { ...spot, scale: d?.scale || 1, hidden: false });
  }
  sound.place(); select(a.id, { focus: true });
}
function storeAway(id) {
  const a = byId.get(id);
  snapshot();
  let extra = 0;
  if (a.kind === "furniture") for (const c of carriedBy(id)) { writeEntry(c.id, { hidden: true }); applyEntry(c.id); extra++; }
  writeEntry(id, { hidden: true }); applyEntry(id);
  if (a.kind === "furniture") refreshSurfaces();
  queueSave(); sound.store();
  if (selected === id) select(null);
  $("card").hidden = true;
  refreshShelf();
  if (extra) status(`上面的 ${extra} 件也一起收进了仓库。`);
}
function renderAdd() {
  const box = $("shelf-add-list"), types = Object.entries(FURNITURE).filter(([, d]) => d.scene === current);
  box.replaceChildren(...types.map(([type, d]) => {
    const b = document.createElement("button"); b.type = "button"; b.textContent = "+ " + d.title;
    b.addEventListener("click", () => addFurniture(type));
    return b;
  }));
}
function addFurniture(type) {
  const id = `f-${type}-${Math.random().toString(36).slice(2, 8)}`, p = freeFloor();
  snapshot();
  saved[current][id] = { type, x: +p.x.toFixed(3), z: +p.z.toFixed(3), yaw: 0, scale: 1, hidden: false };
  queueSave(); sound.place();
  rebuildKeepingCamera();
  select(id, { focus: true });
  const g = furnitureGroups.get(id); if (g) pop(g);
}
function removeFurniture(id) {
  const a = byId.get(id); if (!a?.spawned) return;
  snapshot();
  for (const c of carriedBy(id)) writeEntry(c.id, { hidden: true });
  delete saved[current][id];
  queueSave(); sound.store(); select(null);
  rebuildKeepingCamera();
}
function rebuildKeepingCamera() {
  const pos = camera.position.clone(), target = controls.target.clone(), walking = fp && { ...fp };
  setScene(current, { fly: false });
  camera.position.copy(pos); controls.target.copy(target); controls.update();
  if (walking) { enterWalk(); Object.assign(fp, walking); }
}
function toggleShelf(open) {
  arranging = open;
  $("shelf").hidden = !open; $("open-shelf").setAttribute("aria-pressed", String(open));
  document.body.classList.toggle("arranging", open);
  $("hint").textContent = fp ? walkHint() : orbitHint();
  if (open) { $("card").hidden = true; refreshShelf(); sound.open(); }
  else { select(null); sound.close(); }
}

// ---------- 指针：点选、拖动、悬停 ----------
const ray = new THREE.Raycaster(), pointer = new THREE.Vector2();
let drag = null, hovered = null;
function aim(event) {
  const r = renderer.domElement.getBoundingClientRect();
  pointer.set((event.clientX - r.left) / r.width * 2 - 1, -(event.clientY - r.top) / r.height * 2 + 1);
  ray.setFromCamera(pointer, camera);
}
function visibleChain(o) { for (; o; o = o.parent) if (!o.visible) return false; return true; }
function ownerOf(o) { while (o && !o.userData.assetId) o = o.parent; return o?.userData.assetId || null; }
function pickUnder() {
  const targets = [...items.children, ...[...furnitureGroups.values()].filter(g => g.visible)];
  for (const hit of ray.intersectObjects(targets, true)) {
    if (hit.object.userData.isRing || hit.object.isLight || !visibleChain(hit.object)) continue;
    const id = ownerOf(hit.object);
    if (id) return id;
  }
  return null;
}
const normal = new THREE.Vector3();
function surfaceUnder(exclude, floorOnly = false) {
  const list = floorOnly ? env.floors.concat([...furnitureGroups.values()].filter(g => g.visible && g.userData.info.flat).flatMap(g => g.userData.surfaces)) : surfaces;
  for (const hit of ray.intersectObjects(list, false)) {
    if (exclude && ownerOf(hit.object) === exclude) continue;
    if (!visibleChain(hit.object)) continue;
    normal.copy(hit.face.normal).transformDirection(hit.object.matrixWorld);
    if (normal.y > 0.6) return hit.point;
  }
  return null;
}
renderer.domElement.addEventListener("pointerdown", event => {
  if (event.button !== 0) return;
  aim(event);
  const id = pickUnder(), a = id && byId.get(id);
  drag = { id, x: event.clientX, y: event.clientY, moved: false, look: fp ? { yaw: fp.yaw, pitch: fp.pitch } : null };
  if (arranging && a) {
    controls.enabled = false; renderer.domElement.setPointerCapture(event.pointerId);
    if (a.kind === "furniture") drag.carried = carriedBy(id);
  }
});
renderer.domElement.addEventListener("pointermove", event => {
  aim(event);
  if (drag) {
    const far = Math.hypot(event.clientX - drag.x, event.clientY - drag.y) >= 5;
    if (arranging && drag.id) {
      if (!drag.moved && !far) return;
      const a = byId.get(drag.id), g = groupOf(drag.id);
      if (!drag.moved) { drag.moved = true; snapshot(); select(drag.id); $("card").hidden = true; sound.pick(); if (g.userData.lift) g.userData.lift.position.y = 0.35; }
      const p = surfaceUnder(a.kind === "furniture" ? null : drag.id, a.kind === "furniture");
      if (p) {
        env.clamp(p);
        if (a.kind === "furniture") { g.position.set(p.x, 0, p.z); g.updateMatrixWorld(true); moveCarried(drag.id, drag.carried); }
        else g.position.copy(p);
        renderer.shadowMap.needsUpdate = true;
      }
      $("tip").hidden = true;
      return;
    }
    if (fp && far) { drag.moved = true; fp.yaw = drag.look.yaw - (event.clientX - drag.x) * 0.005; fp.pitch = Math.max(-1.2, Math.min(1.0, drag.look.pitch - (event.clientY - drag.y) * 0.004)); return; }
    if (far) drag.moved = true;
    return;
  }
  const id = pickUnder(), tip = $("tip"), a = id && byId.get(id);
  if (id !== hovered) { hovered = id; if (a && a.kind !== "furniture") sound.hover(); }
  const printer = a?.kind === "furniture" && a.type === "printer";
  if (a && (a.kind !== "furniture" || arranging || printer)) {
    tip.textContent = printer && !arranging ? (readOnly ? "3D 打印机 · 每天的小物从这里打出来" : "3D 打印机 · 点一下打开今日小物") : a.title + (a.printed ? " · 实物" : "") + (arranging ? " · 拖动换位置" : "");
    tip.hidden = false; tip.style.transform = `translate(${event.clientX + 14}px, ${event.clientY + 12}px)`;
  } else tip.hidden = true;
  renderer.domElement.style.cursor = a ? (arranging ? "grab" : (a.kind !== "furniture" || printer) ? "pointer" : "") : fp ? "grab" : "";
});
renderer.domElement.addEventListener("pointerup", () => {
  if (!drag) return;
  const { id, moved } = drag, a = id && byId.get(id);
  if (arranging && a && moved) {
    const g = groupOf(id);
    undoStack.pop(); snapshot();
    if (a.kind === "furniture") { writeEntry(id, { x: +g.position.x.toFixed(3), z: +g.position.z.toFixed(3) }); saveCarried(drag.carried); refreshSurfaces(); }
    else { writeEntry(id, { x: +g.position.x.toFixed(3), y: +g.position.y.toFixed(3), z: +g.position.z.toFixed(3) }); if (g.userData.lift) g.userData.lift.position.y = 0; }
    queueSave(); refreshShelf(); bounce(g); sound.drop();
  } else if (!moved && a) {
    if (a.kind === "furniture" && a.type === "printer" && !arranging) { if (!readOnly) { sound.open(); bench.open(); } }
    else { select(id); if (a.kind !== "furniture") openCard(id); else if (arranging) sound.tap(); }
  } else if (!moved && !a && !arranging) $("card").hidden = true;
  controls.enabled = !fp; drag = null;
});
addEventListener("keydown", event => {
  if (event.target.closest?.("input, textarea, dialog")) return;
  keys.add(event.code);
  if (event.key === "Escape") { if (fp) leaveWalk(); else if (!$("card").hidden) $("card").hidden = true; else toggleShelf(false); }
  if (arranging && selected && (event.key === "q" || event.key === "e")) rotateSelected(event.key === "q" ? -15 : 15);
  if ((event.metaKey || event.ctrlKey) && event.key === "z") { event.preventDefault(); undo(); }
  if (fp && event.code.startsWith("Arrow")) event.preventDefault();
});
addEventListener("keyup", event => keys.delete(event.code));
addEventListener("blur", () => keys.clear());

function rotateSelected(delta) {
  const a = byId.get(selected), e = entryOf(selected), yaw = (((e.yaw || 0) + delta) + 540) % 360 - 180;
  if (a.kind === "furniture") {
    const carried = carriedBy(selected), g = furnitureGroups.get(selected);
    snapshot(); g.rotation.y = yaw * DEG; moveCarried(selected, carried); writeEntry(selected, { yaw }); saveCarried(carried); refreshSurfaces(); queueSave();
  } else commit(selected, { yaw });
  sound.tap(); select(selected);
}
function undo() {
  const last = undoStack.pop();
  if (!last) return;
  saved[last.room] = JSON.parse(last.items);
  const spawnedBefore = furnitureList.filter(f => f.spawned).map(f => f.id).sort().join();
  const spawnedAfter = Object.keys(saved[current]).filter(id => id.startsWith("f-") && saved[current][id].type).sort().join();
  if (spawnedBefore !== spawnedAfter) rebuildKeepingCamera();
  else { for (const a of assets) applyEntry(a.id); refreshSurfaces(); }
  if (selected) select(selected);
  $("undo").disabled = !undoStack.length;
  queueSave(); refreshShelf(); sound.tap();
}

// ---------- 面板按钮 ----------
for (const b of document.querySelectorAll("[data-scene]")) b.addEventListener("click", () => { sound.tap(); choose(b.dataset.scene); });
$("open-shelf").addEventListener("click", () => toggleShelf($("shelf").hidden));
$("shelf-done").addEventListener("click", () => toggleShelf(false));
$("walk").addEventListener("click", () => fp ? leaveWalk() : enterWalk());
$("card-close").addEventListener("click", () => { $("card").hidden = true; sound.close(); });
$("card-store").addEventListener("click", () => { if (selected) storeAway(selected); });
for (const b of document.querySelectorAll("[data-filter]")) b.addEventListener("click", () => { filter = b.dataset.filter; sound.tap(); refreshShelf(); });
$("shelf-search").addEventListener("input", refreshShelf);
$("undo").addEventListener("click", undo);
$("arrange").addEventListener("click", () => {
  snapshot(); saved[current] = Object.fromEntries(Object.entries(saved[current]).filter(([id, e]) => id.startsWith("f-") && e.type));
  rebuildKeepingCamera();
  for (const g of items.children) pop(g, Math.random() * 400);
  queueSave(); sound.success();
  setTimeout(() => status("已经重新摆好，家具也回到了原位。不满意可以点「撤销」。"), 900);
});
let sliderTimer = null, sliderCarry = null;
$("detail-yaw").addEventListener("pointerdown", () => { if (selected && byId.get(selected).kind === "furniture") sliderCarry = carriedBy(selected); });
$("detail-yaw").addEventListener("input", e => {
  if (!selected) return;
  const g = groupOf(selected), id = selected, carry = sliderCarry; g.rotation.y = +e.target.value * DEG;
  if (carry) moveCarried(id, carry);
  clearTimeout(sliderTimer);
  sliderTimer = setTimeout(() => { snapshot(); writeEntry(id, { yaw: +e.target.value }); if (carry) { saveCarried(carry); refreshSurfaces(); } queueSave(); }, 250);
});
$("detail-yaw").addEventListener("change", () => { setTimeout(() => { sliderCarry = null; }, 300); });
$("detail-scale").addEventListener("input", e => {
  if (!selected) return;
  const a = byId.get(selected), g = groupOf(selected), id = selected;
  g.scale.setScalar(a.kind === "furniture" ? e.target.value / 100 : env.base[a.kind] * e.target.value / 100);
  clearTimeout(sliderTimer); sliderTimer = setTimeout(() => commit(id, { scale: +e.target.value / 100 }), 250);
});
$("detail-store").addEventListener("click", () => { if (selected) storeAway(selected); });
$("detail-remove").addEventListener("click", () => { if (selected) removeFurniture(selected); });
$("detail-reset").addEventListener("click", () => {
  if (!selected) return;
  const a = byId.get(selected), id = selected;
  snapshot();
  if (a.kind === "furniture") {
    const carried = carriedBy(id); delete saved[current][id];
    if (a.spawned) writeEntry(id, { x: a.home.x, z: a.home.z, yaw: 0, scale: 1 });
    applyEntry(id); moveCarried(id, carried); saveCarried(carried); refreshSurfaces();
  } else { delete saved[current][id]; if (defaults[id]?.hidden) saved[current][id] = { ...freeSpot(a), hidden: false }; applyEntry(id); }
  select(id); queueSave(); sound.place();
});
document.addEventListener("click", e => {
  const b = e.target.closest?.(".views button, .views a, .shelf button, .card button");
  if (b && !b.dataset.scene && !b.dataset.filter && !["card-close", "open-shelf", "shelf-done", "arrange"].includes(b.id)) sound.tap();
}, true);

let paused = false;
const bench = workbenchPanel({ pause: () => { paused = true; }, resume: () => { paused = false; }, refresh: () => load(true) });

// ---------- 启动 ----------
async function load(refresh = false) {
  const response = await fetch("/data/world.json", { cache: "no-store" });
  world = await response.json();
  worldList = worldAssets(world);
  const palace = world.palace || { scene: "auto", rooms: {} };
  saved = { room: palace.rooms.room?.items || {}, garden: palace.rooms.garden?.items || {} };
  const known = new Set(worldList.map(a => a.id));
  for (const room of Object.values(saved)) for (const id of Object.keys(room)) if (!id.startsWith("f-") && !known.has(id)) delete room[id];
  if (refresh && env) { rebuildKeepingCamera(); return; }
  choice = params.get("scene") || palace.scene || "auto";
  setScene(choice === "auto" ? recommend(worldList).scene : choice, { fly: false });
  $("hint").textContent = orbitHint();
  if (params.has("walk")) enterWalk();
}
let last = performance.now();
const t0 = performance.now();
const one = new THREE.Vector3(1, 1, 1), big = new THREE.Vector3(1.06, 1.06, 1.06);
function frame(now) {
  requestAnimationFrame(frame);
  if (paused) return;
  const dt = Math.min(0.05, (now - last) / 1000); last = now;
  const t = (now - t0) / 1000;
  if (flight && !fp) {
    const k = Math.min(1, (now - flight.t0) / flight.ms), s = k * k * (3 - 2 * k);
    camera.position.lerpVectors(flight.from, flight.to, s); controls.target.lerpVectors(flight.a, flight.b, s);
    if (k >= 1) flight = null;
  }
  if (fp) updateWalk(dt); else controls.update();
  const animating = new Set();
  for (let i = anims.length - 1; i >= 0; i--) {
    const an = anims[i], s = (now - an.t0) / an.dur;
    if (s < 0) continue;
    an.step(Math.min(1, s)); if (s >= 1) anims.splice(i, 1);
  }
  for (const an of anims) animating.add(an);
  for (const g of furnitureGroups.values()) g.userData.info.animate?.(t);
  if (!anims.length) for (const g of items.children) {
    const lift = g.userData.lift; if (!lift || drag?.id === g.userData.assetId) continue;
    lift.scale.lerp(g.userData.assetId === hovered && !arranging ? big : one, 0.15);
  }
  if (selected) { const ring = groupOf(selected)?.userData.ring; if (ring) ring.material.opacity = 0.55 + Math.sin(now / 260) * 0.35; }
  env?.update?.(t);
  renderer.render(scene, camera);
}
soundToggle();
if (readOnly) { $("open-shelf").hidden = true; $("open-workbench").hidden = true; }
load().then(() => requestAnimationFrame(frame)).catch(error => {
  console.error(error);
  $("scene-reason").textContent = "没能读到小岛的资产。请确认本机服务在运行，再刷新这一页。";
});
window.__palace = { get defaults() { return defaults; }, get current() { return current; }, get assets() { return assets; }, get saved() { return saved; }, get fp() { return fp; },
  items, furnitureGroups, renderer, camera, controls, select, setScene, enterWalk, leaveWalk, toggleShelf, blocked };
