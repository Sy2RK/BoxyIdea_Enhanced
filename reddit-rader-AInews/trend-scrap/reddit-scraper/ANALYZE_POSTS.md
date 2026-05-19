# Reddit Post Summarizer

`analyze_posts.py` reads `data/filtered-result.json` and adds a
`video_summary` field to each Reddit post. The field name is intentionally
kept for compatibility with the existing downstream pipeline.

## Workflow

1. Load Reddit posts from `data/filtered-result.json`.
2. Skip records that already have a non-error `video_summary`.
3. Use the configured LLM provider to summarize title, body, subreddit, URL,
   score, comments, and source metadata.
4. Save progress after every post.

## Usage

```bash
python analyze_posts.py
```

The script uses the same LLM configuration as the main pipeline, loaded from
`scripts/.env` or environment variables.
