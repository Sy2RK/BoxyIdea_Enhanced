#!/usr/bin/env python3
"""Phase 1.5: enrich scraped meme posts with visual meme understanding."""

from __future__ import annotations

import argparse
import base64
import copy
import json
import mimetypes
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
PHASE1_DIR = PROJECT_ROOT / "Phase1"
DEFAULT_MODEL = "gpt-5.4-mini"
SUPPORTED_LOCAL_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


SYS_MSG = """You analyze internet memes for a downstream puzzle-design pipeline.
Output ONLY valid JSON. Be conservative and factual.
Rules:
- Separate visible facts from interpretation.
- Do not invent text, characters, brands, usernames, or context not visible in the image or metadata.
- If uncertain, use "unknown" and lower confidence.
- Explain the core joke/punchline, not just the topic.
- Prefer concise Chinese output.
"""


SCHEMA_INSTRUCTIONS = """Return exactly this JSON object shape:
{
  "schema_version": "1.0",
  "visible_text": ["short OCR text strings, empty if none or unreadable"],
  "visual_elements": ["main visible objects/characters/actions"],
  "literal_summary": "what is literally shown, without explaining the joke",
  "punchline": "the meme's central joke or twist",
  "humor_mechanism": ["contrast", "misdirection", "wordplay", "absurdity", "relatability", "social commentary", "other"],
  "why_funny": "why the punchline works",
  "cultural_context": "needed background, or unknown/not needed",
  "confidence": 0.0,
  "boxy_adaptation": {
    "usable": true,
    "core_twist_to_preserve": "the exact comic reversal that later phases must preserve",
    "recommended_angle": "one compact Boxy adaptation direction",
    "avoid_misreadings": ["ways a weak model might misread this meme"]
  },
  "quality_flags": {
    "has_readable_text": false,
    "requires_external_context": false,
    "image_unclear": false,
    "not_a_meme": false
  }
}

Set confidence as a number from 0 to 1.
Use empty arrays instead of null. Use "unknown" instead of null strings.
"""


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_environment() -> None:
    """Load Phase1.5 env first, then Phase2 env for shared LLM settings."""
    for path in [SCRIPT_DIR / ".env", PROJECT_ROOT / "Phase2" / ".env"]:
        if path.exists():
            load_dotenv(path, override=True)


def resolve_path(raw_path: str | None, bases: list[Path]) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.is_absolute() and path.exists():
        return path
    for base in bases:
        candidate = base / path
        if candidate.exists():
            return candidate
    return None


def image_content_part(post: dict) -> dict | None:
    """Build a chat image content part from local image or remote image URL."""
    local_path = resolve_path(
        post.get("local_image_path"),
        [PHASE1_DIR, PROJECT_ROOT, SCRIPT_DIR],
    )
    if local_path and local_path.suffix.lower() in SUPPORTED_LOCAL_IMAGE_EXTS:
        mime = mimetypes.guess_type(local_path.name)[0] or "image/jpeg"
        data = base64.b64encode(local_path.read_bytes()).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{data}"},
        }

    image_url = str(post.get("image_url") or "").strip()
    if image_url.startswith(("http://", "https://")):
        return {"type": "image_url", "image_url": {"url": image_url}}
    return None


def build_user_text(post: dict) -> str:
    metadata = {
        "source": post.get("source", ""),
        "title": post.get("title", ""),
        "description": post.get("description", ""),
        "keywords": post.get("keywords", ""),
        "score": post.get("score", ""),
        "upvote_ratio": post.get("upvote_ratio", ""),
        "num_comments": post.get("num_comments", ""),
        "url": post.get("url", ""),
    }
    return f"""Analyze this meme image and metadata for downstream Boxy level design.

Metadata:
{json.dumps(metadata, ensure_ascii=False, indent=2)}

Task:
1. Read visible image text/OCR carefully.
2. Identify literal visual elements.
3. Explain the punchline and why it is funny.
4. Extract the exact twist later phases must preserve.
5. Flag if it is unclear, not a meme, or needs too much external context.

{SCHEMA_INSTRUCTIONS}"""


def extract_json(text: str) -> dict:
    if not text:
        raise ValueError("empty model response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def normalize_list(value) -> list:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_understanding(raw: dict, model: str) -> dict:
    boxy = raw.get("boxy_adaptation")
    if not isinstance(boxy, dict):
        boxy = {}
    flags = raw.get("quality_flags")
    if not isinstance(flags, dict):
        flags = {}

    try:
        confidence = float(raw.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return {
        "schema_version": "1.0",
        "model": model,
        "visible_text": normalize_list(raw.get("visible_text")),
        "visual_elements": normalize_list(raw.get("visual_elements")),
        "literal_summary": str(raw.get("literal_summary") or "unknown").strip() or "unknown",
        "punchline": str(raw.get("punchline") or "unknown").strip() or "unknown",
        "humor_mechanism": normalize_list(raw.get("humor_mechanism")),
        "why_funny": str(raw.get("why_funny") or "unknown").strip() or "unknown",
        "cultural_context": str(raw.get("cultural_context") or "unknown").strip() or "unknown",
        "confidence": confidence,
        "boxy_adaptation": {
            "usable": bool(boxy.get("usable", True)),
            "core_twist_to_preserve": str(
                boxy.get("core_twist_to_preserve") or "unknown"
            ).strip()
            or "unknown",
            "recommended_angle": str(boxy.get("recommended_angle") or "unknown").strip()
            or "unknown",
            "avoid_misreadings": normalize_list(boxy.get("avoid_misreadings")),
        },
        "quality_flags": {
            "has_readable_text": bool(flags.get("has_readable_text", False)),
            "requires_external_context": bool(flags.get("requires_external_context", False)),
            "image_unclear": bool(flags.get("image_unclear", False)),
            "not_a_meme": bool(flags.get("not_a_meme", False)),
        },
    }


def call_openai_vision(client: OpenAI, model: str, post: dict, timeout: int) -> dict:
    image_part = image_content_part(post)
    if not image_part:
        raise ValueError("no supported local image or remote image_url")

    messages = [
        {"role": "developer", "content": SYS_MSG},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": build_user_text(post)},
                image_part,
            ],
        },
    ]
    request = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_completion_tokens": 1200,
        "timeout": timeout,
    }

    try:
        response = client.chat.completions.create(**request)
    except Exception as exc:
        if "temperature" in str(exc).lower() and "unsupported" in str(exc).lower():
            request.pop("temperature", None)
            response = client.chat.completions.create(**request)
        else:
            raise

    content = response.choices[0].message.content or ""
    return extract_json(content)


