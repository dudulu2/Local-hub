from __future__ import annotations

import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import recommendation_support as rec


class FakeCatalog:
    def __init__(self, items):
        import threading
        self.items = items
        self.built_at = time.time()
        self.lock = threading.RLock()

    def _await(self):
        return None


class FakeStore:
    def __init__(self, items):
        self._smart_catalog = FakeCatalog(items)


def make_item(i: int, folder: str, tags: list[str], rating: int = 0):
    name = f"series-{i:04d}-scene-{i % 23}.mp4"
    return {
        "type": "video",
        "id": f"{folder}/{name}" if folder else name,
        "path": f"{folder}/{name}" if folder else name,
        "name": name,
        "stem": Path(name).stem,
        "folder": folder,
        "ext": "mp4",
        "size": 100_000_000 + i,
        "modified": i,
        "tags": tags,
        "rating": rating,
        "url": "/media/fake",
    }


def main() -> int:
    rng = random.Random(7)
    items = []
    folders = [f"group/{n}" for n in range(24)]
    tag_pool = ["3d", "indoor", "outdoor", "story", "short", "long", "cg", "game"]
    for i in range(3200):
        folder = folders[i % len(folders)]
        tags = rng.sample(tag_pool, k=2)
        rating = 1 if i in {9, 17, 31} else 0
        items.append(make_item(i, folder, tags, rating))

    store = FakeStore(items)
    engine = rec.RecommendationEngine(store)
    current = items[100]
    now = int(time.time() * 1000)
    history = {items[i]["id"]: now - (i % 240) * 86400000 for i in range(0, 800, 11)}
    exposure = {items[i]["id"]: {"at": now - (i % 10) * 86400000, "count": i % 5 + 1} for i in range(0, 1000, 13)}

    started = time.perf_counter()
    result = engine.recommend(current["id"], history, exposure, 10)
    elapsed = (time.perf_counter() - started) * 1000

    assert len(result) == 10, len(result)
    ids = [row["id"] for row in result]
    assert len(ids) == len(set(ids)), "duplicate recommendation"
    assert current["id"] not in ids
    assert all(not (0 < int(row.get("rating", 0) or 0) <= 2) for row in result), "low-rated item leaked"
    folder_counts = {}
    for row in result:
        folder_counts[row["folder"]] = folder_counts.get(row["folder"], 0) + 1
    assert max(folder_counts.values()) <= 3, folder_counts
    # This is deliberately loose for shared CI runners. The algorithm should be
    # metadata-only and comfortably sub-second for a few thousand videos.
    assert elapsed < 1500, f"recommendation too slow: {elapsed:.1f}ms"

    second_started = time.perf_counter()
    result2 = engine.recommend(current["id"], history, exposure, 10)
    second = (time.perf_counter() - second_started) * 1000
    assert len(result2) == 10
    assert second < 700, f"cached recommendation too slow: {second:.1f}ms"
    print(f"recommendation smoke test passed: first={elapsed:.1f}ms cached={second:.1f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
