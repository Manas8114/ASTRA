from __future__ import annotations

from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


class WebSocketHub:
    def __init__(self) -> None:
        self.clients: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.clients.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.clients:
            self.clients.remove(websocket)

    async def broadcast(self, event: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for client in self.clients:
            try:
                await client.send_json(event)
            except Exception:
                stale.append(client)
        for client in stale:
            self.disconnect(client)


def websocket_router(hub: WebSocketHub) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await hub.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            hub.disconnect(websocket)

    return router
