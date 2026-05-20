#!/usr/bin/env python3
"""Phase 4: Push the top 3 Boxy level designs to Feishu as interactive cards."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(path, override=False):
        env_path = Path(path)
        if not env_path.exists():
            return False
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if override or key not in os.environ:
                os.environ[key] = value.strip()
        return True


DEFAULT_FEISHU_BASE_TOKEN = ""
DEFAULT_FEISHU_BASE_TABLE_ID = "tblla4v6G8LqAMeP"
DEFAULT_FEISHU_BASE_URL = "https://scnmrtumk0zm.feishu.cn/base/Ou7Pb9cJJao7CWsaCAmcQQ2unph?table=tblla4v6G8LqAMeP"
SOURCE_LINK_PATTERN = re.compile(r"\[查看来源\]\((.*?)\)")
SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def load_env(script_dir: Path):
    """Load .env from Phase4 first, then fallback to Phase2."""
    env_path = script_dir / ".env"
    if not env_path.exists():
        env_path = script_dir.parent / "Phase2" / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)


def get_target_chat_id() -> str:
    """Resolve the target Feishu chat.

    Set FEISHU_PUSH_TARGET=test to force the pipeline to use FEISHU_TEST_CHAT_ID.
    In test mode we intentionally do not fall back to FEISHU_CHAT_ID, so the
    production chat cannot receive messages by accident.
    """
    push_target = os.environ.get("FEISHU_PUSH_TARGET", "").strip().lower()
    if push_target == "test":
        return os.environ.get("FEISHU_TEST_CHAT_ID", "").strip()
    return os.environ.get("FEISHU_CHAT_ID", "").strip()


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


def resolve_source_image_path(level_data: dict, project_root: Path) -> Path | None:
    """Resolve a level's original meme image path from Phase 2 metadata."""
    raw_path = str(level_data.get("source_image_path") or "").strip()
    if not raw_path:
        return None

    path = Path(raw_path).expanduser()
    candidates = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.extend([
            project_root / path,
            project_root / "Phase1" / path,
            project_root / "Phase1" / "output" / "images" / path.name,
        ])

    for candidate in candidates:
        if candidate.exists() and candidate.suffix.lower() in SUPPORTED_IMAGE_EXTS:
            return candidate
    return None


def upload_image(token: str, image_path: Path) -> str:
    """Upload an image to Feishu and return its image_key."""
    file_size = image_path.stat().st_size
    if file_size > 25 * 1024 * 1024:
        print(
            f"[feishu] Warning: source meme image is {file_size / 1024 / 1024:.1f}MB",
            file=sys.stderr,
        )

    with image_path.open("rb") as f:
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
        raise RuntimeError(f"image upload failed: {data}")
    image_key = data.get("data", {}).get("image_key")
    if not image_key:
        raise RuntimeError(f"image upload did not return image_key: {data}")
    print(f"[feishu] Source meme uploaded: {image_key} ({file_size / 1024:.1f}KB)")
    return image_key


def build_level_title(level_data: dict) -> str:
    level_name = level_data.get("level_name", "Unknown Level")
    return f"Boxy 关卡设计: {level_name}"


def format_hint_design(hint_design, markdown: bool = False) -> str:
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


def build_card(
    level_data: dict,
    base_url: str = DEFAULT_FEISHU_BASE_URL,
    source_image_key: str | None = None,
) -> dict:
    """Build Feishu interactive card from level data."""
    meme_inspiration = level_data.get("meme_inspiration", "")
    surface_layer = level_data.get("surface_layer", "")
    misdirection_layer = level_data.get("misdirection_layer", "")
    full_game_flow = level_data.get("full_game_flow", "")
    hint_design = level_data.get("hint_design", {})
    source_post_url = level_data.get("source_post_url", "")

    elements = []

    if source_image_key:
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**原 meme 图**",
            },
        })
        elements.append({
            "tag": "img",
            "img_key": source_image_key,
            "alt": {"tag": "plain_text", "content": "原 meme 图"},
        })
        elements.append({"tag": "hr"})

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


