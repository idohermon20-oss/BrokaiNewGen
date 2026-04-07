"""
SectorAgent — abstract base class for all sector-specialized research agents.

Every sector agent:
  1. Filters pre-fetched cross-sector signals (Maya/news/earnings/dual-listed) for its tickers
  2. Runs MarketAnomalyDetector on ALL its tickers (8 technical detectors)
  3. Calls get_sector_signals() — overridden per sector for domain-specific macro signals
  4. Groups merged signals via ConvergenceEngine
  5. Runs DeepStockAnalyzer on top-3 candidates
  6. Calls sector-specialized LLM (score_sector) → returns top-2 picks
  7. Returns a structured dict consumed by ResearchManager

Shared infrastructure (no duplication):
  - MarketAnomalyDetector  (sources/market.py)
  - DeepStockAnalyzer      (sources/market.py)
  - ConvergenceEngine      (analysis/convergence.py)
  - LLMAnalyst.score_sector (analysis/llm.py)
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod

from ..analysis.convergence import ConvergenceEngine
from ..analysis.llm import LLMAnalyst
from ..analysis.memory import StockMemoryManager
from ..config import OPENAI_MODEL
from ..models import Signal, now_iso
from ..sources.market import DeepStockAnalyzer, MarketAnomalyDetector
from ..sources.web_news import WebNewsSearcher


class SectorAgent(ABC):
    """Abstract base class — subclass and set `sector_name`, `tickers`, override
    `get_sector_signals()` and `_sector_domain` property."""

    sector_name: str = "Unknown"
    tickers:     list[str] = []

    def __init__(
        self,
        openai_key:     str,
        state:          dict | None = None,
        volume_spike_x: float | None = None,
        price_move_pct: float | None = None,
    ):
        self._llm            = LLMAnalyst(openai_key, model=OPENAI_MODEL)
        self._memory         = StockMemoryManager(state) if state is not None else None
        self._volume_spike_x = volume_spike_x   # None → use module constant
        self._price_move_pct = price_move_pct

    # ── Public entry point ────────────────────────────────────────────────────

    def run(
        self,
        pre_fetched_signals: list[Signal],
        macro_text:          str,
        sector_context:      str = "",
    ) -> dict:
        """
        Full sector analysis. Called by ThreadPoolExecutor in ResearchManager.

        Discovery-first flow:
          1. Gather all signals (pre-fetched cross-sector + technicals + sector-specific macro)
          2. Group by ticker — only tickers WITH signals this week surface here
          3. Deep-analyze ALL relevant tickers (not a fixed top-N)
          4. Sector LLM builds a full ranked portfolio on the relevant subset
          5. Return portfolio + all signals (manager accumulates weekly pool)

        The agent never reports on silent tickers — relevance is determined by
        signal activity, not by membership in a pre-defined list.
        """
        print(f"[{self.sector_name}] Agent starting...")

        # 1. Filter cross-sector signals for our tickers
        my_signals = self._filter_signals(pre_fetched_signals)

        # 2. Run technical scan on all sector tickers
        tech_signals = self._run_technicals()

        # 3. Sector-specific macro signals (oil/VIX/rates/peers)
        extra_signals = self.get_sector_signals()

        # 4. Merge and preliminary convergence
        all_signals  = my_signals + tech_signals + extra_signals
        grouped_prelim = ConvergenceEngine().group_by_ticker(all_signals)

        # 5. DISCOVERY: filter to tickers with signal activity this week
        prelim_relevant = {
            tkr: g for tkr, g in grouped_prelim.items()
            if g.get("final_score", 0) > 0
        }

        if not prelim_relevant:
            print(f"[{self.sector_name}] No active stocks this week.")
            return {
                "sector":          self.sector_name,
                "portfolio":       [],
                "relevant_count":  0,
                "signals_count":   len(all_signals),
                "all_signals":     all_signals,
            }

        # 6. Web news enrichment for top candidates
        #    Search Google News for each relevant ticker, use LLM to extract signals.
        #    Only top-5 by preliminary score to limit API calls.
        ranked_prelim = sorted(
            prelim_relevant, key=lambda t: prelim_relevant[t]["final_score"], reverse=True
        )
        web_signals, web_articles = self._fetch_web_news(ranked_prelim[:5], prelim_relevant)
        if web_signals:
            print(f"[{self.sector_name}] +{len(web_signals)} web news signals added.")
            all_signals = all_signals + web_signals
            # Store news headlines in memory for each ticker
            if self._memory:
                for tkr, articles in web_articles.items():
                    self._memory.update_news_summary(tkr, articles)

        # Re-run convergence with full enriched signal set
        grouped = ConvergenceEngine().group_by_ticker(all_signals)
        relevant = {
            tkr: g for tkr, g in grouped.items()
            if g.get("final_score", 0) > 0
        }

        # 7. Deep-analyze top candidates (cap at 8 to limit API calls)
        #    Skip if fundamentals are fresh in memory (saves yfinance API calls)
        ranked_relevant = sorted(relevant, key=lambda t: relevant[t]["final_score"], reverse=True)
        analyze_set = ranked_relevant[:8]
        if self._memory:
            # Only re-fetch tickers whose memory fundamentals are stale (>7 days old)
            analyze_set = [t for t in analyze_set if self._memory.fundamentals_stale(t)]
        cached_count = len(ranked_relevant[:8]) - len(analyze_set)
        print(f"[{self.sector_name}] {len(relevant)} relevant stocks | "
              f"deep-analyzing {len(analyze_set)} (skipping {cached_count} with fresh cache): "
              f"{', '.join(ranked_relevant[:8])}")
        tech_data = self._deep_analyze(analyze_set, relevant)

        # Store fresh fundamentals in memory and fill from cache for the rest
        full_tech_data: dict = {}
        for tkr in ranked_relevant[:8]:
            if tkr in tech_data:
                full_tech_data[tkr] = tech_data[tkr]
                if self._memory:
                    self._memory.update_fundamentals(tkr, tech_data[tkr])
            elif self._memory:
                cached = self._memory.get(tkr).get("fundamentals")
                if cached:
                    full_tech_data[tkr] = cached  # use cached fundamentals

        # Update signal history in memory for all relevant tickers.
        # Also persist company_name for every ticker so the bot can display it.
        if self._memory:
            for tkr, g in relevant.items():
                self._memory.update_signal_history(tkr, g["signals"], g["final_score"])
                # Extract company_name from grouped data (company_name field on Signal objects)
                company_name = g.get("company_name", "")
                if not company_name:
                    for s in g.get("signals", []):
                        name = getattr(s, "company_name", "") or ""
                        if name and not name.startswith("TASE"):
                            company_name = name
                            break
                if company_name:
                    self._memory.update_company_name(tkr, company_name)

        # Build memory context strings for LLM (one compact string per ticker)
        memory_ctx: dict[str, str] = {}
        if self._memory:
            for tkr in relevant:
                ctx = self._memory.build_context_string(tkr)
                if ctx:
                    memory_ctx[tkr] = ctx

        # 8. Sector-specialized LLM: build portfolio recommendation for ALL relevant stocks
        print(f"[{self.sector_name}] Calling sector LLM for portfolio...")
        portfolio = self._llm.score_sector(
            relevant,
            sector_domain=self._sector_domain,
            macro_text=macro_text,
            technical_data=full_tech_data or None,
            memory_context=memory_ctx or None,
        )

        # Store LLM analyst notes and structured insights back into memory
        if self._memory and portfolio:
            for pick in portfolio:
                tkr       = pick.get("ticker", "")
                rationale = pick.get("rationale", "")
                if not tkr:
                    continue
                if rationale:
                    self._memory.update_analyst_notes(tkr, rationale)
                # Structured memory update — sentiment, risk flag, watch level, key takeaway
                mem_upd = pick.get("memory_update")
                if mem_upd and isinstance(mem_upd, dict):
                    self._memory.update_llm_insights(tkr, mem_upd)

        best = portfolio[0].get("ticker", "none") if portfolio else "none"
        print(f"[{self.sector_name}] Portfolio: {len(portfolio)} stocks | best: {best}")

        return {
            "sector":         self.sector_name,
            "portfolio":      portfolio,
            "best_pick":      best,
            "relevant_count": len(relevant),
            "signals_count":  len(all_signals),
            "all_signals":    all_signals,
        }

    # ── Override in subclass ──────────────────────────────────────────────────

    def get_sector_signals(self) -> list[Signal]:
        """Return sector-specific macro-driven signals. Override per sector."""
        return []

    @property
    @abstractmethod
    def _sector_domain(self) -> str:
        """Sector domain expertise text injected into the LLM system prompt."""

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _fetch_web_news(
        self,
        top_tickers: list[str],
        grouped:     dict,
    ) -> tuple[list[Signal], dict[str, list[dict]]]:
        """
        For each ticker in top_tickers, search Google News and use the LLM to
        extract structured signals.  Returns (signals, articles_by_ticker) so the
        caller can store article headlines in memory.

        Throttled: max 5 tickers, 6 articles each. On any error, continues silently.
        """
        searcher  = WebNewsSearcher()
        signals:  list[Signal]          = []
        articles_map: dict[str, list[dict]] = {}

        for tkr in top_tickers[:5]:
            try:
                company_name = grouped.get(tkr, {}).get("company_name", tkr)
                ticker_yf    = f"{tkr}.TA" if not tkr.endswith(".TA") else tkr

                articles = searcher.search_ticker(tkr, company_name, max_results=6)
                if not articles:
                    continue

                articles_map[tkr] = articles  # save for memory update

                extracted = self._llm.extract_web_news_signals(tkr, company_name, articles)
                for item in extracted:
                    signals.append(Signal(
                        ticker       = tkr,
                        ticker_yf    = ticker_yf,
                        company_name = company_name,
                        signal_type  = item.get("signal_type", "general_news"),
                        headline     = item.get("headline", ""),
                        detail       = item.get("detail", ""),
                        url          = "",
                        timestamp    = now_iso(),
                        score        = float(item.get("relevance", 5)) * 4,
                    ))
            except Exception as e:
                print(f"[{self.sector_name}] Web news error for {tkr}: {e}")

        return signals, articles_map

    def _filter_signals(self, signals: list[Signal]) -> list[Signal]:
        """Keep signals whose ticker_yf or ticker belongs to this sector."""
        ta_set   = set(self.tickers)
        bare_set = {t.replace(".TA", "") for t in self.tickers}
        return [
            s for s in signals
            if s.ticker_yf in ta_set or s.ticker in bare_set
        ]

    def _run_technicals(self) -> list[Signal]:
        """Run all 8 MarketAnomalyDetector methods on every sector ticker."""
        kwargs = {}
        if self._volume_spike_x is not None:
            kwargs["volume_spike_x"] = self._volume_spike_x
        if self._price_move_pct is not None:
            kwargs["price_move_pct"] = self._price_move_pct
        detector = MarketAnomalyDetector(self.tickers, **kwargs)
        # scan_universe with sample_size = full sector (priority = all)
        return detector.scan_universe(
            sample_size=len(self.tickers),
            priority_tickers=self.tickers,
        )

    def _deep_analyze(self, top_tickers: list[str], grouped: dict) -> dict:
        """Run DeepStockAnalyzer for top candidates that have real .TA tickers."""
        analyzer = DeepStockAnalyzer()
        result   = {}
        ta_set   = set(self.tickers)
        for tkr in top_tickers:
            # Resolve ticker_yf from grouped signals
            ticker_yf = None
            for s in grouped.get(tkr, {}).get("signals", []):
                if s.ticker_yf and s.ticker_yf.endswith(".TA"):
                    ticker_yf = s.ticker_yf
                    break
            if not ticker_yf:
                ticker_yf = f"{tkr}.TA"
            if ticker_yf not in ta_set:
                continue
            try:
                data = analyzer.analyze(ticker_yf)
                result[tkr] = {
                    k: data[k] for k in
                    ("rsi_14", "ma_20", "ma_50", "ma_trend", "last_price",
                     "52w_high", "52w_low", "avg_volume", "today_change_pct",
                     "pct_vs_52w_high", "market_cap",
                     "revenue_growth_pct", "net_income_growth_pct",
                     "pe_trailing", "pe_forward", "price_to_book",
                     "dividend_yield", "gross_margin", "net_margin",
                     "debt_to_equity")
                    if k in data
                }
            except Exception:
                pass
            time.sleep(0.3)
        return result

    # ── Shared sector macro helpers ───────────────────────────────────────────

    @staticmethod
    def _peer_move_signal(
        peer_ticker:  str,
        peer_label:   str,
        threshold_pct: float,
        target_tickers: list[str],
        signal_type:  str,
        direction_text: str,
    ) -> list[Signal]:
        """
        Generic helper: if `peer_ticker` moved >= threshold_pct, emit signals
        for all `target_tickers`. Used by sector agents for peer-index logic.
        """
        import yfinance as yf
        try:
            df = yf.Ticker(peer_ticker).history(period="5d", interval="1d")
            if len(df) < 2:
                return []
            prev = df["Close"].iloc[-2]
            last = df["Close"].iloc[-1]
            if prev <= 0:
                return []
            pct = (last - prev) / prev * 100
            if abs(pct) < threshold_pct:
                return []
            direction = "rallied" if pct > 0 else "fell"
            signals: list[Signal] = []
            for tkr in target_tickers:
                ticker = tkr.replace(".TA", "")
                signals.append(Signal(
                    ticker       = ticker,
                    ticker_yf    = tkr,
                    company_name = ticker,
                    signal_type  = signal_type,
                    headline     = f"{peer_label} {direction} {pct:+.1f}% -> {direction_text}",
                    detail       = f"{peer_label}: ${last:.2f} ({pct:+.1f}%) | Sector sympathy move expected",
                    url          = f"https://finance.yahoo.com/quote/{tkr}",
                    timestamp    = now_iso(),
                ))
                time.sleep(0.05)
            return signals
        except Exception:
            return []
