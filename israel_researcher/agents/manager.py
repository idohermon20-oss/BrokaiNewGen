"""
ResearchManager — orchestrates the multi-agent research cycle.

Architecture:
  Phase 1 (sequential): Gather cross-sector data using shared resources
    - Maya filings + institutional filings (Playwright session)
    - Earnings calendar
    - Israeli + global news
    - Dual-listed US overnight moves
    - Macro snapshot + sector rotation context

  Phase 2 (parallel): Run all sector agents via ThreadPoolExecutor
    - Each agent scans its tickers, gets sector-specific signals, calls sector LLM
    - Returns top-2 picks + all raw signals

  Phase 3 (sequential): Manager LLM arbitration
    - Receives sector finalists (6-12 candidates)
    - CIO-style prompt picks top-3 across sectors
    - Sends Telegram alert

  State management and weekly/daily reports handled here (same as before).
"""

from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..alerts  import TelegramReporter
from ..analysis.convergence import WeeklyAccumulator
from ..analysis.llm import LLMAnalyst
from ..analysis.memory import StockMemoryManager
from ..analysis.excel_memory import ExcelMemoryStore
from ..config import (
    BOT_TOKEN, CHAT_ID, DUAL_LISTED_STOCKS, GLOBAL_NEWS_SOURCES,
    OPENAI_API_KEY, TOP_N_ALERTS,
)
from ..bot.bot_state import BotSettings, SECTOR_AGENT_MAP
from ..bot.user_alerts import (
    check_and_fire_alerts, format_alert_message,
    load_user_alerts, save_user_alerts,
)
from ..models import (
    Signal, build_company_map, load_state, now_iso, refresh_company_cache,
    save_state, signal_key, this_week_start, today,
)
from ..sources import (
    ChromeNewsSearcher, DualListedMonitor, EarningsCalendar,
    IsraeliNewsMonitor, MacroContext, MayaMonitor, SectorAnalyzer,
    TASEMarketScraper,
)
from .banks            import BanksAgent
from .construction     import ConstructionAgent
from .discovery        import DiscoveryAgent
from .energy           import EnergyAgent
from .pharma           import PharmaAgent
from .real_estate      import RealEstateAgent
from .tech_defense     import TechDefenseAgent
from .telecom_consumer import TelecomConsumerAgent
from .tourism          import TourismTransportAgent


