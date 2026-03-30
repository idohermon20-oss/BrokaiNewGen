"""
Market data sources:
  MarketAnomalyDetector — volume spikes, price moves, 52w breakouts, MA crossovers,
                          oversold bounces, relative strength leaders
  SectorAnalyzer        — sector-level trend snapshot for LLM context
  DualListedMonitor     — US overnight moves for Israeli dual-listed stocks
  MacroContext          — TA-35, S&P 500, USD/ILS, VIX snapshot
  DeepStockAnalyzer     — RSI, moving averages, revenue growth for weekly report
"""

from __future__ import annotations

import random
import time
from typing import Optional

import pandas as pd
import yfinance as yf

from ..config import (
    VOLUME_SPIKE_X, PRICE_MOVE_PCT, ANOMALY_SAMPLE_SIZE,
    MACRO_TICKERS, DUAL_LISTED_STOCKS, TASE_MAJOR_TICKERS,
)
from ..models import Signal, now_iso

# Sector map: ticker → sector label (for sector context string)
TICKER_SECTOR = {
    "LUMI.TA": "Banks",  "POLI.TA": "Banks",   "MZTF.TA": "Banks",
    "DSCT.TA": "Banks",  "FIBI.TA": "Banks",   "JBNK.TA": "Banks",
    "PHOE.TA": "Insurance", "HARL.TA": "Insurance", "CLIS.TA": "Insurance",
    "MGDL.TA": "Insurance", "MMHD.TA": "Insurance",
    "AZRG.TA": "RealEstate", "AMOT.TA": "RealEstate", "BIG.TA":  "RealEstate",
    "MLSR.TA": "RealEstate", "MVNE.TA": "RealEstate", "DIMRI.TA":"RealEstate",
    "SPEN.TA": "RealEstate", "ALHE.TA": "RealEstate", "GVYM.TA": "RealEstate",
    "ARPT.TA": "RealEstate", "GCT.TA":  "RealEstate", "SKBN.TA": "RealEstate",
    "AURA.TA": "RealEstate", "ROTS.TA": "RealEstate",
    "ESLT.TA": "TechDefense", "NICE.TA": "TechDefense", "NVMI.TA": "TechDefense",
    "TSEM.TA": "TechDefense", "CAMT.TA": "TechDefense", "NXSN.TA": "TechDefense",
    "AUDC.TA": "TechDefense", "ALLT.TA": "TechDefense", "HLAN.TA": "TechDefense",
    "FORTY.TA":"TechDefense", "MLTM.TA": "TechDefense",
    "DLEKG.TA":"Energy", "OPCE.TA": "Energy", "ENLT.TA": "Energy",
    "NVPT.TA": "Energy", "NWMD.TA": "Energy", "ENRG.TA": "Energy",
    "ORL.TA":  "Energy", "PAZ.TA":  "Energy", "RATI.TA": "Energy",
    "TEVA.TA": "Pharma", "ICL.TA":  "Pharma", "KMDA.TA": "Pharma",
    "CGEN.TA": "Pharma", "EVGN.TA": "Pharma",
    "BEZQ.TA": "Telecom","PTNR.TA": "Telecom","CEL.TA":  "Telecom",
    "SAE.TA":  "Consumer","STRS.TA": "Consumer","FTAL.TA": "Consumer",
    "RMLI.TA": "Consumer","ELCO.TA": "Consumer",
    "ISCD.TA": "Finance", "ILCO.TA": "Finance", "DISI.TA": "Finance",
    "TASE.TA": "Finance",
}


