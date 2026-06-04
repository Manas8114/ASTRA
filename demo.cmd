@echo off
setlocal EnableDelayedExpansion

title ASTRA — LIVE DEMO
color 0A

echo.
echo  ███████╗ █████╗ ███████╗████████╗██████╗  █████╗
echo  ██╔══██║██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██╔══██╗
echo  ███████║███████║███████╗   ██║   ██████╔╝███████║
echo  ██╔══██║██╔══██║╚════██║   ██║   ██╔══██╗██╔══██║
echo  ██║  ██║██║  ██║███████║   ██║   ██║  ██║██║  ██║
echo  ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝
echo.
echo  DEMO MODE — Autonomous 5G RAN Self-Healing xApp
echo  ═══════════════════════════════════════════════════
echo.

:: ── Pre-flight: Docker check ─────────────────────────────────────────────────
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Docker Desktop is not running. Please start it and retry.
    pause
    exit /b 1
)
echo  [OK] Docker is running.

:: ── Force demo environment ────────────────────────────────────────────────────
echo  [INFO] Configuring demo environment...
(
echo CELL_ID=cell_001
echo ASTRA_API_PORT=8000
echo DASHBOARD_PORT=3000
echo DEV_MODE=true
echo KPI_SOURCE=dev
echo ASTRA_MODE=demo
echo CONSECUTIVE_ANOMALY_TRIGGER=5
echo DT_APPROVAL_THRESHOLD=0.20
echo HEALING_COOLDOWN_SECONDS=30
echo EWC_LAMBDA=1000
echo LOG_LEVEL=INFO
echo ANOMALY_THRESHOLD_SIGMA=3.0
echo KPI_POLL_SECONDS=1
echo ASTRA_EVENT_DB=data/astra_events.db
echo ASTRA_CONTROL_API_KEY=
echo PROMETHEUS_URL=http://prometheus:9090
echo OPEN5GS_KPI_JSONL=data/open5gs_kpis.jsonl
echo FEDERATED_AGGREGATOR_URL=http://localhost:8888
echo TOPOLOGY_CONFIG=./topology.json
echo MODEL_PATH=./xapp/model/saved_models/lstm_ae_best.pt
echo SCALER_PATH=./training/data/scaler.pkl
) > .env
echo  [OK] .env set to demo defaults.

:: ── Create required directories ───────────────────────────────────────────────
if not exist "data"                     mkdir data
if not exist "xapp\model\saved_models"  mkdir xapp\model\saved_models
if not exist "training\data"            mkdir training\data
echo  [OK] Data directories ready.

:: ── Build images ──────────────────────────────────────────────────────────────
echo.
echo  [BUILD] Building images (first run ~3-5 min for ML training)...
docker compose build --parallel
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Build failed. Check output above.
    pause
    exit /b 1
)
echo  [OK] Images built.

:: ── Tear down any existing stack cleanly ─────────────────────────────────────
echo.
echo  [RESET] Stopping any running ASTRA containers...
docker compose down --remove-orphans >nul 2>&1
echo  [OK] Clean slate.

:: ── Start the full stack ──────────────────────────────────────────────────────
echo.
echo  [START] Launching ASTRA demo stack...
docker compose up -d
if %errorlevel% neq 0 (
    echo  [ERROR] Failed to start containers.
    pause
    exit /b 1
)

:: ── Wait for xApp health ──────────────────────────────────────────────────────
echo.
echo  [WAIT] Waiting for xApp to be ready (up to 90 seconds)...
set /a attempts=0
:healthloop
set /a attempts+=1
if !attempts! gtr 30 (
    echo  [WARN] Health check timed out — the app may still be starting.
    goto :inject
)
docker inspect --format="{{.State.Health.Status}}" astra-xapp 2>nul | findstr "healthy" >nul
if %errorlevel% neq 0 (
    timeout /t 3 /nobreak >nul
    <nul set /p "=."
    goto :healthloop
)
echo.
echo  [OK] xApp is healthy!

:: ── Auto-inject demo anomaly after a short pause ─────────────────────────────
:inject
echo.
echo  [DEMO] Injecting HIGH_LOAD anomaly in 15 seconds...
echo         (Watch the NOC Dashboard for the detection and healing sequence)
echo.
timeout /t 15 /nobreak >nul

:: Try to inject — curl preferred, fall back to PowerShell
where curl >nul 2>&1
if %errorlevel% equ 0 (
    curl -s -X POST "http://localhost:8000/inject/HIGH_LOAD" -o nul
) else (
    powershell -Command "Invoke-WebRequest -Uri 'http://localhost:8000/inject/HIGH_LOAD' -Method POST -UseBasicParsing | Out-Null" 2>nul
)
echo  [INJECTED] HIGH_LOAD anomaly fired — watch the dashboard!

:: ── Print live URLs ───────────────────────────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║              ASTRA DEMO IS LIVE                      ║
echo  ╠══════════════════════════════════════════════════════╣
echo  ║  NOC Dashboard      →  http://localhost:3000         ║
echo  ║  xApp REST API      →  http://localhost:8000         ║
echo  ║  Swagger / API Docs →  http://localhost:8000/docs    ║
echo  ║  WebSocket Feed     →  ws://localhost:8000/ws        ║
echo  ║  Digital Twin gRPC  →  localhost:50051               ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
echo  INJECT MORE ANOMALIES:
echo    HIGH_LOAD:      curl -X POST http://localhost:8000/inject/HIGH_LOAD
echo    POOR_SIGNAL:    curl -X POST http://localhost:8000/inject/POOR_SIGNAL
echo    HANDOVER_STORM: curl -X POST http://localhost:8000/inject/HANDOVER_STORM
echo    SLICE_OVERLOAD: curl -X POST http://localhost:8000/inject/SLICE_OVERLOAD
echo.
echo  STOP:  stop.cmd
echo  LOGS:  docker compose logs -f
echo.

:: ── Open dashboard ────────────────────────────────────────────────────────────
echo  Opening NOC Dashboard...
timeout /t 2 /nobreak >nul
start http://localhost:3000

echo.
echo  Press any key to tail live logs (Ctrl+C exits logs without stopping)...
pause >nul
docker compose logs -f

endlocal
