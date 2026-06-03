from __future__ import annotations

import json
import os
import time
from pathlib import Path

from prometheus_client import Gauge, start_http_server

KPI_NAMES = [
    "dl_throughput_mbps",
    "latency_ms",
    "bler_pct",
    "rsrp_dbm",
    "handover_success_rate",
    "slice_utilisation_pct",
]

GAUGES = {
    name: Gauge(f"astra_{name}", f"ASTRA KPI {name}")
    for name in KPI_NAMES
}


def read_latest_jsonl(path: Path, last_pos: int) -> tuple[dict | None, int]:
    if not path.exists():
        return None, last_pos
    latest = None
    with path.open("r", encoding="utf-8") as handle:
        handle.seek(last_pos)
        for line in handle:
            if line.strip():
                latest = json.loads(line)
        return latest, handle.tell()


def main() -> None:
    source = Path(os.getenv("OPEN5GS_KPI_JSONL", "data/open5gs_kpis.jsonl"))
    port = int(os.getenv("OPEN5GS_KPI_PORT", "9090"))
    start_http_server(port)
    print(f"ASTRA KPI exporter listening on :{port}, source={source}")
    pos = 0
    while True:
        sample, pos = read_latest_jsonl(source, pos)
        if sample:
            for name in KPI_NAMES:
                if name in sample:
                    GAUGES[name].set(float(sample[name]))
        time.sleep(1)


if __name__ == "__main__":
    main()
