from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import subprocess
import threading
import urllib.parse
from http import HTTPStatus
from pathlib import Path

try:
    import imageio_ffmpeg  # Bundled into the Windows EXE; optional in source mode.
except Exception:  # pragma: no cover - source mode may use ffmpeg from PATH instead.
    imageio_ffmpeg = None


_THUMBNAIL_WORKERS = threading.BoundedSemaphore(2)
_KEY_LOCKS: dict[str, threading.Lock] = {}
_KEY_LOCKS_GUARD = threading.Lock()


def _ffmpeg_exe() -> str | None:
    if imageio_ffmpeg is not None:
        try:
            exe = imageio_ffmpeg.get_ffmpeg_exe()
            if exe and Path(exe).exists():
                return exe
        except Exception:
            pass
    return shutil.which("ffmpeg")


def _key_lock(key: str) -> threading.Lock:
    with _KEY_LOCKS_GUARD:
        lock = _KEY_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _KEY_LOCKS[key] = lock
        return lock


def _thumb_identity(store, media: Path) -> tuple[str, str, Path]:
    relative = media.relative_to(store.root).as_posix()
    stat = media.stat()
    identity = f"{relative}\n{stat.st_size}\n{stat.st_mtime_ns}"
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    cache_dir = store.data_dir / "thumbnails"
    return relative, key, cache_dir / f"{key}.jpg"


def _run_ffmpeg(exe: str, source: Path, target: Path, seek: str) -> bool:
    temp = target.with_suffix(".tmp.jpg")
    try:
        temp.unlink(missing_ok=True)
    except OSError:
        pass

    command = [
        exe,
        "-hide_banner",
        "-loglevel", "error",
        "-nostdin",
        "-ss", seek,
        "-i", str(source),
        "-an",
        "-sn",
        "-dn",
        "-frames:v", "1",
        "-vf", "scale=480:-2",
        "-q:v", "7",
        "-y",
        str(temp),
    ]
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "timeout": 18,
        "check": False,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        completed = subprocess.run(command, **kwargs)
        if completed.returncode == 0 and temp.exists() and temp.stat().st_size > 300:
            os.replace(temp, target)
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
    return False


def _ensure_thumbnail(store, media: Path, key: str, target: Path) -> Path | None:
    if target.exists() and target.stat().st_size > 300:
        return target

    exe = _ffmpeg_exe()
    if not exe:
        return None

    target.parent.mkdir(parents=True, exist_ok=True)
    lock = _key_lock(key)
    with lock:
        if target.exists() and target.stat().st_size > 300:
            return target
        # At most two videos are decoded at once, even if the browser requests a full viewport.
        with _THUMBNAIL_WORKERS:
            if _run_ffmpeg(exe, media, target, "1.0"):
                return target
            if _run_ffmpeg(exe, media, target, "0"):
                return target
    return None


def _inject_performance_script(index_text: str) -> str:
    marker = '<script src="/app.js"></script>'
    perf = '<script src="/performance.js"></script>'
    if perf in index_text:
        return index_text
    if marker in index_text:
        # performance.js must run first so it can stop card <video> elements from preloading.
        return index_text.replace(marker, perf + "\n  " + marker, 1)
    return index_text.replace("</body>", "  " + perf + "\n</body>", 1)


def install(server_module) -> None:
    """Install thumbnail/cache behavior without coupling server.py to optional FFmpeg deps."""
    original_make_handler = server_module.make_handler
    performance_js = Path(server_module.APP_DIR) / "performance.js"
    video_exts = set(server_module.VIDEO_EXTS)

    def make_handler(store):
        BaseHandler = original_make_handler(store)

        class PerformanceHandler(BaseHandler):
            def _serve_static(self, file_path: Path):
                if file_path.name == "index.html":
                    try:
                        raw = _inject_performance_script(file_path.read_text("utf-8")).encode("utf-8")
                    except OSError:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    self._headers(HTTPStatus.OK, "text/html; charset=utf-8", len(raw))
                    self.wfile.write(raw)
                    return
                return super()._serve_static(file_path)

            def _serve_thumbnail(self, media: Path):
                try:
                    _relative, key, target = _thumb_identity(store, media)
                except OSError:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return

                etag = f'"{key}"'
                if self.headers.get("If-None-Match") == etag and target.exists():
                    self.send_response(HTTPStatus.NOT_MODIFIED)
                    self.send_header("ETag", etag)
                    self.send_header("Cache-Control", "private, max-age=0, must-revalidate")
                    self.end_headers()
                    return

                result = _ensure_thumbnail(store, media, key, target)
                if result is None:
                    self._json({"ok": False, "error": "无法生成视频预览"}, HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                try:
                    raw = result.read_bytes()
                except OSError:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._headers(
                    HTTPStatus.OK,
                    mimetypes.guess_type(result.name)[0] or "image/jpeg",
                    len(raw),
                    {
                        "ETag": etag,
                        "Cache-Control": "private, max-age=0, must-revalidate",
                    },
                )
                self.wfile.write(raw)

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path == "/performance.js":
                    if performance_js.exists():
                        self._serve_static(performance_js)
                    else:
                        self.send_error(HTTPStatus.NOT_FOUND)
                    return

                if parsed.path == "/api/thumbnail":
                    query = urllib.parse.parse_qs(parsed.query)
                    relative = query.get("path", [""])[0]
                    try:
                        media = store.resolve_media(relative)
                    except (ValueError, FileNotFoundError):
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    if media.suffix.lower() not in video_exts:
                        self.send_error(HTTPStatus.BAD_REQUEST)
                        return
                    self._serve_thumbnail(media)
                    return

                return super().do_GET()

        return PerformanceHandler

    server_module.make_handler = make_handler
