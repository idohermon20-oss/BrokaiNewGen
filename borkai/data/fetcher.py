"""
Data fetching layer.
Wraps yfinance to produce a clean StockData object and a
formatted text block ready for LLM consumption.
"""
from __future__ import annotations

import re
import logging
from datetime import datetime, timedelta
import yfinance as yf
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

from borkai.data.article_fetcher import ArticleContent, fetch_articles, fetch_ddg_articles, format_articles_for_llm


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ArticleImpact:
    """AI-assessed impact of a single news article on a stock."""
    title: str
    url: str
    source: str
    published: str
    impact: str          # "bullish" | "bearish" | "neutral"  (legacy 3-level, preserved for compat)
    impact_summary: str  # 1–2 sentence explanation
    # ── Sentiment engine v2 ───────────────────────────────────────────────────
    # Empty string = legacy article (no v2 assessment done yet).
    # Non-empty = v2 assessed; "neutral" is a valid explicit v2 assignment.
    sentiment: str   = ""         # "strong_bullish" | "bullish" | "neutral" | "bearish" | "strong_bearish"
    impact_score: int = 0         # 0–5  financial strength of the event (5 = very strong impact)
    event_type: str  = ""         # event category, e.g. "partnership", "earnings beat", "guidance cut"
    event_reasoning: str = ""     # 1 sentence: how this event affects the company's financials/valuation
    confidence: float = 0.75      # classifier confidence 0.0-1.0 (rule=0.55-0.90, LLM=0.88)


