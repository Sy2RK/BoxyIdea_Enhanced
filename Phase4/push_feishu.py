#!/usr/bin/env python3
"""Phase 4: Push the top 3 Boxy level designs to Feishu as interactive cards."""

import argparse
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


def load_env(script_dir: Path):
    """Load .env from Phase4 first, then fallback to Phase2."""
    env_path = script_dir / ".env"
    if not env_path.exists():
        env_path = script_dir.parent / "Phase2" / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def get_tenant_token(app_id: str, app_secret: str) -> str:
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


def build_card(level_data: dict) -> dict:
    """Build Feishu interactive card from level data."""
    level_name = level_data.get("level_name", "Unknown Level")
    meme_inspiration = level_data.get("meme_inspiration", "")
    surface_layer = level_data.get("surface_layer", "")
    misdirection_layer = level_data.get("misdirection_layer", "")
    full_game_flow = level_data.get("full_game_flow", "")
    hint_design = level_data.get("hint_design", {})
    source_post_url = level_data.get("source_post_url", "")

    hint_text = hint_design.get("hint_text", "") if isinstance(hint_design, dict) else ""
    hint_surface = hint_design.get("surface_meaning", "") if isinstance(hint_design, dict) else ""
    hint_actual = hint_design.get("actual_meaning", "") if isinstance(hint_design, dict) else ""

    elements = []

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
    if hint_text:
        hint_md = f"**提示语**: {hint_text}\n"
        if hint_surface:
            hint_md += f"- 表面含义: {hint_surface}\n"
        if hint_actual:
            hint_md += f"- 实际含义: {hint_actual}"
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**提示设计**\n{hint_md.strip()}"
            }
        })

    # Source link
    if source_post_url:
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**来源**: [{source_post_url}]({source_post_url})"
            }
        })

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"Boxy 关卡设计: {level_name}"},
                "template": "purple",
            },
            "elements": elements,
        },
    }


def push_card(token: str, chat_id: str, card_payload: dict):
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


def main():
    parser = argparse.ArgumentParser(description="Phase 4: Push top 3 Boxy levels to Feishu")
    parser.add_argument("--input", default=None, help="Path to Phase3_result.txt")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    load_env(script_dir)

    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    chat_id = os.environ.get("FEISHU_CHAT_ID", "")

    if not app_id or not app_secret or not chat_id:
        print("[error] Missing FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_CHAT_ID in .env", file=sys.stderr)
        sys.exit(1)

    input_path = Path(args.input) if args.input else script_dir.parent / "Phase3" / "output" / "Phase3_result.txt"
    if not input_path.exists():
        print(f"[error] Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    try:
        level_data = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[error] Failed to parse input JSON: {e}", file=sys.stderr)
        sys.exit(1)

    # Handle fallback text
    if isinstance(level_data, str):
        print(f"[error] Input contains fallback text: {level_data}", file=sys.stderr)
        sys.exit(1)

    # Support either a single object or a list of objects
    levels = level_data if isinstance(level_data, list) else [level_data]

    output_dir = script_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Pushing to Feishu...")
    token = get_tenant_token(app_id, app_secret)

    success_count = 0
    for i, level in enumerate(levels, start=1):
        print(f"\n[{i}/{len(levels)}] Building and pushing card for: {level.get('level_name', 'Unknown')}")
        card = build_card(level)
        card_path = output_dir / f"feishu_card_{i}.json"
        card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Card JSON saved: {card_path}")

        try:
            result = push_card(token, chat_id, card)
            success_count += 1
            print("Push successful:")
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except requests.exceptions.HTTPError as e:
            resp_body = ""
            if e.response is not None:
                try:
                    resp_body = e.response.json()
                except Exception:
                    resp_body = e.response.text
            print(f"Push failed: {e}")
            print(f"Feishu response: {resp_body}")
            # Provide actionable guidance for known error codes
            if isinstance(resp_body, dict) and resp_body.get("code") == 230002:
                print(f"\n[action required] The bot is not a member of the target chat (chat_id: {chat_id}).")
                print("Please add this bot to the Feishu group/chat, or verify FEISHU_CHAT_ID is correct.")

    print(f"\n[{success_count}/{len(levels)}] cards pushed successfully.")
    if success_count == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
