from __future__ import annotations

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


def video(item_id: str, folder: str, tags: list[str], rating: int = 0) -> dict:
    name = item_id.rsplit('/', 1)[-1]
    return {
        'id': item_id, 'path': item_id, 'name': name, 'stem': Path(name).stem,
        'folder': folder, 'type': 'video', 'ext': 'mp4', 'size': 123456,
        'modified': 1_700_000_000_000, 'tags': tags, 'rating': rating,
        'url': '/media/' + item_id,
    }


def main() -> None:
    items = [
        video('people/alice_walk_01.mp4', 'people', ['alice', 'walk'], 5),
        video('people/alice_walk_02.mp4', 'people', ['alice', 'walk'], 4),
        video('people/alice_room.mp4', 'people', ['alice', 'indoor']),
        video('travel/beach.mp4', 'travel', ['sea', 'outdoor']),
        video('misc/random.mp4', 'misc', ['other']),
    ]
    for i in range(1200):
        items.append(video(f'bulk/{i // 30}/clip_{i:04d}.mp4', f'bulk/{i // 30}', [f'bulk{i % 13}']))

    engine = recommendation_support.RecommendationEngine(FakeStore(items))
    started = time.perf_counter()
    result = engine.recommend('people/alice_walk_01.mp4', {}, {}, set(), 6)
    elapsed = (time.perf_counter() - started) * 1000

    ids = [row['id'] for row in result]
    assert ids and ids[0] == 'people/alice_walk_02.mp4', ids[:4]
    assert 'people/alice_walk_01.mp4' not in ids
    assert len(ids) == len(set(ids))
    assert elapsed < 1500, elapsed

    recent = {'people/alice_walk_02.mp4': {'at': int(time.time() * 1000)}}
    result2 = engine.recommend('people/alice_walk_01.mp4', recent, {}, set(), 6)
    assert result2 and result2[0]['id'] != 'people/alice_walk_02.mp4', result2[:2]
    assert engine.recommend('missing.mp4', {}, {}, set(), 6) == []

    print(f'recommendation isolation smoke test passed ({elapsed:.1f} ms)')


if __name__ == '__main__':
    main()