@dataclass
class StockData:
    ticker: str
    company_name: str
    sector: str
    industry: str
    description: str
    country: Optional[str]
    market_cap: Optional[float]
    employees: Optional[int]

    # Income statement (TTM)
    revenue_ttm: Optional[float]
    net_income_ttm: Optional[float]
    ebitda: Optional[float]
    gross_margin: Optional[float]
    operating_margin: Optional[float]
    net_margin: Optional[float]

    # Balance sheet / liquidity
    total_cash: Optional[float]
    total_debt: Optional[float]
    debt_to_equity: Optional[float]
    current_ratio: Optional[float]
    free_cash_flow: Optional[float]

    # Valuation
    pe_ratio: Optional[float]
    forward_pe: Optional[float]
    pb_ratio: Optional[float]
    ps_ratio: Optional[float]
    ev_to_ebitda: Optional[float]
    dividend_yield: Optional[float]
    beta: Optional[float]

    # Price
    current_price: Optional[float]
    price_52w_high: Optional[float]
    price_52w_low: Optional[float]
    avg_volume: Optional[int]
    price_change_1m: Optional[float]   # percent
    price_change_3m: Optional[float]
    price_change_1y: Optional[float]

    # Technical indicators (computed from price history)
    rsi_14: Optional[float] = None
    ma20: Optional[float] = None
    ma50: Optional[float] = None
    ma20_above_ma50: Optional[bool] = None   # True = golden cross
    volume_vs_avg: Optional[float] = None    # ratio vs 20-day avg (>2.5 = spike)
    price_change_1d: Optional[float] = None  # today's % change

    # Live macro context (fetched at analysis time)
    macro_ta125_chg: Optional[float] = None  # TA-125 1-day % change (None for US stocks)
    macro_sp500_chg: Optional[float] = None  # S&P 500 1-day % change
    macro_vix: Optional[float] = None        # VIX level
    macro_usd_ils: Optional[float] = None    # USD/ILS spot rate
    macro_usd_ils_chg: Optional[float] = None
    macro_oil_chg: Optional[float] = None    # WTI crude 1-day % change

    # News (up to 10 items)
    recent_news: List[Dict[str, str]] = field(default_factory=list)

    # Full article content fetched from news URLs
    article_contents: List[ArticleContent] = field(default_factory=list)

    # AI-assessed per-article impact (populated separately in main.py)
    article_impacts: List[ArticleImpact] = field(default_factory=list)

    # Pre-formatted quarterly earnings comparison string (newest 3 quarters)
    quarterly_earnings_summary: Optional[str] = None


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _fetch_macro_snapshot(is_il: bool) -> Dict[str, Any]:
    """
    Fetch live macro context: S&P 500, VIX, USD/ILS, WTI crude, and TA-125 (IL only).
    Returns a dict with float values; any failures yield None.
    """
    snap: Dict[str, Any] = {}
    tickers_map = {
        "sp500":  "^GSPC",
        "vix":    "^VIX",
        "usdils": "ILS=X",
        "oil":    "CL=F",
    }
    if is_il:
        tickers_map["ta125"] = "^TA125.TA"

    try:
        raw = yf.download(
            list(tickers_map.values()),
            period="5d",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        close = raw["Close"] if "Close" in raw.columns else raw
        for key, sym in tickers_map.items():
            try:
                series = close[sym].dropna()
                if len(series) >= 2:
                    prev = float(series.iloc[-2])
                    last = float(series.iloc[-1])
                    snap[f"{key}_last"] = last
                    snap[f"{key}_chg"] = round((last - prev) / prev * 100, 2) if prev else None
                elif len(series) == 1:
                    snap[f"{key}_last"] = float(series.iloc[-1])
                    snap[f"{key}_chg"] = None
            except Exception:
                pass
    except Exception:
        pass
    return snap


def fetch_stock_data(ticker: str) -> StockData:
    """Fetch comprehensive stock data using yfinance."""
    t = yf.Ticker(ticker.upper())
    info: Dict[str, Any] = t.info or {}
    is_il = ticker.upper().endswith(".TA")

    # Price history (1 year)
    hist = _safe_history(t, "1y")
    if hist is not None and len(hist) > 0:
        current_price = float(hist["Close"].iloc[-1])
        price_52w_high = float(hist["High"].max())
        price_52w_low = float(hist["Low"].min())
    else:
        current_price = info.get("currentPrice")
        price_52w_high = info.get("fiftyTwoWeekHigh")
        price_52w_low = info.get("fiftyTwoWeekLow")

    price_change_1m = _pct_change(hist, 21)
    price_change_3m = _pct_change(hist, 63)
    price_change_1y = _pct_change(hist, len(hist) - 1) if hist is not None and len(hist) > 1 else None
    price_change_1d = _pct_change(hist, 1) if hist is not None and len(hist) > 1 else None

    # Technical indicators from price history
    rsi_14 = ma20 = ma50 = ma20_above_ma50 = volume_vs_avg = None
    if hist is not None and len(hist) >= 20:
        close = hist["Close"]
        rsi_14 = round(float(_calc_rsi(close).iloc[-1]), 1) if len(close) >= 14 else None
        ma20 = round(float(close.rolling(20).mean().iloc[-1]), 4)
        if len(close) >= 50:
            ma50 = round(float(close.rolling(50).mean().iloc[-1]), 4)
            ma20_above_ma50 = bool(ma20 > ma50)
        if "Volume" in hist.columns and len(hist) >= 20:
            avg_vol = float(hist["Volume"].iloc[-20:].mean())
            last_vol = float(hist["Volume"].iloc[-1])
            volume_vs_avg = round(last_vol / avg_vol, 2) if avg_vol > 0 else None

    # Macro snapshot (S&P 500, VIX, USD/ILS, WTI, TA-125)
    macro = _fetch_macro_snapshot(is_il)

    # Recent news
    recent_news: List[Dict[str, str]] = []
    try:
        for item in (t.news or [])[:10]:
            recent_news.append({
                "title": item.get("title", ""),
                "publisher": item.get("publisher", ""),
                "summary": item.get("summary", ""),
                "url": item.get("link", ""),
            })
    except Exception:
        pass

    # Primary article source: DuckDuckGo news search (English + Hebrew, real results)
    company_name_for_fetch = info.get("longName") or info.get("shortName") or ticker.upper()
    article_contents = fetch_ddg_articles(
        company_name=company_name_for_fetch,
        ticker=ticker,
        max_articles=10,
    )

    # Fallback: yfinance news URLs (if DDG returned nothing)
    if not article_contents:
        article_contents = fetch_articles(recent_news, max_articles=5)

    # Quarterly earnings (QoQ comparison)
    currency_for_quarterly = "₪" if is_il else "$"
    quarterly_earnings_summary = _build_quarterly_summary(t, currency_for_quarterly)

    return StockData(
        ticker=ticker.upper(),
        company_name=info.get("longName") or info.get("shortName") or ticker.upper(),
        sector=info.get("sector", "Unknown"),
        industry=info.get("industry", "Unknown"),
        description=info.get("longBusinessSummary", "No description available."),
        country=info.get("country"),
        market_cap=info.get("marketCap"),
        employees=info.get("fullTimeEmployees"),
        revenue_ttm=info.get("totalRevenue"),
        net_income_ttm=info.get("netIncomeToCommon"),
        ebitda=info.get("ebitda"),
        gross_margin=info.get("grossMargins"),
        operating_margin=info.get("operatingMargins"),
        net_margin=info.get("profitMargins"),
        total_cash=info.get("totalCash"),
        total_debt=info.get("totalDebt"),
        debt_to_equity=info.get("debtToEquity"),
        current_ratio=info.get("currentRatio"),
        free_cash_flow=info.get("freeCashflow"),
        pe_ratio=info.get("trailingPE"),
        forward_pe=info.get("forwardPE"),
        pb_ratio=info.get("priceToBook"),
        ps_ratio=info.get("priceToSalesTrailing12Months"),
        ev_to_ebitda=info.get("enterpriseToEbitda"),
        dividend_yield=info.get("dividendYield"),
        beta=info.get("beta"),
        current_price=current_price,
        price_52w_high=price_52w_high,
        price_52w_low=price_52w_low,
        avg_volume=info.get("averageVolume"),
        price_change_1d=price_change_1d,
        price_change_1m=price_change_1m,
        price_change_3m=price_change_3m,
        price_change_1y=price_change_1y,
        rsi_14=rsi_14,
        ma20=ma20,
        ma50=ma50,
        ma20_above_ma50=ma20_above_ma50,
        volume_vs_avg=volume_vs_avg,
        macro_ta125_chg=macro.get("ta125_chg"),
        macro_sp500_chg=macro.get("sp500_chg"),
        macro_vix=macro.get("vix_last"),
        macro_usd_ils=macro.get("usdils_last"),
        macro_usd_ils_chg=macro.get("usdils_chg"),
        macro_oil_chg=macro.get("oil_chg"),
        recent_news=recent_news,
        article_contents=article_contents,
        quarterly_earnings_summary=quarterly_earnings_summary,
    )


# ---------------------------------------------------------------------------
# Quarterly earnings helper
# ---------------------------------------------------------------------------

def _build_quarterly_summary(t: "yf.Ticker", currency: str = "$") -> Optional[str]:
    """
    Extract the 3 most recent quarters of revenue + net income for QoQ context.
    Returns a pre-formatted text block, or None if data is unavailable.
    """
    try:
        import pandas as pd
        qi = t.quarterly_income_stmt
        if qi is None or qi.empty:
            return None

        rev_row = ni_row = None
        for candidate in ("Total Revenue", "Revenue", "Operating Revenue"):
            if candidate in qi.index:
                rev_row = qi.loc[candidate]
                break
        for candidate in ("Net Income", "Net Income Common Stockholders"):
            if candidate in qi.index:
                ni_row = qi.loc[candidate]
                break

        if rev_row is None and ni_row is None:
            return None

        all_cols = list(qi.columns)          # all available quarters, newest first
        quarters = all_cols[:4]              # display up to 4
        lines = ["", "--- QUARTERLY EARNINGS (newest first) ---"]
        for q in quarters:
            q_str = str(q)[:10]
            try:
                rev_val = None if rev_row is None or pd.isna(rev_row[q]) else float(rev_row[q])
            except Exception:
                rev_val = None
            try:
                ni_val = None if ni_row is None or pd.isna(ni_row[q]) else float(ni_row[q])
            except Exception:
                ni_val = None
            lines.append(
                f"  {q_str}: Rev={_fmt_num(rev_val, currency) if rev_val is not None else 'N/A'}"
                f"  Net={_fmt_num(ni_val, currency) if ni_val is not None else 'N/A'}"
            )

        # QoQ changes (most recent vs prior quarter)
        if len(quarters) >= 2:
            changes = []
            if rev_row is not None:
                try:
                    r0 = float(rev_row[quarters[0]]) if not pd.isna(rev_row[quarters[0]]) else None
                    r1 = float(rev_row[quarters[1]]) if not pd.isna(rev_row[quarters[1]]) else None
                    if r0 is not None and r1 is not None and r1 != 0:
                        chg = (r0 - r1) / abs(r1) * 100
                        changes.append(f"Rev QoQ {'+' if chg > 0 else ''}{chg:.1f}%")
                except Exception:
                    pass
            if ni_row is not None:
                try:
                    n0 = float(ni_row[quarters[0]]) if not pd.isna(ni_row[quarters[0]]) else None
                    n1 = float(ni_row[quarters[1]]) if not pd.isna(ni_row[quarters[1]]) else None
                    if n0 is not None and n1 is not None and n1 != 0:
                        chg = (n0 - n1) / abs(n1) * 100
                        changes.append(f"Net QoQ {'+' if chg > 0 else ''}{chg:.1f}%")
                except Exception:
                    pass
            if changes:
                lines.append(f"  Latest vs prior: {', '.join(changes)}")

        # YoY changes (most recent vs same quarter one year ago, i.e. index 4)
        if len(all_cols) >= 5:
            yoy_changes = []
            q_recent = all_cols[0]
            q_year_ago = all_cols[4]
            if rev_row is not None:
                try:
                    r_now = float(rev_row[q_recent]) if not pd.isna(rev_row[q_recent]) else None
                    r_ya  = float(rev_row[q_year_ago]) if not pd.isna(rev_row[q_year_ago]) else None
                    if r_now is not None and r_ya is not None and r_ya != 0:
                        chg = (r_now - r_ya) / abs(r_ya) * 100
                        yoy_changes.append(f"Rev YoY {'+' if chg > 0 else ''}{chg:.1f}%")
                except Exception:
                    pass
            if ni_row is not None:
                try:
                    n_now = float(ni_row[q_recent]) if not pd.isna(ni_row[q_recent]) else None
                    n_ya  = float(ni_row[q_year_ago]) if not pd.isna(ni_row[q_year_ago]) else None
                    if n_now is not None and n_ya is not None and n_ya != 0:
                        chg = (n_now - n_ya) / abs(n_ya) * 100
                        yoy_changes.append(f"Net YoY {'+' if chg > 0 else ''}{chg:.1f}%")
                except Exception:
                    pass
            if yoy_changes:
                lines.append(f"  Year-over-year: {', '.join(yoy_changes)}")

        return "\n".join(lines)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Formatting for LLM
# ---------------------------------------------------------------------------

def format_stock_data_for_llm(data: StockData, currency_symbol: str = "$") -> str:
    """Render StockData as a structured text block for LLM consumption."""
    lines = [
        f"{'='*60}",
        f"STOCK DATA: {data.ticker} — {data.company_name}",
        f"{'='*60}",
        f"Sector: {data.sector}  |  Industry: {data.industry}  |  Country: {data.country or 'N/A'}",
    ]
    s = currency_symbol  # shorthand
    if data.market_cap:
        emp_str = f"  |  Employees: {data.employees:,}" if data.employees else ""
        lines.append(f"Market Cap: {_fmt_num(data.market_cap, s)}{emp_str}")
    lines += [
        "",
        "BUSINESS DESCRIPTION:",
        data.description[:1500],
        "",
        "--- INCOME STATEMENT (TTM) ---",
        f"  Revenue:           {_fmt_num(data.revenue_ttm, s)}",
        f"  Net Income:        {_fmt_num(data.net_income_ttm, s)}",
        f"  EBITDA:            {_fmt_num(data.ebitda, s)}",
        f"  Gross Margin:      {_fmt_pct(data.gross_margin)}",
        f"  Operating Margin:  {_fmt_pct(data.operating_margin)}",
        f"  Net Margin:        {_fmt_pct(data.net_margin)}",
        f"  Free Cash Flow:    {_fmt_num(data.free_cash_flow, s)}",
        "",
        "--- BALANCE SHEET ---",
        f"  Total Cash:        {_fmt_num(data.total_cash, s)}",
        f"  Total Debt:        {_fmt_num(data.total_debt, s)}",
        f"  Debt/Equity:       {data.debt_to_equity or 'N/A'}",
        f"  Current Ratio:     {data.current_ratio or 'N/A'}",
        "",
        "--- VALUATION ---",
        f"  P/E (Trailing):    {data.pe_ratio or 'N/A'}",
        f"  P/E (Forward):     {data.forward_pe or 'N/A'}",
        f"  P/B:               {data.pb_ratio or 'N/A'}",
        f"  P/S:               {data.ps_ratio or 'N/A'}",
        f"  EV/EBITDA:         {data.ev_to_ebitda or 'N/A'}",
        f"  Dividend Yield:    {_fmt_pct(data.dividend_yield)}",
        f"  Beta:              {data.beta or 'N/A'}",
        "",
        "--- PRICE ---",
        f"  Current:           {_fmt_price(data.current_price, s)}",
        f"  52W High:          {_fmt_price(data.price_52w_high, s)}",
        f"  52W Low:           {_fmt_price(data.price_52w_low, s)}",
        f"  Today:             {_fmt_chg(data.price_change_1d)}  |  "
        f"1M: {_fmt_chg(data.price_change_1m)}  |  "
        f"3M: {_fmt_chg(data.price_change_3m)}  |  "
        f"1Y: {_fmt_chg(data.price_change_1y)}",
        "",
        "--- TECHNICAL INDICATORS ---",
        f"  RSI-14:            {data.rsi_14 or 'N/A'}  {'(OVERBOUGHT >70)' if data.rsi_14 and data.rsi_14 > 70 else '(OVERSOLD <30)' if data.rsi_14 and data.rsi_14 < 30 else ''}",
        f"  MA20:              {_fmt_price(data.ma20, s)}  |  MA50: {_fmt_price(data.ma50, s)}",
        f"  MA20 > MA50:       {'YES (Golden Cross ↑)' if data.ma20_above_ma50 else 'NO (Death Cross ↓)' if data.ma20_above_ma50 is not None else 'N/A'}",
        f"  Volume vs 20d Avg: {f'{data.volume_vs_avg:.2f}x' if data.volume_vs_avg else 'N/A'}  {'⚡ VOLUME SPIKE' if data.volume_vs_avg and data.volume_vs_avg >= 2.5 else ''}",
    ]

    # Trend summary — plain-language interpretation of technical signals
    trend_lines: list = []
    has_trend_data = any(v is not None for v in [data.rsi_14, data.ma20_above_ma50, data.price_52w_high, data.price_change_1m])
    if has_trend_data:
        trend_lines = ["", "--- TREND SUMMARY ---"]
        if data.rsi_14 is not None:
            if data.rsi_14 > 70:
                rsi_label = "OVERBOUGHT — momentum risk"
            elif data.rsi_14 < 30:
                rsi_label = "OVERSOLD — potential reversal setup"
            elif data.rsi_14 > 55:
                rsi_label = "bullish momentum"
            elif data.rsi_14 < 45:
                rsi_label = "bearish momentum"
            else:
                rsi_label = "neutral"
            trend_lines.append(f"  RSI-14: {data.rsi_14} → {rsi_label}")
        if data.ma20_above_ma50 is not None:
            trend_lines.append(
                f"  MA structure: {'Golden Cross (MA20>MA50) — bullish' if data.ma20_above_ma50 else 'Death Cross (MA20<MA50) — bearish'}"
            )
        if data.current_price and data.price_52w_high and data.price_52w_high > 0:
            off_high = (data.price_52w_high - data.current_price) / data.price_52w_high * 100
            off_low_str = ""
            if data.price_52w_low and data.price_52w_low > 0:
                off_low = (data.current_price - data.price_52w_low) / data.price_52w_low * 100
                off_low_str = f", {off_low:.1f}% above 52W low"
            trend_lines.append(f"  52W position: {off_high:.1f}% below 52W high{off_low_str}")
        m_parts = []
        if data.price_change_1m is not None:
            m_parts.append(f"1M {'+' if data.price_change_1m > 0 else ''}{data.price_change_1m:.1f}%")
        if data.price_change_3m is not None:
            m_parts.append(f"3M {'+' if data.price_change_3m > 0 else ''}{data.price_change_3m:.1f}%")
        if m_parts:
            trend_lines.append(f"  Momentum: {', '.join(m_parts)}")
    lines += trend_lines

    # Quarterly earnings comparison
    if data.quarterly_earnings_summary:
        lines.append(data.quarterly_earnings_summary)

    # Macro context block (only add if we have data)
    macro_lines = []
    if any(v is not None for v in [
        data.macro_sp500_chg, data.macro_vix, data.macro_usd_ils_chg,
        data.macro_ta125_chg, data.macro_oil_chg,
    ]):
        macro_lines = ["", "--- MARKET CONTEXT (at time of analysis) ---"]
        if data.macro_ta125_chg is not None:
            macro_lines.append(f"  TA-125 (TASE):     {_fmt_chg(data.macro_ta125_chg)}")
        if data.macro_sp500_chg is not None:
            macro_lines.append(f"  S&P 500:           {_fmt_chg(data.macro_sp500_chg)}")
        if data.macro_vix is not None:
            vix_note = "  (ELEVATED FEAR)" if data.macro_vix > 25 else "  (MODERATE)" if data.macro_vix > 18 else ""
            macro_lines.append(f"  VIX:               {data.macro_vix:.1f}{vix_note}")
        if data.macro_usd_ils is not None:
            ils_chg = f"  ({_fmt_chg(data.macro_usd_ils_chg)} today)" if data.macro_usd_ils_chg else ""
            macro_lines.append(f"  USD/ILS:           {data.macro_usd_ils:.4f}{ils_chg}")
        if data.macro_oil_chg is not None:
            macro_lines.append(f"  WTI Crude:         {_fmt_chg(data.macro_oil_chg)} (today)")
    lines += macro_lines

    lines += [
        "",
        "--- RECENT NEWS ---",
    ]
    for i, item in enumerate(data.recent_news, 1):
        lines.append(f"  {i}. [{item.get('publisher', '')}] {item.get('title', '')}")
        if item.get("summary"):
            lines.append(f"     {item['summary'][:200]}")

    # Append full article content if available
    article_block = format_articles_for_llm(data.article_contents)
    if article_block:
        lines.append(article_block)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calc_rsi(series, period: int = 14):
    """Compute RSI-{period} for a price series."""
    import pandas as pd
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def _safe_history(ticker_obj, period: str):
    try:
        hist = ticker_obj.history(period=period)
        return hist if len(hist) > 0 else None
    except Exception:
        return None


def _pct_change(hist, periods_back: int) -> Optional[float]:
    if hist is None or len(hist) <= periods_back or periods_back <= 0:
        return None
    old = float(hist["Close"].iloc[-periods_back])
    new = float(hist["Close"].iloc[-1])
    if old > 0:
        return round((new - old) / old * 100, 2)
    return None


def _fmt_num(val, s: str = "$") -> str:
    if val is None:
        return "N/A"
    v = float(val)
    if abs(v) >= 1e12:
        return f"{s}{v/1e12:.2f}T"
    if abs(v) >= 1e9:
        return f"{s}{v/1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"{s}{v/1e6:.2f}M"
    return f"{s}{v:,.0f}"


def _fmt_pct(val) -> str:
    if val is None:
        return "N/A"
    return f"{float(val)*100:.1f}%"


def _fmt_price(val, s: str = "$") -> str:
    if val is None:
        return "N/A"
    return f"{s}{float(val):.2f}"


def _fmt_chg(val) -> str:
    if val is None:
        return "N/A"
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.1f}%"


