from __future__ import annotations

import atexit
import json
import os
import queue
import subprocess
import threading
import urllib.parse
from http import HTTPStatus
from pathlib import Path

import media_probe
import smart_thumbnail

HOVER_SLOTS = 6

_ENGINE_LOCK = threading.RLock()
_ENGINE_PROCESS: subprocess.Popen | None = None
_ENGINE_BASE = ""
_ENGINE_ROOT: Path | None = None
_ENGINE_LOG = None


def _stop_engine() -> None:
    global _ENGINE_PROCESS, _ENGINE_BASE, _ENGINE_ROOT, _ENGINE_LOG
    with _ENGINE_LOCK:
        process = _ENGINE_PROCESS
        _ENGINE_PROCESS = None
        _ENGINE_BASE = ""
        _ENGINE_ROOT = None
        if process is not None:
            try:
                if process.stdin:
                    process.stdin.close()
            except Exception:
                pass
            try:
                process.terminate()
                process.wait(timeout=1.0)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=0.5)
                except Exception:
                    pass
        if _ENGINE_LOG is not None:
            try:
                _ENGINE_LOG.close()
            except Exception:
                pass
            _ENGINE_LOG = None


atexit.register(_stop_engine)


def _readline_with_timeout(stream, timeout: float = 4.0) -> str:
    result: queue.Queue[str] = queue.Queue(maxsize=1)

    def reader() -> None:
        try:
            result.put(stream.readline())
        except Exception:
            result.put("")

    threading.Thread(target=reader, name="LocalHubMediaEngineHandshake", daemon=True).start()
    try:
        return result.get(timeout=timeout)
    except queue.Empty:
        return ""


