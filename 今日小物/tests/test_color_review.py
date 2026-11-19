"""Replay the reminder and the user's reply without accessing the real chat or printer."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from local_store import now, Problem
from printer import _check_spool, _spool, ColorChanged
from test_printer import ready_status
from workshop import App


BROWN = {"source": "ams-a2", "label": "A2 · 棕色 PLA", "color": "#6F5034", "rgba": "6F5034FF"}


class ColorGateTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.app = App(Path(tmp.name))
        self.enterContext(patch("workshop.read_idle_bed", return_value="c"*64))
        self.day = now().date().isoformat()
        env = patch.dict("os.environ", {"BAMBU_SERIAL":"p2s-test", "BAMBU_ACCESS_CODE":"offline", "BAMBU_IP":"localhost",
                                       "LUX3D_API_KEY":"offline"})
        env.start()
        self.addCleanup(env.stop)
        self.app.save(self.day, {"title":"测试头像", "status":"prepared", "summary":"私密内容",
            "print":{"artifact":"print.gcode.3mf", "estimated_seconds":6000, "dimensions_mm":[42,41,68], "filament_grams":23.5}})
        (self.app.directory(self.day)/"print.gcode.3mf").write_bytes(b"isolated slice")
        self.app.mark_ready(self.day, True, "ams-a3")

    def test_only_current_private_reply_unlocks_start(self):
        self.app.update_settings(self.app.settings | {"auto_prepare": True, "auto_print": True, "at": "00:00"})
        with (
            patch.object(self.app, "personal_chat", True),
            patch("color_review.feishu_webhook.configured", return_value=False),
            patch("color_review.available_spools", return_value=[BROWN]),
            patch("color_review.feishu_print.configured", return_value=True),
            patch("color_review.feishu_print.notify_colors", return_value={"opaque":"private-room"}) as send,
            patch("workshop.send_print", return_value={}) as printer,
        ):
            self.app.run_due(now())
            with self.assertRaisesRegex(Problem, "飞书"):
                self.app.run(self.day, "print")
            printer.assert_not_called()
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(self.app.colors.request, [self.day]*3))
            self.app.colors.tick()
            send.assert_called_once()
            args = send.call_args.kwargs
            self.assertIn("银行卡", args["print_details"])
            self.assertIn("23.50", args["print_details"])
            self.assertNotIn("私密", str(args))
            self.assertEqual(args["choices"], {"ams-a2":"A2 · 棕色 PLA #6F5034"})
            self.app.colors.tick()
            self.app.run_due(now())
            send.assert_called_once()
            printer.assert_not_called()
            j = self.app.job(self.day)
            j["color_review"]["next_check"] = ""
            self.app.save(self.day,j)
            self.app = App(self.app.data)
            self.app.personal_chat = True
            self.app.colors.tick()
            with self.assertRaises(Problem):
                self.app.colors.confirm(self.day, "wrong", "ams-a2")
            with self.assertRaises(Problem):
                self.app.colors.confirm(self.day, args["code"], "ams-a4")
            self.app.colors.confirm(self.day, args["code"], "ams-a2")
            view = self.app.state(self.day)["job"]["color_review"]
            self.assertEqual(view["selected"]["source"], "ams-a2")
            self.assertFalse({"receipt","reply_id","code","device","slice_sha256"} & view.keys())
            self.app.mark_ready(self.day, True, "external")
            self.assertEqual(self.app.job(self.day)["source"],"ams-a2")
            self.app.run_due(now())
            self.app.worker.join(3)
            self.assertEqual(printer.call_count,1)
            self.assertEqual(printer.call_args.kwargs["expected_rgba"],"6F5034FF")
            self.assertEqual(self.app.job(self.day)["status"],"submitted")

    def test_empty_or_changed_slots_require_new_choice(self):
        report = ready_status()
        tray = report["ams"]["ams"][0]["tray"][1]
        tray["tray_color"] = BROWN["rgba"]
        self.assertEqual(_spool(report, "ams-a2"), BROWN)
        _check_spool(report,"ams-a2",BROWN["rgba"])
        tray["tray_color"] = "FFFFFFFF"
        with self.assertRaises(ColorChanged):
            _check_spool(report,"ams-a2",BROWN["rgba"])
        report["ams"]["tray_exist_bits"] = "0"
        with self.assertRaises(ColorChanged):
            _check_spool(report,"ams-a2",BROWN["rgba"])

    def test_no_reminder_for_running_job_or_unrequested_samples(self):
        j = self.app.job(self.day)
        self.app.save("sample", j)
        self.app.save(self.day, j | {"status":"submitted"})
        with patch("color_review.available_spools") as probe:
            self.app.colors.tick()
            probe.assert_not_called()
        with self.assertRaises(Problem):
            self.app.colors.request(self.day)