# ---------------------------------------------------------------------------
# Hybrid News Analysis Engine
# ---------------------------------------------------------------------------
# Architecture:
#   Phase 1 — Rule-based classifier runs on ALL articles (instant, no LLM)
#   Phase 2 — LLM called ONLY for articles that need it (≤ 5 per stock)
#   Phase 3 — Validation pass: prevent neutral for strong positive signals
#   Phase 4 — Assemble ArticleImpact objects
# ---------------------------------------------------------------------------

# ── Rule keyword sets ──────────────────────────────────────────────────────

_RULE_STRONG_BULL = [
    # Price action
    "52-week high", "all-time high", "soars", "soared", "surges", "surged",
    "rallies", "rallied", "jumps", "jumped", "spikes", "spiked",
    # Named partners / tech giants
    "nvidia", "intel", "microsoft", "google", "amazon", "apple", "meta",
    "openai", "tsmc",
    # Earnings / financial
    "record revenue", "record profit", "record earnings", "earnings beat",
    "beats estimates", "beat estimates", "beats expectations", "beat expectations",
    "blowout", "blowout quarter",
    # Strategic
    "major contract", "contract win", "defense contract", "major partnership",
    "ai deal", "ai partnership", "breakthrough", "multi-billion",
    "multi-year contract", "significant contract",
]
_RULE_BULL = [
    "partnership", "collaboration", "expansion", "new market", "new contract",
    "contract", "product launch", "new product", "positive outlook",
    "guidance raised", "guidance upgrade", "upgrade", "analyst upgrade",
    "strong growth", "revenue growth", "profit growth", "new customers",
    "market expansion", "international expansion", "joint venture",
    "strategic agreement", "order book", "backlog growth",
]
_RULE_STRONG_BEAR = [
    "bankruptcy", "insolvency", "delisted", "fraud", "sec charges", "sec action",
    "guidance cut", "guidance slashed", "revenue miss", "earnings miss",
    "misses estimates", "missed estimates", "misses expectations",
    "major loss", "loss widens", "revenue declines sharply",
    "class action", "criminal investigation", "regulatory fine",
]
_RULE_BEAR = [
    "downgrade", "analyst downgrade", "misses", "missed", "decline",
    "revenue decline", "lower guidance", "disappoints", "disappointing",
    "loss", "lawsuit", "investigation", "regulatory", "headcount reduction",
    "layoffs", "delayed", "cancelled", "contract loss", "lost contract",
    "write-down", "writedown", "impairment",
]
# Keywords that make "neutral" classification suspicious
_RULE_ANTINEUTRAL_BULL = [
    "partnership", "contract", "deal", "expansion", "record", "beat",
    "growth", "surge", "rally", "high", "launch", "win", "upgrade",
]
_RULE_ANTINEUTRAL_BEAR = [
    "miss", "loss", "decline", "downgrade", "investigation", "lawsuit",
    "cut", "layoff", "bankruptcy",
]

