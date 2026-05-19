#!/usr/bin/env python3
"""Phase 3: Filter Phase 2 level designs via LLM, then select the best one."""

import argparse
import json
import os
import sys
import time

from dotenv import load_dotenv

# Import shared LLM client (works from sibling directories)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, ".."))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "..", "Phase2"))
from shared.llm_client import LLMClient
from validators import load_mechanics_library, unique_violations, validate_constraints


def load_text_file(path):
    """Read a text file, return content or empty string if not found."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"  [warn] {path} not found, skipping", file=sys.stderr)
        return ""


SYS_MSG_PHASE3 = "You are a game design evaluator. Output ONLY valid JSON or raw text as requested. No markdown code fences, no extra commentary."


def call_llm(client, model, prompt, fallback_model=None, max_tokens=2048, timeout=120):
    """DEPRECATED: kept for backwards compatibility; delegates to LLMClient."""
    return client.call(
        prompt=prompt,
        system_message=SYS_MSG_PHASE3,
        model=model,
        fallback_model=fallback_model,
        temperature=0.4,
        max_tokens=max_tokens,
        timeout=timeout,
    )


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
        "source_meme_understanding": level_data.get("source_meme_understanding", {}),
        "design_brief": level_data.get("_design_brief", {}),
        "mechanic_match": level_data.get("_mechanic_match", {}),
        "level_skeleton": level_data.get("_level_skeleton", {}),
        "validation_report": level_data.get("_validation_report", {}),
        "meme_inspiration": level_data.get("meme_inspiration", ""),
        "surface_layer": level_data.get("surface_layer", ""),
        "misdirection_layer": level_data.get("misdirection_layer", ""),
        "full_game_flow": level_data.get("full_game_flow", ""),
        "hint_design": level_data.get("hint_design", {}),
        "design_check": level_data.get("design_check", {}),
        "playability_contract": level_data.get("playability_contract", {}),
        "meme_binding": level_data.get("meme_binding", {}),
        "implementation_risk": level_data.get("implementation_risk", {}),
        "visual_brief": level_data.get("visual_brief", {}),
        "phase2_quality_scores": level_data.get("quality_scores", {}),
        "candidate_rank_report": level_data.get("candidate_rank_report", {}),
    }


QUALITY_SCORE_KEYS = [
    "meme_fidelity",
    "playability",
    "boxy_fit",
    "implementation_feasibility",
    "visual_clarity",
]


def normalize_quality_scores(raw_scores):
    scores = {}
    for key in QUALITY_SCORE_KEYS:
        try:
            value = int(raw_scores.get(key, 0))
        except (AttributeError, TypeError, ValueError):
            value = 0
        scores[key] = max(0, min(5, value))
    scores["total"] = sum(scores.values())
    return scores


def quality_gate_verdict(evaluation):
    if not isinstance(evaluation, dict):
        return False, normalize_quality_scores({}), ["评审输出不是JSON对象"]

    scores = normalize_quality_scores(evaluation.get("scores", {}))
    reasons = []
    if scores["meme_fidelity"] < 4:
        reasons.append("meme_fidelity低于4")
    if scores["playability"] < 4:
        reasons.append("playability低于4")
    for key in QUALITY_SCORE_KEYS:
        if scores[key] < 3:
            reasons.append(f"{key}低于3")
    if scores["total"] < 20:
        reasons.append("总分低于20")

    model_decision = str(evaluation.get("decision", "")).strip().lower()
    if model_decision == "reject":
        reasons.append("模型判定reject")
    elif model_decision not in {"accept", "reject"}:
        reasons.append("模型未给出明确decision")

    return not reasons, scores, unique_violations(reasons)


def semantic_prefilter_violations(level_data):
    """Catch common explanation-only adaptations before spending evaluator calls."""
    violations = []
    mechanic = level_data.get("_mechanic_match") or {}
    mechanic_id = str(mechanic.get("mechanic_id", "")).strip()
    if mechanic_id == "trash_as_bridge":
        source = level_data.get("source_meme_understanding") or {}
        source_text = " ".join(
            str(source.get(key, ""))
            for key in ["punchline", "why_funny", "core_twist_to_preserve"]
        ).lower()
        judgment_terms = [
            "boring",
            "disgust",
            "slop",
            "无聊",
            "恶心",
            "厌恶",
            "鄙视",
            "嫌弃",
        ]
        overflow_terms = [
            "overflow",
            "flood",
            "overwhelm",
            "unrestricted",
            "addiction",
            "堆积",
            "泛滥",
            "刷屏",
            "淹没",
            "过量",
            "无限",
            "成瘾",
            "沉迷",
            "停不下来",
        ]
        if any(term in source_text for term in judgment_terms) and not any(
            term in source_text for term in overflow_terms
        ):
            violations.append("情绪评价被泛化成垃圾桥")
    return violations


def build_filter_prompt(level_data, background, hints):
    """Single-step evaluation prompt: asks for reasoning ending with a single-word verdict."""
    level_json = json.dumps(condense_level(level_data), indent=2, ensure_ascii=False)

    # Check for constraint violations and include them in the prompt
    violation_note = ""
    if "_constraint_violations" in level_data:
        violations = level_data["_constraint_violations"]
        violation_note = f"""

