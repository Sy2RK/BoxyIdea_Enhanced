#!/usr/bin/env python3
"""Convert Boxy level design JSON into image generation prompts for GPT-Image2."""

import re


MAX_VISIBLE_PUZZLE_OBJECTS = 3


LEVEL_NUMBER_KEYWORDS = (
    "level badge",
    "level number",
    "level counter",
    "level tile",
    "关卡数",
    "关卡号",
    "关卡数字",
    "左上角数字",
    "左上角关卡",
)


BOXY_REFERENCE_STYLE = (
    "Match the actual Boxy game screenshots, not a generic platformer: a panoramic "
    "wide horizontal mobile screen around 2048x945 (about 2.17:1), hand-drawn comic / "
    "sketchbook art, warm off-white paper texture with faint notebook lines, pale green "
    "bushes and soft background silhouettes, loose pencil outlines, slightly wobbly "
    "hand-painted shapes, thin black ground line, small mossy blue-green floating "
    "platform strips, a small cardboard-box character with black stick legs and round "
    "black eyes, pink hand-drawn doors with a heart/check emblem, chunky dark brown "
    "UI buttons with simple yellow icons, and very clean composition."
)


NEGATIVE_IMAGE_GUIDANCE = (
    "Do NOT create a top-down map, isometric diorama, concept-art poster, blueprint, "
    "flowchart, multi-panel explanation, meme collage, realistic 3D render, pixel art, "
    "dense labels, numbered walkthrough, arrows, legends, title cards, explanatory callouts, "
    "extra UI windows, inventory bars, or crowded props. "
    "Do NOT show the whole solution sequence; show one playable in-game moment. "
    "Do NOT use dark beveled tile blocks, brick walls, block mazes, crates, flags, blue-sky "
    "generic platformer backgrounds, polished vector-game art, 3D lighting, square 4:3 framing, "
    "or a plain orange/white cube hero. The character must look like a hand-drawn cardboard box "
    "with stick legs, and platforms must look like small drawn grass/moss strips on paper."
)


STYLE_INSTRUCTIONS = {
    "game_screenshot": (
        BOXY_REFERENCE_STYLE
        + " It must look like a clean in-game screenshot, not a design review board: no title text, "
        "no arrows, no legend, no bottom explanation strip, and no labels naming puzzle objects."
    ),
    "boxy_reference": (
        BOXY_REFERENCE_STYLE
    ),
    "concept_art": (
        "Keep the same Boxy hand-drawn comic style, but make it slightly looser like "
        "production concept art for a single mobile level screenshot. Still keep the "
        "simple horizontal game UI and sparse puzzle layout."
    ),
    "diagram": (
        "Use the same Boxy hand-drawn paper style, but make the puzzle objects a little "
        "clearer for internal review. Keep labels minimal and diegetic, like text already "
        "written on signs in the level. Avoid technical annotation clutter."
    ),
}


def _compact_text(value, max_chars=420):
    """Collapse whitespace and cap long LLM fields so the image prompt stays visual."""
    if not value:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:max_chars].rstrip() + ("..." if len(text) > max_chars else "")


def _extract_visual_beats(full_game_flow, max_beats=3):
    """Keep only the first few gameplay beats; the image should not become a walkthrough."""
    flow = _compact_text(full_game_flow, max_chars=900)
    if not flow:
        return []

    # Prefer numbered Chinese/English walkthrough steps if the model produced them.
    parts = re.split(r"(?:^|\s)(?:\d+[\.\、:]|Step\s+\d+[:.]?)\s*", flow)
    beats = [p.strip(" ;；。") for p in parts if p.strip(" ;；。")]
    if len(beats) <= 1:
        beats = re.split(r"[。.!?；;]\s*", flow)
        beats = [p.strip() for p in beats if p.strip()]
    return beats[:max_beats]


def _uses_level_number_mechanic(level_data):
    """Infer whether the level number badge is part of the puzzle."""
    fields = [
        level_data.get("level_name", ""),
        level_data.get("surface_layer", ""),
        level_data.get("misdirection_layer", ""),
        level_data.get("full_game_flow", ""),
        level_data.get("meme_inspiration", ""),
    ]
    hint_design = level_data.get("hint_design", {})
    if isinstance(hint_design, dict):
        fields.extend([
            hint_design.get("hint_text", ""),
            hint_design.get("actual_meaning", ""),
        ])
    for elem in level_data.get("elements", []):
        if isinstance(elem, dict):
            fields.extend([elem.get("name", ""), elem.get("role", "")])
    text = " ".join(str(field).lower() for field in fields if field)
    return any(keyword in text for keyword in LEVEL_NUMBER_KEYWORDS)


