from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import smart_thumbnail
from io_scheduler import SCHEDULER
import playback_priority


def main() -> None:
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def slow_thumbnail(path, size=360):
        nonlocal calls
        with calls_lock:
            calls += 1
            if calls >= 2:
                entered.set()
        release.wait(2.0)
        return b"ok"

    smart_thumbnail.get_thumbnail = slow_thumbnail
    playback_priority.install()

    workers = [threading.Thread(target=lambda: smart_thumbnail.get_thumbnail(Path("dummy.mp4"), 360)) for _ in range(2)]
    for worker in workers:
        worker.start()
    assert entered.wait(1.0), "two thumbnail slots did not become active"

    started = time.monotonic()
    third = smart_thumbnail.get_thumbnail(Path("third.mp4"), 360)
    elapsed = time.monotonic() - started
    assert third is None, "third thumbnail request should be dropped instead of queued"
    assert elapsed < 0.25, f"third thumbnail request queued for {elapsed:.3f}s"

    SCHEDULER.note(active=True)
    started = time.monotonic()
    blocked = smart_thumbnail.get_thumbnail(Path("playing.mp4"), 360)
    elapsed = time.monotonic() - started
    assert blocked is None, "thumbnail work must yield while viewer is active"
    assert elapsed < 0.25, f"active-playback thumbnail gate took {elapsed:.3f}s"

    release.set()
    for worker in workers:
        worker.join(timeout=2.0)
        assert not worker.is_alive(), "thumbnail worker did not finish"

    SCHEDULER.note(active=False, seeking=False)
    assert not SCHEDULER.busy(), "scheduler failed to clear playback state"
    print("playback priority smoke test passed")


if __name__ == "__main__":
    main()
