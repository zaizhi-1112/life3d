// 触控板和键盘的自由浏览：没有鼠标也能想看哪看哪。
// · 双指滑动：平移（像看地图）          · 双指捏合：以光标处为中心放大缩小
// · Shift + 双指滑动：转视角            · 拖动：转视角（OrbitControls 原样处理）
// · Safari 双指旋转手势：转视角          · 鼠标滚轮：缩放
// · 方向键 / WASD：平移，Q / E：转向，+ / -：缩放（仅第三人称，且不在打字时）
// · 双击地面：飞到那里
import * as THREE from "three";

export function trackpad({ controls, camera, dom, active = () => true, onInput = () => {}, clamp = null, keys = true, rotateKeys = () => true }) {
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  const offset = new THREE.Vector3(), hit = new THREE.Vector3(), right = new THREE.Vector3(), forward = new THREE.Vector3();
  let fly = null;

  function groundAt(x, y) {
    const r = dom.getBoundingClientRect();
    ndc.set((x - r.left) / r.width * 2 - 1, -(y - r.top) / r.height * 2 + 1);
    ray.setFromCamera(ndc, camera);
    plane.constant = -controls.target.y;
    return ray.ray.intersectPlane(plane, hit) ? hit.clone() : null;
  }
  function settle() {
    if (clamp) { const before = controls.target.clone(); clamp(controls.target); camera.position.add(controls.target.clone().sub(before)); }
    controls.update();
  }
  function pan(dx, dy) {
    const dist = camera.position.distanceTo(controls.target), k = dist * 0.0016;
    camera.getWorldDirection(forward); forward.y = 0; if (forward.lengthSq() < 1e-6) forward.set(0, 0, -1); forward.normalize();
    right.crossVectors(forward, camera.up).normalize();
    const move = right.multiplyScalar(dx * k).addScaledVector(forward, -dy * k);
    controls.target.add(move); camera.position.add(move); settle();
  }
  function zoom(factor, x, y) {
    offset.copy(camera.position).sub(controls.target);
    const dist = offset.length(), next = THREE.MathUtils.clamp(dist * factor, controls.minDistance, controls.maxDistance), f = next / dist;
    const point = x === undefined ? null : groundAt(x, y);
    if (point && point.distanceTo(controls.target) < dist * 3) controls.target.lerp(point, 1 - f);
    camera.position.copy(controls.target).addScaledVector(offset, f); settle();
  }
  function rotate(dAzimuth, dPolar) {
    offset.copy(camera.position).sub(controls.target);
    const s = new THREE.Spherical().setFromVector3(offset);
    s.theta -= dAzimuth;
    s.phi = THREE.MathUtils.clamp(s.phi - dPolar, Math.max(0.05, controls.minPolarAngle), Math.min(Math.PI - 0.05, controls.maxPolarAngle));
    if (Number.isFinite(controls.minAzimuthAngle) && Number.isFinite(controls.maxAzimuthAngle)) s.theta = THREE.MathUtils.clamp(s.theta, controls.minAzimuthAngle, controls.maxAzimuthAngle);
    offset.setFromSpherical(s); camera.position.copy(controls.target).add(offset); settle();
  }

  // 抢在 OrbitControls 之前接管滚轮：它只会把滚轮当缩放
  dom.addEventListener("wheel", e => {
    if (!active() || !controls.enabled) return;
    e.preventDefault(); e.stopImmediatePropagation();
    fly = null; onInput();
    const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1, dx = e.deltaX * unit, dy = e.deltaY * unit;
    const mouseWheel = e.deltaMode !== 0 || (dx === 0 && Math.abs(dy) >= 40 && Number.isInteger(dy));
    if (e.ctrlKey || e.metaKey) zoom(Math.exp(dy * 0.012), e.clientX, e.clientY);        // 触控板捏合（浏览器会带上 ctrl）
    else if (mouseWheel) zoom(Math.exp(dy * 0.0016), e.clientX, e.clientY);
    else if (e.shiftKey) rotate(dx * 0.004, dy * 0.003);
    else pan(dx, dy);
  }, { capture: true, passive: false });

  // Safari 的手势事件：捏合缩放、双指旋转
  let lastScale = 1, lastRotation = 0;
  dom.addEventListener("gesturestart", e => { if (!active()) return; e.preventDefault(); lastScale = 1; lastRotation = 0; onInput(); });
  dom.addEventListener("gesturechange", e => {
    if (!active() || !controls.enabled) return;
    e.preventDefault();
    zoom(lastScale / e.scale, e.clientX, e.clientY); lastScale = e.scale;
    rotate((e.rotation - lastRotation) * Math.PI / 180, 0); lastRotation = e.rotation;
  });

  // 双击地面：飞过去
  dom.addEventListener("dblclick", e => {
    if (!active() || !controls.enabled) return;
    const point = groundAt(e.clientX, e.clientY); if (!point) return;
    onInput();
    offset.copy(camera.position).sub(controls.target).multiplyScalar(0.7);
    fly = { t0: performance.now(), fromT: controls.target.clone(), toT: point, fromC: camera.position.clone(), toC: point.clone().add(offset) };
    if (clamp) clamp(fly.toT);
  });

  const held = new Set();
  if (keys) {
    addEventListener("keydown", e => {
      if (e.target.closest?.("input, textarea, select, [contenteditable], dialog") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (!active() || !controls.enabled) return;
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "w", "a", "s", "d", "q", "e", "+", "=", "-", "_"].includes(key)) {
        if (["q", "e"].includes(key) && !rotateKeys()) return;
        held.add(key); if (key.startsWith("Arrow")) e.preventDefault(); onInput();
      }
    });
    addEventListener("keyup", e => held.delete(e.key.length === 1 ? e.key.toLowerCase() : e.key));
    addEventListener("blur", () => held.clear());
  }

  return {
    // 每帧调用：处理按住的键和双击飞行
    update(dt) {
      if (fly) {
        const k = Math.min(1, (performance.now() - fly.t0) / 700), s = k * k * (3 - 2 * k);
        controls.target.lerpVectors(fly.fromT, fly.toT, s); camera.position.lerpVectors(fly.fromC, fly.toC, s); controls.update();
        if (k >= 1) fly = null;
      }
      if (!held.size || !active() || !controls.enabled) return;
      const step = 600 * dt;
      const h = k => held.has(k);
      const x = (h("ArrowRight") || h("d") ? 1 : 0) - (h("ArrowLeft") || h("a") ? 1 : 0);
      const y = (h("ArrowDown") || h("s") ? 1 : 0) - (h("ArrowUp") || h("w") ? 1 : 0);
      if (x || y) pan(x * step, y * step);
      const turn = (h("e") ? 1 : 0) - (h("q") ? 1 : 0);
      if (turn) rotate(turn * 1.6 * dt, 0);
      const z = (h("-") || h("_") ? 1 : 0) - (h("+") || h("=") ? 1 : 0);
      if (z) zoom(Math.exp(z * 1.4 * dt));
    },
    cancel() { fly = null; held.clear(); },
  };
}
