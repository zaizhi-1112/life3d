"""Operate one world sculpture wave using the 今日小物 virtual environment.

From the world project, run "../今日小物/.venv/bin/python" -I -B
tools/aholo_world.py ACTION ID ... . Creation is checkpointed before HTTP.

concepts / models ID ... submit and collect one wave. approve ID ... records
a visual decision made after opening the concept files. receipts refreshes the
shared world ledger. models-batched ID ... resumes approved models in order,
stopping at each ten-piece receipt checkpoint before starting another wave.
"""
import argparse
from dataclasses import replace
from datetime import datetime
import fcntl
from hashlib import sha256
import json
import re
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DAILY = ROOT.parent / "今日小物"
sys.path[:0] = [str(DAILY), str(ROOT / "tools")]
from credit_usage import CONCEPT_RATE, G1_RATE, read_charges
import lux3d
from local_store import credentials, read_json, save_json
from world_shapes import BY_ID, HOUSES, REVISED_FORMS

LEDGER = DATA / "aholo_world.json"
LIMIT = 4000
STAGES = (("lux3d_concept_task_id", "lux3d_concept_create_pending", CONCEPT_RATE),
          ("lux3d_task_id", "lux3d_create_pending", G1_RATE))


def disk_check():
    if shutil.disk_usage(DATA).free < 15 * 1024**3:
        raise RuntimeError("可用磁盘低于 15 GiB，已停止。")


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Workshop:
    def __init__(self):
        self.book = read_json(LEDGER, {})
        if not self.book.get("items"):
            raise ValueError("首批账本缺失，不能确认历史扣款。")
        self.items = {item["id"]: item for item in self.book["items"]}
        for ident, item in self.items.items():
            if item.get("retry_of") and item["retry_of"] in BY_ID:
                shape = BY_ID[item["retry_of"]]
                BY_ID[ident] = replace(shape, shape=item["revised_shape"]) if item.get("revised_shape") else shape
        # Reconcile an interrupted Finder operation without repeating the move.
        for ident, item in self.items.items():
            if not item.pop("source_retirement_pending", False):
                continue
            source = DATA / "aholo" / ident / "model.glb"
            compact = DATA / "exhibits" / f"aholo-{ident}.glb"
            if source.exists():
                item["source_retirement_error"] = "Finder 移入废纸篓失败，保留原文件"
            elif lux3d._is_glb(compact):
                item["model_path"] = str(compact.relative_to(DATA))
                item["source_delivery"] = "减面输入已离开原目录，保留云任务号"
        self.book["budget"] = LIMIT
        self.book["checkpoint_interval"] = 10
        self.book.pop("batch_limit", None)
        credentials(DAILY / "data")
        self.gateway = os.getenv("LUX3D_BASE_URL", lux3d.DEFAULT_GATEWAY).rstrip("/")
        if self.gateway not in lux3d.GATEWAYS:
            raise ValueError("需要官方 Aholo 网关。")
        self.key = os.environ["LUX3D_API_KEY"]
        self.opener = build_opener(lux3d._NoRedirect())

    def save(self):
        receipts = {k: v for item in self.items.values() for k, v in item.get("receipts", {}).items()}
        ids = {str(item[field]) for item in self.items.values() for field, _, _ in STAGES if item.get(field)}
        self.book["confirmed_credits"] = sum(receipts.values())
        self.book["receipts_complete"] = set(receipts) == ids and not any(
            item.get(pending) for item in self.items.values() for _, pending, _ in STAGES)
        self.book["house_allocation"] = self.house_allocation()
        save_json(LEDGER, self.book)

    def house_allocation(self):
        allocation = {"authorized": len(HOUSES) * (CONCEPT_RATE + G1_RATE),
                      "confirmed": 0, "in_flight_estimate": 0, "reserved_unsubmitted": 0}
        for ident in HOUSES:
            house = self.items.get(ident, {})
            for field, pending, cost in STAGES:
                task = str(house.get(field))
                paid = house.get("receipts", {}).get(task)
                if paid is not None:
                    allocation["confirmed"] += paid
                elif house.get(field) or house.get(pending):
                    allocation["in_flight_estimate"] += cost
                else:
                    allocation["reserved_unsubmitted"] += cost
        return allocation

    def reconcile(self):
        ids = {item[field] for item in self.items.values() for field, _, _ in STAGES if item.get(field)}
        receipts = read_charges(self.gateway, self.key, ids)
        for item in self.items.values():
            for field, _, _ in STAGES:
                task_id = item.get(field)
                if task_id in receipts:
                    item.setdefault("receipts", {})[str(task_id)] = receipts[task_id]
        self.save()
        count = sum(bool(i.get("compact_path", i.get("model_path"))) for i in self.items.values())
        print("已确认积分", self.book["confirmed_credits"], "模型数", count, "回执齐", self.book["receipts_complete"], flush=True)
        if count and count % 10 == 0 and self.book["receipts_complete"] and ids == set(receipts):
            snapshots = self.book.setdefault("receipt_checkpoints", [])
            if not any(s["models"] == count for s in snapshots):
                snapshots.append({"at": now(), "models": count, "confirmed_credits": self.book["confirmed_credits"], "tasks": len(receipts)})
                self.save()
        for flag, key in (("replaces", "color_receipt_checkpoints"), ("color_edition", "all_color_receipt_checkpoints")):
            colored = sum(bool(i.get(flag) and i.get("model_path")) for i in self.items.values())
            if colored and colored % 10 == 0 and self.book["receipts_complete"] and ids == set(receipts):
                checkpoints = self.book.setdefault(key, [])
                if not any(r["models"] == colored for r in checkpoints):
                    checkpoints.append({"at": now(), "models": colored, "confirmed_credits": self.book["confirmed_credits"], "tasks": len(ids)})
                    self.save()
        return self.book["receipts_complete"]

    def history(self, task=None):
        page = 1
        while True:
            req = Request(self.gateway + f"/lux3d/v1/generate/task/list?page={page}&pagesize=50",
                          headers={"Authorization": self.key})
            d = lux3d._send(self.opener, req, "查询任务历史").get("d", {})
            rows = [{k: row[k] for k in ("taskId", "taskType", "status", "created", "consumedCredits") if k in row}
                    for row in d.get("items", [])]
            if task is None:
                return rows
            found = [row for row in rows if row.get("taskId") == task]
            if found or not rows or page * 50 >= d.get("total", 0):
                return found
            page += 1

    def check_unknown(self):
        for item in self.items.values():
            if any(item.get(pending) and not item.get(field) for field, pending, _ in STAGES):
                item["history_after_uncertain_create"] = {"at": now(), "recent": self.history()[:12]}
                self.save()
                raise RuntimeError(f"{item['id']} 的创建结果不明，已保存历史供核对，未重新提交。")

    def add(self, ident):
        if ident not in self.items:
            shape = BY_ID[ident]
            item = {"id": ident, "title": shape.title, "stage": {"era":"阶段场景","coast":"海边","gallery":"展台","moment":"路边小物","entrance":"入口","home":"人物房屋"}[shape.zone],
                    "description": shape.description, "placement": shape.placement, "receipts": {}}
            if ident in HOUSES:
                item["color_edition"] = True
            if ident.endswith("-paint"):
                original = self.items[ident.removesuffix("-paint")]
                if original.get("withdrawn") or not original.get("model_path"):
                    raise ValueError("只替换当前保留的原件。")
                item.update(replaces=original["id"], color_edition=True,
                            title=original["title"], stage=original["stage"],
                            placement=original.get("placement", shape.placement),
                            description=original.get("description", shape.description))
            self.items[ident] = item
            self.book["items"].append(item)
            self.save()
        return self.items[ident]

    def check_budget(self, rate, ident):
        committed = self.book["confirmed_credits"]
        for item in self.items.values():
            for field, pending, cost in STAGES:
                task = item.get(field)
                if (task and str(task) not in item.get("receipts", {})) or item.get(pending):
                    committed += cost
        reserve = self.house_allocation()["reserved_unsubmitted"] if ident not in HOUSES else 0
        if committed + reserve + rate > LIMIT:
            raise RuntimeError(f"本件加上房屋待用 {reserve} 积分将超过 4000，已停止。")

    def concept_path(self, item):
        name = item.get("lux3d_concept_filename")
        if name in ("concept.png", "concept.jpg"):
            return DATA / "aholo" / item["id"] / name

    def approve(self, ident):
        item = self.items[ident]
        path = self.concept_path(item)
        if item.get("withdrawn"):
            raise ValueError("这张概念已撤下，请使用另一个版本的编号。")
        if not path or not lux3d._concept_format(path):
            raise ValueError(f"{ident} 概念图尚未下载")
        if not item.get("color_edition"):
            item["description"] = BY_ID[ident].description
        item["concept_review"] = {"decision": "保留", "at": now(), "sha256": sha256(path.read_bytes()).hexdigest()}
        self.save()

    def record_display_review(self, ident):
        item = self.items[ident]
        if not re.fullmatch(r"[a-z0-9-]+", ident):
            raise ValueError("展品编号无效")
        screenshot = ROOT / ("docs/截图/整改对比/精雕" if item.get("color_edition") else "docs/截图/精雕") / (ident + ".png")
        with screenshot.open("rb") as file:
            if file.read(8) != b"\x89PNG\r\n\x1a\n":
                raise ValueError("需要实景 PNG 截图。")
        expected = {str(item[field]) for field, _, _ in STAGES if item.get(field)}
        if len(expected) != 2 or expected != set(item.get("receipts", {})):
            raise ValueError("请先核实这件作品的两笔扣款。")
        compact = DATA / "exhibits" / f"aholo-{ident}.glb"
        if not lux3d._is_glb(compact) or compact.stat().st_size > 2_000_000:
            raise ValueError("精简版无效，保留原始文件。")
        item["world_review"] = {"decision": "保留", "at": now(),
                                "screenshot": str(screenshot.relative_to(ROOT))}
        self.save()
        # Colored originals include the full-resolution paint for future editions.
        if item.get("color_edition") or ident not in BY_ID or item.get("source_retirement_error"):
            return
        source = DATA / "aholo" / ident / "model.glb"
        if source.exists():
            item["source_retirement_pending"] = True
            self.save()
            applescript = ('on run argv\n'
                           'set targetFile to POSIX file (item 1 of argv) as alias\n'
                           'tell application "Finder" to delete targetFile\n'
                           'end run')
            moved = subprocess.run(["osascript", "-e", applescript, str(source)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if moved.returncode or source.exists():
                item["source_retirement_error"] = "Finder 移入废纸篓失败，保留原文件"
                item.pop("source_retirement_pending", None)
                self.save()
                print(f"{ident}：移入废纸篓失败，已保留原文件记录。", flush=True)
                return
        if item.pop("source_retirement_pending", False):
            item["model_path"] = str(compact.relative_to(DATA))
            item["source_delivery"] = "本轮下载的减面输入已移至废纸篓，云任务号保留"
            self.save()

    def try_create(self, item, is_model):
        field, _, cost = STAGES[int(is_model)]
        if item.get(field):
            return True
        disk_check()
        self.check_unknown()
        self.check_budget(cost, item["id"])
        shape = BY_ID[item["id"]]
        payload, endpoint = {"prompt": shape.prompt}, "multimodal-to-image"
        if not is_model:
            item["shape_prompt"] = shape.prompt
        if is_model:
            path = self.concept_path(item)
            review = item.get("concept_review", {})
            if not path or review.get("decision") != "保留" or review.get("sha256") != sha256(path.read_bytes()).hexdigest():
                raise ValueError("先检查并认可这张概念图。")
            url = lux3d._poll(self.opener, self.gateway, self.key, item["lux3d_concept_task_id"], index=0, artifact="概念图")
            payload, endpoint = {"img": url, **lux3d.G1_OPTIONS}, "img-to-3d"
        try:
            task = lux3d._create(self.opener, self.gateway, self.key, endpoint, payload, item, self.save)
        except lux3d.Lux3DError as error:
            if "并发任务已满" in str(error):
                return False
            self.check_unknown()
            raise
        print("已接单", item["id"], task, flush=True)
        return True

    def ready(self, item, is_model):
        if is_model:
            return bool(item.get("compact_path") and (DATA / item["compact_path"]).is_file())
        path = self.concept_path(item)
        return bool(path and path.is_file())

    def record_failed_task(self, item, task, replacement=None):
        history = next(iter(self.history(task)), {})
        if history.get("status") not in (4, 6):
            raise ValueError("任务历史未确认失败，保留任务号。")
        if type(history.get("consumedCredits")) is not int:
            if not item.get("cloud_failure", {}).get("receipt_pending"):
                item["cloud_failure"] = {**history, "checked": now(), "receipt_pending": True}
                self.save()
                print("失败任务等待最终扣款", item["id"], task, flush=True)
            return False
        self.reconcile()
        if item.get("receipts", {}).get(str(task)) != history["consumedCredits"]:
            raise ValueError("未核对到该失败任务的正式扣款。")
        item["cloud_failure"] = {**history, "checked": now(), "replacement": replacement}
        item["withdrawn"] = True
        self.save()
        print("失败已核对", item["id"], task, "扣款", history["consumedCredits"], flush=True)
        return True

    def expected_finish(self):
        """Hold enough for already approved pieces before buying another reference."""
        amount = self.book["confirmed_credits"]
        unbilled = {}
        groups = {}
        for i in self.items.values():
            for field, pending, cost in STAGES:
                task = i.get(field)
                if task and str(task) not in i.get("receipts", {}):
                    unbilled[task] = cost
                elif not task and i.get(pending):
                    unbilled[(i["id"], field)] = cost
            if i.get("color_edition"):
                groups.setdefault(i.get("replaces", i["id"]), []).append(i)
        amount += sum(unbilled.values())
        for versions in groups.values():
            if any(i.get("model_path") for i in versions):
                continue
            live = [i for i in versions if not i.get("withdrawn")]
            if not any(i.get("lux3d_task_id") or i.get("lux3d_create_pending") for i in live):
                amount += G1_RATE
            if live and not any(i.get("lux3d_concept_task_id") or i.get("lux3d_concept_create_pending") for i in live):
                amount += CONCEPT_RATE
        return amount

    def retry_model(self, ident, new_concept=False):
        old = self.items[ident]
        if old.get("retried_by"):
            return old["retried_by"]
        if not old.get("color_edition") or not old.get("replaces") or old.get("model_path"):
            raise ValueError("只能给正式失败且未交付的彩色模型创建续版。")
        task = old.get("lux3d_task_id")
        if not task or not self.record_failed_task(old, task):
            raise ValueError("等待失败任务的正式扣款后再续版。")
        if new_concept and old["replaces"] not in REVISED_FORMS:
            raise ValueError("尚无经过准备的替代造型。")
        if self.expected_finish() + (CONCEPT_RATE if new_concept else 0) > LIMIT:
            raise ValueError("预留所有已通过造型的后续费用后，本次续版将超预算。")
        path = self.concept_path(old)
        review = old.get("concept_review", {})
        if not path or review.get("decision") != "保留" or sha256(path.read_bytes()).hexdigest() != review.get("sha256"):
            raise ValueError("复用的概念图未通过原审签。")
        basis = re.sub(r"-r\d+$", "", ident)
        edition = int(old.get("model_edition", 1)) + 1
        new_id = f"{basis}-r{edition}"
        if new_id in self.items:
            raise ValueError("续版编号已被使用，请核查历史。")
        self.check_budget(G1_RATE, new_id)
        inherited = ("title","description","stage","placement","replaces","color_edition")
        fresh = {key: old[key] for key in inherited if key in old}
        fresh.update(id=new_id, retry_of=ident, model_edition=edition, receipts={})
        BY_ID[new_id] = BY_ID[ident]
        if new_concept:
            fresh["revised_shape"] = REVISED_FORMS[old["replaces"]]
            BY_ID[new_id] = replace(BY_ID[ident], shape=fresh["revised_shape"])
        else:
            target = path.parent.parent / new_id / path.name
            target.parent.mkdir(exist_ok=True)
            if target.exists() and sha256(target.read_bytes()).hexdigest() != review["sha256"]:
                raise ValueError("续版目录已存在另一张概念。")
            if not target.exists():
                partial = target.with_suffix(".copying")
                shutil.copyfile(path, partial)
                partial.replace(target)
            concept_task = old["lux3d_concept_task_id"]
            for key in ("shape_prompt","concept_review","lux3d_concept_task_id","lux3d_concept_filename","lux3d_gateway"):
                if key in old:
                    fresh[key] = old[key]
            fresh["receipts"] = {str(concept_task): old["receipts"][str(concept_task)]}
        old["retried_by"] = new_id
        old["cloud_failure"]["replacement"] = new_id
        self.book["items"].append(fresh)
        self.items[new_id] = fresh
        self.save()
        print("重新出概念" if new_concept else "复用原概念", "续版", new_id, flush=True)
        return new_id

    def collect(self, item, is_model):
        folder = DATA / "aholo" / item["id"]
        folder.mkdir(parents=True, exist_ok=True)
        field, _, _ = STAGES[int(is_model)]
        task = item[field]
        req = Request(self.gateway + f"/lux3d/v1/generate/task/get?taskid={task}", headers={"Authorization":self.key})
        rep = lux3d._send(self.opener, req, "查询任务").get("d", {})
        if rep.get("taskId") == task and rep.get("status") in (4, 6):
            self.record_failed_task(item, task)
            return
        if rep.get("taskId") != task or rep.get("status") not in (0, 1, 3):
            self.reconcile()
            raise RuntimeError(f"任务 {task} 状态 {rep.get('status')}，保留任务号。")
        if rep["status"] != 3:
            return
        disk_check()
        if is_model:
            # Recorded task ID makes generate_model read-only at the gateway.
            model = lux3d.generate_model("", folder, job=item, checkpoint=self.save)
            destination = DATA / "exhibits" / ("aholo-" + item["id"] + ".glb")
            with (DATA / ".compact.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                disk_check()
                partial = destination.with_name(destination.stem + ".partial.glb")
                with (folder / "compact.log").open("w") as log:
                    subprocess.run(["/Applications/Blender.app/Contents/MacOS/Blender", "-b", "-t", "2", "--python-exit-code", "1", "-P",
                                    str(ROOT / "tools/blender/compact_exhibit.py"), "--", str(model), str(partial), *(["--color"] if item.get("color_edition") else [])], stdout=log, stderr=log, check=True)
                if not lux3d._is_glb(partial) or partial.stat().st_size > 2_000_000:
                    raise ValueError("减面结果超预算或无效，未展出")
                if item.get("color_edition"):
                    with partial.open("rb") as handle:
                        handle.seek(12)
                        length = int.from_bytes(handle.read(4), "little")
                        handle.read(4)
                        gltf = json.loads(handle.read(length))
                    if not any("baseColorTexture" in m.get("pbrMetallicRoughness", {}) for m in gltf.get("materials", [])):
                        raise ValueError("彩色展示版缺少基础颜色贴图，保留原件展示。")
                partial.replace(destination)
            if item.get("replaces"):
                self.items[item["replaces"]]["replaced_by"] = item["id"]
            item["compact_path"] = str(destination.relative_to(DATA))
            item["model_path"] = str(model.relative_to(DATA))
        else:
            lux3d._concept_url(self.opener, self.gateway, self.key, "", folder, item, self.save)
        self.save()
        print("就绪", "模型" if is_model else "概念", item["id"], flush=True)

    def model_batch(self, candidates):
        """Stop before the next ledger checkpoint in each applicable count."""
        limits = (
            (None, "receipt_checkpoints"),
            ("color_edition", "all_color_receipt_checkpoints"),
            ("replaces", "color_receipt_checkpoints"),
        )
        counts = [sum(bool(i.get("model_path") and (not flag or i.get(flag)))
                      for i in self.items.values()) for flag, _ in limits]
        for (flag, key), count in zip(limits, counts):
            if count and count % 10 == 0 and not any(r["models"] == count for r in self.book.get(key, [])):
                raise ValueError(f"请先核对 {key} 第 {count} 件的回执。")
        accepted = []
        for item in candidates:
            accepted.append(item)
            reached = False
            for index, (flag, _) in enumerate(limits):
                if not flag or item.get(flag):
                    counts[index] += 1
                    reached |= counts[index] % 10 == 0
            if reached:
                break
        return accepted

    def approved_batches(self, ids):
        self.check_unknown()
        self.reconcile()
        ordered = [self.items[ident] for ident in dict.fromkeys(ids)]
        if not all(item.get("concept_review", {}).get("decision") == "保留" for item in ordered):
            raise ValueError("只可为已逐图审核通过的概念连续建模。")
        while pending := [i for i in ordered if not i.get("withdrawn") and not self.ready(i, True)]:
            batch = self.model_batch(pending)
            self.wave([i["id"] for i in batch], True)

    def wave(self, ids, is_model, queue_only=False):
        self.check_unknown()
        self.reconcile()
        if set(ids) - BY_ID.keys():
            raise ValueError("未登记的造型")
        items = [self.add(ident) for ident in dict.fromkeys(ids)]
        if any(i.get("withdrawn") for i in items):
            raise ValueError("概念已撤下，不能继续创建。")
        if is_model:
            in_cloud = [i for i in self.items.values() if i.get("lux3d_task_id") and
                        not i.get("model_path") and not i.get("withdrawn")]
            pending = {i["id"]: i for i in [*in_cloud, *items] if not i.get("model_path")}
            if len(self.model_batch(pending.values())) != len(pending):
                raise ValueError("本批连同云端在制件会跨过十件核账节点，先完成当前一批。")
        full_at = None
        while True:
            disk_check()
            pending = [i for i in items if not i.get("withdrawn") and not self.ready(i, is_model)]
            if not pending:
                break
            field = STAGES[int(is_model)][0]
            available = None
            if full_at is not None:
                active = sum(row.get("status") in (0, 1) for row in self.history())
                available = max(0, full_at - active)
            for item in pending:
                if item.get(field):
                    continue
                if available == 0:
                    break
                if not self.try_create(item, is_model):
                    # A known rejection has no task ID. Wait for a cloud slot
                    # to free before asking the API to accept another item.
                    active = sum(row.get("status") in (0, 1) for row in self.history())
                    full_at = max(1, active)
                    break
                if available is not None:
                    available -= 1
            if queue_only:
                return
            for item in pending:
                if item.get(field):
                    self.collect(item, is_model)
            if not all(i.get("withdrawn") or self.ready(i, is_model) for i in items):
                time.sleep(12)
        self.reconcile()
        if any(str(i[field]) not in i.get("receipts", {}) for i in items for field, _, _ in STAGES
               if i.get(field) and (is_model or field == STAGES[0][0])):
            raise RuntimeError("本批已有任务尚缺最终回执，核对后再继续。")


def print_status():
    book = read_json(LEDGER, {})
    items = {item["id"]: item for item in book.get("items", [])}
    groups = {}
    for ident in dict.fromkeys([*items, *BY_ID]):
        item = items.get(ident, {})
        if item.get("withdrawn"):
            label = "已撤下"
        elif any(item.get(pending) and not item.get(field) for field, pending, _ in STAGES):
            label = "创建结果待查历史"
        elif item.get("world_review"):
            label = "实景已核"
        elif item.get("model_path"):
            label = "待实景复核"
        elif item.get("lux3d_task_id"):
            label = "模型已有任务号"
        elif item.get("concept_review", {}).get("decision") == "保留":
            label = "概念已核可建模"
        elif item.get("lux3d_concept_filename"):
            label = "待看概念图"
        elif item.get("lux3d_concept_task_id"):
            label = "概念已有任务号"
        else:
            label = "尚未创建"
        groups.setdefault(label, []).append(ident)
    print("官方回执累计", book.get("confirmed_credits"), "/", LIMIT)
    for label, ids in groups.items():
        print(label, len(ids), " ".join(ids))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "concepts", "approve", "models", "models-batched", "queue-models", "retry-model", "layout", "reject-concept", "withdraw-failed", "reviewed", "receipts", "history"])
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--reason", default="")
    parser.add_argument("--new-concept", action="store_true", help="已确认原图反复失败时，另付一张已登记的新造型概念。")
    parser.add_argument("--replacement", choices=BY_ID.keys())
    args = parser.parse_args()
    if args.action == "status":
        print_status()
        return
    if args.action != "history":
        disk_check()
    with (DATA / ".aholo-world.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        workshop = Workshop()
        if args.action == "approve":
            for ident in args.ids:
                workshop.approve(ident)
        elif args.action == "reviewed":
            for ident in args.ids:
                workshop.record_display_review(ident)
        elif args.action == "withdraw-failed":
            if len(args.ids) != 1 or not args.replacement:
                parser.error("需明确撤下的一件及替代编号。")
            item = workshop.items[args.ids[0]]
            task = item.get("lux3d_task_id") or item.get("lux3d_concept_task_id")
            workshop.record_failed_task(item, task, args.replacement)
        elif args.action == "reject-concept":
            if len(args.ids) != 1 or not args.reason.strip():
                parser.error("撤下概念需一件编号和 --reason")
            item = workshop.items[args.ids[0]]
            if not workshop.concept_path(item) or item.get("lux3d_task_id"):
                raise ValueError("仅可撤下看过且未建模的概念图。")
            item["concept_review"] = {"decision": "撤下", "reason": args.reason, "at": now(),
                                      "replacement": args.replacement}
            item["withdrawn"] = True
            workshop.save()
        elif args.action == "layout":
            for ident in args.ids:
                shape = BY_ID[ident]
                item = workshop.items[ident]
                item["placement"] = {**item.get("placement", {}), **shape.placement}
                item["title"] = shape.title
                item["description"] = shape.description
            workshop.save()
        elif args.action == "history":
            print(json.dumps(workshop.history(), ensure_ascii=False))
        elif args.action == "receipts":
            workshop.reconcile()
        elif args.action == "models-batched":
            workshop.approved_batches(args.ids)
        elif args.action == "retry-model":
            for ident in args.ids:
                workshop.retry_model(ident, args.new_concept)
        else:
            workshop.wave(args.ids, args.action in {"models", "queue-models"}, args.action == "queue-models")


if __name__ == "__main__":
    main()
