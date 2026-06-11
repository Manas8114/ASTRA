"""
xapp/persistence/redis_reliability.py
──────────────────────────────────────────────────────────────────────────────
Redis Reliability Layer for ASTRA xApp.

Enhances the base Redis client with:
- Retry queue with exponential backoff
- Backpressure handling (queue depth limits, client-side buffering)
- Health checks with automatic reconnection
- Dead-letter queue for failed operations
- Metrics for observability

Usage:
    from xapp.persistence.redis_reliability import ReliableRedisClient

    client = ReliableRedisClient()
    await client.start()
    await client.add_kpi_history_reliable(cell_id, kpi_data)
    await client.shutdown()
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import redis.asyncio as redis
from prometheus_client import Counter, Gauge, Histogram

from xapp.config import get_settings
from xapp.resilience import create_redis_circuit_breaker

log = logging.getLogger("astra.redis_reliability")

# ── Prometheus Metrics ───────────────────────────────────────────────────────

_REDIS_OPS_TOTAL = Counter(
    "astra_redis_operations_total",
    "Total Redis operations",
    ["operation", "outcome"],  # outcome: success, retry, failed, dlq
)

_REDIS_QUEUE_DEPTH = Gauge(
    "astra_redis_retry_queue_depth",
    "Current depth of retry queue",
    ["queue_name"],
)

_REDIS_DLQ_SIZE = Gauge(
    "astra_redis_dlq_size",
    "Size of dead-letter queue",
)

_REDIS_OP_DURATION = Histogram(
    "astra_redis_operation_duration_seconds",
    "Duration of Redis operations",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

_REDIS_HEALTH = Gauge(
    "astra_redis_health",
    "Redis health status (1=healthy, 0=unhealthy)",
)

_REDIS_RECONNECTS = Counter(
    "astra_redis_reconnects_total",
    "Total Redis reconnection attempts",
)


# ── Data Classes ─────────────────────────────────────────────────────────────

class RetryPolicy(str, Enum):
    EXPONENTIAL = "exponential"
    CONSTANT = "constant"
    LINEAR = "linear"


@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 0.5  # seconds
    max_delay: float = 30.0
    policy: RetryPolicy = RetryPolicy.EXPONENTIAL
    jitter: bool = True


@dataclass
class QueuedOperation:
    """Represents a queued Redis operation for retry."""
    operation: str
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    priority: int = 0  # Higher = more urgent
    created_at: float = field(default_factory=time.monotonic)
    retry_count: int = 0
    correlation_id: Optional[str] = None


@dataclass
class DeadLetterEntry:
    """Entry in the dead-letter queue."""
    operation: str
    args: tuple
    kwargs: dict
    error: str
    retry_count: int
    failed_at: float
    correlation_id: Optional[str] = None


# ── Reliable Redis Client ────────────────────────────────────────────────────

class ReliableRedisClient:
    """
    Redis client with reliability features.

    Features:
    - Automatic retry with exponential backoff
    - Operation queue with priority support
    - Circuit breaker integration
    - Dead-letter queue for permanently failed operations
    - Health monitoring with automatic reconnection
    - Backpressure via queue depth limits
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        password: Optional[str] = None,
        db: Optional[int] = None,
        max_connections: Optional[int] = None,
        retry_config: Optional[RetryConfig] = None,
        queue_maxsize: int = 10000,
        dlq_maxsize: int = 1000,
        health_check_interval: float = 30.0,
    ) -> None:
        settings = get_settings()

        self._host = host or settings.redis.host
        self._port = port or settings.redis.port
        self._password = password or settings.redis.password
        self._db = db or settings.redis.db
        self._max_connections = max_connections or settings.redis.max_connections

        self._retry_config = retry_config or RetryConfig()
        self._queue_maxsize = queue_maxsize
        self._dlq_maxsize = dlq_maxsize
        self._health_check_interval = health_check_interval

        # Redis connection
        self._pool: Optional[redis.ConnectionPool] = None
        self._client: Optional[redis.Redis] = None

        # Internal state
        self._running = False
        self._retry_queue: asyncio.PriorityQueue[QueuedOperation] = asyncio.PriorityQueue(maxsize=queue_maxsize)
        self._dlq: deque[DeadLetterEntry] = deque(maxlen=dlq_maxsize)
        self._health_check_task: Optional[asyncio.Task] = None
        self._retry_worker_task: Optional[asyncio.Task] = None
        self._circuit_breaker = create_redis_circuit_breaker()

        # Backpressure state
        self._backpressure_active = False
        self._high_watermark = queue_maxsize * 0.8
        self._low_watermark = queue_maxsize * 0.4

        log.info(
            "ReliableRedisClient initialized: host=%s, port=%d, queue_maxsize=%d, dlq_maxsize=%d",
            self._host, self._port, queue_maxsize, dlq_maxsize,
        )

    async def start(self) -> None:
        """Initialize connection pool and start background tasks."""
        if self._running:
            return

        self._pool = redis.ConnectionPool(
            host=self._host,
            port=self._port,
            password=self._password,
            db=self._db,
            max_connections=self._max_connections,
            decode_responses=True,
            socket_keepalive=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        self._client = redis.Redis(connection_pool=self._pool)

        self._running = True
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        self._retry_worker_task = asyncio.create_task(self._retry_worker_loop())

        # Test connection
        try:
            await self._client.ping()
            _REDIS_HEALTH.set(1)
            log.info("ReliableRedisClient connected to Redis at %s:%d", self._host, self._port)
        except Exception as e:
            _REDIS_HEALTH.set(0)
            log.error("Failed to connect to Redis: %s", e)
            raise

    async def shutdown(self) -> None:
        """Gracefully shutdown: drain queues, close connections."""
        if not self._running:
            return

        self._running = False
        log.info("Shutting down ReliableRedisClient...")

        # Stop background tasks
        for task in [self._health_check_task, self._retry_worker_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Drain retry queue to DLQ
        drained = 0
        while not self._retry_queue.empty():
            try:
                op = self._retry_queue.get_nowait()
                self._move_to_dlq(op, "Shutdown: operation requeued to DLQ")
                drained += 1
            except asyncio.QueueEmpty:
                break
        if drained:
            log.warning("Drained %d operations to DLQ during shutdown", drained)

        # Close Redis connections
        if self._client:
            await self._client.close()
        if self._pool:
            await self._pool.disconnect()

        _REDIS_HEALTH.set(0)
        log.info("ReliableRedisClient shutdown complete (DLQ size: %d)", len(self._dlq))

    # ── Public API ──────────────────────────────────────────────────────────

    async def add_kpi_history(self, cell_id: str, kpi: dict) -> bool:
        """Add KPI to history stream (fire-and-forget with retry)."""
        return await self._enqueue_operation(
            "add_kpi_history",
            cell_id, kpi,
            priority=1,  # High priority for real-time data
        )

    async def add_anomaly(self, cell_id: str, anomaly: dict) -> bool:
        """Add anomaly to list (fire-and-forget with retry)."""
        return await self._enqueue_operation(
            "add_anomaly",
            cell_id, anomaly,
            priority=2,  # Highest priority for anomalies
        )

    async def add_healing_action(self, cell_id: str, action: dict) -> bool:
        """Add healing action to log (fire-and-forget with retry)."""
        return await self._enqueue_operation(
            "add_healing_action",
            cell_id, action,
            priority=2,
        )

    async def set_latest_attribution(self, cell_id: str, attribution: dict) -> bool:
        """Set latest attribution (fire-and-forget with retry)."""
        return await self._enqueue_operation(
            "set_latest_attribution",
            cell_id, attribution,
            priority=1,
        )

    async def get_kpi_history(self, cell_id: str, limit: int = 3600) -> list[dict]:
        """Get KPI history (synchronous read - no queue)."""
        return await self._execute_with_retry(
            "get_kpi_history",
            self._get_kpi_history_impl,
            cell_id, limit,
        )

    async def get_anomalies(self, cell_id: str, limit: int = 100) -> list[dict]:
        """Get anomalies (synchronous read)."""
        return await self._execute_with_retry(
            "get_anomalies",
            self._get_anomalies_impl,
            cell_id, limit,
        )

    async def get_healing_actions(self, cell_id: str, limit: int = 100) -> list[dict]:
        """Get healing actions (synchronous read)."""
        return await self._execute_with_retry(
            "get_healing_actions",
            self._get_healing_actions_impl,
            cell_id, limit,
        )

    async def get_latest_attribution(self, cell_id: str) -> dict:
        """Get latest attribution (synchronous read)."""
        return await self._execute_with_retry(
            "get_latest_attribution",
            self._get_latest_attribution_impl,
            cell_id,
        )

    async def health_check(self) -> bool:
        """Check Redis connectivity."""
        try:
            if self._client:
                await asyncio.wait_for(self._client.ping(), timeout=2.0)
                _REDIS_HEALTH.set(1)
                return True
        except Exception:
            _REDIS_HEALTH.set(0)
        return False

    def get_stats(self) -> dict[str, Any]:
        """Get client statistics."""
        return {
            "running": self._running,
            "connected": self._client is not None,
            "retry_queue_depth": self._retry_queue.qsize(),
            "dlq_size": len(self._dlq),
            "backpressure_active": self._backpressure_active,
            "high_watermark": self._high_watermark,
            "circuit_breaker": self._circuit_breaker.stats(),
        }

    def get_dlq_entries(self, limit: int = 100) -> list[dict]:
        """Get dead-letter queue entries for inspection."""
        return [
            {
                "operation": e.operation,
                "error": e.error,
                "retry_count": e.retry_count,
                "failed_at": e.failed_at,
                "correlation_id": e.correlation_id,
                "args": e.args,
                "kwargs": e.kwargs,
            }
            for e in list(self._dlq)[-limit:]
        ]

    def retry_dlq_entry(self, index: int) -> bool:
        """Retry a specific DLQ entry."""
        if 0 <= index < len(self._dlq):
            entry = self._dlq[index]
            op = QueuedOperation(
                operation=entry.operation,
                args=entry.args,
                kwargs=entry.kwargs,
                retry_count=0,
                correlation_id=entry.correlation_id,
            )
            try:
                self._retry_queue.put_nowait(op)
                self._dlq.remove(entry)
                return True
            except asyncio.QueueFull:
                return False
        return False

    # ── Internal Implementation ──────────────────────────────────────────────

    async def _enqueue_operation(
        self,
        operation: str,
        *args: Any,
        priority: int = 0,
        **kwargs: Any,
    ) -> bool:
        """Enqueue an operation for async execution with retry."""
        if not self._running:
            log.warning("Cannot enqueue operation '%s': client not running", operation)
            return False

        # Check backpressure
        queue_size = self._retry_queue.qsize()
        if queue_size >= self._high_watermark and not self._backpressure_active:
            self._backpressure_active = True
            log.warning("Redis backpressure activated: queue depth %d >= %d", queue_size, self._high_watermark)
        elif queue_size <= self._low_watermark and self._backpressure_active:
            self._backpressure_active = False
            log.info("Redis backpressure released: queue depth %d <= %d", queue_size, self._low_watermark)

        if self._backpressure_active and priority < 2:
            # Drop low-priority operations under backpressure
            _REDIS_OPS_TOTAL.labels(operation=operation, outcome="dropped_backpressure").inc()
            log.debug("Dropped operation '%s' due to backpressure", operation)
            return False

        try:
            from xapp.observability import get_correlation_id
            corr_id = get_correlation_id()
        except Exception:
            corr_id = None

        op = QueuedOperation(
            operation=operation,
            args=args,
            kwargs=kwargs,
            priority=-priority,  # Negative for priority queue (lower = higher priority)
            correlation_id=corr_id,
        )

        try:
            await asyncio.wait_for(self._retry_queue.put(op), timeout=1.0)
            _REDIS_QUEUE_DEPTH.labels(queue_name="retry").set(self._retry_queue.qsize())
            return True
        except asyncio.TimeoutError:
            _REDIS_OPS_TOTAL.labels(operation=operation, outcome="queue_timeout").inc()
            log.warning("Queue full, operation '%s' timed out", operation)
            return False

    async def _retry_worker_loop(self) -> None:
        """Background worker that processes the retry queue."""
        while self._running:
            try:
                op = await asyncio.wait_for(self._retry_queue.get(), timeout=1.0)
                await self._process_operation(op)
                self._retry_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Retry worker error: %s", e)

    async def _process_operation(self, op: QueuedOperation) -> None:
        """Process a single operation with retry logic."""
        try:
            await self._execute_with_retry(op.operation, self._execute_operation, op)
        except Exception as e:
            # Operation permanently failed - move to DLQ
            self._move_to_dlq(op, str(e))

    async def _execute_operation(self, op: QueuedOperation) -> None:
        """Execute the actual Redis operation."""
        if not self._client:
            raise RuntimeError("Redis client not initialized")

        if op.operation == "add_kpi_history":
            cell_id, kpi = op.args[0], op.args[1]
            key = f"astra:{cell_id}:kpi_history"
            await self._client.xadd(key, {"data": json.dumps(kpi)}, maxlen=3600)

        elif op.operation == "add_anomaly":
            cell_id, anomaly = op.args[0], op.args[1]
            key = f"astra:{cell_id}:anomalies"
            await self._client.lpush(key, json.dumps(anomaly))
            await self._client.ltrim(key, 0, 999)

        elif op.operation == "add_healing_action":
            cell_id, action = op.args[0], op.args[1]
            key = f"astra:{cell_id}:healing_log"
            await self._client.lpush(key, json.dumps(action))
            await self._client.ltrim(key, 0, 999)

        elif op.operation == "set_latest_attribution":
            cell_id, attribution = op.args[0], op.args[1]
            key = f"astra:{cell_id}:attribution"
            await self._client.set(key, json.dumps(attribution))

        else:
            raise ValueError(f"Unknown operation: {op.operation}")

    async def _execute_with_retry(
        self,
        operation: str,
        func: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute function with retry logic and circuit breaker."""
        last_exception = None

        for attempt in range(self._retry_config.max_retries + 1):
            try:
                start = time.monotonic()
                result = await self._circuit_breaker.call(
                    func,
                    *args,
                    **kwargs,
                    fallback=None,
                )
                duration = time.monotonic() - start
                _REDIS_OP_DURATION.labels(operation=operation).observe(duration)
                _REDIS_OPS_TOTAL.labels(operation=operation, outcome="success").inc()
                return result

            except Exception as e:
                last_exception = e
                _REDIS_OPS_TOTAL.labels(operation=operation, outcome="retry").inc()

                if attempt < self._retry_config.max_retries:
                    delay = self._calculate_delay(attempt)
                    log.warning(
                        "Redis operation '%s' failed (attempt %d/%d): %s. Retrying in %.2fs",
                        operation, attempt + 1, self._retry_config.max_retries + 1, e, delay,
                    )
                    await asyncio.sleep(delay)

                    # Try to reconnect if connection error
                    if isinstance(e, (redis.ConnectionError, redis.TimeoutError)):
                        await self._attempt_reconnect()
                else:
                    _REDIS_OPS_TOTAL.labels(operation=operation, outcome="failed").inc()
                    log.error(
                        "Redis operation '%s' failed after %d attempts: %s",
                        operation, self._retry_config.max_retries + 1, e,
                    )

        raise last_exception

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay based on retry policy."""
        config = self._retry_config
        if config.policy == RetryPolicy.EXPONENTIAL:
            delay = config.base_delay * (2 ** attempt)
        elif config.policy == RetryPolicy.LINEAR:
            delay = config.base_delay * (attempt + 1)
        else:  # CONSTANT
            delay = config.base_delay

        delay = min(delay, config.max_delay)

        if config.jitter:
            import random
            delay *= (0.5 + random.random())  # 0.5x to 1.5x

        return delay

    async def _attempt_reconnect(self) -> None:
        """Attempt to reconnect to Redis."""
        log.info("Attempting Redis reconnection...")
        _REDIS_RECONNECTS.inc()

        try:
            if self._client:
                await self._client.close()
            if self._pool:
                await self._pool.disconnect()

            await self.start()
            log.info("Redis reconnection successful")
        except Exception as e:
            log.error("Redis reconnection failed: %s", e)

    async def _health_check_loop(self) -> None:
        """Periodic health check with automatic reconnection."""
        while self._running:
            try:
                await asyncio.sleep(self._health_check_interval)
                if not await self.health_check():
                    log.warning("Health check failed, attempting reconnection...")
                    await self._attempt_reconnect()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Health check error: %s", e)

    # ── DLQ Management ──────────────────────────────────────────────────────

    def _move_to_dlq(self, op: QueuedOperation, error: str) -> None:
        """Move failed operation to dead-letter queue."""
        entry = DeadLetterEntry(
            operation=op.operation,
            args=op.args,
            kwargs=op.kwargs,
            error=error,
            retry_count=op.retry_count,
            failed_at=time.monotonic(),
            correlation_id=op.correlation_id,
        )
        self._dlq.append(entry)
        _REDIS_DLQ_SIZE.set(len(self._dlq))
        _REDIS_OPS_TOTAL.labels(operation=op.operation, outcome="dlq").inc()
        log.error(
            "Operation '%s' moved to DLQ after %d retries: %s",
            op.operation, op.retry_count, error,
        )

    # ── Read Implementations ────────────────────────────────────────────────

    async def _get_kpi_history_impl(self, cell_id: str, limit: int) -> list[dict]:
        key = f"astra:{cell_id}:kpi_history"
        messages = await self._client.xrevrange(key, max='+', min='-', count=limit)
        return [json.loads(m[1]["data"]) for m in reversed(messages)]

    async def _get_anomalies_impl(self, cell_id: str, limit: int) -> list[dict]:
        key = f"astra:{cell_id}:anomalies"
        items = await self._client.lrange(key, 0, limit - 1)
        return [json.loads(i) for i in items]

    async def _get_healing_actions_impl(self, cell_id: str, limit: int) -> list[dict]:
        key = f"astra:{cell_id}:healing_log"
        items = await self._client.lrange(key, 0, limit - 1)
        return [json.loads(i) for i in items]

    async def _get_latest_attribution_impl(self, cell_id: str) -> dict:
        key = f"astra:{cell_id}:attribution"
        val = await self._client.get(key)
        return json.loads(val) if val else {}


# ── Global Instance ──────────────────────────────────────────────────────────

_reliable_redis_client: Optional[ReliableRedisClient] = None


async def get_reliable_redis_client() -> ReliableRedisClient:
    """Get or create the global reliable Redis client."""
    global _reliable_redis_client
    if _reliable_redis_client is None:
        _reliable_redis_client = ReliableRedisClient()
        await _reliable_redis_client.start()
    return _reliable_redis_client


async def shutdown_reliable_redis_client() -> None:
    """Shutdown the global reliable Redis client."""
    global _reliable_redis_client
    if _reliable_redis_client:
        await _reliable_redis_client.shutdown()
        _reliable_redis_client = None