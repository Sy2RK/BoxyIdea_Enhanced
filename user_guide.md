# Boxy Level Design Pipeline — User Guide

## Overview

This pipeline automatically generates game level designs for the mobile puzzle platformer **Boxy** from internet memes, then pushes the best designs to Feishu as interactive cards with AI-generated Boxy-style gameplay screenshots.

| Phase | Purpose | Input | Output |
|-------|---------|-------|--------|
| **Phase 1** | Scrape memes from multiple sources | — | `scraped_posts.json` |
| **Phase 1.5** | Analyze meme images/OCR/punchlines | Phase 1 output | `enriched_posts.json` |
| **Phase 2** | Generate level designs via LLM | Phase 1.5 output | `synthesized_levels.json` |
| **Phase 3** | Filter and select top N designs | Phase 2 output | `Phase3_result.txt` |
| **Phase 4** | Push best designs to Feishu | Phase 3 output | Feishu cards |
| **Phase 5** | Generate Boxy-style gameplay screenshots & push image cards | Phase 3 output | Feishu image cards |

---

## Quick Start

### 1. Run the Full Pipeline

```bash
bash run-pipeline.sh
```

This runs all phases sequentially:
```
Phase 1 → Phase 1.5 → Phase 2 → Phase 3 → Phase 4 → Phase 5
```

### 2. Run a Single Phase

```bash
# Phase 1 only
bash Phase1/run.sh

# Phase 1.5 only
bash Phase1_5/run.sh

# Phase 2 only
bash Phase2/run.sh

# Phase 3 only
bash Phase3/run.sh

# Phase 4 only
bash Phase4/run.sh

# Phase 5 only
bash Phase5/run.sh
```

---

## Environment Setup

Each phase has its own `.env` file. You must create these before running.

### Phase 1 — Reddit Source Setup
Phase 1 now uses Reddit `r/memes` as the primary meme source via the reusable `reddit-rader-AInews` RapidAPI `reddit34` scraper, with KnowYourMeme and Google News as supplemental sources. Create `Phase1/.env` from `Phase1/.env.example` before running the full pipeline:

```bash
RAPIDAPI_KEY=your_rapidapi_key
RAPIDAPI_HOST=reddit34.p.rapidapi.com
```

If you have multiple RapidAPI keys, configure either `RAPIDAPI_KEYS=key1,key2,key3,key4` or numbered variables such as `RAPIDAPI_KEY_1` through `RAPIDAPI_KEY_4`. The scraper tries them in order and retries with the next key when the current key fails.

The default source is `r/memes` with `hot` and `top/day` results. Selection uses `REDDIT_RAPIDAPI_SELECTION_MODE=top_first`, which chooses `top/day` posts first and only uses `hot` to fill remaining slots. You do not need a Reddit developer account for this path, but you do need RapidAPI access to `reddit34`. `REDDIT_USE_PUBLIC=true` can try the public `reddit.com/*.json` fallback, but it is less reliable and may be blocked.

### Phase 2 & Phase 3 — LLM Provider Setup

Phase 1.5 and Phase 2/3 share the same OpenAI settings by default. Phase 1.5 uses the configured OpenAI model to read meme images, OCR text, and produce structured `meme_understanding` fields before Phase 2 generates levels.

Phase 2 and Phase 3 share the same LLM client and run with **one active provider at a time**.
Recommended priority for this project:

1. OpenAI
2. OpenRouter
3. Google AI Studio / Gemini

#### Option A: OpenAI (Default)

Create `.env` in `Phase2/` and `Phase3/`:

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
OPENAI_MODEL=gpt-5.4-mini
```

Phase 1.5 can optionally use a different vision model without changing Phase 2:

```bash
PHASE15_MODEL=gpt-5.4-mini
```

#### Option B: OpenRouter

Create `.env` in `Phase2/` and `Phase3/`:

```bash
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxx
OPENROUTER_MODEL=anthropic/claude-sonnet-4-20250514
OPENROUTER_MODEL_DROP=google/gemini-2.5-pro-exp-03-25
```

#### Option C: Google AI Studio

Create `.env` in `Phase2/` and `Phase3/`:

```bash
LLM_PROVIDER=google
GOOGLE_API_KEY=AIzaSyDAKHYZ0LlnP86jPNbFoSI27-lvLATqf3A
GOOGLE_MODEL=gemini-3.1-flash-lite-preview
```

> **Note:** `LLM_PROVIDER` now defaults to `openai`. OpenAI/OpenRouter/Google API keys can coexist in the same `.env` file, but only **one** `LLM_PROVIDER=...` line should remain active. If you keep multiple active lines, the last one wins. `*_MODEL_DROP` only falls back to another model within the same provider; it does not switch providers automatically.

### Phase 4 — Feishu Setup

Create `.env` in `Phase4/`:

```bash
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FEISHU_CHAT_ID=oc_xxxxxxxxxxxxxxxx
```

> **Important:** The bot must be added to the target Feishu group/chat before running Phase 4, or you will get error `230002: Bot/User can NOT be out of the chat.`

### Phase 5 — ChatGPT Image Generation + Feishu Setup

Phase 5 uses ChatGPT's web UI to generate hand-drawn Boxy gameplay screenshots for each level design, then uploads the images to Feishu and pushes interactive image cards.

Create `.env` in `Phase5/`:

```bash
# Feishu credentials (same as Phase 4)
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FEISHU_CHAT_ID=oc_xxxxxxxxxxxxxxxx

