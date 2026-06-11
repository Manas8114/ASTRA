# ASTRA Production Hardening — Remediation Plan

**Target:** Take ASTRA from hackathon prototype → lab-ready O-RAN xApp  
**Estimated Effort:** 3-4 months (2 engineers)  
**Prerequisites:** Access to O-RAN testbed (ColO-RAN, O-RAN SC, or vendor near-RT RIC)

---

## Phase 1: Infrastructure & Deployment (Weeks 1-4)

### 1.1 Kubernetes Helm Chart — **Priority: CRITICAL**
| Task | Owner | Effort | Dependencies |
|------|-------|--------|--------------|
| Create `helm/astra-xapp/` chart structure | | 2 days | — |
| xApp Deployment: resources, probes, env vars, configmap | | 2 days | 1.1 |
| twin-service Deployment + Service | | 1 day | 1.1 |
| Redis Deployment (StatefulSet) + Service | | 1 day | 1.1 |
| Prometheus ServiceMonitor + Grafana dashboards | | 2 days | 1.1 |
| Ingress for REST/WS APIs (TLS termination) | | 1 day | 1.1 |
| NetworkPolicies (xApp ↔ twin, xApp ↔ Redis, xApp ↔ E2) | | 1 day | 1.1 |
| Helm values files: dev, staging, prod | | 1 day | 1.1 |
| **Total** | | **10 days** | |

**Deliverable:** `helm install astra ./helm/astra-xapp -f values-prod.yaml` deploys full stack.

### 1.2 CI/CD Pipeline — **Priority: HIGH**
| Task | Owner | Effort |
|------|-------|--------|
| GitHub Actions: lint, type-check, unit tests | | 1 day |
| Build multi-arch Docker images (xApp, twin-service, dashboard) | | 2 days |
| Push to GHCR with semantic versioning | | 1 day |
| Helm chart lint + package + publish to OCI registry | | 1 day |
| **Total** | | **5 days** |

---

## Phase 2: O-RAN Integration (Weeks 3-8)

### 2.1 Real E2 RC Client — **Priority: CRITICAL**
**Current:** `xapp/healing/e2_rc_client.py` returns mock success.

**Required Implementation:**
```python
# Replace stub with ricxappframe integration
from ricxappframe.xapp_frame import Xapp
from e2sm_rc.rc_prego_v1 import (
    RcControlHeader, RcControlMessage, AdmissionControl, SliceRebalance, PowerControl
)
```

| Sub-task | Effort |
|----------|--------|
| Add `ricxappframe` + `e2sm_rc` to requirements (pin versions) | 0.5 day |
| Implement `E2RCClient` class: setup, subscription, control encode/decode | 5 days |
| E2 Setup/Teardown handling (RAN function registration) | 2 days |
| Subscription management (trigger: EVENT_A2, report style) | 2 days |
| Control message encoding for 4 action types (admission, slice, power, handover) | 3 days |
| Async acknowledgment handling + retry/timeout logic | 2 days |
| Unit tests with `e2sim` or mock RIC | 2 days |
| **Total** | **16.5 days** |

**Interface Contract (unchanged):**
```python
class E2RCClient:
    async def send_control(self, action_type: str, params: dict[str, float]) -> bool
    # Returns True on ACK, raises on NACK/timeout
```

### 2.2 A1 Policy Interface — **Priority: HIGH**
**Current:** REST `/policy` endpoint + stub `policy_receiver.py`.

**Required:**
| Sub-task | Effort |
|----------|--------|
| Implement A1 mediator (O-RAN SC `a1-interface` or custom) | 5 days |
| Policy type registration: `astra.threshold.v1`, `astra.model.v1` | 2 days |
| Policy enforcement: hot-reload threshold, model swap (ONNX) | 3 days |
| Policy status reporting (A1-PMS) | 2 days |
| **Total** | **12 days** |

---

## Phase 3: Persistence & State (Weeks 5-8)

