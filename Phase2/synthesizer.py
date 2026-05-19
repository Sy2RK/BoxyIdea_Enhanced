#!/usr/bin/env python3
"""Phase 2: Compile Phase1 scraped memes into Boxy level designs via LLM."""

import argparse
import json
import os
import sys
import time

from dotenv import load_dotenv

# Import shared LLM client (works from sibling directories)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, ".."))
from shared.llm_client import LLMClient
from validators import (
    format_mechanics_for_prompt,
    load_mechanics_library,
    unique_violations,
    validate_constraints as validate_level_constraints,
    validation_report,
)


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
    if post.get("meme_understanding"):
        return True
    if not desc:
        return False
    if isinstance(desc, str) and desc.strip() == "":
        return False
    return True


def format_list(items):
    if not items:
        return ""
    if isinstance(items, list):
        return " | ".join(str(item) for item in items if str(item).strip())
    return str(items)


def format_meme_understanding(post):
    """Render Phase1.5 meme understanding as compact prompt context."""
    understanding = post.get("meme_understanding")
    if not isinstance(understanding, dict):
        return ""

    boxy = understanding.get("boxy_adaptation") or {}
    flags = understanding.get("quality_flags") or {}
    return f"""Phase1.5 Meme Understanding (primary source of truth):
Visible text: {format_list(understanding.get('visible_text')) or 'unknown'}
Visual elements: {format_list(understanding.get('visual_elements')) or 'unknown'}
Literal summary: {understanding.get('literal_summary', 'unknown')}
Punchline: {understanding.get('punchline', 'unknown')}
Humor mechanism: {format_list(understanding.get('humor_mechanism')) or 'unknown'}
Why funny: {understanding.get('why_funny', 'unknown')}
Cultural context: {understanding.get('cultural_context', 'unknown')}
Core twist to preserve: {boxy.get('core_twist_to_preserve', 'unknown')}
Recommended Boxy angle: {boxy.get('recommended_angle', 'unknown')}
Avoid misreadings: {format_list(boxy.get('avoid_misreadings')) or 'unknown'}
Confidence: {understanding.get('confidence', 0)}
Quality flags: {json.dumps(flags, ensure_ascii=False)}"""


def build_meme_context(post):
    title = post.get("title", "Untitled meme")
    base_context = f"""Title: {title}
Description: {post.get('description', '')}
Keywords: {post.get('keywords', '')}""".strip()

    understanding_context = format_meme_understanding(post)
    if not understanding_context:
        return base_context

    return f"""{base_context}

{understanding_context}

Source-use rule:
- Treat the Phase1.5 punchline and core twist as the main meme meaning.
- Do not design from the title alone if it would ignore or contradict the punchline.
- Preserve the original comedic reversal in the level concept, then adapt it to Boxy mechanics."""


def condense_meme_understanding(post):
    understanding = post.get("meme_understanding")
    if not isinstance(understanding, dict):
        return {}
    boxy = understanding.get("boxy_adaptation") or {}
    return {
        "punchline": understanding.get("punchline", ""),
        "why_funny": understanding.get("why_funny", ""),
        "core_twist_to_preserve": boxy.get("core_twist_to_preserve", ""),
        "avoid_misreadings": boxy.get("avoid_misreadings", []),
        "confidence": understanding.get("confidence", 0),
    }


def normalize_source_image_path(raw_path, script_dir):
    """Return a project-root-relative source image path when possible."""
    if not raw_path:
        return ""

    project_root = os.path.dirname(script_dir)
    phase1_dir = os.path.join(project_root, "Phase1")
    path_text = str(raw_path)
    candidates = []

    if os.path.isabs(path_text):
        candidates.append(path_text)
    else:
        candidates.append(os.path.join(project_root, path_text))
        candidates.append(os.path.join(phase1_dir, path_text))

    for candidate in candidates:
        if os.path.exists(candidate):
            try:
                return os.path.relpath(candidate, project_root)
            except ValueError:
                return candidate

    return path_text


