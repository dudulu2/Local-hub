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
# The player, orientation patch, hover code and Auto Tag may ask for the same
# metadata at nearly the same time. Serialize the expensive FFmpeg probe and
# re-check the cache after acquiring the slot so duplicate requests collapse to
# one disk read instead of spawning several FFmpeg processes.
_PROBE_EXECUTOR = threading.BoundedSemaphore(1)

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_INPUT_RE = re.compile(r"Input #0,\s*([^,\n]+(?:,[^'\n]+)?)\s*,\s*from", re.IGNORECASE)
_VIDEO_RE = re.compile(r"Stream #\S+.*?Video:\s*([^,\s]+).*?(\d{2,5})x(\d{2,5})", re.IGNORECASE)
_VIDEO_LINE_RE = re.compile(r"Stream #\S+[^\n]*Video:[^\n]*", re.IGNORECASE)
_AUDIO_RE = re.compile(r"Stream #\S+.*?Audio:\s*([^,\s]+)", re.IGNORECASE)
_FPS_RE = re.compile(r"(?:,|\s)(\d+(?:\.\d+)?)\s*fps(?:,|\s)", re.IGNORECASE)
_TBR_RE = re.compile(r"(?:,|\s)(\d+(?:\.\d+)?)\s*tbr(?:,|\s)", re.IGNORECASE)
_ROTATION_RE = re.compile(r"rotation of\s+(-?\d+(?:\.\d+)?)\s+degrees", re.IGNORECASE)
_ROTATE_TAG_RE = re.compile(r"rotate\s*:\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)

_LEGACY_TIMELINE_EXTS = {".avi", ".mpg", ".mpeg", ".ts"}
_TIMELINE_WARNING_PATTERNS = (
    (re.compile(r"non[- ]?monoton(?:ous|ically increasing).*dts", re.IGNORECASE), "DTS 时间戳非单调"),
    (re.compile(r"invalid dts|invalid pts", re.IGNORECASE), "存在无效时间戳"),
    (re.compile(r"timestamp discontinuity|discontinuity", re.IGNORECASE), "时间戳存在跳变"),
    (re.compile(r"estimating duration from bitrate", re.IGNORECASE), "时长只能由码率估算"),
    (re.compile(r"could not find codec parameters", re.IGNORECASE), "流参数不完整"),
    (re.compile(r"corrupt|corrupted", re.IGNORECASE), "媒体流报告损坏数据"),
)


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


def _clean_rate(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not (0.5 <= value <= 240.0):
        return None
    return value


def _timeline_risks(
    *,
    ext: str,
    text: str,
    width: int,
    height: int,
    duration: float | None,
    fps: float | None,
    fps_source: str,
) -> list[str]:
    risks: list[str] = []
    if width <= 0 or height <= 0:
        risks.append("无法确认视频尺寸")
    if duration is None or duration <= 0:
        risks.append("无法确认可靠时长")
    if fps is None:
        risks.append("无法确认可靠帧率")
    elif fps_source != "fps":
        risks.append("帧率只能由容器时基推断")
    for pattern, label in _TIMELINE_WARNING_PATTERNS:
        if pattern.search(text) and label not in risks:
            risks.append(label)
    if ext in _LEGACY_TIMELINE_EXTS and "传统容器时间轴需整理" not in risks:
        risks.append("传统容器时间轴需整理")
    return risks


def _strategy(
    ext: str,
    video_codec: str,
    audio_codec: str,
    *,
    timeline_risk: bool = False,
) -> tuple[str, str, str]:
    ext = ext.lower()
    video = video_codec.lower()
    audio = audio_codec.lower()

    if not video:
        return "unsupported", "transcode", "没有识别到视频轨道"

    native_audio = not audio or audio in {"aac", "mp3", "opus", "vorbis", "flac"}

    if ext in _LEGACY_TIMELINE_EXTS:
        return "compat", "transcode", "传统视频容器先重建时间轴并转换为浏览器稳定格式"

    if ext in {".mp4", ".m4v"} and video == "h264" and native_audio:
        if timeline_risk:
            return "compat", "transcode", "MP4 编码可用，但媒体时间轴信息不完整，先重建时间戳再播放"
        return "native", "remux", "H.264 MP4 且时间轴信息完整，可由浏览器直接播放"
    if ext == ".webm" and video in {"vp8", "vp9", "av1"} and native_audio:
        if timeline_risk:
            return "compat", "transcode", "WebM 时间轴信息不完整，先生成稳定兼容版本"
        return "native", "transcode", "WebM 编码与时间轴信息适合浏览器直接播放"
    if ext == ".mov" and video == "h264":
        if timeline_risk:
            return "compat", "transcode", "MOV 时间轴信息异常，重编码比单纯换容器更可靠"
        return "conditional", "remux", "MOV/H.264 通常能播，但部分文件索引会影响时间轴"
    if video in {"hevc", "h265"}:
        return "conditional", "transcode", "HEVC 是否能直接播放取决于 Windows 与浏览器解码器"
    if video == "h264":
        if timeline_risk:
            return "compat", "transcode", "H.264 流存在时间轴风险，需要重建时间戳"
        return "compat", "remux", "视频编码可用，但当前容器更适合先无损封装为 MP4"
    if video in {"vp8", "vp9", "av1"} and ext not in {".webm", ".mp4", ".m4v"}:
        return "compat", "transcode", "当前容器不适合浏览器直接播放"
    return "compat", "transcode", f"{video_codec or '未知编码'} 建议转换为 H.264/AAC 后播放"


def _probe_uncached(path: Path, stat, timeout: int, key: str) -> dict:
    exe = ffmpeg_exe()
    if not exe:
        data = {
            "ok": False,
            "error": "FFmpeg 不可用",
            "ext": path.suffix.lower().lstrip("."),
            "size": stat.st_size,
            "browserSafe": False,
            "timelineRisk": True,
            "riskReasons": ["无法检查媒体时间轴"],
            "strategy": "unsupported",
            "compatMode": "transcode",
            "reason": "媒体信息无法可靠读取，禁止直接交给浏览器解码",
        }
        _cache_put(key, data)
        return data

    command = [
        exe,
        "-hide_banner",
        "-nostdin",
        "-probesize", "6M",
        "-analyzeduration", "5000000",
        "-i", str(path),
    ]
    kwargs = dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        )

    try:
        result = subprocess.run(command, **kwargs)
        text = result.stderr or ""
    except (OSError, subprocess.SubprocessError) as exc:
        data = {
            "ok": False,
            "error": str(exc),
            "ext": path.suffix.lower().lstrip("."),
            "size": stat.st_size,
            "browserSafe": False,
            "timelineRisk": True,
            "riskReasons": ["媒体探测超时或失败"],
            "strategy": "unsupported",
            "compatMode": "transcode",
            "reason": "媒体信息无法可靠读取，禁止直接交给浏览器解码",
        }
        _cache_put(key, data)
        return data

    duration = _duration_seconds(text)
    input_match = _INPUT_RE.search(text)
    video_match = _VIDEO_RE.search(text)
    video_line_match = _VIDEO_LINE_RE.search(text)
    audio_match = _AUDIO_RE.search(text)
    stream_text = video_line_match.group(0) if video_line_match else (video_match.group(0) if video_match else text)
    fps_match = _FPS_RE.search(stream_text)
    tbr_match = _TBR_RE.search(stream_text)
    rotation_match = _ROTATION_RE.search(text) or _ROTATE_TAG_RE.search(text)

    container = input_match.group(1).strip() if input_match else path.suffix.lower().lstrip(".")
    video_codec = video_match.group(1).lower() if video_match else ""
    audio_codec = audio_match.group(1).lower() if audio_match else ""
    width = int(video_match.group(2)) if video_match else 0
    height = int(video_match.group(3)) if video_match else 0

    fps = None
    fps_source = ""
    if fps_match:
        try:
            fps = _clean_rate(float(fps_match.group(1)))
            if fps is not None:
                fps_source = "fps"
        except ValueError:
            pass
    tbr = None
    if tbr_match:
        try:
            tbr = _clean_rate(float(tbr_match.group(1)))
        except ValueError:
            tbr = None
    if fps is None and tbr is not None:
        fps = tbr
        fps_source = "tbr"

    try:
        rotation = float(rotation_match.group(1)) if rotation_match else 0.0
    except ValueError:
        rotation = 0.0
    normalized_rotation = int(round(rotation / 90.0) * 90) % 360 if rotation else 0
    display_width, display_height = width, height
    if normalized_rotation in {90, 270}:
        display_width, display_height = height, width

    ext = path.suffix.lower()
    risk_reasons = _timeline_risks(
        ext=ext,
        text=text,
        width=width,
        height=height,
        duration=duration,
        fps=fps,
        fps_source=fps_source,
    )
    timeline_risk = bool(risk_reasons)
    strategy, compat_mode, reason = _strategy(
        ext,
        video_codec,
        audio_codec,
        timeline_risk=timeline_risk,
    )
    browser_safe = strategy == "native" and not timeline_risk

    data = {
        "ok": bool(video_codec),
        "path": path.name,
        "ext": ext.lstrip("."),
        "container": container,
        "videoCodec": video_codec or "unknown",
        "audioCodec": audio_codec or "none",
        "width": width,
        "height": height,
        "displayWidth": display_width,
        "displayHeight": display_height,
        "rotation": normalized_rotation,
        "fps": fps,
        "fpsSource": fps_source or "unknown",
        "duration": duration,
        "size": stat.st_size,
        "strategy": strategy,
        "compatMode": compat_mode,
        "reason": reason,
        "browserSafe": browser_safe,
        "timelineRisk": timeline_risk,
        "riskReasons": risk_reasons,
    }
    _cache_put(key, data)
    return data


def probe_media(path: Path, timeout: int = 7) -> dict:
    try:
        key = _identity(path)
        stat = path.stat()
    except OSError:
        return {"ok": False, "error": "文件不存在"}

    cached = _cache_get(key)
    if cached is not None:
        return cached

    with _PROBE_EXECUTOR:
        cached = _cache_get(key)
        if cached is not None:
            return cached
        return _probe_uncached(path, stat, timeout, key)


def clear_probe_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
