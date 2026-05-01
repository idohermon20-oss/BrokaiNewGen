"""
Sector news fetcher.

Fetches recent news headlines for a stock's sector using Google News RSS.
No API key required. Fails gracefully — never raises, always returns a list.
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import List

try:
    import feedparser
    _FEEDPARSER_AVAILABLE = True
except ImportError:
    _FEEDPARSER_AVAILABLE = False


@dataclass
class SectorNewsItem:
    title: str
    source: str
    published: str
    summary: str
    url: str


def fetch_sector_news(
    company_name: str,
    sector: str,
    industry: str = "",
    max_items: int = 12,
    timeout: int = 10,
) -> List[SectorNewsItem]:
    """
    Fetch recent sector-level news from Google News RSS.

    Queries are deliberately sector/market focused — NOT company specific —
    so analysts receive true backdrop context rather than company repetition.

    Returns up to max_items de-duplicated items. Returns [] on any failure.
    """
    if not _FEEDPARSER_AVAILABLE:
        return []

    # Use industry if it's more specific than sector (and different)
    sub_sector = (industry or "").strip()
    if sub_sector and sub_sector.lower() == sector.lower():
        sub_sector = ""

    queries: List[str] = []
    # Sector-level queries — true backdrop, not company-specific
    queries.append(f"{sector} sector Israel news")
    queries.append(f"Israel {sector} market")
    queries.append(f"TASE {sector} stocks")
    if sub_sector:
        queries.append(f"{sub_sector} industry Israel")
        queries.append(f"{sub_sector} stocks outlook")
    queries.append(f"{sector} ETF performance")
    queries.append(f"Tel Aviv {sector} sector")

    seen: set = set()
    results: List[SectorNewsItem] = []

    for query in queries:
        if len(results) >= max_items:
            break
        items = _fetch_rss(query, max_items=6)
        for item in items:
            key = item.title.strip().lower()[:80]
            if key not in seen:
                seen.add(key)
                results.append(item)
            if len(results) >= max_items:
                break

    return results


def _fetch_rss(query: str, max_items: int = 6) -> List[SectorNewsItem]:
    """Fetch a single Google News RSS query. Returns [] on any error."""
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en&gl=IL&ceid=IL:en"
        feed = feedparser.parse(url)
        items = []
        for entry in (feed.entries or [])[:max_items]:
            source = ""
            try:
                source = entry.source.title
            except AttributeError:
                source = entry.get("publisher", "")
            summary = entry.get("summary", "")
            # feedparser sometimes returns HTML in summary — strip basic tags
            summary = summary.replace("<b>", "").replace("</b>", "").replace("&nbsp;", " ")
            items.append(SectorNewsItem(
                title=entry.get("title", ""),
                source=source,
                published=entry.get("published", ""),
                summary=summary[:400],
                url=entry.get("link", ""),
            ))
        return items
    except Exception:
        return []


def format_sector_news_for_llm(items: List[SectorNewsItem]) -> str:
    """Render news items as a structured block for LLM prompt injection."""
    if not items:
        return ""
    lines = [f"SECTOR NEWS ({len(items)} items):"]
    for i, item in enumerate(items, 1):
        lines.append(f"  {i}. [{item.source}] {item.title}")
        if item.summary:
            lines.append(f"     {item.summary[:200]}")
    return "\n".join(lines)
