"""
Per-stock state store for continuous monitoring.

Tracks score history, trend, change detection (new filings / news), and
deep analysis state across all scan cycles. Backed by an atomic JSON file
so state survives restarts.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

MAX_SCORE_HISTORY = 12  # ring buffer of last N scan scores


# ---------------------------------------------------------------------------
# Per-stock state
# ---------------------------------------------------------------------------

@dataclass
class StockState:
    ticker: str
    name: str = ""
    sector: str = ""
    market_cap_bucket: str = ""

    # Score history
    score_history: List[float] = field(default_factory=list)
    curr_score: float = 0.0
    prev_score: float = 0.0
    score_delta: float = 0.0
    peak_score: float = 0.0
    consecutive_up: int = 0
    consecutive_down: int = 0

    # Last L1 raw metrics (cached for trigger checks between L1 scans)
    last_price: float = 0.0
    last_price_change_1d: float = 0.0
    last_volume_ratio: float = 0.0
    last_signals: List[str] = field(default_factory=list)

    # Deep analysis state
    last_deep_at: str = ""          # ISO datetime of last deep run, or ""
    last_deep_score: int = -1       # 0-100, or -1 if never
    last_deep_direction: str = ""
    last_deep_recommendation: str = ""
    deep_count: int = 0

    # Change detection (updated on L2 medium cycle)
    last_maya_count: int = -1       # DDG filing count; -1 = never checked
    new_filing_detected: bool = False
    last_headline_hash: str = ""    # md5 of recent headlines to detect new news
    new_news_detected: bool = False

    # Classification
    trend: str = "new"      # new | stable | heating | cooling
    bucket: str = ""        # breakout | event_driven | momentum | early_mover | ""

    # Timestamps
    first_seen_at: str = ""
    last_updated_at: str = ""


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class StateStore:
    """JSON-backed store of StockState objects, keyed by ticker."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._states: Dict[str, StockState] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            for ticker, d in raw.items():
                s = StockState(ticker=ticker)
                for k, v in d.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
                self._states[ticker] = s
            print(f"[STATE] Loaded {len(self._states)} stock states from {self.path}")
        except Exception as e:
            print(f"[STATE] Could not load state ({e}) — starting fresh")
            self._states = {}

    def save(self) -> None:
        """Atomic write: write to .tmp then os.replace."""
        dirpath = os.path.dirname(self.path)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)
        tmp = self.path + ".tmp"
        data = {t: asdict(s) for t, s in self._states.items()}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    def get(self, ticker: str) -> Optional[StockState]:
        return self._states.get(ticker)

    def get_or_create(
        self, ticker: str, name: str = "", sector: str = "", market_cap_bucket: str = ""
    ) -> StockState:
        if ticker not in self._states:
            now = datetime.now().isoformat()
            self._states[ticker] = StockState(
                ticker=ticker,
                name=name,
                sector=sector,
                market_cap_bucket=market_cap_bucket,
                first_seen_at=now,
                last_updated_at=now,
                trend="new",
            )
        return self._states[ticker]

    def all_states(self) -> List[StockState]:
        return list(self._states.values())

    # ── Update helpers ───────────────────────────────────────────────────────

    def update_from_l1(self, l1_results: list) -> None:
        """Ingest one full Layer 1 scan — update scores, deltas, trends."""
        now = datetime.now().isoformat()
        for r in l1_results:
            if r.error is not None:
                continue
            s = self.get_or_create(
                r.ticker, r.name, r.sector, r.market_cap_bucket
            )
            s.name = r.name or s.name
            s.sector = r.sector or s.sector
            s.market_cap_bucket = r.market_cap_bucket or s.market_cap_bucket

            # Score delta
            s.prev_score = s.curr_score
            s.curr_score = float(r.total_score)
            s.score_delta = s.curr_score - s.prev_score
            s.peak_score = max(s.peak_score, s.curr_score)

            # Score history ring buffer
            s.score_history.append(s.curr_score)
            if len(s.score_history) > MAX_SCORE_HISTORY:
                s.score_history = s.score_history[-MAX_SCORE_HISTORY:]

            # Trend
            if s.score_delta > 0:
                s.consecutive_up += 1
                s.consecutive_down = 0
            elif s.score_delta < 0:
                s.consecutive_down += 1
                s.consecutive_up = 0

            if s.trend != "new":
                if s.score_delta >= 1.5 or s.consecutive_up >= 3:
                    s.trend = "heating"
                elif s.score_delta <= -1.5 or s.consecutive_down >= 3:
                    s.trend = "cooling"
                else:
                    s.trend = "stable"
            else:
                # Promote from "new" after first score
                s.trend = "stable"

            # Raw metrics cache
            if r.current_price is not None:
                s.last_price = float(r.current_price)
            if r.price_change_1d is not None:
                s.last_price_change_1d = float(r.price_change_1d)
            if r.volume_ratio is not None:
                s.last_volume_ratio = float(r.volume_ratio)
            s.last_signals = list(r.signals)
            s.last_updated_at = now

    def update_from_l2(self, l2_results: list) -> None:
        """Ingest Layer 2 results — update Maya counts, headline hashes, buckets."""
        for r in l2_results:
            s = self.get(r.ticker)
            if s is None:
                continue

            # Maya filing change detection
            prev_count = s.last_maya_count
            s.last_maya_count = r.maya_filing_count
            s.new_filing_detected = (prev_count >= 0 and r.maya_filing_count > prev_count)

            # News change detection
            if r.recent_headlines:
                joined = "|".join(sorted(r.recent_headlines))
                new_hash = hashlib.md5(joined.encode()).hexdigest()[:12]
                if s.last_headline_hash and new_hash != s.last_headline_hash:
                    s.new_news_detected = True
                s.last_headline_hash = new_hash

            # Bucket assignment from combined signals
            s.bucket = _assign_bucket(s, r)

    def update_from_deep(
        self,
        ticker: str,
        return_score: int,
        direction: str,
        recommendation: str,
    ) -> None:
        """Record a completed deep analysis run."""
        s = self.get(ticker)
        if s is None:
            return
        s.last_deep_at = datetime.now().isoformat()
        s.last_deep_score = return_score
        s.last_deep_direction = direction
        s.last_deep_recommendation = recommendation
        s.deep_count += 1
        # Reset one-shot change flags; next L2 cycle will re-evaluate
        s.new_filing_detected = False
        s.new_news_detected = False


# ---------------------------------------------------------------------------
# Bucket assignment
# ---------------------------------------------------------------------------

def _assign_bucket(state: StockState, l2_result) -> str:
    """
    Assign a descriptive bucket based on the dominant signal type.
    Priority: event_driven > breakout > momentum > early_mover > ""
    """
    event_impact = getattr(l2_result, "event_impact", "NONE")

    # Event-driven: new filing, new major news, or LLM-detected high-impact event
    if state.new_filing_detected or state.new_news_detected or event_impact == "HIGH":
        return "event_driven"

    # Breakout: strong price move + strong volume in same session
    has_vol = state.last_volume_ratio >= 2.0
    has_price = abs(state.last_price_change_1d) >= 3.0
    if has_vol and has_price:
        return "breakout"

    # Momentum: consecutive-up streak with meaningful current score
    if state.consecutive_up >= 3 and state.curr_score >= 4.0:
        return "momentum"

    # Early mover: previously quiet, now suddenly active
    if state.score_delta >= 2.0 and state.prev_score <= 3.0:
        return "early_mover"

    return ""
