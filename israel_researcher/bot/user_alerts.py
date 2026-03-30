"""
UserAlert — per-user custom alert rules evaluated after every research cycle.

Alert types:
  ipo           — any new IPO / prospectus / spinoff filed on Maya
  earnings      — earnings report publication or upcoming earnings within 3 days
  maya_filing   — any Maya regulatory filing for a specific company
  institutional — institutional investor / insider stake change filing or buyback
  volume_spike  — volume anomaly detected for a specific ticker
  price_move    — significant daily price move for a specific ticker
  any_signal    — any research signal for a specific ticker

Usage:
  add_user_alert(chat_id, "ipo")                       → alert on any IPO
  add_user_alert(chat_id, "earnings", ticker="TEVA")   → alert on TEVA earnings
  add_user_alert(chat_id, "maya_filing", ticker="ESLT")→ any filing for Elbit
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ..config import USER_ALERTS_FILE
from ..models import Signal, signal_key


# ── Constants ────────────────────────────────────────────────────────────────

ALERT_TYPES = [
    "ipo",
    "earnings",
    "maya_filing",
    "institutional",
    "volume_spike",
    "price_move",
    "any_signal",
]

_MAYA_ALL = {
    "maya_ipo", "maya_spinoff", "maya_ma", "maya_contract",
    "maya_buyback", "maya_institutional", "maya_earnings",
    "maya_dividend", "maya_rights", "maya_management", "maya_filing",
}


# ── Dataclass ────────────────────────────────────────────────────────────────

@dataclass
class UserAlert:
    alert_id:         str
    chat_id:          str
    alert_type:       str                         # one of ALERT_TYPES
    ticker:           Optional[str] = None        # None = any ticker / company
    company_name:     Optional[str] = None        # human-readable display name
    created_at:       str = ""
    seen_signal_keys: list = field(default_factory=list)   # fired signal dedup
    description:      str = ""

    # ── Matching ──────────────────────────────────────────────────────────────

    def matches(self, signal: Signal) -> bool:
        """Return True if this signal should trigger this alert."""
        # Ticker / company filter
        if self.ticker:
            bare     = self.ticker.upper().replace(".TA", "")
            sig_bare = (signal.ticker or "").upper().replace(".TA", "")
            company  = (signal.company_name or "").upper()
            if bare not in sig_bare and bare not in company:
                return False

        t = signal.signal_type
        if self.alert_type == "ipo":
            return t in ("maya_ipo", "ipo", "maya_spinoff")
        if self.alert_type == "earnings":
            return t in ("maya_earnings", "earnings", "earnings_calendar")
        if self.alert_type == "maya_filing":
            return t in _MAYA_ALL
        if self.alert_type == "institutional":
            return t in ("maya_institutional", "institutional_investor", "maya_buyback")
        if self.alert_type == "volume_spike":
            return t == "volume_spike"
        if self.alert_type == "price_move":
            return t == "price_move"
        if self.alert_type == "any_signal":
            return True
        return False


# ── Persistence ──────────────────────────────────────────────────────────────

def load_user_alerts() -> list[UserAlert]:
    path = USER_ALERTS_FILE
    if not path.exists():
        return []
    try:
        with open(str(path), encoding="utf-8") as f:
            data = json.load(f)
        return [
            UserAlert(**{k: v for k, v in d.items() if k in UserAlert.__dataclass_fields__})
            for d in data.get("alerts", [])
        ]
    except Exception as e:
        print(f"[UserAlerts] load error: {e}")
        return []


def save_user_alerts(alerts: list[UserAlert]) -> None:
    path = USER_ALERTS_FILE.resolve()
    data = {"alerts": [asdict(a) for a in alerts]}
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── CRUD helpers ─────────────────────────────────────────────────────────────

def add_user_alert(
    chat_id:      str,
    alert_type:   str,
    ticker:       Optional[str] = None,
    company_name: Optional[str] = None,
) -> UserAlert:
    alerts = load_user_alerts()
    alert = UserAlert(
        alert_id         = uuid.uuid4().hex[:8],
        chat_id          = chat_id,
        alert_type       = alert_type,
        ticker           = ticker.upper().replace(".TA", "") if ticker else None,
        company_name     = company_name,
        created_at       = datetime.now(timezone.utc).isoformat(),
        seen_signal_keys = [],
        description      = _describe(alert_type, ticker or company_name),
    )
    alerts.append(alert)
    save_user_alerts(alerts)
    return alert


def delete_user_alert(chat_id: str, alert_id: str) -> bool:
    """Delete alert by short ID. Returns True if found + deleted."""
    alerts = load_user_alerts()
    before = len(alerts)
    alerts = [a for a in alerts if not (a.chat_id == chat_id and a.alert_id == alert_id)]
    if len(alerts) < before:
        save_user_alerts(alerts)
        return True
    return False


def get_alerts_for_chat(chat_id: str) -> list[UserAlert]:
    return [a for a in load_user_alerts() if a.chat_id == chat_id]


# ── Alert checking (called from ResearchManager every cycle) ─────────────────

def check_and_fire_alerts(
    alerts:      list[UserAlert],
    new_signals: list[Signal],
) -> list[tuple[UserAlert, Signal]]:
    """
    Match all alerts against new_signals. Returns (alert, signal) pairs that fired.
    Mutates alert.seen_signal_keys in-place — caller must save_user_alerts() afterward.
    Each (alert, signal) pair fires at most once (dedup by signal_key).
    """
    fired: list[tuple[UserAlert, Signal]] = []
    for alert in alerts:
        for sig in new_signals:
            key = signal_key(sig)
            if key in alert.seen_signal_keys:
                continue
            if alert.matches(sig):
                fired.append((alert, sig))
                alert.seen_signal_keys.append(key)
                # Cap dedup list to avoid unbounded growth
                if len(alert.seen_signal_keys) > 200:
                    alert.seen_signal_keys = alert.seen_signal_keys[-200:]
    return fired


# ── Message formatter ────────────────────────────────────────────────────────

def format_alert_message(alert: UserAlert, signal: Signal) -> str:
    """Build the Telegram text for a fired user alert."""
    type_label = alert.alert_type.upper().replace("_", " ")
    company    = signal.company_name or alert.company_name or signal.ticker
    ticker_str = ""
    if signal.ticker and not signal.ticker.startswith("TASE"):
        ticker_str = f" ({signal.ticker}.TA)"

    msg = (
        f"🔔 Your Alert — {type_label}\n"
        f"{company}{ticker_str}\n\n"
        f"📋 {signal.signal_type}: {signal.headline}\n"
    )
    if signal.detail:
        msg += f"{signal.detail[:280]}\n"
    msg += f"\n[Maya TASE • {signal.timestamp[:10]}]"
    return msg


# ── Internal helpers ─────────────────────────────────────────────────────────

def _describe(alert_type: str, target: Optional[str]) -> str:
    labels = {
        "ipo":          "New IPO / listing filed on Maya",
        "earnings":     "Earnings report published",
        "maya_filing":  "Any Maya regulatory filing",
        "institutional":"Institutional / insider filing",
        "volume_spike": "Volume spike detected",
        "price_move":   "Significant price move",
        "any_signal":   "Any research signal",
    }
    base = labels.get(alert_type, alert_type)
    return f"{base} — {target}" if target else base
