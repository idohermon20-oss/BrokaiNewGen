"""
Deep Analysis Trigger Logic.

Decides which ranked candidates should get a full Borkai deep analysis
this cycle, enforcing:

  - Per-stock cooldown (minimum hours between analyses)
  - Score threshold (don't waste L3 on weak stocks)
  - Hard triggers (new filing, volume spike, price spike) that bypass
    score threshold but still respect a shorter cooldown
  - Maximum concurrent analyses per cycle (prevents runaway cost)

Returns a list of (ticker, trigger_reason) pairs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from .candidate_ranker import RankedCandidate
from .state_store import StateStore


# ---------------------------------------------------------------------------
# Trigger thresholds (all configurable via TriggerConfig)
# ---------------------------------------------------------------------------

@dataclass
class TriggerConfig:
    # Soft trigger: minimum composite score to consider for deep analysis
    score_threshold: float = 7.0

    # Hard triggers bypass score_threshold but still need cooldown
    volume_spike_ratio: float = 3.0      # volume ratio to hard-trigger
    price_spike_pct: float = 5.0         # abs daily % to hard-trigger
    score_delta_threshold: float = 2.5   # score jump to trigger (+ curr >= 5)

    # Cooldowns
    soft_cooldown_hours: float = 4.0     # hours between soft-trigger analyses
    hard_cooldown_hours: float = 1.5     # hours between hard-trigger analyses
    new_stock_cooldown_hours: float = 0.0  # no cooldown for first-ever analysis

    # Per-cycle cap
    max_per_cycle: int = 2


# ---------------------------------------------------------------------------
# Trigger decision
# ---------------------------------------------------------------------------

def _hours_since(iso_ts: str) -> Optional[float]:
    """Return hours elapsed since an ISO timestamp, or None if ts is empty."""
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts)
        return (datetime.now() - dt).total_seconds() / 3600
    except Exception:
        return None


def _check_candidate(
    c: RankedCandidate,
    state_store: StateStore,
    cfg: TriggerConfig,
) -> Optional[str]:
    """
    Evaluate whether a single candidate should trigger deep analysis.

    Returns a reason string if yes, None if no.
    """
    s = state_store.get(c.ticker)
    if s is None:
        return None

    hours = _hours_since(s.last_deep_at)  # None if never analyzed

    # --- Determine if this is a hard or soft trigger ---

    hard_reasons = []

    if s.new_filing_detected:
        hard_reasons.append("new_filing")

    if c.volume_ratio >= cfg.volume_spike_ratio:
        hard_reasons.append(f"vol_spike_{c.volume_ratio:.1f}x")

    if abs(c.price_change_1d) >= cfg.price_spike_pct:
        hard_reasons.append(f"price_spike_{c.price_change_1d:+.1f}%")

    if c.score_delta >= cfg.score_delta_threshold and c.l1_score >= 5:
        hard_reasons.append(f"score_jump_+{c.score_delta:.1f}")

    if c.event_impact == "HIGH":
        hard_reasons.append("high_impact_event")

    is_hard = bool(hard_reasons)
    required_cooldown = cfg.hard_cooldown_hours if is_hard else cfg.soft_cooldown_hours

    # First-ever analysis: use new_stock_cooldown
    if hours is None:
        required_cooldown = cfg.new_stock_cooldown_hours

    # Check cooldown
    if hours is not None and hours < required_cooldown:
        return None  # still cooling down

    # Score gate (soft trigger only)
    if not is_hard and c.composite_score < cfg.score_threshold:
        return None

    if is_hard:
        return f"hard: {', '.join(hard_reasons)}"
    else:
        return f"soft: score={c.composite_score:.1f}"


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def get_trigger_candidates(
    ranked: List[RankedCandidate],
    state_store: StateStore,
    cfg: Optional[TriggerConfig] = None,
) -> List[Tuple[str, str]]:
    """
    Return (ticker, reason) pairs for stocks that should run deep analysis.

    Hard-triggered candidates (new filing, volume spike, etc.) are always
    evaluated first; then soft triggers fill up to max_per_cycle.

    Args:
        ranked:       Full ranked candidate list, best-first.
        state_store:  Current state (for cooldown checks).
        cfg:          TriggerConfig; uses defaults if None.

    Returns:
        List of (ticker, reason) sorted hard triggers first.
    """
    if cfg is None:
        cfg = TriggerConfig()

    hard: List[Tuple[str, str]] = []
    soft: List[Tuple[str, str]] = []

    for c in ranked:
        reason = _check_candidate(c, state_store, cfg)
        if reason is None:
            continue
        if reason.startswith("hard:"):
            hard.append((c.ticker, reason))
        else:
            soft.append((c.ticker, reason))

    combined = hard + soft
    return combined[: cfg.max_per_cycle]
