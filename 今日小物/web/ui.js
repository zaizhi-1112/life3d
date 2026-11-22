"use strict";

const byId = (id) => document.getElementById(id);
const statuses = {
  recorded: "已收录", generating: "Aholo 正在生成", slicing: "正在切片",
  prepared: "切片完成", failed: "准备遇到问题", dispatching: "正在发送",
  submitted: "P2S 已接单", print_unknown: "请查看打印机", unreadable: "记录读取失败", finished: "已有成品",
};
const demoKeys = new Set(["sample", "character", "aholo-character"]);
const activeStatuses = new Set(["generating", "slicing", "dispatching"]);
const form = byId("record-form");
const dialog = byId("settings-dialog");
const connectionForm = byId("connection-form");
const drafts = new Map();
let state;
let selected = initialDay();
let view = "today";
let loadedDate;
let waiting = false;
let loadVersion = 0;
let loadController;
let pollTimer;
let toastTimer;
let pendingSample = false;
let disconnected = false;
let navigationPending = true;
let previewUrl = "";
let historySignature = "";
let photoTarget;
let linkedDay = new URLSearchParams(location.search).get("day");
let linkedCode = new URLSearchParams(location.hash.slice(1)).get("choose");
let modelLinkDay = new URLSearchParams(location.search).get("view") === "3d" && !linkedCode ? selected : null;
let openLinkedModel = Boolean(modelLinkDay);
let choiceEntryDay;

window.addEventListener("hashchange", () => {
  const code = new URLSearchParams(location.hash.slice(1)).get("choose") || "";
  if (!state || !/^[0-9A-F]{8,16}$/i.test(code)) return;
  linkedDay = new URLSearchParams(location.search).get("day") || state.date;
  linkedCode = code;
  if (linkedDay === state.date) {
    render();
    syncDayUrl();
  }
});

function initialDay() {
  const key = new URL(location.href).searchParams.get("day");
  if (demoKeys.has(key)) return key;
  if (!key || !/^\d{4}-\d{2}-\d{2}$/.test(key) || key.startsWith("0000")) return null;
  const parsed = new Date(key + "T12:00:00+08:00");
  const today = new Intl.DateTimeFormat("sv-SE", {timeZone: "Asia/Taipei"}).format(new Date());
  return Number.isFinite(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === key && key <= today ? key : null;
}

function syncDayUrl() {
  const url = new URL(location.href);
  url.search = "";
  url.hash = "";
  if (selected) url.searchParams.set("day", selected);
  if (selected && selected === modelLinkDay) url.searchParams.set("view", "3d");
  if (url.href !== location.href) history.replaceState(null, "", url);
}

function show(id, visible) {
  byId(id).hidden = !visible;
}

// 三端：你对 AI 说的话、Agent 自己做的事、你手写的待办。数字和依据都来自本机记录。
let threeEndsKey = "", wasOrganizing = false;
function countUp(el, to) {
  const start = performance.now(), dur = 700;
  const step = now => { const k = Math.min(1, (now - start) / dur), e = 1 - Math.pow(1 - k, 3); el.firstChild.textContent = String(Math.round(to * e)); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
function renderThreeEnds(sources) {
  const box = byId("three-ends");
  box.hidden = !sources;
  if (!sources) { threeEndsKey = ""; return box.replaceChildren(); }
  const key = JSON.stringify([state?.date, sources.prompts, sources.agent_work, sources.todos]);
  if (key === threeEndsKey && box.childElementCount) return;
  const fresh = key !== threeEndsKey; threeEndsKey = key;
  const cell = (label, count, unit, note) => {
    const item = document.createElement("div");
    item.className = "end";
    const name = document.createElement("span"); name.textContent = label;
    const value = document.createElement("strong"); value.textContent = count;
    const small = document.createElement("small"); small.textContent = unit;
    value.append(small);
    const detail = document.createElement("em"); detail.textContent = note;
    item.append(name, value, detail);
    return item;
  };
  const harnesses = (sources.harnesses || []).join(" · ") || "本机 AI";
  const agentNote = sources.hub_runs ? "中台自动 " + sources.hub_runs + " 次" + (sources.hub_alerts ? " · 提醒 " + sources.hub_alerts : "") : "AI 交回的结果";
  const row = document.createElement("div");
  row.className = "ends";
  row.append(
    cell("你说", sources.prompts, "句", sources.projects ? sources.projects + " 个项目 · " + harnesses.replace("Claude Code", "Claude") : harnesses),
    cell("Agent", sources.agent_work, "项", agentNote),
    cell("待办", sources.todos, "条", "飞书工作岛"),
  );
  const trail = document.createElement("ul");
  trail.className = "trail";
  for (const entry of sources.trail || []) {
    const li = document.createElement("li");
    const tag = document.createElement("b"); tag.textContent = entry.from;
    const text = document.createElement("q"); text.textContent = entry.text;
    li.append(tag, text);
    trail.append(li);
  }
  box.replaceChildren(row, ...(trail.children.length ? [trail] : []));
  if (fresh) {
    box.classList.remove("enter"); void box.offsetWidth; box.classList.add("enter");
    for (const value of row.querySelectorAll("strong")) countUp(value, Number(value.firstChild.textContent) || 0);
  }
}

function setText(id, value) {
  if (byId(id).textContent !== value) byId(id).textContent = value;
}

function say(message) {
  const toast = byId("toast");
  (dialog.open ? dialog : document.body).append(toast);
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 7000);
}

async function json(path, data, signal) {
  const options = data === undefined ? {signal} : data instanceof File ? {
    method: "POST", headers: {"Content-Type": data.type}, body: data,
  } : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)};
  let response;
  try {
    response = await fetch(path, options);
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(data === undefined ? "暂时连不上本机应用。" : "没有收到操作结果。请先查看任务状态，再决定是否重试。");
  }
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error("应用没有返回可读取的结果。请检查应用是否仍在运行。");
  }
  if (!response.ok) throw new Error(result.error || "当前操作没有完成。");
  return result;
}

function stopLoad() {
  clearTimeout(pollTimer);
  if (loadController) loadController.abort();
  loadController = null;
  loadVersion += 1;
}

