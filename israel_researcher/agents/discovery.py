"""
DiscoveryAgent — scans the full TASE universe beyond the 62 hardcoded tickers.

Every run:
  1. DynamicUniverseBuilder validates Maya-registered companies against Yahoo Finance
     (cached; at most 25 new checks per cycle to avoid rate-limiting)
  2. Runs MarketAnomalyDetector on all valid uncovered tickers
  3. Filters to tickers with signal activity this week (discovery-first)
  4. Calls sector LLM with a "general Israeli mid/small-cap" domain prompt

This catches:
  - Newly listed companies (IPOs processed by Maya but not yet in any sector list)
  - Smaller TA-125 and TA-SME constituents not covered by the 6 specialist agents
  - Any stock that appears in Maya filings this week (filing = priority validation)
"""

from __future__ import annotations

import random

from ..config import ANOMALY_SAMPLE_SIZE, SECTOR_TICKERS
from ..models import Signal
from ..sources.market import DynamicUniverseBuilder, MarketAnomalyDetector
from .base import SectorAgent


_IPO_SIGNAL_TYPES = {"maya_ipo", "maya_spinoff"}


class DiscoveryAgent(SectorAgent):
    """
    Covers the full TASE universe not handled by specialist sector agents.
    Universe is built dynamically from the Maya company cache each cycle.
    """

    sector_name = "Discovery"

    def __init__(
        self,
        openai_key: str,
        state:      dict,
        companies:  list[dict],
        priority_symbols: set[str] | None = None,
    ):
        super().__init__(openai_key, state)
        self._priority_symbols: set[str] = set(priority_symbols or set())

        # All tickers already handled by the 6 specialist agents
        covered: set[str] = set()
        for tickers in SECTOR_TICKERS.values():
            covered.update(tickers)

        builder     = DynamicUniverseBuilder(state)
        self.tickers = builder.get_uncovered_tickers(
            companies        = companies,
            covered_set      = covered,
            priority_symbols = priority_symbols,
        )

    def _run_technicals(self) -> list[Signal]:
        """
        Rotation-based technical scan for the full TASE universe.

        Scanning 400-800 tickers every 15 minutes would take 3-5 minutes per cycle
        and hammer Yahoo Finance with rate-limit risk.  Instead we scan:
          - ALL priority tickers (from Maya filings this cycle — always fresh)
          - A random sample of the remaining tickers up to ANOMALY_SAMPLE_SIZE

        Over ~5-6 cycles (75-90 minutes) the full universe rotates through completely.
        Priority tickers are always re-checked every cycle regardless of the sample.
        """
        if not self.tickers:
            return []

        # Normalise priority symbols to .TA format
        priority_set: set[str] = set()
        for s in self._priority_symbols:
            priority_set.add(s if s.endswith(".TA") else f"{s}.TA")
        # Also keep tickers that appeared in pre-fetched cross-sector signals this cycle
        priority_set = {t for t in priority_set if t in set(self.tickers)}

        non_priority = [t for t in self.tickers if t not in priority_set]
        sample_size  = max(0, ANOMALY_SAMPLE_SIZE - len(priority_set))
        sampled      = random.sample(non_priority, min(sample_size, len(non_priority)))
        scan_list    = list(priority_set) + sampled

        print(
            f"[Discovery] Technical scan: {len(priority_set)} priority + "
            f"{len(sampled)} sampled = {len(scan_list)} / {len(self.tickers)} total tickers"
        )
        detector = MarketAnomalyDetector(scan_list)
        return detector.scan_universe(
            sample_size      = len(scan_list),
            priority_tickers = list(priority_set),
        )

    def _filter_signals(self, signals: list[Signal]) -> list[Signal]:
        """
        Extend base filter to also pass through IPO/spinoff signals.
        These have TASE{id} pseudo-tickers (no real Yahoo Finance symbol yet)
        but company_name is populated — web news search uses it as the query,
        and the LLM can score the company on its IPO catalyst alone.
        """
        regular  = super()._filter_signals(signals)
        ipo_sigs = [s for s in signals if s.signal_type in _IPO_SIGNAL_TYPES]
        # Dedupe: if an IPO ticker somehow already appeared in regular, don't double-add
        regular_keys = {(s.ticker, s.signal_type) for s in regular}
        new_ipo = [s for s in ipo_sigs if (s.ticker, s.signal_type) not in regular_keys]
        if new_ipo:
            print(f"[Discovery] +{len(new_ipo)} IPO/spinoff signals added directly (no YF ticker yet).")
        return regular + new_ipo

    # get_sector_signals() intentionally not overridden:
    # Without knowing the sector of each ticker we can't fire targeted
    # macro signals (oil/VIX/shekel).  Technical signals from
    # MarketAnomalyDetector are the primary discovery mechanism here.

    @property
    def _sector_domain(self) -> str:
        return (
            "General Israeli mid-cap and small-cap stocks not covered by major sector agents. "
            "These companies span all sectors — technology, construction, retail, services, "
            "biotech, industrials — and typically have less analyst coverage than TA-35 names. "
            "\n\n"
            "Evaluation framework:\n"
            "- A volume spike on a less-covered stock is MORE actionable than on a TA-35 member "
            "  because institutional discovery is still early.\n"
            "- Maya filing + volume spike = highest conviction combination for mid/small-cap.\n"
            "- Breakout from multi-month consolidation range = technical catalyst regardless of sector.\n"
            "- Institutional buyer entry (13G/13D equivalent on TASE) = strong conviction signal.\n"
            "- New contract or partnership announcement = fundamental catalyst; deal size relative to "
            "  market cap is the key metric (small company, large deal = game changer).\n"
            "- IPO/new listing within past 6 months: high volatility, watch for post-IPO consolidation "
            "  breakout (typical 3-month base then institutional accumulation).\n"
            "- Stocks with ticker starting 'TASE' are brand-new IPOs not yet trading on Yahoo Finance. "
            "  Score them purely on their IPO filing catalyst and any web news found. "
            "  Use the company name (from the 'company' field) as their identifier in your output — "
            "  set ticker to the TASE id as given, name to the company name.\n"
            "\n"
            "Rank by signal quality and catalyst strength. Prefer stocks where multiple independent "
            "signal types converge this week. Do not penalize for small market cap — discovery is the goal."
        )
