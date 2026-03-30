"""
Telegram alert delivery.
"""

from __future__ import annotations

import traceback
import requests

from .config import TOP_N_ALERTS


class TelegramReporter:
    def __init__(self, bot_token: str, chat_id: str):
        self.chat_id    = chat_id
        self._bot_token = bot_token
        self._url       = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def _post(self, chat_id: str, text: str) -> None:
        """Shared HTTP sender — sends to any chat_id."""
        try:
            requests.post(
                self._url,
                json={"chat_id": chat_id, "text": text[:4096]},
                timeout=10,
            )
        except Exception:
            print("[Telegram error]", traceback.format_exc())

    def send(self, text: str) -> None:
        """Send to the default research channel."""
        self._post(self.chat_id, text)

    def reply(self, chat_id: str, text: str) -> None:
        """Send to an arbitrary chat_id (used by BotServer for command replies)."""
        self._post(str(chat_id), text)

    def send_quick_alerts(self, ranked: list[dict], top_n: int = TOP_N_ALERTS) -> None:
        for item in ranked[:top_n]:
            kw      = ", ".join(item.get("keywords", [])[:4]) or "—"
            tier    = item.get("tier", "")
            tier_str = f" [{tier.upper()}]" if tier else ""
            tech    = item.get("technical_setup", "")
            risk    = item.get("main_risk", "")
            sector  = item.get("sector", "")
            score   = item.get("score", 0)
            signals = item.get("signals_count", 0)

            msg = (
                f"TASE Alert{tier_str} — {item.get('ticker', '?')}.TA"
                + (f"  |  {item.get('name', '')}" if item.get("name") else "")
                + f"\n"
                f"Score: {score}/100  |  {signals} signals"
                + (f"  |  {sector}" if sector else "")
                + f"\n\n"
                f"Why now: {item.get('summary', '')}\n"
                f"Key catalyst: {item.get('top_signal', '') or '—'}\n"
            )
            if tech:
                msg += f"Technical setup: {tech}\n"
            if risk:
                msg += f"Main risk: {risk}\n"
            msg += f"Themes: {kw}"
            self.send(msg)

    def send_weekly_report(self, report: dict) -> None:
        winner    = report.get("stock_of_the_week", {})
        runners   = report.get("runners_up", [])
        macro     = report.get("macro_context", "")
        theme     = report.get("week_theme", "")
        sector    = report.get("sector_in_focus", "")
        rationale = winner.get("full_rationale", report.get("full_rationale", ""))

        catalyst  = winner.get("key_catalyst", "")
        tech      = winner.get("technical_setup", "")
        risk      = winner.get("main_risk", "")

        msg = (
            f"TASE STOCK OF THE WEEK\n"
            f"{'='*30}\n"
            f"Pick: {winner.get('ticker', '?')}.TA — {winner.get('name', '')}\n"
            f"Score: {winner.get('score', 0)}/100  |  {winner.get('signals_count', 0)} signals\n"
            f"\n"
            f"Why this week:\n{rationale}\n"
        )
        if catalyst:
            msg += f"\nKey catalyst: {catalyst}"
        if tech:
            msg += f"\nTechnical setup: {tech}"
        if risk:
            msg += f"\nMain risk: {risk}"
        msg += f"\n\nKey themes: {', '.join(winner.get('keywords', []))}\n"
        self.send(msg)

        if runners:
            runner_lines = "\n".join(
                f"  {i+2}. {r.get('ticker')}.TA — {r.get('name')} (score {r.get('score')})\n"
                f"     {r.get('summary', '')} | Catalyst: {r.get('key_catalyst', '—')}"
                for i, r in enumerate(runners[:2])
            )
            self.send(f"Also interesting this week:\n{runner_lines}")

        footer = ""
        if theme:
            footer += f"Week theme: {theme}\n"
        if sector:
            footer += f"Sector in focus: {sector}\n"
        if macro:
            footer += f"\nMacro:\n{macro}"
        if footer:
            self.send(footer.strip())