function scheduleRefresh() {
  clearTimeout(pollTimer);
  if (waiting || document.hidden) return;
  const active = Boolean(state?.busy || state?.checking_printer || state?.organizing);
  pollTimer = setTimeout(refresh, disconnected ? 8000 : active ? 2500 : 12000);
}

async function refresh() {
  stopLoad();
  const version = loadVersion;
  const controller = new AbortController();
  loadController = controller;
  const timeout = setTimeout(() => controller.abort("timeout"), 15000);
  try {
    const updated = await json("/state/" + (selected || "today"), undefined, controller.signal);
    if (version !== loadVersion) return;
    if (!selected && state && state.date === state.today && state.today !== updated.today && drafts.has(state.date)) {
      say("日期已更新。上一天未保存的记录可以在收藏中继续。");
    }
    state = updated;
    if (selected === updated.today && selected !== linkedDay) selected = null;
    syncDayUrl();
    navigationPending = false;
    disconnected = false;
    show("connection-notice", false);
    if (pendingSample && state.sample?.status === "prepared") {
      pendingSample = false;
      chooseDay("sample");
      return;
    }
    render();
  } catch (error) {
    if (version !== loadVersion || controller.signal.aborted && controller.signal.reason !== "timeout") return;
    disconnected = true;
    setText("connection-message", state
      ? "暂时连不上本机应用，当前显示上次读取的内容。"
      : "暂时连不上本机应用。请确认「今日小物」仍在运行。");
    show("connection-notice", true);
    renderControls();
  } finally {
    clearTimeout(timeout);
    if (version === loadVersion) {
      loadController = null;
      scheduleRefresh();
    }
  }
}

async function action(path, data = {}, done) {
  if (waiting || disconnected || navigationPending || !state) return;
  stopLoad();
  waiting = true;
  renderControls();
  try {
    const result = await json(path, data);
    if (done) done(result);
    window.moodSound?.[/print|color|confirm/.test(path) ? "print" : "saved"]?.();
    await refresh();
  } catch (error) {
    window.moodSound?.error();
    say(error.message);
    await refresh();
  } finally {
    waiting = false;
    renderControls();
    scheduleRefresh();
  }
}

function chooseDay(date = null) {
  modelLinkDay = null;
  openLinkedModel = false;
  selected = date === state?.today ? null : date;
  pendingSample = false;
  navigationPending = true;
  renderControls();
  byId("status").textContent = "正在读取";
  setView("today");
  refresh();
}

function setView(target) {
  view = target;
  show("today-view", target === "today");
  show("collection", target === "history");
  for (const [id, current] of [["today-link", target === "today"], ["history-link", target === "history"]]) {
    byId(id).classList.toggle("current", current);
    if (current) byId(id).setAttribute("aria-current", "page");
    else byId(id).removeAttribute("aria-current");
  }
  if (state && target === "history") renderHistory();
}

function recordValues() {
  const fields = new FormData(form);
  const {job} = state;
  const values = {
    summary: fields.get("summary"), mood: fields.get("mood") || "未标记",
    title: fields.get("title"), idea: fields.get("idea"),
  };
  const reason = fields.get("design_reason");
  if (reason !== (job?.design_reason || "")) values.design_reason = reason;
  const prompt = byId("design-prompt");
  if (!prompt.readOnly && prompt.value !== (job?.design_prompt || "")) values.design_prompt = prompt.value;
  if (job?.edit_token) values.edit_token = job.edit_token;
  return values;
}

function fillRecord(values, editing, job) {
  byId("summary").value = values?.summary || "";
  byId("design-title").value = !editing && values?.custom_title === false ? "" : values?.title || "";
  byId("design-idea").value = !editing && values?.custom_design === false ? "" : values?.idea || "";
  byId("design-reason-edit").value = values?.design_reason ?? job?.design_reason ?? "";
  for (const input of document.querySelectorAll("#moods input")) input.checked = input.value === values?.mood;
}

function sampleEntries() {
  return [
    {key: "aholo-character", job: state.aholo_character, name: "Aholo 水獭邮差"},
    {key: "character", job: state.character, name: "本地造型水獭"},
    {key: "sample", job: state.sample, name: "灯塔"},
  ].filter((entry) => entry.job?.print);
}

function duration(seconds) {
  const minutes = Math.max(1, Math.round(seconds / 60));
  return minutes >= 60 ? Math.floor(minutes / 60) + " 小时 " + minutes % 60 + " 分" : minutes + " 分钟";
}

