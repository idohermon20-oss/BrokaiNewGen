"""
Q&A Pipeline — two-LLM-call pattern for natural-language stock questions.

Call 1: LLMAnalyst.plan_intent()  → {ticker, intent, tools, language}
Call 2: Execute tool registry     → context string
Call 3: LLMAnalyst.chat_answer()  → plain-text answer

All tools are Playwright-free — safe to call from the bot daemon thread.
Maya / Chrome news data reaches the bot only through the shared state dict,
which the main research thread populates every 15 minutes.
"""

from __future__ import annotations

import json
import time
import traceback

from ..config import OPENAI_API_KEY, OPENAI_MODEL
from ..analysis.llm import LLMAnalyst
from ..analysis.memory import StockMemoryManager

# ── Compact ticker → company map injected into the intent prompt ──────────────
_KNOWN_TICKERS: dict[str, str] = {
    "TEVA":  "Teva Pharmaceutical / טבע תעשיות",
    "ESLT":  "Elbit Systems / אלביט מערכות",
    "NICE":  "NICE Systems / נייס מערכות",
    "ICL":   "ICL Group / כיל",
    "NVMI":  "Nova Ltd / נובה",
    "TSEM":  "Tower Semiconductor / תאגיד מוליכים למחצה",
    "CAMT":  "Camtek / קמטק",
    "AUDC":  "AudioCodes / אודיוקודס",
    "LUMI":  "Bank Leumi / בנק לאומי",
    "POLI":  "Bank Hapoalim / בנק הפועלים",
    "MZTF":  "Mizrahi-Tefahot / בנק מזרחי טפחות",
    "DSCT":  "Israel Discount Bank / בנק דיסקונט",
    "FIBI":  "First International Bank / הבנק הבינלאומי",
    "AZRG":  "Azrieli Group / קבוצת עזריאלי",
    "AMOT":  "Amot Investments / עמות",
    "BIG":   "BIG Shopping Centers / ביג",
    "BEZQ":  "Bezeq / בזק",
    "PTNR":  "Partner Communications / פרטנר",
    "CEL":   "Cellcom / סלקום",
    "DLEKG": "Delek Group / קבוצת דלק",
    "ENLT":  "Enlight Renewable / אנלייט",
    "ORL":   "Oil Refineries / בתי זיקוק לנפט",
    "PAZ":   "Paz Oil / פז",
    "NWMD":  "NewMed Energy / ניו-מד אנרגיה",
    "PHOE":  "Phoenix Holdings / הפניקס",
    "HARL":  "Harel Insurance / הראל",
    "CLIS":  "Clal Insurance / כלל ביטוח",
    "NXSN":  "NextVision / נקסטוויז'ן",
    "KMDA":  "Kamada / קמדה",
    "ALLT":  "Allot / אלוט",
    "SAE":   "Shufersal / שופרסל",
    "STRS":  "Strauss Group / שטראוס",
    "MTRX":  "Matrix IT / מטריקס",
}

_TICKER_LIST_TEXT = "\n".join(f"  {k}: {v}" for k, v in _KNOWN_TICKERS.items())


