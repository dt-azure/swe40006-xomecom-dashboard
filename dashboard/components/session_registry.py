"""Thread-safe, process-local storage for dashboard session heartbeats."""

from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from time import monotonic

INACTIVITY_TIMEOUT_SECONDS = 90
_CLEANUP_LIMIT = 64


class SessionRegistry:
    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._lock = Lock()
        self._last_seen: OrderedDict[str, float] = OrderedDict()

    def register(self, session_id: str) -> None:
        """Record the first heartbeat without refreshing an existing entry."""
        with self._lock:
            now = self._clock()
            self._cleanup(now)
            self._last_seen.setdefault(session_id, now)

    def heartbeat(self, session_id: str) -> None:
        """Refresh a session, registering it if it is new or was removed."""
        with self._lock:
            now = self._clock()
            self._last_seen[session_id] = now
            self._last_seen.move_to_end(session_id)
            self._cleanup(now)

    def active_count(self) -> int:
        with self._lock:
            now = self._clock()
            self._cleanup(now)
            cutoff = now - INACTIVITY_TIMEOUT_SECONDS
            count = 0
            for last_seen in reversed(self._last_seen.values()):
                if last_seen <= cutoff:
                    break
                count += 1
            return count

    def cleanup_expired(self) -> int:
        """Remove up to one batch of expired entries and return its size."""
        with self._lock:
            return self._cleanup(self._clock())

    def _cleanup(self, now: float) -> int:
        # Entries are ordered by heartbeat time, so cleanup only checks the oldest.
        cutoff = now - INACTIVITY_TIMEOUT_SECONDS
        removed = 0
        while self._last_seen and removed < _CLEANUP_LIMIT:
            if next(iter(self._last_seen.values())) > cutoff:
                break
            self._last_seen.popitem(last=False)
            removed += 1
        return removed
