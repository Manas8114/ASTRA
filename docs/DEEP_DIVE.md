# ASTRA Component Deep Dive

This document provides a technical deep dive into the three most critical components of the ASTRA architecture: the Machine Learning Pipeline, the Digital Twin, and the Action Engine.

## 1. Machine Learning Pipeline (`xapp.model` & `xapp.prediction`)

The Machine Learning architecture of ASTRA focuses on anomaly detection and time-series forecasting. It is designed to be lightweight enough for near-RT RIC deployments.

### LSTM Autoencoder (`lstm_autoencoder.py`)
- **Architecture:** An LSTM-based Sequence-to-Sequence autoencoder.
- **Input:** Sequences of `KPIVector` samples (e.g., shape `[batch, sequence_length, features]`).
- **Function:** Learns the latent representation of "normal" network conditions. During inference, it attempts to reconstruct the input sequence. High reconstruction error indicates an anomaly.
- **Training:** Trained offline or incrementally using PyTorch. Models are saved as `.pt` or exported to `.onnx` for high-performance inference via ONNXRuntime.

### Attention Extractor (`attention_extractor.py`)
- **Function:** When the Anomaly Detector flags an event, the `AttentionExtractor` calculates the feature-wise reconstruction error to find the root cause.
- **Result:** Identifies the "top cause" (e.g., `rsrp_dbm` or `bler_pct`), which the `AnomalyClassifier` maps to a specific `AnomalyType` (e.g., `COVERAGE_HOLE`).

### Forecast Head (`forecast_head.py`)
- **Architecture:** An autoregressive ML prediction model.
- **Function:** Forecasts the future trajectory of KPIs over a configurable horizon (e.g., next 10 seconds).
- **Integration:** Empowers the `PreemptiveHealer` to trigger early interventions before real-world SLA violations occur.

## 2. Digital Twin Simulator (`xapp.digital_twin.twin_simulator`)

Before ASTRA modifies the live network, it must validate its proposed actions to ensure network safety.

- **Purpose:** Acts as a sandbox representing the live 5G cell environment.
- **Process:** The `DigitalTwinSimulator` ingests the current KPI state and a proposed `HealingAction` (e.g., power adjustments, admission control).
- **Simulation:** Uses heuristics (or a secondary ML model) to predict the post-action state. It calculates an `ImpactRiskScore`.
- **Gatekeeper:** If the risk exceeds `DT_APPROVAL_THRESHOLD`, the action is vetoed and recorded in the `healing_log`. Only safe actions are passed to the `E2 RC Client`.

## 3. Healing Action Engine (`xapp.healing.action_engine`)

The decision-making heart of the xApp.

- **Anomaly Mapping:** Uses a deterministic rule-based engine to map an `AnomalyType` to a `HealingAction`. 
  - *Example:* `CONGESTION` -> `ADMISSION_CONTROL` (reject rate = 20%).
  - *Example:* `PACKET_LOSS` -> `POWER_CONTROL` (Tx = +10dB).
- **Cooldown Logic:** Tracks recently executed actions to prevent oscillation or action-spamming (enforced by `HEALING_COOLDOWN_SECONDS`).
- **Actuation:** Defers to the `E2 RC Client` (Radio Control) to encode the action into ASN.1 packets (mocked/simulated in demo mode) and transmit to the underlying E2 Node (gNB).

---

> [!NOTE]
> All components continuously feed telemetry and decisions into `LiveState`, which broadcasts updates via WebSockets to the React NOC Dashboard.
