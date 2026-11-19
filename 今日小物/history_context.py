"""Private, local retrieval of explicitly selected, attributable user records."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import re
import sqlite3
import unicodedata
from zoneinfo import ZoneInfo


TZ = ZoneInfo("Asia/Taipei")
MAX_EXCERPT = 120
MAX_NOTE_BYTES = 16 * 1024 * 1024
BATCH_SIZE = 1000
REF = re.compile(r"hist_[a-f0-9]{24}\Z")
FORWARDED = re.compile(r"^\s*(?:转发(?:消息|内容|聊天记录|自)|转载|摘自|引用自|【(?:转发|转载|聊天记录)】|\[聊天记录\]|合并转发|<msg\b|<appmsg\b)", re.I)
PRIVATE_FIELDS = re.compile(
    r"https?://[^\s<>]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
    r"|(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"
    r"|\bwxid_[A-Za-z0-9_]+\b|(?:/Users/|/home/)[^\s，。；、<>]+"
    r"|[A-Za-z]:[\\/][^\s，。；、<>]+",
    re.I,
)
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(
    id INTEGER PRIMARY KEY, source_key TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL, private_path TEXT NOT NULL, owner_hash TEXT,
    cursor INTEGER NOT NULL DEFAULT 0, fingerprint TEXT
);
CREATE TABLE IF NOT EXISTS documents(
    id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id),
    external_id TEXT NOT NULL, date TEXT NOT NULL, raw_sha256 TEXT NOT NULL,
    private_locator TEXT NOT NULL, UNIQUE(source_id, external_id)
);
CREATE TABLE IF NOT EXISTS segments(
    id INTEGER PRIMARY KEY, ref TEXT UNIQUE NOT NULL, excerpt TEXT NOT NULL,
    date TEXT NOT NULL, source_type TEXT NOT NULL, redacted INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS occurrences(
    document_id INTEGER NOT NULL REFERENCES documents(id),
    ordinal INTEGER NOT NULL, segment_id INTEGER NOT NULL REFERENCES segments(id),
    PRIMARY KEY(document_id, ordinal)
);
CREATE INDEX IF NOT EXISTS occurrences_by_segment ON occurrences(segment_id);
CREATE VIRTUAL TABLE IF NOT EXISTS segment_fts USING fts5(tokens, content='');
"""


class HistoryError(ValueError):
    pass


def _data_dir(data_dir=None):
    return Path(data_dir or os.environ.get("MOODPRINT_DATA") or Path(__file__).resolve().parent / "data").expanduser().resolve()


def _path(data_dir=None):
    return _data_dir(data_dir) / "history" / "context.sqlite3"


def _readonly(path):
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA cache_size=-8192")
    return connection


def _writable(data_dir):
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA cache_size=-8192")
    connection.execute("PRAGMA mmap_size=0")
    connection.executescript(SCHEMA)
    for key in ("sources", "documents", "segments", "occurrences"):
        connection.execute("INSERT OR IGNORE INTO meta VALUES(?, '0')", (key,))
    connection.commit()
    return connection


def _increment(connection, key, count=1):
    connection.execute("UPDATE meta SET value=CAST(value AS INTEGER)+? WHERE key=?", (count, key))


def _updated(connection):
    timestamp = datetime.now(TZ).isoformat(timespec="seconds")
    connection.execute("INSERT OR REPLACE INTO meta VALUES('updated_at',?)", (timestamp,))


def _date(value):
    if isinstance(value, (float, int)):
        return datetime.fromtimestamp(value, timezone.utc).astimezone(TZ).date().isoformat()
    if not isinstance(value, str):
        raise HistoryError("历史记录需要可核实的日期。")
    try:
        result = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HistoryError("历史记录日期请使用 YYYY-MM-DD。") from None
    return result.isoformat()


def _tokens(text, *, query=False):
    normalized = unicodedata.normalize("NFKC", text).casefold()
    tokens = []
    for word in re.findall(r"[\u3400-\u9fff]+|[a-z0-9]+", normalized):
        if re.fullmatch(r"[\u3400-\u9fff]+", word):
            if not query or len(word) == 1:
                tokens.extend(word)
            tokens.extend(word[index:index + 2] for index in range(len(word) - 1))
        else:
            tokens.append(word)
    return list(dict.fromkeys(tokens))


def _segments(text):
    text = unicodedata.normalize("NFC", text).strip()
    if not text or FORWARDED.search(text):
        return
    sanitized, substitutions = PRIVATE_FIELDS.subn("【隐去联系方式或链接】", text)
    sanitized = re.sub(r"[ \t]+", " ", sanitized)
    for start in range(0, len(sanitized), MAX_EXCERPT):
        excerpt = sanitized[start:start + MAX_EXCERPT].strip()
        if len(excerpt) >= 4 and _tokens(excerpt):
            yield excerpt, bool(substitutions)


