"""
Maya TASE Report Fetcher
========================
Two-source UI search — MAYA first, MAGNA fallback:

  PRIMARY (MAYA)
    ticker → tase_stocks.csv → Hebrew company name
           → open maya.tase.co.il/he/reports/companies (with date filter)
           → type Hebrew name into search field
           → wait for autocomplete, click first suggestion
           → extract latest filings from results table
    SUCCESS (≥ 1 filing) → return MAYA results, STOP

  FALLBACK (MAGNA) — only when MAYA returns 0 results
    → open magna.isa.gov.il
    → type same Hebrew name into search field
    → wait for autocomplete, click first suggestion
    → extract filings from results page
    source = "MAGNA" for all fallback results

  NEVER mix sources.

Error / no results → NO_COMPANY_FILINGS_FOUND with full debug info.

Debug output per request:
  ticker / Hebrew name / MAYA URL / search text / autocomplete clicked /
  MAYA count / MAGNA used / MAGNA count / final source

Public API:
  fetch_company_reports(company_name, ticker, ...)  → List[MayaReport]
  assess_company_report_impacts(reports, ...)        → List[MayaReport]
  get_maya_reports(client, config, known_stocks)     → List[MayaReport]
  fetch_raw_reports()                                → List[MayaReport]
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import feedparser
import openai

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

_DIR             = os.path.dirname(__file__)
_TASE_CSV        = os.path.join(_DIR, "tase_stocks.csv")
_MAYA_REPORT_URL = "https://maya.tase.co.il/reports/details/{}"

_MAYA_SEARCH_URL = (
    "https://maya.tase.co.il/he/reports/companies"
    "?fromDate=2025-05-01&toDate=2026-05-01"
    "&isPriority=false&isTradeHalt=false&by=company&freeText="
)
_MAGNA_SEARCH_URL = "https://www.magna.isa.gov.il/?q="


# ── Hebrew name lookup ────────────────────────────────────────────────────────

_HE_NAME_CACHE: Optional[Dict[str, str]] = None


def _load_he_names() -> Dict[str, str]:
    """Load ticker → Hebrew name mapping from tase_stocks.csv (cached)."""
    global _HE_NAME_CACHE
    if _HE_NAME_CACHE is not None:
        return _HE_NAME_CACHE
    mapping: Dict[str, str] = {}
    try:
        with open(_TASE_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                he = (row.get("name_he") or "").strip()
                if he:
                    mapping[row["ticker"].strip().upper()] = he
    except Exception:
        pass
    _HE_NAME_CACHE = mapping
    return mapping


def get_hebrew_name(ticker: str) -> Optional[str]:
    """Return the Hebrew company name for a TASE ticker, or None if unknown."""
    clean = ticker.replace(".TA", "").strip().upper()
    return _load_he_names().get(clean)


# ── Safe print ────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        safe = msg.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8", errors="replace"
        )
        print(safe)


# ── Report type detection ─────────────────────────────────────────────────────

REPORT_TYPE_KEYWORDS: Dict[str, list] = {
    "earnings":       ["רבעוני", "שנתי", "earnings", "revenue", "profit", "רווח", "הכנסות", "תוצאות"],
    "dividend":       ["דיבידנד", "dividend", "חלוקה"],
    "material_event": ["אירוע מהותי", "material", "עסקה", "רכישה", "acquisition", "הסכם"],
    "guidance":       ["תחזית", "guidance", "forecast", "צפי"],
    "regulatory":     ["רגולציה", "regulatory", "אישור", "approval", "FDA", "ISA", "רשות"],
    "appointment":    ["מינוי", "appointment", "CEO", "מנכ", "יו\"ר", "chairman"],
    "bond":           ["אג\"ח", "bond", "אגרות חוב", "הנפקה"],
}


def _detect_report_type(title: str) -> str:
    title_lower = title.lower()
    for rtype, kws in REPORT_TYPE_KEYWORDS.items():
        if any(kw.lower() in title_lower for kw in kws):
            return rtype
    return "other"


# ── MayaReport data class ─────────────────────────────────────────────────────

@dataclass
class MayaReport:
    title:         str
    published:     str
    link:          str
    source:        str
    report_type:   str = "other"
    company_name:  Optional[str] = None
    ticker:        Optional[str] = None
    sector:        Optional[str] = None
    impact:        str = "neutral"
    impact_reason: str = ""
    summary:       str = ""
    fetch_path:    str = ""


# ── URL validation ────────────────────────────────────────────────────────────

_MAYA_REPORT_RE = re.compile(r'maya\.tase\.co\.il.*/reports/(?:details/|companies/)?(\d{6,})')


def _is_maya_report_url(url: str) -> bool:
    return bool(_MAYA_REPORT_RE.search(url))


# ── Playwright browser helpers ────────────────────────────────────────────────

def _launch_browser(pw):
    return pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
            "--disable-gpu",
        ],
    )


def _new_context(browser):
    return browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        locale="he-IL",
        viewport={"width": 1280, "height": 900},
    )


def _pw_navigate(page, url: str, label: str) -> bool:
    """Navigate with fallback wait states. Returns True if any attempt succeeded."""
    try:
        from playwright.sync_api import TimeoutError as PWTimeout
    except ImportError:
        return False
    for wait_state in ("load", "domcontentloaded", "commit"):
        try:
            page.goto(url, wait_until=wait_state, timeout=30_000)
            page.wait_for_timeout(2000)
            _log(f"    [{label}] Navigated ({wait_state}): {url[:80]}")
            return True
        except PWTimeout:
            _log(f"    [{label}] Navigation timeout ({wait_state}), retrying")
        except Exception as exc:
            _log(f"    [{label}] Navigation error ({wait_state}): {exc}")
    return False


def _wait_imperva(page, timeout: int = 10) -> bool:
    """Poll for Imperva session cookies. Returns True when found."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            cookies = page.context.cookies()
            if any(
                c["name"].startswith(("incap_ses", "visid_incap", "nlbi_"))
                for c in cookies
            ):
                _log(f"    [Maya] Imperva cookies ready ({round(time.time()-t0, 1)}s)")
                return True
        except Exception:
            pass
        page.wait_for_timeout(500)
    _log("    [Maya] Imperva cookies not detected — proceeding anyway")
    return False