# Chrome mode — uses system Chrome with persistent login profile
CHATGPT_USE_CHROME=true

# Image generation settings
IMAGE_STYLE=game_screenshot
GENERATION_TIMEOUT=120
```

**Prerequisites:**
1. **Chrome browser** must be installed on the system (not Chromium — the actual Google Chrome)
2. **ChatGPT Plus subscription** is required for image generation (free tier does not support DALL·E image generation in chat)
3. On first run, the script will open a Chrome window to ChatGPT — **log in manually** and the session will be saved in `Phase5/chrome_profile/` for subsequent runs
4. The Feishu bot must be added to the target group (same as Phase 4)

---

## Changing the LLM Model

### Via Environment Variables

Set the appropriate variable in your `.env` file:

| Provider | Variable | Example |
|----------|----------|---------|
| OpenAI | `OPENAI_MODEL` | `gpt-5.4-mini` |
| OpenAI | `OPENAI_MODEL_DROP` | `gpt-4o-mini` |
| OpenRouter | `OPENROUTER_MODEL` | `anthropic/claude-sonnet-4-20250514` |
| OpenRouter | `OPENROUTER_MODEL_DROP` | `google/gemini-2.5-pro-exp-03-25` |
| Google | `GOOGLE_MODEL` | `gemini-3.1-flash-lite-preview` |
| Google | `GOOGLE_MODEL_DROP` | `gemini-2.5-flash` |

### Supported Google Models

Run this to list all available Gemini models:

```bash
python3 -c "
from google import genai
client = genai.Client(api_key='YOUR_GOOGLE_API_KEY')
for m in client.models.list():
    if 'gemini' in m.name.lower():
        print(m.name)
"
```

### Switching Between Providers

Keep only one active `LLM_PROVIDER` line in `.env`:

```bash
# Use OpenAI (default)
LLM_PROVIDER=openai

# Use Google AI Studio
LLM_PROVIDER=google

# Use OpenRouter
LLM_PROVIDER=openrouter
```

Do not keep multiple uncommented `LLM_PROVIDER=...` lines in the same file.

---

## Testing Individual Components

### Test Phase 1 (Scrapers)

```bash
cd Phase1

# Test KnowYourMeme scraper alone
python3 scrapers/knowyourmeme.py --output /tmp/kym.json

# Test Google News scraper alone
python3 scrapers/google_news.py --output /tmp/gn.json

# Test Reddit r/memes scraper alone
python3 scrapers/reddit_rapidapi_memes.py --output /tmp/reddit.json --max-posts 10

# Test merge script
python3 merge_sources.py --output /tmp/merged.json /tmp/reddit.json /tmp/kym.json /tmp/gn.json
```

### Test Phase 1.5 (Meme Understanding)

```bash
cd Phase1_5
python3 meme_understanding.py --max-posts 3
```

### Test Phase 2 (Synthesizer)

```bash
cd Phase2
python3 synthesizer.py
```

### Test Phase 3 (Filter & Select)

```bash
cd Phase3
python3 filter_and_select.py
```

### Test Phase 4 (Feishu Push)

```bash
cd Phase4
python3 push_feishu.py
```

### Test Phase 5 (Visualization)

```bash
cd Phase5

# Generate a Boxy-style screenshot for level 1 using Chrome mode
python3 visualize.py --use-chrome --only 1

# Generate for all levels
python3 visualize.py --use-chrome

# Text-only cards (no image generation, for testing Feishu push)
python3 visualize.py --skip-image
```

> **Note:** The first time you run with `--use-chrome`, a Chrome window will open to ChatGPT. Log in manually, then the script will continue automatically. Subsequent runs will reuse the saved session.

### Test the LLM Client Directly

```bash
cd /path/to/project

# Test OpenAI
python3 -c "
import os
os.environ['LLM_PROVIDER'] = 'openai'
os.environ['OPENAI_API_KEY'] = 'your-key'
from shared.llm_client import LLMClient
c = LLMClient()
print(c.call(prompt='Hello!'))
"

