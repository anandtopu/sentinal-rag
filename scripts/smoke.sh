#!/usr/bin/env bash
set -euo pipefail
curl -fsS http://localhost:8000/ | grep -q '"status":"ok"'
curl -fsS http://localhost:8000/health | grep -q '"status":"ok"'
curl -fsS http://localhost:8000/ready | grep -q '"status":"ready"'
echo "Smoke test passed"
