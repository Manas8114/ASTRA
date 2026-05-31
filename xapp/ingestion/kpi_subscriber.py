from __future__ import annotations

import math
import random
from typing import AsyncIterator

from xapp.ingestion.kpi_schema import KPIVector


async def dev_kpi_stream(state = None, tick: int = 0) -> AsyncIterator[KPIVector]:
    while True:
        phase = tick / 60.0
        traffic = 0.5 + 0.35 * math.sin(phase)
        anomaly_window = (tick // 90) % 5
        throughput = 120 + 260 * traffic + random.gauss(0, 12)
        latency = 8 + 8 * traffic + random.gauss(0, 1.2)
        bler = 0.8 + 2.4 * traffic + random.gauss(0, 0.25)
        rsrp = -72 + 7 * traffic + random.gauss(0, 1.5)
        hsr = 98 - 1.0 * traffic + random.gauss(0, 0.25)
        util = 25 + 55 * traffic + random.gauss(0, 3)

        # Check for active manual injection override
        active_anomaly = None
        if state is not None:
            with state.lock:
                active_anomaly = state.injected_anomaly

        if active_anomaly:
            if active_anomaly == "CONGESTION":
                throughput *= 0.35
                latency *= 2.8
                util *= 1.35
            elif active_anomaly == "HIGH_LATENCY":
                latency += 120
            elif active_anomaly == "PACKET_LOSS":
                bler += 15
                rsrp -= 13
                throughput *= 0.45
            elif active_anomaly == "SLICE_OVERFLOW":
                util += 55
        elif tick % 90 > 45:
            if anomaly_window == 1:
                throughput *= 0.35
                latency *= 2.8
                util *= 1.35
            elif anomaly_window == 2:
                latency += 120
            elif anomaly_window == 3:
                bler += 15
                rsrp -= 13
                throughput *= 0.45
            elif anomaly_window == 4:
                util += 55

        yield KPIVector(
            dl_throughput_mbps=max(0, throughput),
            latency_ms=max(0, latency),
            bler_pct=max(0, bler),
            rsrp_dbm=rsrp,
            handover_success_rate=max(0, min(100, hsr)),
            slice_utilisation_pct=max(0, util),
        )
        tick += 1