function recordedTime(value) {
  if (!value || !Number.isFinite(Date.parse(value))) return "";
  return new Intl.DateTimeFormat("zh-CN", {month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Taipei"}).format(new Date(value));
}

function deviceStatus(job) {
  if (job?.status === "finished") return "";
  const progress = job?.device_progress;
  const names = {RUNNING: "P2S 打印中", FINISH: "P2S 已报完成", FAILED: "P2S 报告打印失败", PAUSE: "P2S 已暂停", PREPARE: "P2S 正在准备", SLICING: "P2S 正在处理切片"};
  const name = names[progress?.state];
  if (!name) return "";
  return name + (Number.isInteger(progress.percent) && progress.percent >= 0 && progress.percent <= 100 && progress.state !== "FINISH" ? " · " + progress.percent + "%" : "");
}

function fileUrl(key, filename) {
  const path = "/files/" + encodeURIComponent(key) + "/" + encodeURIComponent(filename);
  const job = key === state?.date ? state.job : null;
  if (!job) return path;
  const query = new URLSearchParams({revision: job.revision || "original"});
  if (job.artifact_version) query.set("v", job.artifact_version);
  return path + "?" + query;
}

function confirmedSpool(job) {
  const review = job?.color_review;
  return review?.status === "confirmed" && review.selected?.source ? review.selected : null;
}

function spoolLabel(spool) {
  return spool.label || (spool.source === "external" ? "外置料盘" : String(spool.source || "").replace(/^ams-/i, "AMS ").toUpperCase());
}

function renderColorReview(job, eligible) {
  if (choiceEntryDay !== state.date) {
    byId("confirm-code").value = "";
    choiceEntryDay = state.date;
  }
  const review = job?.color_review;
  const prepared = job?.status === "prepared";
  const current = Boolean(eligible && prepared);
  const visible = Boolean(job?.print && (current || review));
  show("color-review", visible);
  if (!visible) return;
  const selectedSpool = confirmedSpool(job);
  const status = selectedSpool ? "confirmed" : review?.status === "confirmed" ? "waiting" : review?.status || "waiting";
  const card = review?.interaction === "card";
  const states = {
    waiting: ["待选色", current && demoKeys.has(state.date) ? "想打印这个样品时，可把选色消息发到飞书。" : "切片已就绪，等待本件的飞书选色通知。"],
    pending: ["准备发飞书", "正在读取 P2S 的 PLA 颜色。"],
    sent: ["等你选颜色", card ? "清空打印板后，在飞书卡片上点你要的颜色。" : "选好料槽后，用飞书通知中的确认码提交。"],
    error: ["选色遇到问题", "请检查飞书和 P2S 连接，再重试选色。"],
    confirmed: ["已确认颜色", card && prepared && !job.ready ? "清盘后，在飞书卡片上点已选颜色即可开打。" : ""],
  };
  const [title, hint] = states[status] || states.waiting;
  setText("color-status", title);
  byId("color-review").dataset.status = status;
  const message = (status === "error" || status === "waiting") && review?.message ? review.message : hint;
  setText("color-message", message);
  show("color-message", Boolean(message));

  const options = selectedSpool ? [selectedSpool] : review?.options || [];
  const list = byId("color-options");
  list.setAttribute("aria-label", selectedSpool ? "本件使用的耗材" : "可用耗材");
  list.replaceChildren(...options.map((spool) => {
    const item = document.createElement("li");
    if (/^#[0-9a-f]{6}$/i.test(spool.color)) {
      const swatch = document.createElement("canvas");
      swatch.width = swatch.height = 16;
      swatch.setAttribute("aria-hidden", "true");
      const ctx = swatch.getContext("2d");
      if (ctx) {
        ctx.fillStyle = spool.color;
        ctx.fillRect(0, 0, 16, 16);
        item.append(swatch);
      }
    }
    item.append(spoolLabel(spool));
    return item;
  }));
  list.hidden = !options.length;
  const canConfirm = Boolean(current && review?.can_confirm && !selectedSpool && (!card || linkedCode));
  show("color-confirm", canConfirm);
  if (canConfirm) {
    const select = byId("confirm-source");
    const signature = JSON.stringify([state.date, options]);
    if (select.dataset.signature !== signature) {
      select.dataset.signature = signature;
      select.replaceChildren(new Option("请选择颜色", ""), ...options.map(spool => new Option(spoolLabel(spool), spool.source)));
    }
  }
  if (state.date === linkedDay && /^[0-9A-F]{8,16}$/i.test(linkedCode || "") && (canConfirm || selectedSpool)) {
    if (canConfirm) byId("confirm-code").value = linkedCode.toUpperCase();
    linkedCode = null;
    requestAnimationFrame(() => byId("color-review").scrollIntoView({block: "center"}));
  }
  show("color-request", Boolean((current || job?.retry_color) && state.connection.printer && ["waiting", "error"].includes(status)));
  setText("color-request", status === "error" ? "重试飞书选色" : "发飞书选色");
}

function render() {
  const {date, today, job} = state;
  const demo = demoKeys.has(date);
  const readable = job?.status !== "unreadable";
  const editing = Boolean(job?.edit_token);
  const editable = !demo && readable && (!job || job.status === "recorded" || editing);
  const formattedDate = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "long", day: "numeric", weekday: "long", timeZone: "Asia/Taipei",
  });
  const sampleLabel = sampleEntries().find((entry) => entry.key === date)?.name || "离线样品";
  setText("date-label", demo ? sampleLabel + " · 样品" : formattedDate.format(new Date(date + "T12:00:00+08:00")));
  if (!demo) byId("date-label").dateTime = date;
  else byId("date-label").removeAttribute("datetime");
  setText("page-heading", job?.title || (readable ? "今天的小物" : "记录读取失败"));
  show("back-today", Boolean(selected));
  const eligible = readable && job && !editing && (demo || date === today || job.resume_color) && !["dispatching", "submitted", "print_unknown", "finished"].includes(job.status);
  const awaitingColor = job?.status === "prepared" && eligible && !confirmedSpool(job);
  setText("status", deviceStatus(job) || (awaitingColor ? "切片完成 · 待选色" : job?.designing ? "Aholo 正在设计造型" : statuses[job?.status] || "待记录"));
  byId("status").dataset.active = String(activeStatuses.has(job?.status));
  show("job-empty", !job);
  show("job-detail", Boolean(job));
  setText("job-error", job?.error || "");
  show("job-error", Boolean(job?.error));
  let progress = job?.designing ? "正在生成造型参考图。" :
    job?.status === "generating" ? "正在把参考图变成 3D 模型。" :
    job?.status === "slicing" ? "正在检查模型，并计算打印时间。" :
    job?.status === "dispatching" ? "正在上传切片并等待 P2S 确认。" :
    job?.status === "submitted" ? "P2S 已接受任务" + (recordedTime(job.submitted_at) ? "（" + recordedTime(job.submitted_at) + "）" : "") + "。收到设备报文后会显示进度。" : "";
  if (deviceStatus(job)) {
    progress = deviceStatus(job) + (job.device_progress.state === "FINISH" ? " · 等待实物照片" : "") +
      (recordedTime(job.device_progress.checked_at) ? "（" + recordedTime(job.device_progress.checked_at) + " 设备报文）" : "");
  }
  if (!demo && date === today && state.settings.auto_prepare && (!job || job.status === "recorded")) {
    progress = !job ? "等待 Agent 交接或保存今天的摘要。" :
      !state.connection.aholo ? "先连接 Aholo，才能按安排生成。" :
      state.settings.auto_print && !state.connection.printer ? "先连接 P2S，才能确认清盘和自动打印。" :
      (state.settings.prepare_after_ready || job.needs_credit_consent) && !job.ready ? (
        job.generation_card?.status === "confirmed" ? "已在飞书确认，马上开始生成。" :
        job.generation_card?.message ? job.generation_card.message :
        state.feishu_cards ? "将在 " + state.settings.at + " 后发飞书生成确认卡，点「生成」即开始。" :
        "等待这版作品的积分确认。") :
      "将在 " + state.settings.at + " 后按安排准备这件小物。";
  }
  if (editing) progress = "编辑期间暂停这件作品的自动制作和发送。";
  setText("progress-note", progress);
  show("progress-note", Boolean(progress));

  const result = job?.print;
  if (result) {
    setText("print-time", duration(result.estimated_seconds));
    const dimensions = result.dimensions_mm;
    setText("print-size", Array.isArray(dimensions) && dimensions.length === 3 && dimensions.every(Number.isFinite)
      ? dimensions.map((size) => Math.round(size * 10) / 10).join(" × ") + " mm" : "待核实");
    setText("size-comparison", result.size_comparison || "");
    const scale = result.sizing?.scale_factor;
    show("print-scale-row", Number.isFinite(scale) && scale > 0);
    if (Number.isFinite(scale)) setText("print-scale", Math.round(scale * 1000) / 10 + "%");
    show("print-weight-row", Number.isFinite(result.filament_grams));
    if (Number.isFinite(result.filament_grams)) setText("print-weight", result.filament_grams + " 克");
    setText("print-layer", result.layer_height_mm + " mm");
    setText("print-support", result.support_used ? "需要拆支撑" : "无需支撑");
    byId("stl").href = fileUrl(date, "model.stl");
    byId("print-file").href = fileUrl(date, "print.gcode.3mf");
  }
  show("metrics", Boolean(result));
  show("size-comparison", Boolean(result?.size_comparison));
  show("job-links", Boolean(result));
  if (job?.concept_image) byId("concept-link").href = fileUrl(date, job.concept_image);
  show("concept-link", Boolean(job?.concept_image));
  renderPrompt(job, editable);
  renderUsage(job);
  renderEditions(job);

  const needsGeneration = !demo && !editing && ["recorded", "failed"].includes(job?.status);
  show("generate", needsGeneration && state.connection.aholo);
  setText("generate", job?.status === "failed" ? "继续准备" : "用 Aholo 生成并切片");
  show("connect-aholo", needsGeneration && !state.connection.aholo);
  renderColorReview(job, eligible);
  show("print-controls", Boolean(state.connection.printer && eligible && job?.color_review?.interaction !== "card" && (result || state.settings.auto_print)));
  show("send-print", job?.status === "prepared");
  setText("send-print", demo ? "发送样品到 P2S" : "发送到 P2S 开始打印");
  byId("ready").checked = Boolean(job?.ready && job.ready_date === today);
  const preparingAfterReady = !demo && date === today && job?.status === "recorded" && (state.settings.prepare_after_ready || job.needs_credit_consent);
  setText("ready-description", preparingAfterReady
    ? "平台已清空，0.4 mm 喷嘴和纹理 PEI 板已就绪。允许用 Aholo 积分生成这版的参考图和模型，切片后等我在飞书选色。"
    : "平台已清空，0.4 mm 喷嘴和纹理 PEI 板已就绪。");
  show("connect-printer", Boolean(!state.connection.printer && eligible && result));

  const examples = sampleEntries();
  setText("sample-button", examples.length ? (demo ? "查看全部样品 ↗" : "查看" + examples[0].name + " ↗") : "试切灯塔样品 ↗");
  const sampleProgress = state.sample?.status === "slicing" ? "正在为灯塔切片…" : state.sample?.error || "";
  setText("sample-progress", sampleProgress);
  show("sample-progress", Boolean(sampleProgress));

  show("record-form", !demo && readable);
  show("sample-story", demo && readable);
  setText("sample-summary", job?.summary || "这件样品用来查看模型和切片。");
  setText("record-heading", demo ? "样品来由" : "经历摘要");
  setText("record-label", demo ? "样品" : editing ? "编辑中" : editable ? job && !drafts.has(date) ? "已保存" : "" : readable ? "已锁定" : "");
  if (loadedDate !== date) {
    const record = drafts.get(date) || job;
    byId("design-fields").open = editing || Boolean(drafts.has(date) && (record.title || record.idea));
    show("finished-error", false);
  }
  if (loadedDate !== date || !drafts.has(date)) fillRecord(editable ? drafts.get(date) || job : job, editing, job);
  loadedDate = date;
  byId("summary").readOnly = !editable;
  byId("moods").disabled = !editable;
  show("design-fields", editable);
  show("save-record", editable);
  show("unlock-record", !demo && readable && Boolean(job) && !editable && !activeStatuses.has(job.status));
  show("cancel-edit", editing);
  show("organize-record", date === today && !job);
  setText("organize-record", state.organizing ? "正在整理…" : "自动整理今天");
  if (wasOrganizing && !state.organizing) window.moodSound?.[job ? "success" : "error"]?.();
  wasOrganizing = Boolean(state.organizing);
  setText("organize-error", state.organize_error || "");
  show("organize-error", Boolean(state.organize_error && !job));
  const sources = job?.daily_sources;
  const threeEnds = !editing && sources && "prompts" in sources && !sources.birthday;
  renderThreeEnds(threeEnds ? sources : null);
  const sourceNote = editing ? "改造型或提示词会建立新版本，旧模型、切片和照片仍可查看。" :
    sources?.birthday ? "取材于生日礼物里的往事。" :
    threeEnds ? (sources.unavailable.length ? "暂未读到 " + sources.unavailable.join("、") + "。" : "") :
    sources ? "整理自飞书工作岛 " + sources.todos + " 条待办记录、Codex " + sources.agent_work + " 项工作结果。" +
      (sources.unavailable.length ? " 暂未读到 " + sources.unavailable.join("、") + "。" : "") +
      (sources.partial ? " 只整理了可读取的近期记录。" : "") :
    !job && date === today ? "读取今天你和 AI 的对话、Agent 交回的结果和飞书工作岛待办。" : "";
  setText("record-source", sourceNote);
  show("record-source", Boolean(sourceNote));
  setText("draft-status", editable && drafts.has(date) ? "尚未保存" : "");

  renderInspiration(job, demo);
  renderScene();
  renderFinished(job);
  renderDates();
  renderControls();
  if (view === "history") renderHistory();
}