class MarketAnomalyDetector:
    def __init__(
        self,
        tickers_yf: list[str],
        volume_spike_x: float = VOLUME_SPIKE_X,
        price_move_pct: float = PRICE_MOVE_PCT,
    ):
        self.tickers_yf      = tickers_yf
        self._volume_spike_x = volume_spike_x
        self._price_move_pct = price_move_pct

    def _history(self, ticker_yf: str) -> pd.DataFrame:
        try:
            return yf.Ticker(ticker_yf).history(period="21d", interval="1d")
        except Exception:
            return pd.DataFrame()

    def _volume_spike(self, ticker_yf: str, df: pd.DataFrame) -> Optional[Signal]:
        if len(df) < 3:
            return None
        today_vol   = df["Volume"].iloc[-1]
        avg_20d_vol = df["Volume"].iloc[:-1].mean()
        if avg_20d_vol <= 0 or today_vol <= 0:
            return None
        ratio = today_vol / avg_20d_vol
        if ratio < self._volume_spike_x:
            return None
        ticker = ticker_yf.replace(".TA", "")
        return Signal(
            ticker       = ticker,
            ticker_yf    = ticker_yf,
            company_name = ticker,
            signal_type  = "volume_spike",
            headline     = f"Volume {ratio:.1f}x 20-day average",
            detail       = f"Today: {int(today_vol):,} | 20d avg: {int(avg_20d_vol):,}",
            url          = f"https://finance.yahoo.com/quote/{ticker_yf}",
            timestamp    = now_iso(),
        )

    def _price_move(self, ticker_yf: str, df: pd.DataFrame) -> Optional[Signal]:
        if len(df) < 2:
            return None
        prev  = df["Close"].iloc[-2]
        today = df["Close"].iloc[-1]
        if prev <= 0:
            return None
        pct = (today - prev) / prev * 100
        if abs(pct) < self._price_move_pct:
            return None
        ticker    = ticker_yf.replace(".TA", "")
        direction = "+" if pct > 0 else ""
        return Signal(
            ticker       = ticker,
            ticker_yf    = ticker_yf,
            company_name = ticker,
            signal_type  = "price_move",
            headline     = f"Price {direction}{pct:.1f}% today",
            detail       = f"{prev:.2f} → {today:.2f} ILS",
            url          = f"https://finance.yahoo.com/quote/{ticker_yf}",
            timestamp    = now_iso(),
        )

    def _breakout_signal(self, ticker_yf: str, df: pd.DataFrame) -> Optional[Signal]:
        """
        52-week high breakout: stock within 3% of its yearly high with above-average volume.
        Real analysts treat this as a momentum continuation signal — institutions that
        accumulated near the high are now willing to pay even more, signaling conviction.
        """
        if len(df) < 3:
            return None
        today_price = df["Close"].iloc[-1]
        if today_price <= 0:
            return None
        try:
            high_52w = yf.Ticker(ticker_yf).fast_info.fifty_two_week_high
        except Exception:
            return None
        if not high_52w or high_52w <= 0:
            return None
        pct_from_high = (today_price / high_52w - 1) * 100
        if pct_from_high < -3.0:   # Not within 3% of 52w high
            return None
        today_vol = df["Volume"].iloc[-1]
        avg_vol   = df["Volume"].iloc[:-1].mean()
        if avg_vol <= 0 or today_vol < avg_vol * 1.2:  # Require 1.2x volume at breakout
            return None
        ticker = ticker_yf.replace(".TA", "")
        return Signal(
            ticker       = ticker,
            ticker_yf    = ticker_yf,
            company_name = ticker,
            signal_type  = "breakout",
            headline     = f"52w breakout: {today_price:.2f} ({pct_from_high:+.1f}% from yearly high) — volume {today_vol/avg_vol:.1f}x",
            detail       = f"52w high: {high_52w:.2f} | Today: {today_price:.2f} | Vol ratio: {today_vol/avg_vol:.1f}x",
            url          = f"https://finance.yahoo.com/quote/{ticker_yf}",
            timestamp    = now_iso(),
        )

    def _ma_crossover_signal(self, ticker_yf: str) -> Optional[Signal]:
        """
        Golden cross: MA20 crosses above MA50 in the last 3 sessions.
        A classic momentum signal used by both retail and institutional traders.
        Only run for priority tickers (requires 3-month history fetch).
        """
        try:
            df = yf.Ticker(ticker_yf).history(period="3mo", interval="1d")
        except Exception:
            return None
        if len(df) < 55:
            return None
        close = df["Close"]
        ma20  = close.rolling(20).mean()
        ma50  = close.rolling(50).mean()
        # Check if MA20 crossed above MA50 in the last 3 sessions
        for i in range(-3, 0):
            try:
                was_below = ma20.iloc[i - 1] <= ma50.iloc[i - 1]
                now_above = ma20.iloc[i]      >  ma50.iloc[i]
            except IndexError:
                continue
            if was_below and now_above:
                ticker = ticker_yf.replace(".TA", "")
                return Signal(
                    ticker       = ticker,
                    ticker_yf    = ticker_yf,
                    company_name = ticker,
                    signal_type  = "ma_crossover",
                    headline     = f"Golden cross: MA20 ({ma20.iloc[-1]:.2f}) crossed above MA50 ({ma50.iloc[-1]:.2f})",
                    detail       = f"Bullish momentum -- short-term trend broke above long-term trend",
                    url          = f"https://finance.yahoo.com/quote/{ticker_yf}",
                    timestamp    = now_iso(),
                )
        return None

    def _oversold_bounce_signal(self, ticker_yf: str, df: pd.DataFrame) -> Optional[Signal]:
        """
        Oversold bounce setup: RSI-14 below 32 with rising short-term volume.

        Real-analyst rationale: When a stock is deeply oversold (RSI < 32) AND volume
        starts rising (5d avg > 20d avg by 20%+), it suggests institutional accumulation
        while retail is still selling. This is often the 'quiet' phase before a reversal.
        Combined with a Maya filing or earnings catalyst, this setup has high hit rate.
        """
        if len(df) < 21:
            return None
        close = df["Close"]
        rsi   = _calc_rsi(close, 14)
        if rsi is None or rsi >= 32:
            return None
        vol     = df["Volume"]
        vol_5d  = vol.iloc[-5:].mean()
        vol_20d = vol.iloc[:-5].mean() if len(df) > 5 else vol.mean()
        if vol_20d <= 0 or vol_5d < vol_20d * 1.2:
            return None
        ticker = ticker_yf.replace(".TA", "")
        return Signal(
            ticker       = ticker,
            ticker_yf    = ticker_yf,
            company_name = ticker,
            signal_type  = "oversold_bounce",
            headline     = f"Oversold bounce setup: RSI {rsi:.0f} with rising volume ({vol_5d/vol_20d:.1f}x 20d avg)",
            detail       = f"RSI-14: {rsi:.1f} | 5d avg vol: {int(vol_5d):,} | 20d avg vol: {int(vol_20d):,} | Ratio: {vol_5d/vol_20d:.2f}x",
            url          = f"https://finance.yahoo.com/quote/{ticker_yf}",
            timestamp    = now_iso(),
        )

    def _low_reversal_signal(self, ticker_yf: str, df: pd.DataFrame) -> Optional[Signal]:
        """
        52w low reversal: stock within 5% of yearly low, bouncing with above-average volume.

        Real-analyst rationale: When a deeply oversold stock touches its 52w low
        and bounces with volume, it signals that buyers stepped in at a key support
        level. This is a classic value-entry / capitulation-reversal setup — especially
        powerful when combined with a catalyst (buyback, contract, institutional buy).
        Currently very relevant for Israeli banks and real estate trading near multi-year lows.
        """
        if len(df) < 3:
            return None
        today_price = df["Close"].iloc[-1]
        if today_price <= 0:
            return None
        # Must be bouncing (today close > yesterday close)
        if df["Close"].iloc[-1] <= df["Close"].iloc[-2]:
            return None
        try:
            low_52w = yf.Ticker(ticker_yf).fast_info.fifty_two_week_low
        except Exception:
            return None
        if not low_52w or low_52w <= 0:
            return None
        pct_from_low = (today_price / low_52w - 1) * 100
        if pct_from_low > 5.0:   # Not within 5% of 52w low
            return None
        today_vol = df["Volume"].iloc[-1]
        avg_vol   = df["Volume"].iloc[:-1].mean()
        if avg_vol <= 0 or today_vol < avg_vol * 1.1:
            return None
        ticker = ticker_yf.replace(".TA", "")
        return Signal(
            ticker       = ticker,
            ticker_yf    = ticker_yf,
            company_name = ticker,
            signal_type  = "low_reversal",
            headline     = f"52w low reversal: {today_price:.2f} ({pct_from_low:+.1f}% from yearly low) -- vol {today_vol/avg_vol:.1f}x",
            detail       = f"52w low: {low_52w:.2f} | Today: {today_price:.2f} | Vol ratio: {today_vol/avg_vol:.1f}x | Bounce from key support",
            url          = f"https://finance.yahoo.com/quote/{ticker_yf}",
            timestamp    = now_iso(),
        )

    def _consecutive_momentum_signal(self, ticker_yf: str, df: pd.DataFrame) -> Optional[Signal]:
        """
        Consecutive momentum: 4+ up sessions with above-average volume majority.

        Real-analyst rationale: On TASE, institutional buying is gradual — funds
        accumulate over multiple sessions to avoid moving the price. Four consecutive
        higher closes with rising volume is the footprint of a large buyer working
        an order. Small/mid-cap TASE stocks often trend for 2-3 weeks once this
        pattern establishes.
        """
        if len(df) < 6:
            return None
        closes  = df["Close"]
        vols    = df["Volume"]
        avg_vol = vols.iloc[:-4].mean() if len(df) > 5 else vols.mean()
        if avg_vol <= 0:
            return None
        # Count consecutive up days from today backwards
        consecutive = 0
        for i in range(-1, -6, -1):
            try:
                if closes.iloc[i] > closes.iloc[i - 1]:
                    consecutive += 1
                else:
                    break
            except IndexError:
                break
        if consecutive < 4:
            return None
        above_avg = sum(1 for i in range(-4, 0) if vols.iloc[i] > avg_vol)
        if above_avg < 2:
            return None
        total_move = (closes.iloc[-1] / closes.iloc[-5] - 1) * 100
        ticker = ticker_yf.replace(".TA", "")
        return Signal(
            ticker       = ticker,
            ticker_yf    = ticker_yf,
            company_name = ticker,
            signal_type  = "consecutive_momentum",
            headline     = f"Consecutive momentum: {consecutive} up days, {total_move:+.1f}% over 4 sessions",
            detail       = f"4-session return: {total_move:+.1f}% | Above-avg volume days: {above_avg}/4 | Sustained institutional buying",
            url          = f"https://finance.yahoo.com/quote/{ticker_yf}",
            timestamp    = now_iso(),
        )

    def _relative_strength_signal(self, ticker_yf: str, df: pd.DataFrame) -> Optional[Signal]:
        """
        Relative strength leader: stock outperforming TA-125 by 5%+ over 20 days.

        Real-analyst rationale: In any market environment, a small number of stocks
        lead the tape. Stocks that outperform their benchmark during weakness are being
        accumulated by informed money. During rallies, RS leaders compound gains faster.
        This is how Livermore/O'Neil identified winners — relative strength first.
        Uses ^TA125.TA as the benchmark (TA-35 not available on Yahoo Finance).
        """
        if len(df) < 21:
            return None
        stock_ret = (df["Close"].iloc[-1] / df["Close"].iloc[-21] - 1) * 100
        if stock_ret <= 0:
            return None
        try:
            bm_df = yf.Ticker("^TA125.TA").history(period="25d", interval="1d")
            if len(bm_df) < 21:
                return None
            bm_ret = (bm_df["Close"].iloc[-1] / bm_df["Close"].iloc[-21] - 1) * 100
        except Exception:
            return None
        excess = stock_ret - bm_ret
        if excess < 5.0:
            return None
        ticker = ticker_yf.replace(".TA", "")
        return Signal(
            ticker       = ticker,
            ticker_yf    = ticker_yf,
            company_name = ticker,
            signal_type  = "relative_strength",
            headline     = f"RS leader: +{stock_ret:.1f}% vs TA-125 +{bm_ret:.1f}% (excess {excess:+.1f}%) over 20d",
            detail       = f"Stock 20d return: {stock_ret:+.1f}% | TA-125 20d return: {bm_ret:+.1f}% | Relative outperformance: {excess:+.1f}%",
            url          = f"https://finance.yahoo.com/quote/{ticker_yf}",
            timestamp    = now_iso(),
        )

    def scan_universe(
        self,
        sample_size:      int = ANOMALY_SAMPLE_SIZE,
        priority_tickers: list[str] | None = None,
    ) -> list[Signal]:
        priority     = [t for t in (priority_tickers or []) if t in self.tickers_yf]
        priority_set = set(priority)
        remaining    = [t for t in self.tickers_yf if t not in priority_set]
        fill         = random.sample(remaining, min(max(sample_size - len(priority), 0), len(remaining)))
        sample       = priority + fill

        signals: list[Signal] = []
        for t in sample:
            try:
                df = self._history(t)
                for detector in (
                    self._volume_spike,
                    self._price_move,
                    self._breakout_signal,
                    self._oversold_bounce_signal,
                    self._low_reversal_signal,
                    self._consecutive_momentum_signal,
                    self._relative_strength_signal,
                ):
                    sig = detector(t, df)
                    if sig:
                        signals.append(sig)
                # MA crossover only for priority tickers (extra fetch required)
                if t in priority_set:
                    sig = self._ma_crossover_signal(t)
                    if sig:
                        signals.append(sig)
            except Exception:
                pass
            time.sleep(0.15)
        return signals


