"""Coordinate the daily record, Aholo preparation and P2S dispatch."""
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, RLock, Thread
from time import monotonic

import history_context
import feishu_print
import feishu_webhook
from color_review import ColorReviews, approved, public_review
from credit_usage import CreditLedger
from daily_draft import draft_for_day
from finished_photo import prepare_photo
from local_store import (
    ACTIVE, CONCEPT_ARTIFACTS, DEMO_KEYS, JobStore, Problem, artifact_directory, bed_is_ready, bed_is_ready_to_print, checked_date, checked_job_key,
    checked_source, connection_state, load_settings, now, printer_identity,
    checked_text, public_job, record_from_input, save_json, update_credentials, validate_settings,
)
from lux3d import generate_model, Lux3DError
from print_prep import prepare_print, size_comparison, with_filament_usage, PreparationError
from printer import read_idle_bed, send_print, printer_status, valid_studio_name, ColorChanged, PrinterError, PrintStatusUnknown
from sample import IDEA, SUMMARY, TITLE, make_sample


MAX_MINUTES = 180
DOWNLOADS = {"preview.png", "model-preview.png", "model.stl", "print.gcode.3mf"}


def concept_prompt(idea):
    return (
        "设计下面描述的掌心收藏玩具，作为图生3D的造型参考。主体本身是完整的三维雕塑，"
        "从正面偏转约20度拍摄，同时看清正面与侧面厚度。角色用表情和姿势表现性格，"
        "手持物紧贴躯干，轮廓里看得出头、身体和短肢。物品保留最有辨识度的三维结构。"
        "用光滑哑光暖白树脂白模表现，背景浅灰，柔和均匀的棚拍光，主体居中，完整入镜。"
        "边缘圆润，表面干净无颗粒。按最终6厘米高的FDM摆件设计，"
        "下盘宽且平，细节使用约1毫米以上的几何体，悬挑靠近身体并与主体连成一体。"
        "画面无文字、边框、浮雕牌、背景道具或强投影。"
        "造型主题：" + idea
    )


def present(job, today):
    view = public_job(job, today)
    if view is None:
        return None
    if job.get("print"):
        view["print"] = job["print"] | {"size_comparison": size_comparison(job["print"].get("dimensions_mm"))}
    review = public_review(job, today)
    if review is not None:
        view["color_review"] = review
    if job.get("design_prompt"):
        if job.get("lux3d_concept_task_id"):
            status = "sent"
        elif job.get("lux3d_concept_create_pending"):
            status = "unknown"
        else:
            status = "planned"
    elif job["status"] == "recorded" and job.get("idea"):
        view["design_prompt"] = concept_prompt(job["idea"])
        status = "planned"
    else:
        status = "archived"
    view["prompt_status"] = status
    return view


def clear_approval(job):
    for field in ("ready_date", "ready_device", "ready_bed", "color_review"):
        job.pop(field, None)
    job.update(ready=False, ready_for_generation=False)


def inspirations(refs, data_dir):
    if not isinstance(refs, list) or len(refs) > 3:
        raise Problem("每件作品最多可关联三条历史原话。")
    items = []
    seen = set()
    for ref in refs:
        if not isinstance(ref, str) or not history_context.REF.fullmatch(ref):
            raise Problem("历史引用需要使用本机索引的条目编号。")
        if ref in seen:
            continue
        try:
            item = history_context.lookup(ref, data_dir=data_dir)
        except (sqlite3.Error, OSError):
            raise Problem("本机历史索引暂时无法读取，请稍后重试。") from None
        if item is None:
            raise Problem("有一条原话在本机索引中不存在。请重新选择。")
        kind = "本人发送的微信文字" if item["source_type"] == "wechat_self_text" else "本人历史文字"
        items.append({"ref": ref, "quote": item["excerpt"], "source": item["date"] + " · " + kind,
                      "redacted": bool(item.get("redacted"))})
        seen.add(ref)
    return items

