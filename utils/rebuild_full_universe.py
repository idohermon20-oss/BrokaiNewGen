"""
rebuild_full_universe.py
========================
Stage 1: Fetch all 788 TLV-listed tickers from Yahoo Finance Screener.
Stage 2: Match Hebrew names from Maya company list using GPT.
Stage 3: Save comprehensive data/tase_stock_reference.json

Run (from project root):
    python utils/rebuild_full_universe.py
"""

from __future__ import annotations
import json, sys, os, tempfile, shutil, time, re
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT))

# SSL fix
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


# ── Stage 1: Fetch complete YF universe ──────────────────────────────────────

def fetch_yf_universe() -> dict[str, str]:
    """Returns {ticker: english_name} for all 788 TLV-listed stocks."""
    from yfinance.screener import screen, EquityQuery

    query = EquityQuery("eq", ["exchange", "TLV"])
    tickers: dict[str, str] = {}
    offset = 0

    print("Stage 1: Fetching YF universe (exchange=TLV)...")
    while True:
        response = screen(query, size=250, offset=offset)
        quotes = response.get("quotes", [])
        total = response.get("total", 0)
        for q in quotes:
            sym = q.get("symbol", "")
            name = q.get("longName") or q.get("shortName") or ""
            if sym:
                tickers[sym] = name
        offset += len(quotes)
        print(f"  {len(tickers)}/{total}", end="\r", flush=True)
        if not quotes or offset >= total:
            break
        time.sleep(0.5)

    print(f"\n  Done: {len(tickers)} tickers")
    return tickers


# ── Stage 2: Load existing Hebrew names from Maya mapping ────────────────────

def load_maya_hebrew() -> dict[str, str]:
    """Returns {ticker.TA: hebrew_name} from maya_company_mapping.json."""
    p = DATA / "maya_company_mapping.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    companies = data.get("companies", {})
    cid_to_ticker = data.get("cid_to_ticker", {})

    ticker_to_hebrew: dict[str, str] = {}
    for cid, info in companies.items():
        ticker = info.get("ticker") or cid_to_ticker.get(cid)
        name = info.get("name", "")
        if ticker and name and ticker not in ticker_to_hebrew:
            ticker_to_hebrew[ticker] = name
    return ticker_to_hebrew


def load_maya_all_companies() -> list[dict]:
    """Returns all Maya companies as list of {cid, name, ticker}."""
    p = DATA / "maya_company_mapping.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    companies = data.get("companies", {})
    cid_to_ticker = data.get("cid_to_ticker", {})
    result = []
    for cid, info in companies.items():
        result.append({
            "cid": cid,
            "name": info.get("name", ""),
            "ticker": info.get("ticker") or cid_to_ticker.get(cid),
        })
    return result


# ── Stage 3: Use GPT to match missing Hebrew names ───────────────────────────

