# Boxy 关卡设计自动化管线 — 项目交接文档

## 1. 项目概述

本项目是一个分阶段自动化管线，用于从互联网 meme 中生成 Boxy（一款移动端解谜平台跳跃游戏）的关卡设计，并将最优设计推送到飞书作为交互式卡片（含可视化概念图）。

### 项目目标
- 每天自动抓取最新 meme（Phase 1）
- 对 meme 图片做 OCR、笑点与反差结构解析（Phase 1.5）
- 通过 LLM 将 meme 转化为关卡设计（Phase 2）
- 通过 LLM 筛选并选出最优设计（Phase 3）
- 将最优设计推送到飞书（Phase 4）
- 通过 ChatGPT 网页端生成关卡概念图并推送带图卡片到飞书（Phase 5）

### 项目阶段一览

| 阶段 | 功能 | 输入 | 输出 |
|------|------|------|------|
| **Phase 1** | 多源 meme 抓取 | — | `scraped_posts.json` |
| **Phase 1.5** | 图片/OCR/笑点解析 | Phase 1 输出 | `enriched_posts.json` |
| **Phase 2** | LLM 生成关卡设计 | Phase 1.5 输出 | `synthesized_levels.json` |
| **Phase 3** | 筛选与排序 | Phase 2 输出 | `Phase3_result.txt` |
| **Phase 4** | 飞书卡片推送 | Phase 3 输出 | 飞书群聊卡片 |
| **Phase 5** | 关卡可视化 | Phase 3 输出 | 飞书带图卡片 + 本地图片 |

---

## 2. 技术架构

### 2.1 整体架构图

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Phase 1    │────▶│  Phase 1.5   │────▶│   Phase 2    │────▶│   Phase 3    │────▶│   Phase 4    │────▶│   Phase 5    │
│  Meme 抓取   │     │ 图片笑点解析  │     │ LLM 生成设计  │     │ LLM 筛选排序  │     │ 飞书卡片推送  │     │ 关卡可视化   │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
       │                    │                    │                    │                    │
  ┌────┴────┐         ┌─────┴─────┐       ┌─────┴─────┐       ┌─────┴─────┐       ┌─────┴─────┐
  │ Know    │         │ OpenAI,   │       │ OpenAI,   │       │ Feishu    │       │ ChatGPT   │
  │ Your    │         │    or     │       │    or     │       │ Open API  │       │ Web UI    │
  │ Meme    │         │ OpenRouter│       │ OpenRouter│       │           │       │ (GPT-Img) │
  │ Google  │         │ Google AI │       │ Google AI │       │           │       │ + Feishu  │
  │ News    │         │  Studio   │       │  Studio   │       │           │       │ Image API │
  └─────────┘         └───────────┘       └───────────┘       └───────────┘       └───────────┘
```

### 2.2 核心设计原则

1. **模块化**：每个 Phase 独立运行，通过文件系统传递数据
2. **可配置**：所有 API 密钥、模型选择、参数均通过 `.env` 配置
3. **容错性**：单点故障不影响其他阶段（如 Phase 2 失败不影响 Phase 3 历史数据）
4. **LLM 无关**：通过 `shared/llm_client.py` 统一封装，支持任意 LLM 提供商

---

## 3. 各阶段技术细节

### 3.1 Phase 1 — Meme 抓取

#### 数据源
- **Reddit r/memes** (`scrapers/reddit_rapidapi_memes.py`)
  - 复用 `reddit-rader-AInews/trend-scrap/reddit-scraper` 的 RapidAPI `reddit34` 抓取模块
  - 抓取 `r/memes/hot` 与 `r/memes/top?t=day`
  - 过滤 NSFW、spoiler、stickied、视频、无图片帖子
  - 下载图片并转换为 Phase1 标准 `{"source": "...", "posts": [...]}` 输出
  - 限制：默认取最高分 10 条，需要配置 `Phase1/.env` 里的 `RAPIDAPI_KEY`

- **KnowYourMeme** (`scrapers/knowyourmeme.py`)
  - 抓取 RSS feed: `https://knowyourmeme.com/memes/all.rss`
  - 技术栈：`urllib.request` + `xml.etree.ElementTree`
  - 提取每篇文章的 JSON-LD metadata（description、image、keywords）
  - 限制：取最新 5 条

