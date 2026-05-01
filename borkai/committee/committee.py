"""
Stage 6: Investment Committee Decision

The committee receives the synthesis and makes the final call.
It builds bull/bear/base scenarios, assigns probabilities, determines
direction and conviction, and identifies what would invalidate the conclusion.

This is where the final investment judgment is formed.
"""
from dataclasses import dataclass, field
from typing import List
import openai

from typing import Optional

from ..config import Config
from ..agents.base_agent import AgentOutput
from ..orchestrator.profiler import StockProfile
from ..orchestrator.relevance_mapper import RelevanceMap
from ..committee.synthesizer import SynthesisResult
from ..utils.llm import call_llm, parse_json_response

VALID_DIRECTIONS = {"up", "conditional_up", "down", "mixed"}
VALID_CONVICTION = {"low", "moderate", "high"}

# Score thresholds that drive direction enforcement
_SCORE_BULLISH          = 70   # score >= this -> must be "up" or "conditional_up"
_SCORE_CONDITIONAL_LOW  = 55   # 55-69 -> "up" or "conditional_up", not "down"
_SCORE_MIXED_LOW        = 40   # 40-54 -> "mixed" expected; "down" only if analyst lean supports it
                                # < 40  -> "down"


def _enforce_direction(
    direction: str,
    invest_recommendation: str,
    return_score: int,
    conviction: str,
) -> tuple:
    """
    Enforce direction/recommendation consistency with the computed score.

    Rules (per spec):
      Score >= 70  -> "up"              invest can be YES or CONDITIONAL
      Score 55-69  -> "up" or "conditional_up"   invest can be YES or CONDITIONAL
      Score 40-54  -> "mixed" preferred   invest usually CONDITIONAL
      Score < 40   -> "down"             invest NO

    Risks do NOT create "mixed" — they reduce conviction.
    "mixed" is reserved for genuine two-sided uncertainty (strong bull AND bear signals).
    A high score with risks = "conditional_up", not "mixed".

    Returns (corrected_direction, corrected_recommendation, correction_note)
    """
    note = ""
    rec  = invest_recommendation.upper() if invest_recommendation else "CONDITIONAL"

    if return_score >= _SCORE_BULLISH:
        if direction not in ("up", "conditional_up"):
            note = (
                f"Direction auto-corrected: score {return_score} >= {_SCORE_BULLISH} "
                f"requires bullish direction (was: {direction})"
            )
            direction = "up"
        if rec == "NO":
            rec  = "CONDITIONAL"
            note += " | Recommendation lifted to CONDITIONAL (score too high for NO)"

    elif return_score >= _SCORE_CONDITIONAL_LOW:
        if direction == "down":
            note = (
                f"Direction auto-corrected: score {return_score} ({_SCORE_CONDITIONAL_LOW}-{_SCORE_BULLISH-1}) "
                f"is inconsistent with BEARISH (was: {direction})"
            )
            direction = "conditional_up"
        elif direction == "mixed":
            # Prefer conditional_up when score is clearly positive
            if return_score >= 62:
                direction = "conditional_up"
                note = (
                    f"Direction refined: score {return_score} with mixed signals -> conditional_up "
                    f"(risks acknowledged but dominant signal is positive)"
                )
        if rec == "NO":
            rec  = "CONDITIONAL"
            note += " | Recommendation lifted to CONDITIONAL (score too high for NO)"

    elif return_score < _SCORE_MIXED_LOW:
        if direction in ("up", "conditional_up"):
            note = (
                f"Direction auto-corrected: score {return_score} < {_SCORE_MIXED_LOW} "
                f"is inconsistent with BULLISH (was: {direction})"
            )
            direction = "down"
        if rec == "YES":
            rec  = "CONDITIONAL"
            note += " | Recommendation lowered to CONDITIONAL (score too low for YES)"

    return direction, rec, note


@dataclass
class Scenario:
    name: str               # "bull" | "bear" | "base"
    description: str        # What happens in this scenario
    probability: str        # e.g. "30%" — qualitative range, not false precision
    key_assumptions: List[str]
    expected_outcome: str