# Impact scores by tier
_RULE_IMPACT = {
    "strong_bullish": 4,
    "bullish":        2,
    "neutral":        1,
    "bearish":        2,
    "strong_bearish": 4,
}

# Event type detection (checked in order; first match wins)
_EVENT_TYPE_MAP = [
    (["earnings beat", "beats estimates", "beats expectations", "blowout"], "earnings beat"),
    (["guidance raised", "guidance upgrade"], "guidance raised"),
    (["guidance cut", "guidance slashed"], "guidance cut"),
    (["partnership", "collaboration", "joint venture", "strategic agreement"], "partnership"),
    (["acquisition", "acquired", "merger", "takeover"], "acquisition"),
    (["product launch", "new product"], "product launch"),
    (["contract", "order book", "backlog"], "contract win"),
    (["expansion", "new market", "international expansion"], "expansion"),
    (["upgrade", "analyst upgrade"], "analyst upgrade"),
    (["downgrade", "analyst downgrade"], "analyst downgrade"),
    (["lawsuit", "class action", "litigation"], "legal risk"),
    (["investigation", "sec charges", "regulatory fine", "fraud"], "regulatory risk"),
    (["layoffs", "headcount reduction"], "restructuring"),
    (["record revenue", "record profit", "record earnings"], "record results"),
    (["52-week high", "all-time high", "soars", "surges", "rallies"], "price action"),
]