def build_image_prompt(level_data, style="game_screenshot"):
    """Convert a level design dict into an image generation prompt for GPT-Image2.

    Args:
        level_data: A dict containing the level design fields (level_name,
            surface_layer, misdirection_layer, elements, hint_design, etc.).
        style: One of 'game_screenshot', 'concept_art', 'diagram'.

    Returns:
        A string prompt suitable for GPT-Image2 image generation.
    """
    level_name = level_data.get("level_name", "Unknown Level")
    surface = level_data.get("surface_layer", "")
    misdirection = level_data.get("misdirection_layer", "")
    elements = level_data.get("elements", [])
    meme_inspiration = level_data.get("meme_inspiration", "")
    visual_brief = level_data.get("visual_brief")
    if not isinstance(visual_brief, dict):
        visual_brief = {}

    # Build a deliberately small elements description. The real Boxy screens are sparse;
    # pushing every JSON element into the image causes clutter and wrong visual output.
    element_descs = []
    for elem in elements[:MAX_VISIBLE_PUZZLE_OBJECTS]:
        if isinstance(elem, dict):
            name = elem.get("name", "")
            role = elem.get("role", "")
            layer = elem.get("layer", "")
            if name:
                desc = f"- {name}"
                if layer:
                    desc += f" ({layer} layer)"
                if role:
                    desc += f": {_compact_text(role, max_chars=120)}"
                element_descs.append(desc)
    elements_text = "\n".join(element_descs) if element_descs else "- One simple puzzle object or sign"
    # Get style instruction
    style_instruction = STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS["game_screenshot"])
    visual_beats = _extract_visual_beats(level_data.get("full_game_flow", ""))
    beats_text = "\n".join(f"- {beat}" for beat in visual_beats) if visual_beats else "- A simple 1 to 3 step puzzle moment"
    must_show = visual_brief.get("must_show") or []
    avoid_showing = visual_brief.get("avoid_showing") or []
    focal_objects = visual_brief.get("focal_objects") or []
    visual_brief_text = ""
    if visual_brief:
        visual_brief_text = f"""
Phase5 visual brief:
- Screenshot state to render: {visual_brief.get('screenshot_state', 'reversal_visible')}
- Must show: {'; '.join(str(item) for item in must_show[:4]) or 'the playable reversal clearly'}
- Focal objects: {'; '.join(str(item) for item in focal_objects[:3]) or 'the core puzzle object and the end door'}
- Avoid showing: {'; '.join(str(item) for item in avoid_showing[:4]) or 'extra explanatory clutter'}"""
    level_badge_rule = (
        "Only show the top-left level badge because the level number itself is part of this puzzle."
        if _uses_level_number_mechanic(level_data)
        else "Leave the top-left level badge area empty; do NOT draw a level number badge."
    )

    prompt = f"""Create ONE screenshot of an actual playable level from the mobile puzzle platformer game "Boxy".

Internal level name (do not render as text): {level_name}

Internal meme inspiration (do not render as text): {meme_inspiration}

Required visual style:
{style_instruction}

Camera and layout:
- Side-view 2D mobile platformer screenshot, panoramic 2048x945-style horizontal frame
- Warm cream paper / notebook background with faint horizontal lines and soft pastel scenery
- Thin black ground line, a few small mossy floating platform strips, one start area, one end door area
- Built-in game UI only: restart / pause / hint buttons top, basket icon top-right, left/right/jump controls at bottom
- {level_badge_rule}
- Keep the UI simple and similar to the provided Boxy reference screenshots
- Do not render the level name, prompt, design notes, arrows, object labels, or a legend inside the image

Scene to depict:
{_compact_text(surface, max_chars=360)}

Main misdirection to imply visually:
{_compact_text(misdirection, max_chars=260)}

Visible puzzle objects, maximum {MAX_VISIBLE_PUZZLE_OBJECTS}:
{elements_text}

Gameplay beats to imply, maximum 3 and not as a sequence:
{beats_text}
{visual_brief_text}

Strict simplicity rules:
- Show no more than 3 puzzle-relevant objects besides Boxy, doors, platforms, and normal UI
- The puzzle should look solvable in 1 to 3 interactions
- Use large empty space and clean staging; do not fill the scene with props
- Avoid readable text inside the play area unless it is a tiny diegetic icon/sign that would exist in the world
- No arrows, dashed paths, captions, bottom explanation strip, object names, title text, or walkthrough markers

Negative guidance:
{NEGATIVE_IMAGE_GUIDANCE}

Reference image rule:
The attached reference screenshots are for visual style only: paper texture, hand-drawn line quality, UI placement, button shape, character style, door style, and overall color mood.
Do NOT copy their level layout, puzzle content, title text, key poster, sketch door, door positions, platform positions, or any specific objects from the reference screenshots.
Do NOT paint over, extend, trace, collage, or edit the reference screenshots.
Generate a completely new original Boxy level screenshot for the level described above, while matching only the art direction and UI style.

Important: This is not a meme image or a design document. It must be a newly generated original gameplay screenshot in the hand-drawn comic style of the two reference screenshots."""

    return prompt
