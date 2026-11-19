"""Bounded, read-only daily inputs for the user's existing summarizing Agent."""
import argparse
import fcntl
import hashlib
import os
import re
import secrets
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import sqlite3

from local_store import TZ, read_json, save_json

HOME = Path(os.environ.get("MOODPRINT_HOME") or Path.home())  # 演示时指向空目录，不读本人待办和 Codex 记录
WORKSPACE = HOME / "Library/Application Support/FeishuIsland/Workspace/workspace.json"
CODEX = HOME / ".codex"
APPLE_EPOCH = 978307200
TAIL_BYTES = 2 * 1024 * 1024
MAX_THREADS = 48


def island_inputs(day, workspace):
    # Dates saved by Swift's default Codable encoder are seconds since 2001.
    start = datetime.combine(day, time.min, TZ).timestamp() - APPLE_EPOCH
    end = start + 86400
    def in_day(value):
        return type(value) in (int, float) and start <= value < end
    with workspace.open(encoding="utf-8") as handle:
        disk = json.load(handle)
    found = {}
    deleted = set(disk.get("deletedTodoHistoryTasks") or [])
    for event in disk.get("todoHistory") or []:
        if event.get("taskID") not in deleted and in_day(event.get("completedAt")):
            found[(event["taskID"], "completed")] = event.get("title", "")
    for item in disk.get("items", []):
        if item.get("id") in deleted:
            continue
        if in_day(item.get("completedAt")) and item.get("state") == "done":
            found[(item["id"], "completed")] = item.get("title", "")
        if in_day(item.get("created")):
            found[(item["id"], "created")] = item.get("title", "")
    return [{"event": kind, "title": title[:220]} for (_, kind), title in found.items() if isinstance(title, str) and title.strip()]


def completed_messages(path, day):
    # Inspect only the tail of a dated candidate. Never return tool payloads or reasoning.
    with path.open("rb") as handle:
        size = handle.seek(0, 2)
        offset = max(0, size - TAIL_BYTES)
        handle.seek(offset)
        if offset:
            handle.readline()
        messages = []
        for line in handle:
            if b'"task_complete"' not in line:
                continue
            try:
                row = json.loads(line)
                payload = row.get("payload", {})
                if row.get("type") != "event_msg" or payload.get("type") != "task_complete":
                    continue
                stamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
                content = payload.get("last_agent_message")
                if stamp.astimezone(TZ).date() == day and isinstance(content, str) and content.strip():
                    messages.append(content.split("<oai-mem-citation>")[0].strip()[:1200])
            except (TypeError, ValueError, KeyError):
                continue
    return messages[-2:], bool(offset)


def codex_inputs(day, codex, exclude_thread=""):
    start = int(datetime.combine(day, time.min, TZ).timestamp())
    end = int(datetime.combine(day + timedelta(days=1), time.min, TZ).timestamp())
    db = next(iter(sorted(codex.glob("state_[0-9]*.sqlite"), reverse=True)), None)
    if db is None:
        raise FileNotFoundError
    c = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        candidates = c.execute("""
            SELECT rollout_path, title, created_at, updated_at FROM threads
            WHERE source IN ('cli','exec','vscode','desktop','appServer')
                AND (thread_source IS NULL OR thread_source IN ('user','agent_created_thread'))
                AND created_at < ? AND updated_at >= ? AND id != ?
            ORDER BY (updated_at < ?) DESC, updated_at DESC LIMIT ?
        """, (end, start, exclude_thread, end, MAX_THREADS + 1)).fetchall()
    finally:
        c.close()
    items = []
    partial = len(candidates) > MAX_THREADS
    sessions = (codex / "sessions").resolve()
    for filename, title, created, updated in candidates[:MAX_THREADS]:
        messages = []
        if filename:
            path = Path(filename).resolve()
            if (path.is_relative_to(sessions) or path.is_relative_to(codex.resolve() / "archived_sessions")) and path.suffix == ".jsonl" and path.is_file():
                try:
                    messages, cut = completed_messages(path, day)
                    partial |= cut
                except OSError:
                    partial = True
            else:
                partial = True
        active = start <= created < end or start <= updated < end
        if messages or active:
            items.append({"topic": (title or "未命名任务")[:140], "agent_reports": messages})
    return items, partial


GIFT_OUTPUT = HOME / "Desktop/AI 送我的 23 岁生日礼物/output"


