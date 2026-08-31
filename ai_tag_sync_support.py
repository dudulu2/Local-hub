from __future__ import annotations

import json
import os
import statistics
import threading
import time
import urllib.parse
from collections import deque
from http import HTTPStatus
from pathlib import Path

from siglip_encoder import ENCODER_NAME
from visual_encoder import cosine


class ManagedTagAssignments:
    """Track only tags that LocalHub AI is allowed to add/remove automatically.

    User-created tags remain ordinary MediaStore tags. When the user manually
    adds/replaces/removes a tag, that tag is promoted out of this AI-managed set
    so later AI setting changes cannot silently delete the user's own work.
    """

    def __init__(self, root: Path) -> None:
        self.path = Path(root).resolve() / ".localhub" / "ai-tag-assignments.json"
        self.lock = threading.RLock()
        self.rows: dict[str, list[str]] = self._load()

    def _load(self) -> dict[str, list[str]]:
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            rows = raw.get("items", {}) if isinstance(raw, dict) else {}
            if not isinstance(rows, dict):
                return {}
            clean: dict[str, list[str]] = {}
            for path, tags in rows.items():
                if isinstance(tags, list):
                    clean[str(path)] = [str(tag).strip() for tag in tags if str(tag).strip()]
            return clean
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps({"version": 1, "items": self.rows}, ensure_ascii=False, indent=2), "utf-8")
        os.replace(temp, self.path)

    def get(self, path: str) -> list[str]:
        with self.lock:
            return list(self.rows.get(str(path), []))

    def set(self, path: str, tags: list[str]) -> None:
        clean: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            text = str(tag).strip()
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            clean.append(text)
        with self.lock:
            if clean:
                self.rows[str(path)] = clean
            else:
                self.rows.pop(str(path), None)
            self._save()

    def note_manual_change(self, paths: list[str], tags: list[str], mode: str) -> None:
        keys = {str(tag).strip().casefold() for tag in tags if str(tag).strip()}
        changed = False
        with self.lock:
            for path in paths:
                path = str(path)
                previous = list(self.rows.get(path, []))
                if not previous:
                    continue
                if mode == "replace":
                    # A full manual replacement means every surviving tag now
                    # belongs to the user, not to the AI lifecycle.
                    self.rows.pop(path, None)
                    changed = True
                    continue
                kept = [tag for tag in previous if tag.casefold() not in keys]
                if kept != previous:
                    changed = True
                    if kept:
                        self.rows[path] = kept
                    else:
                        self.rows.pop(path, None)
            if changed:
                self._save()