function renderUsage(job) {
  const usage = job?.credits;
  show("usage-panel", Boolean(usage));
  if (!usage) return;
  const {versions, complete, confirmed, estimate, estimate_stages: estimateStages} = usage;
  const planned = job.status === "recorded";
  let total = "等待用量记录";
  if (planned && !versions.length) total = "预计 " + estimate + " 积分";
  else if (confirmed !== null) {
    const label = complete ? (versions.some(version => !version.current) ? "各版共扣 " : "实扣 ") : "已核对 ";
    total = label + confirmed + " 积分";
  }
  setText("usage-total", total);
  const list = byId("usage-lines");
  const signature = JSON.stringify([versions, planned, estimate]);
  if (list.dataset.items === signature) return;
  list.dataset.items = signature;
  list.replaceChildren();
  list.title = "";
  if (!versions.length && !planned) {
    list.textContent = "本机还没有可核对的 Aholo 任务编号。";
    return;
  }
  for (const version of versions) {
    const row = document.createElement("p");
    const parts = version.stages.map(stage =>
      stage.label + " " + (stage.credits === null ? "待结算" : stage.credits));
    const label = version.current ? (versions.length > 1 ? "当前版" : "") : "第 " + (version.index + 1) + " 版";
    const allKnown = version.stages.every(stage => stage.credits !== null);
    const subtotal = version.stages.reduce((sum, stage) => sum + (stage.credits ?? 0), 0);
    const prefix = label ? label + " " + version.title + (allKnown ? "（" + subtotal + " 积分）" : "") + " · " : "";
    row.textContent = prefix + parts.join(" · ");
    list.append(row);
  }
  if (planned) {
    const row = document.createElement("p");
    row.textContent = (versions.length ? "当前版预计 " + estimate + " 积分 · " : "") +
      estimateStages.map(stage => stage.label + " " + stage.credits).join(" · ");
    row.title = "按 Aholo 2026 年 11 月 18 日公布的标准价格估算，生成后显示实际扣款。";
    list.append(row);
  }
}

