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
  --accent:      #4d9de0;
  --accent-glow: rgba(77,157,224,0.15);
  --green:       #39d353;
  --green-bg:    rgba(57,211,83,0.08);
  --red:         #f85149;
  --red-bg:      rgba(248,81,73,0.08);
  --amber:       #e3a00a;
  --amber-bg:    rgba(227,160,10,0.08);
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


def _list_report_files():
    """Return individual report .md files from the reports/ dir (newest first)."""
    rdir = Path(REPORTS_DIR)
    if not rdir.exists():
        return []
    files = sorted(rdir.glob("report_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files


# ── Hero ──────────────────────────────────────────────────────────────────────

def render_hero():
    items = [
        ("TA-125", "+0.4%", True), ("ESLT.TA", "+1.2%", True),
        ("BEZQ.TA", "-0.3%", False), ("TEVA.TA", "+0.8%", True),
        ("NICE.TA", "+0.6%", True), ("CHKP.TA", "-0.1%", False),
        ("LUMI.TA", "+1.8%", True), ("PTX.TA", "+2.1%", True),
    ]
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
    label = {"YES": "BUY", "NO": "AVOID", "CONDITIONAL": "CONDITIONAL"}.get(rec.upper(), rec)
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

    # ── Input form ────────────────────────────────────────────────────────────
    with st.form(key="analyze_form", clear_on_submit=False):
        c1, c2, c3, c4 = st.columns([3, 3, 2, 2])
        with c1:
            ticker_input = st.text_input(
                "Ticker Symbol",
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
            _redraw(err=str(exc)[:120])
            st.error(f"Analysis failed: {exc}")
            with st.expander("Full error details"):
                st.code(traceback.format_exc())
            return

    # ── Show result ───────────────────────────────────────────────────────────
    if "last_result" in st.session_state:
        data = st.session_state["last_result"]
        report_en = data["report"]
        result = data["result"]
        d = result.decision

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        render_verdict(
            rec=d.invest_recommendation,
            score=d.return_score,
            direction=d.direction,
            conviction=d.conviction,
            rationale=d.invest_rationale,
        )

        name  = getattr(result.profile, "company_name", "")
        today = getattr(result, "analysis_date", str(date.today()))
        fname = f"borkai_{data['ticker']}_{data['horizon']}_{today}.md"

        col_info, col_dl = st.columns([4, 1])
        with col_info:
            score_c = _score_color(d.return_score)
            st.markdown(f"""
            <div class="bk-card bk-card-accent" style="padding:12px 16px">
              <span style="font-family:var(--mono);font-weight:700;color:#4d9de0;font-size:1.1rem">{data["ticker"]}</span>
              <span style="color:#3d4f61;margin:0 8px">|</span>
              <span style="color:#c9d1d9;font-size:0.88rem">{name}</span>
              <span style="color:#3d4f61;margin:0 8px">|</span>
              <span style="font-family:var(--mono);font-size:0.72rem;color:#57657a">{HORIZON_LABELS.get(data["horizon"], "")} &middot; {today}</span>
              <span style="color:#3d4f61;margin:0 8px">|</span>
              <span style="font-family:var(--mono);font-weight:700;color:{score_c}">{d.return_score}/100</span>
            </div>
            """, unsafe_allow_html=True)
        with col_dl:
            st.download_button(
                "Download Report",
                data=report_en.encode("utf-8"),
                file_name=fname,
                mime="text/markdown",
                use_container_width=True,
                key="dl_report_btn",
            )

        st.divider()

        with st.expander("Full Report", expanded=True):
            st.markdown(report_en)


# ── Tab: Reports ──────────────────────────────────────────────────────────────

def tab_reports():
    st.markdown(
        '<div style="font-family:\'Barlow Condensed\',sans-serif;font-size:1.4rem;font-weight:900;'
        'letter-spacing:0.12em;text-transform:uppercase;margin:16px 0 4px;color:#c9d1d9">'
        'Saved Reports</div>',
        unsafe_allow_html=True,
    )

    files = _list_report_files()
    if not files:
        st.markdown(
            '<div style="padding:48px 0;text-align:center;color:#57657a;font-family:'
            '\'JetBrains Mono\',monospace;font-size:0.8rem">'
            'No saved reports yet. Run an analysis first.</div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.72rem;'
        f'color:#57657a;margin-bottom:12px">{len(files)} reports saved in reports/</div>',
        unsafe_allow_html=True,
    )

    selected = st.selectbox(
        "Select report",
        options=[f.name for f in files],
        key="reports_select",
    )
    if selected:
        content = (Path(REPORTS_DIR) / selected).read_text(encoding="utf-8")
        # Parse basic metadata from filename: report_TICKER_horizon_date_he.md
        parts = selected.replace("report_", "").replace("_he.md", "").split("_")
        ticker_part = parts[0] if parts else selected
        col_info, col_dl = st.columns([4, 1])
        with col_info:
            st.markdown(
                f'<div class="bk-card bk-card-accent" style="padding:10px 16px">'
                f'<span style="font-family:\'JetBrains Mono\',monospace;font-weight:700;color:#4d9de0">{ticker_part}</span>'
                f'<span style="color:#3d4f61;margin:0 8px">|</span>'
                f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:0.72rem;color:#57657a">{selected}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with col_dl:
            st.download_button(
                "Download",
                data=content.encode("utf-8"),
                file_name=selected,
                mime="text/markdown",
                use_container_width=True,
                key="dl_saved_btn",
            )
        with st.expander("Report", expanded=True):
            st.markdown(content)


# ── Tab: Maya Filings ─────────────────────────────────────────────────────────

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
        impact = getattr(rep, "impact", "neutral").lower()
        ic = {"bullish": "#39d353", "bearish": "#f85149"}.get(impact, "#57657a")
        title_s = (rep.title or "")[:90] + ("..." if len(rep.title or "") > 90 else "")
        reason = f'<div style="font-size:0.75rem;color:#57657a;margin-top:3px;font-style:italic">{rep.impact_reason}</div>' if getattr(rep, "impact_reason", "") else ""
        link = f'<a href="{rep.link}" target="_blank" style="color:#4d9de0;font-family:\'JetBrains Mono\',monospace;font-size:0.68rem;text-decoration:none">Maya &rarr;</a>' if getattr(rep, "link", "") else ""
        st.markdown(f"""
        <div class="bk-feed bk-feed-{"bull" if impact=="bullish" else "bear" if impact=="bearish" else ""}" style="margin-bottom:6px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span style="font-family:\'JetBrains Mono\',monospace;font-weight:700;color:#4d9de0;font-size:0.8rem">{getattr(rep,"ticker","")}</span>
            <span class="bk-badge" style="background:{ic}18;color:{ic}">{impact}</span>
          </div>
          <div style="font-size:0.88rem;color:#c9d1d9;margin-top:4px">{title_s}</div>
          {reason}
          <div style="margin-top:6px;text-align:right">{link}</div>
        </div>
        """, unsafe_allow_html=True)


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
        if do_refresh or ts is None:
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
        st.info("No stocks currently above MA20 by >2%, or click Compute Momentum to scan.")
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


# ── Tab: Scanner ──────────────────────────────────────────────────────────────

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
        'Sweep the full TASE universe and rank by expected return score</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
    with c1:
        horizons = st.multiselect("Horizons", options=["short", "medium", "long"],
                                  default=["medium"], key="scan_horizons")
    with c2:
        top_n = st.slider("Top N", 5, 20, 10, key="scan_top_n")
    with c3:
        size_filter = st.selectbox("Size", ["", "large", "mid", "small"],
                                   format_func=lambda x: x.capitalize() if x else "All",
                                   key="scan_size")
    with c4:
        st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
        start_scan = st.button("Start Scan", type="primary", use_container_width=True, key="scan_start_btn")

    if start_scan:
        if not horizons:
            st.error("Select at least one horizon."); return
        def _run():
            from scan_tase import run_scanner
            run_scanner(horizons=horizons, top_n=top_n, output_dir=REPORTS_DIR,
                        size_filter=size_filter or None, resume=False, no_articles=True)
        threading.Thread(target=_run, daemon=True).start()
        st.session_state["scan_running"] = True
        st.success("Scan started in background. Results appear in reports/ as each stock completes.")

    # Show existing scan results
    scan_dirs = []
    rdir = Path(REPORTS_DIR)
    if rdir.exists():
        scan_dirs = sorted(
            [d for d in rdir.iterdir() if d.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}", d.name)],
            reverse=True,
        )

    if scan_dirs:
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        sel_date = st.selectbox("Scan date", [d.name for d in scan_dirs], key="scan_sel_date")
        for hz in ["short", "medium", "long"]:
            rank_file = rdir / sel_date / hz / "ranking_data.json"
            if rank_file.exists():
                ranking = json.loads(rank_file.read_text(encoding="utf-8"))
                st.markdown(
                    f'<div style="font-family:\'Barlow Condensed\',sans-serif;font-weight:700;'
                    f'font-size:0.85rem;letter-spacing:0.15em;text-transform:uppercase;'
                    f'margin:16px 0 6px;color:#57657a">{hz.upper()} results</div>',
                    unsafe_allow_html=True,
                )
                for entry in ranking[:10]:
                    score = entry.get("return_score", 0)
                    rec = entry.get("invest_recommendation", "")
                    color = {"YES": "#39d353", "NO": "#f85149", "CONDITIONAL": "#e3a00a"}.get(rec, "#57657a")
                    bar_c = _score_color(score)
                    st.markdown(f"""
                    <div style="display:flex;align-items:center;gap:14px;padding:8px 14px;
                      background:#0d1117;border:1px solid #1d2433;border-radius:3px;margin:3px 0">
                      <span style="font-family:\'JetBrains Mono\',monospace;font-size:0.72rem;color:#3d4f61;min-width:26px">#{entry.get("rank",0)}</span>
                      <span style="font-family:\'JetBrains Mono\',monospace;font-weight:700;color:#4d9de0;min-width:72px">{entry.get("ticker","")}</span>
                      <span style="color:#c9d1d9;flex:1;font-size:0.88rem">{entry.get("company_name","")}</span>
                      <span class="bk-badge" style="background:{color}12;color:{color}">{rec}</span>
                      <span style="font-family:\'JetBrains Mono\',monospace;font-weight:700;color:{bar_c};min-width:54px;text-align:right">{score}/100</span>
                    </div>
                    """, unsafe_allow_html=True)


# ── Main ──────────────────────────────────────────────────────────────────────

render_hero()

# Handle "go to analyze" navigation from Hot Stocks tab
if st.session_state.get("go_to_analyze"):
    del st.session_state["go_to_analyze"]
    st.info("Switch to the Analyze tab and your ticker is pre-filled.")

TAB_NAMES = ["Analyze", "Reports", "Maya Filings", "Hot Stocks", "Scanner"]
tabs = st.tabs(TAB_NAMES)

TAB_FUNCS = [tab_analyze, tab_reports, tab_maya, tab_hot, tab_scanner]
for tab, fn in zip(tabs, TAB_FUNCS):
    with tab:
        try:
            fn()
        except Exception as _err:
            import traceback
            st.error(f"Error: {_err}")
            with st.expander("Details"):
                st.code(traceback.format_exc())