def birthday_passages(gift):
    feed = gift / "stage5_analysis/world_feed.json"
    if feed.is_file():
        data = read_json(feed, {})
        passages = []
        for group in ("moments", "eras"):
            for row in data.get(group, []):
                if row.get("safe_for_inspiration") is not True or row.get("kind") == "hard":
                    continue
                text = re.sub(r"\s*\[k:[^\]]*\]", "", row.get("text", "")).strip()
                if not text or "待你决定" in text:
                    continue
                period = row.get("date") or row.get("period")
                source = sorted(set(row.get("evidence") or [])) or [period, row["title"]]
                passage_id = hashlib.sha256(json.dumps(source, ensure_ascii=False).encode()).hexdigest()
                passages.append({"period": period, "title": row["title"], "text": text, "id": passage_id})
        return passages
    # Reviewed, ordinary snippets from the original timeline. Do not draw
    # complete mixed periods: several also describe bereavement or hardship.
    path = gift / "stage4_summaries/rollup/L1/第1层汇总.md"
    if not path.is_file():
        return []
    timeline = path.read_text().partition("## 人生时间线")[2].partition("\n## ")[0]
    candidates = [
        ("2022-02", "一起复习", r"高三冲刺时和[^，。；！？\n]{1,12}互换资料、讲题"),
        ("2022 夏", "第一份社群工作", "进了社群当运营练习生"),
        ("2023", "朗诵比赛", "朗诵进决赛"),
        ("2026-06", "毕业季", r"毕业证由[^，。；！？\n]{1,12}代领"),
    ]
    return [{"period": period, "title": title, "text": match[0] + "。"}
            for period, title, pattern in candidates if (match := re.search(pattern, timeline))]


def birthday_input(day, gift, directory, reserve=True):
    passages = birthday_passages(gift)
    if not passages:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    history_path = directory / "birthday-inspirations.json"
    with (directory / ".birthday-inspirations.lock").open("a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        history = read_json(history_path, {})
        key = day.isoformat()
        previous = history.get(key, {})
        earlier = previous.get("passage", {})
        # Check the current safe feed on every retry. A corrected or withdrawn
        # paragraph must never be resurrected from an older cached selection.
        used = set()
        for stamp, entry in history.items():
            if abs((date.fromisoformat(stamp) - day).days) < 60:
                used.update(entry.get("used", []))
                used.update((entry.get("id"), entry.get("digest")))
                old = entry.get("passage", {})
                used.add((old.get("period"), old.get("title")))
        choices = []
        chosen = None
        for row in passages:
            passage = {k: row[k] for k in ("period", "title", "text")}
            label = (passage["period"], passage["title"])
            ident = row.get("id") or hashlib.sha256(json.dumps(label, ensure_ascii=False).encode()).hexdigest()
            digest = hashlib.sha256(passage["text"].encode()).hexdigest()
            candidate = (ident, digest, passage)
            if previous.get("id") == ident or (not previous.get("id") and previous and
                    (previous.get("digest") == digest or label == (earlier.get("period"), earlier.get("title")))):
                chosen = candidate
                break
            if ident not in used and digest not in used and label not in used:
                choices.append(candidate)
        if not chosen and not choices:
            return None
        ident, digest, passage = chosen or secrets.choice(choices)
        if reserve:
            used_today = set(previous.get("used", []))
            used_today.update(x for x in (previous.get("id"), previous.get("digest"), ident, digest) if x)
            updated = {"id": ident, "digest": digest, "passage": passage, "used": sorted(used_today)}
            if previous != updated:
                history[key] = updated
                save_json(history_path, history)
        return passage


def collect(day, workspace=WORKSPACE, codex=CODEX, exclude_thread="", *, gift=GIFT_OUTPUT,
            directory=None, reserve=True):
    result = {"date": day.isoformat(), "todos": [], "agent_work": [], "partial_agent_window": False, "unavailable": []}
    try:
        result["todos"] = island_inputs(day, workspace)
    except (OSError, ValueError, TypeError, KeyError):
        result["unavailable"].append("一切在岛待办")
    try:
        result["agent_work"], result["partial_agent_window"] = codex_inputs(day, codex, exclude_thread)
    except (OSError, sqlite3.Error):
        result["unavailable"].append("Codex 工作记录")
    if (not result["unavailable"] and not result["partial_agent_window"] and
            not result["todos"] and not any(item["agent_reports"] for item in result["agent_work"])):
        store = directory or Path(os.environ.get("MOODPRINT_DATA", Path(__file__).resolve().parent / "data"))
        try:
            result["birthday_inspiration"] = birthday_input(day, gift, store, reserve)
        except (OSError, ValueError, KeyError, TypeError):
            result["unavailable"].append("生日礼物素材")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="为每日整理读取当天的待办事件和本机 Codex 工作结果")
    parser.add_argument("--date", type=date.fromisoformat, default=datetime.now(TZ).date())
    parser.add_argument("--counts", action="store_true", help="只检查来源与条数")
    parser.add_argument("--exclude-thread", default="", help="在定时整理时排除整理任务自己的聊天")
    args = parser.parse_args()
    result = collect(args.date, exclude_thread=args.exclude_thread, reserve=not args.counts)
    if args.counts:
        result.update(todos=len(result["todos"]), agent_work=len(result["agent_work"]),
                      birthday_inspiration=bool(result.get("birthday_inspiration")))
    print(json.dumps(result, ensure_ascii=False))
