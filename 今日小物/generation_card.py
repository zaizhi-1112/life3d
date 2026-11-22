"""Ask for today's Aholo credits in Feishu, so the daily piece needs no visit to the Mac."""
from datetime import datetime, timedelta
from hashlib import sha256
import json
import secrets

import feishu_print
from credit_usage import CONCEPT_RATE, G1_RATE
from local_store import Problem, bed_is_ready, connection_state, now


CREDITS = CONCEPT_RATE + G1_RATE
# Feishu drops a repeated message with the same uuid for one hour, so an
# unclear send can be retried with the same code inside this window.
RETRY_WINDOW = timedelta(minutes=50)


def fingerprint(job):
    """One consent covers one exact version of the design sent to Aholo."""
    shape = [job.get("revision"), job.get("idea"), job.get("design_prompt")]
    return sha256(json.dumps(shape, ensure_ascii=False).encode()).hexdigest()


def gated(job, settings):
    return bool(settings["prepare_after_ready"] or job.get("needs_credit_consent"))


def mac_consent(job, key):
    return bool(bed_is_ready(job, key) and job.get("ready_for_generation"))


def feishu_consent(job, key):
    card = job.get("generation_card") or {}
    return card.get("status") == "confirmed" and card.get("day") == key and card.get("fingerprint") == fingerprint(job)


def public_card(job, key):
    card = job.get("generation_card") or {}
    if not card or card.get("day") != key or card.get("fingerprint") != fingerprint(job):
        return None
    return {name: card[name] for name in ("status", "message") if name in card}


class GenerationCards:
    def __init__(self, app):
        self.app = app

    def wanted(self, job, key):
        settings = self.app.settings
        return bool(job and job.get("status") == "recorded" and not job.get("edit_token") and job.get("idea")
                    and settings["auto_prepare"] and gated(job, settings)
                    and not mac_consent(job, key) and not feishu_consent(job, key))

    def tick(self):
        app = self.app
        if not app.personal_chat:
            return
        stamp = now()
        key = stamp.date().isoformat()
        moment = stamp.isoformat(timespec="seconds")
        with app.guard:
            if stamp.strftime("%H:%M") < app.settings["at"]:
                return
            job = app.job(key)
            if not self.wanted(job, key) or not connection_state()["aholo"]:
                return
            if not feishu_print.cards_enabled() or not app.card_listener.ready.is_set():
                return
            card = job.get("generation_card") or {}
            if card.get("day") != key or card.get("fingerprint") != fingerprint(job):
                card = {"day": key, "fingerprint": fingerprint(job), "code": secrets.token_hex(4).upper(),
                        "status": "pending"}
            if card["status"] in {"sent", "confirmed", "uncertain"} or card.get("next_check", "") > moment:
                return
            first = card.setdefault("first_attempt", moment)
            if stamp - datetime.fromisoformat(first) > RETRY_WINDOW:
                card.update(status="uncertain", message="飞书生成确认卡没有发出可核对的结果。可在这里勾选清盘后生成。")
                job["generation_card"] = card
                app.save(key, job)
                return
            card["next_check"] = (stamp + timedelta(minutes=3)).isoformat(timespec="seconds")
            job["generation_card"] = card
            app.save(key, job)
            payload = dict(day=key, title=job.get("title") or "今日小物", code=card["code"], idea=job["idea"],
                           credits=CREDITS)
        try:
            receipt = feishu_print.notify_generate_card(**payload)
        except feishu_print.FeishuError as error:
            # Retried with the same code in three minutes; Feishu deduplicates it.
            self.update(key, payload["code"], status="error", message=str(error))
            return
        self.update(key, payload["code"], status="sent", receipt=receipt,
                    message="已发到飞书。点「生成」后开始制作，也可以在这里勾选清盘后生成。")

    def update(self, key, code, **fields):
        with self.app.guard:
            job = self.app.job(key) or {}
            card = job.get("generation_card") or {}
            if card.get("code") != code or card.get("status") == "confirmed" or job.get("status") != "recorded":
                return
            card.update(fields)
            self.app.save(key, job)

    def confirm(self, key, code, *, message_id, chat_id, event_id, identity, clicked_at):
        app = self.app
        received = now()
        day = received.date().isoformat()
        if (not isinstance(clicked_at, datetime) or clicked_at.utcoffset() is None
                or not -90 <= (received - clicked_at).total_seconds() <= 300):
            raise Problem("这次点击已过期，请重新点「生成」。")
        if key != day or clicked_at.astimezone(received.tzinfo).date() != received.date():
            raise Problem("这张生成确认卡已过期，不会再用于生成。")
        with app.guard:
            job = app.job(key) or {}
            card = job.get("generation_card") or {}
            receipt = card.get("receipt") or {}
            if (card.get("code") != code or receipt.get("interaction") != "card" or receipt.get("identity") != identity
                    or receipt.get("message_id") != message_id or receipt.get("chat_id") != chat_id):
                raise Problem("这张卡片与本人或当前作品不匹配。")
            title = job.get("title") or "今日小物"
            if job.get("status") in {"generating", "slicing"}:
                return f"「{title}」正在制作，切片后会发选色卡。"
            if job.get("status") in {"prepared", "dispatching", "submitted", "finished", "print_unknown"}:
                return f"「{title}」已经做好，请看最新的选色卡。"
            if job.get("edit_token") or card.get("fingerprint") != fingerprint(job) or card.get("day") != key:
                raise Problem("作品已改动，这张卡不再有效。改好后会发新的生成确认卡。")
            if job.get("status") != "recorded":
                raise Problem("这件作品需要在工作台继续，打开「今日小物」查看原因。")
            if card.get("status") != "confirmed":
                card.update(status="confirmed", event_id=event_id, consented_at=received.isoformat(timespec="seconds"),
                            message="已在飞书确认生成。")
                app.save(key, job)
            if app.working_key is not None:
                return f"已确认。工作台忙完手上的事就开始生成「{title}」。"
            app.run(key, "generate")
            return f"已开始生成「{title}」。大约 20 分钟后切好，再发选色卡给你。"