SYS_MSG_PHASE2 = "You are a game level designer. Output ONLY valid JSON. No markdown fences, no extra text."


CANDIDATE_STRATEGIES = [
    {
        "id": "A_meme_fidelity",
        "label": "Candidate A",
        "focus": (
            "Preserve the meme punchline and comic reversal as strongly as possible. "
            "Reject generic topic adaptation even if it looks easy to stage."
        ),
    },
    {
        "id": "B_playability",
        "label": "Candidate B",
        "focus": (
            "Prioritize a practical Boxy puzzle that can be implemented with physical "
            "objects, clear state changes, and obvious success/failure feedback."
        ),
    },
]


def call_llm(client, model, prompt, fallback_model=None):
    """DEPRECATED: kept for backwards compatibility; delegates to LLMClient."""
    return client.call(
        prompt=prompt,
        system_message=SYS_MSG_PHASE2,
        model=model,
        fallback_model=fallback_model,
        temperature=0.8,
        max_tokens=4096,
        timeout=120,
    )


def call_json(client, prompt, max_tokens=4096, temperature=0.45):
    """Call the LLM and parse a JSON object response."""
    raw = client.call(
        prompt=prompt,
        system_message=SYS_MSG_PHASE2,
        model=None,
        fallback_model=None,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=120,
    )
    data = extract_json(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}")
    return data


def build_design_brief_prompt(post):
    meme_context = build_meme_context(post)
    return f"""You are Phase2A of a meme-to-game design compiler.

Input meme:
---
{meme_context}
---

Task:
Compress the meme into a game design brief. Do NOT design a level yet. Do NOT invent props, terminals, UI controls, labels, badges, or final gameplay.

Output ONLY valid JSON in this exact shape:
{{
  "meme_core": "one sentence describing the meme's actual joke",
  "wrong_expectation": "what the player should incorrectly assume at first",
  "reversal": "the one cognitive reversal that the level should make playable",
  "player_realization": "what the player realizes at the aha moment",
  "emotional_tone": "short tone phrase, e.g. annoyed, suspicious, clever, absurd",
  "must_preserve": ["2-4 concrete things that must survive the adaptation"],
  "must_avoid": ["2-4 misreadings or design traps to avoid"]
}}"""


def build_mechanic_match_prompt(brief, mechanics_library, strategy=None):
    strategy_note = ""
    if strategy:
        strategy_note = f"""
Candidate strategy:
- ID: {strategy.get('id')}
- Focus: {strategy.get('focus')}
"""
    return f"""You are Phase2B of a Boxy level design compiler.

Design brief:
{json.dumps(brief, ensure_ascii=False, indent=2)}

Allowed Boxy mechanic library:
---
{format_mechanics_for_prompt(mechanics_library)}
---
{strategy_note}

Task:
Choose exactly ONE primary mechanic from the library. You may not invent a new mechanic.
Prefer mechanics whose wrong_expectation and reversal are logically isomorphic to the meme, not merely thematically similar.

Output ONLY valid JSON:
{{
  "mechanic_id": "one id from the library",
  "mechanic_name": "library name",
  "fit_reason": "why this mechanic is structurally right for the meme",
  "wrong_expectation_mapping": "how the meme's wrong expectation maps to play",
  "reversal_mapping": "how the meme's reversal maps to play",
  "allowed_player_actions": ["1-3 actions copied or adapted from the library"],
  "world_object_candidates": ["2-3 physical world objects, no UI/text/core labels"],
  "forbidden_objects_to_avoid": ["UI/text/system/label traps that must not become core puzzle objects"],
  "risk_notes": ["main design risks to avoid"]
}}"""


