# ASTRA

ASTRA is a local O-RAN xApp prototype for autonomous 5G RAN self-healing. The current implementation is wired around a single live backend state so KPI changes propagate through anomaly detection, classification, digital twin simulation, healing decisions, REST APIs, WebSocket events, and the dashboard.

## Run Locally

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r xapp\requirements.txt
.\.venv\Scripts\python training\generate_normal_data.py
.\.venv\Scripts\python training\train_lstm.py
.\.venv\Scripts\python -m xapp.main
```

Dashboard:

```powershell
cd dashboard
npm install
npm run dev
```

Open `http://localhost:3000`.

## Production Data Rule

The xApp refuses to fabricate live KPIs unless `DEV_MODE=true`. In production, connect an E2/Open5GS KPI source and push real KPM vectors into the same `LiveState` path used by the API and WebSocket server.