def gpt_match_hebrew_names(
    missing_tickers: dict[str, str],   # {ticker: english_name}
    all_maya_companies: list[dict],     # [{cid, name, ticker}]
    openai_client,
    batch_size: int = 40,
) -> dict[str, str]:
    """
    For each ticker without a Hebrew name, ask GPT to find the matching
    Hebrew company name from the Maya company list.
    Returns {ticker: hebrew_name}.
    """
    result: dict[str, str] = {}
    tickers_list = list(missing_tickers.items())

    # Build a lookup of all Hebrew names (compact)
    all_names = [c["name"] for c in all_maya_companies if c["name"]]
    # Deduplicate
    all_names = sorted(set(all_names))

    total_batches = (len(tickers_list) + batch_size - 1) // batch_size
    print(f"\nStage 3: GPT matching {len(tickers_list)} tickers -> Hebrew names ({total_batches} batches)...")

    for batch_i in range(0, len(tickers_list), batch_size):
        batch = tickers_list[batch_i:batch_i + batch_size]
        batch_num = batch_i // batch_size + 1

        # Build ticker lines
        ticker_lines = "\n".join(
            f"{ticker}: {eng_name}" for ticker, eng_name in batch
        )

        # Give GPT a subset of Maya names around relevant letters to keep prompt short
        # Use first 600 names (sorted alphabetically in Hebrew)
        names_sample = "\n".join(all_names[:600])

        prompt = f"""You are a Tel Aviv Stock Exchange (TASE) expert.

Below is a list of TASE stock tickers with their English names.
Match each ticker to its Hebrew company name from the Maya TASE company list provided.

Rules:
- Return ONLY a JSON object: {{ticker: "Hebrew name"}}
- If no confident match exists, use "" (empty string) — do NOT guess
- Hebrew names on TASE often end with בע"מ or בע'מ
- The ticker prefix usually hints at the Hebrew name (e.g. TEVA → תבע = תרופות, POLI → פועלים = Bank Hapoalim)
- Common transliterations: NICE→נייס, AMDOCS→אמדוקס, ELBIT→אלביט, HAPOALIM→הפועלים, LEUMI→לאומי, DISCOUNT→דיסקונט, ICL→כיל

TICKERS TO MATCH:
{ticker_lines}

MAYA HEBREW COMPANY LIST (partial):
{names_sample}

Respond with ONLY valid JSON. No explanation."""

        try:
            resp = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=2000,
            )
            raw = resp.choices[0].message.content.strip()
            # Strip markdown fences if present
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            matches = json.loads(raw)
            for ticker, heb in matches.items():
                if heb and ticker in missing_tickers:
                    result[ticker] = heb
            print(f"  Batch {batch_num}/{total_batches}: matched {len([v for v in matches.values() if v])}/{len(batch)}", flush=True)
        except Exception as e:
            print(f"  Batch {batch_num} error: {e}", flush=True)

        time.sleep(0.5)

    return result


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # Load .env
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass

    # Stage 1: Complete YF universe
    yf_tickers = fetch_yf_universe()

    # Save updated tase_ticker_names.json
    (DATA / "tase_ticker_names.json").write_text(
        json.dumps(yf_tickers, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved {len(yf_tickers)} tickers to data/tase_ticker_names.json")

    # Stage 2: Load existing Hebrew names
    ticker_to_hebrew = load_maya_hebrew()
    all_maya_companies = load_maya_all_companies()

    with_heb = {t: ticker_to_hebrew[t] for t in yf_tickers if t in ticker_to_hebrew}
    without_heb = {t: yf_tickers[t] for t in yf_tickers if t not in ticker_to_hebrew}
    print(f"\nStage 2: Hebrew names already known: {len(with_heb)}/{len(yf_tickers)}")
    print(f"  Still missing: {len(without_heb)}")

    # Stage 3: GPT matching for missing ones
    gpt_matches: dict[str, str] = {}
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key and without_heb:
        import openai
        client = openai.OpenAI(api_key=openai_key)
        gpt_matches = gpt_match_hebrew_names(without_heb, all_maya_companies, client)
        print(f"  GPT matched: {len(gpt_matches)} new Hebrew names")
    else:
        print("  Skipping GPT (no API key or nothing to match)")

    # Merge all Hebrew names
    final_hebrew = {**ticker_to_hebrew, **gpt_matches}

    # Build final reference
    stocks = []
    for ticker, eng_name in sorted(yf_tickers.items()):
        stocks.append({
            "ticker": ticker,
            "english_name": eng_name,
            "hebrew_name": final_hebrew.get(ticker, ""),
            "hebrew_source": (
                "maya_mapping" if ticker in ticker_to_hebrew
                else "gpt" if ticker in gpt_matches
                else ""
            ),
        })

    # Stats
    with_both = sum(1 for s in stocks if s["english_name"] and s["hebrew_name"])
    with_heb_total = sum(1 for s in stocks if s["hebrew_name"])
    with_eng_total = sum(1 for s in stocks if s["english_name"])

    result = {
        "generated": __import__("datetime").date.today().isoformat(),
        "total": len(stocks),
        "with_english_name": with_eng_total,
        "with_hebrew_name": with_heb_total,
        "with_both_names": with_both,
        "stocks": stocks,
    }

    out = DATA / "tase_stock_reference.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== Final Result ===")
    print(f"Total TASE tickers: {len(stocks)}")
    print(f"With English name:  {with_eng_total}")
    print(f"With Hebrew name:   {with_heb_total}")
    print(f"With BOTH names:    {with_both}")
    print(f"Saved to: {out}")

    # Sample with both names
    both = [s for s in stocks if s["english_name"] and s["hebrew_name"]][:15]
    print("\nSample (both names):")
    for s in both:
        print(f"  {s['ticker']:<18} | {s['english_name'][:28]:<28} | {s['hebrew_name']}")


if __name__ == "__main__":
    main()
