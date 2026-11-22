"""Local job files, daily record inputs and credentials for 今日小物."""
from datetime import datetime
from hashlib import sha256
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
from zoneinfo import ZoneInfo

from printer import FEED_SOURCES, LAN_NETWORKS, PRINTER_ENV


TZ = ZoneInfo("Asia/Taipei")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
DEFAULTS = {"at": "20:30", "auto_prepare": False, "auto_print": False, "prepare_after_ready": False}
CONCEPT_ARTIFACTS = {"concept.png", "concept.jpg"}
DEMO_KEYS = {"sample", "character", "aholo-character"}
ACTIVE = {"generating", "slicing", "dispatching"}
REVISION = re.compile(r"[0-9a-f]{16}\Z")
RECORD_FIELDS = {"date", "summary", "mood", "title", "idea"}
MOTIFS = [
    ("夜班邮差", "一只坐着的小水獭邮差，圆脑袋微微侧倾，短耳朵、豆豆眼和微笑，戴一顶向左偏的短檐邮差帽，双爪把一封厚实的信贴在胸前，尾巴贴地弯到脚旁"),
    ("抱杯打盹", "一只困得眯眼的小熊坐着抱圆杯，双爪贴着杯壁，圆耳朵压低，脚掌和宽臀落在地面上"),
    ("雨天巡逻员", "一只穿连帽雨衣的圆脸小鸭，抬起一只翅膀打招呼，短雨靴并排站立，衣帽和翅膀贴近身体"),
    ("口袋唱机", "一台复古圆角唱机，低矮宽厚的机身，顶面有一张凸起唱片和贴合机身的唱臂，前面有两枚大圆旋钮"),
    ("蘑菇烘焙师", "一位长着蘑菇帽的小小烘焙师，半闭眼笑，短手把一块圆面包托在圆肚皮上，厚围裙贴合身体"),
    ("月球送货员", "一个圆头小机器人向前探身，把包裹夹在两只短臂和身体之间，胖脚稳稳落地，胸前有一枚凸起的圆形按钮"),
]
MOODS = {"平静", "有劲", "疲惫", "松一口气", "烦乱", "未标记"}

CONNECTION_FIELDS = ("LUX3D_API_KEY", *PRINTER_ENV)


class Problem(Exception):
    pass


def now():
    return datetime.now(TZ)


def read_json(path, fallback):
    if not path.is_file():
        return fallback
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, payload):
    tmp = path.with_suffix(".part")
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def credentials(data):
    """Load only supported variables from a private, optional local JSON file."""
    values = read_json(data / "connections.json", {})
    if not isinstance(values, dict):
        raise Problem("连接配置需要使用 JSON 对象。")
    for key in (*CONNECTION_FIELDS, "LUX3D_BASE_URL"):
        if isinstance(values.get(key), str) and values[key].strip():
            os.environ.setdefault(key, values[key].strip())


def checked_text(value, field, maximum, required=False):
    if not isinstance(value, str) or len(value.strip()) > maximum:
        raise Problem(f"{field}最多 {maximum} 字。")
    value = value.strip()
    if required and not value:
        raise Problem(f"请填写{field}。")
    return value


def checked_date(value):
    if not isinstance(value, str) or not DATE.fullmatch(value):
        raise Problem("日期请使用 YYYY-MM-DD。")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise Problem("请填写有效的日期。") from None
    if value > now().date().isoformat():
        raise Problem("请填写今天或更早的日期。")
    return value


def checked_job_key(key):
    return key if isinstance(key, str) and key in DEMO_KEYS else checked_date(key)


def checked_source(source):
    if not isinstance(source, str) or source not in FEED_SOURCES:
        raise Problem("请选择外置 PLA 或第一台 AMS 的料位。")
    return source


