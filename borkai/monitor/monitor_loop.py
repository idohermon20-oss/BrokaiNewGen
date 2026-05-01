"""
Borkai Continuous Monitor — Main Loop
======================================

Orchestrates three layers continuously:

  EVERY CYCLE (default: every 5 min):
    1. Layer 1 fast scan  — yfinance batch, all TASE stocks, no AI
    2. Update state store — score deltas, trends, streak counters
    3. Rank candidates    — composite score + state bonuses
    4. Check L3 triggers  — per-stock cooldown + threshold rules

  EVERY N CYCLES (default: every 6 = ~30 min):
    5. Layer 2 filter     — DDG headlines + Maya count + GPT-4o-mini batch
    6. Update state store — new filings detected, news change hashes, buckets

  ON TRIGGER:
    7. Layer 3 deep       — full Borkai analyze() on qualified candidates only
    8. Save deep report   — dated output directory
    9. Update state store — last_deep_at, last_deep_score, reset change flags

  END OF EVERY CYCLE:
    10. Print dashboard   — ranked table, buckets, triggers, recent deep results
    11. Save state        — atomic JSON write
    12. Sleep             — until next cycle
"""
from __future__ import annotations

import csv
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

import openai

from ..config import load_config
from ..scanner.layer1_fast_scan import run_layer1
from ..scanner.layer2_filter import run_layer2
from .state_store import StateStore
from .candidate_ranker import rank_candidates
from .deep_trigger import TriggerConfig, get_trigger_candidates
from .dashboard import print_cycle, print_startup


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class MonitorConfig:
    """All runtime parameters for the continuous monitor."""

    # Scan intervals
    interval_sec: int = 300       # seconds between L1 scans (default: 5 min)
    l2_every: int = 6             # run L2 every N L1 cycles (default: 30 min)

    # Universe
    csv_path: str = ""            # path to tase_stocks.csv
    size_filter: Optional[str] = None  # large | mid | small | None (all)

    # Funnel widths
    top_l1: int = 30              # top L1 stocks passed to L2
    top_candidates: int = 50      # total ranked candidates to track

    # Deep analysis
    horizon: str = "short"
    no_articles: bool = False
    max_deep_per_cycle: int = 2

    # Trigger thresholds
    score_threshold: float = 7.0
    hard_cooldown_hours: float = 1.5
    soft_cooldown_hours: float = 4.0
    volume_spike_ratio: float = 3.0
    price_spike_pct: float = 5.0
    score_delta_threshold: float = 2.5

    # Output
    output_dir: str = "reports/monitor"
    state_file: str = "monitor_state.json"

    # Misc
    verbose: bool = True


# ---------------------------------------------------------------------------
# Universe loader
# ---------------------------------------------------------------------------

def _load_stocks(csv_path: str, size_filter: Optional[str] = None) -> List[dict]:
    stocks = []
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
            stocks.append({
                "ticker": ticker,
                "name": row.get("name", ticker),
                "sector": row.get("sector", "Unknown"),
                "market_cap_bucket": row.get("market_cap_bucket", ""),
                "name_he": row.get("name_he", ""),
            })
    return stocks


# ---------------------------------------------------------------------------
# Deep analysis runner (Layer 3)
# ---------------------------------------------------------------------------

def _run_deep(
    ticker: str,
    horizon: str,
    config,
    output_dir: str,
    no_articles: bool = False,
) -> Optional[dict]:
    """
    Run full Borkai analyze() on one stock.
    Returns a dict with score/direction/rec, or None on error.
    """
    _root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    try:
        from main import analyze  # type: ignore

        # Use scanner-mode agent counts (4-7 agents, no sector news)
        config.max_agents = config.scanner_max_agents
        config.min_agents = config.scanner_min_agents
        config.sector_news_enabled = False
        if no_articles:
            config.article_fetch_enabled = False

        report_en, analysis_result = analyze(
            ticker=ticker,
            time_horizon=horizon,
            market="il",
            save_report=False,
        )

        d = analysis_result.decision
        result = {
            "score": d.return_score,
            "direction": d.direction,
            "rec": d.invest_recommendation,
            "conviction": d.conviction,
        }

        # Save report to output dir
        scan_date = datetime.now().strftime("%Y-%m-%d")
        deep_dir = os.path.join(output_dir, scan_date, "deep")
        os.makedirs(deep_dir, exist_ok=True)
        ticker_safe = ticker.replace(".", "_")
        fname = f"{ticker_safe}_{datetime.now().strftime('%H%M')}_score{d.return_score}.md"
        with open(os.path.join(deep_dir, fname), "w", encoding="utf-8") as f:
            f.write(report_en)

        print(f"    [L3] {ticker}: score={d.return_score} | {d.direction.upper()} | {d.invest_recommendation}")
        return result

    except Exception as e:
        print(f"    [L3] ERROR analyzing {ticker}: {e}")
        return None


