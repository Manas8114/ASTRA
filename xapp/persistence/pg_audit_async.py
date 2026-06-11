"""
xapp/persistence/pg_audit_async.py
──────────────────────────────────────────────────────────────────────────────
Async PostgreSQL Audit Trail for ASTRA xApp.

Features:
- Async batch writer (buffer + periodic flush)
- Alembic migration support
- Read APIs with filtering
- Connection pooling with health checks
- Metrics for observability

Usage:
    from xapp.persistence.pg_audit_async import AsyncPGAuditTrail

    audit = AsyncPGAuditTrail()
    await audit.start()
    await audit.append_event(cell_id, event_type, payload)
    # ... or use batch:
    await audit.append_batch([(cell_id, event_type, payload), ...])
    await audit.shutdown()
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg
from prometheus_client import Counter, Gauge, Histogram

from xapp.config import get_settings

log = logging.getLogger("astra.pg_audit_async")

# ── Prometheus Metrics ───────────────────────────────────────────────────────

_PG_OPS_TOTAL = Counter(
    "astra_pg_audit_operations_total",
    "Total PostgreSQL audit operations",
    ["operation", "outcome"],  # outcome: success, failed, batch_flushed
)

_PG_BATCH_SIZE = Histogram(
    "astra_pg_audit_batch_size",
    "Size of batches flushed to PostgreSQL",
    buckets=(1, 5, 10, 25, 50, 100, 200, 500, 1000),
)

_PG_FLUSH_DURATION = Histogram(
    "astra_pg_audit_flush_duration_seconds",
    "Duration of batch flush operations",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

_PG_QUEUE_DEPTH = Gauge(
    "astra_pg_audit_queue_depth",
    "Current depth of pending writes queue",
)

_PG_POOL_SIZE = Gauge(
    "astra_pg_pool_size",
    "Current PostgreSQL connection pool size",
)

_PG_HEALTH = Gauge(
    "astra_pg_health",
    "PostgreSQL health status (1=healthy, 0=unhealthy)",
)


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class AuditEvent:
    """Represents an audit event to be written."""
    cell_id: str
    event_type: str
    payload: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: Optional[str] = None


@dataclass
class QueryFilter:
    """Filters for querying audit events."""
    cell_id: Optional[str] = None
    event_type: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    correlation_id: Optional[str] = None
    limit: int = 100
    offset: int = 0


# ── Async PG Audit Trail ────────────────────────────────────────────────────

class AsyncPGAuditTrail:
    """
    Async PostgreSQL audit trail with batch writing.

    Features:
    - Buffered writes with configurable batch size and flush interval
    - Automatic table creation (or use Alembic migrations)
    - Connection pooling with health checks
    - Query API with filtering
    - Metrics for monitoring
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        pool_size: int = 10,
        max_pool_size: int = 20,
        batch_size: int = 100,
        flush_interval: float = 5.0,
        health_check_interval: float = 30.0,
        create_tables: bool = True,
    ) -> None:
        settings = get_settings()

        raw_dsn = dsn or settings.database.url

        # Detect if using SQLite (dev fallback)
        self._use_sqlite = raw_dsn.startswith("sqlite://")
        if self._use_sqlite:
            # Extract path from sqlite:///./data/astra_audit.db
            self._sqlite_path = raw_dsn.replace("sqlite:///", "").replace("sqlite://", "")
            self._dsn = None
            log.info("Using SQLite backend: %s", self._sqlite_path)
        else:
            self._dsn = raw_dsn
            # Ensure postgresql+asyncpg for asyncpg
            if self._dsn.startswith("postgresql://"):
                self._dsn = self._dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif self._dsn.startswith("postgres://"):
                self._dsn = self._dsn.replace("postgres://", "postgresql+asyncpg://", 1)
            self._sqlite_path = None
            log.info("Using PostgreSQL backend")

        self._pool_size = pool_size
        self._max_pool_size = max_pool_size
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._health_check_interval = health_check_interval
        self._create_tables = create_tables

        # State
        self._pool: Optional[asyncpg.Pool] = None
        self._sqlite_conn = None
        self._running = False
        self._write_queue: asyncio.Queue[AuditEvent] = asyncio.Queue()
        self._flush_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None
        self._pending_count = 0

        log.info(
            "AsyncPGAuditTrail initialized: backend=%s, pool_size=%d, batch_size=%d, flush_interval=%.1fs",
            "sqlite" if self._use_sqlite else "postgresql", pool_size, batch_size, flush_interval,
        )

    async def start(self) -> None:
        """Initialize connection pool and start background tasks."""
        if self._running:
            return

        if self._use_sqlite:
            await self._start_sqlite()
        else:
            await self._start_postgres()

        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        self._health_check_task = asyncio.create_task(self._health_check_loop())

        log.info("AsyncPGAuditTrail started")

    async def _start_postgres(self) -> None:
        """Initialize PostgreSQL connection pool."""
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._pool_size,
            max_size=self._max_pool_size,
            command_timeout=30,
            server_settings={
                "application_name": "astra-audit-trail",
            },
        )

        if self._create_tables:
            await self._create_tables_postgres()

        _PG_POOL_SIZE.set(self._pool.get_size())
        _PG_HEALTH.set(1)
        log.info("PostgreSQL connection pool created")

    async def _start_sqlite(self) -> None:
        """Initialize SQLite connection (fallback for dev)."""
        import aiosqlite

        self._sqlite_conn = await aiosqlite.connect(self._sqlite_path)
        self._sqlite_conn.row_factory = aiosqlite.Row

        if self._create_tables:
            await self._create_tables_sqlite()

        _PG_HEALTH.set(1)
        log.info("SQLite connection created (dev mode)")

    async def _create_tables_postgres(self) -> None:
        """Create audit tables in PostgreSQL."""
        async with self._pool.acquire() as conn:
            # Main audit table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS astra_event_audit (
                    id BIGSERIAL PRIMARY KEY,
                    cell_id VARCHAR(128) NOT NULL,
                    event_type VARCHAR(64) NOT NULL,
                    payload JSONB NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    correlation_id VARCHAR(64),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            # Indexes for common queries
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_astra_audit_cell_id
                ON astra_event_audit (cell_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_astra_audit_event_type
                ON astra_event_audit (event_type)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_astra_audit_timestamp
                ON astra_event_audit (timestamp DESC)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_astra_audit_correlation_id
                ON astra_event_audit (correlation_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_astra_audit_cell_type_time
                ON astra_event_audit (cell_id, event_type, timestamp DESC)
            """)

            log.info("PostgreSQL audit tables created/verified")

    async def _create_tables_sqlite(self) -> None:
        """Create audit tables in SQLite."""
        await self._sqlite_conn.executescript("""
            CREATE TABLE IF NOT EXISTS astra_event_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cell_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                correlation_id TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_astra_audit_cell_id
            ON astra_event_audit (cell_id);

            CREATE INDEX IF NOT EXISTS idx_astra_audit_event_type
            ON astra_event_audit (event_type);

            CREATE INDEX IF NOT EXISTS idx_astra_audit_timestamp
            ON astra_event_audit (timestamp DESC);

            CREATE INDEX IF NOT EXISTS idx_astra_audit_correlation_id
            ON astra_event_audit (correlation_id);

            CREATE INDEX IF NOT EXISTS idx_astra_audit_cell_type_time
            ON astra_event_audit (cell_id, event_type, timestamp DESC);
        """)
        await self._sqlite_conn.commit()
        log.info("SQLite audit tables created/verified")

    async def shutdown(self) -> None:
        """Graceful shutdown: flush pending writes, close connections."""
        if not self._running:
            return

        self._running = False
        log.info("Shutting down AsyncPGAuditTrail...")

        # Cancel background tasks
        for task in [self._flush_task, self._health_check_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Final flush
        await self._flush_batch()

        # Close connections
        if self._pool:
            await self._pool.close()
        if self._sqlite_conn:
            await self._sqlite_conn.close()

        _PG_HEALTH.set(0)
        log.info("AsyncPGAuditTrail shutdown complete (pending: %d)", self._pending_count)

    # ── Write API ──────────────────────────────────────────────────────────

    async def append_event(
        self,
        cell_id: str,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> None:
        """Append a single event to the audit trail (queued for batch write)."""
        if not self._running:
            log.warning("Audit trail not running, dropping event: %s", event_type)
            return

        event = AuditEvent(
            cell_id=cell_id,
            event_type=event_type,
            payload=payload,
            correlation_id=correlation_id,
        )

        try:
            await asyncio.wait_for(self._write_queue.put(event), timeout=1.0)
            self._pending_count += 1
            _PG_QUEUE_DEPTH.set(self._write_queue.qsize())
        except asyncio.TimeoutError:
            log.error("Write queue full, dropping event: %s", event_type)

    async def append_batch(self, events: list[tuple[str, str, dict, Optional[str]]]) -> None:
        """Append multiple events at once."""
        for cell_id, event_type, payload, correlation_id in events:
            await self.append_event(cell_id, event_type, payload, correlation_id)

    # ── Read API ──────────────────────────────────────────────────────────

    async def query_events(self, filter: QueryFilter) -> list[dict[str, Any]]:
        """Query audit events with filters."""
        if not self._running:
            return []

        if self._use_sqlite:
            return await self._query_events_sqlite(filter)
        else:
            return await self._query_events_postgres(filter)

    async def _query_events_postgres(self, filter: QueryFilter) -> list[dict[str, Any]]:
        conditions = ["1=1"]
        params = []
        param_idx = 1

        if filter.cell_id:
            conditions.append(f"cell_id = ${param_idx}")
            params.append(filter.cell_id)
            param_idx += 1

        if filter.event_type:
            conditions.append(f"event_type = ${param_idx}")
            params.append(filter.event_type)
            param_idx += 1

        if filter.start_time:
            conditions.append(f"timestamp >= ${param_idx}")
            params.append(filter.start_time)
            param_idx += 1

        if filter.end_time:
            conditions.append(f"timestamp <= ${param_idx}")
            params.append(filter.end_time)
            param_idx += 1

        if filter.correlation_id:
            conditions.append(f"correlation_id = ${param_idx}")
            params.append(filter.correlation_id)
            param_idx += 1

        # Add limit and offset
        params.append(filter.limit)
        params.append(filter.offset)
        limit_idx = param_idx
        offset_idx = param_idx + 1

        query = f"""
            SELECT id, cell_id, event_type, payload, timestamp, correlation_id, created_at
            FROM astra_event_audit
            WHERE {" AND ".join(conditions)}
            ORDER BY timestamp DESC
            LIMIT ${limit_idx} OFFSET ${offset_idx}
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    async def _query_events_sqlite(self, filter: QueryFilter) -> list[dict[str, Any]]:
        import aiosqlite

        conditions = ["1=1"]
        params = []

        if filter.cell_id:
            conditions.append("cell_id = ?")
            params.append(filter.cell_id)

        if filter.event_type:
            conditions.append("event_type = ?")
            params.append(filter.event_type)

        if filter.start_time:
            conditions.append("timestamp >= ?")
            params.append(filter.start_time.isoformat())

        if filter.end_time:
            conditions.append("timestamp <= ?")
            params.append(filter.end_time.isoformat())

        if filter.correlation_id:
            conditions.append("correlation_id = ?")
            params.append(filter.correlation_id)

        params.extend([filter.limit, filter.offset])

        query = f"""
            SELECT id, cell_id, event_type, payload, timestamp, correlation_id, created_at
            FROM astra_event_audit
            WHERE {" AND ".join(conditions)}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """

        cursor = await self._sqlite_conn.execute(query, params)
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            row_dict = dict(row)
            # Parse JSON payload for SQLite
            if isinstance(row_dict.get("payload"), str):
                import json
                row_dict["payload"] = json.loads(row_dict["payload"])
            results.append(row_dict)
        return results

    async def get_event_counts(self, cell_id: Optional[str] = None) -> dict[str, int]:
        """Get event counts by type."""
        if self._use_sqlite:
            return await self._get_event_counts_sqlite(cell_id)
        else:
            return await self._get_event_counts_postgres(cell_id)

    async def _get_event_counts_postgres(self, cell_id: Optional[str] = None) -> dict[str, int]:
        query = """
            SELECT event_type, COUNT(*) as count
            FROM astra_event_audit
        """
        params = []
        if cell_id:
            query += " WHERE cell_id = $1"
            params.append(cell_id)
        query += " GROUP BY event_type"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return {row["event_type"]: row["count"] for row in rows}

    async def _get_event_counts_sqlite(self, cell_id: Optional[str] = None) -> dict[str, int]:
        query = "SELECT event_type, COUNT(*) as count FROM astra_event_audit"
        params = []
        if cell_id:
            query += " WHERE cell_id = ?"
            params.append(cell_id)
        query += " GROUP BY event_type"

        cursor = await self._sqlite_conn.execute(query, params)
        rows = await cursor.fetchall()
        return {row["event_type"]: row["count"] for row in rows}

    async def get_latest_events(self, cell_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get latest events for a cell."""
        filter = QueryFilter(cell_id=cell_id, limit=limit)
        return await self.query_events(filter)

    # ── Background Tasks ──────────────────────────────────────────────────

    async def _flush_loop(self) -> None:
        """Periodically flush the write queue to database."""
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)
                await self._flush_batch()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Flush loop error: %s", e)

    async def _flush_batch(self) -> bool:
        """Flush pending events to database."""
        events = []

        # Collect up to batch_size events
        while len(events) < self._batch_size:
            try:
                event = self._write_queue.get_nowait()
                events.append(event)
                self._write_queue.task_done()
            except asyncio.QueueEmpty:
                break

        if not events:
            return False

        start = time.monotonic()
        try:
            if self._use_sqlite:
                await self._flush_batch_sqlite(events)
            else:
                await self._flush_batch_postgres(events)

            duration = time.monotonic() - start
            _PG_BATCH_SIZE.observe(len(events))
            _PG_FLUSH_DURATION.observe(duration)
            _PG_OPS_TOTAL.labels(operation="flush", outcome="success").inc()
            self._pending_count -= len(events)
            _PG_QUEUE_DEPTH.set(self._write_queue.qsize())

            log.debug("Flushed %d audit events in %.3fs", len(events), duration)
            return True

        except Exception as e:
            _PG_OPS_TOTAL.labels(operation="flush", outcome="failed").inc()
            log.error("Failed to flush batch of %d events: %s", len(events), e)
            # Re-queue events for retry
            for event in reversed(events):
                try:
                    self._write_queue.put_nowait(event)
                except asyncio.QueueFull:
                    log.error("Re-queue failed, queue full: %s", event.event_type)
            return False

    async def _flush_batch_postgres(self, events: list[AuditEvent]) -> None:
        """Batch insert events into PostgreSQL."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for event in events:
                    await conn.execute(
                        """
                        INSERT INTO astra_event_audit (cell_id, event_type, payload, timestamp, correlation_id)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        event.cell_id,
                        event.event_type,
                        json.dumps(event.payload),
                        event.timestamp,
                        event.correlation_id,
                    )

    async def _flush_batch_sqlite(self, events: list[AuditEvent]) -> None:
        """Batch insert events into SQLite."""
        await self._sqlite_conn.execute("BEGIN")
        try:
            for event in events:
                await self._sqlite_conn.execute(
                    """
                    INSERT INTO astra_event_audit (cell_id, event_type, payload, timestamp, correlation_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        event.cell_id,
                        event.event_type,
                        json.dumps(event.payload),
                        event.timestamp.isoformat(),
                        event.correlation_id,
                    ),
                )
            await self._sqlite_conn.execute("COMMIT")
        except Exception:
            await self._sqlite_conn.execute("ROLLBACK")
            raise

    async def _health_check_loop(self) -> None:
        """Periodic health check."""
        while self._running:
            try:
                await asyncio.sleep(self._health_check_interval)
                healthy = await self.health_check()
                if not healthy:
                    log.warning("Database health check failed")
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Health check error: %s", e)

    async def health_check(self) -> bool:
        """Check database connectivity."""
        try:
            if self._use_sqlite:
                await self._sqlite_conn.execute("SELECT 1")
            else:
                async with self._pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
            _PG_HEALTH.set(1)
            if not self._use_sqlite:
                _PG_POOL_SIZE.set(self._pool.get_size())
            return True
        except Exception:
            _PG_HEALTH.set(0)
            return False

    def get_stats(self) -> dict[str, Any]:
        """Get audit trail statistics."""
        return {
            "running": self._running,
            "backend": "sqlite" if self._use_sqlite else "postgresql",
            "pending_writes": self._write_queue.qsize(),
            "batch_size": self._batch_size,
            "flush_interval": self._flush_interval,
            "pool_size": self._pool.get_size() if self._pool else None,
        }


# ── Global Instance ──────────────────────────────────────────────────────────

_async_pg_audit: Optional[AsyncPGAuditTrail] = None


async def get_async_pg_audit() -> AsyncPGAuditTrail:
    """Get or create the global async PG audit trail."""
    global _async_pg_audit
    if _async_pg_audit is None:
        _async_pg_audit = AsyncPGAuditTrail()
        await _async_pg_audit.start()
    return _async_pg_audit


async def shutdown_async_pg_audit() -> None:
    """Shutdown the global async PG audit trail."""
    global _async_pg_audit
    if _async_pg_audit:
        await _async_pg_audit.shutdown()
        _async_pg_audit = None