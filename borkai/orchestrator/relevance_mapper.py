"""
Stage 2: Relevance Mapping

Decides WHICH analytical domains are material for this specific stock
and time horizon — and explicitly excludes irrelevant ones.

This is the most important filtering step. More data is not better.
Relevant data is better.
"""
from dataclasses import dataclass, field
from typing import List, Dict
import openai

from ..config import Config
from ..orchestrator.profiler import StockProfile
from ..utils.llm import call_llm, parse_json_response

VALID_IMPORTANCE = {"core", "supporting", "peripheral", "excluded"}


@dataclass
class DomainRelevance:
    domain: str
    importance: str   # core | supporting | peripheral | excluded
    reason: str       # Why this was included or excluded


@dataclass
class RelevanceMap:
    key_questions: List[str]             # The 3-5 questions the analysis MUST answer
    domains: List[DomainRelevance]       # Classified domains
    explicitly_excluded: List[str]       # Domains ruled out, with reasons

    @property
    def core_domains(self) -> List[str]:
        return [d.domain for d in self.domains if d.importance == "core"]

    @property
    def supporting_domains(self) -> List[str]:
        return [d.domain for d in self.domains if d.importance == "supporting"]


_SYSTEM = """You are the research director at a top-tier investment fund.
Your job is to decide which analytical domains are RELEVANT for a specific stock
at a specific moment — and explicitly exclude irrelevant ones.

You understand that noise kills analysis. Deciding what NOT to study is as important
as deciding what to study. Be decisive. Be specific about why each domain is included or excluded.

Return only valid JSON. No prose outside the JSON object."""


def build_relevance_map(
    profile: StockProfile,
    client: openai.OpenAI,
    config: Config,
) -> RelevanceMap:
    """
    Determine which analytical domains are material for this stock and horizon.
    Returns a structured map of relevant and explicitly excluded domains.
    """
    prompt = f"""{config.market_context}
You are deciding the analytical scope for {profile.ticker} ({profile.company_name}).

STOCK PROFILE:
- Phase: {profile.phase}
- Sector dynamics: {profile.sector_dynamics}
- Current situation: {profile.current_situation}
- What market is focused on: {profile.what_market_is_focused_on}
- Key characteristics: {chr(10).join(f'  • {c}' for c in profile.key_characteristics)}
- Time horizon: {profile.time_horizon.upper()}
- Horizon implications: {profile.horizon_implications}

Your task: Decide which analytical domains are relevant and which are not.

POSSIBLE DOMAINS (not exhaustive — you may add others):
fundamentals, valuation, industry_and_competition, macro_and_geopolitics,
news_and_sentiment, technical_behavior, catalysts_and_events,
regulatory_environment, supply_chain, innovation_and_technology,
management_and_governance, historical_analogs, legal_and_litigation,
capital_structure, customer_concentration, international_exposure

IMPORTANCE LEVELS:
- core: Must be analyzed. Directly drives the investment thesis.
- supporting: Useful context, but not the primary driver.
- peripheral: Acknowledge exists, but do not spend research effort.
- excluded: Explicitly out of scope for this stock/horizon. State why.

Return a JSON object with exactly these fields:
{{
  "key_questions": [
    "<3-5 specific questions this analysis must answer for {profile.ticker} — be concrete, not generic>"
  ],
  "domains": [
    {{
      "domain": "<domain name>",
      "importance": "<core | supporting | peripheral | excluded>",
      "reason": "<specific reason for this classification — reference the stock's situation>"
    }}
  ]
}}

RULES:
- Include ALL domains you consider, even excluded ones (so the reasoning is transparent)
- Every exclusion must have a concrete reason specific to {profile.ticker}
- Do not include domains just to seem thorough — if it doesn't matter for THIS stock, exclude it
- Key questions must be specific to {profile.ticker}, not generic analyst questions"""

    raw = call_llm(
        client=client,
        model=config.models.orchestrator,
        system=_SYSTEM,
        prompt=prompt,
        max_tokens=2048,
        expect_json=True,
    )
    data = parse_json_response(raw)

    domains: List[DomainRelevance] = []
    excluded: List[str] = []

    for d in data.get("domains", []):
        importance = d.get("importance", "peripheral")
        if importance not in VALID_IMPORTANCE:
            importance = "peripheral"
        dr = DomainRelevance(
            domain=d.get("domain", "unknown"),
            importance=importance,
            reason=d.get("reason", ""),
        )
        domains.append(dr)
        if importance == "excluded":
            excluded.append(f"{dr.domain}: {dr.reason}")

    return RelevanceMap(
        key_questions=data.get("key_questions", []),
        domains=domains,
        explicitly_excluded=excluded,
    )
