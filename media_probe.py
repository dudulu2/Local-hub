from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from collections import OrderedDict
from pathlib import Path

try:
    import imageio_ffmpeg
except Exception:
    imageio_ffmpeg = None

_CACHE_LOCK = threading.RLock()
_CACHE: OrderedDict[str, tuple[float, dict]] = OrderedDict()
_CACHE_MAX = 96
_CACHE_TTL = 900.0

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_INPUT_RE = re.compile(r"Input #0,\s*([^,\n]+(?:,[^'\n]+)?)\s*,\s*from", re.IGNORECASE)
_VIDEO_RE = re.compile(r"Stream #\S+.*?Video:\s*([^,\s]+).*?(\d{2,5})x(\d{2,5})", re.IGNORECASE)
_AUDIO_RE = re.compile(r"Stream #\S+.*?Audio:\s*([^,\s]+)", re.IGNORECASE)
_FPS_RE = re.compile(r"(?:,|\s)(\d+(?:\.\d+)?)\s*fps(?:,|\s)", re.IGNORECASE)
_ROTATION_RE = re.compile(r"rotation of\s+(-?\d+(?:\.\d+)?)\s+degrees", re.IGNORECASE)
_ROTATE_TAG_RE = re.compile(r"rotate\s*:\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)


def ffmpeg_exe() -> str | None:
    if imageio_ffmpeg is not None:
        try:
            exe = imageio_ffmpeg.get_ffmpeg_exe()
            if exe and Path(exe).exists():
                return exe
        except Exception:
            pass
    return shutil.which("ffmpeg")


def _identity(path: Path) -> str:
    stat = path.stat()
    return f"{path}\n{stat.st_size}\n{stat.st_mtime_ns}"


def _cache_get(key: str) -> dict | None:
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if not hit:
            return None
        at, data = hit
        if now - at > _CACHE_TTL:
            _CACHE.pop(key, None)
            return None
        _CACHE.move_to_end(key)
        return dict(data)


def _cache_put(key: str, data: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic(), dict(data))
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def _duration_seconds(text: str) -> float | None:
    match = _DURATION_RE.search(text)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    try:
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError:
        return None


def _strategy(ext: str, video_codec: str, audio_codec: str) -> tuple[str, str, str]:
    ext = ext.lower()
    video = video_codec.lower()
    audio = audio_codec.lower()

    if not video:
        return "unsupported", "transcode", "没有识别到视频轨道"

    native_audio = not audio or audio in {"aac", "mp3", "opus", "vorbis", "flac"}

    if ext in {".mp4", ".m4v"} and video == "h264" and native_audio:
        return "native", "remux", "H.264 MP4 通常可由浏览器直接播放"
    if ext == ".webm" and video in {"vp8", "vp9", "av1"} and native_audio:
        return "native", "transcode", "WebM 编码通常可由浏览器直接播放"
    if ext == ".mov" and video == "h264":
        return "conditional", "remux", "MOV/H.264 通常能播，但部分文件索引会影响时间轴"
    if video in {"hevc", "h265"}:
        return "conditional", "transcode", "HEVC 是否能直接播放取决于 Windows 与浏览器解码器"
    if video == "h264":
        return "compat", "remux", "视频编码可用，但当前容器更适合先无损封装为 MP4"
    if video in {"vp8", "vp9", "av1"} and ext not in {".webm", ".mp4", ".m4v"}:
        return "compat", "transcode", "当前容器不适合浏览器直接播放"
    return "compat", "transcode", f"{video_codec or '未知编码'} 建议转换为 H.264/AAC 后播放"


def probe_media(path: Path, timeout: int = 8) -> dict:
    try:
        key = _identity(path)
        stat = path.stat()
    except OSError:
        return {"ok": False, "error": "文件不存在"}

    cached = _cache_get(key)
    if cached is not None:
        return cached

    exe = ffmpeg_exe()
    if not exe:
        data = {
            "ok": False,
            "error": "FFmpeg 不可用",
            "ext": path.suffix.lower().lstrip("."),
            "size": stat.st_size,
        }
        _cache_put(key, data)
        return data

    command = [
        exe,
        "-hide_banner",
        "-nostdin",
        "-probesize", "4M",
        "-analyzeduration", "4000000",
        "-i", str(path),
    ]
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace", timeout=timeout, check=False)
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        result = subprocess.run(command, **kwargs)
        text = result.stderr or ""
    except (OSError, subprocess.SubprocessError) as exc:
        data = {"ok": False, "error": str(exc), "ext": path.suffix.lower().lstrip("."), "size": stat.st_size}
        _cache_put(key, data)
        return data

    duration = _duration_seconds(text)
    input_match = _INPUT_RE.search(text)
    video_match = _VIDEO_RE.search(text)
    audio_match = _AUDIO_RE.search(text)
    fps_match = _FPS_RE.search(video_match.group(0) if video_match else text)
    rotation_match = _ROTATION_RE.search(text) or _ROTATE_TAG_RE.search(text)

    container = input_match.group(1).strip() if input_match else path.suffix.lower().lstrip(".")
    video_codec = video_match.group(1).lower() if video_match else ""
    audio_codec = audio_match.group(1).lower() if audio_match else ""
    width = int(video_match.group(2)) if video_match else 0
    height = int(video_match.group(3)) if video_match else 0
    try:
        fps = float(fps_match.group(1)) if fps_match else None
    except ValueError:
        fps = None
    try:
        rotation = float(rotation_match.group(1)) if rotation_match else 0.0
    except ValueError:
        rotation = 0.0
    normalized_rotation = int(round(rotation / 90.0) * 90) % 360 if rotation else 0
    display_width, display_height = width, height
    if normalized_rotation in {90, 270}:
        display_width, display_height = height, width

    strategy, compat_mode, reason = _strategy(path.suffix.lower(), video_codec, audio_codec)
    data = {
        "ok": bool(video_codec),
        "path": path.name,
        "ext": path.suffix.lower().lstrip("."),
        "container": container,
        "videoCodec": video_codec or "unknown",
        "audioCodec": audio_codec or "none",
        "width": width,
        "height": height,
        "displayWidth": display_width,
        "displayHeight": display_height,
        "rotation": normalized_rotation,
        "fps": fps,
        "duration": duration,
        "size": stat.st_size,
        "strategy": strategy,
        "compatMode": compat_mode,
        "reason": reason,
    }
    _cache_put(key, data)
    return data


def clear_probe_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
