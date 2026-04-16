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

# Get enabled platforms
PLATFORM_COUNT=$(python3 -c "
import json, sys
config = json.load(open('$CONFIG_FILE'))
enabled = [p for p in config['platforms'] if p.get('enabled')]
for p in enabled:
    print(p['scraper'], p['name'])
")

if [ -z "$PLATFORM_COUNT" ]; then
  echo "[error] no enabled platforms in config.json"
  exit 1
fi

echo "[run] Starting scrapers..."

# Run each scraper in parallel
while IFS=' ' read -r SCRAPER NAME; do
  echo "  launching $NAME ($SCRAPER)..."
  IMAGES_DIR="$IMAGES_DIR" python3 "$SCRIPT_DIR/$SCRAPER" \
    --output "$TMP_DIR/${NAME}.json" &
done <<< "$PLATFORM_COUNT"

# Wait for all background jobs
wait

echo "[run] All scrapers finished. Merging..."

# Merge all JSON files into one
MERGE_SCRIPT="
import json, glob, os

output = {}
for path in sorted(glob.glob('$TMP_DIR/*.json')):
    with open(path) as f:
        data = json.load(f)
    source = data.pop('source', os.path.basename(path).replace('.json', ''))
    output[source] = data

out_path = os.path.join('$ABS_OUTPUT_DIR', '$OUTPUT_FILE')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f'[run] Merged {len(output)} sources -> {out_path}')
"

python3 -c "$MERGE_SCRIPT"
