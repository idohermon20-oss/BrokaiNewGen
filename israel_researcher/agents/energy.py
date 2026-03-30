"""
EnergyAgent — covers Israeli energy (9 tickers).

Domain expertise:
  - NWMD/DLEKG: tied to Leviathan/Tamar gas fields — NG=F is primary driver
  - ORL/PAZ: refinery/retail — Brent crack spread (BZ=F vs product prices)
  - ENLT/ENRG/OPCE: renewable energy — more defensive, EU carbon regulation
  - NVPT/RATI: exploration/royalties — oil price sensitive
"""

from __future__ import annotations

from ..config import SECTOR_TICKERS
from ..models import Signal
from .base import SectorAgent


class EnergyAgent(SectorAgent):
    sector_name = "Energy"
    tickers     = SECTOR_TICKERS["Energy"]  # 9 tickers

    @property
    def _sector_domain(self) -> str:
        return (
            "SECTOR: Israeli Energy — natural gas, oil refining, and renewables.\n\n"
            "KEY FACTORS:\n"
            "- Gas assets (NWMD, DLEKG, RATI): Eastern Mediterranean Leviathan/Tamar "
            "gas fields. Natural gas futures (NG=F) is the PRIMARY price driver. "
            "European gas demand and export contracts are structural tailwinds.\n"
            "- Refinery/retail (ORL, PAZ): Brent crude (BZ=F) is most relevant; "
            "refinery margins (crack spread) improve when crude falls but product prices stay high.\n"
            "- Renewables (ENLT, ENRG, OPCE): more defensive, less commodity-sensitive. "
            "EU carbon pricing, Israeli electricity tariffs, and PPA (power purchase agreements) "
            "are the primary catalysts.\n"
            "- NVPT: exploration company — oil discovery news = binary catalyst.\n"
            "- Geopolitical risk: Mediterranean conflict = supply disruption risk for offshore assets.\n\n"
            "SCORING ADJUSTMENTS:\n"
            "+ NG=F up >3% + NWMD/DLEKG/RATI technical signal: EXTREME priority +15\n"
            "+ WTI/Brent up >2% + ORL/PAZ technical: +8\n"
            "+ Signed gas export contract (maya_contract): top-tier signal +12\n"
            "+ Renewables: regulatory approval or PPA contract = +10\n"
            "- Geopolitical risk in filing detail: -8 (supply disruption risk)\n"
            "- Falling oil/gas with only technical signal: max score 55"
        )

    def get_sector_signals(self) -> list[Signal]:
        signals: list[Signal] = []

        # Natural gas (NG=F): most important for Israeli gas companies
        signals.extend(self._peer_move_signal(
            peer_ticker    = "NG=F",
            peer_label     = "Natural Gas (NG=F)",
            threshold_pct  = 3.0,
            target_tickers = ["NWMD.TA", "DLEKG.TA", "RATI.TA", "NVPT.TA"],
            signal_type    = "oil_correlation",
            direction_text = "Israeli gas producer revenue impact",
        ))

        # WTI crude: oil-sensitive companies
        signals.extend(self._peer_move_signal(
            peer_ticker    = "CL=F",
            peer_label     = "WTI Crude (CL=F)",
            threshold_pct  = 2.0,
            target_tickers = ["ORL.TA", "PAZ.TA", "DLEKG.TA", "NVPT.TA", "RATI.TA"],
            signal_type    = "oil_correlation",
            direction_text = "Israeli oil-sensitive energy stocks",
        ))

        # Brent crude: used for ORL refinery margin calculation
        signals.extend(self._peer_move_signal(
            peer_ticker    = "BZ=F",
            peer_label     = "Brent Crude (BZ=F)",
            threshold_pct  = 2.5,
            target_tickers = ["ORL.TA", "PAZ.TA"],
            signal_type    = "oil_correlation",
            direction_text = "Israeli refinery margin impact",
        ))

        # Renewables peer: NextEra Energy (NEE) for ENLT/ENRG/OPCE sentiment
        signals.extend(self._peer_move_signal(
            peer_ticker    = "NEE",
            peer_label     = "US Renewables (NEE)",
            threshold_pct  = 3.0,
            target_tickers = ["ENLT.TA", "ENRG.TA", "OPCE.TA"],
            signal_type    = "sector_peer_move",
            direction_text = "Israeli renewable energy sector sympathy",
        ))

        return signals
