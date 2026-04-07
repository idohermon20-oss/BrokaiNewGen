"""
build_stock_reference.py
========================
Builds a comprehensive TASE stock reference combining:
  - English names from data/tase_ticker_names.json (Yahoo Finance)
  - Hebrew names from data/maya_company_mapping.json (Maya TASE API)
  - Yahoo Finance validation (liveness check)

Output: data/tase_stock_reference.json

Run (from project root):
    python utils/build_stock_reference.py
"""

from __future__ import annotations
import json, sys, time, os, tempfile, shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent

# SSL fix for Hebrew username path (same as israel_researcher/__init__.py)
try:
    import certifi
    _dst = os.path.join(tempfile.gettempdir(), "brokai_cacert.pem")
    if not os.path.exists(_dst):
        shutil.copy2(certifi.where(), _dst)
    os.environ.setdefault("SSL_CERT_FILE", _dst)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", _dst)
    os.environ.setdefault("CURL_CA_BUNDLE", _dst)
except Exception:
    pass
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT))


def load_english_names() -> dict[str, str]:
    """Load {ticker: english_name} from tase_ticker_names.json."""
    p = DATA / "tase_ticker_names.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def load_maya_mapping() -> tuple[dict[str, str], dict[str, str]]:
    """
    Returns:
        cid_to_ticker: {cid: ticker.TA}
        ticker_to_hebrew: {ticker.TA: hebrew_name}  (best Hebrew name per ticker)
    """
    p = DATA / "maya_company_mapping.json"
    if not p.exists():
        return {}, {}
    data = json.loads(p.read_text(encoding="utf-8"))
    cid_to_ticker = data.get("cid_to_ticker", {})
    companies = data.get("companies", {})

    ticker_to_hebrew: dict[str, str] = {}
    for cid, info in companies.items():
        ticker = info.get("ticker") or cid_to_ticker.get(cid)
        name = info.get("name", "")
        if ticker and name and ticker not in ticker_to_hebrew:
            ticker_to_hebrew[ticker] = name

    return cid_to_ticker, ticker_to_hebrew


def validate_ticker_yf(ticker: str) -> tuple[bool, float | None]:
    """Check if ticker is live on Yahoo Finance. Returns (valid, last_price)."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).fast_info
        price = float(info.last_price) if info.last_price else None
        return (price is not None and price > 0), price
    except Exception:
        return False, None


def main():
    english_names = load_english_names()
    _, ticker_to_hebrew = load_maya_mapping()

    print(f"English names: {len(english_names)} tickers", flush=True)
    print(f"Hebrew names:  {len(ticker_to_hebrew)} tickers", flush=True)

    all_tickers = sorted(set(english_names) | set(ticker_to_hebrew))
    print(f"Total unique tickers: {len(all_tickers)}", flush=True)

    # Check existing reference to avoid re-validating already-checked tickers
    ref_path = DATA / "tase_stock_reference.json"
    existing: dict[str, dict] = {}
    if ref_path.exists():
        try:
            existing_data = json.loads(ref_path.read_text(encoding="utf-8"))
            for s in existing_data.get("stocks", []):
                existing[s["ticker"]] = s
        except Exception:
            pass
    print(f"Already validated: {len(existing)} tickers", flush=True)

    stocks = []
    for i, ticker in enumerate(all_tickers, 1):
        eng = english_names.get(ticker, "")
        heb = ticker_to_hebrew.get(ticker, "")

        # Reuse existing validation if we have it
        if ticker in existing:
            ex = existing[ticker]
            entry = {
                "ticker": ticker,
                "english_name": eng or ex.get("english_name", ""),
                "hebrew_name": heb or ex.get("hebrew_name", ""),
                "valid_yf": ex.get("valid_yf", False),
                "last_price": ex.get("last_price"),
            }
        else:
            # Validate against Yahoo Finance
            valid, price = validate_ticker_yf(ticker)
            entry = {
                "ticker": ticker,
                "english_name": eng,
                "hebrew_name": heb,
                "valid_yf": valid,
                "last_price": round(price, 2) if price else None,
            }
            status = "OK" if valid else "XX"
            print(f"  [{i:4d}/{len(all_tickers)}] {ticker:<18} {status}  price={price}", flush=True)
            time.sleep(0.15)

        stocks.append(entry)

    valid_count = sum(1 for s in stocks if s["valid_yf"])
    with_eng = sum(1 for s in stocks if s["english_name"])
    with_heb = sum(1 for s in stocks if s["hebrew_name"])
    with_both = sum(1 for s in stocks if s["english_name"] and s["hebrew_name"])

    result = {
        "generated": __import__("datetime").date.today().isoformat(),
        "total": len(stocks),
        "valid_yf": valid_count,
        "with_english_name": with_eng,
        "with_hebrew_name": with_heb,
        "with_both_names": with_both,
        "stocks": stocks,
    }

    ref_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nSaved {len(stocks)} stocks to {ref_path}")
    print(f"  Valid on YF:       {valid_count}")
    print(f"  With English name: {with_eng}")
    print(f"  With Hebrew name:  {with_heb}")
    print(f"  With both names:   {with_both}")

    # Sample: tickers with both names
    both = [s for s in stocks if s["english_name"] and s["hebrew_name"]][:10]
    print("\nSample (has both names):")
    for s in both:
        print(f"  {s['ticker']:<18} | {s['english_name'][:30]:<30} | {s['hebrew_name']}")


if __name__ == "__main__":
    main()
