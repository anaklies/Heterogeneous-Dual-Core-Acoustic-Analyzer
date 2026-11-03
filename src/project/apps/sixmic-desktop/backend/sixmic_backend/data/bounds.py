"""Bounded queues and byte budgets with explicit overflow accounting.

Real-time views may drop old frames; recording consumers must confirm
continuity separately. Silent dropping is never acceptable.
"""
from __future__ import annotations

import collections
import threading
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class BoundedQueue(Generic[T]):
    def __init__(self, capacity: int, name: str = "queue", drop_policy: str = "oldest") -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if drop_policy not in ("oldest", "newest"):
            raise ValueError("drop_policy must be oldest or newest")
        self.capacity = capacity
        self.name = name
        self.drop_policy = drop_policy
        self._items: collections.deque[T] = collections.deque()
        self._lock = threading.Lock()
        self.enqueued = 0
        self.dequeued = 0
        self.dropped = 0
        self.high_watermark = 0

    def put(self, item: T) -> int:
        """Return number of dropped items (0 when accepted without loss)."""
        dropped = 0
        with self._lock:
            if len(self._items) >= self.capacity:
                if self.drop_policy == "oldest":
                    self._items.popleft()
                    self.dropped += 1
                    dropped = 1
                else:
                    self.dropped += 1
                    return 1
            self._items.append(item)
            self.enqueued += 1
            self.high_watermark = max(self.high_watermark, len(self._items))
        return dropped

    def get(self) -> T | None:
        with self._lock:
            if not self._items:
                return None
            self.dequeued += 1
            return self._items.popleft()

    def peek(self) -> T | None:
        with self._lock:
            return self._items[0] if self._items else None

    def drain(self) -> list[T]:
        with self._lock:
            items = list(self._items)
            self.dequeued += len(items)
            self._items.clear()
            return items

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"name": self.name, "capacity": self.capacity,
                    "depth": len(self._items), "enqueued": self.enqueued,
                    "dequeued": self.dequeued, "dropped": self.dropped,
                    "highWatermark": self.high_watermark,
                    "dropPolicy": self.drop_policy}


class ByteBudget:
    def __init__(self, capacity_bytes: int, name: str = "budget") -> None:
        if capacity_bytes < 0:
            raise ValueError("capacity must be >= 0")
        self.capacity_bytes = capacity_bytes
        self.name = name
        self._used = 0
        self._lock = threading.Lock()
        self.rejected = 0
        self.peak = 0

    def acquire(self, size: int) -> bool:
        if size < 0:
            raise ValueError("size must be >= 0")
        with self._lock:
            if self._used + size > self.capacity_bytes:
                self.rejected += size
                return False
            self._used += size
            self.peak = max(self.peak, self._used)
            return True

    def release(self, size: int) -> None:
        with self._lock:
            self._used = max(0, self._used - max(0, size))

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"name": self.name, "capacityBytes": self.capacity_bytes,
                    "usedBytes": self._used, "peakBytes": self.peak,
                    "rejectedBytes": self.rejected}
