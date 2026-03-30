"""
BanksAgent — covers Banks + Insurance + Finance services (15 tickers).

Domain expertise:
  - Israeli banks benefit from rising rates (NIM expansion)
  - Insurance profits grow with higher bond yields (investment portfolio)
  - BOI (Bank of Israel) rate policy is the primary macro driver
  - US bank index KBE is a sentiment leading indicator
  - Buyback / dividend announcements = management confidence signal
"""

from __future__ import annotations

from ..config import SECTOR_TICKERS
from ..models import Signal
from .base import SectorAgent


class BanksAgent(SectorAgent):
    sector_name = "Banks"
    tickers     = SECTOR_TICKERS["Banks"]   # 15 tickers: banks + insurance + finance

    @property
    def _sector_domain(self) -> str:
        return (
            "SECTOR: Israeli Banks, Insurance, and Financial Services.\n\n"
            "KEY FACTORS:\n"
            "- BOI (Bank of Israel) rate policy is the #1 driver for banks: "
            "rising rates expand Net Interest Margin (NIM), falling rates compress it.\n"
            "- Insurance companies (PHOE, HARL, CLIS, MGDL, MMHD) benefit from "
            "higher bond yields on their investment portfolios.\n"
            "- Banks at 52w lows with rising volume = BOI pause/cut anticipation play "
            "(capital appreciation + high dividend yield compression).\n"
            "- Buyback or dividend increase announcements = management confidence signal "
            "(strongest buy signal for TASE banks).\n"
            "- US bank index (KBE) move = global bank sentiment leading indicator; "
            "Israeli banks follow 0-1 day lag.\n"
            "- Credit quality: watch for NPL (non-performing loan) guidance in filings.\n"
            "- Dual-listed: none in this sector (no US arbitrage signal).\n\n"
            "SCORING ADJUSTMENTS:\n"
            "+ High VIX >25: banks = defensive relative play (stable NIM, high dividends) +5\n"
            "+ BOI rate hike news in headlines: banks +8, insurance +6\n"
            "+ KBE move >2.5%: sympathy signal, apply +6\n"
            "+ Buyback/dividend (maya_buyback, maya_dividend): always strong, +8\n"
            "- Credit quality concern in filing detail: -10\n"
            "- Low RSI (<28) + no catalyst: oversold but wait for catalyst; score 55 max"
        )

    def get_sector_signals(self) -> list[Signal]:
        signals: list[Signal] = []
        # KBE: US bank sector ETF — Israeli banks follow global banking sentiment
        signals.extend(self._peer_move_signal(
            peer_ticker    = "KBE",
            peer_label     = "US Bank ETF (KBE)",
            threshold_pct  = 2.5,
            target_tickers = [t for t in self.tickers if t in {
                "LUMI.TA", "POLI.TA", "MZTF.TA", "DSCT.TA", "FIBI.TA", "JBNK.TA"
            }],
            signal_type    = "sector_peer_move",
            direction_text = "Israeli bank sector sympathy",
        ))
        # XLF: broader US financial ETF for insurance / financial services
        signals.extend(self._peer_move_signal(
            peer_ticker    = "XLF",
            peer_label     = "US Financial ETF (XLF)",
            threshold_pct  = 2.0,
            target_tickers = [t for t in self.tickers if t in {
                "PHOE.TA", "HARL.TA", "CLIS.TA", "MGDL.TA", "MMHD.TA",
                "ISCD.TA", "ILCO.TA", "DISI.TA",
            }],
            signal_type    = "sector_peer_move",
            direction_text = "Israeli insurance/finance sector sympathy",
        ))
        return signals
