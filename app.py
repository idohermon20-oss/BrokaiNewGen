"""
Borkai Web App — Israeli Stock Analysis
Run with:  streamlit run app.py
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

# Load .env using absolute path so it works regardless of Streamlit's CWD
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_APP_DIR, ".env"))

# Ensure project root is on sys.path so `from main import analyze` works
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Borkai | Israeli Stock Intelligence",
    page_icon="▣",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Global CSS ────────────────────────────────────────────────────────────────
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
  --accent:      #4d9de0;
  --accent-glow: rgba(77,157,224,0.15);
  --green:       #39d353;
  --green-bg:    rgba(57,211,83,0.08);
  --red:         #f85149;
  --red-bg:      rgba(248,81,73,0.08);
  --amber:       #e3a00a;
  --amber-bg:    rgba(227,160,10,0.08);
  --cyan:        #00e5ff;
  --mono:        'JetBrains Mono', 'Courier New', monospace;
  --condensed:   'Barlow Condensed', sans-serif;
  --body:        'Karla', sans-serif;
}

/* ── Reset & Base ── */
* { box-sizing: border-box; }

html, body, .stApp {
  background-color: var(--bg) !important;
  color: var(--text);
  font-family: var(--body);
}

.main .block-container {
  padding-top: 0.5rem !important;
  padding-left: 1.5rem !important;
  padding-right: 1.5rem !important;
  max-width: 1440px;
}

/* ── Typography ── */
h1, h2, h3, h4, h5 {
  font-family: var(--condensed);
  color: var(--text);
  letter-spacing: 0.02em;
  text-transform: uppercase;
  font-weight: 700;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: var(--surface); }
::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 2px; }

/* ── Hero ── */
.bk-hero {
  position: relative;
  overflow: hidden;
  background: linear-gradient(180deg, #0a1220 0%, var(--bg) 100%);
  border-bottom: 1px solid var(--border);
  padding: 1.25rem 0 0.75rem 0;
  margin-bottom: 0;
}
.bk-hero::before {
  content: '';
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(77,157,224,0.018) 2px,
    rgba(77,157,224,0.018) 4px
  );
  pointer-events: none;
}
.bk-hero-wordmark {
  font-family: var(--condensed);
  font-weight: 900;
  font-size: 3.4rem;
  line-height: 1;
  letter-spacing: -0.01em;
  color: #fff;
  text-transform: uppercase;
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.bk-hero-wordmark-accent {
  color: var(--accent);
  font-size: 2rem;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  align-self: center;
  padding: 2px 10px;
  border: 1px solid var(--accent);
  border-radius: 3px;
  font-family: var(--mono);
}
.bk-hero-sub {
  font-family: var(--mono);
  font-size: 0.68rem;
  color: var(--text-muted);
  letter-spacing: 0.2em;
  text-transform: uppercase;
  margin-top: 4px;
}
.bk-hero-tags {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.bk-hero-tag {
  font-family: var(--mono);
  font-size: 0.64rem;
  color: var(--text-dim);
  border: 1px solid var(--border);
  padding: 2px 8px;
  border-radius: 2px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.bk-status-dot {
  display: inline-block;
  width: 6px; height: 6px;
  background: var(--green);
  border-radius: 50%;
  margin-right: 5px;
  animation: pulse 2.5s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 4px var(--green); }
  50%       { opacity: 0.4; box-shadow: none; }
}

/* ── Ticker strip ── */
.bk-ticker-strip {
  background: var(--surface);
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  padding: 5px 0;
  margin-top: 12px;
  overflow: hidden;
  font-family: var(--mono);
  font-size: 0.7rem;
  color: var(--text-muted);
  letter-spacing: 0.05em;
  white-space: nowrap;
}
.bk-ticker-inner {
  display: inline-flex;
  gap: 36px;
  animation: tickerScroll 28s linear infinite;
}
@keyframes tickerScroll {
  from { transform: translateX(0); }
  to   { transform: translateX(-50%); }
}
.bk-ticker-item { display: inline-flex; gap: 8px; align-items: center; }
.bk-ticker-up   { color: var(--green); }
.bk-ticker-down { color: var(--red); }

/* ── Navigation tabs ── */
.stTabs [data-baseweb="tab-list"] {
  background: transparent !important;
  border-bottom: 1px solid var(--border) !important;
  gap: 0 !important;
  padding: 0 !important;
  margin-bottom: 0 !important;
  border-radius: 0 !important;
}
.stTabs [data-baseweb="tab"] {
  font-family: var(--condensed) !important;
  font-weight: 700 !important;
  font-size: 0.82rem !important;
  letter-spacing: 0.12em !important;
  text-transform: uppercase !important;
  color: var(--text-muted) !important;
  padding: 10px 20px !important;
  border-radius: 0 !important;
  border-bottom: 2px solid transparent !important;
  background: transparent !important;
  margin-bottom: -1px !important;
}
.stTabs [aria-selected="true"] {
  color: var(--accent) !important;
  border-bottom: 2px solid var(--accent) !important;
  background: transparent !important;
}

/* ── Cards ── */
.bk-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 16px 20px;
  margin: 6px 0;
  position: relative;
}
.bk-card:hover { border-color: var(--border2); }

.bk-card-accent {
  border-left: 2px solid var(--accent);
}

/* ── Feed items ── */
.bk-feed-item {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--border2);
  border-radius: 0 4px 4px 0;
  padding: 10px 14px;
  margin: 5px 0;
  transition: border-color 0.15s, background 0.15s;
}
.bk-feed-item:hover { background: var(--surface2); }
.bk-feed-bullish { border-left-color: var(--green) !important; }
.bk-feed-bearish { border-left-color: var(--red)   !important; }
.bk-feed-neutral { border-left-color: var(--text-dim) !important; }

/* ── Verdict ── */
.bk-verdict {
  position: relative;
  border-radius: 4px;
  padding: 28px 24px;
  margin: 16px 0;
  text-align: center;
  overflow: hidden;
}
.bk-verdict::before {
  content: '';
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    45deg, transparent, transparent 8px,
    rgba(255,255,255,0.012) 8px, rgba(255,255,255,0.012) 16px
  );
  pointer-events: none;
}
.bk-verdict-yes  { background: var(--green-bg); border: 1px solid rgba(57,211,83,0.35); }
.bk-verdict-no   { background: var(--red-bg);   border: 1px solid rgba(248,81,73,0.35); }
.bk-verdict-cond { background: var(--amber-bg); border: 1px solid rgba(227,160,10,0.35); }

.bk-verdict-label {
  font-family: var(--condensed);
  font-weight: 900;
  font-size: 1rem;
  letter-spacing: 0.25em;
  text-transform: uppercase;
  opacity: 0.7;
  margin-bottom: 4px;
}
.bk-verdict-rec {
  font-family: var(--condensed);
  font-weight: 900;
  font-size: 2.6rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  line-height: 1;
}
.bk-verdict-score {
  font-family: var(--mono);
  font-weight: 700;
  font-size: 3.5rem;
  line-height: 1;
  margin: 10px 0 4px;
}
.bk-verdict-score-sub {
  font-family: var(--mono);
  font-size: 1rem;
  opacity: 0.45;
}
.bk-verdict-detail {
  font-size: 0.85rem;
  color: var(--text-muted);
  margin-top: 12px;
  max-width: 500px;
  margin-left: auto;
  margin-right: auto;
  line-height: 1.5;
}

/* ── Score bar ── */
.bk-bar-wrap {
  background: var(--border);
  border-radius: 1px;
  height: 5px;
  overflow: hidden;
  margin: 6px 0;
}
.bk-bar-fill {
  height: 5px;
  border-radius: 1px;
  transition: width 0.8s cubic-bezier(.22,.68,0,1.2);
}

/* ── Badges ── */
.bk-badge {
  display: inline-block;
  font-family: var(--mono);
  font-size: 0.64rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  padding: 2px 8px;
  border-radius: 2px;
  text-transform: uppercase;
}

/* ── Ticker label ── */
.bk-ticker-label {
  font-family: var(--mono);
  font-weight: 700;
  color: var(--accent);
  letter-spacing: 0.05em;
}

/* ── Sector cards ── */
.bk-sector-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 3px;
  margin: 3px 0;
  font-size: 0.85rem;
}
.bk-sector-row:hover { border-color: var(--border2); }

/* ── Hot stock card ── */
.bk-hot-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 14px 16px;
  margin: 5px 0;
  transition: border-color 0.15s, transform 0.1s;
}
.bk-hot-card:hover {
  border-color: var(--border2);
  transform: translateY(-1px);
}
.bk-hot-ticker  { font-family: var(--mono); font-size: 1.15rem; font-weight: 700; color: var(--accent); }
.bk-hot-company { font-size: 0.8rem; color: var(--text-muted); margin-top: 2px; }
.bk-hot-headline { font-size: 0.75rem; color: var(--text-muted); font-style: italic; margin-top: 8px; line-height: 1.4; }

/* ── Pipeline terminal ── */
.bk-terminal {
  background: #04080d;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 16px 20px;
  font-family: var(--mono);
  font-size: 0.78rem;
  color: #7fbd9e;
  line-height: 1.8;
  min-height: 120px;
}
.bk-terminal-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}
.bk-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.bk-dot-red    { background: #f85149; }
.bk-dot-amber  { background: var(--amber); }
.bk-dot-green  { background: var(--green); }
.bk-term-title { font-size: 0.65rem; color: var(--text-dim); letter-spacing: 0.15em; text-transform: uppercase; margin-left: 6px; }
.bk-term-line-ok   { color: var(--green); }
.bk-term-line-wait { color: var(--amber); }
.bk-term-line-dim  { color: var(--text-dim); }
.bk-term-prompt    { color: var(--accent); }

/* ── Report RTL ── */
.bk-report-rtl {
  direction: rtl;
  text-align: right;
  font-family: var(--body);
  font-size: 0.92rem;
  line-height: 1.75;
  color: var(--text);
}
.bk-report-rtl h1, .bk-report-rtl h2 {
  font-family: var(--condensed);
  text-transform: none;
  font-size: 1.4rem;
  margin: 1.5rem 0 0.5rem;
  color: #e6edf3;
  letter-spacing: 0;
}
.bk-report-rtl h3 { font-size: 1.1rem; color: #c9d1d9; text-transform: none; letter-spacing: 0; }
.bk-report-rtl table { width: 100%; border-collapse: collapse; margin: 12px 0; }
.bk-report-rtl th {
  background: var(--surface2);
  padding: 8px 12px;
  border: 1px solid var(--border);
  font-family: var(--mono);
  font-size: 0.72rem;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  text-transform: uppercase;
}
.bk-report-rtl td { padding: 8px 12px; border: 1px solid var(--border); font-size: 0.88rem; }
.bk-report-rtl tr:nth-child(even) { background: var(--surface2); }
.bk-report-rtl code, .bk-report-rtl pre {
  background: #04080d;
  border: 1px solid var(--border);
  border-radius: 3px;
  font-family: var(--mono);
  font-size: 0.78rem;
  color: #7fbd9e;
  direction: ltr;
  text-align: left;
}
.bk-report-rtl pre { padding: 12px 14px; overflow-x: auto; }
.bk-report-rtl code { padding: 1px 6px; }
.bk-report-rtl blockquote {
  border-right: 3px solid var(--accent);
  border-left: none;
  margin: 8px 0;
  padding: 4px 14px 4px 0;
  color: var(--text-muted);
}
.bk-report-rtl hr { border-color: var(--border); }

/* ── Ranking row ── */
.bk-rank-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 18px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 3px;
  margin: 4px 0;
  transition: border-color 0.15s;
}
.bk-rank-row:hover { border-color: var(--border2); }

/* ── Metrics ── */
[data-testid="stMetricValue"] {
  font-family: var(--mono) !important;
  font-size: 1.4rem !important;
  font-weight: 700 !important;
  color: var(--text) !important;
}
[data-testid="stMetricLabel"] {
  font-family: var(--condensed) !important;
  font-size: 0.7rem !important;
  letter-spacing: 0.12em !important;
  text-transform: uppercase !important;
  color: var(--text-muted) !important;
}

/* ── Inputs ── */
.stTextInput input, .stNumberInput input {
  background: var(--surface) !important;
  border: 1px solid var(--border2) !important;
  border-radius: 4px !important;
  color: var(--text) !important;
  font-family: var(--mono) !important;
  font-size: 0.9rem !important;
  padding: 10px 14px !important;
}
.stTextInput input:focus, .stNumberInput input:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 2px var(--accent-glow) !important;
}
.stSelectbox [data-baseweb="select"] > div {
  background: var(--surface) !important;
  border-color: var(--border2) !important;
  border-radius: 4px !important;
  font-family: var(--mono) !important;
  font-size: 0.85rem !important;
}
.stSelectbox [data-baseweb="popover"] { background: var(--surface2) !important; }

/* ── Buttons ── */
.stButton > button {
  background: transparent !important;
  border: 1px solid var(--border2) !important;
  color: var(--text) !important;
  font-family: var(--condensed) !important;
  font-weight: 700 !important;
  font-size: 0.8rem !important;
  letter-spacing: 0.12em !important;
  text-transform: uppercase !important;
  border-radius: 3px !important;
  padding: 8px 18px !important;
  transition: all 0.15s !important;
}
.stButton > button:hover {
  border-color: var(--accent) !important;
  color: var(--accent) !important;
  background: var(--accent-glow) !important;
}
.stButton > button[kind="primary"] {
  background: var(--accent) !important;
  border-color: var(--accent) !important;
  color: #fff !important;
}
.stButton > button[kind="primary"]:hover {
  background: #3d8ac7 !important;
  border-color: #3d8ac7 !important;
  color: #fff !important;
}

/* ── Progress ── */
.stProgress > div > div {
  background: var(--accent) !important;
  border-radius: 1px !important;
}
.stProgress > div {
  background: var(--border) !important;
  border-radius: 1px !important;
  height: 3px !important;
}

/* ── Expander ── */
.streamlit-expanderHeader {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: 4px !important;
  font-family: var(--condensed) !important;
  font-weight: 700 !important;
  font-size: 0.8rem !important;
  letter-spacing: 0.1em !important;
  text-transform: uppercase !important;
  color: var(--text) !important;
}
.streamlit-expanderContent {
  border: 1px solid var(--border) !important;
  border-top: none !important;
  border-radius: 0 0 4px 4px !important;
  background: var(--surface) !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
  background: var(--surface) !important;
  border-right: 1px solid var(--border) !important;
}

/* ── Status widget ── */
[data-testid="stStatus"] {
  background: var(--surface) !important;
  border-color: var(--border) !important;
  border-radius: 4px !important;
}

/* ── Divider ── */
hr { border-color: var(--border) !important; margin: 16px 0 !important; }

/* ── Misc Streamlit overrides ── */
[data-testid="stMarkdownContainer"] p { color: var(--text); font-family: var(--body); }
.stAlert { background: var(--surface) !important; border-color: var(--border) !important; border-radius: 4px !important; }
label, .stCheckbox p { font-family: var(--condensed) !important; font-size: 0.8rem !important; letter-spacing: 0.1em !important; text-transform: uppercase !important; color: var(--text-muted) !important; }
.stSlider [data-baseweb="slider"] { margin-top: 8px; }
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────
HORIZON_LABELS = {
    "short":  "Short  ·  1–4 Weeks",
    "medium": "Medium  ·  1–6 Months",
    "long":   "Long  ·  1–3 Years",
}
HORIZON_SHORT = {"short": "SHORT", "medium": "MED", "long": "LONG"}
REC_ICONS = {"YES": "✅", "NO": "❌", "CONDITIONAL": "⚠️"}
REPORTS_DIR = "reports"
TICKERS_CSV = "borkai/data/tase_stocks.csv"
CACHE_TTL_SECONDS = 3600

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_tase_tickers():
    import csv
    if not os.path.exists(TICKERS_CSV):
        return []
    with open(TICKERS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def list_scan_dates():
    if not os.path.exists(REPORTS_DIR):
        return []
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    dirs = [d for d in os.listdir(REPORTS_DIR)
            if os.path.isdir(os.path.join(REPORTS_DIR, d)) and pattern.match(d)]
    return sorted(dirs, reverse=True)


def load_ranking(scan_date: str, horizon: str):
    path = os.path.join(REPORTS_DIR, scan_date, horizon, "ranking_data.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_report_file(scan_date: str, horizon: str, filename: str) -> str:
    path = os.path.join(REPORTS_DIR, scan_date, horizon, "top", filename)
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_scan_progress(scan_date: str):
    path = os.path.join(REPORTS_DIR, scan_date, "scan_progress.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def score_color(score: int) -> str:
    if score >= 70: return "var(--green)"
    if score >= 45: return "var(--amber)"
    return "var(--red)"


def score_hex(score: int) -> str:
    if score >= 70: return "#39d353"
    if score >= 45: return "#e3a00a"
    return "#f85149"


def cache_age_seconds(cache_key: str, ts_key: str) -> float:
    ts = st.session_state.get(ts_key)
    if ts is None:
        return float("inf")
    return (datetime.now() - ts).total_seconds()


def render_verdict_card(rec: str, score: int, direction: str, conviction: str, rationale: str = ""):
    css_class = {
        "YES": "bk-verdict-yes",
        "NO": "bk-verdict-no",
        "CONDITIONAL": "bk-verdict-cond",
    }.get(rec.upper(), "bk-verdict-cond")
    rec_color = {"YES": "#39d353", "NO": "#f85149", "CONDITIONAL": "#e3a00a"}.get(rec.upper(), "#e3a00a")
    label = {"YES": "BUY", "NO": "AVOID", "CONDITIONAL": "CONDITIONAL"}.get(rec.upper(), rec)
    bar_color = score_hex(score)
    dir_label = {"up": "↑ Bullish", "down": "↓ Bearish", "mixed": "↔ Mixed"}.get(direction, direction)
    conv_star = {"high": "★★★", "moderate": "★★☆", "low": "★☆☆"}.get(conviction, "★☆☆")

    st.markdown(f"""
    <div class="bk-verdict {css_class}">
      <div class="bk-verdict-label">Investment Verdict</div>
      <div class="bk-verdict-rec" style="color:{rec_color}">{label}</div>
      <div class="bk-verdict-score" style="color:{bar_color}">{score}<span class="bk-verdict-score-sub">/100</span></div>
      <div class="bk-bar-wrap" style="width:50%;margin:6px auto">
        <div class="bk-bar-fill" style="width:{score}%;background:{bar_color}"></div>
      </div>
      <div style="margin-top:12px;display:flex;justify-content:center;gap:10px;flex-wrap:wrap">
        <span class="bk-badge" style="background:rgba(77,157,224,0.12);color:var(--accent)">{dir_label}</span>
        <span class="bk-badge" style="background:rgba(57,211,83,0.1);color:var(--green)">Conviction {conv_star}</span>
      </div>
      {'<div class="bk-verdict-detail">' + rationale + '</div>' if rationale else ''}
    </div>
    """, unsafe_allow_html=True)


# ── Hero ──────────────────────────────────────────────────────────────────────

def render_hero():
    ticker_items = [
        ("TA-125", "+0.4%", True), ("ESLT.TA", "+1.2%", True),
        ("BEZQ.TA", "-0.3%", False), ("TEVA.TA", "+0.8%", True),
        ("NICE.TA", "+0.6%", True), ("CHKP.TA", "-0.1%", False),
        ("LUMI.TA", "+1.8%", True), ("PTX.TA", "+2.1%", True),
        ("FIBI.TA", "+0.5%", True), ("AZRG.TA", "-0.7%", False),
    ]
    tick_html = "".join(
        f'<span class="bk-ticker-item"><span style="color:var(--text-dim)">{t}</span>'
        f'<span class="{"bk-ticker-up" if up else "bk-ticker-down"}">{pct}</span></span>'
        for t, pct, up in ticker_items
    )
    tick_double = tick_html + tick_html  # duplicate for seamless loop

    now_str = datetime.now().strftime("%H:%M:%S")
    st.markdown(f"""
    <div class="bk-hero">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;padding:0 4px">
        <div>
          <div class="bk-hero-wordmark">
            BORKAI
            <span class="bk-hero-wordmark-accent">TASE</span>
          </div>
          <div class="bk-hero-sub">Institutional-Grade Israeli Stock Intelligence</div>
          <div class="bk-hero-tags">
            <span class="bk-hero-tag"><span class="bk-status-dot"></span>Live</span>
            <span class="bk-hero-tag">TA-125 Coverage</span>
            <span class="bk-hero-tag">Maya Disclosures</span>
            <span class="bk-hero-tag">AI Analyst Panel</span>
            <span class="bk-hero-tag">RTL Reports</span>
          </div>
        </div>
        <div style="text-align:right;font-family:var(--mono);font-size:0.68rem;color:var(--text-dim);line-height:2">
          <div style="color:var(--text-muted)">{now_str} TLV</div>
          <div>GPT-4o Engine</div>
          <div>v2.0</div>
        </div>
      </div>
      <div class="bk-ticker-strip">
        <div class="bk-ticker-inner">{tick_double}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)


