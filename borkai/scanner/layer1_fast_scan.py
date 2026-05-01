"""
Layer 1: Fast Market Scan
=========================

Scans the entire TASE universe using batched yfinance calls.
No AI, no HTTP requests beyond yfinance. Runs in 30-90 seconds for 100 stocks.

Signals scored (0-10 total):
  price_score      (0-3)  Absolute intraday/daily price move
  volume_score     (0-3)  Volume vs 20-day average
  momentum_score   (0-2)  5-day price momentum
  gap_score        (0-1)  Gap open vs prior close
  volatility_score (0-1)  Recent realized vol spike vs 20D baseline

Output: List[Layer1Result] sorted by total_score descending.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict

import yfinance as yf
import pandas as pd


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Layer1Result:
    ticker: str
    name: str
    sector: str
    market_cap_bucket: str = ""

    # Raw metrics
    current_price: Optional[float] = None
    price_change_1d: Optional[float] = None   # % (daily close-to-close)
    price_change_3d: Optional[float] = None   # %
    price_change_5d: Optional[float] = None   # %
    price_change_7d: Optional[float] = None   # %
    volume_today: Optional[float] = None      # shares (most recent session)
    volume_avg_20d: Optional[float] = None    # 20-day avg volume
    volume_ratio: Optional[float] = None      # today / 20d avg
    gap_pct: Optional[float] = None           # (open - prev_close) / prev_close * 100
    volatility_5d: Optional[float] = None     # annualised realised vol (5D window)
    volatility_20d: Optional[float] = None    # annualised realised vol (20D baseline)

    # Component scores
    price_score: int = 0       # 0-3
    volume_score: int = 0      # 0-3
    momentum_score: int = 0    # 0-2
    gap_score: int = 0         # 0-1
    volatility_score: int = 0  # 0-1
    total_score: int = 0       # 0-10

    # Human-readable signals detected
    signals: List[str] = field(default_factory=list)

    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _price_score(pct: Optional[float]) -> tuple[int, Optional[str]]:
    if pct is None:
        return 0, None
    a = abs(pct)
    direction = "up" if pct > 0 else "down"
    if a >= 5.0:
        return 3, f"{pct:+.1f}% price move ({direction})"
    if a >= 3.0:
        return 2, f"{pct:+.1f}% price move ({direction})"
    if a >= 1.5:
        return 1, f"{pct:+.1f}% price move ({direction})"
    return 0, None


def _volume_score(ratio: Optional[float]) -> tuple[int, Optional[str]]:
    if ratio is None:
        return 0, None
    if ratio >= 3.0:
        return 3, f"{ratio:.1f}x volume spike"
    if ratio >= 2.0:
        return 2, f"{ratio:.1f}x volume (above avg)"
    if ratio >= 1.5:
        return 1, f"{ratio:.1f}x volume (elevated)"
    return 0, None


def _momentum_score(pct_5d: Optional[float]) -> tuple[int, Optional[str]]:
    if pct_5d is None:
        return 0, None
    a = abs(pct_5d)
    direction = "up" if pct_5d > 0 else "down"
    if a >= 8.0:
        return 2, f"Strong 5D momentum {pct_5d:+.1f}% ({direction})"
    if a >= 4.0:
        return 1, f"5D momentum {pct_5d:+.1f}% ({direction})"
    return 0, None


def _gap_score(gap: Optional[float]) -> tuple[int, Optional[str]]:
    if gap is None:
        return 0, None
    if abs(gap) >= 2.0:
        direction = "gap-up" if gap > 0 else "gap-down"
        return 1, f"{direction} {gap:+.1f}%"
    return 0, None


def _volatility_score(vol5: Optional[float], vol20: Optional[float]) -> tuple[int, Optional[str]]:
    if vol5 is None or vol20 is None or vol20 == 0:
        return 0, None
    ratio = vol5 / vol20
    if ratio >= 1.5:
        return 1, f"Volatility spike ({vol5:.0f}% ann. vs {vol20:.0f}% baseline)"
    return 0, None


def _annualized_vol(returns: pd.Series) -> float:
    """Annualized realized volatility from daily returns (%)."""
    if len(returns) < 2:
        return 0.0
    return float(returns.std() * math.sqrt(252))


# ---------------------------------------------------------------------------
# Per-ticker scoring
# ---------------------------------------------------------------------------

def _score_ticker(
    ticker: str,
    stock_meta: dict,
    close: pd.Series,
    volume: pd.Series,
    open_prices: pd.Series,
) -> Layer1Result:
    """Compute all signals and score for one ticker from its history series."""
    result = Layer1Result(
        ticker=ticker,
        name=stock_meta.get("name", ticker),
        sector=stock_meta.get("sector", ""),
        market_cap_bucket=stock_meta.get("market_cap_bucket", ""),
    )

    # Drop NaN and require at least 5 trading days
    close = close.dropna()
    volume = volume.dropna()
    open_prices = open_prices.dropna()

    if len(close) < 5:
        result.error = "no_market_data"
        return result

    result.current_price = float(close.iloc[-1])

    # Daily return
    if len(close) >= 2:
        result.price_change_1d = (close.iloc[-1] / close.iloc[-2] - 1) * 100

    # 3-day return
    if len(close) >= 4:
        result.price_change_3d = (close.iloc[-1] / close.iloc[-4] - 1) * 100

    # 5-day return
    if len(close) >= 6:
        result.price_change_5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100

    # 7-day return
    if len(close) >= 8:
        result.price_change_7d = (close.iloc[-1] / close.iloc[-8] - 1) * 100

    # Volume
    if len(volume) >= 1:
        result.volume_today = float(volume.iloc[-1])
    if len(volume) >= 20:
        result.volume_avg_20d = float(volume.iloc[-20:].mean())
    elif len(volume) >= 5:
        result.volume_avg_20d = float(volume.mean())
    if result.volume_today and result.volume_avg_20d and result.volume_avg_20d > 0:
        result.volume_ratio = result.volume_today / result.volume_avg_20d

    # Gap: today's open vs yesterday's close
    aligned_open = open_prices.reindex(close.index)
    if len(aligned_open.dropna()) >= 1 and len(close) >= 2:
        today_open = float(aligned_open.dropna().iloc[-1])
        prev_close = float(close.iloc[-2])
        if prev_close > 0:
            result.gap_pct = (today_open / prev_close - 1) * 100

    # Realized volatility
    daily_returns = close.pct_change().dropna() * 100
    if len(daily_returns) >= 5:
        result.volatility_5d = _annualized_vol(daily_returns.iloc[-5:])
    if len(daily_returns) >= 20:
        result.volatility_20d = _annualized_vol(daily_returns.iloc[-20:])

    # ── Score each component ────────────────────────────────────────────────
    signals = []

    ps, psig = _price_score(result.price_change_1d)
    result.price_score = ps
    if psig:
        signals.append(psig)

    vs, vsig = _volume_score(result.volume_ratio)
    result.volume_score = vs
    if vsig:
        signals.append(vsig)

    ms, msig = _momentum_score(result.price_change_5d)
    result.momentum_score = ms
    if msig:
        signals.append(msig)

    gs, gsig = _gap_score(result.gap_pct)
    result.gap_score = gs
    if gsig:
        signals.append(gsig)

    vols, volsig = _volatility_score(result.volatility_5d, result.volatility_20d)
    result.volatility_score = vols
    if volsig:
        signals.append(volsig)

    result.total_score = ps + vs + ms + gs + vols
    result.signals = signals
    return result


# ---------------------------------------------------------------------------
# Batch download + scan
# ---------------------------------------------------------------------------

def run_layer1(
    stocks: List[dict],
    batch_size: int = 60,
    min_score: int = 1,
    verbose: bool = True,
) -> List[Layer1Result]:
    """
    Run Layer 1 fast scan across all stocks.

    Downloads 30 days of OHLCV data in batches using yfinance,
    scores each stock, and returns results sorted by total_score descending.

    Args:
        stocks:     list of dicts with keys: ticker, name, sector, market_cap_bucket
        batch_size: tickers per yf.download() call (tune for speed vs memory)
        min_score:  filter out stocks with total_score < min_score before returning
        verbose:    print progress

    Returns:
        List[Layer1Result] sorted highest score first.
    """
    if not stocks:
        return []

    all_results: List[Layer1Result] = []
    total = len(stocks)

    # Process in batches to avoid yfinance timeouts on large ticker lists
    for batch_start in range(0, total, batch_size):
        batch = stocks[batch_start: batch_start + batch_size]
        tickers = [s["ticker"] for s in batch]
        stock_map = {s["ticker"]: s for s in batch}

        if verbose:
            end = min(batch_start + batch_size, total)
            print(f"[L1] Batch {batch_start+1}-{end}/{total}: downloading {len(tickers)} tickers...")

        try:
            # group_by="ticker" puts ticker as the top-level column
            raw = yf.download(
                tickers,
                period="32d",        # 30 trading days + buffer
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
        except Exception as e:
            if verbose:
                print(f"[L1] Batch download error: {e} — skipping batch")
            for s in batch:
                all_results.append(Layer1Result(
                    ticker=s["ticker"], name=s["name"], sector=s.get("sector", ""),
                    error=f"batch download failed: {e}",
                ))
            continue

        if raw.empty:
            if verbose:
                print(f"[L1] Empty response for batch — recording all {len(batch)} as no_data")
            for s in batch:
                all_results.append(Layer1Result(
                    ticker=s["ticker"], name=s["name"], sector=s.get("sector", ""),
                    error="no_market_data",
                ))
            continue

        # Handle single-ticker case: yfinance returns flat columns
        multi_ticker = len(tickers) > 1

        for ticker in tickers:
            stock_meta = stock_map[ticker]
            try:
                if multi_ticker:
                    # Multi-level columns: (metric, ticker)
                    if ticker not in raw.columns.get_level_values(1):
                        all_results.append(Layer1Result(
                            ticker=ticker, name=stock_meta["name"],
                            sector=stock_meta.get("sector", ""),
                            error="no_market_data",
                        ))
                        continue
                    close  = raw["Close"][ticker]
                    volume = raw["Volume"][ticker]
                    opens  = raw["Open"][ticker]
                else:
                    close  = raw["Close"]
                    volume = raw["Volume"]
                    opens  = raw["Open"]

                result = _score_ticker(ticker, stock_meta, close, volume, opens)
                all_results.append(result)

            except Exception as e:
                all_results.append(Layer1Result(
                    ticker=ticker, name=stock_meta.get("name", ticker),
                    sector=stock_meta.get("sector", ""),
                    error=str(e),
                ))

        time.sleep(0.5)  # be polite to yfinance

    # Filter and sort
    valid = [r for r in all_results if r.error is None]
    errors = [r for r in all_results if r.error is not None]

    valid.sort(key=lambda r: r.total_score, reverse=True)

    if verbose:
        scored = [r for r in valid if r.total_score >= min_score]
        print(f"[L1] Complete: {len(valid)} scored, {len(errors)} errors, "
              f"{len(scored)} above min_score={min_score}")

    return valid + errors  # scored stocks first, then errors (for reporting)
