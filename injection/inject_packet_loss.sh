#!/bin/bash
set -e
curl -s -X POST "http://localhost:8000/inject/PACKET_LOSS"
echo "Packet loss injected. ASTRA should declare after consecutive anomalous windows."
