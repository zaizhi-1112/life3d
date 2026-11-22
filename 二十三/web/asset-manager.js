// 布置面板：列出可摆放的展品，选中后在岛上拖动，面板里转向、缩放、收起或放回。
const $ = id => document.getElementById(id);
const FILTERS = {
  all: () => true,
  daily: a => a.kind === "exhibit",
  printed: a => a.printed,
  aholo: a => a.kind === "sculpture",
  model: a => a.kind === "prop" || a.kind === "deco",
  stored: a => a.hidden,
};

// 每日小物按日期从新到旧，样品排后；精雕按阶段再按名称。
function order(a, b) {
  if (a.kind === "exhibit") {
    const da = /^\d/.test(a.sub) ? a.sub : "", db = /^\d/.test(b.sub) ? b.sub : "";
    return db.localeCompare(da) || a.title.localeCompare(b.title, "zh");
  }
  return a.sub.localeCompare(b.sub, "zh") || a.title.localeCompare(b.title, "zh");
}

const KIND = {
  exhibit: a => a.printed ? "已打印" : "每日小物", sculpture: () => "Aholo 精雕",
  prop: () => "其他模型", deco: () => "装饰",
};

export function assetPanel(world) {
  const panel = $("assets"), list = $("asset-list"), search = $("asset-search"), detail = $("asset-detail");
  const yaw = $("asset-yaw"), scale = $("asset-scale"), status = $("asset-status"), undo = $("asset-undo");
  let filter = "all", selected = null, open = false, rows = [];

  function counts(all) {
    for (const button of panel.querySelectorAll("[data-filter]"))
      button.querySelector("span").textContent = all.filter(FILTERS[button.dataset.filter]).length;
  }
  function render() {
    rows = world.list();
    counts(rows);
    const q = search.value.trim();
    const shown = rows.filter(FILTERS[filter]).filter(a => !q || a.title.includes(q) || a.sub.includes(q))
      .sort((a, b) => (a.kind === b.kind ? 0 : a.kind === "exhibit" ? -1 : 1) || order(a, b));
    list.replaceChildren(...shown.map(a => {
      const row = document.createElement("button");
      row.type = "button"; row.className = "asset-row"; row.dataset.id = a.id;
      row.setAttribute("aria-pressed", String(a.id === selected));
      const name = document.createElement("strong"); name.textContent = a.title;
      const meta = document.createElement("small");
      meta.textContent = [KIND[a.kind](a), a.sub].join(" · ");
      const badge = document.createElement("em");
      badge.textContent = a.hidden ? "仓库" : a.moved ? "已调整" : "";
      row.append(name, meta, badge);
      if (a.hidden) row.classList.add("stored");
      row.addEventListener("click", () => world.select(a.id));
      return row;
    }));
    if (!shown.length) {
      const empty = document.createElement("p"); empty.className = "asset-empty";
      empty.textContent = filter === "stored" ? "仓库是空的" : "没有找到";
      list.append(empty);
    }
    undo.disabled = !world.canUndo();
    $("asset-decor-box").hidden = filter !== "model";
    fill();
  }
  function fill() {
    const a = rows.find(r => r.id === selected);
    detail.hidden = !a;
    if (!a) return;
    $("asset-title").textContent = a.title;
    $("asset-meta").textContent = [KIND[a.kind](a), a.sub].join(" · ");
    $("asset-remove").hidden = a.kind !== "deco";
    yaw.value = Math.round(a.yaw); $("asset-yaw-value").textContent = Math.round(a.yaw) + "°";
    scale.value = Math.round(a.scale * 100); $("asset-scale-value").textContent = Math.round(a.scale * 100) + "%";
    yaw.disabled = scale.disabled = a.hidden;
    $("asset-store").textContent = a.hidden ? "摆到眼前" : "收进仓库";
    $("asset-reset").disabled = !a.moved;
    $("asset-look").disabled = a.hidden;
    $("asset-hint").hidden = a.hidden;
  }
  function slider(input, key, toValue, label) {
    input.addEventListener("pointerdown", () => world.begin());
    input.addEventListener("keydown", () => world.begin(), { once: false });
    input.addEventListener("input", () => {
      label(input.value);
      if (selected) world.preview(selected, { [key]: toValue(input.value) });
    });
    input.addEventListener("change", () => { if (selected) world.finish(); });
  }
  slider(yaw, "yaw", v => Number(v), v => { $("asset-yaw-value").textContent = v + "°"; });
  slider(scale, "scale", v => Number(v) / 100, v => { $("asset-scale-value").textContent = v + "%"; });

  for (const button of panel.querySelectorAll("[data-filter]")) button.addEventListener("click", () => {
    filter = button.dataset.filter;
    for (const b of panel.querySelectorAll("[data-filter]")) b.setAttribute("aria-pressed", String(b === button));
    render();
  });
  search.addEventListener("input", render);
  $("asset-look").addEventListener("click", () => selected && world.select(selected));
  $("asset-store").addEventListener("click", () => {
    const a = rows.find(r => r.id === selected);
    if (a) world.change(a.id, { hidden: !a.hidden });
  });
  $("asset-reset").addEventListener("click", () => selected && world.change(selected, { reset: true }));
  undo.addEventListener("click", () => world.undo());
  $("asset-remove").addEventListener("click", () => selected && world.remove(selected));
  const decor = $("asset-decor");
  decor.replaceChildren(...world.decor.map(d => {
    const b = document.createElement("button"); b.type = "button"; b.textContent = "+ " + d.label;
    b.addEventListener("click", () => world.add(d.name));
    return b;
  }));
  $("asset-done").addEventListener("click", hide);
  $("open-assets").addEventListener("click", () => (open ? hide() : show()));

  function show() {
    if (open) return;
    open = true; panel.hidden = false; $("open-assets").setAttribute("aria-pressed", "true");
    world.open(); render();
  }
  function hide() {
    if (!open) return;
    open = false; panel.hidden = true; $("open-assets").setAttribute("aria-pressed", "false");
    world.close();
  }
  return {
    refresh() { if (open) render(); },
    show(id) {
      selected = id || null;
      if (!open) return;
      for (const row of list.querySelectorAll(".asset-row")) row.setAttribute("aria-pressed", String(row.dataset.id === selected));
      list.querySelector(`.asset-row[aria-pressed="true"]`)?.scrollIntoView({ block: "nearest" });
      rows = world.list(); fill();
    },
    problem(text) { const p = $("asset-problem"); p.textContent = text; p.hidden = !text; },
    saving(state, message = "") {
      status.dataset.state = state;
      status.textContent = { waiting: "", saving: "正在保存", saved: "已保存", error: message || "没有保存成功，5 秒后重试" }[state];
      undo.disabled = !world.canUndo();
    },
    active: () => open,
  };
}
