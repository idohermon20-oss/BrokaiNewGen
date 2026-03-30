"""
ConvergenceEngine — groups signals by ticker, computes convergence scores.
WeeklyAccumulator  — manages the weekly pool of signals in state.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from ..models import Signal, signal_key, days_to_earnings, now_iso, this_week_start


class ConvergenceEngine:
    """
    Groups signals by ticker and computes a convergence score.
    Only tickers with 2+ INDEPENDENT signal categories qualify for quick alerts.
    Earnings proximity is factored in as a score booster.
    """

    MULTIPLIERS: dict = {
        # ── Earnings × other ─────────────────────────────────────────────────
        frozenset(["earnings_calendar", "volume_spike"]):             2.5,
        frozenset(["earnings_calendar", "new_contract"]):             2.2,
        frozenset(["earnings_calendar", "maya_contract"]):            2.2,
        frozenset(["earnings_calendar", "institutional_investor"]):   2.0,
        frozenset(["earnings_calendar", "maya_institutional"]):       2.0,
        frozenset(["earnings_calendar", "regulatory_approval"]):      2.3,
        frozenset(["earnings_calendar", "government_defense"]):       2.2,
        frozenset(["earnings_calendar", "breakout"]):                 2.3,
        frozenset(["earnings_calendar", "dual_listed_move"]):         2.2,
        frozenset(["earnings_calendar", "shareholder_return"]):       1.9,
        frozenset(["earnings_calendar", "maya_earnings"]):            1.8,
        frozenset(["earnings_calendar", "ma_crossover"]):             2.0,
        # ── Volume spike × other ─────────────────────────────────────────────
        frozenset(["volume_spike",       "new_contract"]):            1.8,
        frozenset(["volume_spike",       "maya_contract"]):           1.8,
        frozenset(["volume_spike",       "institutional_investor"]):  1.8,
        frozenset(["volume_spike",       "maya_institutional"]):      1.8,
        frozenset(["volume_spike",       "regulatory_approval"]):     1.9,
        frozenset(["volume_spike",       "maya_earnings"]):           2.3,
        frozenset(["volume_spike",       "government_defense"]):      2.0,
        frozenset(["volume_spike",       "maya_ma"]):                 2.0,
        frozenset(["volume_spike",       "maya_ipo"]):                2.2,
        frozenset(["volume_spike",       "breakout"]):                1.8,
        frozenset(["volume_spike",       "dual_listed_move"]):        2.0,
        frozenset(["volume_spike",       "ma_crossover"]):            1.7,
        frozenset(["volume_spike",       "maya_buyback"]):            1.9,
        frozenset(["volume_spike",       "maya_spinoff"]):            2.1,
        frozenset(["volume_spike",       "shareholder_return"]):      1.7,
        # ── Contract × other ─────────────────────────────────────────────────
        frozenset(["new_contract",       "institutional_investor"]):  1.6,
        frozenset(["new_contract",       "maya_institutional"]):      1.6,
        frozenset(["new_contract",       "regulatory_approval"]):     1.9,
        frozenset(["new_contract",       "government_defense"]):      2.0,
        frozenset(["new_contract",       "dual_listed_move"]):        1.9,
        frozenset(["new_contract",       "breakout"]):                2.0,
        frozenset(["new_contract",       "ma_crossover"]):            1.8,
        frozenset(["maya_contract",      "institutional_investor"]):  1.7,
        frozenset(["maya_contract",      "maya_institutional"]):      1.7,
        frozenset(["maya_contract",      "government_defense"]):      2.0,
        frozenset(["maya_contract",      "breakout"]):                2.0,
        frozenset(["maya_contract",      "dual_listed_move"]):        2.0,
        # ── Institutional × other ─────────────────────────────────────────────
        frozenset(["maya_institutional", "volume_spike"]):            1.8,
        frozenset(["maya_institutional", "breakout"]):                1.8,
        frozenset(["maya_institutional", "dual_listed_move"]):        1.9,
        frozenset(["maya_institutional", "new_contract"]):            1.6,
        # ── Technical × fundamental ──────────────────────────────────────────
        frozenset(["breakout",           "dual_listed_move"]):        2.0,
        frozenset(["breakout",           "regulatory_approval"]):     2.1,
        frozenset(["breakout",           "shareholder_return"]):      1.8,
        frozenset(["ma_crossover",       "new_contract"]):            1.8,
        frozenset(["ma_crossover",       "dual_listed_move"]):        1.9,
        frozenset(["ma_crossover",       "oversold_bounce"]):         1.9,
        frozenset(["oversold_bounce",    "earnings_calendar"]):       2.3,
        frozenset(["oversold_bounce",    "volume_spike"]):            1.9,
        frozenset(["oversold_bounce",    "maya_contract"]):           2.0,
        frozenset(["oversold_bounce",    "new_contract"]):            2.0,
        frozenset(["oversold_bounce",    "maya_institutional"]):      1.9,
        frozenset(["oversold_bounce",    "dual_listed_move"]):        2.0,
        frozenset(["oversold_bounce",    "breakout"]):                1.8,
        frozenset(["relative_strength",  "earnings_calendar"]):       2.2,
        frozenset(["relative_strength",  "new_contract"]):            1.9,
        frozenset(["relative_strength",  "maya_contract"]):           1.9,
        frozenset(["relative_strength",  "breakout"]):                2.1,
        frozenset(["relative_strength",  "dual_listed_move"]):        2.0,
        frozenset(["relative_strength",  "volume_spike"]):            1.8,
        frozenset(["dual_listed_move",   "regulatory_approval"]):     2.0,
        frozenset(["dual_listed_move",   "maya_earnings"]):           2.2,
        frozenset(["dual_listed_move",   "maya_buyback"]):            1.8,
        # ── Regulatory × other ───────────────────────────────────────────────
        frozenset(["regulatory_approval","government_defense"]):      2.1,
        frozenset(["regulatory_approval","partnership"]):             1.8,
        # ── Shareholder return × other ───────────────────────────────────────
        frozenset(["maya_buyback",          "institutional_investor"]):  1.9,
        frozenset(["maya_dividend",         "institutional_investor"]):  1.6,
        frozenset(["maya_spinoff",          "institutional_investor"]):  1.9,
        frozenset(["maya_spinoff",          "new_contract"]):            2.0,
        # ── Low reversal × catalyst ───────────────────────────────────────────
        frozenset(["low_reversal",          "earnings_calendar"]):        2.4,
        frozenset(["low_reversal",          "maya_contract"]):            2.1,
        frozenset(["low_reversal",          "new_contract"]):             2.1,
        frozenset(["low_reversal",          "maya_buyback"]):             2.2,
        frozenset(["low_reversal",          "maya_institutional"]):       2.0,
        frozenset(["low_reversal",          "institutional_investor"]):   2.0,
        frozenset(["low_reversal",          "dual_listed_move"]):         2.0,
        frozenset(["low_reversal",          "oversold_bounce"]):          1.9,
        frozenset(["low_reversal",          "volume_spike"]):             1.9,
        # ── Consecutive momentum × catalyst ──────────────────────────────────
        frozenset(["consecutive_momentum",  "earnings_calendar"]):        2.2,
        frozenset(["consecutive_momentum",  "new_contract"]):             2.0,
        frozenset(["consecutive_momentum",  "maya_contract"]):            2.0,
        frozenset(["consecutive_momentum",  "breakout"]):                 2.1,
        frozenset(["consecutive_momentum",  "relative_strength"]):        1.9,
        frozenset(["consecutive_momentum",  "dual_listed_move"]):         2.0,
        frozenset(["consecutive_momentum",  "volume_spike"]):             1.8,
        # ── Sector macro signals × individual signals ─────────────────────────
        frozenset(["oil_correlation",       "volume_spike"]):             1.9,
        frozenset(["oil_correlation",       "earnings_calendar"]):        2.0,
        frozenset(["oil_correlation",       "maya_contract"]):            2.0,
        frozenset(["oil_correlation",       "breakout"]):                 1.9,
        frozenset(["oil_correlation",       "low_reversal"]):             2.0,
        frozenset(["shekel_move",           "volume_spike"]):             1.7,
        frozenset(["shekel_move",           "earnings_calendar"]):        1.9,
        frozenset(["shekel_move",           "dual_listed_move"]):         1.9,
        frozenset(["shekel_move",           "maya_contract"]):            1.8,
        frozenset(["shekel_move",           "breakout"]):                 1.8,
        frozenset(["defense_tailwind",      "volume_spike"]):             1.9,
        frozenset(["defense_tailwind",      "earnings_calendar"]):        2.1,
        frozenset(["defense_tailwind",      "maya_contract"]):            2.2,
        frozenset(["defense_tailwind",      "breakout"]):                 2.0,
        frozenset(["defense_tailwind",      "dual_listed_move"]):         2.0,
        frozenset(["defense_tailwind",      "relative_strength"]):        2.0,
        frozenset(["sector_peer_move",      "volume_spike"]):             1.8,
        frozenset(["sector_peer_move",      "earnings_calendar"]):        2.0,
        frozenset(["sector_peer_move",      "dual_listed_move"]):         1.9,
        frozenset(["sector_peer_move",      "breakout"]):                 1.9,
        frozenset(["sector_peer_move",      "maya_contract"]):            1.9,
        # ── Geopolitical × technicals/fundamentals ───────────────────────────
        frozenset(["geopolitical",          "volume_spike"]):             2.1,
        frozenset(["geopolitical",          "breakout"]):                 2.0,
        frozenset(["geopolitical",          "earnings_calendar"]):        2.1,
        frozenset(["geopolitical",          "dual_listed_move"]):         2.2,
        frozenset(["geopolitical",          "maya_contract"]):            2.2,
        frozenset(["geopolitical",          "defense_tailwind"]):         2.3,
        # ── Web-extracted news × technicals/fundamentals ─────────────────────
        frozenset(["earnings",              "volume_spike"]):             2.3,
        frozenset(["earnings",              "breakout"]):                 2.2,
        frozenset(["earnings",              "earnings_calendar"]):        2.0,
        frozenset(["earnings",              "dual_listed_move"]):         2.1,
        frozenset(["earnings",              "oversold_bounce"]):          2.2,
        frozenset(["new_contract",          "earnings"]):                 2.0,
        frozenset(["ipo",                   "volume_spike"]):             2.2,
        frozenset(["ipo",                   "breakout"]):                 2.1,
        frozenset(["buyback",               "volume_spike"]):             1.9,
        frozenset(["buyback",               "oversold_bounce"]):          2.1,
        frozenset(["buyback",               "low_reversal"]):             2.1,
        frozenset(["general_news",          "volume_spike"]):             1.7,
        frozenset(["general_news",          "breakout"]):                 1.7,
        frozenset(["general_news",          "earnings_calendar"]):        1.8,
    }

    BASE_SCORES: dict = {
        # Maya-sourced signals (highest credibility — regulatory filings)
        "maya_ipo":           50,
        "maya_spinoff":       48,
        "maya_ma":            45,
        "maya_contract":      45,
        "maya_buyback":       42,   # buyback = management bullish on stock
        "maya_institutional": 40,
        "maya_earnings":      35,
        "maya_dividend":      32,
        "maya_rights":        22,
        "maya_management":    18,
        "maya_filing":        10,   # generic filing (no specific type matched)
        # News/enriched signal types
        "new_contract":           45,
        "government_defense":     45,
        "institutional_investor": 40,
        "regulatory_approval":    42,
        "shareholder_return":     32,
        "partnership":            30,
        "financial_event":        25,
        "management_change":      18,
        # Technical signals
        "breakout":           35,   # 52w high breakout with volume
        "dual_listed_move":   35,   # US market overnight move
        "ma_crossover":       28,   # golden cross
        "oversold_bounce":       30,  # RSI<32 + rising volume = accumulation setup
        "low_reversal":          32,  # bouncing from 52w low with volume = value entry
        "consecutive_momentum":  20,  # 4+ up sessions with building volume
        "relative_strength":     22,  # outperforming TA-125 by 5%+ over 20 days
        # Sector macro signals
        "oil_correlation":       25,  # oil move >2% -> energy stocks
        "shekel_move":           20,  # USD/ILS move >1.5% -> exporters/importers
        "defense_tailwind":      28,  # VIX >22 -> defense sector
        "sector_peer_move":      22,  # US sector index move -> Israeli sector sympathy
        "volume_spike":          25,
        "price_move":            20,
        # Calendar
        "earnings_calendar":  20,
        # News (base; enricher will upgrade to specific type)
        "israeli_news":       10,
        "global_news":        10,
        # Web-extracted news signals (LLM-classified, higher quality than RSS)
        "general_news":       15,   # LLM found material news but no specific type
        "earnings":           35,   # web news: earnings beat/miss/guidance
        "buyback":            30,   # web news: buyback announcement
        "dividend":           28,   # web news: dividend change
        "ipo":                38,   # web news: new listing / secondary offer
        "geopolitical":       38,   # web news: defense contract, sanctions, security event
    }

    def group_by_ticker(self, signals: list[Signal]) -> dict[str, dict]:
        groups: dict[str, dict] = {}

        for s in signals:
            if not s.ticker or s.ticker == "GENERAL":
                continue
            if s.ticker not in groups:
                groups[s.ticker] = {
                    "signals":          [],
                    "categories":       set(),
                    "days_to_earnings": None,
                    "urgent_earnings":  False,
                    "base_score":       0,
                    "multiplier":       1.0,
                    "final_score":      0,
                    "converged":        False,
                    "company_name":     s.company_name,
                }
            g = groups[s.ticker]
            g["signals"].append(s)
            g["categories"].add(s.signal_type)
            g["base_score"] += self.BASE_SCORES.get(s.signal_type, 5)

            dte = days_to_earnings(s)
            if dte is not None:
                if g["days_to_earnings"] is None or dte < g["days_to_earnings"]:
                    g["days_to_earnings"] = dte

        for ticker, g in groups.items():
            dte = g["days_to_earnings"]
            # Earnings urgency bonus — kept separate from base_score so that:
            #   1. signal_strength sent to LLM reflects ONLY raw signal weight (not earnings urgency)
            #   2. The multiplier rewards signal convergence on the clean signal base
            #   3. Earnings proximity is added on top after multiplier (not inflating it)
            dte_bonus = 0
            if dte is not None:
                if dte <= 0:
                    dte_bonus            = 80
                    g["urgent_earnings"] = True
                elif dte == 1:
                    dte_bonus            = 70
                    g["urgent_earnings"] = True
                elif dte == 2:
                    dte_bonus            = 60
                    g["urgent_earnings"] = True
                elif dte == 3:
                    dte_bonus            = 45
                    g["urgent_earnings"] = True
                elif dte <= 7:
                    dte_bonus = 25
                elif dte <= 14:
                    dte_bonus = 12

            cats      = g["categories"]
            best_mult = 1.0
            for pair, mult in self.MULTIPLIERS.items():
                if pair.issubset(cats) and mult > best_mult:
                    best_mult = mult
            if len(cats) >= 3:
                best_mult *= 1.3

            g["multiplier"]  = round(best_mult, 2)
            # Multiplier applies to signal base only; earnings urgency bonus added on top
            g["final_score"] = min(100, round(g["base_score"] * best_mult) + dte_bonus)
            g["converged"]   = len(cats) >= 2
            g["categories"]  = sorted(g["categories"])

        return groups

    def converged_only(self, grouped: dict[str, dict]) -> dict[str, dict]:
        return {t: g for t, g in grouped.items() if g["converged"]}

    def to_llm_input(self, grouped: dict[str, dict]) -> str:
        """
        Build the JSON input for the sector / quick LLM scorer.
        NOTE: `final_score` is intentionally OMITTED so the LLM scores from scratch
        rather than anchoring on a pre-computed number.
        `signal_strength` and `convergence_multiplier` are provided as raw signal
        quality indicators only — they describe QUANTITY/CONVERGENCE of signals,
        NOT the investment score.
        """
        compact = {
            ticker: {
                "company":               g["company_name"],
                "categories_hit":        list(g["categories"]),
                "signals_count":         len(g["signals"]),
                "days_to_earnings":      g["days_to_earnings"],
                "urgent_earnings":       g["urgent_earnings"],
                "signal_strength":       g["base_score"],       # raw signal weight sum
                "convergence_multiplier": g["multiplier"],      # how well signals corroborate each other
                "top_signals": [
                    {"type": s.signal_type, "headline": s.headline,
                     "detail": s.detail[:120], "keywords": s.keywords_hit}
                    for s in g["signals"][:5]
                ],
            }
            for ticker, g in grouped.items()
        }
        return json.dumps(compact, ensure_ascii=False)


class WeeklyAccumulator:
    """Manages the weekly pool of signals in state."""

    def add(self, state: dict, new_signals: list[Signal]) -> None:
        week = this_week_start()
        if state.get("week_start") != week:
            state["weekly_signals"] = []
            state["week_start"]     = week

        existing_keys = {
            s["ticker"] + s["signal_type"] + s.get("event_date", s["timestamp"][:10])
            for s in state["weekly_signals"]
        }
        for s in new_signals:
            # For earnings_calendar, deduplicate by event_date (not scan date)
            # so the same earnings event isn't added every 15-min cycle
            dedup_date = s.event_date if (s.signal_type == "earnings_calendar" and s.event_date) else s.timestamp[:10]
            key = s.ticker + s.signal_type + dedup_date
            if key not in existing_keys:
                state["weekly_signals"].append(s.to_dict())
                existing_keys.add(key)

        # Safety cap: keep at most 500 signals to avoid LLM context overflow
        if len(state["weekly_signals"]) > 500:
            state["weekly_signals"] = state["weekly_signals"][-500:]

    def get(self, state: dict) -> list[Signal]:
        return [Signal.from_dict(d) for d in state.get("weekly_signals", [])]

    def is_weekly_report_due(self, state: dict) -> bool:
        """True on Thursday, once per week."""
        now = datetime.now()
        if now.weekday() != 3:
            return False
        last = state.get("last_weekly_report", "")
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is not None:
                last_dt = last_dt.replace(tzinfo=None)
            return (now - last_dt).days >= 6
        except Exception:
            return True

    def is_daily_report_due(self, state: dict) -> bool:
        """True after 17:00, once per day."""
        now = datetime.now()
        if now.hour < 17:
            return False
        last = state.get("last_daily_report", "")
        if not last:
            return True
        try:
            return datetime.fromisoformat(last).date() < now.date()
        except Exception:
            return True
