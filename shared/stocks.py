"""
Shared stock utility functions.
Operates on the state dict loaded from data/israel_researcher_state.json.

Usage:
    import json
    from pathlib import Path
    state = json.loads(Path("data/israel_researcher_state.json").read_text(encoding="utf-8"))
    from shared.stocks import find_top_stocks, filter_signals_by_score
"""
from __future__ import annotations


def find_top_stocks(state: dict, n: int = 10, sector: str | None = None) -> list[dict]:
    """
    Return the top-n stocks from stock_memory ranked by best_score.
    Each entry: {ticker, company_name, best_score, sentiment, analyst_notes, watch_for}
    Optionally filter by sector (matches company_name substring).
    """
    memory: dict = state.get("stock_memory", {})
    results = []
    for ticker, info in memory.items():
        if not isinstance(info, dict):
            continue
        if sector and sector.lower() not in info.get("company_name", "").lower():
            continue
        results.append({
            "ticker":        ticker,
            "company_name":  info.get("company_name", ""),
            "best_score":    info.get("best_score", 0),
            "sentiment":     info.get("llm_sentiment", "neutral"),
            "analyst_notes": info.get("analyst_notes", ""),
            "watch_for":     info.get("llm_watch_for", ""),
        })
    results.sort(key=lambda x: x["best_score"], reverse=True)
    return results[:n]


def filter_signals_by_score(
    state: dict,
    min_score: float = 50.0,
    sector: str | None = None,
    signal_type: str | None = None,
) -> list[dict]:
    """
    Filter this week's signals from weekly_signals by score, sector, or type.
    Returns list of signal dicts sorted by score descending.
    """
    signals: list = state.get("weekly_signals", [])
    results = []
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        score = sig.get("score", 0) or sig.get("final_score", 0)
        if score < min_score:
            continue
        if signal_type and signal_type not in sig.get("signal_type", ""):
            continue
        if sector and sector.lower() not in sig.get("company_name", "").lower():
            continue
        results.append(sig)
    results.sort(key=lambda x: x.get("score", x.get("final_score", 0)), reverse=True)
    return results
