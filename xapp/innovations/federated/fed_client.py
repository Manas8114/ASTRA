from __future__ import annotations

import httpx


class FederatedClient:
    def __init__(self, url: str) -> None:
        self.url = url

    async def aggregate(self, gradients: dict) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(f"{self.url}/aggregate", json={"gradients": gradients})
                response.raise_for_status()
                return response.json()
        except Exception:
            return None
