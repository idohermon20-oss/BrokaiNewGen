"""
Live terminal dashboard for the continuous monitor.

Prints an ASCII-safe cycle summary: ranked candidates table, bucket groups,
L3 triggers, and recent deep analysis results.

All output is ASCII-only for Windows compatibility.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from .candidate_ranker import RankedCandidate, group_by_bucket
from .state_store import StateStore


# ---------------------------------------------------------------------------
# Trend / flag display helpers
# ---------------------------------------------------------------------------

_TREND_LABELS = {
    "heating": "[UP]",
    "cooling": "[DN]",
    "stable":  "    ",
    "new":     "[NEW]",
}

_BUCKET_LABELS = {
    "breakout":     "BREAKOUT",
    "event_driven": "EVENT   ",
    "momentum":     "MOMENTUM",
    "early_mover":  "EARLY   ",
    "":             "        ",
}


def _fmt_delta(d: float) -> str:
    if d == 0:
        return "   0.0"
    return f"{d:+6.1f}"


def _fmt_vol(v: float) -> str:
    if v <= 0:
        return "   — "
    return f"{v:5.1f}x"


def _fmt_price(p: float) -> str:
    if p == 0:
        return "  —   "
    return f"{p:+6.1f}%"


def _fmt_age(iso_ts: str) -> str:
    if not iso_ts:
        return "never"
    try:
        dt = datetime.fromisoformat(iso_ts)
        h = (datetime.now() - dt).total_seconds() / 3600
        if h < 1:
            return f"{int(h*60)}m ago"
        return f"{h:.1f}h ago"
    except Exception:
        return "?"


# ---------------------------------------------------------------------------
# Main dashboard print
# ---------------------------------------------------------------------------

def print_cycle(
    cycle: int,
    ranked: List[RankedCandidate],
    state_store: StateStore,
    triggered: List[Tuple[str, str]],
    recent_deep: list,              # list of (ticker, score, dir, rec, iso_ts)
    is_l2_cycle: bool = False,
    l2_count: Optional[int] = None,
    interval_sec: int = 300,
    next_l2_in: Optional[int] = None,
) -> None:
    """Print a full cycle dashboard."""
    now = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    l2_tag = "  [L2 ran this cycle]" if is_l2_cycle else ""
    print(f"\n{'='*72}")
    print(f"  BORKAI MARKET MONITOR  |  Cycle {cycle}  |  {now}{l2_tag}")
    print(f"{'='*72}")

    # ── Top candidates table ─────────────────────────────────────────────────
    valid = [c for c in ranked if c.l1_score > 0 or c.flags]
    print(f"\n  TOP CANDIDATES ({len(valid)} with activity | {len(ranked)} total scored):")
    print(
        f"  {'Ticker':<11} {'Comp':>5} {'L1':>3} {'Delta':>6} {'Trend':<6} "
        f"{'Bucket':<9} {'Vol':>6} {'1D%':>7}  Signals"
    )
    print(f"  {'-'*11} {'-'*5} {'-'*3} {'-'*6} {'-'*6} {'-'*9} {'-'*6} {'-'*7}  {'-'*32}")

    display = sorted(valid, key=lambda c: c.composite_score, reverse=True)[:20]
    for c in display:
        flags_str = " ".join(f"[{f}]" for f in c.flags) if c.flags else ""
        trend_lbl = _TREND_LABELS.get(c.trend, "    ")
        bucket_lbl = _BUCKET_LABELS.get(c.bucket, c.bucket[:8] if c.bucket else "        ")
        sigs = "; ".join(c.signals[:2])[:32] or "—"
        deep_marker = "(*)" if c.last_deep_score >= 0 else "   "
        print(
            f"  {c.ticker:<11} {c.composite_score:>5.1f} {c.l1_score:>3} "
            f"{_fmt_delta(c.score_delta):>6} {trend_lbl:<6} {bucket_lbl:<9} "
            f"{_fmt_vol(c.volume_ratio):>6} {_fmt_price(c.price_change_1d):>7}  "
            f"{sigs}  {flags_str}{deep_marker}"
        )

    # ── Bucket groups ────────────────────────────────────────────────────────
    buckets = group_by_bucket(ranked)
    active_buckets = {b: cs for b, cs in buckets.items() if b and b != "other"}
    if active_buckets:
        print(f"\n  BUCKETS:")
        for bucket in ("event_driven", "breakout", "momentum", "early_mover"):
            cs = active_buckets.get(bucket, [])
            if cs:
                names = ", ".join(c.ticker for c in cs[:8])
                print(f"    {bucket:<14} ({len(cs):>2}): {names}")

    # ── L3 triggers ──────────────────────────────────────────────────────────
    if triggered:
        print(f"\n  L3 TRIGGERS THIS CYCLE ({len(triggered)}):")
        for ticker, reason in triggered:
            print(f"    => {ticker:<12} {reason}")
    else:
        print(f"\n  L3: no triggers this cycle")

    # ── Recent deep analysis results ─────────────────────────────────────────
    if recent_deep:
        print(f"\n  RECENT DEEP ANALYSIS RESULTS:")
        print(f"  {'Ticker':<11} {'Score':>5}  {'Dir':<6} {'Rec':<12} {'When'}")
        print(f"  {'-'*11} {'-'*5}  {'-'*6} {'-'*12} {'-'*14}")
        for entry in recent_deep[-8:]:
            ticker, score, direction, rec, iso_ts = entry
            age = _fmt_age(iso_ts)
            score_str = f"{score:>5}" if score >= 0 else "    ?"
            print(f"  {ticker:<11} {score_str}  {direction:<6} {rec:<12} {age}")

    # ── Footer ───────────────────────────────────────────────────────────────
    print(f"\n  Scan interval: {interval_sec}s", end="")
    if next_l2_in is not None:
        print(f"  |  Next L2 in {next_l2_in} cycle(s)", end="")
    if l2_count is not None and is_l2_cycle:
        print(f"  |  L2 processed {l2_count} candidates", end="")
    print()
    print(f"{'='*72}\n")


# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------

def print_startup(
    universe_size: int,
    interval_sec: int,
    l2_every: int,
    horizon: str,
    cooldown_hours: float,
    score_threshold: float,
    state_file: str,
    output_dir: str,
) -> None:
    print(f"\n{'='*72}")
    print(f"  BORKAI CONTINUOUS MARKET MONITOR")
    print(f"{'='*72}")
    print(f"  Universe   : {universe_size} Israeli stocks (TASE)")
    print(f"  L1 scan    : every {interval_sec}s ({interval_sec//60}m {interval_sec%60}s)")
    print(f"  L2 filter  : every {l2_every} L1 cycles "
          f"(~{interval_sec * l2_every // 60}m)")
    print(f"  L3 horizon : {horizon.upper()}")
    print(f"  L3 cooldown: {cooldown_hours:.1f}h per stock")
    print(f"  L3 trigger : composite score >= {score_threshold}")
    print(f"  State file : {state_file}")
    print(f"  Reports    : {output_dir}")
    print(f"{'='*72}")
    print(f"  Press Ctrl+C to stop.")
    print(f"{'='*72}\n")
