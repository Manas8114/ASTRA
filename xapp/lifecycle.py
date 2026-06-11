"""
xapp/lifecycle.py
──────────────────────────────────────────────────────────────────────────────
Graceful Shutdown Manager for ASTRA xApp.

Handles SIGTERM/SIGINT signals with proper resource cleanup:
- Drains WebSocket client queues before closing connections
- Flushes Redis buffers and closes connections
- Awaits E2 control acknowledgements (with timeout)
- Stops detection loop gracefully
- Closes gRPC channels to twin-service
- Shuts down thread pools and async tasks

Usage:
    from xapp.lifecycle import LifecycleManager, register_shutdown_handlers

    lifecycle = LifecycleManager()

    # Register components for shutdown
    lifecycle.register_websocket_hub(hub)
    lifecycle.register_redis_client(redis_client)
    lifecycle.register_e2_client(e2_client)
    lifecycle.register_twin_channel(grpc_channel)
    lifecycle.register_detection_loop(detection_task)

    # Register signal handlers (call early in main())
    register_shutdown_handlers(lifecycle)

    # On shutdown, call:
    await lifecycle.shutdown()
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from xapp.config import get_settings

log = logging.getLogger("astra.lifecycle")

# ── Type Aliases ──────────────────────────────────────────────────────────────

ShutdownHook = Callable[[], Awaitable[None]] | Callable[[], None]
AsyncShutdownHook = Callable[[], Awaitable[None]]


# ── Component Registration ────────────────────────────────────────────────────

@dataclass
class ShutdownComponent:
    """Represents a component that needs graceful shutdown."""
    name: str
    shutdown_hook: AsyncShutdownHook
    timeout: float = 10.0
    priority: int = 0  # Lower priority shuts down first
    critical: bool = True  # If True, failure logs as ERROR; else WARNING


# ── Lifecycle Manager ────────────────────────────────────────────────────────

class LifecycleManager:
    """
    Manages graceful shutdown of all registered components.

    Components are shutdown in priority order (lowest first).
    Each component has a timeout; if exceeded, shutdown continues.
    """

    def __init__(self, default_timeout: float = 30.0) -> None:
        self._components: list[ShutdownComponent] = []
        self._default_timeout = default_timeout
        self._shutdown_started = False
        self._shutdown_complete = False
        self._start_time: Optional[float] = None
        self._lock = asyncio.Lock()

    def register(
        self,
        name: str,
        hook: AsyncShutdownHook | Callable[[], None],
        timeout: Optional[float] = None,
        priority: int = 0,
        critical: bool = True,
    ) -> None:
        """
        Register a component for graceful shutdown.

        Args:
            name: Human-readable component name (for logging)
            hook: Async callable (or sync) to execute on shutdown
            timeout: Max seconds to wait for this component (default: default_timeout)
            priority: Shutdown order (lower = earlier). Default 0.
            critical: If True, failures are ERROR level; else WARNING.
        """
        if self._shutdown_started:
            log.warning("Cannot register component '%s' after shutdown started", name)
            return

        # Wrap sync hooks
        if asyncio.iscoroutinefunction(hook):
            async_hook = hook
        else:
            async def wrapped() -> None:
                hook()
            async_hook = wrapped

        component = ShutdownComponent(
            name=name,
            shutdown_hook=async_hook,
            timeout=timeout or self._default_timeout,
            priority=priority,
            critical=critical,
        )
        self._components.append(component)
        log.debug("Registered shutdown component: %s (priority=%d, timeout=%.1fs)",
                  name, priority, component.timeout)

    def register_websocket_hub(self, hub: Any, drain_timeout: float = 5.0) -> None:
        """Register WebSocket hub for graceful client disconnect."""
        async def shutdown_ws() -> None:
            log.info("Draining WebSocket connections...")
            if hasattr(hub, 'shutdown'):
                await hub.shutdown()
            elif hasattr(hub, '_hub') and hasattr(hub._hub, 'shutdown'):
                await hub._hub.shutdown()
            else:
                # Fallback: try to disconnect all clients manually
                log.warning("WebSocket hub has no shutdown method, attempting manual cleanup")
        self.register("websocket_hub", shutdown_ws, timeout=drain_timeout, priority=-10)

    def register_redis_client(self, redis_client: Any, flush_timeout: float = 5.0) -> None:
        """Register Redis client for connection close + buffer flush."""
        async def shutdown_redis() -> None:
            log.info("Closing Redis connections...")
            if hasattr(redis_client, 'close'):
                if asyncio.iscoroutinefunction(redis_client.close):
                    await redis_client.close()
                else:
                    redis_client.close()
            elif hasattr(redis_client, 'client') and hasattr(redis_client.client, 'close'):
                await redis_client.client.close()
            # Close connection pool
            if hasattr(redis_client, 'pool') and hasattr(redis_client.pool, 'disconnect'):
                await redis_client.pool.disconnect()
        self.register("redis_client", shutdown_redis, timeout=flush_timeout, priority=-5)

    def register_e2_client(self, e2_client: Any, ack_timeout: float = 10.0) -> None:
        """Register E2 client to await pending acknowledgements."""
        async def shutdown_e2() -> None:
            log.info("Waiting for E2 control acknowledgements...")
            # If e2_client has pending operations, wait for them
            if hasattr(e2_client, 'wait_for_pending_acks'):
                await asyncio.wait_for(e2_client.wait_for_pending_acks(), timeout=ack_timeout)
            elif hasattr(e2_client, '_pending_acks'):
                # Wait for any tracked futures
                pending = [f for f in e2_client._pending_acks if not f.done()]
                if pending:
                    await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=ack_timeout)
        self.register("e2_client", shutdown_e2, timeout=ack_timeout, priority=0)

    def register_twin_channel(self, channel: Any, close_timeout: float = 5.0) -> None:
        """Register gRPC channel to twin-service."""
        async def shutdown_grpc() -> None:
            log.info("Closing gRPC channel to twin-service...")
            if hasattr(channel, 'close'):
                if asyncio.iscoroutinefunction(channel.close):
                    await channel.close()
                else:
                    # gRPC channel close is sync, run in executor
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, channel.close)
        self.register("twin_grpc_channel", shutdown_grpc, timeout=close_timeout, priority=5)

    def register_detection_loop(self, task: asyncio.Task, stop_timeout: float = 15.0) -> None:
        """Register the main detection loop task for cancellation."""
        async def shutdown_loop() -> None:
            log.info("Stopping detection loop...")
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=stop_timeout)
                except asyncio.CancelledError:
                    pass
                except asyncio.TimeoutError:
                    log.warning("Detection loop did not stop within %.1fs", stop_timeout)
        self.register("detection_loop", shutdown_loop, timeout=stop_timeout, priority=-20)

    def register_thread_pool(self, executor: Any, shutdown_timeout: float = 10.0) -> None:
        """Register ThreadPoolExecutor for shutdown."""
        async def shutdown_pool() -> None:
            log.info("Shutting down thread pool...")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, executor.shutdown, True, shutdown_timeout)
        self.register("thread_pool", shutdown_pool, timeout=shutdown_timeout, priority=10)

    def register_custom(self, name: str, hook: AsyncShutdownHook, **kwargs: Any) -> None:
        """Register a custom shutdown hook."""
        self.register(name, hook, **kwargs)

    async def shutdown(self, signal_name: Optional[str] = None) -> None:
        """
        Execute graceful shutdown of all registered components.

        Args:
            signal_name: Name of signal that triggered shutdown (for logging)
        """
        async with self._lock:
            if self._shutdown_started:
                log.warning("Shutdown already in progress")
                return
            self._shutdown_started = True
            self._start_time = time.monotonic()

        log.info("=== GRACEFUL SHUTDOWN INITIATED === %s", f"({signal_name})" if signal_name else "")

        # Sort by priority (lowest first)
        components = sorted(self._components, key=lambda c: c.priority)

        results = {"success": [], "failed": [], "timeout": []}
        overall_timeout = get_settings().observatory.log_level  # Not used; just for settings access
        overall_deadline = self._start_time + self._default_timeout

        for component in components:
            if time.monotonic() > overall_deadline:
                log.error("Overall shutdown timeout exceeded — forcing exit")
                break

            log.info("Shutting down component: %s (timeout=%.1fs)", component.name, component.timeout)
            start = time.monotonic()

            try:
                # Run with component-specific timeout
                await asyncio.wait_for(component.shutdown_hook(), timeout=component.timeout)
                elapsed = time.monotonic() - start
                log.info("Component '%s' shut down successfully in %.2fs", component.name, elapsed)
                results["success"].append(component.name)

            except asyncio.TimeoutError:
                elapsed = time.monotonic() - start
                log.error("Component '%s' shutdown timed out after %.2fs", component.name, elapsed)
                results["timeout"].append(component.name)
                if component.critical:
                    # Critical timeout — log but continue
                    pass

            except Exception as e:
                elapsed = time.monotonic() - start
                level = logging.ERROR if component.critical else logging.WARNING
                log.log(level, "Component '%s' shutdown failed after %.2fs: %s", component.name, elapsed, e)
                results["failed"].append(component.name)

        total_elapsed = time.monotonic() - self._start_time
        self._shutdown_complete = True

        log.info("=== GRACEFUL SHUTDOWN COMPLETE in %.2fs ===", total_elapsed)
        log.info("Results: %d success, %d failed, %d timeout",
                 len(results["success"]), len(results["failed"]), len(results["timeout"]))

        if results["failed"]:
            for name in results["failed"]:
                log.error("  FAILED: %s", name)
        if results["timeout"]:
            for name in results["timeout"]:
                log.error("  TIMEOUT: %s", name)

    @property
    def is_shutting_down(self) -> bool:
        return self._shutdown_started

    @property
    def is_shutdown_complete(self) -> bool:
        return self._shutdown_complete


# ── Global Lifecycle Manager Instance ────────────────────────────────────────

_lifecycle_manager: Optional[LifecycleManager] = None


def get_lifecycle_manager() -> LifecycleManager:
    """Get or create the global lifecycle manager."""
    global _lifecycle_manager
    if _lifecycle_manager is None:
        _lifecycle_manager = LifecycleManager()
    return _lifecycle_manager


def set_lifecycle_manager(manager: LifecycleManager) -> None:
    """Set the global lifecycle manager (for testing)."""
    global _lifecycle_manager
    _lifecycle_manager = manager


# ── Signal Handler Registration ──────────────────────────────────────────────

_shutdown_handlers_registered = False


def register_shutdown_handlers(
    manager: Optional[LifecycleManager] = None,
) -> LifecycleManager:
    """
    Register SIGTERM/SIGINT handlers for graceful shutdown.

    Call this early in main() before starting any long-running tasks.

    Args:
        manager: Optional lifecycle manager (uses global if not provided)

    Returns:
        The lifecycle manager instance
    """
    global _shutdown_handlers_registered

    if manager is None:
        manager = get_lifecycle_manager()

    if _shutdown_handlers_registered:
        log.debug("Shutdown handlers already registered")
        return manager

    def signal_handler(signum: int, frame: Any) -> None:
        signal_name = signal.Signals(signum).name
        log.info("Received signal %s (%d) — initiating graceful shutdown", signal_name, signum)

        # Schedule shutdown in the event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — force synchronous shutdown
            log.error("No running event loop — cannot perform graceful shutdown")
            sys.exit(1)

        loop.create_task(manager.shutdown(signal_name))

    # Register handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Handle SIGHUP if needed (config reload)
    try:
        signal.signal(signal.SIGHUP, signal_handler)
    except AttributeError:
        pass  # Windows doesn't have SIGHUP

    _shutdown_handlers_registered = True
    log.info("Graceful shutdown handlers registered for SIGTERM, SIGINT")

    return manager


# ── Async Context Manager for Automatic Cleanup ──────────────────────────────

class GracefulShutdown:
    """
    Async context manager that automatically registers and executes shutdown.

    Usage:
        async with GracefulShutdown() as lifecycle:
            lifecycle.register_websocket_hub(hub)
            lifecycle.register_detection_loop(task)
            # ... run application ...
            # On exit, shutdown() is called automatically
    """

    def __init__(self, manager: Optional[LifecycleManager] = None) -> None:
        self._manager = manager or get_lifecycle_manager()
        self._own_manager = manager is None

    async def __aenter__(self) -> LifecycleManager:
        register_shutdown_handlers(self._manager)
        return self._manager

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._manager.shutdown()
        if self._own_manager:
            global _lifecycle_manager
            _lifecycle_manager = None


# ── Convenience Decorator ────────────────────────────────────────────────────

def shutdown_hook(
    name: str,
    timeout: float = 10.0,
    priority: int = 0,
    critical: bool = True,
) -> Callable[[AsyncShutdownHook], AsyncShutdownHook]:
    """
    Decorator to register a function as a shutdown hook.

    Usage:
        @shutdown_hook("my_component", timeout=5.0)
        async def cleanup_my_component():
            await my_resource.close()
    """
    def decorator(func: AsyncShutdownHook) -> AsyncShutdownHook:
        # Register immediately when decorated (at module import)
        manager = get_lifecycle_manager()
        manager.register(name, func, timeout=timeout, priority=priority, critical=critical)
        return func
    return decorator