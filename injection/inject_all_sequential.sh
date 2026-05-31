#!/bin/bash
set -e
for type in CONGESTION HIGH_LATENCY PACKET_LOSS SLICE_OVERFLOW; do
  curl -s -X POST "http://localhost:8000/inject/${type}" >/dev/null
  echo "${type} injection marker sent"
  sleep 180
done
