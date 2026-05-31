#!/bin/bash
set -e
docker compose up -d
echo "Dashboard live at http://localhost:3000"
echo "Watch the KPI charts, anomaly timeline, digital twin panel, and healing log."
