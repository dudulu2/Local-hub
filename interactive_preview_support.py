from __future__ import annotations

import os
import subprocess
import threading
import time
import urllib.parse
from collections import OrderedDict
from http import HTTPStatus

import media_probe
import smart_thumbnail
from io_scheduler import SCHEDULER

_CACHE_LOCK = threading.RLock()
_CACHE: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
_CACHE_MAX = 24
_CACHE_TTL = 300.0
_WORKER = threading.BoundedSemaphore(1)
_RATIOS = (0.08, 0.22, 0.38, 0.54, 0.70, 0.86)


def _cache_key(path, slot: int) -> str:
    stat = path.stat()
    return f"{path}\n{stat.st_size}\n{stat.st_mtime_ns}\n{slot}"


def _cache_get(key: str) -> bytes | None:
    now = time.monotonic()
    with _CACHE_LOCK:
        row = _CACHE.get(key)
        if not row:
            return None
        at, data = row
        if now - at > _CACHE_TTL:
            _CACHE.pop(key, None)
            return None
        _CACHE.move_to_end(key)
        return data


def _cache_put(key: str, data: bytes) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic(), data)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def _seek_for(path, slot: int) -> float:
    probe = media_probe.probe_media(path)
    duration = probe.get("duration") if probe.get("ok") else 0
    if isinstance(duration, (int, float)) and duration > 1.5:
        return max(0.25, min(float(duration) - 0.35, float(duration) * _RATIOS[slot]))
    return (3.0, 8.0, 18.0, 36.0, 72.0, 120.0)[slot]


def _terminate(process: subprocess.Popen) -> None:
    try:
        process.terminate()
        process.wait(timeout=0.5)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _interactive_frame(path, slot: int) -> bytes | None:
    snapshot = SCHEDULER.snapshot()
    if snapshot.get("seeking"):
        return None
    try:
        key = _cache_key(path, slot)
    except OSError:
        return None
    hit = _cache_get(key)
    if hit is not None:
        return hit

    # When playback is paused, reuse the normal six-frame cache/extractor. When
    # playback is active, explicit recommendation hover is allowed a tiny,
    # low-priority 240px extraction so the UI can still feel alive.
    if not snapshot.get("playing"):
        data = smart_thumbnail.get_hover_frame(path, slot=slot, size=300)
        if data:
            _cache_put(key, data)
        return data

    exe = media_probe.ffmpeg_exe()
    if not exe:
        return None
    with _WORKER:
        if SCHEDULER.snapshot().get("seeking"):
            return None
        hit = _cache_get(key)
        if hit is not None:
            return hit
        command = [
            exe, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-ss", f"{_seek_for(path, slot):.3f}", "-noaccurate_seek", "-i", str(path),
            "-an", "-sn", "-dn", "-frames:v", "1",
            "-vf", "scale='min(240,iw)':-2",
            "-q:v", "10", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
        ]
        kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if os.name == "nt":
            kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
            )
        try:
            process = subprocess.Popen(command, **kwargs)
        except OSError:
            return None
        started = time.monotonic()
        while True:
            if SCHEDULER.snapshot().get("seeking"):
                _terminate(process)
                return None
            if time.monotonic() - started > 4.0:
                _terminate(process)
                return None
            try:
                out, _ = process.communicate(timeout=0.12)
                data = out or b""
                if process.returncode == 0 and len(data) > 300:
                    _cache_put(key, data)
                    return data
                return None
            except subprocess.TimeoutExpired:
                continue
            except Exception:
                _terminate(process)
                return None


def install(server_module) -> None:
    original_make_handler = server_module.make_handler
    video_exts = set(server_module.VIDEO_EXTS)

    def make_handler(store):
        BaseHandler = original_make_handler(store)

        class InteractivePreviewHandler(BaseHandler):
            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path != "/api/smart/hover-interactive":
                    return super().do_GET()
                query = urllib.parse.parse_qs(parsed.query)
                relative = query.get("path", [""])[0]
                try:
                    slot = int(query.get("slot", ["0"])[0] or 0)
                except ValueError:
                    slot = 0
                slot = max(0, min(5, slot))
                try:
                    media = store.resolve_media(relative)
                except (ValueError, FileNotFoundError):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                if media.suffix.lower() not in video_exts:
                    self.send_error(HTTPStatus.BAD_REQUEST)
                    return
                data = _interactive_frame(media, slot)
                if not data:
                    self.send_response(HTTPStatus.NO_CONTENT)
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    return
                self._headers(
                    HTTPStatus.OK,
                    "image/jpeg",
                    len(data),
                    {"Cache-Control": "no-store", "X-LocalHub-Preview": f"interactive-{slot}"},
                )
                self.wfile.write(data)

        return InteractivePreviewHandler

    server_module.make_handler = make_handler
