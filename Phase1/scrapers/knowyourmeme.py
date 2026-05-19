#!/usr/bin/env python3
"""KnowYourMeme scraper — RSS for links, then visit each page for full description & image."""

import argparse
import json
import os
import re
import sys
import time
import gzip
import urllib.request
import xml.etree.ElementTree as ET


RSS_URL = "https://knowyourmeme.com/memes/all.rss"
MAX_POSTS = 5


def fetch(url, retries=2):
    """Download URL content with basic retries. Accepts partial reads."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    }
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                # Handle gzip responses if server sends them
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8")
        except Exception as e:
            data = getattr(e, "partial", None)
            if data:
                raw = data
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", errors="replace")
            print(f"  [!] Attempt {attempt + 1} failed for {url}: {e}", file=sys.stderr)
            if attempt < retries:
                time.sleep(2)
    return None


def fetch_feed(url):
    """Download RSS feed and return element tree."""
    content = fetch(url)
    if content is None:
        print(f"[knowyourmeme] Failed to fetch RSS feed", file=sys.stderr)
        sys.exit(1)
    return ET.fromstring(content)


def extract_json_ld(html):
    """Extract the application/ld+json block from the page."""
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    if match:
        raw = match.group(1).strip()
        # Remove HTML comments sometimes wrapping JSON-LD
        raw = re.sub(r'^<!--\s*|\s*-->$', '', raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"  [!] JSON-LD decode error: {e}", file=sys.stderr)
    return None


def extract_image_url_rss(description_xml):
    """Fallback: extract <img src> from RSS description."""
    match = re.search(r'src="([^"]+)"', description_xml)
    if match:
        return match.group(1).replace("&amp;", "&")
    return None


def download_image(url, title, images_dir):
    """Download image. Returns local path or None."""
    os.makedirs(images_dir, exist_ok=True)

    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", title).strip("_").lower()[:80]
    ext = "jpg"
    if ".png" in url:
        ext = "png"
    elif ".gif" in url:
        ext = "gif"
    elif ".webp" in url:
        ext = "webp"

    filename = f"kym_{safe_name}.{ext}"
    path = os.path.join(images_dir, filename)

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            with open(path, "wb") as f:
                f.write(resp.read())
        return path
    except Exception as e:
        print(f"  [!] Image download failed: {e}", file=sys.stderr)
        return None


def scrape(max_posts=None):
    root = fetch_feed(RSS_URL)
    items = root.findall(".//item")

    limit = max_posts if max_posts else MAX_POSTS
    posts = []
    for item in items[:limit]:
        title_el = item.find("title")
        link_el = item.find("link")
        pubdate_el = item.find("pubDate")
        desc_el = item.find("description")

        title = title_el.text.strip() if title_el is not None else ""
        link = link_el.text.strip() if link_el is not None else ""
        pub_date = pubdate_el.text.strip() if pubdate_el is not None else ""
        desc_xml_str = ET.tostring(desc_el, encoding="unicode") if desc_el is not None else ""

        # Fallback image URL from RSS
        rss_image = extract_image_url_rss(desc_xml_str)

        print(f"  fetching page: {link}")
        html = fetch(link)

        # If no JSON-LD found (partial read), retry once
        if html and extract_json_ld(html) is None:
            print(f"    [retry] {link}")
            html = fetch(link)

        full_description = ""
        image_url = rss_image
        keywords = ""

        if html:
            json_ld = extract_json_ld(html)
            if json_ld:
                full_description = json_ld.get("description", "")
                image_url = json_ld.get("image", {}).get("url", "") or image_url
                keywords = json_ld.get("keywords", "")
                if isinstance(keywords, list):
                    keywords = ", ".join(keywords)

        local_path = None
        if image_url:
            images_dir = os.path.join(os.environ.get("IMAGES_DIR", "output/images"))
            abs_path = download_image(image_url, title, images_dir)
            # Store relative path (relative to Phase1 directory) instead of absolute
            if abs_path:
                phase1_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                try:
                    local_path = os.path.relpath(abs_path, phase1_dir)
                except ValueError:
                    local_path = abs_path
            else:
                local_path = None

        posts.append({
            "source": "knowyourmeme",
            "title": title,
            "url": link,
            "image_url": image_url,
            "local_image_path": local_path,
            "description": full_description,
            "keywords": keywords,
            "published": pub_date,
        })

        # polite delay
        time.sleep(1)

    return posts


def main():
    parser = argparse.ArgumentParser(description="KnowYourMeme scraper")
    parser.add_argument("--output", required=True, help="Path to write JSON output")
    parser.add_argument("--max-posts", type=int, default=None, help="Maximum posts to fetch")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    posts = scrape(max_posts=args.max_posts)

    result = {"source": "knowyourmeme", "posts": posts}
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"[knowyourmeme] Wrote {len(posts)} posts to {args.output}")


if __name__ == "__main__":
    main()
