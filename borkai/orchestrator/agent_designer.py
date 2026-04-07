"""
Stage 3: Dynamic Agent Team Design

Designs the exact set of expert agents needed for this specific stock.
This is NOT a lookup — agents are designed fresh based on the relevance map.
Each agent gets a precise brief: domain, scope, key question, and explicit boundaries.
"""
from typing import List
import openai

from ..config import Config
from ..orchestrator.profiler import StockProfile
from ..orchestrator.relevance_mapper import RelevanceMap
from ..agents.base_agent import AgentBrief
from ..utils.llm import call_llm, parse_json_response


_SYSTEM = """You are the research director at a top-tier investment fund.
You are designing the expert analyst team for a specific investment research assignment.

Each analyst (agent) you create must:
- Have a precisely scoped domain with no overlap with other analysts
- Have a single clear question to answer
- Understand what is out of scope for their analysis

The team must be lean and purposeful. No agent is created just for completeness.
Every agent must directly contribute to answering the key investment questions.

Return only valid JSON. No prose outside the JSON object."""

# Sector-specific intelligence injected into the agent design prompt.
# Derived from sector agent domain knowledge (banks, tech/defense, energy, etc.)
_SECTOR_INTELLIGENCE = {
    "Financial Services": (
        "KEY SECTOR DRIVERS FOR FINANCIAL SERVICES / BANKING / INSURANCE:\n"
        "- Bank of Israel (BOI) rate policy: rising rates expand net interest margins (bullish banks); "
        "rate cuts expand P/E multiples for REITs and compress bank profitability.\n"
        "- Insurance investment portfolio: higher bond yields boost insurance investment income.\n"
        "- Credit quality: NPL trends and provisioning are the primary risk signal.\n"
        "- US bank sentiment (KBE ETF): >2.5% move in KBE creates sympathy for Israeli banks.\n"
        "- VIX >25: Banks become defensive plays; reduce equity risk exposure.\n"
        "- Dividend yield and buyback capacity are primary shareholder return drivers.\n"
        "ANALYST PRIORITY: Design analysts focused on NIM trajectory, BOI policy sensitivity, "
        "credit quality, and dividend sustainability."
    ),
    "Technology": (
        "KEY SECTOR DRIVERS FOR ISRAELI TECHNOLOGY:\n"
        "- USD/ILS exchange rate: Israeli tech companies report in ILS but earn USD revenue. "
        "Shekel weakening vs USD is a direct earnings tailwind for exporters.\n"
        "- US tech sector sentiment (NASDAQ, S&P 500): Israeli tech trades with high correlation.\n"
        "- Dual-listed stocks: US ADR premium/discount and cross-market arbitrage flows matter.\n"
        "- Defense tech: Companies with defense contracts benefit from escalation (VIX >22).\n"
        "- R&D spending and IP pipeline are primary long-term value drivers.\n"
        "- Semiconductor equipment peers (AMAT, KLAC, LRCX): moves >3% signal sector rotation.\n"
        "ANALYST PRIORITY: Design analysts focused on revenue exposure (domestic vs export), "
        "USD earnings translation, competitive moat, and defense contract mix if applicable."
    ),
    "Industrials": (
        "KEY SECTOR DRIVERS FOR ISRAELI INDUSTRIALS / DEFENSE:\n"
        "- Defense spending: Government budget allocation, escalation signals.\n"
        "- US defense peer moves (LMT, RTX, NOC): >2% move signals sector re-rating.\n"
        "- Contract announcements are primary catalysts — size and duration matter most.\n"
        "- Export orientation: USD/ILS moves directly translate to margin changes.\n"
        "- VIX >22: Structural demand tailwind for defense-exposed companies.\n"
        "ANALYST PRIORITY: Design analysts focused on order backlog, contract pipeline, "
        "government budget sensitivity, and export revenue mix."
    ),
    "Energy": (
        "KEY SECTOR DRIVERS FOR ISRAELI ENERGY:\n"
        "- Natural gas (NG=F futures): Leviathan/Tamar field operators are directly correlated.\n"
        "- Brent crude (BZ=F) and crack spreads: Primary driver for refinery/retail plays.\n"
        "- EU carbon pricing and PPAs: Critical for renewable energy companies.\n"
        "- Geopolitical risk: Mediterranean supply routes and regional tensions affect pricing.\n"
        "- Regulatory approval for export infrastructure is a long-term catalyst.\n"
        "ANALYST PRIORITY: Design analysts for commodity price exposure, infrastructure "
        "development timeline, and regulatory approval risk."
    ),
    "Real Estate": (
        "KEY SECTOR DRIVERS FOR ISRAELI REAL ESTATE:\n"
        "- BOI rate policy: Rate cuts → P/E multiple expansion; rate hikes → compression.\n"
        "- NAV premium/discount: REITs trading at discount to NAV = value signal.\n"
        "- USD/ILS: Foreign currency debt exposure affects servicing costs.\n"
        "- US REIT ETF sentiment (VNQ, IYR) for global risk appetite.\n"
        "- Government housing policy directly affects residential developers.\n"
        "ANALYST PRIORITY: Design analysts for NAV discount, BOI rate sensitivity, "
        "occupancy rates, and debt maturity profile."
    ),
    "Communication Services": (
        "KEY SECTOR DRIVERS FOR ISRAELI TELECOM:\n"
        "- Dividend yield (5-8%) is the primary investment thesis — sustainability is critical.\n"
        "- Competition and pricing pressure from new entrants compress margins.\n"
        "- Regulatory environment (ISA, Ministry of Communications) sets pricing floors.\n"
        "- Infrastructure sharing agreements affect cost structure.\n"
        "ANALYST PRIORITY: Design analysts for dividend coverage ratio, competitive dynamics, "
        "and regulatory environment."
    ),
    "Consumer Staples": (
        "KEY SECTOR DRIVERS FOR ISRAELI CONSUMER / RETAIL:\n"
        "- ILS/USD exchange rate affects import costs for retailers.\n"
        "- Domestic consumer confidence and wage growth drive volume.\n"
        "- US consumer staples sentiment (XLP ETF) as global risk proxy.\n"
        "- Food and drug retail: highly defensive, government price controls apply.\n"
        "ANALYST PRIORITY: Design analysts for same-store sales growth, import cost inflation, "
        "and market share dynamics."
    ),
    "Healthcare": (
        "KEY SECTOR DRIVERS FOR PHARMA / BIOTECH:\n"
        "- US biotech sentiment (XBI, IBB ETFs): Israeli pharma/biotech trades with high correlation.\n"
        "- FDA/EMA/PMDA regulatory approvals: Binary catalysts (+/- 15-20% moves).\n"
        "- Licensing deals and partnership announcements: Primary value creation events.\n"
        "- USD/ILS: Most Israeli pharma companies report in USD.\n"
        "- Clinical trial readouts: Timing and probability of success are key unknowns.\n"
        "ANALYST PRIORITY: Design analysts for pipeline valuation, regulatory risk, "
        "and commercial execution."
    ),
}


