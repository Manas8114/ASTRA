#!/bin/bash
set -e
curl -s -X POST "http://localhost:8000/inject/CONGESTION"
echo "Congestion injected. ASTRA should declare after consecutive anomalous windows."
