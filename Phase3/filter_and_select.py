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


def call_llm(client, model, prompt, fallback_model=None, max_tokens=2048, timeout=120):
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
            timeout=timeout,
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
                timeout=timeout,
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


def condense_level(level_data):
    """Extract only the key fields for evaluation to keep prompts short."""
    return {
        "level_name": level_data.get("level_name", ""),
        "meme_inspiration": level_data.get("meme_inspiration", ""),
        "surface_layer": level_data.get("surface_layer", ""),
        "misdirection_layer": level_data.get("misdirection_layer", ""),
        "full_game_flow": level_data.get("full_game_flow", ""),
        "hint_design": level_data.get("hint_design", {}),
        "design_check": level_data.get("design_check", {}),
    }


def build_filter_prompt(level_data, background, hints):
    """Single-step evaluation prompt: asks for reasoning ending with a single-word verdict."""
    level_json = json.dumps(condense_level(level_data), indent=2, ensure_ascii=False)
    prompt = f"""You are evaluating a level design for the mobile puzzle platformer game 《Boxy》.

Game background and design philosophy:
---
{background}
---
Especially be aware of that: "  翻转必须有逻辑支撑，不能是纯粹的随机或无厘头。
  每个反转元素必须要与后续触发行为有合理逻辑联系，不是毫无相关的关系链。" 
Additional feedback and hints from the design team (may be empty if none provided):
---
{hints}
---

Evaluate the following level design:

{level_json}

Write 2-3 sentences explaining your decision, then end your response with exactly one word on the final line: accept or reject."""
    return prompt


