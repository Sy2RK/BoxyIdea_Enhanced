#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[run] Starting Phase 3: Filter & Select..."
python3 "$SCRIPT_DIR/filter_and_select.py" --config "$SCRIPT_DIR/config.json"
echo "[run] Phase 3 complete."
