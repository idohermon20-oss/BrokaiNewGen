"""
Borkai Live Scanner — Continuous, Zero-API Engine
==================================================

Scans ALL Israeli TASE stocks on a configurable interval using only
yfinance (no AI, no API calls, no tokens consumed).

Architecture
------------
Every cycle:
  1. Fetch TA-125 index daily return (yfinance)
  2. Batch-download all TASE stocks (yfinance, 32-day OHLCV)
  3. Score each stock: price + volume + momentum + RS vs index + gap + vol
  4. Update StateStore: heat scores, trend streaks, heating/cooling detection
  5. Categorise into 4 buckets
  6. Print dashboard + save ranking markdown

Scoring model (max 12)
----------------------
  price_score      0-3   absolute daily move (|1D%|)
  volume_score     0-3   volume / 20D-avg ratio
  momentum_score   0-2   5D price momentum
  rs_score         0-2   outperformance vs TA-125 (NEW)
  gap_score        0-1   gap open vs prior close
  volatility_score 0-1   realized-vol spike vs 20D baseline
  ─────────────────────
  live_score       0-12  used for ranking and heat

Heat score (0-12)
-----------------
  heat = live_score * 0.6 + prev_score * 0.3 + score_delta * 0.1

  Rewards stocks that are *improving* over multiple cycles, not just
  spiking once. A stock with heat > live_score has been building over time.

Categories (can overlap)
------------------------
  BREAKOUT         price_score ≥ 2 AND volume_score ≥ 2
  EARLY_MOVER      volume_score ≥ 2 AND price_score ≤ 1
  STRONG_MOMENTUM  momentum_score ≥ 2 AND consecutive_up ≥ 2
                   OR momentum_score ≥ 1 AND consecutive_up ≥ 3
  UNUSUAL_ACTIVITY volume_score ≥ 3
                   OR volume_score ≥ 2 AND prev_score ≤ 2 (sudden activity)
"""
from __future__ import annotations

import csv
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import yfinance as yf

from .layer1_fast_scan import Layer1Result, run_layer1
from ..monitor.state_store import StateStore, StockState


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "tase_stocks.csv")
DEFAULT_STATE = "scanner_state.json"
DEFAULT_OUTPUT = "reports/scanner"


@dataclass
class LiveScanConfig:
    csv_path:     str           = DEFAULT_CSV
    state_file:   str           = DEFAULT_STATE
    output_dir:   str           = DEFAULT_OUTPUT
    interval_sec: int           = 300         # seconds between cycles (default 5 min)
    size_filter:  Optional[str] = None        # large | mid | small | None (all)
    min_score:    int           = 2           # skip stocks below this score in output
    top_n:        int           = 20          # top N stocks shown in ranked list
    run_once:     bool          = False       # single scan then exit
    verbose:      bool          = True


# ---------------------------------------------------------------------------
# Enriched result
# ---------------------------------------------------------------------------

@dataclass
class LiveResult:
    """Layer 1 result + RS score + heat + categories."""
    ticker:          str
    name:            str
    sector:          str

    # Component scores
    price_score:     int   = 0
    volume_score:    int   = 0
    momentum_score:  int   = 0
    rs_score:        int   = 0   # relative strength vs TA-125
    gap_score:       int   = 0
    volatility_score:int   = 0
    live_score:      int   = 0   # total (0-12)

    # Heat
    heat_score:      float = 0.0
    score_delta:     float = 0.0  # vs previous cycle
    prev_score:      float = 0.0

    # State / trend
    trend:           str   = "new"    # new | stable | heating | cooling
    consecutive_up:  int   = 0
    consecutive_down:int   = 0

    # Raw metrics
    price_change_1d: Optional[float] = None
    price_change_3d: Optional[float] = None
    price_change_5d: Optional[float] = None
    price_change_7d: Optional[float] = None
    volume_ratio:    Optional[float] = None
    rs_vs_index:     Optional[float] = None   # outperformance % vs TA-125

    # Signals (human-readable)
    signals:    List[str]  = field(default_factory=list)
    categories: List[str]  = field(default_factory=list)