def render_understanding_for_description(understanding: dict) -> str:
    boxy = understanding.get("boxy_adaptation") or {}
    lines = [
        "Phase1.5 meme understanding:",
        f"Visible text: {' | '.join(understanding.get('visible_text') or []) or 'unknown'}",
        f"Visual elements: {' | '.join(understanding.get('visual_elements') or []) or 'unknown'}",
        f"Literal summary: {understanding.get('literal_summary', 'unknown')}",
        f"Punchline: {understanding.get('punchline', 'unknown')}",
        f"Why funny: {understanding.get('why_funny', 'unknown')}",
        f"Core twist to preserve: {boxy.get('core_twist_to_preserve', 'unknown')}",
        f"Avoid misreadings: {' | '.join(boxy.get('avoid_misreadings') or []) or 'unknown'}",
        f"Confidence: {understanding.get('confidence', 0)}",
    ]
    return "\n".join(lines)


def enrich_posts(
    data: dict,
    client: OpenAI,
    model: str,
    max_posts: int,
    append_description: bool,
    retries: int = 1,
    retry_wait: float = 2.0,
) -> dict:
    output = copy.deepcopy(data)
    analyzed = 0
    attempted = 0

    for source_name, source_data in output.items():
        if not isinstance(source_data, dict):
            continue
        posts = source_data.get("posts")
        if not isinstance(posts, list):
            continue

        for post in posts:
            if not isinstance(post, dict):
                continue
            if attempted >= max_posts:
                post.setdefault("meme_understanding_skipped_reason", "phase15 max_posts reached")
                continue
            if not image_content_part(post):
                post.setdefault("meme_understanding_skipped_reason", "no analyzable image")
                continue

            title = post.get("title", "untitled")
            attempted += 1
            print(f"  [{attempted}/{max_posts}] understanding: {source_name} / {title}")
            last_error = None
            for attempt in range(retries + 1):
                try:
                    raw = call_openai_vision(client, model, post, timeout=120)
                    understanding = normalize_understanding(raw, model)
                    post["meme_understanding"] = understanding
                    if append_description:
                        existing = str(post.get("description") or "").strip()
                        addition = render_understanding_for_description(understanding)
                        post["description"] = f"{existing}\n\n{addition}".strip()
                    analyzed += 1
                    time.sleep(1)
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < retries:
                        print(
                            f"  [warn] meme understanding failed for {title} "
                            f"(attempt {attempt + 1}/{retries + 1}): {exc}; retrying",
                            file=sys.stderr,
                        )
                        time.sleep(retry_wait)
                    else:
                        print(f"  [warn] meme understanding failed for {title}: {exc}", file=sys.stderr)
                        post["meme_understanding_error"] = str(exc)

    print(f"[phase1.5] Enriched {analyzed}/{attempted} attempted posts")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1.5: visual meme understanding")
    parser.add_argument("--config", default=None, help="Path to config.json")
    parser.add_argument("--input", default=None, help="Override input JSON path")
    parser.add_argument("--output", default=None, help="Override output JSON path")
    parser.add_argument("--max-posts", type=int, default=None, help="Maximum image posts to analyze")
    parser.add_argument("--model", default=None, help="Override model for meme understanding")
    parser.add_argument("--retries", type=int, default=None, help="Retry count per post on transient errors")
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else SCRIPT_DIR / "config.json"
    config = load_config(config_path)
    load_environment()

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY or LLM_API_KEY is required for Phase1.5 vision analysis")

    model = (
        args.model
        or os.environ.get("PHASE15_MODEL")
        or os.environ.get("OPENAI_VISION_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or DEFAULT_MODEL
    )
    max_posts = args.max_posts if args.max_posts is not None else int(config.get("max_posts", 10))
    retries = args.retries if args.retries is not None else int(config.get("retries", 1))
    append_description = bool(config.get("append_to_description", True))

    input_path = Path(args.input) if args.input else SCRIPT_DIR / config["phase1_input"]
    output_path = Path(args.output) if args.output else SCRIPT_DIR / config["output_dir"] / config["output_file"]

    with input_path.open(encoding="utf-8") as f:
        data = json.load(f)

    print(f"[phase1.5] Provider: openai - Model: {model}")
    print(f"[phase1.5] Input: {input_path}")
    client = OpenAI(api_key=api_key)
    enriched = enrich_posts(data, client, model, max_posts, append_description, retries=retries)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    print(f"[phase1.5] Wrote enriched posts -> {output_path}")


if __name__ == "__main__":
    main()
