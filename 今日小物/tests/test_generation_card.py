"""Daily credit consent through a Feishu card, and the off-LAN reminder."""
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import feishu_print
from generation_card import CREDITS, feishu_consent
from local_store import Problem, now, printer_identity
from printer import PrinterUnreachable
from workshop import App


RECEIPT = {"identity": "owner", "message_id": "om_gen", "chat_id": "oc_owner", "interaction": "card"}


class GenerationCardTests(TestCase):
    def setUp(self):
        self.enterContext(patch.dict("os.environ", {"BAMBU_SERIAL": "unit", "BAMBU_IP": "localhost",
                                "BAMBU_ACCESS_CODE": "test", "LUX3D_API_KEY": "test"}, clear=True))
        self.app = App(Path(self.enterContext(TemporaryDirectory())))
        self.app.personal_chat = True
        self.app.settings = {"at": "00:00", "auto_prepare": True, "auto_print": True, "prepare_after_ready": True}
        self.app.card_listener.ready.set()
        self.key = now().date().isoformat()
        self.app.save(self.key, {"status": "recorded", "title": "相机", "idea": "一台矮胖的相机", "summary": "s",
                                 "mood": "未标记", "ready": False, "source": "external"})
        self.enterContext(patch.object(feishu_print, "cards_enabled", return_value=True))
        self.send = self.enterContext(patch.object(feishu_print, "notify_generate_card", return_value=RECEIPT))
        self.app.run = Mock()

    def card(self):
        return self.app.job(self.key)["generation_card"]

    def click(self, **changes):
        params = dict(message_id="om_gen", chat_id="oc_owner", event_id="ev-1", identity="owner", clicked_at=now())
        return self.app.generation_cards.confirm(self.key, self.card()["code"], **(params | changes))

    def test_one_card_per_version_after_the_scheduled_time(self):
        self.app.settings["at"] = "23:59:59"
        self.app.generation_cards.tick()
        self.send.assert_not_called()
        self.app.settings["at"] = "00:00"
        self.app.generation_cards.tick()
        self.app.generation_cards.tick()
        self.send.assert_called_once()
        self.assertEqual(self.send.call_args.kwargs["credits"], CREDITS)
        self.assertEqual(self.card()["status"], "sent")
        # Without a click nothing is generated.
        self.app.run_due(now())
        self.app.run.assert_not_called()

    def test_click_starts_generation_once_consented(self):
        self.app.generation_cards.tick()
        self.assertIn("已开始生成", self.click())
        self.app.run.assert_called_once_with(self.key, "generate")
        self.assertTrue(feishu_consent(self.app.job(self.key), self.key))

    def test_busy_workbench_starts_it_from_the_schedule(self):
        self.app.generation_cards.tick()
        self.app.working_key = "sample"
        self.assertIn("忙完", self.click())
        self.app.run.assert_not_called()
        self.app.working_key = None
        self.app.run_due(now())
        self.app.run.assert_called_once_with(self.key, "generate")

    def test_changed_design_or_foreign_click_is_not_consent(self):
        self.app.generation_cards.tick()
        for changes in ({"message_id": "om_other"}, {"chat_id": "oc_else"}, {"identity": "other"},
                        {"clicked_at": now() - timedelta(minutes=6)}):
            with self.subTest(changes=changes), self.assertRaises(Problem):
                self.click(**changes)
        job = self.app.job(self.key)
        job["idea"] = "换成一只狐狸"
        self.app.save(self.key, job)
        with self.assertRaisesRegex(Problem, "已改动"):
            self.click()
        self.app.run_due(now())
        self.app.run.assert_not_called()
        # The new version gets its own card.
        self.app.generation_cards.tick()
        self.assertEqual(self.send.call_count, 2)

    def test_failed_send_retries_with_the_same_code(self):
        self.send.side_effect = feishu_print.FeishuError("飞书未返回可核对的发送结果。", uncertain=True)
        self.app.generation_cards.tick()
        code = self.card()["code"]
        self.assertEqual(self.card()["status"], "error")
        job = self.app.job(self.key)
        job["generation_card"]["next_check"] = ""
        self.app.save(self.key, job)
        self.send.side_effect = None
        self.app.generation_cards.tick()
        self.assertEqual(self.card()["code"], code)
        self.assertEqual(self.card()["status"], "sent")

    def test_no_card_when_consent_is_not_required(self):
        self.app.settings["prepare_after_ready"] = False
        self.app.generation_cards.tick()
        self.send.assert_not_called()


class AwayReminderTests(TestCase):
    def setUp(self):
        self.enterContext(patch.dict("os.environ", {"BAMBU_SERIAL": "unit", "BAMBU_IP": "localhost",
                                "BAMBU_ACCESS_CODE": "test", "LUX3D_API_KEY": "test"}, clear=True))
        self.app = App(Path(self.enterContext(TemporaryDirectory())))
        self.app.personal_chat = True
        self.key = now().date().isoformat()
        self.app.save(self.key, {"status": "prepared", "title": "相机", "idea": "i", "summary": "s", "mood": "未标记",
                                 "ready": False, "source": "external",
                                 "print": {"artifact": "print.gcode.3mf", "estimated_seconds": 1400}})
        self.enterContext(patch("color_review.available_spools",
                                side_effect=PrinterUnreachable("连不上 P2S：这台 Mac 现在不在打印机所在的局域网")))
        self.enterContext(patch.object(feishu_print, "configured", return_value=True))
        self.text = self.enterContext(patch.object(feishu_print, "notify_text", return_value={}))

    def test_reminds_once_per_piece(self):
        for _ in range(3):
            job = self.app.job(self.key)
            if job.get("color_review"):
                job["color_review"]["next_check"] = ""
                self.app.save(self.key, job)
            self.app.colors.tick()
        self.text.assert_called_once()
        self.assertIn("连不上打印机", self.text.call_args.kwargs["text"])
        review = self.app.job(self.key)["color_review"]
        self.assertTrue(review["away_notified"])
        self.assertEqual(review["device"], printer_identity())