function renderPrompt(job, editable) {
  const prompt = job?.design_prompt;
  const status = job?.prompt_status;
  const labels = {planned: "参考图 · 待调用", sent: "已用于参考图", unknown: "提交结果待确认", archived: "存档造型描述"};
  setText("prompt-state", labels[status] || (prompt ? "参考图提示词" : job ? "存档造型描述" : ""));
  setText("design-reason", job?.design_reason || "");
  show("design-reason", Boolean(job?.design_reason));
  setText("idea", prompt ? "" : job?.idea || "");
  show("idea", !prompt && Boolean(job?.idea));
  const input = byId("design-prompt");
  const visible = Boolean(prompt || editable && job?.idea);
  input.readOnly = !editable;
  const value = (editable ? drafts.get(state.date)?.design_prompt ?? prompt : prompt) || "";
  if (input.value !== value) input.value = value;
  show("design-prompt", visible);
  show("save-prompt", editable && Boolean(drafts.get(state.date) && "design_prompt" in drafts.get(state.date)));
  const referenceNote = job?.portrait_reference
    ? "Aholo 根据你选的头像和这段文字设计公仔，G1 再从公仔参考图建模。"
    : "这段文字用于生成参考图，G1 再从参考图建模。";
  setText("prompt-empty", prompt ? referenceNote :
    job?.idea ? "这条记录未保存当时的完整提示词。" : "保存经历后，这里会留下造型及使用的提示词。");
}

function renderEditions(job) {
  const editions = job?.editions || [];
  show("previous-editions", Boolean(editions.length));
  const list = byId("edition-links");
  const signature = JSON.stringify([state.date, editions]);
  if (list.dataset.items === signature) return;
  list.dataset.items = signature;
  const labels = {"model.stl": "STL 模型", "print.gcode.3mf": "切片", "finished.jpg": "实物照片",
    "finished.png": "实物照片", "concept.jpg": "参考图", "concept.png": "参考图"};
  list.replaceChildren(...editions.map(edition => {
    const row = document.createElement("p");
    row.append("第 " + (edition.index + 1) + " 版 · " + edition.title);
    for (const name of edition.files) {
      const link = document.createElement("a");
      link.href = "/files/" + encodeURIComponent(state.date) + "/" + encodeURIComponent(name) + "?edition=" + edition.index;
      link.textContent = labels[name];
      if (name.endsWith(".stl") || name.endsWith(".3mf")) link.download = "";
      else { link.target = "_blank"; link.rel = "noopener"; }
      row.append("　", link);
    }
    return row;
  }));
}

function renderInspiration(job, demo) {
  const items = Array.isArray(job?.inspiration) ? job.inspiration : [];
  const signature = JSON.stringify(items);
  const list = byId("inspiration-list");
  if (list.dataset.items !== signature) {
    list.dataset.items = signature;
    list.replaceChildren();
    for (const item of items) {
      const quote = document.createElement("blockquote");
      const text = document.createElement("p");
      text.textContent = item.quote;
      const source = document.createElement("cite");
      source.textContent = item.source || "已交接原话";
      quote.append(text, source);
      list.append(quote);
    }
  }
  setText("no-inspiration", items.length ? "" : demo ? "这件样品未关联你的日常原话。" : "还没有交接可追溯的原话依据。");
  show("no-inspiration", !items.length);
}

function setAttributeIfChanged(element, name, value) {
  if (value) {
    if (element.getAttribute(name) !== value) element.setAttribute(name, value);
  } else if (element.hasAttribute(name)) element.removeAttribute(name);
}