⚠️ AUTOMATED CONSTRAINT CHECK FLAGGED: This design was detected to contain the following forbidden interaction types: {', '.join(violations)}.
You MUST reject this design if the core mechanic relies on these forbidden types."""

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

CRITICAL EVALUATION RULES — reject immediately if the core mechanic involves:
1. ❌ Dragging text/words/letters as puzzle objects (e.g. dragging the word "START" onto a door)
2. ❌ Clicking/tapping text/words/labels/sign text as puzzle objects (text can hint, but cannot be the thing that changes state)
3. ❌ Dragging UI elements as puzzle objects (e.g. dragging a button, label, or icon to a slot)
4. ❌ Using phone hardware sensors (gyroscope, accelerometer, camera) for puzzles
5. ❌ Using religious elements for puzzle mechanics
6. ❌ More than 3 puzzle-relevant interactions / discovery points, or a long chain of mechanisms
7. ❌ A crowded screen with many props, labels, or UI elements that would not fit Boxy's sparse hand-drawn mobile interface
8. ❌ If source_meme_understanding is present, the design ignores or contradicts its punchline/core_twist_to_preserve and only uses a generic topic from the title
9. ❌ The gameplay is "dreamy": it jumps from meme words to arbitrary props without a clear wrong_expectation → reversal → player action chain
10. ❌ The joke only exists in the written explanation; the playable action itself does not embody the meme's reversal
11. ❌ The selected mechanic and level skeleton do not match the final level flow
{violation_note}

Important preference:
- Do NOT require a UI-based or fourth-wall trick. A clean world-physical reversal is preferred when it better preserves the meme.
- Penalize UI/text/system tricks when they become the core solution.

Evaluate the following level design:

{level_json}

Return ONLY valid JSON in this exact shape:
{{
  "decision": "accept or reject",
  "scores": {{
    "meme_fidelity": 1,
    "playability": 1,
    "boxy_fit": 1,
    "implementation_feasibility": 1,
    "visual_clarity": 1
  }},
  "summary": "one short Chinese sentence",
  "keep_reason": "why this is worth sending forward, empty if rejected",
  "main_risks": ["1-3 concrete risks"],
  "reject_reason": "why it failed, empty if accepted"
}}

Scoring thresholds you must apply:
- Reject if meme_fidelity < 4 or playability < 4.
- Reject if any score is below 3.
- Reject if total score is below 20.
- A design can be visually nice and still rejected if it cannot become a playable Boxy puzzle."""
    return prompt