# ---------------------------------------------------------------------------
# Ranking output file
# ---------------------------------------------------------------------------

def _save_ranking(ranked, state_store: StateStore, output_dir: str) -> None:
    """Write the current ranking to a markdown file (overwritten each cycle)."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "current_ranking.md")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# BORKAI MONITOR — CURRENT RANKING",
        f"**Updated:** {now}  |  **Stocks tracked:** {len(ranked)}",
        "",
        "| # | Ticker | Score | L1 | Delta | Trend | Bucket | Vol | 1D% | Flags | Signals |",
        "|---|--------|:-----:|:--:|:-----:|:-----:|:------:|:---:|:---:|-------|---------|",
    ]
    for i, c in enumerate(ranked[:30], 1):
        delta_str = f"{c.score_delta:+.1f}" if c.score_delta else "0"
        vol_str = f"{c.volume_ratio:.1f}x" if c.volume_ratio > 0 else "—"
        price_str = f"{c.price_change_1d:+.1f}%" if c.price_change_1d else "—"
        flags = " ".join(c.flags) or "—"
        sigs = "; ".join(c.signals[:2]) or "—"
        lines.append(
            f"| {i} | **{c.ticker}** | {c.composite_score:.1f} | {c.l1_score} "
            f"| {delta_str} | {c.trend} | {c.bucket or '—'} | {vol_str} "
            f"| {price_str} | {flags} | {sigs} |"
        )

    # Bucket sections
    from .candidate_ranker import group_by_bucket
    buckets = group_by_bucket(ranked)
    for bname in ("event_driven", "breakout", "momentum", "early_mover"):
        cs = buckets.get(bname, [])
        if not cs:
            continue
        lines += ["", f"## {bname.replace('_', ' ').title()}", ""]
        for c in cs:
            deep_note = ""
            s = state_store.get(c.ticker)
            if s and s.last_deep_score >= 0:
                deep_note = (f"  *(last deep: score={s.last_deep_score} "
                             f"{s.last_deep_direction.upper()} {s.last_deep_recommendation})*")
            lines.append(
                f"- **{c.ticker}** ({c.name}) — {', '.join(c.signals[:3]) or 'no signals'}"
                f"  {', '.join(c.flags)}{deep_note}"
            )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Main monitor loop
# ---------------------------------------------------------------------------

def run_monitor(cfg: Optional[MonitorConfig] = None) -> None:
    """
    Start the continuous market monitor. Runs until Ctrl+C.
    """
    if cfg is None:
        cfg = MonitorConfig()

    # ── Setup ────────────────────────────────────────────────────────────────
    _root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from dotenv import load_dotenv
    load_dotenv(os.path.join(_root, ".env"))

    # Resolve CSV path
    if not cfg.csv_path:
        cfg.csv_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "tase_stocks.csv"
        )
    cfg.csv_path = os.path.abspath(cfg.csv_path)

    stocks = _load_stocks(cfg.csv_path, cfg.size_filter)
    if not stocks:
        print("[MONITOR] ERROR: no stocks loaded. Check CSV path.")
        return

    # Hebrew name map for L2 searches
    name_he_map = {}
    for s in stocks:
        clean = s["ticker"].replace(".TA", "").upper()
        if s.get("name_he"):
            name_he_map[clean] = s["name_he"]

    borkai_config = load_config(market="il")
    client = openai.OpenAI(api_key=borkai_config.openai_api_key)

    state_store = StateStore(cfg.state_file)

    trigger_cfg = TriggerConfig(
        score_threshold=cfg.score_threshold,
        volume_spike_ratio=cfg.volume_spike_ratio,
        price_spike_pct=cfg.price_spike_pct,
        score_delta_threshold=cfg.score_delta_threshold,
        soft_cooldown_hours=cfg.soft_cooldown_hours,
        hard_cooldown_hours=cfg.hard_cooldown_hours,
        max_per_cycle=cfg.max_deep_per_cycle,
    )

    os.makedirs(cfg.output_dir, exist_ok=True)

    print_startup(
        universe_size=len(stocks),
        interval_sec=cfg.interval_sec,
        l2_every=cfg.l2_every,
        horizon=cfg.horizon,
        cooldown_hours=cfg.soft_cooldown_hours,
        score_threshold=cfg.score_threshold,
        state_file=cfg.state_file,
        output_dir=cfg.output_dir,
    )

    cycle = 0
    recent_deep: list = []   # list of (ticker, score, dir, rec, iso_ts)
    last_ranked = []

    # ── Main loop ────────────────────────────────────────────────────────────
    while True:
        cycle += 1
        t_cycle_start = time.time()
        is_l2_cycle = (cycle % cfg.l2_every == 0) or (cycle == 1)
        l2_count = None

        print(f"\n[MONITOR] === Cycle {cycle} | {datetime.now().strftime('%H:%M:%S')} "
              f"{'| L2 this cycle' if is_l2_cycle else ''} ===")

        # ── LAYER 1: fast scan (every cycle) ─────────────────────────────────
        print(f"[L1] Scanning {len(stocks)} stocks...")
        try:
            l1_results = run_layer1(stocks, verbose=cfg.verbose)
        except Exception as e:
            print(f"[L1] ERROR: {e}")
            l1_results = []

        # Update state from L1
        state_store.update_from_l1(l1_results)

        # ── LAYER 2: light AI filter (every l2_every cycles) ─────────────────
        l2_results = None
        if is_l2_cycle and l1_results:
            print(f"[L2] Running light AI filter on top {cfg.top_l1}...")
            try:
                l2_results = run_layer2(
                    layer1_results=l1_results,
                    client=client,
                    top_n=cfg.top_l1,
                    model=borkai_config.models.agent,
                    name_he_map=name_he_map,
                    verbose=cfg.verbose,
                )
                state_store.update_from_l2(l2_results)
                l2_count = len(l2_results)
            except Exception as e:
                print(f"[L2] ERROR: {e}")
                l2_results = None

        # ── RANK candidates ───────────────────────────────────────────────────
        ranked = rank_candidates(
            l1_results=l1_results,
            state_store=state_store,
            top_n=cfg.top_candidates,
            l2_results=l2_results,
        )
        last_ranked = ranked

        # ── CHECK L3 TRIGGERS ─────────────────────────────────────────────────
        triggered = get_trigger_candidates(ranked, state_store, trigger_cfg)

        # ── RUN DEEP ANALYSIS on triggered stocks ─────────────────────────────
        for ticker, reason in triggered:
            print(f"\n[L3] Deep analysis triggered: {ticker} ({reason})")
            result = _run_deep(
                ticker=ticker,
                horizon=cfg.horizon,
                config=borkai_config,
                output_dir=cfg.output_dir,
                no_articles=cfg.no_articles,
            )
            if result:
                state_store.update_from_deep(
                    ticker=ticker,
                    return_score=result["score"],
                    direction=result["direction"],
                    recommendation=result["rec"],
                )
                now_ts = datetime.now().isoformat()
                recent_deep.append((ticker, result["score"], result["direction"], result["rec"], now_ts))
                recent_deep = recent_deep[-20:]  # keep last 20 entries

        # ── PRINT DASHBOARD ───────────────────────────────────────────────────
        next_l2 = cfg.l2_every - (cycle % cfg.l2_every)
        if next_l2 == cfg.l2_every:
            next_l2 = 0

        print_cycle(
            cycle=cycle,
            ranked=ranked,
            state_store=state_store,
            triggered=triggered,
            recent_deep=recent_deep,
            is_l2_cycle=is_l2_cycle,
            l2_count=l2_count,
            interval_sec=cfg.interval_sec,
            next_l2_in=next_l2 if not is_l2_cycle else None,
        )

        # ── SAVE STATE + RANKING ──────────────────────────────────────────────
        state_store.save()
        _save_ranking(ranked, state_store, cfg.output_dir)

        # ── SLEEP ─────────────────────────────────────────────────────────────
        elapsed = time.time() - t_cycle_start
        sleep_sec = max(0.0, cfg.interval_sec - elapsed)
        if sleep_sec > 0:
            print(f"[MONITOR] Cycle {cycle} done in {elapsed:.0f}s. "
                  f"Next scan in {sleep_sec:.0f}s ...\n")
            time.sleep(sleep_sec)
        else:
            print(f"[MONITOR] Cycle {cycle} done in {elapsed:.0f}s "
                  f"(exceeded interval by {-sleep_sec:.0f}s)\n")
