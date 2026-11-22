"""A delivered color choice can outlive its workday. A cleared bed cannot."""
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from local_store import Problem, now, printer_identity
from workshop import App


class OvernightPrintTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict("os.environ", {
            "BAMBU_SERIAL": "test", "BAMBU_IP": "localhost", "BAMBU_ACCESS_CODE": "test",
            "LUX3D_API_KEY": "test",
        }, clear=True))
        self.bed = self.enterContext(patch("workshop.read_idle_bed", return_value="c" * 64))
        self.send = self.enterContext(patch("workshop.send_print", return_value={}))
        self.app = App(Path(self.enterContext(TemporaryDirectory())))
        self.app.update_settings(self.app.settings | {"auto_prepare": True, "auto_print": True, "at": "20:30"})
        self.stamp = now().replace(hour=8, minute=0)
        self.today = self.stamp.date().isoformat()
        self.key = (self.stamp.date() - timedelta(days=3)).isoformat()
        self.spool = {"source": "ams-a2", "label": "A2 PLA", "color": "#FFFFFF", "rgba": "FFFFFFFF"}
        self.code = "ABCD1234"
        self.digest = "a" * 64
        self.app.save(self.key, {
            "status": "prepared", "print": {"artifact": "print.gcode.3mf", "estimated_seconds": 5400,
                                            "slice_sha256": self.digest},
            "color_review": {
                "day": self.key, "status": "sent", "device": printer_identity(), "code": self.code,
                "channel": "private", "can_confirm": True, "attempted_at": self.key + "T23:55:00+08:00",
                "options": [self.spool], "slice_sha256": self.digest,
                "receipt": {"mode": "one_way", "message_id": "test", "identity": "test", "code": self.code},
            },
        })

    def test_confirm_after_restart_dispatches_only_this_slice_before_daily_schedule(self):
        view = self.app.state(self.key)["job"]
        self.assertTrue(view["resume_color"])
        self.assertTrue(view["color_review"]["can_confirm"])
        self.app.mark_ready(self.key, True, None)
        restarted = App(self.app.data)
        restarted.run_due(self.stamp)
        self.send.assert_not_called()
        restarted.colors.confirm(self.key, self.code, self.spool["source"])
        restarted.run_due(self.stamp)
        restarted.worker.join(3)
        restarted.run_due(self.stamp)
        self.send.assert_called_once_with(
            self.app.directory(self.key) / "print.gcode.3mf", model="P2S", source=self.spool["source"],
            expected_rgba=self.spool["rgba"], expected_slice=self.digest, expected_bed="c" * 64,
        )
        self.assertEqual(restarted.job(self.key)["status"], "submitted")

    def test_previous_bed_clearance_never_dispatches(self):
        self.app.colors.confirm(self.key, self.code, self.spool["source"])
        job = self.app.job(self.key)
        self.app.save(self.key, job | {"ready": True, "ready_date": self.key, "ready_device": printer_identity(),
                                      "ready_bed": "c" * 64})
        restarted = App(self.app.data)
        self.assertFalse(restarted.state(self.key)["job"]["ready"])
        restarted.run_due(self.stamp)
        with self.assertRaisesRegex(Problem, "清盘"):
            restarted.run(self.key, "print")
        self.send.assert_not_called()

    def test_another_clearance_revokes_the_historical_job(self):
        self.app.mark_ready(self.key, True, None)
        self.app.save(self.today, {"status": "prepared", "print": self.app.job(self.key)["print"]})
        self.app.mark_ready(self.today, True, None)
        self.assertFalse(self.app.job(self.key)["ready"])
        self.app.colors.confirm(self.key, self.code, self.spool["source"])
        self.app.run_due(self.stamp)
        self.send.assert_not_called()

    def test_closed_editor_cannot_revive_a_clearance_used_elsewhere(self):
        self.app.mark_ready(self.key, True, None)
        self.app.edit(self.key, True)
        reopened = App(self.app.data)
        edit_token = reopened.job(self.key)["edit_token"]
        reopened.save(self.today, {"status": "prepared", "print": reopened.job(self.key)["print"]})
        reopened.mark_ready(self.today, True, None)
        reopened.edit(self.key, False, edit_token)
        self.assertFalse(reopened.state(self.key)["job"]["ready"])
        self.send.assert_not_called()

    def test_edited_or_unrelated_slice_cannot_use_this_clearance(self):
        job = self.app.job(self.key)
        for changed in ({"edit_token": "open"}, {"print": job["print"] | {"slice_sha256": "b" * 64}},
                        {"color_review": job["color_review"] | {"day": self.today}}):
            with self.subTest(changed=list(changed)):
                self.app.save(self.key, job | changed)
                self.assertFalse(self.app.state(self.key)["job"].get("resume_color"))
                with self.assertRaises(Problem):
                    self.app.mark_ready(self.key, True, None)
        self.bed.assert_not_called()
        self.send.assert_not_called()
