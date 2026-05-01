"""
Maya Filings Retrieval — Regression Validator
==============================================

Tests that fetch_company_reports() returns real Maya TASE filings for a
set of Israeli stocks covering the main failure scenarios:

  - Stocks present in tase_stocks.csv with name_he + maya_id  (easy path)
  - Stocks present in tase_stocks.csv with name_he but no maya_id
  - Stocks NOT in tase_stocks.csv at all                       (NXSN - hard case)
  - Stocks given by English name only
  - Stocks with ambiguous / common Hebrew names

Run:
    python -m borkai.data.validate_maya
  or
    python borkai/data/validate_maya.py

Each test prints a result line.  The script exits with code 1 if any
MANDATORY case fails.
"""
from __future__ import annotations

import sys
import os
import time
from typing import List, Optional

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from borkai.data.maya_fetcher import fetch_company_reports, MayaReport
from borkai.data.company_resolver import resolve_company


# ── Test case definitions ──────────────────────────────────────────────────────

TEST_CASES = [
    # (label, query, mandatory)
    # Mandatory: failure = overall test failure
    ("ESLT (Elbit, large+known)",      "ESLT",              True),
    ("BEZQ (Bezeq, known id)",         "BEZQ",              True),
    ("TEVA (Teva, large pharma)",      "TEVA",              True),
    ("HAPO (Bank Hapoalim)",           "HAPO",              True),
    ("NXSN (Next Vision — hard case)", "NXSN",              True),   # key regression
    ("ZIM (by ticker)",                "ZIM",               True),
    ("NICE (NiCE Systems)",            "NICE",              True),
    # Advisory: failure logged but does not fail the suite
    ("ITRN (Ituran, may be small)",    "ITRN",              False),
    ("ARBE (Arbe Robotics, new IPO)",  "ARBE",              False),
    ("Elbit Systems (English name)",   "Elbit Systems",     False),
    ("Next Vision (English name)",     "Next Vision",       False),
]

_MAYA_SOURCES = {"Maya TASE (Playwright)", "Maya TASE (DDG)"}
_NON_MAYA_FETCH_PATHS = {"rss:google_news"}


def _validate_reports(reports: List[MayaReport], label: str) -> dict:
    """
    Validate that a report list meets the Maya-only rule.
    Returns a result dict.
    """
    total = len(reports)
    maya_reports   = [r for r in reports if r.source in _MAYA_SOURCES
                      or r.fetch_path.startswith(("playwright:", "ddg:"))]
    non_maya       = [r for r in reports if r.fetch_path in _NON_MAYA_FETCH_PATHS]
    paths_used     = list({r.fetch_path for r in reports})

    ok = total > 0 and len(non_maya) == 0
    return {
        "label":       label,
        "ok":          ok,
        "total":       total,
        "maya_count":  len(maya_reports),
        "non_maya":    len(non_maya),
        "paths":       paths_used,
    }


def run_validation(max_items: int = 5, skip_playwright: bool = False) -> bool:
    """
    Run all test cases.  Returns True if all mandatory cases pass.
    """
    print("=" * 70)
    print("Maya Filings Retrieval — Regression Validation")
    print("=" * 70)

    mandatory_failures = []
    advisory_failures  = []

    for label, query, mandatory in TEST_CASES:
        print(f"\n[TEST] {label}  (query={query!r})")

        # 1. Resolve identity
        identity = resolve_company(query)
        print(f"  Identity: ticker={identity.ticker!r}  name_he={identity.name_he!r}"
              f"  maya_id={identity.maya_id}  conf={identity.confidence:.2f}"
              f"  path={identity.resolution_path}")

        # 2. Fetch filings
        t0 = time.time()
        try:
            reports = fetch_company_reports(
                company_name=identity.name_en or query,
                ticker=identity.ticker or query,
                max_items=max_items,
                name_he=identity.name_he,
                identity=identity,
            )
        except Exception as exc:
            print(f"  EXCEPTION: {exc}")
            result = {"label": label, "ok": False, "total": 0, "maya_count": 0,
                      "non_maya": 0, "paths": []}
        else:
            result = _validate_reports(reports, label)
        elapsed = time.time() - t0

        # 3. Print result
        status = "PASS" if result["ok"] else "FAIL"
        print(f"  [{status}] {result['total']} filings in {elapsed:.1f}s "
              f"| maya={result['maya_count']} non_maya={result['non_maya']} "
              f"| paths={result['paths']}")

        if not result["ok"]:
            if mandatory:
                mandatory_failures.append(label)
                print(f"  *** MANDATORY FAILURE ***")
            else:
                advisory_failures.append(label)
                print(f"  (advisory only)")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    total_cases = len(TEST_CASES)
    mandatory_cases = sum(1 for _, _, m in TEST_CASES if m)
    advisory_cases  = total_cases - mandatory_cases

    passed_mandatory = mandatory_cases - len(mandatory_failures)
    passed_advisory  = advisory_cases  - len(advisory_failures)

    print(f"Mandatory: {passed_mandatory}/{mandatory_cases} passed")
    print(f"Advisory:  {passed_advisory}/{advisory_cases} passed")

    if mandatory_failures:
        print(f"\nMANDATORY FAILURES:")
        for f in mandatory_failures:
            print(f"  - {f}")

    if advisory_failures:
        print(f"\nAdvisory failures:")
        for f in advisory_failures:
            print(f"  - {f}")

    overall = len(mandatory_failures) == 0
    print(f"\nOverall: {'PASS' if overall else 'FAIL'}")
    return overall


if __name__ == "__main__":
    success = run_validation()
    sys.exit(0 if success else 1)
