"""
BotServer — Telegram long-polling bot running as a daemon thread.

Routing:
  /command  → commands.py handler
  free text → QAPipeline.answer() → split-send reply

Concurrency model:
  Research cycle: main thread (Playwright, ThreadPoolExecutor)
  Bot polling:    daemon thread (threading.Thread(daemon=True))
  Shared state:   guarded by threading.RLock (held only during brief reads)
  BotSettings mutations: GIL-safe (atomic attribute assignment)
"""

from __future__ import annotations

import copy
import threading
import time
import traceback
from typing import Callable

import requests

from .bot_state import BotSettings
from .commands import handle_command
from .qa_pipeline import QAPipeline
from .user_alerts import add_user_alert, delete_user_alert, get_alerts_for_chat


# Per-chat cooldown: ignore rapid re-questions within N seconds
_COOLDOWN_SECONDS = 10
# Keep last N messages (role/content dicts) per chat — 8 = 4 turns
_HISTORY_MAX = 8

# Keywords that mean "yes, confirm" (lowercase, Hebrew + English)
_YES_WORDS = {
    "yes", "yep", "sure", "ok", "yeah", "do it", "add it", "confirm",
    "approve", "go ahead", "set it", "add", "create", "absolutely",
    "כן", "בטח", "אוקי", "הוסף", "כן בבקשה", "בסדר", "אישור", "אשר",
}
# Keywords that mean "no, cancel"
_NO_WORDS = {
    "no", "nope", "cancel", "don't", "never mind", "stop", "skip",
    "לא", "בטל", "לא תודה", "ביטול", "לא צריך",
}


def _is_confirmation(text: str) -> bool | None:
    """Return True=yes, False=no, None=unclear."""
    lower = text.lower().strip()
    if lower in _YES_WORDS or any(lower == w for w in _YES_WORDS):
        return True
    # also accept single-word answers that are in the yes set
    words = set(lower.split())
    if words & _YES_WORDS:
        return True
    if lower in _NO_WORDS or words & _NO_WORDS:
        return False
    return None


