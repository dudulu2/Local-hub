from __future__ import annotations

import hashlib
import json
import math
import random
import re
import threading
import time
import urllib.parse
import zlib
from collections import defaultdict
from http import HTTPStatus
from pathlib import Path

RECOMMEND_LIMIT = 10
RECENT_WATCH_MS = 3 * 24 * 60 * 60 * 1000
RECENT_EXPOSURE_MS = 7 * 24 * 60 * 60 * 1000

_TOKEN_RE = re.compile(r"[\w\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+", re.UNICODE)
_SPLIT_RE = re.compile(r"[\s._\-\[\](){}【】（）]+")


def _stable_feature(value: str) -> int:
    return zlib.crc32(value.encode("utf-8", "ignore")) & 0xFFFFFFFF


def _normalize(value: str) -> str:
    value = str(value or "").casefold().replace("\\", "/")
    return " ".join(_TOKEN_RE.findall(value))


def _tokens(value: str) -> list[str]:
    text = _normalize(value)
    if not text:
        return []
    out: list[str] = []
    for token in text.split():
        if not token:
            continue
        out.append(token)
        if len(token) >= 4:
            out.append(token[:4])
    return out


def _char_ngrams(value: str, size: int = 3, limit: int = 36) -> list[str]:
    compact = "".join(ch for ch in _normalize(value) if not ch.isspace())
    if not compact:
        return []
    if len(compact) <= size:
        return [compact]
    grams = [compact[i : i + size] for i in range(len(compact) - size + 1)]
    if len(grams) <= limit:
        return grams
    # Evenly sample long filenames instead of letting one long title dominate.
    step = max(1, len(grams) // limit)
    return grams[::step][:limit]


def _embedding(item: dict) -> frozenset[int]:
    """Tiny local text embedding: hashed sparse features, no model or media I/O."""
    features: set[int] = set()
    name = str(item.get("stem") or Path(str(item.get("name", ""))).stem)
    folder = str(item.get("folder", ""))
    tags = [str(tag).strip() for tag in item.get("tags", []) if str(tag).strip()]

    for token in _tokens(name):
        features.add(_stable_feature("t:" + token))
    for gram in _char_ngrams(name, 2, 22):
        features.add(_stable_feature("b:" + gram))
    for gram in _char_ngrams(name, 3, 26):
        features.add(_stable_feature("g:" + gram))

    parts = [part for part in folder.replace("\\", "/").split("/") if part]
    for part in parts[-3:]:
        for token in _tokens(part):
            features.add(_stable_feature("f:" + token))
    if folder:
        features.add(_stable_feature("fp:" + folder.casefold()))

    # Tags are strong semantic signals; repeat them into independent namespaces
    # so binary cosine gives tag matches more weight without float vectors.
    for tag in tags:
        normalized = _normalize(tag)
        if not normalized:
            continue
        for salt in range(4):
            features.add(_stable_feature(f"tag{salt}:{normalized}"))

    return frozenset(features)


def _cosine_binary(left: frozenset[int], right: frozenset[int]) -> float:
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    overlap = sum(1 for feature in left if feature in right)
    return overlap / math.sqrt(len(left) * len(right))


def _tag_similarity(a: dict, b: dict) -> float:
    left = {str(x).casefold() for x in a.get("tags", []) if str(x).strip()}
    right = {str(x).casefold() for x in b.get("tags", []) if str(x).strip()}
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _parent(folder: str) -> str:
    parts = str(folder or "").replace("\\", "/").split("/")
    return "/".join(parts[:-1]) if len(parts) > 1 else ""


def _freshness(last_played: int, now_ms: int) -> float:
    if not last_played:
        return 1.0
    age_days = max(0.0, (now_ms - last_played) / 86400000.0)
    if age_days < 1:
        return 0.0
    if age_days < 3:
        return 0.08
    if age_days < 14:
        return 0.45
    if age_days < 60:
        return 0.75
    if age_days < 180:
        return 0.92
    return 1.0


def _exposure_factor(row: dict | None, now_ms: int) -> float:
    if not row:
        return 1.0
    at = int(row.get("at", 0) or 0)
    count = max(0, int(row.get("count", 0) or 0))
    if not at:
        return 1.0
    age_days = max(0.0, (now_ms - at) / 86400000.0)
    if age_days < 1:
        base = 0.03
    elif age_days < 3:
        base = 0.16
    elif age_days < 7:
        base = 0.35
    elif age_days < 21:
        base = 0.72
    else:
        base = 1.0
    return max(0.02, base / (1.0 + min(count, 12) * 0.035))


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

    def _catalog(self):
        return getattr(self.store, "_smart_catalog", None)

    def _snapshot(self) -> tuple[list[dict], tuple[int, int]]:
        catalog = self._catalog()
        if catalog is None:
            return [], (0, 0)
        catalog._await()
        with catalog.lock:
            items = [dict(item) for item in catalog.items if item.get("type") == "video"]
            signature = (len(items), int(catalog.built_at * 1000))
        return items, signature

    def _ensure_index(self) -> None:
        items, signature = self._snapshot()
        with self.lock:
            if self.signature == signature:
                return
        videos = items
        by_id = {str(item.get("id", "")): item for item in videos}
        vectors = {item_id: _embedding(item) for item_id, item in by_id.items()}
        with self.lock:
            self.videos = videos
            self.by_id = by_id
            self.vectors = vectors
            self.signature = signature

    def recommend(self, current_id: str, history: dict[str, int], exposure: dict[str, dict], limit: int = RECOMMEND_LIMIT) -> list[dict]:
        started = time.perf_counter()
        self._ensure_index()
        limit = max(1, min(18, int(limit or RECOMMEND_LIMIT)))
        now_ms = int(time.time() * 1000)
        with self.lock:
            current = self.by_id.get(current_id)
            current_vec = self.vectors.get(current_id, frozenset())
            videos = list(self.videos)
            vectors = self.vectors
        if not current:
            return []

        current_folder = str(current.get("folder", ""))
        current_parent = _parent(current_folder)
        scored: list[dict] = []
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

            last_played = int(history.get(item_id, 0) or 0)
            if last_played and now_ms - last_played < RECENT_WATCH_MS:
                # Recently watched items are rarely useful underneath another video.
                continue

            vector = vectors.get(item_id, frozenset())
            semantic = _cosine_binary(current_vec, vector)
            tag_sim = _tag_similarity(current, item)
            folder = str(item.get("folder", ""))
            same_folder = bool(folder == current_folder)
            sibling = bool(not same_folder and _parent(folder) == current_parent and current_parent)
            freshness = _freshness(last_played, now_ms)
            exposure_factor = _exposure_factor(exposure.get(item_id), now_ms)

            relation = semantic * 0.58 + tag_sim * 0.23 + (0.14 if same_folder else 0.07 if sibling else 0.0) + freshness * 0.05
            explore = freshness * 0.56 + exposure_factor * 0.30 + (0.14 if not same_folder else 0.02)
            relation *= 0.45 + 0.55 * exposure_factor

            scored.append({
                "item": item,
                "id": item_id,
                "vector": vector,
                "semantic": semantic,
                "tag": tag_sim,
                "same": same_folder,
                "sibling": sibling,
                "freshness": freshness,
                "exposure": exposure_factor,
                "relation": relation,
                "explore": explore,
            })

        if not scored:
            return []

        # Candidate pools. Strong stays related, weak favors medium similarity and
        # different locations, exploration favors stale/unseen/under-exposed items.
        strong_pool = sorted(scored, key=lambda row: row["relation"], reverse=True)[: max(60, limit * 10)]
        weak_pool = sorted(
            scored,
            key=lambda row: (
                (0.32 - abs(row["semantic"] - 0.24)) * 0.45
                + row["tag"] * 0.22
                + (0.10 if row["sibling"] else 0.0)
                + (0.14 if not row["same"] else -0.08)
                + row["freshness"] * 0.09
            ) * (0.55 + 0.45 * row["exposure"]),
            reverse=True,
        )[: max(90, limit * 14)]

        seed_text = f"{current_id}|{int(time.time() // 21600)}|{sum(int(v.get('count', 0) or 0) for v in exposure.values())}"
        rng = random.Random(int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16))
        explore_pool = list(scored)
        rng.shuffle(explore_pool)
        explore_pool.sort(key=lambda row: row["explore"] + rng.random() * 0.28, reverse=True)
        explore_pool = explore_pool[: max(120, limit * 18)]

        strong_target = max(1, round(limit * 0.4))
        weak_target = max(1, round(limit * 0.4))
        explore_target = max(0, limit - strong_target - weak_target)
        selected: list[dict] = []
        folder_counts: defaultdict[str, int] = defaultdict(int)

        def pick(pool: list[dict], target: int, diversity: float, folder_cap: int) -> None:
            for _ in range(target):
                best = None
                best_score = -1e9
                for row in pool:
                    if any(existing["id"] == row["id"] for existing in selected):
                        continue
                    folder = str(row["item"].get("folder", ""))
                    if folder_counts[folder] >= folder_cap:
                        continue
                    similarity_to_selected = 0.0
                    if selected:
                        similarity_to_selected = max(_cosine_binary(row["vector"], existing["vector"]) for existing in selected)
                    base = row["relation"] if pool is strong_pool else row["explore"] if pool is explore_pool else (
                        row["semantic"] * 0.40 + row["tag"] * 0.18 + row["freshness"] * 0.20 + row["exposure"] * 0.22
                    )
                    score = base - diversity * similarity_to_selected
                    if score > best_score:
                        best_score = score
                        best = row
                if best is None:
                    break
                selected.append(best)
                folder_counts[str(best["item"].get("folder", ""))] += 1

        pick(strong_pool, strong_target, diversity=0.34, folder_cap=2)
        pick(weak_pool, weak_target, diversity=0.48, folder_cap=2)
        pick(explore_pool, explore_target, diversity=0.62, folder_cap=1)

        # Fill shortages from the global ranked pool while keeping the diversity
        # penalty; this matters for very small libraries.
        if len(selected) < limit:
            fallback = sorted(scored, key=lambda row: row["relation"] + row["explore"] * 0.35, reverse=True)
            pick(fallback, limit - len(selected), diversity=0.52, folder_cap=3)

        result = [_public(row["item"]) for row in selected[:limit]]
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        # Internal diagnostics are useful during development but tiny and harmless.
        for row in result:
            row["_recMs"] = round(elapsed_ms, 1)
        return result


