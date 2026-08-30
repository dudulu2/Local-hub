from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.parse
from http import HTTPStatus
from pathlib import Path

import ai_settings_support
import media_probe
from io_scheduler import SCHEDULER
from visual_encoder import mean_vector


def _terminate(process: subprocess.Popen) -> None:
    try:
        process.terminate()
        process.wait(timeout=0.6)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _extract_frame_balanced(path: Path, seek: float, *, size: int = 192, timeout: float = 8.0) -> tuple[bytes | None, bool]:
    """Extract one tiny frame at low OS/FFmpeg priority.

    Playback is allowed to continue in balanced mode. Seeking is different: a
    scrub should feel immediate, so the extraction is terminated as soon as a
    seek heartbeat arrives. The bool return value indicates that interruption.
    """
    if SCHEDULER.snapshot().get("seeking"):
        return None, True
    exe = media_probe.ffmpeg_exe()
    if not exe:
        return None, False
    command = [
        exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-threads", "1", "-filter_threads", "1",
        "-ss", f"{max(0.0, seek):.3f}", "-noaccurate_seek", "-i", str(path),
        "-an", "-sn", "-dn", "-frames:v", "1",
        "-vf", f"scale='min({int(size)},iw)':-2",
        "-q:v", "10", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ]
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        flags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        kwargs["creationflags"] = flags
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError:
        return None, False

    started = time.monotonic()
    while True:
        if SCHEDULER.snapshot().get("seeking"):
            _terminate(process)
            return None, True
        if time.monotonic() - started > timeout:
            _terminate(process)
            return None, False
        try:
            out, _ = process.communicate(timeout=0.12)
            data = out or b""
            return (data if process.returncode == 0 and len(data) > 300 else None), False
        except subprocess.TimeoutExpired:
            continue
        except Exception:
            _terminate(process)
            return None, False


def _patch_manager(auto_tag_support_module) -> None:
    Manager = auto_tag_support_module.AutoTagManager
    if getattr(Manager, "_localhub_ai_center_patched", False):
        return

    original_analyze = Manager._analyze

    def analyze_balanced(self, relative: str) -> str:
        mode = getattr(self, "ai_background_mode", "balanced")
        if mode == "idle":
            return original_analyze(self, relative)

        try:
            path = self.store.resolve_media(relative)
            stat = path.stat()
        except (ValueError, FileNotFoundError, OSError):
            self.index.remove(relative)
            return "missing"
        if path.suffix.lower() not in set(getattr(__import__("server"), "VIDEO_EXTS", set())):
            return "skip"
        if self.index.signature_matches(relative, stat.st_size, stat.st_mtime_ns, self.encoder.name):
            return "cached"
        if SCHEDULER.snapshot().get("seeking"):
            return "busy"

        probe = media_probe.probe_media(path)
        if SCHEDULER.snapshot().get("seeking"):
            return "busy"
        duration = float(probe.get("duration") or 0.0) if probe.get("ok") else 0.0
        candidates: list[tuple[int, float, tuple[float, ...], float]] = []

        for slot, ratio, seek in auto_tag_support_module._sample_positions(duration):
            io_state = SCHEDULER.snapshot()
            if io_state.get("seeking"):
                return "busy"
            data, interrupted = _extract_frame_balanced(path, seek, size=192, timeout=8.0)
            if interrupted:
                return "busy"
            if data is None:
                continue
            encoded = self.encoder.encode_jpeg(data)
            if encoded is None:
                continue
            candidates.append((slot, ratio, encoded.vector, encoded.quality))
            # While a movie is actually playing, deliberately leave small gaps
            # between frame inferences. One AI worker + one FFmpeg thread + below
            # normal priority keeps throughput modest but makes playback dominant.
            if SCHEDULER.snapshot().get("playing"):
                if self.stop.wait(0.32):
                    return "busy"
            if SCHEDULER.snapshot().get("seeking"):
                return "busy"

        if not candidates:
            return "failed"
        selected = auto_tag_support_module._select_representative(candidates)
        aggregate = mean_vector([row[2] for row in selected])
        if not aggregate:
            return "failed"
        self.index.save_media(
            relative,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            duration=duration,
            encoder=self.encoder.name,
            vector=aggregate,
            frames=selected,
        )
        self.invalidate_prototypes()
        return "ok"

    def worker_balanced(self) -> None:
        while not self.stop.is_set():
            job = self._next_job()
            if job is None:
                self.wake.wait(0.8)
                self.wake.clear()
                continue
            path, source = job
            if source == "library":
                with self.lock:
                    if not self.library_running:
                        self.library.appendleft(path)
                        continue

            mode = getattr(self, "ai_background_mode", "balanced")
            if mode == "idle":
                if not SCHEDULER.wait_background_idle(self.stop, grace=4.0):
                    continue
            else:
                # Balanced mode can coexist with playback, but never fights a
                # timeline scrub/seek. Wait only for the seek to finish.
                while SCHEDULER.snapshot().get("seeking") and not self.stop.wait(0.18):
                    pass
                if self.stop.is_set():
                    return

            with self.lock:
                self.current = path
            started = time.perf_counter()
            requeue = False
            try:
                outcome = self._analyze(path)
                if outcome == "busy":
                    requeue = True
                elif outcome in {"ok", "cached"}:
                    with self.lock:
                        self.completed += 1
                else:
                    with self.lock:
                        self.failed += 1
            except Exception as exc:
                with self.lock:
                    self.failed += 1
                    self.last_error = str(exc)
            finally:
                elapsed = (time.perf_counter() - started) * 1000.0
                with self.lock:
                    self.last_elapsed_ms = elapsed
                    self.current = ""

            if requeue:
                if source == "manual":
                    self.queue_media(path)
                else:
                    with self.lock:
                        self.library.appendleft(path)
                self.stop.wait(0.25)
                continue

            io_state = SCHEDULER.snapshot()
            if mode == "balanced":
                delay = 0.62 if io_state.get("playing") else 0.22
            else:
                delay = 1.2 if self.last_elapsed_ms < 3500 else min(5.0, self.last_elapsed_ms / 1800.0)
            self.stop.wait(delay)

    Manager._analyze = analyze_balanced
    Manager._worker = worker_balanced
    Manager._localhub_ai_center_patched = True


