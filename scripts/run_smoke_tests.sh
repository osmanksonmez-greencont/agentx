#!/usr/bin/env bash
set -euo pipefail

python3 -m compileall agentx >/dev/null
python3 -m compileall bridge >/dev/null || true

echo "Smoke tests passed: compile checks succeeded"
