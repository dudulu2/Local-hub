from __future__ import annotations

import threading
import time


class IOScheduler:
    """Tiny process-wide gate that always prioritizes playback over background I/O.

    The browser sends heartbeats while a video is playing. Background workers
    are allowed to run only after playback/seeking has been idle for a grace
    period. A stale browser tab cannot block work forever because activity has a
    TTL.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._playing_until = 0.0
        self._seeking_until = 0.0
        self._last_interactive = 0.0

    def note(self, *, playing: bool | None = None, seeking: bool | None = None) -> None:
        now = time.monotonic()
        with self._changed:
            if playing is True:
                # Heartbeats are intentionally generous: throttled background
                # tabs must still protect an actively playing video.
                self._playing_until = max(self._playing_until, now + 30.0)
                self._last_interactive = now
            elif playing is False:
                self._playing_until = now
                self._last_interactive = now

            if seeking is True:
                self._seeking_until = max(self._seeking_until, now + 12.0)
                self._last_interactive = now
            elif seeking is False:
                self._seeking_until = now
                self._last_interactive = now
            self._changed.notify_all()

    def busy(self) -> bool:
        now = time.monotonic()
        with self._lock:
            return now < self._playing_until or now < self._seeking_until

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self._lock:
            return {
                "playing": now < self._playing_until,
                "seeking": now < self._seeking_until,
                "idleFor": max(0.0, now - self._last_interactive) if self._last_interactive else 999999.0,
            }

    def wait_background_idle(
        self,
        stop_event: threading.Event | None = None,
        *,
        grace: float = 4.0,
        timeout: float | None = None,
    ) -> bool:
        """Wait until playback is inactive and has stayed idle for ``grace``.

        Returns False when stopped or when timeout expires.
        """
        started = time.monotonic()
        with self._changed:
            while True:
                if stop_event is not None and stop_event.is_set():
                    return False
                now = time.monotonic()
                busy_for = max(self._playing_until, self._seeking_until) - now
                idle_for = now - self._last_interactive if self._last_interactive else grace
                if busy_for <= 0 and idle_for >= grace:
                    return True
                if timeout is not None and now - started >= timeout:
                    return False
                wait_for = 0.25
                if busy_for > 0:
                    wait_for = min(0.5, max(0.1, busy_for))
                elif idle_for < grace:
                    wait_for = min(0.5, max(0.1, grace - idle_for))
                self._changed.wait(wait_for)


SCHEDULER = IOScheduler()
