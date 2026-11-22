// 记忆宫殿的家具和摆设：全部用代码生成，每件都是可以在资产管理里移动、转向、缩放、收起的资产。
// 每个 build 在本地坐标里搭（原点在地面中心，正面朝 +z），返回可摆东西的槽位和占地半宽。
import * as THREE from "three";
import { buildTree } from "./nice-props.js";

const materials = new Map();
export function mat(color, { rough = 0.82, metal = 0, emissive = null, glow = 0, opacity = 1 } = {}) {
  const key = [color, rough, metal, emissive, glow, opacity].join("|");
  if (!materials.has(key)) {
    const m = new THREE.MeshStandardMaterial({ color, roughness: rough, metalness: metal });
    if (emissive) { m.emissive = new THREE.Color(emissive); m.emissiveIntensity = glow; }
    if (opacity < 1) { m.transparent = true; m.opacity = opacity; m.depthWrite = false; }
    materials.set(key, m);
  }
  return materials.get(key);
}
export const resin = new THREE.MeshStandardMaterial({ color: "#efe6d6", roughness: 0.55 });

// surface=true 的面可以摆东西（拖动时用它们找落点）
export function kit(root, surfaces) {
  const add = (geo, color, x, y, z, { surface = false, shadow = true, ry = 0, rz = 0, material = null } = {}) => {
    const mesh = new THREE.Mesh(geo, material || mat(color));
    mesh.position.set(x, y, z); mesh.rotation.y = ry; mesh.rotation.z = rz;
    mesh.castShadow = shadow; mesh.receiveShadow = true;
    if (surface) surfaces.push(mesh);
    root.add(mesh);
    return mesh;
  };
  return {
    add,
    box: (w, h, d, color, x, y, z, o) => add(new THREE.BoxGeometry(w, h, d), color, x, y, z, o),
    cyl: (rt, rb, h, color, x, y, z, o = {}) => add(new THREE.CylinderGeometry(rt, rb, h, o.seg || 24), color, x, y, z, o),
    ball: (r, color, x, y, z, o = {}) => add(new THREE.IcosahedronGeometry(r, o.detail ?? 1), color, x, y, z, o),
  };
}

const wood = "#8a5d40", dark = "#6e4a35", spines = ["#7d5a8c", "#b9734f", "#5f7d75", "#d8b07a", "#8b4f4f", "#4e5f80", "#c9b08a"];
const row = (n, from, to) => Array.from({ length: n }, (_, i) => from + (to - from) * (i + 0.5) / n);

