import { readOnly } from "./island-panels.js";

const byId = id => document.getElementById(id);
const dialog = byId("people-manager");
const list = byId("people-list");
const form = byId("people-form");
const search = byId("people-search");
const status = byId("people-status");
const next = byId("people-next");
const discard = byId("people-discard");
const keys = ["title", "kicker", "text", "aside"];
const groups = [...dialog.querySelectorAll("[data-scope]")];
if (readOnly) {
  for (const key of keys) form.elements[key].readOnly = true;
  form.querySelector("[type=submit]").hidden = true;
  next.textContent = "下一位";
  next.removeAttribute("title");
}
let people = [], active = null, scope = "house", busy = false, generation = 0, conflict = false;

function inGroup(person, group) { return Boolean(person.house_style) === (group === "house"); }
function matches() {
  const query = search.value.trim().toLocaleLowerCase();
  if (query === "家人" || query === "家庭") return people.filter(p => inGroup(p, scope) && p.home_group === "family");
  return people.filter(p => inGroup(p, scope) && (!query ||
    [p.name, ...keys.map(k => p.card[k])].some(s => (s || "").toLocaleLowerCase().includes(query))));
}
function changes() {
  return Object.fromEntries(keys.filter(k => active && form.elements[k].value !== (active.card[k] || ""))
    .map(k => [k, form.elements[k].value]));
}
function refreshControls() {
  const dirty = Object.keys(changes()).length > 0;
  discard.hidden = !dirty && !conflict;
  discard.textContent = conflict ? "载入已保存版本" : "撤销未保存修改";
  byId("people-fields").disabled = busy;
  form.querySelector("[type=submit]").disabled = busy || !dirty;
  const rows = matches(), at = rows.indexOf(active);
  next.disabled = busy || at < 0 || at >= rows.length - 1;
  byId("people-visit").textContent = active?.house_style ? "去看小屋" : "去看信箱";
  byId("people-visit").disabled = busy || !active;
}
function drawList() {
  const rows = matches();
  const buttons = rows.map(person => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "people-entry";
    button.dataset.id = person.card_id;
    button.setAttribute("aria-current", String(person === active));
    const title = person.card.title || person.name;
    button.textContent = title === person.name ? title : title + " · " + person.name;
    button.title = button.textContent;
    return button;
  });
  if (!buttons.length && people.length) {
    const empty = document.createElement("p");
    empty.className = "people-empty";
    empty.textContent = search.value.trim() ? "没有匹配的人物" : "这一组还没有人物";
    buttons.push(empty);
  }
  list.replaceChildren(...buttons);
  for (const button of groups) {
    const group = button.dataset.scope;
    button.setAttribute("aria-pressed", String(scope === group));
    button.textContent = (group === "house" ? "住户" : "信箱") + " " + people.filter(p => inGroup(p, group)).length;
  }
  refreshControls();
}
function select(person, scroll = false) {
  active = person || null;
  form.hidden = !active;
  conflict = false;
  for (const k of keys) form.elements[k].value = active?.card[k] || "";
  status.textContent = "";
  drawList();
  if (scroll) list.querySelector("[aria-current=true]")?.scrollIntoView({block:"nearest", inline:"nearest"});
}
async function save() {
  if (readOnly) return true;
  const fields = changes();
  if (!active || !Object.keys(fields).length) return true;
  if (conflict) return false;
  if (!form.reportValidity()) return false;
  const expected = Object.fromEntries(Object.keys(fields).map(k => [k, active.card[k] || ""]));
  busy = true;
  refreshControls();
  status.textContent = "正在保存…";
  try {
    const response = await fetch("/api/edits", {method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({id:active.card_id, fields, expected}), signal:AbortSignal.timeout(8000)});
    const result = await response.json();
    if (response.status === 409 && result.card) {
      active.card = result.card;
      conflict = true;
      status.textContent = "这份文字在另一处改过。可先复制草稿，再载入已保存版本。";
      return false;
    }
    if (!response.ok) throw new Error(result.error || "本机暂时无法保存，请再试一次。");
    active.card = result.card;
    for (const k of keys) form.elements[k].value = active.card[k] || "";
    window.dispatchEvent(new CustomEvent("person-card-saved", {detail:{id:active.card_id, card:result.card}}));
    drawList();
    status.textContent = "已保存到小岛";
    return true;
  } catch (error) {
    status.textContent = error instanceof TypeError || error.name === "TimeoutError" ?
      "暂时连不上小岛，草稿还在。连接恢复后点保存。" : error.message;
    return false;
  } finally {
    busy = false;
    refreshControls();
  }
}
async function transition(action) {
  if (busy || conflict || !await save()) return;
  action();
}
async function loadPeople() {
  const session = ++generation;
  byId("people-retry").hidden = true;
  status.textContent = "正在读取人物…";
  try {
    const response = await fetch("/data/world.json", {cache:"no-store", signal:AbortSignal.timeout(8000)});
    if (!response.ok) throw new Error();
    const data = await response.json();
    if (session !== generation) return;
    people = data.people;
    select(matches()[0]);
    if (!people.length) status.textContent = "小岛还没有人物卡。";
  } catch {
    if (session !== generation) return;
    status.textContent = "没能读取名单，请重新读取。";
    byId("people-retry").hidden = false;
  }
}
function open(group) {
  if (dialog.open) return;
  people = []; scope = "house"; search.value = group === "family" ? "家人" : "";
  select(null);
  dialog.showModal();
  window.dispatchEvent(new Event("people-manager-open"));
  search.focus();
  loadPeople();
}
function close() { transition(() => dialog.close()); }
byId("open-people").addEventListener("click", open);
window.addEventListener("people-manager-request", e => open(e.detail?.group));
byId("people-close").addEventListener("click", close);
byId("people-visit").addEventListener("click", () => {
  if (!active) return;
  const target = active.home_group === "family" ? "house-family" : active.card_id;
  transition(() => {
    dialog.close();
    const hash = "#object=" + encodeURIComponent(target);
    if (location.hash === hash) window.dispatchEvent(new HashChangeEvent("hashchange"));
    else location.hash = hash;
  });
});
dialog.addEventListener("cancel", e => { e.preventDefault(); close(); });
dialog.addEventListener("close", () => {
  generation++;
  const url = new URL(location.href);
  if (url.searchParams.get("panel") === "people") {
    url.searchParams.delete("panel");
    history.replaceState(null, "", url);
  }
  window.dispatchEvent(new Event("people-manager-close"));
  byId("open-people").focus({preventScroll:true});
});
byId("people-retry").addEventListener("click", loadPeople);
groups.forEach(button => button.addEventListener("click", () => {
  if (button.dataset.scope !== scope) transition(() => { scope = button.dataset.scope; select(matches()[0]); });
}));
list.addEventListener("click", e => {
  const id = e.target.closest("button[data-id]")?.dataset.id;
  if (id && id !== active?.card_id) transition(() => select(people.find(p => p.card_id === id)));
});
search.addEventListener("input", () => {
  if (!busy && !conflict && !Object.keys(changes()).length && !matches().includes(active)) select(matches()[0]);
  else drawList();
});
search.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.isComposing && matches().length) {
    e.preventDefault();
    transition(() => { select(matches()[0]); form.elements.text.focus(); });
  }
});
form.addEventListener("input", () => {
  if (!conflict) status.textContent = Object.keys(changes()).length ? "切换人物或回岛时会自动保存" : "";
  refreshControls();
});
form.addEventListener("submit", e => { e.preventDefault(); if (!busy) save(); });
discard.addEventListener("click", () => { if (!busy) select(active); });
function saveNext() {
  if (next.disabled) return;
  const rows = matches(), following = rows[rows.indexOf(active) + 1];
  if (following) transition(() => { select(following, true); form.elements.text.focus(); });
}
next.addEventListener("click", saveNext);
dialog.addEventListener("keydown", e => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && !e.isComposing) {
    e.preventDefault();
    if (next.disabled) { if (!busy) save(); } else saveNext();
  }
});

if (new URLSearchParams(location.search).get("panel") === "people") {
  if (document.readyState === "complete") open();
  else window.addEventListener("load", open, {once:true});
}
