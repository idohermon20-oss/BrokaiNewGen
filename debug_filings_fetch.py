"""
Standalone filings debug script.
Usage:  python debug_filings_fetch.py PTNR
        python debug_filings_fetch.py ESLT
"""
import json
import os
import sys
import tempfile
import time

# ── Ticker → Hebrew name ──────────────────────────────────────────────────────
_DIR    = os.path.dirname(__file__)
_CSV    = os.path.join(_DIR, "borkai", "data", "tase_stocks.csv")
_OUTDIR = tempfile.gettempdir()

def _he_name(ticker: str) -> str | None:
    import csv
    clean = ticker.replace(".TA", "").strip().upper()
    try:
        with open(_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("ticker", "").strip().upper() == clean:
                    return (row.get("name_he") or "").strip() or None
    except Exception as exc:
        print(f"[ERROR] CSV read failed: {exc}")
    return None

def _screenshot(page, stage: str) -> None:
    path = os.path.join(_OUTDIR, f"dbg_{stage}.png")
    try:
        page.screenshot(path=path, full_page=False)
        print(f"  [screenshot] {path}")
    except Exception as exc:
        print(f"  [screenshot-fail] {stage}: {exc}")

def _save_html(page, stage: str) -> None:
    path = os.path.join(_OUTDIR, f"dbg_{stage}.html")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(page.content())
        print(f"  [html] {path}")
    except Exception as exc:
        print(f"  [html-fail] {stage}: {exc}")


# ── Main debug fetch ──────────────────────────────────────────────────────────

MAYA_URL = (
    "https://maya.tase.co.il/he/reports/companies"
    "?fromDate=2025-05-01&toDate=2026-05-01"
    "&isPriority=false&isTradeHalt=false&by=company&freeText="
)
MAGNA_URL = "https://www.magna.isa.gov.il/?q="


def debug_maya(ticker: str, name_he: str) -> list:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    print(f"\n{'='*60}")
    print(f"  MAYA fetch: {ticker} / {name_he}")
    print(f"  URL: {MAYA_URL}")
    print(f"{'='*60}")

    all_requests:  list[str] = []
    all_responses: list[dict] = []

    def on_request(req):
        if req.resource_type in ("xhr", "fetch"):
            all_requests.append(req.url)

    def on_response(resp):
        if resp.request.resource_type in ("xhr", "fetch"):
            entry = {"url": resp.url, "status": resp.status, "body": ""}
            try:
                if resp.status == 200:
                    entry["body"] = resp.text()[:300]
            except Exception:
                pass
            all_responses.append(entry)
            print(f"  [net] {resp.status} {resp.url[:100]}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="he-IL",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        page.on("request",  on_request)
        page.on("response", on_response)

        # ── 1. Navigate ───────────────────────────────────────────────────────
        print("\n[step 1] Navigating to MAYA…")
        try:
            page.goto(MAYA_URL, wait_until="load", timeout=30_000)
            page.wait_for_timeout(2000)
        except Exception as exc:
            print(f"  [nav-fail] {exc}")
        _screenshot(page, "01_loaded")
        print(f"  [page title] {page.title()}")

        # ── 2. Find search input ──────────────────────────────────────────────
        print(f"\n[step 2] Looking for search input (waiting for Angular to bootstrap)…")
        from playwright.sync_api import TimeoutError as PWTimeout
        # Must use wait_for_selector — el.count() returns 0 immediately before Angular
        # renders formcontrolname attributes. wait_for_selector polls until it appears.
        primary   = "input[formcontrolname='freeText']"
        fallbacks = [
            "input[formcontrolname='companyName']",
            "mat-form-field input[type='text']",
            "input.mat-input-element",
            "input[placeholder*='חיפוש']",
        ]
        found_sel = None
        try:
            page.wait_for_selector(primary, timeout=15_000)
            found_sel = primary
            print(f"  [input] Angular form ready: {primary!r}")
        except PWTimeout:
            print(f"  [input] Angular primary timed out — trying fallbacks")
            for sel in fallbacks:
                try:
                    page.wait_for_selector(sel, timeout=5_000)
                    found_sel = sel
                    print(f"  [input] fallback found: {sel!r}")
                    break
                except PWTimeout:
                    continue

        if not found_sel:
            print("  [ERROR] no search input found — Angular may not have loaded")
            _screenshot(page, "02_no_input")
            _save_html(page, "02_no_input")
            browser.close()
            return []

        el = page.locator(found_sel).first
        el.click()
        page.wait_for_timeout(200)
        page.keyboard.press("Control+a")
        page.keyboard.press("Delete")
        page.keyboard.type(name_he)
        print(f"  [typed] {name_he!r} into {found_sel!r}")

        _screenshot(page, "02_after_typing")

        # ── 3. Autocomplete ───────────────────────────────────────────────────
        print(f"\n[step 3] Waiting for autocomplete…")
        page.wait_for_timeout(2000)

        ac_selectors = [
            ".cdk-overlay-container mat-option",
            ".mat-autocomplete-panel mat-option",
            "mat-option",
            "[role='listbox'] [role='option']",
        ]
        options_found: list[str] = []
        for sel in ac_selectors:
            try:
                els = page.locator(sel).all()
                if els:
                    options_found = [e.inner_text() for e in els[:10]]
                    break
            except Exception:
                continue

        print(f"  [autocomplete] {len(options_found)} options: {options_found[:5]}")
        _screenshot(page, "03_suggestions")

        # ── 4. Click first autocomplete option, capture API response ─────────
        print(f"\n[step 4] Clicking first autocomplete option…")
        reports_raw: list = []

        try:
            with page.expect_response(
                lambda r: "/api/v1/reports/companies" in r.url and r.status == 200,
                timeout=12_000,
            ) as response_info:
                clicked = False
                for sel in ac_selectors:
                    try:
                        el = page.locator(sel).first
                        if el.count() > 0 and el.is_visible(timeout=2000):
                            txt = el.inner_text()
                            el.click()
                            print(f"  [clicked] {txt!r}")
                            clicked = True
                            break
                    except Exception:
                        continue
                if not clicked:
                    print("  [no autocomplete] pressing Enter")
                    page.keyboard.press("Enter")

            resp = response_info.value
            print(f"  [api-response] status={resp.status} url={resp.url[:100]}")
            data = resp.json()
            print(f"  [api-response] keys={list(data.keys()) if isinstance(data, dict) else type(data)}")
            items = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(items, list):
                reports_raw = items
                print(f"  [api-response] {len(reports_raw)} items")

        except PWTimeout:
            print("  [expect_response TIMEOUT] — no /api/v1/reports/companies seen")
            print(f"  [all XHR/fetch URLs seen]:")
            for url in all_requests[-20:]:
                print(f"    {url}")

        _screenshot(page, "04_after_click")
        page.wait_for_timeout(2000)
        _screenshot(page, "05_results")
        _save_html(page, "05_results")

        # ── 5. Print extracted filings ────────────────────────────────────────
        print(f"\n[step 5] Extracted {len(reports_raw)} raw items")
        filings = []
        for item in reports_raw[:20]:
            fid   = item.get("id", "")
            title = (item.get("header") or item.get("title") or "").strip()
            date  = item.get("publishDate", "")
            if date and "T" in str(date):
                from datetime import datetime
                try:
                    date = datetime.fromisoformat(str(date).split(".")[0]).strftime("%Y-%m-%d")
                except Exception:
                    pass
            link = f"https://maya.tase.co.il/reports/details/{fid}" if fid else ""
            filings.append({"date": date, "title": title, "link": link})

        for i, f in enumerate(filings[:5]):
            print(f"  [{i+1}] {f['date']} | {f['title'][:70]}")
            print(f"       {f['link']}")

        browser.close()
        return filings


def debug_magna(ticker: str, name_he: str) -> list:
    from playwright.sync_api import sync_playwright

    print(f"\n{'='*60}")
    print(f"  MAGNA fallback: {ticker} / {name_he}")
    print(f"  URL: {MAGNA_URL}")
    print(f"{'='*60}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="he-IL",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()

        def on_response(resp):
            if resp.request.resource_type in ("xhr", "fetch"):
                print(f"  [net] {resp.status} {resp.url[:100]}")

        page.on("response", on_response)

        print("\n[step 1] Navigating to MAGNA…")
        try:
            page.goto(MAGNA_URL, wait_until="load", timeout=30_000)
            page.wait_for_timeout(2000)
        except Exception as exc:
            print(f"  [nav-fail] {exc}")
        _screenshot(page, "magna_01_loaded")

        print(f"\n[step 2] Looking for MAGNA search input…")
        from playwright.sync_api import TimeoutError as PWTimeout
        magna_selectors = [
            "input[name='q']", "input#q", "input#search",
            "input[type='search']", "input[placeholder*='חיפוש']",
            "input[type='text']",
        ]
        found_sel = None
        for sel in magna_selectors:
            try:
                page.wait_for_selector(sel, timeout=6_000)
                found_sel = sel
                print(f"  [input] {sel!r}")
                break
            except PWTimeout:
                continue

        if not found_sel:
            print("  [ERROR] no search input found on MAGNA")
            _screenshot(page, "magna_02_no_input")
            browser.close()
            return []

        _screenshot(page, "magna_02_after_typing")
        page.wait_for_timeout(1500)

        print("\n[step 3] Checking autocomplete / submitting…")
        ac_selectors = [
            ".autocomplete-results li", ".suggestions li",
            ".dropdown-menu li", "[role='option']",
        ]
        clicked = False
        for sel in ac_selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible(timeout=3000):
                    txt = el.inner_text()
                    el.click()
                    print(f"  [clicked] {txt!r}")
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            print("  [no autocomplete] pressing Enter")
            page.keyboard.press("Enter")

        page.wait_for_timeout(3000)
        _screenshot(page, "magna_03_results")
        _save_html(page, "magna_03_results")

        print("\n[step 4] Scraping result links…")
        try:
            items = page.evaluate("""
                () => {
                    const out = [];
                    for (const a of document.querySelectorAll('a[href]')) {
                        const href = a.href || '';
                        const text = (a.innerText || a.textContent || '').trim();
                        if (!href || href.includes('javascript') || text.length < 5) continue;
                        if (href.includes('magna.isa') || href.includes('isa.gov.il')) {
                            out.push({ href, text });
                        }
                    }
                    return out.slice(0, 30);
                }
            """)
            print(f"  [links found] {len(items)}")
            for i, it in enumerate(items[:5]):
                print(f"  [{i+1}] {it.get('text','')[:70]}")
                print(f"       {it.get('href','')[:100]}")
        except Exception as exc:
            print(f"  [scrape-fail] {exc}")
            items = []

        browser.close()
        return items


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ticker = sys.argv[1].strip().upper().replace(".TA", "") if len(sys.argv) > 1 else "PTNR"

    name_he = _he_name(ticker)
    print(f"\nTicker:      {ticker}")
    print(f"Hebrew name: {name_he!r}")

    if not name_he:
        print(f"[ERROR] ticker '{ticker}' not found in {_CSV}")
        sys.exit(1)

    # ── Try MAYA first ────────────────────────────────────────────────────────
    maya_results = debug_maya(ticker, name_he)

    print(f"\n{'='*60}")
    print(f"  MAYA result: {len(maya_results)} filings")
    print(f"{'='*60}")

    if maya_results:
        print("\n✓ MAYA succeeded. No MAGNA needed.")
        sys.exit(0)

    # ── MAGNA fallback ────────────────────────────────────────────────────────
    print("\n→ MAYA returned 0 — trying MAGNA fallback…")
    magna_results = debug_magna(ticker, name_he)

    print(f"\n{'='*60}")
    print(f"  MAGNA result: {len(magna_results)} items")
    print(f"{'='*60}")

    if not magna_results:
        print(f"\n✗ FILINGS_FETCH_FAILED")
        print(f"  ticker:       {ticker}")
        print(f"  hebrew_name:  {name_he}")
        print(f"  maya_result:  0")
        print(f"  magna_result: 0")
        print(f"  screenshots:  {_OUTDIR}/dbg_*.png")
        sys.exit(1)

    print("\n✓ MAGNA fallback succeeded.")
