"""
TechDefenseAgent — covers Israeli tech and defense (21 tickers).

Defense primes:      ESLT, NXSN
Defense components:  ARYT, ASHO, TATT
Naval:               ISHI
Tactical comms/C2:   CMER

Drone/surveillance:  ARDM, SMSH
Defense venture:     ELRN
Semiconductors:      NVMI, TSEM, CAMT
Software/comms:      NICE, AUDC, ALLT
IT services:         MTRX, HLAN, FORTY, MLTM
Industrial tech:     KRNT

Domain expertise:
  - Defense contracts = multi-year revenue visibility; IDF/NATO = highest quality
  - Small-cap defense (ARYT, ASHO, ISHI, CMER, SMSH): contract = transformative catalyst
  - Semiconductor equipment (NVMI, TSEM, CAMT): follow global semis cycle
  - Shekel weakness = export revenue boost (all tickers export in USD)
  - Dual-listed stocks (10): US overnight move predicts TASE next-day
  - VIX spike = geopolitical tension = structural tailwind for defense
"""

from __future__ import annotations

from ..config import SECTOR_TICKERS
from ..models import Signal
from .base import SectorAgent


class TechDefenseAgent(SectorAgent):
    sector_name = "TechDefense"
    tickers     = SECTOR_TICKERS["TechDefense"]  # 21 tickers

    # US defense peers — move >2% creates sector tailwind for Israeli defense
    _DEFENSE_PEERS = ["LMT", "RTX", "NOC"]
    # US semiconductor equipment peers — most relevant for CAMT, NVMI, TSEM
    _SEMI_PEERS    = ["AMAT", "KLAC", "LRCX"]
    # Dual-listed subset (US overnight move = direct TASE signal)
    _DUAL_LISTED   = ["ESLT.TA", "NICE.TA", "NVMI.TA", "TSEM.TA",
                      "CAMT.TA", "AUDC.TA", "ALLT.TA", "KRNT.TA",
                      "TATT.TA"]

    @property
    def _sector_domain(self) -> str:
        return (
            "SECTOR: Israeli Technology and Defense.\n\n"
            "━━ DEFENSE PRIME CONTRACTORS ━━\n"
            "- ESLT (Elbit Systems, dual-listed Nasdaq+TASE): Israel's largest private "
            "defense company. Drones, EW, optics, C4ISR. IDF/NATO multi-year contracts "
            "= highest quality catalyst. VIX >22 = structural demand tailwind.\n"
            "- NXSN (NextVision): stabilized cameras and imaging pods for UAVs. "
            "Pure IDF/export play — contract announcements are transformative.\n\n"
            "━━ DEFENSE SUB-SYSTEMS & COMPONENTS ━━\n"
            "- ARYT (Aryt Industries): sole Israeli supplier of electronic fuzes for IDF "
            "artillery, mortars, and tank rounds. Any IDF tender win = transformative for "
            "this small-cap. Post-Oct 2023 demand surge is structural, not cyclical.\n"
            "- ASHO (Ashot Ashkelon): precision gears, landing gear, and engine shafts for "
            "IDF aircraft. Small-cap; large contract = material catalyst.\n"
            "- TATT (TAT Technologies, dual-listed Nasdaq+TASE): heat transfer/fuel systems "
            "MRO for military aircraft. Works on IDF and NATO fleets. Revenue in USD — "
            "shekel weakness = direct tailwind.\n\n"
            "━━ NAVAL DEFENSE ━━\n"
            "- ISHI (Israel Shipyards): designs and builds naval vessels for the Israeli Navy "
            "(patrol boats, corvettes). Contract for new vessel = high-value multi-year signal.\n\n"
            "━━ TACTICAL COMMUNICATIONS & C2 ━━\n"
            "- CMER (Mer Group): sole IDF supplier of tactical land/naval communications and "
            "command-and-control systems. Classified contracts → Maya filings often generic. "
            "Any contract filing = major signal regardless of disclosed value.\n\n"
            "━━ DRONE & SURVEILLANCE ━━\n"
            "- ARDM (Aerodrome Group): drone data collection and AI analysis for "
            "defense/infrastructure surveillance. Growing IDF drone doctrine = structural tailwind.\n"
            "- SMSH (SmartShooter): AI-powered SMASH targeting system (locks onto moving targets, "
            "counter-drone). IPO'd March 2026. NATO and IDF adoption = key catalyst.\n\n"
            "━━ DEFENSE-TECH VENTURE ━━\n"
            "- ELRN (Elron Electronic Industries): venture holding company commercializing "
            "Rafael defense IP through the RDC joint venture. Portfolio exit or new investment = catalyst.\n\n"
            "━━ SEMICONDUCTORS & HARDWARE ━━\n"
            "- NVMI/TSEM/CAMT: follow global semis cycle. US peers AMAT/KLAC/LRCX moves "
            ">3% = leading indicator.\n\n"
            "━━ SOFTWARE & SERVICES ━━\n"
            "- NICE/AUDC/ALLT/HLAN: follow SaaS/cloud valuations; US tech sentiment matters.\n"
            "- FORTY (Formula Systems): IT holding company, diversified risk.\n"
            "- KRNT (Kornit Digital, dual-listed Nasdaq+TASE): digital textile printing. "
            "Pure USD exporter — shekel weakening = tailwind. New brand deployment = catalyst.\n\n"
            "━━ SHARED MACRO FACTORS ━━\n"
            "- Shekel weakness (USD/ILS rising): boosts USD revenues across ALL tickers.\n"
            "- Dual-listed US overnight move: near-certain TASE next-day predictor "
            "(ESLT, NICE, NVMI, TSEM, CAMT, AUDC, ALLT, KRNT, TATT).\n"
            "- VIX >22: geopolitical tension = structural tailwind for all defense tickers.\n\n"
            "━━ SCORING ADJUSTMENTS ━━\n"
            "+ ARYT/ASHO/ISHI IDF contract/tender: +15 (small-cap, highly material)\n"
            "+ CMER contract filing (even generic/classified): +12 (sole-supplier, recurring)\n"
            "+ SMSH international/NATO adoption: +12 (validates commercial model)\n"
            "+ Defense contract (maya_contract + government_defense): best combo, +15\n"
            "+ US semis peers >3% + CAMT/NVMI technical: +10\n"
            "+ TATT US overnight move + technical: +8\n"
            "+ Shekel weakened >1.5%: all exporters +6\n"
            "+ VIX >22 + defense ticker: +8 geopolitical premium\n"
            "- RSI >75 + no hard catalyst: overbought risk -8\n"
            "- Single technical only (no fundamental): max score 60"
        )

    def get_sector_signals(self) -> list[Signal]:
        signals: list[Signal] = []

        # US defense peers: LMT, RTX, NOC — move >2% -> all Israeli defense tickers
        _DEFENSE_TICKERS = [
            "ESLT.TA", "NXSN.TA", "ARYT.TA", "ASHO.TA",
            "ISHI.TA", "CMER.TA", "ARDM.TA", "SMSH.TA", "ELRN.TA",
        ]
        for peer in self._DEFENSE_PEERS:
            signals.extend(self._peer_move_signal(
                peer_ticker    = peer,
                peer_label     = f"US Defense ({peer})",
                threshold_pct  = 2.0,
                target_tickers = _DEFENSE_TICKERS,
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

        # USD/ILS: shekel weakening -> exporter revenue boost (all tickers are USD exporters)
        signals.extend(self._peer_move_signal(
            peer_ticker    = "ILS=X",
            peer_label     = "USD/ILS (shekel weakening)",
            threshold_pct  = 1.5,
            target_tickers = self.tickers,
            signal_type    = "shekel_move",
            direction_text = "Israeli tech/defense export revenue tailwind",
        ))

        return signals
