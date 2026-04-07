"""
Article content fetcher.

Fetches and extracts readable text from news article URLs so agents
receive full article context, not just headlines and summaries.

Designed to fail gracefully — a fetch failure never aborts the analysis.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Dict

try:
    import requests
    from bs4 import BeautifulSoup
    _DEPS_AVAILABLE = True
except ImportError:
    _DEPS_AVAILABLE = False

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
}

_MAX_ARTICLE_CHARS = 2500   # Per-article character limit
_NOISE_TAGS = {"script", "style", "nav", "header", "footer", "aside", "form", "noscript"}

# Domains that are not news sources
_JUNK_DOMAINS = {
    "facebook.com", "twitter.com", "x.com", "linkedin.com", "instagram.com",
    "reddit.com", "skyscrapercity.com", "wikipedia.org", "wikidata.org",
    "youtube.com", "tiktok.com", "pinterest.com", "quora.com",
    "digrin.com",
}

# URL path fragments that indicate stock data pages (not news articles)
_STOCK_DATA_PATHS = (
    "/quote/", "/quotes/", "?quote=", "/equities/", "/stocks/list/",
    "/company/", "/markets/companies/", "/market-data/",
    "/symbols/", "/technicals", "/s/il/", "/stock/",
    "/money/stockdetails", "/money/stock",
)
# URL path suffixes that indicate stock data pages
_STOCK_DATA_SUFFIXES = ("/quote", "/quotes", "/technicals", "/financials")

# Domains that only serve stock data (never news articles)
_STOCK_DATA_DOMAINS = {
    "fintel.io", "stockinvest.us", "stockanalysis.com",
    "macrotrends.net", "wisesheets.io", "finbox.com",
}


@dataclass
class ArticleContent:
    title: str
    url: str
    publisher: str
    text: str           # Extracted body text (truncated)
    fetch_success: bool


def _extract_text(html: str) -> str:
    """Extract readable body text from raw HTML."""
    soup = BeautifulSoup(html, "lxml")

    # Remove noise tags
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()

    # Prefer <article> tag; fall back to <main>, then <body>
    container = soup.find("article") or soup.find("main") or soup.find("body")
    if container is None:
        return ""

    # Collect paragraph text
    paragraphs = container.find_all("p")
    if paragraphs:
        text = " ".join(p.get_text(separator=" ", strip=True) for p in paragraphs)
    else:
        text = container.get_text(separator=" ", strip=True)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fetch_one(url: str, title: str, publisher: str, timeout: int) -> ArticleContent:
    """Fetch a single article. Returns ArticleContent with fetch_success=False on any error."""
    if not url:
        return ArticleContent(title=title, url=url, publisher=publisher, text="", fetch_success=False)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code != 200:
            return ArticleContent(title=title, url=url, publisher=publisher, text="", fetch_success=False)
        text = _extract_text(resp.text)
        if len(text) < 100:  # Too short — probably a JS-rendered page or paywall
            return ArticleContent(title=title, url=url, publisher=publisher, text="", fetch_success=False)
        return ArticleContent(
            title=title,
            url=url,
            publisher=publisher,
            text=text[:_MAX_ARTICLE_CHARS],
            fetch_success=True,
        )
    except Exception:
        return ArticleContent(title=title, url=url, publisher=publisher, text="", fetch_success=False)


def fetch_articles(
    news_items: List[Dict[str, str]],
    max_articles: int = 5,
    timeout: int = 8,
) -> List[ArticleContent]:
    """
    Fetch article content for a list of news items.

    news_items: list of dicts with keys: title, publisher, url
    Returns ArticleContent for each item (fetch_success=False if unavailable).
    """
    if not _DEPS_AVAILABLE:
        return []

    results = []
    attempts = 0
    for item in news_items:
        if attempts >= max_articles:
            break
        attempts += 1
        ac = _fetch_one(
            url=item.get("url", ""),
            title=item.get("title", ""),
            publisher=item.get("publisher", ""),
            timeout=timeout,
        )
        results.append(ac)

    return results


def _is_news_url(url: str) -> bool:
    """Return False for stock-data pages and junk domains."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.lower().lstrip("www.")
        if any(domain == j or domain.endswith("." + j) for j in _JUNK_DOMAINS):
            return False
        if any(domain == j or domain.endswith("." + j) for j in _STOCK_DATA_DOMAINS):
            return False
        path = parsed.path.lower().rstrip("?#").rstrip("/")
        if any(p in path for p in _STOCK_DATA_PATHS):
            return False
        if any(path.endswith(s) for s in _STOCK_DATA_SUFFIXES):
            return False
    except Exception:
        pass
    return True


