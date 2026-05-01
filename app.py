"""
Borkai Web App
Run with:  python -m streamlit run app.py
"""
import streamlit as st
import os
import sys
import json
import re
import threading
from datetime import date, datetime
from pathlib import Path
from dotenv import load_dotenv

# ── Setup ─────────────────────────────────────────────────────────────────────
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_APP_DIR, ".env"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Borkai | Israeli Stock Intelligence",
    page_icon="B",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&family=Karla:wght@300;400;500;600;700&display=swap');

:root {
  --bg:          #080c10;
  --surface:     #0d1117;
  --surface2:    #111820;
  --border:      #1d2433;
  --border2:     #2a3447;
  --text:        #c9d1d9;
  --text-muted:  #57657a;
  --text-dim:    #3d4f61;
  --accent:        #4d9de0;
  --accent-glow:   rgba(77,157,224,0.15);
  --accent-dim:    rgba(77,157,224,0.08);
  --accent-border: rgba(77,157,224,0.30);
  --green:         #39d353;
  --green-bg:      rgba(57,211,83,0.08);
  --green-border:  rgba(57,211,83,0.35);
  --red:           #f85149;
  --red-bg:        rgba(248,81,73,0.08);
  --red-border:    rgba(248,81,73,0.35);
  --amber:         #e3a00a;
  --amber-bg:      rgba(227,160,10,0.08);
  --amber-border:  rgba(227,160,10,0.35);
  --surface3:      #04080d;
  --mono:        'JetBrains Mono', 'Courier New', monospace;
  --condensed:   'Barlow Condensed', sans-serif;
  --body:        'Karla', sans-serif;
}
* { box-sizing: border-box; }
html, body, .stApp { background-color: var(--bg) !important; color: var(--text); font-family: var(--body); }
.main .block-container { padding-top: 0.5rem !important; padding-left: 1.5rem !important; padding-right: 1.5rem !important; max-width: 1440px; }
h1,h2,h3,h4,h5 { font-family: var(--condensed); color: var(--text); letter-spacing: 0.02em; text-transform: uppercase; font-weight: 700; }
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: var(--surface); }
::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 2px; }

