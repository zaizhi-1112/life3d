// 代码生成的海：几组 Gerstner 波叠在一起，顶点在着色器里起伏；
// 浪尖发亮，靠岸处一圈圈白沫。JS 里的 waveHeight 与着色器同一套公式，船可以跟着浪起伏。
import * as THREE from "three";

const WAVES = [
  // 方向 x, z, 波长, 振幅, 陡度, 速度倍数
  [1.0, 0.25, 22, 0.22, 0.55, 1.0],
  [-0.35, 1.0, 13, 0.13, 0.5, 1.1],
  [0.7, -0.7, 7.5, 0.07, 0.45, 1.25],
  [-0.9, -0.3, 4.2, 0.035, 0.4, 1.4],
];
const G = 9.8;

function prepared() {
  return WAVES.map(([dx, dz, L, A, Q, s]) => {
    const len = Math.hypot(dx, dz), k = 2 * Math.PI / L;
    return { dx: dx / len, dz: dz / len, k, A, Q, c: Math.sqrt(G / k) * 0.55 * s };
  });
}

export function createOcean({ size = 520, segments = 300, level = -0.35, shore = 60, shoreWidth = 7,
  deep = "#24284a", shallow = "#5f7fa3", crest = "#f3d9c4", foam = "#fff3e6", calm = 1 } = {}) {
  const waves = prepared();
  const geometry = new THREE.PlaneGeometry(size, size, segments, segments);
  geometry.rotateX(-Math.PI / 2);
  const uniforms = {
    uTime: { value: 0 }, uShore: { value: shore }, uShoreWidth: { value: shoreWidth }, uCalm: { value: calm },
    uDeep: { value: new THREE.Color(deep) }, uShallow: { value: new THREE.Color(shallow) },
    uCrest: { value: new THREE.Color(crest) }, uFoam: { value: new THREE.Color(foam) },
  };
  const material = new THREE.MeshStandardMaterial({ color: deep, roughness: 0.16, metalness: 0.05, transparent: true, opacity: 0.96 });
  const decl = waves.map((w, i) => `const vec4 W${i} = vec4(${w.dx.toFixed(4)}, ${w.dz.toFixed(4)}, ${w.k.toFixed(4)}, ${w.c.toFixed(4)});
    const vec2 P${i} = vec2(${w.A.toFixed(4)}, ${w.Q.toFixed(4)});`).join("\n");
  const sum = waves.map((_, i) => `gerstner(W${i}, P${i}, p, t, amp, disp, nrm);`).join("\n");
  material.onBeforeCompile = shader => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", `#include <common>
        uniform float uTime; uniform float uShore; uniform float uShoreWidth; uniform float uCalm;
        varying float vLift; varying vec2 vPlane;
        ${decl}
        void gerstner(vec4 w, vec2 pa, vec2 p, float t, float amp, inout vec3 disp, inout vec3 nrm){
          float f = w.z * (dot(w.xy, p) - w.w * t);
          float a = pa.x * amp, c = cos(f), s = sin(f);
          disp += vec3(pa.y * a * w.x * c, a * s, pa.y * a * w.y * c);
          nrm -= vec3(w.x * w.z * a * c, pa.y * w.z * a * s, w.y * w.z * a * c);
        }`)
      .replace("#include <beginnormal_vertex>", `
        vec2 p = (modelMatrix * vec4(position, 1.0)).xz;
        float r = length(p);
        float amp = uCalm * mix(0.35, 1.0, smoothstep(uShore - 2.0, uShore + 18.0, r)) * (1.0 - smoothstep(180.0, 255.0, r));
        float t = uTime;
        vec3 disp = vec3(0.0), nrm = vec3(0.0, 1.0, 0.0);
        ${sum}
        vec3 objectNormal = normalize(nrm);
        #ifdef USE_TANGENT
          vec3 objectTangent = vec3(tangent.xyz);
        #endif`)
      .replace("#include <begin_vertex>", `vec3 transformed = position + disp; vLift = disp.y; vPlane = p;`);
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", `#include <common>
        uniform float uTime; uniform float uShore; uniform float uShoreWidth;
        uniform vec3 uDeep; uniform vec3 uShallow; uniform vec3 uCrest; uniform vec3 uFoam;
        varying float vLift; varying vec2 vPlane;`)
      .replace("#include <color_fragment>", `#include <color_fragment>
        float r = length(vPlane);
        float near = 1.0 - smoothstep(uShore, uShore + uShoreWidth * 2.6, r);
        vec3 water = mix(uDeep, uShallow, near * 0.85 + 0.12);
        water = mix(water, uCrest, smoothstep(0.24, 0.46, vLift) * 0.16);
        float band = sin(r * 2.4 - uTime * 1.6 + sin(atan(vPlane.y, vPlane.x) * 7.0) * 0.6);
        float foamLine = smoothstep(0.82, 1.0, band) * (1.0 - smoothstep(uShore - 1.0, uShore + uShoreWidth, r)) * step(uShore - 2.5, r);
        float edge = 1.0 - smoothstep(uShore - 1.4, uShore + 0.8, r);
        water = mix(water, uFoam, clamp(foamLine * 0.75 + edge * 0.55, 0.0, 0.9));
        diffuseColor.rgb = water;`)
      .replace("#include <normal_fragment_maps>", `#include <normal_fragment_maps>
        {
          vec2 q = vPlane * 0.9;
          float tt = uTime * 1.3;
          vec2 ripple = vec2(sin(q.x * 3.1 + tt) + sin(q.y * 2.3 - tt * 1.2 + q.x * 0.7),
                             cos(q.y * 3.4 - tt * 0.9) + cos(q.x * 2.7 + q.y * 1.1 + tt * 1.1)) * 0.035;
          ripple += vec2(sin(q.x * 9.0 + q.y * 4.0 - tt * 2.0), cos(q.y * 8.0 - q.x * 3.0 + tt * 1.7)) * 0.015;
          normal = normalize(normal + (viewMatrix * vec4(ripple.x, 0.0, ripple.y, 0.0)).xyz);
        }`)
      .replace("#include <emissivemap_fragment>", `#include <emissivemap_fragment>
        totalEmissiveRadiance += uCrest * smoothstep(0.3, 0.5, vLift) * 0.03;`);
  };
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.y = level;
  mesh.receiveShadow = true;
  // 远处一圈平静的海，接到地平线
  const far = new THREE.Mesh(new THREE.RingGeometry(size * 0.47, 1100, 64, 1), new THREE.MeshStandardMaterial({ color: deep, roughness: 0.25 }));
  far.rotation.x = -Math.PI / 2; far.position.y = level - 0.02;
  const group = new THREE.Group(); group.add(mesh, far);
  return {
    group, uniforms,
    update(t) { uniforms.uTime.value = t; },
    height(x, z, t = uniforms.uTime.value) {
      const r = Math.hypot(x, z);
      const smooth = e => { const k = Math.min(1, Math.max(0, e)); return k * k * (3 - 2 * k); };
      const amp = uniforms.uCalm.value * (0.35 + 0.65 * smooth((r - shore + 2) / 20));
      let y = 0;
      for (const w of waves) y += w.A * amp * Math.sin(w.k * (w.dx * x + w.dz * z - w.c * t));
      return level + y;
    },
    tilt(x, z, t = uniforms.uTime.value) {
      const e = 0.6, h = this.height.bind(this);
      return { x: (h(x, z + e, t) - h(x, z - e, t)) / (2 * e), z: -(h(x + e, z, t) - h(x - e, z, t)) / (2 * e) };
    },
  };
}
