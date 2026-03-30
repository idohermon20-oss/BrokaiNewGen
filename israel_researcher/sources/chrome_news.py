"""
ChromeNewsSearcher — fetches Israeli financial news using headless Chrome (Playwright).

Targets Globes, Calcalist, and TheMarker — the three main Israeli financial
publications.  Reuses an existing Playwright browser context (from MayaMonitor)
to avoid launching a second Chromium instance.

Usage (in manager.py):
    chrome = ChromeNewsSearcher(browser_context=maya._context)
    items  = chrome.fetch_all()          # list of news dicts
    chrome.close()                       # no-op if context is external
"""

from __future__ import annotations

import time
from datetime import datetime


class ChromeNewsSearcher:
    """
    Fetches headline articles from Israeli financial news sites via headless Chrome.

    Pass browser_context (from MayaMonitor._context) to reuse the already-open
    Chromium session.  If omitted, a new browser is launched and closed by close().
    """

    SITES = [
        {"url": "https://www.globes.co.il/news/home.aspx",  "label": "Globes"},
        {"url": "https://www.calcalist.co.il/",              "label": "Calcalist"},
        {"url": "https://www.themarker.com/",                "label": "TheMarker"},
    ]

    # JS run inside the page to extract headline links
    _EXTRACT_JS = """() => {
        const results = [];
        const seen    = new Set();
        const selectors = [
            'h1 a', 'h2 a', 'h3 a', 'h4 a',
            'article a', '.article-title a',
            '[class*="title"] a', '[class*="headline"] a',
        ];
        for (const sel of selectors) {
            document.querySelectorAll(sel).forEach(el => {
                const title = (el.innerText || el.textContent || '').trim();
                const href  = el.href || '';
                if (title.length > 20 && href && !seen.has(title)) {
                    seen.add(title);
                    results.push({title: title, url: href});
                }
            });
        }
        return results;
    }"""

    def __init__(self, browser_context=None):
        self._external_context = browser_context is not None
        if browser_context:
            self._context = browser_context
            self._pw      = None
            self._browser = None
        else:
            from playwright.sync_api import sync_playwright
            self._pw      = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            self._context = self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )

    def close(self) -> None:
        """Close browser — no-op if we reused an external context."""
        if not self._external_context:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()

    # ── Public API ──────────────────────────────────────────────────────────────

    def fetch_all(self, max_per_site: int = 15) -> list[dict]:
        """
        Fetch headlines from all SITES.
        Returns list of dicts compatible with IsraeliNewsMonitor.items_to_signals():
          {title, text, url, source_label, seen_at}
        """
        articles: list[dict] = []
        for site in self.SITES:
            try:
                items = self._fetch_site(site["url"], site["label"], max_per_site)
                print(f"[Chrome] {site['label']}: {len(items)} headlines")
                articles.extend(items)
                time.sleep(0.5)   # polite delay between sites
            except Exception as e:
                print(f"[Chrome] {site['label']} error: {e}")
        return articles

    # ── Internals ───────────────────────────────────────────────────────────────

    def _fetch_site(self, url: str, label: str, max_results: int) -> list[dict]:
        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            raw: list[dict] = page.evaluate(self._EXTRACT_JS)
        except Exception:
            return []
        finally:
            page.close()

        now = datetime.utcnow().isoformat()
        results: list[dict] = []
        seen_urls: set[str] = set()

        for item in raw[:max_results]:
            href = item.get("url", "")
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)
            results.append({
                "title":        item["title"],
                "text":         "",          # no body text at this stage
                "url":          href,
                "source_label": label,
                "seen_at":      now,
            })

        return results
