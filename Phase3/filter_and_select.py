#!/usr/bin/env python3
"""Phase 3: Filter Phase 2 level designs via LLM, then select the best one."""

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


def call_llm(client, model, prompt, fallback_model=None, max_tokens=2048):
    """Call OpenRouter LLM and return response text. Falls back to secondary model on failure."""
    messages = [
        {"role": "system", "content": "You are a game design evaluator. Output ONLY valid JSON or raw text as requested. No markdown code fences, no extra commentary."},
        {"role": "user", "content": prompt},
    ]
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.4,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content
    except Exception as primary_err:
        if fallback_model:
            print(f"  [!] Primary model failed: {primary_err}, trying fallback: {fallback_model}", file=sys.stderr)
            response = client.chat.completions.create(
                model=fallback_model,
                messages=messages,
                temperature=0.4,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content
        raise


def extract_json(text):
    """Try to extract JSON from LLM response, handling markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


def build_filter_prompt(level_data, hints):
    """Build the prompt for the accept/reject evaluation step."""
    level_json = json.dumps(level_data, indent=2, ensure_ascii=False)
    prompt = f"""You are evaluating a level design for the mobile puzzle platformer game 《Boxy》.

Here is feedback and hints from the design team (may be empty if none provided):
---
{hints}
---

Evaluate the following level design:

{level_json}

Is this design good enough to be selected as a final level? Consider:
- Creativity and originality
- Fit with the Boxy philosophy (breaking the fourth wall, UI as gameplay, wordplay)
- Clarity of the puzzle structure
- Whether the twist is surprising yet logical
- Whether it avoids introducing too many new elements

Output ONLY a single JSON object with no markdown code fences:
{{
  "accepted": true or false,
  "reason": "one-sentence explanation"
}}"""
    return prompt


def build_selection_prompt(accepted_levels, background):
    """Build the prompt for choosing the best level among accepted ones."""
    levels_text = ""
    for title, data in accepted_levels.items():
        levels_text += f"\n\n=== LEVEL: {title} ===\n"
        levels_text += json.dumps(data, indent=2, ensure_ascii=False)

    prompt = f"""You are the lead designer for the mobile puzzle platformer 《Boxy》.

Here is the game background and design philosophy:
---
{background}
---

Below are the level designs that passed the initial filter. Read them carefully:
{levels_text}

Your task: choose the SINGLE best level design.
Criteria:
- Most creative and memorable twist
- Strongest fit with the Boxy philosophy
- Best balance of surprise and logical consistency
- Best use of existing game elements (doors, UI buttons, text, etc.)

Output ONLY the full JSON object of the chosen level, exactly as it appears above. Do not wrap it in markdown code fences. Do not add any extra text before or after."""
    return prompt


def main():
    parser = argparse.ArgumentParser(description="Phase 3: Filter and select the best Boxy level design")
    parser.add_argument("--config", default=None, help="Path to config.json (default: same dir as script)")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = args.config or os.path.join(script_dir, "config.json")

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    # Load environment variables (prefer Phase3/.env, fallback to Phase2/.env)
    env_path = os.path.join(script_dir, ".env")
    if not os.path.exists(env_path):
        env_path = os.path.join(script_dir, "..", "Phase2", ".env")
    load_dotenv(env_path)
    api_key = os.environ.get("OPENROUTER_API_KEY")
    model = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-20250514")
    fallback_model = os.environ.get("OPENROUTER_MODEL_DROP")

    if not api_key:
        print("[error] OPENROUTER_API_KEY not set. Create a .env file in Phase3/ or export it.", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

    # Resolve paths relative to script directory
    phase2_path = os.path.join(script_dir, config["phase2_input"])
    hint_path = os.path.join(script_dir, config["hint_file"])
    background_path = os.path.join(script_dir, config["background_file"])
    output_dir = os.path.join(script_dir, config["output_dir"])
    accepted_path = os.path.join(output_dir, config["accepted_file"])
    result_path = os.path.join(output_dir, config["result_file"])

    os.makedirs(output_dir, exist_ok=True)

    hints = load_text_file(hint_path)
    background = load_text_file(background_path)

    # Load Phase 2 output
    try:
        with open(phase2_path, encoding="utf-8") as f:
            phase2_data = json.load(f)
    except FileNotFoundError:
        print(f"[error] Phase 2 input not found: {phase2_path}", file=sys.stderr)
        with open(result_path, "w", encoding="utf-8") as f:
            f.write("No good sources this time")
        sys.exit(0)

    # Filter out error entries
    valid_levels = {k: v for k, v in phase2_data.items() if "_error" not in v}
    if not valid_levels:
        print("[filter] No valid level designs found in Phase 2 output (all entries have errors).")
        with open(result_path, "w", encoding="utf-8") as f:
            f.write("No good sources this time")
        with open(accepted_path, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2, ensure_ascii=False)
        sys.exit(0)

    # Step 1: Filter each valid level
    accepted = {}
    items = list(valid_levels.items())
    for i, (title, data) in enumerate(items):
        prompt = build_filter_prompt(data, hints)
        print(f"[{i+1}/{len(items)}] Filtering: {title}")

        try:
            raw = call_llm(client, model, prompt, fallback_model=fallback_model, max_tokens=512)
            verdict = extract_json(raw)

            if verdict.get("accepted") is True:
                accepted[title] = data
                print(f"  ✓ accepted — {verdict.get('reason', '')}")
            else:
                print(f"  ✗ rejected — {verdict.get('reason', '')}")
        except Exception as e:
            print(f"  ✗ evaluation failed: {e}", file=sys.stderr)

        if i < len(items) - 1:
            time.sleep(5)

    # Save accepted levels
    with open(accepted_path, "w", encoding="utf-8") as f:
        json.dump(accepted, f, indent=2, ensure_ascii=False)
    print(f"[filter] {len(accepted)}/{len(valid_levels)} levels accepted → {accepted_path}")

    # Step 2: Select the best one
    if not accepted:
        print("[select] No accepted levels. Writing fallback result.")
        with open(result_path, "w", encoding="utf-8") as f:
            f.write("No good sources this time")
        sys.exit(0)

    select_prompt = build_selection_prompt(accepted, background)
    print(f"[select] Choosing best level from {len(accepted)} accepted designs...")

    try:
        raw_best = call_llm(client, model, select_prompt, fallback_model=fallback_model, max_tokens=4096)
        # Try to clean up markdown fences if the model ignored instructions
        best_text = raw_best.strip()
        if best_text.startswith("```"):
            best_text = best_text.split("\n", 1)[1]
            if best_text.endswith("```"):
                best_text = best_text[:-3]
            best_text = best_text.strip()

        with open(result_path, "w", encoding="utf-8") as f:
            f.write(best_text)
        print(f"[select] Best level written → {result_path}")
    except Exception as e:
        print(f"[error] Selection failed: {e}", file=sys.stderr)
        with open(result_path, "w", encoding="utf-8") as f:
            f.write("No good sources this time")
        sys.exit(1)


if __name__ == "__main__":
    main()