### 3.1 Redis-Backed LiveState — **Priority: HIGH**
**Current:** In-memory `LiveState` class loses everything on restart.

**Schema Design:**
```redis
# Keys (all prefixed: astra:{cell_id}:)
astra:cell_001:kpi_history      # Redis Stream (maxlen=3600)
astra:cell_001:anomalies        # Redis List (LPUSH, LTRIM 1000)
astra:cell_001:healing_log      # Redis List
astra:cell_001:attribution      # Redis Hash (latest)
astra:cell_001:forecast_latest  # Redis String (JSON)
astra:cell_001:prevention_stats # Redis Hash
astra:cell_001:threshold        # Redis String (float)
astra:cell_001:model_version    # Redis String
```

| Sub-task | Effort |
|----------|--------|
| Create `xapp/persistence/redis_client.py` (async, connection pool) | 2 days |
| Refactor `LiveState` to use Redis (snapshot, history, append) | 3 days |
| Add Redis health check + reconnection logic | 1 day |
| Migration script for existing in-memory data | 1 day |
| **Total** | **7 days** |

### 3.2 PostgreSQL Audit Trail — **Priority: MEDIUM**
| Sub-task | Effort |
|----------|--------|
| Schema: anomalies, healing_actions, prevention_events, model_deployments | 1 day |
| SQLAlchemy async models + Alembic migrations | 2 days |
| Write path: async batch insert (buffer 100 rows / 5s) | 2 days |
| Read API: `/audit/anomalies`, `/audit/healing` with filters | 1 day |
| **Total** | **6 days** |

---

## Phase 4: Model Governance (Weeks 6-10)

### 4.1 MLflow Integration — **Priority: HIGH**
| Sub-task | Effort |
|----------|--------|
| Add MLflow tracking to `training/train_lstm.py`, `training/train_forecast.py` | 2 days |
| Model registry: register ONNX artifacts with stage (Staging/Production) | 2 days |
| xApp startup: load model from MLflow by stage + version | 2 days |
| A1 policy: deploy new model version (canary 10% → 100%) | 3 days |
| Rollback endpoint: `/model/rollback` | 1 day |
| **Total** | **10 days** |

### 4.2 Drift Detection & Continual Learning — **Priority: MEDIUM**
**Existing code:** `xapp/innovations/continual/ewc.py`, `anomaly_memory.py` — **unused**.

| Sub-task | Effort |
|----------|--------|
| Wire EWC into `AnomalyDetector` (periodic fine-tune on novel anomalies) | 4 days |
| Drift detector: KS test on reconstruction error distribution (daily) | 2 days |
| Alert on drift → trigger retraining pipeline | 2 days |
| **Total** | **8 days** |

---

## Phase 5: Security Hardening (Weeks 7-10)

| Sub-task | Effort | Notes |
|----------|--------|-------|
| mTLS for gRPC (twin-service) — cert-manager + SPIFFE | 3 days | Use `grpc.SSLChannelCredentials` |
| mTLS for E2 (ricxappframe handles) | 2 days | RIC provides certs |
| OAuth2 / OIDC on REST + WS (Keycloak or dex) | 4 days | Protect all endpoints except `/health` |
| API key rotation + audit log | 1 day | |
| NetworkPolicies (deny-by-default) | 2 days | Already in Helm chart |
| Secrets via External Secrets Operator (Vault/AWS Secrets Manager) | 2 days | |
| **Total** | **14 days** | |

---

## Phase 6: Observability & Operations (Weeks 8-12)

### 6.1 Structured Logging + Tracing
| Sub-task | Effort |
|----------|--------|
| JSON logging (structlog) with correlation IDs | 2 days |
| OpenTelemetry instrumentation (FastAPI, gRPC, Redis, E2) | 3 days |
| Jaeger/Tempo integration | 1 day |
| **Total** | **6 days** |

