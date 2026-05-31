from __future__ import annotations

import json
from pathlib import Path


class HealingLog:
    def __init__(self, path: str = "logs/healing_audit.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")
