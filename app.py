"""
Borkai Web App — Israeli Stock Analysis
Run with:  streamlit run app.py
"""
import streamlit as st
import os
import json
import re
import threading
from datetime import date, datetime
from pathlib import Path

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Borkai | Israeli Stock Analysis",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

.stApp {
    background-color: #0d1117;
    color: #e6edf3;
    font-family: 'Inter', system-ui, -apple-system, "Segoe UI", sans-serif;
}
.main .block-container { padding-top: 1rem; max-width: 1280px; }

/* Hero header */
.bk-hero {
    background: linear-gradient(135deg, #0d1117 0%, #161b22 50%, #0d2036 100%);
    border-bottom: 1px solid #30363d;
    padding: 1rem 1.5rem;
    border-radius: 8px;
    margin-bottom: 1.5rem;
}

/* Generic cards */
.bk-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 20px;
    margin: 8px 0;
}

/* Sector cards */
.bk-sector-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 12px 16px;
    margin: 4px 0;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

/* Maya feed items */
.bk-feed-item {
    background: #161b22;
    border-left: 3px solid #30363d;
    border-radius: 0 8px 8px 0;
    padding: 12px 16px;
    margin: 6px 0;
}
.bk-feed-bullish  { border-left-color: #3fb950; }
.bk-feed-bearish  { border-left-color: #f85149; }
.bk-feed-neutral  { border-left-color: #8b949e; }

/* Verdict boxes */
.bk-verdict-yes  { background:#0d2818; border:3px solid #3fb950; border-radius:12px; padding:24px; text-align:center; margin:16px 0; }
.bk-verdict-no   { background:#2d0f0f; border:3px solid #f85149; border-radius:12px; padding:24px; text-align:center; margin:16px 0; }
.bk-verdict-cond { background:#2d1f0a; border:3px solid #d29922; border-radius:12px; padding:24px; text-align:center; margin:16px 0; }
.bk-verdict-title  { font-size:2rem; font-weight:900; margin:0 0 8px 0; }
.bk-verdict-score  { font-size:3rem; font-weight:bold; margin:8px 0; }
.bk-verdict-detail { font-size:0.95rem; color:#8b949e; margin-top:12px; }

/* Score bar */
.bk-score-wrap { background:#30363d; border-radius:4px; height:8px; margin:8px 0; overflow:hidden; }
.bk-score-bar  { height:8px; border-radius:4px; transition:width 0.3s; }

/* Badges */
.bk-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 600;
    margin: 2px;
}

/* Hot stock cards */
.bk-hot-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 16px;
    margin: 6px 0;
    transition: border-color 0.2s;
}
.bk-hot-card:hover { border-color: #58a6ff; }
.bk-hot-ticker  { font-size: 1.3rem; font-weight: 700; color: #58a6ff; }
.bk-hot-company { font-size: 0.9rem; color: #8b949e; margin-bottom: 4px; }
.bk-hot-headline { font-size: 0.8rem; color: #8b949e; font-style: italic; margin-top: 8px; }

/* Metric overrides */
[data-testid="stMetricValue"] { color: #e6edf3 !important; }
[data-testid="stMetricLabel"] { color: #8b949e !important; }

/* Table rows */
.row-yes  { color: #3fb950 !important; }
.row-no   { color: #f85149 !important; }
.row-cond { color: #d29922 !important; }

/* Headings */
h1, h2, h3, h4 { color: #e6edf3; }

/* Inputs */
.stTextInput input, .stSelectbox select, .stNumberInput input {
    background-color: #161b22 !important;
    border-color: #30363d !important;
    color: #e6edf3 !important;
}

/* Tab styling */
.stTabs [data-baseweb="tab-list"] {
    background-color: #161b22;
    border-radius: 8px;
    padding: 4px;
    gap: 4px;
    border: 1px solid #30363d;
    margin-bottom: 1rem;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 6px;
    color: #8b949e;
    font-weight: 600;
    font-size: 0.9rem;
    padding: 8px 16px;
}
.stTabs [aria-selected="true"] {
    background-color: #1c2d3a !important;
    color: #58a6ff !important;
}

/* Divider */
hr { border-color: #30363d; }

/* Sidebar */
[data-testid="stSidebar"] { background-color: #161b22; border-right: 1px solid #30363d; }
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────
HORIZON_LABELS = {
    "short":  "Short (1-4 weeks)",
    "medium": "Medium (1-6 months)",
    "long":   "Long (1-3 years)",
}
REC_ICONS = {"YES": "✅", "NO": "❌", "CONDITIONAL": "⚠️"}
REPORTS_DIR = "reports"
TICKERS_CSV = "borkai/data/tase_stocks.csv"
CACHE_TTL_SECONDS = 3600  # 1 hour


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_tase_tickers():
    """Return list of dicts: ticker, name, sector, market_cap_bucket."""
    import csv
    if not os.path.exists(TICKERS_CSV):
        return []
    with open(TICKERS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def list_scan_dates():
    """Return sorted list of YYYY-MM-DD date strings in reports/, newest first."""
    if not os.path.exists(REPORTS_DIR):
        return []
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    dirs = [d for d in os.listdir(REPORTS_DIR)
            if os.path.isdir(os.path.join(REPORTS_DIR, d)) and pattern.match(d)]
    return sorted(dirs, reverse=True)


def load_ranking(scan_date: str, horizon: str):
    """Load ranking_data.json for a given scan date + horizon."""
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
    if score >= 70:
        return "#3fb950"
    if score >= 45:
        return "#d29922"
    return "#f85149"


def cache_age_seconds(cache_key: str, ts_key: str) -> float:
    """Return seconds since cache was stored, or inf if no cache."""
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
    icon = REC_ICONS.get(rec.upper(), "❓")
    label = {"YES": "BUY", "NO": "AVOID", "CONDITIONAL": "CONDITIONAL"}.get(rec.upper(), rec)
    bar_color = score_color(score)
    dir_label = {"up": "Upward ↑", "down": "Downward ↓", "mixed": "Mixed ↔"}.get(direction, direction)
    conv_label = {"high": "High", "moderate": "Moderate", "low": "Low"}.get(conviction, conviction)
    badge_style_dir  = "background:#1c2d3a; color:#58a6ff;"
    badge_style_conv = "background:#1f2d1a; color:#3fb950;" if conviction == "high" else "background:#2d2a1a; color:#d29922;"
    rationale_html = f"<div class='bk-verdict-detail'>{rationale}</div>" if rationale else ""

    st.markdown(f"""
    <div class="{css_class}">
      <div class="bk-verdict-title">{icon} {label}</div>
      <div class="bk-verdict-score" style="color:{bar_color}">{score}<span style="font-size:1.2rem;color:#8b949e">/100</span></div>
      <div class="bk-score-wrap" style="width:60%;margin:8px auto;">
        <div class="bk-score-bar" style="width:{score}%;background:{bar_color};"></div>
      </div>
      <div style="margin-top:10px;">
        <span class="bk-badge" style="{badge_style_dir}">Direction: {dir_label}</span>
        <span class="bk-badge" style="{badge_style_conv}">Conviction: {conv_label}</span>
      </div>
      {rationale_html}
    </div>
    """, unsafe_allow_html=True)


# ── Hot Stocks computation ────────────────────────────────────────────────────

POSITIVE_KEYWORDS = [
    "win", "up", "beat", "above", "growth", "positive", "strong",
    "surge", "rally", "profit", "record", "raised", "outperform",
    "upgrade", "buy", "bullish", "dividend", "earnings beat",
]

def _compute_hot_stocks(tickers_data: list) -> list:
    """
    Compute hot score for each stock:
    - momentum_score: price vs 20-day SMA
    - news_score: count positive-keyword headlines * 10 (capped 50)
    Returns list of dicts sorted by hot_score desc.
    """
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

        # ----- momentum score -----
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
                if pct_above > 5:
                    momentum_score = 40
                elif pct_above > 2:
                    momentum_score = 20
                elif pct_above > 0:
                    momentum_score = 5
                else:
                    momentum_score = 0
        except Exception:
            pass

        # ----- news score -----
        news_score   = 0
        top_headline = ""
        news_count   = 0
        if has_news:
            try:
                news_items = fetch_sector_news(
                    company_name=company,
                    sector=sector,
                    max_items=10,
                )
                pos_hits = sum(
                    1 for n in news_items
                    if any(kw in (n.title or "").lower() for kw in POSITIVE_KEYWORDS)
                )
                news_score = min(50, pos_hits * 10)
                news_count = len(news_items)
                top_headline = news_items[0].title if news_items else ""
            except Exception:
                pass

        hot_score = momentum_score + news_score

        # only include stocks with meaningful signal
        if hot_score >= 30 and momentum_pct > 0:
            results.append({
                "ticker":        ticker,
                "company":       company,
                "sector":        sector,
                "size":          size,
                "hot_score":     hot_score,
                "momentum_score": momentum_score,
                "momentum_pct":  momentum_pct,
                "news_score":    news_score,
                "news_count":    news_count,
                "top_headline":  top_headline,
            })

    results.sort(key=lambda x: x["hot_score"], reverse=True)
    return results


# ── Tab: Overview ─────────────────────────────────────────────────────────────

def tab_overview():
    # Hero
    st.markdown("""
    <div class="bk-hero">
      <span style="font-size:2rem;font-weight:900;color:#58a6ff;">📈 Borkai</span>
      <span style="color:#8b949e;font-size:1rem;margin-left:12px;">Israeli Stock Analysis · AI-Powered</span>
      <div style="color:#8b949e;font-size:0.82rem;margin-top:4px;">
        TA-125 coverage · Real-time Maya disclosures · LLM-driven analysis
      </div>
    </div>
    """, unsafe_allow_html=True)

    hot_cache    = st.session_state.get("hot_stocks_cache", [])
    maya_cache   = st.session_state.get("maya_reports_cache", [])
    hot_age      = cache_age_seconds("hot_stocks_cache", "_hot_stocks_ts")
    maya_age     = cache_age_seconds("maya_reports_cache", "_maya_reports_ts")
    hot_fresh    = hot_age < CACHE_TTL_SECONDS
    maya_fresh   = maya_age < CACHE_TTL_SECONDS

    no_data = not hot_cache and not maya_cache

    if no_data:
        st.info("No cached data yet. Use the tabs above to load Hot Stocks or Maya Reports, then return here for the overview.")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("🔥 Go to Hot Stocks", use_container_width=True):
                st.session_state["_nav_to_tab"] = 2
                st.rerun()
        with col_b:
            if st.button("📰 Go to Maya Reports", use_container_width=True):
                st.session_state["_nav_to_tab"] = 1
                st.rerun()
        return

    left_col, mid_col, right_col = st.columns([1.2, 1, 1])

    # ── Left: Hot Sectors ──
    with left_col:
        st.markdown("#### 🌡️ Hot Sectors")
        if hot_cache:
            from collections import Counter
            sector_counts = Counter(s["sector"] for s in hot_cache)
            sector_scores: dict = {}
            for s in hot_cache:
                sec = s["sector"]
                sector_scores.setdefault(sec, []).append(s["hot_score"])
            sector_avg = {sec: sum(v)/len(v) for sec, v in sector_scores.items()}
            top_sectors = sorted(sector_avg.items(), key=lambda x: x[1], reverse=True)[:8]
            for sec, avg_score in top_sectors:
                count = sector_counts[sec]
                bar_color = score_color(int(avg_score))
                indicator = "🟢" if avg_score >= 60 else "🟡" if avg_score >= 40 else "🔴"
                st.markdown(f"""
                <div class="bk-sector-card">
                  <span style="font-weight:600;color:#e6edf3">{indicator} {sec}</span>
                  <span>
                    <span class="bk-badge" style="background:#1c2d3a;color:#58a6ff">{count} stocks</span>
                    <span style="color:{bar_color};font-weight:700">{avg_score:.0f}</span>
                  </span>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown("<span style='color:#8b949e'>No hot stocks data cached.</span>", unsafe_allow_html=True)

    # ── Middle: Top 5 Hot Stocks ──
    with mid_col:
        st.markdown("#### 🔥 Top 5 Hot Stocks")
        if hot_cache:
            for stock in hot_cache[:5]:
                ticker      = stock["ticker"]
                company     = stock["company"]
                hot_score   = stock["hot_score"]
                mom_pct     = stock["momentum_pct"]
                bar_color   = score_color(hot_score)
                mom_color   = "#3fb950" if mom_pct > 0 else "#f85149"
                st.markdown(f"""
                <div class="bk-hot-card" style="padding:12px 14px;margin:4px 0;">
                  <div style="display:flex;justify-content:space-between;align-items:center">
                    <span class="bk-hot-ticker" style="font-size:1.1rem">{ticker}</span>
                    <span class="bk-badge" style="background:{bar_color}22;color:{bar_color}">{hot_score} pts</span>
                  </div>
                  <div class="bk-hot-company">{company}</div>
                  <span class="bk-badge" style="background:{mom_color}22;color:{mom_color};font-size:0.75rem">
                    +{mom_pct:.1f}% above MA
                  </span>
                  <div class="bk-score-wrap" style="margin:6px 0 0 0">
                    <div class="bk-score-bar" style="width:{min(hot_score,100)}%;background:{bar_color}"></div>
                  </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown("<span style='color:#8b949e'>No hot stocks data cached.</span>", unsafe_allow_html=True)

    # ── Right: Latest 5 Maya Reports ──
    with right_col:
        st.markdown("#### 📰 Latest Maya Reports")
        if maya_cache:
            for report in maya_cache[:5]:
                impact = getattr(report, "impact", "neutral").lower()
                feed_cls = f"bk-feed-{impact}"
                impact_color = {"bullish": "#3fb950", "bearish": "#f85149"}.get(impact, "#8b949e")
                ticker_badge = f"<span class='bk-badge' style='background:#1c2d3a;color:#58a6ff'>{report.ticker}</span>" if report.ticker else ""
                title_short = (report.title or "")[:70] + ("…" if len(report.title or "") > 70 else "")
                st.markdown(f"""
                <div class="bk-feed-item {feed_cls}">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
                    {ticker_badge}
                    <span class="bk-badge" style="background:{impact_color}22;color:{impact_color};font-size:0.72rem">{impact}</span>
                  </div>
                  <div style="font-size:0.85rem;color:#e6edf3;line-height:1.3">{title_short}</div>
                  <div style="font-size:0.75rem;color:#8b949e;margin-top:4px">{report.source}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown("<span style='color:#8b949e'>No Maya reports cached.</span>", unsafe_allow_html=True)

    # ── CTA row ──
    st.divider()
    cta1, cta2, cta3 = st.columns(3)
    with cta1:
        if st.button("🚀 Scan Market Now", use_container_width=True):
            st.session_state["_nav_to_tab"] = 3
            st.rerun()
    with cta2:
        if st.button("🔍 Analyze a Stock", use_container_width=True):
            st.session_state["_nav_to_tab"] = 4
            st.rerun()
    with cta3:
        if st.button("🔄 Refresh Overview", use_container_width=True):
            st.session_state.pop("hot_stocks_cache", None)
            st.session_state.pop("_hot_stocks_ts", None)
            st.session_state.pop("maya_reports_cache", None)
            st.session_state.pop("_maya_reports_ts", None)
            st.rerun()


# ── Tab: Maya Reports ─────────────────────────────────────────────────────────

def tab_maya_reports():
    st.markdown("## 📰 Maya Reports")
    st.markdown("<span style='color:#8b949e'>Live TASE corporate disclosure feed from Google News, analyzed by AI.</span>", unsafe_allow_html=True)

    maya_cache = st.session_state.get("maya_reports_cache", [])
    maya_ts    = st.session_state.get("_maya_reports_ts")
    age_str    = f"Fetched {int((datetime.now() - maya_ts).total_seconds() / 60)}m ago" if maya_ts else "Not fetched yet"

    col_btn, col_age = st.columns([1, 3])
    with col_btn:
        refresh = st.button("🔄 Refresh Feed", type="primary", use_container_width=True)
    with col_age:
        st.markdown(f"<span style='color:#8b949e;font-size:0.85rem'>{age_str}</span>", unsafe_allow_html=True)

    if refresh:
        tickers_data = load_tase_tickers()
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if not openai_key:
            st.error("OPENAI_API_KEY environment variable not set. Cannot run LLM analysis.")
            return
        try:
            import openai as _openai
            from borkai.config import load_config
            from borkai.data.maya_fetcher import get_maya_reports
            client = _openai.OpenAI(api_key=openai_key)
            config = load_config()
            with st.spinner("Fetching and analyzing Maya reports…"):
                reports = get_maya_reports(
                    client=client,
                    config=config,
                    known_stocks=tickers_data,
                    max_reports=40,
                )
            st.session_state["maya_reports_cache"] = reports
            st.session_state["_maya_reports_ts"] = datetime.now()
            maya_cache = reports
            st.success(f"Fetched {len(reports)} reports.")
        except Exception as e:
            st.error(f"Failed to fetch Maya reports: {e}")
            return

    if not maya_cache:
        st.info("Click **Refresh Feed** to load the latest Maya reports.")
        return

    # ── Sector activity summary ──
    from collections import Counter
    sectors_seen = [r.sector for r in maya_cache if r.sector]
    if sectors_seen:
        sector_counts = Counter(sectors_seen)
        st.markdown("**Sector Activity Today:**")
        badges_html = " ".join(
            f"<span class='bk-badge' style='background:#1c2d3a;color:#58a6ff'>{sec} ({cnt})</span>"
            for sec, cnt in sector_counts.most_common(8)
        )
        st.markdown(badges_html, unsafe_allow_html=True)
        st.divider()

    # ── Filters ──
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        impact_filter = st.selectbox(
            "Filter by impact",
            options=["all", "bullish", "bearish", "neutral"],
            format_func=lambda x: {"all": "All impacts", "bullish": "🟢 Bullish", "bearish": "🔴 Bearish", "neutral": "⚪ Neutral"}[x],
        )
    with filter_col2:
        all_sectors_in_feed = sorted(set(r.sector for r in maya_cache if r.sector))
        sector_filter = st.multiselect("Filter by sector", options=all_sectors_in_feed)

    # Apply filters
    filtered = maya_cache
    if impact_filter != "all":
        filtered = [r for r in filtered if getattr(r, "impact", "neutral").lower() == impact_filter]
    if sector_filter:
        filtered = [r for r in filtered if r.sector in sector_filter]

    st.markdown(f"<span style='color:#8b949e'>Showing {len(filtered)} of {len(maya_cache)} reports</span>", unsafe_allow_html=True)
    st.divider()

    for report in filtered:
        impact = getattr(report, "impact", "neutral").lower()
        feed_cls = f"bk-feed-{impact}"
        impact_color = {"bullish": "#3fb950", "bearish": "#f85149"}.get(impact, "#8b949e")
        impact_icon  = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}.get(impact, "⚪")
        ticker_badge = (
            f"<span class='bk-badge' style='background:#1c2d3a;color:#58a6ff'>{report.ticker}</span>"
            if report.ticker else ""
        )
        company_html = (
            f"<span style='color:#e6edf3;font-weight:600'>{report.company_name}</span> "
            if report.company_name else ""
        )
        rtype_badge = (
            f"<span class='bk-badge' style='background:#21262d;color:#8b949e'>{report.report_type}</span>"
        )
        summary_html = (
            f"<div style='color:#c9d1d9;font-size:0.87rem;margin-top:6px'>{report.summary}</div>"
            if report.summary else ""
        )
        reason_html = (
            f"<div style='color:#8b949e;font-size:0.8rem;margin-top:4px;font-style:italic'>{report.impact_reason}</div>"
            if report.impact_reason else ""
        )
        link_html = (
            f"<a href='{report.link}' target='_blank' style='color:#58a6ff;font-size:0.78rem'>Read more →</a>"
            if report.link else ""
        )
        pub_html = f"<span style='color:#8b949e;font-size:0.78rem'>{report.source} · {report.published[:16]}</span>" if report.published else ""

        st.markdown(f"""
        <div class="bk-feed-item {feed_cls}" style="margin-bottom:10px">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:4px">
            <div>
              {company_html}{ticker_badge}{rtype_badge}
            </div>
            <span class="bk-badge" style="background:{impact_color}22;color:{impact_color}">
              {impact_icon} {impact.capitalize()}
            </span>
          </div>
          <div style="font-size:0.92rem;color:#e6edf3;margin-top:8px;font-weight:500;line-height:1.4">
            {report.title}
          </div>
          {summary_html}
          {reason_html}
          <div style="margin-top:8px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap">
            {pub_html}
            {link_html}
          </div>
        </div>
        """, unsafe_allow_html=True)


# ── Tab: Hot Stocks ───────────────────────────────────────────────────────────

def tab_hot_stocks():
    st.markdown("## 🔥 Hot Stocks")
    st.markdown("<span style='color:#8b949e'>TASE stocks with strong price momentum above 20-day SMA and positive news sentiment.</span>", unsafe_allow_html=True)

    tickers_data = load_tase_tickers()
    if not tickers_data:
        st.warning(f"No tickers found at `{TICKERS_CSV}`.")
        return

    hot_cache = st.session_state.get("hot_stocks_cache", [])
    hot_ts    = st.session_state.get("_hot_stocks_ts")
    age_str   = f"Computed {int((datetime.now() - hot_ts).total_seconds() / 60)}m ago" if hot_ts else "Not computed yet"

    col_btn, col_age = st.columns([1, 3])
    with col_btn:
        refresh = st.button("🔄 Refresh Hot Stocks", type="primary", use_container_width=True)
    with col_age:
        st.markdown(f"<span style='color:#8b949e;font-size:0.85rem'>{age_str}</span>", unsafe_allow_html=True)

    if refresh:
        st.session_state.pop("hot_stocks_cache", None)
        st.session_state.pop("_hot_stocks_ts", None)
        hot_cache = []

    if not hot_cache:
        if refresh or (hot_ts is None):
            with st.spinner(f"Computing momentum scores for {len(tickers_data)} stocks… (this may take a minute)"):
                results = _compute_hot_stocks(tickers_data)
            st.session_state["hot_stocks_cache"] = results
            st.session_state["_hot_stocks_ts"] = datetime.now()
            hot_cache = results
            if results:
                st.success(f"Found {len(results)} hot stocks.")
            else:
                st.info("No stocks met the hot criteria right now (hot_score ≥ 30 and price above MA20).")
                return
        else:
            st.info("Click **Refresh Hot Stocks** to compute momentum scores.")
            return

    if not hot_cache:
        return

    sectors = sorted(set(s.get("sector", "") for s in tickers_data if s.get("sector")))

    # Filters
    f_col1, f_col2 = st.columns(2)
    with f_col1:
        sector_filter = st.multiselect("Filter by sector", options=sectors, key="hot_sector_filter")
    with f_col2:
        min_score = st.slider("Min hot score", min_value=0, max_value=90, value=30, step=5, key="hot_min_score")

    filtered = hot_cache
    if sector_filter:
        filtered = [s for s in filtered if s.get("sector") in sector_filter]
    if min_score > 0:
        filtered = [s for s in filtered if s.get("hot_score", 0) >= min_score]

    st.markdown(f"<span style='color:#8b949e'>Showing {len(filtered)} stocks</span>", unsafe_allow_html=True)
    st.divider()

    cols = st.columns(3)
    for i, stock in enumerate(filtered):
        ticker       = stock["ticker"]
        company      = stock["company"]
        sector       = stock["sector"]
        hot_score    = stock["hot_score"]
        mom_pct      = stock["momentum_pct"]
        news_count   = stock["news_count"]
        top_headline = stock.get("top_headline", "")
        news_score   = stock.get("news_score", 0)
        mom_score    = stock.get("momentum_score", 0)

        hot_color = score_color(hot_score)
        mom_color = "#3fb950" if mom_pct > 0 else "#f85149"

        with cols[i % 3]:
            headline_html = (
                f"<div class='bk-hot-headline'>{top_headline[:90]}{'…' if len(top_headline) > 90 else ''}</div>"
                if top_headline else ""
            )
            st.markdown(f"""
            <div class="bk-hot-card">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <span class="bk-hot-ticker">{ticker}</span>
                <span class="bk-badge" style="background:{hot_color}22;color:{hot_color};font-size:0.9rem">{hot_score}</span>
              </div>
              <div class="bk-hot-company">{company}</div>
              <span class="bk-badge" style="background:#1f2d1a;color:#3fb950;font-size:0.72rem">{sector}</span>
              <div style="margin-top:10px">
                <span class="bk-badge" style="background:{mom_color}22;color:{mom_color}">
                  MA: +{mom_pct:.1f}% ({mom_score}pts)
                </span>
                <span class="bk-badge" style="background:#21262d;color:#8b949e">
                  News: {news_count} ({news_score}pts)
                </span>
              </div>
              <div class="bk-score-wrap" style="margin-top:8px">
                <div class="bk-score-bar" style="width:{min(hot_score,100)}%;background:{hot_color}"></div>
              </div>
              {headline_html}
            </div>
            """, unsafe_allow_html=True)

            if st.button(f"Analyze {ticker} →", key=f"hot_analyze_{ticker}_{i}", use_container_width=True):
                st.session_state["analyze_ticker"] = ticker
                st.session_state["_nav_to_tab"] = 4
                st.rerun()


# ── Tab: Scanner ──────────────────────────────────────────────────────────────

def tab_scanner():
    st.markdown("## 📊 Scan the Market")
    st.markdown("<span style='color:#8b949e'>Scan all TASE stocks, rank by expected return score, and save reports for the top performers.</span>", unsafe_allow_html=True)

    tickers_data = load_tase_tickers()
    sectors = sorted(set(t.get("sector", "") for t in tickers_data if t.get("sector")))

    # Config row
    col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
    with col1:
        horizons = st.multiselect(
            "Time Horizons",
            options=["short", "medium", "long"],
            default=["medium"],
            format_func=lambda x: HORIZON_LABELS[x],
        )
    with col2:
        top_n = st.slider("Top N to save", 5, 20, 10)
    with col3:
        size_filter = st.selectbox(
            "Size Filter",
            options=["", "large", "mid", "small"],
            format_func=lambda x: {"": "All sizes", "large": "Large cap", "mid": "Mid cap", "small": "Small cap"}[x],
        )
    with col4:
        no_articles = st.checkbox("Skip article fetch (faster)", value=True)

    col_start, col_resume = st.columns(2)
    with col_start:
        start_scan = st.button("🚀 Start New Scan", type="primary", use_container_width=True)
    with col_resume:
        resume_scan = st.button("🔄 Resume Scan", use_container_width=True)

    if start_scan or resume_scan:
        if not horizons:
            st.error("Please select at least one time horizon.")
            return

        def run_in_bg(resume: bool):
            from scan_tase import run_scanner
            run_scanner(
                horizons=horizons,
                top_n=top_n,
                output_dir=REPORTS_DIR,
                size_filter=size_filter or None,
                resume=resume,
                no_articles=no_articles,
            )

        t = threading.Thread(target=run_in_bg, args=(resume_scan,), daemon=True)
        t.start()
        st.session_state["scan_date"] = str(date.today())
        st.success("Scan started in background! Click **Refresh** below to track progress.")

    # Progress display
    scan_date = st.session_state.get("scan_date") or (list_scan_dates() or [None])[0]
    if not scan_date:
        st.info("No scan data yet. Start a new scan above.")
        return

    st.divider()
    st.markdown(f"### Scan Status — {scan_date}")

    progress = read_scan_progress(scan_date)
    if not progress:
        st.info("No progress data yet. The scan may still be initializing.")
    else:
        done  = sum(1 for v in progress.values() if v.get("status") == "done")
        filt  = sum(1 for v in progress.values() if v.get("status") == "filtered")
        fail  = sum(1 for v in progress.values() if v.get("status") == "failed")
        total = len(progress)

        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Total Processed", total)
        col_b.metric("Done", done)
        col_c.metric("Filtered", filt)
        col_d.metric("Failed", fail)

        pct = done / max(total, 1)
        bar_color = score_color(int(pct * 100))
        st.markdown(
            f"<div class='bk-score-wrap'><div class='bk-score-bar' style='width:{pct*100:.1f}%;background:{bar_color}'></div></div>",
            unsafe_allow_html=True,
        )
        st.caption(f"{done}/{total} stocks analyzed ({pct*100:.0f}%)")

    if st.button("🔄 Refresh"):
        st.rerun()

    # Scan history
    scan_dates = list_scan_dates()
    if len(scan_dates) > 1:
        with st.expander("📅 Scan History"):
            for sd in scan_dates:
                horizons_available = [
                    h for h in ["short", "medium", "long"]
                    if os.path.exists(os.path.join(REPORTS_DIR, sd, h, "ranking_data.json"))
                ]
                h_badges = " ".join(
                    f"<span class='bk-badge' style='background:#1c2d3a;color:#58a6ff'>{HORIZON_LABELS[h]}</span>"
                    for h in horizons_available
                )
                st.markdown(
                    f"<div class='bk-card' style='padding:8px 16px'>"
                    f"<span style='color:#e6edf3;font-weight:600'>{sd}</span> {h_badges}</div>",
                    unsafe_allow_html=True,
                )

    # Results per horizon
    for horizon in ["short", "medium", "long"]:
        ranking = load_ranking(scan_date, horizon)
        if ranking:
            st.markdown(f"#### Results — {HORIZON_LABELS[horizon]}")
            _render_ranking_table(ranking, scan_date, horizon)


def _render_ranking_table(ranking: list, scan_date: str, horizon: str):
    if not ranking:
        return
    for entry in ranking:
        score  = entry.get("return_score", 0)
        ticker = entry.get("ticker", "")
        name   = entry.get("company_name", "")
        rec    = entry.get("invest_recommendation", "")
        rank   = entry.get("rank", 0)
        in_top = entry.get("in_top", False)

        color     = "#3fb950" if rec == "YES" else "#f85149" if rec == "NO" else "#d29922"
        icon      = REC_ICONS.get(rec, "")
        bar_color = score_color(score)

        st.markdown(f"""
        <div class="bk-card" style="display:flex;align-items:center;gap:16px;padding:12px 20px;">
          <span style="color:#8b949e;font-size:0.85rem;min-width:28px">#{rank}</span>
          <span style="color:#58a6ff;font-weight:700;min-width:60px">{ticker}</span>
          <span style="color:#e6edf3;flex:1">{name}</span>
          <span class="bk-badge" style="background:#1a1a2e;color:{color}">{icon} {rec}</span>
          <span style="color:{bar_color};font-weight:700;min-width:64px;text-align:right">{score}/100</span>
          {"<span class='bk-badge' style='background:#0d2020;color:#3fb950;font-size:0.7rem'>TOP</span>" if in_top else ""}
        </div>
        """, unsafe_allow_html=True)

        if in_top and entry.get("report_file"):
            he_file = Path(entry["report_file"]).name.replace(".md", "_he.md")
            content = load_report_file(scan_date, horizon, he_file)
            if content:
                with st.expander(f"📄 Report: {ticker}"):
                    st.markdown(content)
                    st.download_button(
                        "📥 Download",
                        data=content.encode("utf-8"),
                        file_name=he_file,
                        mime="text/markdown",
                        key=f"dl_{scan_date}_{horizon}_{ticker}",
                    )


# ── Tab: Analyze ──────────────────────────────────────────────────────────────

def tab_analyze():
    st.markdown("## 🔍 Analyze a Stock")
    st.markdown("<span style='color:#8b949e'>Enter an Israeli stock ticker — the system will analyze it and return a full report.</span>", unsafe_allow_html=True)

    prefill = st.session_state.pop("analyze_ticker", "")

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        ticker_raw = st.text_input(
            "Ticker Symbol",
            value=prefill,
            placeholder="ESLT / BEZQ / TEVA ...",
            help="Without .TA suffix — added automatically",
        )
    with col2:
        horizon = st.selectbox(
            "Time Horizon",
            options=["short", "medium", "long"],
            format_func=lambda x: HORIZON_LABELS[x],
        )
    with col3:
        st.write("")
        st.write("")
        run_btn = st.button("▶ Analyze", type="primary", use_container_width=True)

    if run_btn:
        if not ticker_raw.strip():
            st.error("Please enter a ticker symbol.")
            return

        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if not openai_key:
            st.error("OPENAI_API_KEY environment variable not set. Cannot run analysis.")
            return

        ticker = ticker_raw.strip().upper().replace(".TA", "")
        st.session_state.pop("analysis_result", None)

        with st.status(f"Analyzing {ticker} — please wait...", expanded=True) as status_widget:
            progress_bar = st.progress(0.0)

            def on_progress(stage: int, label: str, detail: str):
                pct = min(stage / 8, 1.0)
                progress_bar.progress(pct)
                st.write(f"**Stage {stage}/8 — {label}** {detail}")

            try:
                from main import analyze
                report_en, report_he, result = analyze(
                    ticker=ticker,
                    time_horizon=horizon,
                    market="il",
                    save_report=True,
                    progress_callback=on_progress,
                )
                st.session_state["analysis_result"] = (report_he, result)
                progress_bar.progress(1.0)
                status_widget.update(label=f"Analysis complete — {ticker}", state="complete")
            except Exception as e:
                status_widget.update(label=f"Analysis failed: {e}", state="error")
                st.error(f"Error during analysis: {e}")
                return

    if "analysis_result" in st.session_state:
        report_he, result = st.session_state["analysis_result"]
        d = result.decision

        st.divider()
        render_verdict_card(
            rec=d.invest_recommendation,
            score=d.return_score,
            direction=d.direction,
            conviction=d.conviction,
            rationale=d.invest_rationale,
        )

        col_dl, col_info = st.columns([1, 3])
        with col_dl:
            fname = f"borkai_{result.ticker}_{result.time_horizon}_{result.analysis_date}_he.md"
            st.download_button(
                label="📥 Download Hebrew Report",
                data=report_he.encode("utf-8"),
                file_name=fname,
                mime="text/markdown",
                use_container_width=True,
            )
        with col_info:
            name  = result.profile.company_name if hasattr(result, "profile") else ""
            horiz = HORIZON_LABELS.get(result.time_horizon, result.time_horizon)
            st.markdown(
                f"<div class='bk-card'><span style='color:#58a6ff;font-weight:700'>{result.ticker}</span>"
                f"<span style='color:#8b949e'> · {name} · {horiz} · {result.analysis_date}</span></div>",
                unsafe_allow_html=True,
            )

        st.divider()
        with st.expander("📄 Full Hebrew Report", expanded=True):
            st.markdown(report_he)


# ── Tab: Reports ──────────────────────────────────────────────────────────────

def tab_reports():
    st.markdown("## 📁 Saved Reports")

    scan_dates = list_scan_dates()
    if not scan_dates:
        st.info("No saved reports yet. Run a stock analysis or market scan first.")
        return

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        selected_date = st.selectbox("Scan Date", scan_dates)
    with col2:
        available_horizons = [
            h for h in ["short", "medium", "long"]
            if os.path.exists(os.path.join(REPORTS_DIR, selected_date, h, "ranking_data.json"))
        ]
        if not available_horizons:
            st.info("No ranking data found for this date.")
            return
        selected_horizon = st.selectbox(
            "Time Horizon",
            available_horizons,
            format_func=lambda x: HORIZON_LABELS.get(x, x),
        )
    with col3:
        st.write("")
        top_only = st.checkbox("Top only", value=True)

    ranking = load_ranking(selected_date, selected_horizon)
    if not ranking:
        st.info("No ranking data for this date and horizon.")
        return

    display = [r for r in ranking if r.get("in_top")] if top_only else ranking
    st.markdown(
        f"<span style='color:#8b949e'>{HORIZON_LABELS.get(selected_horizon, selected_horizon)} · {selected_date} · {len(display)} stocks</span>",
        unsafe_allow_html=True,
    )
    st.divider()

    for entry in display:
        score  = entry.get("return_score", 0)
        ticker = entry.get("ticker", "")
        name   = entry.get("company_name", "")
        rec    = entry.get("invest_recommendation", "")
        rank   = entry.get("rank", 0)
        in_top = entry.get("in_top", False)

        color     = "#3fb950" if rec == "YES" else "#f85149" if rec == "NO" else "#d29922"
        icon      = REC_ICONS.get(rec, "")
        bar_color = score_color(score)

        st.markdown(f"""
        <div class="bk-card" style="display:flex;align-items:center;gap:16px;padding:12px 20px;">
          <span style="color:#8b949e;font-size:0.85rem;min-width:28px">#{rank}</span>
          <span style="color:#58a6ff;font-weight:700;min-width:60px">{ticker}</span>
          <span style="color:#e6edf3;flex:1">{name}</span>
          <div class="bk-score-wrap" style="width:80px;margin:0 8px">
            <div class="bk-score-bar" style="width:{score}%;background:{bar_color}"></div>
          </div>
          <span style="color:{bar_color};font-weight:700;min-width:54px;text-align:right">{score}/100</span>
          <span class="bk-badge" style="background:#1a1a2e;color:{color}">{icon} {rec}</span>
          {"<span class='bk-badge' style='background:#0d2020;color:#3fb950;font-size:0.7rem'>TOP</span>" if in_top else ""}
        </div>
        """, unsafe_allow_html=True)

        if entry.get("report_file"):
            he_file = Path(entry["report_file"]).name.replace(".md", "_he.md")
            content = load_report_file(selected_date, selected_horizon, he_file)
            if content:
                with st.expander(f"📄 Open report: {ticker} — {name}"):
                    st.markdown(content)
                    st.download_button(
                        "📥 Download Hebrew Report",
                        data=content.encode("utf-8"),
                        file_name=he_file,
                        mime="text/markdown",
                        key=f"saved_{selected_date}_{selected_horizon}_{ticker}",
                    )


# ── Main layout ───────────────────────────────────────────────────────────────

TAB_LABELS = [
    "🏠 Overview",
    "📰 Maya Reports",
    "🔥 Hot Stocks",
    "📊 Scanner",
    "🔍 Analyze",
    "📁 Reports",
]

TAB_FUNCS = [
    tab_overview,
    tab_maya_reports,
    tab_hot_stocks,
    tab_scanner,
    tab_analyze,
    tab_reports,
]

tabs = st.tabs(TAB_LABELS)
for i, (tab, fn) in enumerate(zip(tabs, TAB_FUNCS)):
    with tab:
        fn()
