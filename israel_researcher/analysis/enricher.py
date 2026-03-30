"""
SignalEnricher — scans text for high-value keyword groups and upgrades signal_type.
"""

from __future__ import annotations
import re
from typing import Optional

from ..config import KEYWORD_GROUPS
from ..models import Signal, signal_key


def _kw_match(kw: str, text_lower: str) -> bool:
    """Match keyword in text using word boundaries to avoid substring false positives."""
    pattern = r'(?<!\w)' + re.escape(kw.lower()) + r'(?!\w)'
    return bool(re.search(pattern, text_lower))


class SignalEnricher:
    def enrich(self, sig: Signal, full_text: str) -> Signal:
        text_lower     = full_text.lower()
        hits:          list[str]     = []
        dominant_type: Optional[str] = None

        priority_order = [
            "new_contract", "institutional_investor", "regulatory_approval",
            "government_defense", "shareholder_return", "partnership",
            "financial_event", "management_change",
        ]
        for group in priority_order:
            matched = [kw for kw in KEYWORD_GROUPS[group] if _kw_match(kw, text_lower)]
            if matched:
                hits.extend(matched[:3])
                if dominant_type is None:
                    dominant_type = group

        # Keep precise Maya-sourced types unchanged; upgrade generic ones
        _KEEP_AS_IS = {
            "maya_ipo", "maya_earnings", "maya_institutional", "maya_contract",
            "maya_ma", "maya_dividend", "maya_buyback", "maya_rights",
            "maya_spinoff", "maya_management",
            # Technical signals — never overwrite with keyword-based type
            "volume_spike", "price_move", "breakout", "ma_crossover", "dual_listed_move",
            "oversold_bounce", "low_reversal", "consecutive_momentum", "relative_strength",
            "oil_correlation", "shekel_move", "defense_tailwind", "sector_peer_move",
            # Calendar
            "earnings_calendar",
            # Web-extracted (LLM-classified — already precise, don't overwrite)
            "earnings", "buyback", "dividend", "ipo", "general_news",
        }
        if dominant_type and sig.signal_type not in _KEEP_AS_IS:
            sig.signal_type = dominant_type
        sig.keywords_hit = list(dict.fromkeys(hits))[:6]
        return sig

    def enrich_list(self, signals: list[Signal], texts: dict[str, str]) -> list[Signal]:
        for s in signals:
            txt = texts.get(signal_key(s), s.headline + " " + s.detail)
            self.enrich(s, txt)
        return signals
