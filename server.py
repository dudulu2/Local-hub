#!/usr/bin/env python3
"""LocalHub - zero-dependency local media gallery server.

Run this file from the folder that contains your media, or pass --root PATH.
The server only binds to 127.0.0.1 by default and never uploads media.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
STATIC_FILES = {
    "/": APP_DIR / "index.html",
    "/index.html": APP_DIR / "index.html",
    "/styles.css": APP_DIR / "styles.css",
    "/app.js": APP_DIR / "app.js",
}
VIDEO_EXTS = {".mp4", ".webm", ".m4v", ".mov", ".mkv", ".avi", ".ogv", ".mpeg", ".mpg", ".ts"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp", ".svg"}
IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".idea", ".vscode"}
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


def human_path(path: Path) -> str:
    return path.as_posix()


def is_hidden_path(relative: Path) -> bool:
    return any(part.startswith(".") for part in relative.parts)


def scan_media(root: Path) -> list[dict]:
    items: list[dict] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
        current_path = Path(current)
        for filename in files:
            absolute = current_path / filename
            try:
                relative = absolute.relative_to(root)
            except ValueError:
                continue
            if is_hidden_path(relative):
                continue
            ext = absolute.suffix.lower()
            media_type = "video" if ext in VIDEO_EXTS else "image" if ext in IMAGE_EXTS else None
            if not media_type:
                continue
            try:
                stat = absolute.stat()
            except OSError:
                continue
            rel_text = human_path(relative)
            folder = human_path(relative.parent) if relative.parent != Path(".") else ""
            items.append({
                "id": rel_text,
                "name": absolute.name,
                "path": rel_text,
                "folder": folder,
                "type": media_type,
                "ext": ext.lstrip("."),
                "size": stat.st_size,
                "modified": int(stat.st_mtime * 1000),
                "url": "/media/" + urllib.parse.quote(rel_text, safe="/"),
            })
    items.sort(key=lambda item: item["name"].casefold())
    return items


def safe_media_path(root: Path, encoded_relative: str) -> Path | None:
    relative_text = urllib.parse.unquote(encoded_relative).replace("\\", "/").lstrip("/")
    candidate = (root / relative_text).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def pick_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError("No free local port found")


def make_handler(root: Path):
    cache = {"items": [], "at": 0.0}
    cache_lock = threading.Lock()

    class LocalHubHandler(BaseHTTPRequestHandler):
        server_version = "LocalHub/1.0"

        def log_message(self, fmt: str, *args) -> None:
            if getattr(self.server, "quiet", False):
                return
            sys.stdout.write("[LocalHub] %s - %s\n" % (self.address_string(), fmt % args))

        def _headers(self, status: int, content_type: str, length: int | None = None, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache" if content_type.startswith("application/json") else "public, max-age=3600")
            self.send_header("X-Content-Type-Options", "nosniff")
            if length is not None:
                self.send_header("Content-Length", str(length))
            if extra:
                for key, value in extra.items():
                    self.send_header(key, str(value))
            self.end_headers()

        def _json(self, payload: dict, status: int = HTTPStatus.OK):
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._headers(status, "application/json; charset=utf-8", len(raw))
            self.wfile.write(raw)

        def _serve_static(self, file_path: Path):
            if not file_path.exists():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            raw = file_path.read_bytes()
            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            if file_path.suffix in {".html", ".css", ".js"}:
                content_type += "; charset=utf-8"
            self._headers(HTTPStatus.OK, content_type, len(raw))
            self.wfile.write(raw)

        def _serve_media(self, file_path: Path, head_only: bool = False):
            try:
                total = file_path.stat().st_size
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            range_header = self.headers.get("Range", "").strip()
            start, end = 0, max(0, total - 1)
            status = HTTPStatus.OK
            extra = {"Accept-Ranges": "bytes"}

            if range_header:
                match = RANGE_RE.fullmatch(range_header)
                if not match:
                    self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    return
                start_text, end_text = match.groups()
                if start_text:
                    start = int(start_text)
                    end = int(end_text) if end_text else end
                elif end_text:
                    suffix = int(end_text)
                    start = max(0, total - suffix)
                if start >= total or start > end:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{total}")
                    self.end_headers()
                    return
                end = min(end, total - 1)
                status = HTTPStatus.PARTIAL_CONTENT
                extra["Content-Range"] = f"bytes {start}-{end}/{total}"

            length = max(0, end - start + 1)
            self._headers(status, content_type, length, extra)
            if head_only:
                return
            try:
                with file_path.open("rb") as source:
                    source.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = source.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_HEAD(self):
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path.startswith("/media/"):
                media = safe_media_path(root, parsed.path[len("/media/"):])
                if media:
                    self._serve_media(media, head_only=True)
                    return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path

            if path == "/api/media":
                query = urllib.parse.parse_qs(parsed.query)
                force = query.get("rescan", ["0"])[0] == "1"
                with cache_lock:
                    now = time.time()
                    if force or not cache["items"] or now - cache["at"] > 3:
                        cache["items"] = scan_media(root)
                        cache["at"] = now
                    items = list(cache["items"])
                self._json({
                    "root": str(root),
                    "items": items,
                    "count": len(items),
                    "videos": sum(1 for item in items if item["type"] == "video"),
                    "images": sum(1 for item in items if item["type"] == "image"),
                })
                return

            if path.startswith("/media/"):
                media = safe_media_path(root, path[len("/media/"):])
                if media:
                    self._serve_media(media)
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                return

            static = STATIC_FILES.get(path)
            if static:
                self._serve_static(static)
                return

            self.send_error(HTTPStatus.NOT_FOUND)

    return LocalHubHandler


def main() -> int:
    parser = argparse.ArgumentParser(description="LocalHub local media gallery")
    parser.add_argument("--root", type=Path, default=APP_DIR, help="Media root folder (default: project folder)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8787, help="Preferred port (default: 8787)")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically")
    parser.add_argument("--quiet", action="store_true", help="Reduce request logs")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"[LocalHub] Media folder does not exist: {root}", file=sys.stderr)
        return 2

    port = pick_port(args.host, args.port)
    server = ThreadingHTTPServer((args.host, port), make_handler(root))
    server.daemon_threads = True
    server.quiet = args.quiet
    url = f"http://{args.host}:{port}/"

    print("=" * 58)
    print(" LocalHub - Local Media Gallery")
    print(f" Media folder : {root}")
    print(f" Open         : {url}")
    print(" Privacy      : local only; media is not uploaded")
    print(" Stop         : Ctrl+C")
    print("=" * 58)

    if not args.no_open:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        print("\n[LocalHub] Stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