def build_selection_prompt(accepted_items, background, top_n=3):
    """Build the prompt for choosing the best levels among accepted ones.
    accepted_items: list of (index, title, data) tuples."""
    summaries = []
    for idx, title, data in accepted_items:
        summaries.append(f"""
[{idx}] Level Name: {data.get('level_name', title)}
Meme Inspiration: {data.get('meme_inspiration', '')}
Surface Layer: {data.get('surface_layer', '')}
Misdirection Layer: {data.get('misdirection_layer', '')}
Full Game Flow: {data.get('full_game_flow', '')}
Hint Design: {json.dumps(data.get('hint_design', {}), ensure_ascii=False)}
""")

    ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(top_n, f"{top_n}th")
    prompt = f"""You are the lead designer for the mobile puzzle platformer 《Boxy》.

Here is the game background and design philosophy:
---
{background}
---

Below are the level designs that passed the initial filter. Each is prefixed with a number in [brackets]. Read them carefully:
{''.join(summaries)}

Your task: choose the TOP {top_n} best level designs, ranked from best to {ordinal} best.
Criteria:
- Most creative and memorable twist
- Strongest fit with the Boxy philosophy
- Best balance of surprise and logical consistency
- Best use of existing game elements (doors, UI buttons, text, etc.)

Output ONLY the numbers from the brackets, one per line, in order from #1 best to #{top_n} best. For example:
2
5
1

No extra text, no markdown, no explanation. If fewer than {top_n} levels exist, list as many as are available."""
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
    try:
        top_n = int(os.environ.get("TOP_N", "3"))
    except ValueError:
        top_n = 3

    if not api_key:
        print("[error] OPENROUTER_API_KEY not set. Create a .env file in Phase3/ or export it.", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

    # Resolve paths relative to script directory
    phase2_path = os.path.join(script_dir, config["phase2_input"])
    hint_path = os.path.join(script_dir, "..", "Phase2", "hint_from_Feishu.txt")
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

    # Step 1: Filter each valid level (single-step: evaluation + verdict in one call)
    accepted = {}
    items = list(valid_levels.items())
    for i, (title, data) in enumerate(items):
        print(f"[{i+1}/{len(items)}] Filtering: {title}")

        try:
            prompt = build_filter_prompt(data, background, hints)
            raw = call_llm(client, model, prompt, fallback_model=fallback_model, max_tokens=2048)
            if raw is None:
                raise ValueError("LLM returned empty response")

            # Parse verdict robustly from the response
            print(f"  [raw model output]\n{raw}\n  [/raw]")
            text_lower = raw.strip().lower()
            lines = raw.strip().splitlines()
            last_line = lines[-1].strip().lower() if lines else ""
            print(f"  [debug] raw length: {len(raw)} chars, {len(lines)} lines")
            print(f"  [debug] last_line: '{last_line}'")
            print(f"  [debug] 'accept' in full text: {'accept' in text_lower}")
            print(f"  [debug] 'reject' in full text: {'reject' in text_lower}")
            print(f"  ✓ evaluation done")

            # Priority 1: last line contains accept/reject
            if "accept" in last_line and "reject" not in last_line:
                accepted[title] = data
                print(f"  ✓ accepted")
            elif "reject" in last_line and "accept" not in last_line:
                print(f"  ✗ rejected")
            # Priority 2: search whole text for accept/reject
            elif "accept" in text_lower and "reject" not in text_lower:
                accepted[title] = data
                print(f"  ✓ accepted (detected in full text)")
            elif "reject" in text_lower and "accept" not in text_lower:
                print(f"  ✗ rejected (detected in full text)")
            # Priority 3: both words present → prefer the one that appears last
            elif "accept" in text_lower or "reject" in text_lower:
                accept_idx = text_lower.rfind("accept")
                reject_idx = text_lower.rfind("reject")
                if accept_idx > reject_idx:
                    accepted[title] = data
                    print(f"  ✓ accepted (last occurrence)")
                else:
                    print(f"  ✗ rejected (last occurrence)")
            else:
                # Fallback: if the model didn't say accept/reject clearly, default to accepting
                # so we don't silently drop good designs due to formatting quirks
                accepted[title] = data
                print(f"  ✓ accepted (defaulted — no clear verdict found)")
        except Exception as e:
            print(f"  ✗ evaluation failed: {e}", file=sys.stderr)

        if i < len(items) - 1:
            time.sleep(5)

    # Save accepted levels
    with open(accepted_path, "w", encoding="utf-8") as f:
        json.dump(accepted, f, indent=2, ensure_ascii=False)
    print(f"[filter] {len(accepted)}/{len(valid_levels)} levels accepted → {accepted_path}")

    # Step 2: Select the top N
    if not accepted:
        print("[select] No accepted levels. Writing fallback result.")
        with open(result_path, "w", encoding="utf-8") as f:
            f.write("No good sources this time")
        sys.exit(0)

    # Build indexed list for stable selection
    accepted_items = [(i + 1, title, data) for i, (title, data) in enumerate(accepted.items())]
    select_prompt = build_selection_prompt(accepted_items, background, top_n=top_n)
    print(f"[select] Choosing top {top_n} levels from {len(accepted)} accepted designs...")

    try:
        raw_best = call_llm(client, model, select_prompt, fallback_model=fallback_model, max_tokens=256)
        if raw_best is None:
            raise ValueError("LLM returned empty response")

        # Parse numbers from the response (one per line)
        import re
        chosen_indices = []
        for line in raw_best.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            # Extract the first integer from the line
            m = re.search(r"\d+", line)
            if m:
                chosen_indices.append(int(m.group()))

        chosen_indices = chosen_indices[:top_n]
        if not chosen_indices:
            raise ValueError("No level numbers returned by model")

        # Map index -> data directly
        index_to_data = {idx: data for idx, _, data in accepted_items}
        top_levels = []
        for idx in chosen_indices:
            if idx in index_to_data:
                top_levels.append(index_to_data[idx])
            else:
                print(f"  [warn] Model returned invalid index {idx}, skipping", file=sys.stderr)

        if not top_levels:
            raise ValueError(f"Could not match any chosen indices: {chosen_indices}")

        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(top_levels, f, indent=2, ensure_ascii=False)
        print(f"[select] Top {len(top_levels)} levels written → {result_path}")
    except Exception as e:
        print(f"[error] Selection failed: {e}", file=sys.stderr)
        with open(result_path, "w", encoding="utf-8") as f:
            f.write("No good sources this time")
        sys.exit(1)


if __name__ == "__main__":
    main()