@dataclass
class CommitteeDecision:
    direction: str              # up | down | mixed
    confidence_score: str       # e.g. "moderate-high" — qualitative
    conviction: str             # low | moderate | high
    conviction_rationale: str   # Why this conviction level

    summary: str                # Plain-language 2-3 sentence summary

    bull_scenario: Scenario
    base_scenario: Scenario
    bear_scenario: Scenario

    key_bullish_factors: List[str]
    key_bearish_factors: List[str]
    key_risks: List[str]
    key_catalysts: List[str]
    key_assumptions: List[str]

    variant_perception: str     # Where might the market be wrong?
    research_gaps: List[str]
    what_would_invalidate: List[str]

    committee_debate_summary: str  # How the committee debated and resolved disagreements

    invest_recommendation: str   # YES | NO | CONDITIONAL
    invest_rationale: str        # One clear sentence explaining the recommendation
    return_score: int            # 0-100 composite expected return score for ranking

    # ── Enhanced signal fields ─────────────────────────────────────────────────
    risk_score: int = 5          # 1-10 composite risk level (1=very low, 10=very high)
    top_risks: list = None       # Top 3 risks by materiality
    market_regime: str = ""      # risk-on / risk-off / neutral + one sentence on impact
    signal_summary: str = ""     # Formatted signal list: "+ Revenue ↑\n- Valuation ↓\nNet: Bullish"
    relative_strength: str = ""  # Outperforming / underperforming vs sector and market
    consistency_note: str = ""   # Are signals consistent? Call out any contradictions.

    def __post_init__(self):
        if self.top_risks is None:
            self.top_risks = []


_SYSTEM = """You are chairing an investment committee at a top-tier investment firm.
You have received analysis from multiple expert analysts and a synthesis of their views.
Your job is to make the final investment judgment.

You think probabilistically. You build scenarios, not predictions.
You distinguish between facts, interpretations, and assumptions.
You are honest about uncertainty — and you are explicit about what would prove you wrong.

The final output must read like a real investment committee memo.
Return only valid JSON. No prose outside the JSON object."""


def _format_synthesis(synthesis: SynthesisResult) -> str:
    lines = [
        f"Overall lean: {synthesis.overall_lean.upper()}",
        f"Agreement summary: {synthesis.agreement_summary}",
        f"Consensus confidence: {synthesis.consensus_confidence}",
        "",
        "Agreements:",
    ]
    for a in synthesis.agreements:
        lines.append(f"  [{a.strength}] {a.topic}: {a.shared_view}")
    lines.append("\nDisagreements:")
    for d in synthesis.disagreements:
        lines.append(
            f"  [{d.conflict_type}] {d.topic}\n"
            f"    {d.agent_a}: {d.view_a}\n"
            f"    {d.agent_b}: {d.view_b}\n"
            f"    Resolution: {d.resolution}"
        )
    lines.append("\nUnresolved tensions:")
    for t in synthesis.unresolved_tensions:
        lines.append(f"  • {t}")
    return "\n".join(lines)


def _format_agent_summaries(outputs: List[AgentOutput]) -> str:
    lines = []
    for out in outputs:
        lines.append(
            f"• {out.agent_name}: {out.stance.upper()} ({out.confidence} confidence) — {out.key_finding}"
        )
    return "\n".join(lines)


def _parse_return_score(raw_value, computed_score: Optional[int]) -> int:
    """
    Parse the LLM's return_score and enforce the ±5 constraint when a
    computed_score was provided by the scoring engine.
    """
    try:
        llm_score = int(raw_value) if isinstance(raw_value, (int, float)) else 50
    except (TypeError, ValueError):
        llm_score = 50

    llm_score = max(0, min(100, llm_score))

    if computed_score is not None:
        # Hard clamp: LLM may only move the score ±5 from the system-computed value
        llm_score = max(computed_score - 5, min(computed_score + 5, llm_score))

    return llm_score


