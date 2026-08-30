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
    """Replace Catalog with a snapshot-aware, collection-first subclass."""
    BaseCatalog = smart_mode_module.Catalog
    media_public = smart_mode_module._media_public
    pack_public = smart_mode_module._pack_public

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
                return items, float(raw.get("builtAt", 0.0) or 0.0)
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
                    row = stats.setdefault(path,{"path":path,"name":parts[depth-1],"videos":0,"images":0,"total":0})
                    row["total"] += 1
                    row["videos" if item.get("type") == "video" else "images"] += 1
                searches.append((f"{item.get('name','')} {folder} {' '.join(item.get('tags', []))}".casefold(), item))
            with self.lock:
                self.items=items; self.by_id=by_id; self.direct_by_folder=direct
                self.folder_stats=stats; self.search_rows=searches; self.built_at=built_at or time.time()
                # The snapshot is the previous known library baseline. Restoring
                # it lets the background refresh identify videos copied in while
                # LocalHub was closed instead of silently treating them as old.
                self.video_ids={item["id"] for item in items if item.get("type")=="video"}
                self.initialized=True

        def _save_snapshot(self) -> None:
            with self.lock:
                items=list(self.items); built_at=self.built_at
            if not items:
                return
            try:
                self.store.data_dir.mkdir(parents=True, exist_ok=True)
                temp=self._snapshot_path.with_suffix(".tmp")
                temp.write_text(json.dumps({"version":SNAPSHOT_VERSION,"builtAt":built_at,"items":items},ensure_ascii=False,separators=(",",":")),"utf-8")
                os.replace(temp,self._snapshot_path)
            except OSError:
                pass

        def _start_refresh(self) -> None:
            if not self._snapshot_bootstrapped:
                self._snapshot_bootstrapped=True
                snapshot=self._load_snapshot()
                if snapshot:
                    items,built_at=snapshot
                    self._apply_snapshot(items,built_at)
                    self.ready.set()
                    with self.lock:
                        if self.building:
                            return
                        self.building=True
                    threading.Thread(target=self._refresh_worker,name="LocalHubCatalogRefresh",daemon=True).start()
                    return
            return super()._start_refresh()

        def _refresh_worker(self) -> None:
            super()._refresh_worker()
            self._save_snapshot()

        def _folder_payload(self, folder: str) -> list[dict]:
            """Folder view is a collection view, not a flat file dump.

            Videos remain individual cards. Two or more direct images become one
            book/pack card represented by the first image. A single image remains
            an ordinary image card. Child folders stay navigable.
            """
            with self.lock:
                direct=list(self.direct_by_folder.get(folder, []))
                child_paths=set()
                prefix=folder+"/" if folder else ""
                for path in self.folder_stats:
                    if not path.startswith(prefix) or path==folder:
                        continue
                    remainder=path[len(prefix):]
                    if "/" not in remainder:
                        child_paths.add(path)
                child_rows=[dict(self.folder_stats[path]) for path in child_paths]
            child_rows.sort(key=lambda row:row["name"].casefold())
            result=[{"kind":"folder",**row} for row in child_rows]
            videos=[item for item in direct if item["type"]=="video"]
            images=[item for item in direct if item["type"]=="image"]
            videos.sort(key=lambda item:item.get("modified",0),reverse=True)
            result.extend(media_public(item) for item in videos)
            if len(images)>=2:
                result.append(pack_public(folder,images))
            elif images:
                result.append(media_public(images[0]))
            return result

        def list_view(self, view: str, folder: str = "", q: str = "", offset: int = 0, limit: int = 30) -> dict:
            if view != "packs":
                return super().list_view(view, folder, q, offset, limit)
            self._await()
            limit=max(1,min(60,limit)); offset=max(0,offset)
            rows=[]
            with self.lock:
                folders=list(self.direct_by_folder.keys())
                direct_map={path:list(self.direct_by_folder.get(path,[])) for path in folders}
            for path,direct in direct_map.items():
                images=[item for item in direct if item["type"]=="image"]
                if len(images)>=2:
                    rows.append(pack_public(path,images))
            rows.sort(key=lambda row:row.get("modified",0),reverse=True)
            page=rows[offset:offset+limit]
            return {"title":"图包 / 图册","items":page,"total":len(rows),"offset":offset,"limit":limit,"hasMore":offset+limit<len(rows)}

    smart_mode_module.Catalog = SnapshotCatalog
