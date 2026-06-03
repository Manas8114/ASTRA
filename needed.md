# ASTRA Needed Keys And Values

This file lists the keys, tokens, credentials, and external values needed to run ASTRA in demo, lab, and production-style modes.

## Demo Mode

These can stay empty or use defaults.

```env
DEV_MODE=true
ASTRA_MODE=demo
KPI_SOURCE=dev
ASTRA_CONTROL_API_KEY=
```

No external API key is required for demo mode.

## Dashboard / Control API

Set this if you want to protect dangerous control endpoints like `/policy` and `/inject/*`.

```env
ASTRA_CONTROL_API_KEY=change-this-control-token
```

Use this value as the `x-api-key` header when calling protected endpoints.

## Open5GS / KPI File Mode

Use this when Open5GS or a scraper writes KPI samples to a JSONL file.

```env
DEV_MODE=false
ASTRA_MODE=lab
KPI_SOURCE=open5gs_file
OPEN5GS_HOST=open5gs
OPEN5GS_KPI_JSONL=data/open5gs_kpis.jsonl
OPEN5GS_KPI_PORT=9090
```

Required external value:

```text
Path or mounted volume where Open5GS KPI JSONL samples are written.
```

## Prometheus KPI Mode

Use this when KPI values are available through Prometheus queries.

```env
DEV_MODE=false
ASTRA_MODE=lab
KPI_SOURCE=prometheus
PROMETHEUS_URL=http://prometheus:9090
```

Prometheus query keys:

```env
PROM_QUERY_DL_THROUGHPUT_MBPS=astra_dl_throughput_mbps
PROM_QUERY_LATENCY_MS=astra_latency_ms
PROM_QUERY_BLER_PCT=astra_bler_pct
PROM_QUERY_RSRP_DBM=astra_rsrp_dbm
PROM_QUERY_HANDOVER_SUCCESS_RATE=astra_handover_success_rate
PROM_QUERY_SLICE_UTILISATION_PCT=astra_slice_utilisation_pct
```

## FlexRIC / E2 Interface

Needed for real RIC integration.

```env
FLEXRIC_HOST=flexric
FLEXRIC_E2_PORT=36421
```

External values still needed from your lab:

```text
FlexRIC build/runtime path
E2 node host/IP
E2 node SCTP port
RAN function ID for KPM
RAN function ID for RC
KPM service model version
RC service model version
Cell/global gNB ID mapping
```

## A1 Policy API

Use this when Non-RT RIC or policy tooling pushes policies.

```env
A1_API_KEY=change-this-a1-token
```

In production mode, A1 policy requests must provide this key.

## Digital Twin Service

For local demo, the in-process Python twin is enough. For gRPC twin mode:

```env
TWIN_SERVICE_HOST=localhost
TWIN_SERVICE_PORT=50051
DT_APPROVAL_THRESHOLD=0.20
```

## Redis / Persistence

Optional, used for production-style event persistence.

```env
REDIS_HOST=localhost
REDIS_PORT=6379
ASTRA_EVENT_DB=data/astra_events.db
ASTRA_DISABLE_EVENT_DB=false
```

## Model Artifacts

These are files, not secret keys, but they are required for full ML mode.

```env
MODEL_PATH=./xapp/model/saved_models/lstm_ae_best.pt
SCALER_PATH=./training/data/scaler.pkl
THRESHOLD_PATH=./xapp/model/saved_models/threshold.json
FORECAST_MODEL_PATH=./xapp/model/saved_models/forecast_head.pt
ONNX_MODEL_PATH=./xapp/model/saved_models/lstm_ae_best.onnx
```

Generate them with:

```powershell
python training\generate_normal_data.py
python training\train_lstm.py
python training\train_forecast.py
python training\export_onnx.py
```

## Healing Safety Values

```env
CONSECUTIVE_ANOMALY_TRIGGER=5
ANOMALY_THRESHOLD_SIGMA=3.0
HEALING_COOLDOWN_SECONDS=30
DT_APPROVAL_THRESHOLD=0.20
EWC_LAMBDA=1000
```

## Federated Learning

Only needed if you run a federated aggregator.

```env
FEDERATED_AGGREGATOR_URL=http://localhost:8888
```

External value needed:

```text
Aggregator server URL and authentication token if your aggregator requires one.
```

## Docker Ports

```env
ASTRA_API_PORT=8000
ASTRA_WS_PORT=8765
DASHBOARD_PORT=3000
PROMETHEUS_PORT=9091
GRAFANA_PORT=3001
OPEN5GS_KPI_PORT=9090
FLEXRIC_E2_PORT=36421
```

## Minimum Keys To Fill For A Serious Lab Demo

```env
ASTRA_CONTROL_API_KEY=your-control-token
KPI_SOURCE=open5gs_file
OPEN5GS_KPI_JSONL=data/open5gs_kpis.jsonl
FLEXRIC_HOST=your-flexric-host
FLEXRIC_E2_PORT=36421
A1_API_KEY=your-a1-token
```

## Not Needed

ASTRA does not require cloud API keys for the default demo. It can run locally with generated/trained model artifacts and local KPI streams.
