"""
Borkai Live Scanner — Continuous Israeli Market Scanner (Zero API)
==================================================================

Continuously scans all TASE stocks using only yfinance.
No AI. No API calls. No tokens consumed.

Detects:
  - Breakout candidates     (price surge + volume confirmation)
  - Early movers            (volume leading before price catches up)
  - Strong momentum         (multi-day directional build-up)
  - Unusual activity        (behaviour change after quiet period)

Usage:
    python scan_live.py                        # all stocks, 5-min cycles
    python scan_live.py --interval 120         # scan every 2 minutes
    python scan_live.py --interval 600         # scan every 10 minutes
    python scan_live.py --size large           # large-caps only
    python scan_live.py --once                 # single scan then exit
    python scan_live.py --quiet                # suppress per-batch progress
    python scan_live.py --min-score 3          # raise signal bar
    python scan_live.py --top-n 30             # show top 30 in ranked list

Output:
    Console: live dashboard printed each cycle
    File:    reports/scanner/current_ranking.md  (overwritten each cycle)
    State:   scanner_state.json  (heat/trend history, survives restarts)
"""
import argparse
import os
import sys

# Fix Unicode on Windows Hebrew locale
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

from borkai.scanner.live_scanner import LiveScanConfig, run_live_scan


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Borkai Live Scanner — continuous TASE scan, zero API calls",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--interval", type=int, default=300, metavar="SECONDS",
        help="Seconds between scan cycles (default: 300 = 5 min)",
    )
    parser.add_argument(
        "--size", choices=["large", "mid", "small"], default=None,
        help="Filter stocks by market cap bucket (default: all)",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single scan cycle then exit",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-batch download progress output",
    )
    parser.add_argument(
        "--min-score", type=int, default=2, dest="min_score",
        help="Minimum live score to appear in category lists (default: 2)",
    )
    parser.add_argument(
        "--top-n", type=int, default=20, dest="top_n",
        help="Number of stocks shown in the overall ranked list (default: 20)",
    )
    parser.add_argument(
        "--output-dir", default="reports/scanner", dest="output_dir",
        help="Directory for ranking markdown output (default: reports/scanner)",
    )
    parser.add_argument(
        "--state-file", default="scanner_state.json", dest="state_file",
        help="JSON file for persistent heat/trend state (default: scanner_state.json)",
    )
    parser.add_argument(
        "--csv", default=None,
        help="Path to TASE stocks CSV (default: borkai/data/tase_stocks.csv)",
    )

    args = parser.parse_args()

    # Default CSV path relative to this file
    csv_path = args.csv or os.path.join(
        _ROOT, "borkai", "data", "tase_stocks.csv"
    )

    cfg = LiveScanConfig(
        csv_path     = csv_path,
        state_file   = args.state_file,
        output_dir   = args.output_dir,
        interval_sec = args.interval,
        size_filter  = args.size,
        min_score    = args.min_score,
        top_n        = args.top_n,
        run_once     = args.once,
        verbose      = not args.quiet,
    )

    try:
        run_live_scan(cfg)
    except KeyboardInterrupt:
        print("\n\n[SCANNER] Stopped by user. State saved.")
    except FileNotFoundError as e:
        print(f"\n[SCANNER] ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
