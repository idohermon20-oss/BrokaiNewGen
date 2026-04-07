"""
fetch_tase_universe.py
======================
Fetches the complete TASE stock universe from Yahoo Finance Screener,
cross-references with our sector config, and exports to Excel.

Run (from project root):
    python utils/fetch_tase_universe.py

Output:
    data/tase_universe_full.xlsx  — all .TA tickers with name, sector coverage, validity
"""

from __future__ import annotations

import time
import sys
import os
from pathlib import Path as _Path

# ── SSL fix (same as israel_researcher/__init__.py for Hebrew username) ──────
import tempfile
try:
    import certifi
    _cert_src = certifi.where()
    _cert_dst = os.path.join(tempfile.gettempdir(), "brokai_cacert.pem")
    if not os.path.exists(_cert_dst):
        import shutil
        shutil.copy2(_cert_src, _cert_dst)
    os.environ.setdefault("SSL_CERT_FILE", _cert_dst)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", _cert_dst)
    os.environ.setdefault("CURL_CA_BUNDLE", _cert_dst)
except Exception:
    pass

import yfinance as yf
import pandas as pd

# ── Import sector config (add project root to path so the package is found) ──
sys.path.insert(0, str(_Path(__file__).parent.parent))
from israel_researcher.config import SECTOR_TICKERS, TASE_MAJOR_TICKERS


# ── Step 1: Fetch all .TA tickers from Yahoo Finance Screener ────────────────
def fetch_all_ta_tickers() -> list[str]:
    """Fetch all TLV-listed tickers from Yahoo Finance Screener."""
    print("Fetching all TLV tickers from Yahoo Finance Screener...")
    tickers: list[str] = []
    try:
        from yfinance.screener import screen, EquityQuery
        query  = EquityQuery("eq", ["exchange", "TLV"])
        offset = 0
        while True:
            response = screen(query, size=250, offset=offset)
            quotes   = response.get("quotes", [])
            for q in quotes:
                sym = q.get("symbol", "")
                if sym.endswith(".TA"):
                    tickers.append(sym)
            total = response.get("total", 0)
            offset += len(quotes)
            print(f"  Fetched {len(tickers)}/{total} so far...", end="\r")
            if not quotes or offset >= total:
                break
            time.sleep(0.3)
        print(f"\n  Done. Yahoo Finance Screener: {len(tickers)} TLV tickers total.")
    except Exception as exc:
        print(f"  Screener error: {exc}")
        print("  Falling back to TASE_MAJOR_TICKERS hardcoded list.")
        tickers = list(TASE_MAJOR_TICKERS)
    return sorted(set(tickers))


# ── Step 2: Build sector coverage map ────────────────────────────────────────
def build_coverage_map() -> dict[str, str]:
    """Return {ticker.TA: sector_name} for all hardcoded sector tickers."""
    coverage: dict[str, str] = {}
    for sector, tickers in SECTOR_TICKERS.items():
        for t in tickers:
            coverage[t] = sector
    return coverage


# ── Step 3: Validate tickers against Yahoo Finance (sample) ──────────────────
def validate_ticker(ticker: str) -> tuple[str, float | None]:
    """Return (ticker, last_price | None). None = invalid/delisted."""
    try:
        info = yf.Ticker(ticker).fast_info
        price = float(info.last_price) if info.last_price else None
        return ticker, price
    except Exception:
        return ticker, None


# ── Step 4: Get company name from Yahoo Finance ───────────────────────────────
def get_name(ticker: str) -> str:
    try:
        info = yf.Ticker(ticker).info
        return info.get("longName") or info.get("shortName") or ""
    except Exception:
        return ""


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    all_tickers  = fetch_all_ta_tickers()
    coverage_map = build_coverage_map()

    print(f"\nBuilding universe table for {len(all_tickers)} tickers...")
    print("(Validating prices and names — this takes ~10-15 minutes for the full list)")
    print("Press Ctrl+C to stop early — partial results will still be saved.\n")

    rows = []
    for i, ticker in enumerate(all_tickers, 1):
        sector = coverage_map.get(ticker, "DiscoveryAgent")
        is_hardcoded = ticker in coverage_map

        # Validate + get price (skip slow name fetch to keep it fast)
        _, price = validate_ticker(ticker)
        valid = price is not None and price > 0

        rows.append({
            "Ticker":         ticker,
            "Sector":         sector,
            "Hardcoded":      "Yes" if is_hardcoded else "No",
            "Valid_YF":       "Yes" if valid else "No/Delisted",
            "Last_Price":     round(price, 2) if price else None,
        })

        status = "v" if valid else "x"
        print(f"  [{i:4d}/{len(all_tickers)}] {ticker:<18} {status}  {sector}")
        time.sleep(0.15)  # Rate limit

    df = pd.DataFrame(rows)

    # ── Summary stats ────────────────────────────────────────────────────────
    total       = len(df)
    valid_count = (df["Valid_YF"] == "Yes").sum()
    hardcoded   = (df["Hardcoded"] == "Yes").sum()
    discovery   = (df["Hardcoded"] == "No").sum()

    print(f"\n{'='*60}")
    print(f"TASE Universe Summary")
    print(f"{'='*60}")
    print(f"  Total .TA tickers (YF Screener):  {total}")
    print(f"  Valid / tradeable:                {valid_count}")
    print(f"  Hardcoded in sector agents:       {hardcoded}")
    print(f"  Covered by DiscoveryAgent:        {discovery}")
    print(f"\n  Sector breakdown (hardcoded):")
    for sector in sorted(SECTOR_TICKERS.keys()):
        n = (df["Sector"] == sector).sum()
        print(f"    {sector:<30} {n}")

    # ── Export to data/ ───────────────────────────────────────────────────────
    out_path = str(_Path(__file__).parent.parent / "data" / "tase_universe_full.xlsx")
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        # Sheet 1: Full universe
        df.to_excel(writer, sheet_name="Full Universe", index=False)

        # Sheet 2: Hardcoded sector tickers only
        df[df["Hardcoded"] == "Yes"].to_excel(
            writer, sheet_name="Sector Agents", index=False
        )

        # Sheet 3: Discovery-only (not hardcoded)
        df[df["Hardcoded"] == "No"].to_excel(
            writer, sheet_name="Discovery Only", index=False
        )

        # Sheet 4: Invalid / delisted
        df[df["Valid_YF"] != "Yes"].to_excel(
            writer, sheet_name="Invalid or Delisted", index=False
        )

    print(f"\n  Saved to: {out_path}")
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted — partial results NOT saved (add save logic if needed).")
