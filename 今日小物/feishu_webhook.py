"""One-way print notices to a custom Feishu bot in the user's own private group."""
import base64
from contextlib import contextmanager
from datetime import date
import fcntl
from hashlib import sha256
import hmac
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
from time import time
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPRedirectHandler, Request

from local_store import DEMO_KEYS, read_json, save_json
from printer import FEED_SOURCES


HOOK = re.compile(r"https://open\.feishu\.cn/open-apis/bot/v2/hook/[a-zA-Z0-9_-]{16,128}")
CONFIG = "feishu-webhook.json"


class WebhookError(Exception):
    def __init__(self, message, *, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


@contextmanager
def _locked(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(directory / ".webhook.lock", os.O_CREAT | os.O_RDWR, 0o600), "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _config(directory):
    try:
        value = read_json(directory / CONFIG, {})
        if (isinstance(value, dict) and value.get("only_me") is True and
                isinstance(value.get("webhook"), str) and HOOK.fullmatch(value["webhook"]) and
                isinstance(value.get("secret", ""), str)):
            return value
    except (ValueError, OSError):
        pass
    return {}


def configured(data_dir):
    return bool(_config(Path(data_dir)))


def configure(data_dir, *, webhook, secret=None, only_me=False):
    """A blank URL keeps the destination. A changed URL needs its own signing secret."""
    if only_me is not True:
        raise WebhookError("请先确认这是仅有你本人的专用通知群。")
    directory = Path(data_dir)
    with _locked(directory):
        previous = _config(directory)
        if webhook is None or webhook == "":
            webhook = previous.get("webhook", "")
        if not isinstance(webhook, str) or not HOOK.fullmatch(webhook.strip()):
            raise WebhookError("请粘贴飞书自定义机器人的完整 HTTPS Webhook 地址。")
        webhook = webhook.strip()
        if secret is None:
            secret = previous.get("secret", "") if previous.get("webhook") == webhook else ""
        if not isinstance(secret, str) or len(secret) > 256 or any(not 33 <= ord(char) <= 126 for char in secret):
            raise WebhookError("签名密钥格式有误，请重新复制。")
        save_json(directory / CONFIG, {"only_me": True, "webhook": webhook, "secret": secret})
    return {"configured": True}


def disable(data_dir):
    directory = Path(data_dir)
    with _locked(directory):
        save_json(directory / CONFIG, {})
    return {"configured": False}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post(config, payload):
    if config.get("secret"):
        stamp = str(int(time()))
        key = (stamp + "\n" + config["secret"]).encode()
        payload.update(timestamp=stamp, sign=base64.b64encode(hmac.digest(key, b"", "sha256")).decode())
    body = json.dumps(payload, ensure_ascii=False).encode()
    if len(body) > 20000:
        raise WebhookError("通知内容超过飞书大小限制，请缩短提示。")
    request = Request(config["webhook"], data=body, headers={"Content-Type": "application/json"}, method="POST")
    unknown = "飞书送达结果不明，本次通知已停止重发。请查看专用通知群。"
    try:
        with build_opener(_NoRedirect()).open(request, timeout=10) as response:
            if response.status != 200:
                raise WebhookError(unknown, uncertain=True)
            raw = response.read(8193)
    except HTTPError as error:
        with error:
            if not 400 <= error.code < 500:
                raise WebhookError(unknown, uncertain=True) from None
            try:
                raw = error.read(8193)
            except (HTTPException, OSError):
                raise WebhookError(unknown, uncertain=True) from None
        failed_http = True
    except (OSError, HTTPException, ValueError, UnicodeError):
        raise WebhookError(unknown, uncertain=True) from None
    else:
        failed_http = False
    try:
        data = json.loads(raw) if len(raw) <= 8192 else None
    except (UnicodeError, ValueError):
        raise WebhookError(unknown, uncertain=True) from None
    if not isinstance(data, dict):
        raise WebhookError(unknown, uncertain=True)
    status = data.get("code", data.get("StatusCode"))
    if type(status) is not int:
        raise WebhookError(unknown, uncertain=True)
    if status != 0:
        raise WebhookError(f"飞书拒绝了通知（{status}），请核对机器人签名、关键词和可用状态。")
    if failed_http:
        raise WebhookError(unknown, uncertain=True)


def _notice(day, title, code, choices, print_details):
    if not isinstance(day, str):
        raise WebhookError("无效的作品日期。")
    if day in DEMO_KEYS:
        label = "样品"
    else:
        try:
            label = date.fromisoformat(day).isoformat()
        except ValueError:
            raise WebhookError("无效的作品日期。") from None
        if day != label:
            raise WebhookError("无效的作品日期。")
    if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9]{6,16}", code):
        raise WebhookError("选色确认码无效。")
    if not isinstance(choices, dict) or not choices or not choices.keys() <= set(FEED_SOURCES):
        raise WebhookError("缺少有效的 PLA 选项。")
    if not all(isinstance(v, str) and v.strip() for v in (title, print_details, *choices.values())):
        raise WebhookError("选色通知缺少作品或耗材信息。")
    local_url = f"http://127.0.0.1:17868/?day={day}#choose={code}"
    def line(value):
        return [{"tag": "text", "text": value}]
    rows = [line(f"{label} · {title}"), line(print_details), line("可选耗材　" + "、".join(choices.values())),
            line(f"确认码　{code}"), line("在运行「今日小物」的 Mac 打开这件作品，核对确认码并选择料槽。"),
            [{"tag": "a", "text": "在这台 Mac 打开作品", "href": local_url}], line(local_url)]
    return {"msg_type": "post", "content": {"post": {"zh_cn": {"title": "今日小物 · 待选色", "content": rows}}}}


def notify_colors(data_dir, *, day, title, code, choices, print_details):
    """Send once per request. A pending marker survives crashes and ambiguous HTTP outcomes."""
    payload = _notice(day, title, code, choices, print_details)
    directory = Path(data_dir)
    deliveries = directory / "webhook-deliveries"
    result_path = deliveries / (day + "-" + code + ".json")
    with _locked(directory):
        config = _config(directory)
        if not config:
            raise WebhookError("请先在本机设置仅有本人的飞书通知群。")
        receipt = {"mode": "one_way", "channel": "webhook", "code": code,
                   "identity": sha256(config["webhook"].encode()).hexdigest()}
        try:
            record = read_json(result_path, None)
        except (OSError, ValueError):
            raise WebhookError("无法核对上次通知，本次已停止重发。", uncertain=True) from None
        if record is not None:
            if isinstance(record, dict) and record.get("status") == "sent" and record.get("receipt") == receipt:
                return receipt
            if not isinstance(record, dict) or record.get("status") != "rejected":
                raise WebhookError("本次通知已尝试发送。请先查看飞书专用群。", uncertain=True)
        deliveries.mkdir(mode=0o700, exist_ok=True)
        save_json(result_path, {"status": "attempted"})
    try:
        _post(config, payload)
    except WebhookError as error:
        if not error.uncertain:
            with _locked(directory):
                save_json(result_path, {"status": "rejected"})
        raise
    try:
        with _locked(directory):
            save_json(result_path, {"status": "sent", "receipt": receipt})
    except OSError:
        raise WebhookError("飞书已接受通知，本机暂未保存回执。请查看专用通知群。", uncertain=True) from None
    return receipt
