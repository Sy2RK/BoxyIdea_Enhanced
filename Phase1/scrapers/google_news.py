#!/usr/bin/env python3
"""Google News scraper — uses Playwright to render search results and extract article content."""

import argparse
import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright
import trafilatura


SEARCH_URL = 'https://news.google.com/search?q="meme"%20when%3A1d&hl=en-US&gl=US&ceid=US%3Aen'
MAX_POSTS = 5

CRYPTO_KEYWORDS = {"coin", "crypto", "token", "blockchain", "dogecoin", "shiba", "bitcoin", "ethereum", "altcoin"}


def is_crypto_spam(title):
    """Return True if the title is clearly about crypto/meme coins."""
    words = set(re.findall(r"[a-zA-Z]+", title.lower()))
    return not words.isdisjoint(CRYPTO_KEYWORDS)


def extract_article_content(url):
    """Fetch original article and extract main text using trafilatura."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            if text:
                return text.strip()
    except Exception as e:
        print(f"    [!] Article extraction failed for {url}: {e}", file=sys.stderr)
    return ""


def parse_time_ago(time_text):
    """Convert 'X hours ago' or 'X minutes ago' to a rough RFC-822 date string."""
    if not time_text:
        return ""
    try:
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        match = re.search(r'(\d+)\s+(minute|hour|day|week)s?\s+ago', time_text.lower())
        if match:
            num, unit = int(match.group(1)), match.group(2)
            delta = {
                'minute': datetime.timedelta(minutes=num),
                'hour': datetime.timedelta(hours=num),
                'day': datetime.timedelta(days=num),
                'week': datetime.timedelta(weeks=num),
            }[unit]
            pub = now - delta
            return pub.strftime("%a, %d %b %Y %H:%M:%S %z")
    except Exception:
        pass
    return time_text


def scrape():
    posts = []
    seen_titles = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()

        print(f"  loading Google News search...")
        page.goto(SEARCH_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)

        # Extract article cards via JS evaluation
        articles = page.evaluate("""
            () => {
                const results = [];
                const allA = Array.from(document.querySelectorAll('a'));

                for (const a of allA) {
                    const text = a.innerText?.trim();
                    if (!text || text.length < 20) continue;
                    if (!text.toLowerCase().includes('meme')) continue;

                    // Find parent C-WIZ
                    let parent = a.parentElement;
                    while (parent && parent.tagName !== 'C-WIZ') {
                        parent = parent.parentElement;
                    }
                    if (!parent) continue;

                    // Skip if we've seen this title
                    if (results.some(r => r.title === text)) continue;

                    const lines = parent.innerText.split('\\n')
                        .map(l => l.trim()).filter(l => l);

                    // Extract source (first line before "More")
                    let source = "";
                    let timeAgo = "";
                    for (let i = 0; i < lines.length; i++) {
                        if (lines[i] === "More") {
                            source = lines[i - 1] || "";
                        }
                        if (lines[i].match(/^\\d+\\s+(minute|hour|day|week)s?\\s+ago$/i)) {
                            timeAgo = lines[i];
                        }
                    }

                    results.push({
                        title: text,
                        href: a.href,
                        source: source,
                        timeAgo: timeAgo,
                    });
                }
                return results;
            }
        """)

        print(f"  found {len(articles)} unique article cards")

        for article in articles:
            if len(posts) >= MAX_POSTS:
                break

            title = article.get("title", "")
            if not title or is_crypto_spam(title):
                continue

            # Deduplicate by normalized title
            norm_title = re.sub(r"[^a-zA-Z0-9]", "", title.lower())
            if norm_title in seen_titles:
                continue
            seen_titles.add(norm_title)

            href = article.get("href", "")
            source = article.get("source", "")
            time_ago = article.get("timeAgo", "")

            print(f"  [{len(posts)+1}] {title}")

            description = ""
            if href:
                print(f"      resolving article...")
                try:
                    # Open article page to get the redirected URL and content
                    article_page = context.new_page()
                    article_page.goto(href, wait_until="domcontentloaded", timeout=30000)
                    article_page.wait_for_timeout(3000)
                    final_url = article_page.url
                    article_page.close()

                    if final_url and not final_url.startswith("https://news.google.com"):
                        print(f"      final url: {final_url}")
                        content = extract_article_content(final_url)
                        description = content if content else ""
                        href = final_url
                except Exception as e:
                    print(f"      [!] Failed to resolve article: {e}", file=sys.stderr)

            if not description:
                description = title  # fallback

            posts.append({
                "source": "google_news",
                "title": title,
                "url": href,
                "image_url": None,
                "local_image_path": None,
                "description": description,
                "keywords": "",
                "published": parse_time_ago(time_ago),
            })

        browser.close()

    return posts


def main():
    parser = argparse.ArgumentParser(description="Google News meme scraper")
    parser.add_argument("--output", required=True, help="Path to write JSON output")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    posts = scrape()

    result = {"source": "google_news", "posts": posts}
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"[google_news] Wrote {len(posts)} posts to {args.output}")


if __name__ == "__main__":
    main()
