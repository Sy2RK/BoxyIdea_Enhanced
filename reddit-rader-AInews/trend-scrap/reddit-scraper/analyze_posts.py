#!/usr/bin/env python3
"""
Reddit post summarizer.

Adds the legacy `video_summary` field to Reddit post records so the
existing classification, trend analysis, and Feishu delivery pipeline can
continue to consume filtered-result.json without schema churn.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DATA_DIR = BASE_DIR / "data"
RESULT_FILE = DATA_DIR / "filtered-result.json"
sys.path.insert(0, str(SCRIPTS_DIR))

from llm_client import LLMConfigError, LLMError, LLMRateLimitError
from llm_factory import get_default_client


SYSTEM_PROMPT = """You summarize Reddit AI trend posts for a product and UA trend radar.
Return concise Chinese analysis. Focus on what the post is about, why it may matter,
what audience reaction or discussion signal is visible, and whether it suggests a
reusable AI content/effect idea. Do not invent facts beyond the post metadata."""


def load_results() -> list[dict[str, Any]]:
    if not RESULT_FILE.exists():
        raise FileNotFoundError(f"Result file not found: {RESULT_FILE}")
    with open(RESULT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Result file must contain a JSON array: {RESULT_FILE}")
    return data


def save_results(data: list[dict[str, Any]]) -> None:
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fmt_number(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}K"
    return str(int(number))


def build_prompt(post: dict[str, Any]) -> str:
    reddit_meta = post.get("redditMeta") or {}
    url = (post.get("videoMeta") or {}).get("webVideoUrl") or reddit_meta.get("permalink") or ""
    text = str(post.get("text") or "").strip()
    if len(text) > 4000:
        text = text[:4000] + "\n...[truncated]"

    return f"""请总结以下 Reddit AI 相关帖子，输出 4-6 句中文，不要使用 Markdown 表格。

帖子信息：
- Post ID: {post.get("id", "")}
- Subreddit: {reddit_meta.get("subreddit", "")}
- Author: {reddit_meta.get("author", "")}
- Source type: {reddit_meta.get("source_type", "")}
- Score/Upvotes: {fmt_number(post.get("diggCount", 0))}
- Comments: {fmt_number(post.get("shareCount", 0))}
- Hot score: {fmt_number(post.get("playCount", 0))}
- Created at: {post.get("createTimeISO", "")}
- URL: {url}

正文：
{text}
"""


def summarize_post(llm_client, post: dict[str, Any]) -> str:
    response = llm_client.call(
        SYSTEM_PROMPT,
        build_prompt(post),
        max_tokens=900,
        temperature=0.3,
    )
    return response.strip()


def process_posts() -> None:
    try:
        llm_client = get_default_client()
    except LLMConfigError as exc:
        raise ValueError(f"Failed to initialize LLM client: {exc}") from exc

    results = load_results()
    print(f"\nLoading results from: {RESULT_FILE}")
    print(f"Found {len(results)} Reddit posts")

    updated_count = 0
    skipped_count = 0

    for index, post in enumerate(results, 1):
        post_id = post.get("id", "unknown")
        existing_summary = str(post.get("video_summary") or "")
        if existing_summary and not existing_summary.startswith("ERROR"):
            print(f"\n[{index}/{len(results)}] Skipping {post_id} (already summarized)")
            skipped_count += 1
            continue

        print(f"\n[{index}/{len(results)}] Summarizing Reddit post {post_id}")
        try:
            post["video_summary"] = summarize_post(llm_client, post)
            updated_count += 1
        except LLMRateLimitError:
            raise
        except LLMError as exc:
            print(f"  ERROR: {exc}")
            post["video_summary"] = f"ERROR: {exc}"
        except Exception as exc:
            print(f"  ERROR: {exc}")
            post["video_summary"] = f"ERROR: {exc}"

        save_results(results)
        print("  Progress saved")
        time.sleep(0.5)

    print("\n" + "=" * 50)
    print("Summary:")
    print(f"  - Updated: {updated_count}")
    print(f"  - Skipped: {skipped_count}")
    print("=" * 50)


if __name__ == "__main__":
    try:
        process_posts()
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"Unexpected error: {exc}")
        raise