def _pw_fill(page, selectors: list, text: str, timeout: int = 8000, label: str = "") -> Optional[str]:
    """Try each selector in order; fill the first visible input found. Returns matched selector or None."""
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=timeout)
            if el and el.is_visible():
                el.click()
                page.wait_for_timeout(200)
                el.fill(text)
                _log(f"    [{label}] Filled input ({sel!r}) with {text!r}")
                return sel
        except Exception:
            continue
    return None


def _pw_click_first(page, selectors: list, timeout: int = 5000, label: str = "") -> Optional[str]:
    """Try each selector; click the first visible element. Returns matched selector or None."""
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=timeout)
            if el and el.is_visible():
                el.click()
                _log(f"    [{label}] Clicked ({sel!r})")
                return sel
        except Exception:
            continue
    return None


# ── Screenshot helper ─────────────────────────────────────────────────────────

import tempfile as _tempfile


def _screenshot(page, ticker: str, stage: str) -> None:
    try:
        path = os.path.join(_tempfile.gettempdir(), f"maya_{ticker}_{stage}.png")
        page.screenshot(path=path, full_page=False)
        _log(f"    [Maya] Screenshot → {path}")
    except Exception as exc:
        _log(f"    [Maya] Screenshot failed ({stage}): {exc}")


# ── Raw report builder ────────────────────────────────────────────────────────

def _raw_to_reports(
    raw_items: list,
    company_name: str,
    ticker_clean: str,
    seen: set,
    max_items: int,
    source: str = "Maya TASE",
    fetch_path: str = "maya_api",
) -> List[MayaReport]:
    out: List[MayaReport] = []
    for item in raw_items:
        if len(out) >= max_items:
            break
        filing_id = item.get("id") or ""
        title     = (item.get("title") or item.get("header") or "").strip()
        for sfx in [" | מאיה - אתר הבורסה", " | MAYA - TASE Site", " - מאיה"]:
            title = title.replace(sfx, "").strip()
        published = item.get("publishDate") or item.get("date") or ""
        if published and "T" in str(published):
            try:
                published = datetime.fromisoformat(
                    str(published).split(".")[0]
                ).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
        link = _MAYA_REPORT_URL.format(filing_id) if filing_id else ""
        if not link or link in seen:
            continue
        seen.add(link)
        out.append(MayaReport(
            title=title or f"Report {filing_id}",
            published=str(published),
            link=link,
            source=source,
            report_type=_detect_report_type(title),
            company_name=company_name,
            ticker=ticker_clean,
            fetch_path=fetch_path,
        ))
    return out


# ── MAYA: response interceptor (capture Angular's own API calls) ──────────────

