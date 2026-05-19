#!/usr/bin/env python3
"""Shared design validation utilities for Boxy meme-to-level generation."""

import json
import os
import re


FORBIDDEN_PATTERNS = [
    (r"拖[动拽].{0,24}[文词字]", "文字拖动"),
    (r"拖[动拽].{0,24}(词块|文字|单词|提示文本|hint)", "文字拖动"),
    (r"\bdrag(?:ging)?\b.{0,32}\b(text|word|letter)\b", "文字拖动"),
    (r"点击.{0,24}(文字|文本|单词|词块|标签|提示语|牌子)", "文字点击"),
    (r"点.{0,24}(文字|文本|单词|词块|标签|提示语|牌子)", "文字点击"),
    (r"\b(click|tap)\b.{0,32}\b(text|word|letter|label|caption)\b", "文字点击"),
    (r"牌子翻成", "文字状态变化"),
    (r"拖[动拽].{0,24}(UI|按钮|标签|图标|控件)", "UI拖动"),
    (r"\bdrag(?:ging)?\b.{0,32}\b(button|ui|label|icon)\b", "UI拖动"),
    (r"(陀螺仪|加速计|摇晃手机|摄像头|相机)", "手机硬件"),
    (r"(gyroscope|accelerometer|shake.{0,12}phone|camera)", "手机硬件"),
    (r"(宗教|十字架|圣经|religious)", "宗教元素"),
]


ABSTRACT_CORE_TERMS = [
    "ui",
    "菜单",
    "设置",
    "控件",
    "按钮",
    "图标",
    "标签",
    "标签牌",
    "身份牌",
    "候选人标签牌",
    "终端",
    "系统终端",
    "身份识别",
    "登录",
    "账号",
    "扫描",
    "识别槽",
    "隐藏切换",
    "开关面板",
]


CORE_ACTION_TERMS = [
    "核心",
    "关键",
    "唯一",
    "触发",
    "生成",
    "改变",
    "切换",
    "放入",
    "拖入",
    "点击",
    "开启",
    "解锁",
    "通关",
    "解决",
    "谜题",
    "交互",
]


WORLD_SWITCH_TERMS = [
    "物理开关",
    "物理按钮",
    "地面开关",
    "地面按钮",
    "压力板",
    "机关",
    "拉杆",
    "world switch",
    "physical switch",
]


def _default_library_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "mechanics_library.json")


