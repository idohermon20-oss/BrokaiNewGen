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

from ..config import Config
from ..agents.base_agent import AgentOutput
from ..orchestrator.profiler import StockProfile
from ..orchestrator.relevance_mapper import RelevanceMap
from ..committee.synthesizer import SynthesisResult
from ..utils.llm import call_llm, parse_json_response

VALID_DIRECTIONS = {"up", "down", "mixed"}
VALID_CONVICTION = {"low", "moderate", "high"}


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
            f"• {out.agent_name}: {out.stance.upper()} ({out.confidence} confidence) — {out.key_finding[:200]}"
        )
    return "\n".join(lines)


def run_investment_committee(
    outputs: List[AgentOutput],
    synthesis: SynthesisResult,
    profile: StockProfile,
    relevance_map: RelevanceMap,
    client: openai.OpenAI,
    config: Config,
) -> CommitteeDecision:
    """
    Run the investment committee and produce the final decision.
    """
    synthesis_text = _format_synthesis(synthesis)
    agent_summaries = _format_agent_summaries(outputs)
    key_questions = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(relevance_map.key_questions))

    prompt = f"""{config.market_context}
Investment Committee for: {profile.ticker} ({profile.company_name})
Time horizon: {profile.time_horizon.upper()}
Phase: {profile.phase}

QUESTIONS THIS ANALYSIS SET OUT TO ANSWER:
{key_questions}

ANALYST TEAM POSITIONS:
{agent_summaries}

SYNTHESIS:
{synthesis_text}

Make the investment committee decision. Return a JSON object:
{{
  "direction": "<up | down | mixed>",
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

  "return_score": <integer 0-100. Composite expected return score for this stock in the given time horizon.
    50 = neutral/no edge. >70 = meaningfully bullish expected return. <30 = meaningfully bearish.
    Factor in: direction, conviction, base-case probability, upside/downside asymmetry, and time-adjusted expected value.
    Calibration guide: most stocks score 35-65. Only score >80 if conviction=high AND direction=up. Only score <20 if conviction=high AND direction=down.
    This score is used to rank stocks against each other — be consistent and honest.>
}}

RULES:
- Do NOT express false precision. "moderate-high confidence" is more honest than "73%"
- Conviction is REDUCED if there are meaningful unresolved disagreements
- Scenarios must be internally consistent — each must have plausible assumptions
- variant_perception must identify something specific, not just say 'market may be wrong'
- what_would_invalidate must be specific events or data points, not vague risks"""

    raw = call_llm(
        client=client,
        model=config.models.committee,
        system=_SYSTEM,
        prompt=prompt,
        max_tokens=5000,
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

    return CommitteeDecision(
        direction=direction,
        confidence_score=data.get("confidence_score", "low"),
        conviction=conviction,
        conviction_rationale=data.get("conviction_rationale", ""),
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
        invest_recommendation=data.get("invest_recommendation", "CONDITIONAL"),
        invest_rationale=data.get("invest_rationale", ""),
        return_score=max(0, min(100, int(data.get("return_score", 50))
                                if isinstance(data.get("return_score"), (int, float)) else 50)),
    )