# ── Hot Stocks computation ─────────────────────────────────────────────────────

POSITIVE_KEYWORDS = [
    "win", "up", "beat", "above", "growth", "positive", "strong",
    "surge", "rally", "profit", "record", "raised", "outperform",
    "upgrade", "buy", "bullish", "dividend", "earnings beat",
]

def _compute_hot_stocks(tickers_data: list) -> list:
    try:
        import yfinance as yf
    except ImportError:
        return []
    try:
        from borkai.data.sector_news import fetch_sector_news
        has_news = True
    except ImportError:
        has_news = False

    results = []
    for tk in tickers_data:
        ticker  = tk.get("ticker", "")
        company = tk.get("name", ticker)
        sector  = tk.get("sector", "")
        size    = tk.get("market_cap_bucket", "")
        if not ticker:
            continue

        momentum_score = 0
        momentum_pct   = 0.0
        try:
            hist = yf.Ticker(ticker + ".TA").history(period="1mo")
            if len(hist) >= 5:
                close = hist["Close"]
                sma20 = close.rolling(min(20, len(close))).mean().iloc[-1]
                price = close.iloc[-1]
                pct_above = (price - sma20) / sma20 * 100 if sma20 > 0 else 0
                momentum_pct = round(pct_above, 2)
                if pct_above > 5:   momentum_score = 40
                elif pct_above > 2: momentum_score = 20
                elif pct_above > 0: momentum_score = 5
        except Exception:
            pass

        news_score   = 0
        top_headline = ""
        news_count   = 0
        if has_news:
            try:
                news_items = fetch_sector_news(company_name=company, sector=sector, max_items=10)
                pos_hits = sum(1 for n in news_items if any(kw in (n.title or "").lower() for kw in POSITIVE_KEYWORDS))
                news_score = min(50, pos_hits * 10)
                news_count = len(news_items)
                top_headline = news_items[0].title if news_items else ""
            except Exception:
                pass

        hot_score = momentum_score + news_score
        if hot_score >= 30 and momentum_pct > 0:
            results.append({
                "ticker": ticker, "company": company, "sector": sector, "size": size,
                "hot_score": hot_score, "momentum_score": momentum_score, "momentum_pct": momentum_pct,
                "news_score": news_score, "news_count": news_count, "top_headline": top_headline,
            })

    results.sort(key=lambda x: x["hot_score"], reverse=True)
    return results


