// 声音全部用 WebAudio 现场合成，不下载音频文件。第一次点击或按键后才出声（浏览器规定）。
// 右下角的小喇叭可静音，选择记在本机浏览器里。
const KEY = "island-23-sound";
let ctx = null, master = null, ambientBus = null, ambientNodes = [], ambientKind = null, wanted = null;
let muted = localStorage.getItem(KEY) === "off";
let lastStep = 0;

function start() {
  if (ctx) { if (ctx.state === "suspended") ctx.resume(); return true; }
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return false;
  ctx = new AC();
  master = ctx.createGain(); master.gain.value = muted ? 0 : 0.7; master.connect(ctx.destination);
  ambientBus = ctx.createGain(); ambientBus.gain.value = 0; ambientBus.connect(master);
  if (wanted) ambient(wanted);
  return true;
}
for (const type of ["pointerdown", "keydown"]) addEventListener(type, start, { capture: true, passive: true });

function noiseBuffer(seconds = 2, brown = false) {
  const buffer = ctx.createBuffer(1, ctx.sampleRate * seconds, ctx.sampleRate), data = buffer.getChannelData(0);
  let last = 0;
  for (let i = 0; i < data.length; i++) {
    const white = Math.random() * 2 - 1;
    if (brown) { last = (last + 0.02 * white) / 1.02; data[i] = last * 3.5; } else data[i] = white;
  }
  return buffer;
}
let whiteCache = null;
function noise(duration, { freq = 1200, q = 0.8, type = "bandpass", gain = 0.2, attack = 0.005, sweep = null } = {}) {
  if (!ctx || muted) return;
  whiteCache ||= noiseBuffer(1.5);
  const src = ctx.createBufferSource(); src.buffer = whiteCache;
  const filter = ctx.createBiquadFilter(); filter.type = type; filter.frequency.value = freq; filter.Q.value = q;
  const g = ctx.createGain(), t = ctx.currentTime;
  g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(gain, t + attack); g.gain.exponentialRampToValueAtTime(0.0008, t + duration);
  if (sweep) filter.frequency.exponentialRampToValueAtTime(sweep, t + duration);
  src.connect(filter).connect(g).connect(master);
  src.start(t, Math.random() * 0.5); src.stop(t + duration + 0.05);
}
function tone(freq, duration, { type = "sine", gain = 0.15, delay = 0, to = null, attack = 0.006 } = {}) {
  if (!ctx || muted) return;
  const o = ctx.createOscillator(), g = ctx.createGain(), t = ctx.currentTime + delay;
  o.type = type; o.frequency.setValueAtTime(freq, t);
  if (to) o.frequency.exponentialRampToValueAtTime(to, t + duration);
  g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(gain, t + attack); g.gain.exponentialRampToValueAtTime(0.0008, t + duration);
  o.connect(g).connect(master); o.start(t); o.stop(t + duration + 0.05);
}