class DualListedMonitor:
    """
    Monitors US-listed Israeli stocks for significant overnight price moves.

    Real-analyst rationale: Israeli dual-listed stocks (TEVA, Check Point, NICE, etc.)
    trade in both New York and Tel Aviv. When the US session closes with a big move,
    the TASE open will follow — creating a predictable arbitrage window. A +5% Nasdaq
    move in CHKP tonight is a near-certain signal that CHKP.TA opens higher tomorrow.
    This is one of the most reliable leading indicators for TASE blue chips.
    """

    MOVE_THRESHOLD = 2.0   # % move on US market to generate a signal

    def get_signals(self, dual_listed: dict[str, str] | None = None) -> list[Signal]:
        """
        dual_listed: {us_ticker: ta_ticker} — defaults to DUAL_LISTED_STOCKS from config.
        Returns a Signal for each stock where the US session moved >= MOVE_THRESHOLD %.
        """
        stocks  = dual_listed or DUAL_LISTED_STOCKS
        signals: list[Signal] = []

        for us_ticker, ta_ticker in stocks.items():
            try:
                df = yf.Ticker(us_ticker).history(period="5d", interval="1d")
                if len(df) < 2:
                    continue
                prev = df["Close"].iloc[-2]
                last = df["Close"].iloc[-1]
                if prev <= 0:
                    continue
                pct = (last - prev) / prev * 100
                if abs(pct) < self.MOVE_THRESHOLD:
                    continue
                ta_tkr    = ta_ticker.replace(".TA", "")
                direction = "rallied" if pct > 0 else "fell"
                signals.append(Signal(
                    ticker       = ta_tkr,
                    ticker_yf    = ta_ticker,
                    company_name = us_ticker,
                    signal_type  = "dual_listed_move",
                    headline     = f"{us_ticker} {direction} {pct:+.1f}% on US market -> TASE impact expected",
                    detail       = f"US close: ${last:.2f} (prev: ${prev:.2f}) | Move: {pct:+.1f}%",
                    url          = f"https://finance.yahoo.com/quote/{us_ticker}",
                    timestamp    = now_iso(),
                ))
            except Exception:
                pass
            time.sleep(0.1)

        return signals


