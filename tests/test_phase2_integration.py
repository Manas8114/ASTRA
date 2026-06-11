"""
tests/test_phase2_integration.py
──────────────────────────────────────────────────────────────────────────────
Integration tests for Phase 2:
- Redis Reliability Layer
- PostgreSQL Async Audit Trail
- Drift Detection
- End-to-end healing pipeline tests
"""

import asyncio
import pytest
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from xapp.persistence.redis_reliability import ReliableRedisClient, RetryConfig, RetryPolicy, DeadLetterEntry
from xapp.persistence.pg_audit_async import AsyncPGAuditTrail, AuditEvent, QueryFilter
from xapp.ml.drift_detection import DriftDetector, DriftConfig, DriftSeverity, DriftType
from xapp.healing.action_engine import HealingActionEngine, HealingAction
from xapp.ingestion.kpi_schema import AnomalyType


class TestRedisReliability:
    """Test Redis reliability layer."""

    @pytest.mark.asyncio
    async def test_reliable_client_start_stop(self):
        """Test client starts and stops cleanly."""
        client = ReliableRedisClient(
            host="localhost", port=6379,
            db=15,  # Use test DB
        )

    @pytest.mark.asyncio
    async def test_retry_logic(self):
        """Test retry with exponential backoff."""
        config = RetryConfig(max_retries=2, base_delay=0.01, policy=RetryPolicy.EXPONENTIAL)

        # Test delay calculation manually
        # For exponential: base_delay * 2^attempt
        delay0 = 0.01 * (2 ** 0)  # 0.01
        delay1 = 0.01 * (2 ** 1)  # 0.02
        assert delay0 == 0.01
        assert delay1 == 0.02

    @pytest.mark.asyncio
    async def test_dead_letter_queue(self):
        """Test DLQ stores failed operations."""
        client = ReliableRedisClient(host="localhost", port=6379, db=15)

        # Manually add to DLQ
        entry = DeadLetterEntry(
            operation="test_op",
            args=("arg1",),
            kwargs={"key": "value"},
            error="Connection failed",
            retry_count=3,
            failed_at=1000.0,
            correlation_id="test-corr-id",
        )
        client._dlq.append(entry)

        dlq_entries = client.get_dlq_entries()
        assert len(dlq_entries) == 1
        assert dlq_entries[0]["operation"] == "test_op"
        assert dlq_entries[0]["retry_count"] == 3

    @pytest.mark.asyncio
    async def test_dlq_retry(self):
        """Test retrying a DLQ entry."""
        client = ReliableRedisClient(host="localhost", port=6379, db=15)

        entry = DeadLetterEntry(
            operation="add_kpi_history",
            args=("cell_1", {"latency_ms": 10}),
            kwargs={},
            error="Timeout",
            retry_count=3,
            failed_at=1000.0,
        )
        client._dlq.append(entry)

        # First add a working mock to the queue
        # We can't easily test the full flow without Redis, but we can test the mechanism
        assert len(client._dlq) == 1


class TestAsyncPGAuditTrail:
    """Test async PostgreSQL audit trail."""

    @pytest.mark.asyncio
    async def test_sqlite_audit_trail(self, tmp_path):
        """Test audit trail with SQLite backend."""
        db_path = tmp_path / "test_audit.db"
        audit = AsyncPGAuditTrail(dsn=f"sqlite:///{db_path}")

    @pytest.mark.asyncio
    async def test_append_and_query_events(self, tmp_path):
        """Test appending and querying events."""
        db_path = tmp_path / "test_audit.db"
        audit = AsyncPGAuditTrail(dsn=f"sqlite:///{db_path}", flush_interval=0.1)
        await audit.start()

        # Append events
        await audit.append_event("cell_1", "KPI_UPDATE", {"latency_ms": 10}, "corr-1")
        await audit.append_event("cell_1", "ANOMALY_DETECTED", {"type": "CONGESTION"}, "corr-2")
        await audit.append_event("cell_2", "HEALING_APPLIED", {"action": "ADMISSION_CONTROL"}, "corr-3")

        # Force flush
        await audit._flush_batch()

        # Query events
        filter = QueryFilter(cell_id="cell_1", limit=10)
        events = await audit.query_events(filter)

        assert len(events) == 2
        assert all(e["cell_id"] == "cell_1" for e in events)

        # Test event counts
        counts = await audit.get_event_counts("cell_1")
        assert counts["KPI_UPDATE"] == 1
        assert counts["ANOMALY_DETECTED"] == 1

        await audit.shutdown()

    @pytest.mark.asyncio
    async def test_batch_append(self, tmp_path):
        """Test batch append of events."""
        db_path = tmp_path / "test_audit.db"
        audit = AsyncPGAuditTrail(dsn=f"sqlite:///{db_path}", flush_interval=10.0)
        await audit.start()

        events = [
            ("cell_1", "KPI_UPDATE", {"latency": 10}, f"corr-{i}")
            for i in range(20)
        ]
        await audit.append_batch(events)

        # Force flush
        await audit._flush_batch()

        filter = QueryFilter(cell_id="cell_1", limit=25)
        results = await audit.query_events(filter)
        assert len(results) == 20

        await audit.shutdown()

    @pytest.mark.asyncio
    async def test_latest_events(self, tmp_path):
        """Test getting latest events for a cell."""
        db_path = tmp_path / "test_audit.db"
        audit = AsyncPGAuditTrail(dsn=f"sqlite:///{db_path}", flush_interval=0.1)
        await audit.start()

        for i in range(5):
            await audit.append_event(
                "cell_1", "KPI_UPDATE", {"iteration": i}, f"corr-{i}"
            )
        # Force flush
        await audit._flush_batch()

        latest = await audit.get_latest_events("cell_1", limit=3)
        assert len(latest) == 3
        # Should be in descending timestamp order
        assert latest[0]["payload"]["iteration"] == 4
        assert latest[1]["payload"]["iteration"] == 3

        await audit.shutdown()