def _attach_response_interceptor(page) -> list:
    """
    Attach a response listener that captures MAYA's /api/v1/reports/companies
    responses. Returns a shared list that gets populated as Angular makes API calls.
    The list is populated in place — check it after UI interactions complete.
    """
    captured: list = []

    def _on_response(response):
        try:
            if "/api/v1/reports/companies" in response.url and response.status == 200:
                data = response.json()
                items = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(items, list) and items:
                    _log(f"    [Maya-Intercept] Captured {len(items)} items from Angular API call")
                    captured.extend(items)
        except Exception:
            pass

    page.on("response", _on_response)
    return captured


# ── MAYA: API probe (full debug response) ────────────────────────────────────

def _maya_api_probe(page, name_he: str, max_items: int) -> tuple[Optional[int], list]:
    """
    Phase B: call MAYA's internal APIs from within the browser session.
    Returns (companyId, raw_report_list). Logs every HTTP status and body snippet.
    """
    name_json = json.dumps(name_he)

    # ── Step B1: search for companyId by Hebrew name ──────────────────────────
    search_js = f"""
    async () => {{
        const term = {name_json};
        const encoded = encodeURIComponent(term);
        const urls = [
            `/api/v1/companies?searchTerm=${{encoded}}&pageSize=10&pageNumber=1`,
            `/api/v1/companies?searchTerm=${{encoded}}&pageSize=5`,
        ];
        const results = [];
        for (const url of urls) {{
            try {{
                const r = await fetch(url, {{
                    method: 'GET',
                    headers: {{
                        'accept': 'application/json, text/plain, */*',
                        'accept-language': 'he-IL,he;q=0.9',
                        'x-requested-with': 'XMLHttpRequest',
                    }},
                }});
                const text = await r.text();
                results.push({{ url, status: r.status, body: text.slice(0, 500) }});
                if (r.ok) {{
                    try {{
                        const data = JSON.parse(text);
                        const items = Array.isArray(data) ? data
                            : (data.items || data.companies || data.data || data.results || []);
                        for (const item of (items || [])) {{
                            const cid = item.companyId || item.id || item.CompanyId || item.issuerNumber;
                            const n   = item.name || item.companyName || item.nameHe || '';
                            if (typeof cid === 'number' && cid > 0) return {{ cid, name: n, url, debug: results }};
                            if (typeof cid === 'string' && /^\\d+$/.test(cid) && parseInt(cid) > 0)
                                return {{ cid: parseInt(cid), name: n, url, debug: results }};
                        }}
                    }} catch(e) {{}}
                }}
            }} catch(e) {{ results.push({{ url, error: String(e) }}); }}
        }}
        return {{ cid: null, debug: results }};
    }}
    """
    company_id: Optional[int] = None
    try:
        res = page.evaluate(search_js)
        if isinstance(res, dict):
            debug = res.get("debug", [])
            for entry in (debug or []):
                _log(f"    [Maya-API] {entry.get('url','')} → status={entry.get('status','?')} body={entry.get('body','')[:120]}")
            cid = res.get("cid")
            if isinstance(cid, int) and cid > 0:
                _log(f"    [Maya-API] companyId={cid} ({res.get('name','')})")
                company_id = cid
            else:
                _log(f"    [Maya-API] no companyId found in search response")
    except Exception as exc:
        _log(f"    [Maya-API] search evaluate error: {exc}")

    if not company_id:
        return None, []

    # ── Step B2: fetch reports by companyId ───────────────────────────────────
    body_json = json.dumps({
        "pageNumber": 1, "companyId": company_id,
        "pageSize": max_items, "limit": max_items, "offset": 0,
    })
    reports_js = f"""
    async () => {{
        try {{
            const r = await fetch('/api/v1/reports/companies', {{
                method: 'POST',
                headers: {{
                    'accept': 'application/json, text/plain, */*',
                    'content-type': 'application/json',
                    'accept-language': 'he-IL,he;q=0.9',
                }},
                body: {json.dumps(body_json)},
            }});
            const text = await r.text();
            return {{ status: r.status, body: text.slice(0, 300), ok: r.ok,
                      data: r.ok ? JSON.parse(text) : null }};
        }} catch(e) {{
            return {{ error: String(e) }};
        }}
    }}
    """
    try:
        res = page.evaluate(reports_js)
        if isinstance(res, dict):
            _log(f"    [Maya-API] reports POST → status={res.get('status','?')} body={res.get('body','')[:120]}")
            data = res.get("data")
            if isinstance(data, list):
                _log(f"    [Maya-API] reports list length={len(data)}")
                return company_id, data
            _log(f"    [Maya-API] reports data not a list: {type(data)}")
    except Exception as exc:
        _log(f"    [Maya-API] reports evaluate error: {exc}")

    return company_id, []


# ── MAYA: UI automation → expect_response capture ────────────────────────────

