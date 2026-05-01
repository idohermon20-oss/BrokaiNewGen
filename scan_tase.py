"""
Borkai TASE Scanner

Scans all Israeli stocks in the TASE universe, runs full Borkai analysis
for one or more time horizons, ranks stocks by expected return score,
and saves top-N reports in organized folders.

Usage:
    python scan_tase.py --horizons medium
    python scan_tase.py --horizons short medium long --top-n 15
    python scan_tase.py --horizons medium --size large --resume
    python scan_tase.py --horizons short --no-articles    # skip article fetching (faster)

Output structure:
    reports/
    └── YYYY-MM-DD/
        ├── scan_progress.json
        ├── short/
        │   ├── ranking_summary.md
        │   ├── ranking_data.json
        │   └── top/
        │       ├── 01_ESLT_TA_score87.md
        │       ├── 01_ESLT_TA_score87_he.md
        │       └── ...
        ├── medium/  ...
        └── long/    ...
"""
import argparse
import csv
import json
import os
import sys
import io
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Dict

import openai

from borkai.config import load_config, Config
from borkai.data.fetcher import fetch_stock_data
from main import analyze

DEFAULT_CSV = os.path.join(os.path.dirname(__file__), "borkai", "data", "tase_stocks.csv")
DEFAULT_OUTPUT_DIR = "reports"
DEFAULT_TOP_N = 10


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ScanResult:
    ticker: str
    company_name: str
    horizon: str
    return_score: int
    direction: str
    conviction: str
    invest_recommendation: str
    report_en: str
    analysis_date: str
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Stock list loading
# ---------------------------------------------------------------------------