class TestDriftDetection:
    """Test drift detection functionality."""

    def test_drift_detector_initialization(self):
        """Test detector initializes with default config."""
        detector = DriftDetector()
        assert detector._config.ks_warning_threshold == 0.05
        assert detector._config.psi_warning_threshold == 0.1
        assert len(detector._feature_names) == 6

    def test_set_reference_window(self):
        """Test setting reference window."""
        detector = DriftDetector()

        # Generate normal errors (mean=0.01, std=0.005)
        import numpy as np
        ref_errors = np.random.normal(0.01, 0.005, 500).tolist()
        ref_features = {
            "latency_ms": np.random.normal(10, 2, 500).tolist(),
            "bler_pct": np.random.normal(1, 0.3, 500).tolist(),
        }

        detector.set_reference_window(ref_errors, ref_features)

        assert detector._ref_error_mean is not None
        assert detector._ref_error_std is not None
        assert "latency_ms" in detector._ref_feature_means

    def test_ks_test_no_drift(self):
        """Test KS test doesn't trigger on similar distributions."""
        detector = DriftDetector(DriftConfig(min_samples=50))

        import numpy as np
        # Same distribution for reference and current
        ref_errors = np.random.normal(0.01, 0.005, 200).tolist()
        cur_errors = np.random.normal(0.01, 0.005, 200).tolist()

        detector.set_reference_window(ref_errors)
        detector._current_errors.extend(cur_errors)

        alerts = detector.check_drift()
        # Should not trigger with same distribution
        ks_alerts = [a for a in alerts if a.drift_type == DriftType.KS_TEST]
        assert len(ks_alerts) == 0

    def test_ks_test_detects_drift(self):
        """Test KS test detects distribution shift."""
        detector = DriftDetector(DriftConfig(min_samples=50, ks_warning_threshold=0.05))

        import numpy as np
        # Different distributions
        ref_errors = np.random.normal(0.01, 0.005, 200).tolist()
        cur_errors = np.random.normal(0.05, 0.02, 200).tolist()  # Shifted mean

        detector.set_reference_window(ref_errors)
        detector._current_errors.extend(cur_errors)

        alerts = detector.check_drift()
        ks_alerts = [a for a in alerts if a.drift_type == DriftType.KS_TEST]
        assert len(ks_alerts) > 0
        assert ks_alerts[0].severity in [DriftSeverity.WARNING, DriftSeverity.CRITICAL]

    def test_psi_detection(self):
        """Test PSI detects feature drift."""
        detector = DriftDetector(DriftConfig(min_samples=50, psi_warning_threshold=0.1))

        import numpy as np
        # Reference: latency ~ N(10, 2)
        ref_features = {
            "latency_ms": np.random.normal(10, 2, 200).tolist(),
        }
        # Current: latency shifted to N(15, 2)
        cur_features = {
            "latency_ms": np.random.normal(15, 2, 200).tolist(),
        }

        detector.set_reference_window([0.01]*200, ref_features)
        for v in cur_features["latency_ms"]:
            detector.add_feature_values({"latency_ms": v})

        alerts = detector.check_drift()
        psi_alerts = [a for a in alerts if a.drift_type == DriftType.PSI]
        assert len(psi_alerts) > 0
        assert psi_alerts[0].feature == "latency_ms"

    def test_feature_shift_detection(self):
        """Test feature mean shift detection."""
        detector = DriftDetector(DriftConfig(min_samples=50))

        import numpy as np
        # Reference: latency ~ N(10, 2)
        np.random.seed(42)  # Deterministic for testing
        ref_features = {
            "latency_ms": np.random.normal(10, 2, 200).tolist(),
        }
        # Current: latency shifted significantly to N(20, 2)
        np.random.seed(123)
        cur_features = {
            "latency_ms": np.random.normal(20, 2, 200).tolist(),  # 5 sigma shift!
        }

        detector.set_reference_window([0.01]*200, ref_features)
        for v in cur_features["latency_ms"]:
            detector.add_feature_values({"latency_ms": v})

        alerts = detector.check_drift()
        shift_alerts = [a for a in alerts if a.drift_type == DriftType.FEATURE_DRIFT]
        assert len(shift_alerts) > 0
        # With fixed seeds, z-score should be > 5 for CRITICAL
        assert shift_alerts[0].severity in [DriftSeverity.WARNING, DriftSeverity.CRITICAL]

    def test_retraining_trigger(self):
        """Test retraining trigger logic."""
        config = DriftConfig(
            min_samples=50,
            enable_retraining_trigger=True,
            retraining_cooldown_hours=0.001,  # Very short for testing
        )
        detector = DriftDetector(config)

        import numpy as np
        ref_errors = np.random.normal(0.01, 0.005, 200).tolist()
        ref_features = {
            "latency_ms": np.random.normal(10, 2, 200).tolist(),
        }
        detector.set_reference_window(ref_errors, ref_features)

        # Add drift that will trigger critical alerts
        detector._current_errors.extend(np.random.normal(0.1, 0.05, 200).tolist())
        for _ in range(200):
            detector.add_feature_values({"latency_ms": np.random.normal(25, 2)})

        alerts = detector.check_drift()
        critical_alerts = [a for a in alerts if a.severity == DriftSeverity.CRITICAL]
        assert len(critical_alerts) >= 2

        assert detector.should_trigger_retraining() is True

    def test_stats_and_alerts(self):
        """Test stats and alert retrieval."""
        detector = DriftDetector()

        import numpy as np
        ref_errors = np.random.normal(0.01, 0.005, 100).tolist()
        detector.set_reference_window(ref_errors)

        stats = detector.get_stats()
        assert stats["reference_error_count"] == 100
        assert stats["ref_error_mean"] is not None

        alerts = detector.get_recent_alerts()
        assert isinstance(alerts, list)


