/**
 * Reddit Scraper - Main Entry
 *
 * Uses the RapidAPI reddit34 API to collect Reddit AI trend posts,
 * normalize them into the existing pipeline JSON contract, and export
 * data/filtered-result.json for downstream analysis.
 */

require('dotenv').config();
const fs = require('fs');
const path = require('path');
const axios = require('axios');

function loadFeedbackRules() {
  const rulesPath = path.join(__dirname, '..', '..', '..', 'references', 'reddit_feedback_optimization_rules.json');
  if (!fs.existsSync(rulesPath)) {
    return {};
  }
  try {
    return JSON.parse(fs.readFileSync(rulesPath, 'utf-8'));
  } catch (error) {
    console.warn(`Warning: failed to load reddit feedback rules, falling back to scraper config: ${error.message}`);
    return {};
  }
}

function getRuleScrapeConfig(rules) {
  const scrape = rules && typeof rules === 'object' ? (rules.scrape || {}) : {};
  const searchQueries = Array.isArray(scrape.search_queries)
    ? scrape.search_queries.map(query => String(query || '').trim()).filter(Boolean)
    : [];
  const resultsPerKeyword = Number.parseInt(scrape.results_per_keyword, 10);
  return {
    searchQueries,
    resultsPerKeyword: Number.isFinite(resultsPerKeyword) && resultsPerKeyword > 0 ? resultsPerKeyword : null
  };
}

function parseCsvList(value) {
  if (!value) {
    return [];
  }
  if (Array.isArray(value)) {
    return value.map(item => String(item || '').trim()).filter(Boolean);
  }
  return String(value)
    .split(/[\n,;]+/)
    .map(item => item.trim())
    .filter(Boolean);
}

function asNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function buildRedditUrl(permalink) {
  if (!permalink) {
    return '';
  }
  if (/^https?:\/\//i.test(permalink)) {
    return permalink;
  }
  return `https://www.reddit.com${permalink}`;
}

function extractPostData(item) {
  if (!item) {
    return null;
  }
  if (item.data && typeof item.data === 'object') {
    return item.data;
  }
  return item;
}

function extractPosts(payload) {
  const data = payload && payload.data ? payload.data : payload;
  if (!data) {
    return [];
  }
  if (Array.isArray(data.posts)) {
    return data.posts.map(extractPostData).filter(Boolean);
  }
  if (Array.isArray(data.children)) {
    return data.children.map(extractPostData).filter(Boolean);
  }
  if (Array.isArray(data)) {
    return data.map(extractPostData).filter(Boolean);
  }
  return [];
}

const DEFAULT_SUBREDDITS = [
  'ArtificialInteligence',
  'singularity',
  'OpenAI',
  'ChatGPT',
  'LocalLLaMA',
  'StableDiffusion',
  'aivideo'
];

const CONFIG = {
  forcePublicReddit: ['1', 'true', 'yes'].includes(String(process.env.REDDIT_USE_PUBLIC || '').toLowerCase()),
  rapidApiKey: process.env.RAPIDAPI_KEY || '',
  rapidApiHost: process.env.RAPIDAPI_HOST || 'reddit34.p.rapidapi.com',
  redditUserAgent: process.env.REDDIT_USER_AGENT || 'reddit-rader-AInews/1.0',
  resultsPerKeyword: 15,
  requestDelayMs: 350,
  defaultQueries: ['aifilter', 'aivideo', 'aiphoto', 'aidance'],
  subreddits: DEFAULT_SUBREDDITS,
  popularSorts: ['hot', 'new'],
  subredditSort: 'hot',
  subredditTopTime: 'day',
  dataDir: path.join(__dirname, '..', 'data'),
  filters: {
    minPlayCount: 0,
    minDiggCount: 0,
    minShareCount: 0
  }
};