def run_investment_committee(
    outputs: List[AgentOutput],
    synthesis: SynthesisResult,
    profile: StockProfile,
    relevance_map: RelevanceMap,
    client: openai.OpenAI,
    config: Config,
    computed_score: Optional[int] = None,
) -> CommitteeDecision:
    """
    Run the investment committee and produce the final decision.
    """
    synthesis_text = _format_synthesis(synthesis)
    agent_summaries = _format_agent_summaries(outputs)
    key_questions = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(relevance_map.key_questions))

    # Build the score-validation block
    if computed_score is not None:
        score_block = (
            f"\nCOMPUTED SCORE (system-calculated, do NOT invent a new number):\n"
            f"  Raw score: {computed_score}/100\n"
            f"  Your job: validate this score and optionally adjust by at most ±5 points.\n"
            f"  Set return_score = {computed_score} ± 5 only. Justify any adjustment in conviction_rationale.\n"
        )
    else:
        score_block = ""

    prompt = f"""{config.market_context}
Investment Committee for: {profile.ticker} ({profile.company_name})
Time horizon: {profile.time_horizon.upper()}
Phase: {profile.phase}
{score_block}

QUESTIONS THIS ANALYSIS SET OUT TO ANSWER:
{key_questions}

ANALYST TEAM POSITIONS:
{agent_summaries}

SYNTHESIS:
{synthesis_text}

Make the investment committee decision. Return a JSON object:
{{
  "direction": "<up | conditional_up | down | mixed — RULES BELOW>",
  "confidence_score": "<e.g. 'moderate', 'moderate-high', 'low' — be honest, not precise>",
  "conviction": "<low | moderate | high>",
  "conviction_rationale": "<Why exactly this conviction level? Reference specific agreements/disagreements/gaps>",

  "summary": "<2-3 plain-language sentences. What is the bottom line and why? Understandable to a non-expert.>",

  "bull_scenario": {{
    "name": "bull",
    "description": "<what happens in this scenario — be specific to {profile.ticker}>",
    "probability": "<rough probability range, e.g. '25-35%'>",
    "key_assumptions": ["<what must be true for this scenario>"],
    "expected_outcome": "<what price/performance outcome looks like>"
  }},
  "base_scenario": {{
    "name": "base",
    "description": "<most likely path>",
    "probability": "<e.g. '45-55%'>",
    "key_assumptions": ["<what must be true>"],
    "expected_outcome": "<expected outcome>"
  }},
  "bear_scenario": {{
    "name": "bear",
    "description": "<downside path>",
    "probability": "<e.g. '20-30%'>",
    "key_assumptions": ["<what must be true>"],
    "expected_outcome": "<expected outcome>"
  }},

  "key_bullish_factors": ["<top bullish drivers, ordered by materiality>"],
  "key_bearish_factors": ["<top bearish risks, ordered by materiality>"],
  "key_risks": ["<risks that could cause material underperformance>"],
  "key_catalysts": ["<specific near-term and long-term events that could move the stock>"],
  "key_assumptions": ["<the most critical assumptions underlying the base case>"],

  "variant_perception": "<Where might the market be mispricing this? What does Borkai see that consensus misses?>",
  "research_gaps": ["<what we don't know that could materially change the conclusion>"],
  "what_would_invalidate": ["<specific developments that would prove this thesis wrong>"],

  "committee_debate_summary": "<2-3 sentences: how did the committee weigh disagreements? How were conflicts resolved? What drove the final conviction level?>",

  "invest_recommendation": "<YES | NO | CONDITIONAL — a single binary team verdict: should capital be deployed in this stock now?>",
  "invest_rationale": "<One direct sentence explaining the recommendation. Be concrete — reference the specific dominant factor that tipped the decision.>",

  "return_score": <integer 0-100. IMPORTANT: If a computed_score was provided above, you MUST stay within ±5 of that number. The system has already calculated a structured score from financial data, filings, news, technical signals, and analyst votes. Your role is to VALIDATE, not reinvent. Only adjust if you see a compelling qualitative reason the system could not capture (e.g. a binary event risk, a major geopolitical factor, a thesis-invalidating development visible in the reasoning but not in raw data). If no computed_score was provided, use: 50=neutral, >70=meaningfully bullish, <30=meaningfully bearish.>,

  "risk_score": <integer 1-10. Composite risk level. 1=very low risk, 10=extremely high risk.
    Consider: valuation risk, geopolitical exposure, execution risk, currency risk, liquidity, leverage, regulatory risk.
    Most stocks score 3-7. Score >8 only if multiple material risks compound each other.>,
  "top_risks": ["<top 3 specific risks ordered by materiality — be concrete, not generic>"],
  "market_regime": "<Is the current market environment risk-on, risk-off, or neutral? One sentence on how this regime specifically affects {profile.ticker} (sector tailwinds/headwinds, currency impact, macro sensitivity).>",
  "signal_summary": "<Compressed signal list. Format exactly as follows — one signal per line, '+' for bullish, '-' for bearish, then blank line, then 'Net: [lean]'. Example: '+ Strong earnings growth\\n+ Positive Maya filings\\n- High valuation\\n- Currency headwind\\n\\nNet: Bullish'>",
  "relative_strength": "<Is {profile.ticker} outperforming, underperforming, or inline with its sector and the broader market? Reference specific price performance or momentum data.>",
  "consistency_note": "<Do all signal types align? Check: financials vs price trend vs news vs filings vs analyst stances. If signals are consistent, confirm it. If there are contradictions, identify exactly what conflicts and why it matters for the investment decision.>"
}}

DIRECTION RULES (CRITICAL — follow exactly):
  "up"             : Majority of strong signals are positive. No major contradiction.
                     Risks exist but do NOT dominate. Score typically >= 65.
  "conditional_up" : Positive signals dominate, but ONE meaningful risk could change the outcome.
                     Use this — NOT "mixed" — when a high score coexists with a specific risk.
                     Score typically 50-70. Example: strong growth + currency/regulatory risk.
  "mixed"          : Strong signals exist on BOTH the bull AND bear side simultaneously.
                     Genuine two-sided uncertainty where you cannot call a dominant direction.
                     NOT a catch-all for "there are some risks". Score typically 40-60.
  "down"           : Majority of strong signals are negative. Score typically < 45.

  IMPORTANT: "mixed" means BOTH sides are strong. A positive dominant signal with risks =
  "conditional_up". Do NOT use "mixed" just because risks exist.

SCORE ALIGNMENT (direction must be consistent with return_score):
  Score >= 70   -> direction MUST be "up" or "conditional_up"
  Score 55-69   -> direction must be "up" or "conditional_up" (not "down", not "mixed" unless truly two-sided)
  Score 40-54   -> "mixed" is appropriate; "conditional_up" if lean is positive
  Score < 40    -> direction must be "down"

RULES:
- Do NOT express false precision. "moderate-high confidence" is more honest than "73%"
- Conviction is REDUCED if there are meaningful unresolved disagreements — but direction stays aligned with score
- Risks reduce conviction and may trigger "conditional_up" — they do NOT flip direction to "mixed" or "down"
- Scenarios must be internally consistent — each must have plausible assumptions
- variant_perception must identify something specific, not just say 'market may be wrong'
- what_would_invalidate must be specific events or data points, not vague risks"""

    raw = call_llm(
        client=client,
        model=config.models.committee,
        system=_SYSTEM,
        prompt=prompt,
        max_tokens=6000,
        expect_json=True,
    )
    data = parse_json_response(raw)

    def _parse_scenario(d: dict, default_name: str) -> Scenario:
        return Scenario(
            name=d.get("name", default_name),
            description=d.get("description", ""),
            probability=d.get("probability", "unknown"),
            key_assumptions=d.get("key_assumptions", []),
            expected_outcome=d.get("expected_outcome", ""),
        )

    direction = data.get("direction", "mixed")
    if direction not in VALID_DIRECTIONS:
        direction = "mixed"

    conviction = data.get("conviction", "low")
    if conviction not in VALID_CONVICTION:
        conviction = "low"

    raw_risk = data.get("risk_score", 5)
    risk_score = max(1, min(10, int(raw_risk) if isinstance(raw_risk, (int, float)) else 5))

    # Parse final score first so enforcement can use it
    parsed_score = _parse_return_score(data.get("return_score"), computed_score)
    invest_rec   = data.get("invest_recommendation", "CONDITIONAL")

    # Enforce direction/recommendation consistency with score
    direction, invest_rec, correction_note = _enforce_direction(
        direction, invest_rec, parsed_score, conviction
    )

    # Append correction note to conviction_rationale so it's visible in the report
    conviction_rationale = data.get("conviction_rationale", "")
    if correction_note:
        conviction_rationale = f"{conviction_rationale} [AUTO-CORRECTED: {correction_note}]".strip()

    return CommitteeDecision(
        direction=direction,
        confidence_score=data.get("confidence_score", "low"),
        conviction=conviction,
        conviction_rationale=conviction_rationale,
        summary=data.get("summary", ""),
        bull_scenario=_parse_scenario(data.get("bull_scenario", {}), "bull"),
        base_scenario=_parse_scenario(data.get("base_scenario", {}), "base"),
        bear_scenario=_parse_scenario(data.get("bear_scenario", {}), "bear"),
        key_bullish_factors=data.get("key_bullish_factors", []),
        key_bearish_factors=data.get("key_bearish_factors", []),
        key_risks=data.get("key_risks", []),
        key_catalysts=data.get("key_catalysts", []),
        key_assumptions=data.get("key_assumptions", []),
        variant_perception=data.get("variant_perception", ""),
        research_gaps=data.get("research_gaps", []),
        what_would_invalidate=data.get("what_would_invalidate", []),
        committee_debate_summary=data.get("committee_debate_summary", ""),
        invest_recommendation=invest_rec,
        invest_rationale=data.get("invest_rationale", ""),
        return_score=parsed_score,
        risk_score=risk_score,
        top_risks=data.get("top_risks", []),
        market_regime=data.get("market_regime", ""),
        signal_summary=data.get("signal_summary", ""),
        relative_strength=data.get("relative_strength", ""),
        consistency_note=data.get("consistency_note", ""),
    )
