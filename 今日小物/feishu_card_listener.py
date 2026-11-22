"""Receive print buttons from the bound Feishu app's official event stream."""
from datetime import datetime
import json
import os
import re
import selectors
import subprocess
from threading import Event, Lock, Thread
from time import monotonic

import feishu_print
from generation_card import CREDITS, fingerprint
from local_store import Problem, TZ, checked_job_key, checked_source, now


EVENT = "card.action.trigger"
# Keep the CLI's fetched card content, unrelated actions and form fields out of this process.
PROJECTION = (
    'select(.type == "card.action.trigger" and .host == "im_message" and .action_tag == "button")'
    ' | {type, host, action_tag, action_value, chat_id, message_id, operator_id, event_id, timestamp, token}'
)
READY = b"[event] ready event_key=card.action.trigger"
MAX_LINE = 64 * 1024
PRINT = "moodprint_print"
GENERATE = "moodprint_generate"
ACTIONS = {PRINT, GENERATE}
ACKNOWLEDGE = {
    PRINT: "收到。正在核对打印板和耗材，确认后发送到 P2S，约 1 分钟。",
    GENERATE: "收到，正在开始生成。",
}


class _EventFramer:
    """Join one JSON event from the CLI's stdout. With --jq the CLI pretty-prints
    each event over several lines; without it, an event is a single line."""

    def __init__(self):
        self.lines = []
        self.size = 0

    def feed(self, line):
        if not self.lines and not line.lstrip().startswith(b"{"):
            return None
        self.lines.append(line)
        self.size += len(line) + 1
        raw = b"\n".join(self.lines)
        try:
            json.loads(raw)
        except ValueError:
            # A pretty-printed top-level object closes with "}" in column 0.
            if line == b"}" or self.size > MAX_LINE:
                self.lines, self.size = [], 0
            return None
        self.lines, self.size = [], 0
        return raw


def _shape(value):
    """Describe an event value without keeping tokens or ids in the local log."""
    if isinstance(value, str):
        return f"str[{len(value)}]" + (":" + value[:3] if len(value) > 3 else "")
    return type(value).__name__


def _check_click(raw, account):
    """Parse the official CLI's flat event. It encodes action_value as a JSON string.
    Returns (click, None) or (None, reason) so a dropped tap can be diagnosed."""
    try:
        event = json.loads(raw)
        if not isinstance(event, dict):
            return None, "not an object"
        for field, wanted in (("type", EVENT), ("host", "im_message"), ("action_tag", "button")):
            if event.get(field) != wanted:
                return None, f"{field}={event.get(field)!r}"
        if event.get("operator_id") != account.owner:
            return None, "operator is not the bound owner " + _shape(event.get("operator_id"))
        action = event["action_value"]
        if isinstance(action, str):
            action = json.loads(action)
        if not isinstance(action, dict) or action.get("action") not in ACTIONS:
            return None, "action_value " + _shape(action)
        kind = action["action"]
        day = checked_job_key(action["day"])
        source = checked_source(action["source"]) if kind == PRINT else None
        for name, value, pattern in (
            ("code", action["code"], r"[A-Z0-9]{6,16}"), ("message_id", event["message_id"], r"om_[A-Za-z0-9]+"),
            ("chat_id", event["chat_id"], r"oc_[A-Za-z0-9]+"), ("event_id", event["event_id"], r"[A-Za-z0-9_-]{1,128}"),
            ("timestamp", event["timestamp"], r"[0-9]{13}|[0-9]{16}"),
        ):
            if not isinstance(value, str) or not re.fullmatch(pattern, value):
                return None, f"{name} {_shape(value)}"
        # Documented as milliseconds; the CLI actually delivers microseconds.
        stamp = event["timestamp"]
        clicked_at = datetime.fromtimestamp(int(stamp) / (1000 if len(stamp) == 13 else 1_000_000), TZ)
        return (event, kind, day, action["code"], source, clicked_at), None
    except KeyError as error:
        return None, f"missing {error}"
    except (TypeError, ValueError, OverflowError, RecursionError, Problem) as error:
        return None, type(error).__name__ + ": " + str(error)[:80]


def _parse_click(raw, account):
    return _check_click(raw, account)[0]