def _maya_ui_and_intercept(page, name_he: str) -> list:
    """
    Type Hebrew name into MAYA search → click first autocomplete suggestion →
    use page.expect_response() to synchronously capture the Angular API call
    that renders the company's filing table.

    Returns the raw API items list (dicts with id/header/publishDate).
    Returns [] on any failure or timeout.

    This is more reliable than a fixed-delay interceptor because we wait for
    the EXACT network response Angular makes when the company filter is applied.
    """
    try:
        from playwright.sync_api import TimeoutError as PWTimeout
    except ImportError:
        return []

    # ── Find search input ─────────────────────────────────────────────────────
    input_selectors = [
        "input[formcontrolname='freeText']",
        "input[formcontrolname='companyName']",
        "mat-form-field input[type='text']",
        "input.mat-input-element",
        "input[placeholder*='חיפוש']",
        "input[placeholder*='שם']",
        "input[placeholder*='חברה']",
        "input[type='text']:not([readonly]):not([disabled])",
    ]
    found_input = False
    for sel in input_selectors:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible(timeout=4000):
                el.click()
                page.wait_for_timeout(300)
                page.keyboard.press("Control+a")
                page.keyboard.press("Delete")
                page.keyboard.type(name_he)
                _log(f"    [Maya-UI] Typed {name_he!r} into {sel!r}")
                found_input = True
                break
        except Exception:
            continue

    if not found_input:
        _log("    [Maya-UI] search input not found")
        return []

    # ── Wait for autocomplete panel ───────────────────────────────────────────
    page.wait_for_timeout(1500)

    ac_option_selectors = [
        ".cdk-overlay-container mat-option",
        ".mat-autocomplete-panel mat-option",
        "mat-option",
        "[role='listbox'] [role='option']",
        ".mat-option",
    ]

    # ── Click autocomplete while waiting for the Angular API response ─────────
    # page.expect_response() waits synchronously for a matching HTTP response.
    # The Angular app calls /api/v1/reports/companies when a company is selected;
    # Imperva allows this because the request comes from the real browser session.
    try:
        with page.expect_response(
            lambda r: "/api/v1/reports/companies" in r.url and r.status == 200,
            timeout=10_000,
        ) as response_info:
            clicked_ac = False
            for sel in ac_option_selectors:
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible(timeout=2000):
                        option_text = el.inner_text()
                        _log(f"    [Maya-UI] Autocomplete option: {option_text!r}")
                        el.click()
                        clicked_ac = True
                        _log(f"    [Maya-UI] Clicked autocomplete")
                        break
                except Exception:
                    continue
            if not clicked_ac:
                _log("    [Maya-UI] no autocomplete visible — pressing Enter")
                page.keyboard.press("Enter")

        response = response_info.value
        data     = response.json()
        items    = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(items, list):
            _log(f"    [Maya-UI] expect_response captured {len(items)} items")
            return items
        _log(f"    [Maya-UI] unexpected data type: {type(items)}")
    except PWTimeout:
        _log("    [Maya-UI] expect_response timeout — Angular API call not observed")
    except Exception as exc:
        _log(f"    [Maya-UI] expect_response error: {exc}")

    return []


# ── MAYA main fetch ───────────────────────────────────────────────────────────

