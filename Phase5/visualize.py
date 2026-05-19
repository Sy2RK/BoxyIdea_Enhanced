#!/usr/bin/env python3
"""Phase 5: Visualize Boxy level designs — generate concept images via ChatGPT and push to Feishu."""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Ensure Phase5 directory is in the Python path for local module imports
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from chatgpt_browser import ChatGPTBrowser
from image_prompt_builder import build_image_prompt
from feishu_image import (
    get_tenant_token,
    upload_image,
    build_card_with_image,
    push_card_with_image,
    format_hint_design,
    format_quality_summary,
    DEFAULT_FEISHU_BASE_TOKEN,
    DEFAULT_FEISHU_BASE_TABLE_ID,
    DEFAULT_FEISHU_BASE_URL,
)

SUPPORTED_SOURCE_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def load_env(script_dir):
    """Load .env from Phase5 first, then fallback to Phase4."""
    env_path = script_dir / ".env"
    if not env_path.exists():
        env_path = script_dir.parent / "Phase4" / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
        print(f"[visualize] Loaded env from {env_path}")
    else:
        print(f"[visualize] Warning: No .env file found", file=sys.stderr)


def get_target_chat_id():
    """Resolve the target Feishu chat.

    FEISHU_PUSH_TARGET=test forces FEISHU_TEST_CHAT_ID and deliberately avoids
    falling back to FEISHU_CHAT_ID, protecting the original group from test runs.
    """
    push_target = os.environ.get("FEISHU_PUSH_TARGET", "").strip().lower()
    if push_target == "test":
        return os.environ.get("FEISHU_TEST_CHAT_ID", "").strip()
    return os.environ.get("FEISHU_CHAT_ID", "").strip()


def resolve_reference_images(script_dir, config, cli_paths):
    """Resolve configured reference images or directories to local image files."""
    raw_paths = []
    if cli_paths:
        raw_paths.extend(cli_paths)
    env_paths = os.environ.get("REFERENCE_IMAGE_PATHS", "").strip()
    if env_paths:
        raw_paths.extend([p for p in env_paths.split(os.pathsep) if p])
    raw_paths.extend(config.get("reference_images", []))

    image_paths = []
    image_exts = {".png", ".jpg", ".jpeg", ".webp"}
    for raw_path in raw_paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = script_dir / path
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.suffix.lower() in image_exts:
                    image_paths.append(child)
        elif path.suffix.lower() in image_exts:
            image_paths.append(path)

    # Preserve order while dropping duplicates.
    seen = set()
    resolved = []
    for path in image_paths:
        key = str(path.resolve())
        if key not in seen:
            seen.add(key)
            resolved.append(path.resolve())
    return resolved


def resolve_source_image_path(project_root, level):
    """Resolve a level's original meme image path from Phase 2 metadata."""
    raw_path = str(level.get("source_image_path") or "").strip()
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
        if candidate.exists() and candidate.suffix.lower() in SUPPORTED_SOURCE_IMAGE_EXTS:
            return candidate.resolve()
    return None


