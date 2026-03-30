"""
Data model: Signal dataclass, state persistence, and shared helper functions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from .config import STATE_FILE


# ─── Signal ────────────────────────────────────────────────────────────────────

@dataclass
class Signal:
    ticker:       str
    ticker_yf:    str
    company_name: str
    signal_type:  str     # maya_ipo | maya_earnings | maya_institutional | maya_contract |
                          # volume_spike | price_move | new_contract | institutional_investor |
                          # regulatory_approval | government_defense | partnership |
                          # israeli_news | global_news | earnings_calendar
    headline:     str
    detail:       str
    url:          str
    timestamp:    str     # ISO-8601
    keywords_hit: list[str] = field(default_factory=list)
    score:        float = 0.0
    event_date:   str   = ""   # YYYY-MM-DD — populated for earnings_calendar signals

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Signal":
        d.setdefault("keywords_hit", [])
        d.setdefault("score", 0.0)
        d.setdefault("event_date", "")
        return Signal(**d)


# ─── State persistence ─────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            # Restore memory from Excel backup if stock_memory was wiped
            if not state.get("stock_memory"):
                _restore_memory_from_excel(state)
            return state
        except Exception:
            pass
    state = {
        "last_run_iso":            "",
        "last_daily_report":       "",
        "last_weekly_report":      "",
        "seen_maya_report_ids":    [],
        "seen_signal_keys":        [],
        "weekly_signals":          [],
        "week_start":              "",
        "tase_company_cache":      {"fetched_at": "", "companies": []},
        "ticker_validation_cache": {},   # {ABCD.TA: {valid: bool, checked: YYYY-MM-DD}}
        "tase_universe_cache":     {"fetched_at": "", "tickers": []},
    }
    _restore_memory_from_excel(state)
    return state


def _restore_memory_from_excel(state: dict) -> None:
    """Attempt to restore stock_memory from Excel backup (silent on failure)."""
    try:
        from .analysis.excel_memory import ExcelMemoryStore
        restored = ExcelMemoryStore().restore_to_state(state)
        if restored:
            print(f"[Memory] Restored {restored} tickers from Excel backup.")
    except Exception:
        pass


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ─── Helpers ───────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def this_week_start() -> str:
    """Monday of current week as YYYY-MM-DD."""
    d = datetime.now()
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")


def signal_key(s: Signal) -> str:
    return f"{s.ticker}_{s.signal_type}_{s.timestamp[:10]}"


def days_to_earnings(s: Signal) -> Optional[int]:
    """Days until earnings event, or None if signal is not earnings_calendar."""
    if s.signal_type != "earnings_calendar" or not s.event_date:
        return None
    try:
        ed = datetime.strptime(s.event_date[:10], "%Y-%m-%d").date()
        return (ed - datetime.now().date()).days
    except Exception:
        return None


def build_company_map(companies: list[dict]) -> dict[str, str]:
    """{company_name_lowercase: ticker}"""
    result = {}
    for c in companies:
        name   = c.get("CompanyName", c.get("Name", ""))
        ticker = c.get("CompanyTicker", c.get("Symbol", ""))
        if name and ticker:
            result[name.lower()] = ticker
    return result


def strip_json_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.lower().startswith("json"):
            raw = raw[4:]
    return raw.strip()


def refresh_company_cache(state: dict, maya) -> list[dict]:
    """Returns TASE company list, refreshing from Maya if cache is >24h old."""
    cache          = state.get("tase_company_cache", {})
    fetched_at_str = cache.get("fetched_at", "")
    companies      = cache.get("companies", [])
    cache_stale    = True

    if fetched_at_str and companies:
        try:
            fetched_at  = datetime.fromisoformat(fetched_at_str)
            cache_stale = (datetime.now(timezone.utc) - fetched_at.astimezone(timezone.utc)) > timedelta(hours=24)
        except Exception:
            pass

    if cache_stale:
        print("[Maya] Refreshing company list...")
        fresh = maya.fetch_company_list()
        if fresh:
            companies = fresh
            state["tase_company_cache"] = {"fetched_at": now_iso(), "companies": companies}
            print(f"[Maya] {len(companies)} companies loaded.")
        else:
            print("[Maya] Company list unavailable, using cache.")

    return companies