# ── Tab: Overview ─────────────────────────────────────────────────────────────

def tab_overview():
    hot_cache  = st.session_state.get("hot_stocks_cache", [])
    maya_cache = st.session_state.get("maya_reports_cache", [])
    hot_age    = cache_age_seconds("hot_stocks_cache", "_hot_stocks_ts")
    maya_age   = cache_age_seconds("maya_reports_cache", "_maya_reports_ts")

    if not hot_cache and not maya_cache:
        st.markdown("""
        <div style="padding:48px 0;text-align:center;color:var(--text-muted)">
          <div style="font-family:var(--mono);font-size:3rem;opacity:0.15;letter-spacing:0.2em">▣</div>
          <div style="font-family:var(--condensed);font-size:1.1rem;letter-spacing:0.2em;text-transform:uppercase;margin-top:16px">
            No market data loaded
          </div>
          <div style="font-size:0.82rem;margin-top:8px">
            Use Hot Stocks or Maya Reports tabs to load data, then return here.
          </div>
        </div>
        """, unsafe_allow_html=True)
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("→ Hot Stocks", use_container_width=True):
                st.session_state["_nav_to_tab"] = 2; st.rerun()
        with col_b:
            if st.button("→ Maya Reports", use_container_width=True):
                st.session_state["_nav_to_tab"] = 1; st.rerun()
        return

    left_col, mid_col, right_col = st.columns([1.2, 1, 1])

    with left_col:
        st.markdown('<div style="font-family:var(--condensed);font-size:0.72rem;letter-spacing:0.2em;color:var(--text-muted);text-transform:uppercase;margin-bottom:8px">Hot Sectors</div>', unsafe_allow_html=True)
        if hot_cache:
            from collections import Counter
            sector_scores: dict = {}
            for s in hot_cache:
                sector_scores.setdefault(s["sector"], []).append(s["hot_score"])
            sector_avg = {sec: sum(v)/len(v) for sec, v in sector_scores.items()}
            top_sectors = sorted(sector_avg.items(), key=lambda x: x[1], reverse=True)[:8]
            for sec, avg_score in top_sectors:
                cnt = len(sector_scores[sec])
                bar_color = score_hex(int(avg_score))
                indicator = "▲" if avg_score >= 60 else "◆" if avg_score >= 40 else "▼"
                ind_color = "#39d353" if avg_score >= 60 else "#e3a00a" if avg_score >= 40 else "#f85149"
                st.markdown(f"""
                <div class="bk-sector-row">
                  <span style="color:var(--text)">{sec}</span>
                  <span style="display:flex;align-items:center;gap:8px">
                    <span class="bk-badge" style="background:rgba(77,157,224,0.1);color:var(--accent)">{cnt}</span>
                    <span style="font-family:var(--mono);font-weight:700;color:{bar_color};font-size:0.78rem">{ind_color and ""}{indicator} {avg_score:.0f}</span>
                  </span>
                </div>
                """, unsafe_allow_html=True)

    with mid_col:
        st.markdown('<div style="font-family:var(--condensed);font-size:0.72rem;letter-spacing:0.2em;color:var(--text-muted);text-transform:uppercase;margin-bottom:8px">Top 5 Momentum</div>', unsafe_allow_html=True)
        if hot_cache:
            for stock in hot_cache[:5]:
                bar_color = score_hex(stock["hot_score"])
                mom_color = "#39d353" if stock["momentum_pct"] > 0 else "#f85149"
                st.markdown(f"""
                <div class="bk-hot-card" style="padding:10px 12px">
                  <div style="display:flex;justify-content:space-between;align-items:center">
                    <span class="bk-hot-ticker" style="font-size:1rem">{stock["ticker"]}</span>
                    <span class="bk-badge" style="background:{bar_color}18;color:{bar_color}">{stock["hot_score"]} pts</span>
                  </div>
                  <div class="bk-hot-company">{stock["company"]}</div>
                  <span class="bk-badge" style="background:{mom_color}12;color:{mom_color};margin-top:4px">
                    +{stock["momentum_pct"]:.1f}% vs MA
                  </span>
                  <div class="bk-bar-wrap" style="margin-top:6px">
                    <div class="bk-bar-fill" style="width:{min(stock['hot_score'],100)}%;background:{bar_color}"></div>
                  </div>
                </div>
                """, unsafe_allow_html=True)

    with right_col:
        st.markdown('<div style="font-family:var(--condensed);font-size:0.72rem;letter-spacing:0.2em;color:var(--text-muted);text-transform:uppercase;margin-bottom:8px">Latest Maya Disclosures</div>', unsafe_allow_html=True)
        if maya_cache:
            for report in maya_cache[:5]:
                impact = getattr(report, "impact", "neutral").lower()
                impact_color = {"bullish": "#39d353", "bearish": "#f85149"}.get(impact, "#57657a")
                ticker_badge = f"<span class='bk-badge' style='background:rgba(77,157,224,0.1);color:var(--accent)'>{report.ticker}</span>" if report.ticker else ""
                title_short = (report.title or "")[:65] + ("…" if len(report.title or "") > 65 else "")
                st.markdown(f"""
                <div class="bk-feed-item bk-feed-{impact}" style="padding:8px 12px">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px">
                    {ticker_badge}
                    <span class="bk-badge" style="background:{impact_color}18;color:{impact_color}">{impact}</span>
                  </div>
                  <div style="font-size:0.8rem;color:var(--text);line-height:1.3">{title_short}</div>
                  <div style="font-size:0.7rem;color:var(--text-muted);margin-top:3px;font-family:var(--mono)">{report.source}</div>
                </div>
                """, unsafe_allow_html=True)

    st.divider()
    cta1, cta2, cta3 = st.columns(3)
    with cta1:
        if st.button("→ Scan Market", use_container_width=True):
            st.session_state["_nav_to_tab"] = 3; st.rerun()
    with cta2:
        if st.button("→ Analyze a Stock", use_container_width=True):
            st.session_state["_nav_to_tab"] = 4; st.rerun()
    with cta3:
        if st.button("↺ Refresh", use_container_width=True):
            for k in ["hot_stocks_cache", "_hot_stocks_ts", "maya_reports_cache", "_maya_reports_ts"]:
                st.session_state.pop(k, None)
            st.rerun()


