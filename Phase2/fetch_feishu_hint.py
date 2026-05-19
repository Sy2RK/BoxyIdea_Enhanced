#!/usr/bin/env python3
"""Fetch hint content from Feishu wiki/doc and write it to hint_from_Feishu.txt."""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

WIKI_URL = "https://scnmrtumk0zm.feishu.cn/wiki/XQFPwrS4Oi34UxkiJYxcVxgOncc"


def load_env(script_dir: Path):
    """Load .env from Phase2 first, then also load Phase4/.env if it exists (to pick up Feishu credentials)."""
    env_path = script_dir / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
    env_path_phase4 = script_dir.parent / "Phase4" / ".env"
    if env_path_phase4.exists():
        load_dotenv(env_path_phase4, override=True)


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


def resolve_wiki_token(wiki_token: str, tenant_token: str) -> str:
    """Resolve Feishu wiki token to docx document_id (obj_token)."""
    resp = requests.get(
        "https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node",
        headers={"Authorization": f"Bearer {tenant_token}"},
        params={"token": wiki_token},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"wiki resolve failed: {data}")
    node = data.get("data", {}).get("node", {})
    obj_token = node.get("obj_token")
    obj_type = node.get("obj_type")
    if not obj_token:
        raise RuntimeError(f"No obj_token found for wiki token {wiki_token}")
    if obj_type != "docx":
        raise RuntimeError(f"Wiki node is not a docx document (type: {obj_type})")
    return obj_token


def fetch_doc_raw_content(document_id: str, tenant_token: str) -> str:
    """Fetch raw text content from a Feishu docx document."""
    resp = requests.get(
        f"https://open.feishu.cn/open-apis/docx/v1/documents/{document_id}/raw_content",
        headers={"Authorization": f"Bearer {tenant_token}"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"docx raw_content failed: {data}")
    return data.get("data", {}).get("content", "")


def extract_wiki_token(url: str) -> str:
    """Extract wiki token from a Feishu wiki URL."""
    match = re.search(r"/wiki/([a-zA-Z0-9_-]+)", url)
    if not match:
        raise ValueError(f"Cannot extract wiki token from URL: {url}")
    return match.group(1)


def update_hint_file(output_path: Path, content: str):
    """Write fetched content to hint file."""
    output_path.write_text(content, encoding="utf-8")
    print(f"[fetch_feishu_hint] Updated {output_path} ({len(content)} chars)")


def main():
    parser = argparse.ArgumentParser(description="Fetch hint from Feishu wiki and update hint_from_Feishu.txt")
    parser.add_argument("--output", default=None, help="Path to output file (default: hint_from_Feishu.txt in script dir)")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    load_env(script_dir)

    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")

    if not app_id or not app_secret:
        print("[error] Missing FEISHU_APP_ID / FEISHU_APP_SECRET in .env", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output) if args.output else script_dir / "hint_from_Feishu.txt"

    try:
        wiki_token = extract_wiki_token(WIKI_URL)
        tenant_token = get_tenant_token(app_id, app_secret)
        document_id = resolve_wiki_token(wiki_token, tenant_token)
        content = fetch_doc_raw_content(document_id, tenant_token)
        update_hint_file(output_path, content)
    except Exception as e:
        print(f"[error] Failed to fetch Feishu hint: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
