"""
utils/build_llm_mapping.py
--------------------------
Use GPT-4o-mini to match unresolved Maya company names to real .TA Yahoo Finance tickers.

Reads:  data/maya_company_mapping.json  (937 unmatched companies)
        data/israel_researcher_state.json  (tase_universe_cache — 528 equity tickers)
Writes: data/maya_company_mapping.json  (adds new cid_to_ticker entries)

Usage (from project root):
    python utils/build_llm_mapping.py

The script sends batches of 50 Hebrew company names to GPT and asks it to identify
which .TA ticker each company corresponds to (if listed on TASE). Only tickers that
exist in the 528-stock equity universe are accepted. Runs until all companies are
processed or the user interrupts.
"""

from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

# ── paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
MAPPING_PATH  = DATA / "maya_company_mapping.json"
STATE_PATH    = DATA / "israel_researcher_state.json"

# ── config ───────────────────────────────────────────────────────────────────
BATCH_SIZE = 50
SLEEP_BETWEEN_BATCHES = 1.0  # seconds


def load_openai_key() -> str:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        sys.exit("OPENAI_API_KEY not found in .env")
    return key


def load_equity_universe() -> tuple[set[str], dict[str, str]]:
    """Return (set of .TA equity tickers, dict of ticker→English name)."""
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f)
    tickers = state.get("tase_universe_cache", {}).get("tickers", [])
    equity = {t for t in tickers if "-" not in t}
    names_path = DATA / "tase_ticker_names.json"
    names: dict[str, str] = {}
    if names_path.exists():
        with open(names_path, "r", encoding="utf-8") as f:
            names = json.load(f)
    return equity, names


def load_mapping() -> dict:
    with open(MAPPING_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_mapping(data: dict) -> None:
    tmp = MAPPING_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(MAPPING_PATH)


def ask_gpt(client, batch: list[tuple[str, str]], universe: set[str], names: dict[str, str] | None = None) -> dict[str, str]:
    """
    Send a batch of (companyId, hebrew_name) pairs to GPT.
    Returns {companyId: ticker} for confident matches only.
    """
    lines = "\n".join(f"{cid}: {name}" for cid, name in batch)
    # Build universe string with English names where available
    if names:
        ticker_lines = [f"{t} ({names[t]})" if t in names else t for t in sorted(universe)]
    else:
        ticker_lines = sorted(universe)
    universe_str = "\n".join(ticker_lines)

    prompt = f"""You are an expert on Israeli capital markets and TASE (Tel Aviv Stock Exchange).

Below is a list of Israeli companies registered on the Maya TASE disclosure system, given as:
  companyId: Hebrew company name

For each company, identify its Yahoo Finance ticker on TASE (ending in .TA) if it is publicly traded.
Only return a match if you are confident (>85% certain) the ticker is correct.
Only use tickers from the allowed universe listed below.
If a company is not publicly traded, is a subsidiary, or you are not confident, return null.

ALLOWED TICKERS (ticker | English name):
{universe_str}

COMPANIES TO MATCH:
{lines}

Respond with ONLY a valid JSON object mapping companyId (string) to ticker (string or null).
Example: {{"297": "ABCD.TA", "1390": null, "1397": "EFGH.TA"}}
No explanation, no markdown, just the JSON object.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=800,
    )
    raw = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        print(f"  [WARN] JSON parse error: {raw[:200]}")
        return {}

    # Validate: only keep tickers in the universe
    validated: dict[str, str] = {}
    for cid, ticker in result.items():
        if ticker and isinstance(ticker, str) and ticker in universe:
            validated[cid] = ticker
    return validated


def main() -> None:
    key = load_openai_key()
    from openai import OpenAI
    client = OpenAI(api_key=key)

    equity_universe, ticker_names = load_equity_universe()
    print(f"Equity universe: {len(equity_universe)} tickers ({len(ticker_names)} with English names)")

    mapping = load_mapping()
    cid_to_ticker: dict[str, str] = mapping.get("cid_to_ticker", {})
    companies: dict[str, dict] = mapping.get("companies", {})

    # Build unmatched list (skip blocked CIDs)
    blocked: set[str] = set(mapping.get("blocked_cids", {}).keys())
    unmatched = [(cid, info["name"]) for cid, info in companies.items()
                 if cid not in cid_to_ticker and cid not in blocked and info.get("name")]
    print(f"Unmatched companies: {len(unmatched)}")
    print(f"Will process in batches of {BATCH_SIZE} (~{len(unmatched)//BATCH_SIZE + 1} batches)")

    new_matches = 0
    batch_num = 0

    for i in range(0, len(unmatched), BATCH_SIZE):
        batch = unmatched[i:i + BATCH_SIZE]
        batch_num += 1
        print(f"\nBatch {batch_num} ({i+1}–{min(i+BATCH_SIZE, len(unmatched))} of {len(unmatched)})...", end=" ", flush=True)

        try:
            matches = ask_gpt(client, batch, equity_universe, ticker_names)
        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(5)
            continue

        if matches:
            print(f"{len(matches)} new matches:")
            for cid, ticker in matches.items():
                name = companies.get(cid, {}).get("name", "?")
                print(f"    {cid} ({name.encode('ascii','replace').decode()}) -> {ticker}")
            cid_to_ticker.update(matches)
            # Update company ticker field too
            for cid, ticker in matches.items():
                if cid in companies:
                    companies[cid]["ticker"] = ticker
            new_matches += len(matches)

            # Save after each batch so progress is not lost
            mapping["cid_to_ticker"] = cid_to_ticker
            mapping["companies"] = companies
            mapping["total_matched"] = len(cid_to_ticker)
            save_mapping(mapping)
        else:
            print("no matches")

        if i + BATCH_SIZE < len(unmatched):
            time.sleep(SLEEP_BETWEEN_BATCHES)

    print(f"\n=== Done. Added {new_matches} new ticker mappings. Total: {len(cid_to_ticker)} ===")


if __name__ == "__main__":
    main()
