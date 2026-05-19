# Reddit Scraper

RapidAPI `reddit34` 数据抓取器。它会抓取 Reddit AI 趋势帖子，并转换为下游流水线已有的兼容 JSON 字段。

## 配置

复制环境变量模板并填入 RapidAPI 参数：

```bash
cp .env.example .env
```

```env
RAPIDAPI_KEY=your_rapidapi_key
RAPIDAPI_HOST=reddit34.p.rapidapi.com
```

`config/config.json` 可配置搜索词、subreddit、热门排序和基础筛选条件。反馈优化器也会从 `references/reddit_feedback_optimization_rules.json` 读取 `scrape.search_queries` 和 `results_per_keyword`。

## 运行

```bash
npm install
npm start
```

输出文件：

```text
trend-scrap/reddit-scraper/data/filtered-result.json
```

## 兼容字段

为了保持现有 Python 流水线不大改，下游字段名继续保留：

| 字段 | Reddit 映射 |
|------|-------------|
| `id` | Reddit post id |
| `text` | `title + selftext` |
| `diggCount` | `score / ups` |
| `shareCount` | `num_comments` |
| `playCount` | `score + num_comments * 5` |
| `videoMeta.webVideoUrl` | Reddit permalink |
| `sourcePlatform` | `reddit` |
| `redditMeta` | subreddit、author、score、comments、upvote ratio、external url、source type |

## 测试

```bash
npm test
```
