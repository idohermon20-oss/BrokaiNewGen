"""
make_pdf.py — Generate israel_researcher_docs.pdf
Comprehensive block-diagram documentation of the TASE equity research system.

Usage:
    python make_pdf.py

Output: israel_researcher_docs.pdf  (same directory)
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D

# ── Palette ───────────────────────────────────────────────────────────────────
BG       = "#0D1B2A"   # deep navy
ACCENT1  = "#00C8FF"   # cyan
ACCENT2  = "#00E596"   # teal-green
ACCENT3  = "#FFB300"   # amber
ACCENT4  = "#FF4D6D"   # coral-red
WHITE    = "#FFFFFF"
LGRAY    = "#B0C4DE"
DGRAY    = "#1E3045"
MGRAY    = "#2A4058"
PURPLE   = "#9B59B6"
ORANGE   = "#E67E22"

OUTPUT   = "israel_researcher_docs.pdf"


# ── Drawing helpers ───────────────────────────────────────────────────────────

def new_page(pdf, figsize=(17, 11)):
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 17); ax.set_ylim(0, 11)
    ax.axis("off")
    return fig, ax


def box(ax, x, y, w, h, color, text="", fontsize=9, text_color=WHITE,
        bold=False, radius=0.15, alpha=1.0, border_color=None):
    """Draw filled rounded box with centred text."""
    fancy = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        linewidth=1.2 if border_color else 0,
        edgecolor=border_color or color,
        facecolor=color,
        alpha=alpha,
        zorder=3,
    )
    ax.add_patch(fancy)
    if text:
        weight = "bold" if bold else "normal"
        ax.text(
            x + w / 2, y + h / 2, text,
            ha="center", va="center",
            fontsize=fontsize, color=text_color,
            fontweight=weight,
            wrap=True,
            zorder=4,
        )


def arrow(ax, x1, y1, x2, y2, color=LGRAY, lw=1.5, style="->"):
    ax.annotate(
        "", xy=(x2, y2), xytext=(x1, y1),
        arrowprops=dict(arrowstyle=style, color=color, lw=lw),
        zorder=5,
    )


def hdr(ax, title, subtitle=""):
    ax.text(8.5, 10.55, title, ha="center", va="center",
            fontsize=20, color=ACCENT1, fontweight="bold", zorder=6)
    if subtitle:
        ax.text(8.5, 10.15, subtitle, ha="center", va="center",
                fontsize=11, color=LGRAY, zorder=6)
    # separator line
    ax.add_line(Line2D([0.3, 16.7], [9.9, 9.9], color=ACCENT1, lw=1.5, zorder=6))


def label(ax, text, x, y, fontsize=8, color=LGRAY, ha="center", va="center", bold=False):
    ax.text(x, y, text, ha=ha, va=va, fontsize=fontsize, color=color,
            fontweight="bold" if bold else "normal", zorder=6)


def section_box(ax, x, y, w, h, title, title_color=ACCENT2):
    # outer border
    border = FancyBboxPatch((x, y), w, h,
                             boxstyle="round,pad=0,rounding_size=0.1",
                             linewidth=1, edgecolor=title_color,
                             facecolor=DGRAY, alpha=0.6, zorder=2)
    ax.add_patch(border)
    ax.text(x + w / 2, y + h - 0.02, title, ha="center", va="top",
            fontsize=8, color=title_color, fontweight="bold", zorder=7)


# ── Page 1: Title & Goal Philosophy ──────────────────────────────────────────

def page_title(pdf):
    fig, ax = new_page(pdf)

    # hero box
    box(ax, 1.5, 5.2, 14, 4.5, DGRAY, radius=0.3, border_color=ACCENT1)
    ax.text(8.5, 9.0, "ISRAEL RESEARCHER", ha="center", va="center",
            fontsize=36, color=ACCENT1, fontweight="bold")
    ax.text(8.5, 8.2, "AI-Powered TASE Equity Research System", ha="center", va="center",
            fontsize=18, color=WHITE)
    ax.text(8.5, 7.5, "Full Architecture & Workflow Documentation", ha="center", va="center",
            fontsize=13, color=LGRAY)

    # divider
    ax.add_line(Line2D([3, 14], [7.1, 7.1], color=ACCENT2, lw=1))

    # summary stats
    stats = [
        ("7", "Sector Agents"),
        ("3", "Pipeline Phases"),
        ("40+", "Signal Types"),
        ("15 min", "Cycle Time"),
        ("500+", "TASE Stocks\nCovered"),
    ]
    for i, (val, lbl) in enumerate(stats):
        cx = 2.0 + i * 2.7
        box(ax, cx - 0.7, 5.7, 1.4, 1.0, MGRAY, radius=0.12, border_color=ACCENT3)
        ax.text(cx, 6.35, val, ha="center", va="center",
                fontsize=18, color=ACCENT3, fontweight="bold")
        ax.text(cx, 5.85, lbl, ha="center", va="center",
                fontsize=7, color=LGRAY)

    # Goal pills
    goals = [
        (ACCENT2, "Full TASE Universe"),
        (ACCENT1, "Reads Israeli & Global News"),
        (ACCENT3, "Geopolitics-Aware"),
        (ACCENT4, "Low-Volume Stocks Valid"),
        (PURPLE,  "Maya Filings Primary Signal"),
        (ORANGE,  "Catalyst vs Market Cap"),
        (ACCENT2, "Excel Memory Notebook"),
        (ACCENT1, "IPOs from Day 1"),
    ]
    ax.text(8.5, 5.2, "Project Goals", ha="center", va="center",
            fontsize=11, color=WHITE, fontweight="bold")
    cols, rows = 4, 2
    for i, (col, txt) in enumerate(goals):
        r, c = divmod(i, cols)
        gx = 0.8 + c * 4.0
        gy = 4.4 - r * 0.65
        box(ax, gx, gy, 3.5, 0.5, col, text=txt, fontsize=8.5,
            text_color=BG, bold=True, radius=0.12)

    ax.text(8.5, 0.4, "Runs every 15 minutes  •  Telegram alerts  •  Weekly Stock of the Week report",
            ha="center", va="center", fontsize=9, color=LGRAY)

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ── Page 2: High-level 3-Phase Workflow ───────────────────────────────────────

def page_workflow(pdf):
    fig, ax = new_page(pdf)
    hdr(ax, "SYSTEM WORKFLOW — 3 PHASE PIPELINE",
        "Every 15 minutes: Data Collection → Sector Agents → CIO Arbitration → Telegram")

    # Phase boxes
    phases = [
        (ACCENT1, "PHASE 1\nCross-Sector Data\nCollection",
         "Sequential, shared\nPlaywright browser"),
        (ACCENT2, "PHASE 2\nSector Agents\n(7 parallel)",
         "ThreadPoolExecutor\n4 workers"),
        (ACCENT3, "PHASE 3\nCIO Manager\nArbitration",
         "Best pick across\nall sectors"),
        (ACCENT4, "OUTPUT\nTelegram\nAlerts",
         "Quick alert +\nDaily + Weekly"),
    ]
    px = [0.4, 4.5, 9.0, 13.5]
    for i, (col, title, sub) in enumerate(phases):
        box(ax, px[i], 7.6, 3.6, 1.8, col, radius=0.15, text_color=BG)
        ax.text(px[i] + 1.8, 8.5, title, ha="center", va="center",
                fontsize=11, color=BG, fontweight="bold")
        ax.text(px[i] + 1.8, 7.75, sub, ha="center", va="center",
                fontsize=7.5, color=BG)
        if i < 3:
            arrow(ax, px[i] + 3.6, 8.5, px[i+1], 8.5, color=WHITE, lw=2.5)

    # Phase 1 details
    section_box(ax, 0.3, 2.5, 3.8, 4.9, "PHASE 1 — Data Sources", ACCENT1)
    p1_items = [
        (ACCENT1,  "Maya Company Cache (24h TTL)"),
        (ACCENT1,  "Maya Filings — IPO/Earnings/Contract\n/Institutional/Buyback/Spinoff"),
        (ACCENT1,  "Earnings Calendar (10-day window)"),
        (ACCENT1,  "Dual-Listed US Overnight Moves\n(TEVA, NICE, ICL… ≥2% → signal)"),
        (ACCENT1,  "Israeli News RSS\n(Ynet, Walla, Maariv)"),
        (ACCENT1,  "Global Headlines (Yahoo, WSJ)"),
        (ACCENT1,  "Macro: TA-125, SP500, VIX,\nUSD/ILS, NASDAQ, OIL, US10Y"),
        (ACCENT1,  "Sector Rotation Context\n(BULL/NEUTRAL/BEAR labels)"),
    ]
    for i, (col, txt) in enumerate(p1_items):
        gy = 6.2 - i * 0.52
        box(ax, 0.4, gy, 3.6, 0.44, MGRAY, text=txt, fontsize=6.5,
            radius=0.08, border_color=col)

    # Phase 2 details
    section_box(ax, 4.4, 2.5, 4.2, 4.9, "PHASE 2 — 7 Sector Agents", ACCENT2)
    agents = [
        (ACCENT2,  "BanksAgent  (15 tickers)"),
        (ACCENT2,  "TechDefenseAgent  (11 tickers)"),
        (ACCENT2,  "EnergyAgent  (9 tickers)"),
        (ACCENT2,  "PharmaAgent  (5 tickers)"),
        (ACCENT2,  "RealEstateAgent  (14 tickers)"),
        (ACCENT2,  "TelecomConsumerAgent  (8 tickers)"),
        (ACCENT2,  "DiscoveryAgent  (full TASE ~500)"),
    ]
    for i, (col, txt) in enumerate(agents):
        gy = 6.2 - i * 0.52
        box(ax, 4.5, gy, 4.0, 0.44, MGRAY, text=txt, fontsize=7,
            radius=0.08, border_color=col)

    # Phase 3 details
    section_box(ax, 8.9, 2.5, 4.2, 4.9, "PHASE 3 — CIO Arbitration", ACCENT3)
    p3_items = [
        "Receives full portfolio from all 7 agents",
        "CIO rules: no 2 picks same sector\n(unless score > 90)",
        "Prioritise strongest macro tailwind",
        "Balance large-cap + mid/small-cap",
        "Best pick = catalyst + technicals\n+ macro alignment",
        "Outputs: stock_of_the_week,\nrunners_up, week_theme",
        "Dedup: skip already-alerted today",
    ]
    for i, txt in enumerate(p3_items):
        gy = 6.2 - i * 0.52
        box(ax, 9.0, gy, 4.0, 0.44, MGRAY, text=txt, fontsize=6.5,
            radius=0.08, border_color=ACCENT3)

    # Output details
    section_box(ax, 13.3, 2.5, 3.4, 4.9, "OUTPUT", ACCENT4)
    out_items = [
        (ACCENT4,  "Quick Alert\n(every cycle if score > 0)"),
        (ACCENT4,  "Daily Summary\n(after 17:00 Israel time)"),
        (ACCENT4,  "Weekly Report\n(Thursday 17:00)\nStock of the Week"),
        (ACCENT1,  "Excel Memory\nSaved after each cycle"),
    ]
    for i, (col, txt) in enumerate(out_items):
        gy = 6.1 - i * 0.9
        box(ax, 13.4, gy, 3.2, 0.8, MGRAY, text=txt, fontsize=6.5,
            radius=0.08, border_color=col)

    # State persistence banner
    box(ax, 0.3, 0.3, 16.4, 1.8, MGRAY, radius=0.15, border_color=ACCENT2, alpha=0.7)
    ax.text(8.5, 1.7, "STATE PERSISTENCE", ha="center", va="center",
            fontsize=9, color=ACCENT2, fontweight="bold")
    state_items = [
        "israel_researcher_state.json\n(seen_maya_ids, signal_keys,\ncompany_cache, ticker_validation)",
        "stock_memory dict\n(per-ticker fundamentals,\nsignal_history, analyst_notes)",
        "Excel Workbook\nSheet1: Alerts history\nSheet2: Weekly picks\nSheet3: Memory backup",
        "alerted_today\n(daily dedup, restored\nfrom Excel on restart)",
        "tase_universe_cache\n(Yahoo Screener results\n24h TTL, ~500 tickers)",
    ]
    for i, txt in enumerate(state_items):
        cx = 1.9 + i * 3.2
        box(ax, cx - 1.4, 0.35, 2.7, 1.2, DGRAY, text=txt, fontsize=6.2,
            radius=0.1, border_color=ACCENT1)

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ── Page 3: Per-Agent Internal Flow ──────────────────────────────────────────

def page_agent_flow(pdf):
    fig, ax = new_page(pdf)
    hdr(ax, "SECTOR AGENT — INTERNAL 9-STEP FLOW",
        "Each of the 7 sector agents follows this pipeline every cycle")

    steps = [
        (ACCENT1,  "STEP 1\nFilter Pre-fetched\nCross-Sector Signals",
         "Keep only signals for\nthis agent's tickers"),
        (ACCENT2,  "STEP 2\n8-Detector Technical\nScan",
         "volume_spike, price_move,\nbreakout, ma_crossover,\noversold_bounce,\nlow_reversal,\nconsecutive_momentum,\nrelative_strength"),
        (ACCENT3,  "STEP 3\nSector Macro\nSignals",
         "Banks: KBE/XLF, IL10Y\nTech/Defense: LMT, AMAT,\nVIX, shekel\nEnergy: WTI, NG, Brent\nPharma: XBI, IBB\nRE: VNQ, shekel\nTelecom: XLP, IYZ"),
        (ACCENT4,  "STEP 4\nPreliminary\nConvergenceEngine",
         "group_by_ticker()\nbase_score × multiplier\nEarnings gradient +80→+12\n3-category boost ×1.3"),
        (PURPLE,   "STEP 5\nFilter to\nScore > 0",
         "Silent tickers excluded;\nIPO TASE pseudo-tickers\npassed through directly"),
        (ORANGE,   "STEP 6\nWeb News\nEnrichment (top 5)",
         "Google News RSS\n2 queries per ticker\nLLM extracts signals:\nnew_contract, earnings,\nregulatory, partnership…"),
        (ACCENT2,  "STEP 7\nRe-run\nConvergenceEngine",
         "Web news can raise\nscores; re-ranks\ncandidates"),
        (ACCENT1,  "STEP 8\nDeepStockAnalyzer\n(top 8)",
         "RSI-14, MA-20, MA-50\npct_vs_52w_high\nmarket_cap\nrevenue_growth_pct"),
        (ACCENT3,  "STEP 9\nSector LLM\n(score_sector)",
         "Full ranked portfolio\n{ticker, tier, score,\nrationale, key_catalyst}"),
    ]

    total = len(steps)
    cols = 3
    rows = 3
    box_w, box_h = 4.8, 2.4
    start_x = 0.35
    start_y = 6.8
    gap_x = 5.5
    gap_y = 2.65

    positions = []
    for idx in range(total):
        r = idx // cols
        c = idx % cols
        x = start_x + c * gap_x
        y = start_y - r * gap_y
        positions.append((x, y))
        col, title, detail = steps[idx]
        # main box
        box(ax, x, y, box_w, box_h - 0.15, col, radius=0.15, alpha=0.9)
        ax.text(x + box_w / 2, y + box_h - 0.55, title,
                ha="center", va="center", fontsize=9.5, color=BG, fontweight="bold")
        # detail sub-box
        box(ax, x + 0.1, y + 0.1, box_w - 0.2, 1.4, DGRAY, radius=0.08, alpha=0.85)
        ax.text(x + box_w / 2, y + 0.85, detail,
                ha="center", va="center", fontsize=6.5, color=LGRAY)
        # step label chip
        box(ax, x + box_w - 0.95, y + box_h - 0.45, 0.85, 0.32, DGRAY, radius=0.08)
        ax.text(x + box_w - 0.52, y + box_h - 0.28, f"#{idx+1}",
                ha="center", va="center", fontsize=7, color=WHITE, fontweight="bold")

    # arrows — row by row, then down
    for idx in range(total - 1):
        r = idx // cols
        c = idx % cols
        x, y = positions[idx]
        nx, ny = positions[idx + 1]
        if c < cols - 1:
            # horizontal arrow to next in row
            arrow(ax, x + box_w, y + (box_h - 0.15) / 2,
                  nx, ny + (box_h - 0.15) / 2, color=WHITE, lw=2)
        else:
            # down to next row (go to leftmost in next row)
            # draw a down then left arrow
            mid_y = y - 0.25
            ax.annotate("", xy=(nx + box_w, mid_y),
                        xytext=(x + box_w, y),
                        arrowprops=dict(arrowstyle="-", color=LGRAY, lw=1.5,
                                        connectionstyle="arc3,rad=0"))
            ax.annotate("", xy=(nx + box_w, ny + (box_h - 0.15)),
                        xytext=(nx + box_w, mid_y),
                        arrowprops=dict(arrowstyle="->", color=WHITE, lw=2))

    # bottom note
    box(ax, 0.3, 0.15, 16.4, 0.85, MGRAY, radius=0.12, border_color=ACCENT2, alpha=0.7)
    ax.text(8.5, 0.58, "DiscoveryAgent OVERRIDE: Step 1 _filter_signals() injects maya_ipo/maya_spinoff directly (no .TA ticker needed)   "
            "•   Memory injected into Step 9 LLM call as compact context string",
            ha="center", va="center", fontsize=7.5, color=LGRAY)

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ── Page 4: Code Architecture ─────────────────────────────────────────────────

def page_architecture(pdf):
    fig, ax = new_page(pdf)
    hdr(ax, "CODE ARCHITECTURE — FILE MAP",
        "Package: israel_researcher/   |   Entry: python -m israel_researcher")

    # Entry point
    box(ax, 6.5, 8.8, 4.0, 0.8, ACCENT1, text="researcher.py\nrun_research_cycle() + main() loop",
        fontsize=8, text_color=BG, bold=True, radius=0.12)

    # Manager
    box(ax, 6.0, 7.5, 5.0, 0.85, ACCENT3,
        text="agents/manager.py — ResearchManager\n_run(), _gather_cross_sector(), _arbitrate()",
        fontsize=8, text_color=BG, bold=True, radius=0.12)
    arrow(ax, 8.5, 8.8, 8.5, 8.35, color=WHITE, lw=2)

    # Agents row
    agents_defs = [
        ("agents/banks.py\nBanksAgent\n15 tickers", ACCENT2, 0.3),
        ("agents/tech_defense.py\nTechDefenseAgent\n11 tickers", ACCENT2, 3.0),
        ("agents/energy.py\nEnergyAgent\n9 tickers", ACCENT2, 5.7),
        ("agents/pharma.py\nPharmaAgent\n5 tickers", ACCENT2, 8.4),
        ("agents/real_estate.py\nRealEstateAgent\n14 tickers", ACCENT2, 11.1),
        ("agents/telecom\n_consumer.py\n8 tickers", ACCENT2, 13.8),
        ("agents/discovery.py\nDiscoveryAgent\n~500 tickers", ACCENT4, 13.8),
    ]
    # draw 6 agents side by side in a row
    n_agents = 6
    for i in range(n_agents):
        ax_pos = 0.25 + i * 2.7
        txt, col, _ = agents_defs[i]
        box(ax, ax_pos, 5.6, 2.4, 1.0, col, text=txt, fontsize=6, text_color=BG,
            bold=False, radius=0.1)
        arrow(ax, 8.5, 7.5, ax_pos + 1.2, 6.6, color=LGRAY, lw=1)

    # Discovery separately at right
    box(ax, 14.2, 5.6, 2.5, 1.0, ACCENT4,
        text="agents/discovery.py\nDiscoveryAgent\n~500 tickers TASE", fontsize=6,
        text_color=BG, bold=False, radius=0.1)
    arrow(ax, 8.5, 7.5, 15.45, 6.6, color=LGRAY, lw=1)

    # base.py
    box(ax, 6.5, 5.6, 3.8, 1.0, MGRAY,
        text="agents/base.py — SectorAgent\nrun(), _fetch_web_news(), _filter_signals()\n_build_prompt(), _run_llm()",
        fontsize=6.5, text_color=LGRAY, radius=0.1, border_color=ACCENT2)
    ax.text(8.4, 5.3, "all agents inherit from ↑", ha="center", fontsize=7, color=LGRAY)

    # Sources column
    section_box(ax, 0.2, 2.1, 4.8, 3.0, "sources/", ACCENT1)
    srcs = [
        ("sources/maya.py\nMayaMonitor, MayaFilingExtractor\nEarningsCalendar", ACCENT1),
        ("sources/market.py\nMarketAnomalyDetector, SectorAnalyzer\nDeepStockAnalyzer, DynamicUniverseBuilder\nDualListedMonitor, MacroContext", ACCENT1),
        ("sources/news_monitor.py\nIsraeliNewsMonitor (RSS + name match)", ACCENT1),
        ("sources/web_news.py\nWebNewsSearcher (Google News RSS)", ACCENT1),
    ]
    for i, (txt, col) in enumerate(srcs):
        box(ax, 0.3, 4.35 - i * 0.65, 4.6, 0.58, MGRAY, text=txt,
            fontsize=6, radius=0.08, border_color=col)

    # Analysis column
    section_box(ax, 5.3, 2.1, 4.8, 3.0, "analysis/", ACCENT3)
    anlys = [
        ("analysis/enricher.py\nSignalEnricher\nkeyword → signal_type upgrade", ACCENT3),
        ("analysis/convergence.py\nConvergenceEngine (scoring+multipliers)\nWeeklyAccumulator", ACCENT3),
        ("analysis/llm.py\nLLMAnalyst: score_sector()\narbitrate(), extract_web_news_signals()", ACCENT3),
        ("analysis/memory.py\nStockMemoryManager\nfundamentals, signal_history, notes", ACCENT3),
        ("analysis/excel_memory.py\nExcelMemoryStore\nread/write/restore from Excel backup", ACCENT3),
    ]
    for i, (txt, col) in enumerate(anlys):
        box(ax, 5.4, 4.5 - i * 0.58, 4.6, 0.51, MGRAY, text=txt,
            fontsize=6, radius=0.08, border_color=col)

    # Config / Models column
    section_box(ax, 10.4, 2.1, 3.2, 3.0, "config + models", ACCENT2)
    cfgs = [
        ("config.py\nBOT_TOKEN, OPENAI_KEY\nSECTOR_TICKERS\nMACRO_TICKERS\nThresholds", ACCENT2),
        ("models.py\nSignal dataclass\nload_state() / save_state()\nRefresh company cache", ACCENT2),
        ("alerts.py\nTelegramReporter\nquick_alert()\ndaily_summary()\nweekly_report()", ACCENT4),
    ]
    for i, (txt, col) in enumerate(cfgs):
        box(ax, 10.5, 4.35 - i * 0.82, 3.0, 0.75, MGRAY, text=txt,
            fontsize=6, radius=0.08, border_color=col)

    # External row
    section_box(ax, 13.8, 2.1, 3.0, 3.0, "External / Data", LGRAY)
    exts = [
        ("yfinance\nYahoo Finance prices\nScreener, Search", LGRAY),
        ("OpenAI GPT\ngpt-4o-mini LLM calls\nall analyst prompts", LGRAY),
        ("Playwright\nHeadless Chromium\nMaya WAF bypass", LGRAY),
        ("Telegram Bot API\nalerts + reports", LGRAY),
    ]
    for i, (txt, col) in enumerate(exts):
        box(ax, 13.9, 4.35 - i * 0.65, 2.8, 0.58, DGRAY, text=txt,
            fontsize=5.8, radius=0.08, border_color=col)

    # State box at bottom
    box(ax, 0.2, 0.2, 16.6, 1.6, MGRAY, radius=0.15, border_color=ACCENT2, alpha=0.7)
    ax.text(8.5, 1.5, "STATE & PERSISTENCE", ha="center", fontsize=9,
            color=ACCENT2, fontweight="bold")
    state_cols = [
        ("israel_researcher_state.json\nPrimary state: seen IDs,\ncompany cache, validation cache", ACCENT1),
        ("stock_memory (in state)\nPer-ticker: fundamentals,\nsignal_history, analyst_notes", ACCENT3),
        ("israel_researcher_memory.xlsx\nSheet1: Alerts  Sheet2: Picks\nSheet3: Memory backup", ACCENT2),
        ("atyr_state.json\nmulti_biotech_state.json\nseen.json (news dedup)", LGRAY),
    ]
    for i, (txt, col) in enumerate(state_cols):
        box(ax, 0.4 + i * 4.1, 0.3, 3.8, 1.1, DGRAY, text=txt, fontsize=6.5,
            radius=0.1, border_color=col)

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ── Page 5: Signal Types & Scoring ───────────────────────────────────────────

def page_signals(pdf):
    fig, ax = new_page(pdf)
    hdr(ax, "SIGNAL TYPES, BASE SCORES & CONVERGENCE MULTIPLIERS",
        "ConvergenceEngine — final_score = base_score × best_multiplier  (+earnings_gradient  ×3-category boost)")

    # Signal types table (left)
    section_box(ax, 0.2, 1.0, 7.5, 8.7, "Signal Types — Base Scores", ACCENT1)
    signals_data = [
        # (signal_type, source, base_score, color)
        ("maya_ipo",             "Maya filing",      50, ACCENT4),
        ("maya_contract",        "Maya filing",      45, ACCENT4),
        ("new_contract",         "Web news / LLM",   45, ACCENT3),
        ("regulatory_approval",  "Web news / LLM",   42, ACCENT3),
        ("maya_institutional",   "Maya filing",      40, ACCENT1),
        ("institutional_investor","Web news / LLM",  40, ACCENT1),
        ("maya_earnings",        "Maya filing",      38, ACCENT2),
        ("ipo (web)",            "Web news / LLM",   38, ORANGE),
        ("breakout",             "Technical scan",   35, ACCENT2),
        ("dual_listed_move",     "US overnight",     35, ACCENT2),
        ("earnings (web)",       "Web news / LLM",   35, ACCENT2),
        ("maya_buyback",         "Maya filing",      32, ACCENT1),
        ("earnings_calendar",    "TASE corp actions",30, ACCENT3),
        ("volume_spike",         "Technical scan",   28, LGRAY),
        ("relative_strength",    "Technical scan",   26, LGRAY),
        ("price_move",           "Technical scan",   25, LGRAY),
        ("partnership",          "Web news / LLM",   25, ORANGE),
        ("ma_crossover",         "Technical scan",   22, LGRAY),
        ("consecutive_momentum", "Technical scan",   20, LGRAY),
        ("oversold_bounce",      "Technical scan",   18, LGRAY),
        ("low_reversal",         "Technical scan",   16, LGRAY),
        ("israeli_news",         "RSS feeds",        15, ACCENT2),
        ("geopolitical",         "Web news / LLM",   15, ACCENT4),
        ("general_news",         "Web news / LLM",   10, LGRAY),
    ]
    headers = ["Signal Type", "Source", "Base"]
    col_x = [0.35, 3.5, 6.5]
    row_h = 0.34
    # header row
    for j, (htext, cx) in enumerate(zip(headers, col_x)):
        box(ax, cx, 8.95, 2.8 if j < 2 else 0.9, 0.32, ACCENT1,
            text=htext, fontsize=7.5, text_color=BG, bold=True, radius=0.06)
    for i, (stype, src, score, col) in enumerate(signals_data):
        gy = 8.55 - i * row_h
        box(ax, 0.35, gy, 3.0, row_h - 0.03, col, text=stype, fontsize=6.2,
            text_color=BG if col != LGRAY else BG, bold=True, radius=0.05)
        ax.text(3.52, gy + (row_h - 0.03) / 2, src, va="center",
                fontsize=5.8, color=LGRAY)
        # score bar
        bar_max = 1.2
        bar_w = bar_max * score / 50
        bar_col = ACCENT3 if score >= 40 else (ACCENT2 if score >= 25 else LGRAY)
        box(ax, 6.5, gy + 0.04, bar_w, row_h - 0.1, bar_col, radius=0.04, alpha=0.85)
        ax.text(6.55 + bar_w + 0.05, gy + (row_h - 0.03) / 2, str(score),
                va="center", fontsize=6, color=WHITE, fontweight="bold")

    # Convergence multipliers (right)
    section_box(ax, 8.0, 5.0, 8.8, 4.7, "Top Convergence Multipliers", ACCENT3)
    multipliers = [
        ("earnings_calendar + volume_spike", "2.5×"),
        ("low_reversal + earnings_calendar",  "2.4×"),
        ("oversold_bounce + earnings_calendar","2.3×"),
        ("earnings (web) + volume_spike",     "2.3×"),
        ("relative_strength + earnings_cal.", "2.2×"),
        ("breakout + earnings_calendar",      "2.1×"),
        ("ma_crossover + earnings_calendar",  "2.0×"),
        ("dual_listed + earnings_calendar",   "2.0×"),
        ("maya_ipo + volume_spike",           "1.9×"),
        ("new_contract + volume_spike",       "1.8×"),
        ("institutional + price_move",        "1.7×"),
        ("regulatory + volume_spike",         "1.6×"),
    ]
    for i, (pair, mult) in enumerate(multipliers):
        gy = 9.0 - i * 0.37
        box(ax, 8.1, gy, 6.8, 0.32, MGRAY, text=pair, fontsize=6.2,
            radius=0.06, border_color=ACCENT3)
        box(ax, 15.0, gy, 1.6, 0.32, ACCENT3, text=mult, fontsize=7.5,
            text_color=BG, bold=True, radius=0.06)

    # Scoring rules (bottom right)
    section_box(ax, 8.0, 1.0, 8.8, 3.7, "Scoring Rules & Tier Calibration", ACCENT2)
    rules = [
        (ACCENT3, "Earnings Gradient (dte = days to earnings):",
         "dte=0→+80   dte=1→+70   dte=2→+60   dte=3→+45   dte≤7→+25   dte≤14→+12"),
        (ACCENT2, "3-Category Boost:",
         "If signals from 3+ independent categories → final_score ×1.3"),
        (ACCENT1, "Score Tier Mapping:",
         "≥80=STRONG BUY    60-79=BUY    45-59=WATCH    <45=MONITOR"),
        (ACCENT4, "Deal Materiality (vs Market Cap):",
         "deal_size > 10% mktCap = transformative    < 1% mktCap = immaterial"),
        (LGRAY,   "Low-Volume TASE stocks:",
         "<100K shares/day is normal. Volume spike still actionable. Micro-cap needs hard catalyst for score > 65"),
        (ACCENT3, "IPO Stocks (TASE pseudo-ticker):",
         "Score on IPO filing catalyst + web news. No technicals available yet — skip technical steps."),
    ]
    for i, (col, title, detail) in enumerate(rules):
        gy = 4.1 - i * 0.52
        box(ax, 8.1, gy, 8.6, 0.22, col, text=title, fontsize=6.5,
            text_color=BG, bold=True, radius=0.05)
        ax.text(8.15, gy - 0.13, detail, fontsize=5.8, color=LGRAY, va="top")

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ── Page 6: Memory System ─────────────────────────────────────────────────────

def page_memory(pdf):
    fig, ax = new_page(pdf)
    hdr(ax, "MEMORY SYSTEM — PER-TICKER KNOWLEDGE BASE",
        "StockMemoryManager accumulates knowledge across cycles — LLM gets richer context each run")

    # Central memory store
    box(ax, 5.5, 5.8, 6.0, 2.8, DGRAY, radius=0.2, border_color=ACCENT3,
        text="", alpha=0.9)
    ax.text(8.5, 8.25, "StockMemoryManager", ha="center", fontsize=12,
            color=ACCENT3, fontweight="bold")
    ax.text(8.5, 7.9, "state[\"stock_memory\"][ticker]", ha="center",
            fontsize=8.5, color=LGRAY)

    memory_fields = [
        ("fundamentals", "RSI-14, MA-20/50, pct_vs_52w, market_cap, rev_growth  (7-day TTL)"),
        ("signal_history", "Last 10 cycles: {date, signal_types, final_score}"),
        ("analyst_notes", "Current LLM analysis (≤300 chars), updated each appearance"),
        ("prior_analyst_notes", "Previous day's notes [date] — enables trend recognition"),
        ("recent_news", "Top-3 headlines from web news (150 chars max)"),
        ("consecutive_active", "# of cycles in a row with active signals"),
    ]
    for i, (field, desc) in enumerate(memory_fields):
        gy = 7.6 - i * 0.32
        ax.text(5.65, gy, f"• {field}:", fontsize=6.5, color=ACCENT2,
                fontweight="bold", va="center")
        ax.text(8.0, gy, desc, fontsize=6, color=LGRAY, va="center")

    # Writers → Memory
    writers = [
        (1.5, 8.5, ACCENT2, "DeepStockAnalyzer\n(Step 8)\nupdate_fundamentals()"),
        (1.5, 6.8, ACCENT1, "ConvergenceEngine\n(Steps 4/7)\nupdate_signal_history()"),
        (1.5, 5.2, ACCENT3, "LLMAnalyst\n(Step 9)\nupdate_analyst_notes()"),
        (1.5, 3.6, ACCENT4, "WebNewsSearcher\n(Step 6)\nupdate_news_summary()"),
    ]
    for wx, wy, col, txt in writers:
        box(ax, wx - 1.2, wy - 0.45, 2.4, 0.9, col, text=txt, fontsize=6.5,
            text_color=BG, bold=False, radius=0.1)
        arrow(ax, wx + 1.2, wy, 5.5, 7.2, color=col, lw=1.5)

    # Memory → LLM Context
    box(ax, 11.8, 6.8, 3.5, 1.6, ACCENT1, radius=0.15,
        text="LLM Sector Prompt\n(Step 9 input)", fontsize=9, text_color=BG, bold=True)
    arrow(ax, 11.5, 7.2, 11.8, 7.2, color=ACCENT1, lw=2.5)

    # Context string breakdown
    section_box(ax, 11.5, 2.5, 5.0, 4.0, "Memory Context String (injected)", ACCENT1)
    ctx_parts = [
        ("Latest analysis:", "Current analyst_notes (200 chars)", ACCENT3),
        ("Prior:",           "prior_analyst_notes (120 chars, dated)", ACCENT2),
        ("History:",         "N cycles, consecutive_active, recent signals, best_score", ACCENT1),
        ("Recent news:",     "Top headlines (150 chars)", ACCENT4),
        ("Technicals:",      "RSI, MA_trend, vs52wHigh%, revGrowth%, mktCap", LGRAY),
    ]
    for i, (key, val, col) in enumerate(ctx_parts):
        gy = 5.8 - i * 0.6
        box(ax, 11.6, gy, 1.5, 0.48, col, text=key, fontsize=6.5,
            text_color=BG, bold=True, radius=0.07)
        ax.text(13.2, gy + 0.22, val, fontsize=6, color=LGRAY, va="center")

    # Excel backup flow
    section_box(ax, 0.2, 1.0, 11.0, 2.8, "Excel Memory Backup — Two-Layer Persistence", ACCENT2)
    excel_items = [
        (ACCENT2, "Sheet 1: Alerts\nAll tickers alerted with date/score\nalerted_today restored from here on restart"),
        (ACCENT3, "Sheet 2: Weekly Picks\nStock of the week history\nscore, rationale, key_catalyst"),
        (ACCENT1, "Sheet 3: Memory Backup\nAll StockMemory entries serialised\nRestored if state.json wiped"),
        (ACCENT4, "Prune Logic\n• Signal history: keep last 10 cycles\n• Memory entries: prune after 30 days inactive\n• Validation cache: valid=30d, invalid=7d TTL"),
    ]
    for i, (col, txt) in enumerate(excel_items):
        box(ax, 0.3 + i * 2.7, 1.1, 2.5, 2.4, MGRAY, text=txt, fontsize=6.5,
            radius=0.1, border_color=col)

    # restart persistence callout
    box(ax, 11.5, 0.2, 5.2, 1.5, MGRAY, radius=0.12, border_color=ACCENT4)
    ax.text(14.1, 1.35, "RESTART PERSISTENCE", ha="center", fontsize=8.5,
            color=ACCENT4, fontweight="bold")
    ax.text(14.1, 0.95, "On code restart:\n1. load_state() reads state.json\n"
            "2. If stock_memory empty → ExcelMemoryStore.restore_to_state()\n"
            "3. alerted_today restored from Sheet 1 by current date",
            ha="center", va="center", fontsize=6.5, color=LGRAY)

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ── Page 7: LLM Prompt Framework ──────────────────────────────────────────────

def page_llm(pdf):
    fig, ax = new_page(pdf)
    hdr(ax, "LLM ANALYST PROMPTS — WHAT THE AI KNOWS",
        "3 specialized system prompts injected with macro + memory + geopolitical context every cycle")

    prompts = [
        (ACCENT2, "QUICK SYSTEM\n_QUICK_SYSTEM",
         "Used for: quick alert scoring\nall signal types, tiers",
         [
             "Signal scoring tiers: STRONG BUY / BUY / WATCH / MONITOR",
             "Israeli Geopolitical Framework:",
             "  • Security escalation → defense sector (ELBIT, RAFAEL), retail ↓",
             "  • BoI rate → track US10Y proxy; rate cut = banks, real estate ↑",
             "  • Shekel depreciation → exporters (tech, defense) ↑, importers ↓",
             "  • Oil/gas move → energy stocks (Delek, NewMed)",
             "  • Political instability → VIX + safe-haven bias",
             "Small-Cap & Low-Volume TASE Rules:",
             "  • <100K shares/day is normal — spike still actionable",
             "  • Micro-cap + hard catalyst → score up to 65",
             "  • deal > 10% mktCap = transformative",
             "  • TASE IPOs (pseudo-ticker) → score on filing + web news",
         ]),
        (ACCENT3, "SECTOR BASE SYSTEM\n_SECTOR_BASE_SYSTEM",
         "Used for: each sector agent Step 9\nPer-sector domain knowledge",
         [
             "Sector-specific domain expertise injected per agent",
             "OIL/USD_ILS/US10Y sector impact rules",
             "Macro context string (TA-125, VIX, USD/ILS, SP500…)",
             "Sector rotation labels (BULL+/BULL/NEUTRAL/BEAR/BEAR-)",
             "Per-ticker memory context (analyst_notes, history, news)",
             "Micro-cap hard catalyst threshold (score > 65 requires it)",
             "Deal materiality relative to market cap",
             "IPO handling: score TASE pseudo-tickers on catalyst",
             "Output: ranked portfolio [{tier, score, rationale, catalyst}]",
         ]),
        (ACCENT1, "MANAGER / CIO SYSTEM\n_MANAGER_SYSTEM",
         "Used for: Phase 3 cross-sector arbitration\nStock of the Week selection",
         [
             "Receives full portfolios from all 7 agents",
             "CIO Rules:",
             "  • No 2 picks from same sector unless score > 90",
             "  • Prioritise sector with strongest macro tailwind",
             "  • Balance large-cap + at least one mid/small-cap",
             "  • Best pick = hard catalyst + confirming technicals + macro",
             "Israeli Geopolitical & Political Context:",
             "  • VIX spike + USD/ILS rise → defense before retail",
             "  • US10Y rising → careful with banks and REITs",
             "  • Oil rising → NewMed, Delek; falling → airlines",
             "  • USD/ILS weak → exporters (NICE, ELBIT) outperform",
             "Output: stock_of_the_week + runners_up + macro_context",
         ]),
    ]

    col_w = 5.3
    for i, (col, title, sub, items) in enumerate(prompts):
        cx = 0.35 + i * 5.5
        box(ax, cx, 8.0, col_w, 1.5, col, radius=0.15, text_color=BG)
        ax.text(cx + col_w / 2, 9.12, title, ha="center", fontsize=8.5,
                color=BG, fontweight="bold")
        ax.text(cx + col_w / 2, 8.15, sub, ha="center", fontsize=6.5, color=BG)

        box(ax, cx, 1.0, col_w, 6.8, DGRAY, radius=0.12, border_color=col, alpha=0.6)
        for j, item in enumerate(items):
            gy = 7.4 - j * 0.55
            indent = item.startswith("  ")
            icon = "  ›" if indent else "•"
            clr = LGRAY if indent else WHITE
            ax.text(cx + 0.25, gy, f"{icon} {item.strip()}",
                    fontsize=6 if indent else 6.5, color=clr, va="top")

    # Web news signal types box
    box(ax, 0.2, 0.15, 16.6, 0.72, MGRAY, radius=0.1, border_color=ACCENT4)
    ax.text(8.5, 0.6, "Web News LLM — extract_web_news_signals() outputs these types:",
            ha="center", fontsize=8, color=ACCENT4, fontweight="bold")
    web_types = "new_contract • earnings • institutional_investor • regulatory_approval • partnership • buyback • dividend • ipo • geopolitical • general_news"
    ax.text(8.5, 0.3, web_types, ha="center", fontsize=7, color=LGRAY)

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ── Page 8: Discovery Agent Deep Dive ────────────────────────────────────────

def page_discovery(pdf):
    fig, ax = new_page(pdf)
    hdr(ax, "DISCOVERY AGENT — FULL TASE UNIVERSE",
        "DiscoveryAgent covers all ~500 TASE stocks beyond the 6 sector lists")

    # Flow
    flow_steps = [
        (ACCENT1, "Yahoo Finance\nScreener\nexchange=TLV",
         "~500 TLV-listed\nequities returned\nPaginates 250/page"),
        (ACCENT3, "Cached 24h\ntase_universe_cache",
         "Avoids rate limiting;\nrefreshed once/day;\nstored in state JSON"),
        (ACCENT2, "Exclude already\ncovered tickers",
         "Remove tickers in\nany sector agent list;\nfind truly new ones"),
        (ACCENT4, "Validate with\nyfinance fast_info",
         "fast_info.last_price > 0\nMax 50 new per cycle;\npriority: today's Maya"),
        (LGRAY,   "validation_cache\n(30d / 7d TTL)",
         "valid=30d, invalid=7d;\ncleans TASE{id}.TA\npseudo-ticker pollution"),
        (ACCENT1, "Technical Scan\n8 detectors",
         "Same anomaly detectors\nas sector agents;\nno sector macro"),
    ]
    bx = [0.35, 3.2, 6.05, 8.9, 11.75, 14.6]
    for i, (col, title, detail) in enumerate(flow_steps):
        box(ax, bx[i], 7.6, 2.5, 1.6, col, radius=0.12, text_color=BG)
        ax.text(bx[i] + 1.25, 8.95, title, ha="center", fontsize=7.5,
                color=BG, fontweight="bold")
        ax.text(bx[i] + 1.25, 7.8, detail, ha="center", fontsize=6, color=BG)
        if i < len(flow_steps) - 1:
            arrow(ax, bx[i] + 2.5, 8.4, bx[i+1], 8.4, color=WHITE, lw=2)

    # IPO handling section
    section_box(ax, 0.2, 3.5, 7.8, 3.8, "IPO Signal Direct Injection", ACCENT4)
    box(ax, 0.3, 6.4, 7.6, 0.6, ACCENT4,
        text="Problem: maya_ipo signals use TASE{id} pseudo-ticker → no real .TA symbol",
        fontsize=7.5, text_color=BG, bold=True, radius=0.08)

    ipo_steps = [
        ("MayaMonitor detects\nIPO filing (PDF)",
         "signal: ticker='TASE{id}'\nticker_yf=''\nsignal_type='maya_ipo'", ACCENT4),
        ("base._filter_signals()\nblocks TASE tickers\n(not in validated set)",
         "normal sector agents\nNEVER see IPO signals", ACCENT4),
        ("DiscoveryAgent\n_filter_signals() OVERRIDE",
         "passes maya_ipo AND\nmaya_spinoff directly\nwithout YF validation", ACCENT2),
        ("Web news step\n_fetch_web_news()",
         "Uses company_name as\nquery (not ticker)\nfinds news despite no .TA", ACCENT2),
        ("LLM scores stock\nwith TASE pseudo-ticker",
         "Score = IPO catalyst\n+ web news found\nNo technicals possible", ACCENT3),
    ]
    for i, (step, detail, col) in enumerate(ipo_steps):
        sx = 0.4 + i * 1.5
        box(ax, sx, 4.55, 1.35, 1.65, MGRAY, radius=0.1, border_color=col)
        ax.text(sx + 0.675, 5.9, step, ha="center", fontsize=5.8,
                color=col, fontweight="bold", va="center")
        ax.text(sx + 0.675, 4.9, detail, ha="center", fontsize=5.2,
                color=LGRAY, va="center")
        if i < len(ipo_steps) - 1:
            arrow(ax, sx + 1.35, 5.35, sx + 1.5, 5.35, color=col, lw=1.5)

    ax.text(4.1, 4.2, "_IPO_SIGNAL_TYPES = {\"maya_ipo\", \"maya_spinoff\"}",
            ha="center", fontsize=7.5, color=ACCENT2, fontfamily="monospace")

    # Priority symbols
    section_box(ax, 8.2, 3.5, 8.6, 3.8, "Priority Symbol Resolution", ACCENT2)
    priority_txt = [
        "• manager.py builds priority set from today's Maya signals:",
        "  priority = {s.ticker for s in pre_fetched if not s.ticker.startswith('TASE')}",
        "",
        "• DynamicUniverseBuilder normalises to .TA format:",
        "  TEVA → TEVA.TA   (bare symbol from Maya institutional)",
        "",
        "• Priority tickers validated FIRST in each cycle",
        "  (before general TASE screener tickers)",
        "",
        "• Max 50 new validations per cycle to avoid rate-limiting",
        "  → full TASE universe (~500) populates over ~10 cycles",
        "",
        "• _clean_pseudo_ticker_pollution() strips TASE\\d+.TA",
        "  from validation cache on every DynamicUniverseBuilder init",
    ]
    for i, line in enumerate(priority_txt):
        color = ACCENT2 if line.startswith("•") else (ACCENT3 if "TEVA" in line or "'TASE'" in line else LGRAY)
        ax.text(8.35, 6.95 - i * 0.28, line, fontsize=6.5, color=color,
                fontfamily="monospace" if line.strip().startswith("priority") or "TEVA" in line else "sans-serif")

    # Bottom note about convergence limitation
    box(ax, 0.2, 0.2, 16.6, 3.1, MGRAY, radius=0.15, border_color=ACCENT4, alpha=0.6)
    ax.text(8.5, 3.0, "KNOWN LIMITATION — TICKER IDENTITY GAP", ha="center",
            fontsize=9, color=ACCENT4, fontweight="bold")
    gap_items = [
        "Maya filings → TASE{companyId}  pseudo-tickers (no real symbol from Maya API)",
        "yfinance technicals → real .TA symbols   (e.g. ELBIT.TA, TEVA.TA)",
        "These CANNOT converge — a company's Maya IPO filing and its volume spike are DIFFERENT tickers in ConvergenceEngine",
        "Solution paths: Web news (LLM bridges company name → signal)  |  DiscoveryAgent validates .TA once stock starts trading",
        "Result: sector agents rely on technicals + web news for real-ticker coverage; Maya signals boost score via TASE pseudo-ticker separately",
    ]
    for i, txt in enumerate(gap_items):
        col = ACCENT4 if i < 2 else (ACCENT3 if i == 2 else LGRAY)
        ax.text(0.5, 2.7 - i * 0.55, f"{'→' if i >= 3 else '•'} {txt}",
                fontsize=7, color=col)

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ── Page 9: Future Improvements ───────────────────────────────────────────────

def page_improvements(pdf):
    fig, ax = new_page(pdf)
    hdr(ax, "POTENTIAL FUTURE IMPROVEMENTS",
        "Areas where additional logic can be added to make the researcher smarter")

    categories = [
        (ACCENT1, "DATA SOURCES", [
            "Options flow data (unusual calls/puts on TASE options) → alpha signal",
            "SEC/EDGAR for dual-listed companies (TEVA, NICE) — US filings often precede TASE moves",
            "Bank of Israel press releases (MPC decisions, FX interventions)",
            "IIA (Israeli Innovation Authority) grant announcements — tech catalysts",
            "Ministry of Defense procurement database — defense sector",
            "Institutional short interest changes (quarterly TASE disclosures)",
        ]),
        (ACCENT2, "SIGNAL PROCESSING", [
            "Merge TASE{id} ↔ real .TA ticker via company name fuzzy match → true convergence",
            "Insider trading filings (Form 4 equivalent in Israel) as institutional signal",
            "Dividend yield relative to sector average — yield compression signal",
            "Options implied volatility spike before earnings → elevated uncertainty signal",
            "Cross-asset correlation: USD/ILS vs tech sector performance auto-detected",
            "Identify when a stock is approaching MSCI rebalancing inclusion threshold",
        ]),
        (ACCENT3, "LLM / AI", [
            "Per-sector fine-tuned prompts with historical example good/bad picks",
            "Post-mortem analysis: after 1 week, did the pick actually move? Feed back into scoring",
            "Multi-LLM consensus: run GPT-4o and Claude in parallel, arbitrate disagreements",
            "Sentiment tracking: track LLM confidence over consecutive cycles for a stock",
            "Automatic stop-loss/take-profit targets from LLM based on technicals",
            "Natural language query interface: 'What's happening in energy sector today?'",
        ]),
        (ACCENT4, "ALERTS & REPORTING", [
            "Portfolio tracker: compare alerted stocks to actual TASE closing prices next day",
            "Weekly performance report: how did last week's picks do? P&L summary",
            "Sector heat map image generated and sent to Telegram",
            "Interactive Telegram bot: reply to alert with /details {ticker} for deep analysis",
            "Email digest option alongside Telegram",
            "Dashboard web UI showing all current signals and scores in real time",
        ]),
        (PURPLE, "INFRASTRUCTURE", [
            "Move to async architecture (asyncio + aiohttp) — all HTTP calls currently blocking",
            "Redis cache for ticker validation — survives process restarts without JSON read",
            "Containerize with Docker — reproducible environment, easy deployment",
            "CI/CD pipeline with pytest: unit tests for signal scoring, convergence math",
            "Rate limit manager: exponential backoff for yfinance / Google News 429s",
            "Separate background process for Maya scraping (no shared Playwright session limit)",
        ]),
        (ORANGE, "MARKET MICROSTRUCTURE", [
            "TASE tick data via TASE DataFlow API (official TASE streaming) — real-time",
            "Bid-ask spread monitoring: widening spread before news = informed trading",
            "Market maker activity: identify when prop desks are accumulating",
            "ETF flow tracking: Migdal/Psagot/IBI ETF rebalances drive large volumes",
            "Dual-listed premium/discount: TEVA ADR vs TEVA.TA divergence → arb signal",
            "Index rebalancing calendar: TA-35/TA-90/TA-125 quarterly rebalancing dates",
        ]),
    ]

    cols = 2
    box_w = 7.8
    box_h = 4.0
    for i, (col, title, items) in enumerate(categories):
        r = i // cols
        c = i % cols
        bx = 0.35 + c * 8.45
        by = 8.6 - r * 4.15
        box(ax, bx, by - box_h + 0.3, box_w, 0.45, col, text=title,
            fontsize=8.5, text_color=BG, bold=True, radius=0.08)
        box(ax, bx, by - box_h - 0.25, box_w, box_h - 0.2, DGRAY,
            radius=0.1, border_color=col, alpha=0.5)
        for j, item in enumerate(items):
            gy = by - 0.55 - j * 0.5
            ax.text(bx + 0.25, gy, f"• {item}", fontsize=6.3, color=LGRAY, va="top")

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ── Page 10: Geopolitical & Macro Framework ───────────────────────────────────

def page_geopolitics(pdf):
    fig, ax = new_page(pdf)
    hdr(ax, "GEOPOLITICAL & MACRO CONTEXT FRAMEWORK",
        "How macro signals map to sector impacts — injected into every LLM call")

    macro_signals = [
        ("USD/ILS\n(ILS=X)", "Shekel Rate", ACCENT3,
         [("↑ (shekel weak)", ACCENT4, ["Exporters UP: NICE, Amdocs, ELBIT, Check Point",
                                         "Importers DOWN: retail, food manufacturers",
                                         "Tourism sector DOWN"]),
          ("↓ (shekel strong)", ACCENT2, ["Importers benefit",
                                           "Tech exporters face margin pressure",
                                           "BoI may hold rates longer"])]),
        ("US10Y\n(^TNX)", "US 10-Year Yield\n(BoI Rate Proxy)", ACCENT1,
         [("Rising yields", ACCENT4, ["Banks: NIM expansion → BUY banks",
                                       "Real Estate: mortgage costs ↑ → headwind",
                                       "BoI likely to follow Fed higher"]),
          ("Falling yields", ACCENT2, ["Real Estate: mortgage relief → BUY REITs",
                                        "Banks: NIM compression → caution",
                                        "Growth stocks: discount rate falls"])]),
        ("OIL\n(CL=F)", "WTI Crude Oil", ORANGE,
         [("Rising oil", ACCENT3, ["Energy: NewMed Energy, Delek Group UP",
                                    "Transport/airlines: cost pressure DOWN",
                                    "Inflation risk → BoI hawkish"]),
          ("Falling oil", ACCENT2, ["Energy sector headwind",
                                     "Airlines, logistics benefit",
                                     "Import bill falls → shekel support"])]),
        ("VIX\n(^VIX)", "Fear Index", ACCENT4,
         [("VIX spike (>25)", ACCENT4, ["Defense: ELBIT, Rafael systems → BUY",
                                         "Retail / consumer: avoid",
                                         "Flight to quality; large-cap over small"]),
          ("VIX low (<15)", ACCENT2, ["Risk-on: small/mid-cap TASE",
                                       "Growth and momentum strategies",
                                       "IPO window opens"])]),
    ]

    for i, (ticker, name, col, scenarios) in enumerate(macro_signals):
        bx = 0.3 + i * 4.2
        # Ticker chip
        box(ax, bx, 8.8, 3.8, 0.8, col, text=f"{ticker}\n{name}",
            fontsize=8, text_color=BG, bold=True, radius=0.12)
        # Scenarios
        for j, (scenario, scol, impacts) in enumerate(scenarios):
            gy = 7.9 - j * 3.3
            box(ax, bx, gy, 3.8, 0.38, scol, text=scenario,
                fontsize=7.5, text_color=BG, bold=True, radius=0.08)
            for k, impact in enumerate(impacts):
                box(ax, bx + 0.05, gy - (k + 1) * 0.54,
                    3.7, 0.48, MGRAY, text=impact, fontsize=6, radius=0.06,
                    border_color=scol, alpha=0.85)

    # Security / Geopolitical section
    section_box(ax, 0.2, 0.2, 16.6, 1.8, "Security Escalation Rules (Israeli Geopolitics)", ACCENT4)
    geo_rules = [
        (ACCENT4,  "Escalation\n(war/terror/\nmissile)", ["ELBIT Systems (ESLT.TA) → BUY",
                                                            "Rafael (private, use ESLT proxy)",
                                                            "Consumer/retail → sell/avoid",
                                                            "Tourism/hotels → avoid"]),
        (ACCENT3,  "Political\nInstability\n(coalition crisis)", ["VIX + USD/ILS likely rising",
                                                                   "Defensive sectors preferred",
                                                                   "Avoid highly leveraged companies",
                                                                   "BoI likely to intervene in FX"]),
        (ACCENT1,  "Government\nTenders &\nDefense Contracts", ["Ministry of Defense announcement → ELBIT/Orbit",
                                                                  "IIA tech grant → small-cap tech",
                                                                  "Infrastructure tender → cement/construction",
                                                                  "Size vs market cap = materiality"]),
        (ACCENT2,  "Sanctions /\nInternational\nRelations", ["Export ban → immediate revenue risk",
                                                              "New market access (UAE, Bahrain deals) → ↑",
                                                              "US-Israel defense MoU → defense sector",
                                                              "Fintech regulation → banks"]),
    ]
    for i, (col, category, items) in enumerate(geo_rules):
        gx = 0.35 + i * 4.1
        box(ax, gx, 1.5, 1.1, 0.42, col, text=category, fontsize=5.5,
            text_color=BG, bold=True, radius=0.06)
        for j, item in enumerate(items):
            ax.text(gx + 1.2, 1.75 - j * 0.38, f"• {item}",
                    fontsize=5.8, color=LGRAY, va="top")

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ── Generate PDF ──────────────────────────────────────────────────────────────

def main():
    print(f"Generating {OUTPUT} ...")
    with PdfPages(OUTPUT) as pdf:
        # Page metadata
        d = pdf.infodict()
        d["Title"]   = "Israel Researcher — Architecture & Workflow Documentation"
        d["Author"]  = "BorsaProject / Brokai"
        d["Subject"] = "TASE Equity Research System — Full Technical Documentation"

        page_title(pdf)          # 1: title + goals
        page_workflow(pdf)       # 2: 3-phase pipeline overview
        page_agent_flow(pdf)     # 3: sector agent 9-step internal flow
        page_architecture(pdf)   # 4: code file map / class diagram
        page_signals(pdf)        # 5: signal types + scoring
        page_memory(pdf)         # 6: memory system
        page_llm(pdf)            # 7: LLM prompts
        page_discovery(pdf)      # 8: discovery agent + IPO handling
        page_geopolitics(pdf)    # 9: macro/geopolitical framework
        page_improvements(pdf)   # 10: future improvements

    print(f"Done -> {OUTPUT}  (10 pages)")


if __name__ == "__main__":
    main()
