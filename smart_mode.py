from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
import urllib.parse
from collections import Counter, defaultdict
from http import HTTPStatus
from pathlib import Path

import smart_thumbnail

HOME_MIN = 13
HOME_MAX = 15
PAGE_LIMIT = 30
CHANGE_CHECK_INTERVAL = 8.0
VIDEO_EXTENSIONS = {".mp4", ".webm", ".m4v", ".mov", ".mkv", ".avi", ".ogv", ".mpeg", ".mpg", ".ts"}
WATCH_IGNORED_DIRS = {".git", ".localhub", "__pycache__", "node_modules", ".idea", ".vscode"}


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _thumb_url(rel: str) -> str:
    return "/api/smart/thumb?path=" + urllib.parse.quote(rel, safe="")


def _norm_stem(name: str) -> str:
    stem = Path(name).stem.casefold()
    stem = re.sub(r"(?:img|image|photo|pic|screenshot|scan|page|pict|dsc)[-_ ]*", "", stem)
    return re.sub(r"[\W_\d]+", "", stem)


def _pack_like(images: list[dict]) -> bool:
    if len(images) < 4:
        return False
    # Classify from already-indexed metadata; never decode the whole folder.
    sample = images[: min(24, len(images))]
    stems = [_norm_stem(item["name"]) for item in sample]
    useful = [stem for stem in stems if stem]
    name_similar = False
    if useful:
        prefixes = Counter(stem[: min(6, len(stem))] for stem in useful)
        name_similar = prefixes.most_common(1)[0][1] / len(useful) >= 0.55

    sizes = sorted(max(1, int(item.get("size", 1))) for item in sample)
    lo = sizes[max(0, len(sizes) // 5)]
    hi = sizes[min(len(sizes) - 1, (len(sizes) * 4) // 5)]
    size_similar = hi / max(1, lo) <= 1.75
    same_ext = Counter(item.get("ext", "") for item in sample).most_common(1)[0][1] / len(sample) >= 0.70
    return name_similar or (size_similar and same_ext)


def _media_public(item: dict) -> dict:
    return {
        "kind": item["type"],
        "id": item["id"],
        "name": item["name"],
        "stem": item.get("stem", Path(item["name"]).stem),
        "path": item["path"],
        "folder": item.get("folder", ""),
        "ext": item.get("ext", ""),
        "size": int(item.get("size", 0)),
        "modified": int(item.get("modified", 0)),
        "tags": list(item.get("tags", [])),
        "url": item["url"],
        "thumb": _thumb_url(item["id"]),
    }


def _pack_public(folder: str, images: list[dict]) -> dict:
    images = sorted(images, key=lambda item: item["name"].casefold())
    cover = images[0]
    return {
        "kind": "pack",
        "id": f"pack:{folder}",
        "folder": folder,
        "name": Path(folder).name if folder else "根目录图片",
        "count": len(images),
        "cover": cover["url"],
        "coverThumb": _thumb_url(cover["id"]),
        "modified": max(i.get("modified", 0) for i in images),
    }


class Catalog:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.ready = threading.Event()
        self.items: list[dict] = []
        self.by_id: dict[str, dict] = {}
        self.direct_by_folder: dict[str, list[dict]] = defaultdict(list)
        self.folder_stats: dict[str, dict] = {}
        self.search_rows: list[tuple[str, dict]] = []
        self.video_ids: set[str] = set()
        self.session_new_ids: list[str] = []
        self.initialized = False
        self.last_change_check = 0.0
        self._track_next_refresh = False
        self.built_at = 0.0
        self.building = False
        self._start_refresh()

    def _start_refresh(self) -> None:
        with self.lock:
            if self.building:
                return
            self.building = True
            self.ready.clear()
        threading.Thread(target=self._refresh_worker, name="LocalHubCatalog", daemon=True).start()

    def refresh(self, wait: bool = False, track_new: bool = False) -> None:
        with self.lock:
            if track_new:
                self._track_next_refresh = True
        self._start_refresh()
        if wait:
            self.ready.wait(20)

    def _refresh_worker(self) -> None:
        try:
            items = self.store.scan()
            by_id = {item["id"]: item for item in items}
            current_video_ids = {item["id"] for item in items if item["type"] == "video"}
            direct: dict[str, list[dict]] = defaultdict(list)
            stats: dict[str, dict] = {}
            for item in items:
                folder = item.get("folder", "")
                direct[folder].append(item)
                parts = folder.split("/") if folder else []
                for depth in range(1, len(parts) + 1):
                    path = "/".join(parts[:depth])
                    row = stats.setdefault(path, {"path": path, "name": parts[depth - 1], "videos": 0, "images": 0, "total": 0})
                    row["total"] += 1
                    row["videos" if item["type"] == "video" else "images"] += 1

            searches: list[tuple[str, dict]] = []
            for item in items:
                blob = f"{item['name']} {item.get('folder','')} {' '.join(item.get('tags',[]))}".casefold()
                searches.append((blob, item))

            with self.lock:
                previous_video_ids = set(self.video_ids)
                was_initialized = self.initialized
                track_new = bool(self._track_next_refresh)
                self._track_next_refresh = False
                self.items = items
                self.by_id = by_id
                self.direct_by_folder = direct
                self.folder_stats = stats
                self.search_rows = searches
                self.video_ids = current_video_ids
                self.built_at = time.time()

                existing = [item_id for item_id in self.session_new_ids if item_id in by_id]
                if was_initialized and track_new:
                    added = [
                        item["id"]
                        for item in sorted(items, key=lambda row: row.get("modified", 0), reverse=True)
                        if item["type"] == "video" and item["id"] not in previous_video_ids
                    ]
                    merged: list[str] = []
                    seen: set[str] = set()
                    for item_id in added + existing:
                        if item_id in seen:
                            continue
                        seen.add(item_id)
                        merged.append(item_id)
                    self.session_new_ids = merged
                else:
                    self.session_new_ids = existing
                    if not was_initialized:
                        # Everything present during a first build with no prior
                        # snapshot is the baseline, not an unread notification.
                        self.initialized = True
        finally:
            with self.lock:
                self.building = False
                self.ready.set()

    def _await(self) -> None:
        self.ready.wait(20)

    def _quick_video_ids(self) -> set[str]:
        """Cheap addition/removal check: paths only, no media stat/probe work."""
        result: set[str] = set()
        root = self.store.root
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in WATCH_IGNORED_DIRS and not d.startswith(".")]
            current_path = Path(current)
            for filename in files:
                if Path(filename).suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                absolute = current_path / filename
                try:
                    relative = absolute.relative_to(root)
                except ValueError:
                    continue
                if any(part.startswith(".") for part in relative.parts):
                    continue
                result.add(relative.as_posix())
        return result

    def detect_changes(self) -> bool:
        """Refresh the full catalog only when a throttled path check changed."""
        self._await()
        now = time.monotonic()
        with self.lock:
            if self.building or now - self.last_change_check < CHANGE_CHECK_INTERVAL:
                return False
            self.last_change_check = now
            known = set(self.video_ids)
        try:
            current = self._quick_video_ids()
        except OSError:
            return False
        if current == known:
            return False
        self.refresh(wait=True, track_new=True)
        return True

    def stats(self) -> dict:
        self._await()
        with self.lock:
            videos = sum(1 for item in self.items if item["type"] == "video")
            images = len(self.items) - videos
            return {
                "count": len(self.items), "videos": videos, "images": images,
                "folders": len(self.folder_stats), "builtAt": int(self.built_at * 1000),
                "newVideos": len(self.session_new_ids),
            }

    def folders(self, limit: int = 120) -> list[dict]:
        self._await()
        with self.lock:
            rows = [dict(row) for row in self.folder_stats.values()]

        # Sidebar folders must be emitted in real tree preorder. Sorting every
        # depth globally makes a child such as Videos/上课 appear after an
        # unrelated root folder (for example 亚洲), which visually attaches the
        # child to the wrong parent. Keep each child directly under its true
        # parent path instead.
        by_parent: dict[str, list[dict]] = defaultdict(list)
        known_paths = {row["path"] for row in rows}
        for row in rows:
            path = row["path"]
            parent = path.rsplit("/", 1)[0] if "/" in path else ""
            if parent and parent not in known_paths:
                parent = ""
            by_parent[parent].append(row)

        for siblings in by_parent.values():
            siblings.sort(key=lambda r: (-r["videos"], -r["images"], r["name"].casefold(), r["path"].casefold()))

        ordered: list[dict] = []
        seen: set[str] = set()

        def visit(parent: str) -> None:
            for row in by_parent.get(parent, []):
                path = row["path"]
                if path in seen or len(ordered) >= limit:
                    continue
                seen.add(path)
                ordered.append(row)
                visit(path)

        visit("")
        if len(ordered) < min(limit, len(rows)):
            leftovers = [row for row in rows if row["path"] not in seen]
            leftovers.sort(key=lambda r: (r["path"].casefold(),))
            ordered.extend(leftovers[: max(0, limit - len(ordered))])
        return ordered[:limit]

    def home(self) -> list[dict]:
        self._await()
        with self.lock:
            root_videos = [item for item in self.direct_by_folder.get("", []) if item["type"] == "video"]
            all_videos = [item for item in self.items if item["type"] == "video"]
            by_folder = defaultdict(list)
            for item in all_videos:
                if item.get("folder"):
                    by_folder[item["folder"]].append(item)

        root_videos.sort(key=lambda item: item.get("modified", 0), reverse=True)
        selected = root_videos[:HOME_MAX]
        selected_ids = {item["id"] for item in selected}
        if len(selected) < HOME_MIN:
            day = int(time.time() // 86400)
            seed_text = f"{self.store.root}|{day}"
            seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16)
            rng = random.Random(seed)
            folders = list(by_folder)
            rng.shuffle(folders)
            for folder in folders:
                choices = [x for x in by_folder[folder] if x["id"] not in selected_ids]
                if not choices:
                    continue
                item = rng.choice(choices)
                selected.append(item)
                selected_ids.add(item["id"])
                if len(selected) >= HOME_MIN:
                    break
            if len(selected) < HOME_MAX:
                rest = [item for item in all_videos if item["id"] not in selected_ids]
                rng.shuffle(rest)
                selected.extend(rest[: HOME_MAX - len(selected)])
        return [_media_public(item) for item in selected[:HOME_MAX]]

    def _folder_payload(self, folder: str) -> list[dict]:
        with self.lock:
            direct = list(self.direct_by_folder.get(folder, []))
            child_paths = set()
            prefix = folder + "/" if folder else ""
            for path in self.folder_stats:
                if not path.startswith(prefix) or path == folder:
                    continue
                remainder = path[len(prefix):]
                if "/" not in remainder:
                    child_paths.add(path)
            child_rows = [dict(self.folder_stats[path]) for path in child_paths]

        child_rows.sort(key=lambda row: row["name"].casefold())
        result: list[dict] = [{"kind": "folder", **row} for row in child_rows]
        videos = [item for item in direct if item["type"] == "video"]
        images = [item for item in direct if item["type"] == "image"]
        videos.sort(key=lambda item: item.get("modified", 0), reverse=True)
        result.extend(_media_public(item) for item in videos)

        # In a mixed folder, all stills collapse into one image pack. In an
        # image-only folder, pack them only when names or sizes look related.
        should_pack = bool(images) and (bool(videos) or _pack_like(images))
        if should_pack:
            result.append(_pack_public(folder, images))
        else:
            result.extend(_media_public(item) for item in images)
        return result

    def list_view(self, view: str, folder: str = "", q: str = "", offset: int = 0, limit: int = PAGE_LIMIT) -> dict:
        catalog_changed = False
        if view == "new":
            catalog_changed = self.detect_changes()
        else:
            self._await()
        limit = max(1, min(60, limit))
        offset = max(0, offset)
        if view == "folder":
            rows = self._folder_payload(folder)
            title = folder or "根目录"
        elif view == "packs":
            rows = []
            with self.lock:
                folders = list(self.direct_by_folder.keys())
            for path in folders:
                direct = list(self.direct_by_folder.get(path, []))
                images = [item for item in direct if item["type"] == "image"]
                videos = [item for item in direct if item["type"] == "video"]
                if images and (videos or _pack_like(images)):
                    rows.append(_pack_public(path, images))
            rows.sort(key=lambda row: row.get("modified", 0), reverse=True)
            title = "图包 / 图册"
        elif view == "search":
            needle = q.strip().casefold()
            with self.lock:
                matches = [item for blob, item in self.search_rows if needle and needle in blob]
            matches.sort(key=lambda item: item.get("modified", 0), reverse=True)
            rows = [_media_public(item) for item in matches]
            title = f"搜索：{q}"
        elif view == "new":
            with self.lock:
                rows = [
                    _media_public(self.by_id[item_id])
                    for item_id in self.session_new_ids
                    if item_id in self.by_id and self.by_id[item_id]["type"] == "video"
                ]
            title = "新视频"
        else:
            with self.lock:
                videos = [item for item in self.items if item["type"] == "video"]
            videos.sort(key=lambda item: item.get("modified", 0), reverse=True)
            rows = [_media_public(item) for item in videos]
            title = "全部视频"
        page = rows[offset: offset + limit]
        payload = {"title": title, "items": page, "total": len(rows), "offset": offset, "limit": limit, "hasMore": offset + limit < len(rows)}
        if view == "new":
            payload["catalogChanged"] = catalog_changed
        return payload

    def by_ids(self, ids: list[str]) -> list[dict]:
        self._await()
        with self.lock:
            rows = [self.by_id[item_id] for item_id in ids if item_id in self.by_id]
        return [_media_public(item) for item in rows]

    def pack(self, folder: str) -> dict:
        self._await()
        with self.lock:
            images = [item for item in self.direct_by_folder.get(folder, []) if item["type"] == "image"]
        images.sort(key=lambda item: item["name"].casefold())
        return {
            "folder": folder,
            "title": Path(folder).name if folder else "根目录图片",
            "images": [_media_public(item) for item in images],
        }


def install(server_module) -> None:
    original_make_handler = server_module.make_handler
    app_dir = Path(server_module.APP_DIR)
    smart_html = app_dir / "smart_index.html"
    smart_js = app_dir / "smart_ui.js"
    smart_css = app_dir / "smart_ui.css"
    server_module.STATIC_FILES["/library_experience.js"] = app_dir / "library_experience.js"
    server_module.STATIC_FILES["/library_experience.css"] = app_dir / "library_experience.css"

    def make_handler(store):
        BaseHandler = original_make_handler(store)
        catalog = Catalog(store)

        class SmartHandler(BaseHandler):
            server_version = "LocalHub/2.0"

            def _send_json(self, payload, status=HTTPStatus.OK):
                raw = _json_bytes(payload)
                self._headers(status, "application/json; charset=utf-8", len(raw), {"Cache-Control": "no-store"})
                self.wfile.write(raw)

            def _smart_static(self, path: Path, content_type: str):
                try:
                    raw = path.read_bytes()
                except OSError:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._headers(HTTPStatus.OK, content_type, len(raw), {"Cache-Control": "no-cache"})
                self.wfile.write(raw)

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                path = parsed.path
                query = urllib.parse.parse_qs(parsed.query)
                if path in {"/", "/index.html"}:
                    return self._smart_static(smart_html, "text/html; charset=utf-8")
                if path == "/smart_ui.js":
                    return self._smart_static(smart_js, "application/javascript; charset=utf-8")
                if path == "/smart_ui.css":
                    return self._smart_static(smart_css, "text/css; charset=utf-8")
                if path == "/api/smart/home":
                    return self._send_json({"items": catalog.home(), "folders": catalog.folders(), "stats": catalog.stats()})
                if path == "/api/smart/list":
                    try:
                        offset = int(query.get("offset", ["0"])[0] or 0)
                        limit = int(query.get("limit", [str(PAGE_LIMIT)])[0] or PAGE_LIMIT)
                    except ValueError:
                        offset, limit = 0, PAGE_LIMIT
                    payload = catalog.list_view(
                        query.get("view", ["videos"])[0],
                        query.get("folder", [""])[0],
                        query.get("q", [""])[0],
                        offset,
                        limit,
                    )
                    return self._send_json(payload)
                if path == "/api/smart/by-ids":
                    raw_ids = query.get("ids", [""])[0]
                    ids = [item for item in raw_ids.split("\n") if item][:120]
                    return self._send_json({"items": catalog.by_ids(ids)})
                if path == "/api/smart/pack":
                    return self._send_json(catalog.pack(query.get("folder", [""])[0]))
                if path == "/api/smart/rescan":
                    # Manual rescans include LocalHub's own rename/move workflow.
                    # They refresh the catalog but deliberately do not create new
                    # video notifications from path changes.
                    catalog.refresh(wait=True, track_new=False)
                    return self._send_json({"ok": True, "stats": catalog.stats()})
                if path == "/api/smart/thumb":
                    relative = query.get("path", [""])[0]
                    try:
                        media = store.resolve_media(relative)
                    except (ValueError, FileNotFoundError):
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    data = smart_thumbnail.get_thumbnail(media, 360)
                    if not data:
                        self.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
                        return
                    self._headers(HTTPStatus.OK, "image/jpeg", len(data), {"Cache-Control": "no-store"})
                    self.wfile.write(data)
                    return
                return super().do_GET()

        return SmartHandler

    server_module.make_handler = make_handler
