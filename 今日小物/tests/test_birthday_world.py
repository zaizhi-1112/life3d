"""Offline cross-project tests for birthday inspiration and gallery handoff."""
from contextlib import closing
from datetime import date, timedelta
from http.client import HTTPConnection
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
from threading import Thread
from unittest import TestCase
from unittest.mock import patch

from daily_inputs import birthday_passages, collect

WORLD = Path(__file__).resolve().parents[2] / "二十三"


class BirthdayHandoff(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.daily = self.root / "daily"
        self.feed = self.root / "gift/stage5_analysis/world_feed.json"
        self.feed.parent.mkdir(parents=True)
        self.workspace = self.root / "island.json"
        self.workspace.write_text("{}")
        with closing(sqlite3.connect(self.root / "state_5.sqlite")) as db:
            db.execute("CREATE TABLE threads(id,title,rollout_path,updated_at,created_at,source,thread_source)")
        moments = [{"date": "2026-06-01", "title": t, "text": t, "kind": k, "safe_for_inspiration": safe}
                   for t, k, safe in [("海边捡石头", "joy", True), ("画一张船票", "help", True),
                                      ("待你决定", "hard", True), ("未核实", "joy", False)]]
        for n, event in enumerate(moments):
            event["evidence"] = [f"fixture-{n}"]
        feed = {"moments": moments, "eras": [], "circles": [], "people": [], "emotions": []}
        self.feed.write_text(json.dumps(feed))

    def inputs(self, day):
        return collect(day, self.workspace, self.root, gift=self.feed.parents[1], directory=self.daily)

    def test_empty_day_reserves_safe_passage_for_sixty_days_and_reuses_same_day(self):
        day = date(2026, 9, 1)
        first = self.inputs(day)["birthday_inspiration"]
        self.assertIn(first["title"], {"海边捡石头", "画一张船票"})
        self.assertEqual(self.inputs(day)["birthday_inspiration"], first)
        second = self.inputs(day + timedelta(days=1))["birthday_inspiration"]
        self.assertNotEqual(second, first)
        self.assertIsNone(self.inputs(day + timedelta(days=59))["birthday_inspiration"])
        self.assertEqual(self.inputs(day + timedelta(days=60))["birthday_inspiration"], first)
        self.workspace.write_text("invalid")
        self.assertNotIn("birthday_inspiration", self.inputs(day))

    def test_amended_passage_is_not_repeated_and_withdrawn_passages_are_not_replayed(self):
        day = date(2026, 9, 1)
        first = self.inputs(day)["birthday_inspiration"]
        feed = json.loads(self.feed.read_text())
        selected = next(row for row in feed["moments"] if row["title"] == first["title"])
        selected["text"] += "。这是复核后的描述。"
        self.feed.write_text(json.dumps(feed))
        self.assertEqual(self.inputs(day)["birthday_inspiration"]["text"], selected["text"])
        self.assertNotEqual(self.inputs(day+timedelta(days=1))["birthday_inspiration"]["title"], selected["title"])
        selected["safe_for_inspiration"] = False
        self.feed.write_text(json.dumps(feed))
        self.assertIsNone(self.inputs(day)["birthday_inspiration"])

    def test_fallback_uses_only_reviewed_fragments_of_the_timeline(self):
        archive = self.root / "archive"
        timeline = archive / "stage4_summaries/rollup/L1/第1层汇总.md"
        timeline.parent.mkdir(parents=True)
        timeline.write_text("## 人生时间线\n那年有一段痛苦经历，待你决定是否展开。后来朗诵进决赛。\n## 附录\n进了社群当运营练习生。")
        self.assertEqual([p["text"] for p in birthday_passages(archive)], ["朗诵进决赛。"])

    def test_sculpture_switches_only_to_linked_available_editions_and_keeps_edits(self):
        world_data = self.root / "world"
        with patch.dict(os.environ, {"BIRTHDAY_WORLD_DATA": str(world_data),
                                     "BIRTHDAY_GIFT_OUTPUT": str(self.feed.parents[1]),
                                     "MOODPRINT_DATA": str(self.daily)}):
            spec = importlib.util.spec_from_file_location("edition_test_catalog", WORLD / "tools/build_world_data.py")
            catalog = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(catalog)
        catalog.COMPACT.mkdir(parents=True)
        original = {"id": "boat", "title": "岸边的小船", "placement": {"zone": "coast", "slot": 2},
                    "model_path": "original.glb"}
        edition = {"id": "blue-boat", "title": "制作版标题", "replaces": "boat", "model_path": "blue.glb"}
        entries = [original, edition]
        edits = {"sc-boat": {"title": "小时候的船", "text": "我自己改的文字"}}
        catalog.save(catalog.EDITS, edits)

        def model_file(ident):
            return catalog.COMPACT / f"aholo-{ident}.glb"

        def shown():
            catalog.save(catalog.LEDGER, {"items": entries})
            world = catalog.build(persist=False)
            self.assertEqual(len(world["sculptures"]), 1)
            row = world["sculptures"][0]
            self.assertEqual(row["id"], row["card_id"])
            self.assertEqual(row["card_id"], "sc-boat")
            self.assertEqual({k: row["card"][k] for k in ("title", "text")}, edits["sc-boat"])
            self.assertEqual(row["placement"], original["placement"])
            self.assertEqual(row["model"], str(model_file(row["version_id"])))
            self.assertFalse(any(key.startswith("sc-") and key != "sc-boat" for key in world["cards"]))
            return row["version_id"]

        model_file("boat").write_bytes(b"original fixture")
        self.assertEqual(shown(), "boat")
        original["replaced_by"] = "blue-boat"
        self.assertEqual(shown(), "boat")  # Download/compaction is incomplete.
        model_file("blue-boat").write_bytes(b"blue fixture")
        # An artist may have laid out the original slot again after paying
        # for this edition. Its old snapshot must not move the live exhibit.
        edition["placement"] = {"zone": "coast", "slot": 1}
        self.assertEqual(shown(), "blue-boat")
        edition["withdrawn"] = True
        self.assertEqual(shown(), "boat")
        edition["withdrawn"] = False
        edition["replaces"] = "unrelated"
        self.assertEqual(shown(), "boat")
        edition["replaces"] = "boat"
        edition["replaced_by"] = "new-boat"
        entries.append({"id": "new-boat", "replaces": "blue-boat", "model_path": "new.glb"})
        self.assertEqual(shown(), "blue-boat")
        model_file("new-boat").write_bytes(b"new fixture")
        self.assertEqual(shown(), "new-boat")
        entries[-1]["withdrawn"] = True
        self.assertEqual(shown(), "blue-boat")
        self.assertEqual(catalog.load(catalog.EDITS, {}), edits)
        self.assertEqual(model_file("boat").read_bytes(), b"original fixture")

    def start_world(self):
        env = {"BIRTHDAY_WORLD_DATA": str(self.root / "world"), "MOODPRINT_DATA": str(self.daily),
               "BIRTHDAY_GIFT_OUTPUT": str(self.feed.parents[1])}
        with patch.dict(os.environ, env), patch.dict(sys.modules), patch.object(sys, "path", sys.path.copy()):
            # The service imports its catalog once, binding this test's data directories.
            sys.modules.pop("build_world_data", None)
            spec = importlib.util.spec_from_file_location("birthday_test_server", WORLD / "serve.py")
            server = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(server)
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        origin = "http://127.0.0.1:" + str(httpd.server_port)

        def request(path, payload=None, *, status=200, raw=False):
            conn = HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
            try:
                conn.request("GET" if payload is None else "POST", path, None if payload is None else json.dumps(payload),
                             {"Origin": origin, "Content-Type": "application/json"})
                r = conn.getresponse()
                self.assertEqual(r.status, status)
                return r.read() if raw else json.loads(r.read())
            finally:
                conn.close()

        return server, request

    def test_person_cards_and_shared_home_models_use_separate_identities(self):
        server, request = self.start_world()
        catalog = server.data
        feed = json.loads(self.feed.read_text())
        feed["people"] = [
            {"id": f"p{i}", "name": "山风" if i == 47 else f"人物{i}", "from": "2022-06", "to": "",
             "layer": 1 if i < 30 else 4, "weight": 200-i, "line": f"小传{i}"} for i in range(130)
        ]
        self.feed.write_text(json.dumps(feed))
        residents = [{"id": f"p{i}", "style": style} for i, style in
                     [(0, "home-pink"), (1, "home-ink"), (2, "home-studio"), (33, "home-observatory")]]
        residents.extend({"id": f"p{i}", "style": "home-family", "group": "family"} for i in (30, 31, 32))
        residents.extend({"id": style + "-owner", "style": style, "name": name} for style, name in
                         [("home-grove", "山风"), ("home-bridge", "桥边"), ("home-lantern", "灯旁")])
        catalog.save(catalog.HOUSING, {"residents": residents})
        styles = {"home-common"} | {p["style"] for p in residents}
        catalog.COMPACT.mkdir()
        model_bytes = (WORLD / "assets/cottage_small.glb").read_bytes()
        buildings = []
        for style in sorted(styles):
            buildings.append({"id": style, "title": style, "placement": {"zone": "home"}, "model_path": "model.glb"})
            (catalog.COMPACT / f"aholo-{style}.glb").write_bytes(model_bytes)
        catalog.save(catalog.LEDGER, {"items": buildings})
        world = request("/data/world.json")
        people = world["people"]
        occupants = [p for p in people if p["house_style"]]
        self.assertEqual(len(people) - len(occupants), 96)
        self.assertEqual(len(occupants), 37)
        self.assertEqual(len({p["card_id"] for p in occupants}), 37)
        self.assertEqual(len({p.get("home_group") or p["id"] for p in occupants}), 35)
        self.assertEqual(sum(p["house_style"] == "home-common" for p in occupants), 27)
        self.assertEqual({p["card_id"]: p["house_style"] for p in people if p["name"] == "山风"},
                         {"person:p47": None, "person:home-grove-owner": "home-grove"})
        self.assertEqual({h["style"] for h in world["houses"]}, styles)
        self.assertEqual(len(world["houses"]), 9)
        self.assertFalse(world["sculptures"])
        for h in world["houses"]:
            self.assertTrue(h["model"].startswith("/models/" + h["id"] + "?"))
            self.assertEqual(request(h["model"], raw=True), model_bytes)
            self.assertNotIn(h["id"], world["cards"])
        (catalog.COMPACT / "aholo-unlisted.glb").write_bytes(model_bytes)
        request("/models/sc-unlisted", status=404, raw=True)
        request("/models/sc-home-family?format=stl", status=404, raw=True)

        family = [p for p in occupants if p.get("home_group") == "family"]
        self.assertEqual(len(family), 3)
        expected_edits = {}
        for p in family:
            fields = {"title": "共用门牌", "text": f"单独记录 {p['id']}"}
            key = p["card_id"]
            request("/api/edits", {"id": key, "fields": fields})
            expected_edits[key] = fields
        self.assertEqual(catalog.load(catalog.EDITS, {}), expected_edits)
        cards = request("/data/world.json")["cards"]
        for key, fields in expected_edits.items():
            self.assertEqual((cards[key]["title"], cards[key]["text"]), (fields["title"], fields["text"]))
        first = family[0]["card_id"]
        request("/api/edits", {"id": first, "reset": True})
        expected_edits.pop(first)
        self.assertEqual(catalog.load(catalog.EDITS, {}), expected_edits)

    def test_live_world_rebuild_edits_restore_and_model_deduplication(self):
        server, request = self.start_world()
        broken = self.daily / "jobs/broken/job.json"
        broken.parent.mkdir(parents=True)
        broken.write_text("{")
        initial = request("/data/world.json")
        self.assertFalse(initial["exhibits"])
        moment = initial["moments"][0]["card_id"]
        request("/api/edits", {"id": moment, "fields": {"title": "我给这段往事的标题"}})
        feed = json.loads(self.feed.read_text())
        feed["moments"][0].update(title="核对后的标题", date="2026-06-02")
        self.feed.write_text(json.dumps(feed))
        rebuilt = request("/data/world.json")["moments"][0]
        self.assertEqual(rebuilt["card_id"], moment)
        self.assertEqual(rebuilt["card"]["title"], "我给这段往事的标题")
        folder = self.daily / "jobs/2026-09-02"
        folder.mkdir(parents=True)
        meta = {"title": "测试帆船", "summary": "学会折一艘船", "design_reason": "一个三角形的帆", "status": "prepared",
                "lux3d_task_id": 1}
        (folder / "job.json").write_text(json.dumps(meta))
        # Closed tetrahedron, a real binary STL for the existing Blender reducer.
        points = [(0,0,0), (1,0,0), (0,1,0), (0,0,1)]
        faces = [(0,2,1), (0,1,3), (0,3,2), (1,2,3)]
        stl = bytes(80) + struct.pack("<I", 4)
        for face in faces:
            stl += struct.pack("<12fH", 0,0,0, *(c for i in face for c in points[i]), 0)
        (folder/"model.stl").write_bytes(stl)
        (folder/"model.glb").write_bytes(b"original-for-selector-test")
        meta["print"] = {"mesh": "model.stl"}
        (folder/"job.json").write_text(json.dumps(meta))
        alias = folder.parent / "sample"
        alias.mkdir()
        (alias/"job.json").write_text(json.dumps(meta))
        (alias/"model.stl").write_bytes(stl)
        # Exercise asynchronous scheduling without launching Blender in offline tests.
        with patch.object(server.gallery, "reduce"):
            world = request("/data/world.json")
            self.assertEqual(len(world["exhibits"]), 1)
            row = world["exhibits"][0]
            self.assertEqual(row["format"], "stl")
            self.assertEqual(row["print_state"], "尚未开打")
            compact = self.root / "world/exhibits/test.glb"
            compact.parent.mkdir(exist_ok=True)
            compact.write_bytes(bytes(64))
            catalog = server.data
            catalog.save(compact.with_suffix(".source.json"), catalog.compact_record(folder/"model.glb", compact))
            self.assertFalse(catalog.fresh_compact(folder/"model.stl", compact))
            self.assertNotIn("original", row)
            self.assertEqual(len(world["emotions"]), len({e["month"] for e in world["emotions"]}))
            self.assertTrue(all(not e["has_data"] for e in world["emotions"]))
            key = row["card_id"]
            request("/api/edits", {"id": key, "fields": {"title": "小船"}})
            meta.update(status="finished", finished_photo="finished.jpg")
            (folder/"finished.jpg").write_bytes((WORLD.parent / "今日小物/web/lighthouse.jpg").read_bytes())
            (folder/"job.json").write_text(json.dumps(meta))
            row = request("/data/world.json")["exhibits"][0]
            self.assertEqual(row["card"]["title"], "小船")
            self.assertTrue(row["photo_url"])
            self.assertEqual(row["print_state"], "已留实物照片")
            self.assertEqual(request("/api/edits", {"id": key, "reset": True})["card"]["title"], meta["title"])
            revision = "0123456789abcdef"
            revised = {"title": "第二艘小船", "status": "recorded", "revision": revision, "prior_versions": [meta]}
            (folder/"job.json").write_text(json.dumps(revised))
            draft_exhibit = next(item for item in request("/data/world.json")["exhibits"] if item["id"] == row["id"])
            self.assertEqual(draft_exhibit["title"], meta["title"])
            self.assertTrue(draft_exhibit["photo_url"])
            revised_folder = folder / "versions" / revision
            revised_folder.mkdir(parents=True)
            (revised_folder/"model.glb").write_bytes(b"new model fixture")
            latest = next(item for item in request("/data/world.json")["exhibits"] if item["id"] == row["id"])
            self.assertEqual(latest["title"], revised["title"])
            self.assertFalse(latest["photo_url"])
            self.assertEqual(request(latest["model"], raw=True), b"new model fixture")
