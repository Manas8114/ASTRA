from __future__ import annotations

from collections import deque
from threading import Lock


class AnomalyMemoryBuffer:
    def __init__(self, capacity: int = 500) -> None:
        self.capacity = capacity
        self._items = deque(maxlen=capacity)
        self._lock = Lock()

    def add(self, error_vector: dict[str, float]) -> bool:
        with self._lock:
            self._items.append(error_vector)
            return len(self._items) == self.capacity

    def drain(self) -> list[dict[str, float]]:
        with self._lock:
            items = list(self._items)
            self._items.clear()
            return items