def _engine_executable(app_dir: Path) -> Path:
    candidates = [
        app_dir / "localhub-media-engine.exe",
        app_dir / "localhub-media-engine",
        app_dir / "build_tools" / "localhub-media-engine.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _start_engine(root: Path, app_dir: Path) -> str:
    global _ENGINE_PROCESS, _ENGINE_BASE, _ENGINE_ROOT, _ENGINE_LOG
    root = root.resolve()
    with _ENGINE_LOCK:
        if (
            _ENGINE_PROCESS is not None
            and _ENGINE_PROCESS.poll() is None
            and _ENGINE_ROOT == root
            and _ENGINE_BASE
        ):
            return _ENGINE_BASE

        _stop_engine()
        engine = _engine_executable(app_dir)
        if not engine.exists():
            raise RuntimeError(f"Player V4 媒体引擎缺失：{engine}")
        ffmpeg = media_probe.ffmpeg_exe()
        if not ffmpeg:
            raise RuntimeError("Player V4 找不到 FFmpeg")

        log_dir = root / ".localhub"
        log_dir.mkdir(parents=True, exist_ok=True)
        _ENGINE_LOG = (log_dir / "media-engine.log").open("a", encoding="utf-8")
        kwargs = dict(
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=_ENGINE_LOG,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        process = subprocess.Popen(
            [
                str(engine),
                "--root", str(root),
                "--ffmpeg", str(ffmpeg),
                "--port", "0",
            ],
            **kwargs,
        )
        if process.stdout is None:
            process.kill()
            raise RuntimeError("Player V4 媒体引擎没有启动输出")
        line = _readline_with_timeout(process.stdout, 4.0).strip()
        if not line:
            try:
                process.kill()
            except OSError:
                pass
            raise RuntimeError("Player V4 媒体引擎启动超时")
        try:
            payload = json.loads(line)
            port = int(payload.get("port", 0))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            try:
                process.kill()
            except OSError:
                pass
            raise RuntimeError(f"Player V4 媒体引擎握手失败：{line[:160]}") from exc
        if not (1 <= port <= 65535):
            try:
                process.kill()
            except OSError:
                pass
            raise RuntimeError("Player V4 媒体引擎返回无效端口")

        _ENGINE_PROCESS = process
        _ENGINE_ROOT = root
        _ENGINE_BASE = f"http://127.0.0.1:{port}"
        return _ENGINE_BASE


def _inject_player_v4(html: bytes) -> bytes:
    text = html.decode("utf-8")
    if "player_v4.js" in text:
        return html
    head = (
        '<link rel="stylesheet" href="/vendor/video-js.min.css">\n'
        '<link rel="stylesheet" href="/player_v4.css">\n'
    )
    body = (
        '<script src="/vendor/video.min.js"></script>\n'
        '<script src="/player_v4.js"></script>\n'
    )
    if "</head>" in text:
        text = text.replace("</head>", head + "</head>", 1)
    if "</body>" in text:
        text = text.replace("</body>", body + "</body>", 1)
    return text.encode("utf-8")


def install(server_module) -> None:
    """Install preview endpoints and Player V4 without changing the stable catalog core."""
    original_make_handler = server_module.make_handler
    original_server_close = server_module.ThreadingHTTPServer.server_close
    video_exts = set(server_module.VIDEO_EXTS)
    app_dir = Path(server_module.APP_DIR)

    # The media engine owns a log handle and a child process. Tie both to the
    # LocalHub HTTP server lifetime so tests, restarts and tray exits release
    # Windows file handles deterministically instead of relying only on atexit.
    def server_close(self):
        try:
            _stop_engine()
        finally:
            return original_server_close(self)

    server_module.ThreadingHTTPServer.server_close = server_close

    server_module.STATIC_FILES["/player_v4.js"] = app_dir / "player_v4.js"
    server_module.STATIC_FILES["/player_v4.css"] = app_dir / "player_v4.css"
    server_module.STATIC_FILES["/vendor/video.min.js"] = app_dir / "vendor" / "video.min.js"
    server_module.STATIC_FILES["/vendor/video-js.min.css"] = app_dir / "vendor" / "video-js.min.css"
    server_module.STATIC_FILES["/vendor/VIDEOJS-LICENSE.txt"] = app_dir / "vendor" / "VIDEOJS-LICENSE.txt"

    def make_handler(store):
        BaseHandler = original_make_handler(store)
        engine_error = ""
        try:
            engine_base = _start_engine(store.root, app_dir)
        except Exception as exc:
            engine_base = ""
            engine_error = str(exc)

        class PreviewHandler(BaseHandler):
            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(parsed.query)

                if parsed.path in {"/", "/index.html"}:
                    target = app_dir / "smart_index.html"
                    if not target.exists():
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    raw = _inject_player_v4(target.read_bytes())
                    self._headers(
                        HTTPStatus.OK,
                        "text/html; charset=utf-8",
                        len(raw),
                        {"Cache-Control": "no-store"},
                    )
                    self.wfile.write(raw)
                    return

                if parsed.path == "/api/media-engine":
                    if engine_base:
                        return self._send_json({"ok": True, "baseUrl": engine_base, "player": "v4"})
                    return self._send_json({"ok": False, "error": engine_error or "媒体引擎不可用"}, 503)

                if parsed.path == "/api/smart/hover":
                    relative = query.get("path", [""])[0]
                    try:
                        slot = int(query.get("slot", ["0"])[0] or 0)
                    except ValueError:
                        slot = 0
                    slot = max(0, min(HOVER_SLOTS - 1, slot))
                    try:
                        media = store.resolve_media(relative)
                    except (ValueError, FileNotFoundError):
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    if media.suffix.lower() not in video_exts:
                        self.send_error(HTTPStatus.BAD_REQUEST)
                        return
                    data = smart_thumbnail.get_hover_frame(media, slot=slot, size=360)
                    if not data:
                        self.send_response(HTTPStatus.NO_CONTENT)
                        self.send_header("Cache-Control", "no-store")
                        self.end_headers()
                        return
                    self._headers(
                        HTTPStatus.OK,
                        "image/jpeg",
                        len(data),
                        {"Cache-Control": "no-store", "X-LocalHub-Preview": f"hover-{slot}"},
                    )
                    self.wfile.write(data)
                    return

                if parsed.path == "/api/smart/preview-status":
                    raw = json.dumps(
                        {
                            "ok": True,
                            "ffmpeg": smart_thumbnail.ffmpeg_available(),
                            "hoverWorkers": 1,
                            "hoverSlots": HOVER_SLOTS,
                            "player": "v4",
                            "mediaEngine": bool(engine_base),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    self._headers(HTTPStatus.OK, "application/json; charset=utf-8", len(raw), {"Cache-Control": "no-store"})
                    self.wfile.write(raw)
                    return

                return super().do_GET()

        return PreviewHandler

    server_module.make_handler = make_handler