function renderScene() {
  const job = state.job;
  const result = job?.print;
  const example = sampleEntries()[0];
  let key = state.date;
  let model;
  let filename;
  let label;
  let title;
  let info;
  let waitingForModel = false;
  if (result) {
    model = fileUrl(key, "model.stl");
    filename = result.model_preview || "preview.png";
    label = demoKeys.has(key) ? "样品 · 实际模型" : "实际模型";
    title = job.title;
    info = "P2S · " + duration(result.estimated_seconds);
  } else if (job?.concept_image) {
    filename = job.concept_image;
    label = "造型参考图";
    title = job.title;
    info = "3D 模型正在准备";
  } else if (!job && !demoKeys.has(key) && example) {
    key = example.key;
    model = fileUrl(key, "model.stl");
    filename = example.job.print.model_preview || "preview.png";
    label = "参考样品 · " + example.name;
    title = example.job.title;
    info = "点击下方入口查看这件样品";
  } else if (job) {
    waitingForModel = true;
    label = job.status === "generating" || job.status === "slicing" ? "正在准备" : "待生成";
    title = job.title || "这一天的小物";
    info = "尚无 3D 模型";
  } else {
    label = "灯塔样品 · 渲染";
    title = "风停后的灯塔";
    info = "离线样品";
  }
  const url = waitingForModel ? "" : filename ? fileUrl(key, filename) : "/lighthouse.jpg";
  const viewer = byId("model-viewer");
  setAttributeIfChanged(viewer, "src", model);
  setAttributeIfChanged(viewer, "poster", model ? url : null);
  setAttributeIfChanged(viewer, "label", title || "3D 模型");
  show("model-viewer", Boolean(model));
  if (openLinkedModel && result && key === modelLinkDay && view === "today") {
    openLinkedModel = false;
    viewer.open("rotate");
    viewer.scrollIntoView({block: "center"});
  }
  show("preview-link", !model && !waitingForModel);
  show("model-empty", waitingForModel);
  setText("model-empty-title", waitingForModel ? title : "");
  setText("model-empty-text", !waitingForModel ? "" : job.status === "generating" || job.status === "slicing"
    ? "正在准备这件作品的模型。" : job.status === "unreadable"
    ? "这条记录暂时无法读取。" : job.status === "failed"
    ? "模型准备暂停，可以查看下方原因。" : "还没有生成这件作品的模型。");
  if (url !== previewUrl) {
    previewUrl = url;
    show("image-error", false);
  }
  setAttributeIfChanged(byId("showcase"), "src", !model && !waitingForModel ? url : null);
  byId("showcase").alt = title + (job?.concept_image && !model ? "的造型参考图" : "的模型预览");
  byId("preview-link").href = url;
  setText("photo-tag", label);
  setText("photo-caption", title);
  setText("photo-meta", info);
}

function renderFinished(job) {
  const filename = job?.finished_photo;
  const hasPhoto = ["finished.jpg", "finished.png"].includes(filename);
  show("finished-link", hasPhoto);
  show("finished-empty", !hasPhoto);
  if (hasPhoto) {
    const url = new URL(fileUrl(state.date, filename), location.href);
    url.searchParams.set("photo", job.finished_at || filename);
    setAttributeIfChanged(byId("finished-image"), "src", url.href);
    byId("finished-image").alt = (job.title || "这件作品") + "的实物成品照片";
    byId("finished-link").href = url.href;
  }
  setText("finished-state", hasPhoto ? "实物记录" : job?.device_progress?.state === "FINISH" ? "已报完成" : "待记录");
  const time = recordedTime(job?.finished_at);
  setText("finished-note", hasPhoto ? (time ? time + " 上传" : "已保存实物照片") : "还没有成品照片");
  setText("finished-empty-message", deviceStatus(job) ? deviceStatus(job) + (job.device_progress.state === "FINISH" ? " · 等待实物照片" : "") :
    job?.print ? "打印完成后，添加一张实物照片。" : "模型切片后，可以上传实物照片。");
  setText("upload-finished", hasPhoto ? "更换成品照片" : "上传成品照片");
}

function dateKeys() {
  const keys = new Set([state.today, ...(state.history || []), ...drafts.keys()]);
  if (!demoKeys.has(state.date)) keys.add(state.date);
  return [...keys].sort();
}

function renderDates() {
  const keys = dateKeys();
  const select = byId("day-select");
  const demo = demoKeys.has(state.date);
  const signature = JSON.stringify([keys, demo ? state.date : ""]);
  if (select.dataset.items !== signature) {
    select.dataset.items = signature;
    select.replaceChildren();
    if (demo) {
      const option = document.createElement("option");
      option.value = state.date;
      option.textContent = "样品 · " + (state.job?.title || "作品");
      select.append(option);
    }
    for (const key of [...keys].reverse()) {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = key + (key === state.today ? " · 今天" : "");
      select.append(option);
    }
  }
  select.value = state.date;
}

function renderControls() {
  const paired = Boolean(state?.feishu_bound);
  const webhook = Boolean(state?.feishu_webhook);
  const cards = state?.feishu_cards;
  setText("feishu-status", webhook ? "已使用你的专用群通知机器人。" : cards
    ? (state.feishu_cards_online ? "已连接。清盘后，直接在飞书私聊点颜色打印。" : "飞书卡片接收器正在连接。")
    : paired ? "已连接飞书工作岛。启用卡片前，请在飞书开发者后台配置长连接和「卡片回传交互」。" : "连接普通消息机器人后，摆件切片时会收到飞书通知。");
  show("feishu-bind", !paired && !webhook);
  show("feishu-enable-cards", paired && !cards && !webhook);
  if (paired || webhook) show("feishu-instruction", false);
  const unavailable = waiting || disconnected || navigationPending || !state;
  const machineBusy = Boolean(state?.busy || state?.checking_printer);
  const hasDraft = Boolean(state && drafts.has(state.date));
  for (const id of ["generate", "send-print"]) {
    byId(id).disabled = unavailable || machineBusy || hasDraft;
  }
  const preparingCurrent = state?.busy === state?.date && ["generating", "slicing"].includes(state?.job?.status);
  const markingUnavailable = unavailable || ["dispatching", "finished"].includes(state?.job?.status) ||
    Boolean(state?.checking_printer || state?.busy && !preparingCurrent);
  byId("ready").disabled = markingUnavailable || hasDraft;
  byId("color-request").disabled = unavailable || machineBusy;
  byId("confirm-color-button").disabled = unavailable || !state?.job?.color_review?.can_confirm ||
    !byId("confirm-source").value || !byId("confirm-code").value.trim();
  byId("send-print").disabled ||= !byId("ready").checked || !confirmedSpool(state?.job);
  const keys = state ? dateKeys() : [];
  const index = keys.indexOf(state?.date);
  byId("previous-day").disabled = navigationPending || !state || index <= 0;
  byId("next-day").disabled = navigationPending || !state || index < 0 || index >= keys.length - 1;
  byId("day-select").disabled = navigationPending || !state;
  byId("upload-finished").disabled = unavailable || !state?.job?.print || ["unreadable", "dispatching"].includes(state?.job?.status);
  byId("finished-file").disabled = byId("upload-finished").disabled;
  byId("sample-button").disabled = unavailable || Boolean(state?.busy && !sampleEntries().length);
  byId("save-record").disabled = unavailable || Boolean(state?.busy && state.busy === state.date);
  byId("save-prompt").disabled = byId("save-record").disabled;
  byId("organize-record").disabled = unavailable || Boolean(state?.organizing) || hasDraft;
  byId("unlock-record").disabled = unavailable || Boolean(state?.busy && state.busy === state.date);
  byId("cancel-edit").disabled = unavailable;
  for (const button of document.querySelectorAll("#schedule-form button, #connection-form button")) button.disabled = unavailable;
  byId("prepare-after-ready").disabled = unavailable || !(byId("auto-prepare").checked && byId("auto-print").checked);
  byId("printer-check").disabled = unavailable || machineBusy || !state?.connection.printer;
  byId("settings-link").disabled = !state;
  byId("record-form").inert = navigationPending;
  byId("job-detail").inert = navigationPending;
  byId("today-view").setAttribute("aria-busy", String(navigationPending));
  byId("printer-check").textContent = state?.checking_printer ? "正在检查 P2S…" : "测试 P2S 连接";
  setText("settings-error", state?.settings_error || "");
  const history = state?.personal_history;
  setText("personal-history", history?.count ? "本地已索引 " + history.count + " 条可引用节选，来自 " + history.sources + " 个来源。" : "尚未接入可核验的原话记录。Agent 可以随每日摘要交接引用依据。");
  show("settings-error", Boolean(state?.settings_error));
  byId("printer-footer").textContent = state?.connection.printer ? "拓竹 P2S · 已配置" : "拓竹 P2S · 待连接";
  for (const input of connectionForm.querySelectorAll("input[name]")) {
    const configured = Boolean(state?.connection.fields?.[input.name]);
    const status = byId(input.id + "-status");
    status.textContent = configured ? "已保存" : "待填写";
    status.classList.toggle("configured", configured);
    input.placeholder = configured ? "留空保留原值" : "请输入";
  }
}

