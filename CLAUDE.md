# BorsaProject (Brokai) — Claude Code Guide

## Who you are helping and what they are building

**Shai (Developer 1)** is building `israel_researcher` — an autonomous AI analyst for the Israeli stock market (TASE). This is the active, production module. When Shai asks for help, the work is almost always inside `israel_researcher/` or one of the shared support layers (`data/`, `utils/`, `shared/`).

The system runs every 15 minutes, reads Maya TASE filings in real-time, scans 500+ Israeli stocks for technical signals, runs 8 sector LLM agents in parallel, and sends Telegram alerts with scored stock picks. Think of it as a buy-side equity analyst running 24/7.

A second developer (Ido) is planned to build `portfolio/` on top of Shai's research signals — but that module does not exist yet.

## Purpose
AI-powered stock research for the Israeli (TASE) market, with a planned portfolio management layer.
Multi-developer monorepo — each top-level folder has a clear owner.

## Monorepo Layout

| Folder | Owner | Status | Purpose |
|--------|-------|--------|---------|
| `israel_researcher/` | Developer 1 (Shai) | Active | TASE research agent — Maya filings, sector agents, LLM scoring, Telegram bot |
| `portfolio/` | Developer 2 | Planned | Portfolio management built on research signals |
| `shared/` | Both | Active | Shared Python functions: top stocks, signal filtering, financial report parsing, portfolio analytics |
| `data/` | Both | Active | Runtime state & memory files read/written by all modules |
| `utils/` | Both | Active | Data-fetch and doc-generation scripts (fetch_maya, fetch_tase, build_llm_mapping, make_pdf, make_pptx) |
| `docs/` | Both | Active | Generated documentation — never edit directly |

## Collaboration Rules
1. `israel_researcher/` is Developer 1's domain — do not modify its internals.
2. `portfolio/` reads from `data/` and imports from `shared/` — not from `israel_researcher`.
3. Functions useful to both developers go in `shared/`, not inside either module.
4. All runtime data (state, memory, mappings) lives in `data/`.
5. Generated docs go in `docs/` only — never inside a package folder.
6. `.env` at root is shared by all modules.

## Entry Points

| Command (from project root) | Description |
|-----------------------------|-------------|
| `python -m israel_researcher` | TASE research loop + Telegram bot |
| `python portfolio/main.py` | (planned) Portfolio management |
| `python utils/make_pdf.py` | Regenerate PDF → docs/ |
| `python utils/make_pptx.py` | Regenerate slide deck → docs/ |
| `python utils/fetch_maya_companies.py` | Rebuild Maya company universe (Playwright, ~5 min) → data/maya_companies_full.xlsx |
| `python utils/fetch_tase_universe.py` | Rebuild TASE equity universe from YF Screener → data/tase_universe_full.xlsx |
| `python utils/build_llm_mapping.py` | Expand Maya companyId→.TA ticker mapping via GPT-4o-mini |

## Quick Shared API

```python
import json
from pathlib import Path
from shared.stocks import find_top_stocks, filter_signals_by_score
from shared.analytics import find_max_stock, calc_pnl, sector_weights
from shared.reports import parse_financial_report, summarize_filing

state = json.loads(Path("data/israel_researcher_state.json").read_text(encoding="utf-8"))
top = find_top_stocks(state, n=10)
```

---