def validate_settings(settings):
    if not isinstance(settings, dict) or set(settings) != set(DEFAULTS):
        raise Problem("请检查每日安排。")
    if not isinstance(settings["at"], str) or not TIME.fullmatch(settings["at"]):
        raise Problem("请选择有效的每日准备时间。")
    if any(type(settings[key]) is not bool for key in ("auto_prepare", "auto_print", "prepare_after_ready")):
        raise Problem("请检查自动化开关。")
    if settings["auto_print"] and not settings["auto_prepare"]:
        raise Problem("开启自动发送前，请开启每天自动准备。")
    if settings["prepare_after_ready"] and not settings["auto_print"]:
        raise Problem("清盘后自动制作需要同时开启自动准备和发送。")


def load_settings(directory):
    try:
        saved = read_json(directory / "settings.json", {})
        settings = DEFAULTS | saved
        validate_settings(settings)
    except (OSError, ValueError, TypeError, Problem):
        return DEFAULTS.copy(), "每日安排无法读取，自动操作已暂停。请检查时间和开关后保存。"
    return settings, None


def connection_state():
    fields = {key: bool(os.environ.get(key)) for key in CONNECTION_FIELDS}
    return {"aholo": fields["LUX3D_API_KEY"], "printer": all(fields[k] for k in PRINTER_ENV), "fields": fields}


def update_credentials(directory, data):
    if not data or set(data).difference(CONNECTION_FIELDS):
        raise Problem("连接字段无效。")
    updates = {}
    for key, raw in data.items():
        value = checked_text(raw, "连接信息", 256)
        if not value:
            continue
        if key == "BAMBU_IP":
            try:
                address = ipaddress.IPv4Address(value)
            except ValueError:
                raise Problem("请填写 P2S 的局域网 IPv4 地址。") from None
            if not any(address in network for network in LAN_NETWORKS):
                raise Problem("请填写 P2S 的局域网地址。")
        if key == "BAMBU_SERIAL" and not re.fullmatch(r"22E[A-Z0-9]{8,24}", value):
            raise Problem("请核对打印机序列号。")
        if key == "BAMBU_ACCESS_CODE" and not re.fullmatch(r"[A-Za-z0-9]{8}", value):
            raise Problem("请核对局域网访问码。")
        if key == "LUX3D_API_KEY" and not all(33 <= ord(char) <= 126 for char in value):
            raise Problem("请核对 Aholo API Key，检查是否多复制了空格或换行。")
        updates[key] = value
    if updates:
        path = directory / "connections.json"
        save_json(path, read_json(path, {}) | updates)
        os.environ.update(updates)


def design_choices(job):
    """Older job files contain the final design but no explicit override flags."""
    motif = next((name for name, idea in MOTIFS if job.get("idea") == idea), None)
    custom_design = job.get("custom_design", bool(job.get("idea")) and motif is None)
    custom_title = job.get("custom_title", bool(job.get("title")) and job["title"] != (motif or "今日小物"))
    return {"custom_design": custom_design, "custom_title": custom_title}


def record_from_input(data, previous, recent_titles):
    if set(data) - RECORD_FIELDS:
        raise Problem("记录只接受 date、summary、mood、title、idea。")
    summary = checked_text(data.get("summary", ""), "当天摘要", 4000, True)
    mood = data.get("mood") or "未标记"
    if not isinstance(mood, str) or mood not in MOODS:
        raise Problem("请选择一个有效的心情。")
    title = checked_text(data.get("title", ""), "摆件名称", 40)
    idea = checked_text(data.get("idea", ""), "摆件描述", 600)
    old = previous or {}
    flags = design_choices(old)
    same_entry = old.get("summary") == summary and old.get("mood") == mood
    if previous and old.get("status") != "recorded":
        # A repeat handoff can acknowledge the locked record without modifying it.
        title_matches = "title" not in data or title == old.get("title") or (not title and not flags["custom_title"])
        idea_matches = "idea" not in data or idea == old.get("idea") or (not idea and not flags["custom_design"])
        if same_entry and title_matches and idea_matches:
            return previous
        raise Problem("这一天已开始制作，原来的记录和摆件已锁定。")
    # Agents often update just the summary. An empty field explicitly clears
    # an override, while an omitted field preserves the user's choice.
    if "title" not in data and flags["custom_title"]:
        title = old["title"]
    if "idea" not in data and flags["custom_design"]:
        idea = old["idea"]
    overrides = {"custom_title": bool(title), "custom_design": bool(idea)}
    if not idea:
        if old.get("mood") == mood and not flags["custom_design"] and old.get("idea"):
            idea = old["idea"]
            selected_title = next((name for name, shape in MOTIFS if shape == idea), "今日小物")
        else:
            choices = MOTIFS[:3] if mood in {"疲惫", "平静", "烦乱"} else MOTIFS
            fresh = [item for item in choices if item[0] not in recent_titles]
            selected_title, idea = secrets.choice(fresh or choices)
        title = title or selected_title
    record = {
        **(previous or {"source": "external", "ready": False}), **overrides,
        "status": "recorded", "summary": summary, "mood": mood, "title": title or "今日小物", "idea": idea,
    }
    return previous if record == previous else record


