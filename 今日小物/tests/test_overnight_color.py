"""A delivered Feishu notice remains usable for its original slice across midnight."""
from copy import deepcopy
from datetime import timedelta
from threading import RLock
import unittest
from unittest.mock import Mock, patch

from color_review import ColorReviews, approved, can_resume_color, can_retry_color, public_review
from feishu_print import FeishuError
from local_store import Problem, bed_is_ready_to_print, now


class OvernightColorTests(unittest.TestCase):
    def setUp(self):
        current = now().date()
        self.today = current.isoformat()
        self.key = (current - timedelta(days=1)).isoformat()
        self.enterContext(patch("color_review.printer_identity", return_value="device"))
        self.spool = {"source": "ams-a2", "rgba": "FF0000FF", "color": "#FF0000", "label": "红色"}
        self.code = "A1B2C3D4"
        self.job = {
            "status": "prepared",
            "print": {"artifact": "print.gcode.3mf", "slice_sha256": "a" * 64},
            "ready": True, "ready_date": self.key, "ready_device": "device", "ready_bed": "b" * 64,
            "color_review": {
                "status": "sent", "day": self.key, "device": "device", "slice_sha256": "a" * 64,
                "code": self.code, "channel": "private", "attempted_at": self.key + "T23:59:00+08:00",
                "receipt": {"mode": "one_way", "message_id": "om_example", "code": self.code, "identity": "owner"},
                "can_confirm": True, "options": [self.spool],
                "details": "测试切片",
            },
        }
        self.app = Mock(guard=RLock())
        self.app.job.side_effect = lambda key: self.job if key == self.key else None
        self.colors = ColorReviews(self.app)

    def test_resume_original_notice_without_resending_or_reusing_bed_clearance(self):
        self.assertTrue(can_resume_color(self.key, self.job))
        public = public_review(self.job, self.today, self.key)
        self.assertEqual(public["status"], "sent")
        self.assertNotIn("code", public)
        self.assertFalse(approved(self.job, self.today, self.key))
        self.colors.request(self.key)
        self.colors.tick()
        self.app.save.assert_not_called()
        with self.assertRaises(Problem):
            self.colors.confirm(self.key, "wrong", self.spool["source"])
        with self.assertRaises(Problem):
            self.colors.confirm(self.key, self.code, "ams-a1")
        self.colors.confirm(self.key, self.code, self.spool["source"])
        self.assertTrue(approved(self.job, self.today, self.key))
        self.assertFalse(bed_is_ready_to_print(self.job, self.today))

    def test_webhook_receipt_is_also_bound_to_the_original_code(self):
        review = self.job["color_review"]
        review.update(channel="webhook", receipt={"channel": "webhook", "mode": "one_way", "code": self.code, "identity": "owner"})
        self.assertTrue(can_resume_color(self.key, self.job))
        review["receipt"]["code"] = "DIFFERENT"
        self.assertFalse(can_resume_color(self.key, self.job))

    def test_receipt_from_a_send_started_before_midnight_is_saved(self):
        review = self.job["color_review"]
        receipt = review.pop("receipt")
        review.update(status="pending", can_confirm=False)
        self.assertFalse(self.colors.update(self.key, self.code, status="pending", attempted_at=self.today))
        self.assertFalse(self.colors.update(self.key, "different", status="sent", receipt=receipt))
        self.assertTrue(self.colors.update(self.key, self.code, status="sent", receipt=receipt, can_confirm=True))
        self.assertTrue(can_resume_color(self.key, self.job))

    def test_no_historical_approval_for_another_job_or_changed_slice(self):
        future = (now().date() + timedelta(days=2)).isoformat()
        for invalid_key in ("sample", self.today, future, "2026-02-31", None):
            with self.subTest(key=invalid_key):
                self.assertFalse(can_resume_color(invalid_key, self.job))
        changes = [
            ("color_review", {"receipt": {}}), ("color_review", {"receipt": {"message_id": "om_example"}}),
            ("color_review", {"status": "pending"}), ("color_review", {"day": self.today}),
            ("color_review", {"device": "other-device"}), ("print", {"slice_sha256": "d" * 64}),
            ("print", {"artifact": "another-file.3mf"}),
            (None, {"edit_token": "edited"}), (None, {"status": "submitted"}),
        ]
        for field, update in changes:
            with self.subTest(field=field, update=update):
                job = deepcopy(self.job)
                (job if field is None else job[field]).update(update)
                self.assertFalse(can_resume_color(self.key, job))
                with patch.object(self.app, "job", return_value=job), self.assertRaises(Problem):
                    self.colors.confirm(self.key, self.code, self.spool["source"])

    def rejected_notice(self):
        review = self.job["color_review"]
        receipt = review.pop("receipt")
        review.update(status="error", attempted_at=None, can_confirm=False,
                      message="飞书拒绝请求（99991672），请检查机器人的发送权限与个人可见范围。")
        self.enterContext(patch("color_review.feishu_print.configured", return_value=True))
        return receipt

    def test_historical_retry_is_explicit_once_and_reuses_original_notice(self):
        receipt = self.rejected_notice()
        self.assertTrue(can_retry_color(self.key, self.job))
        self.assertFalse(can_resume_color(self.key, self.job))
        send = self.enterContext(patch("color_review.feishu_print.notify_colors", return_value=receipt))
        self.colors.tick()
        send.assert_not_called()
        self.colors.request(self.key)
        self.colors.request(self.key)
        self.colors.tick()
        self.colors.tick()
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs["code"], self.code)
        self.assertEqual(send.call_args.kwargs["day"], self.key)
        self.assertTrue(can_resume_color(self.key, self.job))
        self.assertFalse(can_retry_color(self.key, self.job))

    def test_rejected_retry_stops_until_requested_unknown_result_cannot_retry(self):
        self.rejected_notice()
        send = self.enterContext(patch("color_review.feishu_print.notify_colors",
                                       side_effect=[FeishuError("飞书拒绝请求（99991672），未授权。"),
                                                    FeishuError("飞书未返回结果。", uncertain=True)]))
        self.colors.request(self.key)
        self.colors.tick()
        self.colors.tick()
        send.assert_called_once()
        self.assertTrue(can_retry_color(self.key, self.job))
        self.colors.request(self.key)
        self.colors.tick()
        self.assertEqual(send.call_count, 2)
        self.assertFalse(can_retry_color(self.key, self.job))
        with self.assertRaises(Problem):
            self.colors.request(self.key)

    def test_only_explicit_rejection_on_original_slice_can_be_retried(self):
        self.rejected_notice()
        for change in ({"delivery_uncertain": True}, {"channel": "other"}, {"attempted_at": self.today},
                       {"message": "无法确认机器人"}, {"options": []}, {"device": "changed"}, {"slice_sha256": "e" * 64}):
            job = deepcopy(self.job)
            job["color_review"].update(change)
            with self.subTest(change=change):
                self.assertFalse(can_retry_color(self.key, job))
