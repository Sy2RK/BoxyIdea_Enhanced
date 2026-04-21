#!/usr/bin/env python3
"""Merge outputs from multiple scrapers into a single scraped_posts.json."""

import argparse
import json
import os


def main():
    parser = argparse.ArgumentParser(description="Merge scraper outputs into one JSON")
    parser.add_argument("--output", required=True, help="Path to write merged JSON")
    parser.add_argument("sources", nargs="+", help="Paths to scraper output JSON files")
    args = parser.parse_args()

    output = {}
    for path in args.sources:
        if not os.path.exists(path):
            print(f"[warn] Source file not found, skipping: {path}", file=sys.stderr)
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        source = data.pop("source", os.path.basename(path).replace(".json", ""))
        output[source] = data

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"[merge] Merged {len(output)} sources -> {args.output}")


if __name__ == "__main__":
    import sys
    main()
