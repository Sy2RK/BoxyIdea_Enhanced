#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.json"

# Read config
if [ ! -f "$CONFIG_FILE" ]; then
  echo "[error] config.json not found"
  exit 1
fi

# Extract settings — all paths resolve relative to config.json location
OUTPUT_DIR=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['output_dir'])")
OUTPUT_FILE=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['output_file'])")

# Make output paths absolute relative to this script's directory
ABS_OUTPUT_DIR="$SCRIPT_DIR/$OUTPUT_DIR"
IMAGES_DIR="$ABS_OUTPUT_DIR/images"
mkdir -p "$ABS_OUTPUT_DIR"

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

# Get enabled platforms with their config
PLATFORM_CONFIG=$(python3 -c "
import json, sys
config = json.load(open('$CONFIG_FILE'))
enabled = [p for p in config['platforms'] if p.get('enabled')]
for p in enabled:
    max_posts = p.get('max_posts', '')
    print(p['scraper'], p['name'], max_posts)
")

if [ -z "$PLATFORM_CONFIG" ]; then
  echo "[error] no enabled platforms in config.json"
  exit 1
fi

echo "[run] Starting scrapers..."

# Run each scraper in parallel
while IFS=' ' read -r SCRAPER NAME MAX_POSTS; do
  echo "  launching $NAME ($SCRAPER)..."
  EXTRA_ARGS=""
  if [ -n "$MAX_POSTS" ]; then
    EXTRA_ARGS="--max-posts $MAX_POSTS"
  fi
  IMAGES_DIR="$IMAGES_DIR" python3 "$SCRIPT_DIR/$SCRAPER" \
    --output "$TMP_DIR/${NAME}.json" $EXTRA_ARGS &
done <<< "$PLATFORM_CONFIG"

# Wait for all background jobs
wait

echo "[run] All scrapers finished. Merging..."

python3 "$SCRIPT_DIR/merge_sources.py" \
  --output "$ABS_OUTPUT_DIR/$OUTPUT_FILE" \
  "$TMP_DIR"/*.json
