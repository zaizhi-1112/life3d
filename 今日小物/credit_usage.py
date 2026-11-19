"""Reconcile local Aholo task IDs with the account's read-only usage records."""
import os
from threading import Lock, Thread
from time import monotonic
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from local_store import read_json, save_json
from lux3d import DEFAULT_GATEWAY, GATEWAYS, Lux3DError, _NoRedirect, _send, _task_id


# Published standard rates checked on 2026-11-18. Actuals always come from consumedCredits.
CONCEPT_RATE = 12
G1_RATE = 20
STAGES = (("lux3d_concept_task_id", "参考图", CONCEPT_RATE), ("lux3d_task_id", "G1 建模", G1_RATE))


def read_charges(gateway, api_key, wanted):
    if gateway not in GATEWAYS or not api_key or not wanted:
        return {}
    found = {}
    opener = build_opener(_NoRedirect())
    page = 1
    while True:
        query = urlencode({"page": page, "pagesize": 50})
        request = Request(gateway + "/lux3d/v1/generate/task/list?" + query, headers={"Authorization": api_key})
        reply = _send(opener, request, "查询积分明细")
        data = reply.get("d")
        if reply.get("c") != "0" or not isinstance(data, dict):
            break
        items = data.get("items")
        if not isinstance(items, list) or data.get("page") != page:
            break
        for row in items:
            if not isinstance(row, dict):
                continue
            task = row.get("taskId")
            amount = row.get("consumedCredits")
            if (_task_id(task) and task in wanted and row.get("status") in (3, 4, 6)
                    and type(amount) is int and amount >= 0):
                found[task] = amount
        size, total = data.get("pageSize"), data.get("total")
        if not items or wanted.issubset(found) or type(size) is not int or size < 1 or type(total) is not int or page * size >= total:
            break
        page += 1
    return found


def usage_report(job, receipts):
    """Stage totals are per version. A reused task ID is charged just once overall."""
    unknown = False
    seen = set()
    versions = []
    for index, version in enumerate([*job.get("prior_versions", []), job]):
        stages = []
        for field, label, rate in STAGES:
            task = version.get(field)
            pending = version.get("lux3d_concept_create_pending" if field == STAGES[0][0] else "lux3d_create_pending")
            if not _task_id(task) and not pending:
                continue
            amount = receipts.get(str(task)) if _task_id(task) else None
            if type(amount) is not int or amount < 0:
                amount = None
                unknown = True
            if _task_id(task):
                seen.add(task)
            stages.append({"label": label, "credits": amount})
        if stages:
            versions.append({"title": version.get("title") or "作品", "stages": stages,
                             "index": index, "current": version is job})
    verified = [receipts[str(i)] for i in seen if type(receipts.get(str(i))) is int and receipts[str(i)] >= 0]
    expected = STAGES[1:] if job.get("lux3d_external_concept") else STAGES
    estimate = sum(rate for _, _, rate in expected)
    return {"versions": versions, "confirmed": sum(verified) if verified else None,
            "complete": bool(versions) and not unknown, "estimate": estimate,
            "estimate_stages": [{"label": label, "credits": rate} for _, label, rate in expected]}


class CreditLedger:
    """Persist only matching terminal-task charges, independent of model job checkpoints."""
    def __init__(self, directory):
        self.path = directory / "aholo-usage.json"
        try:
            values = read_json(self.path, {})
        except (OSError, ValueError):
            values = {}
        self.receipts = values if isinstance(values, dict) else {}
        self.lock = Lock()
        self.busy = False
        self.next_lookup = {}

    def report(self, job):
        with self.lock:
            result = usage_report(job, self.receipts)
            gateway = os.environ.get("LUX3D_BASE_URL", DEFAULT_GATEWAY).rstrip("/")
            api_key = os.environ.get("LUX3D_API_KEY", "").strip()
            wanted = {v[field] for v in [*job.get("prior_versions", []), job]
                      for field, _, _ in STAGES if _task_id(v.get(field)) and str(v[field]) not in self.receipts
                      and self.next_lookup.get(v[field], 0) <= monotonic()
                      and v.get("lux3d_gateway", gateway) == gateway}
            if wanted and not self.busy and api_key and gateway in GATEWAYS:
                self.busy = True
                for task in wanted:
                    self.next_lookup[task] = monotonic() + 45
                Thread(target=self.refresh, args=(gateway, api_key, wanted), daemon=True).start()
            return result

    def refresh(self, gateway, api_key, wanted):
        try:
            found = read_charges(gateway, api_key, wanted)
            if found:
                with self.lock:
                    merged = {**self.receipts, **{str(k): v for k, v in found.items()}}
                    save_json(self.path, merged)
                    self.receipts = merged
                    for task in found:
                        self.next_lookup.pop(task, None)
        except (Lux3DError, OSError, ValueError):
            pass  # A later refresh resumes reconciliation without submitting more work.
        finally:
            with self.lock:
                self.busy = False
