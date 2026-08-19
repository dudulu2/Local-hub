from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import media_probe


def cleanup_root(root: Path) -> None:
    try:
        shutil.rmtree(root / ".localhub" / "repair", ignore_errors=True)
    except OSError:
        pass


def _terminate(process: subprocess.Popen | None) -> None:
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
class RepairJob:
    job_id: str
    source: Path
    output: Path
    fps: float
    duration: float | None = None
    status: str = "queued"
    progress: float = 0.0
    error: str = ""
    cancelled: bool = False
    process: subprocess.Popen | None = field(default=None, repr=False, compare=False)

    def public(self) -> dict:
        return {
            "id": self.job_id,
            "status": self.status,
            "progress": round(max(0.0, min(100.0, self.progress)), 1),
            "error": self.error,
            "fps": round(self.fps, 3),
            "duration": self.duration,
            "url": f"/api/repair/file?id={urllib.parse.quote(self.job_id)}" if self.status == "ready" else None,
        }


class RepairManager:
    def __init__(self, root: Path):
        self.root = root
        self.folder = root / ".localhub" / "repair"
        self.lock = threading.RLock()
        self.jobs: dict[str, RepairJob] = {}
        self.worker = threading.BoundedSemaphore(1)

    def _job_id(self, source: Path) -> str:
        st = source.stat()
        raw = f"{source}|{st.st_size}|{st.st_mtime_ns}|timeline1".encode("utf-8", "surrogatepass")
        return hashlib.sha256(raw).hexdigest()[:24]

    def start(self, source: Path) -> dict:
        probe = media_probe.probe_media(source)
        if not probe.get("ok"):
            raise ValueError(probe.get("error") or "无法读取视频信息")
        fps = float(probe.get("fps") or 0.0)
        if not 5.0 <= fps <= 120.0:
            fps = 30.0
        job_id = self._job_id(source)
        self.folder.mkdir(parents=True, exist_ok=True)
        output = self.folder / f"{job_id}.repair.mp4"
        with self.lock:
            existing = self.jobs.get(job_id)
            if existing and existing.status in {"queued", "working", "ready"}:
                return existing.public()
            job = RepairJob(job_id=job_id, source=source, output=output, fps=fps, duration=probe.get("duration"))
            self.jobs[job_id] = job
        threading.Thread(target=self._run, args=(job, probe), name=f"LocalHubRepair-{job_id[:6]}", daemon=True).start()
        return job.public()

    def status(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return job.public() if job else None

    def file(self, job_id: str) -> Path | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.status != "ready" or not job.output.exists():
                return None
            return job.output

    def cancel(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.status not in {"queued", "working"}:
                return False
            job.cancelled = True
            job.status = "error"
            job.error = "修复播放已取消"
            process = job.process
        _terminate(process)
        return True

    def _run(self, job: RepairJob, probe: dict) -> None:
        with self.worker:
            if job.cancelled:
                return
            job.status = "working"
            try:
                job.output.unlink(missing_ok=True)
            except OSError:
                pass
            exe = media_probe.ffmpeg_exe()
            if not exe:
                job.status = "error"
                job.error = "FFmpeg 不可用"
                return

            fps_text = f"{job.fps:.6f}".rstrip("0").rstrip(".")
            audio = str(probe.get("audioCodec", "")).lower()
            command = [
                exe, "-hide_banner", "-loglevel", "warning", "-nostdin", "-y",
                "-fflags", "+genpts+discardcorrupt", "-err_detect", "ignore_err",
                "-i", str(job.source),
                "-map", "0:v:0", "-map", "0:a:0?",
                "-vf", f"fps={fps_text},setpts=N/({fps_text}*TB)",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-fps_mode", "cfr", "-video_track_timescale", "90000",
            ]
            if audio in {"", "none", "unknown"}:
                command += ["-an"]
            else:
                command += ["-c:a", "aac", "-b:a", "160k", "-af", "aresample=async=1:first_pts=0"]
            command += [
                "-avoid_negative_ts", "make_zero", "-max_muxing_queue_size", "4096",
                "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(job.output),
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
                job.process = process
            except OSError as exc:
                job.status = "error"
                job.error = str(exc)
                return

            stderr_tail: list[str] = []
            def drain_stderr() -> None:
                if process.stderr is None:
                    return
                try:
                    for line in process.stderr:
                        text = line.strip()
                        if text:
                            if len(stderr_tail) >= 20:
                                stderr_tail.pop(0)
                            stderr_tail.append(text)
                except Exception:
                    pass

            t = threading.Thread(target=drain_stderr, daemon=True)
            t.start()
            duration = float(job.duration or 0.0)
            try:
                if process.stdout is not None:
                    for line in process.stdout:
                        if job.cancelled:
                            _terminate(process)
                            break
                        key, sep, value = line.strip().partition("=")
                        if not sep:
                            continue
                        if key in {"out_time_ms", "out_time_us"} and duration > 0:
                            try:
                                job.progress = min(99.0, max(job.progress, float(value) / 1_000_000.0 / duration * 100.0))
                            except ValueError:
                                pass
                        elif key == "progress" and value == "end":
                            job.progress = 99.5
                code = process.wait()
                t.join(timeout=0.5)
            except Exception as exc:
                _terminate(process)
                if not job.cancelled:
                    job.error = str(exc)
                code = -1
            finally:
                job.process = None

            if job.cancelled:
                try:
                    job.output.unlink(missing_ok=True)
                except OSError:
                    pass
                return
            if code == 0 and job.output.exists() and job.output.stat().st_size > 1024:
                job.status = "ready"
                job.progress = 100.0
            else:
                job.status = "error"
                if not job.error:
                    detail = " · ".join(stderr_tail[-6:])
                    job.error = detail[-900:] if detail else f"FFmpeg 返回 {code}"
                try:
                    job.output.unlink(missing_ok=True)
                except OSError:
                    pass


def install(server_module) -> None:
    original_make_handler = server_module.make_handler

    def make_handler(store):
        BaseHandler = original_make_handler(store)
        manager = RepairManager(store.root)

        class RepairHandler(BaseHandler):
            def do_POST(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path == "/api/repair/start":
                    try:
                        payload = self._read_json()
                        media = store.resolve_media(str(payload.get("path", "")))
                        return self._send_json({"ok": True, "job": manager.start(media)})
                    except (ValueError, FileNotFoundError) as exc:
                        return self._send_json({"ok": False, "error": str(exc)}, 400)
                if parsed.path == "/api/repair/cancel":
                    try:
                        payload = self._read_json()
                        return self._send_json({"ok": True, "cancelled": manager.cancel(str(payload.get("id", "")))})
                    except ValueError as exc:
                        return self._send_json({"ok": False, "error": str(exc)}, 400)
                return super().do_POST()

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                if parsed.path == "/repair_ui.js":
                    target = Path(server_module.APP_DIR) / "repair_ui.js"
                    try:
                        raw = target.read_bytes()
                    except OSError:
                        self.send_error(404)
                        return
                    self._headers(200, "application/javascript; charset=utf-8", len(raw), {"Cache-Control": "no-cache"})
                    self.wfile.write(raw)
                    return
                if parsed.path == "/api/repair/status":
                    result = manager.status(query.get("id", [""])[0])
                    if not result:
                        self.send_error(404)
                        return
                    return self._send_json({"ok": True, "job": result})
                if parsed.path == "/api/repair/file":
                    target = manager.file(query.get("id", [""])[0])
                    if not target:
                        self.send_error(404)
                        return
                    return self._serve_media(target)
                return super().do_GET()

            def do_HEAD(self):
                parsed = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                if parsed.path == "/api/repair/file":
                    target = manager.file(query.get("id", [""])[0])
                    if not target:
                        self.send_error(404)
                        return
                    return self._serve_media(target, head_only=True)
                return super().do_HEAD()

        return RepairHandler

    server_module.make_handler = make_handler
