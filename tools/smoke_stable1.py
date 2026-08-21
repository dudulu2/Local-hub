from __future__ import annotations

import inspect
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import recommendation_support


class FakeCatalog:
    def __init__(self, items):
        self.items = items
        self.lock = threading.RLock()
        self.built_at = time.time()

    def _await(self):
        return None


class FakeStore:
    def __init__(self, items):
        self._smart_catalog = FakeCatalog(items)


def item(idx: int, *, folder: str, tags: list[str], name: str, rating: int = 0):
    return {
        "type": "video",
        "id": f"{folder}/v{idx}.mp4" if folder else f"v{idx}.mp4",
        "name": name,
        "stem": Path(name).stem,
        "folder": folder,
        "ext": ".mp4",
        "tags": tags,
        "rating": rating,
    }


def main() -> int:
    move = (ROOT / "move_branding.js").read_text("utf-8")
    rec_ui = (ROOT / "recommendation_ui.js").read_text("utf-8")
    preview = (ROOT / "preview_support.py").read_text("utf-8")
    player = (ROOT / "player_v4.js").read_text("utf-8")

    for marker in ("LONG_PRESS_MS = 500", "folderBackBtn", "/api/smart/rescan", "location.reload()"):
        if marker not in move:
            raise RuntimeError(f"stable move/navigation marker missing: {marker}")

    if ".player-shell" in rec_ui:
        raise RuntimeError("recommendation UI must not override Player V4 player-shell geometry")
    if "lh-viewer-modal-lock" not in rec_ui or "lh-recommend-grid" not in rec_ui:
        raise RuntimeError("recommendation grid/modal scroll isolation missing")

    if preview.find("/player_v4.js") > preview.find("/recommendation_ui.js"):
        raise RuntimeError("recommendation UI must load after Player V4")
    if "videojs.use" not in player or "/transcode.mp4" not in player:
        raise RuntimeError("Player V4 source unexpectedly changed")

    thumb_source = inspect.getsource(recommendation_support._isolated_thumb)
    for forbidden in ("get_thumbnail(", "_shell_thumbnail", "_ffmpeg", "subprocess"):
        if forbidden in thumb_source:
            raise RuntimeError(f"recommendation cover path may compete with playback: {forbidden}")
    if "_cache_get" not in thumb_source:
        raise RuntimeError("stable recommendation covers must reuse existing thumbnail cache")

    items = [
        item(0, folder="people/alice", tags=["alice", "walk"], name="alice walk 001.mp4", rating=5),
        item(1, folder="people/alice", tags=["alice", "walk"], name="alice walk 002.mp4", rating=5),
        item(2, folder="people/alice", tags=["alice"], name="alice portrait.mp4", rating=4),
        item(3, folder="people/bob", tags=["bob"], name="unrelated bob.mp4"),
        item(4, folder="travel", tags=["city"], name="city night.mp4"),
    ]
    store = FakeStore(items)
    engine = recommendation_support.RecommendationEngine(store)
    current = items[0]["id"]
    result = engine.recommend(current, {}, {}, set(), limit=4)
    ids = [row["id"] for row in result]
    if current in ids or len(ids) != len(set(ids)):
        raise RuntimeError("recommendation leaked current item or duplicates")
    if not ids or ids[0] != items[1]["id"]:
        raise RuntimeError(f"strong related recommendation did not rank first: {ids}")

    print("Stable1 feature isolation smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
