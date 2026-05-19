#!/usr/bin/env python3
"""ChatGPT web browser automation — uses Playwright to interact with ChatGPT web UI for image generation.

Supports two modes:
1. Chrome mode (default, recommended): Launches the system Chrome with a persistent user profile.
   Login sessions are preserved across runs. No manual setup needed.
2. Standalone mode: Launches Playwright's built-in Chromium and manages cookies manually.

Chrome mode uses Playwright's launch_persistent_context with channel="chrome", which:
- Uses the system-installed Google Chrome browser
- Stores login state in a persistent user data directory
- Does NOT require --remote-debugging-port or CDP
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


CHATGPT_URL = "https://chatgpt.com"

# Default user data directory for Chrome persistent context
DEFAULT_USER_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome_profile")


class ChatGPTQuotaLimitError(RuntimeError):
    """Raised when ChatGPT shows a message / generation quota limit."""

# Selectors for ChatGPT web UI (may need updates if OpenAI changes the DOM)
SELECTORS = {
    # Input area — ChatGPT uses a ProseMirror contenteditable div
    "prompt_textarea": "#prompt-textarea",
    "prompt_textarea_fallback": "div.ProseMirror[contenteditable='true']",
    # Send button (only visible when logged in and text is entered)
    "send_button": 'button[data-testid="send-button"]',
    "send_button_fallback": 'button[data-testid="fruitjuice-send-button"]',
    # Response area — the latest assistant message
    "assistant_message": ".markdown",
    # Images in response
    "response_image": ".agent-turn img[src]",
    # Stop button (visible while generating)
    "stop_button": 'button[aria-label="Stop generating"]',
    # Login buttons (present when NOT logged in)
    "login_button": 'button[data-testid="login-button"]',
    "signup_button": 'button[data-testid="signup-button"]',
    # New chat button
    "new_chat_button": '[data-testid="create-new-chat-button"]',
    # File upload input. ChatGPT keeps this hidden, but Playwright can set files directly.
    "file_input": 'input[type="file"]',
}


class ChatGPTBrowser:
    """Automates ChatGPT web UI for image generation using Playwright.

    Supports two connection modes:
    - Chrome mode (use_chrome=True): Uses system Chrome with persistent profile (recommended)
    - Standalone mode: Launches Playwright Chromium and manages cookies manually
    """

    def __init__(self, cookie_path=None, headless=False, timeout=120,
                 use_chrome=False, user_data_dir=None):
        """Initialize the browser.

        Args:
            cookie_path: Path to save/load cookies JSON file (standalone mode only).
            headless: Whether to run browser in headless mode.
            timeout: Default timeout in seconds for waiting operations.
            use_chrome: If True, use system Chrome with persistent profile (recommended).
            user_data_dir: Directory for Chrome persistent profile (default: Phase5/chrome_profile).
        """
        self.cookie_path = Path(cookie_path) if cookie_path else None
        self.headless = headless
        self.timeout = timeout
        self.use_chrome = use_chrome
        self.user_data_dir = user_data_dir or DEFAULT_USER_DATA_DIR
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._owns_browser = False  # Track if we launched the browser
        self.last_error = None

    def start(self):
        """Launch browser and navigate to ChatGPT."""
        self.playwright = sync_playwright().start()

        if self.use_chrome:
            self._start_chrome()
        else:
            self._start_standalone()

    def _start_chrome(self):
        """Launch system Chrome with a persistent user profile.

        This uses Playwright's launch_persistent_context with channel="chrome",
        which preserves login sessions across runs without needing CDP.
        """
        try:
            # Ensure the user data directory exists
            Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)

            # Launch Chrome with persistent context
            # channel="chrome" uses the system-installed Google Chrome
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                channel="chrome",
                headless=self.headless,
                viewport={"width": 1400, "height": 900},
                # Don't use default args that might conflict with Chrome
                args=[
                    "--disable-blink-features=AutomationControlled",
                ],
                ignore_default_args=["--enable-automation"],
            )
            self._owns_browser = True
            self.browser = None  # persistent context doesn't have a separate browser object

            # Get or create a page
            if self.context.pages:
                self.page = self.context.pages[0]
            else:
                self.page = self.context.new_page()

            print(f"[chatgpt] Chrome launched with persistent profile: {self.user_data_dir}")

            # Navigate to ChatGPT
            self.page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=30000)
            self.page.wait_for_timeout(3000)

        except Exception as e:
            print(f"[chatgpt] Failed to launch Chrome: {e}", file=sys.stderr)
            print(f"[chatgpt] Make sure Google Chrome is installed on this system.", file=sys.stderr)
            raise

    def _start_standalone(self):
        """Launch a new Playwright Chromium browser and load cookies."""
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        self._owns_browser = True
        self.context = self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900},
        )

        # Load cookies if they exist
        if self.cookie_path and self.cookie_path.exists():
            try:
                cookies = json.loads(self.cookie_path.read_text(encoding="utf-8"))
                self.context.add_cookies(cookies)
                print(f"[chatgpt] Loaded {len(cookies)} cookies from {self.cookie_path}")
            except Exception as e:
                print(f"[chatgpt] Failed to load cookies: {e}", file=sys.stderr)

        self.page = self.context.new_page()
        self.page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=30000)
        self.page.wait_for_timeout(3000)

    def ensure_logged_in(self) -> bool:
        """Check if user is logged in. If not, wait for manual login.

        Login detection strategy:
        - If login/signup buttons are visible → NOT logged in
        - If no login buttons AND textarea is visible → logged in

        Returns:
            True if logged in, False if login failed.
        """
        if self._is_logged_in():
            print("[chatgpt] Already logged in.")
            return True

        # Not logged in — prompt user to log in manually
        print("\n" + "=" * 60)
        print("[chatgpt] NOT LOGGED IN. Please log in manually in the browser window.")
        print("[chatgpt] After logging in, the script will continue automatically.")
        print("=" * 60 + "\n")

        max_wait = 300  # 5 minutes
        start = time.time()
        while time.time() - start < max_wait:
            if self._is_logged_in():
                print("[chatgpt] Login detected!")
                if not self.use_chrome:
                    self.save_cookies()
                return True
            time.sleep(2)

        print("[chatgpt] Login timeout (5 minutes). Exiting.", file=sys.stderr)
        return False

    def _is_logged_in(self) -> bool:
        """Check if the user is currently logged in to ChatGPT.

        Returns True if no login buttons are visible (indicating logged-in state).
        """
        try:
            # If login button is visible, user is NOT logged in
            login_btn = self.page.query_selector(SELECTORS["login_button"])
            if login_btn and login_btn.is_visible():
                return False

            signup_btn = self.page.query_selector(SELECTORS["signup_button"])
            if signup_btn and signup_btn.is_visible():
                return False

            # No login/signup buttons visible — check for textarea as confirmation
            textarea = self.page.query_selector(SELECTORS["prompt_textarea"])
            if textarea and textarea.is_visible():
                return True

        except Exception:
            pass

        return False

    def save_cookies(self):
        """Save current browser cookies to file (standalone mode only)."""
        if not self.context or not self.cookie_path or self.use_chrome:
            return
        cookies = self.context.cookies()
        self.cookie_path.parent.mkdir(parents=True, exist_ok=True)
        self.cookie_path.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
        print(f"[chatgpt] Saved {len(cookies)} cookies to {self.cookie_path}")

    def generate_image(self, prompt, output_path, timeout=None, retries=1, reference_image_paths=None):
        """Send an image generation prompt to ChatGPT and download the result.

        Args:
            prompt: The image generation prompt text.
            output_path: Local path to save the generated image.
            timeout: Timeout in seconds (default: use instance timeout).
            retries: Number of retries on failure.
            reference_image_paths: Optional local images to upload with the prompt.

        Returns:
            output_path if successful, None if failed.
        """
        timeout = timeout or self.timeout
        self.last_error = None

        for attempt in range(retries + 1):
            try:
                # Start a new chat for each generation to avoid context pollution
                self._start_new_chat()
                self._raise_if_quota_limited()

                print(f"[chatgpt] Sending image generation prompt (attempt {attempt + 1})...")
                self._send_message(prompt, reference_image_paths=reference_image_paths)
                print(f"[chatgpt] Waiting for image generation (timeout: {timeout}s)...")

                image_url = self._wait_for_image(timeout)
                if not image_url:
                    print(f"[chatgpt] No image found in response.", file=sys.stderr)
                    if attempt < retries:
                        print(f"[chatgpt] Retrying...")
                        self.page.wait_for_timeout(3000)
                    continue

                print(f"[chatgpt] Image found, downloading...")
                result = self._download_image(image_url, output_path)
                if result:
                    print(f"[chatgpt] Image saved: {output_path}")
                    return result

            except PlaywrightTimeout:
                self.last_error = "timeout waiting for image generation"
                print(f"[chatgpt] Timeout waiting for image generation.", file=sys.stderr)
            except ChatGPTQuotaLimitError as e:
                self.last_error = f"quota limit detected: {e}"
                print(f"[chatgpt] Quota limit detected: {e}", file=sys.stderr)
                return None
            except Exception as e:
                self.last_error = str(e)
                print(f"[chatgpt] Error generating image: {e}", file=sys.stderr)

            if attempt < retries:
                print(f"[chatgpt] Retrying...")
                self.page.wait_for_timeout(5000)

        return None

    def _start_new_chat(self):
        """Navigate to a new chat to avoid context pollution."""
        try:
            # Try clicking the "New chat" button
            new_chat = self.page.query_selector(SELECTORS["new_chat_button"])
            if new_chat and new_chat.is_visible():
                new_chat.click()
                self.page.wait_for_timeout(2000)
                return
        except Exception:
            pass

        # Fallback: navigate directly to ChatGPT home
        try:
            self.page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=15000)
            self.page.wait_for_timeout(2000)
        except Exception:
            pass

    def _send_message(self, prompt, reference_image_paths=None):
        """Type a prompt into the ChatGPT input box, attach reference images, and send it."""
        self._raise_if_quota_limited()

        # Find the textarea (ProseMirror contenteditable div)
        textarea = self.page.query_selector(SELECTORS["prompt_textarea"])
        if not textarea:
            textarea = self.page.query_selector(SELECTORS["prompt_textarea_fallback"])
        if not textarea:
            raise RuntimeError("Cannot find ChatGPT input textarea. DOM may have changed.")

        # Click to focus
        textarea.click()
        self.page.wait_for_timeout(500)

        # Clear any existing text
        self.page.keyboard.press("Meta+a")
        self.page.keyboard.press("Backspace")
        self.page.wait_for_timeout(300)

        if reference_image_paths:
            self._upload_reference_images(reference_image_paths)
            self._raise_if_quota_limited()

        # Insert the whole prompt atomically. Typing long multi-line prompts key by key
        # can make ChatGPT submit the first paragraph early and leave the rest behind.
        self._insert_prompt_text(textarea, prompt)
        self.page.wait_for_timeout(1000)
        self._raise_if_quota_limited()

        # Find and click the send button (appears after text is entered)
        send_btn = self.page.query_selector(SELECTORS["send_button"])
        if not send_btn:
            send_btn = self.page.query_selector(SELECTORS["send_button_fallback"])
        if send_btn:
            try:
                if send_btn.is_visible():
                    send_btn.click()
                else:
                    # Button exists but not visible, try Enter
                    self.page.keyboard.press("Enter")
            except Exception:
                self.page.keyboard.press("Enter")
        else:
            # No send button found, try pressing Enter as fallback
            self.page.keyboard.press("Enter")

        self.page.wait_for_timeout(2000)

    def _insert_prompt_text(self, textarea, prompt):
        """Insert a long prompt as one composer value instead of key-by-key typing."""
        try:
            textarea.fill(prompt)
            return
        except Exception:
            pass

        try:
            textarea.click()
            self.page.keyboard.insert_text(prompt)
            return
        except Exception:
            pass

        # Last-resort DOM insertion for contenteditable editors.
        self.page.evaluate(
            """({selector, text}) => {
                const el = document.querySelector(selector) || document.querySelector("div.ProseMirror[contenteditable='true']");
                if (!el) throw new Error("composer not found");
                el.focus();
                el.textContent = text;
                el.dispatchEvent(new InputEvent("input", {
                    inputType: "insertText",
                    data: text,
                    bubbles: true,
                    cancelable: true
                }));
            }""",
            {"selector": SELECTORS["prompt_textarea"], "text": prompt},
        )

    def _raise_if_quota_limited(self):
        """Stop before sending when ChatGPT reports a quota/message limit."""
        try:
            page_text = self.page.inner_text("body")
        except Exception:
            return

        text = page_text.lower()
        patterns = [
            "you've reached",
            "rate limit",
            "message limit",
            "usage limit",
            "try again later",
            "你已达到",
            "消息数量上限",
            "达到消息",
            "达到上限",
            "后重试",
            "稍后重试",
        ]
        if any(pattern in text for pattern in patterns):
            snippet = ""
            for line in page_text.splitlines():
                if any(p in line.lower() for p in patterns):
                    snippet = line.strip()
                    break
            raise ChatGPTQuotaLimitError(snippet or "ChatGPT quota/message limit is visible")

    def _upload_reference_images(self, image_paths):
        """Attach local reference images to the current ChatGPT composer."""
        paths = [str(Path(p).resolve()) for p in image_paths]
        missing = [p for p in paths if not Path(p).exists()]
        if missing:
            raise FileNotFoundError(f"Reference image not found: {missing[0]}")

        print(f"[chatgpt] Uploading {len(paths)} reference image(s)...")

        file_input = self.page.query_selector(SELECTORS["file_input"])
        if not file_input:
            # Some ChatGPT builds only create the input after clicking the attach button.
            attach_selectors = [
                'button[aria-label*="Attach"]',
                'button[aria-label*="Upload"]',
                'button[data-testid*="attach"]',
                'button[data-testid*="upload"]',
            ]
            for selector in attach_selectors:
                button = self.page.query_selector(selector)
                if button and button.is_visible():
                    try:
                        button.click()
                        self.page.wait_for_timeout(1000)
                        break
                    except Exception:
                        pass
            file_input = self.page.query_selector(SELECTORS["file_input"])

        if not file_input:
            raise RuntimeError("Cannot find ChatGPT file upload input. DOM may have changed.")

        file_input.set_input_files(paths)
        self.page.wait_for_timeout(5000)
        print("[chatgpt] Reference images attached.")

    def _wait_for_image(self, timeout):
        """Wait for an image to appear in the latest assistant response.

        Returns:
            The image src URL, or None if not found.
        """
        start = time.time()
        stop_button_gone = False

        while time.time() - start < timeout:
            self._raise_if_quota_limited()

            # Check for stop button (still generating)
            try:
                stop_btn = self.page.query_selector(SELECTORS["stop_button"])
                if stop_btn and stop_btn.is_visible():
                    stop_button_gone = False
                    self.page.wait_for_timeout(2000)
                    continue
            except Exception:
                pass

            # Stop button disappeared — generation should be complete
            if not stop_button_gone:
                stop_button_gone = True
                # Wait a bit for the DOM to update after generation completes
                self.page.wait_for_timeout(3000)

            # Look for images in the response
            try:
                images = self.page.query_selector_all(SELECTORS["response_image"])
                if images:
                    # Get the last image (most recent response)
                    for img in reversed(images):
                        src = img.get_attribute("src")
                        if src and not src.startswith("data:"):
                            # Skip small icons/avatars by checking image dimensions
                            box = img.bounding_box()
                            if box and box["width"] > 100 and box["height"] > 100:
                                return src
            except Exception:
                pass

            # Check for error messages
            try:
                page_text = self.page.inner_text("body")
                if "rate limit" in page_text.lower() or "you've reached" in page_text.lower():
                    print("[chatgpt] Rate limit detected.", file=sys.stderr)
                    return None
                if "something went wrong" in page_text.lower():
                    print("[chatgpt] Error detected in ChatGPT response.", file=sys.stderr)
                    return None
            except Exception:
                pass

            self.page.wait_for_timeout(3000)

        return None

    def _download_image(self, url, output_path):
        """Download an image from URL to local path.

        Uses the browser's fetch() API to ensure cookies/auth are included.
        Falls back to canvas-based extraction if fetch fails.

        Args:
            url: The image URL.
            output_path: Local file path to save the image.

        Returns:
            output_path if successful, None if failed.
        """
        try:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Method 1: Use browser's fetch() API (preserves cookies/auth)
            result = self._download_via_browser_fetch(url, output_path)
            if result:
                return result

            # Method 2: Use canvas-based extraction
            result = self._download_via_canvas(url, output_path)
            if result:
                return result

            # Method 3: Fallback to urllib (works for public URLs only)
            result = self._download_via_urllib(url, output_path)
            if result:
                return result

        except Exception as e:
            print(f"[chatgpt] All download methods failed: {e}", file=sys.stderr)

        return None

    def _download_via_browser_fetch(self, url, output_path):
        """Download image using browser's fetch() API — preserves auth cookies."""
        try:
            import base64
            b64_data = self.page.evaluate("""
                async (url) => {
                    try {
                        const response = await fetch(url);
                        if (!response.ok) return null;
                        const blob = await response.blob();
                        const reader = new FileReader();
                        return new Promise((resolve) => {
                            reader.onloadend = () => {
                                const dataUrl = reader.result;
                                const base64 = dataUrl.split(',')[1];
                                resolve(base64);
                            };
                            reader.readAsDataURL(blob);
                        });
                    } catch (e) {
                        return null;
                    }
                }
            """, url)

            if b64_data:
                data = base64.b64decode(b64_data)
                if len(data) < 1000:
                    print(f"[chatgpt] Fetched image too small ({len(data)} bytes).", file=sys.stderr)
                    return None
                output_path.write_bytes(data)
                print(f"[chatgpt] Image downloaded via browser fetch ({len(data)} bytes)")
                return str(output_path)
        except Exception as e:
            print(f"[chatgpt] Browser fetch download failed: {e}", file=sys.stderr)
        return None

    def _download_via_canvas(self, url, output_path):
        """Download image by opening it in a new tab and extracting via canvas."""
        import base64
        new_page = self.context.new_page()
        try:
            new_page.goto(url, wait_until="load", timeout=30000)
            data_url = new_page.evaluate("""
                () => {
                    const img = document.querySelector('img');
                    if (!img) return null;
                    const canvas = document.createElement('canvas');
                    canvas.width = img.naturalWidth;
                    canvas.height = img.naturalHeight;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0);
                    return canvas.toDataURL('image/png');
                }
            """)
            if data_url and data_url.startswith("data:image"):
                b64_data = data_url.split(",", 1)[1]
                data = base64.b64decode(b64_data)
                if len(data) < 1000:
                    return None
                output_path.write_bytes(data)
                print(f"[chatgpt] Image downloaded via canvas ({len(data)} bytes)")
                return str(output_path)
        except Exception as e:
            print(f"[chatgpt] Canvas download failed: {e}", file=sys.stderr)
        finally:
            new_page.close()
        return None

    def _download_via_urllib(self, url, output_path):
        """Download image using urllib — only works for public URLs."""
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                if len(data) < 1000:
                    return None
                output_path.write_bytes(data)
                print(f"[chatgpt] Image downloaded via urllib ({len(data)} bytes)")
                return str(output_path)
        except Exception as e:
            print(f"[chatgpt] urllib download failed: {e}", file=sys.stderr)
        return None

    def close(self):
        """Save cookies and close the browser."""
        try:
            self.save_cookies()
        except Exception:
            pass

        try:
            if self.context and self._owns_browser:
                self.context.close()
        except Exception:
            pass

        try:
            if self.browser and self._owns_browser:
                self.browser.close()
        except Exception:
            pass

        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
