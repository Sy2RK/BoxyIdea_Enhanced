#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[run] Starting Phase 4: Push top 3 levels to Feishu..."
python3 "$SCRIPT_DIR/push_feishu.py" --input "$SCRIPT_DIR/../Phase3/output/Phase3_result.txt"
echo "[run] Phase 4 complete."