def install(server_module, smart_mode_module) -> None:
    # Capture the existing Catalog instance without changing smart_mode's public
    # API or causing a second filesystem scan.
    original_catalog_init = smart_mode_module.Catalog.__init__
    if not getattr(original_catalog_init, "_localhub_recommend_wrapped", False):
        def catalog_init(self, store, *args, **kwargs):
            original_catalog_init(self, store, *args, **kwargs)
            store._smart_catalog = self
        catalog_init._localhub_recommend_wrapped = True
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
                try:
                    data = self._read_json()
                    current = str(data.get("path", ""))
                    limit = int(data.get("limit", RECOMMEND_LIMIT) or RECOMMEND_LIMIT)
                    history_rows = data.get("history", []) if isinstance(data.get("history", []), list) else []
                    exposure_rows = data.get("exposure", []) if isinstance(data.get("exposure", []), list) else []
                    history = {
                        str(row.get("id", "")): int(row.get("at", 0) or 0)
                        for row in history_rows[:300]
                        if isinstance(row, dict) and row.get("id")
                    }
                    exposure = {
                        str(row.get("id", "")): {"at": int(row.get("at", 0) or 0), "count": int(row.get("count", 0) or 0)}
                        for row in exposure_rows[:400]
                        if isinstance(row, dict) and row.get("id")
                    }
                    items = engine.recommend(current, history, exposure, limit)
                    raw = json.dumps({"ok": True, "items": items}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    self._headers(HTTPStatus.OK, "application/json; charset=utf-8", len(raw), {"Cache-Control": "no-store"})
                    self.wfile.write(raw)
                except (ValueError, TypeError) as exc:
                    self._error_json(HTTPStatus.BAD_REQUEST, str(exc))
                except Exception as exc:
                    self._error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"推荐生成失败: {exc}")

        return RecommendationHandler

    server_module.make_handler = make_handler