- **Google News** (`scrapers/google_news.py`)
  - 搜索 `"meme" when:1d`（最近 24 小时）
  - 技术栈：**Playwright**（渲染 JS 页面）+ **trafilatura**（文章内容提取）
  - 过滤加密货币相关内容（标题含 coin/crypto/token/blockchain 等）
  - 限制：取前 10 条非加密货币 meme 新闻

#### 合并逻辑 (`merge_sources.py`)
- 读取所有 scraper 输出 JSON（格式：`{"source": "xxx", "posts": [...]}`）
- 按 `source` 字段分组合并为单个 `scraped_posts.json`

#### 输出格式
```json
{
  "knowyourmeme": {
    "posts": [
      {
        "source": "knowyourmeme",
        "title": "...",
        "url": "...",
        "image_url": "...",
        "local_image_path": "...",
        "description": "...",
        "keywords": "...",
        "published": "..."
      }
    ]
  },
  "google_news": {
    "posts": [...]
  }
}
```

#### 关键实现细节
- KYM scraper 通过 `extract_json_ld()` 从 HTML 中提取 `application/ld+json` 脚本块
- Google News scraper 使用 JS 注入在 DOM 中定位 `C-WIZ` 元素来提取文章卡片
- 两个 scraper 通过 `run.sh` 中的 `&` 在后台并行运行

---

### 3.2 Phase 1.5 — Meme 图片理解

#### 核心逻辑 (`Phase1_5/meme_understanding.py`)
- 读取 Phase 1 的 `scraped_posts.json`，保持原有 `source -> posts` 结构。
- 对带图片的帖子调用 OpenAI 视觉模型（默认沿用 `Phase2/.env` 的 `OPENAI_MODEL=gpt-5.4-mini`）。
- 输出 `meme_understanding`，包含：
  - `visible_text`：图片 OCR 文本。
  - `visual_elements`：主要视觉元素。
  - `punchline` / `why_funny`：核心笑点与为什么好笑。
  - `boxy_adaptation.core_twist_to_preserve`：Phase 2 必须保留的反差/误导结构。
  - `quality_flags`：图片不清晰、不是 meme、强依赖外部语境等风险。
- 默认把简明解析追加到 `description`，让旧的 Phase 2 prompt 也能获得关键语境。

#### 设计目的
- 弥补小模型只看标题时容易“脑补主题但漏掉图片笑点”的问题。
- 将视觉理解、关卡生成、筛选解耦，便于单独替换模型或重跑某一层。
- 给 Phase 3 提供源 meme 的 punchline，用于判断关卡是否偏离原梗。

### 3.3 Phase 2 — 关卡设计生成

#### 核心逻辑 (`synthesizer.py`)
采用 **两步式 LLM 调用** 提高 JSON 输出可靠性：

**Step 1：叙事设计**
- 输入：meme 标题 + 描述 + 关键词 + 游戏背景 + 设计要求
- 输出：自然语言描述的关卡设计

**Step 2：JSON 格式化**
- 输入：Step 1 的叙事设计
- 输出：严格符合预定义 schema 的 JSON

#### Prompt 设计
- `background.txt`：Boxy 游戏核心设计理念
- `response_point.txt`：关卡设计必须回答的检查点
- `hint_from_Feishu.txt`：从飞书 Wiki 动态获取的设计团队反馈
- 当前生成约束：关卡应贴合实际 Boxy 手绘漫画风横版界面，保持稀疏构图，核心解谜点通常不超过 3 个，避免长流程和多机关堆叠

#### 输出 JSON Schema
```json
{
  "level_name": "关卡名称",
  "meme_inspiration": "meme 灵感来源",
  "surface_layer": "表层描述",
  "misdirection_layer": "误导层描述",
  "full_game_flow": "完整流程",
  "hint_design": {
    "hint_text": "提示文字",
    "surface_meaning": "表面含义",
    "actual_meaning": "实际含义",
    "participates_in_gameplay": false
  },
  "design_check": {
    "short_path": true,
    "no_new_elements": true,
    "rational_but_unexpected": true,
    "hint_gives_direction": true,
    "progression_with_previous": true
  }
}
```

