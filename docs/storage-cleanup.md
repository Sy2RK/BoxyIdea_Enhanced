# Storage and Cleanup Notes

This project can look large even after cache cleanup because most of the disk
usage comes from dependencies, browser profiles, generated outputs, and Git
history rather than disposable cache files.

The snapshot below was measured on 2026-05-20 from the repository root.

## Current Size Breakdown

Approximate total size:

```text
940M .
```

Largest items:

| Path | Size | What it is |
| --- | ---: | --- |
| `.venv` | `283M` | Root Python virtual environment. Playwright is the largest package. |
| `Phase5` | `270M` | Phase5 runtime data, mostly the local Chrome profile. |
| `reddit-rader-AInews` | `241M` | Nested project data, artifacts, and its own virtual environment. |
| `.git` | `83M` | Git object database and repository history. |
| `Phase1/output` | `50M` | Generated Phase1 output images/data. |
| `Phase2` | `10M` | Phase2 code plus Node dependencies. |

Notable subdirectories:

| Path | Size | Notes |
| --- | ---: | --- |
| `Phase5/chrome_profile` | `238M` | Local browser profile/session data. |
| `reddit-rader-AInews/skill_runs` | `130M` | Pipeline run artifacts, including `pipeline_artifacts.sqlite`. |
| `.venv/lib/python3.14/site-packages/playwright` | `130M` | Playwright runtime package. |
| `reddit-rader-AInews/.venv` | `51M` | Nested Python virtual environment. |
| `reddit-rader-AInews/trend-scrap` | `55M` | Reddit scraper package and dependencies. |
| `Phase5/output` | `29M` | Generated Phase5 review/card/image output. |
| `Phase2/node_modules` | `10M` | Phase2 Node dependencies. |

## What Was Cleaned

The previous cleanup removed disposable Python/tooling caches such as:

```text
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.cache/
.vite/
.next/
.turbo/
```

No source files, `.env` files, dependency directories, virtual environments, or
runtime output folders were removed.

## Safe Cleanup Commands

These commands remove rebuildable cache files only:

```sh
find . \
  -path './.git' -prune -o \
  -path './.venv' -prune -o \
  -path './reddit-rader-AInews/.venv' -prune -o \
  -type d \( \
    -name __pycache__ -o \
    -name .pytest_cache -o \
    -name .mypy_cache -o \
    -name .ruff_cache -o \
    -name .cache -o \
    -name .vite -o \
    -name .next -o \
    -name .turbo \
  \) -prune -exec rm -rf {} +
```

## Optional Space Reclaim

Use these only when the related runtime state or generated artifacts are no
longer needed.

| Command | Frees | Tradeoff |
| --- | ---: | --- |
| `rm -rf Phase5/chrome_profile` | About `238M` | Removes local Chrome/ChatGPT session state. You may need to log in again. |
| `rm -rf reddit-rader-AInews/skill_runs` | About `130M` | Removes previous pipeline run artifacts. |
| `rm -rf Phase1/output` | About `50M` | Removes generated Phase1 output. |
| `rm -rf Phase5/output` | About `29M` | Removes generated Phase5 output. |
| `rm -rf .venv` | About `283M` | Removes the root Python environment. Reinstall dependencies before running Python phases. |
| `rm -rf reddit-rader-AInews/.venv` | About `51M` | Removes the nested Python environment. |
| `rm -rf Phase2/node_modules` | About `10M` | Removes Phase2 Node dependencies. Run `npm install` in `Phase2` before using it again. |

## Useful Inspection Commands

Show top-level disk usage:

```sh
du -sh .[!.]* * 2>/dev/null | sort -h
```

Show the largest nested directories:

```sh
find . -maxdepth 3 -type d -exec du -sh {} + 2>/dev/null | sort -h | tail -40
```

Show large files:

```sh
find . -type f -size +20M -exec ls -lh {} + 2>/dev/null | sort -k5 -h
```

