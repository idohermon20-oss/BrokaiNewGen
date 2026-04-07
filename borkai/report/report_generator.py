"""
Report Generation

Assembles all analysis into a structured, institutional-quality research report.
Report order:
  1. Stock Overview
  2. Analysis Team
  3. Individual Expert Opinions
  4. Synthesis & Bias Check
  5. Investment Committee Verdict
  6. Recent Articles (with per-article impact)
  7. Maya / TASE Regulatory Reports (with per-report impact)
  8. Conviction Rationale
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

    # Per-article impact assessments (populated in main.py)
    article_impacts: list = field(default_factory=list)   # List[ArticleImpact]
    # Company-specific Maya/TASE filings (populated in main.py)
    maya_reports: list = field(default_factory=list)      # List[MayaReport]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _impact_badge(impact: str) -> str:
    return {
        "bullish": "🟢 BULLISH",
        "bearish": "🔴 BEARISH",
        "neutral": "⚪ NEUTRAL",
    }.get(impact.lower(), f"⚪ {impact.upper()}")


def _stance_badge(stance: str) -> str:
    return {
        "bullish": "🟢 BULLISH",
        "bearish": "🔴 BEARISH",
        "neutral": "⚪ NEUTRAL",
        "mixed":   "🟡 MIXED",
    }.get(stance.lower(), stance.upper())


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
        "CONDITIONAL": "⚠️ CONDITIONAL",
    }.get(d.invest_recommendation.upper(), d.invest_recommendation.upper())

    direction_label = {
        "up":    "BULLISH ↑",
        "down":  "BEARISH ↓",
        "mixed": "MIXED / NEUTRAL ↔",
    }.get(d.direction, d.direction.upper())

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

    # ── HIGHLIGHTS ──────────────────────────────────────────────────────────
    lines += [
        "## HIGHLIGHTS",
        "",
        f"**Verdict:** {invest_badge}  |  **Direction:** {direction_label}  |  "
        f"**Return Score:** {d.return_score}/100  |  **Conviction:** {d.conviction.upper()}",
        "",
    ]

    # Top articles (up to 5, sorted bearish/bullish before neutral)
    if result.article_impacts:
        lines.append("### Latest Articles")
        lines.append("")
        sorted_arts = sorted(
            result.article_impacts,
            key=lambda a: (0 if a.impact == "bullish" else 1 if a.impact == "bearish" else 2),
        )
        for art in sorted_arts[:5]:
            badge = _impact_badge(art.impact)
            url_part = f"[{art.title}]({art.url})" if art.url else art.title
            src = f"_{art.source}_  " if art.source else ""
            summary = f" — {art.impact_summary}" if art.impact_summary else ""
            lines.append(f"- {badge} {src}{url_part}{summary}")
        lines.append("")

    # Top Maya reports (up to 5)
    if result.maya_reports:
        lines.append("### Maya / TASE Filings")
        lines.append("")
        sorted_maya = sorted(
            result.maya_reports,
            key=lambda r: (0 if r.impact == "bullish" else 1 if r.impact == "bearish" else 2),
        )
        for rep in sorted_maya[:5]:
            badge = _impact_badge(rep.impact)
            url_part = f"[{rep.title}]({rep.link})" if rep.link else rep.title
            src = f"_{rep.source}_  " if rep.source else ""
            reason = f" — {rep.impact_reason}" if rep.impact_reason else ""
            lines.append(f"- {badge} {src}{url_part}{reason}")
        lines.append("")

    lines += [
        "---",
        "",

        # ── 1. STOCK OVERVIEW ──────────────────────────────────────────────
        "## 1. STOCK OVERVIEW",
        "",
        f"**Sector:** {p.sector_dynamics}",
        "",
        f"**Current Situation:**  {p.current_situation}",
        "",
        f"**What the Market Is Focused On:**  {p.what_market_is_focused_on}",
        "",
        f"**Horizon Implications ({result.time_horizon.upper()}):**  {p.horizon_implications}",
        "",
    ]

    if p.key_characteristics:
        lines.append("**Key Characteristics:**")
        for kc in p.key_characteristics:
            lines.append(f"- {kc}")
        lines.append("")

    # Sector intelligence (if available)
    sa = result.sector_analysis
    if sa and not sa.analysis_skipped:
        sentiment_label = {
            "bullish": "BULLISH", "bearish": "BEARISH",
            "mixed": "MIXED", "neutral": "NEUTRAL",
        }.get(sa.market_sentiment, sa.market_sentiment.upper())
        lines += [
            f"**Sector Sentiment ({sa.sector}):** {sentiment_label}",
            f"> {sa.sentiment_rationale}",
            "",
        ]
        if sa.relevance_to_stock:
            lines += [f"**Sector Relevance to {result.ticker}:** {sa.relevance_to_stock}", ""]

    lines += [
        "---",
        "",

        # ── 2. ANALYSIS TEAM ───────────────────────────────────────────────
        f"## 2. ANALYSIS TEAM  ({len(result.agent_outputs)} analysts)",
        "",
        "| # | Analyst | Specialty | Stance | Confidence |",
        "|---|---------|-----------|--------|------------|",
    ]
    for i, out in enumerate(result.agent_outputs, 1):
        lines.append(
            f"| {i} | **{out.agent_name}** | {out.domain} "
            f"| {_stance_badge(out.stance)} | {out.confidence.upper()} |"
        )

    lines += [
        "",
        "---",
        "",

        # ── 3. INDIVIDUAL EXPERT OPINIONS ─────────────────────────────────
        "## 3. INDIVIDUAL EXPERT OPINIONS",
        "",
    ]

    for out in result.agent_outputs:
        lines += [
            f"### {out.agent_name}",
            f"**Domain:** {out.domain}  |  "
            f"**Stance:** {_stance_badge(out.stance)}  |  "
            f"**Confidence:** {out.confidence.upper()}",
            "",
            f"**Key Finding:** {out.key_finding}",
            "",
            "**Reasoning:**",
            "",
            str(out.full_reasoning),
            "",
        ]
        if out.evidence:
            lines.append("**Evidence:**")
            for e in out.evidence:
                badge = _impact_badge(e.direction)
                lines.append(
                    f"- {badge} _{e.fact}_ "
                    f"(source: {e.source}, relevance: {e.relevance}, reliability: {e.reliability})  "
                    f"→ {e.interpretation}"
                )
            lines.append("")
        if out.key_unknowns:
            lines.append("**Key Unknowns:**")
            for u in out.key_unknowns:
                lines.append(f"- {u}")
            lines.append("")
        if out.flags_for_committee:
            lines.append("**Flags for Committee:**")
            for f_ in out.flags_for_committee:
                lines.append(f"- {f_}")
            lines.append("")
        lines.append("---")
        lines.append("")

    lines += [
        # ── 4. SYNTHESIS & BIAS CHECK ──────────────────────────────────────
        "## 4. SYNTHESIS & BIAS CHECK",
        "",
        f"**Overall Lean:** {s.overall_lean.upper()}  |  "
        f"**Consensus Confidence:** {s.consensus_confidence.upper()}",
        "",
        f"{s.agreement_summary}",
        "",
    ]

    if s.agreements:
        lines.append("### Where Analysts Agree")
        for a in s.agreements:
            agents_str = ", ".join(a.agents_involved)
            lines.append(f"- **[{a.strength.upper()}]** {a.topic}: {a.shared_view} _(analysts: {agents_str})_")
        lines.append("")

    if s.disagreements:
        lines.append("### Where Analysts Disagree")
        for dis in s.disagreements:
            lines += [
                f"- **[{dis.conflict_type.upper()}]** {dis.topic}",
                f"  - {dis.agent_a}: {dis.view_a}",
                f"  - {dis.agent_b}: {dis.view_b}",
                f"  - _Resolution:_ {dis.resolution}",
                f"  - _Committee implication:_ {dis.committee_implication}",
            ]
        lines.append("")

    if s.unresolved_tensions:
        lines.append("### Unresolved Tensions")
        for t in s.unresolved_tensions:
            lines.append(f"- {t}")
        lines.append("")

    if s.bias_assessment:
        lines += [
            "### Bias Check",
            "",
            f"> {s.bias_assessment}",
            "",
        ]

    if s.strongest_evidence_domains:
        lines.append(f"**Strongest evidence:** {', '.join(s.strongest_evidence_domains)}")
    if s.weakest_evidence_domains:
        lines.append(f"**Weakest evidence:** {', '.join(s.weakest_evidence_domains)}")

    lines += [
        "",
        "---",
        "",

        # ── 5. INVESTMENT COMMITTEE VERDICT ───────────────────────────────
        "## 5. INVESTMENT COMMITTEE VERDICT",
        "",
        f"## {invest_badge}",
        "",
        f"**Direction:** {direction_label}",
        f"**Conviction:** {d.conviction.upper()}",
        f"**Return Score:** {d.return_score}/100",
        f"**Confidence:** {d.confidence_score}",
        "",
        f"> {d.invest_rationale}",
        "",
        f"{d.summary}",
        "",
        f"_{d.committee_debate_summary}_",
        "",
        "### Scenario Analysis",
        "",
        "#### 🐂 Bull Case",
        f"**Probability:** {d.bull_scenario.probability}",
        "",
        str(d.bull_scenario.description),
        "",
        "**Key assumptions:**",
    ]
    for a in d.bull_scenario.key_assumptions:
        lines.append(f"- {a}")
    lines += [
        f"**Expected outcome:** {d.bull_scenario.expected_outcome}",
        "",
        "#### ⚖️ Base Case",
        f"**Probability:** {d.base_scenario.probability}",
        "",
        str(d.base_scenario.description),
        "",
        "**Key assumptions:**",
    ]
    for a in d.base_scenario.key_assumptions:
        lines.append(f"- {a}")
    lines += [
        f"**Expected outcome:** {d.base_scenario.expected_outcome}",
        "",
        "#### 🐻 Bear Case",
        f"**Probability:** {d.bear_scenario.probability}",
        "",
        str(d.bear_scenario.description),
        "",
        "**Key assumptions:**",
    ]
    for a in d.bear_scenario.key_assumptions:
        lines.append(f"- {a}")
    lines += [
        f"**Expected outcome:** {d.bear_scenario.expected_outcome}",
        "",
        "### Key Factors",
        "",
        "**Bullish Factors:**",
    ]
    for f_ in d.key_bullish_factors:
        lines.append(f"- {f_}")
    lines.append("")
    lines.append("**Bearish Factors:**")
    for f_ in d.key_bearish_factors:
        lines.append(f"- {f_}")
    lines.append("")
    lines.append("**Key Risks:**")
    for r in d.key_risks:
        lines.append(f"- {r}")
    lines.append("")
    lines.append("**Catalysts to Watch:**")
    for c in d.key_catalysts:
        lines.append(f"- {c}")
    lines.append("")
    lines.append("**What Would Invalidate This Thesis:**")
    for w in d.what_would_invalidate:
        lines.append(f"- {w}")

    lines += [
        "",
        "**Variant Perception:**",
        "",
        str(d.variant_perception),
        "",
        "---",
        "",

        # ── 6. RECENT ARTICLES ─────────────────────────────────────────────
        f"## 6. RECENT ARTICLES  ({len(result.article_impacts)} articles)",
        "",
    ]

    if result.article_impacts:
        for art in result.article_impacts:
            badge = _impact_badge(art.impact)
            url_part = f"[{art.title}]({art.url})" if art.url else art.title
            source_date = " · ".join(filter(None, [art.source, art.published[:10] if art.published else ""]))
            lines += [
                f"### {url_part}",
                f"**Source:** {source_date}  |  **Impact:** {badge}",
                "",
            ]
            if art.impact_summary:
                lines.append(f"> {art.impact_summary}")
            lines.append("")
    else:
        lines.append("_No articles were retrieved for this analysis._")
        lines.append("")

    lines += [
        "---",
        "",

        # ── 7. MAYA / TASE REGULATORY REPORTS ─────────────────────────────
        f"## 7. MAYA / TASE REGULATORY REPORTS  ({len(result.maya_reports)} filings)",
        "",
    ]

    if result.maya_reports:
        for rep in result.maya_reports:
            badge = _impact_badge(rep.impact)
            url_part = f"[{rep.title}]({rep.link})" if rep.link else rep.title
            source_date = " · ".join(filter(None, [
                rep.source,
                rep.published[:10] if rep.published else "",
                rep.report_type if rep.report_type != "other" else "",
            ]))
            lines += [
                f"### {url_part}",
                f"**Filing type:** {rep.report_type.replace('_', ' ').title()}  |  "
                f"**Source:** {source_date}  |  **Impact:** {badge}",
                "",
            ]
            if rep.impact_reason:
                lines.append(f"> {rep.impact_reason}")
            lines.append("")
    else:
        lines.append("_No Maya/TASE filings were retrieved for this analysis._")
        lines.append("")

    lines += [
        "---",
        "",

        # ── 8. CONVICTION RATIONALE ────────────────────────────────────────
        "## 8. CONVICTION RATIONALE",
        "",
        f"**Conviction Level:** {d.conviction.upper()}",
        "",
        d.conviction_rationale,
        "",
        "---",
        "",
        "_This report was generated by Borkai — an adaptive, institutional-grade stock "
        "intelligence system. It is for informational purposes only and does not constitute "
        "financial advice._",
    ]

    return "\n".join(lines)