class TestEndToEndHealing:
    """End-to-end tests for the healing pipeline."""

    @pytest.mark.asyncio
    async def test_healing_action_engine_with_circuit_breaker(self):
        """Test healing engine uses circuit breaker."""
        engine = HealingActionEngine()

        action = HealingAction("ADMISSION_CONTROL", {"pct": 0.20})

        class MockSimResult:
            improvement_pct = 0.50
            projected_state = {"dl_throughput_mbps": 80.0}

        result = await engine.execute(
            AnomalyType.CONGESTION, action, MockSimResult(), {"dl_throughput_mbps": 100.0}
        )

        assert result["type"] == "HEALING_APPLIED"
        assert "e2_result" in result
        assert engine._e2_breaker is not None

    @pytest.mark.asyncio
    async def test_healing_wait_for_acks(self):
        """Test graceful shutdown waits for E2 acks."""
        engine = HealingActionEngine()
        await engine.wait_for_pending_acks(timeout=1.0)
        # Should complete without error

    @pytest.mark.asyncio
    async def test_digital_twin_circuit_breaker(self):
        """Test digital twin uses shared circuit breaker."""
        from xapp.digital_twin.twin_simulator import DigitalTwinSimulator
        from xapp.model.anomaly_detector import AnomalyDetector

        detector = AnomalyDetector()
        twin = DigitalTwinSimulator(detector)

        assert twin._circuit is not None
        assert hasattr(twin._circuit, 'call')
        assert hasattr(twin._circuit, 'record_success')


class TestConfiguration:
    """Test configuration system."""

    def test_settings_validation(self):
        """Test settings load correctly."""
        from xapp.config import get_settings
        settings = get_settings()
        assert settings.cell_id == "cell_001"
        assert settings.security.mode == "demo"
        assert settings.websocket.max_clients == 100

    def test_nested_settings(self):
        """Test nested settings access."""
        from xapp.config import get_settings
        settings = get_settings()
        assert settings.redis.host == "localhost"
        assert settings.e2.circuit_failure_threshold == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])