# ---------------------------------------------------------------------------
# Index fetch
# ---------------------------------------------------------------------------

def fetch_index_change(symbol: str = "^TA125") -> float:
    """
    Return the TA-125 index 1-day % change.
    Falls back to 0.0 silently on any error (keeps scanner running without index data).
    """
    try:
        hist = yf.Ticker(symbol).history(period="4d")
        hist = hist.dropna(subset=["Close"])
        if len(hist) >= 2:
            change = float((hist["Close"].iloc[-1] / hist["Close"].iloc[-2] - 1) * 100)
            return round(change, 2)
    except Exception:
        pass
    return 0.0


# ---------------------------------------------------------------------------
# RS scoring
# ---------------------------------------------------------------------------

def _rs_score(
    price_change_1d: Optional[float],
    index_change: float,
) -> Tuple[int, float, Optional[str]]:
    """
    Compute relative-strength score and return (score, rs_pct, signal_text).

    rs_pct = stock_1d% - index_1d%

    Thresholds:
      rs ≥ 4%   → score 2  (strongly outperforming index)
      rs ≥ 1.5% → score 1  (mildly outperforming)
      else       → score 0
    """
    if price_change_1d is None:
        return 0, 0.0, None
    rs = price_change_1d - index_change
    if rs >= 4.0:
        return 2, rs, f"Outperforms TA-125 by {rs:+.1f}%"
    if rs >= 1.5:
        return 1, rs, f"Outperforms TA-125 by {rs:+.1f}%"
    return 0, rs, None


# ---------------------------------------------------------------------------
# Heat score
# ---------------------------------------------------------------------------

def _heat(curr: float, prev: float) -> float:
    """
    Heat score rewards stocks that are improving over consecutive cycles.

    Formula: curr*0.6 + prev*0.3 + delta*0.1

    Interpretation:
      heat > live_score  → stock has been building momentum
      heat < live_score  → recent spike, cooling from a higher level
      heat ≈ live_score  → stable signal
    """
    delta = curr - prev
    return round(curr * 0.6 + prev * 0.3 + delta * 0.1, 1)


# ---------------------------------------------------------------------------
# Categorisation
# ---------------------------------------------------------------------------

def _categorize(
    l1: Layer1Result,
    rs_score: int,
    state: StockState,
) -> List[str]:
    """
    Assign a stock to one or more categories based on its signal profile.
    A stock can belong to multiple categories simultaneously.
    """
    cats: List[str] = []

    # ── BREAKOUT ──────────────────────────────────────────────────────────────
    # Classic price + volume confirmation — the move is real, volume is backing it.
    if l1.price_score >= 2 and l1.volume_score >= 2:
        cats.append("BREAKOUT")

    # ── EARLY MOVER ───────────────────────────────────────────────────────────
    # Volume is surging but price hasn't caught up yet.
    # This is the most predictive early signal — smart money accumulating.
    if l1.volume_score >= 2 and l1.price_score <= 1:
        cats.append("EARLY_MOVER")

    # ── STRONG MOMENTUM ───────────────────────────────────────────────────────
    # Multi-day directional build-up — not a one-session event.
    if l1.momentum_score >= 2 and state.consecutive_up >= 2:
        cats.append("STRONG_MOMENTUM")
    elif l1.momentum_score >= 1 and state.consecutive_up >= 3:
        cats.append("STRONG_MOMENTUM")

    # ── UNUSUAL ACTIVITY ──────────────────────────────────────────────────────
    # Abnormal volume spike, or sudden activity after a quiet period.
    if l1.volume_score >= 3:
        cats.append("UNUSUAL_ACTIVITY")
    elif l1.volume_score >= 2 and state.prev_score <= 2:
        # Low previous score → sudden activity = behaviour change
        cats.append("UNUSUAL_ACTIVITY")

    return cats


