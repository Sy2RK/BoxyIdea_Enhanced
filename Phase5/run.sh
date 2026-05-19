#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[run] Starting Phase 5: Visualize level designs..."
python3 "$SCRIPT_DIR/visualize.py" --config "$SCRIPT_DIR/config.json"
echo "[run] Phase 5 complete."