def _build_dynamic_ticker_list(state: dict) -> str:
    """
    Build ticker → company name reference by merging:
      1. Hardcoded _KNOWN_TICKERS (curated, always first)
      2. All stocks tracked in stock_memory that have a company_name stored
         (grows automatically as the research cycle processes more stocks)
    Capped at 200 entries to stay within the intent-prompt token budget.
    """
    lines: list[str] = list(_KNOWN_TICKERS.items())   # (ticker, name) tuples
    seen = set(_KNOWN_TICKERS)

    for tkr, entry in state.get("stock_memory", {}).items():
        if tkr in seen or tkr.startswith("TASE"):
            continue
        company = entry.get("company_name", "")
        if company:
            lines.append((tkr, company))
            seen.add(tkr)
        if len(lines) >= 200:
            break

    return "\n".join(f"  {k}: {v}" for k, v in lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sig_get(s, key: str, default="") -> str:
    """Read a field from a Signal object or a dict (state JSON round-trip)."""
    if isinstance(s, dict):
        return s.get(key, default) or default
    return getattr(s, key, default) or default


def _format_signal(s) -> str:
    ticker   = _sig_get(s, "ticker")
    sig_type = _sig_get(s, "signal_type")
    headline = _sig_get(s, "headline")
    detail   = _sig_get(s, "detail")
    ts       = _sig_get(s, "timestamp")[:10]
    line = f"• [{sig_type}] {ticker} — {headline} ({ts})"
    if detail:
        line += f"\n  {detail[:200]}"
    return line


# ══════════════════════════════════════════════════════════════════════════════
# Tool implementations — all Playwright-free
# ══════════════════════════════════════════════════════════════════════════════

def _tool_macro(_ticker: str | None, _state: dict) -> str:
    """Live macro snapshot: TA-125, S&P500, USD/ILS, VIX, oil, US10Y."""
    try:
        from ..sources.market import MacroContext
        return MacroContext().get()
    except Exception as e:
        return f"[macro error: {e}]"


def _tool_sector(_ticker: str | None, _state: dict) -> str:
    """TASE sector rotation: BULL+/BULL/NEUTRAL/BEAR/BEAR- for all sectors with RSI + 1M return."""
    try:
        from ..sources.market import SectorAnalyzer
        return SectorAnalyzer().get_sector_context()
    except Exception as e:
        return f"[sector error: {e}]"


def _tool_stock_data(ticker: str | None, state: dict) -> str:
    """
    Deep technical + fundamental snapshot for a specific ticker:
    RSI-14, MA-20, MA-50, MA trend, last price, 52w high/low, market cap,
    revenue growth, net income growth, avg volume.
    Requires a known ticker symbol.
    """
    if not ticker:
        return ""
    try:
        from ..sources.market import DeepStockAnalyzer
        ticker_yf = ticker + ".TA" if not ticker.endswith(".TA") else ticker
        data = DeepStockAnalyzer().analyze(ticker_yf)
        if not data or not any(data.get(k) for k in ("rsi_14", "last_price", "market_cap")):
            return (
                f"Yahoo Finance has no live price data for {ticker}.TA — "
                f"the stock may be thinly traded, recently listed, or use a different ticker format. "
                f"Check news, Maya filings, and researcher memory for available signals."
            )

        # Format as human-readable text so LLM can cite numbers naturally
        company = (
            _KNOWN_TICKERS.get(ticker)
            or state.get("_bot_resolved_company")
            or state.get("stock_memory", {}).get(ticker, {}).get("company_name")
            or ticker
        )

        rsi      = data.get("rsi_14", "?")
        trend    = data.get("ma_trend", "?")
        price    = data.get("last_price", "?")
        vs52     = data.get("pct_vs_52w_high", "?")
        hi52     = data.get("52w_high", "?")
        lo52     = data.get("52w_low", "?")
        cap      = data.get("market_cap")
        rev      = data.get("revenue_growth_pct", "?")
        inc      = data.get("income_growth_pct", "?")
        vol      = data.get("avg_volume", "?")
        day_chg  = data.get("today_change_pct")

        cap_str = f"₪{cap/1e9:.1f}B" if cap and cap >= 1e9 else (f"₪{cap/1e6:.0f}M" if cap else "?")

        rsi_label = ""
        try:
            rv = float(rsi)
            if rv < 30:   rsi_label = " — OVERSOLD"
            elif rv > 70: rsi_label = " — OVERBOUGHT"
            else:          rsi_label = " — neutral"
        except Exception:
            pass

        vol_str = f"{int(vol):,}" if vol and vol != "?" else "?"

        day_str = ""
        if day_chg is not None:
            sign = "+" if day_chg >= 0 else ""
            day_str = f"  ({sign}{day_chg:.2f}% today)"

        lines = [
            f"Live Data — {ticker} ({company}):",
            f"  Price: ₪{price}{day_str}  |  52w range: ₪{lo52} – ₪{hi52}  ({vs52}% from high)",
            f"  RSI-14: {rsi}{rsi_label}  |  MA trend: {trend}",
            f"  Market cap: {cap_str}",
            f"  Revenue growth: {rev}%  |  Net income growth: {inc}%",
            f"  Avg daily volume: {vol_str} shares",
        ]

        # Period returns — separate 1y fetch so we can answer "how much did it go up?"
        try:
            import yfinance as yf
            hist = yf.Ticker(ticker_yf).history(period="1y", interval="1d")
            c = hist["Close"]
            if len(c) >= 5:
                def _ret(n: int) -> str:
                    return f"{(c.iloc[-1] / c.iloc[-n] - 1) * 100:+.1f}%" if len(c) >= n else "n/a"
                ret_parts = [f"1W {_ret(5)}", f"1M {_ret(21)}"]
                if len(c) >= 63:
                    ret_parts.append(f"3M {_ret(63)}")
                if len(c) >= 200:
                    ret_parts.append(f"1Y {_ret(252)}")
                lines.append(f"  Returns: {' | '.join(ret_parts)}")
        except Exception:
            pass

        # Valuation multiples + upcoming earnings date (yfinance .info — bot only, ~1-2s)
        try:
            import yfinance as yf
            info = yf.Ticker(ticker_yf).info
            val_parts = []
            pe_t = info.get("trailingPE")
            pe_f = info.get("forwardPE")
            pb   = info.get("priceToBook")
            div  = info.get("dividendYield")
            beta = info.get("beta")
            if pe_t and pe_t > 0:  val_parts.append(f"P/E {pe_t:.1f}×")
            if pe_f and pe_f > 0:  val_parts.append(f"Fwd P/E {pe_f:.1f}×")
            if pb   and pb   > 0:  val_parts.append(f"P/B {pb:.2f}×")
            if div  and div  > 0:  val_parts.append(f"Div yield {div*100:.1f}%")
            if beta is not None:   val_parts.append(f"Beta {beta:.2f}")
            if val_parts:
                lines.append(f"  Valuation: {' | '.join(val_parts)}")

            # Upcoming earnings date
            earn_date = info.get("earningsDate") or info.get("earningsTimestamp")
            if earn_date:
                import datetime
                if isinstance(earn_date, (int, float)):
                    earn_date = datetime.datetime.fromtimestamp(earn_date).strftime("%Y-%m-%d")
                elif hasattr(earn_date, "strftime"):
                    earn_date = earn_date.strftime("%Y-%m-%d")
                lines.append(f"  Next earnings (yfinance): {earn_date}")
        except Exception:
            pass

        # Also look up earnings date from researcher state (Maya EarningsCalendar signals)
        try:
            weekly = state.get("weekly_signals", [])
            bare = ticker.replace(".TA", "").upper()
            earn_sigs = [
                s for s in weekly
                if _sig_get(s, "signal_type") == "earnings_calendar"
                and bare in _sig_get(s, "ticker").replace(".TA", "").upper()
            ]
            if earn_sigs:
                ev = earn_sigs[0]
                ev_date = _sig_get(ev, "event_date") or _sig_get(ev, "detail")[:10]
                lines.append(f"  Next earnings (Maya calendar): {ev_date} — {_sig_get(ev, 'headline')}")
        except Exception:
            pass

        return "\n".join(lines)
    except Exception as e:
        return f"[stock_data error for {ticker}: {e}]"


def _tool_web_news(ticker: str | None, state: dict) -> str:
    """
    Live Google News RSS search for a specific ticker/company.
    Returns up to 8 recent article titles + snippets.
    Best for: breaking news, latest announcements not yet in state.
    """
    if not ticker:
        return ""
    try:
        from ..sources.web_news import WebNewsSearcher
        # Prefer: known map → LLM-resolved company name → memory-stored name → ticker as fallback
        company_name = (
            _KNOWN_TICKERS.get(ticker)
            or state.get("_bot_resolved_company")
            or state.get("stock_memory", {}).get(ticker, {}).get("company_name")
            or ticker
        )
        articles = WebNewsSearcher().search_ticker(ticker, company_name)
        if not articles:
            return f"No recent news found for {ticker}."
        lines = [f"- {a.get('title', '')}: {a.get('snippet', '')}" for a in articles[:8]]
        return "\n".join(lines)
    except Exception as e:
        return f"[web_news error for {ticker}: {e}]"


def _tool_memory(ticker: str | None, state: dict) -> str:
    """
    Researcher's accumulated memory for a ticker:
    analyst notes (current + prior week), LLM sentiment, risk flag,
    watch-for trigger, signal history, cached fundamentals, Maya history, recent headlines.
    Best for: understanding the full ongoing thesis and what changed recently.
    """
    try:
        mem = StockMemoryManager(state)
        if ticker:
            # Use full briefing for rich, structured LLM context
            briefing = mem.get_full_briefing(ticker)
            return briefing or f"No accumulated memory for {ticker} yet. Research cycle may not have processed this stock."
        # No ticker — list all tracked tickers with their sentiment
        stock_memory = state.get("stock_memory", {})
        if not stock_memory:
            return "No stock memory yet — research cycle hasn't run."
        lines = []
        for tkr, entry in sorted(stock_memory.items())[:30]:
            sentiment = entry.get("llm_sentiment", "neutral")
            note = entry.get("llm_memory_note", "")[:80]
            last = entry.get("signal_history", [{}])[-1].get("date", "?") if entry.get("signal_history") else "?"
            company = entry.get("company_name", "")
            company_str = f" ({company})" if company else ""
            lines.append(f"• {tkr}{company_str} [{sentiment}] last seen {last} — {note}")
        return "Tracked stocks with analyst sentiment:\n" + "\n".join(lines)
    except Exception as e:
        return f"[memory error: {e}]"


def _tool_weekly_signals(ticker: str | None, state: dict) -> str:
    """
    All signals the research cycle collected THIS WEEK for a specific ticker —
    or the top-20 highest-scoring signals across all tickers if no ticker given.
    Shows signal type, headline, detail, score. Directly exposes what the
    researcher pipeline found (Maya filings, volume spikes, news, technicals).
    """
    try:
        weekly = state.get("weekly_signals", [])
        if not weekly:
            return "No weekly signals yet — research cycle hasn't run."

        if ticker:
            bare = ticker.replace(".TA", "").upper()
            matching = [
                s for s in weekly
                if bare in _sig_get(s, "ticker").replace(".TA", "").upper()
            ]
            if not matching:
                return f"No signals found for {ticker} this week."
            lines = [f"Signals for {ticker} this week ({len(matching)} total):"]
            for s in matching[:20]:
                lines.append(_format_signal(s))
            return "\n".join(lines)
        else:
            # Return top-20 by base_score, across all tickers
            def _score(s):
                return float(_sig_get(s, "score") or 0)
            top = sorted(weekly, key=_score, reverse=True)[:20]
            lines = [f"Top signals this week ({len(weekly)} total collected):"]
            for s in top:
                lines.append(_format_signal(s))
            return "\n".join(lines)
    except Exception as e:
        return f"[weekly_signals error: {e}]"


def _tool_maya_filings(ticker: str | None, state: dict) -> str:
    """
    Maya regulatory filing signals from TASE disclosure system collected this week.
    Covers: IPOs, earnings reports, institutional filings, contracts, buybacks,
    dividends, M&A, management changes. These are ground-truth regulatory events —
    highest-credibility signals before the news cycle picks them up.
    Can filter by ticker or return all recent filings.
    """
    try:
        MAYA_TYPES = {
            "maya_ipo", "maya_spinoff", "maya_ma", "maya_contract",
            "maya_buyback", "maya_institutional", "maya_earnings",
            "maya_dividend", "maya_rights", "maya_management", "maya_filing",
        }
        weekly = state.get("weekly_signals", [])
        filings = [s for s in weekly if _sig_get(s, "signal_type") in MAYA_TYPES]

        if ticker:
            bare = ticker.replace(".TA", "").upper()
            filings = [
                s for s in filings
                if bare in _sig_get(s, "ticker").replace(".TA", "").upper()
            ]
            if not filings:
                return f"No Maya filings found for {ticker} this week."
            lines = [f"Maya filings for {ticker} ({len(filings)}):"]
        else:
            if not filings:
                return "No Maya filings collected this week yet."
            # Sort by type priority: ipo > ma > contract > institutional > earnings > rest
            _priority = {"maya_ipo": 0, "maya_ma": 1, "maya_contract": 2,
                         "maya_institutional": 3, "maya_earnings": 4}
            filings = sorted(filings, key=lambda s: _priority.get(_sig_get(s, "signal_type"), 9))[:20]
            lines = [f"Recent Maya filings ({len(filings)} shown):"]

        for s in filings[:20]:
            lines.append(_format_signal(s))
        return "\n".join(lines)
    except Exception as e:
        return f"[maya_filings error: {e}]"


def _tool_alerted_stocks(_ticker: str | None, state: dict) -> str:
    """
    Stocks the researcher already recommended/alerted on today and the current
    stock-of-the-week pick. Shows scores, rationale, and key catalysts from
    the manager LLM's arbitration output. Best for: "what should I buy today?"
    """
    try:
        lines = []

        # Stock of the week
        report = state.get("last_arbitration_report", {})
        if report:
            sotw = report.get("stock_of_the_week", {})
            if sotw:
                ticker   = sotw.get("ticker", "?")
                name     = sotw.get("name", "")
                score    = sotw.get("score", 0)
                catalyst = sotw.get("key_catalyst", "")
                rationale= (sotw.get("full_rationale") or "")[:300]
                risk     = sotw.get("main_risk", "")
                lines.append(f"★ Stock of the week: {ticker}.TA — {name} (score {score}/100)")
                if catalyst:
                    lines.append(f"  Key catalyst: {catalyst}")
                if rationale:
                    lines.append(f"  Rationale: {rationale}")
                if risk:
                    lines.append(f"  Main risk: {risk}")

            runners = report.get("runners_up", [])
            if runners:
                lines.append("\nRunners-up:")
                for r in runners[:2]:
                    lines.append(
                        f"  • {r.get('ticker')}.TA — {r.get('name')} "
                        f"(score {r.get('score')}) | {r.get('key_catalyst','')}"
                    )

        # Alerted today
        alerted = {t: d for t, d in state.get("alerted_today", {}).items()}
        if alerted:
            lines.append(f"\nAlerted today: {', '.join(alerted.keys())}")

        if not lines:
            return "No stock recommendations yet — research cycle hasn't completed arbitration."
        return "\n".join(lines)
    except Exception as e:
        return f"[alerted_stocks error: {e}]"


def _tool_live_scan(ticker: str | None, _state: dict) -> str:
    """
    Run a real-time MarketAnomalyDetector scan on a specific ticker RIGHT NOW
    using live Yahoo Finance data. Detects: volume spike, price move, 52w breakout,
    oversold bounce, 52w low reversal, consecutive momentum, relative strength.
    Best for: 'Is anything happening with X right now?' type questions.
    Requires a known .TA ticker. Takes ~5 seconds.
    """
    if not ticker:
        return ""
    try:
        from ..sources.market import MarketAnomalyDetector
        ticker_yf = ticker + ".TA" if not ticker.endswith(".TA") else ticker
        detector = MarketAnomalyDetector([ticker_yf])
        signals = detector.scan_universe(
            sample_size=1,
            priority_tickers=[ticker_yf],
        )
        if not signals:
            return f"No anomalies detected for {ticker} right now (no volume spike, price move, or technical trigger)."
        lines = [f"Live scan results for {ticker}:"]
        for s in signals:
            lines.append(f"  [{s.signal_type}] {s.headline}")
            if s.detail:
                lines.append(f"    {s.detail}")
        return "\n".join(lines)
    except Exception as e:
        return f"[live_scan error for {ticker}: {e}]"


def _tool_recent_ipos(_ticker: str | None, state: dict) -> str:
    """
    IPO and new-listing signals collected by the researcher from Maya filings this week.
    Covers: new prospectuses, first-day listings, rights issues filed on TASE.
    Data comes from the research cycle — no Playwright required.
    """
    try:
        weekly = state.get("weekly_signals", [])
        ipos = [
            s for s in weekly
            if _sig_get(s, "signal_type") in ("maya_ipo", "ipo", "maya_spinoff")
        ]
        if not ipos:
            return (
                "No IPO or new-listing signals found this week. "
                "Maya filings are collected every 15 minutes — try again after the next research cycle."
            )
        lines = [f"IPO / new listing signals this week ({len(ipos)}):"]
        for s in ipos[:15]:
            lines.append(_format_signal(s))
        return "\n".join(lines)
    except Exception as e:
        return f"[recent_ipos error: {e}]"


def _tool_tracked_stocks(_ticker: str | None, state: dict) -> str:
    """
    All stocks currently in the researcher's memory with their LLM-assigned sentiment,
    best score this cycle, risk flag, and what to watch for next.
    Best for: 'What stocks are you tracking?', 'Show me all bullish stocks',
    'Which stocks have the highest scores?'
    """
    try:
        stock_memory = state.get("stock_memory", {})
        if not stock_memory:
            return "No stocks tracked yet — research cycle hasn't run."

        # Build rows: (ticker, company, sentiment, best_score, note, watch)
        rows = []
        for tkr, entry in stock_memory.items():
            history = entry.get("signal_history", [])
            best_score = max((h.get("final_score", 0) for h in history), default=0) if history else 0
            sentiment  = entry.get("llm_sentiment", "neutral")
            note       = entry.get("llm_memory_note", "")[:100]
            watch      = entry.get("llm_watch_for", "")[:80]
            company    = entry.get("company_name", "")
            rows.append((tkr, company, sentiment, best_score, note, watch))

        # Sort: bullish first, then by best_score desc
        _order = {"bullish": 0, "neutral": 1, "bearish": 2}
        rows.sort(key=lambda r: (_order.get(r[2], 1), -r[3]))

        lines = [f"Tracked stocks ({len(rows)} total):"]
        for tkr, company, sentiment, score, note, watch in rows[:40]:
            company_str = f" ({company})" if company else ""
            line = f"• {tkr}{company_str} [{sentiment}] score={score:.0f}"
            if note:
                line += f" — {note}"
            if watch:
                line += f" | Watch: {watch}"
            lines.append(line)
        return "\n".join(lines)
    except Exception as e:
        return f"[tracked_stocks error: {e}]"


def _tool_maya_history(ticker: str | None, state: dict) -> str:
    """
    Maya regulatory filing history for a specific stock, accumulated across all research cycles.
    Shows IPO prospectus, earnings reports, contract filings, institutional changes,
    buybacks, dividends, management changes — in reverse chronological order.
    Best for: understanding a company's full regulatory timeline on TASE.
    Requires a known ticker. History grows with each research cycle.
    """
    if not ticker:
        return "Please specify a ticker to get Maya filing history."
    try:
        mem     = StockMemoryManager(state)
        history = mem.get_maya_history(ticker)
        if not history:
            return (
                f"No Maya filing history found for {ticker} yet. "
                "History is built up as Maya filings arrive each research cycle."
            )
        lines = [f"Maya filing history for {ticker} ({len(history)} entries, newest first):"]
        for h in history[:20]:
            date     = h.get("date", "?")
            ftype    = h.get("type", "?")
            company  = h.get("company", "")
            headline = h.get("headline", "")
            detail   = h.get("detail", "")
            entry = f"• [{date}] {ftype}"
            if company:
                entry += f" — {company}"
            entry += f": {headline}"
            if detail:
                entry += f"\n  {detail[:180]}"
            lines.append(entry)
        return "\n".join(lines)
    except Exception as e:
        return f"[maya_history error for {ticker}: {e}]"


def _tool_user_alerts(_ticker: str | None, state: dict) -> str:
    """
    Lists the user's active custom alert rules (for THIS chat only).
    Shows alert type, target ticker/company, creation date, and how many times each fired.
    Use this when the user asks 'what alerts do I have set?' or 'show my alerts'.
    Does NOT require a ticker.
    """
    try:
        from .user_alerts import get_alerts_for_chat
        chat_id = state.get("_bot_chat_id", "")
        if not chat_id:
            return "Cannot identify chat — no alerts to show."
        alerts = get_alerts_for_chat(chat_id)
        if not alerts:
            return (
                "You have no custom alerts set.\n"
                "Use /alert_add to create one. For example:\n"
                "  /alert_add ipo — alert on any new IPO\n"
                "  /alert_add earnings TEVA — alert when TEVA publishes earnings\n"
                "  /alert_add maya_filing ESLT — any Maya filing for Elbit"
            )
        lines = [f"Your active alerts ({len(alerts)}):"]
        for a in alerts:
            target = f" → {a.ticker or a.company_name}" if (a.ticker or a.company_name) else ""
            lines.append(
                f"• [{a.alert_id}] {a.alert_type.upper()}{target} "
                f"(fired {len(a.seen_signal_keys)}× | since {a.created_at[:10]})"
            )
        lines.append("\nTo delete: /alert_del <id>")
        return "\n".join(lines)
    except Exception as e:
        return f"[user_alerts error: {e}]"


def _tool_ipo_watchlist(_ticker: str | None, state: dict) -> str:
    """
    All IPO and new-listing activity tracked by the researcher:
    - Maya IPO / spinoff filings from this week (ground-truth from TASE disclosures)
    - IPO entries stored in researcher memory from previous cycles
    Best for: 'What new companies are listing on TASE?', 'Any IPOs this week?'
    Does NOT require a ticker.
    """
    try:
        lines = []

        # Current week Maya IPO signals
        weekly = state.get("weekly_signals", [])
        ipo_signals = [
            s for s in weekly
            if _sig_get(s, "signal_type") in ("maya_ipo", "ipo", "maya_spinoff")
        ]
        if ipo_signals:
            lines.append(f"IPO / new-listing signals this week ({len(ipo_signals)}):")
            for s in ipo_signals[:10]:
                lines.append(_format_signal(s))
        else:
            lines.append("No new IPO signals found this week yet.")

        # Historical IPO memory (companies that had maya_ipo signals in prior cycles)
        stock_memory = state.get("stock_memory", {})
        ipo_memory = []
        for ticker, entry in stock_memory.items():
            maya_hist = entry.get("maya_history", [])
            ipo_entries = [h for h in maya_hist if h.get("type") in ("maya_ipo", "ipo", "maya_spinoff")]
            if ipo_entries:
                latest = ipo_entries[0]   # already newest-first
                ipo_memory.append((ticker, entry.get("company_name") or ticker, latest))

        if ipo_memory:
            lines.append(f"\nIPO companies tracked in memory ({len(ipo_memory)}):")
            for ticker, company, latest in ipo_memory[:10]:
                lines.append(f"• {ticker} — {company} | Filed: {latest.get('date', '?')} | {latest.get('headline', '')}")

        return "\n".join(lines) if lines else "No IPO data available yet."
    except Exception as e:
        return f"[ipo_watchlist error: {e}]"


# ── Tool registry ─────────────────────────────────────────────────────────────

_TOOL_REGISTRY: dict[str, callable] = {
    # Market data (live yfinance)
    "get_macro":          _tool_macro,
    "get_sector_context": _tool_sector,
    "get_stock_data":     _tool_stock_data,
    "run_live_scan":      _tool_live_scan,
    # News (live Google News RSS)
    "search_news":        _tool_web_news,
    # Researcher state (populated by main research cycle every 15 min)
    "get_weekly_signals": _tool_weekly_signals,
    "get_maya_filings":   _tool_maya_filings,
    "get_alerted_stocks": _tool_alerted_stocks,
    "get_recent_ipos":    _tool_recent_ipos,
    "get_tracked_stocks": _tool_tracked_stocks,
    "get_memory":         _tool_memory,
    # Maya history + custom alerts
    "get_maya_history":   _tool_maya_history,
    "get_user_alerts":    _tool_user_alerts,
    "get_ipo_watchlist":  _tool_ipo_watchlist,
}

# Full tool catalogue injected into the intent prompt
TOOL_CATALOGUE = """
Available tools (pick 1–4 that best answer the question):

LIVE MARKET DATA (calls Yahoo Finance now):
  get_macro          — TA-125, S&P500, USD/ILS, VIX, oil, US10Y snapshot
  get_sector_context — BULL+/BULL/NEUTRAL/BEAR/BEAR- for all TASE sectors + RSI + 1M return
  get_stock_data     — Deep technicals + fundamentals for ONE ticker (RSI, MAs, market cap, revenue growth)
  run_live_scan      — Real-time anomaly scan for ONE ticker (volume spike, breakout, oversold, momentum)

LIVE NEWS (Google News RSS):
  search_news        — Latest news articles for ONE ticker/company (titles + snippets)

RESEARCHER STATE (populated by main cycle every 15 min — no network call needed):
  get_weekly_signals — All signals collected THIS WEEK for a ticker (or top-20 across all tickers)
  get_maya_filings   — Maya TASE regulatory filings this week (IPOs, contracts, institutional, earnings)
  get_alerted_stocks — Today's buy recommendations + Stock of the Week from manager LLM
  get_recent_ipos    — New IPO / new listing signals from Maya filings this week
  get_tracked_stocks — All stocks in researcher memory with sentiment, score, risk, watch-for
  get_memory         — Deep analyst memory for ONE ticker (notes, sentiment, risk flag, signal history)

RESEARCHER STATE (cont.):
  get_maya_history   — Full Maya regulatory filing history for ONE ticker across all past cycles (IPO, earnings, contracts...)
  get_user_alerts    — List the user's own custom alert rules set via /alert_add (for THIS chat)
  get_ipo_watchlist  — All IPO / new-listing activity tracked by the researcher (this week + memory)

SELECTION RULES:
  • Stock-specific question      → get_stock_data + search_news + get_memory + get_weekly_signals + get_maya_filings
                                   (+ run_live_scan if asking about right NOW)
  • "What to buy today"          → get_alerted_stocks + get_macro
  • Market overview              → get_macro + get_sector_context
  • Sector question              → get_sector_context + get_macro
  • IPO / new listings           → get_ipo_watchlist + get_macro
  • Maya filings / news          → get_maya_filings (+ get_memory if ticker known)
  • Filing HISTORY for a stock   → get_maya_history (best for "what has TEVA filed over time?")
  • "What is the researcher tracking" → get_tracked_stocks
  • "What happened this week"    → get_weekly_signals + get_alerted_stocks
  • Real-time anomaly check      → run_live_scan + get_stock_data + get_memory
  • "Show my alerts / what alerts do I have" → get_user_alerts
"""


# ── QAPipeline ────────────────────────────────────────────────────────────────

# Intent types that require a resolved ticker to be useful
_STOCK_INTENTS = {"stock_analysis", "live_scan", "earnings_query"}

# Canonical tool sets per intent — used as hard fallback when the LLM omits tools
# or mistakenly returns direct_answer for a data question.
_INTENT_REQUIRED_TOOLS: dict[str, list[str]] = {
    "stock_analysis":  ["get_stock_data", "search_news", "get_memory", "get_weekly_signals", "get_maya_filings"],
    "live_scan":       ["run_live_scan", "get_stock_data", "get_memory"],
    "earnings_query":  ["get_weekly_signals", "get_stock_data", "get_memory"],
    "market_overview": ["get_macro", "get_sector_context"],
    "sector_query":    ["get_sector_context", "get_macro"],
    "ipo_query":       ["get_ipo_watchlist", "get_macro"],
    "maya_query":      ["get_maya_filings"],
    "maya_history":    ["get_maya_history"],
    "recommendations": ["get_alerted_stocks", "get_macro"],
    "tracker_query":   ["get_tracked_stocks"],
    "alert_query":     ["get_user_alerts"],
    "general_question":["get_macro"],
}


class QAPipeline:
    def __init__(self, state: dict):
        self._state = state
        self._llm   = LLMAnalyst(OPENAI_API_KEY, OPENAI_MODEL)
        # Build ticker reference dynamically — grows as research cycle tracks more stocks
        self._ticker_list = _build_dynamic_ticker_list(state)

    def answer(self, question: str, history: list | None = None):
        """Full Q&A pipeline.
        Returns:
          - str: plain-text answer (normal case)
          - dict with key "_pending_action": action data dict — bot must ask user to confirm
        history: list of {role, content} dicts (last N messages from this chat).
        """
        # Call 1: intent + tool plan
        try:
            plan = self._llm.plan_intent(question, self._ticker_list, TOOL_CATALOGUE,
                                         history=history)
        except Exception:
            print("[QA] plan_intent error:", traceback.format_exc())
            plan = {
                "ticker": None,
                "intent": "general_question",
                "tools": ["get_macro"],
                "language": "en",
            }

        ticker   = plan.get("ticker")
        intent   = plan.get("intent", "general_question")
        # Preserve empty list explicitly — do NOT let [] fall through to ["get_macro"]
        # (plan_intent returns [] for direct_answer; None means it was missing entirely)
        raw_tools = plan.get("tools")
        tools     = raw_tools if raw_tools is not None else ["get_macro"]
        language  = plan.get("language", "en")

        # Hebrew heuristic — force Hebrew if message contains Hebrew chars
        if any("\u05d0" <= c <= "\u05ea" for c in question):
            language = "he"

        # ── Action intent: user wants to SET/DELETE an alert or change settings ──
        # Parse action parameters with a dedicated LLM call, then return a
        # pending-action dict so BotServer can ask the user to confirm.
        if intent == "action_intent":
            return self._handle_action_intent(question, ticker, language)

        # ── Safeguard: direct_answer + resolved ticker is almost always wrong ──
        # "What is Teva's RSI?" → plan_intent might return direct_answer because
        # it thinks it knows from training data. But live data is always better.
        # Override to stock_analysis and force the full tool set.
        if intent == "direct_answer" and ticker:
            print(f"[QA] direct_answer override → stock_analysis (ticker={ticker})")
            intent = "stock_analysis"
            tools  = list(_INTENT_REQUIRED_TOOLS["stock_analysis"])

        # ── Hebrew ticker resolution ──────────────────────────────────────────
        # When the user mentioned a company by Hebrew name and plan_intent
        # didn't recognise the ticker, ask the LLM with the full TASE company list.
        if not ticker and intent in _STOCK_INTENTS:
            ticker, resolved_company = self._resolve_ticker_from_state(question)
            if ticker:
                print(f"[QA] Hebrew resolution: '{resolved_company}' → {ticker}")
                self._state["_bot_resolved_company"] = resolved_company
            else:
                self._state["_bot_resolved_company"] = None

        # ── Enforce full context for stock questions ──────────────────────────
        # For any stock-specific intent with a resolved ticker, always include the
        # complete set of context tools so the LLM has all available knowledge:
        # live technicals + news + analyst memory + this week's signals + Maya filings.
        # get_weekly_signals and get_maya_filings are pure state reads (no network call).
        if ticker and intent in _STOCK_INTENTS | {"maya_query", "earnings_query"}:
            for must in _INTENT_REQUIRED_TOOLS.get("stock_analysis", []):
                if must not in tools:
                    tools.append(must)

        # Validate tool names against registry (direct_answer → empty list stays empty)
        tools = [t for t in tools if t in _TOOL_REGISTRY]

        # ── Safeguard: data intent with no valid tools → use canonical defaults ──
        if not tools and intent in _INTENT_REQUIRED_TOOLS:
            tools = list(_INTENT_REQUIRED_TOOLS[intent])
            print(f"[QA] empty tools safeguard → {tools}")
        elif not tools and intent != "direct_answer":
            tools = ["get_macro"]

        print(f"[QA] intent={intent} ticker={ticker} tools={tools or '[]'} lang={language}")

        # Call 2: run tools sequentially (skipped entirely for direct_answer)
        context_parts: list[str] = []
        for tool_name in tools:
            fn = _TOOL_REGISTRY[tool_name]
            try:
                result = fn(ticker, self._state)
                if result:
                    context_parts.append(f"[{tool_name}]\n{result}")
            except Exception:
                print(f"[QA] tool {tool_name} error:", traceback.format_exc())
            time.sleep(0.3)   # yfinance rate limit between calls

        context = "\n\n".join(context_parts) if context_parts else ""

        # Call 3: synthesis (with conversation history for continuity)
        try:
            return self._llm.chat_answer(question, context, language, history=history or [])
        except Exception:
            print("[QA] chat_answer error:", traceback.format_exc())
            if language == "he":
                return "מצטער, אירעה שגיאה בניתוח. נסה שנית."
            return "Sorry, an error occurred during analysis. Please try again."

    def _handle_action_intent(self, question: str, ticker: str | None, language: str) -> dict:
        """
        Parse an action request (add/delete alert) and return a pending-action dict.
        BotServer will send the confirm_message and wait for the user's yes/no.
        """
        try:
            action = self._llm.parse_action_intent(question, self._ticker_list)
        except Exception:
            print("[QA] parse_action_intent error:", traceback.format_exc())
            action = {"action": "none"}

        if action.get("action") == "none":
            # Couldn't parse a clear action — fall back to a helpful answer
            if language == "he":
                return "לא הצלחתי להבין בדיוק איזו התראה להוסיף. נסה למשל:\n• \"תתריע לי כש-TEVA עולה 5%\"\n• \"הוסף התראה על הנפקות חדשות\"\n• \"התראה על נפח מסחר חריג ב-ESLT\""
            return "I couldn't parse a clear alert request. Try for example:\n• \"Alert me when TEVA rises 5%\"\n• \"Notify me of new IPOs\"\n• \"Volume spike alert for Elbit\""

        # Ticker from plan_intent may be more reliable than parse_action for well-known tickers
        if ticker and not action.get("ticker"):
            action["ticker"] = ticker

        # Hebrew resolution for tickers not identified
        if not action.get("ticker") and action.get("action") == "add_alert":
            resolved_ticker, resolved_company = self._resolve_ticker_from_state(question)
            if resolved_ticker:
                action["ticker"] = resolved_ticker
                if not action.get("company_name"):
                    action["company_name"] = resolved_company

        action["_language"] = language
        confirm_msg = action.get("confirm_he" if language == "he" else "confirm_en", "Confirm?")
        return {"_pending_action": action, "_confirm_msg": confirm_msg}

    def _resolve_ticker_from_state(self, question: str) -> tuple[str | None, str | None]:
        """
        Try to find a TASE ticker for a Hebrew company name the user mentioned.
        Uses LLM with full Maya company cache as reference.
        Returns (ticker, company_name) or (None, None).
        """
        try:
            cache = self._state.get("tase_company_cache", {})
            companies = cache.get("companies", [])
            if not companies:
                return None, None

            # Build compact company list text: "CompanyName (ID: 123)"
            lines = []
            for c in companies[:500]:   # cap at 500 to stay within token budget
                name = c.get("CompanyName") or c.get("companyName") or ""
                cid  = c.get("CompanyId") or c.get("companyId") or ""
                tkr  = c.get("CompanyTicker") or c.get("ticker") or ""
                if name:
                    entry = name
                    if tkr and not tkr.startswith("TASE"):
                        entry += f" ({tkr})"
                    elif cid:
                        entry += f" (ID:{cid})"
                    lines.append(entry)

            company_list_text = "\n".join(lines)
            result = self._llm.resolve_ticker(question, company_list_text)

            confidence = result.get("confidence", "low")
            ticker     = result.get("ticker") or ""
            company    = result.get("company_name") or ""

            # confidence is a string: "high" | "medium" | "low"
            if confidence in ("high", "medium") and ticker and not ticker.startswith("TASE"):
                return ticker.upper().replace(".TA", ""), company
            return None, None
        except Exception:
            print("[QA] resolve_ticker error:", traceback.format_exc())
            return None, None