class RedditScraper {
  constructor(config = {}) {
    this.config = {
      ...CONFIG,
      ...config,
      filters: { ...CONFIG.filters, ...(config.filters || {}) }
    };
    this.rawData = [];
    this.filteredData = [];
    this.usePublicReddit = this.config.forcePublicReddit || !this.config.rapidApiKey;

    if (!fs.existsSync(this.config.dataDir)) {
      fs.mkdirSync(this.config.dataDir, { recursive: true });
    }

    if (this.usePublicReddit) {
      console.warn('Warning: RAPIDAPI_KEY is missing; falling back to reddit.com public JSON endpoints.');
      this.client = axios.create({
        baseURL: 'https://www.reddit.com',
        timeout: 30000,
        headers: {
          'User-Agent': this.config.redditUserAgent
        }
      });
    } else {
      this.client = axios.create({
        baseURL: `https://${this.config.rapidApiHost}`,
        timeout: 30000,
        headers: {
          'X-RapidAPI-Key': this.config.rapidApiKey,
          'X-RapidAPI-Host': this.config.rapidApiHost
        }
      });
    }
  }

  async delay() {
    const delayMs = Number(this.config.requestDelayMs || 0);
    if (delayMs <= 0) {
      return;
    }
    await new Promise(resolve => setTimeout(resolve, delayMs));
  }

  async requestPosts(endpoint, params, label) {
    const request = this.buildRequest(endpoint, params);
    console.log(`  - Fetching ${label}: ${request.endpoint} ${JSON.stringify(request.params)}`);
    const response = await this.client.get(request.endpoint, { params: request.params });
    const payload = response.data;
    if (!this.usePublicReddit && (!payload || payload.success !== true)) {
      throw new Error(`reddit34 ${label} failed: ${JSON.stringify(payload)}`);
    }
    const posts = extractPosts(payload);
    console.log(`    received ${posts.length} posts`);
    await this.delay();
    return posts;
  }

  buildRequest(endpoint, params = {}) {
    if (!this.usePublicReddit) {
      return { endpoint, params };
    }

    const limit = Number(params.limit || params.resultsPerKeyword || this.config.resultsPerKeyword || 25);
    if (endpoint === '/getSearchPosts') {
      return {
        endpoint: '/search.json',
        params: {
          q: params.query || '',
          sort: 'new',
          t: 'week',
          limit
        }
      };
    }
    if (endpoint === '/getPopularPosts') {
      const sort = params.sort === 'new' ? 'new' : 'hot';
      return {
        endpoint: `/r/all/${sort}.json`,
        params: { limit: Math.max(limit, 50) }
      };
    }
    if (endpoint === '/getPostsBySubreddit') {
      const subreddit = encodeURIComponent(params.subreddit || 'all');
      const sort = params.sort === 'new' ? 'new' : 'hot';
      return {
        endpoint: `/r/${subreddit}/${sort}.json`,
        params: { limit: Math.max(limit, 50) }
      };
    }
    if (endpoint === '/getTopPostsBySubreddit') {
      const subreddit = encodeURIComponent(params.subreddit || 'all');
      return {
        endpoint: `/r/${subreddit}/top.json`,
        params: {
          t: params.time || 'day',
          limit: Math.max(limit, 50)
        }
      };
    }
    return { endpoint, params: { ...params, limit } };
  }

