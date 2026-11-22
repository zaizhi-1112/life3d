"""Three ends: the person's words to AI, what Agents did, and handwritten todos."""
from datetime import date
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from daily_draft import build_material, checked_draft, draft_for_day
from daily_inputs import claude_inputs, autoloop_inputs, collect


def line(**row):
    return json.dumps(row, ensure_ascii=False)


class ThreeEnds(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.day = date(2026, 11, 19)

    def claude_project(self):
        folder = self.root / ".claude-projects" / "-Users-me-Desktop-today"
        folder.mkdir(parents=True)
        rows = [
            line(type="custom-title", customTitle="做今日小物"),
            line(type="user", timestamp="2026-11-19T02:00:00Z", cwd="/Users/me/Desktop/today",
                 message={"role": "user", "content": "<command-name>/clear</command-name>"}),
            line(type="user", timestamp="2026-11-19T02:01:00Z", cwd="/Users/me/Desktop/today",
                 message={"role": "user", "content": "帮我把每天的心情打印出来，要好看！"}),
            line(type="assistant", timestamp="2026-11-19T02:02:00Z",
                 message={"content": [{"type": "thinking", "thinking": "不应出现"}, {"type": "tool_use", "name": "Bash"}]}),
            line(type="user", timestamp="2026-11-19T02:02:01Z",
                 message={"content": [{"type": "tool_result", "content": "工具输出不应出现"}]}),
            line(type="assistant", timestamp="2026-11-19T02:03:00Z",
                 message={"content": [{"type": "text", "text": "已经做好，样品在桌上。"}]}),
            line(type="user", timestamp="2026-11-19T02:04:00Z", isSidechain=True,
                 message={"content": "子代理的话不算本人"}),
            line(type="user", timestamp="2026-11-18T02:04:00Z", message={"content": "前一天的话"}),
        ]
        (folder / "s.jsonl").write_text("\n".join(rows))
        return self.root / ".claude-projects"

    def hub(self):
        path = self.root / ".agent-hub.db"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE runs(rule, state, summary, created_at)")
        db.execute("CREATE TABLE cards(id INTEGER PRIMARY KEY, kind, title, state, created_at)")
        for n in range(5):
            db.execute("INSERT INTO runs VALUES('网站巡检','done','巡检完成',?)", (f"2026-11-19T0{n}:00:00Z",))
        db.execute("INSERT INTO runs VALUES('异常分析','done','网站已在 23:00 恢复，详情见 /Users/me/report.html',?)",
                   ("2026-11-19T05:00:00Z",))
        db.execute("INSERT INTO runs VALUES('网站巡检','done','前一天',?)", ("2026-11-18T10:00:00Z",))
        for state in ("closed", "open"):
            db.execute("INSERT INTO cards(kind,title,state,created_at) VALUES('notice','网站暂时打不开',?,?)",
                       (state, "2026-11-19T06:00:00Z"))
        db.commit()
        db.close()
        return path

    def test_claude_keeps_only_human_words_and_final_reply(self):
        items, partial = claude_inputs(self.day, self.claude_project())
        self.assertFalse(partial)
        self.assertEqual(items, [{"topic": "做今日小物", "harness": "Claude Code", "project": "today", "by": "你",
                                  "prompts": ["帮我把每天的心情打印出来，要好看！"],
                                  "agent_reports": ["已经做好，样品在桌上。"]}])

    def test_agent_hub_counts_rules_merges_cards_and_hides_paths(self):
        hub = autoloop_inputs(self.day, self.hub())
        self.assertEqual(hub["runs"], 6)
        self.assertEqual(hub["rules"][0], {"rule": "网站巡检", "runs": 5, "unfinished": 0})
        self.assertEqual(hub["cards"], [{"kind": "notice", "title": "网站暂时打不开", "times": 2, "open": 1}])
        self.assertTrue(all("/Users/" not in h["result"] for h in hub["highlights"]))

    def test_collect_merges_three_ends_and_skips_birthday_when_agents_worked(self):
        self.claude_project()
        self.hub()
        sqlite3.connect(self.root / "state_5.sqlite").execute(
            "CREATE TABLE threads(id,rollout_path,title,created_at,updated_at,source,thread_source)").connection.close()
        island = self.root / "island.json"
        island.write_text("{}")
        result = collect(self.day, island, self.root, gift=self.root / "none", directory=self.root / "d")
        self.assertEqual([item["harness"] for item in result["agent_work"]], ["Claude Code"])
        self.assertEqual(result["agent_hub"]["runs"], 6)
        self.assertNotIn("birthday_inspiration", result)

    def test_evidence_must_come_from_material(self):
        material = {"you_said": [{"words": ["帮我把每天的心情打印出来，要好看！"]}]}
        draft = {"summary": "s", "mood": "未标记", "title": "t", "idea": "圆脸小猫", "design_reason": "r",
                 "evidence": [{"from": "你说", "text": "「把每天的心情打印出来」"},
                              {"from": "你说", "text": "这句是编出来的"},
                              {"from": "别人", "text": "要好看"}]}
        result, trail = checked_draft(draft, material)
        self.assertEqual(trail, [{"from": "你说", "text": "把每天的心情打印出来"}])
        self.assertNotIn("evidence", result)

    def test_draft_groups_by_project_and_reports_three_end_counts(self):
        self.claude_project()
        self.hub()
        inputs = collect(self.day, self.root / "missing.json", self.root / "nocodex", gift=self.root / "none",
                         directory=self.root / "d", claude=self.root / ".claude-projects", hub=self.root / ".agent-hub.db")
        material = build_material("2026-11-19", inputs)
        self.assertEqual(material["you_said"][0]["words"], ["帮我把每天的心情打印出来，要好看！"])
        self.assertIn("网站暂时打不开（2 次，仍未处理）", material["agent_hub"]["alerts"])
        reply = ({"summary": "你今天说「把每天的心情打印出来」", "mood": "有劲", "title": "心情打印机",
                  "idea": "抱着纸卷的小打印机", "design_reason": "把心情变成实物"},
                 [{"from": "你说", "text": "把每天的心情打印出来"}])
        with patch("daily_draft.collect", return_value=inputs), patch("daily_draft.write_draft", return_value=reply):
            record, sources = draft_for_day("2026-11-19", self.root / "d")
        self.assertEqual(record["title"], "心情打印机")
        self.assertEqual((sources["prompts"], sources["agent_work"], sources["hub_runs"], sources["hub_alerts"]), (1, 1, 6, 2))
        self.assertEqual(sources["harnesses"], ["Claude Code"])


if __name__ == "__main__":
    unittest.main()
