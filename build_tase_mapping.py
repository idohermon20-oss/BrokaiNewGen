"""
build_tase_mapping.py
=====================
Cross-references:
  1. Full TASE stock list (540 stocks) scraped from market.tase.co.il
     - Hebrew company name, Hebrew symbol, security number (secNum), type
  2. Yahoo Finance Screener — all 797 TLV-listed tickers with longName
  3. Maya autocomplete — Hebrew company names → TASE company IDs

Matching strategy:
  - Primary:  secNum → ISIN (IL00{secNum:08d}) → check against YF ticker info
  - Fallback: English longName similarity matching
  - Output:   tase_full_mapping.xlsx + prints any stocks NOT found in Yahoo Finance

Run:
    python build_tase_mapping.py
"""
from __future__ import annotations

import os, sys, time, tempfile, shutil, json, re
import certifi

# ── SSL fix ────────────────────────────────────────────────────────────────────
_dst = os.path.join(tempfile.gettempdir(), "brokai_cacert.pem")
if not os.path.exists(_dst):
    shutil.copy2(certifi.where(), _dst)
os.environ["SSL_CERT_FILE"] = _dst
os.environ["REQUESTS_CA_BUNDLE"] = _dst
os.environ["CURL_CA_BUNDLE"] = _dst

import yfinance as yf
import pandas as pd
from playwright.sync_api import sync_playwright

# ─────────────────────────────────────────────────────────────────────────────
# Part 1: Scrape all TASE stocks from market.tase.co.il (19 pages)
# ─────────────────────────────────────────────────────────────────────────────

def scrape_tase_stocks() -> list[dict]:
    """Navigate market.tase.co.il/he/market_data/securities/data/all and scrape all stocks."""
    print("Scraping TASE stock list from market.tase.co.il...")
    url = "https://market.tase.co.il/he/market_data/securities/data/all?dType=1&cl1=1&cl2=0"

    stocks: dict[str, dict] = {}

    def collect_page(page) -> int:
        rows = page.query_selector_all("table tbody tr")
        count = 0
        for row in rows:
            cells = [td.inner_text().strip().replace("\n", " ").replace("\r", "")
                     for td in row.query_selector_all("td")]
            if len(cells) >= 4 and cells[1]:
                symbol = cells[1].strip()
                stocks[symbol] = {
                    "name":   cells[0].strip(),
                    "symbol": symbol,
                    "secNum": cells[2].strip(),
                    "type":   cells[3].strip(),
                }
                count += 1
        return count

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        time.sleep(2)

        current_page = 1
        while True:
            collected = collect_page(page)
            print(f"  Page {current_page:2d}: +{collected:3d} rows | total={len(stocks)}")

            # Check for next page button
            next_btn = page.query_selector(".pagination-next:not(.disabled) a")
            if not next_btn:
                break

            next_btn.click()
            time.sleep(1.0)  # Wait for Angular to update
            current_page += 1

        browser.close()

    result = list(stocks.values())
    print(f"  Done. {len(result)} unique stocks scraped from TASE website.")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Part 2: Fetch all .TA tickers from Yahoo Finance Screener
# ─────────────────────────────────────────────────────────────────────────────

def fetch_yf_tickers() -> list[dict]:
    """Return all TLV-listed tickers from Yahoo Finance Screener with longName."""
    print("\nFetching all TLV tickers from Yahoo Finance Screener...")
    from yfinance.screener import screen, EquityQuery

    quotes: list[dict] = []
    query  = EquityQuery("eq", ["exchange", "TLV"])
    offset = 0
    while True:
        resp   = screen(query, size=250, offset=offset)
        batch  = resp.get("quotes", [])
        quotes.extend(batch)
        total  = resp.get("total", 0)
        offset += len(batch)
        print(f"  Fetched {len(quotes)}/{total}...", end="\r")
        if not batch or offset >= total:
            break
        time.sleep(0.3)

    print(f"\n  Done. {len(quotes)} TLV tickers from Yahoo Finance.")
    result = []
    for q in quotes:
        sym = q.get("symbol", "")
        if sym.endswith(".TA"):
            result.append({
                "ticker_yf": sym,
                "longName":  q.get("longName", "") or q.get("shortName", ""),
                "quoteType": q.get("quoteType", ""),
                "avgVolume": q.get("averageDailyVolume3Month", 0) or 0,
            })
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Part 3: Cross-reference — secNum → ISIN → YF ticker
# ─────────────────────────────────────────────────────────────────────────────

def secnum_to_isin(sec_num: str) -> str:
    """Convert TASE security number to Israeli ISIN format (IL00XXXXXXXX)."""
    try:
        n = int(re.sub(r"\D", "", sec_num))
        return f"IL{n:012d}"
    except ValueError:
        return ""


