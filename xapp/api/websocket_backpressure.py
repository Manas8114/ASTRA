"""
xapp/api/websocket_backpressure.py
──────────────────────────────────────────────────────────────────────────────
WebSocket Backpressure Management for ASTRA xApp.

Addresses the critical slow-consumer problem in the WebSocket hub:
- Per-client bounded asyncio queues
- Configurable drop policies (oldest, newest, disconnect)
- Slow consumer detection and metrics
- Automatic cleanup of stale connections
- Prometheus metrics for observability

Usage:
    hub = WebSocketHub(settings=ws_settings)
    await hub.connect(websocket)
    await hub.broadcast(event)  # Non-blocking, handles backpressure internally
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from fastapi import WebSocket
from prometheus_client import Counter, Gauge, Histogram

from xapp.config import get_settings, WebSocketSettings

log = logging.getLogger("astra.websocket")

# ── Prometheus Metrics ───────────────────────────────────────────────────────

_WS_CLIENTS = Gauge(
    "astra_websocket_clients_connected",
    "Number of currently connected WebSocket clients",
)

_WS_MESSAGES_SENT = Counter(
    "astra_websocket_messages_sent_total",
    "Total WebSocket messages sent",
    ["client_id", "outcome"],  # outcome: sent, dropped, error
)

_WS_QUEUE_SIZE = Gauge(
    "astra_websocket_client_queue_size",
    "Current message queue size per client",
    ["client_id"],
)

_WS_QUEUE_DROPS = Counter(
    "astra_websocket_queue_drops_total",
    "Total messages dropped due to queue full",
    ["client_id", "policy"],  # policy: drop_oldest, drop_newest
)

_WS_SLOW_CONSUMER = Counter(
    "astra_websocket_slow_consumer_total",
    "Total slow consumer detections",
    ["client_id"],
)

_WS_SEND_DURATION = Histogram(
    "astra_websocket_send_duration_seconds",
    "Time spent sending messages to clients",
    ["client_id"],
    buckets=(0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)


# ── Drop Policy Enum ─────────────────────────────────────────────────────────

class DropPolicy(str, Enum):
    DROP_OLDEST = "drop_oldest"      # Remove oldest message, add new (default)
    DROP_NEWEST = "drop_newest"      # Discard new message, keep queue
    DISCONNECT = "disconnect"        # Close connection immediately


# ── Client State ─────────────────────────────────────────────────────────────

@dataclass
class WSClient:
    """Represents a connected WebSocket client with backpressure management."""
    websocket: WebSocket
    client_id: str
    queue: asyncio.Queue
    connected_at: float = field(default_factory=time.monotonic)
    last_ping_at: float = field(default_factory=time.monotonic)
    last_activity_at: float = field(default_factory=time.monotonic)
    messages_sent: int = 0
    messages_dropped: int = 0
    slow_consumer_count: int = 0
    _send_task: Optional[asyncio.Task] = None
    _closed: bool = False

    def __post_init__(self) -> None:
        # Metrics labels
        self._metrics_id = self.client_id.replace(".", "_").replace("-", "_")


# ── WebSocket Hub with Backpressure ──────────────────────────────────────────

class WebSocketHub:
    """
    WebSocket connection manager with per-client backpressure.

    Key features:
    - Each client gets a bounded asyncio.Queue
    - Background sender task per client drains queue to WebSocket
    - Broadcast is non-blocking: puts to queues, returns immediately
    - Slow consumers detected via queue depth + send latency
    - Configurable drop policy when queue is full
    - Automatic cleanup of disconnected/slow clients
    """

    def __init__(
        self,
        settings: Optional[WebSocketSettings] = None,
        max_clients: Optional[int] = None,
        client_queue_size: Optional[int] = None,
        drop_policy: Optional[DropPolicy] = None,
        slow_consumer_timeout: Optional[float] = None,
    ) -> None:
        self._settings = settings or get_settings().websocket
        self._max_clients = max_clients or self._settings.max_clients
        self._queue_size = client_queue_size or self._settings.client_queue_size
        self._drop_policy = drop_policy or DropPolicy(self._settings.drop_policy)
        self._slow_timeout = slow_consumer_timeout or self._settings.slow_consumer_timeout

        self._clients: dict[str, WSClient] = {}
        self._lock = asyncio.Lock()
        self._client_counter = 0
        self._broadcast_count = 0
        _WS_CLIENTS.set(0)

        log.info(
            "WebSocketHub initialized: max_clients=%d, queue_size=%d, drop_policy=%s",
            self._max_clients, self._queue_size, self._drop_policy.value,
        )

    async def connect(self, websocket: WebSocket) -> str:
        """
        Accept a new WebSocket connection.

        Returns:
            client_id assigned to this connection

        Raises:
            ConnectionRefusedError: If max_clients limit reached
        """
        async with self._lock:
            if len(self._clients) >= self._max_clients:
                log.warning("WebSocket connection refused: max clients (%d) reached", self._max_clients)
                await websocket.close(code=1013, reason="Server at capacity")
                raise ConnectionRefusedError("Max WebSocket clients reached")

            await websocket.accept()

            self._client_counter += 1
            client_id = f"ws_{self._client_counter}_{int(time.monotonic() * 1000)}"

            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
            client = WSClient(
                websocket=websocket,
                client_id=client_id,
                queue=queue,
            )
            self._clients[client_id] = client

            # Start background sender task for this client
            client._send_task = asyncio.create_task(self._sender_loop(client))
            _WS_CLIENTS.inc()

            log.info("WebSocket client connected: %s (total: %d)", client_id, len(self._clients))
            return client_id

    async def disconnect(self, client_id: str, code: int = 1000, reason: str = "Normal closure") -> bool:
        """
        Disconnect a client gracefully.

        Returns:
            True if client was found and disconnected
        """
        async with self._lock:
            client = self._clients.pop(client_id, None)

        if client is None:
            return False

        client._closed = True

        # Cancel sender task
        if client._send_task and not client._send_task.done():
            client._send_task.cancel()
            try:
                await client._send_task
            except asyncio.CancelledError:
                pass

        # Close WebSocket
        try:
            await client.websocket.close(code=code, reason=reason)
        except Exception:
            pass

        _WS_CLIENTS.dec()
        log.info("WebSocket client disconnected: %s (total: %d)", client_id, len(self._clients))
        return True

    async def broadcast(self, event: dict[str, Any]) -> dict[str, int]:
        """
        Broadcast an event to all connected clients.

        Non-blocking: puts event into each client's queue and returns immediately.
        Slow consumers are handled by their individual sender tasks.

        Returns:
            Dict with stats: {"queued": int, "dropped": int, "errors": int}
        """
        self._broadcast_count += 1
        event["_broadcast_id"] = self._broadcast_count
        event["_timestamp"] = time.time()

        stats = {"queued": 0, "dropped": 0, "errors": 0}

        # Get snapshot of clients to avoid holding lock during queue puts
        async with self._lock:
            clients = list(self._clients.values())

        for client in clients:
            try:
                await self._enqueue(client, event)
                stats["queued"] += 1
            except Exception as e:
                stats["errors"] += 1
                log.debug("Broadcast enqueue error for %s: %s", client.client_id, e)

        return stats

    async def send_to(self, client_id: str, event: dict[str, Any]) -> bool:
        """Send event to a specific client."""
        async with self._lock:
            client = self._clients.get(client_id)

        if client is None:
            return False

        try:
            await self._enqueue(client, event)
            return True
        except Exception:
            return False

    async def _enqueue(self, client: WSClient, event: dict[str, Any]) -> None:
        """Enqueue event with backpressure handling."""
        try:
            client.queue.put_nowait(event)
            _WS_QUEUE_SIZE.labels(client_id=client._metrics_id).set(client.queue.qsize())
        except asyncio.QueueFull:
            # Queue full — apply drop policy
            await self._handle_queue_full(client, event)

    async def _handle_queue_full(self, client: WSClient, event: dict[str, Any]) -> None:
        """Handle queue full according to drop policy."""
        client.messages_dropped += 1
        _WS_QUEUE_DROPS.labels(client_id=client._metrics_id, policy=self._drop_policy.value).inc()

        if self._drop_policy == DropPolicy.DROP_OLDEST:
            # Remove oldest, add new
            try:
                _ = client.queue.get_nowait()  # Discard oldest
                client.queue.put_nowait(event)
                log.debug("Dropped oldest message for client %s", client.client_id)
            except asyncio.QueueEmpty:
                pass  # Race condition, just drop new

        elif self._drop_policy == DropPolicy.DROP_NEWEST:
            # Drop the new event (already counted)
            log.debug("Dropped newest message for client %s (queue full)", client.client_id)

        elif self._drop_policy == DropPolicy.DISCONNECT:
            # Schedule disconnect
            log.warning("Disconnecting slow client %s (queue full)", client.client_id)
            asyncio.create_task(self.disconnect(client.client_id, code=1013, reason="Slow consumer"))

    async def _sender_loop(self, client: WSClient) -> None:
        """
        Background task that drains the client's queue and sends to WebSocket.

        Handles:
        - WebSocket send with timeout
        - Slow consumer detection
        - Automatic disconnect on repeated failures
        - Ping/pong keepalive
        """
        consecutive_errors = 0
        max_consecutive_errors = 5

        while not client._closed:
            try:
                # Wait for next message with timeout to allow ping checks
                try:
                    event = await asyncio.wait_for(
                        client.queue.get(),
                        timeout=self._settings.ping_interval,
                    )
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    await self._send_ping(client)
                    continue

                # Send message with timing
                start = time.monotonic()
                await client.websocket.send_json(event)
                duration = time.monotonic() - start

                client.messages_sent += 1
                client.last_activity_at = time.monotonic()
                consecutive_errors = 0

                _WS_MESSAGES_SENT.labels(
                    client_id=client._metrics_id, outcome="sent"
                ).inc()
                _WS_SEND_DURATION.labels(client_id=client._metrics_id).observe(duration)
                _WS_QUEUE_SIZE.labels(client_id=client._metrics_id).set(client.queue.qsize())

                # Slow consumer detection
                if duration > self._slow_timeout:
                    client.slow_consumer_count += 1
                    _WS_SLOW_CONSUMER.labels(client_id=client._metrics_id).inc()
                    log.warning(
                        "Slow consumer detected: %s (send took %.2fs, count=%d)",
                        client.client_id, duration, client.slow_consumer_count,
                    )

                    # If consistently slow, consider disconnecting
                    if client.slow_consumer_count > 10:
                        log.error("Client %s consistently slow — disconnecting", client.client_id)
                        await self.disconnect(client.client_id, code=1013, reason="Consistently slow consumer")
                        break

            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                _WS_MESSAGES_SENT.labels(
                    client_id=client._metrics_id, outcome="error"
                ).inc()

                log.warning(
                    "WebSocket send error for %s (consecutive=%d): %s",
                    client.client_id, consecutive_errors, e,
                )

                if consecutive_errors >= max_consecutive_errors:
                    log.error("Too many errors for client %s — disconnecting", client.client_id)
                    await self.disconnect(client.client_id, code=1011, reason="Repeated send errors")
                    break

                # Brief pause before retry
                await asyncio.sleep(0.1)

    async def _send_ping(self, client: WSClient) -> bool:
        """Send WebSocket ping frame."""
        try:
            await client.websocket.send_json({"type": "PING", "timestamp": time.time()})
            client.last_ping_at = time.monotonic()
            return True
        except Exception as e:
            log.debug("Ping failed for %s: %s", client.client_id, e)
            return False

    def get_client_stats(self, client_id: str) -> Optional[dict[str, Any]]:
        """Get statistics for a specific client."""
        client = self._clients.get(client_id)
        if not client:
            return None

        return {
            "client_id": client.client_id,
            "connected_at": client.connected_at,
            "uptime_seconds": time.monotonic() - client.connected_at,
            "messages_sent": client.messages_sent,
            "messages_dropped": client.messages_dropped,
            "slow_consumer_count": client.slow_consumer_count,
            "queue_size": client.queue.qsize(),
            "queue_capacity": self._queue_size,
            "queue_utilization": client.queue.qsize() / self._queue_size,
        }

    def get_all_stats(self) -> dict[str, Any]:
        """Get aggregate statistics for all clients."""
        total_sent = sum(c.messages_sent for c in self._clients.values())
        total_dropped = sum(c.messages_dropped for c in self._clients.values())
        total_slow = sum(c.slow_consumer_count for c in self._clients.values())
        total_queue = sum(c.queue.qsize() for c in self._clients.values())

        return {
            "total_clients": len(self._clients),
            "max_clients": self._max_clients,
            "total_messages_sent": total_sent,
            "total_messages_dropped": total_dropped,
            "total_slow_consumer_events": total_slow,
            "total_queued_messages": total_queue,
            "avg_queue_size": total_queue / max(len(self._clients), 1),
            "clients": {
                cid: self.get_client_stats(cid) for cid in self._clients
            },
        }

    async def cleanup_stale_clients(self, max_idle_seconds: float = 300) -> int:
        """
        Disconnect clients that have been idle too long.

        Returns:
            Number of clients disconnected
        """
        now = time.monotonic()
        stale = []

        async with self._lock:
            for client_id, client in self._clients.items():
                idle_time = now - client.last_activity_at
                if idle_time > max_idle_seconds:
                    stale.append(client_id)

        for client_id in stale:
            await self.disconnect(client_id, code=1001, reason="Idle timeout")

        if stale:
            log.info("Cleaned up %d stale WebSocket clients", len(stale))

        return len(stale)

    async def shutdown(self) -> None:
        """Gracefully disconnect all clients."""
        client_ids = list(self._clients.keys())
        for client_id in client_ids:
            await self.disconnect(client_id, code=1001, reason="Server shutdown")
        log.info("WebSocketHub shutdown complete")


# ── Backward Compatibility Wrapper ───────────────────────────────────────────

class WebSocketHubCompat:
    """
    Drop-in replacement for the old WebSocketHub interface.

    Maintains the same API as the original xapp/api/websocket_server.py
    but uses the new backpressure-enabled implementation internally.
    """

    def __init__(self) -> None:
        self._hub = WebSocketHub()
        self._clients_list: list[WebSocket] = []  # For compatibility

    async def connect(self, websocket: WebSocket) -> None:
        client_id = await self._hub.connect(websocket)
        self._clients_list.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        # Find client by websocket object (inefficient but compatible)
        for client_id, client in list(self._hub._clients.items()):
            if client.websocket is websocket:
                asyncio.create_task(self._hub.disconnect(client_id))
                if websocket in self._clients_list:
                    self._clients_list.remove(websocket)
                break

    async def broadcast(self, event: dict[str, Any]) -> None:
        await self._hub.broadcast(event)

    # Property for compatibility
    @property
    def clients(self) -> list[WebSocket]:
        return self._clients_list


# Export compat instance for drop-in replacement
websocket_hub = WebSocketHubCompat()