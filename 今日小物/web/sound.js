// 今日小物的按键声和提示音：WebAudio 现场合成，不下载音频。第一次点按之后才出声。
// 右下角可以静音，选择记在本机浏览器。
(() => {
  const KEY = "moodprint-sound";
  let ctx = null, master = null, muted = localStorage.getItem(KEY) === "off";
  function start() {
    if (ctx) { if (ctx.state === "suspended") ctx.resume(); return; }
    const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return;
    ctx = new AC(); master = ctx.createGain(); master.gain.value = muted ? 0 : 0.6; master.connect(ctx.destination);
  }
  addEventListener("pointerdown", start, { capture: true, passive: true });
  function tone(freq, duration, { type = "sine", gain = 0.12, delay = 0, to = null } = {}) {
    if (!ctx || muted) return;
    const o = ctx.createOscillator(), g = ctx.createGain(), t = ctx.currentTime + delay;
    o.type = type; o.frequency.setValueAtTime(freq, t); if (to) o.frequency.exponentialRampToValueAtTime(to, t + duration);
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(gain, t + 0.006); g.gain.exponentialRampToValueAtTime(0.0008, t + duration);
    o.connect(g).connect(master); o.start(t); o.stop(t + duration + 0.05);
  }
  const sound = {
    tap() { tone(760, 0.06, { gain: 0.05, to: 600 }); },
    soft() { tone(1100, 0.04, { gain: 0.02 }); },
    success() { [523, 659, 784, 1046].forEach((f, i) => tone(f, 0.32, { gain: 0.05, delay: i * 0.07 })); },
    saved() { tone(587, 0.12, { gain: 0.05 }); tone(880, 0.22, { gain: 0.05, delay: 0.08 }); },
    error() { tone(330, 0.18, { type: "triangle", gain: 0.06, to: 260 }); tone(262, 0.24, { type: "triangle", gain: 0.05, delay: 0.12, to: 220 }); },
    print() { for (let i = 0; i < 6; i++) tone(180 + i * 40, 0.05, { type: "square", gain: 0.015, delay: i * 0.06 }); tone(784, 0.3, { gain: 0.05, delay: 0.4 }); },
    get muted() { return muted; },
    setMuted(v) { muted = v; localStorage.setItem(KEY, v ? "off" : "on"); if (master) master.gain.setTargetAtTime(v ? 0 : 0.6, ctx.currentTime, 0.1); },
  };
  window.moodSound = sound;
  addEventListener("DOMContentLoaded", () => {
    const b = document.createElement("button"); b.type = "button"; b.className = "sound-toggle";
    const paint = () => { b.textContent = muted ? "声音 关" : "声音 开"; b.setAttribute("aria-pressed", String(!muted)); };
    b.addEventListener("click", () => { sound.setMuted(!muted); paint(); start(); sound.tap(); });
    paint(); (document.querySelector('.site-header nav') || document.body).append(b);
    document.addEventListener("click", e => { const t = e.target.closest?.("button, .text-button, a.button, summary, select"); if (t && t !== b) sound.tap(); }, true);
  });
})();
