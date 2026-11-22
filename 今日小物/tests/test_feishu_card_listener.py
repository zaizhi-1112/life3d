"""Offline callback transport and recipient isolation tests."""
import json
import subprocess
import sys
from threading import Event, RLock
from unittest import TestCase
from unittest.mock import Mock, patch

import feishu_card_listener as listener
import feishu_print
from local_store import Problem, now


class CardListenerTests(TestCase):
    def setUp(self):
        self.account = feishu_print._Account("cli_App", "ou_Owner")
        self.day = now().date().isoformat()
        self.code = "A1B2C3D4"
        self.source = "ams-a4"
        self.action = dict(action="moodprint_print", day=self.day, code=self.code, source=self.source)
        self.event = dict(type="card.action.trigger", host="im_message", action_tag="button",
                          operator_id=self.account.owner, token="opaque-update-placeholder", event_id="cb-001",
                          timestamp=str(int(now().timestamp() * 1000)), message_id="om_Card", chat_id="oc_Home",
                          action_value=json.dumps(self.action))
        receipt = dict(identity=self.account.identity, message_id="om_Card", chat_id="oc_Home",
                       interaction="card", code=self.code)
        self.review = dict(code=self.code, receipt={"interaction": "link"}, card_receipt=receipt,
                           options=[dict(label="A4 白色", color="#FFFFFF", source=self.source)], details="2 小时")
        self.job = dict(status="prepared", title="相机", color_review=self.review)
        self.app = Mock(guard=RLock(), personal_chat=True)
        self.app.job.return_value = self.job
        self.app.print_from_card.return_value = "已确认，正在向打印机发送。"
        self.reader = listener.CardListener(self.app)
        self.enterContext(patch.object(feishu_print, "_account", return_value=self.account))
        self.binding = self.enterContext(patch.object(feishu_print, "_verified", return_value={"bot_open_id": "ou_Bot", "card_actions": True}))
        self.feedback = self.enterContext(patch.object(feishu_print, "card_feedback", create=True))

    def handle(self, **overrides):
        self.reader.handle(json.dumps(self.event | overrides).encode(), self.account, "ou_Bot")

    def test_authenticated_click_reaches_exact_job_and_feedback(self):
        self.handle()
        args, kwargs = self.app.print_from_card.call_args
        self.assertEqual(args, (self.day, self.code, self.source))
        self.assertEqual(kwargs["identity"], self.account.identity)
        self.assertEqual(kwargs["message_id"], "om_Card")
        self.assertIsNotNone(kwargs["clicked_at"].tzinfo)
        # Feishu allows two updates per tap: an immediate acknowledgement, then the result.
        self.assertEqual(self.feedback.call_count, 2)
        ack, result = self.feedback.call_args_list
        self.assertEqual(ack.args[0], "opaque-update-placeholder")
        self.assertIn("正在核对", ack.args[1])
        self.assertEqual(result, (("opaque-update-placeholder", self.app.print_from_card.return_value), {"retry": None}))

    def test_other_senders_chats_messages_actions_and_unbound_accounts_are_ignored(self):
        for change in [{"type": "im.message.receive_v1"}, {"operator_id": "ou_Other"}, {"chat_id": "oc_Elsewhere"},
                       {"message_id": "om_Other"}, {"host": "im_top_notice"}, {"action_tag": "checker"},
                       {"event_id": None}, {"timestamp": "999999999999999999999"},
                       {"action_value": "{"}, {"action_value": json.dumps(self.action | {"code": "FFFFFFFF"})},
                       {"action_value": json.dumps(self.action | {"action": "other"})}]:
            with self.subTest(fields=list(change)):
                self.handle(**change)
        self.binding.return_value = {"bot_open_id": "ou_Changed"}
        self.handle()
        self.app.print_from_card.assert_not_called()
        self.feedback.assert_not_called()

    def test_generate_click_reaches_generation_consent_and_keeps_button_on_failure(self):
        self.job.update(status="recorded", idea="一台相机", generation_card=dict(
            code=self.code, day=self.day, receipt=dict(identity=self.account.identity, message_id="om_Card",
                                                       chat_id="oc_Home", interaction="card")))
        self.job["generation_card"]["fingerprint"] = listener.fingerprint(self.job)
        generate = dict(action="moodprint_generate", day=self.day, code=self.code)
        self.app.generation_cards.confirm.return_value = "已开始生成「相机」。"
        self.handle(action_value=json.dumps(generate))
        args, kwargs = self.app.generation_cards.confirm.call_args
        self.assertEqual(args, (self.day, self.code))
        self.assertEqual(kwargs["message_id"], "om_Card")
        self.app.print_from_card.assert_not_called()
        self.assertIn("开始生成", self.feedback.call_args_list[0].args[1])
        self.assertIsNone(self.feedback.call_args.kwargs["retry"])
        self.app.generation_cards.confirm.side_effect = Problem("请先在本机配置 Aholo API Key。")
        self.handle(action_value=json.dumps(generate))
        self.assertEqual(self.feedback.call_args.kwargs["retry"]["kind"], "generate")
        # A print button can never be replayed as consent, nor the reverse.
        self.handle(action_value=json.dumps(generate | {"code": "FFFFFFFF"}))
        self.assertEqual(self.app.generation_cards.confirm.call_count, 2)

    def test_known_preflight_failure_preserves_only_valid_buttons(self):
        self.app.print_from_card.side_effect = Problem("设备忙，稍后再点。")
        self.review["selected"] = {"source": self.source}
        self.review["options"].append(dict(source="external", color="#AAAAAA", label="外置"))
        self.handle()
        self.assertEqual(self.feedback.call_args.kwargs["retry"]["choices"], {self.source: "A4 白色 #FFFFFF"})
        self.job["status"] = "print_unknown"
        self.handle()
        self.assertIsNone(self.feedback.call_args.kwargs["retry"])

    def test_consumer_lifecycle_uses_fake_child_and_ignores_raw_cli_diagnostics(self):
        got_event = Event()
        self.app.print_from_card.side_effect = lambda *a, **k: (got_event.set(), "已提交")[1]
        launch = subprocess.Popen
        children = []
        script = (
            "import sys\n"
            "print('[event] ready event_key=card.action.trigger',file=sys.stderr,flush=True)\n"
            "print(sys.argv[1],flush=True)\n"
            "sys.stdin.readline()\n"
        )

        def fake_cli(cmd, **kwargs):
            self.assertIn("--jq", cmd)
            # The real CLI pretty-prints each --jq result over several lines.
            p = launch([sys.executable, "-B", "-c", script, json.dumps(self.event, indent=2)], **kwargs)
            children.append(p)
            return p

        with (patch.object(feishu_print, "cards_enabled", return_value=True),
              patch.object(feishu_print, "_verify_bot", return_value="ou_Bot"),
              patch.object(listener.subprocess, "Popen", side_effect=fake_cli)):
            try:
                self.reader.start()
                self.reader.start()
                self.assertTrue(self.reader.ready.wait(3))
                self.assertTrue(got_event.wait(3))
            finally:
                self.reader.close()
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertFalse(self.reader.ready.is_set())

    def test_microsecond_timestamp_from_the_real_cli_is_accepted(self):
        # Seen on 2026-11-21: the CLI sends 16-digit microseconds, not the documented milliseconds.
        self.handle(timestamp=str(int(now().timestamp() * 1_000_000)))
        clicked_at = self.app.print_from_card.call_args.kwargs["clicked_at"]
        self.assertLess(abs((now() - clicked_at).total_seconds()), 5)

    def test_framer_accepts_pretty_and_single_line_events_and_drops_noise(self):
        framer = listener._EventFramer()
        pretty = json.dumps(self.event, indent=2).encode().split(b"\n")
        lines = [b"not json", *pretty, json.dumps(self.event).encode(), b"{", b'  "broken": ', b"}", *pretty]
        events = [raw for raw in map(framer.feed, lines) if raw]
        self.assertEqual(len(events), 3)
        self.assertTrue(all(json.loads(raw) == self.event for raw in events))

    def test_isolated_workspace_never_spawns(self):
        self.app.personal_chat = False
        with patch.object(listener.subprocess, "Popen") as spawn:
            self.reader.start()
            self.reader.close()
            spawn.assert_not_called()
