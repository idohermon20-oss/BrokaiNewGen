"""
Data fetching layer.
Wraps yfinance to produce a clean StockData object and a
formatted text block ready for LLM consumption.
"""
from __future__ import annotations

import yfinance as yf
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

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
    impact: str          # "bullish" | "bearish" | "neutral"
    impact_summary: str  # 1–2 sentence explanation


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
    )


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
# Article impact assessment
# ---------------------------------------------------------------------------

def assess_article_impacts(
    article_contents: List[ArticleContent],
    recent_news: List[Dict[str, str]],
    ticker: str,
    company_name: str,
    client,
    config,
) -> List[ArticleImpact]:
    """
    Batch LLM call: assess the bullish/bearish/neutral impact of each
    recent article on the stock. Returns a list of ArticleImpact objects.
    """
    import json

    # Build merged list: prefer full article content, fall back to headline+summary
    items = []
    news_by_url = {n.get("url", ""): n for n in recent_news}

    for ac in article_contents:
        news = news_by_url.get(ac.url, {})
        items.append({
            "id": len(items),
            "title": ac.title or news.get("title", ""),
            "source": ac.publisher or news.get("publisher", ""),
            "published": "",
            "url": ac.url,
            "snippet": (ac.text or "")[:400],
        })

    # Pad with headlines that had no full content
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
                "snippet": n.get("summary", "")[:400],
            })
            seen_urls.add(url)

    if not items:
        return []

    batch_json = json.dumps(
        [{"id": it["id"], "title": it["title"], "source": it["source"], "snippet": it["snippet"]}
         for it in items],
        ensure_ascii=False,
    )

    prompt = f"""You are a senior equity analyst covering {ticker} ({company_name}).

Below are recent news articles about this company. For each article, assess its impact on the stock.

Articles:
{batch_json}

Return a JSON object with key "results", containing an array where each element has:
- "id": same id as input
- "impact": "bullish" / "bearish" / "neutral"
- "impact_summary": 1-2 sentences explaining the impact on {ticker} specifically

Be specific about why the article matters for the stock price. Return valid JSON only."""

    try:
        resp = client.chat.completions.create(
            model=config.models.agent,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        results = data.get("results", data.get("items", []))
        id_map = {r["id"]: r for r in results if "id" in r}
    except Exception:
        id_map = {}

    impacts: List[ArticleImpact] = []
    for it in items:
        info = id_map.get(it["id"], {})
        impacts.append(ArticleImpact(
            title=it["title"],
            url=it["url"],
            source=it["source"],
            published=it["published"],
            impact=info.get("impact", "neutral"),
            impact_summary=info.get("impact_summary", ""),
        ))
    return impacts
