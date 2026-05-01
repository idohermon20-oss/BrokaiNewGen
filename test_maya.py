"""
Maya Report Fetcher — standalone test
======================================
Run without doing a full analysis.

Usage:
    python test_maya.py ESLT
    python test_maya.py BEZQ
    python test_maya.py TEVA --max 15
    python test_maya.py ESLT --name-he "אלביט מערכות"   # override Hebrew name
    python test_maya.py AAPL --name "Apple Inc" --no-assess  # skip LLM impact assessment
"""
import sys
import os
import argparse

# Make sure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def main():
    parser = argparse.ArgumentParser(description="Test the Maya TASE report fetcher.")
    parser.add_argument("ticker",              help="TASE ticker, e.g. ESLT")
    parser.add_argument("--name",              default=None,  help="English company name override")
    parser.add_argument("--name-he",           default=None,  help="Hebrew company name override")
    parser.add_argument("--max",               type=int, default=10, help="Max reports to fetch (default 10)")
    parser.add_argument("--no-assess",         action="store_true",  help="Skip LLM impact assessment")
    parser.add_argument("--market",            default="il", choices=["il", "us"])
    args = parser.parse_args()

    ticker = args.ticker.upper().replace(".TA", "")

    # ── Resolve canonical company identity ───────────────────────────────────
    from borkai.data.company_resolver import resolve_company
    from borkai.data.maya_fetcher import fetch_company_reports, assess_company_report_impacts

    query    = args.name_he or args.name or ticker
    identity = resolve_company(query)

    # Allow CLI overrides to supplement the resolved identity
    if args.name_he:
        identity.name_he = args.name_he
    if args.name:
        identity.name_en = args.name

    company_name = identity.name_en or identity.ticker or ticker

    print(f"\n{'='*60}")
    print(f"  Maya Fetcher Test")
    print(f"  Query   : {query!r}")
    print(f"  Ticker  : {identity.ticker or ticker}")
    print(f"  English : {identity.name_en or '(unknown)'}")
    print(f"  Hebrew  : {identity.name_he or '(unknown)'}")
    print(f"  Maya ID : {identity.maya_id or '(unknown)'}")
    print(f"  Path    : {identity.resolution_path}  confidence={identity.confidence:.2f}")
    if identity.resolution_note:
        print(f"  Note    : {identity.resolution_note}")
    print(f"  Variants: {identity.news_variants}")
    print(f"  Max     : {args.max}")
    print(f"{'='*60}\n")

    # ── Fetch ─────────────────────────────────────────────────────────────────
    print("Fetching reports from Maya TASE (Playwright API / DDG fallback)...")
    reports = fetch_company_reports(
        company_name=company_name,
        ticker=identity.ticker or ticker,
        max_items=args.max,
        identity=identity,
    )

    if not reports:
        print("No reports found.")
        return

    print(f"\n{len(reports)} reports found (before LLM assessment):\n")
    for i, r in enumerate(reports, 1):
        print(f"  [{i:02d}] {r.title[:80]}")
        print(f"       link  : {r.link}")
        print(f"       date  : {r.published or '(no date)'}")
        print(f"       type  : {r.report_type}  |  path: {r.fetch_path}")
        print()

    # ── LLM impact assessment ─────────────────────────────────────────────────
    if args.no_assess:
        print("(Skipping LLM impact assessment — use without --no-assess to run it)")
        return

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("OPENAI_API_KEY not set — skipping impact assessment.")
        print("(Set it in .env or pass --no-assess to skip)")
        return

    print("Running LLM impact assessment...")
    import openai
    from borkai.config import load_config
    client = openai.OpenAI(api_key=api_key)
    config = load_config(market=args.market)

    reports = assess_company_report_impacts(reports, ticker, company_name, client, config)

    print(f"\n{'='*60}")
    print(f"  Results with impact assessment")
    print(f"{'='*60}\n")

    bull = [r for r in reports if r.impact == "bullish"]
    bear = [r for r in reports if r.impact == "bearish"]
    neut = [r for r in reports if r.impact == "neutral"]
    print(f"  Bullish: {len(bull)}  Bearish: {len(bear)}  Neutral: {len(neut)}\n")

    for i, r in enumerate(reports, 1):
        icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}.get(r.impact, "⚪")
        print(f"  {icon} [{i:02d}] {r.title[:75]}")
        if r.impact_reason:
            print(f"        → {r.impact_reason}")
        print(f"        {r.link}")
        print()

    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
