#!/usr/bin/env python3
"""Phase1 adapter for reddit-rader-AInews RapidAPI reddit34 scraper."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path


SOURCE_NAME = "reddit_rapidapi_memes"
DEFAULT_SUBREDDIT = "memes"
DEFAULT_TOP_TIME = "day"
DEFAULT_SORT = "hot"
DEFAULT_FETCH_LIMIT = 30
DEFAULT_MAX_POSTS = 10
DEFAULT_MIN_SCORE = 500
DEFAULT_MIN_UPVOTE_RATIO = 0.8
DEFAULT_SELECTION_MODE = "top_first"
MAX_RAPIDAPI_KEYS = 20
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

NODE_RUNNER = r"""
const fs = require('fs');
const path = require('path');
const { RedditScraper } = require('./src/scraper');

function asBool(value) {
  return ['1', 'true', 'yes', 'y', 'on'].includes(String(value || '').toLowerCase());
}

(async () => {
  const subreddit = process.env.REDDIT_RAPIDAPI_SUBREDDIT || process.env.REDDIT_SUBREDDIT || 'memes';
  const fetchLimit = Number.parseInt(process.env.REDDIT_RAPIDAPI_FETCH_LIMIT || '30', 10);
  const requestDelayMs = Number.parseInt(process.env.REDDIT_RAPIDAPI_REQUEST_DELAY_MS || '350', 10);
  const subredditSort = process.env.REDDIT_RAPIDAPI_SORT || 'hot';
  const subredditTopTime = process.env.REDDIT_RAPIDAPI_TOP_TIME || 'day';

  const scraper = new RedditScraper({
    forcePublicReddit: asBool(process.env.REDDIT_USE_PUBLIC),
    rapidApiKey: process.env.RAPIDAPI_KEY || '',
    rapidApiHost: process.env.RAPIDAPI_HOST || 'reddit34.p.rapidapi.com',
    redditUserAgent: process.env.REDDIT_USER_AGENT || 'boxy-meme-pipeline/rapidapi-adapter',
    defaultQueries: [],
    resultsPerKeyword: Number.isFinite(fetchLimit) && fetchLimit > 0 ? fetchLimit : 30,
    requestDelayMs: Number.isFinite(requestDelayMs) && requestDelayMs >= 0 ? requestDelayMs : 350,
    dataDir: process.env.BOXY_REDDIT_DATA_DIR,
    filters: { minPlayCount: 0, minDiggCount: 0, minShareCount: 0 }
  });

  const result = await scraper.scrape([], {
    subreddits: [subreddit],
    popularSorts: [],
    subredditSort,
    subredditTopTime
  });

  fs.writeFileSync(process.env.BOXY_REDDIT_RAW_OUTPUT, JSON.stringify(result.data, null, 2), 'utf-8');
})().catch(error => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
"""


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def phase1_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def scraper_dir() -> Path:
    return project_root() / "reddit-rader-AInews" / "trend-scrap" / "reddit-scraper"


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE pairs without overriding existing env vars."""
    if not path.exists():
        return

    with path.open(encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key or key in os.environ:
                continue
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            os.environ[key] = value


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got: {value}") from exc


def env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got: {value}") from exc


def split_key_list(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[\s,;]+", value or "") if part.strip()]


def collect_rapidapi_keys() -> list[str]:
    """Collect RapidAPI keys from RAPIDAPI_KEYS and numbered/single key vars."""
    keys = []

    keys.extend(split_key_list(os.environ.get("RAPIDAPI_KEYS", "")))
    keys.extend(split_key_list(os.environ.get("RAPIDAPI_KEY", "")))

    for index in range(1, MAX_RAPIDAPI_KEYS + 1):
        keys.extend(split_key_list(os.environ.get(f"RAPIDAPI_KEY_{index}", "")))
        keys.extend(split_key_list(os.environ.get(f"RAPIDAPI_KEY{index}", "")))

    deduped = []
    seen = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def validate_runtime_config(keys: list[str]) -> None:
    if not shutil.which("node"):
        raise RuntimeError("Node.js is required to run the reddit-rader-AInews scraper")

    entry = scraper_dir() / "src" / "scraper.js"
    if not entry.exists():
        raise RuntimeError(f"RapidAPI Reddit scraper not found: {entry}")

    if not env_bool("REDDIT_USE_PUBLIC", False) and not keys:
        raise RuntimeError(
            "Missing RapidAPI key. Add RAPIDAPI_KEY, RAPIDAPI_KEYS, or RAPIDAPI_KEY_1... "
            "to Phase1/.env, or set REDDIT_USE_PUBLIC=true to try the less reliable "
            "public reddit.com JSON fallback."
        )


def run_node_scraper_once(api_key: str | None, key_label: str) -> list[dict]:
    if api_key:
        print(f"  using RapidAPI key {key_label}")
    else:
        print("  using public reddit.com JSON fallback")

    with tempfile.TemporaryDirectory(prefix="boxy_reddit_rapidapi_") as tmp_dir:
        raw_output = Path(tmp_dir) / "raw_posts.json"
        env = os.environ.copy()
        env.setdefault("RAPIDAPI_HOST", "reddit34.p.rapidapi.com")
        if api_key is not None:
            env["RAPIDAPI_KEY"] = api_key
        env.setdefault("REDDIT_RAPIDAPI_SUBREDDIT", DEFAULT_SUBREDDIT)
        env.setdefault("REDDIT_RAPIDAPI_TOP_TIME", DEFAULT_TOP_TIME)
        env.setdefault("REDDIT_RAPIDAPI_SORT", DEFAULT_SORT)
        env.setdefault("REDDIT_RAPIDAPI_FETCH_LIMIT", str(DEFAULT_FETCH_LIMIT))
        env["BOXY_REDDIT_DATA_DIR"] = str(Path(tmp_dir) / "node_data")
        env["BOXY_REDDIT_RAW_OUTPUT"] = str(raw_output)

        result = subprocess.run(
            ["node", "-e", NODE_RUNNER],
            cwd=scraper_dir(),
            env=env,
            text=True,
            capture_output=True,
            timeout=180,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode != 0:
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="")
            raise RuntimeError(f"reddit-rader-AInews scraper failed with exit code {result.returncode}")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")

        with raw_output.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise RuntimeError("reddit-rader-AInews scraper returned non-list data")
        return data


def run_node_scraper() -> list[dict]:
    keys = collect_rapidapi_keys()
    validate_runtime_config(keys)

    if env_bool("REDDIT_USE_PUBLIC", False) and not keys:
        return run_node_scraper_once(None, "public")

    last_error = None
    for index, key in enumerate(keys, start=1):
        try:
            return run_node_scraper_once(key, f"{index}/{len(keys)}")
        except Exception as exc:
            last_error = exc
            if index < len(keys):
                print(f"  [warn] RapidAPI key {index}/{len(keys)} failed, trying next key: {exc}", file=sys.stderr)
            else:
                print(f"  [warn] RapidAPI key {index}/{len(keys)} failed: {exc}", file=sys.stderr)

    raise RuntimeError(f"All RapidAPI keys failed. Last error: {last_error}")


def is_image_url(url: str) -> bool:
    if not url:
        return False
    parsed = urllib.parse.urlparse(html.unescape(url))
    _, ext = os.path.splitext(parsed.path.lower())
    return ext in IMAGE_EXTENSIONS


def safe_filename(text: str, max_len: int = 70) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", text or "").strip("_").lower()[:max_len] or "post"


def extension_from_url(url: str, default: str = "jpg") -> str:
    parsed = urllib.parse.urlparse(html.unescape(url))
    _, ext = os.path.splitext(parsed.path.lower())
    if ext.startswith(".") and ext in IMAGE_EXTENSIONS:
        return ext[1:]
    return default


def download_image(url: str, reddit_id: str, title: str, images_dir: Path) -> str | None:
    images_dir.mkdir(parents=True, exist_ok=True)
    ext = extension_from_url(url)
    filename = f"reddit_rapidapi_{reddit_id}_{safe_filename(title, 55)}.{ext}"
    path = images_dir / filename
    headers = {"User-Agent": os.environ.get("REDDIT_USER_AGENT", "boxy-meme-pipeline/rapidapi-adapter")}

    try:
        req = urllib.request.Request(html.unescape(url), headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding", "").lower() == "gzip" or raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            path.write_bytes(raw)
        return os.path.relpath(path, phase1_dir())
    except Exception as exc:
        print(f"  [!] Image download failed for {reddit_id}: {exc}", file=sys.stderr)
        return None


def parse_title_and_body(text: str) -> tuple[str, str]:
    parts = [part.strip() for part in str(text or "").split("\n\n", 1)]
    title = parts[0] if parts and parts[0] else "Untitled Reddit meme"
    body = parts[1] if len(parts) > 1 else ""
    return title, body


def format_published(item: dict) -> str:
    iso_value = item.get("createTimeISO")
    if iso_value:
        try:
            parsed = dt.datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
            return parsed.strftime("%a, %d %b %Y %H:%M:%S %z")
        except ValueError:
            return str(iso_value)

    created = item.get("createTime")
    if created:
        try:
            parsed = dt.datetime.fromtimestamp(float(created), tz=dt.timezone.utc)
            return parsed.strftime("%a, %d %b %Y %H:%M:%S %z")
        except Exception:
            return ""
    return ""


def engagement_score(item: dict) -> float:
    try:
        score = float(item.get("diggCount") or 0)
        comments = float(item.get("shareCount") or 0)
        upvote_ratio = float((item.get("redditMeta") or {}).get("upvote_ratio") or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(score * upvote_ratio + comments * 2, 2)


def source_label(item: dict) -> str:
    return str((item.get("redditMeta") or {}).get("source") or "")


def source_rank(item: dict) -> int:
    source = source_label(item)
    if source.startswith("subreddit_top:"):
        return 0
    if source.startswith("subreddit:"):
        return 1
    return 2


def item_passes_basic_filters(item: dict, min_score: int, min_upvote_ratio: float) -> bool:
    meta = item.get("redditMeta") or {}
    reddit_id = str(item.get("id") or "")
    if not reddit_id:
        return False

    target_subreddit = os.environ.get("REDDIT_RAPIDAPI_SUBREDDIT", DEFAULT_SUBREDDIT).strip().lower()
    actual_subreddit = str(meta.get("subreddit") or "").strip().lower()
    if actual_subreddit != target_subreddit:
        return False

    if meta.get("over_18"):
        return False

    image_url = html.unescape(str(meta.get("external_url") or ""))
    if not is_image_url(image_url):
        return False

    score = int(item.get("diggCount") or 0)
    upvote_ratio = float(meta.get("upvote_ratio") or 0)
    return score >= min_score and upvote_ratio >= min_upvote_ratio


def select_items(items: list[dict], output_limit: int, selection_mode: str) -> list[dict]:
    """Select candidates. Default: top/day first, hot only fills remaining slots."""
    selected = []
    seen_ids = set()

    def add_from(candidates: list[dict]) -> None:
        for item in candidates:
            reddit_id = str(item.get("id") or "")
            if not reddit_id or reddit_id in seen_ids:
                continue
            seen_ids.add(reddit_id)
            selected.append(item)
            if len(selected) >= output_limit:
                return

    sorted_items = sorted(items, key=engagement_score, reverse=True)

    if selection_mode == "engagement":
        add_from(sorted_items)
        return selected

    top_items = [item for item in sorted_items if source_label(item).startswith("subreddit_top:")]
    hot_items = [item for item in sorted_items if source_label(item).startswith("subreddit:")]
    other_items = [item for item in sorted_items if source_rank(item) == 2]

    add_from(top_items)
    if len(selected) < output_limit:
        add_from(hot_items)
    if len(selected) < output_limit:
        add_from(other_items)
    return selected


def build_description(title: str, body: str, item: dict, image_url: str) -> str:
    meta = item.get("redditMeta") or {}
    lines = [
        f"Reddit r/{meta.get('subreddit', DEFAULT_SUBREDDIT)} meme post.",
        f"Title: {title}",
        f"Listing source: {meta.get('source', '')}",
        (
            "Metrics: "
            f"score={item.get('diggCount', 0)}, "
            f"upvote_ratio={meta.get('upvote_ratio', '')}, "
            f"comments={item.get('shareCount', 0)}, "
            f"hot_score={item.get('playCount', 0)}"
        ),
        f"Image: {image_url}",
    ]
    if body:
        lines.append(f"Post text: {body[:600]}")
    return "\n".join(lines)


def normalize_post(item: dict, images_dir: Path, download_images: bool) -> dict | None:
    meta = item.get("redditMeta") or {}
    image_url = html.unescape(str(meta.get("external_url") or ""))
    if not is_image_url(image_url):
        return None

    title, body = parse_title_and_body(item.get("text") or "")
    reddit_id = str(item.get("id") or "")
    local_image_path = None
    if download_images:
        local_image_path = download_image(image_url, reddit_id, title, images_dir)

    return {
        "source": SOURCE_NAME,
        "title": title,
        "url": meta.get("permalink") or (item.get("videoMeta") or {}).get("webVideoUrl") or "",
        "image_url": image_url,
        "local_image_path": local_image_path,
        "description": build_description(title, body, item, image_url),
        "keywords": f"reddit, r/{meta.get('subreddit', DEFAULT_SUBREDDIT)}",
        "published": format_published(item),
        "reddit_id": reddit_id,
        "score": item.get("diggCount", 0),
        "upvote_ratio": meta.get("upvote_ratio", 0),
        "num_comments": item.get("shareCount", 0),
        "top_comments": [],
        "engagement_score": engagement_score(item),
    }


def scrape(max_posts: int | None = None) -> list[dict]:
    load_env_file(phase1_dir() / ".env")

    output_limit = max_posts if max_posts is not None else env_int("REDDIT_RAPIDAPI_MAX_POSTS", DEFAULT_MAX_POSTS)
    min_score = env_int("REDDIT_RAPIDAPI_MIN_SCORE", DEFAULT_MIN_SCORE)
    min_upvote_ratio = env_float("REDDIT_RAPIDAPI_MIN_UPVOTE_RATIO", DEFAULT_MIN_UPVOTE_RATIO)
    selection_mode = os.environ.get("REDDIT_RAPIDAPI_SELECTION_MODE", DEFAULT_SELECTION_MODE).strip().lower()
    download_images = env_bool("REDDIT_DOWNLOAD_IMAGES", True)
    images_dir = Path(os.environ.get("IMAGES_DIR") or phase1_dir() / "output" / "images")

    raw_items = run_node_scraper()
    print(f"  loaded {len(raw_items)} normalized Reddit records from reddit-rader-AInews")

    candidates = [
        item
        for item in raw_items
        if item_passes_basic_filters(item, min_score, min_upvote_ratio)
    ]
    top_count = sum(1 for item in candidates if source_label(item).startswith("subreddit_top:"))
    hot_count = sum(1 for item in candidates if source_label(item).startswith("subreddit:"))
    print(
        "  candidates after r/memes image filters: "
        f"{len(candidates)} total ({top_count} top/day, {hot_count} hot)"
    )

    posts = []
    for item in select_items(candidates, output_limit, selection_mode):
        post = normalize_post(item, images_dir, download_images)
        if post:
            posts.append(post)

    print(
        f"  selected {len(posts)} r/{os.environ.get('REDDIT_RAPIDAPI_SUBREDDIT', DEFAULT_SUBREDDIT)} "
        f"image memes using {selection_mode}"
    )
    return posts


def main() -> None:
    parser = argparse.ArgumentParser(description="Reddit r/memes scraper via reddit-rader-AInews RapidAPI adapter")
    parser.add_argument("--output", required=True, help="Path to write JSON output")
    parser.add_argument("--max-posts", type=int, default=None, help="Maximum posts to output")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    try:
        posts = scrape(max_posts=args.max_posts)
    except Exception as exc:
        print(f"[{SOURCE_NAME}] {exc}", file=sys.stderr)
        sys.exit(1)

    result = {"source": SOURCE_NAME, "posts": posts}
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"[{SOURCE_NAME}] Wrote {len(posts)} posts to {args.output}")


if __name__ == "__main__":
    main()
