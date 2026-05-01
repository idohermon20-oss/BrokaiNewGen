"""
Borkai Smart Scanner — CLI Entry Point
=======================================

3-layer Israeli market scanner:

  Layer 1  Fast yfinance scan  (all stocks, no AI, ~30-90s)
  Layer 2  Light AI filter     (top L1 candidates, DDG + GPT-4o-mini, ~60-120s)
  Layer 3  Full deep analysis  (top L2 candidates, full Borkai pipeline)

Usage:
    python smart_scan.py                             # default settings
    python smart_scan.py --horizon short             # short-term scan
    python smart_scan.py --top-l1 40 --top-l2 15 --top-l3 8
    python smart_scan.py --size large                # large-caps only
    python smart_scan.py --no-deep                   # skip Layer 3
    python smart_scan.py --layer1-only               # Layer 1 only (fastest)
    python smart_scan.py --no-articles               # skip article fetching in L3
    python smart_scan.py --output-dir ./my_reports

Output structure:
    reports/
    └── YYYY-MM-DD/
        └── smart_short/
            ├── layer1_scan.md      <- All stocks scored
            ├── layer2_filter.md    <- Candidate details + event classification
            ├── ranking_short.md    <- Deep analysis rankings
            └── deep/
                ├── 01_ESLT_TA_score87.md
                └── ...
"""
import argparse
import os
import sys
import io

# Fix Unicode encoding on Windows Hebrew locale
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

from borkai.scanner.scanner import run_smart_scan, DEFAULT_CSV


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Borkai Smart Scanner — 3-layer Israeli market scan",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Layer depth control
    depth = parser.add_mutually_exclusive_group()
    depth.add_argument(
        "--layer1-only",
        action="store_true",
        help="Run only Layer 1 (fast scan, no AI)",
    )
    depth.add_argument(
        "--no-deep",
        action="store_true",
        help="Run Layers 1 + 2 only (no full deep analysis)",
    )

    # Size / universe
    parser.add_argument(
        "--horizon",
        choices=["short", "medium", "long"],
        default="short",
        help="Time horizon for deep analysis (default: short)",
    )
    parser.add_argument(
        "--size",
        choices=["large", "mid", "small"],
        default=None,
        help="Filter stocks by market cap bucket (default: all)",
    )
    parser.add_argument(
        "--csv",
        default=DEFAULT_CSV,
        help="Path to TASE stocks CSV (default: borkai/data/tase_stocks.csv)",
    )

    # Funnel widths
    parser.add_argument(
        "--top-l1",
        type=int,
        default=30,
        help="Top N from Layer 1 passed to Layer 2 (default: 30)",
    )
    parser.add_argument(
        "--top-l2",
        type=int,
        default=10,
        help="Top N from Layer 2 passed to Layer 3 (default: 10)",
    )
    parser.add_argument(
        "--top-l3",
        type=int,
        default=5,
        help="Max deep analysis reports to save (default: 5)",
    )

    # Output
    parser.add_argument(
        "--output-dir",
        default="reports",
        help="Base output directory (default: reports/)",
    )
    parser.add_argument(
        "--no-articles",
        action="store_true",
        help="Skip article fetching in Layer 3 (faster, lower cost)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress detailed progress output",
    )

    args = parser.parse_args()

    run_deep = not (args.layer1_only or args.no_deep)

    run_smart_scan(
        horizon=args.horizon,
        top_l1=args.top_l1,
        top_l2=args.top_l2,
        top_l3=args.top_l3,
        csv_path=args.csv,
        output_dir=args.output_dir,
        size_filter=args.size,
        run_deep=run_deep,
        no_articles=args.no_articles,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
