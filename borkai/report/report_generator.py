"""
Report Generation

Assembles all analysis into a structured, readable research report.
Design principles:
  - Verdict dashboard with visual score bar at top
  - Analyst panel: one line per analyst — name + one-sentence finding
  - Visual scenario probability bars
  - Synthesis as a compact agreement/disagreement table
  - Articles and Maya filings as bullets, not full sections
"""
from dataclasses import dataclass, field
from typing import List, Optional, Any
from datetime import date

from ..agents.base_agent import AgentOutput
from ..orchestrator.profiler import StockProfile
from ..orchestrator.relevance_mapper import RelevanceMap
from ..orchestrator.sector_analyzer import SectorAnalysis
from ..committee.synthesizer import SynthesisResult
from ..committee.committee import CommitteeDecision
from ..scoring.scoring_engine import ScoringResult


@dataclass
class AnalysisResult:
    """The complete, assembled output of a full Borkai analysis."""
    ticker: str
    time_horizon: str
    analysis_date: str

    profile: StockProfile
    relevance_map: RelevanceMap
    agent_outputs: List[AgentOutput]
    synthesis: SynthesisResult
    decision: CommitteeDecision
    sector_analysis: Optional[SectorAnalysis] = None

    article_impacts: list = field(default_factory=list)
    maya_reports: list = field(default_factory=list)
    stock_data: Optional[Any] = None  # StockData — for price trend in report
    scoring: Optional[ScoringResult] = None  # Structured scoring breakdown


# ---------------------------------------------------------------------------
# Visual helpers
# ---------------------------------------------------------------------------

def _recency_label(published: str) -> str:
    """Return a short recency tag based on days since publication."""
    if not published:
        return ""
    try:
        from datetime import datetime as _dt
        days_old = (_dt.now() - _dt.fromisoformat(published[:10])).days
        if days_old <= 3:
            return "🔥 HOT"
        elif days_old <= 14:
            return "📅 RECENT"
    except Exception:
        pass
    return ""


def _risk_bar(score: int, width: int = 10) -> str:
    """Render a risk level bar: score is 1-10."""
    score = max(1, min(10, score))
    filled = round(score / 10 * width)
    color_char = "▓"
    return color_char * filled + "░" * (width - filled)


def _safe_url(url: str) -> str:
    """Return the URL if it looks valid, else empty string."""
    if not url:
        return ""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return ""
    # Remove any embedded whitespace / newlines that break markdown links
    import re as _re
    url = _re.sub(r"\s+", "%20", url)
    return url


def _impact_badge(impact: str) -> str:
    return {"bullish": "🟢 Bullish", "bearish": "🔴 Bearish", "neutral": "⚪ Neutral"}.get(
        impact.lower(), f"⚪ {impact.capitalize()}"
    )


