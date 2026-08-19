from __future__ import annotations

import threading
import time


class IOScheduler:
    """Process-wide playback priority gate for background media work.

    The browser sends short-lived heartbeats while the viewer is active.
    Thumbnail and hover extraction may run only while the viewer is idle.
    TTLs prevent a crashed or closed tab from blocking background work forever.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active_until = 0.0
        self._seeking_until = 0.0
        self._last_interactive = 0.0

    def note(self, *, active: bool | None = None, seeking: bool | None = None) -> None:
        now = time.monotonic()
        with self._lock:
            if active is True:
                self._active_until = max(self._active_until, now + 30.0)
                self._last_interactive = now
            elif active is False:
                self._active_until = now
                self._last_interactive = now

            if seeking is True:
                self._seeking_until = max(self._seeking_until, now + 12.0)
                self._last_interactive = now
            elif seeking is False:
                self._seeking_until = now
                self._last_interactive = now

    def busy(self) -> bool:
        now = time.monotonic()
        with self._lock:
            return now < self._active_until or now < self._seeking_until

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self._lock:
            return {
                "active": now < self._active_until,
                "seeking": now < self._seeking_until,
                "activeFor": max(0.0, self._active_until - now),
                "idleFor": max(0.0, now - self._last_interactive) if self._last_interactive else 999999.0,
            }


SCHEDULER = IOScheduler()
