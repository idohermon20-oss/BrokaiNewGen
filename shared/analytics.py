"""
Portfolio analytics utilities.
Stateless functions — pass in data, get results back.
"""
from __future__ import annotations


def calc_sector_exposure(positions: list[dict], sector_map: dict[str, str]) -> dict[str, float]:
    """
    Given positions [{ticker, market_value}] and a ticker→sector map,
    return sector→total_value dict.
    """
    exposure: dict[str, float] = {}
    for pos in positions:
        ticker = pos.get("ticker", "")
        value  = pos.get("market_value", 0.0)
        sector = sector_map.get(ticker, "Unknown")
        exposure[sector] = exposure.get(sector, 0.0) + value
    return exposure


def sector_weights(exposure: dict[str, float]) -> dict[str, float]:
    """Convert sector exposure values to percentage weights (0–100)."""
    total = sum(exposure.values())
    if not total:
        return {s: 0.0 for s in exposure}
    return {s: round(v / total * 100, 2) for s, v in exposure.items()}


def calc_pnl(positions: list[dict]) -> dict:
    """
    Calculate P&L summary from positions.
    Each position: {ticker, quantity, avg_cost, current_price}
    Returns: {total_cost, total_value, pnl, pnl_pct}
    """
    total_cost  = sum(p.get("quantity", 0) * p.get("avg_cost", 0) for p in positions)
    total_value = sum(p.get("quantity", 0) * p.get("current_price", 0) for p in positions)
    pnl         = total_value - total_cost
    pnl_pct     = round(pnl / total_cost * 100, 2) if total_cost else 0.0
    return {
        "total_cost":  round(total_cost, 2),
        "total_value": round(total_value, 2),
        "pnl":         round(pnl, 2),
        "pnl_pct":     pnl_pct,
    }


def find_max_stock(state: dict) -> dict | None:
    """Return the stock with the highest best_score from stock_memory."""
    from .stocks import find_top_stocks
    results = find_top_stocks(state, n=1)
    return results[0] if results else None