def _rule_classify(title: str, snippet: str) -> tuple:
    """
    Rule-based article classifier.

    Returns (sentiment, event_type, impact_score, confidence, rule_hits)
    where confidence is 0.0-1.0 and rule_hits is a list of matched keywords.

    Confidence levels:
      0.90 — strong_bullish or strong_bearish match (clear, specific event)
      0.80 — bullish or bearish match (directional but not exceptional)
      0.55 — neutral (default; intentionally low so LLM can override easily)
      If both bull and bear signals hit → confidence drops to signal conflict
    """
    combined = f"{title} {snippet}".lower()

    # Count hits per tier
    sb_hits = [kw for kw in _RULE_STRONG_BULL if kw in combined]
    b_hits  = [kw for kw in _RULE_BULL  if kw in combined]
    sb2_hits= [kw for kw in _RULE_STRONG_BEAR if kw in combined]
    be_hits = [kw for kw in _RULE_BEAR  if kw in combined]

    pos_score = len(sb_hits) * 2 + len(b_hits)
    neg_score = len(sb2_hits) * 2 + len(be_hits)

    # Detect event type
    event_type = "general news"
    for kw_list, etype in _EVENT_TYPE_MAP:
        if any(kw in combined for kw in kw_list):
            event_type = etype
            break

    # Classify
    if pos_score > 0 and neg_score > 0:
        # Conflicting — mark low confidence so LLM handles it
        dominant = "bullish" if pos_score > neg_score else "bearish"
        conf = 0.45
        all_hits = sb_hits + b_hits + sb2_hits + be_hits
        return dominant, event_type, _RULE_IMPACT[dominant], conf, all_hits

    if sb_hits and pos_score >= 2:
        return "strong_bullish", event_type, 4, 0.90, sb_hits
    if sb_hits:
        return "strong_bullish", event_type, 4, 0.85, sb_hits
    if b_hits:
        conf = 0.80 if len(b_hits) >= 2 else 0.72
        return "bullish", event_type, 2, conf, b_hits
    if sb2_hits and neg_score >= 2:
        return "strong_bearish", event_type, 4, 0.90, sb2_hits
    if sb2_hits:
        return "strong_bearish", event_type, 4, 0.85, sb2_hits
    if be_hits:
        conf = 0.80 if len(be_hits) >= 2 else 0.72
        return "bearish", event_type, 2, conf, be_hits

    # No signal detected — neutral with low confidence
    return "neutral", event_type, 0, 0.55, []


def _needs_llm(sentiment: str, confidence: float, impact_score: int, title: str, snippet: str) -> bool:
    """
    Decide whether an article should be sent to the LLM for deeper analysis.

    Triggers:
      - Low confidence: rule classifier is unsure
      - Conflicting signals: both pos and neg keywords fired
      - High-impact articles: important enough to verify
      - Suspicious neutral: article looks non-trivial but rule said neutral
    """
    if confidence < 0.70:
        return True
    if impact_score >= 4:
        return True
    # Suspicious neutral: has anti-neutral keywords but classified neutral
    if sentiment == "neutral":
        combined = f"{title} {snippet}".lower()
        anti_bull = sum(1 for kw in _RULE_ANTINEUTRAL_BULL if kw in combined)
        anti_bear = sum(1 for kw in _RULE_ANTINEUTRAL_BEAR if kw in combined)
        if anti_bull >= 1 or anti_bear >= 1:
            return True
    return False


