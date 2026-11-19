export const readOnly = document.documentElement.hasAttribute("data-read-only");

const $ = id => document.getElementById(id);
const WORKBENCH = "http://127.0.0.1:17868";
const command = 'cd 今日小物 && .venv/bin/python -B app.py --port 17868 --ensure-running';

export function workbenchPanel({pause, resume, refresh}) {
  if (readOnly) return {active: () => false};
  const panel = $("workbench"), frame = $("workbench-frame"), status = $("workbench-status");
  let generation = 0;
  async function localStatus(timeout = 1500) {
    try {
      const response = await fetch("/api/workbench/status", {
        cache: "no-store", signal: AbortSignal.timeout(Math.max(1, timeout)),
      });
      return response.ok && (await response.json()).online === true;
    } catch { return false; }
  }
  async function online() {
    try {
      const response = await fetch(WORKBENCH + "/health", {
        cache: "no-store", signal: AbortSignal.timeout(1500),
      });
      return response.ok && (await response.json()).app === "今日小物";
    } catch { return localStatus(); }
  }
  function showFrame() { frame.src = WORKBENCH + "/"; frame.hidden = false; status.hidden = true; }
  async function open() {
    if (panel.open) return;
    const session = ++generation;
    frame.hidden = true;
    status.textContent = "正在连接工作台"; status.hidden = false;
    pause(); panel.showModal(); $("close-workbench").focus();
    const available = await online();
    if(session !== generation) return;
    if(available) { showFrame(); return; }
    status.textContent = "正在打开工作台，约 5 秒";
    const deadline = Date.now() + 20000;
    try {
      const response = await fetch("/api/workbench/start", {method:"POST",headers:{"Content-Type":"application/json"},body:"{}",signal:AbortSignal.timeout(3000)});
      if (!response.ok) throw new Error();
      let nextCheck = Date.now() + 1000;
      while (session === generation && nextCheck < deadline) {
        const delay = Math.max(0, nextCheck - Date.now());
        await new Promise(resolve => setTimeout(resolve, delay));
        if (session !== generation) return;
        const remaining = deadline - Date.now();
        if (remaining <= 0) break;
        if (await localStatus(Math.min(1500, remaining))) {
          if (session === generation) showFrame();
          return;
        }
        nextCheck = Math.max(nextCheck + 1000, Date.now());
      }
    } catch { /* 下面给出本机启动命令。 */ }
    if(session === generation) failure();
  }
  function failure() {
    status.textContent = "工作台没能启动。可以在终端运行下面的命令，再回来打开。";
    const code=document.createElement("code"); code.textContent=command; status.append(code);
  }
  function close() { if(panel.open) panel.close(); }
  $("open-workbench").addEventListener("click",open);
  $("close-workbench").addEventListener("click",close);
  panel.addEventListener("close",()=>{generation++;frame.removeAttribute("src");frame.hidden=true;resume();refresh();});
  addEventListener("message", e=>{
    if(panel.open && e.origin===WORKBENCH && e.source===frame.contentWindow && e.data?.type==="moodprint:close") close();
  });
  return {open,active:()=>panel.open};
}

export function objectCard({release, changed}) {
  const panel = $("card"), form = $("card-form"), reading = $("card-reading"), status = $("card-status");
  const keys = ["kicker", "title", "text", "aside"];
  let selected = null, linked = null, editing = null, pending = false;

  function read() {
    keys.forEach(key => { $("card-" + key).textContent = selected[key] || ""; });
    $("linked-card").hidden = !linked;
    if (linked) keys.forEach(key => { $("linked-" + key).textContent = linked[key] || ""; });
    const photo = $("card-photo");
    if (selected.photo_url) { photo.src = selected.photo_url; photo.hidden = false; }
    else { photo.hidden = true; photo.removeAttribute("src"); }
    $("edit-card").hidden = readOnly || !selected.id;
    $("edit-linked").hidden = readOnly || !linked?.id;
    editing = null; form.hidden = true; reading.hidden = false; panel.scrollTop = 0;
  }
  function close() {
    if (pending) return;
    panel.hidden = true; selected = linked = editing = null;
  }
  function open(data, related = null, missingModel = false) {
    if (pending) return;
    if (!data) { close(); return; }
    release();
    selected = data; linked = related; panel.hidden = false; status.hidden = true;
    read();
    if (missingModel) { status.textContent = "模型暂时没能显示。请刷新小岛，再打开这件作品。"; status.hidden = false; }
    panel.querySelector(".close").focus({preventScroll: true});
  }
  function beginEdit(data) {
    if (readOnly || !data?.id) return;
    editing = data;
    keys.forEach(key => { form.elements[key].value = data[key] || ""; });
    reading.hidden = true; status.hidden = true; form.hidden = false; form.elements.title.focus();
  }
  panel.querySelector(".close").addEventListener("click", close);
  $("edit-card").addEventListener("click", () => beginEdit(selected));
  $("edit-linked").addEventListener("click", () => beginEdit(linked));
  $("cancel-edit").addEventListener("click", () => {
    const opener = editing === linked ? $("edit-linked") : $("edit-card");
    status.hidden = true; read(); opener.focus();
  });
  async function save(reset) {
    if (pending || !editing) return;
    const fields = {};
    for (const key of keys) {
      const value = form.elements[key].value.trim();
      if (value !== editing[key]) fields[key] = value;
    }
    if (!reset && !Object.keys(fields).length) { read(); return; }
    const payload = reset ? {id: editing.id, reset: true} : {id: editing.id, fields};
    pending = true;
    const buttons = [...panel.querySelectorAll("button")];
    buttons.forEach(button => { button.disabled = true; });
    status.hidden = false; status.textContent = reset ? "正在恢复原文" : "正在保存";
    try {
      const response = await fetch("/api/edits", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload), signal: AbortSignal.timeout(10000),
      });
      const result = await response.json();
      if (!response.ok || !result.card) throw new Error(result.error || "请重新打开小岛后再试。");
      Object.assign(editing, result.card);
      changed(editing); read(); status.textContent = reset ? "已恢复原文" : "已保存";
    } catch (error) {
      const reason=error.name==="TimeoutError" || error instanceof TypeError ? "请重新打开小岛，核对这张卡片后再试。" : error.message;
      status.textContent = "没能保存。" + reason;
    } finally {
      pending = false; buttons.forEach(button => { button.disabled = false; });
    }
  }
  form.addEventListener("submit", event => { event.preventDefault(); save(false); });
  $("reset-edit").addEventListener("click", () => save(true));
  addEventListener("keydown", event => {
    if (event.key !== "Escape" || panel.hidden || $("workbench").open) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (form.hidden) close(); else $("cancel-edit").click();
  }, true);
  return {open, close, active: () => !panel.hidden};
}
