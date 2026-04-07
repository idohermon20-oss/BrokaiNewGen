"""
Sector News Analyzer.

Takes recently fetched news items for a sector and produces structured
intelligence: hot topics, risks, opportunities, and sentiment.
This is a lightweight enrichment layer — it does not affect agent reasoning,
only adds a dedicated section to the final report.
"""
from dataclasses import dataclass, field
from typing import List
import openai

from ..config import Config
from ..data.sector_news import SectorNewsItem, format_sector_news_for_llm
from ..utils.llm import call_llm, parse_json_response


@dataclass
class SectorAnalysis:
    sector: str
    company_name: str
    news_count: int
    hot_topics: List[str] = field(default_factory=list)
    key_risks: List[str] = field(default_factory=list)
    key_opportunities: List[str] = field(default_factory=list)
    market_sentiment: str = "neutral"       # bullish | bearish | mixed | neutral
    sentiment_rationale: str = ""
    relevance_to_stock: str = ""
    analysis_skipped: bool = False
    skip_reason: str = ""


_SYSTEM = """You are a financial news analyst specializing in the Israeli and global stock markets.
You receive recent news headlines for a specific sector and company.
Extract structured investment intelligence. Be specific and concise.
Return only valid JSON. No prose outside the JSON."""


def analyze_sector_news(
    news_items: List[SectorNewsItem],
    company_name: str,
    sector: str,
    ticker: str,
    time_horizon: str,
    market_context: str,
    client: openai.OpenAI,
    config: Config,
) -> SectorAnalysis:
    """
    Analyze sector news and extract structured intelligence for the report.
    Returns SectorAnalysis with analysis_skipped=True if no news available.
    """
    if not news_items:
        return SectorAnalysis(
            sector=sector,
            company_name=company_name,
            news_count=0,
            analysis_skipped=True,
            skip_reason="No news items were fetched for this sector.",
        )

    news_text = format_sector_news_for_llm(news_items)

    prompt = f"""{market_context}
You are analyzing news for: {company_name} ({ticker}) | Sector: {sector} | Time Horizon: {time_horizon.upper()}

{news_text}

Based on these news items, extract sector-level intelligence.

Return a JSON object:
{{
  "hot_topics": [
    "<3-5 dominant themes currently driving this sector — be specific to the news above>"
  ],
  "key_risks": [
    "<2-4 sector-level risks surfaced by recent news>"
  ],
  "key_opportunities": [
    "<2-4 sector-level tailwinds or opportunities from recent news>"
  ],
  "market_sentiment": "<bullish | bearish | mixed | neutral — based on the overall news tone>",
  "sentiment_rationale": "<1-2 sentences explaining the sentiment verdict with reference to specific news items>",
  "relevance_to_stock": "<2-3 sentences: how does this sector news landscape specifically affect {company_name}? Be concrete.>"
}}

RULES:
- Hot topics must be grounded in the actual news items provided, not generic observations
- If news is sparse or unrelated, reflect that in a lower-confidence sentiment
- relevance_to_stock must mention {ticker} specifically, not just the sector"""

    raw = call_llm(
        client=client,
        model=config.models.agent,
        system=_SYSTEM,
        prompt=prompt,
        max_tokens=1000,
        expect_json=True,
    )
    data = parse_json_response(raw)

    sentiment = data.get("market_sentiment", "neutral")
    if sentiment not in {"bullish", "bearish", "mixed", "neutral"}:
        sentiment = "neutral"

    return SectorAnalysis(
        sector=sector,
        company_name=company_name,
        news_count=len(news_items),
        hot_topics=data.get("hot_topics", []),
        key_risks=data.get("key_risks", []),
        key_opportunities=data.get("key_opportunities", []),
        market_sentiment=sentiment,
        sentiment_rationale=data.get("sentiment_rationale", ""),
        relevance_to_stock=data.get("relevance_to_stock", ""),
    )