def fetch_ddg_articles(
    company_name: str,
    ticker: str,
    max_articles: int = 10,
) -> List[ArticleContent]:
    """
    Fetch recent news articles using two sources:
      1. DuckDuckGo news search (English queries) — real news with snippets
      2. Google News RSS (Hebrew queries) — Israeli news sources
    Deduplicates by URL and filters out stock-data pages and junk domains.
    """
    ticker_clean = ticker.replace(".TA", "").strip()
    short_name = " ".join(company_name.split()[:2])

    seen_urls: set = set()
    articles: List[ArticleContent] = []

    # ── Part 1: DuckDuckGo news (English, real-time results with snippets) ─
    try:
        from ddgs import DDGS
        ddgs = DDGS()
        en_queries = [
            f'"{company_name}" stock news',
            f'"{company_name}" earnings OR results OR dividend',
            f'"{ticker_clean}" TASE news',
        ]
        for query in en_queries:
            if len(articles) >= max_articles:
                break
            try:
                raw = list(ddgs.news(query, max_results=5))
            except Exception:
                continue
            for r in raw:
                url = r.get("url", "")
                title = r.get("title", "")
                if not url or not title or url in seen_urls or not _is_news_url(url):
                    continue
                seen_urls.add(url)
                articles.append(ArticleContent(
                    title=title, url=url, publisher=r.get("source", ""),
                    text=(r.get("body") or "")[:_MAX_ARTICLE_CHARS],
                    fetch_success=True,
                ))
                if len(articles) >= max_articles:
                    break
    except ImportError:
        pass

    # ── Part 2: DDG text search fallback (catches Israeli news sites) ─────
    if len(articles) < max_articles:
        try:
            from ddgs import DDGS as _DDGS
            ddgs2 = _DDGS()
            text_queries = [
                f'"{company_name}" TASE news',
                f'"{company_name}" {ticker_clean} news',
            ]
            for query in text_queries:
                if len(articles) >= max_articles:
                    break
                try:
                    raw = list(ddgs2.text(query, max_results=8))
                except Exception:
                    continue
                for r in raw:
                    url = r.get("href", "")
                    title = r.get("title", "")
                    if not url or not title or url in seen_urls or not _is_news_url(url):
                        continue
                    seen_urls.add(url)
                    articles.append(ArticleContent(
                        title=title, url=url, publisher="",
                        text=(r.get("body") or "")[:_MAX_ARTICLE_CHARS],
                        fetch_success=True,
                    ))
                    if len(articles) >= max_articles:
                        break
        except ImportError:
            pass

    # ── Part 3: Google News RSS (Hebrew + English, Israeli news sources) ──
    if len(articles) < max_articles:
        try:
            import feedparser
            rss_searches = [
                ("https://news.google.com/rss/search?q={q}&hl=iw&gl=IL&ceid=IL:iw",
                 f'"{short_name}" בורסה'),
                ("https://news.google.com/rss/search?q={q}&hl=en-US&gl=IL&ceid=IL:en",
                 f'"{company_name}" TASE'),
            ]
            for base, query in rss_searches:
                if len(articles) >= max_articles:
                    break
                try:
                    encoded = query.replace(" ", "+")
                    feed = feedparser.parse(base.format(q=encoded))
                    for entry in feed.entries[:5]:
                        url = entry.get("link", "")
                        title = entry.get("title", "")
                        source = entry.get("source", {}).get("title", "")
                        if not url or not title or url in seen_urls:
                            continue
                        seen_urls.add(url)
                        articles.append(ArticleContent(
                            title=title, url=url, publisher=source,
                            text="", fetch_success=True,
                        ))
                        if len(articles) >= max_articles:
                            break
                except Exception:
                    continue
        except ImportError:
            pass

    return articles


# Keep old name as alias for backward compatibility
def fetch_israeli_articles(
    company_name: str,
    ticker: str,
    max_articles: int = 5,
    timeout: int = 8,
) -> List[ArticleContent]:
    return fetch_ddg_articles(company_name, ticker, max_articles=max_articles)


def format_articles_for_llm(articles: List[ArticleContent], max_total_chars: int = 10000) -> str:
    """
    Render fetched article contents as a structured text block for LLM injection.
    Only includes successfully fetched articles. Returns empty string if none.
    """
    successful = [a for a in articles if a.fetch_success and a.text]
    if not successful:
        return ""

    lines = ["", "--- ONLINE ARTICLE CONTENT ---"]
    total = 0
    for i, art in enumerate(successful, 1):
        if total >= max_total_chars:
            break
        remaining = max_total_chars - total
        snippet = art.text[:remaining]
        lines += [
            f"  Article {i}: [{art.publisher}] {art.title}",
            f"  {snippet}",
            "",
        ]
        total += len(snippet)

    return "\n".join(lines)