# ---------------------------------------------------------------------------
# Enrichment: L1 results + RS + state → LiveResult
# ---------------------------------------------------------------------------

def enrich(
    l1_results: List[Layer1Result],
    state_store: StateStore,
    index_change: float,
) -> List[LiveResult]:
    """
    Build LiveResult objects by combining Layer1 data, RS scoring, and
    the persistent state (heat, trend, streak counters).
    """
    results: List[LiveResult] = []

    for l1 in l1_results:
        if l1.error is not None:
            continue

        state = state_store.get(l1.ticker)
        if state is None:
            # Shouldn't happen after update_from_l1, but guard anyway
            state = StockState(ticker=l1.ticker, name=l1.name, sector=l1.sector)

        # RS score
        rs_sc, rs_pct, rs_sig = _rs_score(l1.price_change_1d, index_change)

        # Signals: start with L1 signals, append RS if non-zero
        signals = list(l1.signals)
        if rs_sig:
            signals.append(rs_sig)

        live_sc = l1.total_score + rs_sc

        # Heat from state (prev_score was set by update_from_l1 before this call)
        heat = _heat(live_sc, state.prev_score)

        # Categories
        cats = _categorize(l1, rs_sc, state)

        results.append(LiveResult(
            ticker          = l1.ticker,
            name            = l1.name,
            sector          = l1.sector,
            price_score     = l1.price_score,
            volume_score    = l1.volume_score,
            momentum_score  = l1.momentum_score,
            rs_score        = rs_sc,
            gap_score       = l1.gap_score,
            volatility_score= l1.volatility_score,
            live_score      = live_sc,
            heat_score      = heat,
            score_delta     = state.score_delta,
            prev_score      = state.prev_score,
            trend           = state.trend,
            consecutive_up  = state.consecutive_up,
            consecutive_down= state.consecutive_down,
            price_change_1d = l1.price_change_1d,
            price_change_3d = l1.price_change_3d,
            price_change_5d = l1.price_change_5d,
            price_change_7d = l1.price_change_7d,
            volume_ratio    = l1.volume_ratio,
            rs_vs_index     = rs_pct,
            signals         = signals,
            categories      = cats,
        ))

    # Sort by live_score desc (heat used as tiebreaker)
    results.sort(key=lambda r: (r.live_score, r.heat_score), reverse=True)
    return results


# ---------------------------------------------------------------------------
# Group by category
# ---------------------------------------------------------------------------

def group_by_category(
    results: List[LiveResult],
    min_score: int = 2,
) -> Dict[str, List[LiveResult]]:
    """
    Return a dict keyed by category name, each value a sorted list of stocks.
    Only stocks with live_score >= min_score are included.
    A stock can appear in multiple categories.
    """
    cats: Dict[str, List[LiveResult]] = {
        "BREAKOUT":        [],
        "EARLY_MOVER":     [],
        "STRONG_MOMENTUM": [],
        "UNUSUAL_ACTIVITY":[],
    }
    for r in results:
        if r.live_score < min_score:
            continue
        for c in r.categories:
            if c in cats:
                cats[c].append(r)
    # Each category sorted by heat_score desc (heat rewards multi-cycle build-up)
    for lst in cats.values():
        lst.sort(key=lambda r: (r.heat_score, r.live_score), reverse=True)
    return cats


# ---------------------------------------------------------------------------
# Console display
# ---------------------------------------------------------------------------

_TREND_ARROW = {
    "heating": "↑↑",
    "stable":  "→ ",
    "cooling": "↓↓",
    "new":     "  ",
}

_CAT_LABEL = {
    "BREAKOUT":         "🔥 BREAKOUT CANDIDATES",
    "EARLY_MOVER":      "📊 EARLY MOVERS",
    "STRONG_MOMENTUM":  "🚀 STRONG MOMENTUM",
    "UNUSUAL_ACTIVITY": "⚡ UNUSUAL ACTIVITY",
}


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "  —  "
    return f"{v:+.1f}%"