class SectorSignalDetector:
    """
    Fires sector-specific macro-driven signals based on sector-level catalysts.

    Rather than analysing individual stock technicals, these signals fire when
    a sector-level catalyst occurs:
      - Oil/gas price move -> energy stocks
      - Shekel depreciation -> exporters (tech/defense/pharma)
      - Shekel appreciation -> importers (consumer/retail)
      - VIX spike (>22)    -> defense sector tailwind
      - US biotech (XBI) move -> Israeli pharma/biotech sympathy
      - US bank index (KBE) move -> Israeli bank sympathy
    """

    # Energy: most sensitive to oil price changes
    ENERGY_OIL = [
        "NWMD.TA", "DLEKG.TA", "ORL.TA", "NVPT.TA", "RATI.TA",
        "PAZ.TA", "OPCE.TA", "ENRG.TA", "ENLT.TA",
    ]

    # Exporters: benefit from weaker shekel (USD/ILS rises)
    # Tech, defense, pharma, chemicals — USD/foreign-currency revenue companies
    SHEKEL_EXPORTERS = [
        "ESLT.TA", "NICE.TA", "NVMI.TA", "TSEM.TA", "CAMT.TA",
        "TEVA.TA", "AUDC.TA", "ALLT.TA", "KMDA.TA", "ICL.TA",
        "MTRX.TA", "NXSN.TA", "HLAN.TA", "FORTY.TA",
        "CGEN.TA", "EVGN.TA", "BRND.TA",
    ]

    # Importers: benefit from stronger shekel (USD/ILS falls)
    # Retail, food manufacturers — buy goods in USD, sell in ILS
    SHEKEL_IMPORTERS = [
        "SAE.TA", "STRS.TA", "RMLI.TA", "ELCO.TA",
        "FTAL.TA",   # Fattal Hotels — USD-denominated travel costs
        "HOT.TA",    # HOT — infrastructure imports
    ]

    # Defense: benefit from geopolitical tension (high VIX / security escalation)
    DEFENSE = [
        "ESLT.TA", "NXSN.TA", "CAMT.TA", "NVMI.TA", "TSEM.TA",
        "HLAN.TA", "FORTY.TA", "MLTM.TA",
    ]

    # Pharma/biotech: follow US biotech index (XBI)
    PHARMA = [
        "TEVA.TA", "KMDA.TA", "CGEN.TA", "EVGN.TA", "ICL.TA",
        "BRND.TA", "BWAY.TA",
    ]

    # Banks: follow US bank index (KBE) for sentiment
    BANKS = [
        "LUMI.TA", "POLI.TA", "MZTF.TA", "DSCT.TA", "FIBI.TA",
        "JBNK.TA",
    ]

    OIL_THRESHOLD    = 2.0   # % oil move to trigger
    SHEKEL_THRESHOLD = 1.5   # % USD/ILS move to trigger
    VIX_TENSION      = 22    # VIX level = geopolitical tension mode
    PHARMA_THRESHOLD = 3.0   # % XBI move to trigger
    BANK_THRESHOLD   = 2.5   # % KBE move to trigger

    def get_all_signals(self) -> list[Signal]:
        signals: list[Signal] = []
        for method in (
            self._energy_oil_signals,
            self._shekel_signals,
            self._defense_vix_signals,
            self._pharma_peer_signals,
            self._bank_peer_signals,
        ):
            try:
                signals.extend(method())
            except Exception:
                pass
        return signals

    def _energy_oil_signals(self) -> list[Signal]:
        """Oil price move >2% -> flag all correlated Israeli energy tickers."""
        oil_df = yf.Ticker("CL=F").history(period="5d", interval="1d")
        if len(oil_df) < 2:
            return []
        prev = oil_df["Close"].iloc[-2]
        last = oil_df["Close"].iloc[-1]
        if prev <= 0:
            return []
        oil_pct = (last - prev) / prev * 100
        if abs(oil_pct) < self.OIL_THRESHOLD:
            return []
        direction = "rose" if oil_pct > 0 else "fell"
        impact    = "positive" if oil_pct > 0 else "negative"
        signals: list[Signal] = []
        for tkr in self.ENERGY_OIL:
            ticker = tkr.replace(".TA", "")
            signals.append(Signal(
                ticker       = ticker,
                ticker_yf    = tkr,
                company_name = ticker,
                signal_type  = "oil_correlation",
                headline     = f"Oil {direction} {oil_pct:+.1f}% -> {impact} for Israeli energy stocks",
                detail       = f"WTI crude: ${last:.2f} (prev: ${prev:.2f}) | Sector catalyst: {impact}",
                url          = f"https://finance.yahoo.com/quote/{tkr}",
                timestamp    = now_iso(),
            ))
            time.sleep(0.05)
        return signals

    def _shekel_signals(self) -> list[Signal]:
        """USD/ILS move >1.5% -> exporters (weakening) or importers (strengthening)."""
        fx_df = yf.Ticker("ILS=X").history(period="5d", interval="1d")
        if len(fx_df) < 2:
            return []
        prev = fx_df["Close"].iloc[-2]
        last = fx_df["Close"].iloc[-1]
        if prev <= 0:
            return []
        fx_pct = (last - prev) / prev * 100
        if abs(fx_pct) < self.SHEKEL_THRESHOLD:
            return []
        signals: list[Signal] = []
        if fx_pct > 0:
            # Shekel weakening -> exporters benefit (their foreign revenue is worth more in ILS)
            for tkr in self.SHEKEL_EXPORTERS:
                ticker = tkr.replace(".TA", "")
                signals.append(Signal(
                    ticker       = ticker,
                    ticker_yf    = tkr,
                    company_name = ticker,
                    signal_type  = "shekel_move",
                    headline     = f"Shekel weakened {fx_pct:+.1f}% (USD/ILS {last:.3f}) -> export revenue tailwind",
                    detail       = f"USD/ILS: {last:.3f} (prev: {prev:.3f}) | Shekel -{ fx_pct:.1f}% | USD-denominated revenue boost for exporters",
                    url          = f"https://finance.yahoo.com/quote/{tkr}",
                    timestamp    = now_iso(),
                ))
        else:
            # Shekel strengthening -> importers benefit (cheaper imported goods)
            for tkr in self.SHEKEL_IMPORTERS:
                ticker = tkr.replace(".TA", "")
                signals.append(Signal(
                    ticker       = ticker,
                    ticker_yf    = tkr,
                    company_name = ticker,
                    signal_type  = "shekel_move",
                    headline     = f"Shekel strengthened {fx_pct:.1f}% (USD/ILS {last:.3f}) -> import cost reduction",
                    detail       = f"USD/ILS: {last:.3f} (prev: {prev:.3f}) | Shekel +{abs(fx_pct):.1f}% | Import cost savings for consumer/retail",
                    url          = f"https://finance.yahoo.com/quote/{tkr}",
                    timestamp    = now_iso(),
                ))
        time.sleep(0.1)
        return signals

    def _defense_vix_signals(self) -> list[Signal]:
        """VIX > 22 -> defense sector benefits from geopolitical tension premium."""
        vix_df = yf.Ticker("^VIX").history(period="3d", interval="1d")
        if len(vix_df) < 1:
            return []
        vix = vix_df["Close"].iloc[-1]
        if vix < self.VIX_TENSION:
            return []
        signals: list[Signal] = []
        for tkr in self.DEFENSE:
            ticker = tkr.replace(".TA", "")
            signals.append(Signal(
                ticker       = ticker,
                ticker_yf    = tkr,
                company_name = ticker,
                signal_type  = "defense_tailwind",
                headline     = f"VIX at {vix:.1f} (tension mode) -> Israeli defense/tech sector tailwind",
                detail       = f"VIX: {vix:.1f} (>={self.VIX_TENSION} = geopolitical tension) | Defense budget demand rising historically above this level",
                url          = f"https://finance.yahoo.com/quote/{tkr}",
                timestamp    = now_iso(),
            ))
        time.sleep(0.1)
        return signals

    def _pharma_peer_signals(self) -> list[Signal]:
        """US biotech index (XBI) moves >3% -> Israeli pharma sympathy move."""
        xbi_df = yf.Ticker("XBI").history(period="5d", interval="1d")
        if len(xbi_df) < 2:
            return []
        prev = xbi_df["Close"].iloc[-2]
        last = xbi_df["Close"].iloc[-1]
        if prev <= 0:
            return []
        xbi_pct = (last - prev) / prev * 100
        if abs(xbi_pct) < self.PHARMA_THRESHOLD:
            return []
        direction = "rallied" if xbi_pct > 0 else "fell"
        signals: list[Signal] = []
        for tkr in self.PHARMA:
            ticker = tkr.replace(".TA", "")
            signals.append(Signal(
                ticker       = ticker,
                ticker_yf    = tkr,
                company_name = ticker,
                signal_type  = "sector_peer_move",
                headline     = f"US Biotech (XBI) {direction} {xbi_pct:+.1f}% -> Israeli pharma sector sympathy",
                detail       = f"XBI: ${last:.2f} ({xbi_pct:+.1f}%) | Global biotech sentiment shift -> TASE pharma follow-through expected",
                url          = f"https://finance.yahoo.com/quote/{tkr}",
                timestamp    = now_iso(),
            ))
        time.sleep(0.1)
        return signals

    def _bank_peer_signals(self) -> list[Signal]:
        """US bank index (KBE) moves >2.5% -> Israeli bank sector sympathy."""
        kbe_df = yf.Ticker("KBE").history(period="5d", interval="1d")
        if len(kbe_df) < 2:
            return []
        prev = kbe_df["Close"].iloc[-2]
        last = kbe_df["Close"].iloc[-1]
        if prev <= 0:
            return []
        kbe_pct = (last - prev) / prev * 100
        if abs(kbe_pct) < self.BANK_THRESHOLD:
            return []
        direction = "rallied" if kbe_pct > 0 else "fell"
        signals: list[Signal] = []
        for tkr in self.BANKS:
            ticker = tkr.replace(".TA", "")
            signals.append(Signal(
                ticker       = ticker,
                ticker_yf    = tkr,
                company_name = ticker,
                signal_type  = "sector_peer_move",
                headline     = f"US Bank index (KBE) {direction} {kbe_pct:+.1f}% -> Israeli bank sector sympathy",
                detail       = f"KBE: ${last:.2f} ({kbe_pct:+.1f}%) | Global bank sentiment shift -> TASE banks follow-through expected",
                url          = f"https://finance.yahoo.com/quote/{tkr}",
                timestamp    = now_iso(),
            ))
        time.sleep(0.1)
        return signals


