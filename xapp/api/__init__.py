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
- cr2e_router_factory: CR²E router factory (Phase 7) — mounts under /cr2e/
"""

from xapp.api.rest_api import rest_router
from xapp.api.a1_api import a1_router
from xapp.api.websocket_backpressure import WebSocketHub, websocket_hub, WebSocketHubCompat
from xapp.api.websocket_server import websocket_router  # Legacy router

# CR²E router — imported lazily to avoid hard dependency if cr2e/ is not installed
def cr2e_router_factory(engine=None):
    """
    Return the CR²E APIRouter mounted under /cr2e/.
    Requires cr2e/ package to be installed (pip install -r cr2e/requirements.txt).
    Returns None if cr2e is not available.
    """
    try:
        from cr2e.api.router import cr2e_router
        from cr2e.main import engine as cr2e_engine
        _engine = engine or cr2e_engine
        return cr2e_router(_engine)
    except ImportError:
        return None

__all__ = [
    "rest_router",
    "a1_router",
    "websocket_router",
    "WebSocketHub",
    "websocket_hub",
    "WebSocketHubCompat",
    "cr2e_router_factory",
]