def _apply_settings(manager, settings_store, siglip_support_module) -> dict:
    settings = settings_store.snapshot()
    manager.ai_background_mode = settings.get("backgroundMode", "balanced")
    prompts = settings_store.prompts()

    # siglip_support imports this dict once; mutate it in place so every helper
    # (hashing, prompt-vector cache, suggestions, status counts) immediately sees
    # the user's enabled Tag groups without creating a second AI implementation.
    target = siglip_support_module.DEFAULT_TAG_PROMPTS
    target.clear()
    target.update(prompts)
    try:
        import auto_tag_prompts
        if auto_tag_prompts.DEFAULT_TAG_PROMPTS is not target:
            auto_tag_prompts.DEFAULT_TAG_PROMPTS.clear()
            auto_tag_prompts.DEFAULT_TAG_PROMPTS.update(prompts)
    except Exception:
        pass

    manager._siglip_prompt_cache = None
    manager.invalidate_prototypes()
    if not settings.get("autoAnalyzeLibrary", True):
        manager.pause_library()
    return settings


def _model_status(manager) -> dict:
    status = dict(manager.siglip_bundle.status())
    status["enabled"] = bool(getattr(manager, "_siglip_enabled", False))
    return status


def _total_videos(store) -> int:
    catalog = getattr(store, "_smart_catalog", None)
    if catalog is not None:
        catalog._await()
        with catalog.lock:
            return sum(1 for item in catalog.items if item.get("type") == "video")
    try:
        return sum(1 for item in store.scan() if item.get("type") == "video")
    except Exception:
        return 0


def _semantic_indexed(manager, siglip_support_module) -> int:
    try:
        from siglip_encoder import ENCODER_NAME
        return int(manager.index.stats(ENCODER_NAME).get("media", 0) or 0)
    except Exception:
        return 0


