"""
Borkai Continuous Market Monitor
=================================

3-layer continuously running market surveillance system for TASE (Israeli stocks).

    Layer 1  Fast yfinance scan     runs every N minutes    (no AI, no cost)
    Layer 2  Light AI filter        runs every M*N minutes  (DDG + GPT-4o-mini)
    Layer 3  Full deep analysis     triggered on demand     (full Borkai pipeline)

Usage:
    from borkai.monitor import run_monitor
"""
from .monitor_loop import run_monitor, MonitorConfig

__all__ = ["run_monitor", "MonitorConfig"]