def build_skeleton_prompt(brief, mechanic_match, mechanics_library, strategy=None):
    mechanic_id = mechanic_match.get("mechanic_id", "")
    library_item = {}
    for item in mechanics_library:
        if item.get("id") == mechanic_id:
            library_item = item
            break
    strategy_note = ""
    if strategy:
        strategy_note = f"""
Candidate strategy:
- ID: {strategy.get('id')}
- Focus: {strategy.get('focus')}
"""

    return f"""You are Phase2C of a Boxy level design compiler.

Design brief:
{json.dumps(brief, ensure_ascii=False, indent=2)}

Selected mechanic:
{json.dumps(mechanic_match, ensure_ascii=False, indent=2)}

Library definition for selected mechanic:
{json.dumps(library_item, ensure_ascii=False, indent=2)}
{strategy_note}

Task:
Create the minimal playable skeleton. Do NOT write final prose yet.

Hard rules:
- Use exactly one core mechanic.
- Use only physical world objects as puzzle objects.
- UI, labels, signs, text, terminals, identity badges, menus, and settings cannot be the core solution.
- Hint text can guide the player but must not be clicked, dragged, transformed, or required as an object.
- Maximum 3 puzzle-relevant world objects.
- Maximum 3 player steps.
- The misleading object and solution object must be the same object or strongly causally linked.
- Include a failure case and an aha moment so the design is playable, not dreamy.

Output ONLY valid JSON:
{{
  "mechanic_id": "{mechanic_id}",
  "level_goal": "reach the end door",
  "misleading_object": "the object that creates the wrong expectation",
  "real_solution_object": "the object/player behavior that creates the reversal",
  "world_objects": ["1-3 physical puzzle objects"],
  "player_steps": ["1-3 concise gameplay steps"],
  "failure_case": "what happens if the player follows the wrong expectation",
  "aha_moment": "what the player realizes",
  "why_this_is_funny": "why this preserves the meme's joke in gameplay"
}}"""


def build_final_level_prompt(
    brief,
    mechanic_match,
    skeleton,
    background,
    response_points,
    hint,
    strategy=None,
):
    strategy_note = ""
    if strategy:
        strategy_note = f"""
Candidate strategy:
- ID: {strategy.get('id')}
- Focus: {strategy.get('focus')}
"""
    return f"""You are Phase2D of a Boxy level design compiler.

Game background:
---
{background}
---

Design-team response points:
---
{response_points}
---

Constraint notes:
---
{hint}
---

Design brief:
{json.dumps(brief, ensure_ascii=False, indent=2)}

Selected mechanic:
{json.dumps(mechanic_match, ensure_ascii=False, indent=2)}

Approved minimal skeleton:
{json.dumps(skeleton, ensure_ascii=False, indent=2)}
{strategy_note}

Task:
Expand the approved skeleton into the existing Phase2 level JSON schema.

Hard rules:
- Do not change the selected mechanic or the skeleton's core action.
- Do not add UI, text, label, terminal, identity, menu, setting, or abstract system objects as core puzzle objects.
- Use no more than 3 puzzle-relevant elements.
- The full_game_flow must be 1-3 numbered steps.
- The hint text must have "participates_in_gameplay": false.
- The joke must live in the playable reversal, not only in the prose.
- Add concrete implementation-facing fields so another designer or engineer can judge playability without rereading the prose.
- The playability_contract must describe observable state changes, not vague feelings.
- The meme_binding must prove that the player action itself carries the meme joke.
- The visual_brief should describe the single screenshot state Phase5 should render. Prefer the solved/reversal-visible state if the mechanic is dynamic.
- The content language should be Chinese.

Output ONLY valid JSON:
{{
  "level_name": "Chinese or bilingual name",
  "meme_inspiration": "How the meme inspired the level concept",
  "surface_layer": "what the scene looks like, what player sees first",
  "misdirection_layer": "false clues and what cognitive bias they exploit",
  "full_game_flow": "numbered 1-3 step walkthrough of the correct playthrough",
  "elements": [{{"name": "object name", "layer": "世界", "role": "its role in the puzzle; include no more than 3 puzzle-relevant world objects"}}],
  "hint_design": {{
    "hint_text": "the on-screen hint text",
    "surface_meaning": "what player thinks at first glance",
    "actual_meaning": "what it really points to",
    "participates_in_gameplay": false
  }},
  "playability_contract": {{
    "initial_state": "what is visible before the player solves the level",
    "wrong_action": "the natural but wrong player action",
    "failure_feedback": "observable feedback when the player follows the wrong expectation",
    "correct_action": "the short correct action, using a physical world object or waiting/positioning behavior",
    "state_change": "what visibly changes in the level after the correct action",
    "win_condition": "how Boxy reaches or unlocks the end door"
  }},
  "meme_binding": {{
    "source_punchline": "the meme punchline in one sentence",
    "playable_reversal": "how the punchline becomes a playable reversal",
    "why_action_preserves_joke": "why the required player action carries the joke",
    "would_lose_joke_if_action_removed": true
  }},
  "implementation_risk": {{
    "needs_new_mechanic": false,
    "relies_on_text_explanation": false,
    "dynamic_state_hard_to_visualize": false,
    "risk_notes": ["1-3 concrete risks or empty array"]
  }},
  "visual_brief": {{
    "screenshot_state": "initial_misdirection | reversal_visible | solved_path",
    "must_show": ["2-4 things the image must make visible"],
    "avoid_showing": ["things that would make the image misleading or too explanatory"],
    "focal_objects": ["1-3 objects Phase5 should emphasize"]
  }},
  "design_check": {{
    "short_path": true,
    "no_new_elements": true,
    "rational_but_unexpected": true,
    "hint_gives_direction": true,
    "progression_with_previous": true
  }}
}}"""


