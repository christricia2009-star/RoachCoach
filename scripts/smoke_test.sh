#!/bin/bash
set -euo pipefail
BASE_URL="${1:-http://localhost:3000}"
echo "Testing ${BASE_URL}/api/health"
curl -fsS "${BASE_URL}/api/health"
echo
echo "Testing ${BASE_URL}/api/radar/status"
curl -fsS "${BASE_URL}/api/radar/status"
echo
echo "Smoke tests passed."
