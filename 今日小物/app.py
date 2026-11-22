#!/usr/bin/env python3
"""Loopback web server, CLI and Agent handoff for 今日小物."""
import argparse
import errno
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
from shutil import copyfileobj
import subprocess
import sys
from threading import Thread
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
import webbrowser
import feishu_print
import feishu_webhook

from finished_photo import MAX_PHOTO_BYTES
from local_store import Problem, checked_date, checked_job_key, checked_source, credentials
from workshop import App

ROOT = Path(__file__).resolve().parent
ASSETS = {"/": "index.html", "/style.css": "style.css", "/ui.js": "ui.js",
          "/viewer.js": "viewer.js", "/viewer.css": "viewer.css", "/viewer-mesh.js": "viewer-mesh.js", "/sound.js": "sound.js",
          "/lighthouse.jpg": "lighthouse.jpg", "/guide": "../使用与接入.html"}
WORLD_ORIGINS = {"http://127.0.0.1:5232", "http://localhost:5232"}
MAX_RECORD_BYTES = 64 * 1024


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def headers_for(self, status, size, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if urlsplit(self.path).path == "/health":
            origin = self.headers.get("Origin")
            self.send_header("Vary", "Origin")
            if origin in WORLD_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origin)
        policy = "default-src 'self'; base-uri 'none'; frame-ancestors http://127.0.0.1:5232 http://localhost:5232; form-action 'self'"
        if urlsplit(self.path).path == "/guide":
            # The offline guide embeds its own CSS and copy/zoom controls.
            policy += "; style-src 'unsafe-inline'; script-src 'unsafe-inline'"
        self.send_header("Content-Security-Policy", policy)
        self.end_headers()

    def reply(self, status, result):
        payload = json.dumps(result, ensure_ascii=False).encode()
        self.headers_for(status, len(payload), "application/json; charset=utf-8")
        self.wfile.write(payload)

    def send_file(self, file):
        content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        with file.open("rb") as handle:
            self.headers_for(200, os.fstat(handle.fileno()).st_size, content_type)
            copyfileobj(handle, self.wfile, length=64 * 1024)

    def origin(self):
        return f"127.0.0.1:{self.server.server_port}"

    def do_GET(self):
        if self.headers.get("Host") != self.origin():
            self.reply(403, {"error": "仅接受本机连接。"})
            return
        url = urlsplit(self.path)
        path = url.path
        app = self.server.app
        try:
            if path == "/health":
                self.reply(200, {"app": "今日小物"})
                return
            if path in ASSETS:
                file = ROOT / "web" / ASSETS[path]
            elif path.startswith("/state/") and path.count("/") == 2:
                self.reply(200, app.state(path.split("/")[-1]))
                return
            elif path.startswith("/files/") and len(path.split("/")) == 4:
                _, _, key, name = path.split("/")
                query = parse_qs(url.query)
                raw_edition = query.get("edition", [None])[0]
                if raw_edition is not None and (not raw_edition.isascii() or not raw_edition.isdigit() or len(raw_edition) > 8):
                    raise Problem("找不到这件作品的旧版。")
                file = app.download(key, name, int(raw_edition) if raw_edition is not None else None,
                                    query.get("revision", [None])[0])
            else:
                raise Problem("找不到页面。")
            self.send_file(file)
        except (BrokenPipeError, ConnectionResetError):
            return
        except (Problem, FileNotFoundError) as exc:
            self.reply(404, {"error": str(exc) if isinstance(exc, Problem) else "找不到文件。"})

    def do_POST(self):
        if (self.headers.get("Host") != self.origin() or
                self.headers.get("Origin") != "http://" + self.origin()):
            self.reply(403, {"error": "仅接受来自本应用的请求。"})
            return
        app = self.server.app
        try:
            size = int(self.headers.get("Content-Length", 0))
            url = urlsplit(self.path)
            parts = url.path.split("/")
            if len(parts) == 3 and parts[1] == "finished-photo":
                key = checked_job_key(parts[2])
                if not 0 < size <= MAX_PHOTO_BYTES:
                    raise Problem("请选择 12 MB 以内的实物照片。")
                media_type = self.headers.get_content_type()
                if media_type not in ("image/jpeg", "image/png"):
                    raise Problem("请选择 JPG 或 PNG 实物照片。")
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise Problem("照片上传不完整，请重试。")
                app.attach_photo(key, raw, media_type, parse_qs(url.query).get("revision", [None])[0])
                self.reply(200, {"ok": True})
                return
            if not 0 < size <= MAX_RECORD_BYTES or self.headers.get_content_type() != "application/json":
                raise Problem("输入格式错误或超出大小限制。")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise Problem("输入需要使用 JSON 对象。")
            if self.path in {"/record", "/agent-record"}:
                self.reply(200, app.submit(data, handoff=self.path == "/agent-record", manual=self.path == "/record"))
                return
            if self.path == "/printer-check":
                self.reply(200, app.test_printer(checked_source(data.get("source", "external"))))
                return
            if self.path == "/settings":
                app.update_settings(data)
            elif self.path == "/organize":
                app.organize(checked_date(data.get("date")))
            elif self.path in {"/unlock", "/cancel-edit"}:
                app.edit(checked_date(data.get("date")), self.path == "/unlock", data.get("edit_token"))
            elif self.path == "/connections":
                app.update_connections(data)
            elif self.path == "/sample":
                app.run("sample", "sample")
            elif self.path == "/ready":
                app.mark_ready(checked_job_key(data.get("date")), data.get("ready"),
                               data.get("source"), data.get("prepare_ok", False))
            elif self.path == "/color-request":
                app.colors.request(checked_job_key(data.get("date")))
            elif self.path == "/color-confirm":
                app.colors.confirm(checked_job_key(data.get("date")), data.get("code"), checked_source(data.get("source")))
            elif self.path == "/color-card":
                app.colors.upgrade_notice(checked_job_key(data.get("date")))
            elif self.path == "/feishu-cards":
                if not app.personal_chat:
                    raise Problem("隔离工作台不连接正式飞书账号。")
                feishu_print.enable_cards()
                app.card_listener.start()
            elif self.path == "/feishu-webhook":
                feishu_webhook.configure(app.data, webhook=data.get("webhook"), secret=data.get("secret"),
                                         only_me=data.get("only_me") is True)
            elif self.path == "/feishu-pair":
                if not app.personal_chat:
                    raise Problem("隔离工作台不连接正式飞书账号。")
                self.reply(200, feishu_print.begin_pairing())
                return
            elif self.path == "/generate":
                app.run(checked_date(data.get("date")), "generate")
            elif self.path == "/print":
                app.run(checked_job_key(data.get("date")), "print")
            else:
                raise Problem("找不到操作。")
            self.reply(200, {"ok": True})
        except (ValueError, UnicodeError):
            self.reply(400, {"error": "输入格式错误。"})
        except (Problem, feishu_print.FeishuError, feishu_webhook.WebhookError) as exc:
            self.reply(400, {"error": str(exc)})