def build_repair_prompt(level_data, violations, brief, mechanic_match, skeleton):
    return f"""Repair this Boxy level JSON so it passes the hard validation rules.

Violations to fix:
{json.dumps(violations, ensure_ascii=False, indent=2)}

Original design brief:
{json.dumps(brief, ensure_ascii=False, indent=2)}

Selected mechanic:
{json.dumps(mechanic_match, ensure_ascii=False, indent=2)}

Approved skeleton:
{json.dumps(skeleton, ensure_ascii=False, indent=2)}

Current level JSON:
{json.dumps(level_data, ensure_ascii=False, indent=2)}

Rules:
- Preserve the meme joke and selected mechanic.
- Remove UI/text/terminal/label/identity/menu/core-system objects from the solution.
- Use only physical world objects as puzzle objects.
- Maximum 3 puzzle elements and 3 player steps.
- Keep or repair playability_contract, meme_binding, implementation_risk, and visual_brief.
- If the current design is explanation-only, move the meme reversal into correct_action and state_change.
- Keep the existing output schema.
- Output ONLY repaired valid JSON."""


def build_candidate_evaluation_prompt(brief, candidates):
    compact_candidates = []
    for candidate in candidates:
        data = candidate["level"]
        compact_candidates.append({
            "candidate_id": candidate["strategy"]["id"],
            "level_name": data.get("level_name", ""),
            "mechanic_id": candidate["mechanic_match"].get("mechanic_id", ""),
            "meme_inspiration": data.get("meme_inspiration", ""),
            "full_game_flow": data.get("full_game_flow", ""),
            "playability_contract": data.get("playability_contract", {}),
            "meme_binding": data.get("meme_binding", {}),
            "implementation_risk": data.get("implementation_risk", {}),
            "visual_brief": data.get("visual_brief", {}),
            "validation_report": data.get("_validation_report", {}),
        })

    return f"""You are Phase2E, a strict Boxy design reviewer.

Design brief:
{json.dumps(brief, ensure_ascii=False, indent=2)}

Candidate levels:
{json.dumps(compact_candidates, ensure_ascii=False, indent=2)}

Score each candidate from 1 to 5 on:
- meme_fidelity: player action preserves the original punchline
- playability: clear initial state, wrong action, feedback, correct action, state change, win condition
- boxy_fit: feels like a short Boxy puzzle, not a generic platform scene
- implementation_feasibility: can be implemented with simple physical objects and limited new code
- visual_clarity: one screenshot can communicate the puzzle state

Rules:
- Penalize designs whose joke only exists in prose.
- Penalize designs whose correct action is arbitrary or dreamlike.
- Penalize designs that rely on text explanation, UI/menu tricks, religion, or many props.
- Prefer a lower-concept but playable puzzle over a poetic but vague one.

Output ONLY valid JSON:
{{
  "selected_candidate_id": "A_meme_fidelity or B_playability",
  "scores": {{
    "A_meme_fidelity": {{
      "meme_fidelity": 1,
      "playability": 1,
      "boxy_fit": 1,
      "implementation_feasibility": 1,
      "visual_clarity": 1,
      "total": 5
    }},
    "B_playability": {{
      "meme_fidelity": 1,
      "playability": 1,
      "boxy_fit": 1,
      "implementation_feasibility": 1,
      "visual_clarity": 1,
      "total": 5
    }}
  }},
  "selection_reason": "why the selected candidate is more usable",
  "main_risks": ["1-3 risks to carry into Phase3"]
}}"""


