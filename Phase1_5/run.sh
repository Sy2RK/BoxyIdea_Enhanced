#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[run] Phase 1.5 meme understanding starting..."
python3 "$SCRIPT_DIR/meme_understanding.py" --config "$SCRIPT_DIR/config.json"
echo "[run] Phase 1.5 complete."
