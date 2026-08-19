from __future__ import annotations

import inspect
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import recommendation_support
import recovery_ui
import ts_compat_patch


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
        'id': item_id,
        'path': item_id,
        'name': name,
        'stem': Path(name).stem,
        'folder': folder,
        'type': 'video',
        'ext': 'mp4',
        'size': 123456,
        'modified': 1_700_000_000_000,
        'tags': tags,
        'rating': rating,
        'url': '/media/' + item_id,
    }


def validate_embedded_js() -> None:
    start = recovery_ui.SCRIPT.find('>') + 1
    end = recovery_ui.SCRIPT.rfind('</script>')
    source = recovery_ui.SCRIPT[start:end]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'recovery-ui.js'
        path.write_text(source, 'utf-8')
        result = subprocess.run(['node', '--check', str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def main() -> None:
    items = [
        video('people/alice_walk_01.mp4', 'people', ['alice', 'walk'], 5),
        video('people/alice_walk_02.mp4', 'people', ['alice', 'walk'], 4),
        video('people/alice_room.mp4', 'people', ['alice', 'indoor']),
        video('travel/beach.mp4', 'travel', ['sea', 'outdoor']),
    ]
    for i in range(1200):
        items.append(video(f'bulk/{i // 30}/clip_{i:04d}.mp4', f'bulk/{i // 30}', [f'bulk{i % 13}']))

    engine = recommendation_support.RecommendationEngine(FakeStore(items))
    started = time.perf_counter()
    result = engine.recommend('people/alice_walk_01.mp4', {}, {}, set(), 6)
    elapsed_ms = (time.perf_counter() - started) * 1000
    ids = [row['id'] for row in result]
    assert ids and ids[0] == 'people/alice_walk_02.mp4', ids[:4]
    assert 'people/alice_walk_01.mp4' not in ids
    assert elapsed_ms < 1500, elapsed_ms

    ui = recovery_ui.SCRIPT + recovery_ui.STYLE
    assert 'lh-video-portrait' in ui
    assert 'lhRecommendations' in ui
    assert '/api/recommend' in ui
    assert '/api/media/probe' not in ui
    assert '/api/playback/activity' not in ui
    assert 'SCHEDULER' not in ui
    validate_embedded_js()

    ts_source = inspect.getsource(ts_compat_patch._execute_ts)
    assert '+genpts+discardcorrupt' in ts_source
    assert 'aac_adtstoasc' in ts_source
    assert '+faststart' in ts_source
    assert 'frag_keyframe' not in ts_source
    assert '/api/compat/stream' not in ts_source

    print(f'recovery isolation smoke test passed ({elapsed_ms:.1f} ms)')


if __name__ == '__main__':
    main()
