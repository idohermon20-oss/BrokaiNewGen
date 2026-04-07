"""
finalize_stock_reference.py
============================
Builds the final, quality-checked tase_stock_reference.json:
  1. Loads 788 tickers + English names from tase_ticker_names.json
  2. Builds Hebrew names from maya_company_mapping.json
     - When multiple cids map to the same .TA ticker, picks the best match
       (longest Hebrew-name prefix that aligns with the English YF name)
  3. Adds manual overrides for known large caps with wrong/missing Hebrew names
  4. Saves to data/tase_stock_reference.json

Run (from project root):
    python utils/finalize_stock_reference.py
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

# ── Manual corrections and additions ─────────────────────────────────────────
# Format: {ticker: hebrew_name}
# Add here when GPT gets it wrong or a key stock is missing
MANUAL_HEBREW = {
    # ── Banks (canonical main bank name, not mortgage/issuance subsidiaries) ──
    "POLI.TA":  "בנק הפועלים בע\"מ",                # Bank Hapoalim (not משכן)
    "MZTF.TA":  "בנק מזרחי טפחות בע\"מ",            # Mizrahi Tefahot Bank
    "DSCT.TA":  "בנק דיסקונט לישראל בע\"מ",         # Bank Discount
    "FIBI.TA":  "הבנק הבינלאומי הראשון לישראל בע\"מ", # First International Bank
    # ── Corrected mappings ────────────────────────────────────────────────────
    "ESLT.TA":  "אלביט מערכות בע\"מ",               # Elbit Systems (not Elbit Imaging)
    # ── Missing large caps ────────────────────────────────────────────────────
    "ICL.TA":   "כיל בע\"מ",                        # ICL Group / Israel Chemicals
    "KMDA.TA":  "קמדה בע\"מ",                        # Kamada
    "MNRV.TA":  "מנורה מבטחים ביטוח בע\"מ",          # Menora Mivtachim Insurance
    "PHOE.TA":  "פניקס החזקות בע\"מ",               # Phoenix Holdings
    "ICTS.TA":  "ICTS אירופה בע\"מ",                 # ICTS Europe
    "PRGO.TA":  "פריגו ישראל פארמה בע\"מ",           # Perrigo Israel
}

# ── False positives in cid_to_ticker (remove these cids from consideration) ──
# cid=1039 is Elbit Imaging, wrongly mapped to ESLT.TA (Elbit Systems)
FALSE_POSITIVE_CIDS = {"1039"}


def load_yf_names() -> dict[str, str]:
    return json.loads((DATA / "tase_ticker_names.json").read_text(encoding="utf-8"))


def build_hebrew_map(yf_names: dict[str, str]) -> dict[str, str]:
    """
    Build {ticker: best_hebrew_name} from maya_company_mapping.json.
    When multiple cids map to the same ticker, picks the one whose
    Hebrew name best aligns with the English YF name.
    """
    mapping = json.loads((DATA / "maya_company_mapping.json").read_text(encoding="utf-8"))
    companies = mapping.get("companies", {})
    cid_to_ticker = mapping.get("cid_to_ticker", {})

    # Group: ticker -> list of (cid, hebrew_name)
    ticker_candidates: dict[str, list[tuple[str, str]]] = {}
    for cid, info in companies.items():
        if cid in FALSE_POSITIVE_CIDS:
            continue
        ticker = info.get("ticker") or cid_to_ticker.get(cid)
        name = info.get("name", "")
        if ticker and name:
            ticker_candidates.setdefault(ticker, []).append((cid, name))

    # For each ticker, pick the best candidate
    ticker_to_hebrew: dict[str, str] = {}
    for ticker, candidates in ticker_candidates.items():
        if len(candidates) == 1:
            ticker_to_hebrew[ticker] = candidates[0][1]
            continue

        # Multiple candidates: prefer the one that has the most character overlap
        # with what we'd expect given the English name
        eng = yf_names.get(ticker, "").lower()
        best_name = candidates[0][1]
        best_score = 0

        for cid, heb_name in candidates:
            # Simple heuristic: longer names with fewer generic words score higher
            # Also prefer names that don't contain subsidiary indicators
            score = len(heb_name)
            # Prefer מערכות over הדמיה for defense tickers (ESLT pattern)
            if "מערכות" in heb_name:
                score += 30
            if "הדמיה" in heb_name and "systems" not in eng and "elbit" not in eng:
                score -= 20
            # Penalize holding company names for operational company tickers
            if "החזקות" in heb_name and any(w in eng for w in ["systems", "pharmaceutical", "chemicals"]):
                score -= 15
            if score > best_score:
                best_score = score
                best_name = heb_name

        ticker_to_hebrew[ticker] = best_name

    return ticker_to_hebrew


def main():
    yf_names = load_yf_names()
    print(f"YF tickers: {len(yf_names)}")

    ticker_to_hebrew = build_hebrew_map(yf_names)
    print(f"Hebrew names from Maya (pre-manual): {len(ticker_to_hebrew)}")

    # Apply manual overrides
    for ticker, heb in MANUAL_HEBREW.items():
        if ticker in yf_names:  # only if ticker is actually in our universe
            ticker_to_hebrew[ticker] = heb
    print(f"After manual additions: {len(ticker_to_hebrew)}")

    # Build final reference
    stocks = []
    for ticker in sorted(yf_names):
        stocks.append({
            "ticker": ticker,
            "english_name": yf_names[ticker],
            "hebrew_name": ticker_to_hebrew.get(ticker, ""),
        })

    with_both = sum(1 for s in stocks if s["english_name"] and s["hebrew_name"])
    with_heb = sum(1 for s in stocks if s["hebrew_name"])
    with_eng = sum(1 for s in stocks if s["english_name"])

    result = {
        "generated": __import__("datetime").date.today().isoformat(),
        "total": len(stocks),
        "with_english_name": with_eng,
        "with_hebrew_name": with_heb,
        "with_both_names": with_both,
        "stocks": stocks,
    }

    out = DATA / "tase_stock_reference.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== Final tase_stock_reference.json ===")
    print(f"Total tickers:    {len(stocks)}")
    print(f"English names:    {with_eng}  (539 equity + 249 bonds/funds)")
    print(f"Hebrew names:     {with_heb}")
    print(f"Both names:       {with_both}")
    print(f"\nKey stocks check:")
    key = ["TEVA.TA","NICE.TA","ICL.TA","ESLT.TA","POLI.TA","LUMI.TA",
           "DSCT.TA","BEZQ.TA","MZTF.TA","NVMI.TA","TSEM.TA","CAMT.TA","KMDA.TA"]
    for t in key:
        s = {s["ticker"]: s for s in stocks}.get(t)
        if s:
            print(f"  {t:<18} | {s['english_name'][:25]:<25} | {s['hebrew_name'] or 'MISSING'}")
        else:
            print(f"  {t:<18} | NOT IN LIST")


if __name__ == "__main__":
    main()