def _fetch_maya_ui(
    name_he: str,
    ticker_clean: str,
    company_name: str,
    max_items: int = 20,
) -> tuple[List[MayaReport], str]:
    """
    Two-phase MAYA fetch with full debug logging and screenshots.

    Phase A — UI automation:
      Navigate to MAYA → type Hebrew name char-by-char → click first autocomplete
      option → wait for table update → scrape DOM for report links.

    Phase B — API probe (if Phase A returns 0):
      Call GET /api/v1/companies?searchTerm={name_he} → companyId
      Call POST /api/v1/reports/companies {companyId} → raw filings
      Full HTTP status + body logged at every step.

    Screenshots saved to system temp dir at each stage.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [], "playwright_not_installed"

    reports: List[MayaReport] = []
    seen:    set = set()

    _log(f"    [Maya] ticker={ticker_clean!r}  search_text={name_he!r}")
    _log(f"    [Maya] MAYA URL: {_MAYA_SEARCH_URL}")

    try:
        with sync_playwright() as pw:
            browser = _launch_browser(pw)
            context = _new_context(browser)
            page    = context.new_page()

            # ── Navigate first, attach interceptor after ──────────────────────
            _pw_navigate(page, _MAYA_SEARCH_URL, "Maya")
            _wait_imperva(page, timeout=12)
            _screenshot(page, ticker_clean, "01_loaded")

            # Extra wait: ensure Angular has had time to render the form even
            # when Imperva cookies arrived instantly (0.0 s) and the JS bundle
            # hasn't finished bootstrapping yet.
            page.wait_for_timeout(1500)

            # ── Phase A: type → autocomplete → expect_response ────────────────
            # _maya_ui_and_intercept uses page.expect_response() to synchronously
            # wait for the Angular API call that fires when a company is selected.
            # No fixed-delay polling — we get the exact response Angular fetches.
            _log(f"    [Maya] Phase A: UI+intercept — typing {name_he!r}")
            raw_items = _maya_ui_and_intercept(page, name_he)
            _screenshot(page, ticker_clean, "02_after_ui")

            if raw_items:
                intercept_reports = _raw_to_reports(
                    raw_items, company_name, ticker_clean, seen, max_items,
                    source="Maya TASE",
                    fetch_path="maya_intercept",
                )
                _log(f"    [Maya] Phase A SUCCESS: {len(intercept_reports)} filings")
                for r in intercept_reports[:2]:
                    _log(f"    [Maya]   {(r.published or '')[:10] or '??'} | {r.title[:70]}")
                browser.close()
                return intercept_reports[:max_items], f"maya_intercept:{len(intercept_reports)}"

            _log(f"    [Maya] Phase A: 0 — trying Phase B (direct API probe)")

            # ── Phase B: API probe with full debug ────────────────────────────
            company_id, raw = _maya_api_probe(page, name_he, max_items)
            _screenshot(page, ticker_clean, "03_after_api")

            if raw:
                reports = _raw_to_reports(
                    raw, company_name, ticker_clean, seen, max_items,
                    source="Maya TASE",
                    fetch_path=f"maya_api:cid={company_id}",
                )

            count = len(reports)
            _log(f"    [Maya] Phase B result: {count} filings (companyId={company_id})")
            for r in reports[:2]:
                _log(f"    [Maya]   {(r.published or '')[:10] or '??'} | {r.title[:70]}")

            browser.close()
            if reports:
                return reports, f"maya_api:{count}:cid={company_id}"
            return [], f"maya_0:cid={company_id}"

    except Exception as exc:
        _log(f"    [Maya] Playwright exception: {exc}")
        return [], f"maya_error:{exc}"


# ── MAGNA UI extraction ───────────────────────────────────────────────────────

def _extract_magna_reports(
    page,
    company_name: str,
    ticker_clean: str,
    max_items: int,
    seen: set,
) -> List[MayaReport]:
    """Extract MayaReport objects from the current MAGNA page DOM."""
    reports: List[MayaReport] = []

    try:
        items = page.evaluate(r"""
            () => {
                // Table rows first
                const rows = Array.from(document.querySelectorAll(
                    'table tbody tr, .result-item, .filing-item, li.result, .search-result'
                ));
                const out = [];
                for (const row of rows.slice(0, 50)) {
                    const a = row.querySelector('a[href]');
                    if (!a) continue;
                    const href = a.href || '';
                    if (!href || href.includes('javascript') || href.includes('#')) continue;
                    const cells = Array.from(row.querySelectorAll('td, .cell, span'));
                    const dateCell = cells.find(c =>
                        /\d{2}[\/\-]\d{2}[\/\-]\d{4}|\d{4}-\d{2}-\d{2}/.test(c.innerText)
                    );
                    out.push({
                        href,
                        text: (a.innerText || a.textContent || '').trim(),
                        date: dateCell ? dateCell.innerText.trim() : '',
                    });
                }
                // Fallback: all links on the page pointing to magna/isa
                if (out.length === 0) {
                    const allLinks = Array.from(document.querySelectorAll('a[href]'));
                    for (const a of allLinks) {
                        const href = a.href || '';
                        const text = (a.innerText || a.textContent || '').trim();
                        if (!href || href.includes('javascript') || href.includes('#')) continue;
                        if (text.length < 5) continue;
                        if (href.includes('magna.isa.gov.il') || href.includes('isa.gov.il')) {
                            out.push({ href, text, date: '' });
                        }
                    }
                }
                return out.slice(0, 40);
            }
        """)

        for item in (items or [])[:max_items * 2]:
            href  = (item.get("href") or "").strip()
            title = (item.get("text") or "").strip()
            date  = (item.get("date") or "").strip()
            if not href or href in seen:
                continue
            seen.add(href)
            reports.append(MayaReport(
                title=title or "Filing",
                published=date,
                link=href,
                source="MAGNA",
                report_type=_detect_report_type(title),
                company_name=company_name,
                ticker=ticker_clean,
                fetch_path="magna_ui",
            ))
    except Exception:
        pass

    return reports[:max_items]


# ── MAGNA UI search ───────────────────────────────────────────────────────────

def _fetch_magna_ui(
    name_he: str,
    ticker_clean: str,
    company_name: str,
    max_items: int = 20,
) -> tuple[List[MayaReport], str]:
    """
    Playwright UI: open MAGNA, type Hebrew name, click autocomplete,
    extract filings from results page.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [], "playwright_not_installed"

    reports: List[MayaReport] = []
    seen:    set = set()

    _log(f"    [Magna] ticker={ticker_clean!r}  search_text={name_he!r}")
    _log(f"    [Magna] MAGNA URL: {_MAGNA_SEARCH_URL}")

    try:
        with sync_playwright() as pw:
            browser = _launch_browser(pw)
            context = _new_context(browser)
            page    = context.new_page()

            # ── Navigate ──────────────────────────────────────────────────────
            _pw_navigate(page, _MAGNA_SEARCH_URL, "Magna")

            # ── Find and fill search field ────────────────────────────────────
            search_selectors = [
                "input[name='q']",
                "input#q",
                "input#search",
                "input[type='search']",
                "input[placeholder*='חיפוש']",
                "input[placeholder*='search' i]",
                "input.form-control[type='text']",
                "input[type='text']",
                ".search-input input",
                "form input",
            ]
            search_sel = _pw_fill(page, search_selectors, name_he, timeout=10_000, label="Magna")

            if not search_sel:
                _log(f"    [Magna] ERROR: search field not found on MAGNA page")
                browser.close()
                return [], "magna_no_search_field"

            # ── Wait for autocomplete, click first suggestion ─────────────────
            page.wait_for_timeout(1500)

            ac_selectors = [
                ".autocomplete-results li:first-child",
                ".suggestions li:first-child",
                ".dropdown-menu li:first-child",
                "[role='listbox'] [role='option']:first-child",
                ".search-suggestion:first-child",
                ".ui-autocomplete li:first-child",
                "ul.typeahead li:first-child",
                ".tt-suggestion:first-child",
            ]
            clicked_sel = _pw_click_first(page, ac_selectors, timeout=4000, label="Magna")

            if clicked_sel:
                _log(f"    [Magna] autocomplete_clicked=true ({clicked_sel})")
            else:
                _log(f"    [Magna] autocomplete_clicked=false — pressing Enter")
                page.keyboard.press("Enter")

            # ── Wait for results ──────────────────────────────────────────────
            page.wait_for_timeout(3000)
            reports = _extract_magna_reports(page, company_name, ticker_clean, max_items, seen)

            if not reports:
                page.wait_for_timeout(2000)
                reports = _extract_magna_reports(page, company_name, ticker_clean, max_items, seen)

            count = len(reports)
            _log(f"    [Magna] MAGNA result_count={count}")
            for r in reports[:2]:
                _log(f"    [Magna]   {r.published or '??'} | {r.title[:70]}")

            browser.close()
            return reports, f"magna_ui:{count}"

    except Exception as exc:
        _log(f"    [Magna] Playwright exception: {exc}")
        return [], f"magna_ui_error:{exc}"


