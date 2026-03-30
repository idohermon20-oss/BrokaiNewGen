"""
fetch_maya_companies.py
=======================
Uses Playwright (Maya WAF bypass) to fetch ALL companies from Maya's
autocomplete API with a comprehensive Hebrew prefix sweep.

Outputs:
  maya_companies_full.xlsx  — company ID, Hebrew name, pseudo-ticker

This gives the complete TASE-listed company universe from Maya's perspective.
Note: Maya does NOT return real ticker symbols (e.g. TEVA.TA) — only company IDs.
      Use fetch_tase_universe.py for real ticker symbols from Yahoo Finance.

Run:
    python fetch_maya_companies.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

# ── SSL fix ──────────────────────────────────────────────────────────────────
import tempfile
try:
    import certifi, shutil
    _dst = os.path.join(tempfile.gettempdir(), "brokai_cacert.pem")
    if not os.path.exists(_dst):
        shutil.copy2(certifi.where(), _dst)
    os.environ.setdefault("SSL_CERT_FILE", _dst)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", _dst)
except Exception:
    pass

import pandas as pd
from playwright.sync_api import sync_playwright

MAYA_BASE   = "https://mayaapi.tase.co.il/api/v1"
MAYA_ORIGIN = "https://maya.tase.co.il"

# Comprehensive Hebrew 2-letter prefixes to cover most company names.
# Each autocomplete call returns companies whose name starts with this prefix.
PREFIXES = [
    # Alef combinations
    "אב", "אג", "אד", "אה", "אז", "אח", "אט", "אי", "אכ", "אל", "אמ",
    "אנ", "אס", "אע", "אפ", "אצ", "אק", "אר", "אש", "את",
    # Bet
    "בא", "בב", "בג", "בד", "בה", "בו", "בז", "בח", "בי", "בכ", "בל",
    "במ", "בנ", "בס", "בע", "בפ", "בצ", "בק", "בר", "בש", "בת",
    # Gimel
    "גא", "גב", "גד", "גה", "גו", "גז", "גח", "גי", "גל", "גמ", "גן",
    "גע", "גפ", "גר", "גש", "גת",
    # Dalet
    "דא", "דב", "דג", "דה", "דו", "דז", "דח", "די", "דל", "דמ", "דנ",
    "דס", "דע", "דפ", "דצ", "דק", "דר", "דש",
    # He
    "הב", "הג", "הד", "הה", "הו", "הז", "הח", "הי", "הכ", "הל", "המ",
    "הנ", "הס", "הע", "הפ", "הצ", "הק", "הר", "הש", "הת",
    # Vav
    "וי",
    # Zayin
    "זה", "זו", "זי", "זכ", "זמ", "זנ", "זע",
    # Chet
    "חב", "חד", "חה", "חו", "חז", "חי", "חכ", "חל", "חמ", "חנ", "חס",
    "חע", "חפ", "חצ", "חק", "חר", "חש", "חת",
    # Tet
    "טב", "טד", "טה", "טו", "טי", "טכ", "טל", "טמ", "טנ", "טע",
    # Yod
    "יב", "יג", "יד", "יה", "יו", "יז", "יח", "יי", "יכ", "יל", "ימ",
    "ינ", "יס", "יע", "יפ", "יצ", "יק", "יר", "יש", "ית",
    # Kaf
    "כב", "כד", "כה", "כו", "כי", "כל", "כמ", "כנ", "כס", "כע", "כפ",
    "כר", "כש", "כת",
    # Lamed
    "לב", "לג", "לד", "לה", "לו", "לז", "לח", "לי", "לכ", "לל", "למ",
    "לנ", "לס", "לע", "לפ", "לצ", "לק", "לר", "לש", "לת",
    # Mem
    "מב", "מג", "מד", "מה", "מו", "מז", "מח", "מי", "מכ", "מל", "ממ",
    "מנ", "מס", "מע", "מפ", "מצ", "מק", "מר", "מש", "מת",
    # Nun
    "נב", "נג", "נד", "נה", "נו", "נז", "נח", "ני", "נכ", "נל", "נמ",
    "ננ", "נס", "נע", "נפ", "נצ", "נק", "נר", "נש", "נת",
    # Samech
    "סב", "סד", "סה", "סו", "סי", "סכ", "סל", "סמ", "סנ", "סע",
    # Ayin
    "עב", "עג", "עד", "עה", "עו", "עז", "עח", "עי", "עכ", "על", "עמ",
    "ענ", "עס", "עפ", "עצ", "עק", "ער", "עש", "עת",
    # Pe
    "פב", "פג", "פד", "פה", "פו", "פז", "פח", "פי", "פכ", "פל", "פמ",
    "פנ", "פס", "פע", "פצ", "פק", "פר", "פש", "פת",
    # Tsadi
    "צב", "צד", "צה", "צו", "צי", "צל", "צמ", "צנ", "צע", "צפ", "צר",
    # Kof
    "קב", "קד", "קה", "קו", "קי", "קכ", "קל", "קמ", "קנ", "קס", "קע",
    "קפ", "קצ", "קר", "קש",
    # Resh
    "רב", "רג", "רד", "רה", "רו", "רז", "רח", "רי", "רכ", "רל", "רמ",
    "רנ", "רס", "רע", "רפ", "רצ", "רק", "רר", "רש",
    # Shin
    "שב", "שג", "שד", "שה", "שו", "שז", "שח", "שי", "שכ", "של", "שמ",
    "שנ", "שס", "שע", "שפ", "שצ", "שק", "שר", "שש", "שת",
    # Tav
    "תב", "תג", "תד", "תה", "תו", "תז", "תח", "תי", "תכ", "תל", "תמ",
    "תנ", "תס", "תע", "תפ", "תצ", "תק", "תר", "תש", "תת",
]


def fetch_all_companies() -> dict[str, str]:
    """
    Sweep all Hebrew prefixes via Maya autocomplete API.
    Returns {company_id: hebrew_name}.
    Uses Playwright to bypass Incapsula WAF.
    """
    companies: dict[str, str] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        # Navigate to Maya to get session cookies / pass WAF challenge
        print("Loading Maya to get session cookies...")
        page.goto(MAYA_ORIGIN, wait_until="networkidle", timeout=30000)
        time.sleep(2)

        print(f"Sweeping {len(PREFIXES)} Hebrew prefixes...")
        for i, prefix in enumerate(PREFIXES, 1):
            try:
                url = f"{MAYA_BASE}/companies/autocomplete?Search={prefix}"
                result = page.evaluate(f"""
                    async () => {{
                        const r = await fetch('{url}', {{
                            headers: {{
                                'Accept': 'application/json',
                                'X-Maya-With': 'allow',
                                'Referer': '{MAYA_ORIGIN}/',
                            }}
                        }});
                        return r.ok ? await r.json() : [];
                    }}
                """)
                if isinstance(result, list):
                    for item in result:
                        key  = str(item.get("key", "")).strip()
                        name = str(item.get("value", "")).strip()
                        if key and name:
                            companies[key] = name

                if i % 20 == 0 or i == len(PREFIXES):
                    print(f"  [{i:4d}/{len(PREFIXES)}] {prefix}  |  {len(companies)} unique companies found")
                time.sleep(0.15)

            except Exception as e:
                print(f"  [{i:4d}] {prefix} ERROR: {e}")
                time.sleep(1)

        browser.close()

    return companies


def main():
    print("=" * 60)
    print("Maya Company Universe Fetcher")
    print("=" * 60)

    companies = fetch_all_companies()

    print(f"\nTotal unique companies from Maya: {len(companies)}")

    # Build DataFrame
    rows = [
        {
            "CompanyId":    cid,
            "CompanyName":  name,
            "PseudoTicker": f"TASE{cid}",
        }
        for cid, name in sorted(companies.items(), key=lambda x: x[1])
    ]
    df = pd.DataFrame(rows)

    # Export
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maya_companies_full.xlsx")
    df.to_excel(out_path, index=False)
    print(f"Saved to: {out_path}")

    # Print sample
    print("\nSample (first 20):")
    for _, row in df.head(20).iterrows():
        print(f"  {row['CompanyId']:>8}  {row['CompanyName']}")

    print("\nNote: Maya returns company names + IDs only — no real ticker symbols.")
    print("      Use fetch_tase_universe.py to get real .TA tickers from Yahoo Finance.")


if __name__ == "__main__":
    main()
