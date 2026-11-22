"use strict";

(() => {
  const vertexShader = `
    attribute vec3 position;
    uniform vec3 center;
    uniform float radius;
    uniform vec4 rotation;
    uniform vec2 scale;
    uniform vec2 pan;
    varying vec3 surface;
    void main() {
      vec3 p = (position - center) / radius;
      float x = rotation.x * p.x - rotation.y * p.y;
      float y = rotation.y * p.x + rotation.x * p.y;
      surface = vec3(x, rotation.w * y + rotation.z * p.z, -rotation.z * y + rotation.w * p.z);
      gl_Position = vec4(surface.xy * scale + pan, -0.9 * surface.z, 1.);
    }`;
  const fragmentShader = `
    #extension GL_OES_standard_derivatives : enable
    precision highp float;
    varying vec3 surface;
    void main() {
      vec3 n = normalize(cross(dFdx(surface), dFdy(surface)));
      float key = max(dot(n, normalize(vec3(-0.55, 0.75, 0.7))), 0.);
      float fill = max(dot(n, normalize(vec3(0.8, 0.1, 0.4))), 0.);
      float light = 0.46 + 0.47 * key + 0.12 * fill;
      gl_FragColor = vec4(vec3(0.92, 0.84, 0.76) * light, 1.);
    }`;
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

  // Build and release a single on-demand GPU context. Camera movement changes
  // uniforms only; the actual STL vertex buffer stays on the GPU until closed.
  function createRenderer(canvas) {
    const gl = canvas.getContext("webgl", {alpha: true, antialias: true, powerPreference: "low-power"});
    if (!gl) throw new Error("当前浏览器无法开启 3D，可查看预览图或下载 STL。");
    const program = gl.createProgram();
    const buffer = gl.createBuffer();
    const shaders = [];
    function dispose() {
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
      for (const shader of shaders) gl.deleteShader(shader);
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    }
    try {
      if (!gl.getExtension("OES_standard_derivatives")) throw new Error();
      for (const [type, source] of [[gl.VERTEX_SHADER, vertexShader], [gl.FRAGMENT_SHADER, fragmentShader]]) {
        const shader = gl.createShader(type);
        shaders.push(shader);
        gl.shaderSource(shader, source);
        gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error();
        gl.attachShader(program, shader);
      }
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error();
      gl.useProgram(program);
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      const position = gl.getAttribLocation(program, "position");
      gl.enableVertexAttribArray(position);
      gl.vertexAttribPointer(position, 3, gl.FLOAT, false, 0, 0);
      gl.enable(gl.DEPTH_TEST);
      gl.clearColor(0, 0, 0, 0);
    } catch {
      dispose();
      throw new Error("浏览器无法绘制模型，可查看预览图或下载 STL。");
    }
    const uniforms = Object.fromEntries(["center", "radius", "rotation", "scale", "pan"]
      .map((key) => [key, gl.getUniformLocation(program, key)]));
    let vertices = 0;
    return {
      dispose,
      upload(mesh) {
        gl.bufferData(gl.ARRAY_BUFFER, mesh.positions, gl.STATIC_DRAW);
        if (gl.getError() !== gl.NO_ERROR) throw new Error("显存不足，仍可查看预览图或下载 STL。");
        gl.uniform3fv(uniforms.center, mesh.center);
        gl.uniform1f(uniforms.radius, mesh.radius);
        vertices = mesh.positions.length / 3;
      },
      draw({yaw, pitch, zoom, panX, panY}) {
        const w = canvas.clientWidth, h = canvas.clientHeight;
        if (!w || !h || !vertices) return;
        const ratio = Math.min(devicePixelRatio || 1, 2, 2048 / Math.max(w, h));
        const width = Math.max(1, Math.round(w * ratio)), height = Math.max(1, Math.round(h * ratio));
        if (canvas.width !== width || canvas.height !== height) {
          canvas.width = width;
          canvas.height = height;
        }
        gl.viewport(0, 0, width, height);
        const span = Math.min(w, h) * zoom * 0.91;
        gl.uniform4f(uniforms.rotation, Math.cos(yaw), Math.sin(yaw), Math.cos(pitch), Math.sin(pitch));
        gl.uniform2f(uniforms.scale, span / w, span / h);
        gl.uniform2f(uniforms.pan, panX, panY);
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        gl.drawArrays(gl.TRIANGLES, 0, vertices);
      },
    };
  }

  const markup = `
    <div class="orbit-stage"><img class="orbit-poster" decoding="async" alt=""></div>
    <div class="orbit-footer">
      <button type="button" class="orbit-launch" data-action="open">360° 查看模型</button>
      <div class="orbit-toolbar" role="group" aria-label="模型视角" hidden>
        <div class="orbit-modes" role="group" aria-label="拖动方式">
          <button type="button" data-action="pan" aria-pressed="true">平移</button>
          <button type="button" data-action="rotate" aria-pressed="false">旋转</button>
        </div>
        <button type="button" data-action="zoom-out" aria-label="缩小模型" title="缩小">−</button>
        <button type="button" data-action="zoom-in" aria-label="放大模型" title="放大">＋</button>
        <button type="button" data-action="reset">复位</button>
        <button type="button" data-action="close">收起</button>
      </div>
      <a class="orbit-file" download="model.stl" hidden>下载 STL</a>
      <span class="orbit-caption" role="status" hidden></span>
    </div>`;
  const viewHome = () => ({yaw: -0.18, pitch: 0.14, zoom: 1, panX: 0, panY: 0});
  class ModelOrbit extends HTMLElement {
    static get observedAttributes() { return ["src", "poster", "label"]; }

    connectedCallback() {
      if (!this.stage) {
        this.innerHTML = markup;
        this.stage = this.querySelector(".orbit-stage");
        this.poster = this.querySelector(".orbit-poster");
        this.openButton = this.querySelector(".orbit-launch");
        this.toolbar = this.querySelector(".orbit-toolbar");
        this.file = this.querySelector(".orbit-file");
        this.caption = this.querySelector(".orbit-caption");
        this.addEventListener("click", (event) => {
          const action = event.target.closest("button[data-action]")?.dataset.action;
          if (action === "open") {
            if (this.worker) this.close();
            else this.open();
          }
          else if (action === "close") { this.close(); this.openButton.focus(); }
          else if (action === "pan" || action === "rotate") {
            this.setMode(action);
            if (event.detail) this.canvas?.focus({preventScroll: true});
          }
          else if (action === "reset") { this.view = viewHome(); this.redraw(); }
          else if (action === "zoom-in") this.zoomBy(1.3);
          else if (action === "zoom-out") this.zoomBy(1 / 1.3);
        });
      }
      this.syncPoster();
      this.close();
    }

    disconnectedCallback() { this.close(); }

    attributeChangedCallback(name, old, value) {
      if (!this.stage || old === value) return;
      if (name === "src") this.close();
      else this.syncPoster();
    }

    syncPoster() {
      const poster = this.getAttribute("poster");
      if (poster && this.poster.getAttribute("src") !== poster) this.poster.src = poster;
      else if (!poster) this.poster.removeAttribute("src");
      this.poster.alt = (this.getAttribute("label") || "摆件") + "的模型预览";
      if (this.canvas) this.canvas.setAttribute("aria-label", this.canvasLabel());
    }

    canvasLabel() {
      return (this.getAttribute("label") || "摆件") +
        "三维模型。方向键" + (this.mode === "rotate" ? "旋转" : "平移") +
        "，加减键缩放，Home 复位，Esc 收起。";
    }

    setMode(mode) {
      this.mode = mode;
      for (const button of this.toolbar.querySelectorAll(".orbit-modes button")) {
        button.setAttribute("aria-pressed", String(button.dataset.action === mode));
      }
      const touch = matchMedia("(pointer: coarse)").matches;
      if (mode === "pan") this.caption.textContent = touch
        ? "单指拖动平移 · 双指捏合缩放" : "拖动或滚动平移 · 用 ＋ / − 缩放";
      else this.caption.textContent = touch
        ? "单指拖动旋转 · 双指捏合缩放" : "拖动旋转 · 滚动缩放";
      this.canvas?.setAttribute("aria-label", this.canvasLabel());
    }

    close(message = "") {
      clearTimeout(this.loadTimer);
      this.worker?.terminate();
      this.worker = null;
      this.inputs?.abort();
      this.inputs = null;
      this.observer?.disconnect();
      this.observer = null;
      if (this.frame) cancelAnimationFrame(this.frame);
      this.frame = 0;
      this.renderer?.dispose();
      this.renderer = null;
      this.canvas?.remove();
      this.canvas = null;
      if (!this.stage) return;
      this.poster.hidden = !this.hasAttribute("poster");
      this.toolbar.hidden = true;
      this.openButton.hidden = !this.getAttribute("src");
      this.openButton.textContent = message ? "重试 3D 预览" : "360° 查看模型";
      this.file.hidden = !message;
      this.file.href = this.getAttribute("src") || "";
      this.caption.textContent = message;
      this.caption.hidden = !message;
    }

    open(mode = "pan") {
      const src = this.getAttribute("src");
      if (!src || this.canvas) return;
      this.view = viewHome();
      const canvas = this.canvas = document.createElement("canvas");
      canvas.tabIndex = 0;
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", this.canvasLabel());
      canvas.setAttribute("aria-keyshortcuts", "ArrowUp ArrowDown ArrowLeft ArrowRight + - Home Escape");
      canvas.hidden = true;
      this.stage.append(canvas);
      this.openButton.textContent = "取消加载";
      this.file.hidden = true;
      this.caption.hidden = false;
      this.caption.textContent = "正在读取本机模型…";
      try {
        this.renderer = createRenderer(canvas);
        this.inputs = new AbortController();
        canvas.addEventListener("webglcontextlost", () => this.close("3D 视图已中断，可重新打开。"), {signal: this.inputs.signal});
        const worker = this.worker = new Worker("/viewer-mesh.js");
        this.loadTimer = setTimeout(() => this.close("模型读取超时，请检查本机应用后重试。"), 30000);
        worker.onerror = () => { if (this.worker === worker) this.close("模型读取工具未能启动，可重试或下载 STL。"); };
        worker.onmessage = ({data}) => {
          if (this.worker !== worker) return;
          clearTimeout(this.loadTimer);
          worker.terminate();
          this.worker = null;
          if (data.error) { this.close(data.error); return; }
          try {
            this.renderer.upload(data);
            this.controls(canvas, this.inputs.signal);
            this.poster.hidden = this.openButton.hidden = true;
            canvas.hidden = this.toolbar.hidden = this.caption.hidden = false;
            this.setMode(mode);
            this.observer = new ResizeObserver(() => this.redraw());
            this.observer.observe(canvas);
            this.redraw();
            canvas.focus({preventScroll: true});
          } catch (error) { this.close(error.message); }
        };
        worker.postMessage(new URL(src, location.href).href);
      } catch (error) { this.close(error.message); }
    }

    redraw() {
      if (this.frame || !this.renderer) return;
      this.frame = requestAnimationFrame(() => {
        this.frame = 0;
        this.renderer?.draw(this.view);
      });
    }

    zoomBy(factor, clientX, clientY) {
      const previous = this.view.zoom;
      this.view.zoom = clamp(previous * factor, 0.35, 8);
      if (clientX !== undefined) {
        const rect = this.canvas.getBoundingClientRect();
        const anchorX = 2 * (clientX - rect.left) / rect.width - 1;
        const anchorY = 1 - 2 * (clientY - rect.top) / rect.height;
        const change = 1 - this.view.zoom / previous;
        this.view.panX += (anchorX - this.view.panX) * change;
        this.view.panY += (anchorY - this.view.panY) * change;
      }
      this.redraw();
    }

    controls(canvas, signal) {
      const pointers = new Map();
      const listen = (name, handler, options = {}) => canvas.addEventListener(name, handler, {signal, ...options});
      const pan = (dx, dy) => {
        this.view.panX += 2 * dx / canvas.clientWidth;
        this.view.panY -= 2 * dy / canvas.clientHeight;
      };
      const rotate = (dx, dy) => {
        this.view.yaw += dx * 0.009;
        this.view.pitch += dy * 0.009;
      };
      listen("pointerdown", (e) => {
        if (e.button > 2 || pointers.size >= 2) return;
        canvas.focus({preventScroll: true});
        canvas.setPointerCapture(e.pointerId);
        pointers.set(e.pointerId, {x: e.clientX, y: e.clientY});
      });
      listen("pointermove", (e) => {
        const before = pointers.get(e.pointerId);
        if (!before) return;
        const dx = e.clientX - before.x, dy = e.clientY - before.y;
        if (pointers.size === 2) {
          const other = [...pointers.values()].find((point) => point !== before);
          const initial = Math.hypot(other.x - before.x, other.y - before.y);
          const distance = Math.hypot(other.x - e.clientX, other.y - e.clientY);
          if (initial > 2 && distance > 2) {
            this.zoomBy(distance / initial, (before.x + other.x) / 2, (before.y + other.y) / 2);
          }
          pan(dx / 2, dy / 2);
        } else if (this.mode === "pan" || e.shiftKey || e.buttons & 6) pan(dx, dy);
        else rotate(dx, dy);
        pointers.set(e.pointerId, {x: e.clientX, y: e.clientY});
        this.redraw();
      });
      for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) listen(name, (e) => pointers.delete(e.pointerId));
      listen("contextmenu", (e) => e.preventDefault());
      listen("wheel", (e) => {
        e.preventDefault();
        const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? canvas.clientHeight : 1;
        if (this.mode === "pan" && !e.ctrlKey && !e.metaKey) {
          pan(-e.deltaX * unit, -e.deltaY * unit);
          this.redraw();
        } else {
          this.zoomBy(Math.exp(-clamp(e.deltaY * unit, -400, 400) * 0.0025), e.clientX, e.clientY);
        }
      }, {passive: false});
      listen("keydown", (e) => {
        const arrows = {ArrowLeft: [-20, 0], ArrowRight: [20, 0], ArrowUp: [0, -20], ArrowDown: [0, 20]};
        if (arrows[e.key]) (this.mode === "pan" || e.shiftKey ? pan : rotate)(...arrows[e.key]);
        else if (e.key === "+" || e.key === "=") this.zoomBy(1.2);
        else if (e.key === "-") this.zoomBy(1 / 1.2);
        else if (e.key === "Home" || e.key === "0") this.view = viewHome();
        else if (e.key === "Escape") { this.close(); this.openButton.focus(); }
        else return;
        e.preventDefault();
        this.redraw();
      });
    }
  }

  customElements.define("model-orbit", ModelOrbit);
})();
