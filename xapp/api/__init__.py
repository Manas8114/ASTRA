"""
xapp/api/__init__.py
──────────────────────────────────────────────────────────────────────────────
API Layer for ASTRA xApp.

Exports:
- WebSocketHub: WebSocket connection manager with backpressure
- websocket_hub: Global compat instance
- websocket_router: FastAPI router for WebSocket endpoints
- rest_router: FastAPI router for REST endpoints
- a1_router: FastAPI router for A1 policy endpoints
"""

from xapp.api.rest_api import rest_router
from xapp.api.a1_api import a1_router
from xapp.api.websocket_backpressure import WebSocketHub, websocket_hub, WebSocketHubCompat
from xapp.api.websocket_server import websocket_router  # Legacy router

__all__ = [
    "rest_router",
    "a1_router",
    "websocket_router",
    "WebSocketHub",
    "websocket_hub",
    "WebSocketHubCompat",
]
