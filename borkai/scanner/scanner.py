"""
Smart Scanner Orchestrator
==========================

Coordinates Layer 1 → Layer 2 → Layer 3 and produces the final ranked output.

Flow:
  1. Load TASE universe from CSV
  2. Layer 1  : fast yfinance scan of ALL stocks   (~30-90s for 100 stocks)
  3. Layer 2  : light AI filter on top L1 stocks   (~60-120s for 30 stocks)
  4. Layer 3  : full Borkai analysis on top L2 only (~5-10 min for 5-10 stocks)

Usage (as a library):
    from borkai.scanner import run_smart_scan
    result = run_smart_scan(top_l1=30, top_l2=10, top_l3=5, horizon="short")
"""
from __future__ import annotations

import csv
import json
import os
import sys
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Dict

import openai

from ..config import load_config, Config
from .layer1_fast_scan import Layer1Result, run_layer1
from .layer2_filter import Layer2Result, run_layer2


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class DeepAnalysisResult:
    ticker: str
    name: str
    return_score: int
    direction: str
    conviction: str
    invest_recommendation: str
    report_en: str
    error: Optional[str] = None


@dataclass
class SmartScanResult:
    scan_date: str
    horizon: str
    total_stocks_scanned: int

    layer1_results: List[Layer1Result] = field(default_factory=list)
    layer2_results: List[Layer2Result] = field(default_factory=list)
    deep_results: List[DeepAnalysisResult] = field(default_factory=list)

    output_dir: Optional[str] = None


# ---------------------------------------------------------------------------
# CSV loader
# ---------------------------------------------------------------------------

DEFAULT_CSV = os.path.join(
    os.path.dirname(__file__), "..", "data", "tase_stocks.csv"
)


def _load_stocks(csv_path: str, size_filter: Optional[str] = None) -> tuple:
    """
    Load all stocks from CSV.  Returns (scannable, skipped) where:
      scannable — stocks with a ticker (can be processed by yfinance)
      skipped   — list of dicts {name_he, security_number, reason} for no-ticker rows
    Applies size_filter only to scannable stocks.
    """
    scannable: List[dict] = []
    skipped: List[dict] = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker   = row.get("ticker", "").strip()
            name_he  = row.get("name_he", "").strip()
            name_en  = row.get("name_en", "").strip()
            sec_num  = row.get("security_number", "").strip()
            display  = name_en or name_he or ticker or "unknown"

            if not ticker:
                skipped.append({
                    "name": display,
                    "name_he": name_he,
                    "security_number": sec_num,
                    "reason": "no ticker in CSV",
                })
                continue

            if size_filter:
                bucket = row.get("market_cap_bucket", "").lower()
                if bucket and bucket != size_filter.lower():
                    # Skip silently — user applied an explicit size filter
                    continue

            if not ticker.endswith(".TA"):
                ticker += ".TA"

            scannable.append({
                "ticker": ticker,
                "name": display,
                "sector": row.get("sector", "Unknown"),
                "market_cap_bucket": row.get("market_cap_bucket", ""),
                "name_he": name_he,
                "security_number": sec_num,
            })

    return scannable, skipped


# ---------------------------------------------------------------------------
# Layer 3: full deep analysis (uses existing analyze() function)
# ---------------------------------------------------------------------------

