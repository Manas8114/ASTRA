#!/bin/bash
set -e
curl -s -X POST "http://localhost:8000/inject/HIGH_LATENCY"
echo "High latency injected. ASTRA should declare after consecutive anomalous windows."