# ── Tab: Maya Reports ─────────────────────────────────────────────────────────

def tab_maya_reports():
    st.markdown('<div style="font-family:var(--condensed);font-size:1.4rem;font-weight:900;letter-spacing:0.12em;text-transform:uppercase;margin:12px 0 4px">Maya Disclosures</div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.8rem;color:var(--text-muted);margin-bottom:16px;font-family:var(--mono)">Live TASE regulatory filings — AI-assessed impact</div>', unsafe_allow_html=True)

    maya_cache = st.session_state.get("maya_reports_cache", [])
    maya_ts    = st.session_state.get("_maya_reports_ts")
    age_str    = f"Updated {int((datetime.now() - maya_ts).total_seconds() / 60)}m ago" if maya_ts else "Not fetched"

    col_btn, col_age = st.columns([1, 4])
    with col_btn:
        refresh = st.button("↺ Refresh Feed", type="primary", use_container_width=True)
    with col_age:
        st.markdown(f'<span style="font-family:var(--mono);font-size:0.72rem;color:var(--text-muted)">{age_str}</span>', unsafe_allow_html=True)

    if refresh:
        tickers_data = load_tase_tickers()
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if not openai_key:
            st.error("OPENAI_API_KEY not set."); return
        try:
            import openai as _openai
            from borkai.config import load_config
            from borkai.data.maya_fetcher import get_maya_reports
            client = _openai.OpenAI(api_key=openai_key)
            config = load_config()
            with st.spinner("Fetching Maya disclosures…"):
                reports = get_maya_reports(client=client, config=config, known_stocks=tickers_data, max_reports=40)
            st.session_state["maya_reports_cache"] = reports
            st.session_state["_maya_reports_ts"] = datetime.now()
            maya_cache = reports
            st.success(f"Loaded {len(reports)} disclosures.")
        except Exception as e:
            st.error(f"Failed: {e}"); return

    if not maya_cache:
        st.markdown('<div style="padding:32px 0;text-align:center;color:var(--text-muted);font-family:var(--mono);font-size:0.8rem">Click Refresh to load the latest TASE filings.</div>', unsafe_allow_html=True)
        return

    from collections import Counter
    sectors_seen = [r.sector for r in maya_cache if r.sector]
    if sectors_seen:
        sector_counts = Counter(sectors_seen)
        badges_html = " ".join(
            f"<span class='bk-badge' style='background:rgba(77,157,224,0.1);color:var(--accent)'>{sec} {cnt}</span>"
            for sec, cnt in sector_counts.most_common(8)
        )
        st.markdown(f'<div style="margin-bottom:12px;display:flex;gap:4px;flex-wrap:wrap">{badges_html}</div>', unsafe_allow_html=True)

    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        impact_filter = st.selectbox("Impact", options=["all", "bullish", "bearish", "neutral"],
            key="maya_impact_filter",
            format_func=lambda x: {"all": "All", "bullish": "Bullish", "bearish": "Bearish", "neutral": "Neutral"}[x])
    with filter_col2:
        all_sectors = sorted(set(r.sector for r in maya_cache if r.sector))
        sector_filter = st.multiselect("Sector", options=all_sectors, key="maya_sector_filter")

    filtered = maya_cache
    if impact_filter != "all":
        filtered = [r for r in filtered if getattr(r, "impact", "neutral").lower() == impact_filter]
    if sector_filter:
        filtered = [r for r in filtered if r.sector in sector_filter]

    st.markdown(f'<div style="font-family:var(--mono);font-size:0.7rem;color:var(--text-muted);margin-bottom:8px">{len(filtered)} / {len(maya_cache)} filings</div>', unsafe_allow_html=True)

    for report in filtered:
        impact = getattr(report, "impact", "neutral").lower()
        impact_color = {"bullish": "#39d353", "bearish": "#f85149"}.get(impact, "#57657a")
        impact_icon  = {"bullish": "▲", "bearish": "▼", "neutral": "◆"}.get(impact, "◆")
        ticker_badge = f"<span class='bk-badge' style='background:rgba(77,157,224,0.1);color:var(--accent)'>{report.ticker}</span>" if report.ticker else ""
        company_html = f"<span style='color:var(--text);font-weight:600'>{report.company_name}</span> " if report.company_name else ""
        rtype_badge  = f"<span class='bk-badge' style='background:var(--surface2);color:var(--text-muted)'>{report.report_type}</span>"
        link_html    = f"<a href='{report.link}' target='_blank' style='color:var(--accent);font-family:var(--mono);font-size:0.68rem;text-decoration:none'>→ Maya</a>" if report.link else ""
        pub_html     = f"<span style='font-family:var(--mono);font-size:0.68rem;color:var(--text-dim)'>{report.source} · {report.published[:16]}</span>" if report.published else ""

        st.markdown(f"""
        <div class="bk-feed-item bk-feed-{impact}" style="margin-bottom:8px">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:4px">
            <div style="display:flex;gap:4px;flex-wrap:wrap;align-items:center">{company_html}{ticker_badge}{rtype_badge}</div>
            <span class="bk-badge" style="background:{impact_color}18;color:{impact_color}">{impact_icon} {impact.upper()}</span>
          </div>
          <div style="font-size:0.88rem;color:var(--text);margin-top:6px;font-weight:500;line-height:1.4">{report.title}</div>
          {'<div style="font-size:0.8rem;color:var(--text-muted);margin-top:4px">' + report.summary + '</div>' if report.summary else ''}
          {'<div style="font-size:0.75rem;color:var(--text-dim);margin-top:4px;font-style:italic">' + report.impact_reason + '</div>' if report.impact_reason else ''}
          <div style="margin-top:8px;display:flex;justify-content:space-between;align-items:center">{pub_html}{link_html}</div>
        </div>
        """, unsafe_allow_html=True)