# ── Main public fetch function ─────────────────────────────────────────────────

def fetch_company_reports(
    company_name: str,
    ticker: str,
    max_items: int = 10,
    name_he: Optional[str] = None,
    identity=None,
) -> List[MayaReport]:
    """
    Fetch company filings: MAYA first, MAGNA fallback.

    Flow:
      1. Resolve Hebrew company name from stock table (tase_stocks.csv).
      2. PRIMARY — MAYA UI search:
           Open maya.tase.co.il/he/reports/companies (with date filter).
           Type Hebrew name → click first autocomplete → extract filings.
           If ≥ 1 filing: return MAYA results, STOP.
      3. FALLBACK — MAGNA UI search (only if MAYA returned 0):
           Open magna.isa.gov.il.
           Type same Hebrew name → click first autocomplete → extract filings.
      4. If both fail: log NO_COMPANY_FILINGS_FOUND, return [].

    Results from MAYA and MAGNA are NEVER mixed.

    Debug log per call:
      ticker / Hebrew name / MAYA URL / search text / autocomplete clicked /
      MAYA count / MAGNA used / MAGNA count / final source
    """
    if identity is not None:
        company_name = getattr(identity, "name_en", None) or company_name
        if getattr(identity, "ticker", None):
            ticker = identity.ticker
        if getattr(identity, "name_he", None):
            name_he = identity.name_he

    ticker_clean = ticker.replace(".TA", "").strip().upper()

    # ── Resolve Hebrew name ───────────────────────────────────────────────────
    if not name_he:
        name_he = get_hebrew_name(ticker_clean)
    if not name_he:
        try:
            from .stock_master import get_master_table as _get_master
            row = _get_master().lookup_by_ticker(ticker_clean)
            if row:
                name_he = row.short_name or row.name_he
        except Exception:
            pass

    _log(f"  [Maya] ===== {ticker_clean} ({company_name}) =====")
    _log(f"  [Maya] ticker={ticker_clean!r}  name_he={name_he!r}")

    if not name_he:
        _log(f"  [Maya] NO_COMPANY_FILINGS_FOUND")
        _log(f"  [Maya]   ticker={ticker_clean!r}")
        _log(f"  [Maya]   reason=no Hebrew name in stock table")
        return []

    # ── PRIMARY: MAYA ─────────────────────────────────────────────────────────
    _log(f"  [Maya] Step 1: MAYA search")
    _log(f"  [Maya]   MAYA URL: {_MAYA_SEARCH_URL}")
    _log(f"  [Maya]   search text: {name_he!r}")

    maya_reports, maya_debug = _fetch_maya_ui(
        name_he=name_he,
        ticker_clean=ticker_clean,
        company_name=company_name,
        max_items=max(max_items, 20),
    )

    maya_ok = len(maya_reports) >= 1
    _log(f"  [Maya] MAYA result_count={len(maya_reports)}  succeeded={maya_ok}")

    if maya_ok:
        _log(f"  [Maya] final_source=MAYA  count={len(maya_reports)}")
        return maya_reports[:max_items]

    # ── FALLBACK: MAGNA ───────────────────────────────────────────────────────
    _log(f"  [Maya] MAYA returned 0 — trying MAGNA fallback")
    _log(f"  [Maya]   MAGNA URL: {_MAGNA_SEARCH_URL}")
    _log(f"  [Maya]   search text: {name_he!r}")

    magna_reports, magna_debug = _fetch_magna_ui(
        name_he=name_he,
        ticker_clean=ticker_clean,
        company_name=company_name,
        max_items=max(max_items, 20),
    )

    magna_ok = len(magna_reports) >= 1
    _log(f"  [Maya] MAGNA result_count={len(magna_reports)}  succeeded={magna_ok}")

    if magna_ok:
        _log(f"  [Maya] final_source=MAGNA  count={len(magna_reports)}")
        return magna_reports[:max_items]

    # ── Both failed ───────────────────────────────────────────────────────────
    _log(f"  [Maya] NO_COMPANY_FILINGS_FOUND")
    _log(f"  [Maya]   ticker={ticker_clean!r}")
    _log(f"  [Maya]   name_he={name_he!r}")
    _log(f"  [Maya]   MAYA query: {name_he!r}  [{maya_debug}]")
    _log(f"  [Maya]   MAGNA query: {name_he!r}  [{magna_debug}]")
    return []


