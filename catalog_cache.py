from __future__ import annotations

import json
import os
import shutil
import threading
import time
from collections import defaultdict
from pathlib import Path

SNAPSHOT_VERSION = 2
SNAPSHOT_FILE = "catalog-v2.json"


def cleanup_legacy_thumbnail_cache(root: Path) -> None:
    """Remove LocalHub v1's app-owned disk thumbnails without blocking startup."""
    old = root / ".localhub" / "thumbnails"
    if not old.exists():
        return

    def worker() -> None:
        try:
            shutil.rmtree(old, ignore_errors=True)
        except Exception:
            pass

    threading.Thread(target=worker, name="LocalHubLegacyCacheCleanup", daemon=True).start()


def install(smart_mode_module) -> None:
    """Replace Catalog with a snapshot-aware subclass.

    A previous metadata snapshot can answer Home/search/folder requests immediately.
    A normal filesystem scan refreshes the snapshot in the background. The snapshot
    contains only file metadata; no image/video bytes or thumbnails are persisted.
    """
    BaseCatalog = smart_mode_module.Catalog

    class SnapshotCatalog(BaseCatalog):
        def __init__(self, store):
            self._snapshot_path = store.data_dir / SNAPSHOT_FILE
            self._snapshot_bootstrapped = False
            super().__init__(store)

        def _load_snapshot(self) -> tuple[list[dict], float] | None:
            try:
                raw = json.loads(self._snapshot_path.read_text("utf-8"))
                if raw.get("version") != SNAPSHOT_VERSION or not isinstance(raw.get("items"), list):
                    return None
                items = [item for item in raw["items"] if isinstance(item, dict) and item.get("id") and item.get("type") in {"video", "image"}]
                if not items:
                    return None
                built_at = float(raw.get("builtAt", 0.0) or 0.0)
                return items, built_at
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                return None

        def _apply_snapshot(self, items: list[dict], built_at: float) -> None:
            by_id = {item["id"]: item for item in items}
            direct: dict[str, list[dict]] = defaultdict(list)
            stats: dict[str, dict] = {}
            searches: list[tuple[str, dict]] = []

            for item in items:
                folder = str(item.get("folder", ""))
                direct[folder].append(item)
                parts = folder.split("/") if folder else []
                for depth in range(1, len(parts) + 1):
                    path = "/".join(parts[:depth])
                    row = stats.setdefault(
                        path,
                        {"path": path, "name": parts[depth - 1], "videos": 0, "images": 0, "total": 0},
                    )
                    row["total"] += 1
                    row["videos" if item.get("type") == "video" else "images"] += 1
                blob = f"{item.get('name','')} {folder} {' '.join(item.get('tags', []))}".casefold()
                searches.append((blob, item))

            with self.lock:
                self.items = items
                self.by_id = by_id
                self.direct_by_folder = direct
                self.folder_stats = stats
                self.search_rows = searches
                self.built_at = built_at or time.time()

        def _save_snapshot(self) -> None:
            with self.lock:
                items = list(self.items)
                built_at = self.built_at
            if not items:
                return
            try:
                self.store.data_dir.mkdir(parents=True, exist_ok=True)
                target = self._snapshot_path
                temp = target.with_suffix(".tmp")
                temp.write_text(
                    json.dumps(
                        {"version": SNAPSHOT_VERSION, "builtAt": built_at, "items": items},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "utf-8",
                )
                os.replace(temp, target)
            except OSError:
                pass

        def _start_refresh(self) -> None:
            # BaseCatalog.__init__ dispatches here after it initializes all index fields.
            if not self._snapshot_bootstrapped:
                self._snapshot_bootstrapped = True
                snapshot = self._load_snapshot()
                if snapshot:
                    items, built_at = snapshot
                    self._apply_snapshot(items, built_at)
                    self.ready.set()
                    # Keep the snapshot usable while a real scan refreshes it.
                    with self.lock:
                        if self.building:
                            return
                        self.building = True
                    threading.Thread(target=self._refresh_worker, name="LocalHubCatalogRefresh", daemon=True).start()
                    return
            # Explicit re-scan still waits for a fresh filesystem traversal.
            return super()._start_refresh()

        def _refresh_worker(self) -> None:
            super()._refresh_worker()
            self._save_snapshot()

    smart_mode_module.Catalog = SnapshotCatalog
