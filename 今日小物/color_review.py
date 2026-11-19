"""One private Feishu color choice for one slice, printer and day."""
from datetime import datetime, timedelta
from hashlib import file_digest
import secrets
import feishu_webhook

import feishu_print
from local_store import DEMO_KEYS, Problem, now, printer_identity
from print_prep import size_comparison, with_filament_usage
from printer import available_spools, PrinterError


def public_review(job, today):
    review = job.get("color_review") or {}
    if not review:
        return {"status": "waiting"} if job.get("status") == "prepared" else None
    result = {key: review[key] for key in ("status", "message", "options", "selected", "can_confirm") if key in review}
    if job.get("status") == "prepared" and (review.get("day") != today or review.get("device") != printer_identity()):
        return {"status": "waiting", "message": "需要为当前打印机重新确认颜色。"}
    return result


def approved(job, today):
    review = job.get("color_review") or {}
    selected = review.get("selected") or {}
    return (review.get("status") == "confirmed" and review.get("day") == today
            and bool(review.get("reply_id") and review.get("device") and review.get("slice_sha256"))
            and review["device"] == printer_identity() and selected.get("source") == job.get("source")
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

    def request(self, key):
        day = now().date().isoformat()
        with self.app.guard:
            job = self.app.job(key)
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
                token = review["code"]
            try:
                self.advance(key, job, review)
            except (feishu_print.FeishuError, feishu_webhook.WebhookError, PrinterError, Problem, OSError) as error:
                message = str(error) if not isinstance(error, OSError) else "无法读取切片，请检查本机文件。"
                self.update(key, token, status="error", message=message, delay=180)

    def update(self, key, token, *, delay=0, **fields):
        with self.app.guard:
            job = self.app.job(key) or {}
            review = job.get("color_review") or {}
            if (job.get("status") != "prepared" or job.get("edit_token") or review.get("code") != token or
                    review.get("device") != printer_identity() or review.get("day") != now().date().isoformat()):
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
        webhook = feishu_webhook.configured(self.app.data)
        if not webhook and not feishu_print.configured():
            raise Problem("请在设置中连接普通飞书通知机器人。连接后可重试选色。")
        if review.get("attempted_at"):
            # A restart can follow a delivered message before its receipt was saved.
            self.update(key, code, status="error", delivery_uncertain=True, can_confirm=True,
                        message="飞书送达状态待核对。已收到消息可直接用其中的码选色，未收到可申请新码。")
            return
        if not self.update(key, code, attempted_at=now().isoformat(timespec="seconds"),
                           channel="webhook" if webhook else "private"):
            return
        payload = {"day": key, "title": job.get("title") or "今日小物", "code": code,
                   "choices": choices, "print_details": review["details"]}
        try:
            receipt = (feishu_webhook.notify_colors(self.app.data, **payload) if webhook
                       else feishu_print.notify_colors(**payload))
        except (feishu_print.FeishuError, feishu_webhook.WebhookError) as error:
            if error.uncertain:
                self.update(key, code, status="error", can_confirm=True, delivery_uncertain=True,
                            message="飞书送达结果待核对。已收到可凭码选色，未收到可申请新码。")
                return
            self.update(key, code, attempted_at=None)
            raise
        self.update(key, code, status="sent", receipt=receipt, can_confirm=True,
                    message="飞书已接收通知。请在此选择料槽，用消息中的确认码确认。")

    def confirm(self, key, code, source):
        day = now().date().isoformat()
        with self.app.guard:
            job = self.app.job(key) or {}
            review = job.get("color_review") or {}
            if (key not in DEMO_KEYS | {day} or job.get("status") != "prepared" or job.get("edit_token")
                    or review.get("day") != day or review.get("device") != printer_identity()
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
