import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ModelConfig:
    # gpt-4o for deep reasoning stages (profiling, committee, report)
    orchestrator: str = "gpt-4o"
    committee: str = "gpt-4o"
    report: str = "gpt-4o"
    # gpt-4o-mini for agent-level reasoning (faster, cheaper, still strong)
    agent: str = "gpt-4o-mini"


# Market context strings injected into all LLM prompts
MARKET_CONTEXTS = {
    "us": (
        "MARKET: United States — NYSE / NASDAQ\n"
        "Currency: USD ($)\n"
        "Regulator: SEC (Securities and Exchange Commission)\n"
    ),
    "il": (
        "MARKET: Israel — Tel Aviv Stock Exchange (TASE)\n"
        "Currency: ILS (Israeli Shekel, \u20aa)\n"
        "Regulator: ISA (Israel Securities Authority)\n"
        "\n"
        "KEY ISRAELI MARKET CONSIDERATIONS — apply these throughout the analysis:\n"
        "- Geopolitical risk: Regional tensions (Middle East conflict, Gaza, Iran) can cause "
        "sudden market-wide volatility regardless of company fundamentals. This is a persistent "
        "and material risk for ALL Israeli stocks.\n"
        "- Bank of Israel monetary policy: Interest rate decisions directly impact financial "
        "stocks and all valuations. Israeli inflation and rate cycles differ from the Fed.\n"
        "- ILS/USD exchange rate: Currency fluctuations affect export-oriented companies "
        "(most Israeli tech), import costs, and foreign investor returns.\n"
        "- Dual-listed stocks: Many Israeli companies (e.g., TEVA, NICE, Check Point) "
        "trade on both TASE and US exchanges. ADR dynamics, arbitrage, and foreign "
        "institutional flows are relevant.\n"
        "- Sector concentration: TASE is dominated by banks (Hapoalim, Leumi, Mizrahi, "
        "Discount, First International), real estate, insurance, telecom (Bezeq, Partner, "
        "Cellcom), technology, and defense (Elbit Systems, Rafael).\n"
        "- Defense sector: Unique to Israel — defense companies benefit from elevated "
        "government spending during security escalations.\n"
        "- Export orientation: Israel is highly export-driven, especially in tech, pharma, "
        "and defense. Global demand and US/EU policy matter greatly.\n"
        "- Market size: TASE is a smaller exchange — liquidity is lower, and large "
        "institutional flows can move prices significantly.\n"
        "- Reporting currency: Financial statements are in ILS; some multinationals report "
        "in USD. Factor in currency when reading financial metrics.\n"
        "- Trading calendar: TASE is closed Friday afternoon, Saturday (Shabbat), and "
        "Jewish holidays. This affects timing of news reactions.\n"
        "- Reserve army: Military reserve call-ups during escalations can temporarily "
        "affect workforce availability, especially in tech companies.\n"
    ),
}


@dataclass
class Config:
    openai_api_key: str
    models: ModelConfig = field(default_factory=ModelConfig)
    max_agents: int = 10
    min_agents: int = 5
    market: str = "us"                  # "us" or "il"
    market_context: str = ""            # Injected into all prompts
    currency_symbol: str = "$"          # Used in data formatting

    # Article fetching
    article_fetch_enabled: bool = True  # Set False to skip article fetching (faster/cheaper)
    article_max_count: int = 5          # Max articles to fetch per stock
    article_timeout_seconds: int = 8    # HTTP timeout per article fetch

    # Scanner mode — reduced agent count to control cost when scanning many stocks
    scanner_max_agents: int = 7
    scanner_min_agents: int = 4

    # Sector news
    sector_news_enabled: bool = True    # Set False in scanner mode for speed
    sector_news_max_items: int = 12


def load_config(market: str = "us") -> Config:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY is not set.\n"
            "Copy .env.example to .env and add your OpenAI API key."
        )
    if market not in MARKET_CONTEXTS:
        raise ValueError(f"market must be one of: {list(MARKET_CONTEXTS.keys())}")

    return Config(
        openai_api_key=api_key,
        market=market,
        market_context=MARKET_CONTEXTS[market],
        currency_symbol="\u20aa" if market == "il" else "$",
    )