def _matches_generate(job, account, event, code):
    card = job.get("generation_card") or {}
    receipt = card.get("receipt") or {}
    return (receipt.get("interaction") == "card" and receipt.get("identity") == account.identity
            and receipt.get("message_id") == event["message_id"] and receipt.get("chat_id") == event["chat_id"]
            and card.get("code") == code)


def _matches(review, account, event, code):
    receipt = review.get("card_receipt") or review.get("receipt") or {}
    return (receipt.get("interaction") == "card" and receipt.get("identity") == account.identity
            and receipt.get("message_id") == event["message_id"] and receipt.get("chat_id") == event["chat_id"]
            and receipt.get("code") == code and review.get("code") == code)


class CardListener:
    def __init__(self, app):
        self.app = app
        self.ready = Event()
        self.status = "未连接"
        self._stop = Event()
        self._lock = Lock()
        self._thread = None
        self._process = None

    def start(self):
        with self._lock:
            if (not self.app.personal_chat or not feishu_print.cards_enabled()
                    or self._thread and self._thread.is_alive()):
                return
            self._stop.clear()
            self._thread = Thread(target=self._supervise, name="Feishu print cards", daemon=True)
            self._thread.start()

    def close(self):
        with self._lock:
            self._stop.set()
            thread = self._thread
            process = self._process
            if process and process.poll() is None:
                process.terminate()
        if thread:
            thread.join()
        self.ready.clear()
        self.status = "未连接"

    def _supervise(self):
        delay = 2
        while not self._stop.is_set():
            started = monotonic()
            self.status = "正在连接"
            try:
                if not feishu_print.cards_enabled():
                    self.status = "未启用"
                    return
                account, binding = feishu_print._checked_binding()
                if not binding.get("card_actions"):
                    return
                self._consume(account, binding["bot_open_id"])
            except (OSError, feishu_print.FeishuError):
                pass
            self.ready.clear()
            if monotonic() - started >= 60:
                delay = 2
            self.status = f"连接中断，{delay} 秒后重试"
            if self._stop.wait(delay):
                break
            delay = min(delay * 2, 60)

    def _consume(self, account, bot_id):
        command = [str(feishu_print.CLI), "--profile", feishu_print.PROFILE, "event", "consume",
                   EVENT, "--as", "bot", "--jq", PROJECTION]
        with self._lock:
            if self._stop.is_set():
                return
            # An open stdin keeps the unbounded consumer alive. Only this child belongs to us.
            process = self._process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
            )
        try:
            self._read_streams(process, account, bot_id)
        finally:
            process.stdin.close()
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()
            with self._lock:
                self._process = None

    def _read_streams(self, process, account, bot_id):
        deadline = monotonic() + 45
        framer = _EventFramer()
        with selectors.DefaultSelector() as streams:
            for pipe in (process.stdout, process.stderr):
                streams.register(pipe, selectors.EVENT_READ, bytearray())
            while streams.get_map() and not self._stop.is_set():
                if not self.ready.is_set() and monotonic() >= deadline:
                    break
                for key, _ in streams.select(1):
                    chunk = os.read(key.fd, 16384)
                    if not chunk:
                        streams.unregister(key.fileobj)
                        continue
                    buffer = key.data
                    buffer.extend(chunk)
                    while b"\n" in buffer:
                        end = buffer.index(b"\n")
                        if end > MAX_LINE:
                            return
                        line = bytes(buffer[:end]).rstrip(b"\r")
                        del buffer[:end + 1]
                        if key.fileobj is process.stdout:
                            if not framer.lines:
                                self.trace("stdout", _shape(line.decode("utf-8", "replace")))
                            event = framer.feed(line)
                            if event and not self._stop.is_set():
                                self.handle(event, account, bot_id)
                        elif line.startswith(READY):
                            self.status = "已连接"
                            self.ready.set()
                        elif line.strip():
                            self.trace("cli", re.sub(r"(token|ticket|access_key)\S*", r"\1=…",
                                                     line.decode("utf-8", "replace"))[:300])
                    if len(buffer) > MAX_LINE:
                        return

    def trace(self, stage, detail=""):
        """Private local trail of each tap, so a silent drop can be found. No tokens or ids."""
        line = json.dumps({"at": now().isoformat(timespec="seconds"), "stage": stage, "detail": detail},
                          ensure_ascii=False)
        try:
            path = self.app.data / "feishu-card-events.log"
            if path.exists() and path.stat().st_size > 256 * 1024:
                path.replace(path.with_suffix(".log.old"))
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except (OSError, AttributeError, TypeError):
            pass

    def handle(self, raw, account, bot_id):
        click, reason = _check_click(raw, account)
        if not click:
            self.trace("dropped", reason)
            return
        event, kind, day, code, source, clicked_at = click
        self.trace("received", f"{kind} {day}")
        try:
            current = feishu_print._account()
            binding = feishu_print._verified(current)
            if current != account or binding.get("card_actions") is not True or binding["bot_open_id"] != bot_id:
                self.trace("dropped", "Feishu binding changed")
                return
        except feishu_print.FeishuError as error:
            self.trace("dropped", str(error))
            return
        with self.app.guard:
            job = self.app.job(day) or {}
            review = job.get("color_review") or {}
            if not (_matches_generate(job, account, event, code) if kind == GENERATE
                    else _matches(review, account, event, code)):
                self.trace("dropped", "card does not match the current piece")
                return

        token = event.get("token")
        usable_token = isinstance(token, str) and token and len(token) <= 4096
        if usable_token:
            # Checking the bed and uploading take a minute; acknowledge the tap now.
            # Feishu allows two updates per callback token: this one and the result.
            try:
                feishu_print.card_feedback(token, ACKNOWLEDGE[kind])
                self.trace("acknowledged")
            except feishu_print.FeishuError as error:
                self.trace("ack failed", str(error))
        else:
            self.trace("no card token")
        if kind == GENERATE:
            message, retry = self.generate(event, day, code, clicked_at, account)
        else:
            message, retry = self.print(event, day, code, source, clicked_at, account)
        self.trace("result", message)
        if usable_token and message:
            try:
                feishu_print.card_feedback(token, message, retry=retry)
            except feishu_print.FeishuError as error:
                self.trace("result update failed", str(error))
                # The print decision is durable; an unsuccessful UI update must not repeat it.
                pass

    def print(self, event, day, code, source, clicked_at, account):
        retry = None
        try:
            message = self.app.print_from_card(
                day, code, source, message_id=event["message_id"], chat_id=event["chat_id"],
                event_id=event["event_id"], identity=account.identity, clicked_at=clicked_at,
            )
        except Problem as error:
            message = str(error)
            with self.app.guard:
                latest = self.app.job(day) or {}
                review = latest.get("color_review") or {}
                if latest.get("status") == "prepared" and not latest.get("edit_token") and _matches(review, account, event, code):
                    # Also show the outcome on the Mac page.
                    review["message"] = "飞书点击没有开打：" + message
                    self.app.save(day, latest)
                    options = review.get("options") or []
                    selected = (review.get("selected") or {}).get("source")
                    choices = {o["source"]: o["label"] + " " + o["color"] for o in options if not selected or o["source"] == selected}
                    if choices and review.get("details"):
                        retry = dict(day=day, title=latest.get("title") or "今日小物", code=code,
                                     choices=choices, print_details=review["details"])
        return message, retry

    def generate(self, event, day, code, clicked_at, account):
        retry = None
        try:
            message = self.app.generation_cards.confirm(
                day, code, message_id=event["message_id"], chat_id=event["chat_id"], event_id=event["event_id"],
                identity=account.identity, clicked_at=clicked_at,
            )
        except Problem as error:
            message = str(error)
            self.app.generation_cards.update(day, code, message="飞书点击没有开始生成：" + message)
            with self.app.guard:
                latest = self.app.job(day) or {}
                card = latest.get("generation_card") or {}
                # An expired card (after midnight) gets no button back.
                if (latest.get("status") == "recorded" and not latest.get("edit_token") and latest.get("idea")
                        and card.get("day") == now().date().isoformat()
                        and _matches_generate(latest, account, event, code) and fingerprint(latest) == card.get("fingerprint")):
                    retry = dict(kind="generate", day=day, title=latest.get("title") or "今日小物", code=code,
                                 idea=latest["idea"], credits=CREDITS)
        return message, retry