### 6.2 Alerting Rules (PrometheusRule)
| Alert | Expression | Severity |
|-------|------------|----------|
| `AstraAnomalyRateHigh` | `rate(astra_anomalies_total[5m]) > 0.1` | warning |
| `AstraHealingFailure` | `rate(astra_healing_failed_total[5m]) > 0` | critical |
| `AstraForecastDrift` | `astra_forecast_confidence < 0.5` | warning |
| `AstraModelMSERegression` | `astra_model_mse > 1.5 * astra_model_mse_baseline` | critical |
| `AstraE2ConnectionDown` | `up{job="astra-xapp"} == 0` | critical |
| `AstraRedisDown` | `redis_up == 0` | critical |
| **Total** | | **3 days** |

---

## Phase 7: Integration Testing (Weeks 10-16)

| Test | Environment | Effort |
|------|-------------|--------|
| Unit tests (existing + new) | GitHub Actions | 5 days |
| Contract tests: E2 control encode/decode | Mock RIC | 3 days |
| Contract tests: A1 policy apply/withdraw | Mock Non-RT RIC | 3 days |
| End-to-end: KPI stream → anomaly → heal (simulated RAN) | ColO-RAN / e2sim | 5 days |
| End-to-end: Preemptive forecast → prevention | ColO-RAN | 3 days |
| Chaos: xApp restart mid-healing (state recovery) | k8s + Litmus | 2 days |
| Load: 100 cells × 1Hz KPIs (resource profiling) | Staging k8s | 3 days |
| **Total** | | **24 days** |

---

## Summary Timeline

| Phase | Weeks | Critical Path |
|-------|-------|---------------|
| 1. Infrastructure | 1-4 | Helm chart → CI/CD |
| 2. E2 Integration | 3-8 | **Real E2 client (16.5 days)** |
| 3. Persistence | 5-8 | Redis LiveState |
| 4. Model Governance | 6-10 | MLflow + drift detection |
| 5. Security | 7-10 | mTLS + OAuth2 |
| 6. Observability | 8-12 | Logging + alerts |
| 7. Integration Test | 10-16 | **E2E with real RIC** |

**Total Calendar Time: ~16 weeks (4 months)**  
**Critical Path:** E2 client → Helm deploy → E2E test with real near-RT RIC

---

## Quick Wins (Do First, < 1 Week Each)

1. ✅ **Helm chart scaffold** — enables k8s deploy immediately
2. ✅ **Redis LiveState** — survives restarts, enables multi-replica
3. ✅ **Structured logging + correlation IDs** — debuggability
4. ✅ **Prometheus alerts** — operational visibility
5. ✅ **MLflow model loading** — versioned models without code changes

---

## Appendix: File Touch Map

| Phase | Files to Create | Files to Modify |
|-------|-----------------|-----------------|
| 1.1 Helm | `helm/astra-xapp/` (15+ files) | — |
| 1.2 CI/CD | `.github/workflows/` (3 files) | `Dockerfile*` |
| 2.1 E2 | `xapp/healing/e2_rc_client_real.py` | `xapp/healing/action_engine.py` (import) |
| 2.2 A1 | `xapp/innovations/a1_policy/mediator.py` | `xapp/api/a1_api.py`, `xapp/main.py` |
| 3.1 Redis | `xapp/persistence/redis_client.py`, `xapp/persistence/state_redis.py` | `xapp/state.py` (replace impl) |
| 3.2 PG | `xapp/persistence/audit.py`, `alembic/` | — |
| 4.1 MLflow | `training/mlflow_utils.py` | `training/train_*.py`, `xapp/main.py` (model load) |
| 4.2 EWC | `xapp/innovations/continual/trainer.py` | `xapp/model/anomaly_detector.py` |
| 5 Security | `helm/astra-xapp/templates/networkpolicy.yaml`, `security/` | `xapp/main.py` (auth middleware) |
| 6 Observability | `xapp/observability/` | `xapp/main.py`, `xapp/healing/*.py` |
| 7 Tests | `tests/integration/`, `tests/contract/` | — |