class ResearchManager:
    """Orchestrates the full multi-agent research cycle."""

    _AGENT_CLASSES = [
        BanksAgent,
        TechDefenseAgent,
        EnergyAgent,
        PharmaAgent,
        RealEstateAgent,
        TelecomConsumerAgent,
        TourismTransportAgent,
        ConstructionAgent,
    ]
    _PARALLEL_WORKERS = 4   # ThreadPoolExecutor max workers

    def __init__(self, openai_key: str, bot_token: str, chat_id: str, settings: BotSettings | None = None):
        self.openai_key = openai_key
        self.settings   = settings
        self.telegram   = TelegramReporter(bot_token, chat_id)
        self.llm        = LLMAnalyst(openai_key)
        self.accumulator= WeeklyAccumulator()

    # ── Main entry point ──────────────────────────────────────────────────────

    def run_cycle(self, state: dict) -> None:
        print(f"[{now_iso()}] ResearchManager cycle start...")
        maya = MayaMonitor()
        try:
            self._run(state, maya)
        finally:
            maya.close()
            save_state(state)
            print(f"[Cycle] Done. Weekly pool: {len(state.get('weekly_signals', []))} signals.")

    # ── Phase 1: Cross-sector data collection ────────────────────────────────

    def _gather_cross_sector(
        self, state: dict, maya: MayaMonitor
    ) -> tuple[list[Signal], str, str, list[dict]]:
        """
        Returns (pre_fetched_signals, macro_text, sector_context, companies).
        All signals here are cross-sector (Maya filings, news, earnings, dual-listed).
        companies is the full Maya company list, used by DiscoveryAgent.
        """
        seen_maya_ids    = set(state.get("seen_maya_report_ids", []))
        seen_signal_keys = set(state.get("seen_signal_keys", []))
        signals: list[Signal] = []

        # Company universe (for news matching)
        companies   = refresh_company_cache(state, maya)
        company_map = build_company_map(companies)

        # TASE market website — full 548-stock list with Hebrew names + security numbers.
        # Enriches company_map so news articles about ANY listed company can be matched
        # to a TASE{secNum} pseudo-ticker (even if not in Maya autocomplete).
        print("[TASE] Fetching complete stock list from market.tase.co.il...")
        tase_scraper  = TASEMarketScraper(state, playwright_context=maya._context)
        tase_stocks   = tase_scraper.get_stocks()
        tase_map_supp = tase_scraper.build_company_map_supplement(tase_stocks)
        company_map.update(tase_map_supp)
        print(f"[TASE] {len(tase_stocks)} stocks | {len(tase_map_supp)} name mappings added to company_map.")

        # Maya filings
        print("[Maya] Fetching reports...")
        maya_sigs, _ = maya.reports_to_signals(maya.fetch_recent_reports(100), seen_maya_ids)
        print(f"[Maya] {len(maya_sigs)} filing signals.")
        signals.extend(maya_sigs)

        # Institutional filings
        print("[Maya] Fetching institutional filings...")
        inst_sigs, _ = maya.reports_to_signals(maya.fetch_institutional_filings(), seen_maya_ids)
        print(f"[Maya] {len(inst_sigs)} institutional signals.")
        signals.extend(inst_sigs)

        # Earnings calendar
        earnings_cal  = EarningsCalendar(maya)
        earnings_sigs = earnings_cal.get_upcoming(days_ahead=10)
        print(f"[Earnings] {len(earnings_sigs)} upcoming events.")
        signals.extend(earnings_sigs)

        # Dual-listed US overnight moves
        print("[Dual] Checking US overnight moves...")
        dual_sigs = DualListedMonitor().get_signals(DUAL_LISTED_STOCKS)
        new_dual  = [s for s in dual_sigs if signal_key(s) not in seen_signal_keys]
        print(f"[Dual] {len(new_dual)} significant US moves.")
        signals.extend(new_dual)

        # Israeli news
        print("[News] Israeli sources...")
        news_monitor = IsraeliNewsMonitor()
        il_sigs = news_monitor.items_to_signals(
            news_monitor.fetch_israeli_news(), "israeli_news", company_map
        )
        print(f"[News] {len(il_sigs)} Israeli news signals.")
        signals.extend(il_sigs)

        # Chrome-based news (Globes, Calcalist, TheMarker via headless browser)
        print("[Chrome] Fetching Israeli financial news via browser...")
        chrome = ChromeNewsSearcher(browser_context=maya._context)
        chrome_items = chrome.fetch_all(max_per_site=15)
        chrome_sigs = news_monitor.items_to_signals(chrome_items, "israeli_news", company_map)
        print(f"[Chrome] {len(chrome_sigs)} Chrome news signals.")
        signals.extend(chrome_sigs)

        # Global headlines (text only, for LLM context)
        print("[News] Global sources...")
        global_items     = news_monitor.fetch_global_news(GLOBAL_NEWS_SOURCES)
        global_headlines = "\n".join(
            f"- {it.get('title', '')}" for it in global_items[:15] if it.get("title")
        )

        # Update seen IDs now (after collection, before agents run).
        # seen_maya_ids was already mutated in-place by reports_to_signals() — just persist it.
        state["seen_maya_report_ids"] = list(seen_maya_ids)
        today_prefix = today()
        for s in signals:
            seen_signal_keys.add(signal_key(s))
        state["seen_signal_keys"] = [k for k in seen_signal_keys if today_prefix in k]

        # Macro snapshot
        print("[Macro] Fetching global market snapshot...")
        macro_text = MacroContext().get()
        print(f"[Macro] {macro_text.splitlines()[0] if macro_text else 'unavailable'}")

        # Sector rotation context
        print("[Sector] Building TASE sector context...")
        sector_ctx = SectorAnalyzer().get_sector_context()
        print(f"[Sector] {sector_ctx.splitlines()[0] if sector_ctx else 'unavailable'}")

        # Attach global context to macro_text for LLM
        if global_headlines:
            macro_text += f"\n\nGlobal headlines:\n{global_headlines}"

        return signals, macro_text, sector_ctx, companies

    # ── Phase 2: Parallel sector agents ──────────────────────────────────────

    def _run_sector_agents(
        self,
        pre_fetched:     list[Signal],
        macro_text:      str,
        sector_ctx:      str,
        state:           dict,
        discovery_agent: "DiscoveryAgent | None" = None,
    ) -> list[dict]:
        """
        Instantiate all sector agents and run them in parallel.
        discovery_agent (if provided) is appended to the pool — it is
        constructed separately because it needs state + company list.
        Returns list of sector result dicts.
        """
        # Filter sector agents by enabled_sectors setting.
        # SECTOR_AGENT_MAP maps sector name → agent class name (e.g. "Banks" → "BanksAgent").
        # Build reverse map so we can look up sector name from agent class name.
        if self.settings is not None:
            enabled = set(self.settings.enabled_sectors)
            _agent_to_sector = {v: k for k, v in SECTOR_AGENT_MAP.items()}
            agent_classes = [
                cls for cls in self._AGENT_CLASSES
                if _agent_to_sector.get(cls.__name__, cls.__name__) in enabled
            ]
        else:
            agent_classes = list(self._AGENT_CLASSES)

        vol_x   = self.settings.volume_spike_x if self.settings else None
        price_p = self.settings.price_move_pct  if self.settings else None
        agents  = [cls(self.openai_key, state, vol_x, price_p) for cls in agent_classes]
        if discovery_agent is not None and discovery_agent.tickers:
            # Only include DiscoveryAgent if "Discovery" is in enabled sectors (or no settings)
            if self.settings is None or "Discovery" in self.settings.enabled_sectors:
                agents.append(discovery_agent)
        elif discovery_agent is not None:
            print("[Discovery] No uncovered tickers found this cycle — skipping.")
        results: list[dict] = []

        print(f"[Manager] Running {len(agents)} sector agents in parallel...")
        with ThreadPoolExecutor(max_workers=self._PARALLEL_WORKERS) as executor:
            futures = {
                executor.submit(agent.run, pre_fetched, macro_text, sector_ctx): agent
                for agent in agents
            }
            for future in as_completed(futures):
                agent = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception:
                    print(f"[{agent.sector_name}] Agent error:\n{traceback.format_exc()}")
                    results.append({
                        "sector":        agent.sector_name,
                        "picks":         [],
                        "signals_count": 0,
                        "all_signals":   [],
                    })

        for r in results:
            n   = r.get("signals_count", 0)
            cnt = r.get("relevant_count", 0)
            top = r.get("best_pick", "none")
            pf  = r.get("portfolio", [])
            print(f"[{r['sector']}] {n} signals | {cnt} relevant stocks | portfolio: {len(pf)} | best: {top}")

        return results

    # ── Phase 3: Manager arbitration ─────────────────────────────────────────

    def _arbitrate(
        self,
        sector_results: list[dict],
        macro_text:     str,
        sector_ctx:     str,
    ) -> dict:
        """
        Build manager LLM input from sector portfolio results and call arbitrate().
        Manager receives the full ranked portfolio from each sector so it can make
        an informed cross-sector allocation decision — not just the top-1 pick.
        """
        manager_input = []
        for r in sector_results:
            portfolio = r.get("portfolio", [])
            if not portfolio:
                continue
            manager_input.append({
                "sector":          r["sector"],
                "best_pick":       r.get("best_pick", ""),
                "relevant_stocks": r.get("relevant_count", 0),
                "signals_total":   r.get("signals_count", 0),
                # Pass full portfolio so manager sees all options, not just #1
                "portfolio":       portfolio,
            })

        if not manager_input:
            print("[Manager] No sector picks — nothing to arbitrate.")
            return {}

        print(f"[Manager] Arbitrating {len(manager_input)} sectors...")
        report = self.llm.arbitrate(manager_input, macro_text, sector_ctx)
        if report:
            winner = report.get("stock_of_the_week", {}).get("ticker", "?")
            print(f"[Manager] Stock of the week: {winner}")
        return report

    # ── Full cycle ────────────────────────────────────────────────────────────

    def _run(self, state: dict, maya: MayaMonitor) -> None:
        excel = ExcelMemoryStore()
        # Restore dedup state from Excel if this is a fresh start (state was reset)
        excel.restore_sent_alerts(state, today())

        # Phase 1
        pre_fetched, macro_text, sector_ctx, companies = self._gather_cross_sector(state, maya)

        # Build DiscoveryAgent from full TASE universe (via Yahoo Finance Screener).
        # Priority: real .TA symbols that appeared in Maya filings this cycle.
        # IPO signals (TASE pseudo-tickers) are injected directly via DiscoveryAgent._filter_signals().
        priority = {s.ticker for s in pre_fetched if not s.ticker.startswith("TASE")}
        discovery = DiscoveryAgent(self.openai_key, state, companies, priority_symbols=priority)

        # Phase 2
        sector_results = self._run_sector_agents(pre_fetched, macro_text, sector_ctx, state, discovery)

        # Collect all signals for weekly accumulation
        all_signals: list[Signal] = list(pre_fetched)
        for r in sector_results:
            all_signals.extend(r.get("all_signals", []))
        self.accumulator.add(state, all_signals)

        # Update per-stock Maya filing history in memory
        mem = StockMemoryManager(state)
        _MAYA_TYPES = {
            "maya_ipo", "maya_spinoff", "maya_ma", "maya_contract",
            "maya_buyback", "maya_institutional", "maya_earnings",
            "maya_dividend", "maya_rights", "maya_management", "maya_filing",
        }
        for sig in pre_fetched:
            if sig.signal_type in _MAYA_TYPES:
                mem.update_maya_history(sig.ticker, sig)

        # Check user-defined custom alerts against all signals this cycle
        user_alerts = load_user_alerts()
        if user_alerts:
            fired = check_and_fire_alerts(user_alerts, all_signals)
            if fired:
                save_user_alerts(user_alerts)
                for alert, signal in fired:
                    msg = format_alert_message(alert, signal)
                    self.telegram.reply(alert.chat_id, msg)
                print(f"[UserAlerts] {len(fired)} custom alert(s) fired.")

        # Phase 3: Manager arbitration for quick alert
        top_n = self.settings.top_n_alerts if self.settings else TOP_N_ALERTS
        alerts_enabled = self.settings.alerts_enabled if self.settings else True
        report = self._arbitrate(sector_results, macro_text, sector_ctx)
        if report:
            report["macro_context"] = macro_text.split("\n\nGlobal headlines:")[0]
            # Persist to state so /weekly command can read it
            state["last_arbitration_report"] = report
            ranked = _report_to_ranked(report)
            # Skip tickers already alerted this week (no new catalyst)
            ranked = _filter_already_alerted(ranked, state)
            if ranked and alerts_enabled:
                sent = ranked[:top_n]
                self.telegram.send_quick_alerts(sent, top_n)
                _mark_alerted(sent, state)
                excel.log_sent_alerts(sent, "quick_alert", this_week_start(), today(), now_iso())

        # Daily summary at 17:00
        if self.accumulator.is_daily_report_due(state) and report:
            print("[Daily] Generating daily summary...")
            self.telegram.send("--- Daily TASE Summary ---")
            ranked_daily = _filter_already_alerted(_report_to_ranked(report), state)
            sent_daily = (ranked_daily or _report_to_ranked(report))[:3]
            self.telegram.send_quick_alerts(sent_daily, top_n=3)
            excel.log_sent_alerts(sent_daily, "daily_summary", this_week_start(), today(), now_iso())
            state["last_daily_report"] = now_iso()

        # Weekly Stock of the Week on Thursday
        if self.accumulator.is_weekly_report_due(state):
            print("[Weekly] Generating Stock of the Week report...")
            weekly_sigs = self.accumulator.get(state)
            if weekly_sigs and report:
                report = _maybe_promote_runner_up(report, weekly_sigs, state)
                report["macro_context"] = macro_text.split("\n\nGlobal headlines:")[0]
                self.telegram.send_weekly_report(report)
                winner_ticker = report.get("stock_of_the_week", {}).get("ticker", "")
                winner        = report.get("stock_of_the_week", {})
                print(f"[Weekly] Pick: {winner_ticker}")
                state["last_weekly_pick"] = winner_ticker
                excel.log_sent_alerts(
                    [{"ticker": winner_ticker, "name": winner.get("name", ""),
                      "score": winner.get("score", 0), "key_catalyst": winner.get("key_catalyst", "")}],
                    "weekly_pick", this_week_start(), today(), now_iso(),
                )
            state["last_weekly_report"] = now_iso()

        # Prune stale stock memory entries (inactive >30 days)
        mem    = StockMemoryManager(state)
        pruned = mem.prune_stale()
        print(f"[Memory] {mem.summary()} ({pruned} stale entries pruned)")

        # Persist memory to Excel (Sheet 1: full backup; Sheet 2: buy/watch picks only)
        excel.sync_active_memory(state)
        excel.log_research_cycle(sector_results, today())

        state["last_run_iso"] = now_iso()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _report_to_ranked(report: dict) -> list[dict]:
    """Convert manager arbitration output to the ranked list format TelegramReporter expects."""
    ranked: list[dict] = []
    sotw = report.get("stock_of_the_week", {})
    if sotw:
        ranked.append({
            "ticker":          sotw.get("ticker", ""),
            "name":            sotw.get("name", ""),
            "score":           sotw.get("score", 0),
            "signals_count":   sotw.get("signals_count", 0),
            "summary":         sotw.get("full_rationale", "")[:300],
            "top_signal":      sotw.get("key_catalyst", ""),
            "keywords":        sotw.get("keywords", []),
            "tier":            sotw.get("tier", ""),
            "technical_setup": sotw.get("technical_setup", ""),
            "main_risk":       sotw.get("main_risk", ""),
            "sector":          sotw.get("sector", ""),
        })
    for ru in report.get("runners_up", []):
        ranked.append({
            "ticker":          ru.get("ticker", ""),
            "name":            ru.get("name", ""),
            "score":           ru.get("score", 0),
            "signals_count":   0,
            "summary":         ru.get("summary", ""),
            "top_signal":      ru.get("key_catalyst", ""),
            "keywords":        [],
            "tier":            ru.get("tier", ""),
            "technical_setup": "",
            "main_risk":       "",
            "sector":          ru.get("sector", ""),
        })
    return ranked