def _llm_classify_batch(
    items: list,
    ticker: str,
    company_name: str,
    client,
    config,
) -> dict:
    """
    LLM classification for a subset of articles (max 5).

    Returns dict mapping item id -> result dict with keys:
      sentiment, impact_score, event_type, event_reasoning, impact_summary
    """
    import json

    if not items:
        return {}

    batch_json = json.dumps(
        [{"id": it["id"], "title": it["title"], "source": it.get("source", ""),
          "snippet": it.get("snippet", "")[:500]}
         for it in items],
        ensure_ascii=False,
    )

    prompt = f"""You are a senior equity analyst covering {ticker} ({company_name}).

For each article below, determine its FINANCIAL IMPACT on {ticker}.
This is NOT about language tone — it is about financial meaning.

REASONING PROCESS (follow for each article):
1. Identify the KEY FINANCIAL EVENT described
2. Explain (1 sentence) HOW this event affects {ticker} financially
3. Then assign sentiment and score

SENTIMENT SCALE:
  strong_bullish (score 4-5): major partnerships, earnings beats, large contracts,
                               record results, major tech partnerships (NVIDIA etc.), price at new highs
  bullish        (score 2-3): positive updates, growth signals, product launches, upgrades
  neutral        (score 0-1): genuinely informational/mixed, unclear financial impact
  bearish        (score 2-3): weak results, negative outlook, declining revenue
  strong_bearish (score 4-5): losses, major downgrades, regulatory action, guidance cuts

VALIDATION RULES — enforce strictly:
  - Partnership with major tech company (NVIDIA, Google, etc.) → MUST be strong_bullish
  - Price surge, 52-week high → MUST be bullish or strong_bullish
  - Expansion, new market entry → at least bullish
  - Strong earnings, guidance raise → at least bullish
  Neutral is ONLY for genuinely ambiguous articles with no clear financial signal.

Articles:
{batch_json}

Return JSON: {{"results": [{{"id": <id>, "event_type": "<category>",
  "event_reasoning": "<1 sentence financial impact>",
  "sentiment": "<strong_bullish|bullish|neutral|bearish|strong_bearish>",
  "impact_score": <0-5>,
  "impact_summary": "<1-2 sentences>"}}]}}"""

    try:
        resp = client.chat.completions.create(
            model=config.models.agent,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        results = data.get("results", data.get("items", []))
        return {r["id"]: r for r in results if "id" in r}
    except Exception:
        return {}


def _validate_article(art_dict: dict) -> str:
    """
    Validation pass: prevent neutral for articles containing strong signals.
    Returns corrected sentiment string.
    """
    sentiment = art_dict.get("sentiment", "neutral")
    if sentiment != "neutral":
        return sentiment

    combined = f"{art_dict.get('title', '')} {art_dict.get('snippet', '')}".lower()

    # Strong bull signals that cannot be neutral
    if any(kw in combined for kw in _RULE_STRONG_BULL):
        return "bullish"
    if sum(1 for kw in _RULE_ANTINEUTRAL_BULL if kw in combined) >= 2:
        return "bullish"
    if any(kw in combined for kw in _RULE_STRONG_BEAR):
        return "bearish"
    if sum(1 for kw in _RULE_ANTINEUTRAL_BEAR if kw in combined) >= 2:
        return "bearish"

    return "neutral"


def assess_article_impacts(
    article_contents: List["ArticleContent"],
    recent_news: List[Dict[str, str]],
    ticker: str,
    company_name: str,
    client,
    config,
) -> List[ArticleImpact]:
    """
    Hybrid news analysis engine:
      Phase 1 — Rule-based classifier runs on ALL articles instantly
      Phase 2 — LLM called for ≤5 articles that need deeper analysis
      Phase 3 — Validation pass prevents neutral misclassification
      Phase 4 — Assemble ArticleImpact objects

    LLM trigger conditions (any one):
      - Rule confidence < 0.70 (unclear/conflicting signals)
      - impact_score >= 4 (high importance — worth verifying)
      - Suspicious neutral (has direction keywords but classified neutral)
    """
    # Build item list
    items = []
    news_by_url = {n.get("url", ""): n for n in recent_news}
    for ac in article_contents:
        news = news_by_url.get(ac.url, {})
        items.append({
            "id": len(items),
            "title": ac.title or news.get("title", ""),
            "source": ac.publisher or news.get("publisher", ""),
            "published": ac.published or "",
            "url": ac.url,
            "snippet": (ac.text or "")[:500],
        })
    seen_urls = {ac.url for ac in article_contents}
    for n in recent_news:
        url = n.get("url", "")
        if url and url not in seen_urls:
            items.append({
                "id": len(items),
                "title": n.get("title", ""),
                "source": n.get("publisher", ""),
                "published": "",
                "url": url,
                "snippet": n.get("summary", "")[:500],
            })
            seen_urls.add(url)

    if not items:
        return []

    # ── Phase 1: Rule-based classification ───────────────────────────────────
    _MAX_LLM_ARTICLES = 5
    rule_results: dict = {}
    llm_candidates = []

    for it in items:
        sentiment, event_type, impact_score, confidence, rule_hits = _rule_classify(
            it["title"], it["snippet"]
        )
        rule_results[it["id"]] = {
            "sentiment":       sentiment,
            "event_type":      event_type,
            "impact_score":    impact_score,
            "confidence":      confidence,
            "rule_hits":       rule_hits,
            "event_reasoning": "",
            "impact_summary":  "",
        }
        if _needs_llm(sentiment, confidence, impact_score, it["title"], it["snippet"]):
            llm_candidates.append((it, confidence, impact_score))

    # ── Phase 2: Selective LLM analysis (priority-sorted, max 5) ─────────────
    # Priority: low confidence first, then high impact, then high importance overall
    llm_candidates.sort(key=lambda x: (x[1], -x[2]))   # ascending conf, desc impact
    llm_items = [c[0] for c in llm_candidates[:_MAX_LLM_ARTICLES]]

    if llm_items:
        llm_results = _llm_classify_batch(llm_items, ticker, company_name, client, config)
        # Merge LLM results into rule_results (LLM overrides)
        for llm_id, r in llm_results.items():
            if llm_id in rule_results:
                sentiment = r.get("sentiment", rule_results[llm_id]["sentiment"])
                if sentiment not in ("strong_bullish", "bullish", "neutral", "bearish", "strong_bearish"):
                    sentiment = rule_results[llm_id]["sentiment"]
                raw_score = r.get("impact_score", 0)
                try:
                    impact_score = max(0, min(5, int(raw_score)))
                except (TypeError, ValueError):
                    impact_score = rule_results[llm_id]["impact_score"]
                rule_results[llm_id].update({
                    "sentiment":       sentiment,
                    "impact_score":    impact_score,
                    "event_type":      r.get("event_type", rule_results[llm_id]["event_type"]),
                    "event_reasoning": r.get("event_reasoning", ""),
                    "impact_summary":  r.get("impact_summary", ""),
                    "confidence":      0.88,   # LLM-assessed
                })
    else:
        llm_results = {}

    # ── Phase 3: Validation pass ──────────────────────────────────────────────
    for it in items:
        res = rule_results[it["id"]]
        corrected = _validate_article({"sentiment": res["sentiment"],
                                       "title": it["title"], "snippet": it["snippet"]})
        if corrected != res["sentiment"]:
            res["sentiment"] = corrected
            # Bump impact_score if it was zero
            if res["impact_score"] == 0:
                res["impact_score"] = 2
            res["event_reasoning"] = (
                res["event_reasoning"] or
                f"Reclassified from neutral: {corrected} signal detected in article"
            )

    # ── Phase 4: Assemble ArticleImpact objects ───────────────────────────────
    _SENTIMENT_TO_IMPACT = {
        "strong_bullish": "bullish",
        "bullish":        "bullish",
        "neutral":        "neutral",
        "bearish":        "bearish",
        "strong_bearish": "bearish",
    }

    impacts: List[ArticleImpact] = []
    for it in items:
        res = rule_results[it["id"]]
        sentiment    = res["sentiment"]
        impact_score = res["impact_score"]
        event_reasoning = res["event_reasoning"]
        impact_summary  = res["impact_summary"] or event_reasoning
        impacts.append(ArticleImpact(
            title=it["title"],
            url=it["url"],
            source=it["source"],
            published=it["published"],
            impact=_SENTIMENT_TO_IMPACT.get(sentiment, "neutral"),
            impact_summary=impact_summary,
            sentiment=sentiment,
            impact_score=impact_score,
            event_type=res["event_type"],
            event_reasoning=event_reasoning,
            confidence=float(res.get("confidence", 0.75)),
        ))

    filtered, meta = filter_article_impacts(impacts, ticker=ticker, company_name=company_name)
    if meta["removed_count"] > 0:
        logger.debug(
            "[news-filter] %s: kept %d / %d articles. Removed: %s",
            ticker, len(filtered), len(impacts),
            ", ".join(f"{k}={v}" for k, v in meta["breakdown"].items() if v),
        )
    return filtered


# ---------------------------------------------------------------------------
# News filter — post-processing for assess_article_impacts()
# ---------------------------------------------------------------------------

# Source credibility tiers (higher = more credible)
_CREDIBILITY_TIER: Dict[str, int] = {
    # Tier 3 — wire services / major financial press
    "reuters.com": 3, "bloomberg.com": 3, "ft.com": 3, "wsj.com": 3,
    "apnews.com": 3, "bbc.co.uk": 3, "bbc.com": 3, "cnbc.com": 3,
    "globes.co.il": 3, "calcalist.co.il": 3, "themarker.com": 3,
    "ynet.co.il": 3, "haaretz.com": 3,
    # Tier 2 — quality financial news / industry press
    "seekingalpha.com": 2, "marketwatch.com": 2, "barrons.com": 2,
    "investopedia.com": 2, "thestreet.com": 2, "businessinsider.com": 2,
    "techcrunch.com": 2, "wired.com": 2, "venturebeat.com": 2,
    "nana10.co.il": 2, "ice.co.il": 2, "bizportal.co.il": 2,
    # Tier 1 — aggregators / lesser-known but real news
    "prnewswire.com": 1, "businesswire.com": 1, "globenewswire.com": 1,
    "accesswire.com": 1, "einpresswire.com": 1,
}

# Stop words for title-based deduplication
_FILTER_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "are", "was", "were", "be", "been", "its", "it",
    "this", "that", "as", "by", "from", "up", "has", "have", "will",
}


