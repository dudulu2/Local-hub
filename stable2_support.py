from __future__ import annotations

import hashlib
import os
import random
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

CACHE_VERSION = "v1"
CACHE_LIMIT_BYTES = 768 * 1024 * 1024
CACHE_TRIM_BYTES = 640 * 1024 * 1024
HOVER_SLOTS = 6
HOME_TARGET = 15
HOME_ROOT_MAX = 5

_INSTALL_LOCK = threading.RLock()
_ACTIVE_CACHE: "PersistentPreviewCache | None" = None
_ORIGINAL_THUMB = None
_ORIGINAL_HOVER = None
_HOME_INSTALLED = False


def _pick_sample(rows: list[dict], count: int, rng) -> list[dict]:
    if count <= 0 or not rows:
        return []
    if count >= len(rows):
        result = list(rows)
        rng.shuffle(result)
        return result
    return rng.sample(rows, count)


def select_home_items(root_videos: list[dict], other_videos: list[dict], target: int = HOME_TARGET, rng=None) -> list[dict]:
    """Return a fresh home mix with root videos capped at one third of 15 slots."""
    rng = rng or random.SystemRandom()
    target = max(0, int(target or HOME_TARGET))
    root_count = min(len(root_videos), HOME_ROOT_MAX, target // 3 if target >= 3 else HOME_ROOT_MAX)
    selected = _pick_sample(root_videos, root_count, rng)
    selected_ids = {str(item.get("id", "")) for item in selected}
    others = [item for item in other_videos if str(item.get("id", "")) not in selected_ids]
    selected.extend(_pick_sample(others, max(0, target - len(selected)), rng))
    rng.shuffle(selected)
    return selected[:target]


def install_home_rotation(smart_mode_module) -> None:
    """Make every home request a fresh mix without changing catalog scanning."""
    global _HOME_INSTALLED
    with _INSTALL_LOCK:
        if _HOME_INSTALLED:
            return
        Catalog = smart_mode_module.Catalog

        def home(self):
            self._await()
            with self.lock:
                root_videos = [
                    item for item in self.direct_by_folder.get("", [])
                    if item.get("type") == "video"
                ]
                other_videos = [
                    item for item in self.items
                    if item.get("type") == "video" and item.get("folder")
                ]
            selected = select_home_items(root_videos, other_videos, getattr(smart_mode_module, "HOME_MAX", HOME_TARGET))
            return [smart_mode_module._media_public(item) for item in selected]

        home._lh_stable2_home = True
        Catalog.home = home
        _HOME_INSTALLED = True


class PersistentPreviewCache:
    """Disk-backed covers/hover frames generated only while the viewer is idle."""

    def __init__(self, store, smart_thumbnail_module, video_exts: set[str]):
        self.store = store
        self.root = Path(store.root).resolve()
        self.smart_thumbnail = smart_thumbnail_module
        self.video_exts = {str(x).lower() for x in video_exts}
        self.cache_dir = self.root / ".localhub" / "preview-cache" / CACHE_VERSION
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._cover_queue: deque[str] = deque()
        self._hover_queue: deque[tuple[str, int]] = deque()
        self._cover_pending: set[str] = set()
        self._hover_pending: set[tuple[str, int]] = set()
        self._playback_active = False
        self._idle_after = time.monotonic() + 1.5
        self._warm_process: subprocess.Popen | None = None
        self._writes = 0
        self._worker = threading.Thread(target=self._run, name="LocalHubPreviewCache", daemon=True)
        self._worker.start()

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        self._kill_warm_process()

    def _relative(self, path: Path) -> str | None:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except (OSError, ValueError):
            return None

    def _resolve(self, relative: str) -> Path | None:
        try:
            path = self.store.resolve_media(str(relative or ""))
        except (ValueError, FileNotFoundError, OSError):
            return None
        if path.suffix.lower() not in self.video_exts:
            return None
        return path

    def _digest(self, path: Path) -> str | None:
        rel = self._relative(path)
        if rel is None:
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        raw = f"{rel}\n{stat.st_size}\n{stat.st_mtime_ns}\n360".encode("utf-8", "ignore")
        return hashlib.sha256(raw).hexdigest()[:32]

    def _cache_path(self, path: Path, slot: int | None = None) -> Path | None:
        digest = self._digest(path)
        if not digest:
            return None
        suffix = "cover" if slot is None else f"h{max(0, min(HOVER_SLOTS - 1, int(slot)))}"
        return self.cache_dir / f"{digest}-{suffix}.jpg"

    def _read_path(self, target: Path | None) -> bytes | None:
        if target is None:
            return None
        try:
            data = target.read_bytes()
            if len(data) < 300:
                return None
            try:
                os.utime(target, None)
            except OSError:
                pass
            return data
        except OSError:
            return None

    def read_cover(self, relative: str) -> bytes | None:
        path = self._resolve(relative)
        return self._read_path(self._cache_path(path)) if path else None

    def read_hover(self, relative: str, slot: int) -> bytes | None:
        path = self._resolve(relative)
        return self._read_path(self._cache_path(path, slot)) if path else None

    def _write(self, target: Path | None, data: bytes | None) -> None:
        if target is None or not data or len(data) < 300:
            return
        try:
            if target.exists() and target.stat().st_size >= 300:
                return
        except OSError:
            pass
        temp = target.with_suffix(target.suffix + ".tmp")
        try:
            temp.write_bytes(data)
            os.replace(temp, target)
            self._writes += 1
            if self._writes % 128 == 0:
                threading.Thread(target=self._trim_cache, name="LocalHubPreviewCacheTrim", daemon=True).start()
        except OSError:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def capture_cover(self, path: Path, data: bytes | None) -> None:
        if self._relative(path) is not None:
            self._write(self._cache_path(path), data)

    def capture_hover(self, path: Path, slot: int, data: bytes | None) -> None:
        if self._relative(path) is not None:
            self._write(self._cache_path(path, slot), data)

    def set_playback_active(self, active: bool) -> None:
        with self._lock:
            self._playback_active = bool(active)
            if active:
                self._idle_after = float("inf")
            else:
                self._idle_after = time.monotonic() + 1.5
        if active:
            self._kill_warm_process()
        self._wake.set()

    def queue_paths(self, paths: list[str], include_hover: bool = True) -> None:
        added = False
        with self._lock:
            for relative in paths[:48]:
                relative = str(relative or "").replace("\\", "/").strip("/")
                if not relative:
                    continue
                path = self._resolve(relative)
                if not path:
                    continue
                cover_target = self._cache_path(path)
                if (not cover_target or not cover_target.exists()) and relative not in self._cover_pending:
                    if len(self._cover_queue) < 96:
                        self._cover_pending.add(relative)
                        self._cover_queue.append(relative)
                        added = True
                if include_hover:
                    for slot in range(HOVER_SLOTS):
                        key = (relative, slot)
                        target = self._cache_path(path, slot)
                        if target and target.exists():
                            continue
                        if key in self._hover_pending or len(self._hover_queue) >= 384:
                            continue
                        self._hover_pending.add(key)
                        self._hover_queue.append(key)
                        added = True
        if added:
            self._wake.set()

    def _idle(self) -> bool:
        with self._lock:
            return not self._playback_active and time.monotonic() >= self._idle_after

    def _next_job(self):
        with self._lock:
            if self._cover_queue:
                relative = self._cover_queue.popleft()
                self._cover_pending.discard(relative)
                return ("cover", relative, None)
            if self._hover_queue:
                relative, slot = self._hover_queue.popleft()
                self._hover_pending.discard((relative, slot))
                return ("hover", relative, slot)
            self._wake.clear()
            return None

    def _kill_warm_process(self) -> None:
        with self._lock:
            process = self._warm_process
            self._warm_process = None
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass

    def _frame(self, path: Path, seek: float, timeout: float = 6.0) -> bytes | None:
        if not self._idle():
            return None
        try:
            import media_probe
            exe = media_probe.ffmpeg_exe()
        except Exception:
            exe = None
        if not exe:
            return None
        command = [
            str(exe), "-hide_banner", "-loglevel", "error", "-nostdin",
            "-ss", f"{max(0.0, float(seek)):.3f}", "-noaccurate_seek", "-i", str(path),
            "-an", "-sn", "-dn", "-frames:v", "1",
            "-vf", "scale='min(360,iw)':-2",
            "-q:v", "8", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
        ]
        kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | 0x00004000
        try:
            process = subprocess.Popen(command, **kwargs)
        except OSError:
            return None
        with self._lock:
            if self._playback_active:
                try:
                    process.kill()
                except OSError:
                    pass
                return None
            self._warm_process = process
        try:
            stdout, _ = process.communicate(timeout=timeout)
            if not self._idle():
                return None
            return stdout if process.returncode == 0 and stdout and len(stdout) > 300 else None
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.communicate(timeout=0.5)
            except Exception:
                pass
            return None
        finally:
            with self._lock:
                if self._warm_process is process:
                    self._warm_process = None

    def _generate_cover(self, path: Path) -> bytes | None:
        if not self._idle():
            return None
        try:
            data = self.smart_thumbnail._shell_thumbnail(path, 360)
        except Exception:
            data = None
        if data:
            return data
        return self._frame(path, 1.0) or self._frame(path, 0.0)

    def _generate_hover(self, path: Path, slot: int) -> bytes | None:
        if not self._idle():
            return None
        try:
            seek = float(self.smart_thumbnail._hover_seek(path, slot))
        except Exception:
            seek = (3.0, 8.0, 18.0, 36.0, 72.0, 120.0)[slot]
        return self._frame(path, seek)

    def _requeue(self, kind: str, relative: str, slot: int | None) -> None:
        with self._lock:
            if kind == "cover":
                if relative not in self._cover_pending and len(self._cover_queue) < 96:
                    self._cover_pending.add(relative)
                    self._cover_queue.appendleft(relative)
            elif slot is not None:
                key = (relative, slot)
                if key not in self._hover_pending and len(self._hover_queue) < 384:
                    self._hover_pending.add(key)
                    self._hover_queue.appendleft(key)
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(0.5)
            if self._stop.is_set():
                break
            if not self._idle():
                time.sleep(0.2)
                continue
            job = self._next_job()
            if not job:
                continue
            kind, relative, slot = job
            path = self._resolve(relative)
            if not path:
                continue
            if not self._idle():
                self._requeue(kind, relative, slot)
                continue
            if kind == "cover":
                target = self._cache_path(path)
                if target and not target.exists():
                    data = self._generate_cover(path)
                    if data:
                        self._write(target, data)
                    elif not self._idle():
                        self._requeue(kind, relative, slot)
            else:
                target = self._cache_path(path, int(slot or 0))
                if target and not target.exists():
                    data = self._generate_hover(path, int(slot or 0))
                    if data:
                        self._write(target, data)
                    elif not self._idle():
                        self._requeue(kind, relative, slot)
            time.sleep(0.12)

    def _trim_cache(self) -> None:
        try:
            files = [p for p in self.cache_dir.glob("*.jpg") if p.is_file()]
            rows = []
            total = 0
            for path in files:
                try:
                    stat = path.stat()
                except OSError:
                    continue
                total += stat.st_size
                rows.append((stat.st_mtime_ns, stat.st_size, path))
            if total <= CACHE_LIMIT_BYTES:
                return
            rows.sort(key=lambda row: row[0])
            for _, size, path in rows:
                try:
                    path.unlink()
                    total -= size
                except OSError:
                    pass
                if total <= CACHE_TRIM_BYTES:
                    break
        except Exception:
            pass


def activate_preview_cache(store, smart_thumbnail_module, video_exts: set[str]) -> PersistentPreviewCache:
    global _ACTIVE_CACHE, _ORIGINAL_THUMB, _ORIGINAL_HOVER
    with _INSTALL_LOCK:
        if _ACTIVE_CACHE is not None:
            _ACTIVE_CACHE.close()
        manager = PersistentPreviewCache(store, smart_thumbnail_module, video_exts)
        _ACTIVE_CACHE = manager

        if _ORIGINAL_THUMB is None:
            _ORIGINAL_THUMB = smart_thumbnail_module.get_thumbnail

            def wrapped_thumbnail(path, size=360):
                data = _ORIGINAL_THUMB(path, size)
                current = _ACTIVE_CACHE
                if current is not None and data:
                    current.capture_cover(Path(path), data)
                return data

            smart_thumbnail_module.get_thumbnail = wrapped_thumbnail

        if _ORIGINAL_HOVER is None:
            _ORIGINAL_HOVER = smart_thumbnail_module.get_hover_frame

            def wrapped_hover(path, slot=0, size=360):
                data = _ORIGINAL_HOVER(path, slot=slot, size=size)
                current = _ACTIVE_CACHE
                if current is not None and data:
                    current.capture_hover(Path(path), int(slot or 0), data)
                return data

            smart_thumbnail_module.get_hover_frame = wrapped_hover
        return manager


def deactivate_preview_cache() -> None:
    global _ACTIVE_CACHE
    with _INSTALL_LOCK:
        manager = _ACTIVE_CACHE
        _ACTIVE_CACHE = None
    if manager is not None:
        manager.close()
