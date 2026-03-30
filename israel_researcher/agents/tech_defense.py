"""
TechDefenseAgent — covers Israeli tech and defense (11 tickers).

Domain expertise:
  - Defense contracts = multi-year revenue visibility (Elbit, NextVision)
  - Semiconductor equipment (NVMI, TSEM, CAMT) follow global semis cycle
  - Shekel weakness = export revenue boost (most revenue in USD)
  - Dual-listed stocks: US overnight move predicts TASE next-day
  - VIX spike = geopolitical tension = structural tailwind for defense
"""

from __future__ import annotations

from ..config import SECTOR_TICKERS
from ..models import Signal
from .base import SectorAgent


class TechDefenseAgent(SectorAgent):
    sector_name = "TechDefense"
    tickers     = SECTOR_TICKERS["TechDefense"]  # 11 tickers

    # US defense peers — move >2% creates sector tailwind for Israeli defense
    _DEFENSE_PEERS = ["LMT", "RTX", "NOC"]
    # US semiconductor equipment peers — most relevant for CAMT, NVMI, TSEM
    _SEMI_PEERS    = ["AMAT", "KLAC", "LRCX"]
    # Dual-listed subset (US overnight move = direct TASE signal)
    _DUAL_LISTED   = ["ESLT.TA", "NICE.TA", "NVMI.TA", "TSEM.TA",
                      "CAMT.TA", "AUDC.TA", "ALLT.TA"]

    @property
    def _sector_domain(self) -> str:
        return (
            "SECTOR: Israeli Technology and Defense.\n\n"
            "KEY FACTORS:\n"
            "- Defense contracts (ESLT/NXSN): multi-year revenue; IDF/NATO contracts "
            "= highest quality catalyst. VIX >22 = geopolitical tension = "
            "structural demand tailwind for Israeli defense.\n"
            "- Semiconductor equipment (NVMI, TSEM, CAMT): follow global semis cycle. "
            "US peers AMAT/KLAC/LRCX moves >3% = leading indicator for CAMT/NVMI.\n"
            "- Shekel weakness (USD/ILS rising): directly boosts USD-denominated "
            "export revenues when translated back to ILS (applies to ALL 11 tickers).\n"
            "- Dual-listed tickers (ESLT, NICE, NVMI, TSEM, CAMT, AUDC, ALLT): "
            "US session overnight move is a near-certain predictor of TASE next-day direction.\n"
            "- Software/services (NICE, AUDC, ALLT, HLAN): follow SaaS/cloud valuations; "
            "US tech sector sentiment matters.\n"
            "- FORTY (Formula Systems): IT holding company, diversified risk.\n\n"
            "SCORING ADJUSTMENTS:\n"
            "+ Defense contract (maya_contract + government_defense): best possible combo, +15\n"
            "+ US semis peers (KLAC/AMAT) up >3% + CAMT/NVMI technical signal: +10\n"
            "+ Shekel weakened >1.5%: apply to all exporters +6\n"
            "+ Dual-listed US move + technical breakout: EXTREME priority\n"
            "+ VIX >22 + defense ticker: +8 (geopolitical premium)\n"
            "- RSI >75 + no hard catalyst: overbought risk, reduce by 8\n"
            "- Single technical signal only (no fundamental): max score 60"
        )

    def get_sector_signals(self) -> list[Signal]:
        signals: list[Signal] = []

        # US defense peers: LMT, RTX, NOC — move >2% -> Israeli defense tailwind
        for peer in self._DEFENSE_PEERS:
            signals.extend(self._peer_move_signal(
                peer_ticker    = peer,
                peer_label     = f"US Defense ({peer})",
                threshold_pct  = 2.0,
                target_tickers = ["ESLT.TA", "NXSN.TA"],
                signal_type    = "defense_tailwind",
                direction_text = "Israeli defense sector tailwind",
            ))

        # US semiconductor equipment peers — move >3% -> CAMT/NVMI/TSEM sympathy
        for peer in self._SEMI_PEERS:
            signals.extend(self._peer_move_signal(
                peer_ticker    = peer,
                peer_label     = f"US Semis ({peer})",
                threshold_pct  = 3.0,
                target_tickers = ["CAMT.TA", "NVMI.TA", "TSEM.TA"],
                signal_type    = "sector_peer_move",
                direction_text = "Israeli semiconductor equipment sympathy",
            ))

        # USD/ILS: shekel weakening -> exporter revenue boost
        signals.extend(self._peer_move_signal(
            peer_ticker    = "ILS=X",
            peer_label     = "USD/ILS (shekel weakening)",
            threshold_pct  = 1.5,
            target_tickers = self.tickers,
            signal_type    = "shekel_move",
            direction_text = "Israeli tech/defense export revenue tailwind",
        ))

        return signals