#### 关键实现细节
- 使用 `extract_json()` 处理 LLM 返回的 markdown 代码块（去除 ```json 包裹）
- 每个 meme 生成一个设计，输出为 JSON 对象，键为 meme 标题
- 5 秒间隔防止 API 限流

---

### 3.4 Phase 3 — 筛选与排序

#### 核心逻辑 (`filter_and_select.py`)
**两步式筛选**：

**Step 1：独立过滤（Filter）**
- 对每个关卡设计单独调用 LLM 评估
- Prompt 要求：先写 2-3 句评估理由，最后单独一行写 `accept` 或 `reject`
- 额外硬性规则：若设计超过 3 个解谜点、流程过长、画面元素过密，或不适合实际 Boxy 手绘漫画风 UI，应直接 reject
- 解析逻辑（按优先级）：
  1. 最后一行是否含 accept/reject
  2. 全文是否含 accept/reject
  3. 两者都出现时取最后出现的那个
  4. 都没有时默认 accept（防止误杀）

**Step 2：比较排序（Select）**
- 将所有通过过滤的设计编号后一次性提交给 LLM
- LLM 只返回编号（如 `2\n5\n1`），代码直接按编号映射
- 避免字符串匹配导致的 fragile 解析

#### 配置参数
- `TOP_N`：选择前 N 个最优设计（通过 `.env` 配置，默认 3）
- `max_tokens`：过滤阶段 2048，选择阶段 256

#### 已知问题与修复历史
| 问题 | 原因 | 修复方案 |
|------|------|----------|
| 所有设计都被 accept | `max_tokens=512` 导致回复被截断，无法到达 verdict 词 | 提升到 2048 |
| 字符串匹配选错设计 | 设计标题含特殊字符，LLM 返回格式不一致 | 改为编号式选择 |

---

### 3.5 Phase 4 — 飞书推送

#### 核心逻辑 (`push_feishu.py`)
1. 读取 Phase 3 输出的 JSON 数组
2. 为每个设计构建飞书交互式卡片（`interactive` 消息类型）
3. 通过飞书 `im/v1/messages` API 推送到指定群聊

#### 卡片结构
- Header：紫色主题，标题为关卡名称
- Elements：灵感来源、表层、误导层、完整流程、提示设计、来源链接

#### 关键实现细节
- 卡片内容 JSON 通过 `json.dumps(card, ensure_ascii=False)` 序列化后作为 `content` 字段
- 每张卡片独立 try/except，单张失败不影响其他卡片推送
- 支持错误码 `230002`（Bot 不在群聊中）的友好提示

---

### 3.6 Phase 5 — 关卡可视化

#### 核心逻辑 (`visualize.py`)
1. 读取 Phase 3 输出的 JSON 数组（与 Phase 4 相同输入）
2. 对每个关卡设计，通过 ChatGPT 网页端（GPT-Image2）生成 Boxy 手绘漫画风游戏截图
3. 将图片上传到飞书 `im/v1/images` API，获取 `image_key`
4. 构建带图片的飞书交互式卡片并推送到群聊

#### 子模块

| 文件 | 功能 |
|------|------|
| `chatgpt_browser.py` | ChatGPT 网页端浏览器自动化（Playwright） |
| `image_prompt_builder.py` | 关卡设计 JSON → 图像生成 prompt 转换 |
| `feishu_image.py` | 飞书图片上传 + 带图卡片构建与推送 |
| `visualize.py` | 主入口，编排完整流程 |

#### 浏览器自动化方案

使用 Playwright `launch_persistent_context(channel="chrome")` 连接系统安装的 Chrome 浏览器：

- **Chrome 模式**（推荐）：使用系统 Chrome + 独立用户配置文件（`Phase5/chrome_profile/`），登录状态跨次运行持久化
- **Standalone 模式**：使用 Playwright 内置 Chromium + Cookie 文件管理

关键实现细节：
- 登录检测：通过检查 `login-button` / `signup-button` 是否存在判断登录状态（而非仅检查 textarea）
- 图片下载：使用浏览器内 `fetch()` API 下载图片（自动携带认证 cookies），三层回退：browser fetch → canvas 提取 → urllib
- 每次生成前自动开启新对话（`_start_new_chat()`），避免上下文污染
- 生成间隔 10 秒，避免速率限制

#### 图像 Prompt 构建

`image_prompt_builder.py` 现在默认约束为实际 Boxy 参考图风格：横版 2D 手机游戏截图、手绘漫画 / 草图线条、纸张纹理、淡色背景、简洁 UI，并限制可见解谜物不超过 3 个，避免生成复杂概念图或完整解谜流程图。

| 风格 | 说明 |
|------|------|
| `game_screenshot` | Boxy 参考图风格（默认），模拟真实手机游戏截图 |
| `boxy_reference` | 与默认风格相同的显式别名 |
| `concept_art` | 稍松的制作概念图，但仍保留 Boxy 横版截图布局 |
| `diagram` | 内部审阅用的简洁示意变体，只允许少量游戏内标签 |

#### 飞书带图卡片结构

- Header：紫色主题，标题为关卡名称
- 图片：顶部展示生成的 Boxy 风格截图
- Elements：灵感来源、表层、误导层、完整流程、提示设计、来源链接
- 若图片生成失败，自动回退为纯文本卡片（与 Phase 4 格式一致）

#### 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `image_style` | `game_screenshot` | 图像生成风格 |
| `generation_timeout` | `120` | 单张图片生成超时（秒） |
| `CHATGPT_USE_CHROME` | `false` | 是否使用系统 Chrome |
| `CHATGPT_HEADLESS` | `false` | 是否无头模式 |

---

## 4. 共享模块

### `shared/llm_client.py`

统一的 LLM 客户端，封装 OpenAI、OpenRouter 和 Google AI Studio 三种后端；每次运行只激活一个 provider。

#### 架构设计
```python
class LLMClient:
    def __init__(self):
        # 根据 LLM_PROVIDER 环境变量自动选择后端
        
    def call(self, prompt, system_message="", model=None, ...):
        # 统一调用接口，自动路由到对应后端