def install(server_module, auto_tag_support_module, siglip_support_module) -> None:
    _patch_manager(auto_tag_support_module)

    app_dir = Path(server_module.APP_DIR)
    server_module.STATIC_FILES["/ai_center.js"] = app_dir / "ai_center.js"
    server_module.STATIC_FILES["/ai_center.css"] = app_dir / "ai_center.css"

    try:
        base_html = (app_dir / "smart_index.html").read_text("utf-8")
        enhanced_html = base_html.replace(
            "</head>",
            '  <link rel="stylesheet" href="/auto_tag_ui.css">\n'
            '  <link rel="stylesheet" href="/playback_stability.css">\n'
            '  <link rel="stylesheet" href="/ai_center.css">\n</head>',
            1,
        ).replace(
            "</body>",
            '  <script src="/auto_tag_ui.js"></script>\n'
            '  <script src="/playback_stability.js"></script>\n'
            '  <script src="/ai_center.js"></script>\n</body>',
            1,
        ).encode("utf-8")
    except OSError:
        enhanced_html = b""

    original_make_handler = server_module.make_handler

    def make_handler(store):
        BaseHandler = original_make_handler(store)
        manager = getattr(store, "_auto_tag_manager", None)
        settings_store = ai_settings_support.AISettingsStore(store.root)
        store._ai_settings_store = settings_store
        if manager is not None:
            _apply_settings(manager, settings_store, siglip_support_module)

            def delayed_autostart() -> None:
                # Let the page/server become responsive first. If the user starts
                # scrubbing immediately, wait. Installed models can then continue
                # at low priority alongside normal playback in balanced mode.
                if manager.stop.wait(6.0):
                    return
                settings = settings_store.snapshot()
                if not settings.get("autoAnalyzeLibrary", True):
                    return
                for _ in range(40):
                    if manager.stop.is_set():
                        return
                    if not SCHEDULER.snapshot().get("seeking"):
                        break
                    manager.stop.wait(0.25)
                try:
                    if manager.siglip_bundle.available():
                        manager.start_library()
                except Exception as exc:
                    with manager.lock:
                        manager.last_error = f"AI auto-start: {exc}"

            threading.Thread(target=delayed_autostart, name="LocalHubAIAutoStart", daemon=True).start()

        class AICenterHandler(BaseHandler):
            def _ai_json(self, payload, status=HTTPStatus.OK):
                raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self._headers(status, "application/json; charset=utf-8", len(raw), {"Cache-Control": "no-store"})
                self.wfile.write(raw)

            def _overview(self):
                if manager is None:
                    return {"ok": False, "error": "AI 尚未初始化"}
                status = manager.status()
                model = _model_status(manager)
                return {
                    "ok": True,
                    "settings": settings_store.snapshot(),
                    "status": status,
                    "model": model,
                    "totalVideos": _total_videos(store),
                    "semanticIndexed": _semantic_indexed(manager, siglip_support_module),
                }

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path in {"/", "/index.html"} and enhanced_html:
                    self._headers(HTTPStatus.OK, "text/html; charset=utf-8", len(enhanced_html), {"Cache-Control": "no-cache"})
                    self.wfile.write(enhanced_html)
                    return
                if parsed.path == "/api/ai/overview":
                    return self._ai_json(self._overview())
                if parsed.path == "/api/ai/settings":
                    return self._ai_json({"ok": True, "settings": settings_store.snapshot()})
                return super().do_GET()

            def do_POST(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path != "/api/ai/settings":
                    return super().do_POST()
                if manager is None:
                    return self._ai_json({"ok": False, "error": "AI 尚未初始化"}, HTTPStatus.SERVICE_UNAVAILABLE)
                try:
                    data = self._read_json()
                    action = str(data.get("action", "save"))
                    if action == "reset":
                        current = settings_store.snapshot()
                        defaults = dict(ai_settings_support.DEFAULT_SETTINGS)
                        defaults["onboardingCompleted"] = current.get("onboardingCompleted", True)
                        defaults["aiOptIn"] = current.get("aiOptIn", False)
                        saved = settings_store.save(defaults)
                    elif action == "save":
                        saved = settings_store.save(data.get("settings", {}))
                    else:
                        raise ValueError("未知 AI 设置操作")
                    saved = _apply_settings(manager, settings_store, siglip_support_module)
                    model = _model_status(manager)
                    if saved.get("autoAnalyzeLibrary", True) and model.get("installed"):
                        manager.start_library()
                    return self._ai_json({"ok": True, "settings": saved, "model": _model_status(manager)})
                except (ValueError, OSError) as exc:
                    return self._ai_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

        return AICenterHandler

    server_module.make_handler = make_handler