function renderHistory() {
  const entries = new Map((state.collection || state.history.map((date) => ({date}))).map((item) => [item.date, item]));
  for (const [date, values] of drafts) {
    entries.set(date, {...entries.get(date), date, title: values.title || entries.get(date)?.title || "未保存的记录", draft: true});
  }
  const examples = sampleEntries();
  const signature = JSON.stringify([entries.size, [...entries.values()], examples.map(({key, job}) => [key, job.title, job.print])]);
  if (signature === historySignature) return;
  historySignature = signature;
  const samples = byId("sample-list");
  samples.replaceChildren();
  for (const {key, job, name} of examples) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "sample-card";
    const image = document.createElement("img");
    image.src = fileUrl(key, job.print.model_preview || "preview.png");
    image.alt = name + "的模型预览";
    image.loading = "lazy";
    const caption = document.createElement("span");
    caption.textContent = name + " · 样品";
    button.append(image, caption);
    button.addEventListener("click", () => chooseDay(key));
    samples.append(button);
  }
  const list = byId("history-list");
  list.replaceChildren();
  for (const item of [...entries.values()].sort((a, b) => b.date.localeCompare(a.date))) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-item";
    const time = document.createElement("time");
    time.dateTime = item.date;
    time.textContent = item.date;
    const title = document.createElement("strong");
    title.textContent = item.title || "当天记录";
    const status = document.createElement("small");
    status.textContent = item.draft ? "尚未保存" : [item.mood === "未标记" ? "" : item.mood, statuses[item.status]].filter(Boolean).join(" · ");
    button.append(time, title, status);
    button.addEventListener("click", () => chooseDay(item.date));
    list.append(button);
  }
  if (!entries.size) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "保存当天记录后，你的小物会在这里慢慢积攒。";
    list.append(empty);
  }
}

function openSettings() {
  if (!state || dialog.open) return;
  byId("schedule-time").value = state.settings.at;
  byId("auto-prepare").checked = state.settings.auto_prepare;
  byId("auto-print").checked = state.settings.auto_print;
  byId("prepare-after-ready").checked = Boolean(state.settings.prepare_after_ready);
  byId("prepare-after-ready").disabled = !(state.settings.auto_prepare && state.settings.auto_print);
  dialog.showModal();
}

byId("feishu-bind").addEventListener("click", () => action("/feishu-pair", {}, result => {
  if (result.bound) say("已连接飞书工作岛的普通私聊通知。");
}));
byId("feishu-enable-cards").addEventListener("click", () => action("/feishu-cards", {}));
byId("webhook-form").addEventListener("submit", event => {
  event.preventDefault();
  action("/feishu-webhook", {webhook: byId("webhook-url").value.trim(), secret: byId("webhook-secret").value.trim(),
    only_me: byId("webhook-only-me").checked}, () => { event.target.reset(); say("已保存专用群通知机器人。"); });
});