def submit_from_agent(args):
    origin = f"http://127.0.0.1:{args.port}"
    if args.record_file == "-":
        data = sys.stdin.buffer.read(MAX_RECORD_BYTES + 1)
    else:
        with Path(args.record_file).open("rb") as handle:
            data = handle.read(MAX_RECORD_BYTES + 1)
    if len(data) > MAX_RECORD_BYTES:
        print("交接记录超过 64 KiB，请缩短当天摘要或造型描述。", file=sys.stderr)
        return 1
    request = Request(origin + "/agent-record", data=data, headers={
        "Content-Type": "application/json", "Origin": origin,
    })
    try:
        with urlopen(request, timeout=10) as response:
            print(response.read().decode())
    except HTTPError as exc:
        print(exc.read().decode(), file=sys.stderr)
        return 1
    except URLError:
        print("请先打开今日小物，再交接当天记录。", file=sys.stderr)
        return 1
    return 0


def ensure_running(port):
    """Start the local workbench without a browser for the daily Agent handoff."""
    def running():
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                return json.loads(response.read(1024)) == {"app": "今日小物"}
        except (ValueError, OSError):
            return False
    if running():
        return 0
    process = subprocess.Popen([sys.executable, "-B", str(ROOT / "app.py"), "--port", str(port)],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    for _ in range(40):
        if running():
            return 0
        if process.poll() is not None:
            break
        time.sleep(0.2)
    print("本机工作台尚未启动，请检查端口和数据目录。", file=sys.stderr)
    return 1


def main():
    parser = argparse.ArgumentParser(description="今日小物")
    parser.add_argument("--port", type=int, default=17868)
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    parser.add_argument("--ensure-running", action="store_true", help="供每日 Agent 使用，在后台打开本机工作台")
    parser.add_argument("--submit", dest="record_file", help="交接日报 JSON 文件。使用 - 从标准输入读取。")
    args = parser.parse_args()
    if args.record_file:
        return submit_from_agent(args)
    if args.ensure_running:
        return ensure_running(args.port)
    os.umask(0o077)
    directory = Path(os.environ.get("MOODPRINT_DATA", ROOT / "data")).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    origin = f"http://127.0.0.1:{args.port}/"
    with (directory / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if args.open:
                webbrowser.open(origin)
                return 0
            raise SystemExit("今日小物已打开。") from None
        credentials(directory)
        try:
            server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
        except OSError as error:
            if error.errno != errno.EADDRINUSE:
                raise
            raise SystemExit(f"本机端口 {args.port} 正在使用。可用 --port 指定另一个端口。") from None
        with server:
            app = server.app = App(directory)
            if app.personal_chat and feishu_print.cards_enabled():
                app.card_listener.start()
            Thread(target=app.schedule, daemon=True).start()
            print(f"今日小物正在运行  {origin}", flush=True)
            if args.open:
                webbrowser.open(origin)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                app.stop.set()
                app.card_listener.close()
                if app.worker:
                    app.worker.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
