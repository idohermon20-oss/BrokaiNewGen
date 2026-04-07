"""
Maya TASE Report Fetcher

Fetches recent corporate disclosures/events for Israeli stocks.
Primary source: Maya TASE API (mayaapi.tase.co.il) with real disclosure links.
Fallback: Google News RSS search for company-related filings.
"""
import feedparser
import openai
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime
import re
import time

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

_MAYA_API_BASE = "https://mayaapi.tase.co.il/api"
_MAYA_REPORT_URL = "https://maya.tase.co.il/reports/details/{}"
_MAYA_COMPANY_URL = "https://maya.tase.co.il/company/{}/events"
_MAYA_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
}

FEED_QUERIES = [
    "דיווח מיידי בורסה תל אביב",
    "דוח רבעוני חברות ישראל",
    "TASE Israel earnings report",
    "בורסה תל אביב אירוע מהותי דיווח",
    "מאיה TASE גילוי נאות",
    "Israel stock dividend announcement",
    "ישראל חברה הנפקה בורסה",
]

REPORT_TYPE_KEYWORDS = {
    "earnings": ["רבעוני", "שנתי", "earnings", "revenue", "profit", "רווח", "הכנסות"],
    "dividend": ["דיבידנד", "dividend", "חלוקה"],
    "material_event": ["אירוע מהותי", "material", "עסקה", "רכישה", "acquisition"],
    "guidance": ["תחזית", "guidance", "forecast", "צפי"],
    "regulatory": ["רגולציה", "regulatory", "אישור", "approval", "FDA", "ISA"],
    "appointment": ["מינוי", "appointment", "CEO", "מנכ"],
}


@dataclass
class MayaReport:
    title: str
    published: str
    link: str
    source: str
    report_type: str = "other"
    company_name: Optional[str] = None
    ticker: Optional[str] = None
    sector: Optional[str] = None
    impact: str = "neutral"          # bullish / bearish / neutral
    impact_reason: str = ""
    summary: str = ""


def _detect_report_type(title: str) -> str:
    title_lower = title.lower()
    for rtype, kws in REPORT_TYPE_KEYWORDS.items():
        if any(kw.lower() in title_lower for kw in kws):
            return rtype
    return "other"


def fetch_raw_reports(max_per_query: int = 8) -> List[MayaReport]:
    """Fetch raw reports from Google News RSS without LLM analysis."""
    seen_links = set()
    reports: List[MayaReport] = []
    base = "https://news.google.com/rss/search?q={q}&hl=iw&gl=IL&ceid=IL:iw"

    for query in FEED_QUERIES:
        try:
            encoded = query.replace(" ", "+")
            url = base.format(q=encoded)
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_query]:
                link = entry.get("link", "")
                if link in seen_links:
                    continue
                seen_links.add(link)
                published = entry.get("published", "")
                source = entry.get("source", {}).get("title", "")
                title = entry.get("title", "")
                reports.append(MayaReport(
                    title=title,
                    published=published,
                    link=link,
                    source=source,
                    report_type=_detect_report_type(title),
                ))
            time.sleep(0.3)
        except Exception:
            continue

    return reports


