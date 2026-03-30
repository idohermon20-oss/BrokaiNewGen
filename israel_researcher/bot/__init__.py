"""
israel_researcher.bot — Interactive Telegram bot package.

Provides BotServer: a daemon thread that polls Telegram for messages and
responds to slash commands and natural-language Q&A about Israeli stocks.

IMPORTANT: This package must NEVER import MayaMonitor, ChromeNewsSearcher,
or any Playwright-dependent code — Playwright is not thread-safe across threads.
"""

from .server import BotServer
from .bot_state import BotSettings, load_bot_settings, ALL_SECTORS
from .user_alerts import (
    UserAlert, ALERT_TYPES,
    add_user_alert, delete_user_alert, get_alerts_for_chat,
    load_user_alerts, save_user_alerts,
    check_and_fire_alerts, format_alert_message,
)

__all__ = [
    "BotServer", "BotSettings", "load_bot_settings", "ALL_SECTORS",
    "UserAlert", "ALERT_TYPES",
    "add_user_alert", "delete_user_alert", "get_alerts_for_chat",
    "load_user_alerts", "save_user_alerts",
    "check_and_fire_alerts", "format_alert_message",
]
