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

STREAM_READY_BYTES = 64 * 1024


def cleanup_root(root: Path) -> None:
    try:
        shutil.rmtree(root / ".localhub" / "mse", ignore_errors=True)
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
class MSEJob:
    job_id: str
    source: Path
    output: Path
    duration: float | None = None
    has_audio: bool = False
    status: str = "queued"
    progress: float = 0.0
    error: str = ""
    cancelled: bool = False
    process: subprocess.Popen | None = field(default=None, repr=False, compare=False)

    def public(self) -> dict:
        try:
            size = self.output.stat().st_size
        except OSError:
            size = 0
        stream_ready = self.status in {"working", "ready"} and size >= STREAM_READY_BYTES
        return {
            "id": self.job_id,
            "status": self.status,
            "progress": round(max(0.0, min(100.0, self.progress)), 1),
            "error": self.error,
            "duration": self.duration,
            "hasAudio": self.has_audio,
            "streamReady": stream_ready,
            "bytes": size,
            "url": f"/api/mse/stream?id={urllib.parse.quote(self.job_id)}" if stream_ready else None,
        }


class MSEManager:
    def __init__(self, root: Path):
        self.root = root
        self.folder = root / ".localhub" / "mse"
        self.lock = threading.RLock()
        self.jobs: dict[str, MSEJob] = {}
        self.worker = threading.BoundedSemaphore(1)

    def _job_id(self, source: Path) -> str:
        st = source.stat()
        raw = f"{source}|{st.st_size}|{st.st_mtime_ns}|mse1".encode("utf-8", "surrogatepass")
        return hashlib.sha256(raw).hexdigest()[:24]

    def start(self, source: Path) -> dict:
        probe = media_probe.probe_media(source)
        if str(probe.get("videoCodec", "")).lower() != "h264":
            raise ValueError("MSE 试播第一版仅验证 H.264 视频")
        audio = str(probe.get("audioCodec", "")).lower()
        has_audio = audio not in {"", "none", "unknown"}
        job_id = self._job_id(source)
        self.folder.mkdir(parents=True, exist_ok=True)
        output = self.folder / f"{job_id}.mse.mp4"
        with self.lock:
            existing = self.jobs.get(job_id)
            if existing and existing.status in {"queued", "working", "ready"}:
                return existing.public()
            job = MSEJob(
                job_id=job_id,
                source=source,
                output=output,
                duration=probe.get("duration"),
                has_audio=has_audio,
            )
            self.jobs[job_id] = job
        threading.Thread(target=self._run, args=(job,), name=f"LocalHubMSE-{job_id[:6]}", daemon=True).start()
        return job.public()

    def status(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return job.public() if job else None

    def job(self, job_id: str) -> MSEJob | None:
        with self.lock:
            return self.jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.status not in {"queued", "working"}:
                return False
            job.cancelled = True
            job.status = "error"
            job.error = "MSE 试播已取消"
            process = job.process
        _terminate(process)
        return True

    def _run(self, job: MSEJob) -> None:
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

            command = [
                exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-fflags", "+genpts+discardcorrupt",
                "-i", str(job.source),
                "-map", "0:v:0", "-map", "0:a:0?",
                "-c:v", "copy",
            ]
            if job.has_audio:
                # Keep video bit-exact but normalize audio to AAC-LC so the MSE
                # SourceBuffer always sees a predictable browser audio codec.
                command += ["-c:a", "aac", "-b:a", "160k", "-af", "aresample=async=1:first_pts=0"]
            else:
                command += ["-an"]
            command += [
                "-avoid_negative_ts", "make_zero",
                "-max_muxing_queue_size", "4096",
                "-video_track_timescale", "90000",
                "-use_editlist", "0",
                "-movflags", "+frag_keyframe+empty_moov+default_base_moof+dash",
                "-progress", "pipe:1", "-nostats",
                "-f", "mp4", str(job.output),
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
                        if len(stderr_tail) >= 16:
                            stderr_tail.pop(0)
                        stderr_tail.append(line.strip())
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
                return
            if code == 0 and job.output.exists() and job.output.stat().st_size > 1024:
                job.status = "ready"
                job.progress = 100.0
            else:
                job.status = "error"
                if not job.error:
                    message = " · ".join(x for x in stderr_tail[-5:] if x)
                    job.error = message[-700:] if message else f"FFmpeg 返回 {code}"


def install(server_module) -> None:
    import preview_support

    original_make_handler = server_module.make_handler
    smart_html = Path(server_module.APP_DIR) / "smart_index.html"
    mse_js = Path(server_module.APP_DIR) / "mse_ui.js"

    def make_handler(store):
        BaseHandler = original_make_handler(store)
        manager = MSEManager(store.root)

        class MSEHandler(BaseHandler):
            def _stream_job(self, job: MSEJob):
                if job.status not in {"working", "ready"} or not job.output.exists():
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-LocalHub-MSE", "fmp4-experiment")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    with job.output.open("rb") as source:
                        while True:
                            chunk = source.read(256 * 1024)
                            if chunk:
                                self.wfile.write(chunk)
                                self.wfile.flush()
                                continue
                            if job.status == "ready":
                                tail = source.read(256 * 1024)
                                if tail:
                                    self.wfile.write(tail)
                                    self.wfile.flush()
                                    continue
                                break
                            if job.status == "error" or job.cancelled:
                                break
                            time.sleep(0.04)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                self.close_connection = True

            def do_POST(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path == "/api/mse/start":
                    try:
                        payload = self._read_json()
                        media = store.resolve_media(str(payload.get("path", "")))
                        return self._send_json({"ok": True, "job": manager.start(media)})
                    except (ValueError, FileNotFoundError) as exc:
                        return self._send_json({"ok": False, "error": str(exc)}, 400)
                if parsed.path == "/api/mse/cancel":
                    try:
                        payload = self._read_json()
                        return self._send_json({"ok": True, "cancelled": manager.cancel(str(payload.get("id", "")))})
                    except ValueError as exc:
                        return self._send_json({"ok": False, "error": str(exc)}, 400)
                return super().do_POST()

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(parsed.query)

                # This experiment deliberately replaces only the RC4 page
                # injection. Recommendation, playback-priority and exact-fit stay
                # identical, while automatic MP4 -> compat remux is omitted so it
                # cannot contaminate the A/B test against MediaSource.
                if parsed.path in {"/", "/index.html"}:
                    try:
                        html = smart_html.read_text("utf-8")
                    except OSError:
                        self.send_error(404)
                        return
                    injected = (
                        '<script src="/recommendation_ui.js"></script>\n'
                        + preview_support._PLAYBACK_PRIORITY_SCRIPT
                        + preview_support._PORTRAIT_LAYOUT_SCRIPT
                        + '<script src="/mse_ui.js"></script>\n'
                    )
                    if "</body>" in html:
                        html = html.replace("</body>", injected + "\n</body>", 1)
                    else:
                        html += injected
                    raw = html.encode("utf-8")
                    self._headers(200, "text/html; charset=utf-8", len(raw), {"Cache-Control": "no-cache"})
                    self.wfile.write(raw)
                    return

                if parsed.path == "/mse_ui.js":
                    try:
                        raw = mse_js.read_bytes()
                    except OSError:
                        self.send_error(404)
                        return
                    self._headers(200, "application/javascript; charset=utf-8", len(raw), {"Cache-Control": "no-cache"})
                    self.wfile.write(raw)
                    return

                if parsed.path == "/api/mse/status":
                    result = manager.status(query.get("id", [""])[0])
                    if not result:
                        self.send_error(404)
                        return
                    return self._send_json({"ok": True, "job": result})
                if parsed.path == "/api/mse/stream":
                    job = manager.job(query.get("id", [""])[0])
                    if not job:
                        self.send_error(404)
                        return
                    return self._stream_job(job)
                return super().do_GET()

        return MSEHandler

    server_module.make_handler = make_handler
