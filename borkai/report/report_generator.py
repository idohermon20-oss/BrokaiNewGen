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
from typing import List, Optional
from datetime import date

from ..agents.base_agent import AgentOutput
from ..orchestrator.profiler import StockProfile
from ..orchestrator.relevance_mapper import RelevanceMap
from ..orchestrator.sector_analyzer import SectorAnalysis
from ..committee.synthesizer import SynthesisResult
from ..committee.committee import CommitteeDecision


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


# ---------------------------------------------------------------------------
# Visual helpers
# ---------------------------------------------------------------------------

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
        "up":    "BULLISH ↑",
        "down":  "BEARISH ↓",
        "mixed": "MIXED ↔",
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

    # Top articles (up to 5, bullish/bearish first)
    if result.article_impacts:
        lines.append("### Latest Articles")
        lines.append("")
        sorted_arts = sorted(
            result.article_impacts,
            key=lambda a: (0 if a.impact == "bullish" else 1 if a.impact == "bearish" else 2),
        )
        for art in sorted_arts[:5]:
            src = f"_{art.source}_  " if art.source else ""
            url_part = f"[{art.title}]({art.url})" if art.url else art.title
            summary = f" — {art.impact_summary}" if art.impact_summary else ""
            lines.append(f"- {_impact_badge(art.impact)} {src}{url_part}{summary}")
        lines.append("")

    # Top Maya filings (up to 5)
    if result.maya_reports:
        lines.append("### Maya / TASE Filings")
        lines.append("")
        sorted_maya = sorted(
            result.maya_reports,
            key=lambda r: (0 if r.impact == "bullish" else 1 if r.impact == "bearish" else 2),
        )
        for rep in sorted_maya[:5]:
            src = f"_{rep.source}_  " if rep.source else ""
            url_part = f"[{rep.title}]({rep.link})" if rep.link else rep.title
            reason = f" — {rep.impact_reason}" if rep.impact_reason else ""
            lines.append(f"- {_impact_badge(rep.impact)} {src}{url_part}{reason}")
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

    sa = result.sector_analysis
    if sa and not sa.analysis_skipped:
        sentiment_icon = {"bullish": "📈", "bearish": "📉", "mixed": "↔️", "neutral": "➡️"}.get(
            sa.market_sentiment, "➡️"
        )
        lines += [
            f"**Sector Sentiment ({sa.sector}):** {sentiment_icon} {sa.market_sentiment.upper()}",
            f"> {sa.sentiment_rationale}",
            "",
            f"**Relevance to {result.ticker}:** {sa.relevance_to_stock}",
            "",
        ]

    lines += ["---", ""]

    # ── 2. ANALYST TEAM ─────────────────────────────────────────────────────
    n = len(result.agent_outputs)
    lines += [
        f"## 2. Analyst Team  ({n} analysts)",
        "",
        _vote_row(result.agent_outputs),
        "",
        "| # | Analyst | Stance | Key Finding |",
        "|---|---------|:------:|-------------|",
    ]
    for i, out in enumerate(result.agent_outputs, 1):
        icon = _stance_icon(out.stance)
        # One-sentence key finding — truncate at first sentence boundary or 120 chars
        finding = out.key_finding or ""
        # Cut at first period/! that ends a sentence (not in abbreviation)
        import re
        first_sentence = re.split(r'(?<=[.!?])\s', finding.strip())
        short = first_sentence[0] if first_sentence else finding
        if len(short) > 130:
            short = short[:127] + "…"
        conf_icon = {"high": "●●●", "moderate": "●●○", "low": "●○○"}.get(out.confidence.lower(), "●○○")
        lines.append(f"| {i} | **{out.agent_name}** | {icon} `{conf_icon}` | {short} |")

    lines += ["", "---", ""]

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
    lines += [
        "## 4. Investment Committee Verdict",
        "",
        f"## {invest_badge}",
        "",
        f"**Direction:** {direction_label}  |  **Conviction:** {conviction_stars}  |  "
        f"**Return Score:** {score}/100",
        "",
        f"> {d.invest_rationale}",
        "",
        f"{d.summary}",
        "",
    ]

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
            url_part = f"[{art.title}]({art.url})" if art.url else art.title
            source_date = " · ".join(filter(None, [art.source, art.published[:10] if art.published else ""]))
            summary = f"\n  > {art.impact_summary}" if art.impact_summary else ""
            lines.append(f"- {_impact_badge(art.impact)}  **{source_date}**  {url_part}{summary}")
            lines.append("")
    else:
        lines.append("_No articles retrieved._")
    lines += ["", "---", ""]

    # ── 6. MAYA / TASE FILINGS ──────────────────────────────────────────────
    lines += [f"## 6. Maya / TASE Regulatory Filings  ({len(result.maya_reports)} filings)", ""]
    if result.maya_reports:
        for rep in result.maya_reports:
            url_part = f"[{rep.title}]({rep.link})" if rep.link else rep.title
            source_date = " · ".join(filter(None, [
                rep.source,
                rep.published[:10] if rep.published else "",
                rep.report_type.replace("_", " ").title() if rep.report_type != "other" else "",
            ]))
            reason = f"\n  > {rep.impact_reason}" if rep.impact_reason else ""
            lines.append(f"- {_impact_badge(rep.impact)}  **{source_date}**  {url_part}{reason}")
            lines.append("")
    else:
        lines.append("_No Maya/TASE filings retrieved._")
    lines += ["", "---", ""]

    # ── 7. CONVICTION RATIONALE ─────────────────────────────────────────────
    lines += [
        "## 7. Conviction Rationale",
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