def main():
    parser = argparse.ArgumentParser(description="Phase 5: Visualize Boxy level designs")
    parser.add_argument("--config", default=None, help="Path to config.json (default: same dir as script)")
    parser.add_argument("--input", default=None, help="Path to Phase3_result.txt (overrides config)")
    parser.add_argument("--style", default=None, help="Image style: game_screenshot, boxy_reference, concept_art, diagram")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--use-chrome", action="store_true",
                        help="Use system Chrome with persistent profile (preserves login across runs)")
    parser.add_argument("--skip-image", action="store_true", help="Skip image generation, only push text cards")
    parser.add_argument("--only", type=int, default=None, help="Only process the Nth level (1-indexed)")
    parser.add_argument("--reference-image", action="append", default=None,
                        help="Reference image file or directory to upload to ChatGPT. Can be repeated.")
    parser.add_argument("--allow-no-reference-images", action="store_true",
                        help="Allow generation without configured reference images.")
    parser.add_argument("--max-image-generations", type=int, default=None,
                        help="Maximum ChatGPT image generation requests for this run. Default: env/config or 1. Use -1 for unlimited.")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    load_env(script_dir)

    # Load config
    config_path = Path(args.config) if args.config else script_dir / "config.json"
    with open(config_path) as f:
        config = json.load(f)

    # Resolve input path
    if args.input:
        input_path = Path(args.input)
    else:
        input_path = script_dir.parent / "Phase3" / "output" / "Phase3_result.txt"
        # Override with config if available
        if config.get("phase3_input"):
            input_path = script_dir / config["phase3_input"]

    if not input_path.exists():
        print(f"[error] Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Parse input
    try:
        level_data = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[error] Failed to parse input JSON: {e}", file=sys.stderr)
        sys.exit(1)

    # Handle fallback text
    if isinstance(level_data, str):
        print(f"[error] Input contains fallback text: {level_data}", file=sys.stderr)
        sys.exit(1)

    # Support either a single object or a list
    levels = level_data if isinstance(level_data, list) else [level_data]

    # Filter to specific level if requested
    if args.only is not None:
        if 1 <= args.only <= len(levels):
            levels = [levels[args.only - 1]]
        else:
            print(f"[error] --only {args.only} out of range (1-{len(levels)})", file=sys.stderr)
            sys.exit(1)

    # Settings
    image_style = args.style or os.environ.get("IMAGE_STYLE", config.get("image_style", "game_screenshot"))
    generation_timeout = int(os.environ.get("GENERATION_TIMEOUT", config.get("generation_timeout", 120)))
    image_format = config.get("image_format", "png")
    if args.max_image_generations is not None:
        max_image_generations = args.max_image_generations
    else:
        max_image_generations = int(os.environ.get(
            "MAX_IMAGE_GENERATIONS_PER_RUN",
            config.get("max_image_generations_per_run", 1),
        ))
    reference_images = resolve_reference_images(script_dir, config, args.reference_image)
    if not args.skip_image:
        if reference_images:
            print(f"[visualize] Using {len(reference_images)} reference image(s)")
        elif not args.allow_no_reference_images and config.get("reference_images"):
            print("[error] No reference images found. Add the original Boxy screenshots to Phase5/reference_images/ or pass --reference-image.", file=sys.stderr)
            sys.exit(1)

    # Feishu settings
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    chat_id = get_target_chat_id()
    base_token = os.environ.get("FEISHU_BASE_TOKEN") or DEFAULT_FEISHU_BASE_TOKEN
    base_table_id = os.environ.get("FEISHU_BASE_TABLE_ID") or DEFAULT_FEISHU_BASE_TABLE_ID
    base_url = os.environ.get("FEISHU_BASE_URL") or DEFAULT_FEISHU_BASE_URL

    # Output directory
    output_dir = script_dir / config.get("output_dir", "output")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize ChatGPT browser (unless --skip-image)
    browser = None
    if not args.skip_image:
        # Determine Chrome mode from CLI flag or env var
        use_chrome = args.use_chrome or os.environ.get("CHATGPT_USE_CHROME", "false").lower() == "true"
        headless = args.headless or os.environ.get("CHATGPT_HEADLESS", "false").lower() == "true"

        if use_chrome:
            # Chrome mode — use system Chrome with persistent profile (login preserved)
            print("[visualize] Using system Chrome with persistent profile")
            browser = ChatGPTBrowser(
                use_chrome=True,
                headless=headless,
                timeout=generation_timeout,
            )
        else:
            # Standalone mode — launch Playwright Chromium with cookie management
            cookie_dir = script_dir / config.get("cookie_dir", "cookies")
            cookie_dir.mkdir(parents=True, exist_ok=True)
            cookie_path = cookie_dir / "chatgpt_cookies.json"

            browser = ChatGPTBrowser(
                cookie_path=str(cookie_path),
                headless=headless,
                timeout=generation_timeout,
            )

        browser.start()

        if not browser.ensure_logged_in():
            print("[error] Cannot proceed without ChatGPT login.", file=sys.stderr)
            browser.close()
            sys.exit(1)

    # Get Feishu token
    feishu_token = None
    if app_id and app_secret and chat_id:
        try:
            feishu_token = get_tenant_token(app_id, app_secret)
            print(f"[visualize] Feishu token obtained")
        except Exception as e:
            print(f"[error] Failed to get Feishu token: {e}", file=sys.stderr)
    else:
        if os.environ.get("FEISHU_PUSH_TARGET", "").strip().lower() == "test":
            print("[visualize] Warning: Feishu test credentials not configured, skipping push", file=sys.stderr)
        else:
            print("[visualize] Warning: Feishu credentials not configured, skipping push", file=sys.stderr)

    # Process each level
    results = []
    success_count = 0
    push_failed_count = 0
    image_generation_requests = 0
    for i, level in enumerate(levels, start=1):
        level_name = level.get("level_name", f"Level_{i}")
        print(f"\n{'='*60}")
        print(f"[{i}/{len(levels)}] Processing: {level_name}")
        print(f"{'='*60}")

        image_path = None
        image_key = None
        source_image_key = None
        skipped_reason = None
        card_pushed = False
        card_push_error = None

        # Step 1: Generate image
        if not args.skip_image and browser:
            if max_image_generations >= 0 and image_generation_requests >= max_image_generations:
                skipped_reason = f"image generation limit reached ({max_image_generations})"
                print(f"[visualize] Skipping image generation: {skipped_reason}")
            else:
                prompt = build_image_prompt(level, style=image_style)
                img_filename = f"level_{i}_{level_name.replace(' ', '_').replace('/', '_')}.{image_format}"
                img_output_path = output_dir / img_filename

                image_generation_requests += 1
                print(
                    f"[visualize] Generating image with style '{image_style}' "
                    f"({image_generation_requests}/{max_image_generations if max_image_generations >= 0 else 'unlimited'})..."
                )
                image_path = browser.generate_image(
                    prompt=prompt,
                    output_path=str(img_output_path),
                    timeout=generation_timeout,
                    retries=1,
                    reference_image_paths=reference_images,
                )

                if image_path:
                    print(f"[visualize] ✓ Image generated: {image_path}")
                else:
                    skipped_reason = getattr(browser, "last_error", None) or "image generation failed"
                    print(f"[visualize] ✗ Image generation failed", file=sys.stderr)

            # Wait between generations to avoid rate limiting
            if image_path and i < len(levels) and not args.skip_image:
                print("[visualize] Waiting 10 seconds before next generation...")
                import time
                time.sleep(10)

        # Step 2: Upload image to Feishu
        if image_path and feishu_token:
            try:
                image_key = upload_image(feishu_token, image_path)
                print(f"[visualize] ✓ Image uploaded to Feishu: {image_key}")
            except Exception as e:
                print(f"[visualize] ✗ Feishu image upload failed: {e}", file=sys.stderr)

        # Step 2.5: Upload original meme image to Feishu
        source_image_path = resolve_source_image_path(script_dir.parent, level)
        if source_image_path and feishu_token:
            try:
                source_image_key = upload_image(feishu_token, source_image_path)
                print(f"[visualize] ✓ Source meme uploaded to Feishu: {source_image_key}")
            except Exception as e:
                print(f"[visualize] ✗ Source meme upload failed: {e}", file=sys.stderr)
        elif feishu_token:
            print("[visualize] Warning: No local source meme image found for this level", file=sys.stderr)

        # Step 3: Build and push card
        if feishu_token:
            try:
                if skipped_reason and not image_key:
                    print("[visualize] Skipping Feishu image card because no image was generated")
                    results.append({
                        "level_name": level_name,
                        "image_path": image_path,
                        "image_key": image_key,
                        "pushed": False,
                        "skipped_reason": skipped_reason,
                        "card_push_error": None,
                    })
                    continue

                if image_key:
                    card = build_card_with_image(
                        level,
                        image_key,
                        base_url=base_url,
                        source_image_key=source_image_key,
                    )
                else:
                    # Fallback to text-only card (same as Phase 4)
                    card = _build_text_only_card(level, base_url)

                # Save card JSON for debugging
                card_path = output_dir / f"feishu_card_{i}.json"
                card_path.write_text(
                    json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
                )

                result = push_card_with_image(feishu_token, chat_id, card)
                success_count += 1
                card_pushed = True
                print(f"[visualize] ✓ Card pushed to Feishu")

            except Exception as e:
                card_push_error = str(e)
                push_failed_count += 1
                print(f"[visualize] ✗ Card push failed: {e}", file=sys.stderr)
        else:
            # No Feishu — just save the card JSON
            if image_key:
                card = build_card_with_image(
                    level,
                    image_key,
                    base_url=base_url,
                    source_image_key=source_image_key,
                )
            else:
                card = _build_text_only_card(level, base_url)
            card_path = output_dir / f"feishu_card_{i}.json"
            card_path.write_text(
                json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"[visualize] Card JSON saved (no Feishu push): {card_path}")

        results.append({
            "level_name": level_name,
            "image_path": image_path,
            "image_key": image_key,
            "source_image_key": source_image_key,
            "pushed": card_pushed,
            "skipped_reason": skipped_reason,
            "card_push_error": card_push_error,
        })

    # Cleanup
    if browser:
        browser.close()

    # Save summary
    summary_path = output_dir / "visualization_summary.json"
    summary_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n{'='*60}")
    print(f"[visualize] Complete: {success_count}/{len(levels)} cards pushed successfully")
    if push_failed_count:
        print(f"[visualize] Failed pushes: {push_failed_count}", file=sys.stderr)
    print(f"[visualize] Summary: {summary_path}")
    print(f"{'='*60}")

    all_skipped = bool(results) and all(item.get("skipped_reason") for item in results)
    if push_failed_count:
        sys.exit(1)
    if success_count == 0 and feishu_token and not all_skipped:
        sys.exit(1)


def _build_text_only_card(level_data, base_url=DEFAULT_FEISHU_BASE_URL):
    """Build a text-only Feishu card (fallback when no image is available)."""
    meme_inspiration = level_data.get("meme_inspiration", "")
    surface_layer = level_data.get("surface_layer", "")
    misdirection_layer = level_data.get("misdirection_layer", "")
    full_game_flow = level_data.get("full_game_flow", "")
    hint_design = level_data.get("hint_design", {})
    source_post_url = level_data.get("source_post_url", "")

    elements = []

    quality_md = format_quality_summary(level_data)
    if quality_md:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": quality_md}
        })

    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": f"**灵感来源**\n{meme_inspiration}"}
    })
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": f"**表层**\n{surface_layer}"}
    })
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": f"**误导层**\n{misdirection_layer}"}
    })
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": f"**完整流程**\n{full_game_flow}"}
    })

    hint_md = format_hint_design(hint_design, markdown=True)
    if hint_md:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**提示设计**\n{hint_md}"}
        })

    if source_post_url:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**来源**: [查看来源]({source_post_url})"}
        })

    if base_url:
        elements.append({
            "tag": "action",
            "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "查看多维表格"},
                "type": "primary",
                "url": base_url,
            }],
        })

    level_name = level_data.get("level_name", "Unknown Level")
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


if __name__ == "__main__":
    main()
