from __future__ import annotations

from collections import deque
from threading import Lock

import numpy as np

from xapp.ingestion.kpi_schema import KPIVector


class KPIBuffer:
    def __init__(self, window_size: int = 30) -> None:
        self.window_size = window_size
        self._samples: deque[KPIVector] = deque(maxlen=window_size)
        self._lock = Lock()

    def push(self, kpi_vector: KPIVector) -> None:
        with self._lock:
            self._samples.append(kpi_vector)

    def get_window(self) -> np.ndarray | None:
        with self._lock:
            if len(self._samples) < self.window_size:
                return None
            return np.array([sample.to_list() for sample in self._samples], dtype=np.float32)

    def is_ready(self) -> bool:
        with self._lock:
            return len(self._samples) == self.window_size

    def recent_average(self, n: int = 5) -> dict[str, float] | None:
        with self._lock:
            if not self._samples:
                return None
            rows = self._samples if len(self._samples) < n else list(self._samples)[-n:]
        arr = np.array([row.to_list() for row in rows], dtype=np.float32)
        from xapp.ingestion.kpi_schema import KPI_NAMES

        return dict(zip(KPI_NAMES, arr.mean(axis=0).astype(float).tolist()))
