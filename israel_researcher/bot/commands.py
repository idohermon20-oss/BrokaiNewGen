"""
Telegram slash command handlers for the interactive bot.

Settings commands (mutate BotSettings + save):
  /set_interval   /set_topn     /set_volume   /set_price
  /set_language   /set_sectors  /enable_alerts /disable_alerts

Status / query commands (read-only):
  /help  /status  /macro  /earnings  /weekly  /sector
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Callable

from .bot_state import BotSettings, ALL_SECTORS
from .user_alerts import (
    ALERT_TYPES, add_user_alert, delete_user_alert,
    get_alerts_for_chat,
)

# ── Bilingual strings ─────────────────────────────────────────────────────────
# \u202A = LEFT-TO-RIGHT EMBEDDING, \u202C = POP DIRECTIONAL FORMATTING
# Wrap numbers/tickers in LTR markers to prevent Bidi rendering issues in Telegram.

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "help": (
            "📊 TASE Research Bot — Commands\n\n"
            "⚙️ Settings:\n"
            "/set_interval <min>    — Scan interval 5–240 min (default 15)\n"
            "/set_topn <n>          — Top N alerts per report 1–10 (default 3)\n"
            "/set_volume <x>        — Volume spike threshold 1.5–10.0× (default 2.5)\n"
            "/set_price <pct>       — Price move threshold 1.0–20.0% (default 3.5)\n"
            "/set_language en|he    — Reply language (English or Hebrew)\n"
            "/set_sectors s1,s2,... — Enable specific sectors (comma-separated)\n"
            "   Banks · TechDefense · Energy · PharmaBiotech · RealEstate · TelecomConsumer · Discovery\n"
            "/enable_alerts         — Turn on Telegram alert delivery\n"
            "/disable_alerts        — Turn off Telegram alert delivery\n\n"
            "📈 Status & Live Data:\n"
            "/status                — Settings overview + last scan time + alerts sent today\n"
            "/macro                 — Live snapshot: TA-125, S&P500, Nasdaq, USD/ILS, VIX, oil, US10Y\n"
            "/earnings              — Upcoming earnings events from this week's signals\n"
            "/weekly                — Current stock-of-the-week pick + rationale + runners-up\n"
            "/sector <name>         — Sector rotation: BULL+/BULL/NEUTRAL/BEAR/BEAR- (e.g. /sector Banks)\n\n"
            "💬 Ask me anything (English or Hebrew):\n"
            "   Stock questions  — \"What's happening with TEVA?\"  |  \"מה קורה עם אלביט?\"\n"
            "   Buy ideas        — \"What should I buy today?\"\n"
            "   Market overview  — \"How is the market doing?\"\n"
            "   Sector rotation  — \"Which sectors are bullish this week?\"\n"
            "   IPOs & filings   — \"Any new IPOs this week?\"  |  \"Show me Maya filings\"\n"
            "   Concepts         — \"What is RSI?\"  |  \"מה זה P/E?\"\n\n"
            "I remember our conversation — follow-up questions work naturally.\n"
            "I understand Hebrew company names and resolve them to TASE tickers automatically."
        ),
        "he": (
            "📊 בוט מחקר ת\"א — פקודות\n\n"
            "⚙️ הגדרות:\n"
            "/set_interval <דקות>   — מרווח סריקה 5–240 דק׳ (ברירת מחדל 15)\n"
            "/set_topn <מספר>       — כמה התראות לשלוח 1–10 (ברירת מחדל 3)\n"
            "/set_volume <x>        — סף נפח עסקאות 1.5–10.0× (ברירת מחדל 2.5)\n"
            "/set_price <אחוז>      — סף תנועת מחיר 1.0–20.0% (ברירת מחדל 3.5)\n"
            "/set_language en|he    — שפת הממשק (אנגלית או עברית)\n"
            "/set_sectors s1,s2,... — ענפים פעילים (מופרדים בפסיקים)\n"
            "   Banks · TechDefense · Energy · PharmaBiotech · RealEstate · TelecomConsumer · Discovery\n"
            "/enable_alerts         — הפעל שליחת התראות\n"
            "/disable_alerts        — כבה שליחת התראות\n\n"
            "📈 סטטוס ונתונים חיים:\n"
            "/status                — הגדרות + זמן סריקה אחרון + התראות שנשלחו היום\n"
            "/macro                 — מאקרו חי: ת\"א 125, S&P500, נאסד\"ק, דולר/שקל, VIX, נפט, US10Y\n"
            "/earnings              — דיווחים רבעוניים קרובים מהשבוע הנוכחי\n"
            "/weekly                — מניית השבוע + נימוק + מועמדות נוספות\n"
            "/sector <שם>           — רוטציית ענפים: BULL+/BULL/NEUTRAL/BEAR/BEAR- (למשל /sector Banks)\n\n"
            "💬 שאל אותי כל שאלה (עברית או אנגלית):\n"
            "   על מניה ספציפית  — \"מה קורה עם טבע?\"  |  \"מה ה-RSI של אלביט?\"\n"
            "   המלצות קנייה     — \"מה כדאי לקנות היום?\"\n"
            "   סקירת שוק        — \"איך השוק מתנהג?\"\n"
            "   רוטציית ענפים    — \"אילו ענפים חיוביים השבוע?\"\n"
            "   הנפקות ודיווחים  — \"יש הנפקות חדשות?\"\n"
            "   מושגים           — \"מה זה RSI?\"  |  \"הסבר P/E\"\n\n"
            "הבוט זוכר את השיחה — שאלות המשך עובדות באופן טבעי.\n"
            "הבוט מבין שמות חברות בעברית ומחפש את הטיקר המתאים אוטומטית."
        ),
        "interval_set":     "✅ Scan interval set to {min} min (takes effect after current cycle).",
        "interval_bad":     "❌ Interval must be between 5 and 240 minutes.",
        "topn_set":         "✅ Top-N alerts set to {n}.",
        "topn_bad":         "❌ N must be between 1 and 10.",
        "volume_set":       "✅ Volume spike threshold set to {x}×.",
        "volume_bad":       "❌ Multiplier must be between 1.5 and 10.0.",
        "price_set":        "✅ Price move threshold set to {pct}%.",
        "price_bad":        "❌ Threshold must be between 1.0 and 20.0.",
        "lang_set":         "✅ Language set to {lang}.",
        "lang_bad":         "❌ Language must be 'en' or 'he'.",
        "sectors_set":      "✅ Enabled sectors: {sectors}.",
        "sectors_bad":      "❌ Unknown sectors: {bad}. Valid: {valid}.",
        "alerts_on":        "✅ Alerts enabled.",
        "alerts_off":       "✅ Alerts disabled.",
        "unknown_cmd":      "❓ Unknown command. Type /help for the full list.",
        "no_weekly":        "No stock-of-the-week data yet — try again after the first research cycle.",
        "no_earnings":      "No upcoming earnings found in this week's signals.",
        "usage_sector":     "Usage: /sector <name>  (e.g. /sector Banks)",
        "invalid_sector":   "❌ Unknown sector '{name}'. Valid: {valid}",
        # Custom alert strings
        "alert_add_ok":     "✅ Alert set (ID: {id}): {desc}\nYou'll be notified every cycle when this fires.",
        "alert_add_bad":    "❌ Unknown alert type '{type}'. Valid types:\n  " + "  •  ".join(["ipo", "earnings", "maya_filing", "institutional", "volume_spike", "price_move", "any_signal"]),
        "alert_add_usage":  "Usage: /alert_add <type> [ticker]\nExamples:\n  /alert_add ipo\n  /alert_add earnings TEVA\n  /alert_add maya_filing ESLT\n  /alert_add volume_spike LUMI",
        "alert_list_empty": "You have no custom alerts set.\nUse /alert_add to create one.",
        "alert_list_hdr":   "🔔 Your custom alerts ({n}):\n",
        "alert_del_ok":     "✅ Alert {id} deleted.",
        "alert_del_bad":    "❌ Alert ID '{id}' not found. Use /alert_list to see your alerts.",
        "alert_del_usage":  "Usage: /alert_del <id>  (get the ID from /alert_list)",
        "alert_hist_none":  "No Maya filing history found for {ticker} yet.\nHistory is built up as filings arrive each cycle.",
        "alert_hist_usage": "Usage: /alert_history [ticker]  (e.g. /alert_history TEVA)",
    },
    "he": {
        "interval_set":     "✅ מרווח הסריקה עודכן ל-{min} דקות (ייכנס לתוקף בסוף הסבב הנוכחי).",
        "interval_bad":     "❌ יש להזין מרווח בין 5 ל-240 דקות.",
        "topn_set":         "✅ מספר ההתראות עודכן ל-{n}.",
        "topn_bad":         "❌ המספר חייב להיות בין 1 ל-10.",
        "volume_set":       "✅ סף נפח עסקאות עודכן ל-‎{x}× הממוצע.",
        "volume_bad":       "❌ המכפיל חייב להיות בין 1.5 ל-10.0.",
        "price_set":        "✅ סף תנועת מחיר עודכן ל-‎{pct}%.",
        "price_bad":        "❌ הסף חייב להיות בין 1.0 ל-20.0.",
        "lang_set":         "✅ שפה עודכנה ל-{lang}.",
        "lang_bad":         "❌ שפה חייבת להיות 'en' או 'he'.",
        "sectors_set":      "✅ ענפים פעילים: {sectors}.",
        "sectors_bad":      "❌ ענפים לא מוכרים: {bad}. ענפים תקינים: {valid}.",
        "alerts_on":        "✅ שליחת התראות הופעלה.",
        "alerts_off":       "✅ שליחת התראות הושבתה.",
        "unknown_cmd":      "❓ פקודה לא מוכרת. שלח /help לרשימה המלאה.",
        "no_weekly":        "טרם נוצרו נתוני מניית השבוע — נסה שוב לאחר סבב המחקר הראשון.",
        "no_earnings":      "לא נמצאו דיווחים קרובים בשבוע זה.",
        "usage_sector":     "שימוש: /sector <שם>  (לדוגמה /sector Banks)",
        "invalid_sector":   "❌ ענף לא מוכר: '{name}'. ענפים תקינים: {valid}",
        # Custom alert strings (Hebrew)
        "alert_add_ok":     "✅ התראה נקבעה (מזהה: {id}): {desc}\nתקבל התראה בכל פעם שזה יקרה.",
        "alert_add_bad":    "❌ סוג התראה לא מוכר '{type}'.",
        "alert_add_usage":  "שימוש: /alert_add <סוג> [טיקר]\nדוגמאות:\n  /alert_add ipo\n  /alert_add earnings TEVA\n  /alert_add maya_filing ESLT",
        "alert_list_empty": "אין לך התראות מותאמות אישית.\nהשתמש ב-/alert_add ליצירת אחת.",
        "alert_list_hdr":   "🔔 ההתראות שלך ({n}):\n",
        "alert_del_ok":     "✅ התראה {id} נמחקה.",
        "alert_del_bad":    "❌ מזהה '{id}' לא נמצא. השתמש ב-/alert_list לצפייה.",
        "alert_del_usage":  "שימוש: /alert_del <מזהה>",
        "alert_hist_none":  "לא נמצא היסטוריית דיווחי מאיה עבור {ticker}.",
        "alert_hist_usage": "שימוש: /alert_history [טיקר]  (למשל /alert_history TEVA)",
        "help":             "",   # use en help text (set dynamically below)
    },
}
# Hebrew /help falls back to English (bilingual audience can read English commands)
STRINGS["he"]["help"] = STRINGS["en"]["help"]


def _t(lang: str, key: str, **kwargs) -> str:
    """Translate + format a string."""
    tmpl = STRINGS.get(lang, STRINGS["en"]).get(key, STRINGS["en"].get(key, key))
    return tmpl.format(**kwargs) if kwargs else tmpl


# ── Main dispatcher ───────────────────────────────────────────────────────────

def handle_command(
    text:         str,
    chat_id:      str,
    settings:     BotSettings,
    state_getter: Callable[[], dict],
    state_lock:   threading.RLock,
    reply_fn:     Callable[[str, str], None],
) -> None:
    """Route /command text to the correct handler."""
    parts = text.split()
    cmd   = parts[0].split("@")[0].lower()   # strip @botname suffix
    args  = parts[1:]
    lang  = settings.language

    def reply(msg: str) -> None:
        reply_fn(chat_id, msg)

    # ── Settings commands ─────────────────────────────────────────────────────

    if cmd == "/set_interval":
        try:
            minutes = int(args[0])
            assert 5 <= minutes <= 240
            settings.scan_interval_seconds = minutes * 60
            settings.save()
            reply(_t(lang, "interval_set", min=minutes))
        except Exception:
            reply(_t(lang, "interval_bad"))

    elif cmd == "/set_topn":
        try:
            n = int(args[0])
            assert 1 <= n <= 10
            settings.top_n_alerts = n
            settings.save()
            reply(_t(lang, "topn_set", n=n))
        except Exception:
            reply(_t(lang, "topn_bad"))

    elif cmd == "/set_volume":
        try:
            x = float(args[0])
            assert 1.5 <= x <= 10.0
            settings.volume_spike_x = x
            settings.save()
            reply(_t(lang, "volume_set", x=x))
        except Exception:
            reply(_t(lang, "volume_bad"))

    elif cmd == "/set_price":
        try:
            pct = float(args[0])
            assert 1.0 <= pct <= 20.0
            settings.price_move_pct = pct
            settings.save()
            reply(_t(lang, "price_set", pct=pct))
        except Exception:
            reply(_t(lang, "price_bad"))

    elif cmd == "/set_language":
        try:
            new_lang = args[0].lower()
            assert new_lang in ("en", "he")
            settings.language = new_lang
            settings.save()
            reply(_t(new_lang, "lang_set", lang=new_lang))
        except Exception:
            reply(_t(lang, "lang_bad"))

    elif cmd == "/set_sectors":
        try:
            requested = [s.strip() for s in " ".join(args).split(",") if s.strip()]
            bad = [s for s in requested if s not in ALL_SECTORS]
            if bad:
                reply(_t(lang, "sectors_bad", bad=", ".join(bad), valid=", ".join(ALL_SECTORS)))
            else:
                settings.enabled_sectors = requested
                settings.save()
                reply(_t(lang, "sectors_set", sectors=", ".join(requested)))
        except Exception:
            reply(_t(lang, "sectors_bad", bad="?", valid=", ".join(ALL_SECTORS)))

    elif cmd == "/enable_alerts":
        settings.alerts_enabled = True
        settings.save()
        reply(_t(lang, "alerts_on"))

    elif cmd == "/disable_alerts":
        settings.alerts_enabled = False
        settings.save()
        reply(_t(lang, "alerts_off"))

    # ── Status / query commands ───────────────────────────────────────────────

    elif cmd == "/help":
        reply(_t(lang, "help"))

    elif cmd == "/status":
        _handle_status(chat_id, settings, state_getter, state_lock, reply)

    elif cmd == "/macro":
        _handle_macro(chat_id, reply)

    elif cmd == "/earnings":
        _handle_earnings(chat_id, settings, state_getter, state_lock, reply)

    elif cmd == "/weekly":
        _handle_weekly(chat_id, settings, state_getter, state_lock, reply)

    elif cmd == "/sector":
        _handle_sector(chat_id, args, lang, reply)

    # ── Custom user alerts ────────────────────────────────────────────────────

    elif cmd == "/alert_add":
        _handle_alert_add(chat_id, args, lang, state_getter, state_lock, reply)

    elif cmd == "/alert_list":
        _handle_alert_list(chat_id, lang, reply)

    elif cmd == "/alert_del":
        _handle_alert_del(chat_id, args, lang, reply)

    elif cmd == "/alert_history":
        _handle_alert_history(chat_id, args, lang, state_getter, state_lock, reply)

    else:
        reply(_t(lang, "unknown_cmd"))


# ── Individual handlers ───────────────────────────────────────────────────────

def _handle_status(
    chat_id: str,
    settings: BotSettings,
    state_getter: Callable[[], dict],
    state_lock: threading.RLock,
    reply: Callable[[str], None],
) -> None:
    with state_lock:
        state = state_getter()
    last_run   = state.get("last_run_iso", "never")[:19].replace("T", " ")  # human-readable
    alerted    = state.get("alerted_today", {})
    n_alerted  = len(alerted)
    alerted_list = ", ".join(alerted.keys()) if alerted else "—"
    weekly_sigs  = len(state.get("weekly_signals", []))
    tracked      = len(state.get("stock_memory", {}))
    s    = settings
    lang = s.language

    alerts_status = ("✅ ON" if s.alerts_enabled else "🔕 OFF")
    interval_min  = s.scan_interval_seconds // 60

    if lang == "he":
        msg = (
            f"📊 **סטטוס בוט מחקר ת\"א**\n\n"
            f"🕐 סריקה אחרונה: {last_run}\n"
            f"⏱ מרווח סריקה: ‎{interval_min} דקות\n"
            f"🌐 שפה: {s.language}\n"
            f"🔔 התראות: {alerts_status}\n\n"
            f"📈 נתוני מחקר:\n"
            f"  • אותות השבוע: {weekly_sigs}\n"
            f"  • מניות בזיכרון: {tracked}\n"
            f"  • התראות היום ({n_alerted}): {alerted_list}\n\n"
            f"⚙️ הגדרות:\n"
            f"  • Top-N: {s.top_n_alerts}\n"
            f"  • סף נפח: ‎{s.volume_spike_x}×\n"
            f"  • סף מחיר: ‎{s.price_move_pct}%\n"
            f"  • ענפים: {', '.join(s.enabled_sectors)}"
        )
    else:
        msg = (
            f"📊 **TASE Research Bot — Status**\n\n"
            f"🕐 Last scan: {last_run}\n"
            f"⏱ Interval: {interval_min} min\n"
            f"🌐 Language: {s.language}\n"
            f"🔔 Alerts: {alerts_status}\n\n"
            f"📈 Research state:\n"
            f"  • Signals this week: {weekly_sigs}\n"
            f"  • Stocks in memory: {tracked}\n"
            f"  • Alerted today ({n_alerted}): {alerted_list}\n\n"
            f"⚙️ Thresholds:\n"
            f"  • Top-N per alert: {s.top_n_alerts}\n"
            f"  • Volume spike: {s.volume_spike_x}×\n"
            f"  • Price move: {s.price_move_pct}%\n"
            f"  • Active sectors: {', '.join(s.enabled_sectors)}"
        )
    reply(msg)


def _handle_macro(chat_id: str, reply: Callable[[str], None]) -> None:
    """Fetch live macro snapshot via yfinance (Playwright-free — safe in bot thread)."""
    try:
        # Import here to keep the bot package clean (no top-level Playwright imports)
        from ..sources.market import MacroContext
        text = MacroContext().get()
        reply(f"📈 Macro Snapshot\n\n{text}")
    except Exception as e:
        reply(f"⚠️ Could not fetch macro data: {e}")


def _handle_earnings(
    chat_id: str,
    settings: BotSettings,
    state_getter: Callable[[], dict],
    state_lock: threading.RLock,
    reply: Callable[[str], None],
) -> None:
    lang = settings.language
    try:
        with state_lock:
            state = state_getter()
        from ..models import Signal
        weekly_sigs = state.get("weekly_signals", [])
        # weekly_signals may be stored as dicts after load_state JSON round-trip
        earnings = []
        for s in weekly_sigs:
            if isinstance(s, dict):
                if s.get("signal_type") == "earnings_calendar":
                    earnings.append(s)
            elif hasattr(s, "signal_type") and s.signal_type == "earnings_calendar":
                earnings.append({"ticker": s.ticker, "headline": s.headline, "detail": s.detail})

        if not earnings:
            reply(_t(lang, "no_earnings"))
            return

        # Sort by event_date so closest earnings first
        def _event_date(e):
            return e.get("event_date") or e.get("detail", "")[:10] or "9999"
        earnings.sort(key=_event_date)

        header = "📅 **Upcoming Earnings Calendar**\n" if lang == "en" else "📅 **דיווחים קרובים**\n"
        lines = [header]
        for e in earnings[:10]:
            tkr      = e.get("ticker", "?").replace(".TA", "")
            headline = e.get("headline", "")
            detail   = e.get("detail", "")
            ev_date  = e.get("event_date", "")
            date_str = f" [{ev_date}]" if ev_date else ""
            lines.append(f"• **{tkr}**{date_str} — {headline}")
            if detail and detail != headline:
                lines.append(f"  {detail[:120]}")
        reply("\n".join(lines))
    except Exception as exc:
        reply(f"⚠️ Error fetching earnings: {exc}")


def _handle_weekly(
    chat_id: str,
    settings: BotSettings,
    state_getter: Callable[[], dict],
    state_lock: threading.RLock,
    reply: Callable[[str], None],
) -> None:
    lang = settings.language
    try:
        with state_lock:
            state = state_getter()
        report = state.get("last_arbitration_report", {})
        if not report:
            reply(_t(lang, "no_weekly"))
            return

        sotw      = report.get("stock_of_the_week", {})
        runners   = report.get("runners_up", [])
        ticker    = sotw.get("ticker", "?")
        name      = sotw.get("name", "")
        score     = sotw.get("score", 0)
        rationale = sotw.get("full_rationale") or sotw.get("summary", "")
        catalyst  = sotw.get("key_catalyst", "")
        tech      = sotw.get("technical_setup", "")
        risk      = sotw.get("main_risk", "")
        theme     = report.get("week_theme", "")
        macro_ctx = report.get("macro_context", "")

        if lang == "he":
            msg = f"🏆 **מניית השבוע**\n\n**{ticker}.TA** — {name}\nציון: **{score}/100**\n\n"
            if theme:
                msg += f"📌 נושא השבוע: {theme}\n\n"
            if rationale:
                msg += f"{rationale}\n"
            if catalyst:
                msg += f"\n🎯 קטליזטור: {catalyst}"
            if tech:
                msg += f"\n📊 מבנה טכני: {tech}"
            if risk:
                msg += f"\n⚠️ סיכון עיקרי: {risk}"
            if runners:
                msg += "\n\n**מועמדות נוספות:**\n"
                for r in runners[:3]:
                    r_ticker   = r.get("ticker", "?")
                    r_name     = r.get("name", "")
                    r_score    = r.get("score", 0)
                    r_catalyst = r.get("key_catalyst", "") or r.get("summary", "")
                    msg += f"• **{r_ticker}.TA** — {r_name} (ציון {r_score})"
                    if r_catalyst:
                        msg += f"\n  {r_catalyst[:100]}"
                    msg += "\n"
            if macro_ctx:
                msg += f"\n🌍 מאקרו: {macro_ctx[:200]}"
        else:
            msg = f"🏆 **Stock of the Week**\n\n**{ticker}.TA** — {name}\nScore: **{score}/100**\n\n"
            if theme:
                msg += f"📌 Week theme: {theme}\n\n"
            if rationale:
                msg += f"{rationale}\n"
            if catalyst:
                msg += f"\n🎯 Key catalyst: {catalyst}"
            if tech:
                msg += f"\n📊 Technical setup: {tech}"
            if risk:
                msg += f"\n⚠️ Main risk: {risk}"
            if runners:
                msg += "\n\n**Runners-up:**\n"
                for r in runners[:3]:
                    r_ticker   = r.get("ticker", "?")
                    r_name     = r.get("name", "")
                    r_score    = r.get("score", 0)
                    r_catalyst = r.get("key_catalyst", "") or r.get("summary", "")
                    msg += f"• **{r_ticker}.TA** — {r_name} (score {r_score})"
                    if r_catalyst:
                        msg += f"\n  {r_catalyst[:100]}"
                    msg += "\n"
            if macro_ctx:
                msg += f"\n🌍 Macro context: {macro_ctx[:200]}"
        reply(msg)
    except Exception as exc:
        reply(f"⚠️ Error: {exc}")


def _handle_sector(
    chat_id: str,
    args: list[str],
    lang: str,
    reply: Callable[[str], None],
) -> None:
    # Map user-facing sector names → keys used by SectorAnalyzer.SECTOR_SAMPLES
    # SectorAnalyzer uses: Banks, Insurance, RealEstate, TechDefense, Energy, Pharma, Telecom, Consumer, Finance
    _SECTOR_DISPLAY_KEYS = {
        "Banks":           ["Banks", "Insurance", "Finance"],
        "TechDefense":     ["TechDefense"],
        "Energy":          ["Energy"],
        "PharmaBiotech":   ["Pharma"],
        "RealEstate":      ["RealEstate"],
        "TelecomConsumer": ["Telecom", "Consumer"],
        "Discovery":       None,   # Not in SectorAnalyzer — covers all uncovered tickers
    }

    if not args:
        reply(_t(lang, "usage_sector"))
        return
    sector_name = " ".join(args).strip()
    if sector_name not in ALL_SECTORS:
        reply(_t(lang, "invalid_sector", name=sector_name, valid=", ".join(ALL_SECTORS)))
        return

    analyzer_keys = _SECTOR_DISPLAY_KEYS.get(sector_name)
    if analyzer_keys is None:
        if lang == "he":
            reply("📊 DiscoveryAgent סורק את כל מניות הבורסה שאינן מכוסות על ידי סוכני הענפים הספציפיים. אין לו נתוני ענף ספציפיים — השתמש ב-/macro לנתוני מאקרו כלליים.")
        else:
            reply("📊 Discovery covers all TASE stocks not in the named sector lists. It has no sector-specific data — use /macro for broad market context.")
        return

    try:
        from ..sources.market import SectorAnalyzer
        ctx = SectorAnalyzer().get_sector_context()
        # Extract lines that match any of the analyzer key names for this sector
        matching = []
        for line in ctx.splitlines():
            if any(key.lower() in line.lower() for key in analyzer_keys) or not line.strip():
                matching.append(line)
        section = "\n".join(matching).strip() or ctx
        reply(f"📊 Sector: {sector_name}\n\n{section}")
    except Exception as exc:
        reply(f"⚠️ Could not fetch sector data: {exc}")


# ── Custom alert handlers ─────────────────────────────────────────────────────

def _handle_alert_add(
    chat_id:      str,
    args:         list[str],
    lang:         str,
    state_getter: Callable[[], dict],
    state_lock:   threading.RLock,
    reply:        Callable[[str], None],
) -> None:
    """
    /alert_add <type> [ticker]
    Types: ipo  earnings  maya_filing  institutional  volume_spike  price_move  any_signal
    """
    if not args:
        reply(_t(lang, "alert_add_usage"))
        return

    alert_type = args[0].lower()
    if alert_type not in ALERT_TYPES:
        reply(_t(lang, "alert_add_bad", type=alert_type))
        return

    ticker = args[1].upper().replace(".TA", "") if len(args) > 1 else None

    # Try to resolve company name from state (best effort)
    company_name = None
    if ticker:
        try:
            with state_lock:
                state = state_getter()
            mem = state.get("stock_memory", {}).get(ticker, {})
            company_name = mem.get("company_name") or ticker
        except Exception:
            company_name = ticker

    alert = add_user_alert(chat_id, alert_type, ticker=ticker, company_name=company_name)
    reply(_t(lang, "alert_add_ok", id=alert.alert_id, desc=alert.description))


def _handle_alert_list(
    chat_id: str,
    lang:    str,
    reply:   Callable[[str], None],
) -> None:
    """List all custom alerts for this chat."""
    alerts = get_alerts_for_chat(chat_id)
    if not alerts:
        reply(_t(lang, "alert_list_empty"))
        return

    lines = [_t(lang, "alert_list_hdr", n=len(alerts))]
    for a in alerts:
        target = f" — {a.ticker or a.company_name}" if (a.ticker or a.company_name) else ""
        lines.append(f"• [{a.alert_id}] {a.alert_type.upper()}{target}")
        lines.append(f"  {a.description}")
        lines.append(f"  Created: {a.created_at[:10]}  |  Fired: {len(a.seen_signal_keys)}× so far")
    reply("\n".join(lines))


def _handle_alert_del(
    chat_id: str,
    args:    list[str],
    lang:    str,
    reply:   Callable[[str], None],
) -> None:
    """Delete a custom alert by its short ID."""
    if not args:
        reply(_t(lang, "alert_del_usage"))
        return
    alert_id = args[0].lower()
    if delete_user_alert(chat_id, alert_id):
        reply(_t(lang, "alert_del_ok", id=alert_id))
    else:
        reply(_t(lang, "alert_del_bad", id=alert_id))


def _handle_alert_history(
    chat_id:      str,
    args:         list[str],
    lang:         str,
    state_getter: Callable[[], dict],
    state_lock:   threading.RLock,
    reply:        Callable[[str], None],
) -> None:
    """
    /alert_history [ticker]
    Show Maya filing history for a specific stock from researcher memory.
    """
    if not args:
        reply(_t(lang, "alert_hist_usage"))
        return

    ticker = args[0].upper().replace(".TA", "")

    try:
        from ..analysis.memory import StockMemoryManager
        with state_lock:
            state = state_getter()
        mem     = StockMemoryManager(state)
        history = mem.get_maya_history(ticker)

        if not history:
            reply(_t(lang, "alert_hist_none", ticker=ticker))
            return

        lines = [f"📋 Maya filing history for {ticker} ({len(history)} entries):"]
        for h in history[:20]:
            date    = h.get("date", "?")
            ftype   = h.get("type", "?")
            company = h.get("company", "")
            headline= h.get("headline", "")
            detail  = h.get("detail", "")
            entry = f"\n[{date}] {ftype}"
            if company:
                entry += f" — {company}"
            entry += f"\n{headline}"
            if detail:
                entry += f"\n  {detail[:200]}"
            lines.append(entry)

        reply("\n".join(lines))
    except Exception as exc:
        reply(f"⚠️ Error fetching history: {exc}")
