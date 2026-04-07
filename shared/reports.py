"""
Shared financial report utilities.
parse_financial_report() extracts key numbers from Maya filing text.
summarize_filing() returns a compact human-readable string.
"""
from __future__ import annotations
import re


_AMOUNT_RE = re.compile(
    r"(\$|USD|ILS|NIS|₪)?\s*(\d[\d,\.]*)\s*(million|billion|מיליון|מיליארד|M|B)\b",
    re.IGNORECASE,
)
_STAKE_RE = re.compile(r"(\d+\.?\d*)\s*(%|percent)", re.IGNORECASE)


def parse_financial_report(filing_text: str) -> dict:
    """
    Extract structured facts from a Maya filing or financial report text.
    Returns: {deal_size_m, stake_pct, currency, direction}
    All values are None if not found.
    """
    result: dict = {"deal_size_m": None, "stake_pct": None, "currency": None, "direction": None}

    m = _AMOUNT_RE.search(filing_text)
    if m:
        currency = m.group(1) or ("ILS" if any(c in filing_text for c in ["₪", "שקל"]) else "USD")
        raw = float(m.group(2).replace(",", ""))
        multiplier = 1000 if m.group(3).lower() in ("billion", "מיליארד", "b") else 1
        result["deal_size_m"] = raw * multiplier
        result["currency"] = currency

    s = _STAKE_RE.search(filing_text)
    if s:
        result["stake_pct"] = float(s.group(1))

    buy_kw  = ["רכישה", "רכש", "bought", "purchase", "buy", "acquired"]
    sell_kw = ["מכירה", "מכר", "sold", "sale", "sell", "divest"]
    text_l  = filing_text.lower()
    if any(k in text_l for k in buy_kw):
        result["direction"] = "buy"
    elif any(k in text_l for k in sell_kw):
        result["direction"] = "sell"

    return result


def summarize_filing(filing: dict) -> str:
    """
    Return a one-line summary string from a Maya filing dict.
    """
    company = filing.get("company_name", "Unknown")
    title   = filing.get("headline", filing.get("title", ""))
    date    = filing.get("timestamp", "")[:10]
    score   = filing.get("score", "")
    score_s = f" [score={score}]" if score else ""
    return f"{date} | {company} | {title}{score_s}"