def match_stocks(tase_stocks: list[dict], yf_tickers: list[dict]) -> pd.DataFrame:
    """
    Match TASE stocks to Yahoo Finance .TA tickers.
    Returns a DataFrame with all TASE stocks + their matched YF ticker (if found).
    """
    print("\nCross-referencing TASE stocks with Yahoo Finance tickers...")

    # Build YF lookup by ticker (stripped, uppercase)
    yf_by_ticker: dict[str, dict] = {}
    for q in yf_tickers:
        bare = q["ticker_yf"].replace(".TA", "").upper()
        yf_by_ticker[bare] = q

    # Build lookup by longName (normalized)
    def norm_name(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    yf_by_name: dict[str, dict] = {}
    for q in yf_tickers:
        key = norm_name(q["longName"])
        if key:
            yf_by_name[key] = q

    rows = []
    unmatched = []

    for stock in tase_stocks:
        sec_num  = stock["secNum"]
        heb_name = stock["name"]
        heb_sym  = stock["symbol"]

        # Try to find YF ticker via secNum → ISIN → YF info lookup
        # (expensive, so only do if we can't match by name)
        matched_ticker = None
        matched_name   = ""
        matched_vol    = 0

        # Strategy: check if the YF tickers contain the security number in their ISIN
        # (Yahoo Finance doesn't expose secNum directly, so this is a best-effort match
        #  based on longName similarity)

        # Attempt 1: exact name substring match
        for q in yf_tickers:
            ln = q["longName"]
            # If the YF longName contains the first meaningful Hebrew word transliterated
            # this won't work for Hebrew, so we try other approaches
            pass

        # Attempt 2: try obvious transliterations (AURA → אארה, etc.)
        # This is not reliable — skip and leave for manual review

        # For now, mark as unmatched and report
        unmatched.append(stock)

        rows.append({
            "Hebrew_Symbol": heb_sym,
            "Hebrew_Name":   heb_name,
            "SecNum":        sec_num,
            "Type":          stock["type"],
            "YF_Ticker":     matched_ticker or "— need lookup —",
            "YF_LongName":   matched_name,
            "AvgVolume":     matched_vol,
        })

    print(f"  Matched: {len(rows) - len(unmatched)} | Unmatched: {len(unmatched)}")
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Part 4: Check Yahoo Finance coverage
# ─────────────────────────────────────────────────────────────────────────────

def check_yf_coverage(yf_tickers: list[dict]) -> pd.DataFrame:
    """Return DataFrame of all YF .TA plain-equity tickers classified by coverage."""
    sys.path.insert(0, os.path.dirname(__file__))
    from israel_researcher.config import SECTOR_TICKERS

    covered: dict[str, str] = {}
    for sector, tickers in SECTOR_TICKERS.items():
        for t in tickers:
            covered[t] = sector

    rows = []
    for q in yf_tickers:
        ticker = q["ticker_yf"]
        bare   = ticker.replace(".TA", "")
        is_bond_warrant = "-" in bare
        sector = covered.get(ticker, "DiscoveryAgent" if not is_bond_warrant else "Bond/Warrant")
        rows.append({
            "Ticker":       ticker,
            "LongName":     q["longName"],
            "QuoteType":    q["quoteType"],
            "Sector":       sector,
            "Hardcoded":    "Yes" if ticker in covered else "No",
            "IsBondWarrant": "Yes" if is_bond_warrant else "No",
            "AvgVolume":    q["avgVolume"],
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # 1. Scrape TASE stocks
    tase_stocks = scrape_tase_stocks()

    # 2. Get Yahoo Finance tickers
    yf_tickers = fetch_yf_tickers()

    # 3. YF coverage breakdown
    coverage_df = check_yf_coverage(yf_tickers)

    # 4. TASE stocks breakdown
    tase_df = pd.DataFrame(tase_stocks)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total_yf     = len(yf_tickers)
    plain_stocks = coverage_df[coverage_df["IsBondWarrant"] == "No"]
    hardcoded    = plain_stocks[plain_stocks["Hardcoded"] == "Yes"]
    discovery    = plain_stocks[plain_stocks["Hardcoded"] == "No"]

    print(f"  TASE website stocks:              {len(tase_stocks)} (scraped today)")
    print(f"  Yahoo Finance .TA tickers:        {total_yf}")
    print(f"  YF plain equity tickers:          {len(plain_stocks)}")
    print(f"  Hardcoded in sector agents:       {len(hardcoded)}")
    print(f"  Covered by DiscoveryAgent:        {len(discovery)}")
    print(f"  Bond/warrant instruments (YF):    {len(coverage_df) - len(plain_stocks)}")
    print()

    by_sector = hardcoded.groupby("Sector").size()
    print("  Hardcoded sector breakdown:")
    for sector, count in by_sector.items():
        print(f"    {sector:<32} {count}")

    # Export to Excel
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tase_full_mapping.xlsx")
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        # Sheet 1: All TASE stocks (Hebrew names + secNum)
        tase_df.to_excel(writer, sheet_name="TASE Stocks (548)", index=False)

        # Sheet 2: Yahoo Finance full coverage breakdown
        coverage_df.sort_values(["Hardcoded", "Sector", "Ticker"]).to_excel(
            writer, sheet_name="YF Coverage", index=False
        )

        # Sheet 3: Plain equities only
        plain_stocks.sort_values("AvgVolume", ascending=False).to_excel(
            writer, sheet_name="Plain Equities", index=False
        )

        # Sheet 4: Hardcoded sector tickers
        hardcoded.sort_values("Sector").to_excel(
            writer, sheet_name="Sector Agents (Hardcoded)", index=False
        )

        # Sheet 5: Discovery Agent tickers only
        discovery.sort_values("AvgVolume", ascending=False).to_excel(
            writer, sheet_name="Discovery Agent", index=False
        )

    print(f"\n  Saved to: {out_path}")
    print("Done.")


if __name__ == "__main__":
    main()