def design_agent_team(
    profile: StockProfile,
    relevance_map: RelevanceMap,
    client: openai.OpenAI,
    config: Config,
) -> List[AgentBrief]:
    """
    Design the expert agent team for this specific analysis.
    Returns a list of AgentBrief objects, one per agent.
    """
    core_domains_text = "\n".join(
        f"  - {d.domain}: {d.reason}"
        for d in relevance_map.domains
        if d.importance == "core"
    )
    supporting_domains_text = "\n".join(
        f"  - {d.domain}: {d.reason}"
        for d in relevance_map.domains
        if d.importance == "supporting"
    )
    key_questions_text = "\n".join(
        f"  {i+1}. {q}"
        for i, q in enumerate(relevance_map.key_questions)
    )

    # Inject sector-specific intelligence if we recognise the sector
    sector_hint = _SECTOR_INTELLIGENCE.get(profile.sector, "")
    sector_block = f"\nSECTOR INTELLIGENCE — {profile.sector}:\n{sector_hint}\n" if sector_hint else ""

    prompt = f"""{config.market_context}
Design the expert analyst team for {profile.ticker} ({profile.company_name}).

STOCK PROFILE:
- Sector: {profile.sector}
- Phase: {profile.phase}
- Current situation: {profile.current_situation}
- What market is focused on: {profile.what_market_is_focused_on}
- Time horizon: {profile.time_horizon.upper()}
{sector_block}
KEY QUESTIONS THIS ANALYSIS MUST ANSWER:
{key_questions_text}

CORE ANALYTICAL DOMAINS (must be covered):
{core_domains_text}

SUPPORTING DOMAINS (each must get a dedicated analyst — these are material context):
{supporting_domains_text}

Design a team of {config.min_agents}–{config.max_agents} expert analysts.

RULES:
- Each analyst covers a non-overlapping domain
- No two analysts should analyze the same thing
- Every CORE domain must have its own dedicated analyst
- Every SUPPORTING domain must also have its own dedicated analyst
- Each analyst has ONE clear key question to answer
- Scope must be specific enough that the analyst knows exactly what to gather
- "out_of_scope" must explicitly prevent overlap with other analysts
- You may name agents creatively if the situation calls for it (e.g., "Regulatory Risk Analyst" for a pharma stock)
- Do NOT create agents for excluded or peripheral domains unless there is a very strong reason

Return a JSON object with this structure:
{{
  "rationale": "<1-2 sentences on why you chose this team structure>",
  "agents": [
    {{
      "name": "<Descriptive analyst name, e.g. 'Competitive Position Analyst'>",
      "domain": "<short domain identifier, e.g. 'competitive_position'>",
      "scope": "<2-3 sentences: what exactly this analyst covers for {profile.ticker}>",
      "key_question": "<The single most important question this analyst must answer>",
      "out_of_scope": "<What this analyst must NOT cover — prevents overlap>"
    }}
  ]
}}"""

    raw = call_llm(
        client=client,
        model=config.models.orchestrator,
        system=_SYSTEM,
        prompt=prompt,
        max_tokens=3000,
        expect_json=True,
    )
    data = parse_json_response(raw)

    agents: List[AgentBrief] = []
    for a in data.get("agents", []):
        agents.append(AgentBrief(
            name=a.get("name", "Analyst"),
            domain=a.get("domain", "unknown"),
            scope=a.get("scope", ""),
            key_question=a.get("key_question", ""),
            out_of_scope=a.get("out_of_scope", ""),
        ))

    # Enforce agent count bounds
    agents = agents[:config.max_agents]
    if len(agents) < config.min_agents:
        raise ValueError(
            f"Agent designer returned only {len(agents)} agents "
            f"(minimum is {config.min_agents})."
        )

    # Always inject a Trend & Sentiment Analyst (unless the LLM already included one)
    has_trend = any(a.domain in ("trend_sentiment", "trend", "sentiment", "news_sentiment") for a in agents)
    if not has_trend:
        agents.append(AgentBrief(
            name="Trend & Sentiment Analyst",
            domain="trend_sentiment",
            scope=(
                f"Analyze the most recent news articles, analyst commentary, and regulatory "
                f"filings about {profile.company_name} ({profile.ticker}). Identify the current "
                f"market narrative, whether momentum in public coverage is positive or negative, "
                f"and whether external sentiment supports or contradicts the fundamental picture."
            ),
            key_question=(
                "What do the latest articles, news flow, and regulatory disclosures say about "
                "the near-term direction of this stock? Are external catalysts — or risks — "
                "building that the fundamental analysts may be underweighting?"
            ),
            out_of_scope=(
                "Do not re-analyze financial metrics, valuation multiples, or technical chart "
                "patterns — other analysts cover those. Focus exclusively on the narrative in "
                "recent news and filings and what it signals about market sentiment."
            ),
        ))

    return agents