def load_tickers(csv_path: str, size_filter: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Load ALL stocks from CSV.
    Stocks without a ticker are recorded as skipped (not silently dropped).
    Optionally filter by market_cap_bucket (large/mid/small).
    Returns the scannable list and prints a validation summary.
    """
    if not os.path.exists(csv_path):
        print(f"ERROR: Stock list CSV not found at: {csv_path}")
        print("       Update borkai/data/tase_stocks.csv with TASE tickers.")
        sys.exit(1)

    stocks = []
    no_ticker_count = 0
    size_filtered_count = 0

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker  = row.get("ticker", "").strip()
            name_en = row.get("name_en", "").strip()
            name_he = row.get("name_he", "").strip()
            display = name_en or name_he or ticker or "unknown"

            if not ticker:
                no_ticker_count += 1
                continue

            if size_filter:
                bucket = row.get("market_cap_bucket", "").lower()
                if bucket and bucket != size_filter.lower():
                    size_filtered_count += 1
                    continue

            if not ticker.endswith(".TA"):
                ticker = ticker + ".TA"
            stocks.append({
                "ticker": ticker,
                "name": display,
                "sector": row.get("sector", "Unknown"),
                "market_cap_bucket": row.get("market_cap_bucket", ""),
                "name_he": name_he,
            })

    total_in_csv = len(stocks) + no_ticker_count + size_filtered_count
    print(f"\nSTOCK UNIVERSE LOADED FROM: {csv_path}")
    print(f"  Total rows in CSV        : {total_in_csv}")
    print(f"  Scannable (have ticker)  : {len(stocks)}")
    if no_ticker_count:
        print(f"  Skipped (no ticker)      : {no_ticker_count}")
    if size_filter:
        print(f"  Filtered (not {size_filter:5s} cap) : {size_filtered_count}")
    print(f"  Will scan                : {len(stocks)} stocks\n")
    return stocks


# ---------------------------------------------------------------------------
# Pre-filter
# ---------------------------------------------------------------------------

def prefilter_stock(ticker: str) -> tuple:
    """
    Quick data fetch to check if a stock has usable data.
    Returns (passes: bool, reason: str).
    Filters out stocks with no price data, no revenue, or near-zero volume.
    """
    try:
        data = fetch_stock_data(ticker)
        if data.current_price is None:
            return False, "no price data"
        if data.avg_volume is not None and data.avg_volume < 10000:
            return False, f"low volume ({data.avg_volume:,})"
        if data.market_cap is not None and data.market_cap < 100_000_000:
            return False, f"micro-cap (market cap < 100M)"
        return True, "ok"
    except Exception as e:
        return False, f"fetch error: {e}"


# ---------------------------------------------------------------------------
# Progress tracking (for --resume)
# ---------------------------------------------------------------------------

def load_progress(progress_file: str) -> Dict[str, Dict]:
    if os.path.exists(progress_file):
        with open(progress_file, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(progress_file: str, progress: Dict[str, Dict]) -> None:
    with open(progress_file, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Report saving
# ---------------------------------------------------------------------------

def save_top_reports(
    results: List[ScanResult],
    top_n: int,
    base_dir: str,
    horizon: str,
    analysis_date: str,
    client: openai.OpenAI,
    config: Config,
) -> str:
    """
    Save top-N reports to organized folder structure.
    Returns path to the ranking_summary.md file.
    """
    # Sort by return_score descending
    sorted_results = sorted(
        [r for r in results if r.error is None],
        key=lambda r: r.return_score,
        reverse=True,
    )

    horizon_dir = os.path.join(base_dir, analysis_date, horizon)
    top_dir = os.path.join(horizon_dir, "top")
    os.makedirs(top_dir, exist_ok=True)

    # Save top N reports
    for rank, result in enumerate(sorted_results[:top_n], 1):
        ticker_safe = result.ticker.replace(".", "_")
        base_name = f"{rank:02d}_{ticker_safe}_score{result.return_score}"

        en_path = os.path.join(top_dir, f"{base_name}.md")
        with open(en_path, "w", encoding="utf-8") as f:
            f.write(result.report_en)

    # Generate ranking_summary.md (all analyzed stocks, not just top N)
    summary_path = os.path.join(horizon_dir, "ranking_summary.md")
    _write_ranking_summary(sorted_results, top_n, summary_path, horizon, analysis_date)

    # Generate ranking_data.json
    json_path = os.path.join(horizon_dir, "ranking_data.json")
    _write_ranking_json(sorted_results, top_n, json_path, horizon, analysis_date)

    return summary_path


def _write_ranking_summary(
    sorted_results: List[ScanResult],
    top_n: int,
    path: str,
    horizon: str,
    analysis_date: str,
) -> None:
    lines = [
        f"# BORKAI TASE SCAN — {horizon.upper()} HORIZON",
        f"**Date:** {analysis_date}  |  **Stocks analyzed:** {len(sorted_results)}",
        f"**Top {top_n} reports saved in:** `top/`",
        "",
        "| Rank | Ticker | Company | Score | Direction | Conviction | Rec |",
        "|------|--------|---------|-------|-----------|------------|-----|",
    ]
    for rank, r in enumerate(sorted_results, 1):
        marker = " ⭐" if rank <= top_n else ""
        lines.append(
            f"| {rank}{marker} | {r.ticker} | {r.company_name} | {r.return_score} "
            f"| {r.direction.upper()} | {r.conviction.upper()} | {r.invest_recommendation} |"
        )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_ranking_json(
    sorted_results: List[ScanResult],
    top_n: int,
    path: str,
    horizon: str,
    analysis_date: str,
) -> None:
    data = []
    for rank, r in enumerate(sorted_results, 1):
        ticker_safe = r.ticker.replace(".", "_")
        data.append({
            "rank": rank,
            "in_top": rank <= top_n,
            "ticker": r.ticker,
            "company_name": r.company_name,
            "return_score": r.return_score,
            "direction": r.direction,
            "conviction": r.conviction,
            "invest_recommendation": r.invest_recommendation,
            "horizon": horizon,
            "analysis_date": analysis_date,
            "report_file": f"top/{rank:02d}_{ticker_safe}_score{r.return_score}.md" if rank <= top_n else None,
        })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Main scanner loop
# ---------------------------------------------------------------------------

def run_scanner(
    horizons: List[str],
    top_n: int = DEFAULT_TOP_N,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    csv_path: str = DEFAULT_CSV,
    size_filter: Optional[str] = None,
    resume: bool = False,
    no_articles: bool = False,
) -> None:
    analysis_date = str(date.today())
    scan_dir = os.path.join(output_dir, analysis_date)
    os.makedirs(scan_dir, exist_ok=True)
    progress_file = os.path.join(scan_dir, "scan_progress.json")

    config = load_config(market="il")
    if no_articles:
        config.article_fetch_enabled = False
    # Use reduced agent counts and skip sector news in scanner mode (speed + cost)
    config.max_agents = config.scanner_max_agents
    config.min_agents = config.scanner_min_agents
    config.sector_news_enabled = False

    client = openai.OpenAI(api_key=config.openai_api_key)

    stocks = load_tickers(csv_path, size_filter=size_filter)
    progress = load_progress(progress_file) if resume else {}

    # Results per horizon
    horizon_results: Dict[str, List[ScanResult]] = {h: [] for h in horizons}

    # Validation counters
    prefilter_skipped: List[Dict[str, str]] = []  # {ticker, name, reason}

    total = len(stocks)
    for i, stock in enumerate(stocks, 1):
        ticker = stock["ticker"]
        print(f"\n[{i}/{total}] {ticker} — {stock['name']}")

        # Pre-filter: quick data check (no price data, low volume, micro-cap)
        passes, reason = prefilter_stock(ticker)
        if not passes:
            print(f"  SKIP: {reason}")
            prefilter_skipped.append({"ticker": ticker, "name": stock["name"], "reason": reason})
            progress[ticker] = {"status": "filtered", "reason": reason}
            save_progress(progress_file, progress)
            continue

        for horizon in horizons:
            key = f"{ticker}_{horizon}"

            if resume and progress.get(key, {}).get("status") == "done":
                print(f"  RESUME: {horizon} already done — skipping")
                # Reload result from saved data if available
                saved = progress[key].get("result")
                if saved:
                    horizon_results[horizon].append(ScanResult(**saved))
                continue

            print(f"  Analyzing {horizon} horizon...")
            try:
                report_en, result = analyze(
                    ticker=ticker,
                    time_horizon=horizon,
                    market="il",
                    save_report=False,  # Scanner handles saving
                )
                scan_result = ScanResult(
                    ticker=ticker,
                    company_name=result.profile.company_name,
                    horizon=horizon,
                    return_score=result.decision.return_score,
                    direction=result.decision.direction,
                    conviction=result.decision.conviction,
                    invest_recommendation=result.decision.invest_recommendation,
                    report_en=report_en,
                    analysis_date=analysis_date,
                )
                horizon_results[horizon].append(scan_result)
                print(f"    Score: {scan_result.return_score}/100 | {scan_result.direction.upper()} | {scan_result.invest_recommendation}")

                progress[key] = {
                    "status": "done",
                    "result": {
                        "ticker": scan_result.ticker,
                        "company_name": scan_result.company_name,
                        "horizon": scan_result.horizon,
                        "return_score": scan_result.return_score,
                        "direction": scan_result.direction,
                        "conviction": scan_result.conviction,
                        "invest_recommendation": scan_result.invest_recommendation,
                        "report_en": "",  # Don't persist full report in progress file
                        "analysis_date": scan_result.analysis_date,
                    },
                }

            except Exception as e:
                print(f"    ERROR: {e}")
                progress[key] = {"status": "failed", "error": str(e)}
                horizon_results[horizon].append(ScanResult(
                    ticker=ticker,
                    company_name=stock["name"],
                    horizon=horizon,
                    return_score=0,
                    direction="unknown",
                    conviction="unknown",
                    invest_recommendation="N/A",
                    report_en="",
                    analysis_date=analysis_date,
                    error=str(e),
                ))

            save_progress(progress_file, progress)

    # --- Save reports and rankings for each horizon ---
    print("\n" + "=" * 60)
    print("SCAN COMPLETE — Saving top reports...")
    print("=" * 60)

    for horizon in horizons:
        results = horizon_results[horizon]
        successful = [r for r in results if r.error is None]
        failed     = [r for r in results if r.error is not None]
        if not successful:
            print(f"\n{horizon.upper()}: No successful analyses to rank.")
            continue

        print(f"\n{horizon.upper()} horizon — {len(successful)} stocks analyzed:")
        summary_path = save_top_reports(
            results=results,
            top_n=top_n,
            base_dir=output_dir,
            horizon=horizon,
            analysis_date=analysis_date,
            client=client,
            config=config,
        )
        print(f"  Ranking saved to: {summary_path}")

        # Print top 5 to console
        sorted_r = sorted(successful, key=lambda r: r.return_score, reverse=True)
        print(f"  Top 5 ({horizon}):")
        for rank, r in enumerate(sorted_r[:5], 1):
            print(f"    {rank}. {r.ticker:12s} score={r.return_score:3d}  {r.direction.upper():6s}  {r.invest_recommendation}")

    # ── Final validation summary ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("SCAN VALIDATION SUMMARY")
    print("=" * 60)

    # Count analysis results across all horizons (use first horizon as representative)
    first_h = horizons[0]
    first_results  = horizon_results[first_h]
    analyzed_ok    = [r for r in first_results if r.error is None]
    analyzed_err   = [r for r in first_results if r.error is not None]

    print(f"  Stock list (CSV)             : {total} stocks with ticker")
    print(f"  Pre-filter skipped           : {len(prefilter_skipped)}")
    print(f"  Attempted full analysis      : {total - len(prefilter_skipped)}")
    print(f"  Analyzed successfully        : {len(analyzed_ok)}")
    print(f"  Analysis errors              : {len(analyzed_err)}")

    # Pre-filter breakdown by reason
    if prefilter_skipped:
        reason_counts: Dict[str, int] = {}
        for s in prefilter_skipped:
            key = s["reason"]
            reason_counts[key] = reason_counts.get(key, 0) + 1
        print(f"\n  Pre-filter breakdown:")
        for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
            print(f"    [{count:3d}x] {reason}")
        print(f"\n  Pre-filtered stocks (first 10):")
        for s in prefilter_skipped[:10]:
            print(f"    SKIP {s['ticker']:14s} {s['name'][:25]:25s}  → {s['reason']}")
        if len(prefilter_skipped) > 10:
            print(f"    ... and {len(prefilter_skipped)-10} more")

    if analyzed_err:
        print(f"\n  Analysis errors (first 5):")
        for r in analyzed_err[:5]:
            print(f"    FAIL {r.ticker:14s} → {r.error[:60]}")

    print(f"\nAll reports saved under: {os.path.join(output_dir, analysis_date)}/")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Borkai TASE Scanner — scan all Israeli stocks and rank by expected return"
    )
    parser.add_argument(
        "--horizons",
        nargs="+",
        choices=["short", "medium", "long"],
        default=["medium"],
        help="Time horizons to analyze (default: medium)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=DEFAULT_TOP_N,
        help=f"Number of top stocks to save full reports for (default: {DEFAULT_TOP_N})",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Base output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--csv",
        default=DEFAULT_CSV,
        help="Path to TASE stocks CSV (default: borkai/data/tase_stocks.csv)",
    )
    parser.add_argument(
        "--size",
        choices=["large", "mid", "small"],
        default=None,
        help="Filter stocks by market cap bucket (default: all sizes)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a previously interrupted scan (skips already-analyzed stocks)",
    )
    parser.add_argument(
        "--no-articles",
        action="store_true",
        help="Skip online article fetching (faster, lower cost)",
    )

    args = parser.parse_args()

    run_scanner(
        horizons=args.horizons,
        top_n=args.top_n,
        output_dir=args.output_dir,
        csv_path=args.csv,
        size_filter=args.size,
        resume=args.resume,
        no_articles=args.no_articles,
    )


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
