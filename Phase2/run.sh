#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[run] Phase 2 pipeline starting..."

# Step 1: Update hint from Feishu wiki
echo "[run] Fetching latest hint from Feishu..."
python3 "$SCRIPT_DIR/fetch_feishu_hint.py"

# Step 2: Run synthesizer
echo "[run] Running synthesizer..."
python3 "$SCRIPT_DIR/synthesizer.py"

echo "[run] Phase 2 complete."