# ── Simple wrapper (used by app.py Maya tab) ─────────────────────────────────

def fetch_company_reports_simple(
    ticker: str,
    max_items: int = 10,
) -> tuple[List[MayaReport], str, str]:
    """
    Thin wrapper for app.py — same MAYA-first, MAGNA-fallback flow.
    Returns (reports, name_he_used, debug_note).
    """
    ticker_clean = ticker.replace(".TA", "").strip().upper()
    name_he = get_hebrew_name(ticker_clean)
    if not name_he:
        try:
            from .stock_master import get_master_table as _get_master
            row = _get_master().lookup_by_ticker(ticker_clean)
            if row:
                name_he = row.short_name or row.name_he
        except Exception:
            pass

    reports = fetch_company_reports(
        company_name=name_he or ticker_clean,
        ticker=ticker_clean,
        max_items=max_items,
        name_he=name_he,
    )

    source = reports[0].source if reports else "none"
    count  = len(reports)
    debug  = f"{count} filings via {source}" if reports else "no filings found"
    return reports, name_he or ticker_clean, debug


# ── LLM impact assessment ──────────────────────────────────────────────────────

def assess_company_report_impacts(
    reports: List[MayaReport],
    ticker: str,
    company_name: str,
    client: openai.OpenAI,
    config,
) -> List[MayaReport]:
    """Batch LLM call: classify each filing as bullish / bearish / neutral."""
    if not reports:
        return reports

    items_json = json.dumps(
        [{"id": i, "title": r.title, "type": r.report_type, "source": r.source}
         for i, r in enumerate(reports)],
        ensure_ascii=False,
    )

    prompt = f"""You are an Israeli equity analyst covering {ticker} ({company_name}).

Below are recent regulatory filings and news reports about this company from Maya TASE.
For each item assess the likely impact on the stock price.

Items:
{items_json}

Return a JSON object with key "results", each element:
- "id": same as input
- "impact": "bullish" / "bearish" / "neutral"
- "impact_reason": one sentence explaining the impact on {ticker} specifically

Return valid JSON only."""

    try:
        resp = client.chat.completions.create(
            model=config.models.agent,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
            response_format={"type": "json_object"},
        )
        data    = json.loads(resp.choices[0].message.content)
        results = data.get("results", data.get("items", []))
        id_map  = {r["id"]: r for r in results if "id" in r}
        for i, report in enumerate(reports):
            if i in id_map:
                report.impact        = id_map[i].get("impact", "neutral")
                report.impact_reason = id_map[i].get("impact_reason", "")
    except Exception:
        pass

    return reports


