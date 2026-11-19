"""Send personal print notifications through the ordinary Feishu 工作岛 application bot."""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode
import uuid

from local_store import DEMO_KEYS, save_json


PROFILE = "feishu-danmu"
BOT_NAME = "飞书工作岛"
CLI = Path("/Applications/一切在岛.app/Contents/Helpers/lark-cli")
PRODUCTION_DATA = Path(__file__).resolve().parent / "data"
SLOTS = {f"ams-a{i}": f"A{i}" for i in range(1, 5)} | {"external": "外置"}


class FeishuError(Exception):
    def __init__(self, message, *, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


@dataclass(frozen=True, repr=False)
class _Account:
    app_id: str
    owner: str

    @property
    def identity(self):
        return sha256(f"{PROFILE}/{self.app_id}/{self.owner}".encode()).hexdigest()


def _read(path):
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
            return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _state():
    data = Path(os.environ.get("MOODPRINT_DATA") or PRODUCTION_DATA).expanduser().resolve()
    return data / "feishu-owner.json"


def _account():
    if _state().parent != PRODUCTION_DATA:
        raise FeishuError("隔离工作台不连接正式飞书账号。")
    if not CLI.is_file():
        raise FeishuError("找不到一切在岛内置的官方飞书 CLI，请检查应用。")
    apps = _read(Path.home() / ".lark-cli" / "config.json").get("apps") or []
    profiles = [app for app in apps if isinstance(app, dict) and app.get("name") == PROFILE and app.get("brand") == "feishu"]
    if len(profiles) == 1:
        app = profiles[0]
        users = app.get("users") or []
        if (isinstance(users, list) and len(users) == 1 and isinstance(users[0], dict)
                and re.fullmatch(r"ou_[A-Za-z0-9]+", users[0].get("userOpenId") or "")
                and re.fullmatch(r"cli_[A-Za-z0-9]+", app.get("appId", ""))):
            return _Account(app["appId"], users[0]["userOpenId"])
    raise FeishuError("请先为本机「飞书工作岛」登录唯一的个人飞书账号。")


def _api(method, route, *, body=None, params=None):
    sending = method == "POST"
    args = [str(CLI), "--profile", PROFILE, "api", method, "/open-apis" + route, "--as", "bot", "--json"]
    if params:
        args.extend(["--params", json.dumps(params)])
    if body is not None:
        args.extend(["--data", "-"])
    try:
        result = subprocess.run(args, input=json.dumps(body, ensure_ascii=False) if body is not None else None,
                                text=True, capture_output=True, timeout=25)
    except subprocess.TimeoutExpired:
        raise FeishuError("飞书未在时限内返回结果。", uncertain=sending) from None
    except OSError:
        raise FeishuError("无法启动官方飞书 CLI，请检查一切在岛应用。") from None
    parsed = {}
    for stream in (result.stdout, result.stderr):
        try:
            value = json.loads(stream)
        except ValueError:
            continue
        if isinstance(value, dict) and "ok" in value:
            parsed = value
            break
    if result.returncode == 0 and parsed.get("ok") is True and parsed.get("identity") == "bot":
        return parsed.get("data") or {}
    err = parsed.get("error") or {}
    code = str(err.get("code") or "")
    if code.isdigit() and code not in {"0", "500", "502", "503", "504"}:
        raise FeishuError(f"飞书拒绝请求（{code}），请检查机器人的发送权限与个人可见范围。")
    if err.get("type") in {"authorization", "authentication", "validation"}:
        raise FeishuError("飞书拒绝请求，请检查机器人授权与个人可见范围。")
    raise FeishuError("飞书未返回可核对的发送结果。" if sending else "无法确认「飞书工作岛」机器人，请检查网络和应用配置。",
                      uncertain=sending)


def _verify_bot():
    result = _api("GET", "/bot/v3/info")
    if result.get("app_name") != BOT_NAME or not re.fullmatch(r"ou_[A-Za-z0-9]+", result.get("open_id") or ""):
        raise FeishuError("此配置未连接「飞书工作岛」机器人。")
    return result["open_id"]


def configured():
    """A local-only check, also invalidates the binding when the app or owner changes."""
    try:
        return bool(_verified(_account()))
    except FeishuError:
        return False


def _verified(account):
    state = _read(_state())
    if (state.get("version") != 2 or state.get("mode") != "one_way" or state.get("bound") is not True
            or state.get("identity") != account.identity or not state.get("bot_open_id")):
        raise FeishuError("请在本机连接本人已登录的「飞书工作岛」通知。")
    return state


def begin_pairing():
    """Bind the existing authenticated local user's exact app-scoped Open ID; no outbound message."""
    account = _account()
    bot = _verify_bot()
    if _account().identity != account.identity:
        raise FeishuError("本机飞书账号刚刚更改，请重新连接。")
    path = _state()
    path.parent.mkdir(parents=True, exist_ok=True)
    save_json(path, {"version": 2, "bound": True, "mode": "one_way", "identity": account.identity,
                     "bot_open_id": bot})
    return {"bound": True, "mode": "one_way", "bot_name": BOT_NAME}


def notify_colors(*, day, title, code, choices, print_details, claim_code=None):
    claim = claim_code or code
    if (not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9]{6,16}", code)
            or not isinstance(claim, str) or not re.fullmatch(r"[A-Z0-9]{6,32}", claim)
            or not choices or not set(choices) <= SLOTS.keys()
            or not (day in DEMO_KEYS or re.fullmatch(r"\d{4}-\d{2}-\d{2}", day))):
        raise FeishuError("作品、飞书确认码或料槽无效，请重新申请。")
    account = _account()
    binding = _verified(account)
    if _verify_bot() != binding["bot_open_id"] or _account().identity != account.identity:
        raise FeishuError("本机飞书账号或机器人已更改，请重新连接。")
    url = "http://127.0.0.1:17868/?" + urlencode({"day": day}) + "#" + urlencode({"choose": claim})
    options = "\n".join(str(label) for label in choices.values())
    text = (f"今日小物 · 打印选色\n{title}\n{print_details}\n\n可选料槽\n{options}"
            f"\n\n飞书确认码　{claim}\n在这台 Mac 点链接选择颜色。在手机看到提醒时，可回到这台 Mac 打开「今日小物」并输入飞书确认码。\n{url}"
            "\n开打前还需清空并确认打印板。")
    unique = str(uuid.uuid5(uuid.NAMESPACE_URL, f"moodprint/notify/{account.identity}/{day}/{code}"))
    data = _api("POST", "/im/v1/messages", params={"receive_id_type": "open_id"}, body={
        "receive_id": account.owner, "msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False),
        "uuid": unique,
    })
    if (not re.fullmatch(r"om_[A-Za-z0-9]+", data.get("message_id") or "")
            or not re.fullmatch(r"oc_[A-Za-z0-9]+", data.get("chat_id") or "")
            or not str(data.get("create_time") or "").isdigit()):
        raise FeishuError("飞书发送结果未知，请核对原消息。", uncertain=True)
    return {"identity": account.identity, "mode": "one_way", "message_id": data["message_id"],
            "created_ms": int(data["create_time"]), "code": code}
