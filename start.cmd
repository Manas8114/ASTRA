@echo off
setlocal EnableDelayedExpansion

title ASTRA — Quick Start
color 0A

echo.
echo  ███████╗ █████╗ ███████╗████████╗██████╗  █████╗
echo  ██╔══██║██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██╔══██╗
echo  ███████║███████║███████╗   ██║   ██████╔╝███████║
echo  ██╔══██║██╔══██║╚════██║   ██║   ██╔══██╗██╔══██║
echo  ██║  ██║██║  ██║███████║   ██║   ██║  ██║██║  ██║
echo  ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝
echo.
echo  Autonomous 5G RAN Self-Healing  ^|  O-RAN xApp Demo
echo  ═══════════════════════════════════════════════════
echo.

:: ── Check Docker is running ──────────────────────────────────────────────────
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Docker Desktop is not running.
    echo  Please start Docker Desktop and try again.
    echo.
    pause
    exit /b 1
)
echo  [OK] Docker is running.

:: ── Create .env from example if missing ─────────────────────────────────────
if not exist ".env" (
    echo  [INFO] No .env found — creating from .env.example with demo defaults...
    copy ".env.example" ".env" >nul
    echo DEV_MODE=true>> .env
    echo KPI_SOURCE=dev>> .env
    echo ASTRA_MODE=demo>> .env
    echo CELL_ID=cell_001>> .env
    echo CONSECUTIVE_ANOMALY_TRIGGER=5>> .env
    echo DT_APPROVAL_THRESHOLD=0.20>> .env
    echo HEALING_COOLDOWN_SECONDS=30>> .env
    echo EWC_LAMBDA=1000>> .env
    echo LOG_LEVEL=INFO>> .env
    echo  [OK] .env created with demo defaults.
) else (
    echo  [OK] .env found.
)

:: ── Create required data directories ────────────────────────────────────────
if not exist "data" mkdir data
if not exist "xapp\model\saved_models" mkdir xapp\model\saved_models
if not exist "training\data" mkdir training\data
echo  [OK] Data directories ready.

:: ── Pull / build images ──────────────────────────────────────────────────────
echo.
echo  [BUILD] Building Docker images (first run trains the ML model — ~3-5 min)...
echo  This is a one-time operation. Subsequent starts take ^<30 seconds.
echo.

docker compose build --parallel
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Docker build failed. Check the output above.
    pause
    exit /b 1
)
echo.
echo  [OK] Images built successfully.

:: ── Start the stack ──────────────────────────────────────────────────────────
echo.
echo  [START] Starting ASTRA stack...
docker compose up -d
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Failed to start containers.
    pause
    exit /b 1
)

:: ── Wait for health check ────────────────────────────────────────────────────
echo.
echo  [WAIT] Waiting for ASTRA xApp to be healthy...
set /a attempts=0
:healthloop
set /a attempts+=1
if !attempts! gtr 30 (
    echo  [WARN] Health check timed out after 30 attempts. App may still be starting.
    goto :open
)
docker inspect --format="{{.State.Health.Status}}" astra-xapp 2>nul | findstr "healthy" >nul
if %errorlevel% neq 0 (
    timeout /t 3 /nobreak >nul
    set /p dummy=. <nul
    goto :healthloop
)
echo.
echo  [OK] ASTRA xApp is healthy!

:open
:: ── Print URLs ───────────────────────────────────────────────────────────────
echo.
echo  ╔═══════════════════════════════════════════════════════╗
echo  ║              ASTRA IS RUNNING                         ║
echo  ╠═══════════════════════════════════════════════════════╣
echo  ║  NOC Dashboard     →  http://localhost:3000           ║
echo  ║  xApp REST API     →  http://localhost:8000           ║
echo  ║  API Docs (Swagger)→  http://localhost:8000/docs      ║
echo  ║  WebSocket Feed    →  ws://localhost:8000/ws          ║
echo  ║  Digital Twin gRPC →  localhost:50051                 ║
echo  ╚═══════════════════════════════════════════════════════╝
echo.
echo  To inject a fault for demo:
echo    docker exec astra-xapp python -m xapp.ingestion.kpi_adapters
echo    OR use the NOC Controls panel on the dashboard.
echo.
echo  To stop everything:   stop.cmd
echo  To view logs:         docker compose logs -f
echo.

:: ── Open browser ─────────────────────────────────────────────────────────────
echo  Opening NOC dashboard in browser...
timeout /t 3 /nobreak >nul
start http://localhost:3000

echo.
echo  Press any key to tail logs (Ctrl+C to exit logs without stopping)...
pause >nul
docker compose logs -f

endlocal
