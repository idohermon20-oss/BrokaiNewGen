"""
ConstructionAgent — covers Israeli construction and infrastructure engineering (6 tickers).

Large contractors:  ELTR (Electra), DNYA (Danya Cebus), ASHG (Ashtrom)
Mid contractors:    SPEN (Shapir), SKBN (Shikun & Binui), DIMRI (Dimri)

Domain expertise:
  - Government contracts (highways, hospitals, rail, housing): primary catalyst
    - Maya maya_contract filing for construction tender = transformative for mid-caps
  - Housing starts data: monthly Central Bureau of Statistics release
  - Commodity costs: steel (steel ETF SLX), concrete (cement prices)
  - BOI rate policy: lower rates → housing affordability → more starts → backlog growth
  - DNYA is controlled by Africa Israel (AFRE.TA) — any Africa Israel news affects DNYA
  - ELTR (Electra): diversified — construction + facilities management + real estate
    Largest by market cap (~6.7B ILS), most defensive of the group
  - SKBN: significant international operations (Europe, Africa) → shekel moves matter
"""

from __future__ import annotations

from ..config import SECTOR_TICKERS
from ..models import Signal
from .base import SectorAgent


class ConstructionAgent(SectorAgent):
    sector_name = "Construction"
    tickers     = SECTOR_TICKERS["Construction"]  # 6 tickers

    @property
    def _sector_domain(self) -> str:
        return (
            "SECTOR: Israeli Construction and Infrastructure Engineering.\n\n"
            "━━ LARGE CONTRACTORS ━━\n"
            "- ELTR (Electra Ltd, ~6.7B ILS): Israel's largest engineering/construction group. "
            "Three divisions: construction (highways, hospitals, schools), infrastructure "
            "maintenance & facilities management, and real estate development. "
            "Diversified revenue = most defensive in sector. Government megaproject wins = key catalyst.\n"
            "- DNYA (Danya Cebus, ~5.2B ILS): controlled by Africa Israel group. Specializes in "
            "residential towers, hospitals, and government buildings. Backlog growth is the best "
            "leading indicator. Any Africa Israel (AFRE.TA) parent news may cascade.\n"
            "- ASHG (Ashtrom Group, ~7.6B ILS): combined construction + commercial real estate "
            "development. Office and logistics park development in addition to contracting. "
            "Real estate revaluation gains supplement construction earnings.\n\n"
            "━━ MID-CAP CONTRACTORS ━━\n"
            "- SPEN (Shapir Engineering & Industry): infrastructure specialist — roads, bridges, "
            "rail sections, seaports. Government tender win = transformative catalyst. "
            "Exposed to commodity cost inflation (steel, asphalt).\n"
            "- SKBN (Shikun & Binui): Israel's largest residential developer + significant "
            "international construction (Eastern Europe, Africa, Latin America). "
            "International segment diversifies geopolitical risk. USD revenue exposure.\n"
            "- DIMRI (Y.H. Dimri): residential construction and real estate development, "
            "primarily in central Israel. Most correlated to Israeli housing market data.\n\n"
            "━━ KEY MACRO DRIVERS ━━\n"
            "- Government budget: Ministry of Finance construction budget releases — biggest catalyst\n"
            "- Housing starts (CBS data): monthly stat, leads DIMRI/DNYA/ASHG by 6-12 months\n"
            "- BOI rate policy: rate cuts → housing affordability → higher housing starts backlog\n"
            "- Steel prices (SLX ETF): key input cost — rising steel = margin compression\n"
            "- USD/ILS: SKBN international revenue (positive on USD strength)\n"
            "- Israeli government coalition stability: affects capital budget execution\n\n"
            "━━ SCORING ADJUSTMENTS ━━\n"
            "+ Government tender/contract (maya_contract, government keyword): +15 for SPEN/DIMRI "
            "(small-cap, transformative), +10 for ELTR/DNYA/ASHG (large-cap, material but not transformative)\n"
            "+ Housing starts data beat: DIMRI/DNYA/ASHG +8\n"
            "+ BOI rate cut: all +8 (construction financing and housing demand dual benefit)\n"
            "+ SLX (steel ETF) down >3%: SPEN/SKBN +6 (input cost relief)\n"
            "+ SKBN international contract: +10 (revenue diversification catalyst)\n"
            "- Steel prices spike >5%: margin risk for all -6\n"
            "- Government budget freeze or austerity news: -10 (pipeline dries up)\n"
            "- Geopolitical escalation: -6 (construction site safety, permits delayed)"
        )

    def get_sector_signals(self) -> list[Signal]:
        signals: list[Signal] = []

        # SLX: US Steel ETF — input cost proxy for construction companies
        signals.extend(self._peer_move_signal(
            peer_ticker    = "SLX",
            peer_label     = "US Steel ETF (SLX)",
            threshold_pct  = 3.0,
            target_tickers = self.tickers,
            signal_type    = "sector_peer_move",
            direction_text = "Construction steel input cost signal (inverse: SLX down = cost relief)",
        ))

        # US homebuilders ETF: ITB — housing/construction sentiment
        signals.extend(self._peer_move_signal(
            peer_ticker    = "ITB",
            peer_label     = "US Homebuilders ETF (ITB)",
            threshold_pct  = 2.5,
            target_tickers = ["DIMRI.TA", "ASHG.TA", "DNYA.TA", "SKBN.TA"],
            signal_type    = "sector_peer_move",
            direction_text = "Global homebuilder / construction sector sentiment",
        ))

        # USD/ILS: SKBN has international operations; USD strength = revenue tailwind
        signals.extend(self._peer_move_signal(
            peer_ticker    = "ILS=X",
            peer_label     = "USD/ILS move",
            threshold_pct  = 1.5,
            target_tickers = ["SKBN.TA", "ELTR.TA"],
            signal_type    = "shekel_move",
            direction_text = "Construction international revenue / import cost impact",
        ))

        return signals