```

#### 环境变量映射
| 环境变量 | OpenAI 含义 | OpenRouter 含义 | Google 含义 |
|----------|-------------|----------------|-------------|
| `LLM_PROVIDER` | `openai`（默认） | `openrouter` | `google` |
| `LLM_API_KEY` | 通用备用 key | 通用备用 key | 通用备用 key |
| `OPENAI_API_KEY` | OpenAI API key | — | — |
| `OPENAI_MODEL` | 主模型（默认 `gpt-5.4-mini`） | — | — |
| `OPENAI_MODEL_DROP` | 备用模型 | — | — |
| `OPENROUTER_API_KEY` | — | OpenRouter API key | — |
| `OPENROUTER_MODEL` | — | 主模型 | — |
| `OPENROUTER_MODEL_DROP` | — | 备用模型 | — |
| `GOOGLE_API_KEY` | — | — | Google AI Studio API key |
| `GOOGLE_MODEL` | — | — | 主模型（默认 `gemini-3.1-flash-lite-preview`） |
| `GOOGLE_MODEL_DROP` | — | — | 备用模型 |

#### 后端差异处理
- **OpenAI**：使用 `openai` SDK，默认模型为 `gpt-5.4-mini`，在 Chat Completions 中使用 `developer` message
- **OpenRouter**：使用 `openai` SDK，支持 system message、timeout 参数
- **Google AI Studio**：使用 `google-genai` SDK，不支持独立 system message（拼接在 prompt 前）
- 三个后端均支持 provider 内部的 fallback 模型切换
- `*_MODEL_DROP` 只在同一 provider 内降级，不会自动切换到其他 provider

---

## 5. 环境配置指南

### 5.1 最小可运行配置

#### Phase 2 `.env`
```bash
# OpenAI（默认）
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.4-mini

# OpenRouter（手动切换备用；切换时改 LLM_PROVIDER=openrouter）
# OPENROUTER_API_KEY=sk-or-v1-...
# OPENROUTER_MODEL=google/gemini-3.1-pro-preview
# OPENROUTER_MODEL_DROP=anthropic/claude-opus-4.6

# Google AI Studio（手动切换备用；切换时改 LLM_PROVIDER=google）
# GOOGLE_API_KEY=AIzaSy...
# GOOGLE_MODEL=gemini-3.1-flash-lite-preview
```

#### Phase 3 `.env`
```bash
# 同 Phase 2 的 LLM 配置
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.4-mini