/* Hero */
.bk-hero { position:relative; overflow:hidden; background:linear-gradient(180deg,#0a1220 0%,var(--bg) 100%); border-bottom:1px solid var(--border); padding:1.25rem 0 0 0; margin-bottom:0; }
.bk-hero::before { content:''; position:absolute; inset:0; background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(77,157,224,0.018) 2px,rgba(77,157,224,0.018) 4px); pointer-events:none; }
.bk-wordmark { font-family:var(--condensed); font-weight:900; font-size:3.4rem; line-height:1; color:#fff; text-transform:uppercase; display:flex; align-items:baseline; gap:10px; }
.bk-wordmark-accent { color:var(--accent); font-size:2rem; font-weight:600; letter-spacing:0.12em; padding:2px 10px; border:1px solid var(--accent); border-radius:3px; font-family:var(--mono); }
.bk-hero-sub { font-family:var(--mono); font-size:0.68rem; color:var(--text-muted); letter-spacing:0.2em; text-transform:uppercase; margin-top:4px; }
.bk-hero-tags { display:flex; gap:6px; margin-top:8px; flex-wrap:wrap; }
.bk-tag { font-family:var(--mono); font-size:0.64rem; color:var(--text-dim); border:1px solid var(--border); padding:2px 8px; border-radius:2px; letter-spacing:0.1em; text-transform:uppercase; }
.bk-dot-live { display:inline-block; width:6px; height:6px; background:var(--green); border-radius:50%; margin-right:5px; animation:pulse 2.5s ease-in-out infinite; }
@keyframes pulse { 0%,100%{opacity:1;box-shadow:0 0 4px var(--green)} 50%{opacity:.4;box-shadow:none} }
.bk-ticker-strip { background:var(--surface); border-top:1px solid var(--border); border-bottom:1px solid var(--border); padding:5px 0; margin-top:12px; overflow:hidden; font-family:var(--mono); font-size:0.7rem; color:var(--text-muted); letter-spacing:0.05em; white-space:nowrap; }
.bk-ticker-inner { display:inline-flex; gap:36px; animation:tickerScroll 28s linear infinite; }
@keyframes tickerScroll { from{transform:translateX(0)} to{transform:translateX(-50%)} }
.bk-ticker-item { display:inline-flex; gap:8px; align-items:center; }
.bk-up { color:var(--green); }
.bk-dn { color:var(--red); }

/* Tabs */
.stTabs [data-baseweb="tab-list"] { background:transparent !important; border-bottom:1px solid var(--border) !important; gap:0 !important; padding:0 !important; margin-bottom:0 !important; border-radius:0 !important; }
.stTabs [data-baseweb="tab"] { font-family:var(--condensed) !important; font-weight:700 !important; font-size:0.82rem !important; letter-spacing:0.12em !important; text-transform:uppercase !important; color:var(--text-muted) !important; padding:10px 20px !important; border-radius:0 !important; border-bottom:2px solid transparent !important; background:transparent !important; margin-bottom:-1px !important; }
.stTabs [aria-selected="true"] { color:var(--accent) !important; border-bottom:2px solid var(--accent) !important; background:transparent !important; }

/* Cards */
.bk-card { background:var(--surface); border:1px solid var(--border); border-radius:4px; padding:16px 20px; margin:6px 0; }
.bk-card:hover { border-color:var(--border2); }
.bk-card-accent { border-left:2px solid var(--accent); }

/* Terminal */
.bk-terminal { background:#04080d; border:1px solid var(--border); border-radius:4px; padding:16px 20px; font-family:var(--mono); font-size:0.78rem; color:#7fbd9e; line-height:1.8; min-height:100px; }
.bk-terminal-header { display:flex; align-items:center; gap:6px; margin-bottom:12px; padding-bottom:8px; border-bottom:1px solid var(--border); }
.bk-dot { width:8px; height:8px; border-radius:50%; display:inline-block; }
.bk-dot-r { background:#f85149; }
.bk-dot-a { background:#e3a00a; }
.bk-dot-g { background:#39d353; }
.bk-term-title { font-size:0.65rem; color:var(--text-dim); letter-spacing:0.15em; text-transform:uppercase; margin-left:6px; }
.bk-prompt { color:var(--accent); }

/* Verdict */
.bk-verdict { position:relative; border-radius:4px; padding:28px 24px; margin:16px 0; text-align:center; overflow:hidden; }
.bk-verdict::before { content:''; position:absolute; inset:0; background:repeating-linear-gradient(45deg,transparent,transparent 8px,rgba(255,255,255,0.012) 8px,rgba(255,255,255,0.012) 16px); pointer-events:none; }
.bk-v-yes  { background:rgba(57,211,83,0.08);   border:1px solid rgba(57,211,83,0.35); }
.bk-v-no   { background:rgba(248,81,73,0.08);   border:1px solid rgba(248,81,73,0.35); }
.bk-v-cond { background:rgba(227,160,10,0.08);  border:1px solid rgba(227,160,10,0.35); }
.bk-v-label { font-family:var(--condensed); font-weight:900; font-size:1rem; letter-spacing:0.25em; text-transform:uppercase; opacity:.7; margin-bottom:4px; }
.bk-v-rec   { font-family:var(--condensed); font-weight:900; font-size:2.6rem; letter-spacing:0.05em; text-transform:uppercase; line-height:1; }
.bk-v-score { font-family:var(--mono); font-weight:700; font-size:3.5rem; line-height:1; margin:10px 0 4px; }
.bk-v-sub   { font-family:var(--mono); font-size:1rem; opacity:.45; }
.bk-v-detail { font-size:0.85rem; color:var(--text-muted); margin-top:12px; max-width:500px; margin-left:auto; margin-right:auto; line-height:1.5; }
.bk-bar-wrap { background:var(--border); border-radius:1px; height:5px; overflow:hidden; margin:6px 0; }
.bk-bar-fill { height:5px; border-radius:1px; }

/* Badges */
.bk-badge { display:inline-block; font-family:var(--mono); font-size:0.64rem; font-weight:600; letter-spacing:0.08em; padding:2px 8px; border-radius:2px; text-transform:uppercase; }

/* Feed items */
.bk-feed { background:var(--surface); border:1px solid var(--border); border-left:3px solid var(--border2); border-radius:0 4px 4px 0; padding:10px 14px; margin:5px 0; }
.bk-feed:hover { background:var(--surface2); }
.bk-feed-bull { border-left-color:#39d353 !important; }
.bk-feed-bear { border-left-color:#f85149 !important; }

/* Report RTL */
.bk-report { direction:rtl; text-align:right; font-family:var(--body); font-size:0.92rem; line-height:1.75; color:var(--text); }
.bk-report h1,.bk-report h2 { font-family:var(--condensed); text-transform:none; font-size:1.4rem; margin:1.5rem 0 .5rem; color:#e6edf3; letter-spacing:0; }
.bk-report h3 { font-size:1.1rem; color:#c9d1d9; text-transform:none; letter-spacing:0; }
.bk-report table { width:100%; border-collapse:collapse; margin:12px 0; }
.bk-report th { background:var(--surface2); padding:8px 12px; border:1px solid var(--border); font-family:var(--mono); font-size:0.72rem; letter-spacing:0.05em; color:var(--text-muted); text-transform:uppercase; }
.bk-report td { padding:8px 12px; border:1px solid var(--border); font-size:0.88rem; }
.bk-report tr:nth-child(even) { background:var(--surface2); }
.bk-report code,.bk-report pre { background:#04080d; border:1px solid var(--border); border-radius:3px; font-family:var(--mono); font-size:0.78rem; color:#7fbd9e; direction:ltr; text-align:left; }
.bk-report pre { padding:12px 14px; overflow-x:auto; }
.bk-report code { padding:1px 6px; }
.bk-report blockquote { border-right:3px solid var(--accent); border-left:none; margin:8px 0; padding:4px 14px 4px 0; color:var(--text-muted); }
.bk-report hr { border-color:var(--border); }

/* Inputs */
.stTextInput input, .stNumberInput input { background:var(--surface) !important; border:1px solid var(--border2) !important; border-radius:4px !important; color:var(--text) !important; font-family:var(--mono) !important; font-size:0.9rem !important; padding:10px 14px !important; }
.stTextInput input:focus { border-color:var(--accent) !important; box-shadow:0 0 0 2px var(--accent-glow) !important; }
.stSelectbox [data-baseweb="select"] > div { background:var(--surface) !important; border-color:var(--border2) !important; border-radius:4px !important; font-family:var(--mono) !important; font-size:0.85rem !important; }
.stSelectbox [data-baseweb="popover"] { background:var(--surface2) !important; }

/* Buttons */
.stButton > button { background:transparent !important; border:1px solid var(--border2) !important; color:var(--text) !important; font-family:var(--condensed) !important; font-weight:700 !important; font-size:0.8rem !important; letter-spacing:0.12em !important; text-transform:uppercase !important; border-radius:3px !important; padding:8px 18px !important; transition:all .15s !important; }
.stButton > button:hover { border-color:var(--accent) !important; color:var(--accent) !important; background:var(--accent-glow) !important; }
[data-testid="stFormSubmitButton"] > button, .stButton > button[kind="primary"] { background:var(--accent) !important; border-color:var(--accent) !important; color:#fff !important; }
[data-testid="stFormSubmitButton"] > button:hover, .stButton > button[kind="primary"]:hover { background:#3d8ac7 !important; border-color:#3d8ac7 !important; }

/* Progress */
.stProgress > div > div { background:var(--accent) !important; border-radius:1px !important; }
.stProgress > div { background:var(--border) !important; border-radius:1px !important; height:3px !important; }

/* Metrics */
[data-testid="stMetricValue"] { font-family:var(--mono) !important; font-size:1.4rem !important; font-weight:700 !important; color:var(--text) !important; }
[data-testid="stMetricLabel"] { font-family:var(--condensed) !important; font-size:0.7rem !important; letter-spacing:0.12em !important; text-transform:uppercase !important; color:var(--text-muted) !important; }

/* Misc */
hr { border-color:var(--border) !important; margin:16px 0 !important; }
[data-testid="stMarkdownContainer"] p { color:var(--text); font-family:var(--body); }
.stAlert { background:var(--surface) !important; border-color:var(--border) !important; border-radius:4px !important; }
.streamlit-expanderHeader { background:var(--surface) !important; border:1px solid var(--border) !important; border-radius:4px !important; font-family:var(--condensed) !important; font-weight:700 !important; font-size:0.8rem !important; letter-spacing:0.1em !important; text-transform:uppercase !important; color:var(--text) !important; }
[data-testid="stSidebar"] { background:var(--surface) !important; border-right:1px solid var(--border) !important; }
label { font-family:var(--condensed) !important; font-size:0.78rem !important; letter-spacing:0.1em !important; text-transform:uppercase !important; color:var(--text-muted) !important; }

/* ── Dashboard layout additions ── */
.bk-kpi-card { background:var(--surface); border:1px solid var(--border); border-radius:6px; padding:16px 18px; }
.bk-kpi-label { font-family:var(--mono); font-size:0.6rem; letter-spacing:0.18em; text-transform:uppercase; color:var(--text-dim); margin-bottom:8px; }
.bk-section-hdr { display:flex; align-items:center; gap:10px; margin:20px 0 12px; }
.bk-section-num { font-family:var(--mono); font-size:0.7rem; color:var(--accent); }
.bk-section-hdr-label { font-family:var(--condensed); font-weight:800; font-size:0.74rem; letter-spacing:0.22em; text-transform:uppercase; color:var(--text-muted); white-space:nowrap; }
.bk-section-hdr-line { flex:1; height:1px; background:var(--border); }
.bk-factor-panel { background:var(--surface); border:1px solid var(--border); border-radius:6px; padding:16px 18px; min-height:170px; }
.bk-analyst-card { background:var(--surface); border:1px solid var(--border); border-radius:6px; padding:14px 16px; height:100%; }
.bk-feed-article { background:var(--surface); border:1px solid var(--border); border-radius:0 4px 4px 0; padding:10px 13px; margin-bottom:7px; transition:background .1s; }
.bk-feed-article:hover { background:var(--surface2); }
.bk-report-card { background:var(--surface); border:1px solid var(--border); border-radius:6px; padding:14px 18px; cursor:pointer; transition:border-color .15s; }
.bk-report-card:hover { border-color:var(--border2); }
.bk-form-panel { background:var(--surface); border:1px solid var(--border); border-radius:4px; padding:16px 20px; margin-bottom:16px; }
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────
REPORTS_DIR  = "reports"
TICKERS_CSV  = "borkai/data/tase_stocks.csv"
HORIZON_LABELS = {
    "short":  "Short  1-4 Weeks",
    "medium": "Medium  1-6 Months",
    "long":   "Long  1-3 Years",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _score_color(score: int) -> str:
    if score >= 70: return "#39d353"
    if score >= 45: return "#e3a00a"
    return "#f85149"


def _load_tase_tickers():
    import csv
    if not os.path.exists(TICKERS_CSV):
        return []
    with open(TICKERS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _scanner_score_color(score: float) -> str:
    """Color for live scanner scores (0-12 scale)."""
    if score >= 8:  return "#39d353"
    if score >= 5:  return "#e3a00a"
    if score >= 3:  return "#4d9de0"
    return "#57657a"


def _run_live_scan(size_filter=None, min_score=1, top_n=40, verbose=False):
    """
    Run one cycle of the live scanner.
    Returns (live_results, categories, index_change) or raises on error.
    """
    from borkai.scanner.live_scanner import (
        LiveScanConfig, LiveResult, fetch_index_change, enrich,
        group_by_category, _load_stocks,
    )
    from borkai.scanner.layer1_fast_scan import run_layer1
    from borkai.monitor.state_store import StateStore

    csv_path = os.path.join(_APP_DIR, "borkai", "data", "tase_stocks.csv")
    state_file = os.path.join(_APP_DIR, "scanner_state.json")

    stocks = _load_stocks(csv_path, size_filter)
    if not stocks:
        return [], {}, 0.0

    state_store = StateStore(state_file)
    index_change = fetch_index_change()
    l1_results   = run_layer1(stocks, verbose=verbose)
    state_store.update_from_l1(l1_results)
    live_results = enrich(l1_results, state_store, index_change)
    categories   = group_by_category(live_results, min_score=min_score)
    state_store.save()

    return live_results, categories, index_change


def _list_report_files():
    """Return individual report .md files from the reports/ dir (newest first)."""
    rdir = Path(REPORTS_DIR)
    if not rdir.exists():
        return []
    files = sorted(rdir.glob("report_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files


# ── Hero ──────────────────────────────────────────────────────────────────────

_HERO_TICKERS = [
    ("^TA125.TA", "TA-125"),
    ("ESLT.TA",   "ESLT"),
    ("BEZQ.TA",   "BEZQ"),
    ("TEVA.TA",   "TEVA"),
    ("NICE.TA",   "NICE"),
    ("CHKP.TA",   "CHKP"),
    ("LUMI.TA",   "LUMI"),
    ("PTX.TA",    "PTX"),
]
_HERO_CACHE_TTL = 300   # seconds between live data refreshes


def _fetch_hero_data() -> list:
    """
    Fetch live 1-day % change for hero ticker strip via yfinance.
    Returns list of (label, pct_str, is_up). Cached for _HERO_CACHE_TTL seconds.
    Falls back to placeholder "—" on error.
    """
    import time as _time
    now = _time.time()
    if (
        "_hero_data" in st.session_state
        and now - st.session_state.get("_hero_ts", 0) < _HERO_CACHE_TTL
    ):
        return st.session_state["_hero_data"]

    syms   = [sym for sym, _ in _HERO_TICKERS]
    labels = {sym: lbl for sym, lbl in _HERO_TICKERS}
    items: list = []

    try:
        import yfinance as _yf
        raw = _yf.download(
            syms, period="2d", interval="1d",
            auto_adjust=True, progress=False, threads=True,
        )
        multi = len(syms) > 1
        for sym in syms:
            try:
                close = (raw["Close"][sym] if multi else raw["Close"]).dropna()
                if len(close) >= 2:
                    pct = (float(close.iloc[-1]) / float(close.iloc[-2]) - 1) * 100
                    sign = "+" if pct >= 0 else ""
                    items.append((labels[sym], f"{sign}{pct:.1f}%", pct >= 0))
            except Exception:
                items.append((labels[sym], "—", True))
    except Exception:
        items = [(lbl, "—", True) for _, lbl in _HERO_TICKERS]

    st.session_state["_hero_data"] = items
    st.session_state["_hero_ts"]   = now
    return items


def render_hero():
    items = _fetch_hero_data()
    tick_html = "".join(
        f'<span class="bk-ticker-item">'
        f'<span style="color:#3d4f61">{t}</span>'
        f'<span class="{"bk-up" if up else "bk-dn"}">{pct}</span>'
        f'</span>'
        for t, pct, up in items
    )

    st.markdown(f"""
    <div class="bk-hero">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;padding:0 4px">
        <div>
          <div class="bk-wordmark">
            BORKAI
            <span class="bk-wordmark-accent">TASE</span>
          </div>
          <div class="bk-hero-sub">Institutional-Grade Israeli Stock Intelligence</div>
          <div class="bk-hero-tags">
            <span class="bk-tag"><span class="bk-dot-live"></span>Live</span>
            <span class="bk-tag">TA-125 Coverage</span>
            <span class="bk-tag">Maya Disclosures</span>
            <span class="bk-tag">AI Analyst Panel</span>
          </div>
        </div>
        <div style="text-align:right;font-family:var(--mono);font-size:0.68rem;color:#3d4f61;line-height:2">
          <div style="color:#57657a">{datetime.now().strftime("%H:%M:%S")} TLV</div>
          <div>GPT-4o Engine</div>
          <div>v2.0</div>
        </div>
      </div>
      <div class="bk-ticker-strip">
        <div class="bk-ticker-inner">{tick_html + tick_html}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)


# ── Verdict card ──────────────────────────────────────────────────────────────

def render_verdict(rec: str, score: int, direction: str, conviction: str, rationale: str = ""):
    css = {"YES": "bk-v-yes", "NO": "bk-v-no", "CONDITIONAL": "bk-v-cond"}.get(rec.upper(), "bk-v-cond")
    color = {"YES": "#39d353", "NO": "#f85149", "CONDITIONAL": "#e3a00a"}.get(rec.upper(), "#e3a00a")
    label = {"YES": "INVEST", "NO": "AVOID", "CONDITIONAL": "CONDITIONAL"}.get(rec.upper(), rec)
    bar_c = _score_color(score)
    dir_l = {"up": "Bullish", "down": "Bearish", "mixed": "Mixed"}.get(direction, direction.upper())
    stars = {"high": "★★★", "moderate": "★★☆", "low": "★☆☆"}.get(conviction.lower(), "★☆☆")

    st.markdown(f"""
    <div class="bk-verdict {css}">
      <div class="bk-v-label">Investment Verdict</div>
      <div class="bk-v-rec" style="color:{color}">{label}</div>
      <div class="bk-v-score" style="color:{bar_c}">{score}<span class="bk-v-sub">/100</span></div>
      <div class="bk-bar-wrap" style="width:40%;margin:6px auto">
        <div class="bk-bar-fill" style="width:{score}%;background:{bar_c}"></div>
      </div>
      <div style="margin-top:12px;display:flex;justify-content:center;gap:10px;flex-wrap:wrap">
        <span class="bk-badge" style="background:rgba(77,157,224,0.12);color:#4d9de0">{dir_l}</span>
        <span class="bk-badge" style="background:rgba(57,211,83,0.1);color:#39d353">Conviction {stars}</span>
      </div>
      {"<div class='bk-v-detail'>" + rationale + "</div>" if rationale else ""}
    </div>
    """, unsafe_allow_html=True)


def render_analysis_dashboard(result, data):
    """
    Renders the analysis result as a structured financial dashboard.
    Uses result object directly — no markdown parsing. Presentation only.
    """
    import re as _re
    d = result.decision
    p = result.profile
    s = result.synthesis
    sd = getattr(result, "stock_data", None)

    ticker      = data["ticker"]
    horizon     = data.get("horizon", "medium")
    market      = data.get("market", "il")
    today       = getattr(result, "analysis_date", str(date.today()))
    company     = getattr(p, "company_name", "")
    report_en   = data["report"]

    score       = d.return_score
    score_c     = _score_color(score)
    rec         = d.invest_recommendation.upper()
    rec_label   = {"YES": "INVEST", "NO": "AVOID", "CONDITIONAL": "CONDITIONAL"}.get(rec, rec)
    rec_color   = {"YES": "#39d353", "NO": "#f85149", "CONDITIONAL": "#e3a00a"}.get(rec, "#e3a00a")
    rec_bg      = {"YES": "rgba(57,211,83,0.07)", "NO": "rgba(248,81,73,0.07)", "CONDITIONAL": "rgba(227,160,10,0.07)"}.get(rec, "rgba(77,157,224,0.07)")
    rec_border  = {"YES": "rgba(57,211,83,0.28)", "NO": "rgba(248,81,73,0.28)", "CONDITIONAL": "rgba(227,160,10,0.28)"}.get(rec, "rgba(77,157,224,0.28)")
    dir_label   = {"up": "BULLISH ↑", "down": "BEARISH ↓", "mixed": "MIXED ↔"}.get(d.direction, d.direction.upper())
    dir_color   = {"up": "#39d353", "down": "#f85149", "mixed": "#e3a00a"}.get(d.direction, "#57657a")
    conv_stars  = {"high": "★★★", "moderate": "★★☆", "low": "★☆☆"}.get(d.conviction.lower(), "★☆☆")
    conv_color  = {"high": "#39d353", "moderate": "#e3a00a", "low": "#57657a"}.get(d.conviction.lower(), "#57657a")
    lean_color  = {"bullish": "#39d353", "bearish": "#f85149", "mixed": "#e3a00a", "neutral": "#57657a"}.get(s.overall_lean, "#57657a")
    horiz_lbl   = {"short": "Short  ·  1–4 Weeks", "medium": "Medium  ·  1–6 Months", "long": "Long  ·  1–3 Years"}.get(horizon, horizon.upper())
    sym         = "₪" if market == "il" else "$"

    def _safe(txt, n=200):
        txt = (txt or "")[:n]
        return txt.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

    def _fmt_n(v):
        if v is None: return "—"
        v = float(v)
        if abs(v) >= 1e9: return f"{sym}{v/1e9:.1f}B"
        if abs(v) >= 1e6: return f"{sym}{v/1e6:.0f}M"
        return f"{sym}{v:,.0f}"

    def _fmt_pct(v):
        if v is None: return "—"
        return f"{float(v)*100:.1f}%"

    def _section(label):
        st.markdown(f"""
        <div class="bk-section-hdr">
          <span class="bk-section-num">◈</span>
          <span class="bk-section-hdr-label">{label}</span>
          <div class="bk-section-hdr-line"></div>
        </div>""", unsafe_allow_html=True)

    fname = f"borkai_{ticker}_{horizon}_{today}.md"

    # ── IDENTITY BAR ────────────────────────────────────────────────────
    col_id, col_dl = st.columns([5, 1])
    with col_id:
        st.markdown(f"""
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:6px;
                    padding:12px 20px;display:flex;align-items:center;flex-wrap:wrap;gap:16px">
          <div>
            <div style="font-family:var(--mono);font-weight:700;color:#4d9de0;font-size:1.25rem;line-height:1">{_safe(ticker,20)}</div>
            <div style="font-size:0.76rem;color:var(--text-muted);margin-top:3px">{_safe(company,60)}</div>
          </div>
          <div style="width:1px;height:30px;background:var(--border)"></div>
          <div style="font-family:var(--mono);font-size:0.7rem;color:var(--text-muted)">{horiz_lbl}</div>
          <div style="font-family:var(--mono);font-size:0.68rem;color:var(--text-dim)">{today}</div>
          <div style="margin-left:auto;display:flex;align-items:baseline;gap:4px">
            <span style="font-family:var(--mono);font-weight:700;font-size:1.6rem;color:{score_c}">{score}</span>
            <span style="font-family:var(--mono);font-size:0.65rem;color:var(--text-dim)">/100</span>
          </div>
        </div>""", unsafe_allow_html=True)
    with col_dl:
        st.download_button(
            "↓ Report", data=report_en.encode("utf-8"), file_name=fname,
            mime="text/markdown", use_container_width=True, key="dl_report_btn"
        )

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    # ── VERDICT + KPI ROW ───────────────────────────────────────────────
    c_verdict, c_score, c_dir, c_conv, c_phase = st.columns([2.2, 1.4, 1.4, 1.4, 2])

    with c_verdict:
        rationale_short = _safe(d.invest_rationale, 130)
        st.markdown(f"""
        <div style="background:{rec_bg};border:1px solid {rec_border};border-radius:8px;
                    padding:20px 22px;text-align:center">
          <div style="font-family:var(--mono);font-size:0.56rem;letter-spacing:0.22em;
                      color:var(--text-muted);text-transform:uppercase;margin-bottom:6px">Investment Verdict</div>
          <div style="font-family:var(--condensed);font-weight:900;font-size:2.1rem;
                      color:{rec_color};letter-spacing:0.04em;text-transform:uppercase;line-height:1">{rec_label}</div>
          <div style="margin-top:10px;font-size:0.76rem;color:var(--text-muted);line-height:1.45">{rationale_short}</div>
        </div>""", unsafe_allow_html=True)

    with c_score:
        st.markdown(f"""
        <div class="bk-kpi-card" style="text-align:center">
          <div class="bk-kpi-label">Return Score</div>
          <div style="font-family:var(--mono);font-weight:700;font-size:2.4rem;color:{score_c};line-height:1">{score}</div>
          <div style="font-family:var(--mono);font-size:0.6rem;color:var(--text-dim);margin-bottom:10px">/100</div>
          <div style="height:3px;background:var(--border);border-radius:2px;overflow:hidden">
            <div style="width:{score}%;height:100%;background:{score_c};border-radius:2px"></div>
          </div>
        </div>""", unsafe_allow_html=True)

    with c_dir:
        st.markdown(f"""
        <div class="bk-kpi-card" style="text-align:center">
          <div class="bk-kpi-label">Direction</div>
          <div style="font-family:var(--condensed);font-weight:800;font-size:1.35rem;
                      color:{dir_color};line-height:1.1;text-transform:uppercase">{dir_label}</div>
          <div style="font-family:var(--mono);font-size:0.62rem;color:var(--text-muted);margin-top:8px">
            {_safe(s.overall_lean,12).upper()} lean</div>
        </div>""", unsafe_allow_html=True)

    with c_conv:
        st.markdown(f"""
        <div class="bk-kpi-card" style="text-align:center">
          <div class="bk-kpi-label">Conviction</div>
          <div style="font-size:1.7rem;line-height:1;color:{conv_color}">{conv_stars}</div>
          <div style="font-family:var(--condensed);font-weight:700;font-size:0.74rem;
                      color:{conv_color};text-transform:uppercase;letter-spacing:0.1em;margin-top:8px">{d.conviction}</div>
        </div>""", unsafe_allow_html=True)

    with c_phase:
        phase_s     = _safe(getattr(p, "phase", ""), 40)
        situation_s = _safe(getattr(p, "current_situation", ""), 90)
        st.markdown(f"""
        <div class="bk-kpi-card">
          <div class="bk-kpi-label">Market Phase</div>
          <div style="font-family:var(--condensed);font-weight:700;font-size:0.95rem;
                      color:var(--text);text-transform:uppercase;letter-spacing:0.04em;line-height:1.2">{phase_s}</div>
          <div style="font-size:0.76rem;color:var(--text-muted);margin-top:6px;line-height:1.4">{situation_s}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ── KEY FACTORS ─────────────────────────────────────────────────────
    _section("KEY FACTORS")

    def _factor_html(items, color):
        html = ""
        for itm in (items or [])[:5]:
            html += (f'<div style="display:flex;gap:8px;margin-bottom:8px">'
                     f'<span style="color:{color};flex-shrink:0;margin-top:2px;font-size:0.7rem">▸</span>'
                     f'<span style="font-size:0.82rem;color:var(--text-muted);line-height:1.45">{_safe(itm,150)}</span></div>')
        return html or '<div style="font-size:0.8rem;color:var(--text-dim)">—</div>'

    cb, cbr, cr = st.columns(3)
    with cb:
        st.markdown(f"""<div class="bk-factor-panel">
          <div style="font-family:var(--condensed);font-weight:800;font-size:0.7rem;letter-spacing:0.18em;
                      text-transform:uppercase;color:#39d353;margin-bottom:12px">▲ Bullish Factors</div>
          {_factor_html(d.key_bullish_factors, "#39d353")}</div>""", unsafe_allow_html=True)
    with cbr:
        st.markdown(f"""<div class="bk-factor-panel">
          <div style="font-family:var(--condensed);font-weight:800;font-size:0.7rem;letter-spacing:0.18em;
                      text-transform:uppercase;color:#f85149;margin-bottom:12px">▼ Bearish Factors</div>
          {_factor_html(d.key_bearish_factors, "#f85149")}</div>""", unsafe_allow_html=True)
    with cr:
        st.markdown(f"""<div class="bk-factor-panel">
          <div style="font-family:var(--condensed);font-weight:800;font-size:0.7rem;letter-spacing:0.18em;
                      text-transform:uppercase;color:#e3a00a;margin-bottom:12px">⚠ Key Risks</div>
          {_factor_html(d.key_risks, "#e3a00a")}</div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ── PRICE CHART ─────────────────────────────────────────────────────
    _section("PRICE CHART")

    _chart_cfg = {
        "short":  {"period": "1mo", "label": "1-Month",  "mas": [(5, "#a78bfa", "MA5"), (20, "#f59e0b", "MA20")]},
        "medium": {"period": "1y",  "label": "1-Year",   "mas": [(20, "#f59e0b", "MA20"), (50, "#ef4444", "MA50")]},
        "long":   {"period": "5y",  "label": "5-Year",   "mas": [(50, "#f59e0b", "MA50"), (200, "#ef4444", "MA200")]},
    }.get(horizon, {"period": "1y", "label": "1-Year", "mas": [(20, "#f59e0b", "MA20"), (50, "#ef4444", "MA50")]})

    try:
        import yfinance as _yf
        import plotly.graph_objects as _go
        _tkr_yf = ticker if not (market == "il" and not ticker.upper().endswith(".TA")) else ticker + ".TA"
        _hist = _yf.Ticker(_tkr_yf).history(period=_chart_cfg["period"])
        if _hist is not None and len(_hist) > 10:
            _fig = _go.Figure()
            _fig.add_trace(_go.Scatter(
                x=_hist.index, y=_hist["Close"], mode="lines", name="Close",
                line=dict(color="#4d9de0", width=2),
                fill="tozeroy", fillcolor="rgba(77,157,224,0.05)",
            ))
            for _w, _col, _nm in _chart_cfg["mas"]:
                if len(_hist) >= _w:
                    _fig.add_trace(_go.Scatter(
                        x=_hist.index, y=_hist["Close"].rolling(_w).mean(),
                        mode="lines", name=_nm, line=dict(color=_col, width=1.5, dash="dot"),
                    ))
            _fig.update_layout(
                plot_bgcolor="#0d1117", paper_bgcolor="#0d1117",
                font=dict(color="#c9d1d9", size=11),
                xaxis=dict(showgrid=True, gridcolor="#161b22", linecolor="#1d2433", zeroline=False),
                yaxis=dict(showgrid=True, gridcolor="#161b22", linecolor="#1d2433", zeroline=False),
                legend=dict(bgcolor="#0d1117", bordercolor="#1d2433", borderwidth=1,
                            orientation="h", y=1.02, x=0),
                height=340, margin=dict(l=0, r=0, t=12, b=0), hovermode="x unified",
            )
            st.markdown('<div style="background:#0d1117;border:1px solid #1d2433;border-radius:8px;overflow:hidden;padding:14px 10px 6px">', unsafe_allow_html=True)
            st.plotly_chart(_fig, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

            # Chart signals directly below chart
            try:
                from borkai.report.report_generator import _chart_analysis_section
                _clines = _chart_analysis_section(sd, time_horizon=horizon)
                _bullet_lines = [l for l in _clines if l.startswith("- ")]
                if _bullet_lines:
                    sigs_html = ""
                    for bl in _bullet_lines[:5]:
                        cleaned = _re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', bl.lstrip("- "))
                        sigs_html += f'<div style="font-size:0.8rem;color:var(--text-muted);padding:5px 0;border-bottom:1px solid var(--border)">{cleaned}</div>'
                    st.markdown(f'<div style="margin-top:6px;padding:0 4px">{sigs_html}</div>', unsafe_allow_html=True)
            except Exception:
                pass
    except Exception:
        pass

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ── ANALYST PANEL ───────────────────────────────────────────────────
    _section("ANALYST PANEL")

    outputs = result.agent_outputs
    n_bull  = sum(1 for o in outputs if o.stance == "bullish")
    n_bear  = sum(1 for o in outputs if o.stance == "bearish")
    n_mix   = len(outputs) - n_bull - n_bear
    icons_s = "".join({"bullish":"🟢","bearish":"🔴","neutral":"⚪","mixed":"🟡"}.get(o.stance,"⚪") for o in outputs)

    st.markdown(f"""
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:6px;
                padding:12px 18px;margin-bottom:12px;display:flex;align-items:center;gap:18px;flex-wrap:wrap">
      <div style="font-size:1.2rem;letter-spacing:2px">{icons_s}</div>
      <div style="width:1px;height:18px;background:var(--border)"></div>
      <div style="font-family:var(--mono);font-size:0.72rem;color:#39d353"><b>{n_bull}</b> bullish</div>
      <div style="font-family:var(--mono);font-size:0.72rem;color:#f85149"><b>{n_bear}</b> bearish</div>
      <div style="font-family:var(--mono);font-size:0.72rem;color:var(--text-muted)"><b>{n_mix}</b> neutral/mixed</div>
      <div style="margin-left:auto;font-family:var(--mono);font-size:0.64rem;color:var(--text-dim)">{len(outputs)} analysts</div>
    </div>""", unsafe_allow_html=True)

    # 3 columns of analyst cards
    cols_per_row = 3
    for row_start in range(0, len(outputs), cols_per_row):
        row_outs = outputs[row_start:row_start + cols_per_row]
        row_cols = st.columns(len(row_outs))
        for col, out in zip(row_cols, row_outs):
            sc = {"bullish":"#39d353","bearish":"#f85149","neutral":"#57657a","mixed":"#e3a00a"}.get(out.stance,"#57657a")
            conf_i = {"high":"●●●","moderate":"●●○","low":"●○○"}.get(out.confidence.lower(),"●○○")
            sents = _re.split(r'(?<=[.!?])\s+', (out.key_finding or "").strip())
            # Use up to 2 complete sentences — never cut mid-sentence, never add "..."
            opinion = " ".join(sents[:2])
            # HTML-escape only — no length truncation
            opinion_html = opinion.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            with col:
                st.markdown(f"""
                <div class="bk-analyst-card" style="border-top:2px solid {sc}">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px">
                    <div style="font-family:var(--condensed);font-weight:700;font-size:0.82rem;
                                text-transform:uppercase;letter-spacing:0.04em;color:var(--text)">{_safe(out.agent_name,40)}</div>
                    <div style="font-family:var(--mono);font-size:0.58rem;color:{sc}">{conf_i}</div>
                  </div>
                  <div style="font-family:var(--mono);font-size:0.6rem;letter-spacing:0.1em;
                              text-transform:uppercase;color:{sc};margin-bottom:8px">{out.stance.upper()}</div>
                  <div style="font-size:0.79rem;color:var(--text-muted);line-height:1.5">{opinion_html}</div>
                </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ── SCENARIOS ────────────────────────────────────────────────────────
    _section("SCENARIO ANALYSIS")

    def _parse_prob(prob_str):
        nums = _re.findall(r'\d+', str(prob_str))
        return round(sum(int(n) for n in nums) / len(nums)) if nums else 0

    cs_bull, cs_base, cs_bear = st.columns(3)
    for col, label, icon, scenario, top_c, bar_c in [
        (cs_bull, "Bull Case", "🐂", d.bull_scenario, "#39d353", "rgba(57,211,83,0.55)"),
        (cs_base, "Base Case", "⚖️", d.base_scenario, "#4d9de0", "rgba(77,157,224,0.55)"),
        (cs_bear, "Bear Case", "🐻", d.bear_scenario, "#f85149", "rgba(248,81,73,0.55)"),
    ]:
        prob = _parse_prob(scenario.probability)
        desc_s    = _safe(scenario.description or "", 160)
        outcome_s = _safe(scenario.expected_outcome or "", 100)
        with col:
            st.markdown(f"""
            <div style="background:var(--surface);border:1px solid var(--border);border-top:2px solid {top_c};
                        border-radius:6px;padding:16px 18px">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                <div style="font-family:var(--condensed);font-weight:800;font-size:0.84rem;
                            letter-spacing:0.08em;text-transform:uppercase;color:{top_c}">{icon} {label}</div>
                <div style="font-family:var(--mono);font-size:0.72rem;color:var(--text-muted)">{scenario.probability}</div>
              </div>
              <div style="height:3px;background:var(--border);border-radius:2px;overflow:hidden;margin-bottom:12px">
                <div style="width:{prob}%;height:100%;background:{bar_c};border-radius:2px"></div>
              </div>
              <div style="font-size:0.82rem;color:var(--text);line-height:1.5;margin-bottom:8px">{desc_s}</div>
              <div style="font-family:var(--mono);font-size:0.7rem;color:var(--text-muted);font-style:italic">{outcome_s}</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ── SYNTHESIS ───────────────────────────────────────────────────────
    _section("SYNTHESIS")

    c_syn, c_agr = st.columns([3, 2])
    with c_syn:
        agree_summ = _safe(s.agreement_summary or "", 320)
        st.markdown(f"""
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:18px 20px">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap">
            <span style="font-family:var(--condensed);font-weight:800;font-size:0.7rem;
                         letter-spacing:0.2em;text-transform:uppercase;color:var(--text-muted)">Overall Lean</span>
            <span style="font-family:var(--condensed);font-weight:800;font-size:1rem;
                         color:{lean_color};text-transform:uppercase">{s.overall_lean.upper()}</span>
            <span style="font-family:var(--mono);font-size:0.66rem;color:var(--text-dim)">
              · {s.consensus_confidence.upper()} confidence</span>
          </div>
          <div style="font-size:0.83rem;color:var(--text-muted);line-height:1.6">{agree_summ}</div>
        </div>""", unsafe_allow_html=True)

    with c_agr:
        agr_html = ""
        for a in (s.agreements or [])[:3]:
            agr_html += (f'<div style="margin-bottom:10px">'
                         f'<div style="font-family:var(--mono);font-size:0.6rem;color:#39d353;'
                         f'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px">{_safe(a.topic,40)}</div>'
                         f'<div style="font-size:0.78rem;color:var(--text-muted);line-height:1.4">{_safe(a.shared_view,90)}</div>'
                         f'</div>')
        st.markdown(f"""
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:18px 20px">
          <div style="font-family:var(--condensed);font-weight:800;font-size:0.7rem;letter-spacing:0.2em;
                      text-transform:uppercase;color:var(--text-muted);margin-bottom:12px">Points of Agreement</div>
          {agr_html or '<div style="font-size:0.8rem;color:var(--text-dim)">—</div>'}
        </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ── FINANCIAL SNAPSHOT ──────────────────────────────────────────────
    if sd is not None:
        has_fin = any(v is not None for v in [sd.revenue_ttm, sd.net_income_ttm, sd.gross_margin, sd.operating_margin])
        if has_fin:
            _section("FINANCIAL SNAPSHOT")
            fin_cols = st.columns(4)
            metrics_def = [
                ("Revenue TTM",   _fmt_n(sd.revenue_ttm),        None),
                ("Net Income TTM",_fmt_n(sd.net_income_ttm),     sd.net_income_ttm),
                ("Gross Margin",  _fmt_pct(sd.gross_margin),     sd.gross_margin),
                ("Net Margin",    _fmt_pct(sd.net_margin),       sd.net_margin),
            ]
            for col, (lbl, val, raw) in zip(fin_cols, metrics_def):
                vc = "#39d353" if (raw is not None and float(raw) > 0) else "#f85149" if (raw is not None and float(raw) < 0) else "var(--text)"
                with col:
                    st.markdown(f"""
                    <div class="bk-kpi-card" style="text-align:center">
                      <div class="bk-kpi-label">{lbl}</div>
                      <div style="font-family:var(--mono);font-weight:700;font-size:1.3rem;color:{vc}">{val}</div>
                    </div>""", unsafe_allow_html=True)

            if getattr(sd, "quarterly_earnings_summary", None):
                with st.expander("Quarterly Earnings Detail", expanded=False):
                    try:
                        from borkai.report.report_generator import _earnings_section
                        earn_lines = _earnings_section(sd)
                        if earn_lines:
                            st.markdown("\n".join(earn_lines))
                    except Exception:
                        st.text(sd.quarterly_earnings_summary)

            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ── NEWS & FILINGS ──────────────────────────────────────────────────
    if result.article_impacts or result.maya_reports:
        _section("NEWS & FILINGS")
        col_arts, col_maya = st.columns(2)

        with col_arts:
            if result.article_impacts:
                st.markdown('<div style="font-family:var(--condensed);font-weight:700;font-size:0.68rem;'
                            'letter-spacing:0.18em;text-transform:uppercase;color:var(--text-muted);'
                            'margin-bottom:10px">Recent Articles</div>', unsafe_allow_html=True)
                for art in result.article_impacts[:6]:
                    imp = art.impact.lower()
                    ic  = {"bullish":"#39d353","bearish":"#f85149"}.get(imp,"#57657a")
                    clean_url = (art.url or "").strip()
                    if not clean_url.startswith("http"): clean_url = ""
                    title_disp = _safe(art.title or "", 75)
                    link_html  = (f'<a href="{clean_url}" target="_blank" '
                                  f'style="color:var(--text);text-decoration:none">{title_disp}</a>'
                                  if clean_url else title_disp)
                    summ_html  = (f'<div style="font-size:0.76rem;color:var(--text-muted);margin-top:5px">'
                                  f'{_safe(art.impact_summary or "",110)}</div>'
                                  if art.impact_summary else "")
                    st.markdown(f"""
                    <div class="bk-feed-article" style="border-left:2px solid {ic}">
                      <div style="font-size:0.82rem;line-height:1.4;margin-bottom:3px">{link_html}</div>
                      <div style="font-family:var(--mono);font-size:0.62rem;color:var(--text-dim)">
                        {_safe(art.source or "",30)} {'· '+art.published[:10] if art.published else ''}</div>
                      {summ_html}
                    </div>""", unsafe_allow_html=True)

        with col_maya:
            if result.maya_reports:
                st.markdown('<div style="font-family:var(--condensed);font-weight:700;font-size:0.68rem;'
                            'letter-spacing:0.18em;text-transform:uppercase;color:var(--text-muted);'
                            'margin-bottom:10px">Maya / TASE Filings</div>', unsafe_allow_html=True)
                for rep in result.maya_reports[:6]:
                    imp = rep.impact.lower()
                    ic  = {"bullish":"#39d353","bearish":"#f85149"}.get(imp,"#57657a")
                    clean_url = (rep.link or "").strip()
                    if not clean_url.startswith("http"): clean_url = ""
                    title_disp = _safe(rep.title or "", 75)
                    link_html  = (f'<a href="{clean_url}" target="_blank" '
                                  f'style="color:var(--text);text-decoration:none">{title_disp}</a>'
                                  if clean_url else title_disp)
                    reason_html = (f'<div style="font-size:0.76rem;color:var(--text-muted);margin-top:5px">'
                                   f'{_safe(rep.impact_reason or "",110)}</div>'
                                   if getattr(rep,"impact_reason","") else "")
                    # Fetch-source badge: green for Playwright (live), amber for DDG (indexed/stale)
                    fetch_path = getattr(rep, "fetch_path", "")
                    if "playwright" in fetch_path:
                        path_badge = ('<span style="font-family:var(--mono);font-size:0.58rem;'
                                      'color:#39d353;border:1px solid rgba(57,211,83,0.3);'
                                      'padding:1px 5px;border-radius:2px;margin-left:6px">LIVE</span>')
                    elif fetch_path:
                        path_badge = ('<span style="font-family:var(--mono);font-size:0.58rem;'
                                      'color:#e3a00a;border:1px solid rgba(227,160,10,0.3);'
                                      'padding:1px 5px;border-radius:2px;margin-left:6px">DDG</span>')
                    else:
                        path_badge = ""
                    st.markdown(f"""
                    <div class="bk-feed-article" style="border-left:2px solid {ic}">
                      <div style="font-size:0.82rem;line-height:1.4;margin-bottom:3px">{link_html}{path_badge}</div>
                      <div style="font-family:var(--mono);font-size:0.62rem;color:var(--text-dim)">
                        {_safe(getattr(rep,"source",""),30)} {'· '+rep.published[:10] if getattr(rep,"published","") else ''}</div>
                      {reason_html}
                    </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ── FULL REPORT (collapsed) ──────────────────────────────────────────
    with st.expander("📄  Full Research Report (Markdown)", expanded=False):
        st.markdown(report_en)


# ── Tab: Analyze ──────────────────────────────────────────────────────────────

def tab_analyze():
    st.markdown(
        '<div style="font-family:\'Barlow Condensed\',sans-serif;font-size:1.4rem;font-weight:900;'
        'letter-spacing:0.12em;text-transform:uppercase;margin:16px 0 4px;color:#c9d1d9">'
        'Stock Analysis</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="font-size:0.8rem;color:#57657a;margin-bottom:20px;'
        'font-family:\'JetBrains Mono\',monospace">'
        'Full AI analysis — data, news, analyst panel, committee verdict, Hebrew report</div>',
        unsafe_allow_html=True,
    )

    # ── Prefill support (from Live Scan / Hot Stocks "Analyze" buttons) ──────
    _prefill = st.session_state.pop("scanner_prefill", "") or st.session_state.pop("prefill_ticker", "")
    if _prefill:
        st.session_state["_analyze_form_v"] = st.session_state.get("_analyze_form_v", 0) + 1
        st.session_state["_analyze_default"] = _prefill
    _form_key     = f"analyze_form_v{st.session_state.get('_analyze_form_v', 0)}"
    _default_tick = st.session_state.pop("_analyze_default", "")

    # ── Input form ────────────────────────────────────────────────────────────
    st.markdown('<div class="bk-form-panel">', unsafe_allow_html=True)
    with st.form(key=_form_key, clear_on_submit=False):
        c1, c2, c3, c4 = st.columns([3, 3, 2, 2])
        with c1:
            ticker_input = st.text_input(
                "Ticker Symbol",
                value=_default_tick,
                placeholder="ESLT  /  BEZQ  /  TEVA  /  AAPL",
                help="Enter without .TA suffix",
            )
        with c2:
            horizon_input = st.selectbox(
                "Time Horizon",
                options=["short", "medium", "long"],
                index=1,
                format_func=lambda x: HORIZON_LABELS[x],
            )
        with c3:
            market_input = st.selectbox(
                "Market",
                options=["il", "us"],
                format_func=lambda x: {"il": "Israel (TASE)", "us": "US (NYSE/NASDAQ)"}[x],
            )
        with c4:
            st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
            submitted = st.form_submit_button(
                "Run Analysis",
                type="primary",
                use_container_width=True,
            )
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Run analysis on submit ────────────────────────────────────────────────
    if submitted:
        ticker_raw = ticker_input.strip().upper().replace(".TA", "")
        if not ticker_raw:
            st.error("Please enter a ticker symbol (e.g. ESLT, BEZQ, TEVA)")
            return

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            st.error(
                "OpenAI API key not found. "
                "Make sure your .env file has OPENAI_API_KEY=sk-..."
            )
            return

        # Clear previous result
        if "last_result" in st.session_state:
            del st.session_state["last_result"]

        ticker = ticker_raw
        horizon = horizon_input
        market = market_input

        # Static terminal header
        st.markdown(f"""
        <div class="bk-terminal" style="margin-bottom:0;border-bottom:none;border-radius:4px 4px 0 0">
          <div class="bk-terminal-header">
            <span class="bk-dot bk-dot-r"></span>
            <span class="bk-dot bk-dot-a"></span>
            <span class="bk-dot bk-dot-g"></span>
            <span class="bk-term-title">BORKAI ENGINE &mdash; {ticker} &middot; {horizon.upper()} &middot; {market.upper()}</span>
          </div>
          <span class="bk-prompt">$</span> borkai analyze --ticker {ticker} --horizon {horizon} --market {market}
        </div>
        """, unsafe_allow_html=True)

        pbar = st.progress(0.0)
        log_box = st.empty()
        stages_done: list = []

        def _redraw(final: bool = False, err: str = ""):
            rows = []
            for snum, slabel, sdetail in stages_done:
                detail = f'  <span style="color:#3d4f61">{sdetail}</span>' if sdetail else ""
                rows.append(
                    f'<span style="color:#39d353">&#10003;</span> '
                    f'<span style="color:#3d4f61">[{snum:02d}/08]</span> '
                    f'<span style="color:#c9d1d9">{slabel}</span>{detail}'
                )
            if err:
                rows.append(f'<span style="color:#f85149">&#10007; {err}</span>')
            elif final:
                rows.append('<span style="color:#39d353;font-weight:700">&#10003; COMPLETE</span>')
            else:
                rows.append('<span style="color:#e3a00a">&#8635; running&hellip;</span>')

            log_box.markdown(
                '<div class="bk-terminal" style="border-top:none;border-radius:0 0 4px 4px">'
                + "<br>".join(rows) + "</div>",
                unsafe_allow_html=True,
            )

        def _on_progress(stage: int, label: str, detail: str):
            stages_done.append((stage, label, detail))
            pbar.progress(min(stage / 8, 1.0))
            _redraw()

        _redraw()  # show "running…"

        try:
            from main import analyze
            report_en, result = analyze(
                ticker=ticker,
                time_horizon=horizon,
                market=market,
                save_report=True,
                progress_callback=_on_progress,
            )
            st.session_state["last_result"] = {
                "ticker": ticker,
                "horizon": horizon,
                "market": market,
                "report": report_en,
                "result": result,
            }
            pbar.progress(1.0)
            _redraw(final=True)
        except Exception as exc:
            import traceback
            err_msg = str(exc)
            # Surface quota/billing errors clearly without a confusing traceback
            if "insufficient_quota" in err_msg or "quota exceeded" in err_msg.lower() or "billing" in err_msg.lower():
                _redraw(err="OpenAI quota exceeded")
                st.error(
                    "**OpenAI quota exceeded** — your account has no remaining credits.  \n"
                    "Add credits at https://platform.openai.com/settings/billing and retry."
                )
                return
            _redraw(err=err_msg[:120])
            st.error(f"Analysis failed: {exc}")
            with st.expander("Full error details"):
                st.code(traceback.format_exc())
            return

    # ── Show result ───────────────────────────────────────────────────────────
    if "last_result" in st.session_state:
        data = st.session_state["last_result"]
        report_en = data["report"]
        result = data["result"]

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        render_analysis_dashboard(result, data)
    elif not submitted:
        st.markdown("""
        <div style="text-align:center;padding:60px 20px;color:#3d4f61;
          font-family:'JetBrains Mono',monospace">
          <div style="font-size:2rem;margin-bottom:12px">⚡</div>
          <div style="font-size:0.8rem;letter-spacing:0.12em;text-transform:uppercase">
            Enter a ticker and click <strong style="color:#4d9de0">Run Analysis</strong>
          </div>
          <div style="font-size:0.68rem;margin-top:8px;color:#57657a">
            GPT-4o · 8-stage pipeline · analyst panel · committee verdict
          </div>
        </div>
        """, unsafe_allow_html=True)


# ── Tab: Reports ──────────────────────────────────────────────────────────────

def _parse_report_meta(path: Path) -> dict:
    """Extract score, rec, direction, company, date, horizon from a report markdown."""
    import re as _re
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        text = ""

    name = path.name  # e.g. report_ESLT_TA_medium_2026-04-10.md
    # Parse filename: report_TICKER[_TA]_horizon_date.md
    stem = name.replace("report_", "").replace("_he.md", "").replace(".md", "")
    parts = stem.split("_")
    # Remove market suffix (.TA) from ticker part
    ticker_raw = parts[0] if parts else stem
    horizon_raw = ""
    date_raw = ""
    for p in parts[1:]:
        if p in ("short", "medium", "long"):
            horizon_raw = p
        elif _re.match(r"\d{4}-\d{2}-\d{2}", p):
            date_raw = p

    # Parse content
    score_m = _re.search(r"Score\s*:\s*(\d+)/100", text)
    score   = int(score_m.group(1)) if score_m else None

    rec_m = _re.search(r"(INVEST|AVOID|CONDITIONAL)\s*[—\-–]\s*(YES|NO|CONDITIONAL)", text)
    rec   = rec_m.group(2) if rec_m else None
    if not rec:
        rec_m2 = _re.search(r"✅\s*INVEST|invest_recommendation.*YES", text, _re.IGNORECASE)
        rec = "YES" if rec_m2 else None
        if not rec:
            rec_m3 = _re.search(r"❌\s*AVOID|invest_recommendation.*NO", text, _re.IGNORECASE)
            rec = "NO" if rec_m3 else None

    dir_m  = _re.search(r"Direction\s*:\s*(BULLISH|BEARISH|MIXED)", text)
    direction = dir_m.group(1).lower() if dir_m else ""

    co_m  = _re.search(r"##\s*[\w.]+\s*[—\-–]\s*(.+)", text)
    company = co_m.group(1).strip() if co_m else ""

    date_content = _re.search(r"\*\*Date:\*\*\s*(\d{4}-\d{2}-\d{2})", text)
    if date_content:
        date_raw = date_content.group(1)
    horiz_content = _re.search(r"\*\*Horizon:\*\*\s*(\w+)", text)
    if horiz_content:
        horizon_raw = horiz_content.group(1).lower()

    return {
        "path": path,
        "name": name,
        "ticker": ticker_raw,
        "company": company,
        "score": score,
        "rec": rec,
        "direction": direction,
        "horizon": horizon_raw,
        "date": date_raw,
    }


def tab_reports():
    import re as _re

    st.markdown(
        '<div style="font-family:\'Barlow Condensed\',sans-serif;font-size:1.4rem;font-weight:900;'
        'letter-spacing:0.12em;text-transform:uppercase;margin:16px 0 4px;color:#c9d1d9">'
        'Research Reports</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="font-size:0.8rem;color:#57657a;margin-bottom:20px;'
        'font-family:\'JetBrains Mono\',monospace">'
        'Browse AI-generated stock research — click any report to view</div>',
        unsafe_allow_html=True,
    )

    files = _list_report_files()
    # Exclude Hebrew reports from the card grid (they're duplicates)
    files = [f for f in files if not f.name.endswith("_he.md")]

    if not files:
        st.markdown(
            '<div style="padding:60px 0;text-align:center;color:#3d4f61;font-family:'
            '\'JetBrains Mono\',monospace;font-size:0.8rem;letter-spacing:0.1em;text-transform:uppercase">'
            '<div style="font-size:2rem;margin-bottom:12px">📄</div>'
            'No saved reports yet. Run an analysis first.</div>',
            unsafe_allow_html=True,
        )
        return

    # ── Detail view ──────────────────────────────────────────────────────────
    if "reports_selected" in st.session_state:
        sel_name = st.session_state["reports_selected"]
        sel_path = Path(REPORTS_DIR) / sel_name
        if sel_path.exists():
            meta = _parse_report_meta(sel_path)
            content = sel_path.read_text(encoding="utf-8", errors="replace")
            rc = {"YES":"#39d353","NO":"#f85149","CONDITIONAL":"#e3a00a"}.get(meta["rec"] or "", "#57657a")
            rl = {"YES":"INVEST","NO":"AVOID","CONDITIONAL":"CONDITIONAL"}.get(meta["rec"] or "", "—")
            sc = meta["score"] or 0
            sc_c = _score_color(sc) if sc else "#57657a"

            back_col, dl_col = st.columns([5, 1])
            with back_col:
                if st.button("← Back to Reports", key="reports_back"):
                    del st.session_state["reports_selected"]
                    st.rerun()
            with dl_col:
                st.download_button(
                    "↓ Report", data=content.encode("utf-8"),
                    file_name=sel_name, mime="text/markdown",
                    use_container_width=True, key="dl_detail_btn",
                )

            st.markdown(f"""
            <div style="background:var(--surface);border:1px solid var(--border);
              border-radius:6px;padding:20px 24px;margin-top:8px">
              <div style="display:flex;align-items:center;gap:20px;margin-bottom:18px;flex-wrap:wrap">
                <div>
                  <div style="font-family:'JetBrains Mono',monospace;font-weight:700;
                    font-size:1.5rem;color:#4d9de0;line-height:1">{meta['ticker']}</div>
                  <div style="font-size:0.8rem;color:#57657a;margin-top:3px">{meta['company'][:60]}</div>
                </div>
                <div style="margin-left:auto;text-align:right">
                  <div style="font-family:'Barlow Condensed',sans-serif;font-weight:900;
                    font-size:1.8rem;color:{rc};text-transform:uppercase;line-height:1">{rl}</div>
                  <div style="font-family:'JetBrains Mono',monospace;font-weight:700;
                    font-size:2rem;color:{sc_c};line-height:1;margin-top:2px">
                    {sc if sc else '—'}<span style="font-size:0.7rem;color:#3d4f61">/100</span>
                  </div>
                </div>
              </div>
              <div style="height:2px;background:var(--border);border-radius:1px;
                overflow:hidden;margin-bottom:12px">
                <div style="width:{sc}%;height:100%;background:{sc_c};border-radius:1px"></div>
              </div>
              <div style="display:flex;gap:10px;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;color:#3d4f61">
                <span>{meta['date']}</span>
                <span>·</span>
                <span style="text-transform:uppercase">{meta['horizon']}</span>
              </div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
            st.markdown(content)
            return

    # ── Card grid ─────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.7rem;'
        f'color:#57657a;margin-bottom:16px">{len(files)} reports</div>',
        unsafe_allow_html=True,
    )

    metas = [_parse_report_meta(f) for f in files]

    cols_per_row = 3
    for row_start in range(0, len(metas), cols_per_row):
        row = metas[row_start: row_start + cols_per_row]
        cols = st.columns(len(row))
        for col, m in zip(cols, row):
            rc  = {"YES":"#39d353","NO":"#f85149","CONDITIONAL":"#e3a00a"}.get(m["rec"] or "", "#57657a")
            rl  = {"YES":"INVEST","NO":"AVOID","CONDITIONAL":"COND."}.get(m["rec"] or "", "—")
            sc  = m["score"] or 0
            sc_c = _score_color(sc) if sc else "#57657a"
            dir_icon = {"bullish":"↑ BULL","bearish":"↓ BEAR","mixed":"↔ MIXED"}.get(m["direction"], "—")
            dir_c = {"bullish":"#39d353","bearish":"#f85149","mixed":"#e3a00a"}.get(m["direction"], "#57657a")
            with col:
                st.markdown(f"""
                <div class="bk-report-card">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
                    <div>
                      <div style="font-family:'JetBrains Mono',monospace;font-weight:700;
                        color:#4d9de0;font-size:1.1rem;line-height:1">{m['ticker']}</div>
                      <div style="font-size:0.76rem;color:#57657a;margin-top:3px;
                        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px">{m['company'][:32]}</div>
                    </div>
                    <div style="text-align:right">
                      <div style="font-family:'Barlow Condensed',sans-serif;font-weight:900;
                        font-size:0.9rem;color:{rc};text-transform:uppercase">{rl}</div>
                      <div style="font-family:'JetBrains Mono',monospace;font-weight:700;
                        font-size:1.3rem;color:{sc_c};line-height:1;margin-top:2px">
                        {sc if sc else '—'}<span style="font-size:0.6rem;color:#3d4f61">/100</span>
                      </div>
                    </div>
                  </div>
                  <div style="height:2px;background:var(--border);border-radius:1px;overflow:hidden;margin-bottom:8px">
                    <div style="width:{sc}%;height:100%;background:{sc_c};border-radius:1px"></div>
                  </div>
                  <div style="display:flex;gap:8px;font-family:'JetBrains Mono',monospace;
                    font-size:0.63rem;color:#3d4f61;align-items:center">
                    <span>{m['date']}</span>
                    <span>·</span>
                    <span style="text-transform:uppercase">{m['horizon']}</span>
                    <span>·</span>
                    <span style="color:{dir_c}">{dir_icon}</span>
                  </div>
                </div>
                """, unsafe_allow_html=True)
                if st.button("View Report", key=f"rpt_{m['name']}", use_container_width=True):
                    st.session_state["reports_selected"] = m["name"]
                    st.rerun()


# ── Tab: Maya Filings ─────────────────────────────────────────────────────────

def _render_maya_filing_card(rep, show_source: bool = True) -> None:
    """Render a single Maya filing card with title, date, link, and fetch-source badge."""
    impact    = getattr(rep, "impact", "neutral").lower()
    ic        = {"bullish": "#39d353", "bearish": "#f85149"}.get(impact, "#57657a")
    title_raw = rep.title or ""
    title_s   = title_raw[:90] + ("…" if len(title_raw) > 90 else "")
    date_s    = rep.published[:10] if getattr(rep, "published", "") else ""
    rtype     = getattr(rep, "report_type", "") or ""
    reason    = getattr(rep, "impact_reason", "") or ""
    link_url  = getattr(rep, "link", "") or ""
    fetch_path = getattr(rep, "fetch_path", "")

    # LIVE badge (green=Playwright real-time, amber=DDG indexed)
    if "playwright" in fetch_path:
        src_badge = ('<span style="font-family:\'JetBrains Mono\',monospace;font-size:0.58rem;'
                     'color:#39d353;border:1px solid rgba(57,211,83,0.3);padding:1px 5px;'
                     'border-radius:2px;margin-left:6px">LIVE</span>')
    elif fetch_path:
        src_badge = ('<span style="font-family:\'JetBrains Mono\',monospace;font-size:0.58rem;'
                     'color:#e3a00a;border:1px solid rgba(227,160,10,0.3);padding:1px 5px;'
                     'border-radius:2px;margin-left:6px">DDG</span>')
    else:
        src_badge = ""

    link_html   = (f'<a href="{link_url}" target="_blank" '
                   f'style="color:#4d9de0;font-family:\'JetBrains Mono\',monospace;'
                   f'font-size:0.68rem;text-decoration:none">Maya →</a>'
                   if link_url.startswith("http") else "")
    reason_html = (f'<div style="font-size:0.75rem;color:#57657a;margin-top:3px;'
                   f'font-style:italic">{reason[:110]}</div>' if reason else "")
    meta_parts  = [p for p in [date_s, rtype.replace("_", " ").title()] if p]
    meta_s      = " · ".join(meta_parts)

    st.markdown(f"""
    <div class="bk-feed" style="margin-bottom:6px;border-left:2px solid {ic}22;padding:10px 14px">
      <div style="font-size:0.88rem;color:#c9d1d9;line-height:1.4">{title_s}{src_badge if show_source else ""}</div>
      <div style="font-family:\'JetBrains Mono\',monospace;font-size:0.62rem;color:#57657a;
                  margin-top:4px;display:flex;justify-content:space-between;align-items:center">
        <span>{meta_s}</span>
        {link_html}
      </div>
      {reason_html}
    </div>""", unsafe_allow_html=True)


def tab_maya():
    st.markdown(
        '<div style="font-family:\'Barlow Condensed\',sans-serif;font-size:1.4rem;font-weight:900;'
        'letter-spacing:0.12em;text-transform:uppercase;margin:16px 0 4px;color:#c9d1d9">'
        'Maya Disclosures</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="font-size:0.8rem;color:#57657a;margin-bottom:16px;'
        'font-family:\'JetBrains Mono\',monospace">'
        'Live TASE regulatory filings &mdash; AI-assessed impact</div>',
        unsafe_allow_html=True,
    )

    # ── Company filings lookup ─────────────────────────────────────────────────
    st.markdown(
        '<div style="font-family:\'Barlow Condensed\',sans-serif;font-weight:700;font-size:0.78rem;'
        'letter-spacing:0.18em;text-transform:uppercase;color:#4d9de0;'
        'border-bottom:1px solid #1d2433;padding-bottom:6px;margin-bottom:12px">'
        'Company Filings Lookup</div>',
        unsafe_allow_html=True,
    )
    with st.form(key="maya_stock_lookup_form"):
        col_t, col_n, col_b = st.columns([2, 1, 1])
        with col_t:
            lookup_ticker = st.text_input(
                "Ticker",
                placeholder="e.g. LUMI, ESLT, PTNR",
                label_visibility="collapsed",
                key="maya_lookup_ticker_input",
            ).strip().upper().replace(".TA", "")
        with col_n:
            lookup_n = st.selectbox(
                "Filings",
                [10, 15, 20],
                index=0,
                label_visibility="collapsed",
                key="maya_lookup_n",
            )
        with col_b:
            fetch_clicked = st.form_submit_button(
                "Fetch Filings", type="primary", use_container_width=True
            )

    if fetch_clicked and lookup_ticker:
        from borkai.data.maya_fetcher import fetch_company_reports_simple

        with st.spinner(f"Fetching Maya filings for {lookup_ticker} …"):
            try:
                reports, name_he_resolved, debug_note = fetch_company_reports_simple(
                    ticker=lookup_ticker,
                    max_items=lookup_n,
                )
            except Exception as _e:
                reports, name_he_resolved, debug_note = [], lookup_ticker, str(_e)

        # Show debug info: ticker → table → Hebrew name
        from borkai.data.stock_master import get_master_table as _gmt
        _row = _gmt().lookup_by_ticker(lookup_ticker)
        if _row:
            st.markdown(
                f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.72rem;'
                f'color:#57657a;margin-bottom:8px">'
                f'✓ Table match: <span style="color:#c9d1d9">{name_he_resolved}</span>'
                f' &nbsp;·&nbsp; sec# {_row.security_number or "—"}'
                f' &nbsp;·&nbsp; sector: {_row.sector or "—"}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.72rem;'
                f'color:#e3a00a;margin-bottom:8px">'
                f'⚠ Ticker not in table — using: '
                f'<span style="color:#c9d1d9">{name_he_resolved}</span></div>',
                unsafe_allow_html=True,
            )

        st.session_state["maya_stock_cache"] = {
            "ticker":   lookup_ticker,
            "name_he":  name_he_resolved,
            "reports":  reports,
            "debug":    debug_note,
        }

    # ── Display cached company filings ────────────────────────────────────
    stock_cache = st.session_state.get("maya_stock_cache")
    if stock_cache:
        ticker_disp  = stock_cache["ticker"]
        name_he_disp = stock_cache["name_he"]
        reps         = stock_cache["reports"]
        debug_disp   = stock_cache.get("debug", "")

        st.markdown(
            f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.7rem;'
            f'color:#57657a;margin:4px 0 10px">'
            f'{len(reps)} filings for <span style="color:#c9d1d9">{ticker_disp} / {name_he_disp}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        if reps:
            for rep in reps:
                _render_maya_filing_card(rep, show_source=False)
        else:
            detail = debug_disp if debug_disp else "no filings found"
            st.markdown(
                f'<div style="color:#f85149;font-family:\'JetBrains Mono\',monospace;'
                f'font-size:0.78rem;padding:12px 0">'
                f'FILINGS_FETCH_FAILED &nbsp;·&nbsp; {ticker_disp} / {name_he_disp}'
                f'<br>stage: {detail}</div>',
                unsafe_allow_html=True,
            )

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    st.markdown(
        '<div style="font-family:\'Barlow Condensed\',sans-serif;font-weight:700;font-size:0.78rem;'
        'letter-spacing:0.18em;text-transform:uppercase;color:#57657a;'
        'border-bottom:1px solid #1d2433;padding-bottom:6px;margin-bottom:12px">'
        'Market Feed</div>',
        unsafe_allow_html=True,
    )

    maya_cache = st.session_state.get("maya_cache", [])
    ts = st.session_state.get("maya_ts")
    age = f"Updated {int((datetime.now()-ts).total_seconds()/60)}m ago" if ts else "Not loaded"

    c1, c2 = st.columns([1, 4])
    with c1:
        do_refresh = st.button("Refresh Feed", key="maya_refresh_btn", type="primary", use_container_width=True)
    with c2:
        st.markdown(f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:0.72rem;color:#57657a">{age}</span>', unsafe_allow_html=True)

    if do_refresh:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            st.error("OPENAI_API_KEY not set."); return
        try:
            import openai as _openai
            from borkai.config import load_config
            from borkai.data.maya_fetcher import get_maya_reports
            client = _openai.OpenAI(api_key=api_key)
            config = load_config()
            tickers_data = _load_tase_tickers()
            with st.spinner("Fetching Maya filings…"):
                reports = get_maya_reports(client=client, config=config, known_stocks=tickers_data, max_reports=40)
            st.session_state["maya_cache"] = reports
            st.session_state["maya_ts"] = datetime.now()
            maya_cache = reports
            st.success(f"Loaded {len(reports)} filings.")
        except Exception as e:
            st.error(f"Failed: {e}"); return

    if not maya_cache:
        st.markdown(
            '<div style="padding:32px 0;text-align:center;color:#57657a;'
            'font-family:\'JetBrains Mono\',monospace;font-size:0.8rem">'
            'Click Refresh to load the latest TASE filings.</div>',
            unsafe_allow_html=True,
        )
        return

    impact_f = st.selectbox("Filter by impact", ["all", "bullish", "bearish", "neutral"],
                             key="maya_impact_filter",
                             format_func=lambda x: x.capitalize())
    filtered = maya_cache if impact_f == "all" else [r for r in maya_cache if getattr(r, "impact", "neutral").lower() == impact_f]

    st.markdown(f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.7rem;color:#57657a;margin-bottom:8px">{len(filtered)} / {len(maya_cache)} filings</div>', unsafe_allow_html=True)

    for rep in filtered:
        _render_maya_filing_card(rep, show_source=False)


# ── Tab: Hot Stocks ───────────────────────────────────────────────────────────

def tab_hot():
    st.markdown(
        '<div style="font-family:\'Barlow Condensed\',sans-serif;font-size:1.4rem;font-weight:900;'
        'letter-spacing:0.12em;text-transform:uppercase;margin:16px 0 4px;color:#c9d1d9">'
        'Hot Stocks</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="font-size:0.8rem;color:#57657a;margin-bottom:16px;'
        'font-family:\'JetBrains Mono\',monospace">'
        'TASE momentum: price above MA20 + positive news sentiment</div>',
        unsafe_allow_html=True,
    )

    tickers_data = _load_tase_tickers()
    if not tickers_data:
        st.warning(f"No ticker data found at {TICKERS_CSV}")
        return

    hot_cache = st.session_state.get("hot_cache", [])
    ts = st.session_state.get("hot_ts")
    age = f"Computed {int((datetime.now()-ts).total_seconds()/60)}m ago" if ts else "Not computed"

    c1, c2 = st.columns([1, 4])
    with c1:
        do_refresh = st.button("Compute Momentum", key="hot_refresh_btn", type="primary", use_container_width=True)
    with c2:
        st.markdown(f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:0.72rem;color:#57657a">{age}</span>', unsafe_allow_html=True)

    if do_refresh:
        st.session_state.pop("hot_cache", None)
        hot_cache = []

    if not hot_cache:
        if do_refresh:
            results = []
            with st.spinner(f"Computing momentum for {len(tickers_data)} stocks..."):
                try:
                    import yfinance as yf
                    for tk in tickers_data[:50]:  # limit to 50 for speed
                        ticker = tk.get("ticker", "")
                        company = tk.get("name", ticker)
                        if not ticker:
                            continue
                        try:
                            hist = yf.Ticker(ticker + ".TA").history(period="1mo")
                            if len(hist) >= 5:
                                close = hist["Close"]
                                sma = close.rolling(min(20, len(close))).mean().iloc[-1]
                                price = close.iloc[-1]
                                pct = (price - sma) / sma * 100 if sma > 0 else 0
                                if pct > 2:
                                    results.append({"ticker": ticker, "company": company,
                                                    "sector": tk.get("sector", ""), "pct": round(pct, 1)})
                        except Exception:
                            pass
                except Exception as e:
                    st.error(f"yfinance error: {e}")
            results.sort(key=lambda x: x["pct"], reverse=True)
            st.session_state["hot_cache"] = results
            st.session_state["hot_ts"] = datetime.now()
            hot_cache = results

    if not hot_cache:
        st.info("Click **Compute Momentum** to scan TASE stocks above MA20.")
        return

    cols = st.columns(3)
    for i, s in enumerate(hot_cache[:15]):
        c = _score_color(min(int(s["pct"] * 2), 100))
        with cols[i % 3]:
            st.markdown(f"""
            <div class="bk-card" style="padding:12px 14px;margin-bottom:4px">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <span style="font-family:\'JetBrains Mono\',monospace;font-weight:700;color:#4d9de0;font-size:1rem">{s["ticker"]}</span>
                <span class="bk-badge" style="background:{c}18;color:{c}">+{s["pct"]}% MA</span>
              </div>
              <div style="font-size:0.8rem;color:#57657a;margin-top:2px">{s["company"]}</div>
              <div class="bk-bar-wrap" style="margin-top:8px">
                <div class="bk-bar-fill" style="width:{min(s["pct"]*5,100)}%;background:{c}"></div>
              </div>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"Analyze {s['ticker']}", key=f"hot_analyze_{i}", use_container_width=True):
                st.session_state["prefill_ticker"] = s["ticker"]
                st.session_state["go_to_analyze"] = True
                st.rerun()


# ── Tab: Live Scan ────────────────────────────────────────────────────────────

_CAT_META = [
    ("BREAKOUT",         "🔥 Breakout Candidates",   "#4d9de0",
     "Price surge confirmed by heavy volume"),
    ("EARLY_MOVER",      "📊 Early Movers",          "#e3a00a",
     "Volume leading — price hasn't caught up yet"),
    ("STRONG_MOMENTUM",  "🚀 Strong Momentum",       "#39d353",
     "Multi-day directional build-up"),
    ("UNUSUAL_ACTIVITY", "⚡ Unusual Activity",      "#f85149",
     "Abnormal volume or sudden behaviour change"),
]

_TREND_ICON = {
    "heating": "↑↑",
    "stable":  "→",
    "cooling": "↓↓",
    "new":     "new",
}


def tab_live_scan():
    st.markdown(
        '<div style="font-family:\'Barlow Condensed\',sans-serif;font-size:1.4rem;font-weight:900;'
        'letter-spacing:0.12em;text-transform:uppercase;margin:16px 0 4px;color:#c9d1d9">'
        'Live Scan</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="font-size:0.8rem;color:#57657a;margin-bottom:16px;'
        'font-family:\'JetBrains Mono\',monospace">'
        'Zero-API continuous scanner — pure yfinance, no tokens consumed</div>',
        unsafe_allow_html=True,
    )

    # ── Controls ──────────────────────────────────────────────────────────────
    ctrl1, ctrl2, ctrl3, ctrl4, ctrl5 = st.columns([2, 2, 2, 2, 2])
    with ctrl1:
        size_filter = st.selectbox(
            "Market Cap",
            ["", "large", "mid", "small"],
            format_func=lambda x: x.capitalize() if x else "All",
            key="lscan_size",
        )
    with ctrl2:
        min_score = st.selectbox(
            "Min Score",
            [1, 2, 3, 4, 5],
            index=1,
            key="lscan_min_score",
        )
    with ctrl3:
        auto_on = st.toggle("Auto-Refresh", value=False, key="lscan_auto_on")
    with ctrl4:
        auto_min = st.selectbox(
            "Refresh Every",
            [5, 10, 15, 30],
            index=1,
            format_func=lambda x: f"{x} min",
            disabled=not auto_on,
            key="lscan_auto_min",
        )
    with ctrl5:
        st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
        do_scan = st.button("⚡  Scan Now", type="primary", use_container_width=True, key="lscan_btn")

    # ── Auto-refresh logic ────────────────────────────────────────────────────
    last_ts   = st.session_state.get("lscan_ts")
    scan_data = st.session_state.get("lscan_data")

    should_scan = do_scan
    if auto_on and last_ts is not None and scan_data is not None:
        elapsed_sec = (datetime.now() - last_ts).total_seconds()
        if elapsed_sec >= auto_min * 60:
            should_scan = True

    # ── Run scan ──────────────────────────────────────────────────────────────
    if should_scan:
        with st.spinner("Scanning TASE universe — downloading 30D OHLCV data..."):
            try:
                live_results, categories, index_change = _run_live_scan(
                    size_filter=size_filter or None,
                    min_score=min_score,
                    top_n=40,
                )
                st.session_state["lscan_data"] = (live_results, categories, index_change)
                st.session_state["lscan_ts"]   = datetime.now()
                scan_data = st.session_state["lscan_data"]
                last_ts   = st.session_state["lscan_ts"]
            except Exception as e:
                st.error(f"Scan failed: {e}")
                return

    # ── Empty state ───────────────────────────────────────────────────────────
    if scan_data is None:
        st.markdown("""
        <div style="text-align:center;padding:60px 20px;color:#3d4f61;font-family:'JetBrains Mono',monospace">
          <div style="font-size:2rem;margin-bottom:12px">⚡</div>
          <div style="font-size:0.85rem;letter-spacing:0.1em;text-transform:uppercase">
            Click <strong style="color:#4d9de0">Scan Now</strong> to scan the full TASE universe
          </div>
          <div style="font-size:0.72rem;margin-top:8px;color:#57657a">
            No AI — no API calls — pure yfinance market data
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    live_results, categories, index_change = scan_data

    # ── KPI cards ─────────────────────────────────────────────────────────────
    ts_str  = last_ts.strftime("%H:%M:%S") if last_ts else "—"
    n_scored = len([r for r in live_results if r.live_score >= min_score])
    n_breakout = len(categories.get("BREAKOUT", []))
    n_early    = len(categories.get("EARLY_MOVER", []))
    idx_color  = "#39d353" if index_change >= 0 else "#f85149"

    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    for col, label, value, color in [
        (kpi1, "Last Scan",    ts_str,           "#4d9de0"),
        (kpi2, "Stocks Scored", str(n_scored),   "#c9d1d9"),
        (kpi3, "TA-125",       f"{index_change:+.2f}%", idx_color),
        (kpi4, "Breakouts",    str(n_breakout),  "#4d9de0"),
        (kpi5, "Early Movers", str(n_early),     "#e3a00a"),
    ]:
        with col:
            st.markdown(f"""
            <div class="bk-kpi-card">
              <div class="bk-kpi-label">{label}</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:1.5rem;
                font-weight:700;color:{color}">{value}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

    # ── Category sections ─────────────────────────────────────────────────────
    for cat_key, cat_label, cat_color, cat_desc in _CAT_META:
        members = categories.get(cat_key, [])

        # Section header
        st.markdown(f"""
        <div class="bk-section-hdr">
          <span style="font-family:'JetBrains Mono',monospace;font-size:1.1rem">{cat_label.split()[0]}</span>
          <span class="bk-section-hdr-label" style="color:{cat_color}">
            {" ".join(cat_label.split()[1:])} &nbsp;
            <span style="color:#3d4f61;font-weight:400">({len(members)})</span>
          </span>
          <div class="bk-section-hdr-line"></div>
          <span style="font-family:'JetBrains Mono',monospace;font-size:0.65rem;
            color:#3d4f61;white-space:nowrap">{cat_desc}</span>
        </div>
        """, unsafe_allow_html=True)

        if not members:
            st.markdown(
                '<div style="color:#3d4f61;font-family:\'JetBrains Mono\',monospace;'
                'font-size:0.75rem;padding:8px 0 16px">No stocks this cycle</div>',
                unsafe_allow_html=True,
            )
            continue

        # Stock cards in a 3-column grid
        cols = st.columns(3)
        for i, r in enumerate(members[:9]):
            trend_icon = _TREND_ICON.get(r.trend, "")
            delta_str  = f" ({r.score_delta:+.0f})" if r.score_delta else ""
            sc_col     = _scanner_score_color(r.live_score)
            vol_str    = f"{r.volume_ratio:.1f}x" if r.volume_ratio else "—"
            pct_str    = f"{r.price_change_1d:+.1f}%" if r.price_change_1d is not None else "—"
            pct_col    = "#39d353" if (r.price_change_1d or 0) >= 0 else "#f85149"
            sigs       = "; ".join(r.signals[:2]) or "—"
            ticker_disp = r.ticker.replace(".TA", "")

            with cols[i % 3]:
                st.markdown(f"""
                <div class="bk-card" style="padding:12px 14px;margin-bottom:4px;
                  border-left:2px solid {cat_color}20">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
                    <span style="font-family:'JetBrains Mono',monospace;font-weight:700;
                      color:#4d9de0;font-size:1rem">{ticker_disp}</span>
                    <span style="font-family:'JetBrains Mono',monospace;font-weight:700;
                      color:{sc_col};font-size:1rem">{r.live_score}</span>
                  </div>
                  <div style="font-size:0.78rem;color:#57657a;margin-bottom:6px;
                    white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{r.name[:30]}</div>
                  <div style="display:flex;gap:10px;font-family:'JetBrains Mono',monospace;
                    font-size:0.72rem;margin-bottom:6px">
                    <span style="color:{pct_col}">{pct_str}</span>
                    <span style="color:#57657a">Vol {vol_str}</span>
                    <span style="color:#3d4f61">{trend_icon}{delta_str}</span>
                  </div>
                  <div style="font-size:0.68rem;color:#3d4f61;margin-bottom:8px;
                    white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{sigs}</div>
                </div>
                """, unsafe_allow_html=True)
                if st.button(f"→ Analyze {ticker_disp}", key=f"lscan_{cat_key}_{r.ticker}",
                             use_container_width=True):
                    st.session_state["scanner_prefill"] = ticker_disp
                    st.session_state["go_to_analyze"]   = True
                    st.rerun()

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Full ranked table ─────────────────────────────────────────────────────
    with st.expander(f"📋  Full Ranked List ({len(live_results)} stocks)", expanded=False):
        # Filter controls
        tf1, tf2 = st.columns([3, 1])
        with tf1:
            tbl_min = st.slider("Min score", 0, 10, min_score,
                                key="lscan_tbl_min", label_visibility="collapsed")
        with tf2:
            show_n = st.selectbox("Show", [20, 40, 80, 200], index=1,
                                  key="lscan_tbl_n", label_visibility="collapsed")

        filtered = [r for r in live_results if r.live_score >= tbl_min][:show_n]

        rows_html = ""
        for i, r in enumerate(filtered, 1):
            sc_col   = _scanner_score_color(r.live_score)
            pct_str  = f"{r.price_change_1d:+.1f}%" if r.price_change_1d is not None else "—"
            pct5_str = f"{r.price_change_5d:+.1f}%" if r.price_change_5d is not None else "—"
            vol_str  = f"{r.volume_ratio:.1f}x" if r.volume_ratio else "—"
            trend_ic = _TREND_ICON.get(r.trend, "")
            cats_str = " ".join(
                {"BREAKOUT":"🔥","EARLY_MOVER":"📊","STRONG_MOMENTUM":"🚀","UNUSUAL_ACTIVITY":"⚡"}.get(c,"")
                for c in r.categories
            )
            ticker_disp = r.ticker.replace(".TA", "")
            bg = "#0d1117" if i % 2 == 0 else "#111820"
            rows_html += f"""
            <tr style="background:{bg}">
              <td style="color:#3d4f61;text-align:center">{i}</td>
              <td style="font-family:'JetBrains Mono',monospace;font-weight:700;color:#4d9de0">{ticker_disp}</td>
              <td style="color:#c9d1d9;font-size:0.83rem">{r.name[:24]}</td>
              <td style="font-family:'JetBrains Mono',monospace;font-weight:700;
                color:{sc_col};text-align:center">{r.live_score}</td>
              <td style="font-family:'JetBrains Mono',monospace;color:#57657a;text-align:center">{r.heat_score:.1f}</td>
              <td style="font-family:'JetBrains Mono',monospace;
                color:{'#39d353' if (r.price_change_1d or 0)>=0 else '#f85149'};text-align:center">{pct_str}</td>
              <td style="font-family:'JetBrains Mono',monospace;color:#57657a;text-align:center">{pct5_str}</td>
              <td style="font-family:'JetBrains Mono',monospace;color:#57657a;text-align:center">{vol_str}</td>
              <td style="color:#57657a;text-align:center">{trend_ic}</td>
              <td style="text-align:center;font-size:0.9rem">{cats_str}</td>
            </tr>"""

        st.markdown(f"""
        <table style="width:100%;border-collapse:collapse;font-size:0.82rem">
          <thead>
            <tr style="border-bottom:1px solid #1d2433">
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px 8px;text-align:center">#</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px 8px;text-align:left">Ticker</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px 8px;text-align:left">Name</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px 8px;text-align:center">Score</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px 8px;text-align:center">Heat</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px 8px;text-align:center">1D%</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px 8px;text-align:center">5D%</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px 8px;text-align:center">Vol</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px 8px;text-align:center">Trend</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px 8px;text-align:center">Cats</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
        """, unsafe_allow_html=True)

    # ── Quick Analyze picker ──────────────────────────────────────────────────
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    st.markdown(
        '<div style="font-family:\'Barlow Condensed\',sans-serif;font-weight:700;'
        'font-size:0.78rem;letter-spacing:0.15em;text-transform:uppercase;'
        'color:#57657a;margin-bottom:8px">Quick Analyze</div>',
        unsafe_allow_html=True,
    )
    qa1, qa2 = st.columns([4, 1])
    with qa1:
        ticker_opts = [r.ticker.replace(".TA", "") for r in live_results if r.live_score >= min_score]
        if not ticker_opts:
            ticker_opts = [r.ticker.replace(".TA", "") for r in live_results[:20]]
        qa_pick = st.selectbox(
            "Pick stock to analyze",
            ticker_opts,
            key="lscan_qa_pick",
            label_visibility="collapsed",
        )
    with qa2:
        if st.button("→ Analyze", key="lscan_qa_go", use_container_width=True):
            st.session_state["scanner_prefill"] = qa_pick
            st.session_state["go_to_analyze"]   = True
            st.rerun()


# ── Tab: Scanner ──────────────────────────────────────────────────────────────

def _run_full_stock_scan(size_filter=None):
    """
    Load ALL stocks from tase_stocks.csv and run a Layer-1 fast scan.
    Every row is attempted. Returns (l1_results, scannable, skipped, name_he_map).
    l1_results contains one entry per scannable stock — either scored or with error.
    """
    from borkai.scanner.live_scanner import _load_stocks_with_skipped
    from borkai.scanner.layer1_fast_scan import run_layer1

    csv_path = os.path.join(_APP_DIR, "borkai", "data", "tase_stocks.csv")
    scannable, skipped = _load_stocks_with_skipped(csv_path, size_filter)
    name_he_map = {s["ticker"]: s.get("name_he", "") for s in scannable}

    l1_results = run_layer1(scannable, verbose=True)

    # Guarantee: every scannable stock has a result entry
    covered = {r.ticker for r in l1_results}
    for s in scannable:
        if s["ticker"] not in covered:
            from borkai.scanner.layer1_fast_scan import Layer1Result
            l1_results.append(Layer1Result(
                ticker=s["ticker"],
                name=s["name"],
                sector=s.get("sector", ""),
                error="no_market_data",
            ))

    return l1_results, scannable, skipped, name_he_map


def _scanner_reason_label(error: str) -> str:
    """Human-readable failure reason for scanner display."""
    return {
        "no_market_data": "No market data (delisted or not on yfinance)",
        "batch download failed": "Download failed",
    }.get(error, error)


def tab_scanner():
    st.markdown(
        '<div style="font-family:\'Barlow Condensed\',sans-serif;font-size:1.4rem;font-weight:900;'
        'letter-spacing:0.12em;text-transform:uppercase;margin:16px 0 4px;color:#c9d1d9">'
        'Market Scanner</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="font-size:0.8rem;color:#57657a;margin-bottom:16px;'
        'font-family:\'JetBrains Mono\',monospace">'
        'Full TASE universe scan — every stock from tase_stocks, zero AI tokens</div>',
        unsafe_allow_html=True,
    )

    # ── Controls ──────────────────────────────────────────────────────────────
    ctrl1, ctrl2, ctrl3 = st.columns([3, 3, 2])
    with ctrl1:
        size_filter = st.selectbox(
            "Market Cap",
            ["", "large", "mid", "small"],
            format_func=lambda x: x.capitalize() if x else "All sizes",
            key="scanner_size",
        )
    with ctrl2:
        min_score = st.selectbox(
            "Min Score (ranked table)",
            [0, 1, 2, 3, 4, 5],
            index=0,
            key="scanner_min_score",
        )
    with ctrl3:
        st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
        do_scan = st.button(
            "Scan All Stocks", type="primary", use_container_width=True, key="scanner_btn"
        )

    # ── Run scan ──────────────────────────────────────────────────────────────
    if do_scan:
        with st.spinner("Scanning all stocks from tase_stocks table via yfinance…"):
            try:
                l1_results, scannable, skipped, name_he_map = _run_full_stock_scan(
                    size_filter=size_filter or None
                )
                st.session_state["scanner_all_data"] = {
                    "l1":         l1_results,
                    "scannable":  scannable,
                    "skipped":    skipped,
                    "name_he_map":name_he_map,
                    "ts":         datetime.now(),
                    "size_filter":size_filter,
                }
            except Exception as e:
                st.error(f"Scan failed: {e}")
                return

    # ── Empty state ───────────────────────────────────────────────────────────
    data = st.session_state.get("scanner_all_data")
    if data is None:
        st.markdown("""
        <div style="text-align:center;padding:60px 20px;color:#3d4f61;
          font-family:'JetBrains Mono',monospace">
          <div style="font-size:2rem;margin-bottom:12px">📊</div>
          <div style="font-size:0.85rem;letter-spacing:0.1em;text-transform:uppercase">
            Click <strong style="color:#4d9de0">Scan All Stocks</strong>
            to scan every stock from tase_stocks
          </div>
          <div style="font-size:0.72rem;margin-top:8px;color:#57657a">
            Every row is processed · No AI · Pure yfinance
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    l1_results  = data["l1"]
    scannable   = data["scannable"]
    skipped     = data["skipped"]
    name_he_map = data["name_he_map"]
    ts          = data["ts"]

    scanned_ok  = [r for r in l1_results if r.error is None]
    scanned_err = [r for r in l1_results if r.error is not None]

    # Breakdown of skipped rows by reason
    from collections import Counter
    skip_reasons = Counter(s["reason"] for s in skipped)
    n_no_ticker   = skip_reasons.get("no ticker", 0)
    n_size_filt   = sum(v for k, v in skip_reasons.items() if k != "no ticker")
    n_total_csv   = len(scannable) + len(skipped)

    # Verify coverage: every scannable stock accounted for
    n_covered = len(scanned_ok) + len(scanned_err)

    # ── Stats header ──────────────────────────────────────────────────────────
    kc1, kc2, kc3, kc4, kc5 = st.columns(5)
    for col, label, value, color in [
        (kc1, "In tase_stocks",  str(n_total_csv),     "#c9d1d9"),
        (kc2, "Scored",          str(len(scanned_ok)),  "#39d353"),
        (kc3, "No Market Data",  str(len(scanned_err)),
            "#f85149" if scanned_err else "#57657a"),
        (kc4, "Missing Ticker",  str(n_no_ticker),
            "#e3a00a" if n_no_ticker else "#57657a"),
        (kc5, "Size-filtered",   str(n_size_filt),
            "#4d9de0" if n_size_filt else "#57657a"),
    ]:
        with col:
            st.markdown(f"""
            <div class="bk-kpi-card">
              <div class="bk-kpi-label">{label}</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:1.5rem;
                font-weight:700;color:{color}">{value}</div>
            </div>
            """, unsafe_allow_html=True)

    if n_covered < len(scannable):
        st.warning(
            f"Coverage gap: {len(scannable) - n_covered} stocks in tase_stocks "
            f"have no result entry — re-run the scan."
        )

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # ── Ranked scored stocks ──────────────────────────────────────────────────
    ranked = [r for r in scanned_ok if r.total_score >= min_score]
    # scanned_ok is already sorted by score desc (from run_layer1)

    st.markdown(
        f'<div style="font-family:\'Barlow Condensed\',sans-serif;font-weight:700;'
        f'font-size:0.85rem;letter-spacing:0.15em;text-transform:uppercase;'
        f'margin:8px 0 6px;color:#57657a">'
        f'SCORED STOCKS — {len(ranked)} of {len(scanned_ok)} (score ≥ {min_score})</div>',
        unsafe_allow_html=True,
    )

    def _build_scored_table(rows):
        rows_html = ""
        for i, r in enumerate(rows, 1):
            name_he     = name_he_map.get(r.ticker, "")
            ticker_disp = r.ticker.replace(".TA", "")
            sc_col      = _scanner_score_color(r.total_score)
            pct_str     = f"{r.price_change_1d:+.1f}%" if r.price_change_1d is not None else "—"
            pct5_str    = f"{r.price_change_5d:+.1f}%" if r.price_change_5d is not None else "—"
            pct_col     = "#39d353" if (r.price_change_1d or 0) >= 0 else "#f85149"
            vol_str     = f"{r.volume_ratio:.1f}x" if r.volume_ratio else "—"
            mom_str     = f"{r.price_change_5d:+.1f}%" if r.price_change_5d is not None else "—"
            bg          = "#0d1117" if i % 2 == 0 else "#111820"
            rows_html += f"""
            <tr style="background:{bg}">
              <td style="color:#3d4f61;text-align:center;padding:5px 6px">{i}</td>
              <td style="font-family:'JetBrains Mono',monospace;font-weight:700;
                color:#4d9de0;padding:5px 6px">{ticker_disp}</td>
              <td style="color:#c9d1d9;font-size:0.82rem;padding:5px 6px">{r.name[:22]}</td>
              <td style="color:#57657a;font-size:0.78rem;padding:5px 6px;
                direction:rtl;text-align:right">{name_he[:20]}</td>
              <td style="color:#57657a;font-size:0.75rem;padding:5px 6px">{r.sector[:16]}</td>
              <td style="font-family:'JetBrains Mono',monospace;font-weight:700;
                color:{sc_col};text-align:center;padding:5px 6px">{r.total_score}</td>
              <td style="font-family:'JetBrains Mono',monospace;
                color:{pct_col};text-align:center;padding:5px 6px">{pct_str}</td>
              <td style="font-family:'JetBrains Mono',monospace;color:#57657a;
                text-align:center;padding:5px 6px">{pct5_str}</td>
              <td style="font-family:'JetBrains Mono',monospace;color:#57657a;
                text-align:center;padding:5px 6px">{vol_str}</td>
              <td style="color:#39d353;font-size:0.7rem;padding:5px 6px">scanned</td>
            </tr>"""
        return f"""
        <table style="width:100%;border-collapse:collapse;font-size:0.82rem">
          <thead>
            <tr style="border-bottom:1px solid #1d2433">
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px;text-align:center">#</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px">Ticker</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px">Name</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px;text-align:right">שם</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px">Sector</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px;text-align:center">Score</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px;text-align:center">1D%</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px;text-align:center">5D%</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px;text-align:center">Vol</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:6px">Status</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>"""

    st.markdown(_build_scored_table(ranked), unsafe_allow_html=True)

    # ── Quick Analyze picker ──────────────────────────────────────────────────
    if ranked:
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        qa1, qa2 = st.columns([4, 1])
        with qa1:
            qa_pick = st.selectbox(
                "Pick stock to analyze",
                [r.ticker.replace(".TA", "") for r in ranked],
                key="scanner_qa_pick",
                label_visibility="collapsed",
            )
        with qa2:
            if st.button("→ Analyze", key="scanner_qa_go", use_container_width=True):
                st.session_state["scanner_prefill"] = qa_pick
                st.session_state["go_to_analyze"]   = True
                st.rerun()

    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

    # ── Unscored stocks (always visible) ─────────────────────────────────────
    # Group errors by reason (Counter already imported above)
    reason_counts = Counter(r.error for r in scanned_err)

    st.markdown(
        f'<div style="font-family:\'Barlow Condensed\',sans-serif;font-weight:700;'
        f'font-size:0.85rem;letter-spacing:0.15em;text-transform:uppercase;'
        f'margin:8px 0 4px;color:#57657a">'
        f'UNSCORED STOCKS — {len(scanned_err)} stocks</div>',
        unsafe_allow_html=True,
    )

    # Reason summary chips
    if reason_counts:
        chips_html = " ".join(
            f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:0.7rem;'
            f'background:#1d2433;color:#57657a;padding:2px 8px;border-radius:2px;'
            f'margin-right:4px">{_scanner_reason_label(reason)}: {cnt}</span>'
            for reason, cnt in reason_counts.most_common()
        )
        st.markdown(chips_html, unsafe_allow_html=True)
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    if scanned_err:
        err_rows = ""
        for i, r in enumerate(scanned_err, 1):
            name_he     = name_he_map.get(r.ticker, "")
            ticker_disp = r.ticker.replace(".TA", "")
            bg          = "#0d1117" if i % 2 == 0 else "#111820"
            reason_lbl  = _scanner_reason_label(r.error)
            err_rows += f"""
            <tr style="background:{bg}">
              <td style="color:#3d4f61;text-align:center;padding:4px 6px">{i}</td>
              <td style="font-family:'JetBrains Mono',monospace;color:#57657a;
                padding:4px 6px">{ticker_disp}</td>
              <td style="color:#c9d1d9;font-size:0.82rem;padding:4px 6px">{r.name[:26]}</td>
              <td style="color:#57657a;font-size:0.78rem;padding:4px 6px;
                direction:rtl;text-align:right">{name_he[:22]}</td>
              <td style="color:#57657a;font-size:0.75rem;padding:4px 6px">{r.sector[:16]}</td>
              <td style="color:#f85149;font-size:0.72rem;padding:4px 6px">{reason_lbl}</td>
            </tr>"""

        st.markdown(f"""
        <table style="width:100%;border-collapse:collapse;font-size:0.82rem">
          <thead>
            <tr style="border-bottom:1px solid #1d2433">
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:5px 6px;text-align:center">#</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:5px 6px">Ticker</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:5px 6px">Name</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:5px 6px;text-align:right">שם</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:5px 6px">Sector</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:5px 6px">Reason not scored</th>
            </tr>
          </thead>
          <tbody>{err_rows}</tbody>
        </table>
        """, unsafe_allow_html=True)

    # ── Missing-ticker stocks (always visible) ────────────────────────────────
    no_ticker_stocks = [s for s in skipped if s["reason"] == "no ticker"]
    if no_ticker_stocks:
        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        st.markdown(
            f'<div style="font-family:\'Barlow Condensed\',sans-serif;font-weight:700;'
            f'font-size:0.85rem;letter-spacing:0.15em;text-transform:uppercase;'
            f'margin:8px 0 4px;color:#57657a">'
            f'MISSING TICKER — {len(no_ticker_stocks)} stocks (in tase_stocks but no yfinance ticker)</div>',
            unsafe_allow_html=True,
        )
        mt_rows = ""
        for i, s in enumerate(no_ticker_stocks, 1):
            bg = "#0d1117" if i % 2 == 0 else "#111820"
            sec_num = s.get("security_number", "")
            mt_rows += f"""
            <tr style="background:{bg}">
              <td style="color:#3d4f61;text-align:center;padding:4px 6px">{i}</td>
              <td style="color:#e3a00a;font-size:0.78rem;padding:4px 6px;
                direction:rtl">{s["name"][:30]}</td>
              <td style="color:#57657a;font-size:0.72rem;padding:4px 6px">{sec_num}</td>
              <td style="color:#f85149;font-size:0.72rem;padding:4px 6px">missing_ticker</td>
            </tr>"""
        st.markdown(f"""
        <table style="width:100%;border-collapse:collapse;font-size:0.82rem">
          <thead>
            <tr style="border-bottom:1px solid #1d2433">
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:5px 6px;text-align:center">#</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:5px 6px">Name (Hebrew)</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:5px 6px">Security #</th>
              <th style="color:#57657a;font-family:'JetBrains Mono',monospace;
                font-size:0.65rem;padding:5px 6px">Status</th>
            </tr>
          </thead>
          <tbody>{mt_rows}</tbody>
        </table>
        """, unsafe_allow_html=True)

    # ── Size-filtered stocks (collapsed) ─────────────────────────────────────
    size_filtered = [s for s in skipped if s["reason"] != "no ticker"]
    if size_filtered:
        with st.expander(f"Size-filtered Stocks ({len(size_filtered)})", expanded=False):
            for s in size_filtered:
                st.markdown(
                    f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.75rem;'
                    f'color:#57657a;padding:2px 0">'
                    f'<span style="color:#4d9de0">{s["ticker"]}</span>'
                    f' &nbsp;{s["name"]}'
                    f' &nbsp;<span style="color:#3d4f61">— {s["reason"]}</span></div>',
                    unsafe_allow_html=True,
                )


# ── Main ──────────────────────────────────────────────────────────────────────

render_hero()

# Handle "go to analyze" navigation from Live Scan / Hot Stocks tabs.
# scanner_prefill is still in session_state here (tab_analyze pops it later),
# so we can read the ticker before tab_analyze() runs.
if st.session_state.get("go_to_analyze"):
    del st.session_state["go_to_analyze"]
    ticker_hint = (
        st.session_state.get("scanner_prefill", "")
        or st.session_state.get("prefill_ticker", "")
    )
    # Inject JS to programmatically click the "Analyze" tab so the user
    # doesn't have to manually switch tabs.
    import streamlit.components.v1 as _stc
    _stc.html("""
    <script>
    (function() {
        function switchTab() {
            var tabs = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
            for (var i = 0; i < tabs.length; i++) {
                var txt = tabs[i].innerText || tabs[i].textContent || "";
                if (txt.trim().toUpperCase().indexOf("ANALYZE") === 0) {
                    tabs[i].click();
                    return true;
                }
            }
            return false;
        }
        // Retry a few times — the tab bar may not be in the DOM immediately
        var attempts = 0;
        var iv = setInterval(function() {
            if (switchTab() || ++attempts >= 8) clearInterval(iv);
        }, 80);
    })();
    </script>
    """, height=0)
    if ticker_hint:
        try:
            st.toast(f"**{ticker_hint}** pre-filled in the Analyze tab", icon="⚡")
        except AttributeError:
            pass  # older Streamlit without st.toast

TAB_NAMES = ["Analyze", "Live Scan", "Reports", "Maya Filings", "Hot Stocks", "Scanner"]
tabs = st.tabs(TAB_NAMES)

TAB_FUNCS = [tab_analyze, tab_live_scan, tab_reports, tab_maya, tab_hot, tab_scanner]
for tab, fn in zip(tabs, TAB_FUNCS):
    with tab:
        try:
            fn()
        except Exception as _err:
            import traceback
            st.error(f"Error: {_err}")
            with st.expander("Details"):
                st.code(traceback.format_exc())