def analyze_reports_batch(
    reports: List[MayaReport],
    known_stocks: List[Dict],  # list of {ticker, name, sector}
    client: openai.OpenAI,
    config,
    max_analyze: int = 30,
) -> List[MayaReport]:
    """
    Use LLM to batch-analyze reports:
    - Match to known TASE ticker (or None)
    - Classify impact: bullish/bearish/neutral
    - Write a one-sentence summary
    """
    if not reports:
        return []

    batch = reports[:max_analyze]
    stocks_context = "\n".join(
        f"- {s['ticker']}: {s['name']} ({s['sector']})" for s in known_stocks
    )

    items_json = json.dumps([
        {"id": i, "title": r.title, "source": r.source, "type": r.report_type}
        for i, r in enumerate(batch)
    ], ensure_ascii=False)

    prompt = f"""You are an Israeli financial analyst. Below are recent news headlines about TASE (Tel Aviv Stock Exchange) companies.

Known TASE stocks:
{stocks_context}

For each headline, return a JSON array where each element has:
- "id": same id as input
- "company_name": exact company name if identifiable, else null
- "ticker": matching ticker from the list above, else null
- "sector": sector if identifiable, else null
- "impact": "bullish" / "bearish" / "neutral"
- "impact_reason": one sentence why (in English)
- "summary": one-sentence plain-English summary of the event

Headlines:
{items_json}

Return ONLY a valid JSON array, nothing else."""

    try:
        resp = client.chat.completions.create(
            model=config.models.agent,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        # Handle both array and object wrapping
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            # LLM may return {"reports": [...]} or {"items": [...]}
            for key in ("reports", "items", "results", "data"):
                if key in parsed:
                    parsed = parsed[key]
                    break
        if isinstance(parsed, list):
            id_map = {item["id"]: item for item in parsed if "id" in item}
            for i, report in enumerate(batch):
                if i in id_map:
                    info = id_map[i]
                    report.company_name = info.get("company_name")
                    report.ticker = info.get("ticker")
                    report.sector = info.get("sector")
                    report.impact = info.get("impact", "neutral")
                    report.impact_reason = info.get("impact_reason", "")
                    report.summary = info.get("summary", "")
    except Exception:
        pass

    return batch


def get_maya_reports(
    client: openai.OpenAI,
    config,
    known_stocks: List[Dict],
    max_reports: int = 30,
) -> List[MayaReport]:
    """Full pipeline: fetch + analyze. Ready to display."""
    raw = fetch_raw_reports()
    analyzed = analyze_reports_batch(raw, known_stocks, client, config, max_analyze=max_reports)
    return analyzed


# ---------------------------------------------------------------------------
# Company-specific report fetching (for single-stock analysis)
# ---------------------------------------------------------------------------

def _fetch_maya_api_reports(ticker: str, company_name: str, max_items: int = 10) -> List[MayaReport]:
    """
    Try to fetch real filings from the Maya TASE API.
    Returns an empty list (silently) if the API is unreachable or the ticker is unknown.

    Endpoint patterns tried:
      1. GET /api/company/companys?symbol={symbol}  → get CompanyId
      2. GET /api/company/companyevents?CompanyId={id}&Page=1&PageSize={n}  → get filings
    """
    if not _REQUESTS_AVAILABLE:
        return []

    ticker_clean = ticker.replace(".TA", "").strip()
    reports: List[MayaReport] = []

    try:
        # Step 1: Resolve company ID by symbol
        resp = _requests.get(
            f"{_MAYA_API_BASE}/company/companys",
            params={"symbol": ticker_clean},
            headers=_MAYA_HEADERS,
            timeout=8,
        )
        if resp.status_code != 200:
            return []

        data = resp.json()
        # Response may be a list or dict with a list
        companies = data if isinstance(data, list) else data.get("data", data.get("companies", []))
        if not companies:
            return []

        company = companies[0]
        company_id = company.get("CompanyId") or company.get("companyId") or company.get("id")
        if not company_id:
            return []

        # Step 2: Fetch recent filings/events
        resp2 = _requests.get(
            f"{_MAYA_API_BASE}/company/companyevents",
            params={"CompanyId": company_id, "Page": 1, "PageSize": max_items},
            headers=_MAYA_HEADERS,
            timeout=8,
        )
        if resp2.status_code != 200:
            return []

        data2 = resp2.json()
        events = data2 if isinstance(data2, list) else data2.get("data", data2.get("events", data2.get("items", [])))

        for ev in events[:max_items]:
            title = ev.get("Header") or ev.get("header") or ev.get("title") or ev.get("Title") or ""
            published = ev.get("PublishDate") or ev.get("publishDate") or ev.get("date") or ""
            report_id = ev.get("ReportId") or ev.get("reportId") or ev.get("id") or ""
            link = _MAYA_REPORT_URL.format(report_id) if report_id else _MAYA_COMPANY_URL.format(company_id)
            reports.append(MayaReport(
                title=title,
                published=str(published)[:20] if published else "",
                link=link,
                source="Maya TASE",
                report_type=_detect_report_type(title),
                company_name=company_name,
                ticker=ticker_clean,
            ))

    except Exception:
        return []

    return reports


def fetch_company_reports(
    company_name: str,
    ticker: str,
    max_items: int = 10,
) -> List[MayaReport]:
    """
    Fetch actual Maya TASE regulatory filings for a specific company.

    Strategy:
      1. DuckDuckGo site:maya.tase.co.il search → returns real filing URLs
         (maya.tase.co.il/reports/... or maya.tase.co.il/he/reports/...)
      2. Fallback: Google News RSS for company-related disclosure headlines.

    The Maya website blocks direct API/HTTP access (Imperva), so we rely on
    DuckDuckGo's index of Maya pages to surface the actual filing links.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        DDGS = None

    ticker_clean = ticker.replace(".TA", "").strip()
    reports: List[MayaReport] = []
    seen_links: set = set()

    # ── Strategy 1: DuckDuckGo site:maya.tase.co.il ──────────────────────
    if DDGS is not None:
        ddgs = DDGS()
        maya_queries = [
            f'site:maya.tase.co.il "{company_name}"',
            f'site:maya.tase.co.il {ticker_clean}',
        ]
        for query in maya_queries:
            if len(reports) >= max_items:
                break
            try:
                results = list(ddgs.text(query, max_results=12))
            except Exception:
                continue
            for r in results:
                url = r.get("href", "")
                title = r.get("title", "").strip()
                # Only keep actual filing/report pages (must have numeric report ID)
                is_report = bool(re.search(r'/reports/(details/)?\d+', url))
                if not url or not title or url in seen_links or not is_report:
                    continue
                seen_links.add(url)
                # Clean up title – remove company name prefix if duplicated
                clean_title = title
                for prefix in [company_name, ticker_clean, "MAYA - Tase", "מאיה - אתר הבורסה"]:
                    clean_title = clean_title.replace(prefix, "").strip(" -|–")
                if not clean_title:
                    clean_title = title
                reports.append(MayaReport(
                    title=clean_title,
                    published="",
                    link=url,
                    source="Maya TASE",
                    report_type=_detect_report_type(clean_title),
                    company_name=company_name,
                    ticker=ticker_clean,
                ))
                if len(reports) >= max_items:
                    break

    # ── Strategy 2: Google News RSS fallback ─────────────────────────────
    if not reports:
        base_he = "https://news.google.com/rss/search?q={q}&hl=iw&gl=IL&ceid=IL:iw"
        base_en = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=IL&ceid=IL:en"
        rss_queries = [
            (f'"{company_name}" דיווח מיידי', base_he),
            (f'"{company_name}" דוח רבעוני OR תוצאות OR דיבידנד', base_he),
            (f'"{ticker_clean}" TASE filing OR earnings OR disclosure', base_en),
        ]
        for query, base_url in rss_queries:
            try:
                encoded = query.replace(" ", "+")
                feed = feedparser.parse(base_url.format(q=encoded))
                for entry in feed.entries[:max_items]:
                    link = entry.get("link", "")
                    if link in seen_links:
                        continue
                    seen_links.add(link)
                    title = entry.get("title", "")
                    published = entry.get("published", "")
                    source = entry.get("source", {}).get("title", "")
                    reports.append(MayaReport(
                        title=title,
                        published=published,
                        link=link,
                        source=source,
                        report_type=_detect_report_type(title),
                        company_name=company_name,
                        ticker=ticker_clean,
                    ))
                time.sleep(0.2)
            except Exception:
                continue
            if len(reports) >= max_items:
                break

    return reports[:max_items]


def assess_company_report_impacts(
    reports: List[MayaReport],
    ticker: str,
    company_name: str,
    client: openai.OpenAI,
    config,
) -> List[MayaReport]:
    """
    Batch LLM call: for each Maya/news report, assess its specific impact
    on the target stock (bullish / bearish / neutral + one-sentence reason).
    Mutates and returns the same list.
    """
    if not reports:
        return reports

    items_json = json.dumps([
        {"id": i, "title": r.title, "type": r.report_type, "source": r.source}
        for i, r in enumerate(reports)
    ], ensure_ascii=False)

    prompt = f"""You are an Israeli equity analyst covering {ticker} ({company_name}).

Below are recent regulatory filings and news reports about this company.
For each item, assess the likely impact on the stock price.

Items:
{items_json}

Return a JSON object with key "results", each element having:
- "id": same id as input
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
        data = json.loads(resp.choices[0].message.content)
        results = data.get("results", data.get("items", []))
        id_map = {r["id"]: r for r in results if "id" in r}
        for i, report in enumerate(reports):
            if i in id_map:
                report.impact = id_map[i].get("impact", "neutral")
                report.impact_reason = id_map[i].get("impact_reason", "")
    except Exception:
        pass

    return reports
