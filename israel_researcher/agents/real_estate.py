"""
RealEstateAgent — covers Israeli real estate (14 tickers).

Domain expertise:
  - AZRG/AMOT: premium commercial REITs, trade near NAV
  - DIMRI/SKBN/SPEN: residential construction & development
  - BOI rate cuts = direct P/E expansion (all RE stocks re-rate)
  - Stocks near 52w lows + low RSI = BOI pivot anticipation play
  - High dividend yield attracts institutional buyers when rates fall
"""

from __future__ import annotations

from ..config import SECTOR_TICKERS
from ..models import Signal
from .base import SectorAgent


class RealEstateAgent(SectorAgent):
    sector_name = "RealEstate"
    tickers     = SECTOR_TICKERS["RealEstate"]  # 14 tickers

    @property
    def _sector_domain(self) -> str:
        return (
            "SECTOR: Israeli Real Estate — commercial REITs, residential construction.\n\n"
            "KEY FACTORS:\n"
            "- BOI (Bank of Israel) interest rate policy: rate cuts = direct P/E expansion "
            "for all RE stocks (lower cap rates = higher NAV). Even BOI pause hints cause a rally.\n"
            "- AZRG (Azrieli Group): Israel's largest commercial REIT; premium office + retail. "
            "Trades at slight NAV premium. Defensive large-cap.\n"
            "- AMOT, BIG, MLSR, ALHE, GVYM, ARPT, GCT: income-generating commercial RE. "
            "Occupancy rates and rental yield are key. Dividend yield 4-8% = institutional buyers.\n"
            "- DIMRI, SKBN, SPEN, MVNE: residential construction and development. "
            "Follow Israeli housing permit data, mortgage volumes, and population growth.\n"
            "- Shekel strengthening: positive (lower import costs for construction, "
            "lower foreign-currency debt service for leveraged RE companies).\n"
            "- US REIT index (VNQ) sentiment = global RE capital flow leading indicator.\n"
            "- P/B < 0.8 + bouncing from 52w low = deep NAV discount setup (high asymmetry).\n\n"
            "SCORING ADJUSTMENTS:\n"
            "+ BOI rate cut news in global headlines: apply +12 to all RE tickers\n"
            "+ VNQ (US REIT index) up >2%: apply +6\n"
            "+ Shekel strengthened >1.5%: apply +5 (lower foreign debt service)\n"
            "+ low_reversal or oversold_bounce + earnings_calendar: very strong setup +10\n"
            "+ maya_buyback or maya_dividend: management confidence +8\n"
            "- Geopolitical escalation in headlines: -8 (construction delays, tenant risk)\n"
            "- Rising rates hint in BOI statement: -10 (highest negative impact sector)"
        )

    def get_sector_signals(self) -> list[Signal]:
        signals: list[Signal] = []

        # VNQ: US REIT index — global real estate capital flow sentiment
        signals.extend(self._peer_move_signal(
            peer_ticker    = "VNQ",
            peer_label     = "US REIT Index (VNQ)",
            threshold_pct  = 2.0,
            target_tickers = ["AZRG.TA", "AMOT.TA", "BIG.TA", "MLSR.TA", "ALHE.TA"],
            signal_type    = "sector_peer_move",
            direction_text = "Israeli commercial REIT sector sympathy",
        ))

        # Shekel strengthening: beneficial for leveraged RE companies
        # Note: _peer_move_signal checks abs(pct) so both directions fire;
        # we want only shekel strengthening (USD/ILS falling = negative pct).
        # The signal headline describes the direction so the LLM interprets correctly.
        signals.extend(self._peer_move_signal(
            peer_ticker    = "ILS=X",
            peer_label     = "USD/ILS move",
            threshold_pct  = 1.5,
            target_tickers = self.tickers,
            signal_type    = "shekel_move",
            direction_text = "Israeli RE foreign debt service / import cost impact",
        ))

        # IYR: alternative US real estate ETF for broader sentiment check
        signals.extend(self._peer_move_signal(
            peer_ticker    = "IYR",
            peer_label     = "US Real Estate ETF (IYR)",
            threshold_pct  = 2.5,
            target_tickers = ["AZRG.TA", "GCT.TA", "SKBN.TA", "MVNE.TA"],
            signal_type    = "sector_peer_move",
            direction_text = "Global real estate sentiment shift",
        ))

        return signals