byId("today-link").addEventListener("click", () => chooseDay());
document.querySelector(".brand").addEventListener("click", (event) => {
  event.preventDefault();
  chooseDay();
});
byId("back-today").addEventListener("click", () => chooseDay());
byId("day-select").addEventListener("change", (event) => chooseDay(event.currentTarget.value === state.today ? null : event.currentTarget.value));
byId("previous-day").addEventListener("click", () => {
  if (navigationPending || !state) return;
  const keys = dateKeys();
  const index = keys.indexOf(state.date);
  if (index > 0) chooseDay(keys[index - 1]);
});
byId("next-day").addEventListener("click", () => {
  if (navigationPending || !state) return;
  const keys = dateKeys();
  const index = keys.indexOf(state.date);
  if (index >= 0 && index < keys.length - 1) chooseDay(keys[index + 1] === state.today ? null : keys[index + 1]);
});
byId("upload-finished").addEventListener("click", () => {
  photoTarget = {date: state.date, revision: state.job.revision || "original"};
  byId("finished-file").click();
});
byId("finished-file").addEventListener("change", () => {
  const input = byId("finished-file");
  const file = input.files[0];
  if (!file || !state) return;
  if (!["image/jpeg", "image/png"].includes(file.type) || file.size > 12 * 1024 * 1024 || !file.size) {
    setText("finished-error", "请选择 12 MiB 以内的 JPG 或 PNG 图片。");
    show("finished-error", true);
    input.value = "";
    return;
  }
  const {date, revision} = photoTarget || {date: state.date, revision: state.job?.revision || "original"};
  photoTarget = null;
  input.value = "";
  show("finished-error", false);
  action("/finished-photo/" + encodeURIComponent(date) + "?revision=" + encodeURIComponent(revision), file, () => {
    input.value = "";
    say("成品照片已保存。");
  });
});
byId("history-link").addEventListener("click", () => setView("history"));
byId("jump-record").addEventListener("click", () => {
  byId("summary").focus({preventScroll: true});
  byId("workbench").scrollIntoView({behavior: "smooth"});
});
byId("sample-button").addEventListener("click", () => {
  if (waiting || !state) return;
  const examples = sampleEntries();
  if (demoKeys.has(state.date)) setView("history");
  else if (examples.length) chooseDay(examples[0].key);
  else action("/sample", {}, () => { pendingSample = true; });
});
function rememberDraft() {
  if (!state || navigationPending || byId("summary").readOnly) return;
  const values = recordValues();
  drafts.set(state.date, values);
  if (!state.job?.edit_token) setText("record-label", "");
  byId("draft-status").textContent = "尚未保存";
  show("save-prompt", "design_prompt" in values);
  renderControls();
}
form.addEventListener("input", rememberDraft);
byId("design-prompt").addEventListener("input", rememberDraft);
byId("organize-record").addEventListener("click", () => action("/organize", {date: state.date}));
byId("unlock-record").addEventListener("click", () => {
  action("/unlock", {date: state.date}, () => {
    byId("design-fields").open = true;
    byId("summary").focus();
  });
});
byId("cancel-edit").addEventListener("click", () => {
  const {date, job} = state;
  action("/cancel-edit", {date, edit_token: job.edit_token}, () => drafts.delete(date));
});
form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!state || waiting || navigationPending) return;
  const date = state.date;
  const values = recordValues();
  const signature = JSON.stringify(values);
  action("/record", {date, ...values}, () => {
    if (JSON.stringify(drafts.get(date)) === signature || values.edit_token) drafts.delete(date);
    say("记录已保存到本机。");
  });
});
byId("generate").addEventListener("click", () => {
  if (!state || waiting || navigationPending) return;
  const {job, date} = state;
  if (job.status === "recorded" && !window.confirm("Aholo 会用这段描述生成造型参考图，再生成 3D 模型。预计使用 " + (job.credits?.estimate ?? 32) + " 积分，生成后会显示实际扣款。\n\n" + job.idea + "\n\n是否开始？")) return;
  action("/generate", {date});
});
byId("ready").addEventListener("change", (event) => {
  const ready = event.currentTarget.checked;
  const payload = {date: state.date, ready,
    prepare_ok: Boolean(ready && state.job?.status === "recorded" && (state.settings.prepare_after_ready || state.job.needs_credit_consent))};
  if (!state.job?.print) payload.source = state.job?.source || "external";
  action("/ready", payload);
});
byId("color-request").addEventListener("click", () => {
  action("/color-request", {date: state.date});
});
byId("color-confirm").addEventListener("submit", event => {
  event.preventDefault();
  if (byId("confirm-color-button").disabled) return;
  action("/color-confirm", {date: state.date, source: byId("confirm-source").value, code: byId("confirm-code").value},
    () => { byId("confirm-code").value = ""; say("本件颜色已确认。"); });
});
byId("confirm-source").addEventListener("change", renderControls);
byId("confirm-code").addEventListener("input", renderControls);
byId("send-print").addEventListener("click", () => {
  const spool = confirmedSpool(state?.job);
  if (waiting || navigationPending || !state || !spool || !byId("ready").checked) return;
  if (window.confirm("P2S 将使用「" + spoolLabel(spool) + "」打印这件作品。确认平台已清空，是否发送？")) action("/print", {date: state.date});
});
for (const id of ["settings-link", "connect-aholo", "connect-printer"]) byId(id).addEventListener("click", openSettings);
byId("close-settings").addEventListener("click", () => dialog.close());
byId("schedule-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action("/settings", {
    at: byId("schedule-time").value,
    auto_prepare: byId("auto-prepare").checked,
    auto_print: byId("auto-print").checked,
    prepare_after_ready: byId("auto-prepare").checked && byId("auto-print").checked && byId("prepare-after-ready").checked,
  }, () => say("每日安排已保存。"));
});
for (const id of ["auto-prepare", "auto-print"]) byId(id).addEventListener("change", () => {
  const allowed = byId("auto-prepare").checked && byId("auto-print").checked;
  if (!allowed) byId("prepare-after-ready").checked = false;
  byId("prepare-after-ready").disabled = !allowed;
});
connectionForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const fields = Object.fromEntries([...new FormData(connectionForm)].map(([key, value]) => [key, value.trim()]).filter(([, value]) => value));
  if (!Object.keys(fields).length) {
    say("现有连接信息已保留。");
    return;
  }
  action("/connections", fields, () => {
    for (const [key, value] of Object.entries(fields)) {
      const input = connectionForm.elements.namedItem(key);
      if (input.value.trim() === value) input.value = "";
    }
    say("连接信息已保存。");
  });
});
byId("printer-check").addEventListener("click", () => {
  if (waiting) return;
  say("正在读取 P2S 状态…");
  action("/printer-check", {source: state.job?.source || "external"}, (result) => {
    say(result.ready ? "已连接 P2S。设备空闲，所选 PLA 和上传目录可用。" : "已连接 P2S。" + result.reason);
  });
});
byId("retry-load").addEventListener("click", refresh);
byId("showcase").addEventListener("error", () => show("image-error", !byId("preview-link").hidden));
byId("showcase").addEventListener("load", () => show("image-error", false));
byId("retry-image").addEventListener("click", () => {
  const url = new URL(previewUrl, location.href);
  url.searchParams.set("reload", Date.now());
  byId("showcase").src = url.href;
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) clearTimeout(pollTimer);
  else refresh();
});
window.addEventListener("online", refresh);
renderControls();
refresh();

// Let the island reclaim focus even after interacting with this frame.
if (window.parent !== window && document.referrer) {
  const islandOrigin = new URL(document.referrer).origin;
  if (["http://127.0.0.1:5232", "http://localhost:5232"].includes(islandOrigin)) {
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !event.defaultPrevented && !document.querySelector("dialog[open]")) {
        window.parent.postMessage({type: "moodprint:close"}, islandOrigin);
      }
    });
  }
}