class SectorAnalyzer:
    """
    Computes sector-level trend summary for LLM context.

    Fetches 21-day history for a sample of TASE tickers, groups by sector,
    and returns a compact string describing which sectors are leading/lagging.
    This gives the LLM the broader sector rotation context it needs to weigh
    individual signals: a bullish signal in a bearish sector is weaker; a
    bullish signal in a leading sector deserves higher conviction.
    """

    # Representative tickers per sector (subset for speed — 2-3 per sector)
    SECTOR_SAMPLES = {
        "Banks":       ["LUMI.TA", "POLI.TA", "MZTF.TA"],
        "Insurance":   ["PHOE.TA", "HARL.TA"],
        "RealEstate":  ["AZRG.TA", "AMOT.TA", "MLSR.TA"],
        "TechDefense": ["ESLT.TA", "NICE.TA", "TSEM.TA"],
        "Energy":      ["DLEKG.TA", "NWMD.TA", "ENLT.TA"],
        "Pharma":      ["TEVA.TA", "ICL.TA"],
        "Telecom":     ["BEZQ.TA", "PTNR.TA"],
        "Consumer":    ["SAE.TA", "STRS.TA"],
        "Finance":     ["ISCD.TA", "ILCO.TA"],
    }

    def get_sector_context(self) -> str:
        """
        Returns a multi-line string like:
          TechDefense: BULL+ | avg RSI 68 | 1M +8.4%
          Banks:       BEAR- | avg RSI 26 | 1M -5.2%
          ...
        Ordered from strongest to weakest.
        """
        sector_stats: list[tuple[str, str, float, float]] = []

        for sector, tickers in self.SECTOR_SAMPLES.items():
            returns: list[float] = []
            rsis:    list[float] = []
            for tkr in tickers:
                try:
                    df = yf.Ticker(tkr).history(period="25d", interval="1d")
                    if len(df) < 20:
                        continue
                    ret = (df["Close"].iloc[-1] / df["Close"].iloc[-21] - 1) * 100
                    returns.append(ret)
                    rsi = _calc_rsi(df["Close"], 14)
                    if rsi is not None:
                        rsis.append(rsi)
                except Exception:
                    pass
                time.sleep(0.1)
            if not returns:
                continue
            avg_ret = sum(returns) / len(returns)
            avg_rsi = sum(rsis) / len(rsis) if rsis else 50.0
            # Bull/bear label: >+2% and RSI>50 = BULL+; <-2% and RSI<45 = BEAR-; else NEUTRAL
            if avg_ret > 2.0 and avg_rsi > 50:
                label = "BULL+"
            elif avg_ret < -2.0 and avg_rsi < 45:
                label = "BEAR-"
            elif avg_ret > 1.0:
                label = "BULL"
            elif avg_ret < -1.0:
                label = "BEAR"
            else:
                label = "NEUTRAL"
            sector_stats.append((sector, label, avg_ret, avg_rsi))

        # Sort by 1M return descending
        sector_stats.sort(key=lambda x: x[2], reverse=True)

        lines = []
        for sector, label, ret, rsi in sector_stats:
            sign = "+" if ret >= 0 else ""
            lines.append(f"  {sector:<12} {label:<8} | avg RSI {rsi:.0f} | 1M {sign}{ret:.1f}%")

        return "Sector rotation (TASE):\n" + "\n".join(lines) if lines else "Sector data unavailable."


