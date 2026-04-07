"""
Stage 1: Stock Profiling

Produces a sharp, analyst-grade reading of the company's current situation.
This is NOT a company description — it is an analyst's interpretation of
what kind of stock this is and what matters right now.
"""
from dataclasses import dataclass
from typing import List
import openai

from ..config import Config
from ..data.fetcher import StockData, format_stock_data_for_llm
from ..utils.llm import call_llm, parse_json_response


VALID_HORIZONS = {"short", "medium", "long"}
HORIZON_DESCRIPTIONS = {
    "short": "1–4 weeks",
    "medium": "1–6 months",
    "long": "1–3 years",
}

VALID_PHASES = {
    "growth", "mature", "turnaround", "distressed",
    "pre-revenue", "cyclical", "special-situation", "other"
}


@dataclass
class StockProfile:
    ticker: str
    company_name: str
    sector: str
    time_horizon: str
    phase: str
    sector_dynamics: str
    current_situation: str
    what_market_is_focused_on: str
    key_characteristics: List[str]
    horizon_implications: str


_SYSTEM = """You are a senior equity research analyst with 20 years of experience at a top-tier
investment firm. Your job is to produce a sharp, opinionated analyst reading of a stock's
current situation — not a company description, but a professional's view of what matters now.

Be specific. Be direct. Have a point of view. Do not write generic observations.
Return only valid JSON, no prose outside the JSON object."""


def build_stock_profile(
    ticker: str,
    time_horizon: str,
    stock_data: StockData,
    client: openai.OpenAI,
    config: Config,
) -> StockProfile:
    """
    Produce a structured analyst profile of the stock.
    This is the foundation all subsequent reasoning builds on.
    """
    if time_horizon not in VALID_HORIZONS:
        raise ValueError(f"time_horizon must be one of {VALID_HORIZONS}")

    horizon_desc = HORIZON_DESCRIPTIONS[time_horizon]
    stock_text = format_stock_data_for_llm(stock_data, config.currency_symbol)

    prompt = f"""{config.market_context}
Analyze {ticker} for a {time_horizon.upper()} time horizon ({horizon_desc}).

{stock_text}

Produce a professional analyst profile. Return a JSON object with exactly these fields:

{{
  "phase": "<one of: growth | mature | turnaround | distressed | pre-revenue | cyclical | special-situation | other>",
  "sector_dynamics": "<2-3 sentences on what is happening in this sector RIGHT NOW — be specific, not generic>",
  "current_situation": "<2-3 sentences on THIS company's specific situation at this moment — what is the key dynamic?>",
  "what_market_is_focused_on": "<What are investors and analysts currently watching or debating for this specific stock? Be concrete.>",
  "key_characteristics": [
    "<3-5 specific characteristics that make this stock unique or complex to analyze — not generic sector traits>"
  ],
  "horizon_implications": "<For a {time_horizon} horizon ({horizon_desc}), what changes about the analytical focus? What becomes more or less relevant?>"
}}

Do not pad with generic observations. Every sentence must be specific to {ticker}."""

    raw = call_llm(
        client=client,
        model=config.models.orchestrator,
        system=_SYSTEM,
        prompt=prompt,
        max_tokens=2048,
        expect_json=True,
    )
    data = parse_json_response(raw)

    phase = data.get("phase", "other")
    if phase not in VALID_PHASES:
        phase = "other"

    return StockProfile(
        ticker=ticker.upper(),
        company_name=stock_data.company_name,
        sector=stock_data.sector,
        time_horizon=time_horizon,
        phase=phase,
        sector_dynamics=data["sector_dynamics"],
        current_situation=data["current_situation"],
        what_market_is_focused_on=data["what_market_is_focused_on"],
        key_characteristics=data.get("key_characteristics", []),
        horizon_implications=data["horizon_implications"],
    )
