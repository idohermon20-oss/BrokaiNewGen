"""
Stage 4: Agent Reasoning

Each agent is given its brief, the stock data, and the analyst context.
Agents produce structured analysis — NOT raw data summaries.
Each agent must take a stance, support it with evidence, and flag uncertainties.
"""
from typing import List
import openai

from ..config import Config
from ..agents.base_agent import AgentBrief, AgentOutput, EvidenceItem
from ..orchestrator.profiler import StockProfile
from ..orchestrator.relevance_mapper import RelevanceMap
from ..data.fetcher import StockData, format_stock_data_for_llm
from ..utils.llm import call_llm, parse_json_response

VALID_STANCES = {"bullish", "bearish", "neutral", "mixed"}
VALID_CONFIDENCE = {"low", "moderate", "high"}
VALID_RELEVANCE = {"high", "medium", "low"}
VALID_DIRECTION = {"bullish", "bearish", "neutral"}


_SYSTEM = """You are a specialized investment analyst. You have been assigned to analyze
one specific aspect of a stock for an investment committee.

Your job is to:
1. Analyze ONLY your assigned domain — do not stray into other analysts' territory
2. Produce reasoning, not just data summaries
3. Take a clear stance — do not be wishy-washy
4. Clearly separate facts from your interpretations
5. Explicitly state what you don't know
6. Flag anything the investment committee must pay attention to

You are writing for professional investors. Be direct, specific, and honest.
Return only valid JSON. No prose outside the JSON object."""


def _format_article_impacts_for_trend(article_impacts: list) -> str:
    """Format article impacts as a compact block for the Trend analyst prompt."""
    if not article_impacts:
        return ""
    lines = ["\n--- ASSESSED ARTICLE IMPACTS ---"]
    for a in article_impacts:
        badge = a.impact.upper()
        url_ref = f" | {a.url}" if a.url else ""
        lines.append(f"  [{badge}] {a.title} ({a.source}){url_ref}")
        if a.impact_summary:
            lines.append(f"    → {a.impact_summary}")
    return "\n".join(lines)


def _format_maya_reports_for_trend(maya_reports: list) -> str:
    """Format Maya/TASE filings as a compact block for the Trend analyst prompt."""
    if not maya_reports:
        return ""
    lines = ["\n--- MAYA / TASE REGULATORY FILINGS ---"]
    for r in maya_reports:
        badge = r.impact.upper()
        link_ref = f" | {r.link}" if r.link else ""
        lines.append(f"  [{badge}] {r.title} ({r.report_type}){link_ref}")
        if r.impact_reason:
            lines.append(f"    → {r.impact_reason}")
    return "\n".join(lines)


