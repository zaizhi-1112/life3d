"""Offline integration tests for the Agent handoff, worker and single printer bed."""
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import Handler, ROOT
from local_store import Problem, now, printer_identity
from printer import PrinterError, PrintStatusUnknown
from workshop import App


class WorkshopTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.app = App(self.directory)
        self.day = now().date().isoformat()
        self.bed = self.enterContext(patch("workshop.read_idle_bed", return_value="c"*64))
        self.env = patch.dict("os.environ", {
            "LUX3D_API_KEY": "offline", "BAMBU_IP": "test", "BAMBU_SERIAL": "test", "BAMBU_ACCESS_CODE": "test",
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.slice = {"artifact": "print.gcode.3mf", "estimated_seconds": 5990}

    def prepared(self, key):
        self.app.save(key, {"status": "prepared", "ready": False, "print": self.slice})

    def confirmed_color(self, key, source):
        job = self.app.job(key)
        job.update(source=source, color_review={
            "day": self.day, "device": printer_identity(), "status": "confirmed",
            "reply_id": "offline-reply", "slice_sha256": "a"*64,
            "selected": {"source": source, "rgba": "FFFFFFFF"},
        })
        self.app.save(key, job)

    def test_agent_retry_survives_lock_and_restart(self):
        request = {"summary": "测试摘要", "date": self.day, "mood": "平静"}
        self.app.submit(request)
        first = self.app.job(self.day)
        self.app.save(self.day, first | {"status": "slicing", "lux3d_task_id": 23})
        restarted = App(self.directory)
        recovered = restarted.job(self.day)
        self.assertEqual(recovered["status"], "failed")
        restarted.submit(request)
        self.assertEqual(restarted.job(self.day), recovered)
        with self.assertRaises(Problem):
            restarted.submit(request | {"idea": "改成另一个角色"})

    def test_state_indexes_only_labels_and_keeps_corrupt_original(self):
        for day in ("2024-01-01", "2024-01-02"):
            self.app.submit({"date": day, "summary": "不进收藏列表", "idea": "小熊"})
        broken = self.app.directory("2024-01-01") / "job.json"
        broken.write_bytes(b"{")
        self.app.save("character", {"status": "prepared", "lux3d_task_id": 33})
        app = App(self.directory)
        with patch.object(app.store, "read", wraps=app.store.read) as read:
            view = app.state("today")
            self.assertFalse(any(call.args[0] in view["history"] for call in read.call_args_list))
        self.assertEqual(view["date"], self.day)
        self.assertEqual(view["history"], ["2024-01-02", "2024-01-01"])
        self.assertTrue(all("summary" not in item for item in view["collection"]))
        self.assertNotIn("lux3d_task_id", view["character"])
        self.assertEqual(app.state("2024-01-01")["job"]["status"], "unreadable")
        with self.assertRaises(Problem):
            app.submit({"date": "2024-01-01", "summary": "新内容"})
        self.assertEqual(broken.read_bytes(), b"{")

    def test_generation_keeps_mood_private_and_merges_bed_updates(self):
        self.app.submit({"summary": "私密记录", "mood": "疲惫", "idea": "小熊抱杯"})
        def model(prompt, directory, *, job, checkpoint, concept_prompt):
            self.assertNotIn("私密记录", prompt + concept_prompt)
            self.assertIn("小熊抱杯", concept_prompt)
            job["lux3d_concept_task_id"] = 24
            checkpoint()
            self.app.mark_ready(self.day, True, "ams-a2")
            return directory / "model.glb"
        with patch("workshop.generate_model", side_effect=model) as generate, patch("workshop.prepare_print", return_value=self.slice):
            self.app.run(self.day, "generate")
            self.app.worker.join(3)
            generate.assert_called_once()
        job = self.app.job(self.day)
        self.assertEqual((job["ready"], job["source"], job["status"]), (True, "ams-a2", "prepared"))
        self.assertEqual(job["lux3d_concept_task_id"], 24)

    def test_only_one_job_can_use_a_cleared_bed(self):
        self.prepared(self.day)
        self.prepared("aholo-character")
        self.app.mark_ready(self.day, True, "external")
        self.app.mark_ready("aholo-character", True, "ams-a2")
        self.assertFalse(self.app.job(self.day)["ready"])
        self.confirmed_color("aholo-character", "ams-a2")
        with patch("workshop.send_print") as send:
            self.app.run("aholo-character", "print")
            self.app.worker.join(3)
            send.assert_called_once_with(self.app.directory("aholo-character") / "print.gcode.3mf", model="P2S",
                                         source="ams-a2", expected_rgba="FFFFFFFF", expected_slice="a"*64,
                                         expected_bed="c"*64)
            with self.assertRaises(Problem):
                self.app.run(self.day, "print")
        self.assertEqual(self.app.job("aholo-character")["status"], "submitted")
        self.assertFalse(self.app.job("aholo-character")["ready"])
        self.assertNotIn("ready_bed", self.app.job("aholo-character"))

    def test_clearance_is_bound_to_device_after_restart(self):
        self.prepared("character")
        self.app.mark_ready("character", True, "ams-a2")
        original = self.app.job("character")
        self.assertNotIn("ready_device", self.app.state("character")["job"])
        self.assertNotIn("ready_bed", self.app.state("character")["job"])
        with patch.dict("os.environ", {"BAMBU_SERIAL": "other-device"}):
            restarted = App(self.directory)
            self.assertFalse(restarted.state("character")["job"]["ready"])
            with self.assertRaises(Problem):
                restarted.run("character", "print")
        # Old unbound and previous-day confirmations both expire.
        for changes in ({"ready_device": None}, {"ready_date": "2024-01-01"}, {"ready_bed": None}):
            self.app.save("character", original | changes)
            self.assertFalse(self.app.state("character")["job"]["ready"])
            with self.assertRaises(Problem):
                self.app.run("character", "print")

    def test_cancel_or_revise_during_clearance_read(self):
        self.app.submit({"summary": "待制作", "idea": "小猫"})
        for action in ("cancel", "revise"):
            started, finish = Event(), Event()
            def probe():
                started.set()
                finish.wait(3)
                return "a"*64
            self.bed.side_effect = probe
            errors = []
            def mark():
                try:
                    self.app.mark_ready(self.day, True, None)
                except Problem as exc:
                    errors.append(str(exc))
            thread = Thread(target=mark)
            thread.start()
            try:
                self.assertTrue(started.wait(1))
                if action == "cancel":
                    self.app.mark_ready(self.day, False, None)
                else:
                    self.app.submit({"summary": "已变更", "idea": "小狗"})
            finally:
                finish.set()
                thread.join(3)
            self.assertTrue(errors)
            self.assertFalse(self.app.job(self.day)["ready"])

    def test_legacy_clearance_still_allows_paid_generation_only(self):
        self.app.submit({"summary": "历史版本今日批准制作"})
        job = self.app.job(self.day)
        job.update(ready=True, ready_device=printer_identity(), ready_date=self.day, ready_for_generation=True)
        self.app.save(self.day, job)
        self.app.settings.update(auto_prepare=True, auto_print=True, prepare_after_ready=True, at="00:00")
        with patch.object(self.app, "run") as run:
            self.app.run_due(now())
            run.assert_called_once_with(self.day, "generate")
        job.update(status="prepared", print=self.slice)
        self.app.save(self.day, job)
        self.confirmed_color(self.day, "external")
        with self.assertRaisesRegex(Problem, "重新确认清盘"):
            self.app.run(self.day, "print")

    def test_automatic_and_custom_designs_roundtrip(self):
        record = {"date": self.day, "summary": "当天记录", "mood": "有劲"}
        self.app.submit(record | {"title": "我的标题"})
        auto = self.app.state("today")["job"]
        self.assertTrue(auto["custom_title"])
        self.assertFalse(auto["custom_design"])
        self.app.submit(record | {"summary": "补充", "title": "我的标题", "idea": ""})
        self.assertEqual(self.app.job(self.day)["idea"], auto["idea"])
        self.app.submit(record | {"idea": "抱杯的海豹"})
        self.app.submit(record)
        specified = self.app.state("today")["job"]
        self.assertTrue(specified["custom_design"])
        self.assertEqual(specified["idea"], "抱杯的海豹")
        self.app.submit(record | {"summary": "Agent 补充了当天的记录", "mood": "疲惫"})
        updated = self.app.job(self.day)
        self.assertEqual((updated["title"], updated["idea"]), ("我的标题", "抱杯的海豹"))
        self.app.submit(record | {"idea": "", "title": ""})
        self.assertFalse(self.app.state("today")["job"]["custom_design"])

    def test_unreadable_daily_schedule_is_paused_without_overwriting(self):
        path = self.directory / "settings.json"
        for malformed in (b"{", b'{"auto_prepare":"false"}'):
            path.write_bytes(malformed)
            restarted = App(self.directory)
            self.assertFalse(restarted.settings["auto_prepare"])
            self.assertTrue(restarted.state("today")["settings_error"])
            self.assertEqual(path.read_bytes(), malformed)
            restarted.update_settings({"at": "20:30", "auto_prepare": False, "auto_print": False})
            self.assertIsNone(restarted.state("today")["settings_error"])

    def test_failed_or_ambiguous_dispatch_never_repeats(self):
        for error, status in ((PrinterError("设备忙"), "prepared"), (PrintStatusUnknown("待核对"), "print_unknown")):
            self.prepared(self.day)
            self.confirmed_color(self.day, "external")
            self.app.mark_ready(self.day, True, "external")
            with patch("workshop.send_print", side_effect=error) as send:
                self.app.run(self.day, "print")
                self.app.worker.join(3)
                self.app.settings.update(auto_print=True, auto_prepare=True, at="00:00")
                self.app.run_due(now())
                self.assertEqual(send.call_count, 1)
                self.assertEqual(self.app.job(self.day)["status"], status)
                self.assertFalse(self.app.job(self.day)["ready"])
        self.app.save(self.day, {"status": "dispatching", "ready": True})
        restarted = App(self.directory)
        self.assertEqual(restarted.job(self.day)["status"], "print_unknown")
        self.assertFalse(restarted.job(self.day)["ready"])

    def test_connection_probe_does_not_block_records_or_change_credentials(self):
        started, finish = Event(), Event()
        def probe(*, source):
            started.set()
            finish.wait(3)
            return {"ready": True}
        with patch("workshop.printer_status", side_effect=probe):
            thread = Thread(target=self.app.test_printer, args=("ams-a2",))
            thread.start()
            try:
                self.assertTrue(started.wait(1))
                self.assertTrue(self.app.state("today")["checking_printer"])
                self.app.submit({"summary": "连接测试期间仍可交接"})
                with self.assertRaises(Problem):
                    self.app.update_connections({"LUX3D_API_KEY": "different"})
                with self.assertRaises(Problem):
                    self.app.test_printer("ams-a2")
            finally:
                finish.set()
                thread.join(2)
        self.assertFalse(self.app.state("today")["checking_printer"])

    def test_scheduler_respects_time_and_current_day(self):
        self.app.submit({"summary": "当天记录"})
        self.app.submit({"date": "2024-01-01", "summary": "历史"})
        timestamp = now().replace(hour=20, minute=30)
        with patch.object(self.app, "run") as run:
            self.app.run_due(timestamp)
            self.app.settings.update(auto_prepare=True, at="20:30")
            self.app.run_due(timestamp.replace(minute=29))
            run.assert_not_called()
            self.app.run_due(timestamp)
            run.assert_called_once_with(self.day, "generate")

    def test_unlock_keeps_model_for_text_edits_and_creates_new_files_for_prompt_edits(self):
        record = {"date": self.day, "summary": "第一份摘要", "title": "小船", "idea": "一艘圆底小船"}
        self.app.submit(record)
        old = self.app.job(self.day)
        old.update(status="finished", print=self.slice, finished_photo="finished.jpg",
                   design_prompt="一艘圆底小船，三角形短帆", lux3d_task_id=33, ready=True)
        self.app.save(self.day, old)
        original = self.app.directory(self.day)
        (original / "model.stl").write_bytes(b"original mesh")
        (original / "finished.jpg").write_bytes(b"original photo")
        self.app.edit(self.day, True)
        token = self.app.job(self.day)["edit_token"]
        with self.assertRaises(Problem):
            self.app.submit(record | {"summary": "缺少编辑凭据"})
        self.assertTrue(self.app.submit(record | {"summary": "定时交接"}, handoff=True)["kept"])
        self.app.submit(record | {"summary": "补记经历", "edit_token": token})
        self.assertEqual(self.app.job(self.day)["status"], "finished")
        self.assertEqual(self.app.download(self.day, "finished.jpg"), original / "finished.jpg")
        self.assertNotIn("prior_versions", self.app.job(self.day))

        self.app.edit(self.day, True)
        token = self.app.job(self.day)["edit_token"]
        prompt = "一艘圆底小船，厚实的长方形短帆"
        self.app.submit(record | {"summary": "补记经历", "design_prompt": prompt, "edit_token": token})
        restarted = App(self.directory)
        draft = restarted.job(self.day)
        self.assertEqual(draft["status"], "recorded")
        self.assertFalse(draft["ready"])
        self.assertNotIn("print", draft)
        self.assertEqual(draft["prior_versions"][0]["lux3d_task_id"], 33)
        self.assertEqual(restarted.download(self.day, "model.stl", 0).read_bytes(), b"original mesh")
        self.assertEqual(restarted.download(self.day, "finished.jpg", revision="original").read_bytes(), b"original photo")
        with self.assertRaises(Problem):
            restarted.download(self.day, "model.stl")
        restarted.settings.update(auto_prepare=True, at="00:00")
        with patch.object(restarted, "run") as run:
            restarted.run_due(now())
            run.assert_not_called()
        def generate(text, folder, *, job, checkpoint, concept_prompt):
            self.assertEqual(concept_prompt, prompt)
            self.assertNotEqual(folder, original)
            self.assertNotIn("lux3d_task_id", job)
            return folder / "model.glb"
        with patch("workshop.generate_model", side_effect=generate) as model, patch("workshop.prepare_print", return_value=self.slice):
            restarted.run(self.day, "generate")
            restarted.worker.join(3)
            model.assert_called_once()
        self.assertEqual(restarted.job(self.day)["status"], "prepared")
        self.assertEqual((original / "model.stl").read_bytes(), b"original mesh")

    def test_edit_pauses_dispatch_and_cancel_keeps_the_same_slice(self):
        self.app.submit({"date": self.day, "summary": "待打印"})
        job = self.app.job(self.day)
        self.app.save(self.day, job | {"status": "prepared", "print": self.slice})
        self.app.mark_ready(self.day, True, "external")
        self.confirmed_color(self.day, "external")
        self.app.edit(self.day, True)
        self.app.settings.update(auto_prepare=True, auto_print=True, at="00:00")
        with patch("workshop.send_print") as dispatch:
            self.app.run_due(now())
            with self.assertRaises(Problem):
                self.app.run(self.day, "print")
            dispatch.assert_not_called()
        token = self.app.job(self.day)["edit_token"]
        self.app.edit(self.day, False, token)
        with patch.object(self.app, "run") as run:
            self.app.run_due(now())
            run.assert_called_once_with(self.day, "print")

    def test_immediate_organizing_is_single_and_preserves_a_manual_save(self):
        started, finish = Event(), Event()
        record = {"date": self.day, "summary": "整理出的经历", "title": "叠石", "idea": "一摞卵石"}
        sources = {"todos": 1, "agent_work": 1, "partial": False, "unavailable": [], "birthday": False}
        def draft(*_):
            started.set()
            finish.wait(3)
            return record, sources

        with patch("workshop.draft_for_day", side_effect=draft) as model:
            self.app.organize(self.day)
            self.assertTrue(started.wait(2))
            self.app.organize(self.day)
            self.app.submit({"date": self.day, "summary": "手写优先"}, manual=True)
            finish.set()
            self.app.organize_worker.join(3)
            model.assert_called_once()
        self.assertEqual(self.app.job(self.day)["summary"], "手写优先")
        self.assertTrue(self.app.submit(record, handoff=True)["kept"])
        with self.assertRaises(Problem):
            self.app.organize(self.day)

        fresh = App(self.directory / "fresh")
        with patch("workshop.draft_for_day", return_value=(record, sources)):
            fresh.organize(self.day)
            fresh.organize_worker.join(3)
        view = fresh.state("today")
        self.assertEqual(view["job"]["daily_sources"], sources)
        self.assertEqual(view["job"]["prompt_status"], "planned")
        self.assertIn(record["idea"], view["job"]["design_prompt"])
        self.assertFalse(view["organizing"])

    def test_http_cli_and_file_download(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        server.app = self.app
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.shutdown)
        origin = f"http://127.0.0.1:{server.server_port}"
        record = {"summary": "🌙" * 4000}
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "app.py"), "--port", str(server.server_port), "--submit", "-"],
            input=json.dumps(record), text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        with urlopen(origin + "/state/today") as response:
            self.assertEqual(json.load(response)["job"]["summary"], record["summary"])
        self.prepared("character")
        model = self.app.directory("character") / "model.stl"
        model.write_bytes(b"mesh" * 80000)
        with urlopen(origin + "/files/character/model.stl") as response:
            self.assertEqual(response.read(), model.read_bytes())
        req = Request(origin + "/record", data=b"{}", headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as rejected:
            urlopen(req)
        self.assertEqual(rejected.exception.code, 403)
        rejected.exception.close()