# 额外配置
TOP_N=4
```

> 注意：同一个 `.env` 文件里只保留一个未注释的 `LLM_PROVIDER=...`。如果写了多个，最后一个会覆盖前面的配置。

#### Phase 4 `.env`
```bash
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FEISHU_CHAT_ID=oc_xxxxxxxxxxxxxxxx
```

#### Phase 5 `.env`
```bash
# 飞书凭证（同 Phase 4）
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FEISHU_CHAT_ID=oc_xxxxxxxxxxxxxxxx

# Chrome 模式（推荐，登录状态持久化）
CHATGPT_USE_CHROME=true

# 图像生成设置
IMAGE_STYLE=game_screenshot
GENERATION_TIMEOUT=120
```

### 5.2 依赖安装

```bash
# 核心依赖
pip install requests python-dotenv

# Phase 1 - Google News 抓取
pip install playwright trafilatura
playwright install chromium

# Phase 2/3 - LLM
pip install -U openai     # OpenAI / OpenRouter
pip install google-genai  # Google AI Studio

# Phase 4 - 飞书
pip install requests python-dotenv

# Phase 5 - 可视化
pip install playwright python-dotenv requests
# Chrome 模式无需额外安装浏览器驱动
```

---

## 6. 测试指南

### 6.1 端到端测试

```bash
# 完整管线
bash run-pipeline.sh
```

### 6.2 分阶段测试

```bash
# Phase 1
cd Phase1 && bash run.sh

# Phase 1.5
cd Phase1_5 && python3 meme_understanding.py --max-posts 3

# Phase 2（仅生成一个设计测试）
cd Phase2 && python3 -c "
import json, os
os.environ['LLM_PROVIDER'] = 'openai'
from shared.llm_client import LLMClient
c = LLMClient()
print(c.call(prompt='设计一个简单关卡', max_tokens=500))
"

# Phase 3（测试过滤逻辑）
cd Phase3 && python3 filter_and_select.py

# Phase 4（仅测试 API 连通性）
cd Phase4 && python3 -c "
from push_feishu import get_tenant_token
import os
print(get_tenant_token(os.environ['FEISHU_APP_ID'], os.environ['FEISHU_APP_SECRET']))
"

# Phase 5（使用 Chrome 模式生成第 1 个关卡的概念图）
cd Phase5 && python3 visualize.py --use-chrome --only 1
```

### 6.3 冒烟测试清单

| 测试项 | 命令 | 预期结果 |
|--------|------|----------|
| Reddit r/memes 抓取 | `python3 Phase1/scrapers/reddit_rapidapi_memes.py --output /tmp/reddit.json --max-posts 10` | 输出最多 10 条记录 |
| KYM 抓取 | `python3 Phase1/scrapers/knowyourmeme.py --output /tmp/k.json` | 输出 5 条记录 |
| Google News 抓取 | `python3 Phase1/scrapers/google_news.py --output /tmp/g.json` | 输出 10 条记录 |
| LLM 连通性 | `python3 -c "from shared.llm_client import LLMClient; print(LLMClient().call('hi'))"` | 返回非空字符串 |
| 飞书连通性 | `python3 Phase4/push_feishu.py` | 成功推送卡片 |
| Phase 5 可视化 | `python3 Phase5/visualize.py --use-chrome --only 1` | 生成图片并推送带图卡片 |

---

## 7. 常见问题排查

### 7.1 Phase 1

**问题：Google News 返回 0 条结果**
- 检查 Playwright 是否安装：`playwright install chromium`
- 检查网络连接
- Google News 页面结构变更可能导致选择器失效，需更新 `google_news.py` 中的 JS 注入逻辑

**问题：KYM 返回空 description**
- KYM 网站的 JSON-LD 格式可能变更
- 检查 `extract_json_ld()` 中的正则匹配是否仍有效

### 7.2 Phase 2/3

**问题：所有设计都返回 "accepted"**
- 检查 `max_tokens` 是否足够（应 >= 2048）
- 查看 raw model output 确认是否被截断

**问题：JSON 解析失败**
- LLM 可能输出了 markdown 代码块
- `extract_json()` 已处理此情况，若仍失败需检查 LLM 输出格式

**问题：Google AI Studio 返回 404**
- 模型名称错误。可用以下命令查询有效模型名：
```python
from google import genai
client = genai.Client(api_key='your-key')
for m in client.models.list():
    if 'gemini' in m.name.lower():
        print(m.name)
