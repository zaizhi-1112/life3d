"""One private Feishu color choice for one slice, printer and day."""
from datetime import date, datetime, timedelta
from hashlib import file_digest
import re
import secrets
import feishu_webhook

import feishu_print
from local_store import DEMO_KEYS, Problem, now, printer_identity
from print_prep import size_comparison, with_filament_usage
from printer import available_spools, PrinterError, PrinterUnreachable


def _historical_slice(key, job, today):
    try:
        parsed = date.fromisoformat(key)
    except (TypeError, ValueError):
        return False
    today = today or now().date().isoformat()
    if parsed.isoformat() != key or key >= today or not job or job.get("status") != "prepared" or job.get("edit_token"):
        return False
    review = job.get("color_review") or {}
    sliced = job.get("print") or {}
    digest = review.get("slice_sha256")
    return (review.get("day") == key and bool(review.get("device")) and review["device"] == printer_identity()
            and isinstance(digest, str) and bool(re.fullmatch(r"[a-f0-9]{64}", digest))
            and sliced.get("artifact") == "print.gcode.3mf" and sliced.get("slice_sha256") == digest)


def can_resume_color(key, job, *, today=None):
    """An earlier workday can reuse only the delivered notice for this exact slice."""
    if not _historical_slice(key, job, today):
        return False
    review = job["color_review"]
    receipt = review.get("receipt") or {}
    if (review.get("status") not in {"sent", "confirmed"} or not isinstance(receipt, dict) or receipt.get("mode") != "one_way"
            or not receipt.get("identity") or not review.get("code") or receipt.get("code") != review["code"]):
        return False
    if review.get("channel") == "webhook":
        return receipt.get("channel") == "webhook"
    return review.get("channel") == "private" and bool(receipt.get("message_id"))


def _definite_rejection(message):
    return isinstance(message, str) and message.startswith(("飞书拒绝请求", "飞书拒绝了通知（"))


def can_retry_color(key, job, *, today=None):
    if not _historical_slice(key, job, today):
        return False
    review = job["color_review"]
    code = review.get("code")
    return (review.get("status") == "error" and "attempted_at" in review and review["attempted_at"] is None
            and not review.get("receipt") and not review.get("delivery_uncertain")
            and review.get("channel") in {"private", "webhook"}
            and isinstance(code, str) and bool(re.fullmatch(r"[A-Z0-9]{6,16}", code))
            and bool(review.get("options") and review.get("details"))
            and (review.get("send_rejected") is True or _definite_rejection(review.get("message"))))


def _current_review(key, review, today):
    return (review.get("day") == today and (key is None or key == today or key in DEMO_KEYS)
            and bool(review.get("device")) and review["device"] == printer_identity())


def public_review(job, today, key=None):
    review = job.get("color_review") or {}
    if not review:
        return {"status": "waiting"} if job.get("status") == "prepared" else None
    result = {key: review[key] for key in ("status", "message", "options", "selected", "can_confirm") if key in review}
    if (review.get("card_receipt") or review.get("receipt") or {}).get("interaction") == "card":
        result["interaction"] = "card"
    if (job.get("status") == "prepared" and not _current_review(key, review, today)
            and not can_resume_color(key, job, today=today) and not can_retry_color(key, job, today=today)):
        return {"status": "waiting", "message": "需要为当前打印机重新确认颜色。"}
    return result


def approved(job, today, key=None):
    review = job.get("color_review") or {}
    selected = review.get("selected") or {}
    return (review.get("status") == "confirmed" and (_current_review(key, review, today) or can_resume_color(key, job, today=today))
            and bool(review.get("reply_id") and review.get("slice_sha256")) and selected.get("source") == job.get("source")
            and bool(selected.get("rgba")))