export const FURNITURE = {
  // ---------- 小屋 ----------
  bookcase: { title: "书架", scene: "room", build(k) {
    const L = 3.6, boards = [0.06, 0.66, 1.26, 1.86, 2.46];
    k.box(0.05, 2.5, 0.44, wood, -L / 2, 1.25, 0); k.box(0.05, 2.5, 0.44, wood, L / 2, 1.25, 0);
    k.box(L, 2.46, 0.03, "#7b5239", 0, 1.23, -0.21, { shadow: false });
    for (const y of boards) k.box(L, 0.04, 0.44, wood, 0, y, 0, { surface: true });
    boards.forEach((y, r) => {
      let x = -L / 2 + 0.05;
      for (let i = 0; i < 6 + (r % 3); i++) {
        const w = 0.045 + ((i * 7 + r * 3) % 5) * 0.012, h = 0.24 + ((i * 5 + r) % 4) * 0.035;
        k.box(w, h, 0.26, spines[(i + r * 2) % spines.length], x + w / 2, y + 0.02 + h / 2, -0.02, { shadow: false });
        x += w + 0.006;
      }
    });
    return { half: [L / 2, 0.24], slots: { bookcase: [1, 2, 0, 3].flatMap(b => row(5, -L / 2 + 0.85, L / 2 - 0.1).map(x => [x, boards[b] + 0.02, 0.02])) } };
  } },
  wallshelf: { title: "展示墙", scene: "room", build(k, night) {
    const L = 3.2, boards = [0.5, 1.0, 1.5, 2.0, 2.5];
    k.box(L + 0.1, 2.75, 0.04, "#d9c3a5", 0, 1.43, -0.17, { shadow: false });
    for (const y of boards) {
      k.box(L, 0.05, 0.36, "#9a6b4a", 0, y, 0, { surface: true });
      k.box(L, 0.012, 0.012, "#d8b27e", 0, y + 0.02, 0.18, { shadow: false });
      k.box(L - 0.1, 0.01, 0.02, "#ffd9a0", 0, y - 0.03, 0.12, { material: mat("#ffe2b0", { emissive: "#ffc77d", glow: night ? 1.6 : 0.5 }), shadow: false });
    }
    k.box(0.06, 2.8, 0.38, wood, -L / 2, 1.4, 0); k.box(0.06, 2.8, 0.38, wood, L / 2, 1.4, 0);
    return { half: [L / 2 + 0.05, 0.2], slots: { wallshelf: [1, 2, 3, 0, 4].flatMap(b => row(5, -L / 2 + 0.1, L / 2 - 0.1).map(x => [x, boards[b] + 0.025, 0.02])) } };
  } },
  desk: { title: "窗边书桌", scene: "room", build(k, night) {
    const top = 0.78;
    k.box(2.4, 0.06, 0.8, wood, 0, top - 0.03, 0, { surface: true });
    for (const sx of [-1.12, 1.12]) for (const sz of [-0.33, 0.33]) k.box(0.06, top - 0.06, 0.06, dark, sx, (top - 0.06) / 2, sz);
    k.box(0.5, 0.05, 0.48, "#c58a63", -0.3, 0.47, 0.85); k.box(0.5, 0.55, 0.05, "#c58a63", -0.3, 0.75, 1.08);
    for (const sx of [-0.21, 0.21]) for (const sz of [-0.2, 0.2]) k.box(0.04, 0.45, 0.04, dark, -0.3 + sx, 0.225, 0.85 + sz);
    k.cyl(0.1, 0.12, 0.03, dark, -0.95, top + 0.015, -0.15);
    k.cyl(0.012, 0.012, 0.42, dark, -0.95, top + 0.22, -0.15);
    k.add(new THREE.ConeGeometry(0.15, 0.17, 20, 1, true), "#f6dfb4", -0.95, top + 0.46, -0.15, { material: mat("#f6dfb4", { emissive: "#ffcf87", glow: night ? 1.4 : 0.3 }), shadow: false });
    const light = new THREE.PointLight("#ffc98a", night ? 2.4 : 0.6, 3, 2); light.position.set(-0.95, top + 0.4, -0.1); k.add.parent?.add(light);
    return { half: [1.2, 0.45], light, slots: { desk: [[-0.45, top, 0.02], [0.25, top, 0.02], [0.9, top, 0.02]] } };
  } },
  vitrine: { title: "实物陈列柜", scene: "room", build(k, night) {
    const w = 1.6, d = 0.55, shelves = [0.62, 1.07, 1.52];
    k.box(w, 0.55, d, "#7a5843", 0, 0.275, 0);
    k.box(w, 0.06, d, "#5c4130", 0, 1.98, 0);
    for (const sx of [-w / 2, w / 2]) for (const sz of [-d / 2, d / 2]) k.box(0.04, 1.45, 0.04, "#5c4130", sx, 1.27, sz);
    k.box(w, 1.42, 0.02, "#d9c3a5", 0, 1.27, -d / 2 + 0.02, { shadow: false });
    const glass = mat("#dfe9ef", { rough: 0.05, opacity: 0.16 });
    k.box(w - 0.04, 1.42, 0.01, "#fff", 0, 1.27, d / 2, { material: glass, shadow: false });
    k.box(0.01, 1.42, d - 0.04, "#fff", -w / 2, 1.27, 0, { material: glass, shadow: false });
    k.box(0.01, 1.42, d - 0.04, "#fff", w / 2, 1.27, 0, { material: glass, shadow: false });
    for (const y of shelves) k.box(w - 0.06, 0.02, d - 0.06, "#e8eef0", 0, y, 0, { surface: true, material: mat("#e9f0f2", { rough: 0.1, opacity: 0.55 }) });
    k.box(w - 0.1, 0.02, 0.04, "#ffe2b0", 0, 1.94, 0.1, { material: mat("#ffe2b0", { emissive: "#ffd08a", glow: 1.4 }), shadow: false });
    const light = new THREE.PointLight("#ffe0b0", night ? 1.8 : 0.8, 2.4, 2); light.position.set(0, 1.85, 0.1);
    k.add.parent?.add(light);
    return { half: [w / 2, d / 2], light, slots: { vitrine: shelves.flatMap(y => [-0.38, 0.38].map(x => [x, y + 0.012, 0.02])) } };
  } },
  cabinet: { title: "矮柜", scene: "room", build(k) {
    k.box(2.5, 0.82, 0.52, "#a8765a", 0, 0.41, 0);
    k.box(2.56, 0.04, 0.56, wood, 0, 0.84, 0, { surface: true });
    for (const dx of [-0.62, 0.62]) {
      k.box(1.14, 0.62, 0.02, "#b98a6c", dx, 0.42, 0.27, { shadow: false });
      k.box(0.12, 0.03, 0.03, "#d8b27e", dx + (dx < 0 ? 0.42 : -0.42), 0.46, 0.29, { shadow: false });
    }
    return { half: [1.28, 0.28], slots: { cabinet: row(4, -1.2, 1.2).map(x => [x, 0.86, 0]) } };
  } },
  printer: { title: "3D 打印机", scene: "room", build(k, night) {
    k.box(1.15, 0.64, 0.82, "#7a5843", 0, 0.32, 0);
    k.box(1.17, 0.04, 0.84, "#5c4130", 0, 0.66, 0);
    const shell = "#2f3038", top = 0.68;
    for (const [sx, sz] of [[-0.31, -0.31], [0.31, -0.31], [-0.31, 0.31], [0.31, 0.31]]) k.box(0.05, 0.72, 0.05, shell, sx, top + 0.36, sz);
    k.box(0.68, 0.1, 0.68, shell, 0, top + 0.05, 0); k.box(0.68, 0.06, 0.68, shell, 0, top + 0.72, 0);
    k.box(0.6, 0.6, 0.02, shell, 0, top + 0.4, -0.32);
    const glass = mat("#d8e2ea", { rough: 0.1, opacity: 0.18 });
    k.box(0.58, 0.6, 0.01, "#fff", 0, top + 0.4, 0.33, { material: glass, shadow: false });
    k.box(0.01, 0.6, 0.58, "#fff", 0.33, top + 0.4, 0, { material: glass, shadow: false });
    k.box(0.46, 0.02, 0.46, "#9a948c", 0, top + 0.12, 0, { shadow: false });
    k.cyl(0.07, 0.09, 0.1, "#efe6d6", 0.02, top + 0.18, 0.02, { material: resin });
    k.ball(0.06, "#efe6d6", 0.02, top + 0.26, 0.02, { material: resin });
    const gantry = k.box(0.56, 0.025, 0.04, "#8f8a92", 0, top + 0.52, 0, { shadow: false });
    const nozzle = k.box(0.08, 0.09, 0.08, "#d9d4cc", 0.06, top + 0.47, 0, { shadow: false });
    k.box(0.16, 0.07, 0.02, "#9fd3a8", 0.18, top + 0.06, 0.345, { material: mat("#9fd3a8", { emissive: "#7fcf91", glow: 0.9 }), shadow: false });
    k.cyl(0.02, 0.02, 0.12, shell, -0.4, top + 0.55, 0, { seg: 8, rz: Math.PI / 2 });
    k.cyl(0.17, 0.17, 0.07, "#d98b5f", -0.48, top + 0.55, 0, { seg: 28, rz: Math.PI / 2 });
    k.cyl(0.07, 0.07, 0.08, "#efe6d6", -0.48, top + 0.55, 0, { seg: 16, rz: Math.PI / 2 });
    const light = new THREE.PointLight("#ffd29a", night ? 1.6 : 0.6, 1.4, 2); light.position.set(0, top + 0.6, 0);
    k.add.parent?.add(light);
    return { half: [0.6, 0.42], light, printer: true, animate: t => { nozzle.position.x = Math.sin(t * 2.2) * 0.18; nozzle.position.z = Math.cos(t * 1.3) * 0.12; gantry.position.z = nozzle.position.z; } };
  } },
  sofa: { title: "沙发", scene: "room", build(k) {
    const c = "#7d8f86", d = "#6f8178";
    k.box(2.6, 0.38, 0.95, c, 0, 0.24, 0); k.box(2.6, 0.75, 0.22, d, 0, 0.6, -0.38);
    k.box(0.22, 0.6, 0.95, d, -1.3, 0.38, 0); k.box(0.22, 0.6, 0.95, d, 1.3, 0.38, 0);
    for (const x of [-0.62, 0.62]) k.box(1.18, 0.12, 0.72, "#a6b4ab", x, 0.48, 0.06);
    k.box(0.4, 0.34, 0.12, "#d9a88f", -0.85, 0.7, -0.22, { rz: 0.15 }); k.box(0.4, 0.34, 0.12, "#e3c48e", 0.85, 0.7, -0.22, { rz: -0.15 });
    return { half: [1.42, 0.5] };
  } },
  armchair: { title: "扶手椅", scene: "room", build(k) {
    k.box(0.95, 0.38, 0.85, "#c98f7c", 0, 0.24, 0); k.box(0.95, 0.75, 0.2, "#b97d6b", 0, 0.62, -0.36);
    k.box(0.18, 0.55, 0.85, "#b97d6b", -0.48, 0.38, 0); k.box(0.18, 0.55, 0.85, "#b97d6b", 0.48, 0.38, 0);
    k.box(0.6, 0.1, 0.6, "#e0b4a2", 0, 0.47, 0.05);
    return { half: [0.57, 0.46] };
  } },
  coffee: { title: "圆茶几", scene: "room", build(k) {
    k.cyl(0.62, 0.62, 0.05, "#8f6044", 0, 0.47, 0, { seg: 36, surface: true });
    k.cyl(0.07, 0.11, 0.44, dark, 0, 0.22, 0, { seg: 14 });
    k.cyl(0.32, 0.36, 0.03, dark, 0, 0.015, 0, { seg: 24 });
    return { half: [0.62, 0.62], slots: { featured: [[0, 0.495, 0]] } };
  } },
  rug: { title: "圆地毯", scene: "room", build(k) {
    k.cyl(2.6, 2.6, 0.02, "#c98f7c", 0, 0.01, 0, { seg: 56, shadow: false, surface: true });
    k.cyl(2.05, 2.05, 0.022, "#d9a88f", 0, 0.012, 0, { seg: 56, shadow: false, surface: true });
    k.cyl(1.2, 1.2, 0.024, "#e5bba3", 0, 0.013, 0, { seg: 48, shadow: false, surface: true });
    return { half: [2.6, 2.6], walkable: true, flat: true };
  } },
  floorlamp: { title: "落地灯", scene: "room", build(k, night) {
    k.cyl(0.18, 0.2, 0.03, dark, 0, 0.015, 0); k.cyl(0.018, 0.018, 1.55, dark, 0, 0.78, 0);
    k.add(new THREE.CylinderGeometry(0.2, 0.3, 0.32, 24, 1, true), "#f3dfba", 0, 1.62, 0, { material: mat("#f3dfba", { emissive: "#ffc77a", glow: night ? 1.2 : 0.25 }), shadow: false });
    const light = new THREE.PointLight("#ffc98a", night ? 5 : 1, 5, 2); light.position.set(0, 1.6, 0);
    k.add.parent?.add(light);
    return { half: [0.2, 0.2], light };
  } },
  plant: { title: "绿植", scene: "room", build(k) {
    k.cyl(0.24, 0.18, 0.42, "#c1785b", 0, 0.21, 0);
    for (const [dx, dy, dz, r] of [[0, 0.75, 0, 0.36], [0.18, 1.0, 0.1, 0.28], [-0.16, 0.95, -0.08, 0.26], [0.02, 1.2, 0.02, 0.2]]) k.ball(r, "#6f8c5f", dx, dy, dz, { detail: 0 });
    return { half: [0.3, 0.3] };
  } },
  pedestal: { title: "展台", scene: "room", build(k) {
    k.box(0.56, 0.06, 0.56, "#cfc4b2", 0, 0.03, 0); k.box(0.46, 0.84, 0.46, "#e2d9c9", 0, 0.48, 0);
    k.box(0.56, 0.05, 0.56, "#cfc4b2", 0, 0.925, 0, { surface: true });
    return { half: [0.28, 0.28], slots: { pedestal: [[0, 0.95, 0]] } };
  } },
  sidetable: { title: "小边桌", scene: "room", build(k) {
    k.cyl(0.32, 0.32, 0.04, "#9a6b4a", 0, 0.56, 0, { seg: 28, surface: true });
    for (let i = 0; i < 3; i++) { const a = i / 3 * Math.PI * 2; k.box(0.03, 0.56, 0.03, dark, Math.cos(a) * 0.22, 0.28, Math.sin(a) * 0.22); }
    return { half: [0.32, 0.32], slots: { side: [[0, 0.58, 0]] } };
  } },

  // ---------- 花园 ----------
  gplinth: { title: "石台", scene: "garden", build(k) {
    k.cyl(0.26, 0.31, 0.46, "#ddd4c5", 0, 0.23, 0, { seg: 20 });
    k.cyl(0.32, 0.32, 0.05, "#cdc2b0", 0, 0.485, 0, { seg: 20, surface: true });
    return { half: [0.32, 0.32], slots: { gplinth: [[0, 0.51, 0]] } };
  } },
  pergola: { title: "凉亭", scene: "garden", build(k, night) {
    k.cyl(1.45, 1.55, 0.3, "#d2c8b6", 0, 0.15, 0, { seg: 40, surface: true });
    k.cyl(0.44, 0.5, 0.7, "#e2d9c9", 0, 0.65, 0, { seg: 28 });
    k.cyl(0.5, 0.5, 0.05, "#cfc4b2", 0, 1.02, 0, { seg: 28, surface: true });
    for (const [sx, sz] of [[-1.15, -1.15], [1.15, -1.15], [-1.15, 1.15], [1.15, 1.15]]) k.box(0.13, 2.6, 0.13, "#8f6447", sx, 1.6, sz);
    for (const sz of [-1.15, 1.15]) k.box(2.6, 0.1, 0.14, "#7d553b", 0, 2.95, sz);
    for (let i = -5; i <= 5; i++) k.box(0.08, 0.06, 2.7, "#8f6447", i * 0.24, 3.03, 0);
    const bulbs = mat("#ffe1a8", { emissive: "#ffc46b", glow: night ? 2.2 : 0.8 });
    for (let i = 0; i < 14; i++) { const a = i / 13; k.ball(0.035, "#ffd59a", -1.15 + a * 2.3, 2.82 - Math.sin(a * Math.PI) * 0.18, 1.15, { material: bulbs, shadow: false, detail: 0 }); }
    return { half: [0.55, 0.55], slots: { featured: [[0, 1.045, 0]] } };
  } },
  bench: { title: "长椅", scene: "garden", build(k) {
    k.box(1.6, 0.06, 0.5, "#9a6c4a", 0, 0.46, 0, { surface: true }); k.box(1.6, 0.4, 0.05, "#9a6c4a", 0, 0.75, -0.24);
    for (const sx of [-0.7, 0.7]) k.box(0.07, 0.46, 0.44, "#5f4535", sx, 0.23, 0);
    return { half: [0.82, 0.3], slots: { bench: [[0.45, 0.49, 0.02]] } };
  } },
  lantern: { title: "路灯", scene: "garden", build(k, night) {
    k.box(0.06, 1.0, 0.06, "#4f3c32", 0, 0.5, 0);
    k.box(0.2, 0.24, 0.2, "#ffd59a", 0, 1.08, 0, { material: mat("#ffe0a8", { emissive: "#ffb85c", glow: night ? 2.2 : 0.6 }), shadow: false });
    k.box(0.26, 0.04, 0.26, "#4f3c32", 0, 1.22, 0);
    return { half: [0.12, 0.12] };
  } },
  tree: { title: "树", scene: "garden", build(k, night, seed = 0) {
    const kinds = ["tree_round", "tree_autumn", "tree_round_b", "tree_pine", "tree_round"];
    const tree = buildTree(kinds[seed % kinds.length], 30 + seed * 7);
    const box = new THREE.Box3().setFromObject(tree), h = box.max.y - box.min.y;
    tree.scale.setScalar(3.4 / h);
    tree.traverse(m => { if (m.isMesh) { m.castShadow = true; m.receiveShadow = true; } });
    k.add.parent?.add(tree);
    return { half: [0.3, 0.3] };
  } },
  flowerbed: { title: "花坛", scene: "garden", build(k, night, seed = 0) {
    const petals = ["#d98b7a", "#e8c07a", "#b9a3d0", "#f0e2c8", "#e2a1a8"];
    k.add(new THREE.TorusGeometry(0.95, 0.07, 6, 28).rotateX(Math.PI / 2), "#bdb2a0", 0, 0.05, 0, { shadow: false });
    k.cyl(0.92, 0.92, 0.06, "#6d5440", 0, 0.03, 0, { seg: 28, shadow: false, surface: true });
    let s = seed * 97 + 13; const rand = () => (s = (s * 16807) % 2147483647) / 2147483647;
    const flowers = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(0.08, 0), new THREE.MeshStandardMaterial({ roughness: 0.8 }), 30);
    const leaves = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(0.15, 0), mat("#64804f"), 16);
    const m = new THREE.Matrix4();
    for (let i = 0; i < 30; i++) {
      const r = 0.42 + rand() * 0.45, a = rand() * Math.PI * 2;
      m.makeTranslation(Math.cos(a) * r, 0.12 + rand() * 0.12, Math.sin(a) * r); flowers.setMatrixAt(i, m);
      flowers.setColorAt(i, new THREE.Color(petals[(i + seed) % petals.length]));
    }
    for (let i = 0; i < 16; i++) { const r = 0.4 + rand() * 0.45, a = rand() * Math.PI * 2; m.makeTranslation(Math.cos(a) * r, 0.08, Math.sin(a) * r); leaves.setMatrixAt(i, m); }
    k.add.parent?.add(flowers, leaves);
    return { half: [0.25, 0.25], slots: { bed: [[0, 0.06, 0]] } };
  } },
  arch: { title: "入口拱门", scene: "garden", build(k) {
    for (const sx of [-1.05, 1.05]) k.box(0.16, 2.3, 0.16, "#9a6c4a", sx, 1.15, 0);
    k.box(2.5, 0.14, 0.24, "#8a5d40", 0, 2.32, 0); k.box(2.2, 0.1, 0.16, "#8a5d40", 0, 2.1, 0);
    const canvas = document.createElement("canvas"); canvas.width = 256; canvas.height = 64;
    const ctx = canvas.getContext("2d"); ctx.fillStyle = "#ead9b9"; ctx.fillRect(0, 0, 256, 64);
    ctx.fillStyle = "#6b4a34"; ctx.font = "36px 'Songti SC', serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("记 忆 花 园", 128, 34);
    const t = new THREE.CanvasTexture(canvas); t.colorSpace = THREE.SRGBColorSpace;
    k.add(new THREE.PlaneGeometry(1.5, 0.38), "#fff", 0, 1.86, 0.02, { material: new THREE.MeshStandardMaterial({ map: t, side: THREE.DoubleSide, roughness: 0.9 }), shadow: false });
    return { half: [0.1, 0.1], walkable: true };
  } },
};

export function buildFurniture(type, night, seed = 0) {
  const def = FURNITURE[type], group = new THREE.Group(), surfaces = [];
  const k = kit(group, surfaces);
  k.add.parent = group;
  const info = def.build(k, night, seed) || {};
  group.userData.surfaces = surfaces;
  group.userData.info = info;
  return group;
}