def extract_card_source_url(card_payload: dict) -> str:
    elements = card_payload.get("card", {}).get("elements", [])
    for element in elements:
        if element.get("tag") != "div":
            continue
        content = element.get("text", {}).get("content", "")
        if not content.startswith("**来源**"):
            continue
        match = SOURCE_LINK_PATTERN.search(content)
        if match:
            return match.group(1)
    return ""


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


def get_message_push_datetime(push_result: dict) -> datetime:
    data = push_result.get("data", {}) if isinstance(push_result, dict) else {}
    create_time = data.get("create_time") or data.get("message", {}).get("create_time")
    if create_time:
        try:
            timestamp = int(create_time)
            if timestamp > 10_000_000_000:
                timestamp = timestamp / 1000
            return datetime.fromtimestamp(timestamp)
        except (TypeError, ValueError):
            pass
    return datetime.now()


def build_bitable_fields(level_data: dict, pushed_at: datetime, source_url: str = "") -> dict:
    fields = {
        "关卡名": build_level_title(level_data),
        "灵感来源": level_data.get("meme_inspiration", ""),
        "表层": level_data.get("surface_layer", ""),
        "误导层": level_data.get("misdirection_layer", ""),
        "完整流程": level_data.get("full_game_flow", ""),
        "提示设计": format_hint_design(level_data.get("hint_design", {})),
        "推送时间": int(pushed_at.timestamp() * 1000),
    }
    if source_url:
        fields["来源"] = {"text": "查看来源", "link": source_url}
    return fields


def append_bitable_record(token: str, base_token: str, table_id: str, fields: dict) -> dict:
    resp = requests.post(
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/records",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json={"fields": fields},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"bitable append failed: {data}")
    return data


def main():
    parser = argparse.ArgumentParser(description="Phase 4: Push top 3 Boxy levels to Feishu")
    parser.add_argument("--input", default=None, help="Path to Phase3_result.txt")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    load_env(script_dir)

    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    chat_id = get_target_chat_id()
    base_token = os.environ.get("FEISHU_BASE_TOKEN") or DEFAULT_FEISHU_BASE_TOKEN
    base_table_id = os.environ.get("FEISHU_BASE_TABLE_ID") or DEFAULT_FEISHU_BASE_TABLE_ID
    base_url = os.environ.get("FEISHU_BASE_URL") or DEFAULT_FEISHU_BASE_URL

    if not app_id or not app_secret or not chat_id:
        if os.environ.get("FEISHU_PUSH_TARGET", "").strip().lower() == "test":
            print("[error] Missing FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_TEST_CHAT_ID in .env", file=sys.stderr)
        else:
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
    sync_failed_count = 0
    for i, level in enumerate(levels, start=1):
        print(f"\n[{i}/{len(levels)}] Building and pushing card for: {level.get('level_name', 'Unknown')}")
        source_image_key = None
        source_image_path = resolve_source_image_path(level, script_dir.parent)
        if source_image_path:
            try:
                source_image_key = upload_image(token, source_image_path)
            except Exception as e:
                print(
                    f"[warn] Failed to upload source meme image {source_image_path}: {e}",
                    file=sys.stderr,
                )
        else:
            print("[warn] No local source meme image found for this level", file=sys.stderr)

        card = build_card(level, base_url=base_url, source_image_key=source_image_key)
        card_path = output_dir / f"feishu_card_{i}.json"
        card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Card JSON saved: {card_path}")

        try:
            result = push_card(token, chat_id, card)
            success_count += 1
            print("Push successful:")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            pushed_at = get_message_push_datetime(result)
            fields = build_bitable_fields(level, pushed_at, source_url=extract_card_source_url(card))
            try:
                append_bitable_record(token, base_token, base_table_id, fields)
                print(f"Synced to Feishu Base AI-ideas: {pushed_at.strftime('%Y/%m/%d')}")
            except Exception as e:
                sync_failed_count += 1
                print(f"[error] Failed to sync card to Feishu Base AI-ideas: {e}", file=sys.stderr)
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
        except Exception as e:
            print(f"Push failed: {e}")

    print(f"\n[{success_count}/{len(levels)}] cards pushed successfully.")
    if sync_failed_count:
        print(f"[error] {sync_failed_count} pushed cards failed to sync to Feishu Base.", file=sys.stderr)
        sys.exit(1)
    if success_count == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
