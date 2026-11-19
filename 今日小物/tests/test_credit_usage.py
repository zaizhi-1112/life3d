import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from credit_usage import CreditLedger, read_charges, usage_report
from local_store import public_job
from lux3d import DEFAULT_GATEWAY


class AholoCreditTests(unittest.TestCase):
    def test_bill_distinguishes_unknown_pending_and_zero(self):
        job = {"status": "failed", "lux3d_concept_task_id": 8, "lux3d_create_pending": True}
        bill = usage_report(job, {"8": 0})
        self.assertEqual(bill["confirmed"], 0)
        self.assertFalse(bill["complete"])
        self.assertIsNone(bill["versions"][0]["stages"][1]["credits"])
        self.assertIsNone(usage_report(job, {})["confirmed"])

    def test_same_task_id_in_two_variants_is_counted_once(self):
        job = {"status": "prepared", "title": "第二版", "lux3d_concept_task_id": 8, "lux3d_task_id": 12,
               "prior_versions": [{"title": "第一版", "lux3d_concept_task_id": 8, "lux3d_task_id": 9}]}
        bill = usage_report(job, {"8": 12, "9": 20, "12": 20})
        self.assertEqual(bill["confirmed"], 52)
        self.assertTrue(bill["complete"])
        self.assertEqual([v["title"] for v in bill["versions"]], ["第一版", "第二版"])
        self.assertNotIn("prior_versions", public_job(job, "2026-11-18"))
        self.assertNotIn("lux3d_", json.dumps(bill))

    def test_reads_other_pages_and_only_caches_matching_final_tasks(self):
        page1 = {"c": "0", "d": {"page": 1, "total": 5, "pageSize": 3, "items": [
            {"taskId": 100, "consumedCredits": 450, "status": 3},
            {"taskId": 101, "consumedCredits": 0, "status": 1},
            {"taskId": 102, "consumedCredits": None, "status": 3}]}}
        page2 = {"c": "0", "d": {"page": 2, "total": 5, "pageSize": 3, "items": [
            {"taskId": 103, "consumedCredits": 20, "status": 3},
            {"taskId": 104, "consumedCredits": 0, "status": 4}]}}
        with TemporaryDirectory() as tmp:
            path = Path(tmp)
            with patch("credit_usage._send", side_effect=[page1, page2]) as http:
                ledger = CreditLedger(path)
                ledger.refresh(DEFAULT_GATEWAY, "offline", {101, 102, 103, 104})
            self.assertEqual(CreditLedger(path).receipts, {"103": 20, "104": 0})
            self.assertIn("pagesize=50", http.call_args_list[0].args[1].full_url)
            self.assertIn("page=2", http.call_args_list[1].args[1].full_url)
            self.assertEqual(read_charges("https://example.invalid", "offline", {103}), {})