def _score_total(score_block):
    if not isinstance(score_block, dict):
        return 0
    keys = [
        "meme_fidelity",
        "playability",
        "boxy_fit",
        "implementation_feasibility",
        "visual_clarity",
    ]
    total = 0
    for key in keys:
        try:
            value = int(score_block.get(key, 0))
        except (TypeError, ValueError):
            value = 0
        total += max(0, min(5, value))
    return total


def _attach_compiler_metadata(data, brief, mechanic_match, skeleton, strategy):
    data["_design_brief"] = brief
    data["_mechanic_match"] = mechanic_match
    data["_level_skeleton"] = skeleton
    data["_candidate_strategy"] = {
        "id": strategy.get("id", ""),
        "focus": strategy.get("focus", ""),
    }
    return data


def compile_candidate(client, brief, background, response_points, hint, mechanics_library, strategy):
    mechanic_match = call_json(
        client,
        build_mechanic_match_prompt(brief, mechanics_library, strategy=strategy),
        max_tokens=1800,
        temperature=0.25,
    )
    print(
        f"  ✓ {strategy['label']} mechanic: "
        f"{mechanic_match.get('mechanic_id', 'unknown')}"
    )

    skeleton = call_json(
        client,
        build_skeleton_prompt(brief, mechanic_match, mechanics_library, strategy=strategy),
        max_tokens=2200,
        temperature=0.35,
    )
    print(f"  ✓ {strategy['label']} skeleton done")

    data = call_json(
        client,
        build_final_level_prompt(
            brief,
            mechanic_match,
            skeleton,
            background,
            response_points,
            hint,
            strategy=strategy,
        ),
        max_tokens=5200,
        temperature=0.45,
    )
    data = _attach_compiler_metadata(data, brief, mechanic_match, skeleton, strategy)

    violations = validate_level_constraints(data, mechanics_library=mechanics_library)
    if violations:
        print(
            f"  ⚠️ {strategy['label']} repair pass: {', '.join(violations)}",
            file=sys.stderr,
        )
        repaired = call_json(
            client,
            build_repair_prompt(data, violations, brief, mechanic_match, skeleton),
            max_tokens=5200,
            temperature=0.25,
        )
        data = _attach_compiler_metadata(repaired, brief, mechanic_match, skeleton, strategy)
        print(f"  ✓ {strategy['label']} repair done")

    data["_validation_report"] = validation_report(data, mechanics_library=mechanics_library)
    return {
        "strategy": strategy,
        "mechanic_match": mechanic_match,
        "skeleton": skeleton,
        "level": data,
    }