def _run_layer3(
    candidates: List[Layer2Result],
    top_n: int,
    horizon: str,
    config: Config,
    client: openai.OpenAI,
    no_articles: bool = False,
    verbose: bool = True,
) -> List[DeepAnalysisResult]:
    """Run full Borkai analysis on the top Layer 2 candidates."""
    # Import here to avoid circular deps (main.py imports borkai modules)
    _root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from main import analyze  # type: ignore

    deep_candidates = [c for c in candidates if c.recommendation == "DEEP_ANALYSIS"]
    # If not enough DEEP_ANALYSIS, fill with best WATCH candidates
    if len(deep_candidates) < top_n:
        watch = [c for c in candidates if c.recommendation == "WATCH"]
        deep_candidates += watch[: top_n - len(deep_candidates)]
    deep_candidates = deep_candidates[:top_n]

    if not deep_candidates:
        if verbose:
            print("[L3] No candidates to analyze.")
        return []

    if verbose:
        print(f"\n[L3] Running deep analysis on {len(deep_candidates)} stocks...")

    # Temporarily adjust config for scanner mode
    config.max_agents = config.scanner_max_agents
    config.min_agents = config.scanner_min_agents
    config.sector_news_enabled = False
    if no_articles:
        config.article_fetch_enabled = False

    results: List[DeepAnalysisResult] = []
    for i, c in enumerate(deep_candidates, 1):
        if verbose:
            print(f"\n  [L3] {i}/{len(deep_candidates)}: {c.ticker} — {c.name}")
        try:
            report_en, analysis_result = analyze(
                ticker=c.ticker,
                time_horizon=horizon,
                market="il",
                save_report=False,
            )
            d = analysis_result.decision
            results.append(DeepAnalysisResult(
                ticker=c.ticker,
                name=c.name,
                return_score=d.return_score,
                direction=d.direction,
                conviction=d.conviction,
                invest_recommendation=d.invest_recommendation,
                report_en=report_en,
            ))
            if verbose:
                print(f"    Score: {d.return_score}/100 | {d.direction.upper()} | {d.invest_recommendation}")
        except Exception as e:
            if verbose:
                print(f"    ERROR: {e}")
            results.append(DeepAnalysisResult(
                ticker=c.ticker,
                name=c.name,
                return_score=0,
                direction="unknown",
                conviction="unknown",
                invest_recommendation="N/A",
                report_en="",
                error=str(e),
            ))

    results.sort(key=lambda r: r.return_score, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _save_layer1_report(
    results: List[Layer1Result],
    path: str,
    skipped_no_ticker: Optional[List[dict]] = None,
) -> None:
    valid  = [r for r in results if r.error is None]
    errors = [r for r in results if r.error is not None]
    skipped_no_ticker = skipped_no_ticker or []

    lines = [
        "# SMART SCAN — LAYER 1 RESULTS",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Universe Validation",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total stocks in CSV | {len(valid) + len(errors) + len(skipped_no_ticker)} |",
        f"| Scanned successfully | {len(valid)} |",
        f"| Scan errors (yfinance) | {len(errors)} |",
        f"| Skipped — no ticker in CSV | {len(skipped_no_ticker)} |",
        "",
    ]

    # All scored stocks — no truncation
    lines += [
        "## All Stocks — Ranked by Layer 1 Score",
        "",
        "| # | Ticker | Name | Score | Price 1D | Vol Ratio | 5D Mom | Key Signals |",
        "|---|--------|------|:-----:|:--------:|:---------:|:------:|-------------|",
    ]
    for i, r in enumerate(valid, 1):
        p1d  = f"{r.price_change_1d:+.1f}%" if r.price_change_1d is not None else "—"
        vol  = f"{r.volume_ratio:.1f}x"     if r.volume_ratio is not None    else "—"
        m5d  = f"{r.price_change_5d:+.1f}%" if r.price_change_5d is not None else "—"
        sigs = "; ".join(r.signals[:3]) or "—"
        lines.append(
            f"| {i} | {r.ticker} | {r.name[:25]} | **{r.total_score}** "
            f"| {p1d} | {vol} | {m5d} | {sigs} |"
        )

    # Error stocks
    if errors:
        lines += ["", "## Scan Errors", "", "| Ticker | Name | Error |", "|--------|------|-------|"]
        for r in errors:
            lines.append(f"| {r.ticker} | {r.name[:25]} | {r.error} |")

    # No-ticker stocks
    if skipped_no_ticker:
        lines += ["", "## Skipped — No Ticker", "", "| Name | Security # | Reason |", "|------|------------|--------|"]
        for s in skipped_no_ticker:
            lines.append(f"| {s['name'][:30]} | {s.get('security_number','')} | {s['reason']} |")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _save_layer2_report(results: List[Layer2Result], path: str) -> None:
    lines = [
        "# SMART SCAN — LAYER 2 RESULTS",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  "
        f"**Candidates filtered:** {len(results)}",
        "",
        "| # | Ticker | L1 | L2 | Total | Event | Impact | Sentiment | Alignment | Rec |",
        "|---|--------|:--:|:--:|:-----:|-------|:------:|:---------:|:---------:|-----|",
    ]
    for i, r in enumerate(results, 1):
        event_label = r.event_type.replace("_", " ").title() if r.event_detected else "—"
        lines.append(
            f"| {i} | **{r.ticker}** | {r.layer1_score} | {r.layer2_score} | **{r.combined_score}** "
            f"| {event_label} | {r.event_impact} | {r.sentiment} | {r.alignment} | {r.recommendation} |"
        )
        if r.llm_reasoning:
            lines.append(f"|   | | | | | _{r.llm_reasoning}_ | | | | |")

    lines += ["", "---", "", "## Candidate Details", ""]
    for r in results:
        if r.recommendation == "SKIP":
            continue
        rec_icon = "🟢" if r.recommendation == "DEEP_ANALYSIS" else "🟡"
        lines += [
            f"### {rec_icon} {r.ticker} — {r.name}  (Score: {r.combined_score})",
            "",
            f"**Recommendation:** {r.recommendation}  |  **Sector:** {r.sector}",
            "",
            f"**Signals:**",
        ]
        for sig in r.all_signals:
            lines.append(f"- {sig}")
        if r.recent_headlines:
            lines.append("")
            lines.append("**Recent headlines:**")
            for h in r.recent_headlines[:3]:
                lines.append(f"- {h}")
        if r.llm_reasoning:
            lines += ["", f"> {r.llm_reasoning}"]
        lines.append("")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _save_deep_reports(
    deep_results: List[DeepAnalysisResult],
    l2_map: Dict[str, Layer2Result],
    scan_dir: str,
    horizon: str,
    top_n: int,
) -> str:
    """Save individual deep reports and a combined ranking."""
    deep_dir = os.path.join(scan_dir, "deep")
    os.makedirs(deep_dir, exist_ok=True)

    successful = [r for r in deep_results if r.error is None]
    successful.sort(key=lambda r: r.return_score, reverse=True)

    # Save individual reports
    for rank, dr in enumerate(successful[:top_n], 1):
        ticker_safe = dr.ticker.replace(".", "_")
        fname = f"{rank:02d}_{ticker_safe}_score{dr.return_score}.md"
        fpath = os.path.join(deep_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(dr.report_en)

    # Summary ranking
    lines = [
        f"# SMART SCAN — DEEP ANALYSIS RESULTS ({horizon.upper()})",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "| Rank | Ticker | Name | Score | Direction | Conviction | Rec |",
        "|------|--------|------|:-----:|:---------:|:----------:|-----|",
    ]
    for rank, dr in enumerate(successful, 1):
        l2 = l2_map.get(dr.ticker)
        l2_note = f"L1:{l2.layer1_score} L2:{l2.layer2_score}" if l2 else ""
        lines.append(
            f"| {rank} | **{dr.ticker}** | {dr.name[:20]} | {dr.return_score} "
            f"| {dr.direction.upper()} | {dr.conviction.upper()} | {dr.invest_recommendation} | {l2_note} |"
        )

    summary_path = os.path.join(scan_dir, f"ranking_{horizon}.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return summary_path


def _print_scan_summary(result: SmartScanResult) -> None:
    """Print a compact console summary of the scan."""
    print("\n" + "=" * 60)
    print(f"SMART SCAN COMPLETE — {result.scan_date}  [{result.horizon.upper()}]")
    print("=" * 60)

    # Layer 1 top 10
    valid_l1  = [r for r in result.layer1_results if r.error is None]
    error_l1  = [r for r in result.layer1_results if r.error is not None]
    print(f"\nLAYER 1 — Top 10 of {len(valid_l1)} scored stocks (universe: {result.total_stocks_scanned} with ticker):")
    print(f"  {'Ticker':<12} {'Score':>5}  {'1D%':>6}  {'Vol':>5}  Signals")
    print(f"  {'-'*12} {'-'*5}  {'-'*6}  {'-'*5}  {'-'*30}")
    for r in valid_l1[:10]:
        p1d = f"{r.price_change_1d:+.1f}%" if r.price_change_1d is not None else "  —  "
        vol = f"{r.volume_ratio:.1f}x" if r.volume_ratio is not None else "  — "
        sigs = "; ".join(r.signals[:2]) or "—"
        print(f"  {r.ticker:<12} {r.total_score:>5}  {p1d:>6}  {vol:>5}  {sigs}")

    # Layer 2 summary
    if result.layer2_results:
        deep = [r for r in result.layer2_results if r.recommendation == "DEEP_ANALYSIS"]
        watch = [r for r in result.layer2_results if r.recommendation == "WATCH"]
        print(f"\nLAYER 2 — {len(deep)} DEEP_ANALYSIS, {len(watch)} WATCH:")
        for r in result.layer2_results[:10]:
            icon = "=>" if r.recommendation == "DEEP_ANALYSIS" else "  "
            evt = f"[{r.event_type}|{r.event_impact}]" if r.event_detected else ""
            print(f"  {icon} {r.ticker:<12} combined={r.combined_score}  {evt}  {r.sentiment}  {r.alignment}")

    # Layer 3 summary
    if result.deep_results:
        print(f"\nLAYER 3 — Deep Analysis Rankings:")
        for rank, dr in enumerate([r for r in result.deep_results if r.error is None][:10], 1):
            print(f"  {rank}. {dr.ticker:<12} score={dr.return_score:>3}  "
                  f"{dr.direction.upper():<5}  {dr.invest_recommendation}")

    if result.output_dir:
        print(f"\nOutput saved to: {result.output_dir}")
    print()


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def run_smart_scan(
    horizon: str = "short",
    top_l1: int = 30,
    top_l2: int = 10,
    top_l3: int = 5,
    csv_path: str = DEFAULT_CSV,
    output_dir: str = "reports",
    size_filter: Optional[str] = None,
    run_deep: bool = True,
    no_articles: bool = False,
    verbose: bool = True,
) -> SmartScanResult:
    """
    Run the full 3-layer smart scan.

    Args:
        horizon:     Time horizon for deep analysis: short / medium / long
        top_l1:      How many top Layer 1 stocks pass to Layer 2
        top_l2:      How many top Layer 2 stocks trigger deep analysis
        top_l3:      Max deep analysis reports to save
        csv_path:    TASE stocks CSV
        output_dir:  Base folder for all output files
        size_filter: Filter stocks by market_cap_bucket: large/mid/small/None
        run_deep:    Run Layer 3 deep analysis (expensive)
        no_articles: Skip article fetching in Layer 3 (faster)
        verbose:     Print progress

    Returns:
        SmartScanResult with all layer results.
    """
    scan_date = str(date.today())
    scan_dir = os.path.join(output_dir, scan_date, f"smart_{horizon}")
    os.makedirs(scan_dir, exist_ok=True)

    config = load_config(market="il")
    client = openai.OpenAI(api_key=config.openai_api_key)

    # ── Load universe ───────────────────────────────────────────────────────
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Stocks CSV not found: {csv_path}")

    stocks, skipped_no_ticker = _load_stocks(csv_path, size_filter)
    total_in_csv = len(stocks) + len(skipped_no_ticker)

    if verbose:
        size_label = f" ({size_filter})" if size_filter else ""
        print(f"\n{'='*60}")
        print(f"BORKAI SMART SCAN — {horizon.upper()} HORIZON{size_label}")
        print(f"{'='*60}")
        print(f"\nUNIVERSE VALIDATION:")
        print(f"  Total stocks in CSV         : {total_in_csv}")
        print(f"  Scannable (have ticker)     : {len(stocks)}")
        if skipped_no_ticker:
            print(f"  Skipped (no ticker)         : {len(skipped_no_ticker)}")
            for s in skipped_no_ticker[:5]:
                print(f"    - {s['name']} [{s.get('security_number','')}]")
            if len(skipped_no_ticker) > 5:
                print(f"    ... and {len(skipped_no_ticker)-5} more")
        if size_filter:
            print(f"  Size filter applied         : {size_filter.upper()} caps only")
        print(f"\n  Funnel: L1({len(stocks)}) -> L2(top {top_l1}) -> L3(top {top_l2}) -> Reports(top {top_l3})")
        print(f"  Output: {scan_dir}")

    result = SmartScanResult(
        scan_date=scan_date,
        horizon=horizon,
        total_stocks_scanned=len(stocks),
        output_dir=scan_dir,
    )

    # ── LAYER 1: Fast scan ──────────────────────────────────────────────────
    if verbose:
        print(f"\n{'─'*60}")
        print("LAYER 1: Fast Market Scan")
        print(f"{'─'*60}")

    l1_results = run_layer1(stocks, verbose=verbose)
    result.layer1_results = l1_results

    # Print Layer 1 validation summary
    l1_valid  = [r for r in l1_results if r.error is None]
    l1_errors = [r for r in l1_results if r.error is not None]
    if verbose:
        print(f"\n[L1] SCAN VALIDATION SUMMARY:")
        print(f"  Total in CSV             : {total_in_csv}")
        print(f"  Attempted (have ticker)  : {len(stocks)}")
        print(f"  Scored successfully      : {len(l1_valid)}")
        print(f"  Scan errors              : {len(l1_errors)}")
        print(f"  Skipped (no ticker)      : {len(skipped_no_ticker)}")
        if l1_errors:
            # Group by error reason
            reason_counts: Dict[str, int] = {}
            for r in l1_errors:
                key = r.error or "unknown"
                reason_counts[key] = reason_counts.get(key, 0) + 1
            print(f"  Error breakdown:")
            for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1])[:8]:
                print(f"    [{count:3d}x] {reason[:60]}")

    # Save Layer 1 report — all stocks, no truncation
    l1_report_path = os.path.join(scan_dir, "layer1_scan.md")
    _save_layer1_report(l1_results, l1_report_path, skipped_no_ticker=skipped_no_ticker)
    if verbose:
        print(f"[L1] Full report saved: {l1_report_path}  ({len(l1_valid)} stocks ranked)")

    # Build Hebrew name map for Layer 2 (helps DDG/Maya searches)
    name_he_map = {}
    for s in stocks:
        ticker_clean = s["ticker"].replace(".TA", "").upper()
        if s.get("name_he"):
            name_he_map[ticker_clean] = s["name_he"]

    # ── LAYER 2: Smart filter ───────────────────────────────────────────────
    if verbose:
        print(f"\n{'─'*60}")
        print(f"LAYER 2: Smart Filtering (top {top_l1} from Layer 1)")
        print(f"{'─'*60}")

    l2_results = run_layer2(
        layer1_results=l1_results,
        client=client,
        top_n=top_l1,
        model=config.models.agent,   # gpt-4o-mini
        name_he_map=name_he_map,
        verbose=verbose,
    )
    result.layer2_results = l2_results

    # Save Layer 2 report
    l2_report_path = os.path.join(scan_dir, "layer2_filter.md")
    _save_layer2_report(l2_results, l2_report_path)
    if verbose:
        print(f"[L2] Report saved: {l2_report_path}")

    # ── LAYER 3: Deep analysis ──────────────────────────────────────────────
    if run_deep:
        if verbose:
            print(f"\n{'─'*60}")
            print(f"LAYER 3: Deep Analysis (top {top_l2} from Layer 2)")
            print(f"{'─'*60}")

        # Select top_l2 candidates for deep analysis
        top_l2_candidates = l2_results[:top_l2]
        deep_results = _run_layer3(
            top_l2_candidates, top_l3, horizon, config, client,
            no_articles=no_articles, verbose=verbose,
        )
        result.deep_results = deep_results

        # Save deep reports
        l2_map = {r.ticker: r for r in l2_results}
        summary_path = _save_deep_reports(deep_results, l2_map, scan_dir, horizon, top_l3)
        if verbose:
            print(f"[L3] Ranking saved: {summary_path}")
    else:
        if verbose:
            print("\n[L3] Deep analysis skipped (--no-deep flag)")

    # ── Print summary ───────────────────────────────────────────────────────
    _print_scan_summary(result)

    return result