def printer_identity():
    serial = os.environ.get("BAMBU_SERIAL", "").strip()
    return sha256(serial.encode()).hexdigest() if serial else None


def bed_is_ready(job, today):
    return bool(job.get("ready") and job.get("ready_date") == today
                and job.get("ready_device") and job["ready_device"] == printer_identity())


def bed_is_ready_to_print(job, today):
    signature = job.get("ready_bed")
    return bool(bed_is_ready(job, today) and isinstance(signature, str) and re.fullmatch(r"[0-9a-f]{64}", signature))


def public_job(job, today):
    if job is None:
        return None
    result = {key: value for key, value in job.items()
              if not key.startswith("lux3d_") and key not in {"color_review", "ready_device", "ready_bed", "device_ticket", "studio_task_name", "sent_device", "prior_versions", "manual_record", "generation_card"}}
    ready = bed_is_ready_to_print(job, today) if job.get("print") else bed_is_ready(job, today)
    result.update(design_choices(job), ready=ready)
    concept = job.get("lux3d_concept_filename")
    if concept in CONCEPT_ARTIFACTS:
        result["concept_image"] = concept
    if job["status"] == "generating" and not job.get("lux3d_task_id"):
        result["designing"] = True
    return result


def artifact_directory(day_folder: Path, job):
    revision = job.get("revision")
    if revision is None:
        return day_folder
    if not isinstance(revision, str) or not REVISION.fullmatch(revision):
        raise Problem("本机作品版本无法读取。")
    return day_folder / "versions" / revision


class JobStore:
    """JSON files are authoritative. Index only collection labels for display."""
    def __init__(self, data):
        self.jobs = data / "jobs"
        self.jobs.mkdir(parents=True, exist_ok=True)
        self.collection = {}

    def directory(self, key):
        return self.jobs / key

    def read(self, key):
        path = self.directory(key) / "job.json"
        try:
            with path.open(encoding="utf-8") as handle:
                job = json.load(handle)
            if isinstance(job, dict) and isinstance(job.get("status"), str):
                return job
        except FileNotFoundError:
            return None
        except (UnicodeError, ValueError, OSError):
            pass
        return {"status": "unreadable", "error": "这条本地记录无法读取。原文件已保留。"}

    def remember(self, key, job):
        if DATE.fullmatch(key):
            self.collection[key] = {
                "date": key, "title": job.get("title", ""), "status": job["status"], "mood": job.get("mood", ""),
            }

    def save(self, key, job):
        directory = self.directory(key)
        directory.mkdir(exist_ok=True)
        save_json(directory / "job.json", job)
        self.remember(key, job)

    def load_existing(self):
        for directory in self.jobs.iterdir():
            key = directory.name
            if key not in DEMO_KEYS and not DATE.fullmatch(key):
                continue
            job = self.read(key)
            if job is not None:
                self.remember(key, job)
                yield key, job