def build_selection_prompt(accepted_items, background, top_n=3):
    """Build the prompt for choosing the best levels among accepted ones.
    accepted_items: list of (index, title, data) tuples."""
    summaries = []
    for idx, title, data in accepted_items:
        brief = data.get("_design_brief", {})
        mechanic = data.get("_mechanic_match", {})
        skeleton = data.get("_level_skeleton", {})
        summaries.append(f"""
[{idx}] Level Name: {data.get('level_name', title)}
Design Brief: {json.dumps(brief, ensure_ascii=False)}
Mechanic Match: {json.dumps(mechanic, ensure_ascii=False)}
Level Skeleton: {json.dumps(skeleton, ensure_ascii=False)}
Quality Gate: {json.dumps(data.get('_phase3_quality_gate', {}), ensure_ascii=False)}
Playability Contract: {json.dumps(data.get('playability_contract', {}), ensure_ascii=False)}
Meme Binding: {json.dumps(data.get('meme_binding', {}), ensure_ascii=False)}
Implementation Risk: {json.dumps(data.get('implementation_risk', {}), ensure_ascii=False)}
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
- Best use of physical world elements (doors, platforms, switches, hazards, characters)
- Simple enough to stage as a Boxy-style hand-drawn screenshot with no more than 3 puzzle-relevant objects
- Solvable through 1-3 clear interactions / discoveries
- Strongest wrong_expectation → reversal → player_action chain
- Least "dreamy": no arbitrary object chain, no explanation-only joke, no UI/text core puzzle
- Do not favor UI or fourth-wall gimmicks by default; prefer the clearest playable reversal

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
    load_dotenv(env_path, override=False)
    try:
        top_n = int(os.environ.get("TOP_N", "3"))
    except ValueError:
        top_n = 3

    client = LLMClient()
    print(f"[filter] Provider: {client.provider} — Model: {client.model}")
    if client.fallback:
        print(f"[filter] Fallback: {client.fallback}")

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
    mechanics_library = load_mechanics_library(os.path.join(script_dir, "..", "Phase2", "mechanics_library.json"))
    print(f"[filter] Loaded {len(mechanics_library)} Boxy mechanics")

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

    # Pre-filter: auto-reject designs with rule violations before spending LLM calls.
    pre_rejected = 0
    filtered_items = []
    for title, data in items:
        existing = data.get("_constraint_violations", [])
        if not isinstance(existing, list):
            existing = [existing]
        fresh = validate_constraints(
            data,
            mechanics_library=mechanics_library,
            require_compiler_fields=True,
        )
        semantic = semantic_prefilter_violations(data)
        violations = unique_violations(existing + fresh + semantic)
        if violations:
            data["_constraint_violations"] = violations
            print(f"  ✗ auto-rejected {title} (constraint violations: {', '.join(violations)})")
            pre_rejected += 1
        else:
            filtered_items.append((title, data))
    items = filtered_items
    if pre_rejected:
        print(f"[filter] Pre-filtered {pre_rejected} designs with constraint violations")

    for i, (title, data) in enumerate(items):
        print(f"[{i+1}/{len(items)}] Filtering: {title}")

        try:
            prompt = build_filter_prompt(data, background, hints)
            raw = call_llm(client, None, prompt, fallback_model=None, max_tokens=2048)
            if raw is None:
                raise ValueError("LLM returned empty response")

            print(f"  [raw model output]\n{raw}\n  [/raw]")
            evaluation = extract_json(raw)
            passed, scores, gate_reasons = quality_gate_verdict(evaluation)
            evaluation["scores"] = scores
            evaluation["gate_reasons"] = gate_reasons
            data["_phase3_quality_gate"] = evaluation
            print(f"  ✓ evaluation done")

            if passed:
                accepted[title] = data
                print(f"  ✓ accepted (score {scores['total']}/25)")
            else:
                print(f"  ✗ rejected ({', '.join(gate_reasons)})")
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
        raw_best = call_llm(client, None, select_prompt, fallback_model=None, max_tokens=256)
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
