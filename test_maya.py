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

    # ── Resolve company name ──────────────────────────────────────────────────
    from borkai.data.maya_fetcher import get_hebrew_name, fetch_company_reports, assess_company_report_impacts

    name_he = args.name_he or get_hebrew_name(ticker)

    company_name = args.name
    if not company_name:
        # Try to look up English name from CSV
        try:
            import csv as _csv
            _csv_path = os.path.join("borkai", "data", "tase_stocks.csv")
            with open(_csv_path, newline="", encoding="utf-8") as f:
                for row in _csv.DictReader(f):
                    if row["ticker"].strip().upper() == ticker:
                        company_name = row["name"].strip()
                        break
        except Exception:
            pass
        if not company_name:
            company_name = ticker  # fallback

    print(f"\n{'='*60}")
    print(f"  Maya Fetcher Test")
    print(f"  Ticker  : {ticker}")
    print(f"  English : {company_name}")
    print(f"  Hebrew  : {name_he or '(not in mapping)'}")
    print(f"  Max     : {args.max}")
    print(f"{'='*60}\n")

    # ── Fetch ─────────────────────────────────────────────────────────────────
    print("Fetching reports from Maya TASE via DDG...")
    reports = fetch_company_reports(
        company_name=company_name,
        ticker=ticker,
        max_items=args.max,
        name_he=name_he,
    )

    if not reports:
        print("No reports found.")
        return

    print(f"\n{len(reports)} reports found (before LLM assessment):\n")
    for i, r in enumerate(reports, 1):
        print(f"  [{i:02d}] {r.title[:80]}")
        print(f"       {r.link}")
        print(f"       type={r.report_type}  source={r.source}")
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
