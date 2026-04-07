"""
Stage 5: Cross-Agent Synthesis

Before the investment committee meets, this stage maps the landscape
of all agent outputs: where they agree, where they conflict,
which evidence is strongest, and what remains unresolved.

Disagreements are features, not bugs. This is where variant perception lives.
"""
from dataclasses import dataclass, field
from typing import List
import openai

from ..config import Config
from ..agents.base_agent import AgentOutput
from ..orchestrator.profiler import StockProfile
from ..utils.llm import call_llm, parse_json_response

VALID_DISAGREEMENT_TYPES = {
    "factual",      # Two agents have conflicting data
    "interpretive", # Same data, different meaning
    "horizon",      # Bearish short-term, bullish long-term (or vice versa)
    "weight",       # Agents disagree on how much a factor matters
}


@dataclass
class Agreement:
    topic: str
    agents_involved: List[str]
    shared_view: str
    strength: str  # strong | moderate | weak


@dataclass
class Disagreement:
    topic: str
    conflict_type: str  # factual | interpretive | horizon | weight
    agent_a: str
    view_a: str
    agent_b: str
    view_b: str
    resolution: str     # Which agent has stronger evidence, or "unresolved"
    committee_implication: str


@dataclass
class SynthesisResult:
    overall_lean: str           # bullish | bearish | neutral | deeply_mixed
    agreement_summary: str
    agreements: List[Agreement]
    disagreements: List[Disagreement]
    strongest_evidence_domains: List[str]
    weakest_evidence_domains: List[str]
    unresolved_tensions: List[str]
    consensus_confidence: str   # low | moderate | high
    bias_assessment: str = ""   # Groupthink / anchoring / contrarian bias check


_SYSTEM = """You are a senior research director reviewing outputs from multiple analyst teams.
Your job is to map the analytical landscape before the investment committee convenes:
- Where do analysts agree and how strongly?
- Where do they disagree and why?
- Which analysts have the strongest evidence?
- What tensions remain unresolved?

You are building the foundation for the committee's deliberation.
Be precise about conflict types. Do not force false consensus.
Return only valid JSON. No prose outside the JSON object."""


def _format_agent_outputs(outputs: List[AgentOutput]) -> str:
    lines = []
    for out in outputs:
        lines += [
            f"--- {out.agent_name} ({out.domain}) ---",
            f"Stance: {out.stance.upper()} | Confidence: {out.confidence}",
            f"Key Finding: {out.key_finding}",
            "Evidence highlights:",
        ]
        for e in out.evidence[:4]:
            lines.append(
                f"  [{e.direction}|{e.relevance} relevance|{e.reliability} reliability] "
                f"{e.fact} → {e.interpretation}"
            )
        if out.key_unknowns:
            lines.append(f"Key unknowns: {'; '.join(out.key_unknowns[:3])}")
        if out.flags_for_committee:
            lines.append(f"Flags: {'; '.join(out.flags_for_committee[:3])}")
        lines.append("")
    return "\n".join(lines)


def synthesize_agent_outputs(
    outputs: List[AgentOutput],
    profile: StockProfile,
    client: openai.OpenAI,
    config: Config,
) -> SynthesisResult:
    """
    Synthesize all agent outputs before the investment committee.
    Maps agreements, disagreements, evidence strength, and open tensions.
    """
    agents_text = _format_agent_outputs(outputs)
    agent_names = [o.agent_name for o in outputs]

    prompt = f"""{config.market_context}
You are synthesizing analyst team outputs for {profile.ticker} ({profile.company_name}).
Time horizon: {profile.time_horizon.upper()}

ANALYST OUTPUTS:
{agents_text}

Produce a synthesis that maps the analytical landscape. Return a JSON object:
{{
  "overall_lean": "<bullish | bearish | neutral | deeply_mixed — based on weight of evidence across all analysts>",
  "agreement_summary": "<1-2 sentences: where do analysts broadly agree? What is the shared view?>",
  "agreements": [
    {{
      "topic": "<what they agree on>",
      "agents_involved": ["<agent names>"],
      "shared_view": "<what the shared view is>",
      "strength": "<strong | moderate | weak>"
    }}
  ],
  "disagreements": [
    {{
      "topic": "<what they disagree on>",
      "conflict_type": "<factual | interpretive | horizon | weight>",
      "agent_a": "<agent name>",
      "view_a": "<agent A's view>",
      "agent_b": "<agent name>",
      "view_b": "<agent B's view>",
      "resolution": "<which agent has stronger evidence, and why — or 'unresolved'>",
      "committee_implication": "<what does this disagreement mean for the investment committee's decision?>"
    }}
  ],
  "strongest_evidence_domains": ["<domains where evidence is most solid>"],
  "weakest_evidence_domains": ["<domains where evidence is thin or unclear>"],
  "unresolved_tensions": ["<specific questions that remain open after synthesis>"],
  "consensus_confidence": "<low | moderate | high — how confident is the overall analytical team?>",
  "bias_assessment": "<2-3 sentences: Are analysts showing groupthink? Is there anchoring to recent news or the dominant narrative? Is any analyst likely being contrarian for its own sake? Call out any bias you detect honestly.>"
}}

RULES:
- Do not force consensus where genuine disagreements exist
- A disagreement unresolved is a key uncertainty — flag it clearly
- Evaluate evidence strength objectively — the loudest analyst is not always right
- Horizon conflicts are valid: something can be bearish short-term and bullish long-term"""

    raw = call_llm(
        client=client,
        model=config.models.committee,
        system=_SYSTEM,
        prompt=prompt,
        max_tokens=4096,
        expect_json=True,
    )
    data = parse_json_response(raw)

    agreements: List[Agreement] = [
        Agreement(
            topic=a.get("topic", ""),
            agents_involved=a.get("agents_involved", []),
            shared_view=a.get("shared_view", ""),
            strength=a.get("strength", "moderate"),
        )
        for a in data.get("agreements", [])
    ]

    disagreements: List[Disagreement] = []
    for d in data.get("disagreements", []):
        ct = d.get("conflict_type", "interpretive")
        if ct not in VALID_DISAGREEMENT_TYPES:
            ct = "interpretive"
        disagreements.append(Disagreement(
            topic=d.get("topic", ""),
            conflict_type=ct,
            agent_a=d.get("agent_a", ""),
            view_a=d.get("view_a", ""),
            agent_b=d.get("agent_b", ""),
            view_b=d.get("view_b", ""),
            resolution=d.get("resolution", "unresolved"),
            committee_implication=d.get("committee_implication", ""),
        ))

    return SynthesisResult(
        overall_lean=data.get("overall_lean", "neutral"),
        agreement_summary=data.get("agreement_summary", ""),
        agreements=agreements,
        disagreements=disagreements,
        strongest_evidence_domains=data.get("strongest_evidence_domains", []),
        weakest_evidence_domains=data.get("weakest_evidence_domains", []),
        unresolved_tensions=data.get("unresolved_tensions", []),
        consensus_confidence=data.get("consensus_confidence", "low"),
        bias_assessment=data.get("bias_assessment", ""),
    )
