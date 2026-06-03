@echo off
title ASTRA — Stop

echo.
echo  [STOP] Stopping ASTRA stack...
docker compose down
echo.
echo  [OK] All containers stopped.
echo.
echo  To remove built images too (full clean):
echo    docker compose down --rmi all --volumes
echo.
pause
