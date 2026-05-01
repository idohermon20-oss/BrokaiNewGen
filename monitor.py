"""
Borkai Continuous Market Monitor — CLI Entry Point
===================================================

Continuously scans the Israeli stock market (TASE), detects unusual activity,
ranks the strongest candidates, and runs deep analysis only on qualified stocks.

Architecture:
  Layer 1  Fast yfinance scan     -- every --interval seconds (default: 5 min)
  Layer 2  Light AI filter        -- every --l2-every L1 cycles (default: 30 min)
  Layer 3  Full deep analysis     -- triggered by smart re-run rules + cooldown

Usage:
    python monitor.py                          # default settings (5 min L1, 30 min L2)
    python monitor.py --interval 120           # 2-minute L1 scans
    python monitor.py --interval 600           # 10-minute L1 scans
    python monitor.py --size large             # large-caps only
    python monitor.py --horizon medium         # medium-term deep analysis
    python monitor.py --no-deep               # scan + rank only, skip L3
    python monitor.py --no-articles            # skip article fetching in L3
    python monitor.py --cooldown 6             # 6h cooldown between analyses
    python monitor.py --score-threshold 8      # higher bar for deep analysis

Output:
    monitor_state.json          -- per-stock state (survives restarts)
    reports/monitor/
      current_ranking.md        -- live ranked list (updated every cycle)
      YYYY-MM-DD/deep/          -- deep analysis reports as they are generated

Re-run logic:
    Hard triggers (bypass score threshold, short cooldown):
      - New Maya filing detected (DDG count increased)
      - Volume spike >= --vol-spike ratio (default: 3.0x)
      - Price spike >= --price-spike % (default: 5%)
      - Score jump >= --delta-threshold (default: 2.5)
      - High-impact event detected by L2

    Soft trigger (respects full cooldown):
      - Composite score >= --score-threshold (default: 7.0)
"""
import argparse
import os
import sys

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

from borkai.monitor.monitor_loop import run_monitor, MonitorConfig
from borkai.scanner.scanner import DEFAULT_CSV


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Borkai Continuous Market Monitor — live TASE surveillance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Timing
    parser.add_argument(
        "--interval", type=int, default=300, metavar="SECONDS",
        help="Seconds between Layer 1 scans (default: 300 = 5 min)",
    )
    parser.add_argument(
        "--l2-every", type=int, default=6, metavar="N",
        help="Run Layer 2 every N Layer 1 cycles (default: 6 = 30 min at 5-min L1)",
    )

    # Universe
    parser.add_argument(
        "--csv", default=DEFAULT_CSV,
        help="Path to TASE stocks CSV (default: borkai/data/tase_stocks.csv)",
    )
    parser.add_argument(
        "--size", choices=["large", "mid", "small"], default=None,
        help="Filter by market cap bucket (default: all)",
    )

    # Funnel widths
    parser.add_argument(
        "--top-l1", type=int, default=30, metavar="N",
        help="Top N Layer 1 stocks passed to Layer 2 each L2 cycle (default: 30)",
    )
    parser.add_argument(
        "--top-candidates", type=int, default=50, metavar="N",
        help="Total candidates tracked in ranking (default: 50)",
    )

    # Deep analysis
    parser.add_argument(
        "--horizon", choices=["short", "medium", "long"], default="short",
        help="Time horizon for deep analysis (default: short)",
    )
    parser.add_argument(
        "--no-deep", action="store_true",
        help="Disable Layer 3 deep analysis (scan + rank only)",
    )
    parser.add_argument(
        "--no-articles", action="store_true",
        help="Skip article fetching in Layer 3 (faster, lower cost)",
    )
    parser.add_argument(
        "--max-deep", type=int, default=2, metavar="N",
        help="Max deep analyses to run per cycle (default: 2)",
    )

    # Trigger thresholds
    parser.add_argument(
        "--score-threshold", type=float, default=7.0,
        help="Composite score threshold for soft-trigger deep analysis (default: 7.0)",
    )
    parser.add_argument(
        "--cooldown", type=float, default=4.0, metavar="HOURS",
        help="Hours between soft-triggered analyses per stock (default: 4.0)",
    )
    parser.add_argument(
        "--hard-cooldown", type=float, default=1.5, metavar="HOURS",
        help="Hours between hard-triggered analyses per stock (default: 1.5)",
    )
    parser.add_argument(
        "--vol-spike", type=float, default=3.0,
        help="Volume ratio that hard-triggers deep analysis (default: 3.0x)",
    )
    parser.add_argument(
        "--price-spike", type=float, default=5.0,
        help="Abs daily %% price move that hard-triggers deep analysis (default: 5%%)",
    )
    parser.add_argument(
        "--delta-threshold", type=float, default=2.5,
        help="Score jump that hard-triggers deep analysis (default: 2.5)",
    )

    # Output
    parser.add_argument(
        "--output-dir", default="reports/monitor",
        help="Base output directory for reports (default: reports/monitor/)",
    )
    parser.add_argument(
        "--state-file", default="monitor_state.json",
        help="JSON file for persistent state (default: monitor_state.json)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress detailed Layer 1/2 progress output",
    )

    args = parser.parse_args()

    # ── DISABLED ──────────────────────────────────────────────────────────────
    # Automatic continuous market scanning is turned off to prevent unnecessary
    # API token consumption. Use single-stock analysis instead:
    #   python main.py <TICKER> <HORIZON> il
    print(
        "\n[MONITOR] DISABLED — The continuous market monitor has been turned off.\n"
        "          Reason: automatic market-wide scanning consumes too many API tokens.\n"
        "\n"
        "          For single-stock analysis run:\n"
        "            python main.py ESLT medium il\n"
        "            python main.py BEZQ short il\n"
        "\n"
        "          To re-enable the monitor, remove this guard in monitor.py.\n"
    )
    return
    # ── END DISABLED ──────────────────────────────────────────────────────────

    cfg = MonitorConfig(
        interval_sec=args.interval,
        l2_every=args.l2_every,
        csv_path=args.csv,
        size_filter=args.size,
        top_l1=args.top_l1,
        top_candidates=args.top_candidates,
        horizon=args.horizon,
        no_articles=args.no_articles,
        max_deep_per_cycle=0 if args.no_deep else args.max_deep,
        score_threshold=args.score_threshold,
        soft_cooldown_hours=args.cooldown,
        hard_cooldown_hours=args.hard_cooldown,
        volume_spike_ratio=args.vol_spike,
        price_spike_pct=args.price_spike,
        score_delta_threshold=args.delta_threshold,
        output_dir=args.output_dir,
        state_file=args.state_file,
        verbose=not args.quiet,
    )

    try:
        run_monitor(cfg)
    except KeyboardInterrupt:
        print("\n\n[MONITOR] Stopped by user. State saved.")


if __name__ == "__main__":
    main()
