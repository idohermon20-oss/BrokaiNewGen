"""
IsraeliNewsMonitor — fetches Israeli and global RSS feeds for TASE research.
"""

from __future__ import annotations

import datetime as _dt
import re

import feedparser

from ..config import ISRAELI_NEWS_SOURCES, GLOBAL_NEWS_SOURCES
from ..models import Signal, now_iso
from ..analysis.enricher import SignalEnricher


def _check_updates(sources: list[dict]) -> list[dict]:
    """Fetch RSS feeds from a list of source configs and return news items.

    Each source: {"type": "rss", "url": "...", "label": "..."}
    Each returned item: {url, title, text, seen_at, source_label}
    """
    items = []
    for src in sources:
        url   = src.get("url", "")
        label = src.get("label", "")
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                items.append({
                    "url":          entry.get("link", ""),
                    "title":        entry.get("title", ""),
                    "text":         entry.get("summary", ""),
                    "seen_at":      _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "source_label": label,
                })
        except Exception as exc:
            items.append({"url": None, "error": str(exc), "source_label": label})
    return items


class IsraeliNewsMonitor:
    @staticmethod
    def _valid_items(items: list[dict]) -> list[dict]:
        """Drop error entries returned by check_updates (url=None or has 'error' key)."""
        return [it for it in items if it.get("url") and not it.get("error")]

    def fetch_israeli_news(self) -> list[dict]:
        try:
            return self._valid_items(_check_updates(ISRAELI_NEWS_SOURCES))
        except Exception as e:
            print(f"[News] Israeli error: {e}")
            return []

    def fetch_global_news(self, sources: list[dict]) -> list[dict]:
        """Fetch global headlines as macro context (no company-name filter)."""
        try:
            return self._valid_items(_check_updates(sources))
        except Exception as e:
            print(f"[News] Global error: {e}")
            return []

    def fetch_global_news_for_tase(self, company_names: list[str]) -> list[dict]:
        try:
            items = self._valid_items(_check_updates(GLOBAL_NEWS_SOURCES))
            result = []
            for item in items:
                combined = ((item.get("title") or "") + (item.get("text") or "")).lower()
                for name in company_names:
                    n = name.lower()
                    if len(n) < 5:
                        continue
                    if re.search(r'\b' + re.escape(n) + r'\b', combined):
                        result.append(item)
                        break
            return result
        except Exception as e:
            print(f"[News] Global error: {e}")
            return []

    def items_to_signals(
        self,
        items: list[dict],
        signal_type: str,
        company_map: dict[str, str],
    ) -> list[Signal]:
        enricher = SignalEnricher()
        signals  = []
        for item in items:
            combined     = ((item.get("title") or "") + " " + (item.get("text") or "")).lower()
            ticker       = "GENERAL"
            company_name = ""
            for name_lower, tkr in company_map.items():
                if len(name_lower) < 5:
                    continue
                if re.search(r'\b' + re.escape(name_lower) + r'\b', combined):
                    ticker       = tkr
                    company_name = name_lower.title()
                    break

            sig = Signal(
                ticker       = ticker,
                ticker_yf    = f"{ticker}.TA" if ticker != "GENERAL" else "",
                company_name = company_name or item.get("source_label", ""),
                signal_type  = signal_type,
                headline     = item.get("title") or "No title",
                detail       = (item.get("text") or "")[:300],
                url          = item.get("url") or "",
                timestamp    = item.get("seen_at") or now_iso(),
            )
            enricher.enrich(sig, (item.get("title") or "") + " " + (item.get("text") or ""))
            signals.append(sig)
        return signals
