#!/usr/bin/env python3
"""Phase 2: Read Phase1 scraped memes, generate Boxy level designs via OpenRouter LLM."""

import argparse
import json
import os
import sys
import time

from openai import OpenAI
from dotenv import load_dotenv


def load_text_file(path):
    """Read a text file, return content or empty string if not found."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"  [warn] {path} not found, skipping", file=sys.stderr)
        return ""


def has_description(post):
    """Check if a post has meaningful description content."""
    desc = post.get("description")
    if not desc:
        return False
    if isinstance(desc, str) and desc.strip() == "":
        return False
    return True


def build_prompt(post, background, response_points, hint):
    """Build a concise LLM prompt for one meme → level design."""

    meme_context = f"""Title: {post['title']}
Description: {post['description']}
Keywords: {post.get('keywords', '')}""".strip()


    prompt = f"""You are a game level designer for the mobile puzzle platformer 《Boxy》.
Core idea: a box-shaped character moves from start door to end door. Everything on screen — UI buttons, text, signs, settings — can be puzzle elements with physical properties or wordplay meanings.

{background}

here is some hints from the working group: {hint}

Now design a level inspired by this meme:
---
{meme_context}
The design should answer the response points: {response_points}
---
"""
    return prompt


def call_llm(client, model, prompt, fallback_model=None):
    """Call OpenRouter LLM and return response text. Falls back to secondary model on failure."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a game level designer. Output ONLY valid JSON. No markdown fences, no extra text."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=4096,
            timeout=120,
        )
        return response.choices[0].message.content
    except Exception as primary_err:
        if fallback_model:
            print(f"  [!] Primary model failed: {primary_err}, trying fallback: {fallback_model}", file=sys.stderr)
            response = client.chat.completions.create(
                model=fallback_model,
                messages=[
                    {"role": "system", "content": "You are a game level designer. Output ONLY valid JSON. No markdown fences, no extra text."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
                max_tokens=4096,
                timeout=120,
            )
            return response.choices[0].message.content
        raise  # no fallback configured, let caller handle


def build_json_prompt(narrative_design):
    """Second-step prompt: turn a natural-language design into strict JSON."""
    return f"""You are a data formatter. Convert the following level design into the exact JSON schema below.

Original design:
---
{narrative_design}
---

Output ONLY valid JSON. No markdown code fences, no extra commentary. The content language should be in chinese.

Required JSON structure:
{{
  "level_name": "Chinese or bilingual name",
  "meme_inspiration": "How the meme inspired the level concept",
  "surface_layer": "what the scene looks like, what player sees first",
  "misdirection_layer": "false clues and what cognitive bias they exploit",
  "full_game_flow": "numbered step-by-step walkthrough of correct playthrough",
  "elements": [{{"name": "object name", "layer": "UI/世界/元系统", "role": "its role in the puzzle"}}],
  "hint_design": {{
    "hint_text": "the on-screen hint text",
    "surface_meaning": "what player thinks at first glance",
    "actual_meaning": "what it really points to",
    "participates_in_gameplay": false
  }},
  "design_check": {{
    "short_path": true,
    "no_new_elements": true,
    "rational_but_unexpected": true,
    "hint_gives_direction": true,
    "progression_with_previous": true
  }}
}}"""


def extract_json(text):
    """Try to extract JSON from LLM response, handling markdown fences."""
    if not text:
        raise ValueError("LLM returned empty response")
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1]  # remove ```json line
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


def main():
    parser = argparse.ArgumentParser(description="Phase 2: Meme → Boxy Level Design Synthesizer")
    parser.add_argument("--config", default=None, help="Path to config.json (default: same dir as script)")
    args = parser.parse_args()

    # Resolve paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = args.config or os.path.join(script_dir, "config.json")

    with open(config_path) as f:
        config = json.load(f)

    # Load .env from same directory as config
    load_dotenv(os.path.join(script_dir, ".env"))

    api_key = os.environ.get("OPENROUTER_API_KEY")
    model = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-20250514")
    fallback_model = os.environ.get("OPENROUTER_MODEL_DROP")

    if not api_key:
        print("[error] OPENROUTER_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)
    if fallback_model:
        print(f"[synthesizer] Primary model: {model} — Fallback: {fallback_model}")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    # Load context files
    background = load_text_file(os.path.join(script_dir, "background.txt"))
    response_points = load_text_file(os.path.join(script_dir, "response_point.txt"))
    hint = load_text_file(os.path.join(script_dir, "hint_from_Feishu.txt"))

    # Load Phase1 data
    phase1_path = os.path.join(script_dir, config["phase1_input"])
    with open(phase1_path, encoding="utf-8") as f:
        phase1_data = json.load(f)

    # Collect all posts from all sources
    all_posts = []
    for source_name, source_data in phase1_data.items():
        if isinstance(source_data, dict) and "posts" in source_data:
            for post in source_data["posts"]:
                post["_source"] = source_name
                all_posts.append(post)

    # Filter to posts with descriptions
    eligible = [p for p in all_posts if has_description(p)]
    print(f"[synthesizer] {len(eligible)}/{len(all_posts)} posts have descriptions")

    if not eligible:
        print("[synthesizer] No eligible posts, skipping.", file=sys.stderr)
        sys.exit(0)

    # Generate level designs (two-step: narrative → JSON)
    results = {}
    for i, post in enumerate(eligible):
        narrative_prompt = build_prompt(post, background, response_points, hint)
        print(f"[{i+1}/{len(eligible)}] Generating: {post['title']}")

        try:
            # Step 1: narrative design
            narrative = call_llm(client, model, narrative_prompt, fallback_model=fallback_model)
            print(f"  ✓ step 1 (narrative) done")

            if i < len(eligible) - 1:
                time.sleep(5)

            # Step 2: convert to JSON
            json_prompt = build_json_prompt(narrative)
            raw = call_llm(client, model, json_prompt, fallback_model=fallback_model)
            data = extract_json(raw)
            print(f"  ✓ step 2 (json) done")

            # Attach source metadata
            data["source"] = post.get("_source", "unknown")
            data["source_post_title"] = post["title"]
            data["source_post_url"] = post.get("url", "")
            data["source_image_path"] = post.get("local_image_path", "")

            results[post["title"]] = data
            print(f"  ✓ finished")

        except Exception as e:
            print(f"  ✗ failed: {e}", file=sys.stderr)
            results[post["title"]] = {"_error": str(e)}

        # Rate limiting — 5s between posts
        if i < len(eligible) - 1:
            time.sleep(5)

    # Save output
    output_dir = os.path.join(script_dir, config["output_dir"])
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, config["output_file"])

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    ok = sum(1 for v in results.values() if "_error" not in v)
    print(f"[synthesizer] {ok}/{len(results)} levels generated → {output_path}")


if __name__ == "__main__":
    main()
