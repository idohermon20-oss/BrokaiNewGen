"""
utils/fetch_investing_stocks.py
================================
Scrapes ALL Israeli stocks from il.investing.com/equities/israel using Playwright,
extracts English + Hebrew names, matches to .TA Yahoo Finance tickers, and saves
an enriched reference to data/tase_stock_names.json.

Run (from project root):
    python utils/fetch_investing_stocks.py
"""

from __future__ import annotations
import json, os, sys, time, re
from pathlib import Path as _Path

# SSL fix
import tempfile, shutil
try:
    import certifi
    _dst = os.path.join(tempfile.gettempdir(), "brokai_cacert.pem")
    if not os.path.exists(_dst):
        shutil.copy2(certifi.where(), _dst)
    os.environ.setdefault("SSL_CERT_FILE", _dst)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", _dst)
    os.environ.setdefault("CURL_CA_BUNDLE", _dst)
except Exception:
    pass

ROOT = _Path(__file__).parent.parent
DATA = ROOT / "data"

INVESTING_URL = "https://il.investing.com/equities/israel"


def load_yf_universe() -> dict[str, str]:
    """Load {ticker: english_name} from our existing YF data."""
    names_path = DATA / "tase_ticker_names.json"
    if names_path.exists():
        return json.loads(names_path.read_text(encoding="utf-8"))
    return {}


def normalize(s: str) -> str:
    """Lowercase, strip punctuation for fuzzy matching."""
    return re.sub(r"[^a-z0-9\u05d0-\u05ea]", "", s.lower())


def scrape_investing_com() -> list[dict]:
    """
    Use Playwright to load the full investing.com equities page,
    click 'Show All' / scroll to load all rows, and extract the table.
    Returns list of {english_name, hebrew_name, investing_ticker, url}.
    """
    from playwright.sync_api import sync_playwright

    stocks = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="he-IL",
        )
        page = ctx.new_page()

        print(f"Loading {INVESTING_URL} ...")
        page.goto(INVESTING_URL, wait_until="networkidle", timeout=60000)
        time.sleep(3)

        # Dismiss cookie/consent popup if present
        for sel in ["#onetrust-accept-btn-handler", "[data-testid='accept-cookies']",
                    ".js-cookie-accept-all", "#cookieBanner .agree"]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(1)
                    break
            except Exception:
                pass

        # Click "Show All" button if it exists to load all rows
        for sel in [
            "a.showMore", ".showMore", "[data-test='show-more']",
            "a:has-text('הצג הכל')", "a:has-text('Show All')",
            "a:has-text('טען עוד')", "a:has-text('Load More')",
        ]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    print(f"  Clicking '{sel}' to expand list...")
                    btn.click()
                    time.sleep(3)
                    break
            except Exception:
                pass

        # Scroll to bottom to trigger lazy loading
        print("  Scrolling to load all rows...")
        prev_height = 0
        for _ in range(30):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)
            height = page.evaluate("document.body.scrollHeight")
            if height == prev_height:
                break
            prev_height = height

        # Extract all rows from the equities table
        rows = page.evaluate("""
        () => {
            const results = [];
            // Try multiple table selectors used by investing.com
            const selectors = [
                'table.genTbl tbody tr',
                '#cross_rate_markets_stocks_1 tbody tr',
                'table tbody tr',
                '[data-test="equity-table"] tbody tr',
            ];

            let rows = [];
            for (const sel of selectors) {
                rows = document.querySelectorAll(sel);
                if (rows.length > 5) break;
            }

            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length < 2) continue;

                // English name — look for the main link
                let englishName = '';
                let hebrewName = '';
                let url = '';
                let ticker = '';

                const link = row.querySelector('a.bold');
                if (link) {
                    englishName = link.textContent.trim();
                    url = link.href || '';
                }

                // Hebrew name — often in a span or second line
                const hebrewSpan = row.querySelector('span.elp, .second-line, span[dir="rtl"]');
                if (hebrewSpan) {
                    hebrewName = hebrewSpan.textContent.trim();
                }

                // Ticker symbol if shown
                const tickerEl = row.querySelector('.symbol, [data-column-name="symbol"]');
                if (tickerEl) ticker = tickerEl.textContent.trim();

                if (englishName) {
                    results.push({ englishName, hebrewName, ticker, url });
                }
            }
            return results;
        }
        """)

        print(f"  Found {len(rows)} stocks from table extraction.")

        # If table extraction got too few, try a broader approach
        if len(rows) < 50:
            print("  Trying broader extraction...")
            rows = page.evaluate("""
            () => {
                const results = new Map();
                // Get all links that look like stock pages
                document.querySelectorAll('a[href*="/equities/"]').forEach(link => {
                    const href = link.href;
                    if (!href.includes('/equities/israel') && href.includes('/equities/')) {
                        const name = link.textContent.trim();
                        if (name.length > 1 && name.length < 80) {
                            if (!results.has(href)) {
                                results.set(href, { englishName: name, hebrewName: '', ticker: '', url: href });
                            }
                        }
                    }
                });
                return Array.from(results.values());
            }
            """)
            print(f"  Broader extraction: {len(rows)} items")

        browser.close()

    return rows


def match_to_yf(
    investing_stocks: list[dict],
    yf_names: dict[str, str],
) -> list[dict]:
    """
    Try to match each investing.com stock to a Yahoo Finance .TA ticker
    using normalized English name matching.
    Returns enriched list with 'ticker_yf' field.
    """
    # Build reverse lookup: normalized_name -> ticker
    name_to_ticker: dict[str, str] = {}
    for ticker, eng_name in yf_names.items():
        key = normalize(eng_name)
        if key:
            name_to_ticker[key] = ticker

    matched = 0
    for stock in investing_stocks:
        eng = normalize(stock.get("englishName", ""))
        stock["ticker_yf"] = ""

        # Exact match
        if eng in name_to_ticker:
            stock["ticker_yf"] = name_to_ticker[eng]
            matched += 1
            continue

        # Prefix match (first 6+ chars)
        if len(eng) >= 6:
            for key, ticker in name_to_ticker.items():
                if key.startswith(eng[:6]) or eng.startswith(key[:6]):
                    stock["ticker_yf"] = ticker
                    matched += 1
                    break

    print(f"Matched {matched}/{len(investing_stocks)} to YF tickers")
    return investing_stocks


def main():
    yf_names = load_yf_universe()
    print(f"Loaded {len(yf_names)} YF ticker names")

    stocks = scrape_investing_com()
    if not stocks:
        print("ERROR: No stocks scraped. Check Playwright / site structure.")
        sys.exit(1)

    stocks = match_to_yf(stocks, yf_names)

    # Save
    out = DATA / "tase_stock_names.json"
    out.write_text(json.dumps({
        "source": "il.investing.com/equities/israel",
        "total": len(stocks),
        "stocks": stocks,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nSaved {len(stocks)} stocks to {out}")
    matched_count = sum(1 for s in stocks if s.get("ticker_yf"))
    print(f"With YF ticker: {matched_count}")
    print(f"Without YF ticker (Hebrew-only or unmatched): {len(stocks) - matched_count}")

    # Print sample
    print("\nSample (first 20):")
    for s in stocks[:20]:
        print(f"  {s.get('ticker_yf','???'):12} | {s['englishName'][:30]:30} | {s['hebrewName']}")


if __name__ == "__main__":
    main()