# ── Market-wide feed (Maya tab in app) ────────────────────────────────────────

FEED_QUERIES = [
    "דיווח מיידי בורסה תל אביב",
    "דוח רבעוני חברות ישראל",
    "TASE Israel earnings report",
    "בורסה תל אביב אירוע מהותי",
    "מאיה TASE גילוי נאות",
]


def fetch_raw_reports(max_per_query: int = 8) -> List[MayaReport]:
    """Fetch market-wide reports from Google News RSS (no company filter)."""
    seen_links: set = set()
    reports:    List[MayaReport] = []
    base = "https://news.google.com/rss/search?q={q}&hl=iw&gl=IL&ceid=IL:iw"

    for query in FEED_QUERIES:
        try:
            encoded = query.replace(" ", "+")
            feed    = feedparser.parse(base.format(q=encoded))
            for entry in feed.entries[:max_per_query]:
                link = entry.get("link", "")
                if link in seen_links:
                    continue
                seen_links.add(link)
                reports.append(MayaReport(
                    title=entry.get("title", ""),
                    published=entry.get("published", ""),
                    link=link,
                    source=entry.get("source", {}).get("title", ""),
                    report_type=_detect_report_type(entry.get("title", "")),
                ))
            time.sleep(0.3)
        except Exception:
            continue

    return reports


def analyze_reports_batch(
    reports: List[MayaReport],
    known_stocks: List[Dict],
    client: openai.OpenAI,
    config,
    max_analyze: int = 30,
) -> List[MayaReport]:
    """LLM batch: match headlines to tickers and classify impact."""
    if not reports:
        return []

    batch      = reports[:max_analyze]
    stocks_ctx = "\n".join(f"- {s['ticker']}: {s['name']}" for s in known_stocks)
    items_json = json.dumps(
        [{"id": i, "title": r.title, "source": r.source, "type": r.report_type}
         for i, r in enumerate(batch)],
        ensure_ascii=False,
    )

    prompt = f"""You are an Israeli financial analyst.

Known TASE stocks:
{stocks_ctx}

For each headline return a JSON array where each element has:
- "id": same id as input
- "company_name": exact company name if identifiable, else null
- "ticker": matching ticker from the list above, else null
- "sector": sector if identifiable, else null
- "impact": "bullish" / "bearish" / "neutral"
- "impact_reason": one sentence why (in English)
- "summary": one-sentence plain-English summary

Headlines:
{items_json}

Return ONLY a valid JSON array."""

    try:
        resp = client.chat.completions.create(
            model=config.models.agent,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(resp.choices[0].message.content)
        if isinstance(parsed, dict):
            for key in ("reports", "items", "results", "data"):
                if key in parsed:
                    parsed = parsed[key]
                    break
        if isinstance(parsed, list):
            id_map = {item["id"]: item for item in parsed if "id" in item}
            for i, report in enumerate(batch):
                if i in id_map:
                    info = id_map[i]
                    report.company_name  = info.get("company_name")
                    report.ticker        = info.get("ticker")
                    report.sector        = info.get("sector")
                    report.impact        = info.get("impact", "neutral")
                    report.impact_reason = info.get("impact_reason", "")
                    report.summary       = info.get("summary", "")
    except Exception:
        pass

    return batch


def get_maya_reports(
    client: openai.OpenAI,
    config,
    known_stocks: List[Dict],
    max_reports: int = 30,
) -> List[MayaReport]:
    """Full pipeline for the Maya tab: fetch market-wide feed + LLM analysis."""
    raw      = fetch_raw_reports()
    analyzed = analyze_reports_batch(raw, known_stocks, client, config, max_analyze=max_reports)
    return analyzed
