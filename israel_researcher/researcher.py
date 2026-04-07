"""
Main research cycle and entry point.

The monolithic pipeline has been replaced by ResearchManager which uses
sector-specialized agents (BanksAgent, TechDefenseAgent, EnergyAgent,
PharmaAgent, RealEstateAgent, TelecomConsumerAgent) running in parallel,
coordinated by a Manager LLM that acts as the CIO making the final pick.

The interactive Telegram bot (BotServer) runs as a daemon thread alongside the
main research loop, polling for user messages and responding to slash commands
and natural-language Q&A without disrupting the research cycle.
"""

from __future__ import annotations

import threading
import time
import traceback

from .agents.manager import ResearchManager
from .bot import BotServer, load_bot_settings
from .config import (
    BOT_TOKEN, CHAT_ID, OPENAI_API_KEY,
    CHECK_INTERVAL_SECONDS, TASE_MAJOR_TICKERS,
)
from .models import load_state, save_state


def run_research_cycle(
    openai_key: str,
    bot_token:  str,
    chat_id:    str,
    settings=None,
) -> None:
    state   = load_state()
    manager = ResearchManager(openai_key, bot_token, chat_id, settings=settings)
    manager.run_cycle(state)


def main() -> None:
    settings = load_bot_settings()

    print("[START] Israel Stock Researcher (Multi-Agent)")
    print(f"  Scan interval : {settings.scan_interval_seconds // 60} min")
    print(f"  Sector agents : Banks | TechDefense | Energy | Pharma | RealEstate | TelecomConsumer")
    print(f"  Daily report  : 17:00")
    print(f"  Weekly report : Thursday 17:00")
    print(f"  Language      : {settings.language}")
    print(f"  Alerts        : {'enabled' if settings.alerts_enabled else 'disabled'}")
    print()

    # Shared state reference and lock — bot daemon thread reads state briefly
    state_ref:  dict = {"current": {}}
    state_lock: threading.RLock = threading.RLock()

    def _state_getter() -> dict:
        return state_ref["current"]

    # Start bot polling daemon thread
    bot = BotServer(
        bot_token        = BOT_TOKEN,
        default_chat_id  = CHAT_ID,
        settings         = settings,
        state_getter     = _state_getter,
        state_lock       = state_lock,
    )
    bot.start_daemon()

    while True:
        try:
            # Refresh shared state snapshot before cycle
            with state_lock:
                state_ref["current"] = load_state()

            # Refresh financial snapshot cache once per day (for screen_stocks bot tool)
            _state_now = state_ref["current"]
            _today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
            if _state_now.get("last_financial_cache_refresh") != _today:
                try:
                    from .sources.market import refresh_financial_snapshot_cache
                    refresh_financial_snapshot_cache(TASE_MAJOR_TICKERS, _state_now)
                    _state_now["last_financial_cache_refresh"] = _today
                    save_state(_state_now)
                    with state_lock:
                        state_ref["current"] = _state_now
                    print(f"[FinSnap] Daily financial snapshot refreshed ({len(TASE_MAJOR_TICKERS)} tickers)")
                except Exception as _fe:
                    print(f"[FinSnap] Refresh failed (non-fatal): {_fe}")

            run_research_cycle(
                openai_key = OPENAI_API_KEY,
                bot_token  = BOT_TOKEN,
                chat_id    = CHAT_ID,
                settings   = settings,
            )

            # Refresh shared state snapshot after cycle (so /weekly has fresh data)
            with state_lock:
                state_ref["current"] = load_state()

        except KeyboardInterrupt:
            print("\n[EXIT] Stopped.")
            break
        except Exception:
            print("[ERR]", traceback.format_exc())

        # Dynamic sleep — /set_interval takes effect here
        interval = settings.scan_interval_seconds
        print(f"[Sleep] Next cycle in {interval // 60} min ({interval}s)")
        time.sleep(interval)
