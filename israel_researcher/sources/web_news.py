"""
WebNewsSearcher — targeted news search per ticker via Google News RSS.

No API key required.  Uses feedparser (already a project dependency).
Google News RSS supports free-text queries and returns results from
Reuters, Bloomberg, Globes, Calcalist, TheMarker, and other sources
indexed by Google — far broader coverage than the fixed RSS feeds.

Usage:
    searcher = WebNewsSearcher()
    articles = searcher.search_ticker("ESLT", "Elbit Systems", max_results=5)
    # → [{"title": "...", "snippet": "...", "url": "...", "published": "..."}, ...]
"""

from __future__ import annotations

import time
import urllib.parse

import feedparser

from ..config import WEB_NEWS_SEARCH_NAMES


class WebNewsSearcher:
    """
    Searches Google News RSS for company/ticker-specific news.
    Designed to be called for a small set of high-signal tickers per cycle
    (not for every ticker — throttle at the call site).
    """

    _BASE    = "https://news.google.com/rss/search"
    _TIMEOUT = 10   # seconds per request (feedparser uses socket timeout)
    _RETRIES = 2    # retry once on empty result (possible 429 rate-limit)
    _BACKOFF = 3.0  # seconds to wait before retry

    def search(
        self,
        query:       str,
        max_results: int  = 6,
        lang:        str  = "en",
        country:     str  = "IL",
    ) -> list[dict]:
        """
        Query Google News RSS.  Returns up to max_results articles as dicts:
          {title, snippet, url, published}
        Retries once with backoff if result is empty (possible rate-limit).
        """
        params = urllib.parse.urlencode({
            "q":    query,
            "hl":   lang,
            "gl":   country,
            "ceid": f"{country}:{lang}",
        })
        url = f"{self._BASE}?{params}"

        feed = None
        for attempt in range(self._RETRIES):
            try:
                import socket
                old_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(self._TIMEOUT)
                feed = feedparser.parse(url)
                socket.setdefaulttimeout(old_timeout)
            except Exception:
                return []
            if feed.entries:
                break
            if attempt < self._RETRIES - 1:
                time.sleep(self._BACKOFF)

        if not feed or not feed.entries:
            return []

        results: list[dict] = []
        for entry in (feed.entries or [])[:max_results]:
            title   = entry.get("title", "").strip()
            snippet = entry.get("summary", "").strip()
            # Google News RSS often wraps the real URL in a redirect — use as-is
            link      = entry.get("link", "")
            published = entry.get("published", "")
            if title:
                results.append({
                    "title":     title,
                    "snippet":   snippet[:400],
                    "url":       link,
                    "published": published,
                })
        return results

    def search_ticker(
        self,
        ticker:       str,
        company_name: str,
        max_results:  int = 6,
    ) -> list[dict]:
        """
        Search for news about a specific stock.
        Tries two queries: company name first, then ticker symbol fallback.
        Deduplicates by title.
        """
        results: list[dict] = []
        seen_titles: set[str] = set()

        # Apply search name override if configured (better query for some tickers)
        ticker_ta = ticker if ticker.endswith(".TA") else ticker + ".TA"
        company_name = WEB_NEWS_SEARCH_NAMES.get(ticker_ta, company_name)

        # Query 1 — company name (most useful for Israeli companies)
        if company_name:
            for item in self.search(company_name, max_results=max_results):
                t = item["title"].lower()
                if t not in seen_titles:
                    seen_titles.add(t)
                    results.append(item)
            time.sleep(0.3)

        # Query 2 — ticker symbol (catches English-language financial press)
        remaining = max_results - len(results)
        if remaining > 0 and ticker:
            query2 = f"{ticker} stock" if not ticker.startswith("TASE") else company_name
            for item in self.search(query2, max_results=remaining):
                t = item["title"].lower()
                if t not in seen_titles:
                    seen_titles.add(t)
                    results.append(item)

        return results[:max_results]
