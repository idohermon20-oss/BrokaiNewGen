"""
Telegram notification sender.

Sends analysis results to a Telegram chat after each report is generated.
Completely optional — if TELEGRAM_BOT_TOKEN is not set in .env, all calls are no-ops.

Usage:
    from borkai.utils.telegram import send_report_summary
    send_report_summary(ticker, verdict, direction, score, report_path, token, chat_id)
"""
from __future__ import annotations

import os
import textwrap
from typing import Optional


def _send_message(token: str, chat_id: str, text: str) -> bool:
    """POST a message to Telegram. Returns True on success."""
    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        # Telegram max message length is 4096 chars
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            resp = requests.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }, timeout=10)
            if not resp.ok:
                return False
        return True
    except Exception:
        return False


def send_report_summary(
    ticker: str,
    company_name: str,
    verdict: str,
    direction: str,
    return_score: int,
    conviction: str,
    horizon: str,
    highlights: str,
    report_path: Optional[str] = None,
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> bool:
    """
    Send a concise report summary to Telegram.
    Returns True if sent, False if skipped (no token) or failed.
    """
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        return False  # Telegram not configured — silent no-op

    # Verdict badge
    if "invest" in verdict.lower() or "buy" in verdict.lower():
        badge = "✅"
    elif "avoid" in verdict.lower() or "sell" in verdict.lower() or "not" in verdict.lower():
        badge = "❌"
    else:
        badge = "⚠️"

    direction_arrow = {"bullish": "↑", "bearish": "↓", "neutral": "→"}.get(direction.lower(), "")

    text = textwrap.dedent(f"""
        *🤖 BORKAI ANALYSIS COMPLETE*

        *{ticker}* — {company_name}
        Horizon: {horizon.upper()}

        {badge} *{verdict}*
        Direction: {direction.capitalize()} {direction_arrow}
        Return Score: *{return_score}/100*
        Conviction: {conviction.capitalize()}

        {highlights[:800] if highlights else ""}

        {f'📄 Report saved: `{report_path}`' if report_path else ''}
    """).strip()

    return _send_message(token, chat_id, text)
