"""Drive a real workbench through native card events with an isolated printer."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest import TestCase
from unittest.mock import patch

from local_store import Problem, now, printer_identity
from printer import PrinterError, PrintStatusUnknown
from workshop import App


class CardPrintTests(TestCase):
    def setUp(self):
        self.enterContext(patch.dict("os.environ", {"BAMBU_SERIAL": "unit", "BAMBU_IP": "localhost",
                                "BAMBU_ACCESS_CODE": "test", "LUX3D_API_KEY": "test"}, clear=True))
        self.app = App(Path(self.enterContext(TemporaryDirectory())))
        self.key = (now().date() - timedelta(days=1)).isoformat()
        self.spool = {"source": "ams-a4", "rgba": "FFFFFFFF", "label": "A4 · 白色 PLA"}
        self.data = b"isolated slice"
        self.digest = sha256(self.data).hexdigest()
        self.code = "01AB23CD"
        self.receipt = {"interaction": "card", "mode": "one_way", "message_id": "om_card",
                        "chat_id": "oc_owner", "identity": "bound-owner", "code": self.code}
        self.app.save(self.key, {"status": "prepared", "ready": False, "source": "external",
            "print": {"artifact": "print.gcode.3mf", "estimated_seconds": 1400, "slice_sha256": self.digest},
            "color_review": {"status": "sent", "device": printer_identity(), "day": self.key,
                "receipt": self.receipt, "channel": "private", "options": [self.spool], "code": self.code,
                "slice_sha256": self.digest}})
        self.path = self.app.directory(self.key) / "print.gcode.3mf"
        self.path.write_bytes(self.data)
        self.bed = self.enterContext(patch("workshop.read_idle_bed", return_value="b" * 64))
        self.spools = self.enterContext(patch("workshop.available_spools", return_value=[self.spool]))
        self.send = self.enterContext(patch("workshop.send_print", return_value={}))

    def click(self, **changes):
        params = {"key": self.key, "code": self.code, "source": self.spool["source"],
                  "message_id": "om_card", "chat_id": "oc_owner", "identity": "bound-owner",
                  "event_id": "click-1", "clicked_at": now()}
        return self.app.print_from_card(**(params | changes))

    def test_one_click_after_midnight_starts_and_does_not_send_again(self):
        self.assertIn("已接单", self.click())
        self.send.assert_called_once_with(self.path, model="P2S", source="ams-a4", expected_rgba="FFFFFFFF",
                                          expected_slice=self.digest, expected_bed="b" * 64)
        self.app = App(self.app.data)
        self.assertIn("已接单", self.click())
        self.assertIn("已接单", self.click(event_id="second-click"))
        self.app.run_due(now())
        self.assertEqual(self.send.call_count, 1)
        self.assertFalse(self.app.job(self.key)["ready"])

    def test_migrated_legacy_selection_requires_its_new_card(self):
        job = self.app.job(self.key)
        old = self.receipt.copy()
        old.pop("interaction")
        old.update(message_id="om_old")
        job["color_review"].update(status="confirmed", selected={"source": "ams-a4", "rgba": "FFFFFFFF"}, reply_id="local-feishu-code",
                                   receipt=old, card_receipt=self.receipt)
        job["color_review"]["options"].append(self.spool | {"source": "ams-a3"})
        job["source"] = "ams-a4"
        self.app.save(self.key, job)
        self.app.run_due(now())
        with self.assertRaises(Problem):
            self.click(message_id="om_old")
        with self.assertRaisesRegex(Problem, "已确认其他耗材"):
            self.click(source="ams-a3")
        self.send.assert_not_called()
        self.assertIn("已接单", self.click())

    def test_invalid_binding_old_time_and_changed_slice(self):
        for changes in ({"identity": "other"}, {"message_id": "om_other"}, {"chat_id": "oc_else"},
                        {"source": "ams-a1"}, {"code": ""}, {"event_id": ""},
                        {"clicked_at": now() - timedelta(minutes=6)}, {"clicked_at": now().replace(tzinfo=None)}):
            with self.subTest(changes=changes), self.assertRaises(Problem):
                self.click(**changes)
        self.path.write_bytes(b"other slice")
        with self.assertRaisesRegex(Problem, "切片"):
            self.click()
        self.bed.assert_not_called()
        self.send.assert_not_called()
        self.assertFalse(self.app.job(self.key)["ready"])

    def test_machine_and_filament_failures_need_new_click_and_do_not_grant_permission(self):
        self.bed.side_effect = PrinterError("设备忙。")
        with self.assertRaisesRegex(Problem, "设备忙"):
            self.click()
        self.bed.side_effect = None
        with self.assertRaisesRegex(Problem, "已处理"):
            self.click()
        self.spools.return_value = [self.spool | {"rgba": "F00000FF"}]
        with self.assertRaisesRegex(Problem, "颜色已改变"):
            self.click(event_id="second-click")
        self.app.run_due(now())
        self.send.assert_not_called()
        self.assertFalse(self.app.job(self.key)["ready"])
        self.assertNotEqual(self.app.job(self.key)["color_review"]["status"], "confirmed")

    def test_concurrent_edits_or_scheduler_cannot_send_a_half_confirmed_job(self):
        entered, release = Event(), Event()
        def check():
            entered.set()
            self.assertTrue(release.wait(2))
            return "b" * 64
        self.bed.side_effect = check
        with ThreadPoolExecutor(1) as pool:
            first = pool.submit(self.click)
            try:
                self.assertTrue(entered.wait(2))
                self.assertIn("正在核对", self.click())
                self.app.run_due(now())
                self.app.edit(self.key, True)
            finally:
                release.set()
            with self.assertRaisesRegex(Problem, "变化"):
                first.result(timeout=2)
        self.assertFalse(self.app.job(self.key)["ready"])
        self.send.assert_not_called()

    def test_uncertain_device_state_cannot_be_resubmitted_by_a_new_click(self):
        self.send.side_effect = PrintStatusUnknown("待核对")
        with self.assertRaisesRegex(Problem, "待核对"):
            self.click()
        self.app = App(self.app.data)
        with self.assertRaisesRegex(Problem, "待核对"):
            self.click(event_id="second-click")
        self.assertEqual(self.send.call_count, 1)