def studio_observation(job):
    name, version = job.get("studio_task_name"), job.get("artifact_version")
    if job.get("submitted_via") == "Bambu Studio" and valid_studio_name(name, version):
        return name, version
    return None


class App:
    def __init__(self, data):
        self.data = data
        self.personal_chat = data.resolve() == Path(__file__).resolve().parent / "data"
        self.store = JobStore(data)
        self.credits = CreditLedger(data)
        self.colors = ColorReviews(self)
        self.guard = RLock()
        self.worker = None
        self.working_key = None
        self.organize_worker = None
        self.organizing_key = None
        self.organize_errors = {}
        self.checking_printer = False
        self.bed_check_key = None
        self.tracked_key = None
        self.next_observation = 0
        self.stop = Event()
        self.settings, self.settings_error = load_settings(data)
        self.recover()

    def directory(self, key):
        return self.store.directory(key)

    def files(self, key, job):
        return artifact_directory(self.directory(key), job)

    def download(self, key, name, edition=None, revision=None):
        job = self.job(checked_job_key(key))
        if not job:
            raise Problem("找不到作品文件。")
        if edition is not None:
            versions = job.get("prior_versions", [])
            if not 0 <= edition < len(versions):
                raise Problem("找不到这件作品的旧版。")
            job = versions[edition]
        elif revision is not None and revision != (job.get("revision") or "original"):
            job = next((version for version in job.get("prior_versions", []) if version.get("status")
                        and revision == (version.get("revision") or "original")), None)
            if not job:
                raise Problem("找不到这件作品的旧版。")
        return self.artifact(key, job, name)

    def artifact(self, key, job, name):
        folder = self.files(key, job)
        if name in CONCEPT_ARTIFACTS and job.get("lux3d_concept_filename") == name:
            return folder / name
        if name in {"finished.jpg", "finished.png"} and job.get("finished_photo") == name:
            return folder / name
        if name in DOWNLOADS and job.get("print"):
            return folder / name
        raise Problem("找不到作品文件。")

    def job(self, key):
        return self.store.read(key)

    def save(self, key, job):
        self.store.save(key, job)

    def recover(self):
        latest = ""
        for key, job in self.store.load_existing():
            if (job.get("device_ticket") or studio_observation(job)) and job["status"] == "submitted" and job.get("submitted_at", "") > latest:
                self.tracked_key, latest = key, job["submitted_at"]
            if job["status"] not in ACTIVE:
                continue
            if job["status"] == "dispatching":
                job.pop("ready_bed", None)
                job.update(status="print_unknown", ready=False, error="上次发送时应用中断。请在打印机屏幕确认任务。")
            else:
                job.update(status="failed", error="上次准备时应用中断，可以继续准备。")
            self.save(key, job)

    def state(self, key):
        today = now().date().isoformat()
        key = today if key == "today" else checked_job_key(key)
        try:
            index = history_context.summary(data_dir=self.data)
            history_status = {"count": index["segments"], "sources": index["sources"]}
        except (sqlite3.Error, OSError, ValueError):
            history_status = {"count": 0, "sources": 0, "error": "个人历史索引暂时无法读取"}
        with self.guard:
            samples = {name: present(self.job(name), today) for name in DEMO_KEYS}
            stored = self.job(key)
            job = samples[key] if key in DEMO_KEYS else present(stored, today)
            if job and job.get("print"):
                job["print"] = with_filament_usage(job["print"], self.files(key, stored))
            if stored and stored["status"] != "unreadable" and key not in {"sample", "character"}:
                job["credits"] = self.credits.report(stored)
                job["editions"] = [
                    {"index": index, "title": version.get("title", "今日小物"),
                     "files": [name for name in ("model.stl", "print.gcode.3mf", version.get("lux3d_concept_filename"),
                                                 version.get("finished_photo"))
                               if name and self.archived_file(key, version, name)]}
                    for index, version in enumerate(stored.get("prior_versions", []))
                    if version.get("status")
                ]
            history = sorted(self.store.collection, reverse=True)
            return {
                "today": today, "date": key, "job": job, "history": history,
                "collection": [self.store.collection[day] for day in history],
                "personal_history": history_status,
                "sample": samples["sample"], "character": samples["character"],
                "aholo_character": samples["aholo-character"], "settings": self.settings, "settings_error": self.settings_error,
                "connection": connection_state(), "feishu_bound": self.personal_chat and feishu_print.configured(),
                "feishu_webhook": feishu_webhook.configured(self.data),
                "busy": self.working_key, "checking_printer": self.checking_printer,
                "organizing": self.organizing_key == key, "organize_error": self.organize_errors.get(key),
            }

    def archived_file(self, key, version, name):
        try:
            return self.artifact(key, version, name).is_file()
        except Problem:
            return False

    def organize(self, key):
        with self.guard:
            if key != now().date().isoformat():
                raise Problem("即时整理只读取今天的记录。")
            if self.organizing_key == key:
                return
            if self.organizing_key:
                raise Problem("正在整理另一份记录，请稍后再试。")
            if self.job(key):
                raise Problem("今天已有记录，可直接在画布编辑。")
            self.organizing_key = key
            self.organize_errors.clear()
            self.organize_worker = Thread(target=self.finish_organizing, args=(key,), daemon=True)
            self.organize_worker.start()

    def finish_organizing(self, key):
        try:
            record, sources = draft_for_day(key, self.data)
            with self.guard:
                if not self.job(key):
                    self.submit(record, sources=sources)
        except Problem as error:
            with self.guard:
                if not self.job(key):
                    self.organize_errors[key] = str(error)
        except (OSError, ValueError, sqlite3.Error):
            with self.guard:
                if not self.job(key):
                    self.organize_errors[key] = "本机记录暂时无法整理。请重试或手写经历。"
        finally:
            with self.guard:
                self.organizing_key = None

    def edit(self, key, open_editor, edit_token=None):
        checked_date(key)
        with self.guard:
            job = self.job(key)
            if not job or job["status"] in ACTIVE | {"unreadable"} or self.working_key == key:
                raise Problem("请等当前制作或发送结束，再解锁这条记录。")
            if open_editor:
                if job["status"] == "recorded" or job.get("edit_token"):
                    return
                job["edit_token"] = secrets.token_hex(8)
                if self.bed_check_key == key:
                    self.bed_check_key = None
            else:
                if not job.get("edit_token") or edit_token != job["edit_token"]:
                    raise Problem("这条记录的编辑状态已经变化，请重新打开。")
                job.pop("edit_token")
            self.save(key, job)

    def submit(self, data, *, handoff=False, manual=False, sources=None):
        key = checked_date(data.get("date", now().date().isoformat()))
        data = dict(data)
        annotations = {}
        if "inspiration_refs" in data:
            annotations["inspiration"] = inspirations(data.pop("inspiration_refs"), self.data)
        if "design_reason" in data:
            annotations["design_reason"] = checked_text(data.pop("design_reason"), "造型缘由", 500)
        edit_token = data.pop("edit_token", None)
        prompt = (checked_text(data.pop("design_prompt"), "造型提示词", 2000)
                  if "design_prompt" in data else None)
        with self.guard:
            previous = self.job(key)
            if handoff and previous and (previous.get("manual_record") or previous.get("edit_token")):
                return {"date": key, "kept": True}
            editing = previous and previous.get("edit_token")
            if (editing or edit_token) and (not editing or edit_token != editing):
                raise Problem("这条记录的编辑状态已经变化，请重新打开。")
            earlier = sorted((day for day in self.store.collection if day < key), reverse=True)
            recent_titles = [self.store.collection[day]["title"] for day in earlier[:2]]
            base = previous
            if editing:
                data.setdefault("title", previous.get("title", ""))
                data.setdefault("idea", previous.get("idea", ""))
                base = previous | {"status": "recorded"}
            record = record_from_input(data, base, recent_titles)
            shape_changed = previous and record.get("idea") != previous.get("idea")
            prior_prompt = (previous or {}).get("design_prompt")
            effective_prompt = prior_prompt if previous and not shape_changed else None
            if prompt is not None:
                effective_prompt = prompt or concept_prompt(record["idea"])
            previous_prompt = prior_prompt or concept_prompt((previous or {}).get("idea") or record["idea"])
            prompt_changed = prompt is not None and effective_prompt != previous_prompt
            if not editing and previous and previous["status"] != "recorded" and prompt_changed:
                raise Problem("请先解锁，再修改造型提示词。")
            if shape_changed:
                record.pop("inspiration", None)
                record.pop("design_reason", None)
            if shape_changed or prompt_changed:
                if not editing:
                    clear_approval(record)
            if editing:
                record = dict(record)
                for field, flag in (("title", "custom_title"), ("idea", "custom_design")):
                    if record[field] == previous.get(field) and flag not in previous:
                        record.pop(flag, None)
                    elif record[field] == previous.get(field):
                        record[flag] = previous[flag]
                record.pop("edit_token")
                if shape_changed or prompt_changed:
                    snapshot = {k: v for k, v in previous.items() if k not in {"prior_versions", "edit_token"}}
                    keep = {"summary", "mood", "title", "idea", "custom_title", "custom_design",
                            "design_reason", "inspiration", "daily_sources"}
                    record = {k: v for k, v in record.items() if k in keep}
                    record.update(status="recorded", revision=secrets.token_hex(8), ready=False, source="external",
                                  needs_credit_consent=True, prior_versions=[*previous.get("prior_versions", []), snapshot])
                else:
                    record["status"] = previous["status"]
            if any(record.get(k) != v for k, v in annotations.items()):
                if record["status"] != "recorded" and not editing:
                    raise Problem("这一天已开始制作，历史引用与造型缘由已锁定。")
                record = record | annotations
            if shape_changed or prompt_changed or not previous:
                record = dict(record)
                if effective_prompt:
                    record["design_prompt"] = effective_prompt
                else:
                    record.pop("design_prompt", None)
            outbound = record["idea"] + "\n" + (record.get("design_prompt") or "")
            for entry in [*(previous or {}).get("inspiration", []), *record.get("inspiration", [])]:
                if entry["ref"] in outbound or (len(entry["quote"]) >= 8 and entry["quote"] in outbound):
                    raise Problem("请把原话留在经历里，造型栏只写送给 Aholo 的外形和动作。")
            if manual or editing or sources is not None:
                record = record | {"manual_record": True}
            if sources is not None:
                record["daily_sources"] = sources
            if record != previous:
                self.save(key, record)
                self.organize_errors.pop(key, None)
        return {"date": key}

    def attach_photo(self, key, raw, media_type, expected_revision=None):
        checked_job_key(key)
        def eligible():
            job = self.job(key)
            if not job or not job.get("print") or job["status"] not in {"prepared", "submitted", "print_unknown", "finished"}:
                raise Problem("请给已切片的作品添加实物照片。发送中的任务请稍候。")
            return job
        with self.guard:
            original = eligible()
            if expected_revision is not None and expected_revision != (original.get("revision") or "original"):
                raise Problem("作品版本已改变，请为这一版重新选择照片。")
            directory = self.files(key, original)
        with TemporaryDirectory(prefix=".photo-", dir=directory) as temporary:
            photo = prepare_photo(temporary, raw, media_type)
            with self.guard:
                job = eligible()
                if job.get("revision") != original.get("revision"):
                    raise Problem("作品版本已改变，请为这一版重新选择照片。")
                photo.replace(directory / "finished.jpg")
                job.update(status="finished", ready=False, finished_photo="finished.jpg",
                           finished_at=now().isoformat(timespec="seconds"))
                self.save(key, job)

    def update_settings(self, data):
        # Old clients omit this field. Keep an existing per-day credit gate
        # when they edit the schedule of an enabled automatic workflow.
        if "prepare_after_ready" not in data:
            data = data | {"prepare_after_ready": bool(data.get("auto_print") and self.settings["prepare_after_ready"])}
        validate_settings(data)
        if data["auto_prepare"] and not connection_state()["aholo"]:
            raise Problem("请先连接 Aholo，再启用每日自动准备。")
        if data["auto_print"] and not connection_state()["printer"]:
            raise Problem("请先连接打印机，再启用自动发送。")
        with self.guard:
            save_json(self.data / "settings.json", data)
            self.settings, self.settings_error = data, None

    def update_connections(self, data):
        with self.guard:
            if self.working_key or self.checking_printer:
                raise Problem("请等当前任务或连接测试结束后再修改连接。")
            update_credentials(self.data, data)

    def test_printer(self, source):
        checked_source(source)
        with self.guard:
            if self.checking_printer or self.working_key:
                raise Problem("当前任务或连接测试还在进行。")
            if not connection_state()["printer"]:
                raise Problem("请先保存打印机的局域网信息。")
            self.checking_printer = True
        try:
            return printer_status(source=source)
        except PrinterError as exc:
            raise Problem(str(exc)) from None
        finally:
            with self.guard:
                self.checking_printer = False

    def clear_other_ready_jobs(self, key, today):
        # All these jobs share one physical bed. A single clearance is for one job.
        for other in (DEMO_KEYS | {today}) - {key}:
            job = self.job(other)
            if job and job.get("ready"):
                job.update(ready=False, ready_date=None, ready_bed=None)
                self.save(other, job)

    def clearance_job(self, key, ready, prepare_ok):
        job = self.job(key)
        if not job or job.get("edit_token") or job["status"] not in {"recorded", "generating", "slicing", "prepared", "failed"}:
            raise Problem("当前任务无法更改打印机就绪状态。")
        if self.working_key and self.job(self.working_key)["status"] == "dispatching":
            raise Problem("正在发送打印任务，请在清理平台后重新标记就绪。")
        if ready and (self.settings["prepare_after_ready"] or job.get("needs_credit_consent")) and job["status"] == "recorded" and prepare_ok is not True:
            raise Problem("请在制作画布确认当天这件作品可使用 Aholo 积分并在清盘后打印。")
        return job

    def mark_ready(self, key, ready, source, prepare_ok=False):
        if source is not None:
            checked_source(source)
        today = now().date().isoformat()
        if key not in DEMO_KEYS | {today} or type(ready) is not bool:
            raise Problem("打印机就绪只对当天有效。")
        with self.guard:
            job = self.clearance_job(key, ready, prepare_ok)
            if not ready:
                if self.bed_check_key == key:
                    self.bed_check_key = None
                if source is not None and not approved(job, today):
                    job["source"] = source
                job.update(ready=False, ready_date=None, ready_device=None, ready_bed=None, ready_for_generation=False)
                self.save(key, job)
                return
            if self.checking_printer:
                raise Problem("正在核对 P2S，请稍后确认清盘。")
            if not connection_state()["printer"]:
                raise Problem("请先保存打印机的局域网信息。")
            if job.get("ready"):
                job.update(ready=False, ready_date=None, ready_bed=None, ready_for_generation=False)
                self.save(key, job)
            self.clear_other_ready_jobs(key, today)
            device = printer_identity()
            self.bed_check_key = key
            self.checking_printer = True
        try:
            signature = read_idle_bed()
            with self.guard:
                latest = self.clearance_job(key, ready, prepare_ok)
                if (self.bed_check_key != key or today != now().date().isoformat() or device != printer_identity()
                        or latest.get("idea") != job.get("idea") or latest.get("artifact_version") != job.get("artifact_version")):
                    raise Problem("作品或清盘状态已改变，请检查后重新确认。")
                if source is not None and not approved(latest, today):
                    latest["source"] = source
                latest.update(ready=True, ready_date=today, ready_device=device, ready_bed=signature,
                              ready_for_generation=prepare_ok is True)
                self.save(key, latest)
        except PrinterError as exc:
            raise Problem(str(exc)) from None
        finally:
            with self.guard:
                self.checking_printer = False
                self.bed_check_key = None

    def run(self, key, action):
        checked_job_key(key)
        with self.guard:
            if self.working_key is not None:
                raise Problem("正在处理一件摆件，完成后可继续。")
            job = self.job(key)
            if job and job.get("edit_token"):
                raise Problem("请先保存或退出编辑，再继续制作。")
            if action == "sample" and key == "sample":
                if job and "print" in job:
                    return
                if job and job["status"] == "unreadable":
                    raise Problem(job["error"])
                job = {"status": "slicing", "title": TITLE, "idea": IDEA, "summary": SUMMARY, "mood": "平静"}
            elif action == "generate" and key not in DEMO_KEYS:
                if not job or job["status"] not in {"recorded", "failed"}:
                    raise Problem("请先保存当天记录。")
                if not connection_state()["aholo"]:
                    raise Problem("请先在本机配置 Aholo API Key。")
                if not any(job.get(k) for k in ("lux3d_concept_task_id", "lux3d_task_id", "lux3d_concept_create_pending", "lux3d_create_pending")):
                    job.setdefault("design_prompt", concept_prompt(job["idea"]))
                self.files(key, job).mkdir(exist_ok=True, parents=True)
                job["status"] = "generating"
            elif action == "print":
                self.begin_dispatch(key, job)
            else:
                raise Problem("找不到操作。")
            job.pop("error", None)
            self.save(key, job)
            self.working_key = key
            self.worker = Thread(target=self.work, args=(key, job, action), daemon=True)
            self.worker.start()

    def begin_dispatch(self, key, job):
        today = now().date().isoformat()
        if key not in DEMO_KEYS | {today} or not job or job["status"] != "prepared":
            raise Problem("只能发送已完成切片的当天摆件或样品。")
        if self.checking_printer:
            raise Problem("正在读取打印机状态，完成后可发送。")
        if not connection_state()["printer"]:
            raise Problem("请先在本机配置打印机连接。")
        if not bed_is_ready_to_print(job, today):
            raise Problem("请先清空平台，为本件作品重新确认清盘。")
        if not approved(job, today):
            raise Problem("请先打开本件的飞书通知，在工作台选好 PLA 颜色并确认。")
        result = job.get("print") or {}
        seconds = result.get("estimated_seconds")
        if type(seconds) not in (int, float) or not 0 < seconds <= MAX_MINUTES * 60:
            raise Problem("切片估时无效或超过 3 小时。")
        if result.get("artifact") != "print.gcode.3mf":
            raise Problem("缺少可发送的 P2S 切片文件。")
        self.clear_other_ready_jobs(key, today)
        job.update(status="dispatching", ready=False)

    def prepare(self, job, directory, action, checkpoint):
        if action == "sample":
            source = make_sample(directory / "sample.stl")
        else:
            idea = job["idea"]
            source = generate_model(
                "设计一件单色 FDM 桌面摆件，造型完整，结构连成一体，平底，最长边60毫米。造型：" + idea,
                directory, job=job, checkpoint=checkpoint, concept_prompt=job.get("design_prompt") or concept_prompt(idea),
            )
        job["status"] = "slicing"
        checkpoint()
        job["print"] = prepare_print(source, directory, model="P2S", max_minutes=MAX_MINUTES)
        job["status"] = "prepared"

    def work(self, key, job, action):
        directory = self.files(key, job)

        def checkpoint():
            # The user can mark the bed ready while a model is still generating.
            with self.guard:
                if action != "print":
                    latest = self.job(key) or {}
                    for field in ("ready", "source", "ready_date", "ready_device", "ready_bed", "ready_for_generation"):
                        if field in latest:
                            job[field] = latest[field]
                self.save(key, job)

        try:
            if action == "print":
                review = job["color_review"]
                ticket = send_print(directory / "print.gcode.3mf", model="P2S", source=job["source"],
                                    expected_rgba=review["selected"]["rgba"], expected_slice=review["slice_sha256"],
                                    expected_bed=job["ready_bed"])
                job.update(status="submitted", submitted_at=now().isoformat(timespec="seconds"))
                if isinstance(ticket, dict):
                    job.update(device_ticket=ticket, sent_device=printer_identity())
                    with self.guard:
                        self.tracked_key, self.next_observation = key, 0
            else:
                self.prepare(job, directory, action, checkpoint)
        except PrintStatusUnknown as exc:
            job.update(status="print_unknown", error=str(exc))
        except ColorChanged as exc:
            job.pop("color_review", None)
            job.update(status="prepared", error=str(exc))
        except PrinterError as exc:
            job.update(status="prepared", error=str(exc))
        except (Lux3DError, PreparationError, Problem) as exc:
            job.update(status="failed", error=str(exc))
        except Exception:
            if action == "print":
                job.update(status="print_unknown", error="发送结果不明。请在打印机屏幕确认任务。")
            else:
                job.update(status="failed", error="准备失败。请检查本机 Blender、Bambu Studio 和应用配置。")
        finally:
            with self.guard:
                try:
                    if action == "print":
                        job.pop("ready_bed", None)
                    checkpoint()
                finally:
                    self.working_key = None

    def schedule(self):
        while not self.stop.wait(12):
            self.run_due(now())
            self.observe_latest()
            self.colors.tick()

    def observe_latest(self):
        # New dispatches supersede old ones on this single printer. Never infer
        # that a printed part exists from an idle printer or a different task.
        from printer import observe_print, observe_studio_print
        with self.guard:
            key = self.tracked_key
            if not key or self.working_key or self.checking_printer or monotonic() < self.next_observation:
                return
            job = self.job(key) or {}
            ticket = job.get("device_ticket")
            studio = studio_observation(job)
            device = printer_identity()
            try:
                age = now() - datetime.fromisoformat(job.get("submitted_at", ""))
            except (TypeError, ValueError):
                age = timedelta.max
            if (not device or job.get("sent_device") != device or not (ticket or studio) or job.get("status") != "submitted"
                    or job.get("device_progress", {}).get("state") in {"FINISH", "FAILED"} or age > timedelta(days=1)):
                self.tracked_key = None
                return
            self.next_observation = monotonic() + 60
        try:
            progress = observe_print(ticket) if ticket else observe_studio_print(*studio)
        except PrinterError:
            return
        if not progress or progress["state"] == "IDLE":
            return
        with self.guard:
            latest = self.job(key) or {}
            if (key != self.tracked_key or latest.get("status") != "submitted" or latest.get("device_ticket") != ticket
                    or studio_observation(latest) != studio or latest.get("sent_device") != device or device != printer_identity()):
                return
            previous = latest.get("device_progress", {})
            if previous.get("state") != progress["state"] or previous.get("percent") != progress.get("percent"):
                latest["device_progress"] = progress | {"checked_at": now().isoformat(timespec="seconds")}
                self.save(key, latest)

    def run_due(self, timestamp):
        with self.guard:
            if self.working_key or not self.settings["auto_prepare"] or timestamp.strftime("%H:%M") < self.settings["at"]:
                return
            key = timestamp.date().isoformat()
            job = self.job(key)
            if not job or job.get("edit_token"):
                return
            try:
                if job["status"] == "recorded":
                    if (self.settings["prepare_after_ready"] or job.get("needs_credit_consent")) and not (bed_is_ready(job, key) and job.get("ready_for_generation")):
                        return
                    self.run(key, "generate")
                elif self.settings["auto_print"] and job["status"] == "prepared" and bed_is_ready_to_print(job, key) and approved(job, key):
                    self.run(key, "print")
            except Problem:
                # A changed connection or expired clearance will be rechecked next tick.
                return
