"""
TelecomConsumerAgent — covers Telecom (3) + Consumer (6) = 9 tickers.

Domain expertise:
  - Telecom: oligopolistic market (Bezeq dominant), dividend yield is primary driver
  - Consumer defensive: SAE/RMLI (supermarkets) = resilient, inflation pass-through
  - Consumer discretionary: STRS (food/beverage/export), FOX (fashion retail), DIPL (distribution)
  - Shekel strength = lower import costs for consumer/retail importers
  - Hotels/airlines (FTAL) moved to TourismTransportAgent
"""

from __future__ import annotations

from ..config import SECTOR_TICKERS
from ..models import Signal
from .base import SectorAgent


class TelecomConsumerAgent(SectorAgent):
    sector_name = "TelecomConsumer"
    tickers     = SECTOR_TICKERS["TelecomConsumer"]  # 9 tickers

    @property
    def _sector_domain(self) -> str:
        return (
            "SECTOR: Israeli Telecom and Consumer.\n\n"
            "TELECOM (BEZQ, PTNR, CEL):\n"
            "- Oligopolistic market: Bezeq (BEZQ) is dominant fixed-line/broadband, "
            "regulated by Communications Ministry.\n"
            "- Dividend yield (5-8%) is the primary valuation driver — yield compression "
            "when rates fall = price appreciation.\n"
            "- Regulatory risk: open-access rules, interconnect fees can impact margins.\n"
            "- Partner (PTNR) and Cellcom (CEL): mobile operators, competing on 5G rollout.\n"
            "- Catalyst types: dividend announcement, subscriber growth beat, "
            "regulatory decision, M&A consolidation rumors.\n\n"
            "CONSUMER (SAE, STRS, RMLI, ELCO, FOX, DIPL):\n"
            "- SAE (Shufersal) + RMLI (Rami Levi): defensive supermarkets. "
            "Inflation pass-through model = stable margins. Non-cyclical demand.\n"
            "- STRS (Strauss Group): branded food + beverages + export (PepsiCo JV). "
            "Shekel strength reduces import costs; international expansion = growth driver.\n"
            "- ELCO: electronics distribution holding. Discretionary consumer spend.\n"
            "- FOX (Fox-Wizel): Israel's largest fashion/apparel retailer. "
            "Shekel strength = lower garment import costs (sourced in USD/EUR). "
            "Same-store-sales growth and new store openings = catalyst.\n"
            "- DIPL (Diplomat Holdings): food and consumer goods distribution (Heineken, "
            "Procter & Gamble, Unilever brands in Israel). Defensive distributor. "
            "New brand distribution agreement = growth catalyst.\n"
            "- Shekel strengthening: directly reduces import costs for SAE/STRS/RMLI/FOX/DIPL.\n\n"
            "SCORING ADJUSTMENTS:\n"
            "+ Dividend announcement (maya_dividend): telecom = +10 (yield play)\n"
            "+ Shekel strengthened >1.5%: consumer importers +7\n"
            "+ Buyback announcement for BEZQ: strong signal +10\n"
            "+ New brand distribution agreement for DIPL: +10\n"
            "+ FOX new store expansion or same-store-sales beat: +8\n"
            "+ US consumer staples (XLP) up >2%: defensive consumer sympathy +5\n"
            "- BEZQ regulatory headwind in news: -8\n"
            "- Consumer confidence index drop: FOX/ELCO -6 (discretionary exposure)"
        )

    def get_sector_signals(self) -> list[Signal]:
        signals: list[Signal] = []

        # XLP: US Consumer Staples ETF — sentiment for defensive consumer stocks
        signals.extend(self._peer_move_signal(
            peer_ticker    = "XLP",
            peer_label     = "US Consumer Staples (XLP)",
            threshold_pct  = 2.0,
            target_tickers = ["SAE.TA", "STRS.TA", "RMLI.TA"],
            signal_type    = "sector_peer_move",
            direction_text = "Israeli defensive consumer sector sympathy",
        ))

        # XTL: US telecom ETF — global telecom sentiment
        signals.extend(self._peer_move_signal(
            peer_ticker    = "IYZ",
            peer_label     = "US Telecom ETF (IYZ)",
            threshold_pct  = 2.5,
            target_tickers = ["BEZQ.TA", "PTNR.TA", "CEL.TA"],
            signal_type    = "sector_peer_move",
            direction_text = "Israeli telecom sector sympathy",
        ))

        # Shekel move: strengthening helps importers (SAE, STRS, RMLI, ELCO, FOX, DIPL)
        signals.extend(self._peer_move_signal(
            peer_ticker    = "ILS=X",
            peer_label     = "USD/ILS move",
            threshold_pct  = 1.5,
            target_tickers = ["SAE.TA", "STRS.TA", "RMLI.TA", "ELCO.TA", "FOX.TA", "DIPL.TA"],
            signal_type    = "shekel_move",
            direction_text = "Israeli consumer/retail import cost impact",
        ))

        return signals