# Test OpenRouter
python3 -c "
import os
os.environ['LLM_PROVIDER'] = 'openrouter'
os.environ['OPENROUTER_API_KEY'] = 'your-key'
from shared.llm_client import LLMClient
c = LLMClient()
print(c.call(prompt='Hello!'))
"

# Test Google AI Studio
python3 -c "
import os
os.environ['LLM_PROVIDER'] = 'google'
os.environ['GOOGLE_API_KEY'] = 'your-key'
from shared.llm_client import LLMClient
c = LLMClient()
print(c.call(prompt='Hello!'))
"
```

---

## Configuration Files

### Phase 1 — `config.json`

Controls which scrapers run and how many posts to fetch.

```json
{
  "platforms": [
    {
      "name": "reddit_rapidapi_memes",
      "scraper": "scrapers/reddit_rapidapi_memes.py",
      "enabled": true,
      "max_posts": 10
    },
    {
      "name": "knowyourmeme",
      "scraper": "scrapers/knowyourmeme.py",
      "enabled": true
    },
    {
      "name": "google_news",
      "scraper": "scrapers/google_news.py",
      "enabled": true
    }
  ],
  "output_dir": "output",
  "output_file": "scraped_posts.json"
}
```

### Phase 1.5 — `config.json`

```json
{
  "phase1_input": "../Phase1/output/scraped_posts.json",
  "output_dir": "output",
  "output_file": "enriched_posts.json",
  "max_posts": 10,
  "append_to_description": true
}
```

Phase 1.5 adds `meme_understanding` to image posts:
- `visible_text`: OCR-style text visible in the meme.
- `punchline` / `why_funny`: the core joke.
- `boxy_adaptation.core_twist_to_preserve`: what Phase 2 must preserve.
- `quality_flags`: whether the image is unclear, not a meme, or too context-dependent.

### Phase 2 — `config.json`

```json
{
  "phase1_input": "../Phase1_5/output/enriched_posts.json",
  "output_dir": "output",
  "output_file": "synthesized_levels.json"
}
```

Phase 2 generation is intentionally constrained for the current Boxy art direction:
- Each level should use one clear core twist.
- The solution should stay within 1-3 puzzle-relevant interactions or discovery points.
- The visual staging should fit a sparse hand-drawn horizontal mobile screen.

### Phase 3 — `config.json`

```json
{
  "phase2_input": "../Phase2/output/synthesized_levels.json",
  "background_file": "../Phase2/background.txt",
  "output_dir": "output",
  "accepted_file": "accepted_levels.json",
  "result_file": "Phase3_result.txt"
}
```

### Phase 3 — `TOP_N` Setting

Control how many top designs are selected:

```bash
# In Phase3/.env
TOP_N=5
```

Default is `3`. Phase 4 will push all `TOP_N` designs to Feishu.

Phase 3 also rejects designs that are too complex to stage in the actual Boxy UI, including long mechanism chains, crowded prop layouts, or more than 3 puzzle-relevant interactions.

### Phase 5 — `config.json`

```json
{
  "phase3_input": "../Phase3/output/accepted_levels.json",
  "output_dir": "output",
  "image_style": "game_screenshot"
}
```

| Field | Description |
|-------|-------------|
| `phase3_input` | Path to Phase 3 accepted levels JSON |
| `output_dir` | Directory for generated Boxy-style screenshots |
| `image_style` | Default image style for prompt building (overridable via `IMAGE_STYLE` env var) |

### Phase 5 — Image Style Options

The `IMAGE_STYLE` environment variable (or `image_style` in `config.json`) controls the visual style of generated screenshots. The default now targets the actual Boxy reference style: hand-drawn comic art, paper texture, sparse horizontal 2D level layout, simple built-in UI, and no more than 3 puzzle-relevant objects.

| Style | Description |
|-------|-------------|
| `game_screenshot` | Actual Boxy-style hand-drawn gameplay screenshot (default) |
| `boxy_reference` | Alias for the same strict Boxy reference style |
| `concept_art` | Looser production-art variant, still using the Boxy screenshot layout |
| `diagram` | Sparse review-friendly variant with minimal diegetic labels |

---

## Project Structure

```
BoxyIdea/
├── run-pipeline.sh          # Orchestrates all phases
├── user_guide.md            # This file
├── handoff_document.md      # Technical handoff document
├── shared/
│   └── llm_client.py        # Unified LLM client (OpenAI / OpenRouter / Google)
├── Phase1/
│   ├── run.sh
│   ├── config.json
│   ├── merge_sources.py     # Merges multi-source scraper outputs
│   └── scrapers/
│       ├── knowyourmeme.py  # KYM RSS scraper
│       ├── google_news.py   # Google News Playwright scraper
│       └── reddit_rapidapi_memes.py # Reddit r/memes scraper
├── Phase1_5/
│   ├── run.sh
│   ├── config.json
│   └── meme_understanding.py # OCR + punchline enrichment
├── Phase2/
│   ├── run.sh
│   ├── .env                 # LLM provider config
│   ├── synthesizer.py       # Two-step LLM level generation
│   ├── background.txt       # Game design philosophy
│   ├── response_point.txt   # Design constraints
│   └── hint_from_Feishu.txt # Dynamic hints from Feishu wiki
├── Phase3/
│   ├── run.sh
│   ├── .env                 # LLM provider config + TOP_N
│   ├── filter_and_select.py # Filter + rank designs
│   ├── config.json
│   └── output/
├── Phase4/
│   ├── run.sh
│   ├── .env                 # Feishu credentials
│   ├── push_feishu.py       # Push interactive cards
│   └── config.json
└── Phase5/
    ├── run.sh
    ├── .env                 # Feishu credentials + Chrome config
    ├── visualize.py         # Main entry: level visualization pipeline
    ├── chatgpt_browser.py   # ChatGPT browser automation (Playwright)
    ├── image_prompt_builder.py  # Level design → image prompt conversion
    ├── feishu_image.py      # Feishu image upload + image card push
    ├── config.json
    ├── cookies/             # Cookie persistence directory
    ├── chrome_profile/      # Chrome persistent user data (gitignored)
    └── output/              # Generated Boxy-style screenshots