```

### 7.3 Phase 4

**问题：Error 230002**
- 将 Bot 添加到目标飞书群聊
- 或检查 `FEISHU_CHAT_ID` 是否正确

**问题：400 Bad Request**
- 卡片内容过大（>20KB）
- 检查 `build_card()` 输出的 JSON 大小

### 7.4 Phase 5

**问题：Chrome 启动失败**
- 确保系统已安装 Google Chrome
- 关闭所有正在运行的 Chrome 窗口后重试（Playwright 需要独占启动 Chrome）
- 如果使用 `--use-chrome` 模式，确保没有其他 Chrome 实例正在使用同一个用户配置文件

**问题：ChatGPT 未登录**
- 首次运行时，脚本会打开 Chrome 窗口等待手动登录
- 登录后状态保存在 `Phase5/chrome_profile/` 中，后续运行自动使用
- 如果登录状态过期，删除 `chrome_profile/` 目录后重新运行

**问题：图片生成超时**
- 增加 `GENERATION_TIMEOUT`（默认 120 秒）
- ChatGPT 可能遇到速率限制，等待几分钟后重试
- 使用 `--only N` 参数逐个生成，避免连续请求

**问题：图片下载失败**
- ChatGPT 生成的图片 URL 需要认证 cookies
- 脚本已使用浏览器内 `fetch()` API 自动携带 cookies
- 如果仍然失败，检查网络连接和 ChatGPT 账号状态

**问题：ChatGPT DOM 选择器失效**
- OpenAI 可能更新 ChatGPT 网页版 DOM 结构
- 检查 `chatgpt_browser.py` 中 `SELECTORS` 字典的选择器是否仍然有效
- 使用浏览器开发者工具检查新的 DOM 结构并更新选择器

---

## 8. 维护与扩展

### 8.1 添加新的 Meme 数据源

1. 在 `Phase1/scrapers/` 下创建新的 scraper 脚本
2. 输出格式必须包含 `{"source": "xxx", "posts": [...]}`
3. 每个 post 对象必须包含字段：`title`, `url`, `description`, `published`
4. 在 `Phase1/config.json` 中添加平台配置
5. `run.sh` 会自动发现并并行运行新 scraper

### 8.2 更换 LLM 提供商

只需修改 `.env`：
- 已有 `shared/llm_client.py` 封装，无需改动业务代码
- 如需支持新提供商，在 `llm_client.py` 中添加新的 `_init_xxx()` 和 `_call_xxx()` 方法

### 8.3 调整筛选严格度

在 `Phase3/filter_and_select.py` 的 `build_filter_prompt()` 中修改：
- 提示词中的 `"please be very strict"` 段落
- 可添加更具体的评分标准

### 8.4 修改飞书卡片样式

在 `Phase4/push_feishu.py` 的 `build_card()` 中调整：
- `header.template`：颜色主题（purple/blue/red/green/yellow/orange）
- `elements` 数组：增删展示字段

---

## 9. 已知限制

1. **Google News 依赖 JS 渲染**：若 Google 更改页面结构，选择器可能失效
2. **LLM 输出不可控**：即使有两步式 prompt，仍偶尔出现格式异常
3. **飞书卡片大小限制**：单张卡片 content JSON 不能超过约 20KB
4. **无持久化数据库**：所有数据通过文件系统传递，历史数据管理依赖文件覆盖
5. **ChatGPT 网页端依赖**：Phase 5 依赖 ChatGPT 网页版 DOM 结构，OpenAI 更新可能导致选择器失效
6. **Chrome 独占启动**：Phase 5 运行时需要独占 Chrome 浏览器，不能同时使用其他 Chrome 窗口

---

## 10. 文件清单

| 文件 | 用途 | 修改频率 |
|------|------|----------|
| `run-pipeline.sh` | 总调度脚本 | 低 |
| `shared/llm_client.py` | 统一 LLM 客户端 | 中 |
| `Phase1/config.json` | 数据源配置 | 低 |
| `Phase1/run.sh` | Phase 1 调度 | 低 |
| `Phase1/merge_sources.py` | 多源合并 | 低 |
| `Phase1/scrapers/knowyourmeme.py` | KYM 抓取 | 中 |
| `Phase1/scrapers/google_news.py` | Google News 抓取 | 高（页面结构变更） |
| `Phase2/.env` | LLM 配置 | 中 |
| `Phase2/run.sh` | Phase 2 调度 | 低 |
| `Phase2/synthesizer.py` | 关卡生成 | 中 |
| `Phase2/background.txt` | 游戏背景 | 低 |
| `Phase2/response_point.txt` | 设计要求 | 低 |
| `Phase2/hint_from_Feishu.txt` | 动态反馈 | 高（每次运行更新） |
| `Phase3/.env` | LLM + TOP_N 配置 | 中 |
| `Phase3/run.sh` | Phase 3 调度 | 低 |
| `Phase3/filter_and_select.py` | 筛选排序 | 中 |
| `Phase3/config.json` | 输入输出路径 | 低 |
| `Phase4/.env` | 飞书凭证 | 低 |
| `Phase4/run.sh` | Phase 4 调度 | 低 |
| `Phase4/push_feishu.py` | 飞书推送 | 中 |
| `Phase4/config.json` | 输入路径 | 低 |
| `Phase5/.env` | 飞书凭证 + Chrome 配置 | 低 |
| `Phase5/run.sh` | Phase 5 调度 | 低 |
| `Phase5/visualize.py` | 可视化主入口 | 中 |
| `Phase5/chatgpt_browser.py` | ChatGPT 浏览器自动化 | 高（DOM 变更） |
| `Phase5/image_prompt_builder.py` | 图像 prompt 构建 | 中 |
| `Phase5/feishu_image.py` | 飞书图片上传 + 带图卡片 | 中 |
| `Phase5/config.json` | 输入输出路径 + 图像设置 | 低 |

---

## 11. 附录：完整目录树

```
BoxyIdea/
├── run-pipeline.sh              # 总调度脚本（5 阶段）
├── user_guide.md                # 用户操作指南
├── handoff_document.md          # 本交接文档
├── shared/
│   └── llm_client.py            # 统一 LLM 客户端
├── Phase1/
│   ├── run.sh
│   ├── config.json              # 数据源配置
│   ├── merge_sources.py         # 多源数据合并
│   └── scrapers/
│       ├── knowyourmeme.py      # KYM RSS 抓取器
│       └── google_news.py       # Google News Playwright 抓取器
├── Phase2/
│   ├── run.sh
│   ├── .env                     # LLM 提供商配置
│   ├── config.json              # 输入输出路径
│   ├── synthesizer.py           # 两步式 LLM 关卡生成
│   ├── fetch_feishu_hint.py     # 飞书 Wiki 反馈拉取
│   ├── background.txt           # 游戏设计哲学
│   ├── response_point.txt       # 设计约束检查点
│   └── hint_from_Feishu.txt     # 动态设计反馈
├── Phase3/
│   ├── run.sh
│   ├── .env                     # LLM + TOP_N 配置
│   ├── config.json              # 输入输出路径
│   ├── filter_and_select.py     # 过滤 + 排序
│   └── output/
│       ├── accepted_levels.json # 通过过滤的设计
│       └── Phase3_result.txt    # 最终选中的设计
├── Phase4/
│   ├── run.sh
│   ├── .env                     # 飞书凭证
│   ├── config.json              # 输入路径
│   ├── push_feishu.py           # 飞书卡片推送
│   ├── requirements.txt         # 依赖列表
│   └── output/
│       └── feishu_card_*.json   # 生成的卡片 JSON（调试用）
└── Phase5/
    ├── run.sh
    ├── .env                     # 飞书凭证 + Chrome 配置
    ├── .env.example             # 环境变量模板
    ├── config.json              # 输入路径 + 图像风格
    ├── visualize.py             # 主入口：关卡可视化管线
    ├── chatgpt_browser.py       # ChatGPT 浏览器自动化
    ├── image_prompt_builder.py  # 关卡设计 → 图像 Prompt 转换
    ├── feishu_image.py          # 飞书图片上传 + 带图卡片推送
    ├── requirements.txt         # 依赖列表
    ├── cookies/                 # Cookie 持久化目录
    │   └── .gitkeep
    ├── chrome_profile/          # Chrome 持久化用户数据（.gitignore）
    └── output/                  # 生成的概念图
        └── .gitkeep
```

---

*文档版本：2026-05-07*
*最后更新：新增 Phase 5 关卡可视化模块，支持 ChatGPT 图像生成 + 飞书带图卡片推送*