### `israel_researcher/` package structure
```
israel_researcher/
├── __init__.py        ← SSL fix (copies certifi cert to %TEMP% for Hebrew username path)
├── config.py          ← credentials, thresholds, SECTOR_TICKERS, TASE_MAJOR_TICKERS
├── models.py          ← Signal dataclass, state persistence, refresh_company_cache()
├── alerts.py          ← TelegramReporter (quick alerts, daily summary, weekly report)
├── researcher.py      ← run_research_cycle(), main() loop
├── sources/
│   ├── maya.py        ← MayaMonitor, MayaFilingExtractor, EarningsCalendar
│   ├── market.py      ← MarketAnomalyDetector, SectorSignalDetector, SectorAnalyzer,
│   │                     MacroContext, DeepStockAnalyzer, DualListedMonitor,
│   │                     DynamicUniverseBuilder
│   ├── news_monitor.py← IsraeliNewsMonitor (RSS feeds + company name matching)
│   └── web_news.py    ← WebNewsSearcher (Google News RSS, targeted per-ticker search)
├── analysis/
│   ├── enricher.py    ← SignalEnricher (keyword → signal_type upgrade)
│   ├── convergence.py ← ConvergenceEngine (scoring, multipliers), WeeklyAccumulator
│   └── llm.py         ← LLMAnalyst (score_sector, arbitrate, extract_web_news_signals)
└── agents/
    ├── base.py        ← SectorAgent abstract base (run(), _fetch_web_news(), helpers)
    ├── banks.py       ← BanksAgent (Banks + Insurance + Finance, 15 tickers)
    ├── tech_defense.py← TechDefenseAgent (11 tickers)
    ├── energy.py      ← EnergyAgent (9 tickers)
    ├── pharma.py      ← PharmaAgent (5 tickers)
    ├── real_estate.py ← RealEstateAgent (14 tickers)
    ├── telecom_consumer.py ← TelecomConsumerAgent (8 tickers)
    ├── discovery.py   ← DiscoveryAgent (full TASE universe beyond sector lists)
    └── manager.py     ← ResearchManager (orchestrates all phases)
```

---

## `israel_researcher` — Full Pipeline & Flow

### Goal & Philosophy
The israel_researcher is designed to act as a **top-tier Israeli equity analyst** — not just a data scraper. Its mandate:

1. **Cover every Israeli stock** — the full TASE universe, not just the TA-35 or TA-125. Any company listed on TASE, including TA-SME, new IPOs, and low-coverage mid/small-caps, is in scope.

2. **Read and understand news like a human analyst** — Israeli news (Globes, Calcalist, TheMarker, Ynet, Walla, Maariv in Hebrew) and global financial news. Matches company names in articles to TASE tickers. Understands that a headline about "הבנק הבינלאומי" or "פז" maps to a specific stock.

3. **Factor in geopolitics and macro** — Israeli-specific macro context matters enormously: war/ceasefire news, government policy, BoI rate decisions, USD/ILS moves, oil prices (Israel is an energy importer), US-Israel relations, US tariffs affecting exporters, regional security events. These all feed into sector calls (defense up on escalation, tourism/retail down, energy up on oil spike, shekel depreciation helps exporters).

4. **Low-volume TASE stocks are not noise** — many Israeli small-caps trade with very low average volume. A volume spike of 3× on a stock that normally trades 50K shares/day is as meaningful as one on a high-volume stock. Do not filter out low-liquidity tickers — they can generate the highest-alpha signals.

5. **Maya filings are primary intelligence** — the Maya TASE disclosure system is the ground truth for corporate events. Every earnings release, contract win, institutional buyer entry, buyback, dividend, M&A, IPO, and management change is filed there first, before any media. The system reads Maya filings in real-time and scores them before the news cycle picks them up.

6. **Think in catalysts, not noise** — the LLM agents are expected to think like a buy-side analyst: what is the catalyst, how material is it relative to market cap, is it already priced in, what is the risk/reward. A NIS 5M contract for a NIS 500M company = noise; the same contract for a NIS 20M company = game-changer.

7. **Excel memory as analyst notebook** — `israel_researcher_memory.xlsx` accumulates signal history, fundamental snapshots, and analyst notes across cycles. This gives the LLM a "memory" of each stock: what happened last week, whether the signal was new or repeat, whether fundamentals are improving. Better memory → better LLM calls → less hallucination → more actionable alerts.

8. **IPO stocks are included from day 1** — when Maya publishes an IPO prospectus, the DiscoveryAgent immediately includes the company in scoring using its company name for web news search and the `maya_ipo` signal as catalyst, even before the stock starts trading on Yahoo Finance.

### Overview
A multi-agent system that runs every 15 minutes, scanning the full TASE market for actionable investment signals. It uses sector-specialized AI agents running in parallel, coordinated by a CIO manager agent that picks the best cross-sector stock of the week.

