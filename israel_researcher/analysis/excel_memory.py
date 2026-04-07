"""
ExcelMemoryStore — durable Excel persistence for per-stock research memory.

Two-sheet workbook: israel_researcher_memory.xlsx

  Sheet 1 "Active Memory": full mirror of state["stock_memory"], overwritten each cycle.
    → If israel_researcher_state.json is deleted, this is used to restore memory.

  Sheet 2 "Research Log": append-only curated history.
    → Only buy/watch tier picks from sector LLM outputs are written here.
    → Deduplicated by (Date, Ticker) so re-runs don't create duplicate rows.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

EXCEL_PATH = Path(__file__).parent.parent.parent / "data" / "israel_researcher_memory.xlsx"

_ACTIVE_SHEET  = "Active Memory"
_LOG_SHEET     = "Research Log"
_ALERTS_SHEET  = "Sent Alerts"

_ACTIVE_COLS = [
    "Ticker", "Company", "Last Active", "Consecutive Cycles",
    "RSI", "MA Trend", "vs 52w High (%)", "Best Score",
    "Recent News", "Analyst Notes", "Notes Date",
]

_LOG_COLS = [
    "Date", "Ticker", "Company", "Sector", "Tier", "Score",
    "Key Catalyst", "Rationale", "Signal Types", "RSI", "MA Trend", "Market Cap (M ILS)",
]

_ALERTS_COLS = [
    "Timestamp", "Week", "Date", "Type", "Ticker", "Company", "Score", "Key Catalyst",
]


class ExcelMemoryStore:
    """Manages Excel-backed persistence for stock research memory."""

    # ── Sheet 1: full backup ──────────────────────────────────────────────────

    def sync_active_memory(self, state: dict) -> None:
        """Overwrite Sheet 1 with current state["stock_memory"]. Called end of every cycle."""
        stock_memory: dict = state.get("stock_memory", {})
        if not stock_memory:
            return

        rows = []
        for ticker, mem in stock_memory.items():
            fund = mem.get("fundamentals") or {}
            hist = mem.get("signal_history") or []
            best_score = max((h.get("final_score", 0) for h in hist), default=0)
            last_active = hist[-1]["date"] if hist else mem.get("fundamentals_date", "")
            rows.append({
                "Ticker":              ticker,
                "Company":             ticker,   # company_name not stored separately in memory
                "Last Active":         last_active,
                "Consecutive Cycles":  mem.get("consecutive_active", 0),
                "RSI":                 fund.get("rsi_14"),
                "MA Trend":            fund.get("ma_trend", ""),
                "vs 52w High (%)":     fund.get("pct_vs_52w_high"),
                "Best Score":          best_score,
                "Recent News":         mem.get("recent_news", ""),
                "Analyst Notes":       mem.get("analyst_notes", ""),
                "Notes Date":          mem.get("notes_date", ""),
            })

        new_df = pd.DataFrame(rows, columns=_ACTIVE_COLS)
        new_df["RSI"]            = pd.to_numeric(new_df["RSI"],            errors="coerce")
        new_df["vs 52w High (%)"]= pd.to_numeric(new_df["vs 52w High (%)"],errors="coerce")
        new_df["Best Score"]     = pd.to_numeric(new_df["Best Score"],     errors="coerce")

        if EXCEL_PATH.exists():
            try:
                existing = pd.read_excel(EXCEL_PATH, sheet_name=_ACTIVE_SHEET)
                # Drop rows for tickers we're about to update
                existing = existing[~existing["Ticker"].isin(new_df["Ticker"])]
                merged = pd.concat([existing, new_df], ignore_index=True)
            except Exception:
                merged = new_df
        else:
            merged = new_df

        merged = merged.sort_values("Last Active", ascending=False).reset_index(drop=True)
        self._write_sheet(_ACTIVE_SHEET, merged)

    # ── Sheet 2: curated log ──────────────────────────────────────────────────

    def log_research_cycle(self, sector_results: list[dict], cycle_date: str) -> None:
        """Append buy/watch picks from this cycle to Sheet 2. Dedup by (Date, Ticker)."""
        rows = []
        for result in sector_results:
            sector = result.get("sector", "")
            for pick in result.get("portfolio", []):
                tier = pick.get("tier", "monitor")
                if tier not in ("buy", "watch"):
                    continue
                fund = _pick_fundamentals(pick)
                mktcap_raw = fund.get("market_cap")
                mktcap_m   = round(mktcap_raw / 1_000_000, 1) if mktcap_raw else None
                rows.append({
                    "Date":               cycle_date,
                    "Ticker":             pick.get("ticker", ""),
                    "Company":            pick.get("name", pick.get("ticker", "")),
                    "Sector":             sector,
                    "Tier":               tier,
                    "Score":              pick.get("score", 0),
                    "Key Catalyst":       pick.get("key_catalyst", ""),
                    "Rationale":          (pick.get("rationale", ""))[:300],
                    "Signal Types":       ", ".join(pick.get("keywords", [])),
                    "RSI":                fund.get("rsi_14"),
                    "MA Trend":           fund.get("ma_trend", ""),
                    "Market Cap (M ILS)": mktcap_m,
                })

        if not rows:
            return

        new_df = pd.DataFrame(rows, columns=_LOG_COLS)
        new_df["RSI"]   = pd.to_numeric(new_df["RSI"],   errors="coerce")
        new_df["Score"] = pd.to_numeric(new_df["Score"], errors="coerce")

        if EXCEL_PATH.exists():
            try:
                existing = pd.read_excel(EXCEL_PATH, sheet_name=_LOG_SHEET)
                combined = pd.concat([existing, new_df], ignore_index=True)
                combined = combined.drop_duplicates(subset=["Date", "Ticker"], keep="last")
            except Exception:
                combined = new_df
        else:
            combined = new_df

        combined = combined.sort_values(["Date", "Score"], ascending=[False, False]).reset_index(drop=True)
        self._write_sheet(_LOG_SHEET, combined)

    # ── Sheet 3: sent-alert log ───────────────────────────────────────────────

    def log_sent_alerts(
        self,
        alerts:      list[dict],
        alert_type:  str,
        week:        str,
        date:        str,
        timestamp:   str,
    ) -> None:
        """
        Append rows to Sheet 3 ("Sent Alerts") for every ticker just sent.
        alert_type: "quick_alert" | "weekly_pick" | "daily_summary"
        """
        if not alerts:
            return

        rows = [
            {
                "Timestamp":   timestamp,
                "Week":        week,
                "Date":        date,
                "Type":        alert_type,
                "Ticker":      a.get("ticker", ""),
                "Company":     a.get("name", ""),
                "Score":       a.get("score", 0),
                "Key Catalyst": a.get("top_signal") or a.get("key_catalyst", ""),
            }
            for a in alerts
            if a.get("ticker")
        ]
        if not rows:
            return

        new_df = pd.DataFrame(rows, columns=_ALERTS_COLS)
        new_df["Score"] = pd.to_numeric(new_df["Score"], errors="coerce")

        if EXCEL_PATH.exists():
            try:
                existing = pd.read_excel(EXCEL_PATH, sheet_name=_ALERTS_SHEET)
                combined = pd.concat([existing, new_df], ignore_index=True)
            except Exception:
                combined = new_df
        else:
            combined = new_df

        combined = combined.sort_values("Timestamp", ascending=False).reset_index(drop=True)
        self._write_sheet(_ALERTS_SHEET, combined)

    def restore_sent_alerts(self, state: dict, current_day: str) -> None:
        """
        On startup, repopulate state["alerted_today"] and state["last_weekly_pick"]
        from the Sent Alerts sheet so dedup survives a state-file reset.
        Only re-loads rows from current_day to keep dedup scoped to today.
        """
        if not EXCEL_PATH.exists():
            return
        try:
            df = pd.read_excel(EXCEL_PATH, sheet_name=_ALERTS_SHEET)
        except Exception:
            return

        # Restore quick-alert dedup for today
        if "alerted_today" not in state or not state["alerted_today"]:
            today_rows = df[df["Date"].astype(str) == current_day]
            alerted: dict = {}
            for _, row in today_rows.iterrows():
                ticker = str(row.get("Ticker", "")).strip()
                if ticker:
                    alerted[ticker] = current_day
            if alerted:
                state["alerted_today"] = alerted
                print(f"[Excel] Restored {len(alerted)} alerted tickers for today {current_day}")

        # Restore last weekly pick
        if "last_weekly_pick" not in state or not state["last_weekly_pick"]:
            weekly_rows = df[df["Type"].astype(str) == "weekly_pick"].sort_values(
                "Timestamp", ascending=False
            )
            if not weekly_rows.empty:
                last_ticker = str(weekly_rows.iloc[0]["Ticker"]).strip()
                if last_ticker:
                    state["last_weekly_pick"] = last_ticker
                    print(f"[Excel] Restored last_weekly_pick: {last_ticker}")

    # ── State restore ─────────────────────────────────────────────────────────

    def restore_to_state(self, state: dict) -> int:
        """Load Sheet 1 back into state["stock_memory"] if it's empty. Returns count restored."""
        if not EXCEL_PATH.exists():
            return 0
        try:
            df = pd.read_excel(EXCEL_PATH, sheet_name=_ACTIVE_SHEET)
        except Exception:
            return 0

        stock_memory = state.setdefault("stock_memory", {})
        for _, row in df.iterrows():
            ticker = str(row.get("Ticker", "")).strip()
            if not ticker:
                continue
            entry: dict = {}
            if pd.notna(row.get("RSI")) or row.get("MA Trend"):
                entry["fundamentals"] = {
                    "rsi_14":           _float_or_none(row.get("RSI")),
                    "ma_trend":         str(row.get("MA Trend", "") or ""),
                    "pct_vs_52w_high":  _float_or_none(row.get("vs 52w High (%)")),
                }
                entry["fundamentals_date"] = str(row.get("Last Active", "") or "")
            if row.get("Recent News"):
                entry["recent_news"] = str(row["Recent News"])
                entry["news_date"]   = str(row.get("Last Active", "") or "")
            if row.get("Analyst Notes"):
                entry["analyst_notes"] = str(row["Analyst Notes"])
                entry["notes_date"]    = str(row.get("Notes Date", "") or "")
            entry["consecutive_active"] = int(row.get("Consecutive Cycles", 0) or 0)
            entry["signal_history"]     = []
            stock_memory[ticker] = entry

        return len(stock_memory)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _write_sheet(self, sheet_name: str, df: pd.DataFrame) -> None:
        """Write a single sheet to the workbook, preserving all other sheets."""
        if EXCEL_PATH.exists():
            with pd.ExcelWriter(
                EXCEL_PATH, engine="openpyxl", mode="a", if_sheet_exists="replace"
            ) as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        else:
            # First time: create file with all three sheets as empty placeholders
            all_sheets = {
                _ACTIVE_SHEET: _ACTIVE_COLS,
                _LOG_SHEET:    _LOG_COLS,
                _ALERTS_SHEET: _ALERTS_COLS,
            }
            with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl", mode="w") as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                for s, cols in all_sheets.items():
                    if s != sheet_name:
                        pd.DataFrame(columns=cols).to_excel(writer, sheet_name=s, index=False)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _float_or_none(val) -> float | None:
    try:
        v = float(val)
        return None if (v != v) else v   # NaN check
    except (TypeError, ValueError):
        return None


def _pick_fundamentals(pick: dict) -> dict:
    """Extract fundamentals dict from a portfolio pick if embedded (not always present)."""
    return pick.get("fundamentals") or {}
