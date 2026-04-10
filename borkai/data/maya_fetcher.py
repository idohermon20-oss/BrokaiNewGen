"""
Maya TASE Report Fetcher

Fetches recent regulatory filings for Israeli stocks from Maya (maya.tase.co.il).

Strategy for company-specific reports:
  1. DDG search with Hebrew company name  → best precision (Maya indexes Hebrew names)
  2. DDG search with ticker symbol        → good fallback
  3. DDG search with English company name → last resort
  4. Google News RSS fallback             → if DDG returns nothing

The Maya REST API (mayaapi.tase.co.il) is blocked by Imperva — do not use it.
"""
import feedparser
import openai
import json
import csv
import os
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

_MAYA_REPORT_URL  = "https://maya.tase.co.il/reports/details/{}"
_TASE_CSV         = os.path.join(os.path.dirname(__file__), "tase_stocks.csv")

# ── Hebrew name lookup ────────────────────────────────────────────────────────

_HE_NAME_CACHE: Optional[Dict[str, str]] = None   # ticker → name_he


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


# ── Report type detection ─────────────────────────────────────────────────────

REPORT_TYPE_KEYWORDS = {
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


# ── Data class ────────────────────────────────────────────────────────────────

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
    impact: str = "neutral"
    impact_reason: str = ""
    summary: str = ""


# ── URL validation ────────────────────────────────────────────────────────────

# Accept Maya URLs with numeric filing IDs (6+ digits).
# Filing IDs are typically 7 digits (e.g. 1666568); company IDs are 3-4 digits — exclude those.
_MAYA_REPORT_RE = re.compile(r'maya\.tase\.co\.il.*/reports/(?:details/|companies/)?(\d{6,})')


def _is_maya_report_url(url: str) -> bool:
    return bool(_MAYA_REPORT_RE.search(url))


# ── Company-specific fetching ─────────────────────────────────────────────────

def fetch_company_reports(
    company_name: str,
    ticker: str,
    max_items: int = 10,
    name_he: Optional[str] = None,
) -> List[MayaReport]:
    """
    Fetch Maya TASE regulatory filings for a specific company.

    Search order (most precise first):
      1. DDG  site:maya.tase.co.il  "{name_he}"   (Hebrew name — highest yield)
      2. DDG  site:maya.tase.co.il  {ticker}       (ticker symbol)
      3. DDG  site:maya.tase.co.il  "{company_name}" (English name)
      4. Google News RSS fallback

    Args:
        company_name: English company name (e.g. "Elbit Systems")
        ticker:       TASE ticker with or without .TA (e.g. "ESLT" or "ESLT.TA")
        max_items:    Maximum filings to return
        name_he:      Hebrew company name override; if None, looked up from CSV
    """
    try:
        from ddgs import DDGS
        _ddgs_available = True
    except ImportError:
        _ddgs_available = False

    ticker_clean = ticker.replace(".TA", "").strip().upper()

    # Resolve Hebrew name
    if not name_he:
        name_he = get_hebrew_name(ticker_clean)

    reports: List[MayaReport] = []
    seen_links: set = set()

    def _add_ddg_results(query: str) -> int:
        """Run one DDG query, append valid Maya report URLs. Returns count added."""
        if not _ddgs_available:
            return 0
        added = 0
        try:
            ddgs = DDGS()
            results = list(ddgs.text(query, max_results=15))
        except Exception:
            return 0
        for r in results:
            if len(reports) >= max_items:
                break
            url   = r.get("href", "")
            title = r.get("title", "").strip()
            if not url or not title or url in seen_links:
                continue
            if not _is_maya_report_url(url):
                continue
            seen_links.add(url)
            # Strip boilerplate site suffix from title
            for suffix in [" | מאיה - אתר הבורסה", " | MAYA - TASE Site", " - מאיה"]:
                title = title.replace(suffix, "").strip()
            reports.append(MayaReport(
                title=title,
                published="",
                link=url,
                source="Maya TASE",
                report_type=_detect_report_type(title),
                company_name=company_name,
                ticker=ticker_clean,
            ))
            added += 1
        return added

    # ── Strategy 1: Hebrew name (best) ───────────────────────────────────────
    if name_he and len(reports) < max_items:
        _add_ddg_results(f'site:maya.tase.co.il "{name_he}"')

    # ── Strategy 2: Ticker symbol ────────────────────────────────────────────
    if len(reports) < max_items:
        _add_ddg_results(f"site:maya.tase.co.il {ticker_clean}")

    # ── Strategy 3: English name ─────────────────────────────────────────────
    if len(reports) < max_items:
        _add_ddg_results(f'site:maya.tase.co.il "{company_name}"')

    # ── Strategy 4: Google News RSS fallback ─────────────────────────────────
    if not reports:
        base_he = "https://news.google.com/rss/search?q={q}&hl=iw&gl=IL&ceid=IL:iw"
        base_en = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=IL&ceid=IL:en"
        rss_queries = []
        if name_he:
            rss_queries.append((f'"{name_he}" דיווח מיידי OR דוח רבעוני OR דיבידנד', base_he))
        rss_queries += [
            (f'"{company_name}" דיווח OR בורסה', base_he),
            (f'"{company_name}" TASE filing OR earnings OR disclosure', base_en),
        ]
        for query, base_url in rss_queries:
            if len(reports) >= max_items:
                break
            try:
                encoded = query.replace(" ", "+")
                feed = feedparser.parse(base_url.format(q=encoded))
                for entry in feed.entries[:max_items]:
                    link = entry.get("link", "")
                    if link in seen_links:
                        continue
                    seen_links.add(link)
                    title     = entry.get("title", "")
                    published = entry.get("published", "")
                    source    = entry.get("source", {}).get("title", "")
                    reports.append(MayaReport(
                        title=title, published=published, link=link, source=source,
                        report_type=_detect_report_type(title),
                        company_name=company_name, ticker=ticker_clean,
                    ))
                time.sleep(0.2)
            except Exception:
                continue

    return reports[:max_items]


def assess_company_report_impacts(
    reports: List[MayaReport],
    ticker: str,
    company_name: str,
    client: openai.OpenAI,
    config,
) -> List[MayaReport]:
    """
    LLM batch call: classify each filing as bullish / bearish / neutral
    and write a one-sentence impact reason for the target stock.
    """
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


# ── Market-wide feed (used by Maya tab in app) ────────────────────────────────

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
    reports: List[MayaReport] = []
    base = "https://news.google.com/rss/search?q={q}&hl=iw&gl=IL&ceid=IL:iw"

    for query in FEED_QUERIES:
        try:
            encoded = query.replace(" ", "+")
            feed = feedparser.parse(base.format(q=encoded))
            for entry in feed.entries[:max_per_query]:
                link = entry.get("link", "")
                if link in seen_links:
                    continue
                seen_links.add(link)
                published = entry.get("published", "")
                source    = entry.get("source", {}).get("title", "")
                title     = entry.get("title", "")
                reports.append(MayaReport(
                    title=title, published=published, link=link, source=source,
                    report_type=_detect_report_type(title),
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

    batch = reports[:max_analyze]
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
