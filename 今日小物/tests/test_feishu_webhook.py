"""Offline verification of private group consent, signed notices and ambiguous delivery."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import feishu_webhook as hook


URL = "https://open.feishu.cn/open-apis/bot/v2/hook/00000000-aaaa-bbbb-cccc-000000000000"
ARGS = dict(day="sample", title="灯塔样品", code="ABC12345", choices={"ams-a2": "A2 · 棕色 PLA #6F5034"}, print_details="高 5.4 厘米，预计 2 小时。")


class Reply(BytesIO):
    status = 200


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.open = self.enterContext(patch("feishu_webhook.build_opener")).return_value.open

    def setup_hook(self):
        return hook.configure(self.directory, webhook=URL, only_me=True, secret="test-secret")

    def test_explicit_private_group_secret_scope_and_sanitized_config(self):
        for only_me in (False, 1, "true"):
            with self.assertRaises(hook.WebhookError):
                hook.configure(self.directory, webhook=URL, only_me=only_me)
        self.assertFalse(hook.configured(self.directory))
        self.assertEqual(self.setup_hook(), {"configured":True})
        self.assertTrue(hook.configured(self.directory))
        self.assertEqual((self.directory / hook.CONFIG).stat().st_mode & 0o777, 0o600)
        hook.configure(self.directory, webhook="", only_me=True)
        self.assertEqual(json.loads((self.directory / hook.CONFIG).read_text())["secret"], "test-secret")
        hook.configure(self.directory, webhook=URL[:-1]+"1", only_me=True)
        self.assertEqual(json.loads((self.directory / hook.CONFIG).read_text())["secret"], "")
        self.assertEqual(hook.disable(self.directory),{"configured":False})
        self.assertFalse(hook.configured(self.directory))
        self.assertNotIn("https",(self.directory / hook.CONFIG).read_text())
        self.open.assert_not_called()

    def test_accept_only_exact_official_destination(self):
        for url in (URL.replace("https", "http"),URL.replace(".cn/", ".cn.evil.example/"),
                    URL.replace(".cn/", ".cn@evil.example/"),URL.replace(".cn/", ".cn:443/"),
                    URL+"?q=1",URL+"#x",URL+"/other",URL+"%2fanything", URL.replace("v2/hook", "im/v1")):
            with self.subTest(url=url), self.assertRaises(hook.WebhookError) as exc:
                hook.configure(self.directory, webhook=url, only_me=True)
            self.assertNotIn(url, str(exc.exception))
        self.open.assert_not_called()

    def test_notice_includes_mac_location_actual_key_and_signature_and_receipt_is_idempotent(self):
        self.setup_hook()
        self.open.return_value = Reply(b'{"code":0}')
        with patch("feishu_webhook.time", return_value=1700000000):
            receipt = hook.notify_colors(self.directory, **ARGS)
        self.assertEqual(receipt["mode"], "one_way")
        self.assertEqual(receipt["channel"], "webhook")
        self.assertNotIn(URL, str(receipt))
        request = self.open.call_args.args[0]
        self.assertEqual(request.full_url, URL)
        body = json.loads(request.data)
        self.assertEqual(body["timestamp"], "1700000000")
        self.assertEqual(body["sign"], "mbm4Y4oluIPQ00qlBIhX8vAZ0EKv3nw0LuTb91jPL84=")
        rows = body["content"]["post"]["zh_cn"]["content"]
        self.assertEqual([r[0]["href"] for r in rows if r[0]["tag"]=="a"],
                         ["http://127.0.0.1:17868/?day=sample#choose=ABC12345"])
        self.assertIn("在运行「今日小物」的 Mac",str(rows))
        self.assertEqual(hook.notify_colors(self.directory, **ARGS),receipt)
        self.open.assert_called_once()

    def test_unknown_delivery_survives_repeat_and_concurrency(self):
        self.setup_hook()
        started,release=Event(),Event()
        def unclear(*args,**kwargs):
            started.set()
            release.wait(2)
            raise TimeoutError(URL)
        self.open.side_effect=unclear
        with ThreadPoolExecutor(max_workers=1) as pool:
            first=pool.submit(hook.notify_colors,self.directory,**ARGS)
            try:
                self.assertTrue(started.wait(1))
                with self.assertRaises(hook.WebhookError) as pending:
                    hook.notify_colors(self.directory,**ARGS)
                self.assertTrue(pending.exception.uncertain)
            finally:
                release.set()
            with self.assertRaises(hook.WebhookError) as interrupted:
                first.result(2)
            self.assertTrue(interrupted.exception.uncertain)
            self.assertNotIn(URL,str(interrupted.exception))
        with self.assertRaises(hook.WebhookError) as after:
            hook.notify_colors(self.directory, **ARGS)
        self.assertTrue(after.exception.uncertain)
        self.open.assert_called_once()

    def test_redirect_and_unrecognized_response_are_never_replayed(self):
        self.setup_hook()
        self.assertIsNone(hook._NoRedirect().redirect_request(None,None,307,None,None,"https://invalid.example/"))
        for index,outcome in enumerate((HTTPError(URL,307,"redirect",{},BytesIO(b"")),Reply(b'{}'),Reply(b'x'*9000))):
            args=ARGS | {"code":f"CODE000{index}"}
            self.open.side_effect=[outcome]
            with self.assertRaises(hook.WebhookError) as e:
                hook.notify_colors(self.directory,**args)
            self.assertTrue(e.exception.uncertain)
            with self.assertRaises(hook.WebhookError):
                hook.notify_colors(self.directory,**args)
        self.assertEqual(self.open.call_count,3)

    def test_explicit_rejection_can_retry_after_fix_and_old_success_response(self):
        self.setup_hook()
        self.open.side_effect=[HTTPError(URL,400,"bad request",{},BytesIO(b'{"code":19021,"msg":"sensitive"}')),
                               Reply(b'{"StatusCode":0}')]
        with self.assertRaises(hook.WebhookError) as refused:
            hook.notify_colors(self.directory, **ARGS)
        self.assertFalse(refused.exception.uncertain)
        self.assertNotIn("sensitive",str(refused.exception))
        receipt=hook.notify_colors(self.directory, **ARGS)
        self.assertEqual(receipt["code"],ARGS["code"])
        self.assertEqual(self.open.call_count,2)
