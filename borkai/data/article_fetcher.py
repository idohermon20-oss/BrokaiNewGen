"""
Article content fetcher.

Fetches and extracts readable text from news article URLs so agents
receive full article context, not just headlines and summaries.

Designed to fail gracefully — a fetch failure never aborts the analysis.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Dict, Optional

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
    published: str = ""  # ISO date string from source (empty if unknown)


def _parse_pub_date(raw: str) -> str:
    """
    Normalise any date string to "YYYY-MM-DD HH:MM" (sortable ISO prefix).
    Returns "" if the date cannot be parsed.

    Handles:
      - ISO 8601: "2024-04-10T14:30:00+03:00" → "2024-04-10 14:30"
      - RFC 2822: "Wed, 10 Apr 2024 14:30:00 +0300" → "2024-04-10 14:30"
      - Plain date: "2024-04-10" → "2024-04-10 00:00"
      - time.struct_time objects (from feedparser)
    """
    import time as _time
    from datetime import datetime as _dt

    if not raw:
        return ""

    # struct_time from feedparser
    if isinstance(raw, _time.struct_time):
        try:
            return _dt(*raw[:6]).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ""

    s = str(raw).strip()
    if not s:
        return ""

    # ISO 8601 (most common from DDG)
    if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
        # Normalise: replace T with space, drop timezone suffix
        s2 = s.replace("T", " ").replace("Z", "")
        # Trim timezone "+03:00" or " +0300"
        for sep in (" +", " -", "+00", "+01", "+02", "+03", "+05", "+07", "+08", "+09", "+10"):
            idx = s2.find(sep, 10)
            if idx > 0:
                s2 = s2[:idx]
                break
        return s2[:16]

    # RFC 2822
    try:
        import email.utils as _eu
        return _eu.parsedate_to_datetime(s).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass

    # Common short formats
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%m/%d/%Y %H:%M", "%m/%d/%Y"):
        try:
            return _dt.strptime(s, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue

    return ""


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
        # Sanitize: remove null bytes and control characters that cause OpenAI 500 errors
        text = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
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


_TITLE_STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "in", "on", "at", "to", "of", "for",
    "is", "was", "are", "be", "has", "have", "had", "with", "from", "by",
    "its", "that", "this", "as", "it", "he", "she", "they", "we", "you",
    "not", "no", "will", "can", "may", "would", "could", "should",
})


def _title_words(title: str) -> frozenset:
    """Significant words from a title — used for near-duplicate detection."""
    words = re.findall(r"[a-zA-Z\u05d0-\u05ea0-9]+", title.lower())
    return frozenset(w for w in words if w not in _TITLE_STOP_WORDS and len(w) > 2)


def _is_near_duplicate(title: str, seen_fingerprints: list) -> bool:
    """
    Return True if title shares ≥70% word overlap with any previously seen title.
    Catches rephrased versions of the same story (different sources, same event).
    """
    fp = _title_words(title)
    if not fp:
        return False
    for seen_fp in seen_fingerprints:
        if not seen_fp:
            continue
        intersection = len(fp & seen_fp)
        union = len(fp | seen_fp)
        if union > 0 and intersection / union >= 0.70:
            return True
    return False


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
    name_he: Optional[str] = None,
    identity=None,   # Optional[CompanyIdentity] — avoids circular import
) -> List[ArticleContent]:
    """
    Fetch recent news articles using multiple query variants and two sources:
      1. DuckDuckGo news search — real-time results with snippets
      2. Google News RSS — Hebrew + English, Israeli sources

    When a CompanyIdentity is supplied the function uses *all* known name
    variants (English, ticker, Hebrew) so that Hebrew news sources are
    reached even when the caller only had an English company name.

    Deduplicates by URL and filters out stock-data pages and junk domains.
    """
    ticker_clean = ticker.replace(".TA", "").strip()

    # Build ordered query variants — English-first for DDG, Hebrew for RSS
    variants: List[str] = []
    seen_v:   set = set()

    def _add_variant(v: Optional[str]) -> None:
        v = (v or "").strip()
        if v and v not in seen_v:
            seen_v.add(v)
            variants.append(v)

    if identity is not None:
        for v in identity.news_variants:
            _add_variant(v)
        _add_variant(identity.name_he)   # ensure Hebrew is included
    else:
        _add_variant(company_name)
        _add_variant(ticker_clean)
        _add_variant(name_he)

    # Primary name for RSS fallback
    primary_en = variants[0] if variants else company_name
    short_name = " ".join(primary_en.split()[:2])
    # Collect Hebrew variant for Hebrew RSS query
    he_variant = (
        (identity.name_he if identity else name_he) or ""
    ).strip()

    seen_urls:         set  = set()
    seen_title_fps:    list = []   # near-duplicate fingerprints for title-level dedup
    articles:          List[ArticleContent] = []

    def _accept_article(url: str, title: str) -> bool:
        """Return True if the article passes URL- and title-dedup filters."""
        if not url or not title or url in seen_urls or not _is_news_url(url):
            return False
        if _is_near_duplicate(title, seen_title_fps):
            return False
        return True

    def _register_article(url: str, title: str) -> None:
        """Mark url+title as seen so future duplicates are rejected."""
        seen_urls.add(url)
        seen_title_fps.append(_title_words(title))

    # ── Part 1: DuckDuckGo news (English variants, real-time snippets) ────
    try:
        from ddgs import DDGS
        ddgs = DDGS()
        ddg_news_queries: List[str] = []
        for v in variants:
            if v == he_variant:
                # Hebrew news queries — DDG news does support Hebrew search
                ddg_news_queries += [
                    f'"{he_variant}" מניה בורסה',           # "stock exchange"
                    f'"{he_variant}" תוצאות OR דיווח',      # "results OR filing"
                ]
                continue
            ddg_news_queries += [
                f'"{v}" stock news',
                f'"{v}" earnings OR results OR dividend',
                f'"{v}" analyst OR upgrade OR downgrade OR target',
            ]
        # Ticker-specific queries (run once, not per-variant)
        ddg_news_queries.append(f'"{ticker_clean}" TASE news')
        ddg_news_queries.append(f'"{ticker_clean}" Israel stock')
        ddg_news_queries.append(f'"{ticker_clean}" TASE Israel')

        for query in ddg_news_queries:
            if len(articles) >= max_articles:
                break
            try:
                raw = list(ddgs.news(query, max_results=6))
            except Exception:
                continue
            for r in raw:
                url   = r.get("url", "")
                title = r.get("title", "")
                if not _accept_article(url, title):
                    continue
                _register_article(url, title)
                pub = _parse_pub_date(r.get("date") or r.get("published") or "")
                articles.append(ArticleContent(
                    title=title, url=url, publisher=r.get("source", ""),
                    text=(r.get("body") or "")[:_MAX_ARTICLE_CHARS],
                    fetch_success=True,
                    published=pub,
                ))
                if len(articles) >= max_articles:
                    break
    except ImportError:
        pass

    # ── Part 2: DDG text search (catches Israeli news sites) ──────────────
    if len(articles) < max_articles:
        try:
            from ddgs import DDGS as _DDGS
            ddgs2 = _DDGS()
            text_queries: List[str] = []
            for v in variants:
                if v == he_variant:
                    # Hebrew text search — Israeli news sites are indexed in Hebrew
                    text_queries.append(f'"{he_variant}" site:globes.co.il OR site:calcalist.co.il OR site:themarker.com')
                    text_queries.append(f'"{he_variant}" מניה OR בורסה OR רבעוני')
                else:
                    text_queries.append(f'"{v}" TASE news')
                    text_queries.append(f'"{v}" Israel financial news')
            # Ticker-specific text queries
            text_queries.append(f'site:globes.co.il OR site:calcalist.co.il "{ticker_clean}"')
            text_queries.append(f'"{ticker_clean}" TASE regulatory OR filing')
            for query in text_queries:
                if len(articles) >= max_articles:
                    break
                try:
                    raw = list(ddgs2.text(query, max_results=8))
                except Exception:
                    continue
                for r in raw:
                    url   = r.get("href", "")
                    title = r.get("title", "")
                    if not _accept_article(url, title):
                        continue
                    _register_article(url, title)
                    articles.append(ArticleContent(
                        title=title, url=url, publisher="",
                        text=(r.get("body") or "")[:_MAX_ARTICLE_CHARS],
                        fetch_success=True,
                    ))
                    if len(articles) >= max_articles:
                        break
        except ImportError:
            pass

    # ── Part 3a: Hebrew Google News RSS (always runs — high yield for Israeli stocks) ──
    # Hebrew RSS always executes regardless of DDG quota because DDG has poor
    # Hebrew support and misses many Israeli news sources (Globes, Calcalist,
    # TheMarker). Deduplication prevents any true duplicates from being added.
    # We cap Hebrew RSS at HE_RSS_SLOTS to leave headroom for English results.
    _HE_RSS_SLOTS = 12
    if he_variant:
        try:
            import feedparser as _fp_he
            base_he = "https://news.google.com/rss/search?q={q}&hl=iw&gl=IL&ceid=IL:iw"
            he_rss_queries = [
                f'"{he_variant}" בורסה',        # "stock exchange"
                f'"{he_variant}"',               # plain name
                f'"{he_variant}" מניה',          # "stock"
                f'"{he_variant}" תוצאות',        # "results"
                f'"{he_variant}" דיווח',         # "report/disclosure"
                f'"{he_variant}" רבעוני',        # "quarterly"
            ]
            he_rss_count = 0
            for query in he_rss_queries:
                if he_rss_count >= _HE_RSS_SLOTS:
                    break
                try:
                    encoded = query.replace(" ", "+")
                    feed    = _fp_he.parse(base_he.format(q=encoded))
                    for entry in feed.entries[:6]:
                        if he_rss_count >= _HE_RSS_SLOTS:
                            break
                        url    = entry.get("link", "")
                        title  = entry.get("title", "")
                        source = entry.get("source", {}).get("title", "")
                        if not _accept_article(url, title):
                            continue
                        _register_article(url, title)
                        pub = _parse_pub_date(
                            entry.get("published_parsed")
                            or entry.get("published", "")
                            or entry.get("updated_parsed")
                            or entry.get("updated", "")
                        )
                        articles.append(ArticleContent(
                            title=title, url=url, publisher=source,
                            text="", fetch_success=True,
                            published=pub,
                        ))
                        he_rss_count += 1
                except Exception:
                    continue
        except ImportError:
            pass

    # ── Part 3b: English Google News RSS (fallback when quota not yet met) ────
    if len(articles) < max_articles:
        try:
            import feedparser
            base_he = "https://news.google.com/rss/search?q={q}&hl=iw&gl=IL&ceid=IL:iw"
            base_en = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=IL&ceid=IL:en"
            en_rss_searches: List[tuple] = []

            # Short Hebrew name fallback (English context RSS)
            en_rss_searches.append((base_he, f'"{short_name}" בורסה'))

            # English RSS queries
            for v in variants:
                if v != he_variant:
                    en_rss_searches.append((base_en, f'"{v}" TASE'))
                    en_rss_searches.append((base_en, f'"{v}" Israel stock'))
            en_rss_searches.append((base_en, f'"{ticker_clean}" Tel Aviv Stock Exchange'))

            for base, query in en_rss_searches:
                if len(articles) >= max_articles:
                    break
                try:
                    encoded = query.replace(" ", "+")
                    feed    = feedparser.parse(base.format(q=encoded))
                    for entry in feed.entries[:6]:
                        url    = entry.get("link", "")
                        title  = entry.get("title", "")
                        source = entry.get("source", {}).get("title", "")
                        if not _accept_article(url, title):
                            continue
                        _register_article(url, title)
                        pub = _parse_pub_date(
                            entry.get("published_parsed")
                            or entry.get("published", "")
                            or entry.get("updated_parsed")
                            or entry.get("updated", "")
                        )
                        articles.append(ArticleContent(
                            title=title, url=url, publisher=source,
                            text="", fetch_success=True,
                            published=pub,
                        ))
                        if len(articles) >= max_articles:
                            break
                except Exception:
                    continue
        except ImportError:
            pass

    # Sort newest-first: articles with a known date come first, then undated.
    # DDG news() dates are most reliable; RSS dates are also good.
    # DDG text() results often have no date and fall to the bottom naturally.
    articles.sort(
        key=lambda a: _parse_pub_date(a.published) or "0000",
        reverse=True,
    )

    # Debug: print the date range we collected
    dated = [a for a in articles if a.published]
    if dated:
        print(f"  [News] {len(articles)} articles collected | "
              f"newest: {dated[0].published[:10] if dated else '?'} | "
              f"oldest: {dated[-1].published[:10] if dated else '?'} | "
              f"{len(dated)} dated, {len(articles)-len(dated)} undated")
    else:
        print(f"  [News] {len(articles)} articles collected (no dates captured)")

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
