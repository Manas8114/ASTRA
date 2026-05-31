from __future__ import annotations

import json
from pathlib import Path

import httpx


class MultiCellCoordinator:
    def __init__(self, topology_path: str = "topology.json") -> None:
        self.topology_path = Path(topology_path)

    def neighbors(self, cell_id: str) -> list[str]:
        if not self.topology_path.exists():
            return []
        return json.loads(self.topology_path.read_text()).get(cell_id, [])

    async def broadcast(self, source_cell: str, action: str, parameter: dict) -> list[dict]:
        messages = []
        async with httpx.AsyncClient(timeout=3) as client:
            for neighbor in self.neighbors(source_cell):
                payload = {
                    "source_cell": source_cell,
                    "healing_action": action,
                    "parameter": parameter,
                    "expected_load_shift": parameter.get("pct", 0) * 0.75,
                }
                try:
                    await client.post(f"http://{neighbor}:8000/coordination", json=payload)
                except Exception:
                    pass
                messages.append(payload)
        return messages