class MacroContext:
    """Fetches a global macro snapshot to include in the weekly report."""

    def get(self) -> str:
        lines = []
        for label, ticker in MACRO_TICKERS.items():
            try:
                df = yf.Ticker(ticker).history(period="5d", interval="1d")
                if len(df) < 2:
                    continue
                prev = df["Close"].iloc[-2]
                last = df["Close"].iloc[-1]
                pct  = (last - prev) / prev * 100 if prev > 0 else 0
                sign = "+" if pct >= 0 else ""
                lines.append(f"{label}: {last:.2f}  ({sign}{pct:.1f}% today)")
            except Exception:
                pass
        return "\n".join(lines) if lines else "Macro data unavailable."


class DeepStockAnalyzer:
    """Fetches financial ratios + technicals for the weekly top candidates."""

    def analyze(self, ticker_yf: str) -> dict:
        out = {"ticker": ticker_yf}
        try:
            tk   = yf.Ticker(ticker_yf)
            info = tk.fast_info
            out["market_cap"] = getattr(info, "market_cap",   None)
            out["last_price"] = getattr(info, "last_price",   None)
            out["52w_high"]   = getattr(info, "fifty_two_week_high", None)
            out["52w_low"]    = getattr(info, "fifty_two_week_low",  None)
            out["avg_volume"] = getattr(info, "three_month_average_volume", None)

            df = tk.history(period="3mo", interval="1d")
            if len(df) > 20:
                close                  = df["Close"]
                out["rsi_14"]          = _calc_rsi(close, 14)
                out["ma_20"]           = round(close.rolling(20).mean().iloc[-1], 2)
                out["ma_50"]           = round(close.rolling(50).mean().iloc[-1], 2) if len(df) >= 50 else None
                out["pct_vs_52w_high"] = (
                    round((close.iloc[-1] / out["52w_high"] - 1) * 100, 1)
                    if out["52w_high"] else None
                )
                # MA trend direction — useful for LLM context
                if out.get("ma_20") and out.get("ma_50"):
                    out["ma_trend"] = "bullish" if out["ma_20"] > out["ma_50"] else "bearish"
                # Day change: live price vs last session close (or last two closes)
                if len(df) >= 2:
                    prev      = float(close.iloc[-2])
                    last_sess = float(close.iloc[-1])
                    live      = out.get("last_price") or last_sess
                    if prev > 0:
                        # If live price differs from last close → market open (intraday)
                        if last_sess > 0 and abs(live - last_sess) / last_sess > 0.001:
                            out["today_change_pct"] = round((live / last_sess - 1) * 100, 2)
                        else:
                            out["today_change_pct"] = round((last_sess / prev - 1) * 100, 2)

            try:
                fin = tk.income_stmt
                if fin is not None and not fin.empty:
                    rev_row = fin.loc["Total Revenue"] if "Total Revenue" in fin.index else None
                    if rev_row is not None and len(rev_row) >= 2:
                        rev_growth = (rev_row.iloc[0] - rev_row.iloc[1]) / abs(rev_row.iloc[1]) * 100
                        out["revenue_growth_pct"] = round(rev_growth, 1)
                    # Also capture net income growth
                    ni_row = fin.loc["Net Income"] if "Net Income" in fin.index else None
                    if ni_row is not None and len(ni_row) >= 2 and ni_row.iloc[1] != 0:
                        ni_growth = (ni_row.iloc[0] - ni_row.iloc[1]) / abs(ni_row.iloc[1]) * 100
                        out["net_income_growth_pct"] = round(ni_growth, 1)
            except Exception:
                pass
        except Exception as e:
            out["error"] = str(e)
        return out


