"""
TourismTransportAgent — covers Israeli tourism, hotels, and airlines (5 tickers).

Hotels:      ISRO (Isrotel), DANH (Dan Hotels), FTAL (Fattal Holdings)
Airlines:    ELAL (El Al), ISRG (Israir)

Domain expertise:
  - Geopolitical risk is the #1 driver — Israel conflict = immediate tourism collapse
  - ELAL: national carrier, 30%+ fuel cost, OTC in US (ELALY) — oil price = primary cost driver
  - Hotels (ISRO, DANH, FTAL): inbound vs outbound tourism mix matters
    - Israel inbound: dominated by Christian/Jewish pilgrims + business travel
    - Ceasefire/security improvement = fastest recovery catalyst
  - ISRG (Israir): low-cost carrier, domestic routes + Eilat charter — most sensitive to security
  - USD strength: foreign tourists pay in USD → revenue boost for all ILS-cost companies
  - JETS (US airline ETF) + HLT/MAR moves: global travel sentiment leading indicator
"""

from __future__ import annotations

from ..config import SECTOR_TICKERS
from ..models import Signal
from .base import SectorAgent


class TourismTransportAgent(SectorAgent):
    sector_name = "TourismTransport"
    tickers     = SECTOR_TICKERS["TourismTransport"]  # 5 tickers

    _AIRLINE_PEERS = ["DAL", "UAL", "LUV"]   # US airlines — fuel cost / demand proxy
    _HOTEL_PEERS   = ["HLT", "MAR", "IHG"]   # Global hotel chains — occupancy sentiment

    @property
    def _sector_domain(self) -> str:
        return (
            "SECTOR: Israeli Tourism, Hotels, and Airlines.\n\n"
            "━━ AIRLINES ━━\n"
            "- ELAL (El Al Israel Airlines): Israel's national carrier. Dual-listed OTC in US "
            "(ELALY). Fuel is ~30% of operating costs — WTI/Brent spike = margin compression. "
            "Geopolitical escalation = immediate demand collapse (safety alerts, route cancellations). "
            "Security normalization or ceasefire = recovery catalyst. USD strength boosts revenue "
            "(tickets priced in USD) while ILS costs remain. Strong balance sheet post-2020 restructuring.\n"
            "- ISRG (Israir Group): low-cost carrier, domestic routes + Eilat sun-and-sea charters. "
            "Smaller, more volatile. Most sensitive to Israeli domestic security situation. "
            "Eilat corridor expansion = growth catalyst. Any ELAL route capacity cut = ISRG beneficiary.\n\n"
            "━━ HOTELS ━━\n"
            "- ISRO (Isrotel): Israel's largest hotel chain (~40 properties). Mix: Red Sea (Eilat), "
            "Tel Aviv business, Jerusalem religious tourism. High fixed costs = occupancy rate is "
            "the most critical metric. Ceasefire + return of international tourism = strongest catalyst.\n"
            "- DANH (Dan Hotels): premium brand, 15 properties. Tel Aviv and Jerusalem focused. "
            "Higher ADR (average daily rate) than Isrotel — revenue more sensitive to business travel.\n"
            "- FTAL (Fattal Hotels): Israel's fastest-growing hotel group, significant European presence "
            "(Germany, Austria, Netherlands). European segment partially offsets Israeli geopolitical risk. "
            "European hotel demand index matters. M&A of European properties = growth catalyst.\n\n"
            "━━ KEY MACRO DRIVERS ━━\n"
            "- Geopolitical events (war, ceasefire, threat level): #1 driver — immediate -15/+15 impact\n"
            "- WTI/Brent oil price: airline fuel cost — every $10/barrel = ~$30M ELAL annual cost\n"
            "- USD/ILS: USD strength = revenue boost (tickets in USD, costs in ILS)\n"
            "- Israel Tourism Ministry arrival statistics: leading indicator for hotel occupancy\n"
            "- US airline ETF (JETS): global air travel demand sentiment\n"
            "- European hotel demand (HLT/MAR moves >2%): FTAL international segment signal\n\n"
            "━━ SCORING ADJUSTMENTS ━━\n"
            "+ Ceasefire/security normalization headline: all tickers +15 (demand recovery catalyst)\n"
            "+ JETS up >3%: ELAL/ISRG +10 (global air travel sentiment)\n"
            "+ HLT/MAR up >2%: ISRO/DANH/FTAL +8 (hotel sector sentiment)\n"
            "+ USD strengthens >1.5%: all tickers +6 (USD revenue boost)\n"
            "+ FTAL European hotel M&A: +10 (international diversification)\n"
            "- Security escalation / conflict news: all tickers -15 (demand collapse risk)\n"
            "- WTI/Brent spike >5%: ELAL/ISRG -10 (fuel cost squeeze)\n"
            "- Low RSI (<35) + security improving = accumulation setup, do not penalize\n"
            "- Small-cap (ISRG): require hard catalyst before score > 60"
        )

    def get_sector_signals(self) -> list[Signal]:
        signals: list[Signal] = []

        # JETS: US Global Airlines ETF — global air travel demand sentiment
        signals.extend(self._peer_move_signal(
            peer_ticker    = "JETS",
            peer_label     = "US Airlines ETF (JETS)",
            threshold_pct  = 3.0,
            target_tickers = ["ELAL.TA", "ISRG.TA"],
            signal_type    = "sector_peer_move",
            direction_text = "Global airline demand sentiment for Israeli carriers",
        ))

        # US airline peers: DAL/UAL/LUV — fuel cost and demand proxy
        for peer in self._AIRLINE_PEERS:
            signals.extend(self._peer_move_signal(
                peer_ticker    = peer,
                peer_label     = f"US Airline ({peer})",
                threshold_pct  = 3.0,
                target_tickers = ["ELAL.TA", "ISRG.TA"],
                signal_type    = "sector_peer_move",
                direction_text = "Airline fuel cost / demand sympathy",
            ))

        # HLT/MAR: global hotel chains — occupancy and ADR sentiment
        for peer in self._HOTEL_PEERS:
            signals.extend(self._peer_move_signal(
                peer_ticker    = peer,
                peer_label     = f"Global Hotels ({peer})",
                threshold_pct  = 2.0,
                target_tickers = ["ISRO.TA", "DANH.TA", "FTAL.TA"],
                signal_type    = "sector_peer_move",
                direction_text = "Global hotel occupancy / ADR sentiment for Israeli chains",
            ))

        # WTI oil: fuel is 30%+ of airline operating costs
        signals.extend(self._peer_move_signal(
            peer_ticker    = "CL=F",
            peer_label     = "WTI Crude Oil (CL=F)",
            threshold_pct  = 4.0,
            target_tickers = ["ELAL.TA", "ISRG.TA"],
            signal_type    = "sector_peer_move",
            direction_text = "Airline fuel cost impact (WTI move)",
        ))

        # USD/ILS: stronger USD = revenue boost (tickets priced in USD, costs in ILS)
        signals.extend(self._peer_move_signal(
            peer_ticker    = "ILS=X",
            peer_label     = "USD/ILS (USD strength)",
            threshold_pct  = 1.5,
            target_tickers = self.tickers,
            signal_type    = "shekel_move",
            direction_text = "USD-denominated tourism revenue tailwind",
        ))

        return signals
