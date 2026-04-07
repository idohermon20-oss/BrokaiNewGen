"""
match_hebrew_names.py
=====================
Matches 788 YF .TA tickers to Hebrew names without GPT, using:
  1. Existing Maya cid_to_ticker mappings (most reliable)
  2. Name normalization matching between tase_full_mapping.xlsx and maya companies
  3. secNum // 1000 == cid heuristic with name similarity check

Saves results to data/tase_stock_reference.json

Run (from project root):
    python utils/match_hebrew_names.py
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"


def norm(s: str) -> str:
    """Strip Hebrew legal suffixes and punctuation for comparison."""
    s = str(s)
    # Remove common TASE share-type suffixes
    for pat in [r"בע[''\"]*מ", r"ע['']*ש\b", r"\bד\b", r"\bר\b"]:
        s = re.sub(pat, "", s)
    s = re.sub(r"[\s\-\.\,\"']+", "", s)
    return s.strip()


def first_n(s: str, n: int = 4) -> str:
    """First N significant Hebrew characters."""
    clean = re.sub(r"[^\u05d0-\u05ea]", "", s)
    return clean[:n]


def main():
    # ── Load data ─────────────────────────────────────────────────────────────
    yf_names = json.loads((DATA / "tase_ticker_names.json").read_text(encoding="utf-8"))
    mapping = json.loads((DATA / "maya_company_mapping.json").read_text(encoding="utf-8"))
    cid_to_ticker = mapping.get("cid_to_ticker", {})
    companies = mapping.get("companies", {})

    import pandas as pd
    tase_df = pd.read_excel(DATA / "tase_full_mapping.xlsx")

    print(f"YF tickers: {len(yf_names)}")
    print(f"Maya companies: {len(companies)}")
    print(f"TASE local symbols: {len(tase_df)}")

    # ── Method 1: direct ticker from maya mapping ─────────────────────────────
    ticker_to_hebrew: dict[str, str] = {}
    for cid, info in companies.items():
        ticker = info.get("ticker") or cid_to_ticker.get(cid)
        name = info.get("name", "")
        if ticker and name and ticker not in ticker_to_hebrew:
            ticker_to_hebrew[ticker] = name

    m1 = len(ticker_to_hebrew)
    print(f"\nMethod 1 (direct maya mapping):  {m1} tickers have Hebrew names")

    # ── Method 2: tase_full_mapping name → maya name → ticker ─────────────────
    # Build reverse: normalized_maya_name -> ticker
    maya_norm_to_ticker: dict[str, str] = {}
    maya_norm_to_name: dict[str, str] = {}
    for cid, info in companies.items():
        ticker = info.get("ticker") or cid_to_ticker.get(cid)
        name = info.get("name", "")
        if ticker and name:
            key = norm(name)
            if key not in maya_norm_to_ticker:
                maya_norm_to_ticker[key] = ticker
                maya_norm_to_name[key] = name

    # Also build: first-4-hebrew-chars -> list of (norm_key, ticker)
    maya_prefix: dict[str, list[tuple[str, str, str]]] = {}
    for norm_key, ticker in maya_norm_to_ticker.items():
        pref = first_n(norm_key, 4)
        maya_prefix.setdefault(pref, []).append((norm_key, ticker, maya_norm_to_name[norm_key]))

    # Try to match tase_df rows to maya
    m2_new = 0
    tase_secnum_to_ticker: dict[int, tuple[str, str]] = {}  # secNum -> (ticker, heb_name)
    for _, row in tase_df.iterrows():
        tase_name = str(row["name"])
        secNum = int(row["secNum"])
        tase_norm = norm(tase_name)
        tase_pref = first_n(tase_norm, 4)

        # Exact norm match
        if tase_norm in maya_norm_to_ticker:
            ticker = maya_norm_to_ticker[tase_norm]
            tase_secnum_to_ticker[secNum] = (ticker, tase_name)
            if ticker not in ticker_to_hebrew:
                ticker_to_hebrew[ticker] = tase_name
                m2_new += 1
            continue

        # Prefix match (first 4 Hebrew chars) — only if unique match
        candidates = maya_prefix.get(tase_pref, [])
        if len(candidates) == 1:
            _, ticker, maya_name = candidates[0]
            tase_secnum_to_ticker[secNum] = (ticker, tase_name)
            if ticker not in ticker_to_hebrew:
                ticker_to_hebrew[ticker] = tase_name
                m2_new += 1

    print(f"Method 2 (name matching):         +{m2_new} new  (total {len(ticker_to_hebrew)})")

    # ── Method 3: secNum // 1000 == cid with name similarity check ─────────────
    m3_new = 0
    for _, row in tase_df.iterrows():
        secNum = int(row["secNum"])
        tase_name = str(row["name"])
        potential_cid = str(secNum // 1000)

        if potential_cid not in cid_to_ticker:
            continue

        ticker = cid_to_ticker[potential_cid]
        if ticker in ticker_to_hebrew:
            continue  # already have it

        # Name similarity check: first 3 Hebrew chars must overlap
        maya_name = companies.get(potential_cid, {}).get("name", "")
        pref_tase = first_n(norm(tase_name), 3)
        pref_maya = first_n(norm(maya_name), 3)

        if pref_tase and pref_maya and pref_tase == pref_maya:
            ticker_to_hebrew[ticker] = tase_name
            m3_new += 1

    print(f"Method 3 (secNum heuristic):      +{m3_new} new  (total {len(ticker_to_hebrew)})")

    # ── Build final reference ─────────────────────────────────────────────────
    stocks = []
    for ticker in sorted(yf_names):
        eng = yf_names[ticker]
        heb = ticker_to_hebrew.get(ticker, "")
        stocks.append({
            "ticker": ticker,
            "english_name": eng,
            "hebrew_name": heb,
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

    print(f"\n=== Final ===")
    print(f"Total tickers: {len(stocks)}")
    print(f"English names: {with_eng}")
    print(f"Hebrew names:  {with_heb}")
    print(f"Both names:    {with_both}")
    print(f"Saved: {out}")

    # Sample
    both = [s for s in stocks if s["english_name"] and s["hebrew_name"]][:15]
    print("\nSample (both names):")
    for s in both:
        print(f"  {s['ticker']:<18} | {s['english_name'][:28]:<28} | {s['hebrew_name']}")

    # Tickers still missing Hebrew name
    no_heb = [s for s in stocks if not s["hebrew_name"]]
    print(f"\n{len(no_heb)} tickers still have no Hebrew name")


if __name__ == "__main__":
    main()
