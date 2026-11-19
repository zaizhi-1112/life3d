"""History retrieval tests use only synthetic, isolated records."""

from contextlib import closing, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import history_context as history


class HistoryContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / "private"
        self.source = self.root / "explicit-export"
        self.source.mkdir()
        self.database = self.source / "source.sqlite3"
        with closing(sqlite3.connect(self.database)) as connection:
            connection.executescript("""
                CREATE TABLE settings(key TEXT,value TEXT);
                INSERT INTO settings VALUES('self_wxid','synthetic-owner');
                CREATE TABLE senders(id INTEGER,wxid TEXT);
                INSERT INTO senders VALUES(1,'synthetic-owner'),(2,'synthetic-peer');
                CREATE TABLE messages(id INTEGER PRIMARY KEY,ts INTEGER,text TEXT,
                    source_file TEXT,source_index INTEGER,is_me INTEGER,sender INTEGER,kind TEXT);
            """)
        self.add_message(1, "生日那天想收到一只抱着小礼物的水獭。")
        self.add_message(2, "生日那天想收到一只抱着小礼物的水獭。")
        self.add_message(3, "工作太累时想独自散步，看灯塔和海浪。")
        self.add_message(4, "这句话属于别人，不能认作本人。", sender=2, own=0)
        self.add_message(5, "错误标记的他人消息同样不能导入。", sender=2, own=1)
        self.add_message(6, "合并聊天里的文字不能作为本人原话。", kind="forward")
        self.add_message(7, "转发自：这是其他作者写的长文。")
        self.add_message(8, "聊天系统通知，不应当进入个人事实。", kind="system")

    def add_message(self, key, text, *, sender=1, own=1, kind="text"):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)", (
                key, 1704038400 + key, text, "synthetic-source.json", key, own, sender, kind,
            ))
            connection.commit()

    def import_export(self):
        return history.import_wechat_directory(self.source, data_dir=self.data)

    def test_import_is_attributed_deduplicated_and_idempotent(self):
        first = self.import_export()
        self.assertEqual(first["documents"], 3)
        self.assertEqual(first["segments"], 2)
        self.assertEqual(first["occurrences"], 3)
        with patch.object(history, "_updated", wraps=history._updated) as updated:
            second = self.import_export()
            updated.assert_not_called()
        self.assertEqual(second["scanned"], 0)
        self.assertEqual(second["segments"], first["segments"])
        self.assertEqual(second["occurrences"], first["occurrences"])

    def test_local_chinese_approximate_search_and_stable_lookup(self):
        self.import_export()
        hits = history.search("生日礼物 水獭", data_dir=self.data, limit=2)
        self.assertTrue(hits)
        first = hits[0]
        self.assertIn("生日", first["excerpt"])
        self.assertEqual(first, history.lookup(first["ref"], data_dir=self.data))
        self.assertEqual(first["source_type"], "wechat_self_text")
        self.assertEqual(first["date"], "2024-01-01")
        self.assertTrue(history.REF.fullmatch(first["ref"]))
        self.assertLessEqual(len(first["excerpt"]), 120)
        self.assertEqual(set(first), {"ref", "date", "source_type", "excerpt", "redacted"})

    def test_source_append_adds_only_verified_new_records(self):
        first = self.import_export()
        self.add_message(9, "完成一个长期项目后，想给自己一个掌心纪念品。")
        second = self.import_export()
        self.assertEqual(second["imported_documents"], 1)
        self.assertEqual(second["segments"], first["segments"] + 1)
        self.assertEqual(second["documents"], first["documents"] + 1)

    def test_lookup_cannot_resolve_fake_reference_or_caller_quotes(self):
        self.import_export()
        self.assertIsNone(history.lookup("hist_" + "0" * 24, data_dir=self.data))
        self.assertIsNone(history.lookup("not a real quote", data_dir=self.data))
        self.assertIsNone(history.lookup(None, data_dir=self.data))

    def test_phone_email_link_and_path_are_redacted_before_retrieval(self):
        self.add_message(9, "联系邮箱 demo@example.com，电话 13812345678，链接 https://example.com/private，本机 /Users/demo/private.txt，想做一只小海豹。")
        self.import_export()
        hit = history.search("海豹", data_dir=self.data)[0]
        self.assertTrue(hit["redacted"])
        for private in ("demo@example.com", "13812345678", "https://", "/Users/"):
            self.assertNotIn(private, hit["excerpt"])

    def test_summary_reads_cached_meta_and_missing_index_stays_missing(self):
        self.assertFalse(history.summary(data_dir=self.data)["available"])
        self.assertFalse(self.data.exists())
        self.import_export()
        self.assertEqual(history.summary(data_dir=self.data)["segments"], 2)
        self.assertEqual(history._path(self.data).stat().st_mode & 0o777, 0o600)
        self.assertEqual(history._path(self.data).parent.stat().st_mode & 0o777, 0o700)

    def test_note_import_requires_author_evidence_and_supports_incremental_files(self):
        note = self.root / "explicit-note.md"
        note.write_text("生日的时候，希望收到一份安静的礼物。", encoding="utf-8")
        with self.assertRaises(history.HistoryError):
            history.import_file(note, date="2024-02-03", data_dir=self.data)
        result = history.import_file(note, verified_self=True, date="2024-02-03", data_dir=self.data)
        again = history.import_file(note, verified_self=True, date="2024-02-03", data_dir=self.data)
        self.assertEqual(result["documents"], 1)
        self.assertEqual(again["imported_documents"], 0)
        note.write_text("工作结束，想在海边散步，再打印一座灯塔。", encoding="utf-8")
        appended = history.import_file(note, verified_self=True, date="2024-02-04", data_dir=self.data)
        self.assertEqual(appended["documents"], 2)

    def test_jsonl_rejects_assistant_text_and_keeps_provenance_private(self):
        note = self.root / "explicit-note.jsonl"
        note.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in (
            {"role": "assistant", "date": "2024-02-03", "text": "这是 AI 对人的归纳，应排除。"},
            {"role": "user", "date": "2024-02-03", "text": "在生日收到一只抱花小熊会很开心。"},
        )), encoding="utf-8")
        result = history.import_file(note, verified_self=True, data_dir=self.data)
        self.assertEqual(result["documents"], 1)
        hit = history.search("小熊", data_dir=self.data)[0]
        self.assertNotIn("private_path", hit)
        self.assertNotIn(str(note), json.dumps(hit))

    def test_query_limits_and_cli_summary_are_bounded(self):
        self.import_export()
        with self.assertRaises(history.HistoryError):
            history.search("生日", data_dir=self.data, limit=1000)
        with self.assertRaises(history.HistoryError):
            history.search("生日" * 100, data_dir=self.data)
        output = StringIO()
        with redirect_stdout(output):
            code = history.main(["--data-dir", str(self.data), "summary"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["segments"], 2)

    def test_long_records_split_into_retrievable_short_excerpts(self):
        self.add_message(9, "海边的灯塔让我慢慢安静下来。" * 30)
        self.import_export()
        hits = history.search("海边灯塔", data_dir=self.data)
        self.assertTrue(hits)
        self.assertTrue(all(len(item["excerpt"]) <= 120 for item in hits))

    def test_interrupted_batch_resumes_without_duplicates(self):
        insert = history._insert_document
        calls = 0

        def interrupted(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise history.HistoryError("synthetic interruption")
            return insert(*args, **kwargs)

        with patch.object(history, "BATCH_SIZE", 1), patch.object(history, "_insert_document", side_effect=interrupted):
            with self.assertRaises(history.HistoryError):
                self.import_export()
        restored = self.import_export()
        self.assertEqual(restored["documents"], 3)
        self.assertEqual(restored["segments"], 2)
        self.assertEqual(restored["occurrences"], 3)

    def test_invalid_note_batch_rolls_back_imported_lines(self):
        note = self.root / "invalid.jsonl"
        note.write_text(json.dumps({
            "role": "user", "date": "2024-02-03", "text": "这一行不能在第二行失败时被留在半成品中。",
        }, ensure_ascii=False) + "\nnot JSON", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            history.import_file(note, verified_self=True, data_dir=self.data)
        self.assertEqual(history.summary(data_dir=self.data)["documents"], 0)

    def test_import_does_not_modify_original_database(self):
        before = self.database.read_bytes()
        self.import_export()
        self.assertEqual(before, self.database.read_bytes())

    def test_query_connection_is_read_only(self):
        self.import_export()
        with closing(history._readonly(history._path(self.data))) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM segments")


if __name__ == "__main__":
    unittest.main()
