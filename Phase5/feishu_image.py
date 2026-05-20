#!/usr/bin/env python3
"""Feishu image upload and card push with image support for Phase 5."""

import json
import os
import sys

import requests


DEFAULT_FEISHU_BASE_TOKEN = ""
DEFAULT_FEISHU_BASE_TABLE_ID = "tblla4v6G8LqAMeP"
DEFAULT_FEISHU_BASE_URL = "https://scnmrtumk0zm.feishu.cn/base/Ou7Pb9cJJao7CWsaCAmcQQ2unph?table=tblla4v6G8LqAMeP"


def get_tenant_token(app_id, app_secret):
    """Get Feishu tenant access token."""
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"tenant token failed: {data}")
    return data["tenant_access_token"]


def upload_image(token, image_path):
    """Upload an image to Feishu and return the image_key.

    Args:
        token: Feishu tenant access token.
        image_path: Local path to the image file.

    Returns:
        image_key string (e.g. 'img_v3_xxxxx').

    Raises:
        RuntimeError: If upload fails.
    """
    import os
    path = str(image_path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Image file not found: {path}")

    # Check file size (Feishu limit is ~25MB for images)
    file_size = os.path.getsize(path)
    if file_size > 25 * 1024 * 1024:
        print(f"[feishu] Warning: Image size {file_size / 1024 / 1024:.1f}MB exceeds 25MB limit", file=sys.stderr)

    with open(path, "rb") as f:
        resp = requests.post(
            "https://open.feishu.cn/open-apis/im/v1/images",
            headers={"Authorization": f"Bearer {token}"},
            data={"image_type": "message"},
            files={"image": f},
            timeout=60,
        )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Image upload failed: {data}")
    image_key = data.get("data", {}).get("image_key")
    if not image_key:
        raise RuntimeError(f"No image_key in response: {data}")
    print(f"[feishu] Image uploaded: {image_key} ({file_size / 1024:.1f}KB)")
    return image_key


def build_level_title(level_data):
    """Build the card title for a level design."""
    level_name = level_data.get("level_name", "Unknown Level")
    return f"Boxy 关卡设计: {level_name}"


def format_hint_design(hint_design, markdown=True):
    """Format hint design for card display."""
    if not isinstance(hint_design, dict):
        return ""
    hint_text = hint_design.get("hint_text", "")
    hint_surface = hint_design.get("surface_meaning", "")
    hint_actual = hint_design.get("actual_meaning", "")
    if not hint_text:
        return ""
    hint_label = "**提示语**" if markdown else "提示语"
    lines = [f"{hint_label}: {hint_text}"]
    if hint_surface:
        lines.append(f"- 表面含义: {hint_surface}")
    if hint_actual:
        lines.append(f"- 实际含义: {hint_actual}")
    return "\n".join(lines)


def format_quality_summary(level_data):
    """Format Phase2/Phase3 quality metadata for review cards."""
    gate = level_data.get("_phase3_quality_gate")
    scores = {}
    keep_reason = ""
    risks = []
    if isinstance(gate, dict):
        scores = gate.get("scores") or {}
        keep_reason = gate.get("keep_reason") or gate.get("summary") or ""
        risks = gate.get("main_risks") or []

    if not scores:
        scores = level_data.get("quality_scores") or {}
    rank_report = level_data.get("candidate_rank_report")
    if not keep_reason and isinstance(rank_report, dict):
        keep_reason = rank_report.get("selection_reason", "")
        risks = rank_report.get("main_risks", risks)

    score_keys = [
        ("meme_fidelity", "梗绑定"),
        ("playability", "可玩性"),
        ("boxy_fit", "Boxy适配"),
        ("implementation_feasibility", "实现可行"),
        ("visual_clarity", "视觉清晰"),
    ]
    score_parts = []
    total = scores.get("total")
    for key, label in score_keys:
        value = scores.get(key)
        if value is not None:
            score_parts.append(f"{label} {value}/5")
    if total is None and score_parts:
        try:
            total = sum(int(scores.get(key, 0)) for key, _ in score_keys)
        except (TypeError, ValueError):
            total = None

    lines = []
    if total is not None:
        lines.append(f"**可应用性评分**: {total}/25")
    elif score_parts:
        lines.append("**可应用性评分**")
    if score_parts:
        lines.append(" / ".join(score_parts))
    if keep_reason:
        lines.append(f"**保留理由**: {keep_reason}")
    if risks:
        clean_risks = [str(item).strip() for item in risks if str(item).strip()]
        if clean_risks:
            lines.append("**主要风险**: " + "；".join(clean_risks[:3]))
    return "\n".join(lines)


def build_card_with_image(
    level_data,
    image_key,
    base_url=DEFAULT_FEISHU_BASE_URL,
    source_image_key=None,
):
    """Build a Feishu interactive card with images for a level design.

    Args:
        level_data: Level design dict.
        image_key: Feishu image_key for the generated level design image.
        base_url: URL for the "查看多维表格" button.
        source_image_key: Optional Feishu image_key for the original meme image.

    Returns:
        Card payload dict ready for push_card_with_image().
    """
    meme_inspiration = level_data.get("meme_inspiration", "")
    surface_layer = level_data.get("surface_layer", "")
    misdirection_layer = level_data.get("misdirection_layer", "")
    full_game_flow = level_data.get("full_game_flow", "")
    hint_design = level_data.get("hint_design", {})
    source_post_url = level_data.get("source_post_url", "")

    elements = []

    # Original meme image
    if source_image_key:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "**原 meme 图**"},
        })
        elements.append({
            "tag": "img",
            "img_key": source_image_key,
            "alt": {"tag": "plain_text", "content": "原 meme 图"},
        })
        elements.append({"tag": "hr"})

    # Level concept image
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": "**关卡设计图**"},
    })
    elements.append({
        "tag": "img",
        "img_key": image_key,
        "alt": {"tag": "plain_text", "content": "关卡概念图"},
    })

    # Divider
    elements.append({"tag": "hr"})

    quality_md = format_quality_summary(level_data)
    if quality_md:
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": quality_md,
            },
        })

    # Meme inspiration
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"**灵感来源**\n{meme_inspiration}"
        }
    })

    # Surface layer
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"**表层**\n{surface_layer}"
        }
    })

    # Misdirection layer
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"**误导层**\n{misdirection_layer}"
        }
    })

    # Full game flow
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"**完整流程**\n{full_game_flow}"
        }
    })

    # Hint design
    hint_md = format_hint_design(hint_design, markdown=True)
    if hint_md:
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**提示设计**\n{hint_md}"
            }
        })

    # Source link
    if source_post_url:
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**来源**: [查看来源]({source_post_url})"
            }
        })

    # Button to Feishu Base
    if base_url:
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "查看多维表格"},
                    "type": "primary",
                    "url": base_url,
                }
            ],
        })

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": build_level_title(level_data)},
                "template": "purple",
            },
            "elements": elements,
        },
    }


def push_card_with_image(token, chat_id, card_payload):
    """Push a card (with or without image) to a Feishu group chat.

    Args:
        token: Feishu tenant access token.
        chat_id: Target Feishu chat ID.
        card_payload: Card payload dict from build_card_with_image().

    Returns:
        Response data dict from Feishu API.

    Raises:
        RuntimeError: If push fails.
    """
    resp = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages",
        params={"receive_id_type": "chat_id"},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json={
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": json.dumps(card_payload["card"], ensure_ascii=False),
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"push failed: {data}")
    return data
