from __future__ import annotations


class E2RCClient:
    async def send_control(self, action_type: str, parameters: dict) -> dict:
        return {"sent": True, "service_model": "RC v1.0", "action_type": action_type, "parameters": parameters}
