from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import media_probe

# Auto compatibility is intentionally conservative. Sequentially rewriting a
# multi-gigabyte transport stream can saturate the same disk that the browser is
# reading from and make the tab look frozen. Users can still open these files in
# their Windows-associated player (PotPlayer, VLC, etc.).
LARGE_TS_BYTES = 1_500_000_000
LARGE_TS_DURATION = 3600.0
LARGE_TRANSCODE_BYTES = 2_000_000_000
LARGE_TRANSCODE_DURATION = 5400.0


def cleanup_root(root: Path) -> None:
    folder = root / ".localhub" / "compat"
    try:
        shutil.rmtree(folder, ignore_errors=True)
    except OSError:
        pass


def _terminate_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    try:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=1.0)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


@dataclass
class CompatJob:
    job_id: str
    source: Path
    output: Path
    mode: str
    duration: float | None = None
    status: str = "queued"
    progress: float = 0.0
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    cancelled: bool = False
    process: subprocess.Popen | None = field(default=None, repr=False, compare=False)

    def public(self) -> dict:
        return {
            "id": self.job_id,
            "status": self.status,
            "progress": round(max(0.0, min(100.0, self.progress)), 1),
            "mode": self.mode,
            "error": self.error,
            "duration": self.duration,
            "url": f"/api/compat/file?id={urllib.parse.quote(self.job_id)}" if self.status == "ready" else None,
        }


class CompatManager:
    def __init__(self, root: Path):
        self.root = root
        self.folder = root / ".localhub" / "compat"
        self.lock = threading.RLock()
        self.jobs: dict[str, CompatJob] = {}
        # At most one compatibility job per LocalHub instance. This is both a
        # CPU and an I/O safety limit.
        self.worker = threading.BoundedSemaphore(1)

    def _job_id(self, source: Path) -> str:
        stat = source.stat()
        raw = f"{source}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8", "surrogatepass")
        return hashlib.sha256(raw).hexdigest()[:24]

    @staticmethod
    def _auto_block_reason(source: Path, probe: dict, mode: str) -> str:
        try:
            size = int(source.stat().st_size)
        except OSError:
            size = int(probe.get("size") or 0)
        duration = float(probe.get("duration") or 0.0)
        ext = source.suffix.lower()

        if ext == ".ts" and (size >= LARGE_TS_BYTES or duration >= LARGE_TS_DURATION):
            return "大型 TS 默认不自动兼容处理，避免长时间占用磁盘并卡住网页；请优先使用系统播放器。"
        if mode == "transcode" and (size >= LARGE_TRANSCODE_BYTES or duration >= LARGE_TRANSCODE_DURATION):
            return "这个视频需要整段转码且文件较大，LocalHub 已阻止自动转码以保护播放性能；请优先使用系统播放器。"
        return ""

    def start(self, source: Path, requested_mode: str | None = None, *, force: bool = False) -> dict:
        probe = media_probe.probe_media(source)
        mode = requested_mode if requested_mode in {"remux", "transcode"} else probe.get("compatMode", "transcode")
        if mode not in {"remux", "transcode"}:
            mode = "transcode"
        job_id = self._job_id(source)
        self.folder.mkdir(parents=True, exist_ok=True)
        output = self.folder / f"{job_id}.mp4"

        with self.lock:
            existing = self.jobs.get(job_id)
            if existing and existing.status in {"queued", "working", "ready"}:
                return existing.public()

            blocked = "" if force else self._auto_block_reason(source, probe, mode)
            job = CompatJob(job_id=job_id, source=source, output=output, mode=mode, duration=probe.get("duration"))
            self.jobs[job_id] = job
            if blocked:
                # Use the normal error state so the existing browser poller stops
                # immediately instead of spinning forever on a new status value.
                job.status = "error"
                job.error = blocked
                job.finished_at = time.time()
                return job.public()

        threading.Thread(target=self._run, args=(job, probe), name=f"LocalHubCompat-{job_id[:6]}", daemon=True).start()
        return job.public()

    def status(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return job.public() if job else None

    def output_for(self, job_id: str) -> Path | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.status != "ready" or not job.output.exists():
                return None
            return job.output

    def cancel_source(self, source: Path) -> bool:
        try:
            wanted = source.resolve()
        except OSError:
            wanted = source
        process = None
        found = False
        with self.lock:
            for job in self.jobs.values():
                try:
                    same = job.source.resolve() == wanted
                except OSError:
                    same = job.source == source
                if not same or job.status not in {"queued", "working"}:
                    continue
                found = True
                job.cancelled = True
                job.status = "error"
                job.error = "兼容任务已取消"
                job.finished_at = time.time()
                process = job.process
                break
        _terminate_process(process)
        return found

    def _run(self, job: CompatJob, probe: dict) -> None:
        with self.worker:
            if job.cancelled:
                return
            job.status = "working"
            part = job.output.with_suffix(".part.mp4")
            try:
                part.unlink(missing_ok=True)
                job.output.unlink(missing_ok=True)
            except OSError:
                pass

            ok = self._execute(job, probe, part, job.mode)
            if not ok and not job.cancelled and job.mode == "remux":
                job.mode = "transcode"
                job.progress = 0.0
                try:
                    part.unlink(missing_ok=True)
                except OSError:
                    pass
                # A failed remux of a large source must not silently escalate to
                # a multi-hour transcode.
                block = self._auto_block_reason(job.source, probe, "transcode")
                if block:
                    job.error = block
                else:
                    ok = self._execute(job, probe, part, "transcode")

            if job.cancelled:
                try:
                    part.unlink(missing_ok=True)
                except OSError:
                    pass
                return

            if ok:
                try:
                    os.replace(part, job.output)
                    job.status = "ready"
                    job.progress = 100.0
                    job.finished_at = time.time()
                except OSError as exc:
                    job.status = "error"
                    job.error = f"兼容文件保存失败：{exc}"
            else:
                job.status = "error"
                if not job.error:
                    job.error = "FFmpeg 无法生成浏览器兼容版本"
                try:
                    part.unlink(missing_ok=True)
                except OSError:
                    pass

    def _execute(self, job: CompatJob, probe: dict, output: Path, mode: str) -> bool:
        exe = media_probe.ffmpeg_exe()
        if not exe:
            job.error = "FFmpeg 不可用"
            return False
        if job.cancelled:
            return False

        command = [
            exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(job.source),
            "-map", "0:v:0", "-map", "0:a:0?",
            "-map_metadata", "0", "-map_metadata:s:v:0", "0:s:v:0",
        ]
        if mode == "remux":
            command += ["-c:v", "copy"]
            if str(probe.get("audioCodec", "")).lower() == "aac":
                command += ["-c:a", "copy"]
            else:
                command += ["-c:a", "aac", "-b:a", "160k"]
        else:
            # Keep compatibility conversion deliberately below 'use the whole
            # PC' territory. Two x264 threads are enough for a background task
            # and greatly reduce the chance of starving the browser process.
            command += [
                "-filter_threads", "1",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-pix_fmt", "yuv420p", "-threads", "2",
                "-c:a", "aac", "-b:a", "160k",
            ]
        command += ["-movflags", "+faststart+use_metadata_tags", "-progress", "pipe:1", "-nostats", str(output)]

        kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace", bufsize=1)
        if os.name == "nt":
            kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
            )

        try:
            process = subprocess.Popen(command, **kwargs)
            job.process = process
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
                    if len(stderr_chunks) < 20:
                        stderr_chunks.append(line.strip())
            except Exception:
                pass

        stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
        stderr_thread.start()

        try:
            if process.stdout is not None:
                for line in process.stdout:
                    if job.cancelled:
                        _terminate_process(process)
                        break
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
            stderr_thread.join(timeout=0.4)
        except Exception as exc:
            _terminate_process(process)
            if not job.cancelled:
                job.error = str(exc)
            return False
        finally:
            job.process = None

        if job.cancelled:
            return False
        if code != 0:
            message = " · ".join(x for x in stderr_chunks[-4:] if x)
            job.error = message[-500:] if message else f"FFmpeg 返回 {code}"
            return False
        return output.exists() and output.stat().st_size > 1024