def _filter_already_alerted(ranked: list[dict], state: dict) -> list[dict]:
    """
    Remove tickers that were already sent as quick alerts today.
    Prevents flooding the same stock every 15 minutes with no new news.
    """
    day     = today()
    alerted = state.get("alerted_today", {})
    # Drop entries from previous days
    alerted = {t: d for t, d in alerted.items() if d == day}
    state["alerted_today"] = alerted
    return [r for r in ranked if r.get("ticker") not in alerted]


def _mark_alerted(ranked: list[dict], state: dict) -> None:
    """Record tickers as alerted for today."""
    day     = today()
    alerted = state.get("alerted_today", {})
    for r in ranked:
        ticker = r.get("ticker")
        if ticker:
            alerted[ticker] = day
    state["alerted_today"] = alerted


def _maybe_promote_runner_up(report: dict, weekly_sigs: list, state: dict) -> dict:
    """
    If the stock_of_the_week is the same as last week's pick AND has no new
    signals this week, promote the first runner_up to winner instead.
    """
    sotw          = report.get("stock_of_the_week", {})
    winner_ticker = sotw.get("ticker", "")
    last_pick     = state.get("last_weekly_pick", "")

    if not winner_ticker or winner_ticker != last_pick:
        return report  # different pick — nothing to do

    # Check if this ticker generated any signals this week
    tickers_with_signals = {s.ticker for s in weekly_sigs}
    if winner_ticker in tickers_with_signals:
        return report  # new activity this week — keep as winner

    # Same stock, nothing new — promote first runner_up
    runners = report.get("runners_up", [])
    if not runners:
        return report  # no alternative, keep it

    print(f"[Weekly] {winner_ticker} same as last week with no new signals — promoting {runners[0].get('ticker')} to winner.")
    new_winner_ru = runners[0]
    report = dict(report)  # shallow copy to avoid mutating original
    report["stock_of_the_week"] = {
        "ticker":         new_winner_ru.get("ticker", ""),
        "name":           new_winner_ru.get("name", ""),
        "score":          new_winner_ru.get("score", 0),
        "signals_count":  0,
        "full_rationale": new_winner_ru.get("summary", ""),
        "key_catalyst":   new_winner_ru.get("key_catalyst", ""),
        "technical_setup": "",
        "main_risk":      "",
        "keywords":       [],
    }
    report["runners_up"] = runners[1:]
    return report
