# BoxyIdea_Enhanced

BoxyIdea_Enhanced is a staged meme-to-level pipeline for the mobile puzzle platformer Boxy. It pulls current meme material, interprets the visual joke, compiles it into playable Boxy level concepts, filters weak ideas, and pushes review cards with both the original meme image and a generated level concept image.

## Pipeline

- **Phase1**: scrape meme/news sources, including a Reddit r/memes RapidAPI adapter.
- **Phase1.5**: enrich meme posts with visual joke understanding.
- **Phase2**: synthesize Boxy level designs from the meme understanding.
- **Phase3**: filter and rank level designs before downstream spending.
- **Phase4**: push text review cards to Feishu.
- **Phase5**: generate Boxy-style concept images and push dual-image Feishu cards.

## Configuration

Copy the relevant `.env.example` files to local `.env` files and fill in credentials. Real `.env` files are intentionally ignored by Git.

Required integrations depend on the phases you run:

- Reddit/RapidAPI credentials for r/memes scraping.
- OpenAI-compatible LLM credentials for Phase1.5 through Phase3.
- Feishu app credentials for Phase4/Phase5 push.
- A local Chrome/ChatGPT session for Phase5 image generation.

## Notes

The repository keeps only a small curated sample of generated Phase5 outputs. Runtime outputs, caches, browser profiles, raw scraped images, and credentials should stay local.
