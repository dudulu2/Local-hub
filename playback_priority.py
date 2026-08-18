from __future__ import annotations

import os
import subprocess
import threading
import time

import media_probe
import smart_thumbnail
from io_scheduler import SCHEDULER

_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_THUMB_GATE = threading.BoundedSemaphore(2)
_HOVER_GATE = threading.BoundedSemaphore(1)


def _terminate(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    try:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=0.5)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _ffmpeg_frame(path, size: int, seek: float, timeout: int = 7):
    """Interruptible replacement for smart_thumbnail._ffmpeg_frame.

    The moment the media viewer becomes active, an in-flight thumbnail/hover
    FFmpeg is terminated so playback owns disk I/O immediately.
    """
    if SCHEDULER.busy():
        return None
    exe = media_probe.ffmpeg_exe()
    if not exe:
        return None
    command = [
        exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", f"{max(0.0, seek):.3f}", "-noaccurate_seek", "-i", str(path),
        "-an", "-sn", "-dn", "-frames:v", "1",
        "-vf", f"scale='min({size},iw)':-2",
        "-q:v", "8", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ]
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError:
        return None

    started = time.monotonic()
    while True:
        if SCHEDULER.busy():
            _terminate(process)
            return None
        if time.monotonic() - started > timeout:
            _terminate(process)
            return None
        try:
            out, _ = process.communicate(timeout=0.12)
            data = out or b""
            return data if process.returncode == 0 and len(data) > 300 else None
        except subprocess.TimeoutExpired:
            continue
        except Exception:
            _terminate(process)
            return None


def install() -> None:
    """Install bounded, non-queuing thumbnail/hover wrappers exactly once."""
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True

        original_thumbnail = smart_thumbnail.get_thumbnail
        original_hover = smart_thumbnail.get_hover_frame

        def get_thumbnail(path, size: int = 360):
            if SCHEDULER.busy() or not _THUMB_GATE.acquire(blocking=False):
                return None
            try:
                if SCHEDULER.busy():
                    return None
                return original_thumbnail(path, size)
            finally:
                _THUMB_GATE.release()

        def get_hover_frame(path, slot: int = 0, size: int = 360):
            if SCHEDULER.busy() or not _HOVER_GATE.acquire(blocking=False):
                return None
            try:
                if SCHEDULER.busy():
                    return None
                return original_hover(path, slot=slot, size=size)
            finally:
                _HOVER_GATE.release()

        smart_thumbnail._ffmpeg_frame = _ffmpeg_frame
        smart_thumbnail.get_thumbnail = get_thumbnail
        smart_thumbnail.get_hover_frame = get_hover_frame
