# ASTRA & CR²E — Causal 5G RAN Self-Healing

ASTRA and CR²E together form a complete O-RAN self-healing closed loop:
- **ASTRA (Detect & Predict)**: Detects KPI anomalies (LSTM Autoencoder), extracts feature attribution, models preemptive risk paths, simulates healing outcomes (M/M/1 Digital Twin), and applies actions (E2 RC).
- **CR²E (Explain & Prescribe)**: Answers *why* anomalies occur and *what* is the minimal fix. It runs causal discovery (PC/NOTEARS background knowledge constrained by 3GPP/O-RAN domain physics) and causal estimation (DoWhy + EconML LinearDML) to isolate root causes and prescribe precise counterfactual interventions.

All events are streamed to a consolidated NOC React dashboard.

## Recovery Performance (MTTR)

| Metric | Value | Context |
|--------|-------|---------|
| **Manual NOC Baseline** | 2–3 days | Full corporate resolution loop: engineer spots error → ticket raised → logs analysed → fix tested → parameters pushed manually |
| **Production SLA Target** | < 2 minutes | End-to-end target for ASTRA in a live multi-cell O-RAN deployment |
| **Prototype Loop Speed** | ~11.4 seconds | Measured machine-to-machine loop in demo mode: detect → classify → DT simulate → E2 heal |

## Key Innovations

- **Explainable AI (XAI)**: Per-feature reconstruction error attribution with natural-language explanations. The dashboard shows a real-time bar chart of exactly which KPI caused the anomaly (e.g., "handover success contributed 42% of anomaly score").
- **M/M/1 Queuing Digital Twin**: The Digital Twin uses an M/M/1 queuing model where each cell is modelled as a single-server queue. Healing actions modify the arrival rate (λ) and service rate (μ) to project ρ (utilisation), Lq (queue length), latency, throughput, and BLER.
- **Multi-Cell Coordination**: When ASTRA heals a cell, it broadcasts an advisory to neighboring cells via the X2/Xn-style topology graph, allowing them to proactively adjust thresholds before the traffic wave shifts over.
- **Elastic Weight Consolidation (EWC)**: Prevents catastrophic forgetting when the LSTM autoencoder fine-tunes on new network conditions by penalising deviations from Fisher-important weights.
- **Preemptive Healing**: A ForecastHead predicts 60-second KPI risk trajectories, enabling pre-emptive action before anomalies materialise.

## Documentation

For an in-depth understanding of ASTRA's mechanics, please review the following technical documents:
- [High-Level Architecture](docs/ARCHITECTURE.md): An overview of the xApp pipeline and components.
- [Sequence & Data Flows](docs/DATA_FLOW.md): Detailed Mermaid sequence diagrams for reactive and preemptive healing.
- [Component Deep Dive](docs/DEEP_DIVE.md): Technical details on the ML models, Digital Twin, and Action Engine.

## Run Demo Mode

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r xapp\requirements.txt
python training\generate_normal_data.py
python training\train_lstm.py
python -m xapp.main
```

In another terminal:

```powershell
cd dashboard
npm install
npm run dev
```

Open `http://localhost:3000`.

## Modes

Demo mode:

```env
DEV_MODE=true
KPI_SOURCE=dev
ASTRA_MODE=demo
```

Open5GS file/lab mode:

```env
DEV_MODE=false
KPI_SOURCE=open5gs_file
OPEN5GS_KPI_JSONL=data/open5gs_kpis.jsonl
```

Prometheus/lab mode:

```env
DEV_MODE=false
KPI_SOURCE=prometheus
PROMETHEUS_URL=http://prometheus:9090
```

Set `ASTRA_CONTROL_API_KEY` to protect `/policy` and `/inject/*`.

## Docker

Demo:

```powershell
docker compose up --build
```

Lab support profile:

```powershell
docker compose --profile lab up --build
```

The lab profile includes MongoDB, an Open5GS container, a KPI exporter,
Prometheus, Grafana, a gRPC twin service, and a FlexRIC placeholder. FlexRIC and
true E2 node SCTP wiring still depend on your local telecom lab build.

## Implemented

- **ASTRA Core**: Shared backend state for KPI, anomaly, twin, forecast, and healing events.
- **NOC Dashboard**: REST/WebSocket backend and React NOC dashboard with real-time anomaly timeline.
- **LSTM Autoencoder**: LSTM anomaly detector plus real training script.
- **Statistical Fallback**: Statistical detector fallback when no model checkpoint exists.
- **KPI Adapters**: Prometheus and Open5GS JSONL KPI adapters.
- **M/M/1 Queuing Digital Twin**: Queue-based prediction before every healing action.
- **Preemptive Healing**: Forecasting head path using forecasted KPI risk.
- **XAI Reconstruction**: Per-feature attribution with dashboard bar chart.
- **Multi-Cell Coordination**: Topology-based neighbor advisory broadcast.
- **EWC Continual Learning**: Prevent catastrophic forgetting during fine-tuning.
- **CR²E — Causal Root-Cause Engine**: Domain-constrained PC/NOTEARS causal discovery, DoWhy+LinearDML effect estimation with refutations, root-cause ranking, counterfactual prescriptions, and natural language explanations (Ollama / template fallback).
- **Dashboard Integration**: Root Cause panel added directly into the ASTRA React dashboard to stream CR²E reports.
- **Docker Integration**: `cr2e` and `mlflow` services added to Compose for experiment and model snapshot tracking.
- **Automated Tests**: Unit and integration test suites validating domain DAG constraint enforcement, ranker robustness, DoWhy estimation correctness, and counterfactual delta consistency.


## RIC Framework

ASTRA targets the **FlexRIC** Near-RT RIC platform. All E2 interface interactions
(KPM subscription, RC control) use FlexRIC SDKs. The adapter boundaries in
`xapp/ingestion/` and `xapp/healing/e2_rc_client.py` provide clean seams for
integration with the CeNCRA 5G Lab at SRMIST.

## Still Lab Dependent

- True FlexRIC E2 KPM subscription.
- True ASN.1/SCTP E2 RC control against a real E2 node.
- Real gNB/UE traffic generation and Open5GS subscriber/session tuning.

Those are external system integrations, not pure repository code. The project
now has clear adapter boundaries where those lab pieces plug in.

