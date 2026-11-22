"""In-memory rate limiting (not persisted), plus a persisted-cooldown helper."""
from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from collections.abc import Hashable


class Bucket:
    """Allow at most `limit` hits per `per` seconds for each key."""

    def __init__(self, limit: int, per: float) -> None:
        self.limit = limit
        self.per = per
        self._hits: dict[Hashable, deque[float]] = defaultdict(deque)

    def hit(self, key: Hashable, now: float | None = None) -> float:
        """Record a hit. Returns 0.0 if allowed, otherwise seconds to wait."""
        now = time.monotonic() if now is None else now
        q = self._hits[key]
        while q and now - q[0] >= self.per:
            q.popleft()
        if len(q) >= self.limit:
            return self.per - (now - q[0])
        q.append(now)
        return 0.0


class SlidingCounter:
    """Counts events per key inside a trailing time window."""

    def __init__(self) -> None:
        self._events: dict[Hashable, deque[float]] = defaultdict(deque)

    def add(self, key: Hashable, window: float, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        q = self._events[key]
        q.append(now)
        while q and now - q[0] > window:
            q.popleft()
        return len(q)

    def reset(self, key: Hashable) -> None:
        self._events.pop(key, None)


def remaining(last: float, cooldown: float, now: float) -> int:
    """Whole seconds left on a cooldown that started at `last` (0 when ready)."""
    return max(0, math.ceil(last + cooldown - now))
