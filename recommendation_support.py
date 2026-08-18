from __future__ import annotations

import json
import math
import re
import threading
import time
import urllib.parse
import zlib
from collections import defaultdict
from http import HTTPStatus
from pathlib import Path

RECOMMEND_LIMIT = 8
_TOKEN_RE = re.compile(r"[\w\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+", re.UNICODE)


def _norm(value: str) -> str:
    return " ".join(_TOKEN_RE.findall(str(value or "").casefold().replace("\\", "/")))


def _features(item: dict) -> frozenset[int]:
    """Cheap sparse metadata features. Never opens or decodes media files."""
    out: set[int] = set()
    name = str(item.get("stem") or Path(str(item.get("name", ""))).stem)
    folder = str(item.get("folder", ""))
    tags = [str(x).strip() for x in item.get("tags", []) if str(x).strip()]

    def add(namespace: str, value: str) -> None:
        value = _norm(value)
        if value:
            out.add(zlib.crc32(f"{namespace}:{value}".encode("utf-8", "ignore")) & 0xFFFFFFFF)

    normalized_name = _norm(name)
    for token in normalized_name.split():
        add("name", token)
    compact = normalized_name.replace(" ", "")
    if len(compact) >= 2:
        grams = [compact[i:i + 2] for i in range(len(compact) - 1)]
        step = max(1, len(grams) // 24)
        for gram in grams[::step][:24]:
            add("bi", gram)
    if len(compact) >= 3:
        grams = [compact[i:i + 3] for i in range(len(compact) - 2)]
        step = max(1, len(grams) // 24)
        for gram in grams[::step][:24]:
            add("tri", gram)

    parts = [x for x in folder.replace("\\", "/").split("/") if x]
    for part in parts[-3:]:
        add("folder", part)
    if folder:
        add("folder-path", folder)

    # Tags are the strongest explicit user signal. Replicate them into separate
    # namespaces so binary cosine naturally gives them more weight.
    for tag in tags:
        for salt in range(5):
            add(f"tag{salt}", tag)
    return frozenset(out)


def _cosine(left: frozenset[int], right: frozenset[int]) -> float:
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    overlap = sum(1 for x in left if x in right)
    return overlap / math.sqrt(len(left) * len(right))


def _tag_similarity(a: dict, b: dict) -> float:
    left = {_norm(x) for x in a.get("tags", []) if _norm(x)}
    right = {_norm(x) for x in b.get("tags", []) if _norm(x)}
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _parent(folder: str) -> str:
    parts = [x for x in str(folder or "").replace("\\", "/").split("/") if x]
    return "/".join(parts[:-1])


def _public(item: dict) -> dict:
    rel = str(item.get("id", ""))
    try:
        rating = max(0, min(5, int(item.get("rating", 0) or 0)))
    except (TypeError, ValueError):
        rating = 0
    return {
        "kind": "video",
        "id": rel,
        "name": item.get("name", Path(rel).name),
        "stem": item.get("stem", Path(str(item.get("name", rel))).stem),
        "path": item.get("path", rel),
        "folder": item.get("folder", ""),
        "ext": item.get("ext", ""),
        "size": int(item.get("size", 0) or 0),
        "modified": int(item.get("modified", 0) or 0),
        "tags": list(item.get("tags", [])),
        "rating": rating,
        "url": item.get("url", "/media/" + urllib.parse.quote(rel, safe="/")),
        "thumb": "/api/smart/thumb?path=" + urllib.parse.quote(rel, safe=""),
    }


class RecommendationEngine:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.signature: tuple[int, int] | None = None
        self.videos: list[dict] = []
        self.by_id: dict[str, dict] = {}
        self.vectors: dict[str, frozenset[int]] = {}

    def _snapshot(self) -> tuple[list[dict], tuple[int, int]]:
        catalog = getattr(self.store, "_smart_catalog", None)
        if catalog is None:
            return [], (0, 0)
        catalog._await()
        with catalog.lock:
            videos = [dict(x) for x in catalog.items if x.get("type") == "video"]
            return videos, (len(videos), int(catalog.built_at * 1000))

    def _ensure(self) -> None:
        videos, signature = self._snapshot()
        with self.lock:
            if self.signature == signature:
                return
        by_id = {str(x.get("id", "")): x for x in videos if x.get("id")}
        vectors = {item_id: _features(item) for item_id, item in by_id.items()}
        with self.lock:
            self.videos = videos
            self.by_id = by_id
            self.vectors = vectors
            self.signature = signature

    def recommend(self, current_id: str, history: dict, exposure: dict, favorites: set[str], limit: int = RECOMMEND_LIMIT) -> list[dict]:
        self._ensure()
        limit = max(1, min(12, int(limit or RECOMMEND_LIMIT)))
        now = int(time.time() * 1000)
        with self.lock:
            current = self.by_id.get(current_id)
            current_vec = self.vectors.get(current_id, frozenset())
            videos = list(self.videos)
            vectors = self.vectors
        if not current:
            return []

        current_folder = str(current.get("folder", ""))
        current_parent = _parent(current_folder)
        scored: list[tuple[float, dict]] = []

        for item in videos:
            item_id = str(item.get("id", ""))
            if not item_id or item_id == current_id:
                continue
            try:
                rating = int(item.get("rating", 0) or 0)
            except (TypeError, ValueError):
                rating = 0
            if 0 < rating <= 2:
                continue

            semantic = _cosine(current_vec, vectors.get(item_id, frozenset()))
            tag_sim = _tag_similarity(current, item)
            folder = str(item.get("folder", ""))
            same_folder = folder == current_folder
            sibling = bool(current_parent and _parent(folder) == current_parent and not same_folder)

            progress = history.get(item_id, {}) if isinstance(history, dict) else {}
            last_played = int(progress.get("at", 0) or 0) if isinstance(progress, dict) else 0
            age_days = (now - last_played) / 86400000.0 if last_played else 9999.0
            if age_days < 0.5 and len(videos) > limit * 3:
                continue
            history_factor = 0.12 if age_days < 2 else 0.45 if age_days < 14 else 0.82 if age_days < 60 else 1.0

            shown = exposure.get(item_id, {}) if isinstance(exposure, dict) else {}
            shown_at = int(shown.get("at", 0) or 0) if isinstance(shown, dict) else 0
            shown_count = int(shown.get("count", 0) or 0) if isinstance(shown, dict) else 0
            shown_age = (now - shown_at) / 86400000.0 if shown_at else 9999.0
            exposure_factor = 0.18 if shown_age < 1 else 0.5 if shown_age < 7 else 1.0
            exposure_factor /= 1.0 + min(10, shown_count) * 0.035

            score = semantic * 0.52 + tag_sim * 0.25
            score += 0.15 if same_folder else 0.07 if sibling else 0.0
            score += max(0, rating - 3) * 0.025
            if item_id in favorites:
                score += 0.025
            score *= 0.55 + history_factor * 0.45
            score *= 0.55 + exposure_factor * 0.45

            # Small deterministic exploration term changes every six hours and
            # prevents a large library from showing the exact same tail forever.
            bucket = int(time.time() // 21600)
            jitter = (zlib.crc32(f"{current_id}|{item_id}|{bucket}".encode("utf-8")) & 0xFFFF) / 65535.0
            score += jitter * 0.035
            scored.append((score, item))

        scored.sort(key=lambda row: row[0], reverse=True)
        selected: list[dict] = []
        folder_counts: defaultdict[str, int] = defaultdict(int)
        for _, item in scored:
            folder = str(item.get("folder", ""))
            if folder_counts[folder] >= 2:
                continue
            selected.append(item)
            folder_counts[folder] += 1
            if len(selected) >= limit:
                break

        # Small or poorly-tagged libraries may have too few diverse folders.
        if len(selected) < limit:
            selected_ids = {str(x.get("id", "")) for x in selected}
            for _, item in scored:
                if str(item.get("id", "")) in selected_ids:
                    continue
                selected.append(item)
                if len(selected) >= limit:
                    break
        return [_public(x) for x in selected[:limit]]


def install(server_module, smart_mode_module) -> None:
    """Install a recommendation endpoint without touching playback or media I/O."""
    original_catalog_init = smart_mode_module.Catalog.__init__
    if not getattr(original_catalog_init, "_lh_rec_wrapped", False):
        def catalog_init(self, store, *args, **kwargs):
            original_catalog_init(self, store, *args, **kwargs)
            store._smart_catalog = self
        catalog_init._lh_rec_wrapped = True
        smart_mode_module.Catalog.__init__ = catalog_init

    original_make_handler = server_module.make_handler

    def make_handler(store):
        BaseHandler = original_make_handler(store)
        engine = RecommendationEngine(store)

        class RecommendationHandler(BaseHandler):
            def do_POST(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path != "/api/recommend":
                    return super().do_POST()
                started = time.perf_counter()
                try:
                    data = self._read_json()
                    current = str(data.get("path", ""))
                    history = data.get("history", {})
                    exposure = data.get("exposure", {})
                    favorites = {str(x) for x in data.get("favorites", []) if str(x)}
                    try:
                        limit = int(data.get("limit", RECOMMEND_LIMIT) or RECOMMEND_LIMIT)
                    except (TypeError, ValueError):
                        limit = RECOMMEND_LIMIT
                    items = engine.recommend(current, history if isinstance(history, dict) else {}, exposure if isinstance(exposure, dict) else {}, favorites, limit)
                    payload = {"ok": True, "items": items, "tookMs": round((time.perf_counter() - started) * 1000.0, 1)}
                    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    self._headers(HTTPStatus.OK, "application/json; charset=utf-8", len(raw), {"Cache-Control": "no-store"})
                    self.wfile.write(raw)
                except Exception as exc:
                    # Recommendation is optional. Return a contained error instead
                    # of letting an auxiliary feature take down the request thread.
                    raw = json.dumps({"ok": False, "items": [], "error": str(exc)}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    self._headers(HTTPStatus.OK, "application/json; charset=utf-8", len(raw), {"Cache-Control": "no-store"})
                    self.wfile.write(raw)

        return RecommendationHandler

    server_module.make_handler = make_handler
