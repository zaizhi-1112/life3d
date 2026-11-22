"""Loopback-only gallery. The world process never performs workbench actions."""
from __future__ import annotations

import fcntl
import re
import json
import mimetypes
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Lock, RLock, Thread
from time import monotonic
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))
import build_world_data as data

WEB = ROOT / "web"
WORKBENCH = ROOT.parent / "今日小物"
WORKBENCH_PORT = int(os.environ.get("WORKBENCH_PORT", "17868"))
# 演示快照：存在时直接展示这份已脱敏的世界数据，不读取任何私人汇总。
# 指定 BIRTHDAY_WORLD_DATA 时改为从数据目录实时生成。
SNAPSHOT = None if "BIRTHDAY_WORLD_DATA" in os.environ else ROOT / "demo/world.json"
BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("model/gltf-binary", ".glb")
mimetypes.add_type("model/stl", ".stl")


class EditConflict(Exception):
    def __init__(self, card):
        self.card = card


class Gallery:
    def __init__(self):
        self.guard = RLock()
        self.stamp = self.world = None
        self.compacting = set()
        self.retry_after = {}

    def read(self):
        with self.guard:
            if SNAPSHOT and SNAPSHOT.is_file():
                if self.world is None:
                    self.world = json.loads(SNAPSHOT.read_text("utf-8"))
                    for group in ("exhibits", "sculptures", "houses"):
                        for row in self.world[group]:
                            for field in ("model", "photo_file"):
                                if row.get(field):
                                    row[field] = str(ROOT / row[field])
                    data.put_cards(self.world, data.load(data.EDITS, {}))
                return self.world
            stamp = data.source_stamp()
            if stamp != self.stamp:
                self.world = data.build()
                self.stamp = stamp
            for item in self.world["exhibits"]:
                ident = item["id"]
                if (item["model"] == item["original"] and ident not in self.compacting
                        and monotonic() >= self.retry_after.get(ident, 0)):
                    self.compacting.add(ident)
                    Thread(target=self.reduce, args=(ident, Path(item["original"])), daemon=True).start()
            return self.world

    def reduce(self, ident, source):
        target = data.COMPACT / (ident + ".glb")
        draft = target.with_name("." + ident + ".part.glb")
        try:
            data.COMPACT.mkdir(parents=True, exist_ok=True)
            with (ROOT / "data/.compact.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if data.fresh_compact(source, target):
                    return
                if shutil.disk_usage(data.DATA).free < 15 * 1024**3:
                    raise OSError("磁盘不足 15 GiB，已暂停减面")
                before = data.model_revision(source)
                subprocess.run([BLENDER, "-b", "-t", "2", "--python-exit-code", "1", "-P",
                                str(ROOT/"tools/blender/compact_exhibit.py"), "--", str(source), str(draft)],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=300, check=True)
                if not 32 < draft.stat().st_size <= 2_000_000 or before != data.model_revision(source):
                    raise ValueError("模型在减面期间有更新或大小超限")
                draft.replace(target)
                data.save(target.with_suffix(".source.json"), data.compact_record(source, target))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            print(f"展品 {ident} 暂时使用原模型：{exc}", file=sys.stderr, flush=True)
            with self.guard:
                self.retry_after[ident] = monotonic() + 180
        finally:
            with self.guard:
                self.compacting.discard(ident)

    def edit(self, request):
        with self.guard:
            key = request.get("id")
            world = self.read()
            if not isinstance(key, str) or key not in world["cards"]:
                raise ValueError("这张卡片已变化，请刷新后再试。")
            edits = data.load(data.EDITS, {})
            fields = request.get("fields")
            if request.get("reset") is True and set(request) == {"id", "reset"}:
                edits.pop(key, None)
            elif set(request) in ({"id", "fields"}, {"id", "fields", "expected"}) and isinstance(fields, dict) and fields:
                limits = {"title": 240, "kicker": 240, "text": 8000, "aside": 4000}
                if any(k not in limits or not isinstance(v, str) or len(v) > limits[k] for k, v in fields.items()):
                    raise ValueError("请缩短文字，再保存。")
                if "title" in fields and not fields["title"].strip():
                    raise ValueError("请给这张卡片留一个标题。")
                updated = {k: v.strip() for k, v in fields.items()}
                if "expected" in request:
                    expected = request["expected"]
                    if (not isinstance(expected, dict) or expected.keys() != fields.keys()
                            or not all(isinstance(v, str) for v in expected.values())):
                        raise ValueError("卡片修改格式不正确。")
                    current = world["cards"][key]
                    if any(current[k] not in (expected[k], updated[k]) for k in fields):
                        raise EditConflict(current)
                edits[key] = edits.get(key, {}) | updated
            else:
                raise ValueError("卡片修改格式不正确。")
            data.save(data.EDITS, edits)
            data.put_cards(world, edits)
            return {"card": world["cards"][key]}


LAYOUT_LIMITS = {"x": 59.0, "scale": (0.6, 1.6), "yaw": 360.0}
# 非 Aholo 模型：展台长椅（固定编号）和从资产面板放上岛的 Blender 装饰。
DECOR = {"tree_round", "tree_autumn", "tree_pine", "rock_a", "flowers", "grass", "lantern", "bench", "fence", "boat", "cottage_small"}
PROP_ID = re.compile(r"prop-bench-[0-3]")
DECO_ID = re.compile(r"deco-([a-z_]+)-[a-z0-9]{4,12}")


def read_layout():
    layout = data.load(data.LAYOUT, None)
    if layout is None:
        layout = data.load(ROOT / "demo/layout.json", {"items": {}}) if SNAPSHOT else {"items": {}}
    return layout if isinstance(layout, dict) and isinstance(layout.get("items"), dict) else {"items": {}}


def save_layout(request):
    """只接受当前登记的展品，坐标须在岛内。整份替换。"""
    items = request.get("items") if isinstance(request, dict) and set(request) == {"items"} else None
    if not isinstance(items, dict) or len(items) > 600:
        raise ValueError("摆放格式不正确，请刷新后再试。")
    with gallery.guard:
        world = gallery.read()
        known = {r["id"] for group in ("exhibits", "sculptures") for r in world[group]}
    previous = read_layout()["items"]
    clean = {key: value for key, value in previous.items()
             if key not in known and not PROP_ID.fullmatch(key) and not DECO_ID.fullmatch(key)}  # 已撤下展品的摆放原样保留
    for key, entry in items.items():
        deco = DECO_ID.fullmatch(key) if isinstance(key, str) else None
        allowed = {"x", "z", "yaw", "scale", "hidden"} | ({"asset"} if deco else set())
        if (key not in known and not PROP_ID.fullmatch(key) and not deco) or not isinstance(entry, dict) or not set(entry) <= allowed:
            raise ValueError("有一件展品已变化，请刷新后再试。")
        row = {}
        if deco:
            if entry.get("asset") != deco.group(1) or deco.group(1) not in DECOR or "x" not in entry:
                raise ValueError("这件装饰的格式不正确，请刷新后再试。")
            row["asset"] = entry["asset"]
        for field in ("x", "z", "yaw", "scale"):
            if field in entry:
                value = entry[field]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or abs(value) == float("inf"):
                    raise ValueError("摆放数值不正确。")
                row[field] = round(float(value), 3)
        if ("x" in row) != ("z" in row) or ("x" in row and (row["x"] ** 2 + row["z"] ** 2) ** .5 > LAYOUT_LIMITS["x"]):
            raise ValueError("请把展品放在岛上。")
        if "scale" in row and not LAYOUT_LIMITS["scale"][0] <= row["scale"] <= LAYOUT_LIMITS["scale"][1]:
            raise ValueError("大小超出范围。")
        if "yaw" in row and abs(row["yaw"]) > LAYOUT_LIMITS["yaw"]:
            raise ValueError("朝向超出范围。")
        if "hidden" in entry:
            if not isinstance(entry["hidden"], bool):
                raise ValueError("摆放格式不正确。")
            if entry["hidden"]:
                row["hidden"] = True
        if row:
            clean[key] = row
    saved = {"items": clean}
    with (data.DATA / ".layout.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data.save(data.LAYOUT, saved)
    return saved


PALACE_SCENES = ("room", "garden")
# 宫殿家具：默认家具编号（f-bookcase-a）和用户新添的家具（f-<类型>-<随机>，需带 type）。
FURNITURE_TYPES = {"bookcase", "wallshelf", "desk", "vitrine", "cabinet", "printer", "sofa", "armchair", "coffee", "rug",
                   "floorlamp", "plant", "pedestal", "sidetable", "gplinth", "pergola", "bench", "lantern", "tree", "flowerbed", "arch"}
FURNITURE_ID = re.compile(r"f-[a-z0-9-]{2,40}")


def read_palace():
    palace = data.load(data.DATA / "palace.json", None)
    if not isinstance(palace, dict):
        return {"scene": "auto", "rooms": {}}
    rooms = palace.get("rooms") if isinstance(palace.get("rooms"), dict) else {}
    return {"scene": palace.get("scene") if palace.get("scene") in ("auto", *PALACE_SCENES) else "auto",
            "rooms": {k: v for k, v in rooms.items() if k in PALACE_SCENES and isinstance(v, dict)}}


def save_palace(request):
    """记忆宫殿的摆放：只收登记过的展品 id，坐标在场景内。整份替换当前场景，其余场景保留。"""
    if not isinstance(request, dict) or not set(request) <= {"scene", "room", "items"}:
        raise ValueError("摆放格式不正确，请刷新后再试。")
    palace = read_palace()
    if "scene" in request:
        if request["scene"] not in ("auto", *PALACE_SCENES):
            raise ValueError("没有这个场景。")
        palace["scene"] = request["scene"]
    if "room" in request or "items" in request:
        room, items = request.get("room"), request.get("items")
        if room not in PALACE_SCENES or not isinstance(items, dict) or len(items) > 400:
            raise ValueError("摆放格式不正确，请刷新后再试。")
        with gallery.guard:
            world = gallery.read()
            known = {r["id"] for group in ("exhibits", "sculptures") for r in world[group]}
        limits = {"x": (-24, 24), "z": (-24, 24), "y": (0, 4), "yaw": (-360, 360), "scale": (0.5, 2)}
        clean = {}
        for key, entry in items.items():
            furniture = isinstance(key, str) and FURNITURE_ID.fullmatch(key)
            allowed = {*limits, "hidden"} | ({"type"} if furniture else set())
            if (key not in known and not furniture) or not isinstance(entry, dict) or not set(entry) <= allowed:
                raise ValueError("有一件展品已变化，请刷新后再试。")
            row = {}
            if "type" in entry:
                if entry["type"] not in FURNITURE_TYPES:
                    raise ValueError("没有这种家具。")
                row["type"] = entry["type"]
            for field, (low, high) in limits.items():
                if field in entry:
                    value = entry[field]
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                        raise ValueError("摆放数值超出场景范围。")
                    row[field] = round(float(value), 3)
            if "hidden" in entry:
                if not isinstance(entry["hidden"], bool):
                    raise ValueError("摆放格式不正确。")
                row["hidden"] = entry["hidden"]
            clean[key] = row
        palace["rooms"][room] = {"items": clean}
    with (data.DATA / ".layout.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data.save(data.DATA / "palace.json", palace)
    return palace


def online():
    try:
        with urlopen(f"http://127.0.0.1:{WORKBENCH_PORT}/health", timeout=1.5) as response:
            return json.loads(response.read(512)) == {"app": "今日小物"}
    except (ValueError, OSError):
        return False


gallery = Gallery()
launch_lock = Lock()
launch_process = None


def start_workbench():
    global launch_process
    with launch_lock:
        if online():
            return {"online": True}
        if launch_process is None or launch_process.poll() is not None:
            launch_process = subprocess.Popen([str(WORKBENCH/".venv/bin/python"), "-B", "app.py", "--port", str(WORKBENCH_PORT), "--ensure-running"],
                                              cwd=WORKBENCH, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL, start_new_session=True)
        return {"online": False, "starting": True}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, *_):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def local_host(self):
        return self.client_address[0] == "127.0.0.1" and self.headers.get("Host") in {
            f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

    def reply(self, status, body):
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        if not self.local_host() or self.headers.get("Origin") != "http://" + self.headers["Host"]:
            return self.reply(403, {"error": "请从本机岛屿页面操作。"})
        path = urlsplit(self.path).path
        try:
            if path == "/api/workbench/start":
                return self.reply(200, start_workbench())
            if path not in ("/api/edits", "/api/layout", "/api/palace"):
                return self.send_error(404)
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 64 * 1024 or self.headers.get_content_type() != "application/json":
                raise ValueError("请使用页面内的编辑按钮保存。")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("卡片修改格式不正确。")
            if path == "/api/layout":
                return self.reply(200, {"layout": save_layout(payload)})
            if path == "/api/palace":
                return self.reply(200, {"palace": save_palace(payload)})
            self.reply(200, gallery.edit(payload))
        except EditConflict as exc:
            self.reply(409, {"error": "卡片文字已在另一处更新。", "card": exc.card})
        except (ValueError, UnicodeError) as exc:
            self.reply(400, {"error": str(exc)})
        except OSError:
            self.reply(503, {"error": "本机操作未完成，请检查目录和剩余空间再试。"})

    def do_GET(self):
        if not self.local_host():
            return self.send_error(403)
        path = urlsplit(self.path).path
        if path == "/api/workbench/status":
            return self.reply(200, {"online": online()})
        if path == "/data/world.json":
            world = dict(gallery.read())
            # Browser uses opaque IDs. Local file paths stay inside the server.
            for group in ("exhibits", "sculptures", "houses"):
                world[group] = [{k: v for k, v in r.items() if k not in {"original", "photo_file", "model"}}
                                | {"model": f"/models/{r['id']}?format={r['format']}&v={r['model_revision']}"} for r in world[group]]
            world["layout"] = read_layout()
            world["palace"] = read_palace()
            return self.reply(200, world)
        if path.startswith("/assets/"):
            name = path.removeprefix("/assets/")
            if "/" in name or not name.endswith(".glb"):
                return self.send_error(404)
            return self._file(ROOT / "assets" / name)
        if path.startswith(("/models/", "/photos/")):
            # The page first requests world.json; reuse that snapshot for all its assets.
            with gallery.guard:
                world = gallery.world or gallery.read()
            field = "photo_file" if path.startswith("/photos/") else "model"
            for item in world["exhibits"] + world["sculptures"] + world["houses"]:
                if item["id"] == path.split("/")[-1] and item.get(field):
                    file = Path(item[field])
                    fmt = parse_qs(urlsplit(self.path).query).get("format", [None])[0]
                    if field == "model" and fmt and fmt != item["format"]:
                        original = item.get("original")
                        if original and Path(original).suffix == "." + fmt:
                            file = Path(original)
                        else:
                            return self.send_error(404)
                    return self._file(file)
            return self.send_error(404)
        return super().do_GET()

    def _file(self, path):
        if not path.is_file():
            return self.send_error(404)
        with path.open("rb") as f:
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(os.fstat(f.fileno()).st_size))
            self.end_headers()
            try:
                shutil.copyfileobj(f, self.wfile, length=128 * 1024)
            except (BrokenPipeError, ConnectionResetError):
                pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5232"))
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
