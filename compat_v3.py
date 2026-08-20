from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

import compat_support
import media_probe

_INSTALLED = False
_CACHE_LIMIT_BYTES = 8 * 1024 * 1024 * 1024
_CACHE_TARGET_BYTES = 6 * 1024 * 1024 * 1024


def _validate_output(source: Path, output: Path, source_probe: dict) -> tuple[bool, str]:
    try:
        if not output.exists() or output.stat().st_size <= 1024:
            return False, "兼容副本为空或未完整写入"
    except OSError as exc:
        return False, f"兼容副本不可访问：{exc}"

    probe = media_probe.probe_media(output, timeout=10)
    if not probe.get("ok"):
        return False, f"兼容副本验证失败：{probe.get('error') or '无法读取媒体信息'}"
    if str(probe.get("videoCodec", "")).lower() != "h264":
        return False, f"兼容副本视频编码不是 H.264：{probe.get('videoCodec') or 'unknown'}"

    src_audio = str(source_probe.get("audioCodec", "")).lower()
    out_audio = str(probe.get("audioCodec", "")).lower()
    if src_audio not in {"", "none", "unknown"} and out_audio not in {"aac", "none", "unknown"}:
        return False, f"兼容副本音频编码异常：{out_audio or 'unknown'}"

    expected = float(source_probe.get("duration") or 0.0)
    actual = float(probe.get("duration") or 0.0)
    if expected > 0:
        if actual <= 0:
            return False, "兼容副本没有有效时长"
        tolerance = max(2.0, expected * 0.03)
        if abs(actual - expected) > tolerance:
            return False, f"兼容副本时长异常：原始 {expected:.2f}s / 输出 {actual:.2f}s"
    return True, ""


def _execute(job, probe: dict, output: Path, mode: str) -> bool:
    exe = media_probe.ffmpeg_exe()
    if not exe:
        job.error = "FFmpeg 不可用"
        return False

    video_codec = str(probe.get("videoCodec", "")).lower()
    audio_codec = str(probe.get("audioCodec", "")).lower()
    if mode == "remux" and video_codec != "h264":
        mode = "transcode"
        job.mode = "transcode"

    command = [
        exe,
        "-hide_banner",
        "-loglevel", "error",
        "-nostdin",
        "-y",
        "-fflags", "+genpts+discardcorrupt",
        "-i", str(job.source),
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-sn", "-dn",
    ]

    if mode == "remux":
        command += ["-c:v", "copy"]
        if audio_codec == "aac":
            command += ["-c:a", "copy"]
            if job.source.suffix.lower() == ".ts":
                command += ["-bsf:a", "aac_adtstoasc"]
        elif audio_codec in {"", "none", "unknown"}:
            command += ["-an"]
        else:
            command += ["-c:a", "aac", "-b:a", "160k", "-af", "asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0"]
    else:
        command += [
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-vf", "setpts=PTS-STARTPTS",
            "-force_key_frames", "expr:gte(t,n_forced*2)",
            "-sc_threshold", "0",
            "-fps_mode", "vfr",
        ]
        if audio_codec in {"", "none", "unknown"}:
            command += ["-an"]
        else:
            command += [
                "-c:a", "aac",
                "-b:a", "160k",
                "-af", "asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0",
            ]

    command += [
        "-avoid_negative_ts", "make_zero",
        "-max_muxing_queue_size", "2048",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        "-nostats",
        str(output),
    ]

    kwargs = dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        bufsize=1,
    )
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        job.error = str(exc)
        return False

    duration = float(job.duration or 0.0)
    stderr_chunks: list[str] = []

    def drain_stderr() -> None:
        if process.stderr is None:
            return
        try:
            for line in process.stderr:
                line = line.strip()
                if not line:
                    continue
                if len(stderr_chunks) >= 24:
                    stderr_chunks.pop(0)
                stderr_chunks.append(line)
        except Exception:
            pass

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()
    try:
        if process.stdout is not None:
            for line in process.stdout:
                key, sep, value = line.strip().partition("=")
                if not sep:
                    continue
                if key in {"out_time_ms", "out_time_us"} and duration > 0:
                    try:
                        micros = float(value)
                        job.progress = min(99.0, max(job.progress, micros / 1_000_000.0 / duration * 100.0))
                    except ValueError:
                        pass
                elif key == "progress" and value == "end":
                    job.progress = 99.5
        code = process.wait()
        stderr_thread.join(timeout=0.5)
    except Exception as exc:
        try:
            process.kill()
        except OSError:
            pass
        job.error = str(exc)
        return False

    if code != 0:
        message = " · ".join(stderr_chunks[-6:])
        job.error = message[-700:] if message else f"FFmpeg 返回 {code}"
        return False

    ok, error = _validate_output(job.source, output, probe)
    if not ok:
        job.error = error
        return False
    return True


def _start(self, source: Path, requested_mode: str | None = None) -> dict:
    probe = media_probe.probe_media(source)
    video_codec = str(probe.get("videoCodec", "")).lower()

    if requested_mode == "transcode":
        mode = "transcode"
    elif requested_mode == "remux" and video_codec == "h264":
        mode = "remux"
    else:
        mode = str(probe.get("compatMode", "transcode"))
        if mode == "remux" and video_codec != "h264":
            mode = "transcode"

    job_id = self._job_id(source)
    self.folder.mkdir(parents=True, exist_ok=True)
    output = self.folder / f"{job_id}.mp4"

    with self.lock:
        existing = self.jobs.get(job_id)
        if existing and existing.status in {"queued", "working", "ready"}:
            return existing.public()

    if output.exists():
        ok, _ = _validate_output(source, output, probe)
        if ok:
            job = compat_support.CompatJob(
                job_id=job_id,
                source=source,
                output=output,
                mode=mode,
                duration=probe.get("duration"),
                status="ready",
                progress=100.0,
                finished_at=output.stat().st_mtime,
            )
            with self.lock:
                self.jobs[job_id] = job
            return job.public()
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass

    job = compat_support.CompatJob(
        job_id=job_id,
        source=source,
        output=output,
        mode=mode,
        duration=probe.get("duration"),
    )
    with self.lock:
        self.jobs[job_id] = job
    threading.Thread(target=self._run, args=(job, probe), name=f"LocalHubCompat-{job_id[:6]}", daemon=True).start()
    return job.public()


def _cleanup_root(root: Path) -> None:
    folder = root / ".localhub" / "compat"
    if not folder.exists():
        return

    now = time.time()
    files: list[tuple[float, int, Path]] = []
    total = 0
    try:
        for path in folder.iterdir():
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if path.name.endswith(".part.mp4"):
                if now - stat.st_mtime > 6 * 3600:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                continue
            if path.suffix.lower() != ".mp4":
                continue
            total += stat.st_size
            files.append((stat.st_mtime, stat.st_size, path))
    except OSError:
        return

    if total <= _CACHE_LIMIT_BYTES:
        return
    for _, size, path in sorted(files):
        try:
            path.unlink(missing_ok=True)
            total -= size
        except OSError:
            pass
        if total <= _CACHE_TARGET_BYTES:
            break


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    compat_support.CompatManager.start = _start
    compat_support.CompatManager._execute = _execute
    compat_support.cleanup_root = _cleanup_root
