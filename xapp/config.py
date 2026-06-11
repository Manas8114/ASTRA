"""
xapp/config.py
──────────────────────────────────────────────────────────────────────────────
Centralized Configuration for ASTRA xApp using Pydantic Settings.

Features:
- Environment-specific configs (dev/staging/prod)
- Fail-fast validation on startup
- Type-safe access to all environment variables
- Single source of truth — replaces scattered os.getenv() calls.

Usage:
    from xapp.config import settings
    print(settings.redis.host)
    print(settings.e2.mode)
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RedisSettings(BaseSettings):
    """Redis connection settings."""
    host: str = Field(default="localhost", description="Redis host")
    port: int = Field(default=6379, ge=1, le=65535, description="Redis port")
    password: Optional[str] = Field(default=None, description="Redis password (optional)")
    db: int = Field(default=0, ge=0, le=15, description="Redis database number")
    max_connections: int = Field(default=50, ge=1, le=200, description="Connection pool size")
    socket_timeout: float = Field(default=5.0, gt=0, description="Socket timeout seconds")
    socket_connect_timeout: float = Field(default=5.0, gt=0, description="Socket connect timeout")
    retry_on_timeout: bool = Field(default=True, description="Retry on timeout")
    health_check_interval: int = Field(default=30, ge=5, description="Health check interval seconds")

    # Stream/List limits
    kpi_history_maxlen: int = Field(default=3600, description="KPI history stream max length")
    anomalies_maxlen: int = Field(default=1000, description="Anomalies list max length")
    healing_log_maxlen: int = Field(default=1000, description="Healing log list max length")

    model_config = SettingsConfigDict(env_prefix="REDIS_", extra="ignore")


class E2Settings(BaseSettings):
    """E2 RC Client settings."""
    mode: Literal["demo", "prod"] = Field(default="demo", description="E2 client mode")
    ric_request_timeout: float = Field(default=10.0, gt=0, description="Control request timeout seconds")
    max_retries: int = Field(default=3, ge=0, le=10, description="Max retries for failed control requests")
    retry_backoff_base: float = Field(default=1.0, gt=0, description="Exponential backoff base seconds")
    circuit_failure_threshold: int = Field(default=3, ge=1, description="Circuit breaker failure threshold")
    circuit_recovery_timeout: float = Field(default=30.0, gt=0, description="Circuit breaker recovery timeout seconds")
    ran_function_id: int = Field(default=3, description="E2SM-RC RAN function ID")

    model_config = SettingsConfigDict(env_prefix="E2_", extra="ignore")


class TwinSettings(BaseSettings):
    """Digital Twin settings."""
    mode: Literal["local", "grpc"] = Field(default="local", description="Twin mode: local M/M/1 or gRPC service")
    grpc_url: str = Field(default="localhost:50051", description="gRPC twin-service URL")
    grpc_timeout: float = Field(default=2.0, gt=0, description="gRPC call timeout seconds")
    approval_threshold: float = Field(default=0.20, gt=0, le=1, description="Minimum improvement % for approval")
    circuit_failure_threshold: int = Field(default=3, ge=1, description="Circuit breaker failure threshold")
    circuit_recovery_timeout: float = Field(default=30.0, gt=0, description="Circuit breaker recovery timeout seconds")

    model_config = SettingsConfigDict(env_prefix="TWIN_", extra="ignore")


class KPISettings(BaseSettings):
    """KPI Ingestion settings."""
    source: Literal["dev", "prometheus", "open5gs_file"] = Field(default="dev", description="KPI data source")
    poll_seconds: float = Field(default=1.0, gt=0, le=60, description="KPI polling interval seconds")
    consecutive_anomaly_trigger: int = Field(default=5, ge=1, le=100, description="Consecutive anomalies before declaration")
    anomaly_threshold_sigma: float = Field(default=3.0, gt=0, le=10, description="Sigma multiplier for dynamic threshold")

    # Prometheus specific
    prometheus_url: str = Field(default="http://localhost:9090", description="Prometheus base URL")

    # Open5GS file specific
    open5gs_kpi_jsonl: str = Field(default="data/open5gs_kpis.jsonl", description="Open5GS KPI JSONL file path")

    model_config = SettingsConfigDict(env_prefix="KPI_", extra="ignore")


class ModelSettings(BaseSettings):
    """ML Model settings."""
    # Paths
    lstm_ae_pt_path: str = Field(default="xapp/model/saved_models/lstm_ae_best.pt", description="PyTorch LSTM AE weights")
    lstm_ae_onnx_path: str = Field(default="xapp/model/saved_models/lstm_ae_best.onnx", description="ONNX LSTM AE model")
    lstm_ae_onnx_quantized_path: str = Field(default="xapp/model/saved_models/lstm_ae_best_quantized.onnx", description="Quantized ONNX model")
    scaler_path: str = Field(default="training/data/scaler.pkl", description="MinMax scaler pickle")
    threshold_path: str = Field(default="xapp/model/saved_models/threshold.json", description="Threshold JSON")
    forecast_head_path: str = Field(default="xapp/model/saved_models/forecast_head.pt", description="ForecastHead weights")

    # Inference
    device: Literal["auto", "cpu", "cuda"] = Field(default="auto", description="Inference device")
    force_cpu: bool = Field(default=False, description="Force CPU even if GPU available")
    gpu_mem_fraction: float = Field(default=0.8, gt=0, le=1, description="GPU memory fraction limit")
    onnx_providers: list[str] = Field(default=["CUDAExecutionProvider", "CPUExecutionProvider"], description="ONNX execution providers")

    # Training / Continual Learning
    ewc_enabled: bool = Field(default=True, description="Enable Elastic Weight Consolidation")
    ewc_lambda: float = Field(default=1000.0, gt=0, description="EWC regularization strength")
    ewc_buffer_capacity: int = Field(default=500, ge=10, description="Anomaly memory buffer capacity")

    model_config = SettingsConfigDict(env_prefix="MODEL_", extra="ignore")


class ForecastSettings(BaseSettings):
    """Forecast/Preemptive Healing settings."""
    horizon: int = Field(default=300, ge=10, le=3600, description="Forecast horizon in seconds")
    preemptive_horizon: int = Field(default=60, ge=10, le=300, description="Preemptive alert horizon seconds")
    confidence_gate: float = Field(default=0.65, gt=0, le=1, description="Minimum confidence for preemptive action")
    min_confidence: float = Field(default=0.65, gt=0, le=1, description="Alias for confidence_gate")

    model_config = SettingsConfigDict(env_prefix="FORECAST_", extra="ignore")


class HealingSettings(BaseSettings):
    """Healing Action settings."""
    cooldown_seconds: float = Field(default=30.0, gt=0, le=3600, description="Healing cooldown between actions")
    blast_radius_limits: dict[str, float] = Field(
        default_factory=lambda: {
            "ADMISSION_CONTROL": 0.15,
            "SLICE_REBALANCE": 0.20,
            "POWER_CONTROL": 5.0,
            "HANDOVER_THRESHOLD_ADJUST": 2.0,
        },
        description="Prod-mode parameter limits per action type"
    )

    model_config = SettingsConfigDict(env_prefix="HEALING_", extra="ignore")


class MultiCellSettings(BaseSettings):
    """Multi-Cell Coordination settings."""
    enabled: bool = Field(default=True, description="Enable multi-cell coordination")
    topology_path: str = Field(default="topology.json", description="Cell topology JSON file")
    http_timeout: float = Field(default=3.0, gt=0, description="HTTP timeout for neighbor calls")
    max_retries: int = Field(default=2, ge=0, le=5, description="Max retries for neighbor notification")

    model_config = SettingsConfigDict(env_prefix="MULTICELL_", extra="ignore")


class A1Settings(BaseSettings):
    """A1 Policy Interface settings."""
    api_key: Optional[str] = Field(default=None, description="A1 API key for authentication")
    policy_types: list[str] = Field(default=["astra.threshold.v1", "astra.model.v1"], description="Registered policy type IDs")

    model_config = SettingsConfigDict(env_prefix="A1_", extra="ignore")


class SecuritySettings(BaseSettings):
    """Security / Auth settings."""
    mode: Literal["demo", "lab", "prod"] = Field(default="demo", description="Overall ASTRA mode")
    control_api_key: Optional[str] = Field(default=None, description="Control endpoint API key")
    admin_token: Optional[str] = Field(default=None, description="Admin static token")
    viewer_token: Optional[str] = Field(default=None, description="Viewer static token")
    oidc_issuer: Optional[str] = Field(default=None, description="OIDC issuer URL (Keycloak/Okta)")
    require_mtls: bool = Field(default=False, description="Require mTLS client certificates in prod")

    model_config = SettingsConfigDict(env_prefix="ASTRA_", extra="ignore")


class ObservatorySettings(BaseSettings):
    """Observability settings."""
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO", description="Log level")
    log_format: Literal["json", "console"] = Field(default="json", description="Log format")
    enable_tracing: bool = Field(default=False, description="Enable OpenTelemetry tracing")
    otel_endpoint: Optional[str] = Field(default=None, description="OTLP exporter endpoint")
    service_name: str = Field(default="astra-xapp", description="Service name for tracing")
    metrics_enabled: bool = Field(default=True, description="Enable Prometheus metrics")
    metrics_port: int = Field(default=8000, description="Metrics endpoint port (same as HTTP)")

    model_config = SettingsConfigDict(env_prefix="OBS_", extra="ignore")


class WebSocketSettings(BaseSettings):
    """WebSocket Hub settings."""
    max_clients: int = Field(default=100, ge=1, le=1000, description="Max concurrent WebSocket connections")
    client_queue_size: int = Field(default=1000, ge=100, le=10000, description="Per-client message queue size")
    slow_consumer_timeout: float = Field(default=5.0, gt=0, description="Timeout before marking client as slow")
    drop_policy: Literal["drop_oldest", "drop_newest", "disconnect"] = Field(
        default="drop_oldest",
        description="Behavior when client queue is full"
    )
    ping_interval: float = Field(default=30.0, gt=0, description="WebSocket ping interval seconds")
    ping_timeout: float = Field(default=10.0, gt=0, description="WebSocket ping timeout seconds")

    model_config = SettingsConfigDict(env_prefix="WS_", extra="ignore")


class APISettings(BaseSettings):
    """REST API settings."""
    host: str = Field(default="0.0.0.0", description="API bind host")
    port: int = Field(default=8000, ge=1, le=65535, description="API bind port")
    cors_origins: list[str] = Field(default=["http://localhost:3000", "http://127.0.0.1:3000"], description="Allowed CORS origins")
    rate_limit_times: int = Field(default=50, ge=1, description="Rate limit requests per window")
    rate_limit_seconds: int = Field(default=60, ge=1, description="Rate limit window seconds")

    model_config = SettingsConfigDict(env_prefix="API_", extra="ignore")


class DatabaseSettings(BaseSettings):
    """PostgreSQL Database settings."""
    url: str = Field(default="sqlite:///./data/astra_audit.db", description="Database URL (PostgreSQL or SQLite)")
    pool_size: int = Field(default=10, ge=1, le=50, description="Connection pool size")
    max_overflow: int = Field(default=20, ge=0, le=100, description="Max overflow connections")
    pool_timeout: float = Field(default=30.0, gt=0, description="Pool checkout timeout seconds")
    pool_recycle: int = Field(default=3600, ge=60, description="Connection recycle seconds")
    echo: bool = Field(default=False, description="Echo SQL statements")

    model_config = SettingsConfigDict(env_prefix="DB_", extra="ignore")


class Settings(BaseSettings):
    """Root ASTRA Settings — aggregates all sub-settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_nested_delimiter="__",
    )

    # Sub-settings (auto-populated from env with prefixes)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    e2: E2Settings = Field(default_factory=E2Settings)
    twin: TwinSettings = Field(default_factory=TwinSettings)
    kpi: KPISettings = Field(default_factory=KPISettings)
    model: ModelSettings = Field(default_factory=ModelSettings)
    forecast: ForecastSettings = Field(default_factory=ForecastSettings)
    healing: HealingSettings = Field(default_factory=HealingSettings)
    multicell: MultiCellSettings = Field(default_factory=MultiCellSettings)
    a1: A1Settings = Field(default_factory=A1Settings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    observatory: ObservatorySettings = Field(default_factory=ObservatorySettings)
    websocket: WebSocketSettings = Field(default_factory=WebSocketSettings)
    api: APISettings = Field(default_factory=APISettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)

    # Cell identification
    cell_id: str = Field(default="cell_001", description="Cell identifier")

    # Derived / computed properties
    @property
    def is_prod(self) -> bool:
        return self.security.mode == "prod"

    @property
    def is_lab(self) -> bool:
        return self.security.mode == "lab"

    @property
    def is_demo(self) -> bool:
        return self.security.mode == "demo"

    @model_validator(mode="after")
    def validate_prod_requirements(self) -> "Settings":
        """Fail fast on production startup if critical config is missing."""
        if self.is_prod:
            errors = []

            # Security requirements
            if not self.security.control_api_key:
                errors.append("ASTRA_CONTROL_API_KEY is required in prod mode")
            if not self.security.admin_token:
                errors.append("ASTRA_ADMIN_TOKEN is required in prod mode")
            if self.security.oidc_issuer is None:
                errors.append("OIDC_ISSUER is required in prod mode for OIDC auth")

            # Database requirements
            if self.database.url.startswith("sqlite"):
                errors.append("PostgreSQL DATABASE_URL is required in prod mode (sqlite not allowed)")

            # Redis requirements
            if self.redis.host == "localhost":
                errors.append("REDIS_HOST must be configured for prod (cannot be localhost)")

            # E2 requirements
            if self.e2.mode == "prod" and self.e2.max_retries < 1:
                errors.append("E2_MAX_RETRIES must be >= 1 in prod mode")

            if errors:
                raise ValueError(f"Production configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

        return self

    @model_validator(mode="after")
    def validate_paths(self) -> "Settings":
        """Validate that required model files exist (except in demo mode where we can train)."""
        if not self.is_demo:
            required_files = [
                (self.model.lstm_ae_pt_path, "LSTM Autoencoder PyTorch weights"),
                (self.model.scaler_path, "MinMax scaler"),
                (self.model.threshold_path, "Threshold configuration"),
            ]
            for path_str, desc in required_files:
                path = Path(path_str)
                if not path.exists():
                    # In prod/lab, these MUST exist. In demo, we can fall back to training.
                    if self.is_prod or self.is_lab:
                        raise ValueError(f"Required file not found: {path_str} ({desc})")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached settings instance. Raises on validation failure."""
    return Settings()


# Convenience accessor for backward compatibility during migration
settings = get_settings()


def reload_settings() -> Settings:
    """Force reload settings (clears cache). Useful for testing."""
    get_settings.cache_clear()
    return get_settings()