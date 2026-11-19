"""Build data/world.json from the birthday-gift rollups and the 今日小物 jobs.

Reads only model-written summaries and job metadata, never the raw chat
database. Output stays on this Mac (data/ is private, never uploaded).

    python3 -I tools/build_world_data.py
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GIFT_OUTPUT = Path(os.environ.get("BIRTHDAY_GIFT_OUTPUT", Path.home() / "Desktop/AI 送我的 23 岁生日礼物/output"))
GIFT = GIFT_OUTPUT / "stage4_summaries/rollup"
FEED = GIFT_OUTPUT / "stage5_analysis/world_feed.json"
DAILY = Path(os.environ.get("MOODPRINT_DATA", ROOT.parent / "今日小物/data"))
DATA = Path(os.environ.get("BIRTHDAY_WORLD_DATA", ROOT / "data"))
OUT = DATA / "world.json"
EDITS = DATA / "edits.json"
LEDGER = DATA / "aholo_world.json"
HOUSING = DATA / "housing.json"
COMPACT = DATA / "exhibits"  # Blender 减面后的展示版，见 tools/blender/compact_exhibit.py
START_MONTH = "2022-06"  # 用户确认：2022 年夏天之前记录很少
EVIDENCE = re.compile(r"\s*\[k:[^\]]*\]")
MODEL_NAMES = ("model.glb", "courier.glb", "model.stl")


def clean(text: str) -> str:
    return EVIDENCE.sub("", text).strip() if isinstance(text, str) else ""


def month_key(value: str) -> str | None:
    match = re.match(r"(\d{4})-(\d{2})", value or "")
    return f"{match[1]}-{match[2]}" if match else None


def emotions() -> list[dict]:
    months: dict[str, dict] = {}
    for path in sorted(GIFT.glob("L[1-6]/emotion_monthly.json")):
        for series in json.loads(path.read_text("utf-8")).values():
            for raw, value in series.items():
                key = month_key(raw)
                if not key or key < START_MONTH:
                    continue
                slot = months.setdefault(key, {"pos": 0, "neg": 0})
                slot["pos"] += int(value.get("pos", 0))
                slot["neg"] += int(value.get("neg", 0))
    return [{"month": k, **v} for k, v in sorted(months.items())]


def eras() -> list[dict]:
    path = GIFT / "L1/第1层汇总.md"
    text = path.read_text("utf-8")
    section = text.split("## 人生时间线", 1)[1].split("\n## ", 1)[0]
    result = []
    for block in re.split(r"\n(?=\*\*)", section.strip()):
        head = re.match(r"\*\*(.+?)｜(.+?)\*\*\s*\n?(.*)", block, re.S)
        if not head:
            continue
        period, title, body = head[1].strip(), head[2].strip(), clean(head[3])
        start = month_key(period.replace(" ", "")) or (period[:4] + "-06")
        result.append({"period": period, "title": title, "start": start,
                       "text": body[:360]})
    return result


def people(limit: int = 30) -> list[dict]:
    index = json.loads((GIFT / "L1/digest_index.json").read_text("utf-8"))
    rows = []
    for pid, meta in index.items():
        bio = GIFT / "L1/people" / f"{pid}.md"
        title, line = meta.get("name", pid), ""
        if bio.exists():
            lines = bio.read_text("utf-8").splitlines()
            title = lines[0].lstrip("# ").strip() if lines else title
            line = next((clean(l.split("：", 1)[1]) for l in lines if l.startswith("一句话：")), "")
        rows.append({"id": pid, "name": title, "line": line[:200],
                     "from": month_key(meta.get("from", "")) or START_MONTH,
                     "to": month_key(meta.get("to", "")) or "",
                     "layer": 1, "weight": int(meta.get("chunks", 1))})
    rows.sort(key=lambda r: -r["weight"])
    return sorted(rows[:limit], key=lambda r: r["from"])


def load(path, default):
    return json.loads(path.read_text("utf-8")) if path.is_file() else default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(f.name, path)


def stable_id(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:20]


def model_revision(path):
    stat = path.stat()
    return f"{stat.st_mtime_ns:x}-{stat.st_size:x}"


def assign_homes(people, residents):
    """Keep household membership independent of an edited card name."""
    by_id = {p["id"]: p for p in people}
    first_layer = [p for p in people if p.get("layer") == 1]
    ordinary = {p["id"] for p in sorted(first_layer, key=lambda p: -int(p.get("weight", 0)))[:30]}
    for p in people:
        p["house_style"] = "home-common" if p["id"] in ordinary else None
    for resident in residents:
        key = resident["id"]
        if key not in by_id:
            person = {k: resident.get(k, "") for k in ("id", "name", "from", "to", "line")}
            person.update(weight=0, layer=None)
            people.append(person)
            by_id[key] = person
        p = by_id[key]
        p["house_style"] = resident["style"]
        if resident.get("group"):
            p["home_group"] = resident["group"]


def sculptures():
    rows = []
    first = {"flame-keeper": "一只小熊蜷着膝，把一团火苗捧在手心。", "pocket-stall": "掀开遮阳布，折起的木箱就成了摆卡片的小摊。"}
    entries = {r["id"]: r for r in load(LEDGER, {}).get("items", [])}
    for ident, item in entries.items():
        if item.get("replaces") or item.get("withdrawn") or not item.get("model_path"):
            continue
        # The slot and edit key belong to the original exhibit. Switch only
        # after the corresponding display file and both ledger links exist.
        active = item
        seen = {ident}
        while (successor := entries.get(active.get("replaced_by"))):
            next_id = successor["id"]
            next_model = COMPACT / f"aholo-{next_id}.glb"
            if (next_id in seen or successor.get("replaces") != active["id"] or successor.get("withdrawn")
                    or not successor.get("model_path") or not next_model.is_file()):
                break
            seen.add(next_id)
            active = successor
        model = COMPACT / f"aholo-{active['id']}.glb"
        if not model.is_file():
            continue
        rows.append({"id": f"sc-{ident}", "title": item["title"], "stage": item.get("stage", ""),
                     "description": item.get("description") or first.get(ident, ""),
                     "placement": item.get("placement") or active.get("placement") or {"zone": "entrance"},
                     "version_id": active["id"],
                     "model": str(model), "format": "glb", "model_revision": model_revision(model), "source": "aholo"})
    return rows


def print_state(job):
    progress = job.get("device_progress")
    state = progress.get("state") if isinstance(progress, dict) else None
    if job.get("status") == "finished":
        return "已留实物照片"
    if state == "FINISH":
        return "打印机报告已完成"
    if state == "FAILED":
        return "打印未完成"
    if job.get("status") == "submitted":
        return "打印机已接单，尚无完工回执"
    if job.get("status") in {"print_unknown", "dispatching"}:
        return "发送状态待核实"
    return "尚未开打"


def compact_record(source, dest):
    return {"source": source.name, "source_revision": model_revision(source), "display_revision": model_revision(dest)}


def fresh_compact(source, dest):
    if not dest.is_file() or not 32 < dest.stat().st_size <= 2_000_000:
        return False
    try:
        return load(dest.with_suffix(".source.json"), None) == compact_record(source, dest)
    except (OSError, ValueError):
        return False


def exhibit(path):
    folder = path.parent
    job = load(path, {})
    if not isinstance(job, dict) or not isinstance(job.get("status"), str):
        return None
    # Keep exhibiting the latest model while its replacement is a draft.
    for version in (job, *reversed(job.get("prior_versions", []))):
        if not version.get("status"):
            continue
        revision = version.get("revision")
        if revision is not None and (not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{16}", revision)):
            continue
        files = folder / "versions" / revision if revision else folder
        # The repaired, oriented mesh can differ from the original cloud GLB.
        sliced = version.get("print")
        mesh = sliced.get("mesh") if isinstance(sliced, dict) else None
        candidates = (mesh, *MODEL_NAMES) if mesh in MODEL_NAMES else MODEL_NAMES
        original = next((files / n for n in candidates if (files / n).is_file() and (files / n).stat().st_size), None)
        if original:
            job = version
            break
    else:
        return None
    stat = original.stat()
    task = job.get("lux3d_task_id")
    if type(task) not in (int, str):
        task = None
    ident = "ex-" + stable_id(folder.name)
    small = COMPACT / (ident + ".glb")
    model = small if fresh_compact(original, small) else original
    photo = job.get("finished_photo")
    has_photo = photo in ("finished.jpg", "finished.png") and (files / photo).is_file()
    row = {"id": ident, "title": clean(job.get("title")) or folder.name,
           "date": folder.name if re.fullmatch(r"\d{4}-\d{2}-\d{2}", folder.name) else "",
           "summary": clean(job.get("summary")), "reason": clean(job.get("design_reason")),
           "status": job["status"], "print_state": print_state(job),
           "model": str(model), "format": model.suffix[1:], "original": str(original),
           "model_revision": model_revision(model),
           "photo_url": "/photos/" + ident if has_photo else "", "photo_file": str(files/photo) if has_photo else "",
           "source": "aholo" if task else ("sample" if not folder.name[:1].isdigit() else "daily")}
    return row, task, (stat.st_dev, stat.st_ino)


def exhibits():
    found, seen_tasks, seen_files = [], set(), set()
    # Prefer dated jobs if historical sample entries reference the same model task.
    for path in sorted(DAILY.glob("jobs/*/job.json"), key=lambda p: (not p.parent.name[:1].isdigit(), p)):
        try:
            candidate = exhibit(path)
        except (OSError, ValueError):
            # A single unreadable job should not prevent visiting the rest of the island.
            continue
        if not candidate:
            continue
        row, task, file_id = candidate
        if (task and task in seen_tasks) or file_id in seen_files:
            continue
        found.append(row)
        seen_tasks.add(task)
        seen_files.add(file_id)
    return found


def month_series(rows, end):
    index = {r["month"]: r for r in rows}
    year, month = map(int, START_MONTH.split("-"))
    series = []
    while (key := f"{year:04d}-{month:02d}") <= end:
        data = index.get(key, {})
        series.append({"month": key, "pos": 0, "neg": 0, "peak_note": "", **data,
                       "has_data": data.get("has_data", bool(data.get("pos") or data.get("neg")))})
        year, month = year + (month == 12), month % 12 + 1
    return series


def paragraphs(text):
    value = clean(text or "")
    if len(value) < 100:
        return value
    blocks = []
    for line in value.splitlines():
        chunk = ""
        for sent in re.findall(r"[^。！？]+[。！？]?|[。！？]", line):
            chunk += sent
            if len(chunk) >= 70:
                blocks.append(chunk.strip())
                chunk = ""
        if chunk.strip():
            blocks.append(chunk.strip())
    return "\n\n".join(blocks)


def put_cards(world, edits):
    cards = world["cards"] = {}
    def card(key, kicker, title, text, aside="", row=None):
        fields = {"kicker": clean(kicker), "title": clean(title), "text": paragraphs(text), "aside": paragraphs(aside)}
        cards[key] = fields | edits.get(key, {})
        if row is not None:
            row.update(card_id=key, card=cards[key])
    for e in world["emotions"]:
        text = (f"整理到 {e['pos']} 处开心、{e['neg']} 处难受的片段。" if e["has_data"] else "这个月还没有整理到情绪片段。")
        card("month:"+e["month"], "月灯", e["month"], text, e.get("peak_note", ""), e)
    for e in world["eras"]:
        card("era:"+e["start"], e["period"], e["title"], e["text"], "", e)
    for p in world["people"]:
        period = " — ".join(filter(None, (p["from"], p["to"]))) or "人物小传"
        card("person:"+p["id"], period, p["name"], p["line"], "", p)
    for c in world["circles"]:
        key = str(c.get("id") or stable_id(c["name"], c["from"]))
        card("circle:"+key, c["from"]+" — "+c["to"], c["name"], c["role"], c["type"], c)
    for m in world["moments"]:
        evidence = m.get("evidence") or []
        # The reference survives corrections to the date or headline. Older
        # hand-authored feeds without references retain their original key.
        key = str(m.get("id") or (stable_id("moment", evidence[0]) if evidence else stable_id(m["date"], m["title"])))
        m["id"] = key
        card("moment:"+key, m["date"], m["title"], m["text"], "", m)
    for e in world["exhibits"]:
        card(e["id"], (e["date"] or "样品")+" · "+e["print_state"], e["title"], e["summary"], e["reason"], e)
    for s in world["sculptures"]:
        card(s["id"], s["stage"], s["title"], s["description"], "", s)
    card("core:candle", "生日蜡烛", "二十三", "从 2022 年夏天起，沿月灯走到这里。小屋记着一路遇见的人，展台留给每天做出来的小东西。")
    card("core:empty", "空展台", "留给明天", "下一件做好模型的小物，会出现在这里。")


def current_month():
    return datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m")


def build(*, persist=True):
    feed = load(FEED, None)
    if feed is None:
        feed = {"eras": eras(), "emotions": emotions(), "people": people(), "circles": [], "moments": []}
    world = {k: feed[k] for k in ("eras", "people", "circles", "moments")}
    assign_homes(world["people"], load(HOUSING, {}).get("residents", []))
    end = current_month()
    world_models = sculptures()
    world.update(version=2, start=START_MONTH, end=end, emotions=month_series(feed["emotions"], end),
                 exhibits=exhibits(), sculptures=[m for m in world_models if m["placement"].get("zone") != "home"],
                 houses=[m | {"style": m["id"].removeprefix("sc-")} for m in world_models if m["placement"].get("zone") == "home"])
    put_cards(world, load(EDITS, {}))
    if persist:
        save(OUT, world)
    return world


def source_stamp():
    paths = [FEED, LEDGER, EDITS, HOUSING]
    if not FEED.exists():
        paths += list(GIFT.glob("L[1-6]/emotion_monthly.json")) + list((GIFT / "L1").glob("*.md"))
        paths += [GIFT / "L1/digest_index.json", *GIFT.glob("L1/people/*.md")]
    paths += list(COMPACT.glob("*.glb")) + list(COMPACT.glob("*.source.json"))
    for job in DAILY.glob("jobs/*/job.json"):
        paths.append(job)
        for folder in (job.parent, *job.parent.glob("versions/*")):
            paths.extend(folder / n for n in (*MODEL_NAMES, "finished.jpg", "finished.png"))
    result = []
    for p in paths:
        try:
            st = p.stat()
        except FileNotFoundError:
            continue
        result.append((str(p), st.st_size, st.st_mtime_ns))
    return current_month(), sorted(result)


if __name__ == "__main__":
    world = build()
    print(" ".join(f"{k}={len(world[k])}" for k in ("eras", "emotions", "people", "circles", "moments", "exhibits", "sculptures")))
