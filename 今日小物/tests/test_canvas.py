"""Daily source attribution, authentic print evidence and scheduled credit consent."""
from datetime import date, datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from daily_inputs import APPLE_EPOCH, TZ, collect
from local_store import Problem, now, printer_identity
from workshop import App


class CanvasTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data = Path(temp.name)
        self.app = App(self.data)
        self.enterContext(patch("workshop.read_idle_bed", return_value="c"*64))
        self.day = now().date().isoformat()

    def test_source_ref_resolves_to_private_snapshot_only(self):
        ref = "hist_" + "a" * 24
        item = {"excerpt": "这是一条虚构的测试原话", "ref": ref, "date": "2025-03-04",
                "source_type": "wechat_self_text", "redacted": False}
        payload = {"summary": "仅本机查看的经历", "idea": "抱着笔记本的小狐", "design_reason": "把倾听做成侧耳动作",
                   "inspiration_refs": [ref]}
        with patch("history_context.lookup", return_value=item):
            self.app.submit(payload)
            with self.assertRaises(Problem):
                self.app.submit(payload | {"idea": item["excerpt"]})
        job = self.app.state("today")["job"]
        self.assertEqual(job["inspiration"][0]["quote"], item["excerpt"])
        self.assertIn("2025-03-04", job["inspiration"][0]["source"])
        self.assertNotIn(item["excerpt"], job["design_prompt"])
        self.assertNotIn(payload["summary"], job["design_prompt"])
        self.assertEqual(job["prompt_status"], "planned")
        # Never reconstruct a previously unsaved prompt for legacy paid jobs.
        self.app.save(self.day, {"status": "prepared", "idea": "老作品", "lux3d_task_id": 42})
        self.assertEqual(self.app.state("today")["job"]["prompt_status"], "archived")
        self.assertNotIn("design_prompt", self.app.state("today")["job"])

    def test_recorded_prompt_equals_the_generated_prompt(self):
        self.app.submit({"summary": "本地事实", "idea": "合上本子的猫头鹰"})
        with patch.dict("os.environ", {"LUX3D_API_KEY": "fake"}):
            def generate(prompt, folder, *, job, checkpoint, concept_prompt):
                self.assertEqual(self.app.job(self.day)["design_prompt"], concept_prompt)
                job["lux3d_concept_task_id"] = 5
                checkpoint()
                return folder / "model.glb"
            with patch("workshop.generate_model", side_effect=generate) as g, patch("workshop.prepare_print", return_value={"model": "P2S"}):
                self.app.run(self.day, "generate")
                self.app.worker.join(3)
                g.assert_called_once()
        self.assertEqual(self.app.state("today")["job"]["prompt_status"], "sent")

    def test_daily_credit_gate_and_old_settings_client(self):
        with patch.dict("os.environ", {"LUX3D_API_KEY": "offline", "BAMBU_SERIAL": "offline", "BAMBU_IP": "test", "BAMBU_ACCESS_CODE":"test"}):
            self.app.update_settings({"at":"00:00", "auto_prepare":True, "auto_print":True, "prepare_after_ready":True})
            self.app.update_settings({"at":"00:01", "auto_prepare":True, "auto_print":True})
            self.assertTrue(self.app.settings["prepare_after_ready"])
            self.app.submit({"summary":"测试", "idea":"测试造型"})
            with patch.object(self.app, "run") as run:
                stamp = now().replace(hour=21)
                self.app.run_due(stamp)
                with self.assertRaises(Problem):
                    self.app.mark_ready(self.day, True, "ams-a2")
                run.assert_not_called()
                self.app.mark_ready(self.day, True, "ams-a2", prepare_ok=True)
                self.app.run_due(stamp)
                run.assert_called_once_with(self.day, "generate")
                self.app.submit({"summary":"换个造型", "idea":"新造型"})
                self.assertFalse(self.app.state("today")["job"]["ready"])
                self.app.run_due(stamp)
                self.assertEqual(run.call_count, 1)

    def test_finished_photo_is_real_input_and_ends_auto_dispatch(self):
        self.app.save(self.day, {"status":"submitted", "print":{"model":"P2S"}, "ready":False})
        with self.assertRaises(Problem):
            self.app.attach_photo(self.day, b"not an image", "image/jpeg")
        self.assertNotIn("finished_photo", self.app.job(self.day))
        # Local image fixture represents an uploaded photo only inside this test.
        image = (Path(__file__).resolve().parents[1] / "web" / "lighthouse.jpg").read_bytes()
        self.app.attach_photo(self.day, image, "image/jpeg")
        job = self.app.state("today")["job"]
        self.assertEqual(job["status"], "finished")
        self.assertTrue((self.app.directory(self.day) / job["finished_photo"]).is_file())
        self.assertTrue(job["finished_at"])
        with self.assertRaises(Problem):
            self.app.run(self.day, "print")

    def test_device_observation_survives_restart_without_inventing_a_photo(self):
        ticket = {"task_id":"12345", "name":"mood-123456789abc"}
        with patch.dict("os.environ", {"BAMBU_SERIAL":"local-test", "BAMBU_IP":"test", "BAMBU_ACCESS_CODE":"test"}):
            self.app.save(self.day, {"status":"prepared", "print":{"artifact":"print.gcode.3mf", "estimated_seconds":100}})
            self.app.mark_ready(self.day, True, "external")
            job = self.app.job(self.day)
            job["color_review"] = {"day": self.day, "device": job["ready_device"], "status": "confirmed",
                                   "selected": {"source": "external", "rgba": "FFFFFFFF"},
                                   "reply_id": "offline-reply", "slice_sha256": "a"*64}
            self.app.save(self.day, job)
            with patch("workshop.send_print", return_value=ticket):
                self.app.run(self.day, "print")
                self.app.worker.join(3)
            restarted = App(self.data)
            with patch("printer.observe_print", side_effect=[None, {"state":"FINISH", "percent":100}]) as observe:
                restarted.observe_latest()
                self.assertNotIn("device_progress", restarted.job(self.day))
                restarted.next_observation = 0
                restarted.observe_latest()
                restarted.next_observation = 0
                restarted.observe_latest()
                self.assertEqual(observe.call_count, 2)
            job = restarted.state("today")["job"]
            self.assertEqual(job["device_progress"]["state"], "FINISH")
            self.assertEqual(job["status"], "submitted")
            self.assertNotIn("device_ticket", job)
            self.assertNotIn("finished_photo", job)

    def test_studio_receipt_survives_midnight_restart_and_cannot_bind_other_printer(self):
        name, version = "Avatar-1234abcd", "1234abcdef123456"
        submitted = now().replace(hour=23, minute=58)
        from datetime import timedelta
        after_midnight = submitted + timedelta(minutes=10)
        with patch.dict("os.environ", {"BAMBU_SERIAL": "fixture-only"}):
            job = {"title":"sample", "status":"submitted", "ready":False, "submitted_via":"Bambu Studio",
                   "studio_task_name":name, "artifact_version":version, "sent_device":printer_identity(),
                   "submitted_at":submitted.isoformat(timespec="seconds")}
            self.app.save(self.day, job)
            with patch("workshop.now", return_value=after_midnight), patch("printer.observe_studio_print", return_value={"state":"RUNNING","percent":37}) as observe:
                restarted=App(self.data)
                self.assertEqual(restarted.tracked_key, self.day)
                restarted.observe_latest()
                observe.assert_called_once_with(name, version)
                public = restarted.state(self.day)["job"]
                self.assertEqual(public["device_progress"]["percent"],37)
                self.assertNotIn("studio_task_name",public)
                self.assertNotIn("device_ticket",restarted.job(self.day))
                with patch.dict("os.environ", {"BAMBU_SERIAL":"different"}):
                    restarted.next_observation=0
                    restarted.observe_latest()
                observe.assert_called_once()
            self.app.save(self.day, job | {"submitted_via":"unconfirmed"})
            self.assertIsNone(App(self.data).tracked_key)

    def test_daily_inputs_uses_human_completion_and_skips_self(self):
        day = date(2026,4,1)
        start = int(datetime(2026,4,1,12,tzinfo=TZ).timestamp())
        apple = start - APPLE_EPOCH
        island = self.data / "workspace.json"
        island.write_text(json.dumps({
            "trash":[{"title":"丢弃内容"}],
            "items":[{"id":"a", "state":"todo","created":apple,"title":"未完成待办"},
                     {"id":"b", "state":"done","completedAt":apple,"title":"完成的待办"}],
            "todoHistory":[{"taskID":"b","completedAt":apple,"title":"完成的待办"}],
        }))
        sessions = self.data / "sessions"
        sessions.mkdir()
        session = sessions / "work.jsonl"
        session.write_text('\n'.join(json.dumps({"type":"event_msg","timestamp":"2026-04-01T04:00:00Z","payload":p}) for p in [
            {"type":"message","text":"不读取对话"}, {"type":"task_complete","last_agent_message":"测试完成并给出结果"}]))
        db = sqlite3.connect(self.data / "state_5.sqlite")
        db.execute("CREATE TABLE threads(id,rollout_path,title,created_at,updated_at,source,thread_source)")
        for uid in ("real","daily-bot"):
            db.execute("INSERT INTO threads VALUES(?,?,?,?,?,?,?)",(uid,str(session),"任务",start,start,"vscode","user"))
        db.commit()
        db.close()
        r = collect(day, island, self.data, exclude_thread="daily-bot")
        self.assertEqual(len(r["todos"]),2)
        self.assertEqual(r["agent_work"],[{"topic":"任务","agent_reports":["测试完成并给出结果"], "harness": "Codex",
                                           "project": "日常对话", "by": "你", "prompts": []}])
        self.assertEqual(r["unavailable"], [])
