"""Offline checks for the ordinary bot's private, one-way notifications."""
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import feishu_print as feishu


class TestOrdinaryBot(TestCase):
    def setUp(self):
        temp = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.data = temp / "data"
        self.enterContext(patch.object(feishu, "PRODUCTION_DATA", self.data))
        self.enterContext(patch.dict(os.environ, {"MOODPRINT_DATA": str(self.data)}))
        self.enterContext(patch.object(feishu.Path, "home", return_value=temp))
        cli = temp / "lark-cli"
        cli.touch()
        self.enterContext(patch.object(feishu, "CLI", cli))
        self.profile_path = temp / ".lark-cli" / "config.json"
        self.profile_path.parent.mkdir()
        self.profile = {"name": "feishu-danmu", "appId": "cli_danmu", "brand":"feishu",
                        "users": [{"userOpenId":"ou_owner"}]}
        self.profiles(self.profile)
        self.bot = {"app_name":"飞书工作岛", "open_id":"ou_bot"}
        self.posted = []
        self.api = self.enterContext(patch.object(feishu, "_api", side_effect=self.fake_api))
        self.params = {"day": "2026-11-19", "code": "1A2B3C4D", "title": "头像小物",
                       "print_details": "高 60 毫米，约鸡蛋高。2 小时 10 分钟，14 克。",
                       "choices": {"ams-a2": "A2 棕色 PLA", "external": "外置 白色 PLA"}}

    def profiles(self, *apps):
        self.profile_path.write_text(json.dumps({"apps": apps}), encoding="utf-8")

    def fake_api(self, method, route, *, body=None, params=None):
        if method == "GET":
            self.assertEqual(route, "/bot/v3/info")
            return self.bot
        self.assertEqual((method, route), ("POST", "/im/v1/messages"))
        self.assertEqual(params, {"receive_id_type":"open_id"})
        self.assertEqual(body["receive_id"], "ou_owner")
        self.posted.append(body)
        return {"message_id": "om_invite", "create_time": "1795018200000", "chat_id": "oc_room"}

    def test_bind_without_sending_or_reading_any_chat(self):
        self.assertFalse(feishu.configured())
        self.assertEqual(feishu.begin_pairing(), {"bound": True, "mode": "one_way", "bot_name": "飞书工作岛"})
        self.assertFalse(feishu.cards_enabled())
        self.api.assert_called_once_with("GET", "/bot/v3/info")
        self.assertTrue(feishu.configured())
        self.assertFalse(self.posted)
        state = json.loads(feishu._state().read_text())
        self.assertNotIn("ou_owner", str(state))

    def test_switching_owner_app_or_bot_cannot_send(self):
        feishu.begin_pairing()
        for source in [self.profile | {"users":[{"userOpenId":"ou_other"}]}, self.profile | {"appId":"cli_changed"},
                       self.profile | {"users":[{"userOpenId":"ou_owner"}, {"userOpenId":"ou_other"}]},
                       self.profile | {"name":"other"}]:
            self.profiles(source)
            self.assertFalse(feishu.configured())
            with self.assertRaises(feishu.FeishuError):
                feishu.notify_colors(**self.params)
        self.profiles(self.profile)
        self.bot["open_id"] = "ou_unexpected"
        with self.assertRaises(feishu.FeishuError):
            feishu.notify_colors(**self.params)
        self.assertFalse(self.posted)

    def test_notice_has_print_details_private_code_real_job_and_stable_uuid(self):
        feishu.begin_pairing()
        first = feishu.notify_colors(**self.params, claim_code="FEEDBEEF")
        second = feishu.notify_colors(**self.params, claim_code="FEEDBEEF")
        self.assertEqual(first, second)
        self.assertEqual(first["mode"], "one_way")
        self.assertEqual(first["message_id"], "om_invite")
        self.assertEqual(self.posted[0]["uuid"], self.posted[1]["uuid"])
        text = json.loads(self.posted[0]["content"])["text"]
        for part in ("60 毫米", "鸡蛋", "2 小时", "14 克", "A2 棕色 PLA", "FEEDBEEF", "清空",
                     "http://127.0.0.1:17868/?day=2026-11-19#choose=FEEDBEEF"):
            self.assertIn(part, text)
        feishu.notify_colors(**(self.params | {"day":"aholo-character"}))
        self.assertIn("?day=aholo-character#choose=1A2B3C4D", self.posted[-1]["content"])
        self.assertNotEqual(self.posted[-1]["uuid"], self.posted[0]["uuid"])

    def test_revoked_or_preexisting_legacy_binding_cannot_send(self):
        self.data.mkdir()
        feishu._state().write_text(json.dumps({"bound":True,"identity":feishu._account().identity, "chat":"oc_old"}))
        self.assertFalse(feishu.configured())
        with self.assertRaises(feishu.FeishuError):
            feishu.notify_colors(**self.params)
        self.api.assert_not_called()

    def test_native_card_uses_verified_spools_one_click_and_a_separate_delivery_id(self):
        feishu.begin_pairing()
        with self.assertRaises(feishu.FeishuError):
            feishu.notify_card(**self.params)
        self.assertFalse(self.posted)
        feishu.enable_cards()
        self.assertTrue(feishu.cards_enabled())
        feishu.notify_colors(**self.params)
        receipt = feishu.notify_card(**self.params)
        self.assertEqual(feishu.notify_card(**self.params), receipt)
        self.assertNotEqual(self.posted[0]["uuid"], self.posted[1]["uuid"])
        self.assertEqual(self.posted[1]["uuid"], self.posted[2]["uuid"])
        self.assertEqual(receipt["interaction"], "card")
        self.assertEqual(receipt["chat_id"], "oc_room")
        self.assertEqual(receipt["identity"], feishu.bound_identity())
        self.assertEqual(self.posted[1]["msg_type"], "interactive")
        card = json.loads(self.posted[1]["content"])
        self.assertEqual(card["schema"], "2.0")
        self.assertIn(self.params["title"], card["header"]["title"]["content"])
        self.assertNotIn("http", self.posted[1]["content"])
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["text"]["content"], self.params["print_details"])
        buttons = [el for el in elements if el["tag"] == "button"]
        self.assertEqual(len(buttons), len(self.params["choices"]))
        for button, source in zip(buttons, self.params["choices"]):
            self.assertIn("已清盘", button["text"]["content"])
            self.assertIn("打印", button["text"]["content"])
            self.assertEqual(button["behaviors"], [{"type":"callback", "value":{
                "action":"moodprint_print", "day":self.params["day"], "code":self.params["code"], "source":source}}])
        self.profiles(self.profile | {"users":[{"userOpenId":"ou_changed"}]})
        self.assertFalse(feishu.cards_enabled())
        with self.assertRaises(feishu.FeishuError):
            feishu.bound_identity()
        with self.assertRaises(feishu.FeishuError):
            feishu.enable_cards()
        self.assertEqual(len(self.posted), 3)

    def test_feedback_retains_choices_only_for_retry(self):
        feishu.begin_pairing()
        feishu.enable_cards()
        self.api.side_effect = lambda method, *args, **kwargs: self.bot if method == "GET" else {}
        for retry in (self.params, None):
            feishu.card_feedback("test-callback", "打印状态示例", retry=retry)
            args, kwargs = self.api.call_args
            self.assertEqual(args, ("POST", "/interactive/v1/card/update"))
            self.assertEqual(kwargs["body"]["token"], "test-callback")
            elements = kwargs["body"]["card"]["body"]["elements"]
            self.assertTrue(any(el.get("text", {}).get("content") == "打印状态示例" for el in elements))
            self.assertEqual(sum(el["tag"] == "button" for el in elements), 2 if retry else 0)

    def test_generate_feedback_redraws_the_single_consent_button(self):
        feishu.begin_pairing()
        feishu.enable_cards()
        self.api.side_effect = lambda method, *args, **kwargs: self.bot if method == "GET" else {}
        retry = dict(kind="generate", day="2026-11-20", title="相机", code="A1B2C3D4", idea="一台相机", credits=32)
        feishu.card_feedback("test-callback", "Aholo 暂时不可用", retry=retry)
        elements = self.api.call_args.kwargs["body"]["card"]["body"]["elements"]
        buttons = [el for el in elements if el["tag"] == "button"]
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0]["behaviors"][0]["value"]["action"], "moodprint_generate")
        self.assertIn("32", buttons[0]["text"]["content"])

    def test_isolated_workbench_never_accesses_the_live_robot(self):
        with patch.dict(os.environ, {"MOODPRINT_DATA": str(self.data / "fixture")}):
            self.assertFalse(feishu.configured())
            with self.assertRaises(feishu.FeishuError):
                feishu.begin_pairing()
            self.api.assert_not_called()


class TestFeishuTransport(TestCase):
    def test_detailed_post_error_differs_from_timeout(self):
        error = subprocess.CompletedProcess([], 1, '{"ok":false,"error":{"code":99991672}}', "")
        with patch.object(feishu.subprocess, "run", return_value=error):
            with self.assertRaises(feishu.FeishuError) as result:
                feishu._api("POST", "/im/v1/messages", body={})
            self.assertFalse(result.exception.uncertain)
        with patch.object(feishu.subprocess, "run", side_effect=subprocess.TimeoutExpired([], 1)):
            for method in ("POST", "GET"):
                with self.assertRaises(feishu.FeishuError) as result:
                    feishu._api(method, "/im/v1/messages", body={})
                self.assertIs(result.exception.uncertain, method == "POST")
