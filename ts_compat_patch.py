from __future__ import annotations

import os
import subprocess
import threading

import compat_support
import media_probe


_INSTALLED = False


def _execute_ts(job, probe: dict, output, mode: str) -> bool:
    """TS-only FFmpeg path layered over the 2.2.3 compatibility manager.

    Keep the stable 2.2.3 job lifecycle (finish first, then play). This patch only
    changes FFmpeg arguments for transport streams; it does not add growing-file
    streaming, media-probe scheduling, or playback-priority coordination.
    """
    exe = media_probe.ffmpeg_exe()
    if not exe:
        job.error = "FFmpeg 不可用"
        return False

    command = [
        exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-fflags",
        "+genpts+discardcorrupt",
        "-i",
        str(job.source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
    ]

    audio_codec = str(probe.get("audioCodec", "")).lower()
    if mode == "remux":
        command += ["-c:v", "copy"]
        if audio_codec == "aac":
            command += ["-c:a", "copy", "-bsf:a", "aac_adtstoasc"]
        elif audio_codec in {"", "none", "unknown"}:
            command += ["-an"]
        else:
            command += ["-c:a", "aac", "-b:a", "160k"]
    else:
        command += [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "24",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "2",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
        ]
        if audio_codec not in {"", "none", "unknown"}:
            command += ["-af", "aresample=async=1:first_pts=0"]
        command += ["-fps_mode", "vfr"]

    command += [
        "-avoid_negative_ts",
        "make_zero",
        "-max_muxing_queue_size",
        "2048",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
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
                if len(stderr_chunks) >= 24:
                    stderr_chunks.pop(0)
                stderr_chunks.append(line.strip())
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
        message = " · ".join(x for x in stderr_chunks[-6:] if x)
        job.error = message[-700:] if message else f"FFmpeg 返回 {code}"
        return False
    try:
        return output.exists() and output.stat().st_size > 1024
    except OSError:
        return False


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_start = compat_support.CompatManager.start
    original_execute = compat_support.CompatManager._execute

    def start(self, source, requested_mode=None):
        if source.suffix.lower() == ".ts":
            try:
                probe = media_probe.probe_media(source)
                if str(probe.get("videoCodec", "")).lower() == "h264":
                    requested_mode = "remux"
            except Exception:
                pass
        return original_start(self, source, requested_mode)

    def execute(self, job, probe, output, mode):
        if job.source.suffix.lower() == ".ts":
            return _execute_ts(job, probe, output, mode)
        return original_execute(self, job, probe, output, mode)

    compat_support.CompatManager.start = start
    compat_support.CompatManager._execute = execute