class DynamicUniverseBuilder:
    """
    Expands the scan universe beyond hardcoded sector tickers by validating
    all TLV-listed equities (fetched from Yahoo Finance Screener) against
    Yahoo Finance live data.

    Universe source: Yahoo Finance Screener for exchange=TLV (refreshed daily).
    Validation cache: persistent in state JSON, per-ticker TTL.
    Priority symbols (from Maya filings or resolved IPO tickers) are validated first.

    Throttle: at most _MAX_NEW_VALIDATIONS per cycle to avoid rate-limiting.
    Valid tickers are rechecked every 30 days; invalid ones every 7 days.
    """

    _MAX_NEW_VALIDATIONS = 50   # raised from 25 to speed up initial cache population
    _VALID_TTL_DAYS      = 30   # recheck valid tickers monthly
    _INVALID_TTL_DAYS    = 7    # recheck invalid tickers weekly
    _UNIVERSE_TTL_HOURS  = 24   # refresh full TLV stock list once per day

    def __init__(self, state: dict):
        self._state = state
        self._cache: dict = state.setdefault("ticker_validation_cache", {})
        self._clean_pseudo_ticker_pollution()

    def _clean_pseudo_ticker_pollution(self) -> None:
        """Remove stale TASE{digits}.TA entries that were cached by old code versions."""
        import re
        stale = [k for k in self._cache if re.match(r"^TASE\d+\.TA$", k)]
        for k in stale:
            del self._cache[k]
        if stale:
            print(f"[Universe] Cleaned {len(stale)} stale pseudo-ticker cache entries.")

    def _fetch_tase_universe(self) -> list[str]:
        """
        Fetch all TLV-listed equity tickers from Yahoo Finance Screener.
        Cached in state["tase_universe_cache"] for 24h to avoid redundant calls.
        Falls back to TASE_MAJOR_TICKERS hardcoded list if screener is unavailable.

        yfinance 1.2.0 API: `from yfinance.screener import screen, EquityQuery`
        Exchange code for TASE (Tel Aviv) is 'TLV' (country key 'il').
        Do NOT pass sortField — it causes HTTP 400 in this version.
        """
        from datetime import datetime as _dt
        cache = self._state.setdefault("tase_universe_cache", {"fetched_at": "", "tickers": []})
        fetched_at = cache.get("fetched_at", "")
        if fetched_at:
            try:
                age_hours = (_dt.now() - _dt.fromisoformat(fetched_at)).total_seconds() / 3600
                if age_hours < self._UNIVERSE_TTL_HOURS and cache.get("tickers"):
                    return cache["tickers"]
            except Exception:
                pass

        tickers: list[str] = []
        try:
            from yfinance.screener import screen, EquityQuery
            query  = EquityQuery("eq", ["exchange", "TLV"])
            offset = 0
            while True:
                response = screen(query, size=250, offset=offset)
                quotes   = response.get("quotes", [])
                for q in quotes:
                    sym = q.get("symbol", "")
                    if sym.endswith(".TA"):
                        tickers.append(sym)
                total = response.get("total", 0)
                offset += len(quotes)
                if not quotes or offset >= total:
                    break
                time.sleep(0.3)
            print(f"[Universe] Yahoo Finance Screener: {len(tickers)} TLV tickers fetched.")
        except Exception as exc:
            print(f"[Universe] Screener unavailable ({exc}); falling back to TASE_MAJOR_TICKERS.")

        if not tickers:
            # Fallback: use the curated major ticker list so DiscoveryAgent isn't empty
            tickers = list(TASE_MAJOR_TICKERS)
            print(f"[Universe] Fallback: {len(tickers)} tickers from TASE_MAJOR_TICKERS.")

        if tickers:
            cache["fetched_at"] = _dt.now().isoformat()
            cache["tickers"]    = tickers
        return tickers

    def get_uncovered_tickers(
        self,
        companies:        list[dict],
        covered_set:      set[str],
        priority_symbols: set[str] | None = None,
    ) -> list[str]:
        """
        Return all Yahoo-Finance-valid .TA tickers from the full TLV universe
        that are not already in covered_set (i.e. not handled by sector agents).

        companies        — Maya company list (used only for legacy compat, ignored for ticker source)
        covered_set      — set of .TA tickers already handled by sector agents
        priority_symbols — full .TA tickers to validate first (IPO resolved tickers, filing tickers)
        """
        from datetime import datetime as _dt
        today_str = _dt.now().strftime("%Y-%m-%d")

        # Source: Yahoo Finance Screener (replaces Maya company cache which has no real tickers)
        universe = self._fetch_tase_universe()
        if not universe:
            return []

        # Normalize priority_symbols: accept both bare ("TEVA") and full ("TEVA.TA") forms
        priority_set: set[str] = set()
        for s in (priority_symbols or set()):
            priority_set.add(s if s.endswith(".TA") else f"{s}.TA")
        seen: set[str] = set()
        priority_ordered: list[str] = []
        rest_ordered:     list[str] = []

        for ticker_yf in universe:
            if ticker_yf in covered_set or ticker_yf in seen:
                continue
            seen.add(ticker_yf)
            if ticker_yf in priority_set:
                priority_ordered.append(ticker_yf)
            else:
                rest_ordered.append(ticker_yf)

        ordered = priority_ordered + rest_ordered

        valid_results: list[str] = []
        to_validate:   list[str] = []

        for ticker_yf in ordered:
            entry = self._cache.get(ticker_yf)
            if entry:
                is_valid = entry.get("valid", False)
                try:
                    age = (_dt.now() - _dt.strptime(entry["checked"], "%Y-%m-%d")).days
                except Exception:
                    age = 999
                ttl = self._VALID_TTL_DAYS if is_valid else self._INVALID_TTL_DAYS
                if age < ttl:
                    if is_valid:
                        valid_results.append(ticker_yf)
                    continue   # no re-validation needed
            to_validate.append(ticker_yf)

        # Validate up to _MAX_NEW_VALIDATIONS new tickers (priority-first order preserved)
        validated = 0
        deferred  = 0
        for ticker_yf in to_validate:
            if validated >= self._MAX_NEW_VALIDATIONS:
                deferred += 1
                continue
            is_valid = self._check_ticker(ticker_yf)
            self._cache[ticker_yf] = {"valid": is_valid, "checked": today_str}
            if is_valid:
                valid_results.append(ticker_yf)
            validated += 1
            time.sleep(0.15)

        print(
            f"[Universe] {len(valid_results)} valid uncovered tickers "
            f"({validated} newly validated, {deferred} deferred to next cycle)."
        )
        return valid_results

    @staticmethod
    def _check_ticker(ticker_yf: str) -> bool:
        """Quick Yahoo Finance liveness check — fast_info only, no history."""
        try:
            price = yf.Ticker(ticker_yf).fast_info.last_price
            return price is not None and price > 0
        except Exception:
            return False