class AITagReconciler:
    def __init__(self, manager, store, assignments: ManagedTagAssignments, raw_set_tags) -> None:
        self.manager = manager
        self.store = store
        self.assignments = assignments
        self.raw_set_tags = raw_set_tags
        self.lock = threading.RLock()
        self.queue: deque[str] = deque()
        self.queued: set[str] = set()
        self.wake = threading.Event()
        self.stop = getattr(manager, "stop", threading.Event())
        self.revision = 0
        self.changes: deque[tuple[int, str]] = deque(maxlen=512)
        self.sync_running = False
        self.sync_total = 0
        self.sync_done = 0
        self.last_error = ""
        threading.Thread(target=self._worker, name="LocalHubAITagSync", daemon=True).start()

    def settings(self) -> dict:
        settings_store = getattr(self.store, "_ai_settings_store", None)
        if settings_store is None:
            return {}
        try:
            return settings_store.snapshot()
        except Exception:
            return {}

    def queue_path(self, path: str) -> None:
        path = str(path or "").strip()
        if not path:
            return
        with self.lock:
            if path in self.queued:
                return
            self.queued.add(path)
            self.queue.append(path)
        self.wake.set()

    def reconcile_all(self) -> None:
        try:
            rows = self.manager.index.all_media(ENCODER_NAME)
            paths = [str(row.get("path", "")) for row in rows if row.get("path")]
        except Exception:
            paths = []
        with self.lock:
            self.sync_running = True
            self.sync_total = len(paths)
            self.sync_done = 0
        for path in paths:
            self.queue_path(path)
        if not paths:
            with self.lock:
                self.sync_running = False

    def _prompt_scores(self, path: str) -> list[tuple[str, float]] | None:
        settings = self.settings()
        if not settings.get("aiOptIn", False):
            return []
        if not getattr(self.manager, "_siglip_enabled", False):
            try:
                if not self.manager._enable_siglip():
                    return None
            except Exception:
                return None

        try:
            text_vectors = self.manager._siglip_prompt_vectors()
        except Exception:
            return None
        if not text_vectors:
            return None

        required_keys = {
            str(row.get("tag", "")).strip().casefold()
            for group in settings.get("groups", [])
            if isinstance(group, dict) and group.get("enabled")
            for row in (group.get("tags", []) if isinstance(group.get("tags"), list) else [])
            if isinstance(row, dict) and str(row.get("tag", "")).strip()
        }
        available_keys = {str(tag).strip().casefold() for tag in text_vectors}
        if required_keys:
            coverage = len(required_keys & available_keys) / max(1, len(required_keys))
            if coverage < 0.97:
                try:
                    warmer = getattr(self.manager, "_start_siglip_prompt_warmup", None)
                    if callable(warmer):
                        warmer()
                except Exception:
                    pass
                return None

        try:
            frames = [row[2] for row in self.manager.index.frame_vectors(path) if row[2]]
            if not frames:
                vector = self.manager.index.media_vector(path, ENCODER_NAME)
                frames = [vector] if vector else []
            if not frames:
                return None
            feedback = {key.casefold(): int(value) for key, value in self.manager.index.feedback_for(path).items()}
        except Exception:
            return None

        scored: list[tuple[str, float]] = []
        for tag, text_vector in text_vectors.items():
            if feedback.get(str(tag).casefold()) == -1:
                continue
            values = sorted(cosine(frame, text_vector) for frame in frames)
            if not values:
                continue
            mean_score = statistics.fmean(values)
            upper = values[max(0, int((len(values) - 1) * 0.75))]
            peak = values[-1]
            score = mean_score * 0.55 + upper * 0.30 + peak * 0.15
            scored.append((str(tag), float(score)))
        scored.sort(key=lambda row: row[1], reverse=True)
        return scored

    @staticmethod
    def _select(scored: list[tuple[str, float]], settings: dict) -> list[str]:
        """Select precise tags per semantic group, with a tiny usable fallback."""
        if not scored:
            return []
        score_map = {str(tag).casefold(): (str(tag), float(score)) for tag, score in scored}
        selected: list[str] = []
        selected_keys: set[str] = set()
        fallback_groups: list[tuple[str, list[tuple[str, float]], float, float]] = []

        for group in settings.get("groups", []):
            if not isinstance(group, dict) or not group.get("enabled"):
                continue
            candidates: list[tuple[str, float]] = []
            for row in group.get("tags", []):
                if not isinstance(row, dict):
                    continue
                key = str(row.get("tag", "")).strip().casefold()
                if key and key in score_map:
                    candidates.append(score_map[key])
            candidates.sort(key=lambda row: row[1], reverse=True)
            if len(candidates) < 3:
                continue

            values = [score for _, score in candidates]
            median = statistics.median(values)
            spread = statistics.pstdev(values) if len(values) > 1 else 0.0
            best = candidates[0][1]
            runner = candidates[1][1]
            best_lift = best - median
            gap = best - runner
            group_id = str(group.get("id", ""))
            fallback_groups.append((group_id, candidates, best_lift, spread))

            min_lift = max(0.0030, spread * 0.42)
            min_gap = max(0.0010, spread * 0.065)
            strong = best_lift >= min_lift and (gap >= min_gap or best_lift >= max(0.0075, spread * 0.82))
            if not strong:
                continue

            max_tags = 4 if group_id == "all" else 2
            cutoff = max(median + max(0.0025, spread * 0.36), best - (0.020 if group_id == "all" else 0.012))
            emitted = 0
            for tag, score in candidates:
                if emitted >= max_tags or score < cutoff:
                    break
                key = tag.casefold()
                if key in selected_keys:
                    continue
                selected_keys.add(key)
                selected.append(tag)
                emitted += 1

        if selected:
            return selected[:12]

        usable = [row for row in fallback_groups if row[1]]
        if not usable:
            return []
        usable.sort(key=lambda row: (row[0] == "all", row[2] / max(0.001, row[3])), reverse=True)
        _, candidates, _, _ = usable[0]
        return [candidates[0][0]] if candidates else []

    def _publish_catalog_tags(self, path: str, tags: list[str]) -> None:
        catalog = getattr(self.store, "_smart_catalog", None)
        if catalog is None:
            return
        try:
            with catalog.lock:
                item = catalog.by_id.get(path)
                if not item:
                    return
                item["tags"] = list(tags)
                blob = f"{item['name']} {item.get('folder','')} {' '.join(tags)}".casefold()
                for index, (_, row) in enumerate(catalog.search_rows):
                    if row is item or row.get("id") == path:
                        catalog.search_rows[index] = (blob, item)
                        break
        except Exception:
            pass

    def _mark_changed(self, path: str) -> None:
        with self.lock:
            self.revision += 1
            self.changes.append((self.revision, path))

    def reconcile_path(self, path: str) -> str:
        scored = self._prompt_scores(path)
        if scored is None:
            return "retry"
        desired = self._select(scored, self.settings())
        previous_ai = self.assignments.get(path)
        existing = self.store.tags_for(path)
        previous_keys = {tag.casefold() for tag in previous_ai}
        manual = [tag for tag in existing if tag.casefold() not in previous_keys]
        manual_keys = {tag.casefold() for tag in manual}
        managed = [tag for tag in desired if tag.casefold() not in manual_keys]
        merged = list(manual)
        seen = set(manual_keys)
        for tag in managed:
            key = tag.casefold()
            if key not in seen:
                seen.add(key)
                merged.append(tag)

        if merged != existing or managed != previous_ai:
            self.raw_set_tags(self.store, [path], merged, "replace")
            self.assignments.set(path, managed)
            self._publish_catalog_tags(path, merged)
            self._mark_changed(path)
        return "ok"

    def _worker(self) -> None:
        while not self.stop.is_set():
            path = ""
            with self.lock:
                if self.queue:
                    path = self.queue.popleft()
                    self.queued.discard(path)
            if not path:
                with self.lock:
                    if self.sync_running and not self.queued and not self.queue:
                        self.sync_running = False
                self.wake.wait(0.8)
                self.wake.clear()
                continue
            try:
                outcome = self.reconcile_path(path)
                if outcome == "retry":
                    if not self.stop.wait(0.9):
                        self.queue_path(path)
                    continue
                with self.lock:
                    if self.sync_running:
                        self.sync_done = min(self.sync_total, self.sync_done + 1)
            except Exception as exc:
                with self.lock:
                    self.last_error = str(exc)
                    if self.sync_running:
                        self.sync_done = min(self.sync_total, self.sync_done + 1)
            self.stop.wait(0.05)

    def status(self, since: int = 0) -> dict:
        with self.lock:
            paths: list[str] = []
            seen: set[str] = set()
            for revision, path in self.changes:
                if revision <= since or path in seen:
                    continue
                seen.add(path)
                paths.append(path)
            return {
                "ok": True,
                "revision": self.revision,
                "changed": paths[-120:],
                "syncRunning": self.sync_running,
                "syncTotal": self.sync_total,
                "syncDone": self.sync_done,
                "queued": len(self.queue),
                "lastError": self.last_error,
            }