def load_mechanics_library(path=None):
    """Load the Boxy mechanic library."""
    library_path = path or _default_library_path()
    with open(library_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("mechanics library must be a list")
    return data


def mechanics_by_id(mechanics_library):
    return {
        item.get("id"): item
        for item in mechanics_library
        if isinstance(item, dict) and item.get("id")
    }


def format_mechanics_for_prompt(mechanics_library):
    """Render mechanic library into compact prompt text."""
    blocks = []
    for item in mechanics_library:
        blocks.append(
            "\n".join([
                f"ID: {item.get('id', '')}",
                f"Name: {item.get('name', '')}",
                f"Wrong expectation: {item.get('wrong_expectation', '')}",
                f"Reversal: {item.get('reversal', '')}",
                f"Usable when: {' | '.join(item.get('usable_when', []))}",
                f"Allowed actions: {' | '.join(item.get('allowed_actions', []))}",
                f"Forbidden: {' | '.join(item.get('forbidden', []))}",
            ])
        )
    return "\n\n".join(blocks)


def unique_violations(violations):
    seen = set()
    result = []
    for violation in violations:
        if not violation:
            continue
        text = str(violation)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _flatten_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    return str(value)


def _level_text(level_data):
    fields = [
        level_data.get("level_name", ""),
        level_data.get("meme_inspiration", ""),
        level_data.get("surface_layer", ""),
        level_data.get("misdirection_layer", ""),
        level_data.get("full_game_flow", ""),
        level_data.get("hint_design", {}),
        level_data.get("_design_brief", {}),
        level_data.get("_mechanic_match", {}),
        level_data.get("_level_skeleton", {}),
    ]
    for elem in level_data.get("elements", []):
        fields.append(elem)
    return _flatten_text(fields)


def _count_steps(level_data):
    skeleton = level_data.get("_level_skeleton")
    if isinstance(skeleton, dict) and isinstance(skeleton.get("player_steps"), list):
        return len([step for step in skeleton["player_steps"] if str(step).strip()])

    flow = str(level_data.get("full_game_flow", ""))
    numbered = re.findall(r"(?:^|\n|\s)(?:\d+[\.\、:]|Step\s+\d+[:.])", flow)
    if numbered:
        return len(numbered)
    sentences = [part for part in re.split(r"[。.!?；;]\s*", flow) if part.strip()]
    return len(sentences)


def _is_world_switch(name, role):
    text = f"{name} {role}".lower()
    return any(term.lower() in text for term in WORLD_SWITCH_TERMS)


def _element_is_abstract_core(elem):
    if not isinstance(elem, dict):
        return False
    name = str(elem.get("name", ""))
    role = str(elem.get("role", ""))
    layer = str(elem.get("layer", ""))
    text = f"{name} {role}".lower()

    if _is_world_switch(name, role):
        return False

    has_abstract = any(term.lower() in text for term in ABSTRACT_CORE_TERMS)
    has_core_action = any(term.lower() in text for term in CORE_ACTION_TERMS)
    ui_layer = layer.strip().lower() in {"ui", "元系统", "meta", "system"}

    return (ui_layer and has_core_action) or (has_abstract and has_core_action)


def validate_constraints(level_data, mechanics_library=None, require_compiler_fields=False):
    """Return a list of human-readable violations.

    The rules are intentionally conservative: it is better to reject a dreamy
    design early than to spend image-generation budget on a non-playable idea.
    """
    violations = []
    combined_text = _level_text(level_data)

    for pattern, violation_type in FORBIDDEN_PATTERNS:
        if re.search(pattern, combined_text, re.IGNORECASE):
            violations.append(violation_type)

    hint = level_data.get("hint_design", {})
    if isinstance(hint, dict) and hint.get("participates_in_gameplay"):
        violations.append("提示文本参与解谜")

    elements = level_data.get("elements", [])
    if isinstance(elements, list):
        puzzle_elements = [elem for elem in elements if isinstance(elem, dict)]
        if len(puzzle_elements) > 3:
            violations.append("核心元素超过3个")
        for elem in puzzle_elements:
            if _element_is_abstract_core(elem):
                violations.append("UI或抽象系统核心解谜")
                break

    if _count_steps(level_data) > 3:
        violations.append("关键步骤超过3步")

    skeleton = level_data.get("_level_skeleton")
    if isinstance(skeleton, dict):
        world_objects = skeleton.get("world_objects")
        if isinstance(world_objects, list) and len([o for o in world_objects if str(o).strip()]) > 3:
            violations.append("骨架对象超过3个")

    binding = level_data.get("meme_binding")
    if isinstance(binding, dict) and binding.get("would_lose_joke_if_action_removed") is False:
        violations.append("笑点未绑定到操作")

    risk = level_data.get("implementation_risk")
    if isinstance(risk, dict):
        if risk.get("relies_on_text_explanation"):
            violations.append("依赖文字解释")

    if require_compiler_fields:
        for key, label in [
            ("_design_brief", "缺少设计简报"),
            ("_mechanic_match", "缺少机制匹配"),
            ("_level_skeleton", "缺少关卡骨架"),
            ("playability_contract", "缺少可玩性契约"),
            ("meme_binding", "缺少梗绑定说明"),
            ("implementation_risk", "缺少实现风险说明"),
            ("visual_brief", "缺少视觉简报"),
        ]:
            if not isinstance(level_data.get(key), dict):
                violations.append(label)

    if mechanics_library:
        valid_ids = mechanics_by_id(mechanics_library)
        mechanic_id = ""
        match = level_data.get("_mechanic_match")
        if isinstance(match, dict):
            mechanic_id = str(match.get("mechanic_id", "")).strip()
        if not mechanic_id and isinstance(skeleton, dict):
            mechanic_id = str(skeleton.get("mechanic_id", "")).strip()
        if mechanic_id and mechanic_id not in valid_ids:
            violations.append("未知机制ID")

    return unique_violations(violations)


def validation_report(level_data, mechanics_library=None):
    violations = validate_constraints(level_data, mechanics_library=mechanics_library)
    return {
        "passed": not violations,
        "violations": violations,
        "step_count": _count_steps(level_data),
        "element_count": len(level_data.get("elements", [])) if isinstance(level_data.get("elements"), list) else 0,
        "has_playability_contract": isinstance(level_data.get("playability_contract"), dict),
        "has_meme_binding": isinstance(level_data.get("meme_binding"), dict),
        "has_visual_brief": isinstance(level_data.get("visual_brief"), dict),
    }