class TASEMarketScraper:
    """
    Scrapes the complete TASE stock list from market.tase.co.il using Playwright.

    Returns all 548 listed stocks with Hebrew company names and TASE security numbers.
    Uses the existing Maya Playwright browser context (same session) to avoid
    spinning up a second browser.

    Cached in state["tase_market_cache"] for 24 hours.

    Why this matters:
      - Maya autocomplete covers company names via prefix sweep — may miss some
      - TASE market website is the authoritative list of ALL listed securities
      - Hebrew names from here → added to company_map → better news-article matching
      - Security numbers → TASE{secNum} pseudo-tickers that can carry news signals
    """

    _URL       = "https://market.tase.co.il/he/market_data/securities/data/all?dType=1&cl1=1&cl2=0"
    _TTL_HOURS = 24

    def __init__(self, state: dict, playwright_context=None):
        self._state   = state
        self._context = playwright_context  # shared Playwright browser context from Maya

    # ── Public ───────────────────────────────────────────────────────────────

    def get_stocks(self) -> list[dict]:
        """
        Return cached TASE stock list or scrape fresh from market.tase.co.il.
        Each item: {name, symbol (Hebrew), secNum, type}
        """
        from datetime import datetime as _dt
        cache = self._state.setdefault("tase_market_cache", {"fetched_at": "", "stocks": []})
        fetched_at = cache.get("fetched_at", "")
        if fetched_at and cache.get("stocks"):
            try:
                age_h = (_dt.now() - _dt.fromisoformat(fetched_at)).total_seconds() / 3600
                if age_h < self._TTL_HOURS:
                    print(f"[TASE] Using cached stock list ({len(cache['stocks'])} stocks).")
                    return cache["stocks"]
            except Exception:
                pass

        stocks = self._fetch()
        if stocks:
            from datetime import datetime as _dt2
            cache["fetched_at"] = _dt2.now().isoformat()
            cache["stocks"]     = stocks
        return stocks

    def build_company_map_supplement(self, stocks: list[dict]) -> dict[str, str]:
        """
        Build a Hebrew-name → pseudo-ticker supplement for the news company_map.
        Maps Hebrew company names (lowercase) to TASE{secNum} pseudo-tickers.

        Also strips common Hebrew corporate suffixes (ע"ש, בע"מ, parenthetical year)
        to maximise name-matching recall against news headlines.
        """
        import re as _re
        result: dict[str, str] = {}
        for s in stocks:
            name    = s.get("name", "").strip()
            sec_num = s.get("secNum", "").strip()
            if not name or not sec_num:
                continue
            pseudo = f"TASE{sec_num}"
            result[name.lower()] = pseudo
            # Also add version without suffixes like ע"ש / ע''ש / בע"מ / (1988)
            clean = _re.sub(
                r"\s*(ע[\"']+ש|בע[\"']+מ|בע\"מ|\(\d{4}\))\s*", " ", name
            ).strip()
            if clean and clean.lower() != name.lower() and len(clean) >= 4:
                result[clean.lower()] = pseudo
        return result

    # ── Private ──────────────────────────────────────────────────────────────

    def _fetch(self) -> list[dict]:
        """
        Scrape all pages of the TASE stock list via Playwright pagination.
        Uses the shared browser context; creates a new page and closes it when done.
        """
        if not self._context:
            print("[TASE] No Playwright context available — skipping market website scrape.")
            return []

        stocks: dict[str, dict] = {}
        page = None
        try:
            page = self._context.new_page()
            page.goto(self._URL, wait_until="networkidle", timeout=30000)
            time.sleep(2)

            page_num = 1
            while True:
                rows = page.query_selector_all("table tbody tr")
                for row in rows:
                    cells = [
                        td.inner_text().strip().replace("\n", " ").replace("\r", "")
                        for td in row.query_selector_all("td")
                    ]
                    if len(cells) >= 4 and cells[1]:
                        sym = cells[1].strip()
                        stocks[sym] = {
                            "name":   cells[0].strip(),
                            "symbol": sym,
                            "secNum": cells[2].strip(),
                            "type":   cells[3].strip(),
                        }

                next_btn = page.query_selector(".pagination-next:not(.disabled) a")
                if not next_btn:
                    break
                next_btn.click()
                time.sleep(1.0)
                page_num += 1

            print(f"[TASE] Scraped {len(stocks)} stocks from market.tase.co.il ({page_num} pages).")
        except Exception as exc:
            print(f"[TASE] market.tase.co.il scrape error: {exc}")
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass

        return list(stocks.values())


def _calc_rsi(close: pd.Series, period: int = 14) -> Optional[float]:
    try:
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(period).mean()
        loss  = (-delta.clip(upper=0)).rolling(period).mean()
        rs    = gain / loss
        rsi   = 100 - (100 / (1 + rs))
        return round(rsi.iloc[-1], 1)
    except Exception:
        return None
