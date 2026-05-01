"""
BEZEQ Freshness Test
=====================

Validates that the system retrieves genuinely recent:
  1. MAYA TASE filings for BEZEQ
  2. News/articles for BEZEQ

Run this to verify the fix:
    python test_bezeq_freshness.py

Expected output:
  - MAYA filings: dates within the last 30-60 days
  - News articles: dates within the last 7 days
  - Both sorted newest-first

If you see dates from years ago, the fix did not work.
"""
import os
import sys
from datetime import datetime, timedelta

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Fix Windows encoding
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

TICKER     = "BEZQ.TA"
TICKER_RAW = "BEZQ"
COMPANY    = "Bezeq Israeli Telecommunication"
NAME_HE    = None   # will be resolved from CSV


# ---------------------------------------------------------------------------
# Part 1: Resolve company identity
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print(f"  BEZEQ FRESHNESS TEST")
print("=" * 60)

from borkai.data.company_resolver import resolve_from_ticker_and_name
identity = resolve_from_ticker_and_name(TICKER, COMPANY)
NAME_HE = identity.name_he
print(f"\nIdentity resolved:")
print(f"  ticker     : {identity.ticker}")
print(f"  name_he    : {identity.name_he}")
print(f"  name_en    : {identity.name_en}")
print(f"  maya_id    : {identity.maya_id}")
print(f"  resolve    : {identity.resolution_path}")


# ---------------------------------------------------------------------------
# Part 2: Fetch MAYA filings
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("  PART 1: MAYA FILINGS")
print("=" * 60)

from borkai.data.maya_fetcher import fetch_company_reports

maya_reports = fetch_company_reports(
    company_name=COMPANY,
    ticker=TICKER,
    max_items=10,
    identity=identity,
)

print(f"\n  MAYA RESULT: {len(maya_reports)} filings retrieved")
print(f"  {'#':<3} {'Date':<18} {'Path':<35} Title")
print(f"  {'-'*3} {'-'*18} {'-'*35} {'-'*40}")
for i, r in enumerate(maya_reports, 1):
    date_str = (r.published or "NO DATE")[:16]
    marker   = " <-- NEWEST" if i == 1 else ""
    print(f"  {i:<3} {date_str:<18} {r.fetch_path:<35} {r.title[:50]}{marker}")

# Validation
now = datetime.now()
print(f"\n  VALIDATION:")
if not maya_reports:
    print("  FAIL: no Maya filings retrieved!")
elif not maya_reports[0].published:
    print("  WARN: newest filing has no date (DDG fallback, no Playwright dates)")
else:
    try:
        newest_dt = datetime.fromisoformat(maya_reports[0].published[:16])
        age_days  = (now - newest_dt).days
        if age_days <= 30:
            print(f"  PASS: newest filing is {age_days} day(s) old ({maya_reports[0].published[:10]}) — FRESH")
        elif age_days <= 90:
            print(f"  WARN: newest filing is {age_days} day(s) old ({maya_reports[0].published[:10]}) — acceptable but not ideal")
        else:
            print(f"  FAIL: newest filing is {age_days} day(s) old ({maya_reports[0].published[:10]}) — STALE!")
    except Exception as e:
        print(f"  WARN: could not parse newest filing date: {e}")

dated = [r for r in maya_reports if r.published]
undated = [r for r in maya_reports if not r.published]
print(f"  Dated filings  : {len(dated)}")
print(f"  Undated filings: {len(undated)} (DDG fallback — no date available)")


# ---------------------------------------------------------------------------
# Part 3: Fetch news/articles
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("  PART 2: NEWS / ARTICLES")
print("=" * 60)

from borkai.data.article_fetcher import fetch_ddg_articles

articles = fetch_ddg_articles(
    company_name=COMPANY,
    ticker=TICKER,
    max_articles=10,
    name_he=NAME_HE,
    identity=identity,
)

print(f"\n  NEWS RESULT: {len(articles)} articles retrieved")
print(f"  {'#':<3} {'Date':<18} {'Publisher':<25} Title")
print(f"  {'-'*3} {'-'*18} {'-'*25} {'-'*40}")
for i, a in enumerate(articles, 1):
    date_str = (a.published or "NO DATE")[:16]
    pub      = (a.publisher or "—")[:23]
    title    = a.title[:50]
    marker   = " <-- NEWEST" if i == 1 else ""
    print(f"  {i:<3} {date_str:<18} {pub:<25} {title}{marker}")

# Validation
print(f"\n  VALIDATION:")
dated_articles = [a for a in articles if a.published]
undated_articles = [a for a in articles if not a.published]

if not articles:
    print("  FAIL: no news articles retrieved!")
elif not dated_articles:
    print("  WARN: no articles have dates captured — DDG may have changed format")
else:
    newest_a = dated_articles[0]
    try:
        newest_a_dt = datetime.fromisoformat(newest_a.published[:16])
        age_days    = (now - newest_a_dt).days
        if age_days <= 7:
            print(f"  PASS: newest article is {age_days} day(s) old ({newest_a.published[:10]}) — FRESH")
        elif age_days <= 30:
            print(f"  WARN: newest article is {age_days} day(s) old ({newest_a.published[:10]}) — acceptable")
        else:
            print(f"  FAIL: newest article is {age_days} day(s) old ({newest_a.published[:10]}) — STALE!")
    except Exception as e:
        print(f"  WARN: could not parse newest article date: {e}")

print(f"  Dated articles  : {len(dated_articles)}")
print(f"  Undated articles: {len(undated_articles)}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("  SUMMARY")
print("=" * 60)

maya_ok = (
    len(maya_reports) > 0
    and maya_reports[0].published
    and (datetime.now() - datetime.fromisoformat(maya_reports[0].published[:16])).days <= 90
) if maya_reports and maya_reports[0].published else False

news_ok = (
    len(dated_articles) > 0
    and (datetime.now() - datetime.fromisoformat(dated_articles[0].published[:16])).days <= 30
) if dated_articles else False

print(f"  MAYA filings : {'PASS' if maya_ok else 'CHECK ABOVE'}")
print(f"  News articles: {'PASS' if news_ok else 'CHECK ABOVE'}")
print()
if not maya_ok:
    print("  If MAYA failed: check that Playwright is installed ('playwright install chromium')")
    print("  If dates are blank: Playwright failed, DDG fallback used (no dates)")
if not news_ok:
    print("  If news dates are blank: DDG changed their API response format")
    print("  If news is old: DDG text() is being used instead of news()")
print("=" * 60 + "\n")
