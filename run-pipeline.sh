#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "========================================"
echo "Boxy Pipeline: Phase 1 → Phase 2 → Phase 3 → Phase 4"
echo "========================================"

echo ""
echo "[pipeline] Running Phase 1..."
bash "$SCRIPT_DIR/Phase1/run.sh"

echo ""
echo "[pipeline] Running Phase 2..."
bash "$SCRIPT_DIR/Phase2/run.sh"

echo ""
echo "[pipeline] Running Phase 3..."
bash "$SCRIPT_DIR/Phase3/run.sh"

echo ""
echo "[pipeline] Running Phase 4..."
bash "$SCRIPT_DIR/Phase4/run.sh"

echo ""
echo "========================================"
echo "Pipeline complete."
echo "========================================"
