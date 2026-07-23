"""
cr2e/config.py
─────────────────────────────────────────────────────────────────────────────
CR²E Pydantic Settings — mirrors ASTRA's settings pattern exactly.

All fields have safe defaults for demo mode.
Production / lab values are injected via environment variables.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CR2ESettings(BaseSettings):
    """Top-level CR²E configuration block."""

    model_config = SettingsConfigDict(
        env_prefix="CR2E_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Mode ──────────────────────────────────────────────────────────────────
    mode: Literal["demo", "lab", "prod"] = Field(
        default="demo",
        description="Operating mode: demo = synthetic data, lab/prod = real KPI stream",
    )

    # ── Causal discovery ──────────────────────────────────────────────────────
    discovery_algorithm: Literal["pc", "notears"] = Field(
        default="pc",
        description="Structure-learning algorithm: pc (causal-learn) or notears",
    )
    history_window_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Rolling KPI history window used for discovery (hours)",
    )
    discovery_alpha: float = Field(
        default=0.05,
        gt=0,
        lt=1,
        description="PC independence test significance level",
    )
    discovery_ci_test: str = Field(
        default="fisherz",
        description="PC conditional independence test (fisherz, kci, chisq, …)",
    )
    dag_constraint_path: str = Field(
        default="cr2e/data/domain_dag.json",
        description="Path to domain-constrained DAG JSON (forbidden/required edges)",
    )
    dag_snapshot_path: str = Field(
        default="cr2e/data/dag_snapshot.json",
        description="Path where the discovered DAG is persisted",
    )

    # ── Causal inference ──────────────────────────────────────────────────────
    estimator: Literal["linear_dml"] = Field(
        default="linear_dml",
        description="Effect estimator (EconML LinearDML; extensible to other estimators)",
    )
    refutation_tests: list[str] = Field(
        default_factory=lambda: [
            "placebo_treatment",
            "random_common_cause",
            "data_subset",
        ],
        description="DoWhy refutation test suite to run per causal query",
    )
    min_history_rows: int = Field(
        default=200,
        ge=50,
        description="Minimum rows required in the per-fault window for estimation",
    )

    # ── Root-cause ranking ────────────────────────────────────────────────────
    top_k_causes: int = Field(
        default=3,
        ge=1,
        le=6,
        description="Number of top root causes to report per fault event",
    )

    # ── Counterfactual ────────────────────────────────────────────────────────
    counterfactual_target_resolution_pct: float = Field(
        default=0.80,
        gt=0,
        le=1.0,
        description="Target fraction of degradation to resolve via minimal intervention",
    )

    # ── Explanation (NL) ──────────────────────────────────────────────────────
    ollama_url: str = Field(
        default="http://localhost:11434",
        description="Ollama API base URL for local LLM explanation generation",
    )
    ollama_model: str = Field(
        default="qwen2.5:7b",
        description="Ollama model to use for NL explanation",
    )
    ollama_timeout: float = Field(
        default=30.0,
        gt=0,
        description="Ollama request timeout seconds",
    )

    # ── Experiment tracking ───────────────────────────────────────────────────
    mlflow_uri: str = Field(
        default="http://localhost:5000",
        description="MLflow tracking server URI",
    )
    mlflow_experiment: str = Field(
        default="cr2e-causal-discovery",
        description="MLflow experiment name",
    )
    mlflow_enabled: bool = Field(
        default=True,
        description="Enable MLflow run logging",
    )

    # ── API ────────────────────────────────────────────────────────────────────
    host: str = Field(default="0.0.0.0", description="CR²E API bind host")
    port: int = Field(default=8001, ge=1, le=65535, description="CR²E API port")
    astra_ws_url: str = Field(
        default="ws://localhost:8000/ws",
        description="ASTRA WebSocket URL for anomaly event subscription (lab/prod mode)",
    )

    # ── GPU ────────────────────────────────────────────────────────────────────
    gpu_enabled: bool = Field(
        default=False,
        description="Enable GPU acceleration for NOTEARS (Phase 8; only after measured baseline)",
    )


@lru_cache(maxsize=1)
def get_cr2e_settings() -> CR2ESettings:
    """Get cached CR²E settings. Call reload_cr2e_settings() in tests."""
    return CR2ESettings()


settings = get_cr2e_settings()


def reload_cr2e_settings() -> CR2ESettings:
    """Force-reload settings; clears cache. Useful for testing."""
    get_cr2e_settings.cache_clear()
    return get_cr2e_settings()
