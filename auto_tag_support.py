from __future__ import annotations

import json
import math
import os
import queue
import statistics
import subprocess
import threading
import time
import urllib.parse
from collections import defaultdict, deque
from http import HTTPStatus
from pathlib import Path

import media_probe
from io_scheduler import SCHEDULER
from visual_encoder import DEFAULT_ENCODER, cosine, mean_vector
from visual_index import VisualIndex


CANDIDATE_RATIOS = (0.08, 0.20, 0.32, 0.44, 0.56, 0.68, 0.80, 0.92)
FALLBACK_SEEKS = (2.0, 7.0, 15.0, 30.0, 60.0, 120.0, 180.0, 300.0)
REPRESENTATIVE_FRAMES = 6
MIN_TAG_POSITIVES = 3


def _terminate(process: subprocess.Popen) -> None:
    try:
        process.terminate()
        process.wait(timeout=0.8)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _extract_frame_interruptible(path: Path, seek: float, size: int = 192, timeout: float = 8.0) -> bytes | None:
    """Extract one tiny frame and abort quickly if playback becomes active."""
    if SCHEDULER.busy():
        return None
    exe = media_probe.ffmpeg_exe()
    if not exe:
        return None
    command = [
        exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", f"{max(0.0, seek):.3f}", "-noaccurate_seek", "-i", str(path),
        "-an", "-sn", "-dn", "-frames:v", "1",
        "-vf", f"scale='min({int(size)},iw)':-2",
        "-q:v", "9", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
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


def _sample_positions(duration: float) -> list[tuple[int, float, float]]:
    if duration > 1.5:
        rows = []
        for slot, ratio in enumerate(CANDIDATE_RATIOS):
            seek = max(0.25, min(duration - 0.35, duration * ratio))
            rows.append((slot, ratio, seek))
        return rows
    return [(slot, 0.0, seek) for slot, seek in enumerate(FALLBACK_SEEKS)]


def _select_representative(rows: list[tuple[int, float, tuple[float, ...], float]]) -> list[tuple[int, float, tuple[float, ...], float]]:
    if len(rows) <= REPRESENTATIVE_FRAMES:
        return rows

    # Prefer an informative anchor, then farthest-point sampling. This gives
    # diversity without decoding the entire video or running scene detection.
    first = max(rows, key=lambda row: row[3])
    selected = [first]
    remaining = [row for row in rows if row is not first]
    while remaining and len(selected) < REPRESENTATIVE_FRAMES:
        best = max(
            remaining,
            key=lambda row: min(1.0 - cosine(row[2], existing[2]) for existing in selected) + row[3] * 0.08,
        )
        selected.append(best)
        remaining.remove(best)
    return sorted(selected, key=lambda row: row[0])


class AutoTagManager:
    def __init__(self, store) -> None:
        self.store = store
        self.index = VisualIndex(store.root)
        self.encoder = DEFAULT_ENCODER
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.urgent: queue.Queue[str] = queue.Queue()
        self.urgent_set: set[str] = set()
        self.library: deque[str] = deque()
        self.library_running = False
        self.current = ""
        self.completed = 0
        self.failed = 0
        self.last_error = ""
        self.last_elapsed_ms = 0.0
        self._prototype_cache: tuple[float, dict[str, dict]] | None = None
        self.thread = threading.Thread(target=self._worker, name="LocalHubAutoTag", daemon=True)
        self.thread.start()

    def invalidate_prototypes(self) -> None:
        with self.lock:
            self._prototype_cache = None

    def queue_media(self, path: str) -> None:
        clean = str(path or "").replace("\\", "/").lstrip("/")
        if not clean:
            return
        with self.lock:
            if clean == self.current or clean in self.urgent_set:
                return
            self.urgent_set.add(clean)
            self.urgent.put(clean)
            self.wake.set()

    def _catalog_video_ids(self) -> list[str]:
        catalog = getattr(self.store, "_smart_catalog", None)
        if catalog is not None:
            catalog._await()
            with catalog.lock:
                return [str(item.get("id", "")) for item in catalog.items if item.get("type") == "video" and item.get("id")]
        return [str(item.get("id", "")) for item in self.store.scan() if item.get("type") == "video"]

    def start_library(self) -> int:
        paths = self._catalog_video_ids()
        with self.lock:
            existing = set(self.library)
            for path in paths:
                if path and path not in existing and path not in self.urgent_set and path != self.current:
                    self.library.append(path)
                    existing.add(path)
            self.library_running = True
            self.wake.set()
            return len(self.library)

    def pause_library(self) -> None:
        with self.lock:
            self.library_running = False

    def _next_job(self) -> tuple[str, str] | None:
        try:
            path = self.urgent.get_nowait()
            with self.lock:
                self.urgent_set.discard(path)
            return path, "manual"
        except queue.Empty:
            pass
        with self.lock:
            if self.library_running and self.library:
                return self.library.popleft(), "library"
        return None

    def _worker(self) -> None:
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
            if not SCHEDULER.wait_background_idle(self.stop, grace=4.0):
                continue
            with self.lock:
                self.current = path
            started = time.perf_counter()
            try:
                outcome = self._analyze(path)
                if outcome == "busy":
                    # Playback started during extraction. Put the job back and
                    # yield immediately; the active video always wins.
                    if source == "manual":
                        self.queue_media(path)
                    else:
                        with self.lock:
                            self.library.appendleft(path)
                    continue
                if outcome == "ok" or outcome == "cached":
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
            # Low-risk default: deliberately leave air between videos. Slow
            # disks/backups get more recovery time automatically.
            delay = 1.2 if self.last_elapsed_ms < 3500 else min(5.0, self.last_elapsed_ms / 1800.0)
            self.stop.wait(delay)

    def _analyze(self, relative: str) -> str:
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

        if SCHEDULER.busy():
            return "busy"
        probe = media_probe.probe_media(path)
        duration = float(probe.get("duration") or 0.0) if probe.get("ok") else 0.0
        candidates: list[tuple[int, float, tuple[float, ...], float]] = []
        for slot, ratio, seek in _sample_positions(duration):
            if not SCHEDULER.wait_background_idle(self.stop, grace=1.0):
                return "busy"
            data = _extract_frame_interruptible(path, seek, size=192, timeout=8.0)
            if data is None:
                if SCHEDULER.busy():
                    return "busy"
                continue
            encoded = self.encoder.encode_jpeg(data)
            if encoded is None:
                continue
            candidates.append((slot, ratio, encoded.vector, encoded.quality))

        if not candidates:
            return "failed"
        selected = _select_representative(candidates)
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

    def _prototypes(self) -> dict[str, dict]:
        now = time.monotonic()
        with self.lock:
            if self._prototype_cache and now < self._prototype_cache[0]:
                return self._prototype_cache[1]

        rows = self.index.all_media(self.encoder.name)
        vectors = {row["path"]: row["vector"] for row in rows if row["vector"]}
        with self.store.lock:
            metadata = dict(self.store._metadata.get("items", {}))

        grouped: defaultdict[str, list[tuple[float, ...]]] = defaultdict(list)
        labels: dict[str, str] = {}
        for path, vector in vectors.items():
            tags = metadata.get(path, {}).get("tags", [])
            if not isinstance(tags, list):
                continue
            for tag in tags:
                label = str(tag).strip()
                if not label:
                    continue
                key = label.casefold()
                labels.setdefault(key, label)
                grouped[key].append(vector)

        result: dict[str, dict] = {}
        for key, positives in grouped.items():
            if len(positives) < MIN_TAG_POSITIVES:
                continue
            prototype = mean_vector(positives)
            sims = [cosine(vector, prototype) for vector in positives]
            avg = statistics.fmean(sims) if sims else 0.0
            std = statistics.pstdev(sims) if len(sims) > 1 else 0.0
            # Conservative because the built-in fingerprint is not semantic.
            threshold = max(0.76, min(0.97, avg - std * 1.15 - 0.015))
            result[key] = {
                "tag": labels[key],
                "prototype": prototype,
                "threshold": threshold,
                "positives": len(positives),
            }
        with self.lock:
            self._prototype_cache = (now + 12.0, result)
        return result

    def suggestions(self, path: str, limit: int = 6) -> dict:
        vector = self.index.media_vector(path, self.encoder.name)
        if not vector:
            return {"ready": False, "items": [], "reason": "not-indexed"}
        frames = [row[2] for row in self.index.frame_vectors(path) if row[2]]
        existing = {tag.casefold() for tag in self.store.tags_for(path)}
        feedback = {key.casefold(): value for key, value in self.index.feedback_for(path).items()}
        prototypes = self._prototypes()
        items = []
        for key, row in prototypes.items():
            if key in existing or feedback.get(key) == -1:
                continue
            prototype = row["prototype"]
            threshold = float(row["threshold"])
            sim = cosine(vector, prototype)
            frame_sims = [cosine(frame, prototype) for frame in frames] if frames else [sim]
            coverage = sum(1 for value in frame_sims if value >= threshold - 0.035) / max(1, len(frame_sims))
            peak = max(frame_sims) if frame_sims else sim
            if sim < threshold or coverage < 0.34:
                continue
            confidence = max(0.0, min(1.0, 0.62 * sim + 0.23 * coverage + 0.15 * peak))
            items.append(
                {
                    "tag": row["tag"],
                    "confidence": round(confidence, 4),
                    "similarity": round(sim, 4),
                    "coverage": round(coverage, 3),
                    "positives": int(row["positives"]),
                    "source": "visual-prototype",
                }
            )
        items.sort(key=lambda item: (item["confidence"], item["positives"]), reverse=True)
        return {"ready": True, "items": items[: max(1, min(10, int(limit)))], "reason": ""}

    def status(self, path: str = "") -> dict:
        index_stats = self.index.stats(self.encoder.name)
        prototypes = self._prototypes()
        with self.lock:
            payload = {
                "ok": True,
                "encoder": self.encoder.name,
                "semanticModel": False,
                "libraryRunning": self.library_running,
                "queued": self.urgent.qsize() + len(self.library),
                "current": self.current,
                "completed": self.completed,
                "failed": self.failed,
                "lastError": self.last_error,
                "lastElapsedMs": round(self.last_elapsed_ms, 1),
                "indexed": index_stats["media"],
                "indexedFrames": index_stats["frames"],
                "learnedTags": len(prototypes),
                "minPositives": MIN_TAG_POSITIVES,
                "io": SCHEDULER.snapshot(),
            }
        if path:
            payload["pathIndexed"] = bool(self.index.media_vector(path, self.encoder.name))
        return payload


def install(server_module, smart_mode_module) -> None:
    Store = server_module.MediaStore

    # Keep the prototype cache coherent when a user confirms or removes tags.
    if not getattr(Store.set_tags, "_localhub_auto_tag_wrapped", False):
        original_set_tags = Store.set_tags

        def set_tags_with_visual_learning(self, paths, tags, mode="replace"):
            result = original_set_tags(self, paths, tags, mode)
            manager = getattr(self, "_auto_tag_manager", None)
            if manager is not None:
                manager.invalidate_prototypes()
            return result

        set_tags_with_visual_learning._localhub_auto_tag_wrapped = True
        Store.set_tags = set_tags_with_visual_learning

    original_make_handler = server_module.make_handler

    def make_handler(store):
        BaseHandler = original_make_handler(store)
        manager = AutoTagManager(store)
        store._auto_tag_manager = manager

        class AutoTagHandler(BaseHandler):
            def _send_auto_json(self, payload, status=HTTPStatus.OK):
                raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self._headers(status, "application/json; charset=utf-8", len(raw), {"Cache-Control": "no-store"})
                self.wfile.write(raw)

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                if parsed.path == "/api/auto-tag/status":
                    path = query.get("path", [""])[0]
                    return self._send_auto_json(manager.status(path))
                if parsed.path == "/api/auto-tag/suggestions":
                    path = query.get("path", [""])[0]
                    try:
                        store.resolve_media(path)
                        return self._send_auto_json({"ok": True, **manager.suggestions(path)})
                    except (ValueError, FileNotFoundError) as exc:
                        return self._send_auto_json({"ok": False, "error": str(exc)}, HTTPStatus.NOT_FOUND)
                return super().do_GET()

            def do_POST(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path not in {"/api/auto-tag/queue", "/api/auto-tag/library", "/api/auto-tag/feedback"}:
                    return super().do_POST()
                try:
                    data = self._read_json()
                    if parsed.path == "/api/auto-tag/queue":
                        path = str(data.get("path", ""))
                        store.resolve_media(path)
                        manager.queue_media(path)
                        return self._send_auto_json({"ok": True, **manager.status(path)})
                    if parsed.path == "/api/auto-tag/library":
                        action = str(data.get("action", "start"))
                        if action == "pause":
                            manager.pause_library()
                        elif action == "start":
                            manager.start_library()
                        else:
                            raise ValueError("未知后台分析操作")
                        return self._send_auto_json(manager.status())
                    path = str(data.get("path", ""))
                    tag = str(data.get("tag", "")).strip()
                    value = int(data.get("value", -1))
                    store.resolve_media(path)
                    manager.index.set_feedback(path, tag, value)
                    manager.invalidate_prototypes()
                    return self._send_auto_json({"ok": True})
                except FileNotFoundError as exc:
                    return self._send_auto_json({"ok": False, "error": str(exc)}, HTTPStatus.NOT_FOUND)
                except (ValueError, OSError) as exc:
                    return self._send_auto_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

        return AutoTagHandler

    server_module.make_handler = make_handler