def _source_credibility(source: str) -> int:
    """Return credibility tier 1–3; default 1 for unknown sources."""
    if not source:
        return 1
    domain = source.lower().strip().lstrip("www.")
    # Strip protocol if accidentally included
    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    for known, tier in _CREDIBILITY_TIER.items():
        if domain == known or domain.endswith("." + known):
            return tier
    return 1


def _article_pub_dt(published: str) -> Optional[datetime]:
    """Parse 'YYYY-MM-DD HH:MM' string → datetime, or None if unparseable."""
    if not published:
        return None
    try:
        return datetime.strptime(published[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        try:
            return datetime.strptime(published[:10], "%Y-%m-%d")
        except ValueError:
            return None


def _title_fingerprint(title: str) -> frozenset:
    """Significant word set for near-duplicate detection (mirrors article_fetcher logic)."""
    words = re.findall(r"[a-zA-Z\u05d0-\u05ea0-9]+", title.lower())
    return frozenset(w for w in words if w not in _FILTER_STOP_WORDS and len(w) > 2)


# URL path fragments that mark non-article pages (supplement article_fetcher's gate)
_NON_ARTICLE_URL_PATHS = (
    "/quote/", "/quotes/", "/symbol/", "/symbols/", "/equities/",
    "/stock/", "/stocks/", "/ticker/", "/company/", "/profile/",
    "/chart/", "/historical/", "/dividends/", "/financials/",
    "/market-data/", "/markets/", "/indices/", "/index/",
    "/money/stock", "/money/stockdetails",
    "/forum/", "/message-board/", "/board/", "/thread/",
    "/tag/", "/tags/", "/category/", "/categories/",
    "/archive/", "/archives/", "/list/", "/listing/",
)
_NON_ARTICLE_URL_SUFFIXES = (
    "/quote", "/quotes", "/financials", "/technicals", "/overview",
    "/chart", "/profile", "/holders", "/dividends", "/history",
)

# Keywords that mark a title as generic market-wide noise (not company-specific)
# Used only when the article has NO company signal at all.
_MARKET_WIDE_TITLE_KW = [
    # ── Market-wide updates ───────────────────────────────────────────────────
    "market update", "weekly recap", "daily recap", "market roundup",
    "weekly roundup", "market outlook", "market summary", "market review",
    "market rally", "market selloff", "market correction", "market close",
    "market open", "stock market", "equity market",
    # ── Index references ──────────────────────────────────────────────────────
    "ta-125", "ta125", "ta 125", "tel aviv 125",
    "s&p 500", "s&p500", "dow jones", "nasdaq composite",
    "ftse 100", "dax index", "nikkei",
    "index update", "index performance", "index hits",
    # ── Regional / exchange-wide ──────────────────────────────────────────────
    "israeli market", "israeli stocks", "israeli shares",
    "tel aviv market", "tel aviv stocks", "tase stocks",
    "global markets", "asian markets", "european markets", "us markets",
    # ── Sector-wide (without company mention) ─────────────────────────────────
    "sector outlook", "sector update", "sector analysis",
    "sector performance", "sector roundup", "sector review",
    "sector broad", "sector wide", "industry outlook",
    "industry update", "industry analysis", "industry performance",
    # ── Generic investor / macro ──────────────────────────────────────────────
    "investor sentiment", "market breadth", "breadth indicator",
    "market sentiment", "macro outlook", "economic outlook",
    "interest rate outlook", "fed rate", "central bank",
]


def _build_company_tokens(ticker: str, company_name: str) -> List[str]:
    """
    Build a list of lowercase strings any of which, if present in an article
    title, confirms the article is about this specific company.

    Examples:
      ticker="ESLT", company_name="Elbit Systems"
      -> ["eslt", "elbit systems", "elbit"]

      ticker="BEZQ", company_name="Bezeq The Israeli Telecommunication"
      -> ["bezq", "bezeq the israeli telecommunication", "bezeq"]
    """
    tokens: List[str] = []
    if ticker:
        tokens.append(ticker.lower())
    if company_name:
        name = company_name.strip()
        tokens.append(name.lower())
        # First significant word (length > 3)
        first = next(
            (w for w in name.split() if len(w) > 3 and w.lower() not in
             {"the", "and", "for", "ltd", "inc", "corp", "plc", "llc", "co.", "co"}),
            None
        )
        if first and first.lower() not in tokens:
            tokens.append(first.lower())
    return tokens


def _is_non_article_url(url: str) -> bool:
    """Return True if the URL looks like a stock data page, profile, or list page."""
    if not url:
        return False
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path.lower().rstrip("/")
        if any(p in path for p in _NON_ARTICLE_URL_PATHS):
            return True
        if any(path.endswith(s) for s in _NON_ARTICLE_URL_SUFFIXES):
            return True
    except Exception:
        pass
    return False


def _is_company_relevant(art: ArticleImpact, tokens: List[str]) -> bool:
    """
    Return True if the article is relevant to the specific company.

    Logic (conservative — prefer keeping over silently dropping):
      1. If ticker or company name appears in the title -> relevant.
      2. If the article has a non-neutral sentiment signal -> the hybrid engine
         already determined it has directional impact on this stock -> relevant.
      3. If neither 1 nor 2: check for market-wide noise keywords in the title.
         Only remove if a market-wide keyword is found (positive identification
         of irrelevance, not just absence of company name).
    """
    title_lower = (art.title or "").lower()

    # Rule 1: company token in title
    if any(tok and tok in title_lower for tok in tokens):
        return True

    # Rule 2: non-neutral sentiment — classifier already tagged it as company-specific
    sentiment = art.sentiment or ""
    if sentiment in ("strong_bullish", "bullish", "bearish", "strong_bearish"):
        return True

    # Rule 3: only mark irrelevant if it's clearly market-wide noise
    if any(kw in title_lower for kw in _MARKET_WIDE_TITLE_KW):
        return False  # generic market article with no company signal

    # Default: keep (unknown relevance is not grounds for removal)
    return True


def filter_article_impacts(
    impacts: List[ArticleImpact],
    ticker: str = "",
    company_name: str = "",
    max_articles: int = 12,
    max_age_days: int = 90,
    min_impact_score: int = 2,
) -> Tuple[List[ArticleImpact], Dict[str, Any]]:
    """
    6-stage post-processing pipeline for stock-specific news articles.

    Stages (in order):
      1. Time filter          — drop articles older than *max_age_days* (90 days)
      2. Non-article pages    — drop stock-data/profile/list/forum URLs
      3. Company relevance    — drop clearly generic market-wide articles
      4. Impact filter        — drop articles with impact_score < *min_impact_score*
      5. Deduplication        — same-event articles: keep best source
      6. Sort + limit         — sort by quality, return top *max_articles* (12)

    MAYA filings: completely separate pipeline, never passed here.
    Sector news:  separate pipeline, not filtered here.

    Returns
    -------
    (filtered_list, metadata_dict)
      metadata keys:
        original_count, kept_count, removed_count,
        breakdown: {too_old, non_article_page, not_company_specific,
                    low_impact, duplicate}
    """
    now    = datetime.now()
    cutoff = now - timedelta(days=max_age_days)
    tokens = _build_company_tokens(ticker, company_name)

    original_count = len(impacts)
    breakdown: Dict[str, int] = {
        "too_old":              0,
        "non_article_page":     0,
        "not_company_specific": 0,
        "low_impact":           0,
        "duplicate":            0,
    }

    # ── Stage 1: Time filter ──────────────────────────────────────────────────
    after_time: List[ArticleImpact] = []
    for art in impacts:
        dt = _article_pub_dt(art.published)
        if dt is None:
            after_time.append(art)   # no date — keep (safer than silently dropping)
        elif dt >= cutoff:
            after_time.append(art)
        else:
            breakdown["too_old"] += 1

    # ── Stage 2: Non-article page filter ─────────────────────────────────────
    after_url: List[ArticleImpact] = []
    for art in after_time:
        if _is_non_article_url(art.url):
            breakdown["non_article_page"] += 1
        else:
            after_url.append(art)

    # ── Stage 3: Company relevance filter ────────────────────────────────────
    after_relevance: List[ArticleImpact] = []
    for art in after_url:
        if _is_company_relevant(art, tokens):
            after_relevance.append(art)
        else:
            breakdown["not_company_specific"] += 1

    # ── Stage 4: Impact filter ────────────────────────────────────────────────
    after_impact: List[ArticleImpact] = []
    for art in after_relevance:
        if art.impact_score >= min_impact_score:
            after_impact.append(art)
        else:
            breakdown["low_impact"] += 1

    # ── Stage 5: Deduplication ────────────────────────────────────────────────
    # Sort best-first so the highest-quality version of each story is kept.
    def _sort_key(a: ArticleImpact) -> tuple:
        dt = _article_pub_dt(a.published)
        return (a.impact_score, _source_credibility(a.source), dt.timestamp() if dt else 0.0)

    deduped: List[ArticleImpact] = []
    seen_fps: List[frozenset] = []
    for art in sorted(after_impact, key=_sort_key, reverse=True):
        fp = _title_fingerprint(art.title)
        is_dup = False
        if fp:
            for seen_fp in seen_fps:
                if seen_fp and len(fp & seen_fp) / max(len(fp), len(seen_fp)) >= 0.70:
                    is_dup = True
                    break
        if is_dup:
            breakdown["duplicate"] += 1
        else:
            seen_fps.append(fp)
            deduped.append(art)

    # ── Stage 6: Sort + limit ─────────────────────────────────────────────────
    # Already sorted best-first from Stage 5. Slice to cap.
    result = deduped[:max_articles]

    removed_count = original_count - len(result)
    meta: Dict[str, Any] = {
        "original_count": original_count,
        "kept_count":     len(result),
        "removed_count":  removed_count,
        "breakdown":      breakdown,
    }
    return result, meta