# ── Tab: Hot Stocks ───────────────────────────────────────────────────────────

def tab_hot_stocks():
    st.markdown('<div style="font-family:var(--condensed);font-size:1.4rem;font-weight:900;letter-spacing:0.12em;text-transform:uppercase;margin:12px 0 4px">Hot Stocks</div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.8rem;color:var(--text-muted);margin-bottom:16px;font-family:var(--mono)">TASE stocks with price momentum above MA20 and positive news sentiment</div>', unsafe_allow_html=True)

    tickers_data = load_tase_tickers()
    if not tickers_data:
        st.warning(f"No tickers at `{TICKERS_CSV}`"); return

    hot_cache = st.session_state.get("hot_stocks_cache", [])
    hot_ts    = st.session_state.get("_hot_stocks_ts")
    age_str   = f"Computed {int((datetime.now() - hot_ts).total_seconds() / 60)}m ago" if hot_ts else "Not computed"

    col_btn, col_age = st.columns([1, 4])
    with col_btn:
        refresh = st.button("↺ Refresh", type="primary", use_container_width=True)
    with col_age:
        st.markdown(f'<span style="font-family:var(--mono);font-size:0.72rem;color:var(--text-muted)">{age_str}</span>', unsafe_allow_html=True)

    if refresh:
        for k in ["hot_stocks_cache", "_hot_stocks_ts"]: st.session_state.pop(k, None)
        hot_cache = []

    if not hot_cache:
        if refresh or hot_ts is None:
            with st.spinner(f"Computing momentum for {len(tickers_data)} stocks…"):
                results = _compute_hot_stocks(tickers_data)
            st.session_state["hot_stocks_cache"] = results
            st.session_state["_hot_stocks_ts"] = datetime.now()
            hot_cache = results
            if not results:
                st.info("No stocks met hot criteria (score ≥ 30, price above MA20)."); return
        else:
            st.markdown('<div style="padding:24px 0;text-align:center;color:var(--text-muted);font-family:var(--mono);font-size:0.8rem">Click Refresh to compute momentum scores.</div>', unsafe_allow_html=True)
            return

    if not hot_cache: return

    sectors = sorted(set(s.get("sector", "") for s in tickers_data if s.get("sector")))
    f_col1, f_col2 = st.columns(2)
    with f_col1:
        sector_filter = st.multiselect("Sector", options=sectors, key="hot_sector_filter")
    with f_col2:
        min_score = st.slider("Min score", min_value=0, max_value=90, value=30, step=5, key="hot_min_score")

    filtered = hot_cache
    if sector_filter: filtered = [s for s in filtered if s.get("sector") in sector_filter]
    if min_score > 0: filtered = [s for s in filtered if s.get("hot_score", 0) >= min_score]

    st.markdown(f'<div style="font-family:var(--mono);font-size:0.7rem;color:var(--text-muted);margin-bottom:8px">{len(filtered)} stocks</div>', unsafe_allow_html=True)

    cols = st.columns(3)
    for i, stock in enumerate(filtered):
        hot_color = score_hex(stock["hot_score"])
        mom_color = "#39d353" if stock["momentum_pct"] > 0 else "#f85149"
        headline_html = (
            f'<div class="bk-hot-headline">{stock["top_headline"][:90]}{"…" if len(stock["top_headline"]) > 90 else ""}</div>'
            if stock.get("top_headline") else ""
        )
        with cols[i % 3]:
            st.markdown(f"""
            <div class="bk-hot-card">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <span class="bk-hot-ticker">{stock["ticker"]}</span>
                <span class="bk-badge" style="background:{hot_color}18;color:{hot_color};font-size:0.78rem">{stock["hot_score"]}</span>
              </div>
              <div class="bk-hot-company">{stock["company"]}</div>
              <span class="bk-badge" style="background:rgba(57,211,83,0.08);color:#39d353;font-size:0.65rem">{stock["sector"]}</span>
              <div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:4px">
                <span class="bk-badge" style="background:{mom_color}12;color:{mom_color}">MA +{stock["momentum_pct"]:.1f}%</span>
                <span class="bk-badge" style="background:var(--surface2);color:var(--text-muted)">{stock["news_count"]} articles</span>
              </div>
              <div class="bk-bar-wrap" style="margin-top:8px">
                <div class="bk-bar-fill" style="width:{min(stock['hot_score'],100)}%;background:{hot_color}"></div>
              </div>
              {headline_html}
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"Analyze →", key=f"ha_{stock['ticker']}_{i}", use_container_width=True):
                st.session_state["analyze_ticker"] = stock["ticker"]
                st.session_state["_nav_to_tab"] = 4
                st.rerun()


# ── Tab: Scanner ──────────────────────────────────────────────────────────────

def tab_scanner():
    st.markdown('<div style="font-family:var(--condensed);font-size:1.4rem;font-weight:900;letter-spacing:0.12em;text-transform:uppercase;margin:12px 0 4px">Market Scanner</div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.8rem;color:var(--text-muted);margin-bottom:16px;font-family:var(--mono)">Full TASE sweep — rank by expected return score, save top-N reports</div>', unsafe_allow_html=True)

    tickers_data = load_tase_tickers()
    col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
    with col1:
        horizons = st.multiselect("Horizons", options=["short", "medium", "long"], default=["medium"],
            format_func=lambda x: HORIZON_SHORT[x])
    with col2:
        top_n = st.slider("Top N", 5, 20, 10)
    with col3:
        size_filter = st.selectbox("Size", options=["", "large", "mid", "small"],
            format_func=lambda x: {"": "All", "large": "Large", "mid": "Mid", "small": "Small"}[x])
    with col4:
        no_articles = st.checkbox("Skip articles", value=True)

    col_start, col_resume = st.columns(2)
    with col_start:
        start_scan = st.button("▶ Start Scan", type="primary", use_container_width=True)
    with col_resume:
        resume_scan = st.button("↺ Resume", use_container_width=True)

    if start_scan or resume_scan:
        if not horizons:
            st.error("Select at least one horizon."); return

        def run_in_bg(resume: bool):
            from scan_tase import run_scanner
            run_scanner(horizons=horizons, top_n=top_n, output_dir=REPORTS_DIR,
                        size_filter=size_filter or None, resume=resume, no_articles=no_articles)

        threading.Thread(target=run_in_bg, args=(resume_scan,), daemon=True).start()
        st.session_state["scan_date"] = str(date.today())
        st.success("Scan running in background — click Refresh below to track progress.")

    scan_date = st.session_state.get("scan_date") or (list_scan_dates() or [None])[0]
    if not scan_date:
        st.markdown('<div style="padding:24px 0;text-align:center;color:var(--text-muted);font-family:var(--mono);font-size:0.8rem">No scan data. Start a scan above.</div>', unsafe_allow_html=True)
        return

    st.markdown(f'<div style="font-family:var(--condensed);font-size:0.9rem;font-weight:700;letter-spacing:0.15em;text-transform:uppercase;margin:16px 0 8px;color:var(--text-muted)">Scan Status — {scan_date}</div>', unsafe_allow_html=True)

    progress = read_scan_progress(scan_date)
    if progress:
        done  = sum(1 for v in progress.values() if v.get("status") == "done")
        filt  = sum(1 for v in progress.values() if v.get("status") == "filtered")
        fail  = sum(1 for v in progress.values() if v.get("status") == "failed")
        total = len(progress)
        pct   = done / max(total, 1)
        bar_c = score_hex(int(pct * 100))

        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Processed", total)
        col_b.metric("Done", done)
        col_c.metric("Filtered", filt)
        col_d.metric("Failed", fail)

        st.markdown(f"""
        <div class="bk-bar-wrap" style="height:8px;margin:8px 0">
          <div class="bk-bar-fill" style="height:8px;width:{pct*100:.1f}%;background:{bar_c}"></div>
        </div>
        <div style="font-family:var(--mono);font-size:0.7rem;color:var(--text-muted)">{done}/{total} · {pct*100:.0f}%</div>
        """, unsafe_allow_html=True)

    if st.button("↺ Refresh Status"): st.rerun()

    scan_dates = list_scan_dates()
    if len(scan_dates) > 1:
        with st.expander("Scan History"):
            for sd in scan_dates:
                h_avail = [h for h in ["short","medium","long"]
                           if os.path.exists(os.path.join(REPORTS_DIR, sd, h, "ranking_data.json"))]
                h_html = " ".join(
                    f"<span class='bk-badge' style='background:rgba(77,157,224,0.1);color:var(--accent)'>{HORIZON_SHORT[h]}</span>"
                    for h in h_avail
                )
                st.markdown(f"<div class='bk-card' style='padding:8px 14px;display:flex;align-items:center;gap:10px'>"
                            f"<span style='font-family:var(--mono);font-size:0.8rem'>{sd}</span>{h_html}</div>",
                            unsafe_allow_html=True)

    for horizon in ["short", "medium", "long"]:
        ranking = load_ranking(scan_date, horizon)
        if ranking:
            st.markdown(f'<div style="font-family:var(--condensed);font-size:0.85rem;font-weight:700;letter-spacing:0.15em;text-transform:uppercase;margin:16px 0 6px;color:var(--text-muted)">Results — {HORIZON_SHORT[horizon]}</div>', unsafe_allow_html=True)
            _render_ranking_table(ranking, scan_date, horizon)


def _render_ranking_table(ranking: list, scan_date: str, horizon: str):
    for entry in ranking:
        score  = entry.get("return_score", 0)
        ticker = entry.get("ticker", "")
        name   = entry.get("company_name", "")
        rec    = entry.get("invest_recommendation", "")
        rank   = entry.get("rank", 0)
        in_top = entry.get("in_top", False)
        color  = "#39d353" if rec == "YES" else "#f85149" if rec == "NO" else "#e3a00a"
        bar_c  = score_hex(score)
        top_badge = "<span class='bk-badge' style='background:rgba(57,211,83,0.1);color:#39d353'>TOP</span>" if in_top else ""

        st.markdown(f"""
        <div class="bk-rank-row">
          <span style="font-family:var(--mono);font-size:0.72rem;color:var(--text-dim);min-width:26px">#{rank}</span>
          <span class="bk-ticker-label" style="min-width:72px">{ticker}</span>
          <span style="color:var(--text);flex:1;font-size:0.88rem">{name}</span>
          <span class="bk-badge" style="background:{color}12;color:{color}">{rec}</span>
          <div class="bk-bar-wrap" style="width:60px;margin:0 8px 0 0">
            <div class="bk-bar-fill" style="width:{score}%;background:{bar_c}"></div>
          </div>
          <span style="font-family:var(--mono);font-weight:700;color:{bar_c};min-width:54px;text-align:right;font-size:0.82rem">{score}/100</span>
          {top_badge}
        </div>
        """, unsafe_allow_html=True)

        if in_top and entry.get("report_file"):
            he_file = Path(entry["report_file"]).name.replace(".md", "_he.md")
            content = load_report_file(scan_date, horizon, he_file)
            if content:
                with st.expander(f"Report: {ticker}"):
                    st.markdown(f'<div class="bk-report-rtl">', unsafe_allow_html=True)
                    st.markdown(content)
                    st.markdown('</div>', unsafe_allow_html=True)
                    st.download_button("↓ Download", data=content.encode("utf-8"),
                        file_name=he_file, mime="text/markdown",
                        key=f"dl_{scan_date}_{horizon}_{ticker}")


# ── Tab: Analyze ──────────────────────────────────────────────────────────────

def tab_analyze():
    st.markdown('<div style="font-family:var(--condensed);font-size:1.4rem;font-weight:900;letter-spacing:0.12em;text-transform:uppercase;margin:12px 0 4px">Stock Analysis</div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.8rem;color:var(--text-muted);margin-bottom:16px;font-family:var(--mono)">Full AI analysis pipeline — data, analysts, committee, report</div>', unsafe_allow_html=True)

    # Use get+delete pattern instead of pop to avoid state modification issues
    prefill = st.session_state.get("analyze_ticker", "")
    if "analyze_ticker" in st.session_state:
        del st.session_state["analyze_ticker"]

    col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
    with col1:
        ticker_raw = st.text_input("Ticker", value=prefill, placeholder="ESLT / BEZQ / TEVA …",
            key="analyze_ticker_input",
            help="Without .TA suffix — added automatically for IL market")
    with col2:
        horizon = st.selectbox("Horizon", options=["short", "medium", "long"],
            key="analyze_horizon",
            format_func=lambda x: HORIZON_LABELS[x])
    with col3:
        market = st.selectbox("Market", options=["il", "us"],
            key="analyze_market",
            format_func=lambda x: {"il": "🇮🇱 TASE", "us": "🇺🇸 US"}[x])
    with col4:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        run_btn = st.button("▶ Analyze", key="analyze_run_btn", type="primary", use_container_width=True)

    if run_btn:
        if not ticker_raw.strip():
            st.error("Enter a ticker symbol."); return

        # Check API key early
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if not openai_key:
            st.error(
                "**OPENAI_API_KEY not found.**\n\n"
                "Create a `.env` file in the project root with:\n"
                "```\nOPENAI_API_KEY=sk-...\n```"
            )
            return

        ticker = ticker_raw.strip().upper().replace(".TA", "")
        st.session_state.pop("analysis_result", None)

        # Terminal header (static)
        st.markdown(f"""
        <div class="bk-terminal" style="margin-bottom:0;border-bottom:none;border-radius:4px 4px 0 0">
          <div class="bk-terminal-header">
            <span class="bk-dot bk-dot-red"></span>
            <span class="bk-dot bk-dot-amber"></span>
            <span class="bk-dot bk-dot-green"></span>
            <span class="bk-term-title">BORKAI ENGINE — {ticker} · {HORIZON_SHORT.get(horizon, horizon.upper())} · {market.upper()}</span>
          </div>
          <span class="bk-term-prompt">$</span> borkai analyze --ticker {ticker} --horizon {horizon} --market {market}
        </div>
        """, unsafe_allow_html=True)

        progress_bar = st.progress(0.0)
        log_placeholder = st.empty()
        completed_stages: list = []

        def _render_log(final: bool = False, error: str = ""):
            lines: list = []
            for s, l, d in completed_stages:
                detail_part = ""
                if d:
                    detail_part = f'  <span style="color:var(--text-dim)">{d}</span>'
                lines.append(
                    f'<span style="color:#39d353">✓</span> '
                    f'<span style="color:var(--text-dim);font-family:var(--mono)">[{s:02d}/08]</span> '
                    f'<span style="color:#c9d1d9">{l}</span>{detail_part}'
                )
            if error:
                lines.append(f'<span style="color:#f85149">✗ {error}</span>')
            elif not final:
                lines.append(f'<span style="color:#e3a00a">⟳  running…</span>')
            else:
                lines.append(f'<span style="color:#39d353;font-weight:700">✓ COMPLETE</span>')

            html = (
                '<div class="bk-terminal" style="border-top:none;border-radius:0 0 4px 4px;min-height:80px">'
                + "<br>".join(lines)
                + "</div>"
            )
            log_placeholder.markdown(html, unsafe_allow_html=True)

        def on_progress(stage: int, label: str, detail: str):
            completed_stages.append((stage, label, detail))
            progress_bar.progress(min(stage / 8, 1.0))
            _render_log()

        _render_log()  # show empty terminal with "running…"

        try:
            from main import analyze as run_analysis
            report_en, report_he, result = run_analysis(
                ticker=ticker,
                time_horizon=horizon,
                market=market,
                save_report=True,
                progress_callback=on_progress,
            )
            st.session_state["analysis_result"] = (report_he, result)
            progress_bar.progress(1.0)
            _render_log(final=True)
        except Exception as exc:
            import traceback as tb
            _render_log(error=str(exc))
            st.error(f"Analysis failed: {exc}")
            with st.expander("Full traceback"):
                st.code(tb.format_exc())
            return

    # ── Display stored result ────────────────────────────────────────────────
    if "analysis_result" in st.session_state:
        report_he, result = st.session_state["analysis_result"]
        d = result.decision

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        render_verdict_card(
            rec=d.invest_recommendation, score=d.return_score,
            direction=d.direction, conviction=d.conviction,
            rationale=d.invest_rationale,
        )

        # Info row
        name  = result.profile.company_name if hasattr(result, "profile") else ""
        horiz = HORIZON_LABELS.get(result.time_horizon, result.time_horizon)
        fname = f"borkai_{result.ticker}_{result.time_horizon}_{result.analysis_date}_he.md"

        col_info, col_dl = st.columns([3, 1])
        with col_info:
            st.markdown(f"""
            <div class="bk-card bk-card-accent" style="padding:12px 16px">
              <span class="bk-ticker-label" style="font-size:1.1rem">{result.ticker}</span>
              <span style="color:var(--text);margin:0 8px">·</span>
              <span style="color:var(--text-muted);font-size:0.88rem">{name}</span>
              <span style="color:var(--text-dim);margin:0 8px">·</span>
              <span style="font-family:var(--mono);font-size:0.72rem;color:var(--text-muted)">{horiz} · {result.analysis_date}</span>
            </div>
            """, unsafe_allow_html=True)
        with col_dl:
            st.download_button("↓ Hebrew Report", data=report_he.encode("utf-8"),
                               file_name=fname, mime="text/markdown", use_container_width=True)

        st.divider()

        # RTL-wrapped report
        with st.expander("Full Report (Hebrew)", expanded=True):
            st.markdown('<div class="bk-report-rtl">', unsafe_allow_html=True)
            st.markdown(report_he)
            st.markdown('</div>', unsafe_allow_html=True)


# ── Tab: Reports ──────────────────────────────────────────────────────────────

def tab_reports():
    st.markdown('<div style="font-family:var(--condensed);font-size:1.4rem;font-weight:900;letter-spacing:0.12em;text-transform:uppercase;margin:12px 0 4px">Saved Reports</div>', unsafe_allow_html=True)

    scan_dates = list_scan_dates()
    if not scan_dates:
        st.markdown('<div style="padding:32px 0;text-align:center;color:var(--text-muted);font-family:var(--mono);font-size:0.8rem">No saved reports. Run a scan or analyze a stock first.</div>', unsafe_allow_html=True)
        return

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        selected_date = st.selectbox("Date", scan_dates)
    with col2:
        available_horizons = [h for h in ["short", "medium", "long"]
            if os.path.exists(os.path.join(REPORTS_DIR, selected_date, h, "ranking_data.json"))]
        if not available_horizons:
            st.info("No ranking data for this date."); return
        selected_horizon = st.selectbox("Horizon", available_horizons,
            format_func=lambda x: HORIZON_SHORT.get(x, x))
    with col3:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        top_only = st.checkbox("Top only", value=True)

    ranking = load_ranking(selected_date, selected_horizon)
    if not ranking:
        st.info("No ranking data."); return

    display = [r for r in ranking if r.get("in_top")] if top_only else ranking
    st.markdown(f'<div style="font-family:var(--mono);font-size:0.7rem;color:var(--text-muted);margin-bottom:8px">{HORIZON_SHORT.get(selected_horizon, selected_horizon)} · {selected_date} · {len(display)} stocks</div>', unsafe_allow_html=True)

    for entry in display:
        score  = entry.get("return_score", 0)
        ticker = entry.get("ticker", "")
        name   = entry.get("company_name", "")
        rec    = entry.get("invest_recommendation", "")
        rank   = entry.get("rank", 0)
        in_top = entry.get("in_top", False)
        color  = "#39d353" if rec == "YES" else "#f85149" if rec == "NO" else "#e3a00a"
        bar_c  = score_hex(score)
        top_badge = "<span class='bk-badge' style='background:rgba(57,211,83,0.1);color:#39d353'>TOP</span>" if in_top else ""

        st.markdown(f"""
        <div class="bk-rank-row">
          <span style="font-family:var(--mono);font-size:0.72rem;color:var(--text-dim);min-width:26px">#{rank}</span>
          <span class="bk-ticker-label" style="min-width:72px">{ticker}</span>
          <span style="color:var(--text);flex:1;font-size:0.88rem">{name}</span>
          <div class="bk-bar-wrap" style="width:60px;margin:0 8px 0 0">
            <div class="bk-bar-fill" style="width:{score}%;background:{bar_c}"></div>
          </div>
          <span style="font-family:var(--mono);font-weight:700;color:{bar_c};min-width:52px;text-align:right;font-size:0.82rem">{score}/100</span>
          <span class="bk-badge" style="background:{color}12;color:{color}">{rec}</span>
          {top_badge}
        </div>
        """, unsafe_allow_html=True)

        if entry.get("report_file"):
            he_file = Path(entry["report_file"]).name.replace(".md", "_he.md")
            content = load_report_file(selected_date, selected_horizon, he_file)
            if content:
                with st.expander(f"Report — {ticker} · {name}"):
                    st.markdown('<div class="bk-report-rtl">', unsafe_allow_html=True)
                    st.markdown(content)
                    st.markdown('</div>', unsafe_allow_html=True)
                    st.download_button("↓ Download", data=content.encode("utf-8"),
                        file_name=he_file, mime="text/markdown",
                        key=f"saved_{selected_date}_{selected_horizon}_{ticker}")


# ── Main layout ───────────────────────────────────────────────────────────────

render_hero()

TAB_LABELS = ["Overview", "Maya", "Hot Stocks", "Scanner", "Analyze", "Reports"]
TAB_FUNCS  = [tab_overview, tab_maya_reports, tab_hot_stocks, tab_scanner, tab_analyze, tab_reports]

tabs = st.tabs(TAB_LABELS)
for i, (tab, fn) in enumerate(zip(tabs, TAB_FUNCS)):
    with tab:
        try:
            fn()
        except Exception as _tab_err:
            import traceback as _tb
            st.error(f"**Error in {TAB_LABELS[i]} tab:** {_tab_err}")
            st.code(_tb.format_exc())