  async scrape(queries = [], customParams = {}) {
    console.log('='.repeat(50));
    console.log('Reddit Scraper - Greatbay Studio');
    console.log('='.repeat(50));

    const finalQueries = (queries && queries.length > 0 ? queries : this.config.defaultQueries)
      .map(query => String(query || '').trim())
      .filter(Boolean);
    const subreddits = parseCsvList(customParams.subreddits || this.config.subreddits);
    const popularSorts = parseCsvList(customParams.popularSorts || this.config.popularSorts);
    const resultsPerKeyword = Number(customParams.resultsPerKeyword || this.config.resultsPerKeyword || 15);

    this.rawData = [];
    const seenIds = new Set();
    const addPosts = (posts, source) => {
      let added = 0;
      for (const post of posts) {
        const id = String(post.id || post.name || '').trim();
        if (!id || seenIds.has(id)) {
          continue;
        }
        seenIds.add(id);
        this.rawData.push({ ...post, _source: source });
        added++;
      }
      console.log(`    added ${added} unique posts from ${source}`);
    };

    for (const query of finalQueries) {
      try {
        const posts = await this.requestPosts('/getSearchPosts', { query }, `search:${query}`);
        addPosts(posts.slice(0, resultsPerKeyword), `search:${query}`);
      } catch (error) {
        console.warn(`Warning: search query "${query}" failed: ${error.message}`);
      }
    }

    for (const sort of popularSorts) {
      try {
        const posts = await this.requestPosts('/getPopularPosts', { sort }, `popular:${sort}`);
        addPosts(posts, `popular:${sort}`);
      } catch (error) {
        console.warn(`Warning: popular sort "${sort}" failed: ${error.message}`);
      }
    }

    for (const subreddit of subreddits) {
      try {
        const posts = await this.requestPosts(
          '/getPostsBySubreddit',
          { subreddit, sort: customParams.subredditSort || this.config.subredditSort, limit: resultsPerKeyword },
          `subreddit:${subreddit}`
        );
        addPosts(posts, `subreddit:${subreddit}`);
      } catch (error) {
        console.warn(`Warning: subreddit "${subreddit}" failed: ${error.message}`);
      }

      try {
        const posts = await this.requestPosts(
          '/getTopPostsBySubreddit',
          { subreddit, time: customParams.subredditTopTime || this.config.subredditTopTime, limit: resultsPerKeyword },
          `subreddit_top:${subreddit}`
        );
        addPosts(posts, `subreddit_top:${subreddit}`);
      } catch (error) {
        console.warn(`Warning: top subreddit "${subreddit}" failed: ${error.message}`);
      }
    }

    if (this.rawData.length === 0) {
      throw new Error('No Reddit posts fetched from reddit34');
    }

    this.saveRawData(finalQueries);
    this.cleanAndFilter();
    this.saveFilteredData();

    return {
      rawCount: this.rawData.length,
      filteredCount: this.filteredData.length,
      data: this.filteredData
    };
  }

  cleanAndFilter() {
    this.filteredData = this.rawData
      .map(item => this.cleanItem(item))
      .filter(item => this.filterItem(item));
    console.log(`Filtered data: ${this.filteredData.length} posts`);
  }

  cleanItem(item) {
    const title = String(item.title || '').trim();
    const selftext = String(item.selftext || '').trim();
    const text = [title, selftext].filter(Boolean).join('\n\n');
    const score = asNumber(item.score || item.ups, 0);
    const comments = asNumber(item.num_comments, 0);
    const createdUtc = asNumber(item.created_utc || item.created, 0);
    const permalink = buildRedditUrl(item.permalink);
    const sourceType = item._source || 'reddit';
    const externalUrl = item.url_overridden_by_dest || item.url || '';
    const isVideo = Boolean(item.is_video || item.media?.reddit_video || item.secure_media?.reddit_video);
    const sourcePostType = isVideo ? 'video' : (item.is_self ? 'text' : (item.post_hint || 'link'));
    const hotScore = Math.max(0, score) + Math.max(0, comments) * 5;

    return {
      id: item.id || '',
      text,
      textLanguage: 'unknown',
      hashtags: [
        item.subreddit ? { name: item.subreddit } : null,
        item.link_flair_text ? { name: item.link_flair_text } : null
      ].filter(Boolean),
      diggCount: score,
      shareCount: comments,
      playCount: hotScore,
      videoMeta: {
        duration: 0,
        downloadAddr: '',
        webVideoUrl: permalink || externalUrl
      },
      authorMeta: {
        name: item.author || '',
        nickName: item.author || '',
        fans: asNumber(item.subreddit_subscribers, 0)
      },
      createTime: createdUtc,
      createTimeISO: createdUtc ? new Date(createdUtc * 1000).toISOString() : '',
      sourcePlatform: 'reddit',
      redditMeta: {
        subreddit: item.subreddit || '',
        subreddit_prefixed: item.subreddit_name_prefixed || '',
        author: item.author || '',
        score,
        ups: asNumber(item.ups || score, score),
        comments,
        upvote_ratio: asNumber(item.upvote_ratio, 0),
        external_url: externalUrl,
        permalink: permalink || '',
        source_type: sourcePostType,
        source: sourceType,
        domain: item.domain || '',
        over_18: Boolean(item.over_18)
      }
    };
  }