def _source(connection, path, kind, owner_hash=None):
    source_key = sha256((kind + "\0" + str(path)).encode()).hexdigest()
    cursor = connection.execute(
        "INSERT OR IGNORE INTO sources(source_key,kind,private_path,owner_hash) VALUES(?,?,?,?)",
        (source_key, kind, str(path), owner_hash),
    )
    if cursor.rowcount:
        _increment(connection, "sources")
    row = connection.execute("SELECT * FROM sources WHERE source_key=?", (source_key,)).fetchone()
    if row["owner_hash"] != owner_hash:
        raise HistoryError("来源的本人身份标记已变化，请核对来源后再导入。")
    return row


def _insert_document(connection, source, external_id, date, text, locator):
    parts = list(_segments(text))
    if not parts:
        return 0
    digest = sha256(text.encode()).hexdigest()
    existing = connection.execute(
        "SELECT raw_sha256 FROM documents WHERE source_id=? AND external_id=?", (source["id"], str(external_id)),
    ).fetchone()
    if existing:
        if existing["raw_sha256"] != digest:
            raise HistoryError("已导入的原始记录发生变化，保留现有索引并停止本批导入。")
        return 0
    document_id = connection.execute(
        "INSERT INTO documents(source_id,external_id,date,raw_sha256,private_locator) VALUES(?,?,?,?,?)",
        (source["id"], str(external_id), date, digest, json.dumps(locator, ensure_ascii=False)),
    ).lastrowid
    _increment(connection, "documents")
    for ordinal, (excerpt, redacted) in enumerate(parts):
        ref = "hist_" + sha256(excerpt.encode()).hexdigest()[:24]
        cursor = connection.execute(
            "INSERT OR IGNORE INTO segments(ref,excerpt,date,source_type,redacted) VALUES(?,?,?,?,?)",
            (ref, excerpt, date, source["kind"], int(redacted)),
        )
        if cursor.rowcount:
            segment_id = cursor.lastrowid
            connection.execute("INSERT INTO segment_fts(rowid,tokens) VALUES(?,?)", (segment_id, " ".join(_tokens(excerpt))))
            _increment(connection, "segments")
        else:
            segment_id = connection.execute("SELECT id FROM segments WHERE ref=?", (ref,)).fetchone()[0]
            connection.execute(
                "UPDATE segments SET date=?,source_type=? WHERE id=? AND date>?",
                (date, source["kind"], segment_id, date),
            )
        connection.execute("INSERT INTO occurrences VALUES(?,?,?)", (document_id, ordinal, segment_id))
        _increment(connection, "occurrences")
    return 1


def _public(row):
    if row is None:
        return None
    return {key: row[key] for key in ("ref", "date", "source_type", "excerpt")} | {"redacted": bool(row["redacted"])}


def search(query: str, *, data_dir=None, limit: int = 6):
    """Retrieve at most 12 short private excerpts for the local Agent."""
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 160:
        raise HistoryError("检索词需要 1 至 160 字。")
    if type(limit) is not int or not 1 <= limit <= 12:
        raise HistoryError("检索条数需要在 1 至 12 条之间。")
    path = _path(data_dir)
    tokens = _tokens(query, query=True)[:80]
    if not path.is_file() or not tokens:
        return []
    expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
    with closing(_readonly(path)) as connection:
        rows = connection.execute(
            "SELECT s.ref,s.date,s.source_type,s.excerpt,s.redacted FROM segment_fts "
            "JOIN segments s ON s.id=segment_fts.rowid WHERE segment_fts MATCH ? "
            "ORDER BY bm25(segment_fts),s.id LIMIT ?", (expression, limit),
        ).fetchall()
    return [_public(row) for row in rows]


def lookup(ref: str, *, data_dir=None):
    """Resolve a stable local reference, without accepting caller-supplied quotes."""
    if not isinstance(ref, str) or not REF.fullmatch(ref):
        return None
    path = _path(data_dir)
    if not path.is_file():
        return None
    with closing(_readonly(path)) as connection:
        row = connection.execute("SELECT ref,date,source_type,excerpt,redacted FROM segments WHERE ref=?", (ref,)).fetchone()
    return _public(row)


def summary(*, data_dir=None):
    """Read cached counts only. This never scans historical messages."""
    result = {"available": False, "sources": 0, "documents": 0, "segments": 0, "occurrences": 0, "updated_at": None}
    path = _path(data_dir)
    if not path.is_file():
        return result
    with closing(_readonly(path)) as connection:
        values = dict(connection.execute("SELECT key,value FROM meta"))
    for key in ("sources", "documents", "segments", "occurrences"):
        result[key] = int(values.get(key, 0))
    result.update(available=result["segments"] > 0, updated_at=values.get("updated_at"))
    return result


