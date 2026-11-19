"""Resume the two authorized sculptures when the account balance is unavailable."""
import fcntl
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DAILY = ROOT.parent / "今日小物"
sys.path.insert(0, str(DAILY))
from local_store import credentials, read_json, save_json
from credit_usage import read_charges
from lux3d import DEFAULT_GATEWAY, GATEWAYS, generate_model

SCULPTURES = (
    ("flame-keeper", "捧火苗的小陶偶", "生日蜡烛",
     "单件象牙白树脂小雕像，蜷膝坐着的圆耳小熊双掌捧起一颗琥珀色烛火，火苗与前额之间留一道弯月形空隙，细密的陶刀刻纹沿短绒毛旋转。厚圆底，正面略侧，纯色背景，完整展示物件，无文字。"),
    ("pocket-stall", "口袋里的折叠摊", "校园摊位",
     "单件微缩折叠摊车，圆角木箱打开成桌面，弧形遮阳布有清楚的缝线，桌边小夹子夹住数张层叠的无字卡片，一只短脚凳收在车底。象牙白哑光树脂，浅琥珀把手，四分之三正面视图，纯色背景，无文字。"),
)

def main():
    ledger_path = DATA / "aholo_world.json"
    with (DATA / ".aholo-world.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ledger = read_json(ledger_path, {"items": [], "balance": None, "batch_limit": 2,
                                         "balance_note": "官方公开接口未提供余额，任务列表只返回扣款。"})
        def checkpoint():
            save_json(ledger_path, ledger)
        credentials(DAILY / "data")
        gateway = os.getenv("LUX3D_BASE_URL", DEFAULT_GATEWAY)
        if gateway not in GATEWAYS:
            raise ValueError("unknown gateway")
        for ident, title, stage, shape in SCULPTURES:
            job = next((item for item in ledger["items"] if item["id"] == ident), None)
            if job is None:
                if len(ledger["items"]) >= 2:
                    raise ValueError("batch full")
                job = {"id": ident, "title": title, "stage": stage}
                ledger["items"].append(job)
                checkpoint()
            if shutil.disk_usage(DATA).free < 15 * 1024**3:
                raise RuntimeError("可用磁盘低于 15 GiB")
            model = generate_model(shape, DATA / "aholo" / ident, job=job,
                                   checkpoint=checkpoint, concept_prompt=shape)
            job["model_path"] = str(model.relative_to(DATA))
            checkpoint()
            ids = {job["lux3d_concept_task_id"], job["lux3d_task_id"]}
            receipts = read_charges(gateway, os.environ["LUX3D_API_KEY"], ids)
            job["receipts"] = {str(k): v for k, v in receipts.items()}
            complete = all(len(item.get("receipts", {})) == 2 for item in ledger["items"])
            ledger["confirmed_credits"] = sum({k: v for i in ledger["items"] for k, v in i.get("receipts", {}).items()}.values())
            ledger["receipts_complete"] = complete
            checkpoint()
            if set(receipts) != ids or ledger["confirmed_credits"] + (32 if ident == SCULPTURES[0][0] else 0) > 200:
                raise RuntimeError("核对积分后再继续")
            print(ident, "ready", sum(receipts.values()), flush=True)

if __name__ == "__main__":
    main()