def run_agent(
    brief: AgentBrief,
    stock_data: StockData,
    profile: StockProfile,
    relevance_map: RelevanceMap,
    client: openai.OpenAI,
    config: Config,
    article_impacts: list = None,
    maya_reports: list = None,
) -> AgentOutput:
    """
    Run a single expert agent and return its structured output.
    """
    stock_text = format_stock_data_for_llm(stock_data, config.currency_symbol)

    # Inject article impacts + Maya filings for the Trend analyst specifically
    is_trend_agent = brief.domain in ("trend_sentiment", "trend", "sentiment", "news_sentiment")
    trend_extra = ""
    if is_trend_agent:
        trend_extra = (
            _format_article_impacts_for_trend(article_impacts or [])
            + _format_maya_reports_for_trend(maya_reports or [])
        )

    key_questions_text = "\n".join(
        f"  {i+1}. {q}" for i, q in enumerate(relevance_map.key_questions)
    )

    prompt = f"""{config.market_context}
You are: {brief.name}
Your domain: {brief.domain}

OVERALL ANALYSIS CONTEXT:
- Stock: {profile.ticker} ({profile.company_name})
- Phase: {profile.phase}
- Time Horizon: {profile.time_horizon.upper()}
- Current situation: {profile.current_situation}
- What market is focused on: {profile.what_market_is_focused_on}

THE INVESTMENT COMMITTEE'S KEY QUESTIONS:
{key_questions_text}

YOUR SPECIFIC ASSIGNMENT:
Scope: {brief.scope}
Your key question to answer: {brief.key_question}
Out of scope for you (do NOT cover this): {brief.out_of_scope}

AVAILABLE DATA:
{stock_text}{trend_extra}

Analyze {profile.ticker} through your specific lens. Focus only on your domain.

Return a JSON object with exactly these fields:
{{
  "key_finding": "<One paragraph: your most important analytical finding — take a clear position>",
  "stance": "<bullish | bearish | neutral | mixed>",
  "confidence": "<low | moderate | high>",
  "evidence": [
    {{
      "fact": "<a specific, sourced observation from the data>",
      "source": "<where this came from: e.g. 'income statement', 'news headline', 'price data'>",
      "relevance": "<high | medium | low>",
      "reliability": "<high | medium | low>",
      "direction": "<bullish | bearish | neutral>",
      "interpretation": "<what does this mean for your domain thesis?>"
    }}
  ],
  "key_unknowns": [
    "<specific things you need to know but cannot determine from available data>"
  ],
  "flags_for_committee": [
    "<important observations, conflicts, or surprises the investment committee must weigh>"
  ],
  "full_reasoning": "<full analytical narrative — 2-4 paragraphs. Walk through your reasoning step by step. Be specific to {profile.ticker}. Do not summarize the company — analyze it.>"
}}

RULES:
- Evidence items must reference actual data from the dataset, not invented facts
- Stance must reflect your overall view for the assigned time horizon
- Do not hedge everything — take a position while acknowledging uncertainty
- If you genuinely cannot form a view, state why explicitly in key_unknowns
- full_reasoning should read like an analyst memo section, not a chatbot answer"""

    raw = call_llm(
        client=client,
        model=config.models.agent,
        system=_SYSTEM,
        prompt=prompt,
        max_tokens=8192,
        expect_json=True,
    )
    data = parse_json_response(raw)

    # Parse evidence items
    evidence: List[EvidenceItem] = []
    for e in data.get("evidence", []):
        relevance = e.get("relevance", "medium")
        if relevance not in VALID_RELEVANCE:
            relevance = "medium"
        reliability = e.get("reliability", "medium")
        if reliability not in VALID_RELEVANCE:
            reliability = "medium"
        direction = e.get("direction", "neutral")
        if direction not in VALID_DIRECTION:
            direction = "neutral"
        evidence.append(EvidenceItem(
            fact=e.get("fact", ""),
            source=e.get("source", ""),
            relevance=relevance,
            reliability=reliability,
            direction=direction,
            interpretation=e.get("interpretation", ""),
        ))

    stance = data.get("stance", "neutral")
    if stance not in VALID_STANCES:
        stance = "neutral"

    confidence = data.get("confidence", "low")
    if confidence not in VALID_CONFIDENCE:
        confidence = "low"

    return AgentOutput(
        agent_name=brief.name,
        domain=brief.domain,
        key_finding=data.get("key_finding", ""),
        stance=stance,
        confidence=confidence,
        evidence=evidence,
        key_unknowns=data.get("key_unknowns", []),
        flags_for_committee=data.get("flags_for_committee", []),
        full_reasoning=data.get("full_reasoning", ""),
    )


def run_all_agents(
    briefs: List[AgentBrief],
    stock_data: StockData,
    profile: StockProfile,
    relevance_map: RelevanceMap,
    client: openai.OpenAI,
    config: Config,
    verbose: bool = False,
    article_impacts: list = None,
    maya_reports: list = None,
) -> List[AgentOutput]:
    """Run all agents sequentially and return their outputs."""
    outputs: List[AgentOutput] = []
    for brief in briefs:
        if verbose:
            print(f"  Running agent: {brief.name}...")
        output = run_agent(
            brief, stock_data, profile, relevance_map, client, config,
            article_impacts=article_impacts,
            maya_reports=maya_reports,
        )
        if verbose:
            print(f"    Stance: {output.stance} | Confidence: {output.confidence}")
        outputs.append(output)
    return outputs
