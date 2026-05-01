"""
Borkai Scoring Engine
=====================
Computes a structured, explainable score for a stock analysis.
LLMs generate reasoning. The system computes the score.

Score components (max 100):
  Financial Strength   0-20  margins, FCF, debt, current ratio
  Company Events/Maya  0-20  filing type × direction × recency
  News & Sentiment     0-10  article direction × recency
  Sector Heat          0-10  sector news + hot-sector keywords + macro regime
  Technical            0-10  RSI, MA cross, price momentum, volume
  Growth Potential     0-15  revenue growth, forward guidance, contracts, expansion
  Analyst Consensus    0-15  vote tally × confidence × evidence quality
  Risk Adjustment     -10-0  leverage, dilution, negative margins, VIX
  ──────────────────────────
  Raw total            0-100 (capped at 100)

The committee only validates / adjusts ±5 on top of raw_total.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ScoreComponent:
    name: str
    score: float         # actual score earned (can be negative for Risk)
    max_score: float     # ceiling for this component
    signals: List[str]   # human-readable signal bullets
    reasoning: str       # one-sentence why


@dataclass
class ScoreBoost:
    """
    A positive signal boost earned when multiple independent evidence sources converge.
    Boosts are additive on top of component scores but require real evidence — no hype.
    """
    name: str
    points: float        # actual boost earned
    max_points: float    # ceiling for this boost type
    reason: str          # one-line explanation of what triggered it
    triggered_by: List[str]  # specific signals that qualified


@dataclass
class ScoringResult:
    financial:    ScoreComponent   # 0-20
    events:       ScoreComponent   # 0-20
    news:         ScoreComponent   # 0-10
    sector_macro: ScoreComponent   # 0-10  (sector heat)
    technical:    ScoreComponent   # 0-10
    growth:       ScoreComponent   # 0-15  (new)
    consensus:    ScoreComponent   # 0-15  (increased from 10)
    risk:         ScoreComponent   # -10 to 0

    raw_total:    float            # final pre-committee score (after boosts + constraints)
    final_total:  float            # set after committee ±5 adjustment

    top_positive_drivers: List[str]
    top_negative_drivers: List[str]
    most_impactful_event: str      # single most impactful recent filing or article

    # Boost / calibration layers (defaults for backward compat)
    base_total:             float      = 0.0   # component sum before boosts
    boosts:                 List[ScoreBoost] = field(default_factory=list)
    consistency_adjustment: float      = 0.0   # convergence premium when signals align
    contradiction_penalty:  float      = 0.0   # deduction for cross-signal conflicts
    pre_calibration_total:  float      = 0.0   # score before soft compression
    score_gaps:             List[str]  = field(default_factory=list)  # what prevents higher score


# ── Recency weights ───────────────────────────────────────────────────────────

def _recency_weight(published: Optional[str]) -> float:
    """
    Return a weight 0.0-1.0 based on how many days ago the event was published.
      ≤ 3 days  → 1.0
      ≤ 14 days → 0.7
      ≤ 60 days → 0.4
      older     → 0.2
      no date   → 0.3
    """
    if not published:
        return 0.3
    try:
        pub = datetime.fromisoformat(published[:10])
        now = datetime.now()
        days_old = (now - pub).days
    except Exception:
        return 0.3
    if days_old <= 3:
        return 1.0
    if days_old <= 14:
        return 0.7
    if days_old <= 60:
        return 0.4
    return 0.2


def _direction_value(impact: str) -> float:
    """Convert impact string to numeric direction: bullish=+1, bearish=-1, neutral=0."""
    return {"bullish": 1.0, "bearish": -1.0}.get((impact or "").lower(), 0.0)


def _parse_quarterly_growth(summary: str) -> dict:
    """
    Parse the quarterly_earnings_summary string for revenue and net income growth rates.
    Expected format:
      2024-01-01: Rev=500M Net=80M
      Latest vs prior: Rev QoQ +12.5% Net QoQ +18.3%
      Year-over-year: Rev YoY +25.1% Net YoY +30.2%

    Returns dict with keys: rev_qoq, net_qoq, rev_yoy, net_yoy (float or None).
    """
    result: dict = {"rev_qoq": None, "net_qoq": None, "rev_yoy": None, "net_yoy": None}
    if not summary:
        return result
    for line in summary.splitlines():
        m = re.search(r"Rev\s+QoQ\s*([+-]?\d+\.?\d*)%", line, re.IGNORECASE)
        if m:
            result["rev_qoq"] = float(m.group(1))
        m = re.search(r"Net\s+QoQ\s*([+-]?\d+\.?\d*)%", line, re.IGNORECASE)
        if m:
            result["net_qoq"] = float(m.group(1))
        m = re.search(r"Rev\s+YoY\s*([+-]?\d+\.?\d*)%", line, re.IGNORECASE)
        if m:
            result["rev_yoy"] = float(m.group(1))
        m = re.search(r"Net\s+YoY\s*([+-]?\d+\.?\d*)%", line, re.IGNORECASE)
        if m:
            result["net_yoy"] = float(m.group(1))
    return result


# ── Component scorers ─────────────────────────────────────────────────────────

def _score_financial(stock_data: Any) -> ScoreComponent:
    """
    Financial Strength: 0-20 — three-part structure

    Part 1 — Profitability base (0-8):
      Gross margin + Operating margin + Net margin.
      Measures current financial health. No penalty for zero; losses move to Part 3.

    Part 2 — Growth signals (0-9):
      Revenue QoQ + Revenue YoY + Net income growth + Margin trend.
      Parsed directly from quarterly_earnings_summary.
      GROWTH IS A PRIMARY SIGNAL — strong revenue/earnings growth is highly rewarded.

    Part 3 — Balance sheet risk (-5 to +3):
      FCF, leverage, liquidity, operating loss flag.
      Negative factors REDUCE score but cannot erase strong profitability + growth.

    Target ranges:
      Strong growth + profitability : 14–18
      Good fundamentals              : 10–13
      Moderate                       :  6–9
      Weak                           :  3–5
      Very weak / loss-making        :  0–2
    """
    signals: List[str] = []
    sd = stock_data

    # ── Part 1: Profitability base (0-8) ─────────────────────────────────────
    prof = 0.0

    gm = getattr(sd, "gross_margin", None)
    om = getattr(sd, "operating_margin", None)
    nm = getattr(sd, "net_margin", None)

    if gm is not None:
        if   gm >= 0.50: prof += 2.5; signals.append(f"+ Gross margin {gm*100:.0f}% (excellent)")
        elif gm >= 0.30: prof += 2.0; signals.append(f"+ Gross margin {gm*100:.0f}% (solid)")
        elif gm >= 0.15: prof += 1.2; signals.append(f"~ Gross margin {gm*100:.0f}% (acceptable)")
        elif gm >= 0.05: prof += 0.5; signals.append(f"~ Gross margin {gm*100:.0f}% (thin)")
        else:                          signals.append(f"- Gross margin {gm*100:.0f}% (very thin)")

    if om is not None:
        if   om >= 0.20: prof += 2.5; signals.append(f"+ Operating margin {om*100:.0f}% (strong)")
        elif om >= 0.10: prof += 2.0; signals.append(f"+ Operating margin {om*100:.0f}% (healthy)")
        elif om >= 0.05: prof += 1.2; signals.append(f"~ Operating margin {om*100:.0f}% (marginal)")
        elif om >= 0.00: prof += 0.3; signals.append(f"~ Operating margin {om*100:.0f}% (breakeven)")
        # negative: no profitability credit; risk penalty applied in Part 3

    if nm is not None:
        if   nm >= 0.15: prof += 3.0; signals.append(f"+ Net margin {nm*100:.0f}% (excellent)")
        elif nm >= 0.08: prof += 2.5; signals.append(f"+ Net margin {nm*100:.0f}% (good)")
        elif nm >= 0.03: prof += 1.5; signals.append(f"~ Net margin {nm*100:.0f}% (positive)")
        elif nm >= 0.00: prof += 0.5; signals.append(f"~ Net margin {nm*100:.0f}% (breakeven)")
        # negative: no profitability credit; risk penalty applied in Part 3

    prof = max(0.0, min(8.0, prof))

    # ── Part 2: Growth signals (0-9) ─────────────────────────────────────────
    growth = 0.0
    q = _parse_quarterly_growth(getattr(sd, "quarterly_earnings_summary", "") or "")
    has_growth_data = any(v is not None for v in q.values())

    # Revenue QoQ (0-2.5)
    if q["rev_qoq"] is not None:
        v = q["rev_qoq"]
        if   v >= 15: growth += 2.5; signals.append(f"+ Revenue QoQ +{v:.1f}% (strong growth)")
        elif v >= 8:  growth += 2.0; signals.append(f"+ Revenue QoQ +{v:.1f}% (healthy growth)")
        elif v >= 3:  growth += 1.3; signals.append(f"+ Revenue QoQ +{v:.1f}% (moderate growth)")
        elif v >= 0:  growth += 0.5; signals.append(f"~ Revenue QoQ {v:+.1f}% (flat)")
        elif v >= -10: growth -= 0.5; signals.append(f"- Revenue QoQ {v:.1f}% (declining)")
        else:          growth -= 1.5; signals.append(f"- Revenue QoQ {v:.1f}% (sharp decline)")

    # Revenue YoY (0-2.5) — longer-term trend, weighted slightly heavier
    if q["rev_yoy"] is not None:
        v = q["rev_yoy"]
        if   v >= 25: growth += 2.5; signals.append(f"+ Revenue YoY +{v:.1f}% (high growth)")
        elif v >= 15: growth += 2.0; signals.append(f"+ Revenue YoY +{v:.1f}% (strong YoY)")
        elif v >= 7:  growth += 1.3; signals.append(f"+ Revenue YoY +{v:.1f}% (growing YoY)")
        elif v >= 0:  growth += 0.5; signals.append(f"~ Revenue YoY {v:+.1f}% (flat YoY)")
        elif v >= -10: growth -= 0.8; signals.append(f"- Revenue YoY {v:.1f}% (declining YoY)")
        else:          growth -= 2.0; signals.append(f"- Revenue YoY {v:.1f}% (sharp YoY decline)")

    # Net income growth — use QoQ first, fall back to YoY (0-2.5)
    ni_val, ni_label = (
        (q["net_qoq"], "QoQ") if q["net_qoq"] is not None
        else (q["net_yoy"], "YoY") if q["net_yoy"] is not None
        else (None, "")
    )
    if ni_val is not None:
        if   ni_val >= 20: growth += 2.5; signals.append(f"+ Net income {ni_label} +{ni_val:.1f}% (strong earnings growth)")
        elif ni_val >= 10: growth += 1.8; signals.append(f"+ Net income {ni_label} +{ni_val:.1f}% (growing earnings)")
        elif ni_val >= 0:  growth += 0.8; signals.append(f"~ Net income {ni_label} {ni_val:+.1f}% (stable)")
        elif ni_val >= -15: growth -= 0.5; signals.append(f"- Net income {ni_label} {ni_val:.1f}% (declining)")
        else:               growth -= 1.5; signals.append(f"- Net income {ni_label} {ni_val:.1f}% (sharp decline)")

    # Margin trend: earnings outpacing revenue → expansion (0-1.5)
    rg = q["rev_qoq"] if q["rev_qoq"] is not None else q["rev_yoy"]
    ng = q["net_qoq"] if q["net_qoq"] is not None else q["net_yoy"]
    if rg is not None and ng is not None:
        if ng > rg and ng > 0:
            growth += 1.5; signals.append(f"+ Margin expansion: earnings growing faster than revenue")
        elif rg > 0 and ng >= 0:
            growth += 0.5; signals.append(f"~ Margins holding stable while revenue grows")
        elif rg < 0 and ng < rg:
            growth -= 0.5; signals.append(f"- Margin compression: costs growing faster than revenue")

    if not has_growth_data:
        signals.append("~ No quarterly growth data available")

    growth = max(-3.0, min(9.0, growth))

    # ── Part 3: Balance sheet risk (-5 to +3) ────────────────────────────────
    # Positive FCF/liquidity contribute modestly; risks reduce but don't dominate.
    bs = 0.0

    fcf = getattr(sd, "free_cash_flow", None)
    if fcf is not None:
        if   fcf > 50e6:  bs += 2.0; signals.append(f"+ Strong FCF ({fcf/1e6:.0f}M)")
        elif fcf > 0:     bs += 1.0; signals.append(f"+ Positive FCF ({fcf/1e6:.0f}M)")
        elif fcf > -10e6: bs -= 0.5; signals.append(f"~ Slightly negative FCF ({fcf/1e6:.0f}M)")
        elif fcf > -50e6: bs -= 1.0; signals.append(f"- Negative FCF ({fcf/1e6:.0f}M)")
        else:             bs -= 1.5; signals.append(f"- Large negative FCF ({fcf/1e6:.0f}M)")

    de = getattr(sd, "debt_to_equity", None)
    if de is not None:
        if   de < 0.3:  bs += 1.0; signals.append(f"+ Low leverage D/E {de:.1f}")
        elif de < 1.0:  bs += 0.5; signals.append(f"+ Moderate leverage D/E {de:.1f}")
        elif de < 2.0:  signals.append(f"~ Elevated leverage D/E {de:.1f}")
        elif de < 4.0:  bs -= 1.0; signals.append(f"- High leverage D/E {de:.1f}")
        else:           bs -= 2.0; signals.append(f"- Very high leverage D/E {de:.1f}")

    cr = getattr(sd, "current_ratio", None)
    if cr is not None:
        if   cr >= 2.0:  bs += 0.5; signals.append(f"+ Current ratio {cr:.1f} (strong liquidity)")
        elif cr >= 1.0:  signals.append(f"~ Current ratio {cr:.1f} (adequate)")
        else:            bs -= 1.0; signals.append(f"- Current ratio {cr:.1f} (liquidity risk)")

    # Operating loss is a viability risk flag (not double-counted in profitability)
    if om is not None and om < -0.05:
        bs -= 1.5; signals.append(f"- Operating loss {om*100:.0f}% (viability concern)")
    elif om is not None and om < 0:
        bs -= 0.5; signals.append(f"~ Operating loss {om*100:.0f}% (marginal)")

    bs = max(-5.0, min(3.0, bs))

    # ── Final: validate mid-range floor ──────────────────────────────────────
    score = prof + growth + bs
    # Validation: if company shows revenue growth, profit growth, and positive margins,
    # the score must not fall below the mid-range floor (10/20).
    has_revenue_growth = (
        (q["rev_qoq"] is not None and q["rev_qoq"] >= 3) or
        (q["rev_yoy"] is not None and q["rev_yoy"] >= 5)
    )
    has_profit_growth = ni_val is not None and ni_val >= 0
    has_positive_margins = (nm is not None and nm >= 0.03) and (om is not None and om >= 0)

    if has_revenue_growth and has_profit_growth and has_positive_margins:
        if score < 10.0:
            signals.append(f"~ Score floored at 10 (revenue growth + profit growth + positive margins)")
            score = 10.0

    score = max(0.0, min(20.0, score))
    reasoning = (
        f"Financial {score:.1f}/20 — "
        f"profitability {prof:.1f}/8 + growth {growth:.1f}/9 + balance sheet {bs:.1f}"
    )
    return ScoreComponent("Financial Strength", score, 20.0, signals, reasoning)


# ── Maya event tier classification ───────────────────────────────────────────
# Tier 1 — Strategic / transformative: rare, high-impact, re-rates the company
_TIER1_EVENT_KW = [
    # Big-tech partnerships
    "nvidia", "intel", "microsoft", "google", "amazon", "apple", "meta",
    # M&A / corporate control
    "acquisition", "merger", "acquired", "takeover", "רכישה", "מיזוג",
    # Major strategic / expansion
    "international expansion", "new market", "הרחבה בינלאומית",
    "defense contract", "חוזה ביטחוני", "חוזה עם צבא", "חוזה עם משרד הביטחון",
    "strategic partnership", "שיתוף פעולה אסטרטגי",
    "breakthrough", "פריצת דרך",
    "multi-year", "multi-billion", "major contract", "חוזה ענק",
    "artificial intelligence", "בינה מלאכותית",
    "ipo", "הנפקה",
    "joint venture", "מיזם משותף",
    "government contract", "חוזה ממשלתי",
    "nato", "nato contract",
]
# Tier 2 — Strong operational: earnings beats, guidance raises, meaningful contracts
_TIER2_EVENT_KW = [
    "record revenue", "הכנסות שיא", "record quarter", "שיא רבעוני",
    "earnings beat", "beat estimates", "עלה על הציפיות",
    "guidance raised", "guidance upgrade", "raised guidance", "העלאת תחזית",
    "product launch", "השקת מוצר",
    "new contract", "contract won", "חוזה חדש", "זכייה בחוזה",
    "backlog", "צבר הזמנות", "order book",
    "partnership", "שיתוף פעולה",
    "agreement", "הסכם",
    "expansion", "הרחבה",
    "regulatory approval", "אישור רגולטורי",
    "approved", "אושר",
    "significant contract", "meaningful contract",
]
# Tier 3 override — Routine / administrative: these cap magnitude regardless of type
_TIER3_OVERRIDE_KW = [
    "appointment", "מינוי", "resignation", "התפטרות",
    "annual meeting", "אסיפה שנתית", "general meeting", "אסיפה כללית",
    "dividend", "דיבידנד",
    "proxy", "administrative", "correction", "amendment",
    "routine", "board member", "חבר דירקטוריון",
    "chairman", "יו\"ר",
    "director", "officer",
]

# Tier magnitude: how much a single bullish event of each tier contributes
_TIER_MAGNITUDE = {1: 10.0, 2: 6.0, 3: 2.0}


def _classify_filing_tier(title: str, rtype: str) -> int:
    """
    Classify a Maya filing into Tier 1 (strategic), Tier 2 (operational), or Tier 3 (routine).
    Tier 3 override takes priority — administrative events are never promoted.
    """
    t  = (title or "").lower()
    rt = (rtype or "").lower()

    # Tier-3 override first: administrative events stay low-impact
    if rt in ("appointment", "bond") or any(kw in t for kw in _TIER3_OVERRIDE_KW):
        return 3

    # Tier-1: strategic / transformative keywords
    if any(kw in t for kw in _TIER1_EVENT_KW):
        return 1

    # Tier-2: strong operational keywords or filing types
    if any(kw in t for kw in _TIER2_EVENT_KW):
        return 2
    if rt in ("earnings", "material_event", "guidance", "regulatory"):
        return 2

    return 3  # default: routine


def _detect_event_cluster(classified: list) -> float:
    """
    Detect bullish clusters among classified filings and return a bonus score.
    classified: list of (tier, direction) tuples.

    Cluster bonuses:
      ≥3 Tier-1 bullish  →  +5.0   (multiple strategic wins)
      ≥2 Tier-1 bullish  →  +3.5   (two strategic wins)
      1 Tier-1 + ≥2 Tier-1/2 bullish → +2.0
      ≥4 Tier-2 bullish  →  +1.5   (strong operational momentum)
    """
    tier1_bull  = [x for x in classified if x[0] == 1 and x[1] > 0]
    tier12_bull = [x for x in classified if x[0] <= 2 and x[1] > 0]
    tier2_bull  = [x for x in classified if x[0] == 2 and x[1] > 0]

    if len(tier1_bull) >= 3:
        return 5.0
    if len(tier1_bull) >= 2:
        return 3.5
    if len(tier1_bull) >= 1 and len(tier12_bull) >= 3:
        return 2.0
    if len(tier2_bull) >= 4:
        return 1.5
    return 0.0

# ── Signal quality keyword maps ───────────────────────────────────────────────
# High-quality filing signals: concrete operational/financial events
_HIGH_QUALITY_FILING_KW = [
    "contract", "חוזה", "partnership", "agreement", "acquisition", "merger",
    "expansion", "record revenue", "guidance raised", "raises guidance", "beats",
    "backlog", "new customer", "market share", "strategic", "billion", "מיליארד",
    "long-term", "multi-year", "הסכם", "פרטנרשיפ", "רכישה", "הרחבה",
]
# Low-quality filing signals: administrative / routine / immaterial
_LOW_QUALITY_FILING_KW = [
    "appointment", "מינוי", "resignation", "התפטרות", "annual meeting",
    "אסיפה שנתית", "proxy", "administrative", "correction", "amendment",
    "routine", "immaterial", "technical correction",
]
# High-quality news signals: concrete data / events
_HIGH_QUALITY_NEWS_KW = [
    "revenue", "earnings", "contract", "partnership", "acquisition",
    "beat estimates", "raised guidance", "record", "backlog", "deal won",
    "analyst upgrade", "price target raised", "market share", "cash flow",
    "eps beat", "growth rate", "guidance raised",
]
# Low-quality news signals: opinion / speculation
_LOW_QUALITY_NEWS_KW = [
    "may", "could", "might", "speculate", "rumor", "expects", "forecast",
    "prediction", "potential", "possible", "some analysts",
]


def _filing_quality_multiplier(title: str, rtype: str) -> float:
    """Return a quality multiplier 0.6–1.4 based on filing content richness."""
    t = (title or "").lower()
    if any(kw in t for kw in _HIGH_QUALITY_FILING_KW):
        return 1.4
    if rtype.lower() in ("appointment", "bond") or any(kw in t for kw in _LOW_QUALITY_FILING_KW):
        return 0.7
    return 1.0


def _news_quality_multiplier(title: str, summary: str) -> float:
    """Return a quality multiplier 0.7–1.4 based on article content."""
    combined = f"{(title or '')} {(summary or '')}".lower()
    if any(kw in combined for kw in _HIGH_QUALITY_NEWS_KW):
        return 1.35
    if sum(1 for kw in _LOW_QUALITY_NEWS_KW if kw in combined) >= 2:
        return 0.7
    return 1.0


# ── News sentiment engine v2: 5-level direction values ───────────────────────
# Maps ArticleImpact.sentiment (v2 field) to a numeric direction for scoring.
# Strong signals carry double the weight of ordinary signals.
_SENTIMENT_DIRECTION = {
    "strong_bullish":  2.0,
    "bullish":         1.0,
    "neutral":         0.0,
    "bearish":        -1.0,
    "strong_bearish": -2.0,
}

# Display labels for report output
_SENTIMENT_LABEL = {
    "strong_bullish": "STRONG BULL",
    "bullish":        "BULLISH",
    "neutral":        "NEUTRAL",
    "bearish":        "BEARISH",
    "strong_bearish": "STRONG BEAR",
}


def _score_events(maya_reports: list) -> tuple:
    """
    Company Events/Maya: 0-20
    Tier-based weighting: Tier-1 strategic × 10, Tier-2 operational × 6, Tier-3 routine × 2.
    Cluster detection adds a bonus when multiple strong events converge.
    Validation floor ensures high-impact events (Tier-1) are always reflected strongly.

    Tier 1 — Strategic / transformative  (magnitude 10): acquisitions, major partnerships,
              defense/government contracts, international expansion, big-tech alliances.
    Tier 2 — Strong operational          (magnitude 6):  earnings beats, guidance raises,
              product launches, meaningful contracts, record revenue.
    Tier 3 — Routine / administrative    (magnitude 2):  appointments, dividends, meetings.
    """
    signals: List[str] = []
    raw_sum = 0.0
    best_event: Optional[str] = None
    best_event_weight = 0.0
    classified: List[tuple] = []   # (tier, direction) for cluster detection

    for rep in (maya_reports or []):
        rtype   = getattr(rep, "report_type", "other") or "other"
        impact  = getattr(rep, "impact", "neutral") or "neutral"
        pub     = getattr(rep, "published", None)
        title   = getattr(rep, "title", "") or ""

        tier      = _classify_filing_tier(title, rtype)
        magnitude = _TIER_MAGNITUDE[tier]
        direction = _direction_value(impact)
        recency   = _recency_weight(pub)

        contribution = magnitude * direction * recency
        raw_sum += contribution
        classified.append((tier, direction))

        abs_weight = magnitude * recency
        if abs_weight > best_event_weight:
            best_event_weight = abs_weight
            best_event = title

        date_str = (pub or "")[:10]
        dir_icon = "+" if direction > 0 else ("-" if direction < 0 else "~")
        tier_tag = f" [T{tier}]"
        signals.append(
            f"{dir_icon} [{date_str}] {rtype.capitalize()}: {title[:55]}{tier_tag}"
            + (f" ({impact})" if impact != "neutral" else "")
        )

    # Normalize: max_theoretical = 55 (tuned for tier magnitudes)
    # Maps [-55, +55] → [0, 20]; neutral (0 raw) → 10
    max_theoretical = 55.0
    score = max(0.0, min(20.0, (raw_sum + max_theoretical) / (2 * max_theoretical) * 20.0))

    # Cluster bonus: multiple strong events in the same period → add pts directly
    cluster_bonus = _detect_event_cluster(classified)
    if cluster_bonus > 0:
        score = min(20.0, score + cluster_bonus)
        signals.append(f"+ Cluster bonus +{cluster_bonus:.1f} ({sum(1 for t, d in classified if t <= 2 and d > 0)} Tier-1/2 bullish events)")

    # Validation floor: Tier-1 bullish events must result in a high Maya score
    # Strategic corporate actions are real — they must be reflected strongly.
    tier1_bull = sum(1 for t, d in classified if t == 1 and d > 0)
    if tier1_bull >= 2 and score < 15.0:
        signals.append(f"~ Score floored at 15 ({tier1_bull} Tier-1 bullish events)")
        score = 15.0
    elif tier1_bull == 1 and score < 12.0:
        signals.append(f"~ Score floored at 12 (1 Tier-1 bullish event)")
        score = 12.0

    if not signals:
        signals.append("~ No Maya filings available")
        score = 10.0  # neutral default

    reasoning = f"Events score {score:.1f}/20 from {len(maya_reports or [])} Maya filings (tier-classified)"
    return ScoreComponent("Company Events / Maya", score, 20.0, signals[:8], reasoning), best_event



def _compute_news_strength(article_impacts: list) -> tuple:
    """
    Single source of truth for all news-derived scores and boosts.

    Spec formula:
      news_strength = sum(sentiment_value x impact_score x confidence x recency)

    impact_score is used directly on the 0-5 scale (NOT divided by 5).
    This means a 5/5 impact article is 5x more influential than a 1/5 article,
    which correctly reflects how much news matters.

      Max per article : direction=+2, impact=5, conf=1.0, recency=1.0 -> +10.0
      Typical range   : [-30, +30] for realistic article sets

    Legacy articles (no sentiment field) use quality * 3 as an impact proxy
    so quality=1.0 maps to ~impact 3 equivalent.

    Returns (news_strength: float, stats: dict)
    stats keys: strong_bull_n, bull_n, strong_bear_n, bear_n, high_bull_n, high_bear_n
    """
    strength = 0.0
    stats = dict(strong_bull_n=0, bull_n=0, strong_bear_n=0, bear_n=0,
                 high_bull_n=0, high_bear_n=0)

    for art in (article_impacts or []):
        sentiment    = getattr(art, "sentiment", "")    or ""
        impact_score = getattr(art, "impact_score", 0) or 0
        pub          = getattr(art, "published", None)
        conf         = max(0.5, min(1.0, getattr(art, "confidence", 0.75) or 0.75))
        recency      = _recency_weight(pub)

        if sentiment in _SENTIMENT_DIRECTION:
            direction    = _SENTIMENT_DIRECTION[sentiment]
            # Spec formula: sentiment_value x impact_score x confidence x recency
            contribution = direction * impact_score * conf * recency
            strength    += contribution

            if   sentiment == "strong_bullish": stats["strong_bull_n"] += 1
            elif sentiment == "strong_bearish": stats["strong_bear_n"] += 1
            elif sentiment == "bullish":        stats["bull_n"]        += 1
            elif sentiment == "bearish":        stats["bear_n"]        += 1

            if impact_score >= 4:
                if direction > 0:  stats["high_bull_n"] += 1
                elif direction < 0: stats["high_bear_n"] += 1
        else:
            # Legacy 3-level path: scale quality to impact_score range
            # quality 0.7-1.35 x 3 = roughly 2-4 impact equivalent
            impact  = getattr(art, "impact", "neutral") or "neutral"
            summary = getattr(art, "impact_summary", "") or ""
            title   = getattr(art, "title", "") or ""
            direction    = _direction_value(impact)
            quality      = _news_quality_multiplier(title, summary)
            contribution = direction * (quality * 3.0) * recency
            strength    += contribution
            if direction > 0:  stats["bull_n"]  += 1
            elif direction < 0: stats["bear_n"] += 1

    return strength, stats


def _score_news(article_impacts: list) -> ScoreComponent:
    """
    News & Sentiment: 0-10.

    Uses _compute_news_strength() as single source of truth for the numeric signal.
    Signal bullets are built in a separate pass (display only).
    Both this function and _boost_news_momentum() use the same raw_sum value,
    ensuring news_score and news_boost can never contradict each other.
    """
    arts    = article_impacts or []
    signals: List[str] = []

    # ── Numeric computation (single source of truth) ──────────────────────────
    raw_sum, stats = _compute_news_strength(arts)
    strong_bull_n  = stats["strong_bull_n"]
    strong_bear_n  = stats["strong_bear_n"]
    bull_n         = stats["bull_n"]
    bear_n         = stats["bear_n"]

    # ── Signal bullets (display only) ─────────────────────────────────────────
    for art in arts:
        sentiment    = getattr(art, "sentiment", "")    or ""
        impact_score = getattr(art, "impact_score", 0) or 0
        pub          = getattr(art, "published", None)
        title        = (getattr(art, "title", "") or "")
        event_type   = (getattr(art, "event_type", "") or "")
        event_reason = (getattr(art, "event_reasoning", "") or "")
        date_str     = (pub or "")[:10]

        if sentiment in _SENTIMENT_DIRECTION:
            direction = _SENTIMENT_DIRECTION[sentiment]
            dir_icon  = "+" if direction > 0 else ("-" if direction < 0 else "~")
            label     = _SENTIMENT_LABEL.get(sentiment, sentiment.upper())
            score_tag = f" [{impact_score}/5]" if impact_score else ""
            type_tag  = f" ({event_type})" if event_type else ""
            signals.append(f"{dir_icon} [{date_str}] [{label}{score_tag}] {title[:50]}{type_tag}")
            if event_reason:
                signals.append(f"   -> {event_reason[:100]}")
        else:
            impact  = (getattr(art, "impact", "neutral") or "neutral")
            summary = (getattr(art, "impact_summary", "") or "")
            direction = _direction_value(impact)
            quality   = _news_quality_multiplier(title, summary)
            dir_icon  = "+" if direction > 0 else ("-" if direction < 0 else "~")
            q_tag     = " [HIGH-Q]" if quality > 1.2 else ""
            signals.append(f"{dir_icon} [{date_str}] {title[:55]}{q_tag}")

    # ── Normalize using symmetric +-22 window ────────────────────────────────
    # Calibrated so that a typical strong-positive cluster scores correctly:
    #   3 bullish articles impact=4 conf=0.88 fresh -> strength~10.6 -> score~7.4
    #   2 strong_bullish impact=5 conf=0.88 fresh  -> strength~17.6 -> score~9.0
    #   4+ strong articles                          -> score 9-10 (strong cluster)
    # Symmetric: same formula applies to negative side.
    _NEWS_NORMALIZER = 22.0
    score = max(0.0, min(10.0, 5.0 + (raw_sum / _NEWS_NORMALIZER) * 5.0))

    # ── Conflict detection ────────────────────────────────────────────────────
    if strong_bull_n > 0 and strong_bear_n > 0:
        signals.append(
            f"~ CONFLICT: {strong_bull_n} strong bullish vs {strong_bear_n} strong bearish | "
            f"dominant: {'bullish' if raw_sum > 0 else 'bearish'} | strength={raw_sum:.2f}"
        )
        compression = min(0.4, (min(strong_bull_n, strong_bear_n) * 0.1))
        score = score * (1 - compression) + 5.0 * compression

    # ── Spec-defined validation floors ───────────────────────────────────────
    # Count all articles for percentage calculation
    total_arts = len(arts)
    all_bull   = strong_bull_n + bull_n
    all_bear   = strong_bear_n + bear_n
    bull_pct   = all_bull / total_arts if total_arts > 0 else 0.0
    high_bull_n = stats["high_bull_n"]   # articles with impact_score >= 4 AND bullish direction

    # Floor 1: >= 60% bullish + >= 2 high-impact (impact>=4) articles -> score >= 7
    if bull_pct >= 0.60 and high_bull_n >= 2 and score < 7.0:
        score = 7.0
        signals.append(
            f"~ Floor 7.0: {bull_pct:.0%} bullish ({all_bull}/{total_arts}), "
            f"{high_bull_n} high-impact articles"
        )

    # Floor 2: >= 70% bullish + >= 3 high-impact articles -> score >= 8
    if bull_pct >= 0.70 and high_bull_n >= 3 and score < 8.0:
        score = 8.0
        signals.append(
            f"~ Floor 8.0: {bull_pct:.0%} bullish ({all_bull}/{total_arts}), "
            f"{high_bull_n} high-impact articles"
        )

    if not signals:
        signals.append("~ No articles available")
        score = 5.0

    # ── Aggregated reasoning (full debug output) ──────────────────────────────
    lean = "bullish" if all_bull > all_bear else ("bearish" if all_bear > all_bull else "mixed/neutral")
    reasoning = (
        f"articles={total_arts} | bullish={all_bull} ({bull_pct:.0%}) "
        f"bearish={all_bear} neutral={total_arts - all_bull - all_bear} | "
        f"high-impact bullish={high_bull_n} | "
        f"strength={raw_sum:.2f} | score={score:.1f}/10 | lean={lean}"
    )
    return ScoreComponent("News & Sentiment", score, 10.0, signals[:10], reasoning)


# ── Sector tier classification ────────────────────────────────────────────────
# Tier 1: structurally hot in the current market — AI supercycle, defense spending surge.
#   These sectors have REAL capital flows and REAL demand right now. A Tier-1 score
#   reflects market reality, not generic description.
_SECTOR_TIER1_KW = {
    # Multi-word first (checked as substrings — no false-positive risk)
    "artificial intelligence", "data center", "cybersecurity",
    # Single-word: use whole-word matching (see _kw_in_sector)
    "semiconductor", "foundry", "defense", "aerospace", "cyber",
    "military", "weapons",
}
# Short keywords matched as whole words only (avoid "ai" in "retail", "chip" in "championship")
_SECTOR_TIER1_WORD_KW = {"ai", "chip"}

# Tier 2: growing sectors with moderate tailwinds.
_SECTOR_TIER2_KW = {
    "cloud", "software", "technology", "fintech", "payments",
    "healthcare technology", "medtech", "biotech", "pharmaceutical",
    "renewable energy", "solar", "clean energy", "space",
    "robotics", "automation", "enterprise software", "intelligence",
}
# Out-of-favor sectors with structural headwinds.
_SECTOR_COLD_KW = {
    "real estate", "reit", "utilities", "tobacco", "coal",
}

# Keyword sets for keyword-based assessment of sector news item sentiment.
# Used when SectorNewsItem has no pre-assessed 'impact' field.
_SECTOR_BULL_KW = [
    # Strong positive
    "surge", "surges", "record", "rally", "boom", "booming", "soars",
    "outperform", "breakthrough", "milestone",
    # Growth / demand
    "strong demand", "high demand", "growing demand", "growth", "grow", "growing",
    "strong", "increases", "increased", "expanding", "expand", "expansion",
    "positive outlook", "increased spending", "budget increase",
    # Market signals
    "upgrades", "upgrade", "bullish", "invest", "investment", "inflows",
    "new orders", "contract", "wins", "rises", "rise", "gains", "gain",
    "momentum", "robust", "accelerat", "improve", "improving",
]
_SECTOR_BEAR_KW = [
    # Directional
    "decline", "declines", "fall", "falls", "drops", "drop",
    "correction", "selloff", "sell-off",
    # Demand / business
    "weak demand", "downturn", "oversupply", "slowing", "slow",
    "miss", "disappoints", "disappointing", "headwind",
    # Sentiment
    "bearish", "downgrade", "cut", "cuts", "negative", "warning", "trouble",
    "concern", "risk off", "risk-off",
]

# Keywords that confirm a company actually participates meaningfully in a hot sector.
# Avoids inflating sector heat for companies that only peripherally touch the sector.
_SECTOR_PARTICIPATION_KW: dict = {
    "artificial intelligence": ["ai", "artificial intelligence", "machine learning",
                                  "deep learning", "neural", "llm", "generative", "gpu"],
    "ai":                      ["ai", "artificial intelligence", "machine learning",
                                  "deep learning", "neural", "llm", "generative", "gpu"],
    "semiconductor":           ["semiconductor", "chip", "wafer", "foundry", "fab",
                                  "silicon", "integrated circuit", "analog", "mixed-signal"],
    "chip":                    ["semiconductor", "chip", "wafer", "foundry", "fab",
                                  "silicon", "integrated circuit"],
    "foundry":                 ["foundry", "fab", "wafer", "semiconductor"],
    "defense":                 ["defense", "military", "weapon", "army", "idf", "nato",
                                  "government contract", "aerospace"],
    "aerospace":               ["aerospace", "aviation", "aircraft", "space", "satellite",
                                  "defense"],
    "cybersecurity":           ["cyber", "security", "firewall", "encryption",
                                  "threat", "soc", "endpoint"],
    "cyber":                   ["cyber", "security", "firewall", "encryption", "threat"],
    "data center":             ["data center", "cloud", "server", "rack",
                                  "infrastructure", "hyperscaler", "colocation"],
    "military":                ["defense", "military", "weapon", "army", "government"],
}


def _kw_in_sector(kw: str, text: str) -> bool:
    """
    Check that a keyword appears as a whole word in text.
    Short keywords (≤4 chars) use regex word boundaries to avoid false matches
    like 'ai' inside 'retail' or 'chip' inside 'championship'.
    Longer keywords use plain substring matching (fast, no false-positive risk).
    """
    if len(kw) <= 4:
        return bool(re.search(r"\b" + re.escape(kw) + r"\b", text))
    return kw in text


def _get_sector_tier(sector: str, industry: str) -> tuple:
    """
    Classify the company's sector into Tier 1 / Tier 2 / cold / neutral (3).
    Returns (tier: int, matched_label: str).
    """
    combined = f"{(sector or '')} {(industry or '')}".lower()

    # Tier 1: multi-word + long keywords (safe substring), then short whole-word keywords
    for kw in _SECTOR_TIER1_KW:
        if kw in combined:
            return 1, kw
    for kw in _SECTOR_TIER1_WORD_KW:
        if _kw_in_sector(kw, combined):
            return 1, kw

    for kw in _SECTOR_TIER2_KW:
        if kw in combined:
            return 2, kw
    for kw in _SECTOR_COLD_KW:
        if kw in combined:
            return -1, kw
    return 3, ""  # neutral / unrecognized


def _assess_sector_item_direction(item) -> float:
    """
    Keyword-based sentiment for a sector news item.
    SectorNewsItem has no pre-assessed impact field, so we derive direction
    from the title + summary text.
    Returns +1.0 (positive), 0.0 (neutral), or -1.0 (negative) for the sector.
    """
    title   = (getattr(item, "title",   "") or "").lower()
    summary = (getattr(item, "summary", "") or "").lower()
    text    = f"{title} {summary}"
    bull = sum(1 for kw in _SECTOR_BULL_KW if kw in text)
    bear = sum(1 for kw in _SECTOR_BEAR_KW if kw in text)
    if bull >= bear + 1:
        return 1.0
    if bear >= bull + 1:
        return -1.0
    return 0.0


def _company_sector_alignment(stock_data: Any, kw_label: str) -> float:
    """
    Check whether the company actually participates meaningfully in the hot sector.
    Returns a multiplier: 1.0 (confirmed), 0.75 (likely), 0.45 (peripheral).

    Prevents inflating sector heat for companies whose sector label matches but
    whose actual business does not (e.g. a telecom classified under 'Technology').

    Fast path: if the sector keyword itself appears in the industry field → confirmed (1.0).
    This avoids false penalties for companies whose primary SIC is the hot sector.
    """
    if not kw_label or kw_label not in _SECTOR_PARTICIPATION_KW:
        return 1.0  # no specific check available — give full credit

    desc     = (getattr(stock_data, "description", "") or "").lower()
    industry = (getattr(stock_data, "industry",    "") or "").lower()
    sector   = (getattr(stock_data, "sector",      "") or "").lower()

    # Fast path: sector keyword in the industry name → confirmed participant
    if kw_label in industry:
        return 1.0

    combined = f"{desc[:600]} {industry} {sector}"

    # Check participation keywords in company profile
    kws  = _SECTOR_PARTICIPATION_KW[kw_label]
    hits = sum(1 for kw in kws if kw in combined)
    if hits >= 2:
        return 1.0   # confirmed: multiple domain-specific terms found
    if hits == 1:
        return 0.8   # likely: one domain term found
    return 0.45      # peripheral: sector label matches but description does not confirm


def _score_sector_heat(
    stock_data: Any,
    sector_news: list,
    market: str,
) -> ScoreComponent:
    """
    Sector Heat: 0-10  — market-driven, multi-signal.

    Scoring model (4 layers):
      1. Structural sector demand  (0-4):  tier-based baseline reflecting real market reality.
         Tier 1 (AI/semi/defense/cyber) earns 4.0 — these sectors have genuine capital flows.
         Tier 2 (cloud/biotech/fintech)  earns 2.5.
         Neutral                          earns 1.5.
         Cold (real estate/utilities)     earns 0.0.

      2. Sector news flow          (-2 to +3):  keyword-assessed direction × recency.
         Fixes the core problem: SectorNewsItem has no pre-assessed impact field.
         We derive sentiment from title+summary keywords (bull vs. bear count).

      3. Macro regime              (-2 to +3):  VIX + daily index direction.

      4. Validation floors (CRITICAL):
         Tier 1 + positive sector news (≥2 items) → floor at 7.0
         Tier 1 without clear negative evidence   → floor at 6.0
         (Rationale: market reality — AI/semiconductor ARE hot. Do not under-score
          unless explicit negative evidence exists — e.g. sector sell-off + high VIX.)

      Company alignment: if the company's description does not confirm participation
      in its sector keyword, the Tier-1 structural bonus is partially reduced.
    """
    signals: List[str] = []
    sd = stock_data

    sector_str   = getattr(sd, "sector",   "") or ""
    industry_str = getattr(sd, "industry", "") or ""
    tier, kw_label = _get_sector_tier(sector_str, industry_str)

    # ── 1. Structural sector demand baseline ─────────────────────────────────
    if tier == 1:
        struct_pts = 4.0
        signals.append(f"+ Tier-1 sector '{kw_label}' — AI/semiconductor/defense/cyber structural demand")
    elif tier == 2:
        struct_pts = 2.5
        signals.append(f"+ Tier-2 sector '{kw_label or sector_str}' — growing sector tailwind")
    elif tier == -1:
        struct_pts = 1.0
        signals.append(f"- Cold sector '{kw_label}' — structural headwinds (low baseline)")
    else:
        struct_pts = 2.0
        signals.append(f"~ Sector '{sector_str or 'unknown'}' — neutral heat baseline")

    score = struct_pts

    # Company-sector alignment: reduce Tier-1 bonus if company doesn't genuinely participate
    alignment = _company_sector_alignment(sd, kw_label)
    if tier == 1 and alignment < 0.9:
        struct_reduction = (1.0 - alignment) * struct_pts * 0.5
        score -= struct_reduction
        signals.append(
            f"~ Sector alignment {alignment*100:.0f}% — structural bonus reduced "
            f"(company description does not fully confirm {kw_label} participation)"
        )

    # ── 2. Sector news flow ───────────────────────────────────────────────────
    news_sum      = 0.0
    positive_count = 0
    negative_count = 0

    for item in (sector_news or []):
        pub       = getattr(item, "published", None) or getattr(item, "date", None) or ""
        direction = _assess_sector_item_direction(item)
        recency   = _recency_weight(pub)
        news_sum += direction * recency

        title    = (getattr(item, "title", "") or str(item)[:60])
        date_str = str(pub)[:10]
        if direction > 0:
            positive_count += 1
            signals.append(f"+ [sector] [{date_str}] {title[:60]}")
        elif direction < 0:
            negative_count += 1
            signals.append(f"- [sector] [{date_str}] {title[:60]}")

    # Scale: 8 recent positive items → +3 pts; 8 negative → -2 pts
    news_pts = max(-2.0, min(3.0, news_sum * 0.375))
    score += news_pts

    if sector_news:
        if positive_count > 0 or negative_count > 0:
            signals.append(
                f"~ Sector news: {positive_count} positive, {negative_count} negative "
                f"(of {len(sector_news)} items)"
            )
        else:
            signals.append(f"~ Sector news: {len(sector_news)} items — no directional signal")
    else:
        signals.append("~ No sector news available")

    # ── 3. Macro regime ───────────────────────────────────────────────────────
    vix      = getattr(sd, "macro_vix",       None)
    ta125    = getattr(sd, "macro_ta125_chg", None)
    sp500    = getattr(sd, "macro_sp500_chg", None)
    index_chg = ta125 if (market == "il" and ta125 is not None) else sp500

    macro_pts = 0.0
    if vix is not None:
        if vix < 15:
            macro_pts += 1.5; signals.append(f"+ VIX {vix:.0f} (low fear — risk-on)")
        elif vix < 20:
            macro_pts += 1.0; signals.append(f"~ VIX {vix:.0f} (calm backdrop)")
        elif vix < 30:
            macro_pts -= 0.5; signals.append(f"~ VIX {vix:.0f} (elevated uncertainty)")
        else:
            macro_pts -= 2.0; signals.append(f"- VIX {vix:.0f} (risk-off — sector headwind)")
    if index_chg is not None:
        if index_chg > 1.0:
            macro_pts += 1.5; signals.append(f"+ Index +{index_chg:.1f}% (strong backdrop)")
        elif index_chg > 0.2:
            macro_pts += 0.5; signals.append(f"+ Index +{index_chg:.1f}%")
        elif index_chg > -0.2:
            pass  # flat — no signal
        elif index_chg > -1.0:
            macro_pts -= 0.5; signals.append(f"- Index {index_chg:.1f}% (weak market)")
        else:
            macro_pts -= 1.5; signals.append(f"- Index {index_chg:.1f}% (sell-off)")
    macro_pts = max(-2.0, min(3.0, macro_pts))
    score += macro_pts

    score = max(0.0, min(10.0, score))

    # ── 4. Validation floors — market reality enforcement ─────────────────────
    # CRITICAL: known hot sectors must not score below mid-range without clear
    # evidence of a sector downturn. Risk ≠ weak sector.
    if tier == 1:
        # Determine if there is CLEAR negative evidence for a sector reversal
        is_clearly_negative = (
            (vix is not None and vix > 30)
            and (negative_count > positive_count)
        )
        if not is_clearly_negative:
            if positive_count >= 2 and score < 7.0:
                score = 7.0
                signals.append(
                    f"~ Score floored at 7.0: Tier-1 sector with "
                    f"{positive_count} positive sector news items"
                )
            elif score < 6.0:
                score = 6.0
                signals.append(
                    f"~ Score floored at 6.0: Tier-1 sector ({kw_label}) — "
                    f"structural demand is real, no clear negative evidence"
                )

    if not signals:
        signals.append("~ Sector heat data unavailable")

    tier_label = f"T{tier}" if tier > 0 else "cold"
    reasoning = (
        f"Sector heat {score:.1f}/10 — [{tier_label}] '{kw_label or sector_str}' | "
        f"struct {struct_pts:.1f} + news {news_pts:+.1f} + macro {macro_pts:+.1f} | "
        f"{positive_count}pos/{negative_count}neg sector news"
    )
    return ScoreComponent("Sector Heat", score, 10.0, signals[:9], reasoning)


# ── Growth Potential keywords ─────────────────────────────────────────────────
_GROWTH_POS_KW = [
    # Financial momentum
    "revenue growth", "record revenue", "beat expectations", "beats estimates",
    "guidance raised", "guidance upgrade", "double-digit growth", "strong growth",
    "accelerating", "high growth", "profit growth", "earnings beat",
    # Strategic expansion
    "new contract", "backlog", "order book", "new market", "market expansion",
    "international expansion", "product launch", "product launch", "strategic partnership",
    "new customers", "deal won", "win rate", "scalable",
    # AI / innovation / sector tailwinds
    "artificial intelligence", "ai integration", "machine learning", "ai-powered",
    "data center", "cloud adoption", "digital transformation", "innovation",
    "technology adoption", "automation", "next-generation",
]
_GROWTH_NEG_KW = [
    "revenue decline", "revenue miss", "guidance cut", "guidance lowered",
    "loss widening", "slowing growth", "market contraction", "lost contract",
    "churn", "cancelled order", "headcount reduction", "delayed", "writedown",
]
# Maya-specific positive growth title keywords (Hebrew + English)
_MAYA_GROWTH_POS_KW = [
    "חוזה", "הסכם", "התרחבות", "כניסה לשוק", "שותפות", "פריצת דרך",
    "contract", "agreement", "expansion", "new market", "partnership",
    "backlog", "order", "strategic", "joint venture", "technology",
]
_MAYA_GROWTH_NEG_KW = [
    "ביטול", "cancellation", "terminated", "lost", "exit market",
]


def _score_growth(
    stock_data: Any,
    maya_reports: list,
    article_impacts: list,
    agent_outputs: list,
) -> ScoreComponent:
    """
    Growth Potential: 0-15
    Reflects the company's real business direction: financial momentum +
    strategic moves + market opportunity.

    Four signal layers, each contributes independently:
      1. Financial momentum  (0-5)  revenue/earnings trend, PE expansion, price momentum
      2. Maya growth signals (0-4)  expansion/contract/guidance filings
      3. News growth signals (0-4)  AI exposure, new markets, launches, partnerships
      4. Analyst signals     (0-3)  growth-focused mentions in analyst reasoning

    Growth tiers:
      Strong (12-15): 3+ reinforcing signals from different layers
      Moderate (8-12): 2 layers positive, or 1 strong
      Weak (4-8):  limited or inconsistent signals
      None (0-4):  no directional signal

    Validation floor: revenue growth + (AI/innovation OR expansion) -> score >= 9.0
    No penalties for high PE or risk factors (those belong to Risk Adjustment).
    """
    signals: List[str] = []
    score = 0.0
    sd = stock_data

    # Track which layers are positive for tier classification
    fin_positive   = False
    maya_positive  = False
    news_positive  = False
    agent_positive = False

    # ── 1. Financial momentum (0-5) ──────────────────────────────────────────
    fin_pts = 0.0

    # Forward PE vs trailing PE: forward < trailing -> analysts expect EPS growth
    fwd_pe = getattr(sd, "forward_pe", None)
    pe     = getattr(sd, "pe_ratio", None)
    if fwd_pe is not None and pe is not None and pe > 0 and fwd_pe > 0:
        ratio = fwd_pe / pe
        if ratio < 0.75:
            fin_pts += 2.0
            signals.append(f"+ Strong EPS growth expected (fwd PE {fwd_pe:.1f} vs trailing {pe:.1f}, ratio {ratio:.2f})")
        elif ratio < 0.90:
            fin_pts += 1.0
            signals.append(f"+ Moderate EPS growth expected (fwd/trailing ratio {ratio:.2f})")
        elif ratio > 1.15:
            fin_pts -= 0.5
            signals.append(f"~ EPS expected to shrink (fwd PE {fwd_pe:.1f} > trailing {pe:.1f})")

    # 1Y price appreciation: sustained momentum = growth narrative is intact
    pc1y = getattr(sd, "price_change_1y", None)
    if pc1y is not None:
        if pc1y > 50:
            fin_pts += 2.0
            signals.append(f"+ Very strong 1Y price appreciation +{pc1y:.0f}% (growth momentum)")
        elif pc1y > 20:
            fin_pts += 1.5
            signals.append(f"+ Strong 1Y performance +{pc1y:.0f}%")
        elif pc1y > 5:
            fin_pts += 0.5
            signals.append(f"+ Positive 1Y performance +{pc1y:.0f}%")
        elif pc1y < -30:
            fin_pts -= 1.0
            signals.append(f"- Severe 1Y decline {pc1y:.0f}% (growth concerns)")
        elif pc1y < -15:
            fin_pts -= 0.5
            signals.append(f"- 1Y decline {pc1y:.0f}%")

    # 3M momentum: recent acceleration
    pc3m = getattr(sd, "price_change_3m", None)
    if pc3m is not None:
        if pc3m > 20:
            fin_pts += 1.0
            signals.append(f"+ 3M momentum surge +{pc3m:.0f}% (accelerating)")
        elif pc3m > 8:
            fin_pts += 0.5
            signals.append(f"+ 3M momentum +{pc3m:.0f}%")

    # Quarterly earnings: parse for growth/decline keywords
    q_summary = (getattr(sd, "quarterly_earnings_summary", "") or "").lower()
    if q_summary:
        q_pos = sum(1 for kw in ["growth", "increase", "improved", "higher", "beat", "record"] if kw in q_summary)
        q_neg = sum(1 for kw in ["decline", "decrease", "lower", "loss", "miss", "fell"] if kw in q_summary)
        if q_pos >= 2 and q_pos > q_neg:
            fin_pts += 1.5
            signals.append("+ Quarterly earnings show consistent positive trend (2+ growth mentions)")
        elif q_pos > q_neg:
            fin_pts += 0.75
            signals.append("+ Quarterly earnings show improving trend")
        elif q_neg > q_pos + 1:
            fin_pts -= 0.75
            signals.append("- Quarterly earnings show declining trend")

    # Operating margin: healthy margin = growth is profitable, not just top-line
    op_margin = getattr(sd, "operating_margin", None)
    if op_margin is not None:
        if op_margin > 0.20:
            fin_pts += 0.5
            signals.append(f"+ Strong operating margin {op_margin*100:.1f}% (profitable growth)")
        elif op_margin > 0.10:
            fin_pts += 0.25
        elif op_margin < 0:
            fin_pts -= 0.5
            signals.append(f"- Negative operating margin {op_margin*100:.1f}%")

    fin_pts = max(-2.0, min(5.0, fin_pts))
    score  += fin_pts
    if fin_pts >= 1.5:
        fin_positive = True

    # ── 2. Maya growth signals (0-4) ─────────────────────────────────────────
    maya_pts = 0.0
    for rep in (maya_reports or []):
        title  = (getattr(rep, "title", "") or "").lower()
        rtype  = (getattr(rep, "report_type", "") or "").lower()
        impact = (getattr(rep, "impact", "neutral") or "neutral").lower()
        pub    = getattr(rep, "published", None)
        recency = _recency_weight(pub)

        # Tier-aware: use existing classifier
        tier = _classify_filing_tier(title, rtype)

        if rtype in ("guidance", "earnings"):
            if impact == "bullish":
                pts = 2.0 if tier == 1 else 1.5
                maya_pts += pts * recency
                signals.append(f"+ [{rtype.capitalize()} T{tier}] Positive guidance/earnings: {getattr(rep, 'title', '')[:50]}")
            elif impact == "bearish":
                maya_pts -= 1.0 * recency
                signals.append(f"- [{rtype.capitalize()}] Negative guidance")

        if any(kw in title for kw in _MAYA_GROWTH_POS_KW):
            pts = 1.5 if tier == 1 else 1.0
            maya_pts += pts * recency
            signals.append(f"+ Growth filing [T{tier}]: {getattr(rep, 'title', '')[:55]}")
        elif any(kw in title for kw in _MAYA_GROWTH_NEG_KW):
            maya_pts -= 0.8 * recency
            signals.append(f"- Negative filing: {getattr(rep, 'title', '')[:55]}")

    maya_pts = max(-2.0, min(4.0, maya_pts))
    if maya_pts >= 1.0:
        maya_positive = True
    # Secondary source discount: Events/Maya component already scores these filings
    # as its primary signal. Growth takes a 40% share (secondary view: growth direction)
    maya_pts *= 0.6
    score   += maya_pts

    # ── 3. News growth signals (0-4) ─────────────────────────────────────────
    news_pts      = 0.0
    ai_exposure   = False
    expansion_hit = False

    for art in (article_impacts or []):
        title     = (getattr(art, "title", "") or "").lower()
        summary   = (getattr(art, "impact_summary", "") or "").lower()
        reasoning = (getattr(art, "event_reasoning", "") or "").lower()
        sentiment = (getattr(art, "sentiment", "") or "").lower()
        impact    = (getattr(art, "impact", "neutral") or "neutral").lower()
        imp_score = getattr(art, "impact_score", 0) or 0
        pub       = getattr(art, "published", None)
        recency   = _recency_weight(pub)
        combined  = f"{title} {summary} {reasoning}"

        pos_hits = sum(1 for kw in _GROWTH_POS_KW if kw in combined)
        neg_hits = sum(1 for kw in _GROWTH_NEG_KW if kw in combined)
        net      = pos_hits - neg_hits

        # Detect AI/innovation exposure
        if any(kw in combined for kw in ["artificial intelligence", "ai ", " ai ", "machine learning",
                                          "data center", "cloud", "automation", "digital"]):
            ai_exposure = True

        # Detect expansion signals
        if any(kw in combined for kw in ["new market", "expansion", "partnership", "new contract",
                                          "product launch", "international"]):
            expansion_hit = True

        # Score using v2 sentiment if available, else legacy impact
        if sentiment in ("strong_bullish", "bullish"):
            mag = max(0.3, imp_score / 5.0)
            if net > 0:
                news_pts += 1.2 * mag * recency
                signals.append(f"+ Growth signal [{sentiment.upper()}|{imp_score}/5]: {getattr(art, 'title', '')[:50]}")
            else:
                news_pts += 0.6 * mag * recency
        elif sentiment in ("strong_bearish", "bearish"):
            if neg_hits > 0:
                news_pts -= 0.6 * recency
        elif impact == "bullish" and net > 0:
            # Legacy path
            news_pts += 0.8 * recency
            signals.append(f"+ Growth signal in news: {getattr(art, 'title', '')[:50]}")
        elif impact == "bearish" and neg_hits > 0:
            news_pts -= 0.5 * recency

    if ai_exposure:
        signals.append("+ AI/innovation exposure detected in news")
    if expansion_hit:
        signals.append("+ Market expansion or partnership signals in news")

    news_pts = max(-2.0, min(4.0, news_pts))
    if news_pts >= 0.8:
        news_positive = True
    # Secondary source discount: News & Sentiment component already scores these articles
    # as its primary signal. Growth takes a 50% share (secondary view: growth direction)
    news_pts *= 0.5
    score   += news_pts

    # ── 4. Analyst growth signals (0-3) ──────────────────────────────────────
    agent_pts   = 0.0
    conv_map    = {"high": 1.0, "moderate": 0.75, "low": 0.5}

    for out in (agent_outputs or []):
        stance   = (getattr(out, "stance", "") or "").lower()
        conf     = (getattr(out, "confidence", "moderate") or "moderate").lower()
        analysis = (
            (getattr(out, "full_reasoning", "") or "") + " " +
            (getattr(out, "key_finding", "") or "")
        ).lower()
        w = conv_map.get(conf, 0.75)

        pos_hits = sum(1 for kw in _GROWTH_POS_KW if kw in analysis)
        neg_hits = sum(1 for kw in _GROWTH_NEG_KW if kw in analysis)
        net_kw   = pos_hits - neg_hits

        if stance == "bullish":
            base = 0.6 * w
        elif stance == "bearish":
            base = -0.3 * w
        else:
            base = 0.0

        kw_bonus = max(-0.4, min(0.6, net_kw * 0.12)) * w
        agent_pts += base + kw_bonus

    agent_pts = max(-1.5, min(3.0, agent_pts))
    score    += agent_pts
    if agent_pts >= 0.6:
        agent_positive = True

    # ── Growth tier classification ────────────────────────────────────────────
    positive_layers = sum([fin_positive, maya_positive, news_positive, agent_positive])

    if positive_layers >= 3:
        tier_label = "STRONG GROWTH"
    elif positive_layers == 2:
        tier_label = "MODERATE GROWTH"
    elif positive_layers == 1:
        tier_label = "WEAK GROWTH"
    else:
        tier_label = "NO CLEAR GROWTH"

    signals.insert(0, f"Growth tier: {tier_label} ({positive_layers}/4 layers positive)")

    if not signals[1:]:
        signals.append("~ No growth signals detected — limited data")

    # ── Base shift: neutral = 6.0 ─────────────────────────────────────────────
    # Raw score range: ~[-5, +16]. Shift by +2 so zero-signal lands near 6.
    raw = score + 2.0
    final = max(0.0, min(15.0, raw))

    # ── Validation floor ──────────────────────────────────────────────────────
    # A company showing financial momentum AND (AI/innovation OR expansion) must
    # not score below mid-range regardless of signal weight.
    has_fin_momentum = (
        (pc1y is not None and pc1y > 10) or
        (fwd_pe is not None and pe is not None and pe > 0 and fwd_pe > 0 and fwd_pe / pe < 0.92) or
        fin_pts >= 1.0
    )
    has_innovation_or_expansion = ai_exposure or expansion_hit or maya_positive

    if has_fin_momentum and has_innovation_or_expansion and final < 9.0:
        final = 9.0
        signals.append(
            "~ Growth floored at 9.0: financial momentum + AI/innovation or expansion signals"
        )
    elif positive_layers >= 3 and final < 11.0:
        final = 11.0
        signals.append(
            "~ Growth floored at 11.0: 3+ reinforcing layers (strong multi-signal growth)"
        )

    reasoning = (
        f"Growth potential {final:.1f}/15 | {tier_label} | "
        f"fin {fin_pts:+.1f}  maya {maya_pts:+.1f}  news {news_pts:+.1f}  agents {agent_pts:+.1f}"
    )
    return ScoreComponent("Growth Potential", final, 15.0, signals[:10], reasoning)


def _compute_analyst_eq(out) -> float:
    """
    Evidence Quality score 0-5 for a single AgentOutput.

    Two components:
      A) Evidence list quality  -- count + source/relevance ratings
      B) Reasoning keyword density -- financial/data terms in full_reasoning + key_finding

    Cap at 5.0.
    """
    # A: Evidence list
    evidence = getattr(out, "evidence", None) or []
    n = len(evidence)
    if n == 0:
        base = 0.0
    elif n == 1:
        base = 0.5
    elif n == 2:
        base = 1.0
    else:
        base = 1.5  # 3+ items

    item_bonus = 0.0
    _STRONG_SOURCES = {"maya", "filing", "financial", "earnings", "yfinance",
                       "guidance", "backlog", "contract", "balance sheet", "cash flow"}
    for item in evidence:
        src = (getattr(item, "source", "") or "").lower()
        rel = (getattr(item, "relevance", "") or "").lower()
        if any(kw in src for kw in _STRONG_SOURCES):
            item_bonus += 0.4
        if rel == "high":
            item_bonus += 0.2

    eq_a = min(3.5, base + item_bonus)

    # B: Reasoning keyword density
    _REASONING_KW = [
        "revenue", "earnings", "eps", "margin", "guidance", "backlog",
        "contract", "filing", "maya", "%", "million", "billion",
        "cash flow", "balance sheet", "pe ratio", "ebitda", "quarterly",
        "year-over-year", "yoy", "beat", "miss", "raised", "lowered",
    ]
    text = (
        (getattr(out, "full_reasoning", "") or "") + " " +
        (getattr(out, "key_finding", "") or "")
    ).lower()
    hits = sum(1 for kw in _REASONING_KW if kw in text)
    eq_b = min(1.5, hits * 0.15)

    return min(5.0, eq_a + eq_b)


def _score_consensus(
    agent_outputs: list,
    synthesis: Any,
    evidence_strength: float = 1.0,
) -> ScoreComponent:
    """
    Analyst Consensus: 0-15
    Evidence-weighted scoring -- analysts with strong data references count more.

    Formula per analyst:
      direction:   bullish=+1, bearish=-1, mixed/neutral=0
      conviction:  high=1.0, moderate=0.75, low=0.5
      eq:          evidence quality 0-5 (from _compute_analyst_eq)
      contribution = direction * eq * conviction

    Aggregation:
      bull_strength = sum of positive contributions
      bear_strength = sum of abs(negative contributions)
      net_lean      = bull_strength - bear_strength
      max_net       = max(n_analysts * 3.5, 10.0)
      raw_score     = 7.5 + (net_lean / max_net) * 7.5

    Tension penalty: proportional, reduced when consensus is strong.

    Amplifier gate:
      evidence_strength < 0.30 -> cap 7.5
      evidence_strength < 0.55 -> cap ramps 7.5..15
    """
    signals: List[str] = []

    _CONVICTION = {"high": 1.0, "moderate": 0.75, "low": 0.5}

    bull_strength = 0.0
    bear_strength = 0.0
    neutral_drag  = 0.0
    analyst_rows: list = []

    # Pre-compute severity profile for all analysts
    risk_profile = _compute_analyst_risk_profile(agent_outputs)
    severity_map = risk_profile["analyst_severity_map"]

    for out in (agent_outputs or []):
        name    = (getattr(out, "agent_name", "") or "analyst").strip()
        stance  = (getattr(out, "stance", "") or "").lower()
        conf    = (getattr(out, "confidence", "moderate") or "moderate").lower()
        conv    = _CONVICTION.get(conf, 0.75)
        eq      = _compute_analyst_eq(out)

        if stance == "bullish":
            direction = 1
        elif stance == "bearish":
            direction = -1
        else:
            direction = 0  # neutral / mixed

        # Severity amplification: bearish/mixed analysts with high-severity risks
        # contribute more to bear_strength — their warning cannot be diluted by votes
        severity = severity_map.get(name, "low")
        sev_mult = _SEVERITY_MULTIPLIER.get(severity, 1.0) if direction <= 0 else 1.0

        contribution = direction * eq * conv * sev_mult

        if direction > 0:
            bull_strength += contribution
        elif direction < 0:
            bear_strength += abs(contribution)
        else:
            # Neutral/mixed: severity-amplified drag — high-severity concerns still count
            neutral_drag += eq * conv * 0.15 * sev_mult

        analyst_rows.append((name, stance, eq, conv, contribution, severity))

    n_analysts  = max(1, len(agent_outputs or []))
    net_lean    = bull_strength - bear_strength
    max_net     = max(n_analysts * 3.5, 10.0)
    raw_score   = 7.5 + (net_lean / max_net) * 7.5

    # Tension penalty: proportional, softened when strong consensus exists
    tensions = getattr(synthesis, "unresolved_tensions", []) if synthesis else []
    base_penalty     = min(3.0, len(tensions) * 0.6)
    strong_consensus = abs(net_lean) > max_net * 0.4
    tension_penalty  = base_penalty * (0.6 if strong_consensus else 1.0)

    # Neutral drag: mild dampener when many analysts sit on the fence
    raw_score -= min(1.5, neutral_drag)

    score = max(0.0, min(15.0, raw_score - tension_penalty))

    # Per-analyst count labels
    bull_n = sum(1 for _, s, *_ in analyst_rows if s == "bullish")
    bear_n = sum(1 for _, s, *_ in analyst_rows if s == "bearish")
    neut_n = n_analysts - bull_n - bear_n

    # Signals
    lean_label = (
        "STRONG BULL" if net_lean > max_net * 0.5 else
        "BULL"        if net_lean > max_net * 0.2 else
        "STRONG BEAR" if net_lean < -max_net * 0.5 else
        "BEAR"        if net_lean < -max_net * 0.2 else
        "NEUTRAL"
    )
    signals.append(
        f"Analyst votes: {bull_n} bullish / {bear_n} bearish / {neut_n} neutral | "
        f"net lean: {lean_label} ({net_lean:+.1f})"
    )
    signals.append(
        f"Bull strength: {bull_strength:.1f}  Bear strength: {bear_strength:.1f}  "
        f"Net: {net_lean:+.1f} / max {max_net:.1f}"
    )
    if tension_penalty > 0:
        signals.append(
            f"- {len(tensions)} unresolved tensions "
            f"(-{tension_penalty:.1f} pts{'  [reduced -- strong consensus]' if strong_consensus else ''})"
        )
    if neutral_drag > 0.1:
        signals.append(f"~ Neutral/mixed drag: -{min(1.5, neutral_drag):.1f}")

    # Severity signals
    if risk_profile["high_signals"]:
        n_high = len(risk_profile["high_signals"])
        signals.append(
            f"! HIGH severity risk(s) detected ({n_high} analyst(s)) — "
            f"bear_strength amplified ×{_SEVERITY_MULTIPLIER['high']}"
        )
    if risk_profile["medium_signals"]:
        n_med = len(risk_profile["medium_signals"])
        signals.append(
            f"~ MEDIUM severity risk(s) detected ({n_med} analyst(s)) — "
            f"bear_strength amplified ×{_SEVERITY_MULTIPLIER['medium']}"
        )

    # Top-3 analysts by EQ score (now includes severity)
    top3 = sorted(analyst_rows, key=lambda r: r[2], reverse=True)[:3]
    for a_name, a_stance, a_eq, a_conv, a_contrib, a_sev in top3:
        sev_tag = f" [{a_sev.upper()}]" if a_sev != "low" else ""
        signals.append(
            f"  {a_name[:32]:<32} | {a_stance.upper():<8} | EQ {a_eq:.1f}/5 | "
            f"conv {a_conv:.2f} | contrib {a_contrib:+.2f}{sev_tag}"
        )

    overall_lean = getattr(synthesis, "overall_lean", "neutral") if synthesis else "neutral"
    signals.append(f"Synthesis lean: {overall_lean.upper()}")

    score = max(0.0, min(15.0, score))

    # HIGH severity risk override: a single high-severity analyst cannot be ignored
    # even when the bullish majority dominates the raw score.
    n_high_analysts = len(risk_profile["high_signals"])
    if n_high_analysts >= 2 and score > 9.0:
        score = 9.0
        signals.append(
            f"! Consensus capped at 9.0: {n_high_analysts} analysts flagged HIGH severity risk "
            f"(structural/regulatory/debt — bullish majority cannot override)"
        )
    elif n_high_analysts == 1 and score > 11.0:
        score = 11.0
        signals.append(
            f"! Consensus capped at 11.0: 1 analyst flagged HIGH severity risk "
            f"(override: single critical risk cannot be diluted)"
        )

    # Amplifier gate: consensus only counts when objective evidence exists
    _WEAK_EV   = 0.30
    _MEDIUM_EV = 0.55

    if evidence_strength < _WEAK_EV:
        cap = 7.5
        if score > cap:
            score = cap
            signals.append(
                f"~ Consensus capped at {cap} (objective evidence too weak -- "
                f"financial + events + news combined only {evidence_strength*50:.0f}/50)"
            )
    elif evidence_strength < _MEDIUM_EV:
        ramp = (evidence_strength - _WEAK_EV) / (_MEDIUM_EV - _WEAK_EV)
        cap = 7.5 + ramp * 7.5
        if score > cap:
            score = cap
            signals.append(
                f"~ Consensus partially capped at {cap:.1f} "
                f"(moderate objective evidence {evidence_strength*50:.0f}/50)"
            )

    reasoning = (
        f"Consensus {score:.1f}/15 -- {bull_n}B/{bear_n}Be/{neut_n}N | "
        f"bull {bull_strength:.1f} vs bear {bear_strength:.1f} | "
        f"{len(tensions)} tensions (-{tension_penalty:.1f})"
    )
    return ScoreComponent("Analyst Consensus", score, 15.0, signals, reasoning)


# ── Risk severity classification ─────────────────────────────────────────────

_RISK_HIGH_KW = [
    # Financial distress
    "unsustainable debt", "debt crisis", "covenant breach", "default risk", "insolvency",
    "bankruptcy", "going concern",
    # Regulatory / legal
    "regulatory ban", "license revocation", "sec investigation", "criminal", "fraud",
    "regulatory action", "regulatory threat", "class action",
    # Structural
    "structural weakness", "structural decline", "existential risk", "existential threat",
    "collapse", "severe", "critical risk", "major lawsuit",
    # Business
    "major business risk", "unsustainable model", "fundamental flaw",
]
_RISK_MEDIUM_KW = [
    "slowing growth", "growth slowdown", "margin pressure", "margin compression",
    "dependency", "concentration risk", "customer concentration", "key man risk",
    "execution risk", "competitive pressure", "market share loss", "debt load",
    "rising costs", "supply chain risk", "geopolitical", "currency risk", "refinancing",
    "regulatory pressure", "regulatory headwind", "significant competition",
    "delayed", "integration risk", "macro sensitivity",
]
_RISK_LOW_KW = [
    "valuation", "high pe", "overvalued", "competition", "volatile", "volatility",
    "uncertainty", "minor risk", "slight concern", "interest rate", "macro headwind",
    "slowing", "some risk",
]

# How much to amplify a bearish analyst's contribution based on their risk severity
_SEVERITY_MULTIPLIER = {"high": 2.5, "medium": 1.5, "low": 1.0}


def _classify_risk_severity(text: str) -> str:
    """
    Classify a risk statement as 'high', 'medium', or 'low'.
    Checked in priority order: high → medium → low → default low.
    """
    t = (text or "").lower()
    if any(kw in t for kw in _RISK_HIGH_KW):
        return "high"
    if any(kw in t for kw in _RISK_MEDIUM_KW):
        return "medium"
    if any(kw in t for kw in _RISK_LOW_KW):
        return "low"
    return "low"  # default: treat unknown risk claims as low


def _compute_analyst_risk_profile(agent_outputs: list) -> dict:
    """
    Scan ALL analyst outputs for risk signals, classify by severity.

    Sources scanned (in order of reliability):
      1. flags_for_committee — explicit risk flags raised for the committee
      2. key_unknowns        — gaps the analyst flagged as dangerous
      3. key_finding         — top-line summary (contains risk language for bearish analysts)
      4. full_reasoning      — full narrative (for bearish/mixed analysts only)

    Returns a dict:
      {
        "max_severity":  "high" | "medium" | "low",
        "high_signals":  List[str],   # text snippets that triggered HIGH
        "medium_signals": List[str],
        "low_signals":   List[str],
        "analyst_severity_map": {agent_name: severity}
      }
    """
    high_signals:   List[str] = []
    medium_signals: List[str] = []
    low_signals:    List[str] = []
    analyst_severity_map: dict = {}

    for out in (agent_outputs or []):
        name    = (getattr(out, "agent_name", "") or "analyst").strip()
        stance  = (getattr(out, "stance", "") or "").lower()

        # Gather risk text from all sources
        risk_texts = []
        for flag in (getattr(out, "flags_for_committee", []) or []):
            risk_texts.append(str(flag))
        for unk in (getattr(out, "key_unknowns", []) or []):
            risk_texts.append(str(unk))
        # For bearish/mixed analysts also check their finding and reasoning
        if stance in ("bearish", "mixed", "neutral"):
            risk_texts.append(getattr(out, "key_finding", "") or "")
            risk_texts.append(getattr(out, "full_reasoning", "") or "")

        worst = "low"
        worst_text = ""
        for text in risk_texts:
            sev = _classify_risk_severity(text)
            if sev == "high" and worst != "high":
                worst = "high"; worst_text = text[:120]
            elif sev == "medium" and worst == "low":
                worst = "medium"; worst_text = text[:120]

        analyst_severity_map[name] = worst

        if worst == "high":
            high_signals.append(f"{name}: {worst_text}")
        elif worst == "medium":
            medium_signals.append(f"{name}: {worst_text}")
        else:
            low_signals.append(name)

    max_severity = (
        "high"   if high_signals else
        "medium" if medium_signals else
        "low"
    )

    return {
        "max_severity":         max_severity,
        "high_signals":         high_signals,
        "medium_signals":       medium_signals,
        "low_signals":          low_signals,
        "analyst_severity_map": analyst_severity_map,
    }


def _score_risk_adjustment(
    stock_data: Any,
    maya_reports: list,
    market: str,
    agent_outputs: Optional[list] = None,
) -> ScoreComponent:
    """
    Risk Adjustment: -10 to 0
    Checks:
      - Financial: dilution in Maya, high leverage, negative margins, elevated VIX
      - Analyst-identified: HIGH/MEDIUM severity risks from flags_for_committee and key_unknowns
        HIGH severity: -2 to -4 (can override bullish consensus)
        MEDIUM severity: -0.5 to -1.5 (moderate reduction)
        LOW severity: no penalty (reduces conviction only, handled in consensus)
    """
    signals: List[str] = []
    penalty = 0.0
    sd = stock_data

    # ── 1. Financial data risks ───────────────────────────────────────────────
    de = getattr(sd, "debt_to_equity", None)
    if de is not None and de > 3.0:
        penalty -= 3.0
        signals.append(f"- High leverage D/E {de:.1f} (risk-off penalty)")

    om = getattr(sd, "operating_margin", None)
    if om is not None and om < 0:
        penalty -= 2.0
        signals.append(f"- Operating loss margin {om*100:.0f}% (viability risk)")

    vix = getattr(sd, "macro_vix", None)
    if vix is not None and vix > 30:
        penalty -= 2.0
        signals.append(f"- VIX {vix:.0f} > 30 (systemic risk environment)")

    for rep in (maya_reports or []):
        title = (getattr(rep, "title", "") or "").lower()
        if any(k in title for k in ["הצעת זכויות", "rights offering", "dilution",
                                     "הרחבת סדרה", "new shares"]):
            penalty -= 2.0
            signals.append(f"- Possible dilution: {getattr(rep, 'title', '')[:60]}")
            break

    # ── 2. Analyst-identified risks (severity-aware) ──────────────────────────
    if agent_outputs:
        risk_profile = _compute_analyst_risk_profile(agent_outputs)
        max_sev = risk_profile["max_severity"]

        if risk_profile["high_signals"]:
            n_high = len(risk_profile["high_signals"])
            # 1 HIGH signal → -2; 2+ → -4; diminishing returns above 2
            high_pen = min(4.0, 2.0 + (n_high - 1) * 1.0)
            penalty -= high_pen
            for sig in risk_profile["high_signals"][:3]:
                signals.append(f"- [HIGH RISK] {sig[:100]}")
            signals.append(
                f"- Analyst HIGH severity risk override: -{high_pen:.1f} pts "
                f"({n_high} analyst(s) flagged structural/regulatory/debt risk)"
            )

        if risk_profile["medium_signals"]:
            n_med = len(risk_profile["medium_signals"])
            med_pen = min(1.5, 0.5 * n_med)
            penalty -= med_pen
            for sig in risk_profile["medium_signals"][:2]:
                signals.append(f"~ [MEDIUM RISK] {sig[:100]}")

        if not risk_profile["high_signals"] and not risk_profile["medium_signals"] and risk_profile["low_signals"]:
            signals.append(
                f"~ {len(risk_profile['low_signals'])} analyst(s) flagged LOW severity risks "
                f"(valuation/competition/volatility — no penalty, reduces conviction only)"
            )

    if not signals:
        signals.append("~ No material risk flags detected")

    penalty = max(-10.0, min(0.0, penalty))
    reasoning = (
        f"Risk adjustment {penalty:.1f} — financial data + "
        f"analyst severity-weighted risk flags"
    )
    return ScoreComponent("Risk Adjustment", penalty, 0.0, signals, reasoning)


# ── Positive signal boosts ────────────────────────────────────────────────────
# Boosts reward genuine evidence convergence. Each boost requires specific, measurable
# conditions — no boost fires without real data. Hard constraints still apply after.

def _boost_event_momentum(maya_reports: list, events_score: float) -> Optional[ScoreBoost]:
    """
    Event Momentum: +5 to +10
    Triggered by ≥2 recent Tier 1/2 bullish Maya filings (within last 14 days).
    Tier 3 (appointments, dividends, admin) does NOT qualify — only real strategic
    or operational events count.
    Requires events_score ≥ 10 (overall events context is not negative).
    """
    if events_score < 10.0:
        return None  # overall event context is neutral/negative — no momentum

    recent_bullish: List[str] = []
    for rep in (maya_reports or []):
        impact = (getattr(rep, "impact", "") or "").lower()
        pub    = getattr(rep, "published", None)
        title  = getattr(rep, "title", "") or ""
        rtype  = getattr(rep, "report_type", "other") or "other"

        # Only Tier 1 and Tier 2 events qualify for momentum boost
        tier = _classify_filing_tier(title, rtype)
        if impact == "bullish" and tier <= 2 and _recency_weight(pub) >= 0.7:
            recent_bullish.append(title or "filing")

    if len(recent_bullish) < 2:
        return None

    # 2 filings → +5.0; each additional adds +1.5, capped at +10
    pts = min(10.0, 5.0 + (len(recent_bullish) - 2) * 1.5)
    triggered = [f"Recent Tier-1/2 bullish filing: {t[:65]}" for t in recent_bullish[:4]]
    return ScoreBoost(
        name="Event Momentum",
        points=round(pts, 1),
        max_points=10.0,
        reason=f"{len(recent_bullish)} recent Tier-1/2 bullish filings in past 14 days",
        triggered_by=triggered,
    )


def _boost_growth_confirmation(
    growth_score:    float,
    financial_score: float,
    events_score:    float,
    news_score:      float,
) -> Optional[ScoreBoost]:
    """
    Growth Confirmation: +5 to +8
    Triggered when growth evidence (score ≥ 8) is corroborated by at least one
    other independent signal (strong events, strong news, or strong financials).
    Prevents growth narrative from being believed without corroboration.
    """
    if growth_score < 8.0:
        return None

    has_event_support = events_score >= 11.0
    has_news_support  = news_score  >= 6.5
    has_fin_support   = financial_score >= 12.0

    n_supporting = sum([has_event_support, has_news_support, has_fin_support])
    if n_supporting < 1:
        return None  # growth alone without any corroboration — no boost

    # 1 supporting signal → +5.0, 2 → +6.5, 3 → +8.0
    pts = min(8.0, 5.0 + (n_supporting - 1) * 1.5)
    triggered = []
    if has_fin_support:   triggered.append(f"Financial Strength {financial_score:.1f}/20 (≥12)")
    if has_event_support: triggered.append(f"Events/Maya {events_score:.1f}/20 (≥11)")
    if has_news_support:  triggered.append(f"News Sentiment {news_score:.1f}/10 (≥6.5)")

    return ScoreBoost(
        name="Growth Confirmation",
        points=round(pts, 1),
        max_points=8.0,
        reason=f"Growth evidence ({growth_score:.1f}/15) confirmed by {n_supporting} independent signal(s)",
        triggered_by=[f"Growth score: {growth_score:.1f}/15"] + triggered,
    )


def _boost_analyst_alignment(
    consensus_score:  float,
    evidence_strength: float,
    agent_outputs:    list,
) -> Optional[ScoreBoost]:
    """
    Analyst Alignment: +3 to +6
    Triggered when ≥60% of analysts are bullish AND objective evidence strength ≥ 0.50.
    Analysts amplify evidence — they cannot manufacture a boost independently.
    """
    if not agent_outputs:
        return None
    if consensus_score < 8.0:
        return None  # consensus itself is weak — nothing to amplify

    bull_n  = sum(1 for o in agent_outputs if (getattr(o, "stance", "") or "").lower() == "bullish")
    total_n = len(agent_outputs)
    bull_pct = bull_n / total_n

    if bull_pct < 0.60 or evidence_strength < 0.50:
        return None  # insufficient consensus or evidence base

    # Scale with both alignment strength and evidence quality
    alignment_factor = min(1.0, (bull_pct - 0.60) / 0.40)   # 0 at 60%, 1.0 at 100%
    evidence_factor  = min(1.0, (evidence_strength - 0.50) / 0.50)  # 0 at 50%, 1.0 at 100%
    pts = 3.0 + alignment_factor * 2.0 + evidence_factor * 1.0
    pts = min(6.0, pts)

    return ScoreBoost(
        name="Analyst Alignment",
        points=round(pts, 1),
        max_points=6.0,
        reason=f"{bull_n}/{total_n} analysts bullish ({bull_pct*100:.0f}%) with evidence support",
        triggered_by=[
            f"{bull_n}/{total_n} bullish analysts ({bull_pct*100:.0f}%)",
            f"Objective evidence strength: {evidence_strength*50:.0f}/50",
            f"Consensus score: {consensus_score:.1f}/15",
        ],
    )


def _boost_sector_tailwind(
    sector_heat_score: float,
    sector_news:       list,
) -> Optional[ScoreBoost]:
    """
    Sector Tailwind: +3 to +5
    Triggered when sector heat ≥ 7.0 AND at least one positive sector news item exists.

    Uses keyword-based direction assessment (_assess_sector_item_direction) because
    SectorNewsItem objects do not carry a pre-assessed impact field — checking
    item.impact or item.sentiment would always return "neutral" and suppress this boost.
    """
    if sector_heat_score < 7.0:
        return None

    positive_news: List[str] = []
    for item in (sector_news or []):
        direction = _assess_sector_item_direction(item)
        if direction > 0:
            positive_news.append(getattr(item, "title", "") or str(item)[:55])

    if not positive_news:
        return None  # no real news support — sector keyword alone not enough

    # sector heat 7.0 → +3.0, 10.0 → +5.0
    pts = min(5.0, 3.0 + (sector_heat_score - 7.0) / 3.0 * 2.0)

    return ScoreBoost(
        name="Sector Tailwind",
        points=round(pts, 1),
        max_points=5.0,
        reason=f"Sector heat {sector_heat_score:.1f}/10 backed by {len(positive_news)} bullish news item(s)",
        triggered_by=[
            f"Sector heat: {sector_heat_score:.1f}/10",
            *[f"Bullish sector news: {t[:65]}" for t in positive_news[:2]],
        ],
    )


def _boost_news_momentum(
    article_impacts: list,
    news_score: float,
    news_strength: float = 0.0,
) -> Optional[ScoreBoost]:
    """
    News Momentum Boost: +2 to +6.

    Derived from news_strength — the same raw signal that drives news_score.
    Both use _compute_news_strength() as their source, so they can NEVER
    contradict each other.

    Boost tiers (aligned with news_score normalisation scale, impact_score-direct formula):
      news_strength >= 20  ->  +6.0   (news_score ~ 9.5)
      news_strength >= 10  ->  +4.0   (news_score ~ 7.3)
      news_strength >= 5   ->  +2.0   (news_score ~ 6.1)
      news_strength <  5   ->  no boost

    By construction:
      boost >= 4  ->  news_strength >= 10  ->  news_score >= 7.3  (spec: must be >= 7)
      news_score < 6  ->  news_strength < 4.4  ->  boost = 0      (spec: must be low/zero)

    Requires news_score >= 5.0 as secondary gate.
    Reduced by 2 pts if strong bearish counterbalance exists.
    """
    if news_score < 5.0:
        return None

    # Derive boost directly from news_strength (same input as news_score)
    if news_strength >= 20.0:
        pts = 6.0
    elif news_strength >= 10.0:
        pts = 4.0
    elif news_strength >= 5.0:
        pts = 2.0
    else:
        return None

    # Counterbalance: high-impact bearish articles reduce the boost
    arts = article_impacts or []
    high_bear = [
        a for a in arts
        if (getattr(a, "impact_score", 0) or 0) >= 4
        and (getattr(a, "sentiment", "") or "") in ("strong_bearish", "bearish")
    ]
    counterbalance_note = ""
    if len(high_bear) >= 2:
        pts = max(0.5, pts - 2.0)
        counterbalance_note = f" (reduced: {len(high_bear)} high-impact bearish offset)"

    # Build triggered_by from top bullish articles (transparency only — not used for scoring)
    high_bull = sorted(
        [a for a in arts
         if (getattr(a, "sentiment", "") or "") in ("strong_bullish", "bullish")
         and (getattr(a, "impact_score", 0) or 0) >= 3],
        key=lambda a: (getattr(a, "impact_score", 0) or 0),
        reverse=True,
    )
    triggered = [
        f"[{(getattr(a, 'sentiment', '') or '').upper()}|{getattr(a, 'impact_score', 0)}/5] "
        f"{(getattr(a, 'title', '') or '')[:55]}"
        for a in high_bull[:4]
    ] or [f"news_strength={news_strength:.2f}"]

    return ScoreBoost(
        name="News Momentum",
        points=round(pts, 1),
        max_points=6.0,
        reason=f"news_strength={news_strength:.2f} -> +{pts:.1f}pts{counterbalance_note}",
        triggered_by=triggered,
    )


def _boost_news_cross_component(
    article_impacts: list,
    news_score:      float,
    growth_score:    float,
    events_score:    float,
    sector_score:    float,
    news_strength:   float = 0.0,
) -> Optional[ScoreBoost]:
    """
    News Cross-Component Amplifier: +1.5 to +5
    Fires when bullish news content aligns with other strong scoring components.

      Growth news (>=2 articles) + growth score >=8    -> +2.0
      Growth news (>=1 article)  + growth score >=9.5  -> +1.0
      Partnership/contract news + events score >=8    -> +2.0
      Sector/AI news            + sector score >=7    -> +1.5

    Requires news_score >= 5.0 AND news_strength >= 2.0 (news must genuinely be positive).
    """
    if news_score < 5.0:
        return None
    if news_strength < 2.0:
        return None

    _GROWTH_KW   = ["growth", "expansion", "revenue", "earnings", "backlog", "guidance",
                    "revenue growth", "record revenue"]
    _PARTNER_KW  = ["partnership", "collaboration", "contract", "deal", "agreement",
                    "nvidia", "intel", "microsoft", "google", "amazon"]
    _SECTOR_KW   = ["ai ", "artificial intelligence", "semiconductor", "defense",
                    "cyber", "cloud", "data center"]

    growth_arts  = 0
    partner_arts = 0
    sector_arts  = 0

    for art in (article_impacts or []):
        sent = (getattr(art, "sentiment", "") or "").lower()
        if sent not in ("strong_bullish", "bullish"):
            continue
        combined = (
            (getattr(art, "title", "") or "") + " " +
            (getattr(art, "event_type", "") or "") + " " +
            (getattr(art, "event_reasoning", "") or "")
        ).lower()
        if any(kw in combined for kw in _GROWTH_KW):
            growth_arts += 1
        if any(kw in combined for kw in _PARTNER_KW):
            partner_arts += 1
        if any(kw in combined for kw in _SECTOR_KW):
            sector_arts += 1

    triggered = []
    pts = 0.0

    if growth_arts >= 2 and growth_score >= 8.0:
        pts += 2.0
        triggered.append(f"Growth news ({growth_arts} articles) + Growth score {growth_score:.1f}/15")
    elif growth_arts >= 1 and growth_score >= 9.5:
        pts += 1.0
        triggered.append(f"Growth news aligned with strong growth score {growth_score:.1f}/15")

    if partner_arts >= 1 and events_score >= 8.0:
        pts += 2.0
        triggered.append(f"Partnership/contract news ({partner_arts} articles) + Maya events {events_score:.1f}/20")

    if sector_arts >= 1 and sector_score >= 7.0:
        pts += 1.5
        triggered.append(f"Sector/AI news ({sector_arts} articles) + Sector heat {sector_score:.1f}/10")

    if pts < 1.0 or not triggered:
        return None

    pts = min(5.0, pts)
    return ScoreBoost(
        name="News Cross-Component",
        points=round(pts, 1),
        max_points=5.0,
        reason=f"News content aligns with {len(triggered)} other scoring component(s)",
        triggered_by=triggered,
    )


def _news_bearish_penalty(article_impacts: list, news_score: float) -> float:
    """
    Strong negative news penalty: 0 to -5
    Applied when multiple high-impact bearish articles exist.
    Separate from the raw news score — this is a cross-cutting deduction.

      1 high-impact bearish (≥4)  → -2.0
      2 high-impact bearish       → -3.5
      3+ high-impact bearish      → -5.0

    Reduced by half if strong bullish news counterbalances.
    Not applied if news_score is already very low (< 3.5) — penalty already baked in.
    """
    if news_score < 3.5:
        return 0.0   # already low — don't double-penalize

    arts = article_impacts or []
    high_bear = [
        a for a in arts
        if (getattr(a, "impact_score", 0) or 0) >= 4
        and (getattr(a, "sentiment", "") or "") in ("strong_bearish", "bearish")
    ]
    n = len(high_bear)
    if n == 0:
        return 0.0

    if n >= 3:
        penalty = 5.0
    elif n == 2:
        penalty = 3.5
    else:
        penalty = 2.0

    # Reduce if strong bull counterbalances
    high_bull_n = sum(
        1 for a in arts
        if (getattr(a, "impact_score", 0) or 0) >= 4
        and (getattr(a, "sentiment", "") or "") in ("strong_bullish", "bullish")
    )
    if high_bull_n >= n:
        penalty *= 0.5   # counterbalanced — halve the penalty

    return -round(penalty, 1)


def _apply_boost_deduplication(
    b_event:         Optional[ScoreBoost],
    b_growth:        Optional[ScoreBoost],
    b_align:         Optional[ScoreBoost],
    b_sector:        Optional[ScoreBoost],
    b_news_momentum: Optional[ScoreBoost],
    b_news_cross:    Optional[ScoreBoost],
) -> tuple:
    """
    Prevent double-counting of the same signal across multiple boosts.

    Sibling pairs (share a primary signal source):

    1. News Momentum + News Cross-Component
       Both fire from article_impacts. If both active, Cross-Component gets 50% discount.

    2. Event Momentum + Growth Confirmation
       Event Momentum fires for strong Maya filings; Growth Confirmation checks
       events_score >= 11 (achieved by those same filings).
       If Event Momentum fires, Growth Confirmation gets 40% discount.

    3. News Momentum + Growth Confirmation (news path only, no Event sibling)
       News Momentum fires for strong articles; Growth Confirmation partially triggered
       by news_score >= 6.5 (same articles). 30% partial discount.

    Hard cap: total boosts <= 18 pts.
    Returns (List[ScoreBoost], List[str] dedup_notes).
    """
    _BOOST_HARD_CAP = 18.0
    dedup_notes: List[str] = []

    # Collect all non-None boosts, work with mutable dicts
    def _clone(b: ScoreBoost, new_pts: float, note: str) -> ScoreBoost:
        return ScoreBoost(
            name=b.name,
            points=round(new_pts, 1),
            max_points=b.max_points,
            reason=b.reason + f" [{note}]",
            triggered_by=b.triggered_by,
        )

    # Rule 1: News Momentum + News Cross-Component
    final_news_cross = b_news_cross
    if b_news_momentum and b_news_cross:
        old = b_news_cross.points
        new = old * 0.5
        final_news_cross = _clone(b_news_cross, new, "50% dedup: News Momentum sibling")
        dedup_notes.append(
            f"~ Dedup: News Cross-Component {old:.1f} -> {new:.1f} "
            f"(same articles already counted in News Momentum)"
        )

    # Rule 2: Event Momentum + Growth Confirmation
    final_b_growth = b_growth
    if b_event and b_growth:
        old = b_growth.points
        new = old * 0.6
        final_b_growth = _clone(b_growth, new, "40% dedup: Event Momentum sibling")
        dedup_notes.append(
            f"~ Dedup: Growth Confirmation {old:.1f} -> {new:.1f} "
            f"(same Maya filings already counted in Event Momentum)"
        )

    # Rule 3: News Momentum + Growth Confirmation (partial, only if Rule 2 didn't fire)
    if b_news_momentum and final_b_growth and not b_event:
        old = final_b_growth.points
        new = old * 0.7
        final_b_growth = _clone(final_b_growth, new, "30% dedup: News Momentum partial overlap")
        dedup_notes.append(
            f"~ Dedup: Growth Confirmation {old:.1f} -> {new:.1f} "
            f"(news_score trigger partially overlaps News Momentum articles)"
        )

    # Assemble final boost list
    active = [b for b in [b_event, final_b_growth, b_align, b_sector, b_news_momentum, final_news_cross] if b]

    # Hard cap
    raw_total = sum(b.points for b in active)
    if raw_total > _BOOST_HARD_CAP:
        # Scale all boosts proportionally to stay at cap
        scale = _BOOST_HARD_CAP / raw_total
        active = [_clone(b, b.points * scale, f"scaled {scale:.2f}: hard cap {_BOOST_HARD_CAP}") for b in active]
        dedup_notes.append(
            f"~ Total boosts hard-capped at {_BOOST_HARD_CAP} pts "
            f"(raw {raw_total:.1f} -> scaled proportionally)"
        )

    return active, dedup_notes


def _compute_consistency_adjustment(boosts: List[ScoreBoost]) -> tuple:
    """
    Proportional convergence premium when multiple independent boosts fire.
    Signal alignment across different evidence domains is intrinsically valuable.

    ≥2 active boosts → +2.0 to +5.0 proportional to number and magnitude.
    Returns (adjustment_pts, reason_str).
    """
    active = [b for b in boosts if b.points > 0]
    n = len(active)
    if n < 2:
        return 0.0, ""

    total_boost_pts = sum(b.points for b in active)
    # Convergence premium: grows with number of converging signals
    # 2 active → base ~+2.0; each extra adds ~+1.0; total magnitude adds a small tail
    adj = min(5.0, (n - 1) * 1.5 + total_boost_pts * 0.04)
    adj = round(adj, 1)
    names = ", ".join(b.name for b in active)
    reason = f"Signal convergence across {n} domains ({names})"
    return adj, reason


# ── Contradiction detection ───────────────────────────────────────────────────

def _detect_contradictions(
    financial_score:  float,
    events_score:     float,
    growth_score:     float,
    consensus_score:  float,
    evidence_strength: float,
) -> tuple:
    """
    Detect cross-signal contradictions and return a score penalty.
    Contradictions occur when a positive narrative lacks corresponding fundamental support.

    Returns (penalty_pts, List[contradiction_messages]).

    Checked contradictions:
      1. Growth story (≥9.5) vs weak financials (≤7):
         Strong growth claim but company fundamentals don't support it.

      2. Analyst optimism (≥11) vs negative event context (≤6):
         Analysts bullish but Maya filings show negative/no catalyst.
    """
    penalty = 0.0
    messages: List[str] = []

    # ── Contradiction 1: Growth narrative vs weak financial reality ────────────
    if growth_score >= 9.5 and financial_score <= 7.0:
        # Growth score is high but financials are poor — the story doesn't match facts
        pen = min(8.0, (growth_score - 9.0) * 1.2 + max(0, 7.0 - financial_score) * 0.6)
        penalty += pen
        messages.append(
            f"Growth narrative ({growth_score:.1f}/15) contradicts weak fundamentals "
            f"({financial_score:.1f}/20) — score reduced {pen:.1f} pts. "
            f"Concrete financial evidence needed to validate growth claim."
        )

    # ── Contradiction 2: Analyst optimism vs no/negative event catalyst ───────
    if consensus_score >= 11.0 and events_score <= 6.0:
        pen = min(7.0, (consensus_score - 11.0) * 1.0 + max(0, 6.0 - events_score) * 0.5)
        penalty += pen
        messages.append(
            f"Analyst consensus ({consensus_score:.1f}/15) not supported by event/filing "
            f"evidence ({events_score:.1f}/20) — score reduced {pen:.1f} pts. "
            f"Analyst optimism without filings is speculative."
        )

    return min(12.0, round(penalty, 1)), messages


# ── Score calibration ─────────────────────────────────────────────────────────

def _apply_calibration(raw: float) -> float:
    """
    Soft compression to produce a realistic score distribution.

    Target ranges across the full stock universe:
      Weak stocks      20–40
      Average stocks   40–60
      Strong stocks    60–80
      Excellent        80–90+

    Compression curve (piecewise linear):
      0–40    → 0–40    (no compression — weak zone preserved)
      40–65   → 40–62.5 (0.90× above 40)
      65–80   → 62.5–73.75 (0.75× above 65)
      80–100  → 73.75–87.75 (0.70× above 80)

    This ensures:
      - A stock scoring 85 pre-calibration (strong) → ~77 (top of 60-80 range)
      - A stock scoring 100 pre-calibration (excellent) → ~88 (80-90 range)
      - Average stocks (55-60 pre) → ~53-57 (within 40-60)
    """
    if raw <= 40.0:
        return round(raw, 1)
    elif raw <= 65.0:
        return round(40.0 + (raw - 40.0) * 0.90, 1)
    elif raw <= 80.0:
        return round(62.5 + (raw - 65.0) * 0.75, 1)
    else:
        return round(73.75 + (raw - 80.0) * 0.70, 1)


# ── Hard constraint enforcement ───────────────────────────────────────────────

def _apply_hard_constraints(
    raw_total: float,
    financial: ScoreComponent,
    events: ScoreComponent,
    risk: ScoreComponent,
) -> tuple:
    """
    Apply hard score caps based on objective evidence quality.
    Returns (capped_total, gap_messages).

    Caps:
      Financial < 10  → total cannot exceed 65  (weak fundamentals = no strong thesis)
      Events    < 8   → total cannot exceed 70  (no positive catalyst = limited upside)
      Risk      < -5  → flag material risk factors (penalty already in raw_total)
    """
    gaps: List[str] = []
    capped = raw_total

    # ── Cap 1: weak financial base ────────────────────────────────────────────
    if financial.score < 10.0:
        if capped > 65.0:
            capped = 65.0
            gaps.append(
                f"Financial Strength {financial.score:.1f}/20 is below threshold (10) "
                f"— final score capped at 65. "
                f"To unlock higher scores: improve margins, FCF, or reduce leverage."
            )
        else:
            gaps.append(
                f"Financial Strength {financial.score:.1f}/20 limits upside "
                f"(cap activates at 65 once other signals push higher). "
                f"Stronger fundamentals required for a high-conviction thesis."
            )

    # ── Cap 2: no positive events/filings ────────────────────────────────────
    if events.score < 8.0:
        if capped > 70.0:
            capped = 70.0
            gaps.append(
                f"Events/Maya score {events.score:.1f}/20 is below threshold (8) "
                f"— no strong bullish catalyst found in filings, score capped at 70. "
                f"Positive earnings, guidance, or contract filing would unlock higher scores."
            )
        else:
            gaps.append(
                f"Events/Maya score {events.score:.1f}/20 — no confirmed positive catalyst. "
                f"A bullish filing (guidance, contract, earnings beat) would strengthen the case."
            )

    # ── Flag: material risk ───────────────────────────────────────────────────
    if risk.score < -5.0:
        gaps.append(
            f"Material risk flags ({risk.score:.0f} pts): {'; '.join(s for s in risk.signals if s.startswith('-'))}. "
            f"Resolving leverage, dilution, or loss risks would reduce penalty."
        )

    return min(raw_total, capped), gaps


# ── Main entry point ──────────────────────────────────────────────────────────

def compute_score(
    stock_data: Any,
    maya_reports: list,
    article_impacts: list,
    sector_news: list,
    agent_outputs: list,
    synthesis: Any,
    market: str = "il",
    time_horizon: str = "medium",
) -> ScoringResult:
    """
    Compute a structured, explainable score for a stock analysis.

    Score model (max 100):
      Financial Strength   0-20
      Company Events/Maya  0-20
      News & Sentiment     0-10
      Sector Heat          0-10
      Technical            0-10
      Growth Potential     0-15  (new)
      Analyst Consensus    0-15  (increased from 10)
      Risk Adjustment     -10-0
    """
    # ── 1. Component scoring ──────────────────────────────────────────────────
    financial    = _score_financial(stock_data)
    events_comp, best_event = _score_events(maya_reports)
    news         = _score_news(article_impacts)
    sector_macro = _score_sector_heat(stock_data, sector_news, market)
    technical    = _score_technical(stock_data)
    growth       = _score_growth(stock_data, maya_reports, article_impacts, agent_outputs)
    risk         = _score_risk_adjustment(stock_data, maya_reports, market, agent_outputs)

    # Evidence strength: objective (non-analyst) signal quality, used to gate consensus.
    _MAX_OBJ_EVIDENCE = 50.0  # 20 + 20 + 10
    evidence_strength = max(0.0, min(1.0,
        (financial.score + events_comp.score + news.score) / _MAX_OBJ_EVIDENCE
    ))

    consensus = _score_consensus(agent_outputs, synthesis, evidence_strength)

    base_total = (
        financial.score
        + events_comp.score
        + news.score
        + sector_macro.score
        + technical.score
        + growth.score
        + consensus.score
        + risk.score
    )
    base_total = max(0.0, min(100.0, base_total))

    # ── 2. Signal boosts (evidence convergence layer) ─────────────────────────
    # Boosts fire when independent data sources AGREE — they reward genuine
    # multi-source convergence, not noise.  Each boost has its own evidence gate.
    # Deduplication prevents the same signal from contributing to multiple boosts.
    # Compute news_strength once — shared source of truth for score AND boost
    news_strength, _ns = _compute_news_strength(article_impacts)

    b_event = _boost_event_momentum(maya_reports, events_comp.score)
    b_growth_boost = _boost_growth_confirmation(
        growth.score, financial.score, events_comp.score, news.score
    )
    b_align = _boost_analyst_alignment(consensus.score, evidence_strength, agent_outputs)
    b_sector = _boost_sector_tailwind(sector_macro.score, sector_news)
    b_news_momentum = _boost_news_momentum(article_impacts, news.score, news_strength)
    b_news_cross = _boost_news_cross_component(
        article_impacts, news.score,
        growth.score, events_comp.score, sector_macro.score,
        news_strength=news_strength,
    )

    # Validation: news_score and news_boost derive from the same news_strength, but
    # conflict compression in _score_news() can push the score slightly below the
    # expected floor. Enforce alignment explicitly as a safety net.
    if b_news_momentum is not None:
        if b_news_momentum.points >= 4.0 and news.score < 7.0:
            adj_score = max(news.score, 7.0)
            news = ScoreComponent(
                news.name, adj_score, news.max_score,
                news.signals + [f"~ Score aligned to 7.0 (news_strength={news_strength:.2f}, boost={b_news_momentum.points:.1f}pts)"],
                news.reasoning,
            )
            base_total = max(0.0, min(100.0,
                financial.score + events_comp.score + news.score + sector_macro.score
                + technical.score + growth.score + consensus.score + risk.score
            ))
        elif news.score < 6.0 and b_news_momentum.points > 2.0:
            old_pts = b_news_momentum.points
            b_news_momentum = ScoreBoost(
                b_news_momentum.name, 2.0, b_news_momentum.max_points,
                b_news_momentum.reason + f" [capped 2.0: news_score={news.score:.1f}<6.0]",
                b_news_momentum.triggered_by,
            )

    active_boosts, dedup_notes = _apply_boost_deduplication(
        b_event, b_growth_boost, b_align, b_sector, b_news_momentum, b_news_cross
    )
    total_boost_pts = sum(b.points for b in active_boosts)

    # News bearish penalty — applied separately from boosts (negative signal)
    news_bear_penalty = _news_bearish_penalty(article_impacts, news.score)

    # ── 3. Consistency adjustment (convergence premium) ───────────────────────
    consistency_pts, consistency_reason = _compute_consistency_adjustment(active_boosts)

    # ── 4. Contradiction detection ────────────────────────────────────────────
    # Check for cross-signal conflicts BEFORE applying the convergence premium.
    # Contradictions reduce the convergence premium and apply a direct penalty.
    contradiction_penalty, contradiction_msgs = _detect_contradictions(
        financial.score, events_comp.score, growth.score,
        consensus.score, evidence_strength,
    )
    # If contradictions exist, zero out the convergence premium (signals don't align)
    if contradiction_penalty > 0:
        consistency_pts = 0.0

    # ── 5. Pre-calibration total ──────────────────────────────────────────────
    pre_calibration = max(0.0, min(100.0,
        base_total + total_boost_pts + consistency_pts - contradiction_penalty + news_bear_penalty
    ))

    # ── 6. Hard constraints (applied AFTER boosts — caps are absolute) ────────
    post_constraint, score_gaps = _apply_hard_constraints(
        pre_calibration, financial, events_comp, risk
    )
    score_gaps.extend(contradiction_msgs)
    score_gaps.extend(dedup_notes)
    if news_bear_penalty < 0:
        score_gaps.append(
            f"Strong negative news penalty: {news_bear_penalty:.1f} pts "
            f"({sum(1 for a in (article_impacts or []) if (getattr(a, 'impact_score', 0) or 0) >= 4 and (getattr(a, 'sentiment', '') or '') in ('strong_bearish', 'bearish'))} high-impact bearish articles)"
        )

    # ── 7. Calibration — soft compression for realistic distribution ──────────
    raw_total = _apply_calibration(post_constraint)

    # ── 8. Driver collection ─────────────────────────────────────────────────
    all_signals: list = []
    for comp in [financial, events_comp, news, sector_macro, technical, growth, consensus]:
        for sig in comp.signals:
            if sig.startswith("+"):
                all_signals.append((1, sig))
            elif sig.startswith("-"):
                all_signals.append((-1, sig))
    for sig in risk.signals:
        if sig.startswith("-"):
            all_signals.append((-1, sig))

    positive_drivers = [s for v, s in all_signals if v > 0][:3]
    negative_drivers = [s for v, s in all_signals if v < 0][:3]

    # Most impactful event: prefer best Maya filing, fall back to latest article
    most_impactful = best_event or ""
    if not most_impactful and article_impacts:
        for art in sorted(article_impacts,
                          key=lambda a: _recency_weight(getattr(a, "published", None)),
                          reverse=True):
            if (getattr(art, "impact", "neutral") or "neutral") != "neutral":
                most_impactful = getattr(art, "title", "") or ""
                break

    return ScoringResult(
        financial=financial,
        events=events_comp,
        news=news,
        sector_macro=sector_macro,
        technical=technical,
        growth=growth,
        consensus=consensus,
        risk=risk,
        base_total=round(base_total, 1),
        boosts=active_boosts,
        consistency_adjustment=round(consistency_pts, 1),
        contradiction_penalty=round(contradiction_penalty, 1),
        pre_calibration_total=round(post_constraint, 1),
        raw_total=round(raw_total, 1),
        final_total=round(raw_total, 1),
        top_positive_drivers=positive_drivers,
        top_negative_drivers=negative_drivers,
        most_impactful_event=most_impactful,
        score_gaps=score_gaps,
    )


def _score_technical(stock_data: Any) -> ScoreComponent:
    """
    Technical: 0-10
    RSI-14 (2pt), MA cross (3pt), 1M price change (3pt), volume spike (2pt).
    """
    signals: List[str] = []
    score = 0.0
    sd = stock_data

    # RSI (0-2)
    rsi = getattr(sd, "rsi_14", None)
    if rsi is not None:
        if 45 <= rsi <= 65:
            score += 2; signals.append(f"+ RSI {rsi} (healthy momentum zone)")
        elif rsi > 65:
            score += 1; signals.append(f"~ RSI {rsi} (approaching overbought)")
        elif rsi > 30:
            score += 1; signals.append(f"~ RSI {rsi} (below 45 — weak momentum)")
        else:
            score -= 1; signals.append(f"- RSI {rsi} (oversold — possible reversal)")

    # MA cross (0-3)
    ma_above = getattr(sd, "ma20_above_ma50", None)
    if ma_above is not None:
        if ma_above:
            score += 3; signals.append("+ MA20 > MA50 (golden cross — bullish trend)")
        else:
            score -= 1; signals.append("- MA20 < MA50 (death cross — bearish trend)")

    # 1M price change (0-3)
    pc1m = getattr(sd, "price_change_1m", None)
    if pc1m is not None:
        if pc1m > 10:
            score += 3; signals.append(f"+ Strong 1M momentum +{pc1m:.1f}%")
        elif pc1m > 3:
            score += 2; signals.append(f"+ Positive 1M change +{pc1m:.1f}%")
        elif pc1m > -3:
            score += 1; signals.append(f"~ Flat 1M change {pc1m:+.1f}%")
        elif pc1m > -10:
            score -= 1; signals.append(f"- Negative 1M change {pc1m:.1f}%")
        else:
            score -= 2; signals.append(f"- Sharp 1M decline {pc1m:.1f}%")

    # Volume (0-2)
    vol = getattr(sd, "volume_vs_avg", None)
    if vol is not None:
        if vol >= 2.5:
            score += 2; signals.append(f"+ Volume spike {vol:.1f}x avg (unusual activity)")
        elif vol >= 1.3:
            score += 1; signals.append(f"+ Above-average volume {vol:.1f}x")
        else:
            signals.append(f"~ Normal volume {vol:.1f}x avg")

    if not signals:
        signals.append("~ No technical data available")
        score = 5.0

    score = max(0.0, min(10.0, score))
    reasoning = f"Technical score {score:.1f}/10 from RSI, MA cross, momentum, volume"
    return ScoreComponent("Technical", score, 10.0, signals, reasoning)