def choose_best_candidate(client, brief, candidates):
    report = call_json(
        client,
        build_candidate_evaluation_prompt(brief, candidates),
        max_tokens=2200,
        temperature=0.2,
    )
    selected_id = str(report.get("selected_candidate_id", "")).strip()
    by_id = {candidate["strategy"]["id"]: candidate for candidate in candidates}
    if selected_id not in by_id:
        scores = report.get("scores", {})
        selected_id = max(
            by_id,
            key=lambda candidate_id: _score_total(scores.get(candidate_id, {})),
        )
    selected = by_id[selected_id]["level"]
    scores = report.get("scores", {})
    selected["candidate_rank_report"] = report
    selected["quality_scores"] = scores.get(selected_id, {})
    print(f"  ✓ selected candidate: {selected_id}")
    return selected


def compile_level_design(client, post, background, response_points, hint, mechanics_library):
    """Run the structured meme → candidates → quality-ranked level compiler."""
    brief = call_json(client, build_design_brief_prompt(post), max_tokens=1600, temperature=0.35)
    print("  ✓ step 1 (design brief) done")

    candidates = []
    for strategy in CANDIDATE_STRATEGIES:
        candidates.append(
            compile_candidate(
                client=client,
                brief=brief,
                background=background,
                response_points=response_points,
                hint=hint,
                mechanics_library=mechanics_library,
                strategy=strategy,
            )
        )

    return choose_best_candidate(client, brief, candidates)


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
    parser.add_argument("--max-posts", type=int, default=None, help="Limit eligible posts for smoke tests")
    args = parser.parse_args()

    # Resolve paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = args.config or os.path.join(script_dir, "config.json")

    with open(config_path) as f:
        config = json.load(f)

    # Load .env from same directory as config
    load_dotenv(os.path.join(script_dir, ".env"), override=True)

    client = LLMClient()
    print(f"[synthesizer] Provider: {client.provider} — Model: {client.model}")
    if client.fallback:
        print(f"[synthesizer] Fallback: {client.fallback}")

    # Load context files
    background = load_text_file(os.path.join(script_dir, "background.txt"))
    response_points = load_text_file(os.path.join(script_dir, "response_point.txt"))
    hint = load_text_file(os.path.join(script_dir, "hint_from_Feishu.txt"))
    mechanics_path = os.path.join(script_dir, "mechanics_library.json")
    mechanics_library = load_mechanics_library(mechanics_path)
    print(f"[synthesizer] Loaded {len(mechanics_library)} Boxy mechanics")

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
    if args.max_posts is not None:
        eligible = eligible[: max(args.max_posts, 0)]
    print(f"[synthesizer] {len(eligible)}/{len(all_posts)} posts have descriptions")

    if not eligible:
        print("[synthesizer] No eligible posts, skipping.", file=sys.stderr)
        sys.exit(0)

    # Generate level designs via structured compiler: brief → mechanic → skeleton → final JSON.
    results = {}
    for i, post in enumerate(eligible):
        print(f"[{i+1}/{len(eligible)}] Generating: {post['title']}")

        try:
            data = compile_level_design(
                client=client,
                post=post,
                background=background,
                response_points=response_points,
                hint=hint,
                mechanics_library=mechanics_library,
            )

            # Post-validation: check for forbidden interaction types
            violations = validate_level_constraints(data, mechanics_library=mechanics_library)
            if violations:
                violation_types = unique_violations(violations)
                print(f"  ⚠️ Constraint violation detected: {', '.join(violation_types)}", file=sys.stderr)
                data["_constraint_violations"] = violation_types
            else:
                print(f"  ✓ constraint check passed")
            data["_validation_report"] = validation_report(data, mechanics_library=mechanics_library)

            # Attach source metadata
            data["source"] = post.get("_source", "unknown")
            data["source_post_title"] = post["title"]
            data["source_post_url"] = post.get("url", "")
            source_understanding = condense_meme_understanding(post)
            if source_understanding:
                data["source_meme_understanding"] = source_understanding
            data["source_image_path"] = normalize_source_image_path(
                post.get("local_image_path", ""),
                script_dir,
            )

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