def _fmt_vol(v: Optional[float]) -> str:
    if v is None:
        return " — "
    return f"{v:.1f}x"


def display_cycle(
    cycle:        int,
    results:      List[LiveResult],
    categories:   Dict[str, List[LiveResult]],
    index_change: float,
    interval_sec: int,
    state_store:  StateStore,
    top_n:        int = 20,
) -> None:
    """Print the full dashboard for one scan cycle."""
    now = datetime.now().strftime("%H:%M:%S")
    width = 72
    line = "═" * width

    print(f"\n{line}")
    print(f"  BORKAI LIVE SCANNER  │  Cycle {cycle}  │  {now}  │  "
          f"{len(results)} stocks scored")
    print(f"  TA-125: {index_change:+.2f}%  │  "
          f"Next scan in {interval_sec}s")
    print(line)

    # ── Category sections ────────────────────────────────────────────────────
    for cat_key, cat_label in _CAT_LABEL.items():
        members = categories.get(cat_key, [])
        if not members:
            print(f"\n{cat_label}  (none)")
            continue
        print(f"\n{cat_label}  ({len(members)} stocks)")
        print(f"  {'Ticker':<10} {'Score':>5} {'Heat':>6} {'Trend':>5} "
              f"{'1D%':>7} {'Vol':>5}  Signals")
        print(f"  {'-'*10} {'-'*5} {'-'*6} {'-'*5} {'-'*7} {'-'*5}  {'-'*25}")
        for r in members[:8]:
            arrow = _TREND_ARROW.get(r.trend, "  ")
            delta_str = f"({r.score_delta:+.0f})" if r.score_delta != 0 else "    "
            sigs = "; ".join(r.signals[:2]) or "—"
            print(
                f"  {r.ticker:<10} {r.live_score:>5} {r.heat_score:>6.1f} "
                f"{arrow:>2}{delta_str:>5} "
                f"{_fmt_pct(r.price_change_1d):>7} "
                f"{_fmt_vol(r.volume_ratio):>5}  {sigs}"
            )

    # ── Top N overall ────────────────────────────────────────────────────────
    print(f"\n{'─'*width}")
    print(f"  TOP {top_n} OVERALL (by live score):")
    print(f"  {'#':>2} {'Ticker':<10} {'Score':>5} {'Heat':>6} {'1D%':>7} "
          f"{'3D%':>7} {'Vol':>5} {'Cats'}")
    print(f"  {'─'*2} {'─'*10} {'─'*5} {'─'*6} {'─'*7} {'─'*7} {'─'*5} {'─'*20}")
    for i, r in enumerate(results[:top_n], 1):
        cat_str = ",".join(c[:3] for c in r.categories) or "—"
        print(
            f"  {i:>2} {r.ticker:<10} {r.live_score:>5} {r.heat_score:>6.1f} "
            f"{_fmt_pct(r.price_change_1d):>7} "
            f"{_fmt_pct(r.price_change_3d):>7} "
            f"{_fmt_vol(r.volume_ratio):>5} "
            f"{cat_str}"
        )

    # ── Newly heating ────────────────────────────────────────────────────────
    heating = [r for r in results if r.trend == "heating" and r.live_score >= 3]
    if heating:
        print(f"\n  HEATING UP: " + ", ".join(
            f"{r.ticker}({r.live_score}↑)" for r in heating[:8]
        ))
    cooling = [r for r in results if r.trend == "cooling" and r.prev_score >= 4]
    if cooling:
        print(f"  COOLING DOWN: " + ", ".join(
            f"{r.ticker}({r.live_score}↓)" for r in cooling[:5]
        ))

    print(line)


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def save_ranking(
    cycle:      int,
    results:    List[LiveResult],
    categories: Dict[str, List[LiveResult]],
    output_dir: str,
    index_change: float,
) -> None:
    """Write current_ranking.md (overwritten each cycle)."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "current_ranking.md")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# BORKAI LIVE SCANNER — CURRENT RANKING",
        f"**Updated:** {now}  |  **Cycle:** {cycle}  |  **TA-125:** {index_change:+.2f}%",
        "",
    ]

    # Category sections
    for cat_key, cat_label in _CAT_LABEL.items():
        members = categories.get(cat_key, [])
        label = cat_label.replace("🔥 ","").replace("📊 ","").replace("🚀 ","").replace("⚡ ","")
        lines += [f"## {label} ({len(members)})", ""]
        if not members:
            lines.append("_No stocks in this category this cycle._")
            lines.append("")
            continue
        lines += [
            "| Ticker | Score | Heat | Trend | 1D% | 3D% | Vol | Signals |",
            "|--------|:-----:|:----:|:-----:|:---:|:---:|:---:|---------|",
        ]
        for r in members[:10]:
            arrow = {"heating":"↑↑","stable":"→","cooling":"↓↓","new":"new"}.get(r.trend, "")
            delta = f" ({r.score_delta:+.0f})" if r.score_delta else ""
            sigs = "; ".join(r.signals[:2]) or "—"
            lines.append(
                f"| **{r.ticker}** | {r.live_score} | {r.heat_score:.1f} "
                f"| {arrow}{delta} | {_fmt_pct(r.price_change_1d)} "
                f"| {_fmt_pct(r.price_change_3d)} "
                f"| {_fmt_vol(r.volume_ratio)} | {sigs} |"
            )
        lines.append("")

    # Overall top 20
    lines += [
        "## Top 20 Overall",
        "",
        "| # | Ticker | Name | Score | Heat | 1D% | 3D% | 5D% | 7D% | Vol | Categories |",
        "|---|--------|------|:-----:|:----:|:---:|:---:|:---:|:---:|:---:|------------|",
    ]
    for i, r in enumerate(results[:20], 1):
        cats = ", ".join(r.categories) or "—"
        lines.append(
            f"| {i} | **{r.ticker}** | {r.name[:22]} | {r.live_score} "
            f"| {r.heat_score:.1f} "
            f"| {_fmt_pct(r.price_change_1d)} "
            f"| {_fmt_pct(r.price_change_3d)} "
            f"| {_fmt_pct(r.price_change_5d)} "
            f"| {_fmt_pct(r.price_change_7d)} "
            f"| {_fmt_vol(r.volume_ratio)} | {cats} |"
        )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# CSV loader
# ---------------------------------------------------------------------------

def _load_stocks(csv_path: str, size_filter: Optional[str] = None) -> List[dict]:
    stocks: List[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "").strip()
            if not ticker:
                continue
            if size_filter:
                if row.get("market_cap_bucket", "").lower() != size_filter.lower():
                    continue
            if not ticker.endswith(".TA"):
                ticker += ".TA"
            name_en = row.get("name_en", "").strip()
            name_he = row.get("name_he", "").strip()
            stocks.append({
                "ticker":           ticker,
                "name":             name_en or name_he or ticker,
                "sector":           row.get("sector", "Unknown"),
                "market_cap_bucket":row.get("market_cap_bucket", ""),
                "name_he":          name_he,
            })
    return stocks


def _load_stocks_with_skipped(
    csv_path: str,
    size_filter: Optional[str] = None,
) -> Tuple[List[dict], List[dict]]:
    """
    Load stocks from CSV, returning (scannable, skipped).
    skipped includes rows with no ticker and rows filtered by size.
    """
    scannable: List[dict] = []
    skipped:   List[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker  = row.get("ticker", "").strip()
            name_en = row.get("name_en", "").strip()
            name_he = row.get("name_he", "").strip()
            display = name_en or name_he or ticker or "unknown"

            sec_num = row.get("security_number", "").strip()

            if not ticker:
                skipped.append({"ticker": "", "name": display,
                                 "security_number": sec_num, "reason": "no ticker"})
                continue

            if size_filter:
                bucket = row.get("market_cap_bucket", "").lower()
                if bucket and bucket != size_filter.lower():
                    skipped.append({"ticker": ticker, "name": display,
                                    "security_number": sec_num,
                                    "reason": f"size filter ({bucket})"})
                    continue

            if not ticker.endswith(".TA"):
                ticker += ".TA"
            scannable.append({
                "ticker":           ticker,
                "name":             display,
                "sector":           row.get("sector", "Unknown"),
                "market_cap_bucket":row.get("market_cap_bucket", ""),
                "name_he":          name_he,
            })
    return scannable, skipped


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_live_scan(cfg: LiveScanConfig) -> None:
    """
    Run the continuous no-API scanner. Stops on Ctrl+C.

    Each cycle:
      1. Fetch TA-125 index return (yfinance, ~1 call)
      2. Batch-download all stocks (yfinance, ~2-3 calls for 100 stocks)
      3. Score each stock (pure math, no API)
      4. Update state store (heat, trends, streaks)
      5. Categorise and display
      6. Save ranking markdown
      7. Sleep until next cycle
    """
    csv_path = os.path.abspath(cfg.csv_path)
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Stocks CSV not found: {csv_path}")

    stocks = _load_stocks(csv_path, cfg.size_filter)
    if not stocks:
        print("[SCANNER] ERROR: no stocks loaded. Check CSV path / size filter.")
        return

    os.makedirs(cfg.output_dir, exist_ok=True)
    state_store = StateStore(cfg.state_file)

    size_label = f" ({cfg.size_filter})" if cfg.size_filter else ""
    print(f"\n{'═'*72}")
    print(f"  BORKAI LIVE SCANNER — zero API, pure yfinance{size_label}")
    print(f"  Universe: {len(stocks)} stocks  │  Interval: {cfg.interval_sec}s")
    print(f"  State: {cfg.state_file}  │  Output: {cfg.output_dir}")
    print(f"{'═'*72}\n")

    cycle = 0

    while True:
        cycle += 1
        t_start = time.time()

        print(f"[SCANNER] Cycle {cycle} — {datetime.now().strftime('%H:%M:%S')} — "
              f"fetching {len(stocks)} stocks...")

        # ── Step 1: index change ─────────────────────────────────────────────
        index_change = fetch_index_change()
        if cfg.verbose:
            print(f"[SCANNER] TA-125: {index_change:+.2f}%")

        # ── Step 2: Layer 1 scan ─────────────────────────────────────────────
        l1_results = run_layer1(stocks, verbose=cfg.verbose)

        # ── Step 3: update state (score deltas, trends, streaks) ─────────────
        state_store.update_from_l1(l1_results)

        # ── Step 4: enrich with RS + heat + categories ───────────────────────
        live_results = enrich(l1_results, state_store, index_change)

        # ── Step 5: group by category ─────────────────────────────────────────
        categories = group_by_category(live_results, min_score=cfg.min_score)

        # ── Step 6: display ───────────────────────────────────────────────────
        display_cycle(
            cycle=cycle,
            results=live_results,
            categories=categories,
            index_change=index_change,
            interval_sec=cfg.interval_sec,
            state_store=state_store,
            top_n=cfg.top_n,
        )

        # ── Step 7: save markdown ─────────────────────────────────────────────
        save_ranking(cycle, live_results, categories, cfg.output_dir, index_change)

        state_store.save()

        # ── Done ──────────────────────────────────────────────────────────────
        elapsed = time.time() - t_start
        print(f"[SCANNER] Cycle {cycle} done in {elapsed:.0f}s. "
              f"Ranking → {cfg.output_dir}/current_ranking.md")

        if cfg.run_once:
            print("[SCANNER] --once flag set, exiting.")
            break

        sleep_sec = max(0.0, cfg.interval_sec - elapsed)
        if sleep_sec > 0:
            print(f"[SCANNER] Next scan in {sleep_sec:.0f}s ...")
            time.sleep(sleep_sec)
