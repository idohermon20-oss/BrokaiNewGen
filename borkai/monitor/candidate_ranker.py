"""
Candidate Ranker (Layer 2 of the monitor loop).

Takes Layer 1 results + state store and produces a ranked composite score
for each stock. Stocks with hard signals (new filings, volume spikes, etc.)
are pushed to the top regardless of raw L1 score.

Returns a sorted list of RankedCandidate objects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .state_store import StateStore, StockState


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------

@dataclass
class RankedCandidate:
    ticker: str
    name: str
    sector: str
    composite_score: float      # composite ranking score (not capped)
    l1_score: int               # raw Layer 1 score (0-10)
    score_delta: float          # change since last cycle
    trend: str                  # heating | cooling | stable | new
    bucket: str                 # breakout | event_driven | momentum | early_mover | ""
    signals: List[str] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)   # NEW_FILING, VOL_SPIKE, etc.
    volume_ratio: float = 0.0
    price_change_1d: float = 0.0
    last_deep_score: int = -1
    last_deep_at: str = ""
    deep_count: int = 0
    # L2 enrichment (optional — only populated after medium cycle)
    event_type: str = ""
    event_impact: str = ""
    sentiment: str = ""
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Bonus constants (additive on top of L1 score)
# ---------------------------------------------------------------------------

_DELTA_MULTIPLIER   = 0.4   # per point of positive score delta
_DELTA_MAX_BONUS    = 2.0   # cap on delta bonus
_TREND_HEATING      = 1.0
_TREND_NEW          = 0.5
_NEW_FILING_BONUS   = 3.5   # hard signal — most important
_NEW_NEWS_BONUS     = 1.0
_VOL_SPIKE_BONUS    = 1.5   # volume >= 3x
_HIGH_EVENT_BONUS   = 2.0   # L2 HIGH impact event
_CONSEC_UP_BONUS    = 0.3   # per cycle of consecutive gains (capped at 1.5)


# ---------------------------------------------------------------------------
# Core ranking function
# ---------------------------------------------------------------------------

def rank_candidates(
    l1_results: list,
    state_store: StateStore,
    top_n: int = 50,
    l2_results: Optional[list] = None,
) -> List[RankedCandidate]:
    """
    Build a composite-scored, ranked list of candidates.

    Args:
        l1_results:   Output from run_layer1() — all stocks, sorted by L1 score.
        state_store:  Current state store with history and change flags.
        top_n:        How many candidates to return.
        l2_results:   Optional Layer 2 results to enrich ranking; if None, uses
                      only L1 + state signals.

    Returns:
        List[RankedCandidate] sorted by composite_score descending, length <= top_n.
    """
    # Build a fast L2 lookup by ticker
    l2_map: dict = {}
    if l2_results:
        for r in l2_results:
            l2_map[r.ticker] = r

    ranked: List[RankedCandidate] = []

    for r in l1_results:
        if r.error is not None:
            continue
        s = state_store.get(r.ticker)
        if s is None:
            continue

        composite = float(r.total_score)
        flags: List[str] = []

        # Delta bonus (reward stocks heating up this cycle)
        if s.score_delta > 0:
            bonus = min(s.score_delta * _DELTA_MULTIPLIER, _DELTA_MAX_BONUS)
            composite += bonus

        # Trend bonus
        if s.trend == "heating":
            composite += _TREND_HEATING
        elif s.trend == "new":
            composite += _TREND_NEW

        # Consecutive-up streak bonus
        if s.consecutive_up > 0:
            composite += min(s.consecutive_up * _CONSEC_UP_BONUS, 1.5)

        # Hard signal: new Maya filing
        if s.new_filing_detected:
            composite += _NEW_FILING_BONUS
            flags.append("NEW_FILING")

        # Hard signal: new news detected
        if s.new_news_detected:
            composite += _NEW_NEWS_BONUS
            flags.append("NEW_NEWS")

        # Hard signal: volume spike
        if s.last_volume_ratio >= 3.0:
            composite += _VOL_SPIKE_BONUS
            flags.append(f"VOL_{s.last_volume_ratio:.1f}x")

        # L2 enrichment
        l2 = l2_map.get(r.ticker)
        event_type = event_impact = sentiment = reasoning = ""
        if l2:
            event_type   = l2.event_type or ""
            event_impact = l2.event_impact or ""
            sentiment    = l2.sentiment or ""
            reasoning    = l2.llm_reasoning or ""
            if event_impact == "HIGH":
                composite += _HIGH_EVENT_BONUS
                flags.append("HIGH_EVENT")
            elif event_impact == "MEDIUM":
                composite += 0.5

        ranked.append(RankedCandidate(
            ticker=r.ticker,
            name=r.name or r.ticker,
            sector=r.sector or "",
            composite_score=round(composite, 2),
            l1_score=r.total_score,
            score_delta=s.score_delta,
            trend=s.trend,
            bucket=s.bucket,
            signals=list(r.signals),
            flags=flags,
            volume_ratio=s.last_volume_ratio,
            price_change_1d=s.last_price_change_1d,
            last_deep_score=s.last_deep_score,
            last_deep_at=s.last_deep_at,
            deep_count=s.deep_count,
            event_type=event_type,
            event_impact=event_impact,
            sentiment=sentiment,
            reasoning=reasoning,
        ))

    ranked.sort(key=lambda c: c.composite_score, reverse=True)
    return ranked[:top_n]


# ---------------------------------------------------------------------------
# Bucket summary helper
# ---------------------------------------------------------------------------

def group_by_bucket(ranked: List[RankedCandidate]) -> dict:
    """Return a dict of bucket_name -> list of RankedCandidate."""
    groups: dict = {}
    for c in ranked:
        b = c.bucket or "other"
        groups.setdefault(b, []).append(c)
    return groups