def import_wechat_directory(source_dir: Path, *, data_dir=None):
    """Import self-sent plain text only from one explicitly authorized export."""
    root = Path(source_dir).expanduser().resolve()
    candidates = [path for path in root.rglob("*.sqlite3") if path.resolve().is_relative_to(root) and not path.is_symlink()]
    if len(candidates) != 1:
        raise HistoryError("该目录需要包含唯一的、已核对身份的微信导出数据库。")
    path = candidates[0].resolve()
    imported = scanned = 0
    with closing(_readonly(path)) as original, closing(_writable(data_dir)) as target:
        owner = original.execute("SELECT value FROM settings WHERE key='self_wxid'").fetchone()
        if not owner or not owner[0]:
            raise HistoryError("来源没有可核对的本人身份标记。")
        senders = original.execute("SELECT id FROM senders WHERE wxid=?", (owner[0],)).fetchall()
        if len(senders) != 1:
            raise HistoryError("来源的本人发送者身份不唯一。")
        owner_hash = sha256(owner[0].encode()).hexdigest()
        source = _source(target, path, "wechat_self_text", owner_hash)
        rows = original.execute(
            "SELECT id,ts,text,source_file,source_index FROM messages "
            "WHERE id>? AND is_me=1 AND sender=? AND kind='text' AND length(trim(text))>0 ORDER BY id",
            (source["cursor"], senders[0][0]),
        )
        for row in rows:
            scanned += 1
            text = row["text"]
            if isinstance(text, str) and len(text.encode()) <= MAX_NOTE_BYTES:
                imported += _insert_document(target, source, row["id"], _date(row["ts"]), text, {
                    "database_row": row["id"], "source_file": row["source_file"], "source_index": row["source_index"],
                })
            target.execute("UPDATE sources SET cursor=? WHERE id=?", (row["id"], source["id"]))
            if scanned % BATCH_SIZE == 0:
                _updated(target)
                target.commit()
        if target.total_changes:
            _updated(target)
            target.commit()
    return {"source_type": "wechat_self_text", "scanned": scanned, "imported_documents": imported, **summary(data_dir=data_dir)}


def import_file(path: Path, *, verified_self: bool = False, date=None, data_dir=None):
    """Incrementally import one explicitly selected and author-verified local file."""
    if verified_self is not True:
        raise HistoryError("请先核实该文件内容由本人撰写，再指定 verified_self=True。")
    path = Path(path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in (".txt", ".md", ".jsonl") or path.stat().st_size > MAX_NOTE_BYTES:
        raise HistoryError("请选择不超过 16 MiB 的单个 TXT、Markdown 或 JSONL 文件。")
    with path.open("rb") as handle:
        snapshot = handle.read(MAX_NOTE_BYTES + 1)
    if len(snapshot) > MAX_NOTE_BYTES:
        raise HistoryError("指定文件在读取期间超出了 16 MiB 上限。")
    fingerprint = sha256(snapshot).hexdigest()
    imported = scanned = 0
    with closing(_writable(data_dir)) as target:
        source = _source(target, path, "user_verified_note")
        if source["fingerprint"] == fingerprint:
            return {"source_type": "user_verified_note", "scanned": 0, "imported_documents": 0, **summary(data_dir=data_dir)}
        with StringIO(snapshot.decode("utf-8-sig")) as handle:
            if path.suffix.lower() == ".jsonl":
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    scanned += 1
                    if not isinstance(row, dict) or row.get("role") != "user" or not isinstance(row.get("text"), str):
                        continue
                    day = _date(row.get("date", date))
                    digest = sha256(row["text"].encode()).hexdigest()
                    external_id = str(row.get("id", line_number)) + ":" + digest
                    imported += _insert_document(target, source, external_id, day, row["text"], {"line": line_number, "file_sha256": fingerprint})
            else:
                text = handle.read(MAX_NOTE_BYTES + 1)
                scanned = 1
                imported += _insert_document(target, source, fingerprint, _date(date), text, {"file_sha256": fingerprint})
        target.execute("UPDATE sources SET fingerprint=? WHERE id=?", (fingerprint, source["id"]))
        _updated(target)
        target.commit()
    return {"source_type": "user_verified_note", "scanned": scanned, "imported_documents": imported, **summary(data_dir=data_dir)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="给现有 Agent 使用的本机私有历史检索")
    parser.add_argument("--data-dir", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    query = commands.add_parser("search")
    query.add_argument("query")
    query.add_argument("--limit", type=int, default=6)
    reference = commands.add_parser("lookup")
    reference.add_argument("ref")
    commands.add_parser("summary")
    archive = commands.add_parser("import-wechat")
    archive.add_argument("directory", type=Path)
    note = commands.add_parser("import-file")
    note.add_argument("path", type=Path)
    note.add_argument("--verified-self", action="store_true")
    note.add_argument("--date")
    args = parser.parse_args(argv)
    try:
        if args.command == "search":
            result = search(args.query, data_dir=args.data_dir, limit=args.limit)
        elif args.command == "lookup":
            result = lookup(args.ref, data_dir=args.data_dir)
        elif args.command == "summary":
            result = summary(data_dir=args.data_dir)
        elif args.command == "import-wechat":
            result = import_wechat_directory(args.directory, data_dir=args.data_dir)
        else:
            result = import_file(args.path, verified_self=args.verified_self, date=args.date, data_dir=args.data_dir)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (HistoryError, sqlite3.Error, OSError, UnicodeError, json.JSONDecodeError):
        print(json.dumps({"error": "本地历史索引操作失败，请核对来源格式、本人身份与文件权限。"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