def describe(result):
    size = size_comparison(result.get("dimensions_mm"))
    seconds = result.get("estimated_seconds")
    if not size or not isinstance(seconds, (int, float)) or not 0 < seconds <= 10800:
        raise Problem("缺少有效尺寸或切片估时，请重新检查切片。")
    minutes = max(1, int(seconds / 60 + 0.5))
    text = f"{size}。预计 {minutes // 60} 小时 {minutes % 60} 分钟"
    grams = result.get("filament_grams")
    return text + (f"，用料 {grams:.2f} 克。" if isinstance(grams, (int, float)) else "。")


class ColorReviews:
    def __init__(self, app):
        self.app = app
        self._requested_retries = {}
        self._active_retries = {}

    def upgrade_notice(self, key):
        """Give a still-pending legacy private notification its native card exactly once."""
        app = self.app
        if not app.personal_chat or not feishu_print.cards_enabled() or not app.card_listener.ready.is_set():
            raise Problem("飞书卡片接收器尚未连接，请稍后重试。")
        with app.guard:
            job = app.job(key) or {}
            review = job.get("color_review") or {}
            receipt = review.get("receipt") or {}
            if (job.get("status") != "prepared" or job.get("edit_token") or review.get("channel") != "private"
                    or review.get("status") not in {"sent", "confirmed"} or not receipt.get("message_id")
                    or review.get("device") != printer_identity() or receipt.get("code") != review.get("code")
                    or receipt.get("identity") != feishu_print.bound_identity()
                    or not review.get("slice_sha256") or review["slice_sha256"] != job["print"].get("slice_sha256")):
                raise Problem("作品、收件人或切片已经变化，请回到作品核对。")
            if review.get("card_receipt") or receipt.get("interaction") == "card":
                return
            if review.get("card_attempted"):
                raise Problem("卡片已尝试发送，请先到飞书核对送达情况。")
            choices = [review["selected"]] if review.get("selected") else review["options"]
            options = {item["source"]: item["label"] + " " + item["color"] for item in choices}
            code = review["code"]
            review["card_attempted"] = True
            app.save(key, job)
        try:
            card = feishu_print.notify_card(day=key, title=job["title"], code=code, choices=options,
                                            print_details=review["details"])
        except feishu_print.FeishuError as error:
            with app.guard:
                latest = app.job(key) or {}
                current = latest.get("color_review") or {}
                if not error.uncertain and current.get("code") == code:
                    current.pop("card_attempted", None)
                    app.save(key, latest)
            raise
        with app.guard:
            latest = app.job(key) or {}
            current = latest.get("color_review") or {}
            if current.get("code") != code or latest.get("status") != "prepared" or latest.get("edit_token"):
                raise Problem("作品已变更，刚发出的卡片不能开打。")
            current["card_receipt"] = card
            app.save(key, latest)

    def request(self, key):
        day = now().date().isoformat()
        with self.app.guard:
            job = self.app.job(key)
            if can_resume_color(key, job, today=day):
                return
            if can_retry_color(key, job, today=day):
                if key not in self._active_retries:
                    self._requested_retries[key] = job["color_review"]["code"]
                return
            if key not in DEMO_KEYS | {day} or not job or job.get("edit_token") or job.get("status") != "prepared":
                raise Problem("只能为当天已切片的作品或样品申请选色。")
            old = job.get("color_review") or {}
            device = printer_identity()
            if not device:
                raise Problem("请先连接 P2S，再获取可选的 PLA 颜色。")
            if old.get("day") == day and old.get("device") == device:
                if old.get("status") in ("sent", "confirmed", "pending"):
                    return
                attempted = old.get("attempted_at")
                expired_send = (not old.get("receipt") and attempted
                                and now() - datetime.fromisoformat(attempted) >= timedelta(minutes=55))
                if old.get("code") and not expired_send and not old.get("delivery_uncertain"):
                    old.update(status="sent" if old.get("receipt") else "pending", next_check="")
                    old.pop("message", None)
                    self.app.save(key, job)
                    return
            job["color_review"] = {"day": day, "device": device, "code": secrets.token_hex(4).upper(),
                                   "status": "pending"}
            self.app.save(key, job)

    def tick(self):
        if not self.app.personal_chat:
            return
        day = now().date().isoformat()
        with self.app.guard:
            requested = self._requested_retries.copy()
            self._requested_retries.clear()
            self._active_retries.update(requested)
        for key, token in requested.items():
            try:
                with self.app.guard:
                    job = self.app.job(key)
                    if not can_retry_color(key, job, today=day) or job["color_review"]["code"] != token:
                        continue
                self.attempt(key, job, job["color_review"])
            finally:
                with self.app.guard:
                    self._active_retries.pop(key, None)
        for key in (day, *sorted(DEMO_KEYS)):
            with self.app.guard:
                job = self.app.job(key) or {}
                if job.get("status") != "prepared" or job.get("edit_token"):
                    continue
                review = job.get("color_review") or {}
                if (not review or review.get("day") != day or review.get("device") != printer_identity()):
                    if key != day and not (review.get("day") == day and review.get("device")):
                        continue
                    try:
                        self.request(key)
                    except Problem:
                        continue
                    job = self.app.job(key)
                    review = job["color_review"]
                if review.get("status") in ("confirmed", "sent") or review.get("delivery_uncertain") or review.get("next_check", "") > now().isoformat(timespec="seconds"):
                    continue
            self.attempt(key, job, review)

    def attempt(self, key, job, review):
        try:
            self.advance(key, job, review)
        except PrinterUnreachable as error:
            # Without the printer there are no spools to offer. Say why once, so
            # the evening does not pass without any message in Feishu.
            reminded = review.get("away_notified") or self.remind_away(key, job, review)
            self.update(key, review["code"], status="error", message=str(error), delay=180,
                        **({"away_notified": True} if reminded else {}))
        except (feishu_print.FeishuError, feishu_webhook.WebhookError, PrinterError, Problem, OSError) as error:
            message = str(error) if not isinstance(error, OSError) else "无法读取切片，请检查本机文件。"
            self.update(key, review["code"], status="error", message=message, delay=180)

    def remind_away(self, key, job, review):
        if review.get("day") != now().date().isoformat() or not feishu_print.configured():
            return False
        text = (f"今日小物 · {job.get('title') or '今天这件'}\n模型已经切好，但这台 Mac 现在连不上打印机（不在同一个局域网）。"
                "连回打印机所在的 Wi-Fi 后，工作台会自动发选色卡。")
        try:
            feishu_print.notify_text(day=key, key="away/" + review["code"], text=text)
        except feishu_print.FeishuError as error:
            # An unclear send may have arrived; Feishu drops a same-key repeat within an hour anyway.
            return error.uncertain
        return True

    def update(self, key, token, *, delay=0, **fields):
        with self.app.guard:
            job = self.app.job(key) or {}
            review = job.get("color_review") or {}
            if (job.get("status") != "prepared" or job.get("edit_token") or review.get("code") != token or
                    review.get("device") != printer_identity()):
                return False
            day = now().date().isoformat()
            if review.get("day") != day:
                if not _historical_slice(key, job, day):
                    return False
                # A send started before midnight may also finish after midnight.
                completed = job | {"color_review": review | fields}
                if (self._active_retries.get(key) != token
                        and not (fields.get("receipt") and can_resume_color(key, completed, today=day))
                        and not (fields.get("send_rejected") and can_retry_color(key, completed, today=day))):
                    return False
            review.update(fields, next_check=(now() + timedelta(seconds=delay)).isoformat(timespec="seconds"))
            if "selected" in fields:
                job["source"] = fields["selected"]["source"]
            if "slice_sha256" in fields:
                job["print"].setdefault("slice_sha256", fields["slice_sha256"])
            self.app.save(key, job)
            return True

    def advance(self, key, job, review):
        code = review["code"]
        if not review.get("options"):
            options = available_spools()
            directory = self.app.files(key, job)
            path = directory / "print.gcode.3mf"
            with path.open("rb") as handle:
                digest = file_digest(handle, "sha256").hexdigest()
            if job["print"].get("slice_sha256", digest) != digest:
                raise Problem("本机切片与尺寸记录不匹配。请恢复对应的切片或为作品重新切片。")
            description = describe(with_filament_usage(job["print"], directory))
            if not self.update(key, code, options=options, slice_sha256=digest, details=description):
                return
            review = review | {"options": options, "details": description}
        choices = {option["source"]: option["label"] + " " + option["color"] for option in review["options"]}
        retry = self._active_retries.get(key) == code
        webhook = review["channel"] == "webhook" if retry else feishu_webhook.configured(self.app.data)
        if not webhook and not feishu_print.configured():
            raise Problem("请在设置中连接普通飞书通知机器人。连接后可重试选色。")
        native = not webhook and self.app.data == feishu_print.PRODUCTION_DATA and feishu_print.cards_enabled()
        if native and not self.app.card_listener.ready.is_set():
            raise Problem("飞书卡片接收器正在连接，工作台稍后会重试。")
        if review.get("attempted_at"):
            # A restart can follow a delivered message before its receipt was saved.
            self.update(key, code, status="error", delivery_uncertain=True, can_confirm=not native,
                        message="卡片送达待核对，已暂停重发。" if native else "飞书送达状态待核对。已收到消息可直接用其中的码选色，未收到可申请新码。")
            return
        if not self.update(key, code, attempted_at=now().isoformat(timespec="seconds"),
                           channel="webhook" if webhook else "private"):
            return
        payload = {"day": key, "title": job.get("title") or "今日小物", "code": code,
                   "choices": choices, "print_details": review["details"]}
        try:
            if webhook:
                receipt = feishu_webhook.notify_colors(self.app.data, **payload)
            elif native:
                receipt = feishu_print.notify_card(**payload)
            else:
                receipt = feishu_print.notify_colors(**payload)
        except (feishu_print.FeishuError, feishu_webhook.WebhookError) as error:
            if error.uncertain:
                self.update(key, code, status="error", can_confirm=not native, delivery_uncertain=True,
                            message="卡片送达待核对，已暂停重发。" if native else "飞书送达结果待核对。已收到可凭码选色，未收到可申请新码。")
                return
            if _definite_rejection(str(error)):
                self.update(key, code, attempted_at=None, status="error", send_rejected=True, can_confirm=False,
                            message=str(error), delay=180)
                return
            self.update(key, code, attempted_at=None)
            raise
        self.update(key, code, status="sent", receipt=receipt, can_confirm=not native,
                    message="请在飞书中点颜色确认打印。" if native else "飞书已接收通知。请在此选择料槽，用消息中的确认码确认。")

    def confirm(self, key, code, source):
        day = now().date().isoformat()
        with self.app.guard:
            job = self.app.job(key) or {}
            review = job.get("color_review") or {}
            if ((not _current_review(key, review, day) and not can_resume_color(key, job, today=day))
                    or job.get("status") != "prepared" or job.get("edit_token")
                    or not review.get("can_confirm") or not review.get("attempted_at")):
                raise Problem("此件还没有有效的飞书选色通知，请先查看当前作品。")
            selected = next((option for option in review["options"] if option["source"] == source), None)
            if not selected:
                raise Problem("请选择这条通知中实际可用的 PLA 料槽。")
            if review.get("retry_after", "") > now().isoformat(timespec="seconds"):
                raise Problem("请核对最新一条飞书通知的确认码，一分钟后重试。")
            candidate = code.strip().upper() if isinstance(code, str) else ""
            if not candidate.isascii() or not secrets.compare_digest(candidate, review["code"]):
                review["wrong_codes"] = review.get("wrong_codes", 0) + 1
                if review["wrong_codes"] >= 5:
                    review.update(wrong_codes=0, retry_after=(now()+timedelta(seconds=60)).isoformat(timespec="seconds"))
                self.app.save(key, job)
                raise Problem("确认码不匹配，请查看本件最近一条飞书通知。")
            review.update(status="confirmed", can_confirm=False, selected=selected, reply_id="local-feishu-code",
                          message="已用本件飞书确认码选色。")
            job["source"] = source
            self.app.save(key, job)