### Phase 1 — Cross-sector data collection (sequential)
Runs once per cycle before agents start. Uses a single shared Playwright browser session (required to bypass Maya's Incapsula WAF via same-origin fetch).

1. **Maya company cache** — `refresh_company_cache()` fetches all TASE-listed companies from Maya's autocomplete API (hundreds of companies, cached 24h). Used for news matching and as the base for universe expansion.
2. **Maya filings** — POST `/api/v1/reports/companies`, paginated to 100 filings. Each filing becomes a `maya_{type}` Signal (ipo, earnings, contract, institutional, buyback, dividend, spinoff, management). Ticker = `TASE{companyId}` pseudo-ticker (Maya API returns no real symbol).
3. **Institutional filings** — Same endpoint filtered by Hebrew keywords (מחזיק, בעל עניין, רכישה). High-value ones get full text fetched via `fetch_filing_text()` (max 2 per cycle) to extract deal_size, stake_pct, direction.
4. **Earnings calendar** — POST `/api/v1/corporate-actions/financial-reports-schedule`. Events within 10 days become `earnings_calendar` signals with `event_date`.
5. **Dual-listed US overnight moves** — `DualListedMonitor` checks 10 dual-listed stocks (TEVA, NICE, ICL, ESLT, NVMI, TSEM, CAMT, AUDC, ALLT, KMDA) via yfinance. Move ≥ 2% → `dual_listed_move` signal. Most reliable leading indicator for TASE open.
6. **Israeli news** — RSS feeds (Ynet, Walla, Maariv) via `IsraeliNewsMonitor`. Articles matched to companies by Hebrew name regex from the company cache. Often produces `GENERAL` ticker (name mismatch) — enricher upgrades signal type from keywords.
7. **Global headlines** — Yahoo Finance, MarketWatch, WSJ RSS. Used only as LLM context text (no signal generation).
8. **Macro snapshot** — `MacroContext` fetches TA-125, S&P500, VIX, USD/ILS, Nasdaq, **OIL_WTI (CL=F)**, and **US10Y (^TNX)** via yfinance. Formatted string injected into every LLM call. OIL_WTI directly informs energy sector calls; US10Y proxies the BoI rate cycle for banks/real estate.
9. **Sector rotation context** — `SectorAnalyzer` fetches 2-3 representative tickers per sector, computes 1M return and avg RSI, returns `BULL+/BULL/NEUTRAL/BEAR/BEAR-` labels. Also injected into every LLM call.

### Phase 2 — Sector agents (parallel, ThreadPoolExecutor 4 workers)
Seven agents run concurrently. Each is an instance of `SectorAgent` with its own ticker universe.

**Per-agent flow (run() in base.py):**

```
Step 1: Filter pre-fetched cross-sector signals for this sector's tickers
Step 2: MarketAnomalyDetector on all sector tickers (8 detectors):
        - volume_spike     (>2.5× 20d avg volume)
        - price_move       (abs daily move >3.5%)
        - breakout         (new 52w high with volume)
        - ma_crossover     (MA-20 crosses above MA-50, golden cross)
        - oversold_bounce  (RSI<32 + volume rising = accumulation)
        - low_reversal     (within 5% of 52w low + volume bounce)
        - consecutive_momentum (4+ consecutive up days with building volume)
        - relative_strength   (outperforming TA-125 by 5%+ over 20 days)
Step 3: Sector-specific macro signals (override per subclass):
        - BanksAgent:         KBE/XLF US bank ETF move, IL10Y bond yield proxy
        - TechDefenseAgent:   LMT/RTX peers, AMAT/KLAC semis peers, shekel move, VIX defense
        - EnergyAgent:        WTI (CL=F), NG=F, Brent (BZ=F), renewables peer NEE
        - PharmaAgent:        XBI, IBB biotech ETFs, MOS (potash proxy for ICL)
        - RealEstateAgent:    VNQ/IYR REIT ETFs, shekel move
        - TelecomConsumerAgent: XLP/IYZ ETFs, shekel move (importers)
        - DiscoveryAgent:     No sector signals (universe too diverse)
Step 4: Preliminary ConvergenceEngine.group_by_ticker() on all collected signals
Step 5: Filter to tickers with final_score > 0 (discovery-first — silent tickers excluded)
Step 6: Web news enrichment for top-5 preliminary candidates:
        - WebNewsSearcher hits Google News RSS (free, no API key)
        - Two queries per ticker: company name + ticker symbol
        - LLM (extract_web_news_signals) reads articles → structured signals
        - Signal types: new_contract, earnings, institutional_investor,
          regulatory_approval, partnership, buyback, dividend, ipo, general_news
        - relevance < 4 discarded; relevance 4-10 → Signal with score = relevance × 4
Step 7: Re-run ConvergenceEngine with enriched signal set (web news can raise scores)
Step 8: DeepStockAnalyzer on top-8 by score (RSI-14, MA-20, MA-50, pct_vs_52w_high,
        market_cap, revenue_growth_pct) — yfinance financial data
Step 9: Sector LLM (score_sector) — GPT with sector-specialized domain prompt
        Input:  all relevant tickers' convergence data + macro + technical data
        Output: full ranked portfolio [{ticker, tier:"buy|watch|monitor", score, rationale, key_catalyst}]
```

**DiscoveryAgent — full TASE universe coverage:**
- Uses `DynamicUniverseBuilder` which fetches all TLV-listed equities from Yahoo Finance Screener (replaces Maya company cache — Maya's API returns no real ticker symbols)
- Universe cached in `state["tase_universe_cache"]` (24h TTL) — typically 400-500 stocks
- Validates each `.TA` ticker against Yahoo Finance via `fast_info.last_price > 0`
- Validation results cached in `state["ticker_validation_cache"]` (valid: 30d TTL, invalid: 7d TTL)
- Max 50 new validations per cycle (raised from 25 to speed up initial cache population)
- Priority: real `.TA` symbols from Maya filings this cycle are validated first
- Covers TA-SME, newly listed companies, and any ticker not in the 6 sector lists
- **IPO handling**: `_filter_signals()` overrides the base class to pass through `maya_ipo` and `maya_spinoff` signals directly, even when no real ticker exists yet. The `TASE{id}` pseudo-ticker is used; web news search uses the company name (Hebrew) as the Google query. LLM scores the IPO on its filing catalyst + any web news found. No Yahoo Finance data needed.
- Runs standard 8-detector technical scan on all validated uncovered tickers

### Phase 3 — Manager LLM arbitration (sequential)
`ResearchManager._arbitrate()` receives the full portfolio from all 7 sector agents (not just top-1).

**CIO prompt rules:**
- No 2 picks from the same sector unless score > 90
- Prioritize sector with strongest macro tailwind this week
- Balance large-cap with at least one mid/small-cap
- Best pick requires: hard catalyst + confirming technicals + macro alignment
- Portfolio diversification: not all cyclical or all defensive

**Output** — same schema as weekly report:
```json
{
  "stock_of_the_week": {"ticker","name","score","full_rationale","key_catalyst","technical_setup","main_risk","keywords"},
  "runners_up": [{"ticker","name","score","summary","key_catalyst"}],
  "macro_context": "...",
  "week_theme": "...",
  "sector_in_focus": "..."
}
```

### Signal scoring — ConvergenceEngine
- **BASE_SCORES** — 40+ signal types. Top scores: `maya_ipo`=50, `maya_contract`=45, `new_contract`=45, `regulatory_approval`=42, `maya_institutional`=40, `institutional_investor`=40, `ipo`=38 (web), `earnings`=35 (web), `breakout`=35, `dual_listed_move`=35
- **MULTIPLIERS** — ~130 pairs. Top: `earnings_calendar + volume_spike`=2.5×, `low_reversal + earnings_calendar`=2.4×, `oversold_bounce + earnings_calendar`=2.3×, `earnings + volume_spike`=2.3×, `relative_strength + earnings_calendar`=2.2×
- **Earnings gradient** added to base_score: dte=0→+80, dte=1→+70, dte=2→+60, dte=3→+45, dte≤7→+25, dte≤14→+12
- **Three-category boost**: 1.3× additional multiplier if 3+ independent signal categories converge
- `final_score = base_score × multiplier`

### Convergence logic — ticker identity problem
Maya filings use `TASE{companyId}` pseudo-tickers. yfinance uses real `.TA` tickers. These **cannot converge with each other** — a company's Maya filing and its volume spike are treated as different tickers unless a real symbol can be resolved.

Only market-anomaly signals, dual-listed signals, and web news signals carry real `.TA` tickers. This is the main reason sector agent discovery depends on technicals + web news for real-ticker coverage.

### Reports & alerts
- **Quick alert**: every cycle if any stock has `final_score > 0` after manager arbitration — top 3 via Telegram
- **Daily summary**: once after 17:00 Israel time — top 3 from today's arbitration
- **Weekly report** (Thursday 17:00): full Stock of the Week from manager LLM, with deep financial data

### LLM analyst prompts — what they know

All prompts (`_QUICK_SYSTEM`, `_SECTOR_BASE_SYSTEM`, `_MANAGER_SYSTEM`) include:

**Israeli geopolitical framework** — explicit rules for:
- Security escalation → defense sector boost, retail/tourism discount
- BoI rate changes (proxied via US10Y) → banks/insurance up, real estate down
- Shekel moves → exporter vs importer impact
- Oil spikes (WTI) → energy producer revenue uplift
- Israeli political instability → domestic sector discount
- US-Israel diplomatic friction → defense export risk

**Small-cap & low-volume guidance**:
- TASE micro-caps (<100K shares/day) are valid, not noise — volume spike is actionable
- For avg_volume < 300K/day: require hard catalyst before scoring > 65
- Market-cap relative catalyst: deal_size > 10% of market_cap = transformative; < 1% = immaterial
- IPO stocks (TASE pseudo-tickers): score on IPO catalyst + web news, no technicals penalty

**Web news signal types** include `geopolitical` — defense contracts, government tenders, sanctions, security events directly affecting a company.

**Memory context** injected into every sector LLM call includes:
- Latest analyst notes + prior week notes (trend recognition across weeks)
- Signal history: consecutive active cycles, recent signal types, best score
- Recent news headlines
- Technicals: RSI, MA trend, vs-52w-high, revenue growth, **market cap** (for catalyst materiality assessment)

### State persistence (`israel_researcher_state.json`)
```json
{
  "seen_maya_report_ids":    [],     // deduplication for Maya filings (never expires)
  "seen_signal_keys":        [],     // deduplication for market anomaly signals (today only)
  "tase_company_cache":      {"fetched_at":"...", "companies":[...]},  // 24h TTL (Hebrew company names → IDs)
  "tase_universe_cache":     {"fetched_at":"...", "tickers":[]},       // 24h TTL (all real .TA tickers from YF Screener)
  "ticker_validation_cache": {"ABCD.TA":{"valid":true,"checked":"2026-03-25"}},  // YF liveness check
  "stock_memory":            {"TEVA":{"fundamentals":{}, "analyst_notes":"", "prior_analyst_notes":"",
                              "llm_sentiment":"bullish", "llm_memory_note":"<key takeaway>",
                              "llm_risk_flag":"<what invalidates thesis>", "llm_watch_for":"<price/event>"}},
  "weekly_signals":          [],     // accumulates all signals for weekly report
  "week_start":              "",
  "last_run_iso":            "",
  "last_daily_report":       "",
  "last_weekly_report":      "",
  "last_weekly_pick":        "",     // prevents same stock winning twice in a row
  "alerted_today":           {"TEVA":"2026-03-26"}  // daily quick-alert dedup (resets each day)
}
```

### Excel memory (`israel_researcher_memory.xlsx`)
Three sheets that serve as the analyst's persistent notebook:
- **Sheet 1 — Active Stock Memory**: full `stock_memory` backup. Restored to state on startup if state was wiped. Columns: Ticker, LastSeen, SignalCount, BestScore, FundamentalSnapshot, AnalystNotes, NewsHeadlines.
- **Sheet 2 — Buy/Watch Picks**: filtered view of tickers currently in buy or watch tier.
- **Sheet 3 — Sent Alerts**: every Telegram alert ever sent (Timestamp, Week, Date, Type, Ticker, Company, Score, Key Catalyst). Used for daily dedup recovery on restart — `restore_sent_alerts()` reads today's rows to repopulate `alerted_today` if state was reset. Also prevents the same stock being recommended repeatedly without new catalysts.

---

## Running the Project

### Setup
```bash
# Activate virtual environment
source venv/Scripts/activate  # Windows

# Install dependencies (if needed)
pip install yfinance feedparser trafilatura openai pandas beautifulsoup4 playwright
playwright install chromium
```

### Entry Points
```bash
python main.py                # Main stock analysis pipeline
python alert.py               # aTyr Pharma news monitor (Telegram)
python multibiutec.py         # Multi-company biotech news monitor (Telegram)
python -m israel_researcher   # Israeli stock research agent (TASE, Maya, LLM)
```

### Required Configuration (hardcoded in `israel_researcher/config.py`)
- `BOT_TOKEN` — Telegram bot token
- `CHAT_ID` — Telegram chat ID
- `OPENAI_API_KEY` — OpenAI API key
- `OPENAI_MODEL` — default `gpt-4o-mini`

## Tech Stack
- **LLM**: OpenAI API (GPT models)
- **Financial data**: yfinance
- **Data**: pandas, Excel (openpyxl)
- **News**: requests, BeautifulSoup4, feedparser, trafilatura, Google News RSS
- **Browser automation**: Playwright (headless Chromium) — required for Maya scraping
- **Alerts**: Telegram Bot API
- **Python**: 3.8+, dataclasses, pathlib

---

## Known Limitations & Gotchas

- **Maya ticker mapping (238 mappings, 170 unique tickers)**: `data/maya_company_mapping.json` maps Maya `companyId` → real `.TA` ticker. Built via Hebrew name matching + GPT-4o-mini resolution. `maya.py` loads this on startup via `_load_company_mapping()` and uses `resolve_ticker(companyId)` in `reports_to_signals()`. Maya filing signals for known companies now carry real `.TA` tickers and `ticker_yf`, so they CAN converge with yfinance technical signals in the ConvergenceEngine. Companies not in the mapping still get `TASE{cid}` pseudo-tickers. To expand: run `python utils/build_llm_mapping.py`.
- **Maya pseudo-tickers (for unknown companies)**: Maya API returns no real stock symbols for ~850 smaller/private companies. These still use `TASE{companyId}` IDs. IPO stocks are an exception: DiscoveryAgent scores them directly via their `maya_ipo` signal + company-name web news search.
- **Maya company cache has no real tickers**: `fetch_company_list()` now uses real `.TA` ticker when known via `maya_company_mapping.json`, else `TASE{id}`. `DynamicUniverseBuilder` uses Yahoo Finance Screener (exchange=TLV) as the universe source. The Maya company cache is used for Hebrew company name → ID mapping (for news matching).
- **yfinance SSL on Hebrew username**: `__init__.py` copies certifi cert to `%TEMP%\brokai_cacert.pem` and sets `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE` before any imports.
- **Israeli news name matching**: Regex word-boundary match on Hebrew company names from Maya autocomplete. Often fails (name variants, abbreviations) → `GENERAL` ticker → contributes nothing to convergence. Hebrew text matching is inherently imprecise due to construct forms and abbreviations.
- **Low-volume TASE stocks**: Many TA-SME stocks trade <50K shares/day. `MarketAnomalyDetector` thresholds are calibrated for TASE (volume_spike = 2.5×, price_move = 3.5%) — do not raise these as it would exclude valid small-cap signals.
- **New IPOs**: `maya_ipo` signal fires on day of prospectus. DiscoveryAgent now includes these immediately (via `_filter_signals` override) and searches web news by company name. No Yahoo Finance ticker needed.
- **YF Screener availability**: `yf.Screener` requires yfinance 0.2.37+. If unavailable or rate-limited, `_fetch_tase_universe()` returns empty and DiscoveryAgent logs a warning and skips that cycle — sector agents are unaffected.
- **Google News rate limiting**: `WebNewsSearcher` uses 0.3s sleep between queries. If Google blocks (429), results return empty — agent continues without web news for that cycle.
- **DynamicUniverseBuilder throttle**: Max 50 new Yahoo Finance validations per cycle. First run takes ~10 cycles to validate the full ~500-stock TLV universe.
- **Daily alert dedup**: `alerted_today` in state prevents re-sending the same stock multiple times in one day. Restored from Excel (Sheet 3) on restart. Resets each calendar day.
- **Memory analyst notes**: Accumulate across days — current analysis stored in `analyst_notes`, previous day's notes preserved in `prior_analyst_notes`. LLM sees both for trend recognition. Notes are NOT overwritten within the same day; overwritten with prior-preservation on next day.
- **Structured LLM memory insights**: Each sector LLM call also returns `memory_update` per stock with 4 fields: `memory_note` (distilled 1-sentence non-obvious insight), `sentiment` (bullish/bearish/neutral), `risk_flag` (what invalidates thesis), `watch_for` (price level or catalyst to monitor). These are saved via `StockMemoryManager.update_llm_insights()` and injected back into the next cycle's LLM prompt via `build_context_string()`. This lets the LLM notice patterns humans and raw signals miss (e.g. "third consecutive week of volume with no news = informed trading").
- **Market cap in memory**: `build_context_string()` includes `mktCap` from cached fundamentals so the LLM can assess catalyst size relative to company size without additional API calls.
- **Delisted stocks**: Sapiens International (SPNS/SMTC) — delisted Dec 2025. Magic Software (MGIC) — delisted Feb 2026. Silicom (SILC) — acquired by Celestica 2023. Kornit Digital (KRNT.TA) — delisted from TASE 2021, still on Nasdaq only. Ituran (ITRN.TA) — delisted from TASE, still on Nasdaq only. Do not add `.TA` variants of these.
- **`^TA35.TA` invalid**: Use `^TA125.TA` instead.
- **Clal Insurance**: ticker is `CLIS.TA` not `CLAL.TA`.
- **State files**: Never delete `*_state.json` — they track deduplication and validation caches that take many cycles to rebuild. Excel memory survives state wipes and is used to restore `stock_memory` and `alerted_today`.

## Notes
- No `requirements.txt` — dependencies live in `venv/`
- `clientProtfolio.py` is deprecated
- `seen.json` deduplicates news articles by URL — 0 news signals on re-run is normal; new articles appear every 15-30 min

---

## Telegram Bot — Interactive Interface

The bot runs as a **daemon thread** alongside the main research cycle. It transforms the system from a push-only broadcaster into a two-way analyst assistant.

### Threading model

```
Main thread  → Research cycle (Playwright, ThreadPoolExecutor, state updates every 15 min)
Bot thread   → Daemon long-poll (getUpdates timeout=30s, no Playwright, no blocking)
Shared state → RLock-guarded; bot deepcopies state before LLM calls (lock held for ms only)
Settings     → bot_state.json (separate file; survives research state resets)
```

### Routing

```
Incoming Telegram message
  ├── starts with "/"  →  handle_command()    commands.py — mutates settings or reads state
  └── free text        →  QAPipeline.answer() qa_pipeline.py — LLM intent → tools → answer
        ├── 10 sec per-chat cooldown enforced
        ├── "Analyzing..." placeholder sent immediately
        ├── state deepcopy taken under RLock
        └── reply split at paragraph boundaries (≤4096 chars/chunk)
```

### Slash commands (14 total)

**Settings — mutate `BotSettings`, saved atomically to `bot_state.json`:**

| Command | Range | Effect | Takes effect |
|---------|-------|--------|--------------|
| `/set_interval <min>` | 5–240 | Scan interval | Next `time.sleep()` |
| `/set_topn <n>` | 1–10 | Stocks per alert | Immediately |
| `/set_volume <x>` | 1.5–10.0 | Volume spike threshold (× 20d avg) | Next cycle |
| `/set_price <pct>` | 1.0–20.0 | Price move threshold (% abs daily) | Next cycle |
| `/set_language en\|he` | — | Reply language for all bot messages | Immediately |
| `/set_sectors s1,s2,...` | ALL_SECTORS | Which sector agents run | Next cycle |
| `/enable_alerts` | — | Gates `send_quick_alerts()` in manager | Immediately |
| `/disable_alerts` | — | Same — turns off | Immediately |

Valid sector names: `Banks  TechDefense  Energy  PharmaBiotech  RealEstate  TelecomConsumer  Discovery`

**Status — read-only:**

| Command | Data source | Output |
|---------|-------------|--------|
| `/help` | Static | Full command reference |
| `/status` | `settings` + `state` | Interval, language, alerts, last scan time, alerted today |
| `/macro` | `MacroContext()` — live yfinance | TA-125, S&P500, Nasdaq, USD/ILS, VIX, WTI oil, US10Y |
| `/earnings` | `state["weekly_signals"]` | Upcoming earnings events with days-to-earnings |
| `/weekly` | `state["last_arbitration_report"]` | Stock of the week + runners-up + macro context |
| `/sector <name>` | `SectorAnalyzer()` — live yfinance | BULL+/BULL/NEUTRAL/BEAR/BEAR- + RSI + 1M return |

### Q&A pipeline — free-text questions

Three LLM calls per question:

```
1. plan_intent(question, known_tickers, tool_catalogue)
   → {ticker, intent, tools[], language}

2. Tool execution — runs selected tools sequentially (skipped if intent=direct_answer)
   → context string concatenated from tool outputs

3. chat_answer(question, context, language, history)
   → plain-text answer (3–6 sentences)
   → no context → LLM answers from own knowledge (direct_answer mode)
```

**Intent types:** `stock_analysis` · `live_scan` · `earnings_query` · `market_overview` · `sector_query` · `ipo_query` · `maya_query` · `recommendations` · `tracker_query` · `direct_answer` · `general_question`

**Conversation history:** Last 8 messages (4 turns) per `chat_id` stored in `BotServer._chat_history`. Passed to `chat_answer()` — follow-ups like "what about its RSI?" resolve the ticker from the prior turn automatically.

**Hebrew ticker resolution:** When `plan_intent` returns `ticker=null` for a stock-specific intent, `_resolve_ticker_from_state()` is called:
- Builds company list from `state["tase_company_cache"]["companies"]` (up to 500 entries)
- Calls `llm.resolve_ticker(question, company_list)` → `{ticker, company_name, confidence}`
- Accepted only if `confidence >= 0.6`
- Resolved `company_name` stored in `state["_bot_resolved_company"]` so `search_news` can use it as the Google query

### Tool registry — 11 tools (all Playwright-free)

**Live market data (yfinance / Google News RSS):**

| Tool | Ticker? | Returns |
|------|---------|---------|
| `get_macro` | No | TA-125, S&P500, Nasdaq, USD/ILS, VIX, WTI, US10Y |
| `get_sector_context` | No | BULL+/BULL/NEUTRAL/BEAR/BEAR- per sector + RSI + 1M return |
| `get_stock_data` | Required | RSI-14, MA-20, MA-50, trend, last price, 52w high/low, market cap, revenue/income growth, avg volume |
| `run_live_scan` | Required | Real-time anomaly scan (volume spike, breakout, oversold bounce, low reversal, momentum, relative strength) |
| `search_news` | Required | Up to 8 Google News articles (title + snippet); uses `_bot_resolved_company` for Hebrew tickers |

**Researcher state (populated every 15 min, no network call):**

| Tool | Ticker? | Returns |
|------|---------|---------|
| `get_weekly_signals` | Optional | All signals this week for ticker, or top-20 by score across all |
| `get_maya_filings` | Optional | Maya TASE regulatory filings (IPO, M&A, contract, institutional, earnings, buyback, dividend, management) |
| `get_alerted_stocks` | No | Stock-of-the-week + runners-up + alerted tickers with scores + catalysts |
| `get_recent_ipos` | No | IPO and new-listing signals from Maya this week |
| `get_tracked_stocks` | No | All stocks in memory: sentiment, best score, memory note, watch-for (up to 40, bullish first) |
| `get_memory` | Optional | Deep analyst memory for one ticker (notes, sentiment, risk flag, signal history, fundamentals) |

**Tool selection by intent:**
- Stock question → `get_stock_data + search_news + get_memory` (+ `run_live_scan` if asking about *right now*)
- "What to buy" → `get_alerted_stocks + get_macro`
- Market overview → `get_macro + get_sector_context`
- Sector question → `get_sector_context + get_macro`
- IPO / new listings → `get_recent_ipos + get_macro`
- Maya filings → `get_maya_filings`
- "What are you tracking?" → `get_tracked_stocks`
- Greeting / concept / bot question → `direct_answer` (no tools, instant LLM response)

### Score calibration (updated)

`to_llm_input()` no longer sends `final_score` to the LLM (prevents anchoring bias).
It sends `signal_strength` (raw weight sum) and `convergence_multiplier` (corroboration factor)
as input-only indicators. The LLM scores each stock independently.

Expected weekly distribution:
- Most stocks: **38–58**
- Strong buy: **65–81**
- Exceptional (≤1 per month): **85–100**

### `BotSettings` fields (`bot_state.json`)

| Field | Default | Controls |
|-------|---------|----------|
| `language` | `"en"` | All bot reply text |
| `alerts_enabled` | `True` | Gates `send_quick_alerts()` in manager |
| `scan_interval_seconds` | `900` | `time.sleep()` duration in main loop |
| `top_n_alerts` | `3` | How many stocks per quick alert |
| `volume_spike_x` | `2.5` | Passed to `MarketAnomalyDetector` |
| `price_move_pct` | `3.5` | Passed to `MarketAnomalyDetector` |
| `enabled_sectors` | all | Filters `_AGENT_CLASSES` list in `ResearchManager` |
| `last_offset` | `0` | Telegram `getUpdates` dedup offset |

Saved via atomic temp-file rename. `last_offset` persisted after every batch so no message is re-processed on restart.
