"""
StockMemoryManager — persistent per-stock knowledge base.

Each cycle, after signals are gathered and the LLM scores a stock,
the results are written back to memory.  On the *next* cycle, the LLM
receives that accumulated context alongside fresh signals — enabling:

  • Trend recognition across weeks ("3 consecutive weeks of volume spikes")
  • Avoiding stale re-fetching  (fundamentals cached 7 days)
  • LLM analyst notes that compound over time instead of restarting each cycle
  • More efficient prompts — a 2-sentence memory string beats 20 raw signal lines

Storage: state["stock_memory"][ticker] = {
    "fundamentals":       {rsi_14, ma_trend, last_price, ...},   # from DeepStockAnalyzer
    "fundamentals_date":  "YYYY-MM-DD",
    "signal_history":     [{date, signal_types, final_score}, ...],  # last 10 cycles
    "analyst_notes":      "LLM-generated analyst summary",
    "notes_date":         "YYYY-MM-DD",
    "recent_news":        "Top 3 headlines from web news this week",
    "news_date":          "YYYY-MM-DD",
    "consecutive_active": int,   # cycles in a row with signals
}

TTLs:
  fundamentals — 7 days (refresh via DeepStockAnalyzer once per week)
  analyst_notes — kept until overwritten (LLM updates whenever stock appears)
  signal_history — last 10 cycle entries kept
  whole entry — pruned after 30 days of inactivity
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from ..models import Signal, today, is_pseudo_ticker, is_cache_stale, fmt_mcap, fmt_rsi_label


class StockMemoryManager:
    _FUNDAMENTALS_TTL_DAYS = 7
    _PRUNE_INACTIVITY_DAYS = 30

    def __init__(self, state: dict):
        self._mem: dict[str, dict] = state.setdefault("stock_memory", {})

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, ticker: str) -> dict:
        return self._mem.get(ticker, {})

    def build_context_string(self, ticker: str) -> str:
        """
        Return a compact single-string memory summary for injection into LLM prompts.
        Empty string if no memory exists yet.
        """
        entry = self._mem.get(ticker)
        if not entry:
            return ""

        parts: list[str] = []

        # Company identity
        company_name = entry.get("company_name", "")
        if company_name:
            parts.append(f"Company: {company_name}")

        # Analyst notes — most recent first, then prior week for trend recognition
        notes = entry.get("analyst_notes", "")
        if notes:
            parts.append(f"Latest analysis: {notes[:200]}")
        prior = entry.get("prior_analyst_notes", "")
        if prior:
            parts.append(f"Prior: {prior[:120]}")

        # Structured LLM insights from last cycle
        sentiment  = entry.get("llm_sentiment", "")
        memory_note = entry.get("llm_memory_note", "")
        risk_flag  = entry.get("llm_risk_flag", "")
        watch_for  = entry.get("llm_watch_for", "")
        if memory_note:
            parts.append(f"KeyTakeaway: {memory_note[:150]}")
        if sentiment:
            parts.append(f"Sentiment: {sentiment}")
        if risk_flag:
            parts.append(f"RiskFlag: {risk_flag[:120]}")
        if watch_for:
            parts.append(f"WatchFor: {watch_for[:100]}")

        # Signal history pattern
        hist = entry.get("signal_history", [])
        if hist:
            n_active = entry.get("consecutive_active", 0)
            recent_types = list({t for h in hist[-3:] for t in h.get("signal_types", [])})
            best_score   = max((h.get("final_score", 0) for h in hist[-5:]), default=0)
            parts.append(
                f"History({len(hist)} cycles): {n_active} consecutive active | "
                f"recent signals: {', '.join(recent_types[:4])} | best score: {best_score:.0f}"
            )

        # Recent news headline summary
        news = entry.get("recent_news", "")
        if news:
            parts.append(f"Recent news: {news[:150]}")

        # Fundamentals snapshot — include market_cap so LLM can judge catalyst materiality
        f = entry.get("fundamentals", {})
        if f:
            rsi   = f.get("rsi_14",            "?")
            trend = f.get("ma_trend",           "?")
            vs52  = f.get("pct_vs_52w_high",    "?")
            rev   = f.get("revenue_growth_pct", "?")
            cap   = f.get("market_cap")
            cap_str = fmt_mcap(cap) if cap else "?"
            parts.append(
                f"Technicals: RSI={rsi} MA={trend} vs52wHigh={vs52}% "
                f"revGrowth={rev}% mktCap={cap_str}"
            )

        # Maya filing history summary — last 3 filings so LLM sees recent corporate events
        maya_hist = entry.get("maya_history", [])
        if maya_hist:
            recent = list(reversed(maya_hist))[:3]   # newest first
            filing_parts = []
            for h in recent:
                ftype    = h.get("type", "?").replace("maya_", "")
                date     = h.get("date", "?")[:7]   # YYYY-MM
                headline = h.get("headline", "")[:50]
                filing_parts.append(f"{ftype}@{date}:{headline}")
            parts.append(f"MayaHistory: {' | '.join(filing_parts)}")

        return " | ".join(parts) if parts else ""

    def fundamentals_stale(self, ticker: str) -> bool:
        """True if fundamentals are missing or older than TTL."""
        date_str = self._mem.get(ticker, {}).get("fundamentals_date", "")
        return is_cache_stale(date_str, self._FUNDAMENTALS_TTL_DAYS)

    # ── Write ─────────────────────────────────────────────────────────────────

    def update_company_name(self, ticker: str, company_name: str) -> None:
        """Store the human-readable company name for a ticker (used by bot tools for display)."""
        if company_name and not is_pseudo_ticker(company_name):
            entry = self._mem.setdefault(ticker, {})
            if not entry.get("company_name"):
                entry["company_name"] = company_name

    def update_fundamentals(self, ticker: str, tech_data: dict) -> None:
        entry = self._mem.setdefault(ticker, {})
        entry["fundamentals"]      = tech_data
        entry["fundamentals_date"] = today()

    def update_signal_history(self, ticker: str, signals: list[Signal], final_score: float) -> None:
        entry   = self._mem.setdefault(ticker, {})
        for s in signals:
            name = getattr(s, "company_name", "") or ""
            if name and not is_pseudo_ticker(name):
                self.update_company_name(ticker, name)
                break
        date    = today()
        history = entry.get("signal_history", [])

        # Deduplicate same-day entry
        history = [h for h in history if h.get("date") != today]
        history.append({
            "date":         date,
            "signal_types": list({s.signal_type for s in signals}),
            "final_score":  round(final_score, 1),
        })
        entry["signal_history"] = history[-10:]  # keep last 10 cycles

        # Track consecutive active cycles
        dates   = sorted({h["date"] for h in entry["signal_history"]}, reverse=True)
        consec  = 1
        for i in range(1, len(dates)):
            prev = datetime.strptime(dates[i-1], "%Y-%m-%d")
            curr = datetime.strptime(dates[i],   "%Y-%m-%d")
            if (prev - curr).days <= 3:   # within 3 days = same active stretch
                consec += 1
            else:
                break
        entry["consecutive_active"] = consec

    def update_analyst_notes(self, ticker: str, notes: str) -> None:
        entry = self._mem.setdefault(ticker, {})
        today_str      = today()
        existing       = entry.get("analyst_notes", "")
        existing_date  = entry.get("notes_date", "")
        if existing and existing_date and existing_date != today_str:
            # Different day — shift to prior notes (2-week trend window for LLM)
            entry["prior_analyst_notes"] = f"[{existing_date}] {existing[:180]}"
        elif existing and existing_date == today_str:
            # Same day — a different sector agent already wrote notes for this stock.
            # Keep whichever is more detailed (longer) to avoid overwriting better analysis.
            if len(notes) <= len(existing):
                return  # existing is at least as good — don't overwrite
        entry["analyst_notes"] = notes[:300]
        entry["notes_date"]    = today_str

    def update_llm_insights(self, ticker: str, insights: dict) -> None:
        """
        Store structured LLM insights from a sector scoring cycle.

        Expected keys in `insights` (all optional):
          memory_note  — distilled 1-sentence takeaway for next cycle
          sentiment    — "bullish" | "bearish" | "neutral"
          risk_flag    — what would invalidate the thesis
          watch_for    — price level, catalyst, or date to monitor next cycle

        These are kept flat in the entry so build_context_string() can surface them.
        """
        if not insights:
            return
        entry = self._mem.setdefault(ticker, {})
        for key in ("memory_note", "sentiment", "risk_flag", "watch_for"):
            val = insights.get(key, "")
            if val:
                entry[f"llm_{key}"] = str(val)[:200]

    def update_news_summary(self, ticker: str, articles: list[dict]) -> None:
        """Store top-3 headlines from web news articles as compact summary."""
        if not articles:
            return
        headlines = [a["title"] for a in articles[:3] if a.get("title")]
        if headlines:
            entry = self._mem.setdefault(ticker, {})
            entry["recent_news"] = " | ".join(headlines)
            entry["news_date"]   = today()

    def update_maya_history(self, ticker: str, signal: Signal) -> None:
        """
        Append a Maya filing to this stock's per-company Maya history.
        Keeps the last 30 filings. Deduplicates by (date + signal_type + headline).
        ticker may be a real .TA symbol OR a TASE{id} pseudo-ticker.
        """
        entry   = self._mem.setdefault(ticker, {})
        # Store company_name from Maya signal (especially useful for TASE pseudo-tickers)
        name = getattr(signal, "company_name", "") or ""
        if name and not name.startswith("TASE"):
            self.update_company_name(ticker, name)
        history = entry.get("maya_history", [])
        record  = {
            "date":        signal.timestamp[:10],
            "type":        signal.signal_type,
            "headline":    signal.headline,
            "detail":      (signal.detail or "")[:300],
            "company":     signal.company_name or "",
        }
        # Deduplicate: skip if identical (date + type + headline) already stored
        key = record["date"] + record["type"] + record["headline"]
        if any(h["date"] + h["type"] + h["headline"] == key for h in history):
            return
        history.append(record)
        entry["maya_history"] = history[-30:]   # keep last 30 filings

    def get_maya_history(self, ticker: str) -> list[dict]:
        """Return the stored Maya filing history for a ticker (newest first)."""
        history = self._mem.get(ticker, {}).get("maya_history", [])
        return list(reversed(history))   # most recent first

    def get_full_briefing(self, ticker: str) -> str:
        """
        Return a comprehensive multi-section analyst briefing for a specific ticker.
        Used by the bot's get_memory tool to give the LLM maximum context.
        Format is human-readable (not JSON) so the LLM can synthesise directly.
        Returns empty string if no memory exists.
        """
        entry = self._mem.get(ticker)
        if not entry:
            return ""

        sections: list[str] = []
        company = entry.get("company_name", ticker)
        sections.append(f"=== Analyst Briefing: {ticker} ({company}) ===")

        # --- Current Analyst Assessment ---
        notes   = entry.get("analyst_notes", "")
        prior   = entry.get("prior_analyst_notes", "")
        if notes:
            sections.append(f"\nCurrent Analysis:\n{notes}")
        if prior:
            sections.append(f"Prior Analysis:\n{prior}")

        # --- LLM Insights ---
        sentiment   = entry.get("llm_sentiment", "")
        memory_note = entry.get("llm_memory_note", "")
        risk_flag   = entry.get("llm_risk_flag", "")
        watch_for   = entry.get("llm_watch_for", "")
        insight_parts = []
        if sentiment:
            insight_parts.append(f"Sentiment: {sentiment.upper()}")
        if memory_note:
            insight_parts.append(f"Key Insight: {memory_note}")
        if risk_flag:
            insight_parts.append(f"Risk: {risk_flag}")
        if watch_for:
            insight_parts.append(f"Watch For: {watch_for}")
        if insight_parts:
            sections.append("\nLLM Assessment:\n" + "\n".join(f"  • {p}" for p in insight_parts))

        # --- Signal Activity Pattern ---
        hist = entry.get("signal_history", [])
        if hist:
            consec = entry.get("consecutive_active", 0)
            recent_types = sorted({t for h in hist[-5:] for t in h.get("signal_types", [])})
            best_score   = max((h.get("final_score", 0) for h in hist), default=0)
            last_seen    = hist[-1].get("date", "?") if hist else "?"
            sections.append(
                f"\nSignal Activity ({len(hist)} cycles recorded):\n"
                f"  • Consecutive active: {consec} cycles\n"
                f"  • Best score: {best_score:.0f}/100\n"
                f"  • Last signal: {last_seen}\n"
                f"  • Recent signal types: {', '.join(recent_types) or 'none'}"
            )

        # --- Technicals (cached) ---
        f = entry.get("fundamentals", {})
        if f:
            rsi   = f.get("rsi_14", "?")
            trend = f.get("ma_trend", "?")
            vs52  = f.get("pct_vs_52w_high", "?")
            rev   = f.get("revenue_growth_pct", "?")
            cap   = f.get("market_cap")
            price = f.get("last_price", "?")
            cap_str   = fmt_mcap(cap) if cap else "?"
            rsi_label = fmt_rsi_label(rsi)
            sections.append(
                f"\nCached Technicals:\n"
                f"  • Price: ₪{price} | RSI-14: {rsi}{rsi_label}\n"
                f"  • MA Trend: {trend} | vs 52w high: {vs52}%\n"
                f"  • Market cap: {cap_str} | Revenue growth: {rev}%"
            )
            if entry.get("fundamentals_date"):
                sections[-1] += f"\n  • Data as of: {entry['fundamentals_date']}"

        # --- Recent News ---
        news = entry.get("recent_news", "")
        if news:
            sections.append(f"\nRecent Headlines:\n  {news}")

        # --- Maya Filing History ---
        maya_hist = entry.get("maya_history", [])
        if maya_hist:
            recent = list(reversed(maya_hist))[:8]  # newest first
            filing_lines = []
            for h in recent:
                ftype    = h.get("type", "?").replace("maya_", "")
                date     = h.get("date", "?")
                headline = h.get("headline", "")
                detail   = h.get("detail", "")[:100]
                line = f"  • [{date}] {ftype}: {headline}"
                if detail:
                    line += f"\n    {detail}"
                filing_lines.append(line)
            sections.append(f"\nMaya Filing History ({len(maya_hist)} total, last 8 shown):\n" + "\n".join(filing_lines))

        return "\n".join(sections)

    # ── Maintenance ───────────────────────────────────────────────────────────

    def prune_stale(self) -> int:
        """Remove entries inactive for more than 30 days. Returns count removed."""
        cutoff  = (datetime.now() - timedelta(days=self._PRUNE_INACTIVITY_DAYS)).strftime("%Y-%m-%d")
        stale   = []
        for ticker, entry in self._mem.items():
            hist = entry.get("signal_history", [])
            last = max((h.get("date", "") for h in hist), default="")
            if not last or last < cutoff:
                stale.append(ticker)
        for t in stale:
            del self._mem[t]
        return len(stale)

    def summary(self) -> str:
        return f"Stock memory: {len(self._mem)} tickers tracked"