// 环境声：海浪（棕噪声 + 慢慢涨落）、小屋（壁炉一样的低噪声 + 钟摆）、花园（海浪远一点 + 偶尔的鸟叫）
function stopAmbient() {
  for (const n of ambientNodes) { try { n.stop?.(); } catch { /* 已停 */ } n.disconnect?.(); }
  ambientNodes = [];
}
function ambient(kind) {
  wanted = kind;
  if (!ctx || kind === ambientKind) return;
  ambientKind = kind; stopAmbient();
  const t = ctx.currentTime;
  ambientBus.gain.cancelScheduledValues(t); ambientBus.gain.setValueAtTime(0, t); ambientBus.gain.linearRampToValueAtTime(kind ? 1 : 0, t + 2.5);
  if (!kind) return;
  const src = ctx.createBufferSource(); src.buffer = noiseBuffer(6, true); src.loop = true;
  const filter = ctx.createBiquadFilter(); filter.type = "lowpass";
  const swell = ctx.createGain();
  const lfo = ctx.createOscillator(), depth = ctx.createGain();
  if (kind === "room") {
    filter.frequency.value = 380; swell.gain.value = 0.05; lfo.frequency.value = 0.13; depth.gain.value = 0.015;
  } else {
    filter.frequency.value = kind === "garden" ? 520 : 700; swell.gain.value = kind === "garden" ? 0.09 : 0.16;
    lfo.frequency.value = 0.09; depth.gain.value = swell.gain.value * 0.7;
  }
  lfo.connect(depth).connect(swell.gain);
  const lfo2 = ctx.createOscillator(), depth2 = ctx.createGain();
  lfo2.frequency.value = 0.07; depth2.gain.value = filter.frequency.value * 0.5; lfo2.connect(depth2).connect(filter.frequency);
  src.connect(filter).connect(swell).connect(ambientBus);
  src.start(); lfo.start(); lfo2.start();
  ambientNodes.push(src, lfo, lfo2, filter, swell, depth, depth2);
  if (kind === "room" || kind === "garden") {
    // 小屋里的钟摆和花园里的鸟，用一个循环定时器
    let alive = true;
    const timer = { stop() { alive = false; }, disconnect() {} };
    ambientNodes.push(timer);
    const loop = () => {
      if (!alive || ambientKind !== kind) return;
      if (!muted && document.visibilityState === "visible") {
        if (kind === "room") noise(0.05, { freq: 2600, q: 6, gain: 0.025 });
        else if (Math.random() < 0.35) { const f = 2200 + Math.random() * 1400; tone(f, 0.09, { gain: 0.025, to: f * 1.25 }); tone(f * 1.1, 0.08, { gain: 0.02, delay: 0.12, to: f * 0.9 }); }
      }
      setTimeout(loop, kind === "room" ? 1000 : 2600 + Math.random() * 4000);
    };
    setTimeout(loop, 1200);
  }
}

export const sound = {
  start,
  ambient,
  tap() { tone(820, 0.07, { gain: 0.06, to: 620 }); },
  hover() { tone(1250, 0.04, { gain: 0.018 }); },
  open() { tone(523, 0.18, { gain: 0.07 }); tone(784, 0.26, { gain: 0.06, delay: 0.07 }); },
  close() { tone(660, 0.14, { gain: 0.05, to: 440 }); },
  pick() { noise(0.09, { freq: 900, q: 2, gain: 0.12 }); tone(330, 0.08, { gain: 0.06, to: 420 }); },
  drop() { noise(0.14, { freq: 380, q: 1.2, gain: 0.18, type: "lowpass" }); tone(150, 0.16, { gain: 0.1, to: 90 }); },
  store() { tone(700, 0.12, { gain: 0.05, to: 350 }); noise(0.18, { freq: 3000, gain: 0.04, sweep: 600 }); },
  place() { tone(392, 0.12, { gain: 0.06 }); tone(587, 0.2, { gain: 0.06, delay: 0.06 }); },
  success() { [523, 659, 784, 1046].forEach((f, i) => tone(f, 0.35, { gain: 0.05, delay: i * 0.07 })); },
  whoosh() { noise(0.7, { freq: 300, q: 0.7, gain: 0.12, attack: 0.25, sweep: 2400 }); },
  step(run = false) {
    const now = performance.now(); if (now - lastStep < (run ? 260 : 400)) return; lastStep = now;
    noise(0.07, { freq: 260 + Math.random() * 120, q: 1.5, gain: 0.08, type: "lowpass" });
  },
  splash() { noise(0.8, { freq: 1600, q: 0.5, gain: 0.08, attack: 0.05, sweep: 400 }); },
  get muted() { return muted; },
  setMuted(value) {
    muted = value; localStorage.setItem(KEY, value ? "off" : "on");
    if (master) master.gain.setTargetAtTime(value ? 0 : 0.7, ctx.currentTime, 0.1);
  },
};

// 右下角静音开关
export function soundToggle() {
  const button = document.createElement("button");
  button.type = "button"; button.className = "sound-toggle";
  const paint = () => { button.textContent = sound.muted ? "声音 关" : "声音 开"; button.setAttribute("aria-pressed", String(!sound.muted)); };
  button.addEventListener("click", () => { sound.setMuted(!sound.muted); paint(); if (!sound.muted) { start(); sound.tap(); } });
  paint(); document.body.append(button);
  return button;
}
