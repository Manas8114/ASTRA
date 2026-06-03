#!/bin/bash
set -e
curl -s -X POST "http://localhost:8000/inject/SLICE_OVERFLOW"
echo "Slice overflow injected. ASTRA should declare after consecutive anomalous windows."
