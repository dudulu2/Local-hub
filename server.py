#!/usr/bin/env python3
"""LocalHub - zero-dependency local media gallery and organizer.

Run this file from the folder that contains your media, or pass --root PATH.
The server binds to 127.0.0.1 by default. Media never leaves the computer.
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
IGNORED_DIRS = {".git", ".localhub", "__pycache__", "node_modules", ".idea", ".vscode"}
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")
INVALID_WINDOWS_CHARS = set('<>:"/\\|?*')
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
MAX_BODY = 256 * 1024


class MediaStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.data_dir = self.root / ".localhub"
        self.metadata_path = self.data_dir / "metadata.json"
        self.lock = threading.RLock()
        self._metadata = self._load_metadata()

    def _load_metadata(self) -> dict:
        try:
            raw = json.loads(self.metadata_path.read_text("utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("items"), dict):
                return raw
        except (OSError, json.JSONDecodeError):
            pass
        return {"version": 1, "items": {}}

    def _save_metadata(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temp = self.metadata_path.with_suffix(".tmp")
        temp.write_text(json.dumps(self._metadata, ensure_ascii=False, indent=2), "utf-8")
        os.replace(temp, self.metadata_path)

    @staticmethod
    def _clean_tags(tags) -> list[str]:
        if not isinstance(tags, list):
            raise ValueError("tags 必须是数组")
        result: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            text = str(tag).strip()
            if not text:
                continue
            if len(text) > 32:
                raise ValueError("单个标签不能超过 32 个字符")
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
            if len(result) > 40:
                raise ValueError("单个媒体最多 40 个标签")
        return result

    def tags_for(self, rel: str) -> list[str]:
        with self.lock:
            meta = self._metadata["items"].get(rel, {})
            tags = meta.get("tags", [])
            return list(tags) if isinstance(tags, list) else []

    def set_tags(self, paths: list[str], tags: list[str], mode: str = "replace") -> None:
        clean = self._clean_tags(tags)
        if mode not in {"replace", "add", "remove"}:
            raise ValueError("未知标签操作")
        with self.lock:
            for rel in paths:
                self.resolve_media(rel)
                entry = dict(self._metadata["items"].get(rel, {}))
                existing = self._clean_tags(entry.get("tags", []))
                if mode == "replace":
                    merged = clean
                elif mode == "add":
                    merged = self._clean_tags(existing + clean)
                else:
                    remove = {tag.casefold() for tag in clean}
                    merged = [tag for tag in existing if tag.casefold() not in remove]
                if merged:
                    entry["tags"] = merged
                    self._metadata["items"][rel] = entry
                else:
                    entry.pop("tags", None)
                    if entry:
                        self._metadata["items"][rel] = entry
                    else:
                        self._metadata["items"].pop(rel, None)
            self._save_metadata()

    def _move_metadata(self, mapping: dict[str, str]) -> None:
        changed = False
        items = self._metadata["items"]
        for old, new in mapping.items():
            if old == new:
                continue
            if old in items:
                items[new] = items.pop(old)
                changed = True
        if changed:
            self._save_metadata()

    def resolve_media(self, rel: str) -> Path:
        text = str(rel).replace("\\", "/").lstrip("/")
        candidate = (self.root / text).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("路径超出媒体库") from exc
        if not candidate.is_file():
            raise FileNotFoundError(text)
        ext = candidate.suffix.lower()
        if ext not in VIDEO_EXTS and ext not in IMAGE_EXTS:
            raise ValueError("不是可管理的媒体文件")
        return candidate

    def resolve_folder(self, folder: str, create: bool = False) -> Path:
        text = str(folder or "").replace("\\", "/").strip("/")
        candidate = (self.root / text).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("目标文件夹超出媒体库") from exc
        if candidate == self.data_dir or self.data_dir in candidate.parents:
            raise ValueError("不能移动到 LocalHub 数据目录")
        if create:
            candidate.mkdir(parents=True, exist_ok=True)
        if not candidate.exists() or not candidate.is_dir():
            raise FileNotFoundError(f"目标文件夹不存在：{text or '根目录'}")
        return candidate

    @staticmethod
    def validate_stem(stem: str) -> str:
        value = str(stem).strip()
        if not value:
            raise ValueError("文件名不能为空")
        if value.endswith(".") or value.endswith(" "):
            raise ValueError("文件名不能以点或空格结尾")
        if any(ord(ch) < 32 or ch in INVALID_WINDOWS_CHARS for ch in value):
            raise ValueError('文件名不能包含 <>:"/\\|?* 等字符')
        if value.split(".", 1)[0].upper() in WINDOWS_RESERVED:
            raise ValueError("该文件名为 Windows 保留名称")
        if len(value) > 180:
            raise ValueError("文件名过长")
        return value

    def rename(self, rel: str, stem: str) -> dict:
        with self.lock:
            source = self.resolve_media(rel)
            clean_stem = self.validate_stem(stem)
            target = source.with_name(clean_stem + source.suffix)
            if target == source:
                return {"old": rel, "new": rel}
            if target.exists():
                raise FileExistsError(f"已存在同名文件：{target.name}")
            source.rename(target)
            new_rel = target.relative_to(self.root).as_posix()
            self._move_metadata({rel: new_rel})
            return {"old": rel, "new": new_rel}

    def move(self, paths: list[str], folder: str, create: bool = False) -> list[dict]:
        with self.lock:
            target_dir = self.resolve_folder(folder, create=create)
            sources: list[tuple[str, Path, Path]] = []
            seen_targets: set[Path] = set()
            for rel in paths:
                source = self.resolve_media(rel)
                target = target_dir / source.name
                if target.resolve() == source.resolve():
                    sources.append((rel, source, target))
                    continue
                if target.exists() or target in seen_targets:
                    raise FileExistsError(f"目标位置已存在同名文件：{target.name}")
                seen_targets.add(target)
                sources.append((rel, source, target))

            moved: list[dict] = []
            mapping: dict[str, str] = {}
            for rel, source, target in sources:
                if source.resolve() != target.resolve():
                    source.rename(target)
                new_rel = target.relative_to(self.root).as_posix()
                moved.append({"old": rel, "new": new_rel})
                mapping[rel] = new_rel
            self._move_metadata(mapping)
            return moved

    def scan(self) -> list[dict]:
        items: list[dict] = []
        with self.lock:
            metadata_items = dict(self._metadata.get("items", {}))
        for current, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
            current_path = Path(current)
            for filename in files:
                absolute = current_path / filename
                try:
                    relative = absolute.relative_to(self.root)
                except ValueError:
                    continue
                if any(part.startswith(".") for part in relative.parts):
                    continue
                ext = absolute.suffix.lower()
                media_type = "video" if ext in VIDEO_EXTS else "image" if ext in IMAGE_EXTS else None
                if not media_type:
                    continue
                try:
                    stat = absolute.stat()
                except OSError:
                    continue
                rel_text = relative.as_posix()
                folder = relative.parent.as_posix() if relative.parent != Path(".") else ""
                tags = metadata_items.get(rel_text, {}).get("tags", [])
                items.append({
                    "id": rel_text,
                    "name": absolute.name,
                    "stem": absolute.stem,
                    "path": rel_text,
                    "folder": folder,
                    "type": media_type,
                    "ext": ext.lstrip("."),
                    "size": stat.st_size,
                    "modified": int(stat.st_mtime * 1000),
                    "tags": tags if isinstance(tags, list) else [],
                    "url": "/media/" + urllib.parse.quote(rel_text, safe="/"),
                })
        items.sort(key=lambda item: item["name"].casefold())
        return items


def pick_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError("No free local port found")


def make_handler(store: MediaStore):
    cache = {"items": [], "at": 0.0}
    cache_lock = threading.Lock()

    def invalidate_cache() -> None:
        with cache_lock:
            cache["items"] = []
            cache["at"] = 0.0

    class LocalHubHandler(BaseHTTPRequestHandler):
        server_version = "LocalHub/1.1"

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

        def _error_json(self, status: int, message: str):
            self._json({"ok": False, "error": message}, status)

        def _read_json(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("无效请求长度") from exc
            if length <= 0 or length > MAX_BODY:
                raise ValueError("请求内容为空或过大")
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("无效 JSON") from exc
            if not isinstance(data, dict):
                raise ValueError("请求必须是对象")
            return data

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
                try:
                    media = store.resolve_media(urllib.parse.unquote(parsed.path[len("/media/"):]))
                except (ValueError, FileNotFoundError):
                    media = None
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
                        cache["items"] = store.scan()
                        cache["at"] = now
                    items = list(cache["items"])
                tag_counts: dict[str, int] = {}
                for item in items:
                    for tag in item.get("tags", []):
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1
                self._json({
                    "root": str(store.root),
                    "items": items,
                    "count": len(items),
                    "videos": sum(1 for item in items if item["type"] == "video"),
                    "images": sum(1 for item in items if item["type"] == "image"),
                    "tags": [{"name": name, "count": count} for name, count in sorted(tag_counts.items(), key=lambda x: (-x[1], x[0].casefold()))],
                })
                return

            if path.startswith("/media/"):
                try:
                    media = store.resolve_media(urllib.parse.unquote(path[len("/media/"):]))
                except (ValueError, FileNotFoundError):
                    media = None
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

        def do_POST(self):
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path != "/api/manage":
                self._error_json(HTTPStatus.NOT_FOUND, "接口不存在")
                return
            try:
                data = self._read_json()
                action = str(data.get("action", ""))

                if action == "set_tags":
                    paths = data.get("paths")
                    if not isinstance(paths, list) or not paths:
                        raise ValueError("请选择至少一个媒体")
                    store.set_tags([str(p) for p in paths], data.get("tags", []), str(data.get("mode", "replace")))
                    invalidate_cache()
                    self._json({"ok": True})
                    return

                if action == "rename":
                    result = store.rename(str(data.get("path", "")), str(data.get("stem", "")))
                    invalidate_cache()
                    self._json({"ok": True, "moved": [result]})
                    return

                if action == "move":
                    paths = data.get("paths")
                    if not isinstance(paths, list) or not paths:
                        raise ValueError("请选择至少一个媒体")
                    results = store.move(
                        [str(p) for p in paths],
                        str(data.get("folder", "")),
                        create=bool(data.get("create", False)),
                    )
                    invalidate_cache()
                    self._json({"ok": True, "moved": results})
                    return

                self._error_json(HTTPStatus.BAD_REQUEST, "未知管理操作")
            except FileExistsError as exc:
                self._error_json(HTTPStatus.CONFLICT, str(exc))
            except FileNotFoundError as exc:
                self._error_json(HTTPStatus.NOT_FOUND, str(exc))
            except (ValueError, OSError) as exc:
                self._error_json(HTTPStatus.BAD_REQUEST, str(exc))

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

    store = MediaStore(root)
    port = pick_port(args.host, args.port)
    server = ThreadingHTTPServer((args.host, port), make_handler(store))
    server.daemon_threads = True
    server.quiet = args.quiet
    url = f"http://{args.host}:{port}/"

    print("=" * 58)
    print(" LocalHub - Local Media Gallery")
    print(f" Media folder : {root}")
    print(f" Open         : {url}")
    print(" Organizer    : tags / rename / move enabled")
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