```

---

## Troubleshooting

### Phase 1: No posts fetched
- Check your internet connection
- Google News scraper requires Playwright + Chromium (see Dependencies)

### Phase 2/3: "API key not found"
- Ensure `.env` exists in the correct phase directory
- Check that `LLM_PROVIDER` matches your configured keys

### Phase 2/3: Model timeout or truncation
- Increase `max_tokens` in the script call
- Try a different model via `.env`

### Phase 4: "Bot/User can NOT be out of the chat" (Error 230002)
- Add the bot to the target Feishu group
- Verify `FEISHU_CHAT_ID` is correct

### Phase 5: Chrome not found / "Chrome channel not found"
- Ensure Google Chrome (not Chromium) is installed on your system
- On macOS: Chrome should be at `/Applications/Google Chrome.app`
- On Linux: Install via your package manager or download from google.com/chrome

### Phase 5: ChatGPT login not detected
- On first run, the script opens a Chrome window — log in to ChatGPT manually
- After login, the session is saved in `Phase5/chrome_profile/` for reuse
- If login state is corrupted, delete `Phase5/chrome_profile/` and re-run

### Phase 5: Image generation timeout
- Increase `GENERATION_TIMEOUT` in `.env` (default: 120 seconds)
- ChatGPT image generation can take 30–90 seconds per image
- Check your ChatGPT Plus subscription — free tier does not support image generation

### Phase 5: Image download fails
- The script uses a three-tier download strategy: browser fetch → canvas → urllib
- If all fail, check your internet connection and ChatGPT session validity
- Try deleting `Phase5/chrome_profile/` and re-logging in

### General: Import errors
- Install dependencies: `pip install -r requirements.txt` (if available) or manually install missing packages

---

## Dependencies

### Core (for all phases)
- Python 3.10+
- `requests`
- `python-dotenv`

### Phase 1 — Google News scraper
- `playwright`
- `trafilatura`

Install:
```bash
pip install playwright trafilatura
playwright install chromium
```

### Phase 2 & 3 — LLM
**For OpenAI / OpenRouter:**
- `openai`

**For Google AI Studio:**
- `google-genai`

Install:
```bash
pip install -U openai      # OpenAI / OpenRouter
pip install google-genai   # Google AI Studio
```

### Phase 4 — Feishu
- `requests`
- `python-dotenv`

### Phase 5 — Visualization
- `playwright` (uses system Chrome, no additional browser download needed)
- `requests`
- `python-dotenv`
- **System requirement:** Google Chrome browser installed

Install:
```bash
pip install playwright requests python-dotenv
# No need to run `playwright install` — Phase 5 uses the system Chrome
```

---

## Tips

1. **Always test Phase 4 separately first** to verify Feishu credentials before running the full pipeline.
2. **Check `TOP_N`** in Phase 3 `.env` if you want more/fewer cards pushed to Feishu.
3. **The pipeline is idempotent** — you can re-run any phase independently if upstream data changes.
4. **Debug mode** — add print statements or use the test snippets above to isolate issues.
5. **Phase 5 first-run login** — On first run with `--use-chrome`, a Chrome window opens to ChatGPT. Log in manually; the session persists in `Phase5/chrome_profile/` for subsequent runs.
6. **Phase 5 text-only mode** — Use `--skip-image` to test Feishu card pushing without image generation (faster, no ChatGPT needed).
7. **Phase 5 single level** — Use `--only N` to generate a screenshot for just one level, useful for quick testing.