def _stance_icon(stance: str) -> str:
    return {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪", "mixed": "🟡"}.get(stance.lower(), "⚪")


def _bar(value: int, total: int = 100, width: int = 30) -> str:
    """Render a filled/empty progress bar."""
    filled = round(value / total * width)
    return "▓" * filled + "░" * (width - filled)


def _pct_bar(pct_str: str, width: int = 20) -> str:
    """Parse a probability string like '35%' or '25-35%' and render a bar."""
    import re as _re
    nums = _re.findall(r'\d+', str(pct_str))
    if nums:
        val = round(sum(int(n) for n in nums) / len(nums))  # average if range
    else:
        val = 0
    val = max(0, min(100, val))
    filled = round(val / 100 * width)
    return "▓" * filled + "░" * (width - filled)


def _earnings_section(sd) -> List[str]:
    """
    Build a 'Latest Financial Report' section from StockData quarterly data.
    Returns a list of markdown lines, or empty list if no data.
    """
    if sd is None or not sd.quarterly_earnings_summary:
        return []

    import re

    lines_in = sd.quarterly_earnings_summary.strip().splitlines()
    quarter_rows: List[tuple] = []
    qoq_line = ""
    yoy_line = ""
    for ln in lines_in:
        ln = ln.strip()
        m = re.match(r"(\d{4}-\d{2}-\d{2}):\s*Rev=(\S+)\s+Net=(\S+)", ln)
        if m:
            quarter_rows.append((m.group(1), m.group(2), m.group(3)))
        elif ln.startswith("Latest vs prior:"):
            qoq_line = ln.replace("Latest vs prior:", "").strip()
        elif ln.startswith("Year-over-year:"):
            yoy_line = ln.replace("Year-over-year:", "").strip()

    if not quarter_rows:
        return []

    out = [
        "## Latest Financial Report",
        "",
        "| Quarter | Revenue | Net Income |",
        "|---------|---------|------------|",
    ]
    for q, rev, net in quarter_rows:
        out.append(f"| {q} | {rev} | {net} |")
    out.append("")

    # TTM profitability metrics (if available from StockData)
    margin_parts = []
    if getattr(sd, "gross_margin", None) is not None:
        margin_parts.append(f"Gross margin: **{sd.gross_margin * 100:.1f}%**")
    if getattr(sd, "operating_margin", None) is not None:
        margin_parts.append(f"Operating margin: **{sd.operating_margin * 100:.1f}%**")
    if getattr(sd, "net_margin", None) is not None:
        margin_parts.append(f"Net margin: **{sd.net_margin * 100:.1f}%**")
    if margin_parts:
        out.append("**TTM Profitability —** " + "  ·  ".join(margin_parts))
        out.append("")

    # Build interpretation sentence(s)
    def _parse_chg(tag: str, text: str) -> Optional[float]:
        m = re.search(rf"{tag}\s*([+-]?\d+\.?\d*)%", text)
        return float(m.group(1)) if m else None

    rev_qoq = _parse_chg("Rev QoQ", qoq_line)
    net_qoq = _parse_chg("Net QoQ", qoq_line)
    rev_yoy = _parse_chg("Rev YoY", yoy_line)
    net_yoy = _parse_chg("Net YoY", yoy_line)

    interp_parts = []
    if rev_qoq is not None:
        adj = "grew" if rev_qoq > 0 else "contracted"
        flag = " ⚠️" if abs(rev_qoq) > 20 else ""
        interp_parts.append(f"Revenue **{adj} {abs(rev_qoq):.1f}% QoQ**{flag}")
    if net_qoq is not None:
        adj = "improved" if net_qoq > 0 else "fell"
        flag = " ⚠️" if abs(net_qoq) > 25 else ""
        interp_parts.append(f"net income **{adj} {abs(net_qoq):.1f}% QoQ**{flag}")

    yoy_parts = []
    if rev_yoy is not None:
        adj = "up" if rev_yoy > 0 else "down"
        yoy_parts.append(f"revenue {adj} **{abs(rev_yoy):.1f}% YoY**")
    if net_yoy is not None:
        adj = "up" if net_yoy > 0 else "down"
        yoy_parts.append(f"net income {adj} **{abs(net_yoy):.1f}% YoY**")

    if interp_parts:
        sentence = "In the latest quarter, " + " while ".join(interp_parts) + "."
        if yoy_parts:
            sentence += " Versus the same quarter last year: " + " and ".join(yoy_parts) + "."
        out.append(f"> {sentence}")
        out.append("")

    # Flag anything unusual
    flags = []
    if rev_qoq is not None and abs(rev_qoq) > 20:
        flags.append(f"Revenue swing of {rev_qoq:+.1f}% QoQ is unusually large — investigate one-time items.")
    if net_qoq is not None and abs(net_qoq) > 30:
        flags.append(f"Net income swing of {net_qoq:+.1f}% QoQ is significant — check non-recurring items.")
    if getattr(sd, "operating_margin", None) is not None and sd.operating_margin < 0:
        flags.append("Operating margin is negative — the business is currently loss-making at the operating level.")
    if getattr(sd, "net_margin", None) is not None and getattr(sd, "gross_margin", None) is not None:
        if sd.gross_margin > 0.4 and sd.net_margin < 0.05:
            flags.append("High gross margin but low net margin suggests elevated SG&A, R&D, or interest expense.")
    for flag in flags:
        out.append(f"> ⚠️ {flag}")
    if flags:
        out.append("")

    out += ["---", ""]
    return out


def _chart_analysis_section(sd, time_horizon: str = "medium") -> List[str]:
    """
    Build a 'Price Chart Analysis' section from StockData technicals.
    Language and focus adapt to the analysis time horizon.
    Returns a list of markdown lines, or empty list if insufficient data.
    """
    if sd is None or sd.current_price is None:
        return []

    horizon_label = {
        "short":  "Short-Term (1–4 Weeks)",
        "medium": "Medium-Term (1–6 Months)",
        "long":   "Long-Term (1–3 Years)",
    }.get(time_horizon, "Medium-Term")

    lines = [f"## Price Chart Analysis — {horizon_label}", ""]

    bullets = []

    # Trend structure — label changes by horizon
    if sd.ma20_above_ma50 is not None:
        if time_horizon == "short":
            context = "near-term momentum"
        elif time_horizon == "long":
            context = "structural trend"
        else:
            context = "medium-term trend"
        if sd.ma20_above_ma50:
            bullets.append(f"MA20 is **above** MA50 (golden cross) — {context} is **bullish**.")
        else:
            bullets.append(f"MA20 is **below** MA50 (death cross) — {context} is **bearish**.")

    # RSI — thresholds same, wording adapts
    if sd.rsi_14 is not None:
        if sd.rsi_14 > 70:
            bullets.append(f"RSI-14 at **{sd.rsi_14}** — **overbought**, momentum reversal risk"
                           + (" in coming sessions." if time_horizon == "short" else " over the near term."))
        elif sd.rsi_14 < 30:
            bullets.append(f"RSI-14 at **{sd.rsi_14}** — **oversold**, potential bounce"
                           + (" setup in coming sessions." if time_horizon == "short" else " or trend reversal setup."))
        elif sd.rsi_14 > 55:
            bullets.append(f"RSI-14 at **{sd.rsi_14}** — positive momentum, not yet extended.")
        elif sd.rsi_14 < 45:
            bullets.append(f"RSI-14 at **{sd.rsi_14}** — soft momentum with mild bearish bias.")
        else:
            bullets.append(f"RSI-14 at **{sd.rsi_14}** — neutral momentum, no clear directional signal.")

    # 52-week range position (relevant for medium/long; still show for short)
    if sd.price_52w_high and sd.price_52w_low and sd.current_price:
        rng = sd.price_52w_high - sd.price_52w_low
        if rng > 0:
            pos = (sd.current_price - sd.price_52w_low) / rng * 100
            off_high = (sd.price_52w_high - sd.current_price) / sd.price_52w_high * 100
            if pos >= 80:
                bullets.append(f"Trading near the **52-week high** ({off_high:.1f}% below it) — strong trend, limited near-term upside room.")
            elif pos <= 20:
                bullets.append(f"Trading near the **52-week low** ({off_high:.1f}% below 52W high) — deeply discounted, weak trend.")
            else:
                bullets.append(f"Trading **{off_high:.1f}% below** the 52-week high — room for recovery if fundamentals support it.")

    # Volume spike
    if sd.volume_vs_avg and sd.volume_vs_avg >= 2.0:
        bullets.append(f"Recent volume is **{sd.volume_vs_avg:.1f}×** the 20-day average — notable interest spike.")

    # Price momentum — horizon-appropriate timeframes
    m_parts = []
    if time_horizon == "short":
        if sd.price_change_1m is not None:
            sign = "+" if sd.price_change_1m > 0 else ""
            m_parts.append(f"**{sign}{sd.price_change_1m:.1f}%** over the past month")
    elif time_horizon == "long":
        if sd.price_change_1y is not None:
            sign = "+" if sd.price_change_1y > 0 else ""
            m_parts.append(f"**{sign}{sd.price_change_1y:.1f}%** over the past year")
        if sd.price_change_3m is not None:
            sign = "+" if sd.price_change_3m > 0 else ""
            m_parts.append(f"**{sign}{sd.price_change_3m:.1f}%** over 3 months")
    else:  # medium
        if sd.price_change_1m is not None:
            sign = "+" if sd.price_change_1m > 0 else ""
            m_parts.append(f"**{sign}{sd.price_change_1m:.1f}%** over 1 month")
        if sd.price_change_3m is not None:
            sign = "+" if sd.price_change_3m > 0 else ""
            m_parts.append(f"**{sign}{sd.price_change_3m:.1f}%** over 3 months")
    if m_parts:
        bullets.append(f"Price performance: {', '.join(m_parts)}.")

    for b in bullets:
        lines.append(f"- {b}")

    lines += ["", "---", ""]
    return lines


def _vote_row(outputs: List[AgentOutput]) -> str:
    """E.g.  🟢🟢🟢🟢🟢🟢🟢🔴🔴⚪   7 bullish · 2 bearish · 1 neutral"""
    icons = "".join(_stance_icon(o.stance) for o in outputs)
    counts = {s: sum(1 for o in outputs if o.stance == s) for s in ("bullish", "bearish", "neutral", "mixed")}
    parts = []
    if counts["bullish"]:  parts.append(f"**{counts['bullish']} bullish**")
    if counts["mixed"]:    parts.append(f"**{counts['mixed']} mixed**")
    if counts["neutral"]:  parts.append(f"{counts['neutral']} neutral")
    if counts["bearish"]:  parts.append(f"**{counts['bearish']} bearish**")
    return f"{icons}   {' · '.join(parts)}"


# ---------------------------------------------------------------------------
# Main report generator
# ---------------------------------------------------------------------------

def generate_report(result: AnalysisResult) -> str:
    d = result.decision
    p = result.profile
    s = result.synthesis

    invest_badge = {
        "YES":         "✅ INVEST — YES",
        "NO":          "❌ DO NOT INVEST",
        "CONDITIONAL": "⚠️  CONDITIONAL",
    }.get(d.invest_recommendation.upper(), d.invest_recommendation.upper())

    direction_label = {
        "up":             "BULLISH ↑",
        "conditional_up": "COND. BULLISH ↑",
        "down":           "BEARISH ↓",
        "mixed":          "MIXED ↔",
    }.get(d.direction, d.direction.upper())

    conviction_stars = {"low": "★☆☆", "moderate": "★★☆", "high": "★★★"}.get(
        d.conviction.lower(), "★☆☆"
    )

    score = d.return_score

    lines = [
        f"# BORKAI RESEARCH REPORT",
        f"## {result.ticker} — {p.company_name}",
        f"**Date:** {result.analysis_date}  |  "
        f"**Horizon:** {result.time_horizon.upper()}  |  "
        f"**Phase:** {p.phase.upper()}",
        "",
        "---",
        "",
    ]

    # ── VERDICT DASHBOARD ───────────────────────────────────────────────────
    lines += [
        "## HIGHLIGHTS",
        "",
        f"```",
        f"  {invest_badge}",
        f"  Direction : {direction_label:<20}  Conviction: {conviction_stars}",
        f"  Score     : {score}/100",
        f"  {_bar(score)}  {score}%",
        f"```",
        "",
    ]

    # ── SCORE BREAKDOWN ──────────────────────────────────────────────────────
    sc = result.scoring
    if sc is not None:
        _growth_sc  = getattr(sc, "growth", None)
        _base_total = getattr(sc, "base_total", sc.raw_total)
        _boosts     = getattr(sc, "boosts", [])
        _cons_adj   = getattr(sc, "consistency_adjustment", 0.0)

        # ── BASE COMPONENTS block ─────────────────────────────────────────────
        lines += [
            "## Score Breakdown",
            "",
            "```",
            "  BASE COMPONENTS",
            f"  Financial Strength : {sc.financial.score:5.1f} / {sc.financial.max_score:.0f}",
            f"  MAYA Events        : {sc.events.score:5.1f} / {sc.events.max_score:.0f}",
            f"  News & Sentiment   : {sc.news.score:5.1f} / {sc.news.max_score:.0f}",
            f"  Sector Heat        : {sc.sector_macro.score:5.1f} / {sc.sector_macro.max_score:.0f}",
            f"  Technical          : {sc.technical.score:5.1f} / {sc.technical.max_score:.0f}",
        ]
        if _growth_sc is not None:
            lines.append(f"  Growth Potential   : {_growth_sc.score:5.1f} / {_growth_sc.max_score:.0f}")
        lines += [
            f"  Analyst Consensus  : {sc.consensus.score:5.1f} / {sc.consensus.max_score:.0f}",
            f"  Risk Adjustment    : {sc.risk.score:5.1f}",
            "  " + "-" * 38,
            f"  Component Total    : {_base_total:5.1f} / 100",
        ]

        # ── SIGNAL BOOSTS block ───────────────────────────────────────────────
        _contra_pen   = getattr(sc, "contradiction_penalty", 0.0)
        _pre_calib    = getattr(sc, "pre_calibration_total", sc.raw_total)
        if _boosts or _cons_adj > 0:
            lines.append("")
            lines.append("  SIGNAL BOOSTS")
            for b in _boosts:
                lines.append(f"  {b.name:<22} : +{b.points:.1f}  ({b.reason})")
            if _cons_adj > 0:
                lines.append(f"  {'Convergence Premium':<22} : +{_cons_adj:.1f}  (multiple signals align)")
            _total_boost = sum(b.points for b in _boosts) + _cons_adj
            lines += [
                "  " + "-" * 38,
                f"  Total Boosts       : +{_total_boost:.1f}",
            ]

        # ── PENALTY / CALIBRATION block ───────────────────────────────────────
        _pre_constraint = min(100.0, round(_base_total + sum(b.points for b in _boosts) + _cons_adj - _contra_pen, 1))
        _hard_cap_fired = _pre_constraint > _pre_calib + 0.05
        _calib_delta    = round(sc.raw_total - _pre_calib, 1)
        lines.append("")
        lines.append("  ADJUSTMENTS")
        if _contra_pen > 0:
            lines.append(f"  Contradiction Pen  : -{_contra_pen:.1f}  (conflicting signals)")
        _pre_constraint_disp = min(100.0, round(_base_total + sum(b.points for b in _boosts) + _cons_adj - _contra_pen, 1))
        if _hard_cap_fired:
            lines.append(f"  Hard Constraint    :  capped at {_pre_calib:.1f}")
        if _calib_delta < -0.5:
            lines.append(f"  Calibration        : {_calib_delta:.1f}  (soft compression for realistic distribution)")
        lines += [
            "  " + "-" * 38,
            f"  RAW TOTAL          : {sc.raw_total:5.1f} / 100",
            f"  FINAL SCORE        : {sc.final_total:5.1f} / 100  (committee validated)",
            "```",
            "",
        ]

        # ── Key drivers ───────────────────────────────────────────────────────
        if sc.top_positive_drivers:
            lines.append("**Key Drivers (Positive):**")
            for driver in sc.top_positive_drivers:
                lines.append(f"  {driver}")
            lines.append("")
        if sc.top_negative_drivers:
            lines.append("**Key Drivers (Negative):**")
            for driver in sc.top_negative_drivers:
                lines.append(f"  {driver}")
            lines.append("")
        if sc.most_impactful_event:
            lines += [f"**Most Impactful Event:** {sc.most_impactful_event}", ""]

        # ── What's missing ────────────────────────────────────────────────────
        _score_gaps = [g for g in getattr(sc, "score_gaps", []) if not g.startswith("Consistency")]
        if _score_gaps:
            lines += ["### What's Missing for a Higher Score", ""]
            for gap in _score_gaps:
                lines.append(f"- {gap}")
            lines.append("")

        # ── Boost detail ──────────────────────────────────────────────────────
        if _boosts:
            lines += ["### Signal Boosts Detail", ""]
            for b in _boosts:
                lines.append(f"**+{b.points:.1f} — {b.name}** (max {b.max_points:.0f}): {b.reason}")
                for t in b.triggered_by:
                    lines.append(f"  - {t}")
                lines.append("")

        # ── Sector Heat explanation ───────────────────────────────────────────
        lines += ["### Sector Heat", ""]
        lines.append(f"**Score: {sc.sector_macro.score:.1f} / {sc.sector_macro.max_score:.0f}** — "
                     f"{sc.sector_macro.reasoning}")
        lines.append("")
        for sig in sc.sector_macro.signals[:5]:
            lines.append(f"- {sig}")
        lines.append("")

        # ── Growth Potential section ──────────────────────────────────────────
        if _growth_sc is not None:
            lines += ["### Growth Potential", ""]
            lines.append(f"**Score: {_growth_sc.score:.1f} / {_growth_sc.max_score:.0f}** — "
                         f"{_growth_sc.reasoning}")
            lines.append("")
            for sig in _growth_sc.signals[:6]:
                lines.append(f"- {sig}")
            lines.append("")

        # ── Analyst Consensus explanation ─────────────────────────────────────
        lines += ["### Analyst Consensus", ""]
        lines.append(f"**Score: {sc.consensus.score:.1f} / {sc.consensus.max_score:.0f}** — "
                     f"{sc.consensus.reasoning}")
        lines.append("")
        for sig in sc.consensus.signals:
            lines.append(f"- {sig}")
        lines.append("")

        lines += ["---", ""]

    # Top articles (up to 8, bullish/bearish first, with recency labels)
    if result.article_impacts:
        lines.append("### Latest Articles")
        lines.append("")
        sorted_arts = sorted(
            result.article_impacts,
            key=lambda a: (0 if a.impact == "bullish" else 1 if a.impact == "bearish" else 2),
        )
        for art in sorted_arts[:8]:
            src = f"_{art.source}_  " if art.source else ""
            clean_url = _safe_url(art.url)
            url_part = f"[{art.title}]({clean_url})" if clean_url else art.title
            summary = f" — {art.impact_summary}" if art.impact_summary else ""
            rec = _recency_label(art.published)
            rec_str = f" **{rec}**" if rec else ""
            lines.append(f"- {_impact_badge(art.impact)}{rec_str} {src}{url_part}{summary}")
        lines.append("")

    # Top Maya filings (up to 8, page order from Maya site)
    if result.maya_reports:
        lines.append("### Maya / TASE Filings")
        lines.append("")
        for rep in result.maya_reports[:8]:
            src = f"_{rep.source}_  " if rep.source else ""
            clean_url = _safe_url(rep.link)
            url_part = f"[{rep.title}]({clean_url})" if clean_url else rep.title
            reason = f" — {rep.impact_reason}" if rep.impact_reason else ""
            date_str = f"[{rep.published[:10]}] " if rep.published else ""
            rec = _recency_label(rep.published)
            rec_str = f" **{rec}**" if rec else ""
            lines.append(f"- {_impact_badge(rep.impact)}{rec_str} {date_str}{src}{url_part}{reason}")
        lines.append("")

    lines += ["---", ""]

    # ── 1. STOCK OVERVIEW ───────────────────────────────────────────────────
    lines += [
        "## 1. Stock Overview",
        "",
        f"**Sector:** {p.sector_dynamics}",
        "",
        f"**Current Situation:** {p.current_situation}",
        "",
        f"**What the Market is Focused on:** {p.what_market_is_focused_on}",
        "",
        f"**Horizon Implications ({result.time_horizon.upper()}):** {p.horizon_implications}",
        "",
    ]
    if p.key_characteristics:
        lines.append("**Key Characteristics:**")
        for kc in p.key_characteristics:
            lines.append(f"- {kc}")
        lines.append("")

    # Price trend snapshot — built from StockData technicals if available
    sd = result.stock_data
    if sd is not None:
        trend_parts = []
        if sd.current_price and sd.price_52w_high and sd.price_52w_high > 0:
            off_high = (sd.price_52w_high - sd.current_price) / sd.price_52w_high * 100
            trend_parts.append(f"{off_high:.1f}% below 52W high")
        if sd.rsi_14 is not None:
            rsi_note = (
                " (overbought)" if sd.rsi_14 > 70
                else " (oversold)" if sd.rsi_14 < 30
                else " (neutral)" if 45 <= sd.rsi_14 <= 55
                else " (bullish)" if sd.rsi_14 > 55
                else " (bearish)"
            )
            trend_parts.append(f"RSI {sd.rsi_14}{rsi_note}")
        if sd.ma20_above_ma50 is not None:
            trend_parts.append("MA20>MA50 ↑" if sd.ma20_above_ma50 else "MA20<MA50 ↓")
        if sd.volume_vs_avg and sd.volume_vs_avg >= 2.5:
            trend_parts.append(f"volume spike {sd.volume_vs_avg:.1f}x avg")
        if sd.price_change_1m is not None:
            sign = "+" if sd.price_change_1m > 0 else ""
            trend_parts.append(f"1M {sign}{sd.price_change_1m:.1f}%")
        if trend_parts:
            lines.append(f"**Price Trend:** {' · '.join(trend_parts)}")
            lines.append("")

    if d.market_regime:
        lines += [f"**Market Regime:** {d.market_regime}", ""]
    if d.relative_strength:
        lines += [f"**Relative Strength:** {d.relative_strength}", ""]

    lines += ["---", ""]

    # ── 1b. SECTOR / INDUSTRY ANALYSIS ──────────────────────────────────────
    sa = result.sector_analysis
    if sa and not sa.analysis_skipped:
        sentiment_icon = {"bullish": "📈", "bearish": "📉", "mixed": "↔️", "neutral": "➡️"}.get(
            sa.market_sentiment, "➡️"
        )
        phase_icon = {
            "momentum":   "🚀",
            "slowdown":   "🔽",
            "transition": "🔀",
            "stable":     "➡️",
        }.get(getattr(sa, "sector_phase", "stable"), "➡️")

        lines += [
            "## Sector / Industry Analysis",
            "",
            f"**Sector:** {sa.sector}  |  "
            f"**Phase:** {phase_icon} {getattr(sa, 'sector_phase', 'stable').upper()}  |  "
            f"**Sentiment:** {sentiment_icon} {sa.market_sentiment.upper()}",
            "",
        ]

        sector_summary = getattr(sa, "sector_summary", "")
        if sector_summary:
            lines += [f"> {sector_summary}", ""]

        if sa.hot_topics:
            lines.append("**Key Sector Themes:**")
            for t in sa.hot_topics:
                lines.append(f"- {t}")
            lines.append("")

        if sa.key_opportunities:
            lines.append("**Sector Opportunities:**")
            for o in sa.key_opportunities:
                lines.append(f"- ✅ {o}")
            lines.append("")

        if sa.key_risks:
            lines.append("**Sector Risks:**")
            for r in sa.key_risks:
                lines.append(f"- ⚠️ {r}")
            lines.append("")

        if sa.relevance_to_stock:
            lines += [
                f"**Impact on {result.ticker}:**",
                f"> {sa.relevance_to_stock}",
                "",
            ]

        # Show up to 5 sector articles
        sector_articles = getattr(sa, "news_items", [])
        if sector_articles:
            lines.append(f"**Recent Sector News** ({len(sector_articles)} articles):")
            lines.append("")
            for item in sector_articles[:5]:
                source_str = f"_{item.source}_  " if item.source else ""
                date_str = f"[{str(item.published)[:10]}] " if item.published else ""
                url = getattr(item, "url", "")
                url_part = f"[{item.title}]({url})" if url else item.title
                lines.append(f"- {date_str}{source_str}{url_part}")
            lines.append("")

        lines += ["---", ""]

    # ── 1c. LATEST FINANCIAL REPORT ─────────────────────────────────────────
    earnings_lines = _earnings_section(sd)
    if earnings_lines:
        lines += earnings_lines

    # ── 1d. PRICE CHART ANALYSIS ─────────────────────────────────────────────
    chart_lines = _chart_analysis_section(sd, time_horizon=result.time_horizon)
    if chart_lines:
        lines += chart_lines

    # ── 2. ANALYST TEAM ─────────────────────────────────────────────────────
    import re as _re
    n = len(result.agent_outputs)
    lines += [
        f"## 2. Analyst Team  ({n} analysts)",
        "",
        _vote_row(result.agent_outputs),
        "",
        "| # | Analyst | Stance | Confidence | Summary |",
        "|---|---------|:------:|:----------:|---------|",
    ]
    for i, out in enumerate(result.agent_outputs, 1):
        icon = _stance_icon(out.stance)
        finding = out.key_finding or ""
        first_sentence = _re.split(r'(?<=[.!?])\s', finding.strip())
        short = first_sentence[0] if first_sentence else finding
        conf_icon = {"high": "●●●", "moderate": "●●○", "low": "●○○"}.get(out.confidence.lower(), "●○○")
        lines.append(f"| {i} | **{out.agent_name}** | {icon} {out.stance.capitalize()} | `{conf_icon}` | {short} |")

    # Analyst opinions — up to 2 sentences per analyst
    lines += ["", "### Analyst Opinions", ""]
    for out in result.agent_outputs:
        icon = _stance_icon(out.stance)
        conf_label = {"high": "high conviction", "moderate": "moderate conviction", "low": "low conviction"}.get(
            out.confidence.lower(), "")
        # Extract up to 2 complete sentences from key_finding — never truncate mid-sentence
        finding = (out.key_finding or "").strip()
        sentences = _re.split(r'(?<=[.!?])\s+', finding)
        opinion = " ".join(sentences[:2])
        if opinion:
            lines.append(f"**{icon} {out.agent_name}** _{conf_label}_: {opinion}")
            lines.append("")

    lines += ["---", ""]

    # ── 3. SYNTHESIS ────────────────────────────────────────────────────────
    lean_icon = {"bullish": "📈", "bearish": "📉", "mixed": "↔️", "neutral": "➡️"}.get(
        s.overall_lean, "➡️"
    )
    lines += [
        "## 3. Synthesis",
        "",
        f"**Overall Lean:** {lean_icon} {s.overall_lean.upper()}  |  "
        f"**Consensus Confidence:** {s.consensus_confidence.upper()}",
        "",
        s.agreement_summary,
        "",
    ]

    if s.agreements:
        lines.append("**Where analysts agree:**")
        for a in s.agreements[:4]:
            lines.append(f"- **{a.topic}:** {a.shared_view}")
        lines.append("")

    if s.disagreements:
        lines.append("**Where analysts disagree:**")
        for dis in s.disagreements[:3]:
            lines.append(f"- **{dis.topic}:** {dis.agent_a} sees _{dis.view_a}_ · {dis.agent_b} sees _{dis.view_b}_")
            if dis.resolution:
                lines.append(f"  → Resolution: {dis.resolution}")
        lines.append("")

    if s.bias_assessment:
        lines += [f"> **Bias check:** {s.bias_assessment}", ""]

    if s.strongest_evidence_domains:
        lines.append(f"**Strongest evidence:** {', '.join(s.strongest_evidence_domains)}  |  "
                     f"**Weakest:** {', '.join(s.weakest_evidence_domains or [])}")
        lines.append("")

    lines += ["---", ""]

    # ── 4. INVESTMENT COMMITTEE VERDICT ─────────────────────────────────────
    risk_bar = _risk_bar(d.risk_score)
    lines += [
        "## 4. Investment Committee Verdict",
        "",
        f"## {invest_badge}",
        "",
        f"**Direction:** {direction_label}  |  **Conviction:** {conviction_stars}  |  "
        f"**Return Score:** {score}/100",
        "",
        f"**Risk Score:** {d.risk_score}/10  `{risk_bar}`",
        "",
        f"> {d.invest_rationale}",
        "",
        f"{d.summary}",
        "",
    ]
    if d.consistency_note:
        lines += [f"> **Signal Consistency:** {d.consistency_note}", ""]

    # Scenario bars
    lines += [
        "### Scenario Analysis",
        "",
        "```",
        f"  🐂 Bull  {_pct_bar(d.bull_scenario.probability)}  {d.bull_scenario.probability}",
        f"  ⚖️  Base  {_pct_bar(d.base_scenario.probability)}  {d.base_scenario.probability}",
        f"  🐻 Bear  {_pct_bar(d.bear_scenario.probability)}  {d.bear_scenario.probability}",
        "```",
        "",
    ]

    for label, icon, scenario in [
        ("Bull Case", "🐂", d.bull_scenario),
        ("Base Case", "⚖️", d.base_scenario),
        ("Bear Case", "🐻", d.bear_scenario),
    ]:
        lines += [
            f"**{icon} {label}** — {scenario.description}",
            f"Expected outcome: _{scenario.expected_outcome}_",
            "",
        ]

    lines += [
        "**Bullish Factors:**",
        *[f"- {f_}" for f_ in d.key_bullish_factors],
        "",
        "**Bearish Factors:**",
        *[f"- {f_}" for f_ in d.key_bearish_factors],
        "",
        "**Key Risks:**",
        *[f"- {r}" for r in d.key_risks],
        "",
        "**Catalysts to Watch:**",
        *[f"- {c}" for c in d.key_catalysts],
        "",
        "**What Would Invalidate This Thesis:**",
        *[f"- {w}" for w in d.what_would_invalidate],
        "",
        f"**Variant Perception:** {d.variant_perception}",
        "",
        "---",
        "",
    ]

    # ── 5. ALL ARTICLES ─────────────────────────────────────────────────────
    lines += [f"## 5. Recent Articles  ({len(result.article_impacts)} articles)", ""]
    if result.article_impacts:
        for art in result.article_impacts:
            clean_url = _safe_url(art.url)
            url_part = f"[{art.title}]({clean_url})" if clean_url else art.title
            source_date = " · ".join(filter(None, [art.source, art.published[:10] if art.published else ""]))
            summary = f"\n  > {art.impact_summary}" if art.impact_summary else ""
            rec = _recency_label(art.published)
            rec_str = f" **{rec}**" if rec else ""
            lines.append(f"- {_impact_badge(art.impact)}{rec_str}  **{source_date}**  {url_part}{summary}")
            lines.append("")
    else:
        lines.append("_No articles retrieved._")
    lines += ["", "---", ""]

    # ── 6. MAYA / TASE FILINGS ──────────────────────────────────────────────
    lines += [f"## 6. Maya / TASE Regulatory Filings  ({len(result.maya_reports)} filings)", ""]
    if result.maya_reports:
        for rep in result.maya_reports:
            clean_url = _safe_url(rep.link)
            url_part = f"[{rep.title}]({clean_url})" if clean_url else rep.title
            source_date = " · ".join(filter(None, [
                rep.source,
                rep.published[:10] if rep.published else "",
                rep.report_type.replace("_", " ").title() if rep.report_type != "other" else "",
            ]))
            reason = f"\n  > {rep.impact_reason}" if rep.impact_reason else ""
            rec = _recency_label(rep.published)
            rec_str = f" **{rec}**" if rec else ""
            lines.append(f"- {_impact_badge(rep.impact)}{rec_str}  **{source_date}**  {url_part}{reason}")
            lines.append("")
    else:
        lines.append("_No Maya/TASE filings retrieved._")
    lines += ["", "---", ""]

    # ── 7. SIGNAL SUMMARY ───────────────────────────────────────────────────
    if d.signal_summary:
        lines += ["## 7. Signal Summary", ""]
        # Render the signal summary in a code block for clean formatting
        lines.append("```")
        for line in d.signal_summary.splitlines():
            lines.append(f"  {line}" if line.strip() else "")
        lines.append("```")
        lines += ["", "---", ""]

    # ── 8. CONVICTION RATIONALE ─────────────────────────────────────────────
    lines += [
        "## 8. Conviction Rationale",
        "",
        f"**Conviction:** {conviction_stars} {d.conviction.upper()}",
        "",
        d.conviction_rationale,
        "",
        "---",
        "",
        "_Report generated by Borkai — institutional-grade AI stock intelligence. "
        "For informational purposes only. Not financial advice._",
    ]

    return "\n".join(lines)