def install(server_module, auto_tag_support_module, ai_center_support_module) -> None:
    app_dir = Path(server_module.APP_DIR)
    server_module.STATIC_FILES["/ai_tag_live_sync.js"] = app_dir / "ai_tag_live_sync.js"
    Manager = auto_tag_support_module.AutoTagManager
    MediaStore = server_module.MediaStore
    if getattr(Manager, "_localhub_managed_ai_tags", False):
        return

    raw_set_tags = MediaStore.set_tags
    original_manager_init = Manager.__init__
    original_analyze = Manager._analyze
    original_apply_settings = ai_center_support_module._apply_settings

    def manual_set_tags(self, paths, tags, mode="replace"):
        assignment_store = getattr(self, "_ai_managed_tag_store", None)
        if assignment_store is not None:
            assignment_store.note_manual_change([str(path) for path in paths], [str(tag) for tag in tags], str(mode))
        return raw_set_tags(self, paths, tags, mode)

    MediaStore.set_tags = manual_set_tags

    def manager_init(self, store):
        original_manager_init(self, store)
        assignments = ManagedTagAssignments(store.root)
        store._ai_managed_tag_store = assignments
        reconciler = AITagReconciler(self, store, assignments, raw_set_tags)
        self._ai_tag_reconciler = reconciler
        store._ai_tag_reconciler = reconciler

        def reconcile_existing_index():
            for _ in range(50):
                if self.stop.wait(0.20):
                    return
                settings_store = getattr(store, "_ai_settings_store", None)
                if settings_store is None:
                    continue
                try:
                    settings = settings_store.snapshot()
                    if settings.get("aiOptIn", False):
                        reconciler.reconcile_all()
                except Exception as exc:
                    with reconciler.lock:
                        reconciler.last_error = f"startup reconcile: {exc}"
                return

        threading.Thread(target=reconcile_existing_index, name="LocalHubAITagStartupSync", daemon=True).start()

    def analyze_and_tag(self, relative: str):
        outcome = original_analyze(self, relative)
        if outcome in {"ok", "cached"}:
            reconciler = getattr(self, "_ai_tag_reconciler", None)
            if reconciler is not None:
                reconciler.queue_path(relative)
        return outcome

    def apply_settings_and_sync(manager, settings_store, siglip_support_module):
        settings = original_apply_settings(manager, settings_store, siglip_support_module)
        reconciler = getattr(manager, "_ai_tag_reconciler", None)
        if reconciler is not None:
            # Changing enabled Tag groups or their English prompts only requires
            # rescoring cached vectors. Video frames are NOT decoded again.
            reconciler.reconcile_all()
        return settings

    Manager.__init__ = manager_init
    Manager._analyze = analyze_and_tag
    Manager._localhub_managed_ai_tags = True
    ai_center_support_module._apply_settings = apply_settings_and_sync

    original_make_handler = server_module.make_handler

    def make_handler(store):
        BaseHandler = original_make_handler(store)

        class AITagSyncHandler(BaseHandler):
            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path != "/api/ai/tag-sync":
                    return super().do_GET()
                try:
                    since = int(urllib.parse.parse_qs(parsed.query).get("since", ["0"])[0] or 0)
                except ValueError:
                    since = 0
                reconciler = getattr(store, "_ai_tag_reconciler", None)
                payload = reconciler.status(max(0, since)) if reconciler is not None else {"ok": True, "revision": 0, "changed": []}
                raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self._headers(HTTPStatus.OK, "application/json; charset=utf-8", len(raw), {"Cache-Control": "no-store"})
                self.wfile.write(raw)

        return AITagSyncHandler

    server_module.make_handler = make_handler
