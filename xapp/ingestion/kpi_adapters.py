from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import AsyncIterator

import httpx

from xapp.ingestion.kpi_schema import KPI_NAMES, KPIVector
from xapp.ingestion.kpi_subscriber import dev_kpi_stream


class KPIAdapterError(RuntimeError):
    pass


async def prometheus_kpi_stream(state=None) -> AsyncIterator[KPIVector]:
    """Read KPI values from Prometheus HTTP API.

    Configure one instant query per KPI with env vars:
    ``PROM_QUERY_DL_THROUGHPUT_MBPS``, ``PROM_QUERY_LATENCY_MS``, etc.
    """

    base_url = os.getenv("PROMETHEUS_URL", "http://localhost:9091")
    interval = float(os.getenv("KPI_POLL_SECONDS", "1"))

    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            values: dict[str, float] = {}
            for name in KPI_NAMES:
                env_name = f"PROM_QUERY_{name.upper()}"
                query = os.getenv(env_name, name)
                resp = await client.get(f"{base_url}/api/v1/query", params={"query": query})
                resp.raise_for_status()
                payload = resp.json()
                result = payload.get("data", {}).get("result", [])
                if not result:
                    raise KPIAdapterError(f"Prometheus query returned no data: {query}")
                values[name] = float(result[0]["value"][1])
            yield KPIVector.from_dict(values)
            await asyncio.sleep(interval)


async def open5gs_file_kpi_stream(state=None) -> AsyncIterator[KPIVector]:
    """Tail a JSONL KPI file exported from Open5GS/log scraper.

    Each line must contain the six KPI fields. This is intentionally simple:
    it gives the lab stack a real file/socket boundary without hiding behind
    dashboard-generated data.
    """

    path = Path(os.getenv("OPEN5GS_KPI_JSONL", "data/open5gs_kpis.jsonl"))
    interval = float(os.getenv("KPI_POLL_SECONDS", "1"))
    position = 0
    while True:
        if not path.exists():
            raise KPIAdapterError(f"Open5GS KPI file not found: {path}")
        with path.open("r", encoding="utf-8") as handle:
            handle.seek(position)
            line = handle.readline()
            position = handle.tell()
        if line:
            yield KPIVector.from_dict(json.loads(line))
        await asyncio.sleep(interval)


def select_kpi_stream(state=None) -> AsyncIterator[KPIVector]:
    source = os.getenv("KPI_SOURCE", "dev").lower()
    if source == "dev":
        return dev_kpi_stream(state)
    if source == "prometheus":
        return prometheus_kpi_stream(state)
    if source in {"open5gs", "open5gs_file"}:
        return open5gs_file_kpi_stream(state)
    raise KPIAdapterError(f"Unsupported KPI_SOURCE={source}")