class BotServer:
    def __init__(
        self,
        bot_token: str,
        default_chat_id: str,
        settings: BotSettings,
        state_getter: Callable[[], dict],
        state_lock: threading.RLock,
    ):
        self._token           = bot_token
        self._default_chat    = default_chat_id
        self._settings        = settings
        self._get_state       = state_getter
        self._lock            = state_lock
        self._base_url        = f"https://api.telegram.org/bot{bot_token}"
        self._last_msg_time:  dict[str, float] = {}   # chat_id → last message timestamp
        self._chat_history:   dict[str, list]  = {}   # chat_id → [{role, content}, ...]
        self._pending_actions: dict[str, dict] = {}   # chat_id → pending action dict

    # ── Public API ────────────────────────────────────────────────────────────

    def start_daemon(self) -> threading.Thread:
        t = threading.Thread(target=self._poll_loop, daemon=True, name="BotPoller")
        t.start()
        print("[BotPoller] started")
        return t

    # ── Internal polling loop ─────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while True:
            try:
                updates = self._get_updates(timeout=30)
                if updates:
                    for upd in updates:
                        try:
                            self._handle_update(upd)
                        except Exception:
                            print("[BotPoller] update error:", traceback.format_exc())
                    # Advance offset past the last processed update
                    last_id = updates[-1]["update_id"]
                    self._settings.last_offset = last_id + 1
                    self._settings.save()
            except Exception:
                print("[BotPoller] poll error:", traceback.format_exc())
                time.sleep(5)

    def _get_updates(self, timeout: int = 30) -> list[dict]:
        try:
            resp = requests.get(
                f"{self._base_url}/getUpdates",
                params={"offset": self._settings.last_offset, "timeout": timeout},
                timeout=timeout + 5,
            )
            data = resp.json()
            if data.get("ok"):
                return data.get("result", [])
        except Exception:
            pass
        return []

    def _handle_update(self, update: dict) -> None:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return
        chat_id  = str(msg.get("chat", {}).get("id", ""))
        text     = (msg.get("text") or "").strip()
        if not chat_id or not text:
            return

        lang = self._settings.language

        if text.startswith("/"):
            # Slash commands clear any pending confirmation
            self._pending_actions.pop(chat_id, None)
            handle_command(
                text         = text,
                chat_id      = chat_id,
                settings     = self._settings,
                state_getter = self._get_state,
                state_lock   = self._lock,
                reply_fn     = self._reply,
            )
        else:
            # ── Check if user is responding to a pending action confirmation ──
            if chat_id in self._pending_actions:
                confirmed = _is_confirmation(text)
                if confirmed is True:
                    action  = self._pending_actions.pop(chat_id)
                    reply   = self._execute_pending_action(chat_id, action)
                    self._reply(chat_id, reply)
                    return
                elif confirmed is False:
                    self._pending_actions.pop(chat_id)
                    if lang == "he":
                        self._reply(chat_id, "בסדר, ביטלתי. שאל אותי כל שאלה.")
                    else:
                        self._reply(chat_id, "OK, cancelled. Ask me anything.")
                    return
                # confirmed is None → unclear response → clear pending and continue
                # with the new message as a fresh question
                self._pending_actions.pop(chat_id, None)

            # Cooldown check
            now = time.time()
            if now - self._last_msg_time.get(chat_id, 0) < _COOLDOWN_SECONDS:
                if lang == "he":
                    self._reply(chat_id, "⏳ נא להמתין מספר שניות בין שאלות.")
                else:
                    self._reply(chat_id, "⏳ Please wait a moment between questions.")
                return
            self._last_msg_time[chat_id] = now

            # Q&A pipeline
            if lang == "he":
                self._reply(chat_id, "🔍 מנתח את השאלה שלך...")
            else:
                self._reply(chat_id, "🔍 Analyzing your question...")

            try:
                # Snapshot state under lock — deepcopy so LLM call runs outside the lock
                with self._lock:
                    state_snapshot = copy.deepcopy(self._get_state())

                # Inject chat_id so tools like get_user_alerts can filter by chat
                state_snapshot["_bot_chat_id"] = chat_id

                history  = self._chat_history.get(chat_id, [])
                pipeline = QAPipeline(state_snapshot)
                result   = pipeline.answer(text, history=history)

                # Check if pipeline returned a pending action (action_intent flow)
                if isinstance(result, dict) and "_pending_action" in result:
                    action      = result["_pending_action"]
                    confirm_msg = result.get("_confirm_msg", "Confirm?")
                    self._pending_actions[chat_id] = action
                    if lang == "he":
                        self._reply(chat_id, f"🔔 {confirm_msg}\n\nענה **כן** לאישור או **לא** לביטול.")
                    else:
                        self._reply(chat_id, f"🔔 {confirm_msg}\n\nReply **yes** to confirm or **no** to cancel.")
                    # Don't add to history (it's a confirmation prompt, not a real answer)
                    return

                answer = result  # plain string
                self._split_send(chat_id, answer)

                # Update per-chat conversation history
                history = history + [
                    {"role": "user",      "content": text},
                    {"role": "assistant", "content": answer},
                ]
                self._chat_history[chat_id] = history[-_HISTORY_MAX:]

            except Exception:
                print("[BotPoller] Q&A error:", traceback.format_exc())
                if lang == "he":
                    self._reply(chat_id, "מצטער, אירעה שגיאה. נסה שנית.")
                else:
                    self._reply(chat_id, "Sorry, an error occurred. Please try again.")

    # ── Action execution ──────────────────────────────────────────────────────

    def _execute_pending_action(self, chat_id: str, action: dict) -> str:
        """Execute a confirmed action (add/delete alert) and return a reply string."""
        lang        = action.get("_language") or self._settings.language
        action_type = action.get("action", "none")

        if action_type == "add_alert":
            alert_type   = action.get("alert_type",   "any_signal")
            ticker       = action.get("ticker")       or None
            company_name = action.get("company_name") or None

            # Normalise ticker — strip .TA suffix for storage
            if ticker:
                ticker = ticker.upper().replace(".TA", "")

            try:
                alert = add_user_alert(
                    chat_id      = chat_id,
                    alert_type   = alert_type,
                    ticker       = ticker,
                    company_name = company_name,
                )
                print(f"[BotPoller] Alert added: {alert.alert_id} type={alert_type} ticker={ticker}")
                if lang == "he":
                    return (
                        f"✅ התראה הוגדרה (ID: **{alert.alert_id}**):\n"
                        f"{alert.description}\n\n"
                        f"תקבל התראה בכל פעם שזה יקרה.\n"
                        f"להצגת כל ההתראות שלך: /alert_list\n"
                        f"למחיקת התראה: /alert_del {alert.alert_id}"
                    )
                return (
                    f"✅ Alert set (ID: **{alert.alert_id}**):\n"
                    f"{alert.description}\n\n"
                    f"You'll be notified every research cycle when this fires.\n"
                    f"View your alerts: /alert_list\n"
                    f"Remove this alert: /alert_del {alert.alert_id}"
                )
            except Exception:
                print("[BotPoller] add_user_alert error:", traceback.format_exc())
                if lang == "he":
                    return "אירעה שגיאה בהוספת ההתראה. נסה שנית."
                return "Failed to add alert. Please try again."

        if action_type == "delete_alert":
            ticker = (action.get("ticker") or "").upper().replace(".TA", "") or None
            # Find alerts for this chat matching the ticker
            alerts = get_alerts_for_chat(chat_id)
            if ticker:
                targets = [a for a in alerts if a.ticker == ticker or (a.company_name or "").upper() == ticker]
            else:
                targets = alerts

            if not targets:
                if lang == "he":
                    return "לא נמצאו התראות למחיקה. השתמש ב-/alert_list לצפייה."
                return "No matching alerts found to delete. Use /alert_list to view yours."

            # Delete all matching alerts
            deleted = []
            for a in targets:
                if delete_user_alert(chat_id, a.alert_id):
                    deleted.append(f"{a.alert_id} ({a.description})")

            if lang == "he":
                return f"✅ נמחקו {len(deleted)} התראות:\n" + "\n".join(deleted)
            return f"✅ Deleted {len(deleted)} alert(s):\n" + "\n".join(deleted)

        if action_type == "change_setting":
            from .bot_state import ALL_SECTORS
            setting_name  = (action.get("setting_name") or "").lower().strip()
            setting_value = str(action.get("setting_value") or "").strip()

            if setting_name == "language":
                new_lang = setting_value.lower()
                if new_lang not in ("en", "he"):
                    return ("❌ Language must be 'en' or 'he'." if lang != "he"
                            else "❌ שפה חייבת להיות 'en' או 'he'.")
                self._settings.language = new_lang
                self._settings.save()
                return ("✅ Language set to English." if new_lang == "en"
                        else "✅ שפה עודכנה לעברית.")

            elif setting_name == "interval":
                try:
                    minutes = int(float(setting_value))
                    assert 5 <= minutes <= 240
                    self._settings.scan_interval_seconds = minutes * 60
                    self._settings.save()
                    return (f"✅ Scan interval set to {minutes} min." if lang != "he"
                            else f"✅ מרווח הסריקה עודכן ל-{minutes} דקות.")
                except Exception:
                    return ("❌ Interval must be 5–240 minutes." if lang != "he"
                            else "❌ מרווח חייב להיות בין 5 ל-240 דקות.")

            elif setting_name == "topn":
                try:
                    n = int(float(setting_value))
                    assert 1 <= n <= 10
                    self._settings.top_n_alerts = n
                    self._settings.save()
                    return (f"✅ Top-N alerts set to {n}." if lang != "he"
                            else f"✅ מספר ההתראות עודכן ל-{n}.")
                except Exception:
                    return ("❌ N must be 1–10." if lang != "he"
                            else "❌ המספר חייב להיות בין 1 ל-10.")

            elif setting_name == "volume":
                try:
                    x = float(setting_value)
                    assert 1.5 <= x <= 10.0
                    self._settings.volume_spike_x = x
                    self._settings.save()
                    return (f"✅ Volume spike threshold set to {x}×." if lang != "he"
                            else f"✅ סף נפח עסקאות עודכן ל-{x}×.")
                except Exception:
                    return ("❌ Multiplier must be 1.5–10.0." if lang != "he"
                            else "❌ המכפיל חייב להיות בין 1.5 ל-10.0.")

            elif setting_name == "price":
                try:
                    pct = float(setting_value)
                    assert 1.0 <= pct <= 20.0
                    self._settings.price_move_pct = pct
                    self._settings.save()
                    return (f"✅ Price move threshold set to {pct}%." if lang != "he"
                            else f"✅ סף תנועת מחיר עודכן ל-{pct}%.")
                except Exception:
                    return ("❌ Threshold must be 1.0–20.0." if lang != "he"
                            else "❌ הסף חייב להיות בין 1.0 ל-20.0.")

            elif setting_name == "alerts_on":
                self._settings.alerts_enabled = True
                self._settings.save()
                return ("✅ Alerts enabled." if lang != "he"
                        else "✅ שליחת התראות הופעלה.")

            elif setting_name == "alerts_off":
                self._settings.alerts_enabled = False
                self._settings.save()
                return ("✅ Alerts disabled." if lang != "he"
                        else "✅ שליחת התראות הושבתה.")

            elif setting_name == "sectors":
                requested = [s.strip() for s in setting_value.split(",") if s.strip()]
                bad = [s for s in requested if s not in ALL_SECTORS]
                if bad:
                    return (f"❌ Unknown sectors: {', '.join(bad)}. Valid: {', '.join(ALL_SECTORS)}"
                            if lang != "he" else
                            f"❌ ענפים לא מוכרים: {', '.join(bad)}. תקינים: {', '.join(ALL_SECTORS)}")
                self._settings.enabled_sectors = requested
                self._settings.save()
                return (f"✅ Enabled sectors: {', '.join(requested)}." if lang != "he"
                        else f"✅ ענפים פעילים: {', '.join(requested)}.")

            return ("❌ Could not identify the setting to change." if lang != "he"
                    else "❌ לא זיהיתי את ההגדרה לשינוי.")

        if lang == "he":
            return "לא הצלחתי לבצע את הפעולה. נסה שנית."
        return "Could not execute the action. Please try again."

    # ── Reply helpers ─────────────────────────────────────────────────────────

    def _reply(self, chat_id: str, text: str) -> None:
        try:
            requests.post(
                f"{self._base_url}/sendMessage",
                json={"chat_id": chat_id, "text": text[:4096]},
                timeout=10,
            )
        except Exception:
            print("[BotPoller] send error:", traceback.format_exc())

    def _split_send(self, chat_id: str, text: str) -> None:
        """Send long messages in chunks ≤4096 chars, splitting at paragraph boundaries."""
        if len(text) <= 4096:
            self._reply(chat_id, text)
            return
        chunks: list[str] = []
        current = ""
        for para in text.split("\n\n"):
            candidate = (current + "\n\n" + para).lstrip() if current else para
            if len(candidate) > 4096:
                if current:
                    chunks.append(current)
                current = para
            else:
                current = candidate
        if current:
            chunks.append(current)
        for chunk in chunks:
            self._reply(chat_id, chunk)
            time.sleep(0.3)
