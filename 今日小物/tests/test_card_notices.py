"""Exercise card migration and first delivery without a real printer or Feishu."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from feishu_print import FeishuError
from local_store import Problem, now
from workshop import App


class CardNoticeTests(TestCase):
    def setUp(self):
        data = Path(self.enterContext(TemporaryDirectory()))
        self.app = App(data)
        self.app.personal_chat = True
        self.app.card_listener.ready.set()
        self.enterContext(patch("feishu_print.PRODUCTION_DATA", data))
        self.enterContext(patch("feishu_print.cards_enabled", return_value=True))
        self.enterContext(patch("feishu_print.bound_identity", return_value="bound-user"))
        self.enterContext(patch("feishu_print.configured", return_value=True))
        self.enterContext(patch("color_review.printer_identity", return_value="printer"))
        self.day = now().date().isoformat()
        self.spools = [
            {"source": "ams-a3", "label": "A3 · 浅蓝色 PLA", "color": "#A4DBE8", "rgba": "A4DBE8FF"},
            {"source": "ams-a4", "label": "A4 · 白色 PLA", "color": "#FFFFFF", "rgba": "FFFFFFFF"},
        ]
        self.enterContext(patch("color_review.available_spools", return_value=self.spools))
        self.send = self.enterContext(patch("feishu_print._send_private", side_effect=self.receipt))
        self.digest = sha256(b"fixture").hexdigest()
        self.app.save(self.day, {
            "title": "测试相机", "ready": False, "status": "prepared",
            "print": {"artifact": "print.gcode.3mf", "dimensions_mm": [60, 66, 66], "estimated_seconds": 10751,
                      "filament_grams": 41.32, "slice_sha256": self.digest},
        })
        (self.app.directory(self.day) / "print.gcode.3mf").write_bytes(b"fixture")

    def receipt(self, day, code, msg_type, card):
        self.assertEqual(day, self.day)
        self.assertEqual(msg_type, "interactive")
        return {"interaction": "card", "mode": "one_way", "code": code, "identity": "bound-user",
                "message_id": "om_new", "chat_id": "oc_private"}

    def button_sources(self):
        card = self.send.call_args.args[3]
        buttons = [row for row in card["body"]["elements"] if row["tag"] == "button"]
        for row in buttons:
            self.assertIn("已清盘", row["text"]["content"])
            self.assertEqual(row["behaviors"][0]["type"], "callback")
        return [row["behaviors"][0]["value"]["source"] for row in buttons]

    def save_old_selection(self):
        job = self.app.job(self.day)
        job.update(source="ams-a4", color_review={
            "channel": "private", "status": "confirmed", "day": self.day, "device": "printer",
            "details": "已核实的切片尺寸和耗时", "code": "ABCD1234", "slice_sha256": self.digest,
            "selected": self.spools[1], "options": self.spools, "reply_id": "local-feishu-code",
            "receipt": {"mode": "one_way", "identity": "bound-user", "code": "ABCD1234", "message_id": "om_old"},
        })
        self.app.save(self.day, job)

    def test_upgrade_keeps_only_previously_selected_color_and_original_receipt(self):
        self.save_old_selection()
        self.app.colors.upgrade_notice(self.day)
        self.app.colors.upgrade_notice(self.day)
        self.assertEqual(self.button_sources(), ["ams-a4"])
        self.send.assert_called_once()
        review = self.app.job(self.day)["color_review"]
        self.assertEqual(review["receipt"]["message_id"], "om_old")
        self.assertEqual(review["card_receipt"]["message_id"], "om_new")
        self.assertFalse(self.app.job(self.day)["ready"])

    def test_uncertain_upgrade_remains_claimed_after_a_restart(self):
        self.save_old_selection()
        self.send.side_effect = FeishuError("发送状态不明", uncertain=True)
        with self.assertRaises(FeishuError):
            self.app.colors.upgrade_notice(self.day)
        again = App(self.app.data)
        again.personal_chat = True
        again.card_listener.ready.set()
        with self.assertRaisesRegex(Problem, "已尝试发送"):
            again.colors.upgrade_notice(self.day)
        self.send.assert_called_once()
        self.assertNotIn("card_receipt", again.job(self.day)["color_review"])

    def test_new_slice_delivers_one_card_with_all_reported_spools(self):
        self.app.colors.tick()
        self.app.colors.tick()
        self.send.assert_called_once()
        self.assertEqual(self.button_sources(), ["ams-a3", "ams-a4"])
        job = self.app.job(self.day)
        self.assertEqual((job["status"], job["ready"]), ("prepared", False))
        review = job["color_review"]
        self.assertEqual(review["status"], "sent")
        self.assertEqual(review["receipt"]["code"], review["code"])
        self.assertEqual(review["receipt"]["interaction"], "card")
        self.assertFalse(review["can_confirm"])

    def test_uncertain_first_delivery_is_not_repeated_by_the_scheduler(self):
        self.send.side_effect = FeishuError("发送状态不明", uncertain=True)
        self.app.colors.tick()
        self.app.colors.tick()
        self.send.assert_called_once()
        review = self.app.job(self.day)["color_review"]
        self.assertTrue(review["delivery_uncertain"])
        self.assertNotIn("receipt", review)
