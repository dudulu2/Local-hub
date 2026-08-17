from __future__ import annotations

import hashlib
import json
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


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _norm_stem(name: str) -> str:
    stem = Path(name).stem.casefold()
    stem = re.sub(r"(?:img|image|photo|pic|screenshot|scan|page|pict|dsc)[-_ ]*", "", stem)
    return re.sub(r"[\W_\d]+", "", stem)


def _pack_like(images: list[dict]) -> bool:
    if len(images) < 4:
        return False
    # Cheap heuristic only: never decode thousands of images merely to classify a folder.
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
        "thumb": "/api/smart/thumb?path=" + urllib.parse.quote(item["id"], safe=""),
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

    def refresh(self, wait: bool = False) -> None:
        self._start_refresh()
        if wait:
            self.ready.wait(20)

    def _refresh_worker(self) -> None:
        try:
            items = self.store.scan()
            by_id = {item["id"]: item for item in items}
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
                self.items = items
                self.by_id = by_id
                self.direct_by_folder = direct
                self.folder_stats = stats
                self.search_rows = searches
                self.built_at = time.time()
        finally:
            with self.lock:
                self.building = False
                self.ready.set()

    def _await(self) -> None:
        self.ready.wait(20)

    def stats(self) -> dict:
        self._await()
        with self.lock:
            videos = sum(1 for item in self.items if item["type"] == "video")
            images = len(self.items) - videos
            return {
                "count": len(self.items), "videos": videos, "images": images,
                "folders": len(self.folder_stats), "builtAt": int(self.built_at * 1000),
            }

    def folders(self, limit: int = 120) -> list[dict]:
        self._await()
        with self.lock:
            rows = list(self.folder_stats.values())
        rows.sort(key=lambda r: (r["path"].count("/"), -r["videos"], -r["images"], r["path"].casefold()))
        return rows[:limit]

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
            # First pass: one item per folder for variety.
            for folder in folders:
                choices = [x for x in by_folder[folder] if x["id"] not in selected_ids]
                if not choices:
                    continue
                item = rng.choice(choices)
                selected.append(item); selected_ids.add(item["id"])
                if len(selected) >= HOME_MIN:
                    break
            # Second pass if the library has very few folders.
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
            child_rows = [self.folder_stats[path] for path in child_paths]

        child_rows.sort(key=lambda row: row["name"].casefold())
        result: list[dict] = [{"kind": "folder", **row} for row in child_rows]
        videos = [item for item in direct if item["type"] == "video"]
        images = [item for item in direct if item["type"] == "image"]
        videos.sort(key=lambda item: item.get("modified", 0), reverse=True)
        result.extend(_media_public(item) for item in videos)

        # Mixed folders behave like a real collection: videos are individual,
        # all still images are represented by one book/pack cover.
        should_pack = bool(images) and (bool(videos) or _pack_like(images))
        if should_pack:
            images.sort(key=lambda item: item["name"].casefold())
            cover = images[0]
            result.append({
                "kind": "pack", "id": f"pack:{folder}", "folder": folder,
                "name": Path(folder).name if folder else "根目录图片",
                "count": len(images), "cover": cover["url"], "modified": max(i.get("modified", 0) for i in images),
            })
        else:
            result.extend(_media_public(item) for item in images)
        return result

    def list_view(self, view: str, folder: str = "", q: str = "", offset: int = 0, limit: int = PAGE_LIMIT) -> dict:
        self._await()
        limit = max(1, min(60, limit)); offset = max(0, offset)
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
                    images.sort(key=lambda item: item["name"].casefold())
                    rows.append({"kind": "pack", "id": f"pack:{path}", "folder": path, "name": Path(path).name if path else "根目录图片", "count": len(images), "cover": images[0]["url"], "modified": max(i.get("modified", 0) for i in images)})
            rows.sort(key=lambda row: row.get("modified", 0), reverse=True)
            title = "图包 / 图册"
        elif view == "search":
            needle = q.strip().casefold()
            with self.lock:
                matches = [item for blob, item in self.search_rows if needle and needle in blob]
            matches.sort(key=lambda item: item.get("modified", 0), reverse=True)
            rows = [_media_public(item) for item in matches]
            title = f"搜索：{q}"
        else:
            with self.lock:
                videos = [item for item in self.items if item["type"] == "video"]
            videos.sort(key=lambda item: item.get("modified", 0), reverse=True)
            rows = [_media_public(item) for item in videos]
            title = "全部视频"
        page = rows[offset: offset + limit]
        return {"title": title, "items": page, "total": len(rows), "offset": offset, "limit": limit, "hasMore": offset + limit < len(rows)}

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
                    self.send_error(HTTPStatus.NOT_FOUND); return
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
                    payload = catalog.list_view(
                        query.get("view", ["videos"])[0],
                        query.get("folder", [""])[0],
                        query.get("q", [""])[0],
                        int(query.get("offset", ["0"])[0] or 0),
                        int(query.get("limit", [str(PAGE_LIMIT)])[0] or PAGE_LIMIT),
                    )
                    return self._send_json(payload)
                if path == "/api/smart/pack":
                    return self._send_json(catalog.pack(query.get("folder", [""])[0]))
                if path == "/api/smart/rescan":
                    catalog.refresh(wait=True)
                    return self._send_json({"ok": True, "stats": catalog.stats()})
                if path == "/api/smart/thumb":
                    relative = query.get("path", [""])[0]
                    try:
                        media = store.resolve_media(relative)
                    except (ValueError, FileNotFoundError):
                        self.send_error(HTTPStatus.NOT_FOUND); return
                    if media.suffix.lower() not in server_module.VIDEO_EXTS:
                        self.send_error(HTTPStatus.BAD_REQUEST); return
                    data = smart_thumbnail.get_thumbnail(media, 360)
                    if not data:
                        self.send_error(HTTPStatus.SERVICE_UNAVAILABLE); return
                    self._headers(HTTPStatus.OK, "image/jpeg", len(data), {"Cache-Control": "no-store"})
                    self.wfile.write(data)
                    return
                return super().do_GET()

        return SmartHandler

    server_module.make_handler = make_handler