def install(server_module) -> None:
    original_make_handler = server_module.make_handler

    def make_handler(store):
        BaseHandler = original_make_handler(store)
        manager = CompatManager(store.root)

        class CompatHandler(BaseHandler):
            def do_POST(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path == "/api/compat/start":
                    try:
                        payload = self._read_json()
                        media = store.resolve_media(str(payload.get("path", "")))
                        result = manager.start(
                            media,
                            str(payload.get("mode", "")) or None,
                            force=bool(payload.get("force", False)),
                        )
                        return self._send_json({"ok": True, "job": result})
                    except (ValueError, FileNotFoundError) as exc:
                        return self._send_json({"ok": False, "error": str(exc)}, 400)
                if parsed.path == "/api/compat/cancel":
                    try:
                        payload = self._read_json()
                        media = store.resolve_media(str(payload.get("path", "")))
                        return self._send_json({"ok": True, "cancelled": manager.cancel_source(media)})
                    except (ValueError, FileNotFoundError) as exc:
                        return self._send_json({"ok": False, "error": str(exc)}, 400)
                if parsed.path == "/api/compat/open-system":
                    try:
                        payload = self._read_json()
                        media = store.resolve_media(str(payload.get("path", "")))
                        if os.name != "nt":
                            raise ValueError("仅 Windows 支持调用系统播放器")
                        os.startfile(media)  # type: ignore[attr-defined]
                        return self._send_json({"ok": True})
                    except (ValueError, FileNotFoundError, OSError) as exc:
                        return self._send_json({"ok": False, "error": str(exc)}, 400)
                return super().do_POST()

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                if parsed.path == "/api/health":
                    return self._send_json({"ok": True, "service": "LocalHub"})
                if parsed.path == "/api/media/probe":
                    relative = query.get("path", [""])[0]
                    try:
                        media = store.resolve_media(relative)
                    except (ValueError, FileNotFoundError):
                        self.send_error(404)
                        return
                    probe = media_probe.probe_media(media)
                    probe["autoCompatBlocked"] = bool(manager._auto_block_reason(media, probe, str(probe.get("compatMode", "transcode"))))
                    probe["systemPreferred"] = bool(probe["autoCompatBlocked"])
                    return self._send_json({"ok": True, "probe": probe})
                if parsed.path == "/api/compat/status":
                    job_id = query.get("id", [""])[0]
                    result = manager.status(job_id)
                    if not result:
                        self.send_error(404)
                        return
                    return self._send_json({"ok": True, "job": result})
                if parsed.path == "/api/compat/file":
                    job_id = query.get("id", [""])[0]
                    output = manager.output_for(job_id)
                    if not output:
                        self.send_error(404)
                        return
                    return self._serve_media(output)
                return super().do_GET()

        return CompatHandler

    server_module.make_handler = make_handler