  filterItem(item) {
    const filters = this.config.filters || {};
    if (item.playCount < asNumber(filters.minPlayCount, 0)) {
      return false;
    }
    if (item.diggCount < asNumber(filters.minDiggCount, 0)) {
      return false;
    }
    if (item.shareCount < asNumber(filters.minShareCount, 0)) {
      return false;
    }
    return true;
  }

  saveRawData(queries) {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const queryStr = queries && queries.length > 0 ? queries.join('_') : 'reddit';
    const filename = `raw_reddit_${queryStr}_${timestamp}.json`;
    const rawDir = path.join(this.config.dataDir, 'raw');
    if (!fs.existsSync(rawDir)) {
      fs.mkdirSync(rawDir, { recursive: true });
    }
    fs.writeFileSync(path.join(rawDir, filename), JSON.stringify(this.rawData, null, 2), 'utf-8');
    console.log(`Raw data saved: ${filename}`);
    return filename;
  }

  saveFilteredData() {
    const filepath = path.join(this.config.dataDir, 'filtered-result.json');
    fs.writeFileSync(filepath, JSON.stringify(this.filteredData, null, 2), 'utf-8');
    console.log(`Filtered result exported: filtered-result.json (${this.filteredData.length} posts)`);
    return 'filtered-result.json';
  }

  getStatistics() {
    if (!this.filteredData.length) {
      return null;
    }
    const totalScore = this.filteredData.reduce((sum, item) => sum + asNumber(item.diggCount, 0), 0);
    const totalComments = this.filteredData.reduce((sum, item) => sum + asNumber(item.shareCount, 0), 0);
    return {
      totalPosts: this.filteredData.length,
      totalScore,
      totalComments,
      avgScore: Math.round(totalScore / this.filteredData.length),
      avgComments: Math.round(totalComments / this.filteredData.length)
    };
  }
}

async function main() {
  const configPath = path.join(__dirname, '..', 'config', 'config.json');
  let userConfig = {};
  if (fs.existsSync(configPath)) {
    userConfig = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
  }

  const feedbackRules = loadFeedbackRules();
  const ruleScrapeConfig = getRuleScrapeConfig(feedbackRules);
  const configuredCustomParams = userConfig.customParams || {};
  const scraper = new RedditScraper({
    rapidApiKey: userConfig.rapidApiKey || process.env.RAPIDAPI_KEY,
    rapidApiHost: userConfig.rapidApiHost || process.env.RAPIDAPI_HOST || CONFIG.rapidApiHost,
    filters: userConfig.filters || CONFIG.filters,
    subreddits: userConfig.subreddits || configuredCustomParams.subreddits || CONFIG.subreddits,
    popularSorts: userConfig.popularSorts || configuredCustomParams.popularSorts || CONFIG.popularSorts,
    resultsPerKeyword: ruleScrapeConfig.resultsPerKeyword || userConfig.resultsPerKeyword || CONFIG.resultsPerKeyword,
    requestDelayMs: userConfig.requestDelayMs ?? CONFIG.requestDelayMs
  });

  const queries = ruleScrapeConfig.searchQueries.length > 0
    ? ruleScrapeConfig.searchQueries
    : (userConfig.defaultQueries || CONFIG.defaultQueries);

  try {
    await scraper.scrape(queries, configuredCustomParams);
    const stats = scraper.getStatistics();
    if (stats) {
      console.log('\nData statistics:');
      console.log(`  Total posts: ${stats.totalPosts}`);
      console.log(`  Total score: ${stats.totalScore.toLocaleString()}`);
      console.log(`  Total comments: ${stats.totalComments.toLocaleString()}`);
      console.log(`  Avg score: ${stats.avgScore.toLocaleString()}`);
      console.log(`  Avg comments: ${stats.avgComments.toLocaleString()}`);
    }
    console.log('\nReddit scraping complete.');
  } catch (error) {
    console.error(`Reddit scraping failed: ${error.message}`);
    process.exit(1);
  }
}

module.exports = { RedditScraper, CONFIG, extractPosts, extractPostData };

if (require.main === module) {
  main();
}
