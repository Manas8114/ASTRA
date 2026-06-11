# ASTRA: Complete Setup & Execution Guide

This document outlines everything you need to know, acquire, and configure to completely run the ASTRA (Autonomous Self-healing Telecom Radio Analytics) O-RAN xApp from local development up to a Kubernetes cluster deployment.

---

## 1. What You Need (Prerequisites)

### A. Local Development & Testing
To run and test the project locally without an O-RAN testbed:
* **Python 3.13+** (Required for Modern typing and async capabilities)
* **uv** (The extremely fast Python package installer and resolver used in this project)
* **Git** (For version control)
* **Docker Desktop** (If you want to build and test container images locally)

### B. Production Deployment (Kubernetes)
To deploy this inside a simulated or real telco environment:
* **Kubernetes Cluster** (Minikube, k3d, kind, or a managed cloud K8s cluster)
* **Helm 3** (To deploy the `astra-xapp` chart)
* **O-RAN near-RT RIC Testbed** (Optional, e.g. ColO-RAN, OSC RIC, or a vendor RIC environment to natively use `ricxappframe` and `e2sm_rc`)

---

## 2. How to Run Locally (Demo/Dev Mode)

In Dev Mode, ASTRA runs a mock Digital Twin and stubs out the actual E2AP control interface, allowing you to view the Dashboard and test ML inferences without a real telecom network.

### Step 1: Install Dependencies
We use `uv` for dependency management.
```bash
# From the root directory:
uv sync --frozen
```

### Step 2: Start the Digital Twin gRPC Service
ASTRA relies on an M/M/1 queueing simulator to validate pre-emptive healing actions before applying them.
```bash
# Open a new terminal
cd twin-service
uv run python server.py
# Expected output: Digital Twin gRPC Server (M/M/1 Engine) started on port 50051
```

### Step 3: Start the xApp Backend
```bash
# Open a second terminal
# Set required environment variables for local testing
export DEV_MODE=true
export ASTRA_MODE=demo
export TWIN_SERVICE_URL=localhost:50051

# Start the FastAPI server
uv run python -m xapp.main
# Expected output: Uvicorn running on http://0.0.0.0:8000
```
*Note: On Windows PowerShell, use `$env:DEV_MODE="true"` instead of `export`.*

### Step 4: Run the Test Suite
Ensure all integrations are working correctly:
```bash
uv run pytest tests/
```

---

## 3. How to Run in Production (Kubernetes/Helm)

In Production Mode, ASTRA is deployed as a microservices architecture inside Kubernetes. It consists of the core xApp, the Digital Twin, and a Redis instance for rate-limiting.

### Step 1: Build the Docker Images
```bash
# Build the core xApp
docker build -t astra-xapp:dev -f xapp/Dockerfile .

# Build the Twin Service
docker build -t astra-twin:dev -f twin-service/Dockerfile twin-service/
```

### Step 2: Deploy using Helm
The Helm chart provisions Deployments, Services, ConfigMaps, and an Ingress.
```bash
# Lint the chart first to ensure validity
helm lint helm/astra-xapp -f helm/astra-xapp/values-dev.yaml

# Install the chart into your cluster
helm upgrade --install astra-deploy helm/astra-xapp -f helm/astra-xapp/values-dev.yaml
```

### Step 3: Verify the Deployment
```bash
kubectl get pods
# You should see:
# astra-deploy-astra-xapp-xxxx (Running)
# astra-deploy-twin-xxxx       (Running)
# astra-deploy-redis-0         (Running)
```

---

## 4. Key Environment Variables & Configuration

When deploying ASTRA, these variables dictate its behaviour. In Kubernetes, these are managed automatically via the `values.yaml` and `ConfigMap`, but you can override them:

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `ASTRA_MODE` | `demo` | Set to `prod` to enable real E2 client transmission, JWT Auth, and Rate Limiting. |
| `DEV_MODE` | `false` | Set to `true` locally to bypass checking for external Prometheus KPI sources. |
| `ASTRA_CORS_ORIGINS`| *None* | Comma-separated list of allowed dashboard domains (e.g., `http://dashboard.local`). |
| `ASTRA_ADMIN_TOKEN` | *Random* | Bearer token required to use `/policy` and `/inject` REST endpoints. |
| `PREEMPTIVE_CONFIDENCE_GATE` | `0.65` | Minimum forecast confidence (0-1) before an automatic pre-emptive action is triggered. |
| `DT_APPROVAL_THRESHOLD` | `0.20` | Twin must guarantee at least a 20% MSE improvement before allowing an action. |
| `ASTRA_EWC_ENABLED` | `true` | Enables Elastic Weight Consolidation (Continual Learning) so the LSTM remembers past anomalies. |

---

## 5. Model Retraining & Quantization

If you need to update the LSTM Autoencoder with new data or optimize it for edge hardware:

**To retrain the model:**
```bash
# Runs the PyTorch training loop and saves the best model
uv run python training/train_lstm_ae.py
```

**To export and Quantize (INT8) for the Edge RIC:**
```bash
# Converts the .pt model to .onnx and applies INT8 dynamic quantization
uv run python training/export_onnx.py
```
*The resulting `lstm_ae_best_quantized.onnx` is automatically loaded by the xApp in production mode to save power and latency.*
