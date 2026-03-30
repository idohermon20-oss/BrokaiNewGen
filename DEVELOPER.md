# Israel Researcher — Developer Guide

**System:** AI-powered TASE (Tel Aviv Stock Exchange) equity research agent
**Language:** Python 3.10+
**Primary entry point:** `python -m israel_researcher`
**Last updated:** 2026-03-27

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Directory Structure](#2-directory-structure)
3. [Data Models](#3-data-models)
4. [Research Cycle — Full Pipeline](#4-research-cycle--full-pipeline)
   - 4.1 Phase 1: Cross-Sector Data Collection
   - 4.2 Phase 2: Parallel Sector Agents
   - 4.3 Phase 3: Manager LLM Arbitration
5. [Memory System](#5-memory-system)
6. [Signal Scoring & Convergence](#6-signal-scoring--convergence)
7. [Telegram Bot Interface](#7-telegram-bot-interface)
   - 7.1 Threading Model
   - 7.2 Slash Commands
   - 7.3 Q&A Pipeline
   - 7.4 Custom User Alerts
8. [LLM Prompts Reference](#8-llm-prompts-reference)
9. [Configuration Reference](#9-configuration-reference)
10. [State & Persistence](#10-state--persistence)
11. [Adding a New Sector Agent](#11-adding-a-new-sector-agent)
12. [Adding a New Bot Tool](#12-adding-a-new-bot-tool)
13. [Running & Deployment](#13-running--deployment)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Architecture Overview

The system is a **multi-agent AI research loop** that runs every 15 minutes, scanning the full TASE market for actionable investment signals. It combines:

- **Regulatory filings** from Maya TASE (ground truth, ahead of news)
- **Technical analysis** via yfinance (volume spikes, breakouts, RSI/MA signals)
- **Israeli financial news** (Globes, Calcalist, TheMarker via Playwright; Ynet/Walla/Maariv RSS)
- **Google News** per-stock (real-time enrichment)
- **Macro context** (TA-125, S&P500, VIX, USD/ILS, WTI oil, US10Y)
- **LLM scoring** (OpenAI GPT — sector-specialized + CIO arbitration)
- **Persistent memory** (per-stock analyst notes + signal history + fundamentals cache)
- **Interactive Telegram bot** (natural-language Q&A + slash commands)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          researcher.py  (main loop)                         │
│                                                                             │
│   Main thread:  ResearchManager.run_cycle() every 15 min                   │
│   Bot thread:   BotServer.start_daemon() — long-poll Telegram               │
│   Shared state: threading.RLock guarded; bot deepcopies before LLM calls   │
└────────────────────────┬────────────────────────────────────────────────────┘
                         │
         ┌───────────────▼───────────────┐
         │         ResearchManager        │
         │                               │
         │  Phase 1 ─ cross-sector data  │  (sequential, Playwright browser)
         │  Phase 2 ─ sector agents      │  (parallel, ThreadPoolExecutor × 4)
         │  Phase 3 ─ manager LLM pick   │  (sequential)
         └───────────────────────────────┘
                         │
         ┌───────────────▼──────────────────────────────────────┐
         │              Sector Agents (7 total)                  │
         │                                                      │
         │  BanksAgent      TechDefenseAgent   EnergyAgent      │
         │  PharmaAgent     RealEstateAgent    TelecomAgent      │
         │  DiscoveryAgent (full TASE universe)                  │
         │                                                      │
         │  Each agent: technicals → sector macro → convergence  │
         │              → web news enrichment → LLM score        │
         └──────────────────────────────────────────────────────┘
```

---

## 2. Directory Structure

```
israel_researcher/
├── __init__.py         SSL cert fix + package exports
├── __main__.py         Entry point (python -m israel_researcher)
├── config.py           All credentials, thresholds, sector tickers
├── models.py           Signal dataclass, state load/save, helpers
├── researcher.py       Main loop: BotServer daemon + run_cycle()
├── alerts.py           TelegramReporter — quick alerts, summaries, weekly
│
├── agents/
│   ├── base.py         SectorAgent abstract base class
│   ├── manager.py      ResearchManager — orchestrates all 3 phases
│   ├── banks.py        BanksAgent (15 tickers: banks + insurance + finance)
│   ├── tech_defense.py TechDefenseAgent (11 tickers)
│   ├── energy.py       EnergyAgent (9 tickers)
│   ├── pharma.py       PharmaAgent (5 tickers)
│   ├── real_estate.py  RealEstateAgent (14 tickers)
│   ├── telecom_consumer.py TelecomConsumerAgent (8 tickers)
│   └── discovery.py    DiscoveryAgent (full TASE universe, ~500 stocks)
│
├── analysis/
│   ├── convergence.py  ConvergenceEngine — signal scoring + multipliers
│   ├── enricher.py     SignalEnricher — keyword-based signal type upgrade
│   ├── llm.py          LLMAnalyst — all LLM calls (sector, manager, Q&A)
│   ├── memory.py       StockMemoryManager — per-stock persistent knowledge
│   └── excel_memory.py ExcelMemoryStore — 3-sheet Excel backup
│
├── sources/
│   ├── maya.py         MayaMonitor — TASE filing API (Playwright WAF bypass)
│   ├── market.py       MarketAnomalyDetector, DeepStockAnalyzer, MacroContext,
│   │                   SectorAnalyzer, DualListedMonitor, DynamicUniverseBuilder
│   ├── news_monitor.py IsraeliNewsMonitor — RSS + company name matching
│   ├── web_news.py     WebNewsSearcher — Google News RSS per ticker
│   └── chrome_news.py  ChromeNewsSearcher — Playwright scraper (Globes, etc.)
│
└── bot/
    ├── server.py       BotServer — Telegram long-poll daemon thread
    ├── bot_state.py    BotSettings dataclass + JSON persistence
    ├── commands.py     18 slash command handlers
    ├── qa_pipeline.py  QAPipeline — 3-LLM-call Q&A flow + 14 tools
    └── user_alerts.py  Custom user-defined alert rules
```

---

## 3. Data Models

### 3.1 Signal — Core Data Unit

```python
@dataclass
class Signal:
    ticker:       str           # TASE{companyId} or ABCD (bare symbol)
    ticker_yf:    str           # Yahoo Finance symbol: ABCD.TA (or empty)
    company_name: str           # Human-readable company name (Hebrew or English)
    signal_type:  str           # See signal type list below
    headline:     str           # Short summary (1 sentence)
    detail:       str           # Full context (2-4 sentences or filing text)
    url:          str           # Source URL
    timestamp:    str           # ISO-8601 datetime string
    keywords_hit: list[str]     # Keywords that triggered signal (from enricher)
    score:        float         # Raw signal score (from BASE_SCORES)
    event_date:   str           # YYYY-MM-DD for earnings_calendar signals
```

**Signal type hierarchy (40+ types, by source):**

| Source | Signal Types |
|--------|-------------|
| Maya TASE filings | `maya_ipo` (50pts), `maya_spinoff` (48), `maya_ma` (45), `maya_contract` (45), `maya_buyback` (42), `maya_institutional` (40), `maya_earnings` (35), `maya_dividend` (32), `maya_rights` (22), `maya_management` (18) |
| News/enricher | `new_contract` (45), `government_defense` (45), `regulatory_approval` (42), `institutional_investor` (40), `shareholder_return` (32), `partnership` (30), `financial_event` (25) |
| Technical detectors | `breakout` (35), `dual_listed_move` (35), `low_reversal` (32), `oversold_bounce` (30), `ma_crossover` (28), `relative_strength` (22), `consecutive_momentum` (20) |
| Sector macro | `oil_correlation` (25), `defense_tailwind` (28), `shekel_move` (20), `sector_peer_move` (22) |
| Calendar | `earnings_calendar` (20) |
| Web news extracted | `ipo` (38), `earnings` (35), `buyback` (30), `dividend` (28), `general_news` (15) |

### 3.2 BotSettings — Runtime Configuration

```python
@dataclass
class BotSettings:
    language:             str   = "en"        # "en" | "he"
    alerts_enabled:       bool  = True         # gates send_quick_alerts()
    scan_interval_seconds: int  = 900          # sleep between cycles (15 min)
    top_n_alerts:         int   = 3            # stocks per quick alert
    volume_spike_x:       float = 2.5          # volume anomaly threshold
    price_move_pct:       float = 3.5          # price move threshold (%)
    enabled_sectors:      list  = ALL_SECTORS  # which agents run
    last_offset:          int   = 0            # Telegram getUpdates dedup
```

Saved atomically to `bot_state.json` via temp-file rename.

### 3.3 State Dict — Full Schema

```json
{
  "last_run_iso":           "2026-03-27T14:30:00",
  "last_daily_report":      "2026-03-27",
  "last_weekly_report":     "2026-03-27",
  "last_weekly_pick":       "TEVA",
  "seen_maya_report_ids":   ["abc123", "..."],
  "seen_signal_keys":       ["TEVA_volume_spike_2026-03-27", "..."],
  "alerted_today":          {"TEVA": "2026-03-27", "ESLT": "2026-03-27"},
  "week_start":             "2026-03-23",

  "weekly_signals":         [{...Signal as dict...}, ...],

  "tase_company_cache": {
    "fetched_at": "2026-03-27T10:00:00",
    "companies":  [{"CompanyName": "טבע תעשיות", "CompanyId": "123", "CompanyTicker": "TASE123"}]
  },

  "tase_universe_cache": {
    "fetched_at": "2026-03-27T10:00:00",
    "tickers":    ["TEVA.TA", "ESLT.TA", "LUMI.TA", "..."]
  },

  "ticker_validation_cache": {
    "TEVA.TA":  {"valid": true,  "checked": "2026-03-27"},
    "XXXX.TA":  {"valid": false, "checked": "2026-03-27"}
  },

  "stock_memory": {
    "TEVA": {
      "company_name":       "Teva Pharmaceutical Industries",
      "fundamentals":       {"rsi_14": 45.2, "ma_trend": "bullish", "last_price": 12.78,
                             "pct_vs_52w_high": -16.2, "market_cap": 45000000000,
                             "revenue_growth_pct": 8.3},
      "fundamentals_date":  "2026-03-27",
      "analyst_notes":      "Strong recovery momentum. Volume building on positive catalysts.",
      "prior_analyst_notes":"[2026-03-20] Breaking out of consolidation range.",
      "notes_date":         "2026-03-27",
      "llm_sentiment":      "bullish",
      "llm_memory_note":    "Third consecutive week of volume above 20d average.",
      "llm_risk_flag":      "US generic drug pricing headwinds persist.",
      "llm_watch_for":      "Break above ₪13.50 with volume confirmation.",
      "signal_history": [
        {"date": "2026-03-20", "signal_types": ["volume_spike", "ma_crossover"], "final_score": 55.0},
        {"date": "2026-03-27", "signal_types": ["breakout", "dual_listed_move"], "final_score": 68.0}
      ],
      "consecutive_active": 2,
      "recent_news":        "Teva wins EU approval | Q4 beat expectations | New CEO announced",
      "news_date":          "2026-03-27",
      "maya_history": [
        {"date": "2026-03-15", "type": "maya_earnings", "headline": "Q4 2025 Results",
         "detail": "Revenue $3.8B, up 8% YoY", "company": "טבע תעשיות"}
      ]
    }
  },

  "last_arbitration_report": {
    "stock_of_the_week": {
      "ticker": "ESLT", "name": "Elbit Systems", "score": 72,
      "full_rationale": "...", "key_catalyst": "Defense contract $500M",
      "technical_setup": "Breaking out of 3-month consolidation",
      "main_risk": "FX exposure on USD contracts", "keywords": ["defense", "contract"]
    },
    "runners_up": [{"ticker": "NVMI", "name": "Nova", "score": 65, "key_catalyst": "..."}],
    "macro_context": "Risk-on environment. VIX low. S&P500 at ATH.",
    "week_theme":    "Defense sector outperforming on geopolitical tensions.",
    "sector_in_focus": "TechDefense"
  }
}
```

---

## 4. Research Cycle — Full Pipeline

### 4.1 Phase 1: Cross-Sector Data Collection

**File:** `agents/manager.py` → `ResearchManager._gather_cross_sector()`

All steps run **sequentially** using a **shared Playwright browser session** (required to bypass Maya's Incapsula WAF via same-origin fetch). Steps:

| Step | Source | What it produces |
|------|--------|------------------|
| 1 | `models.refresh_company_cache()` | Maya company list (400+ companies, Hebrew names + IDs). 24h cache. |
| 2 | `TASEMarketScraper.get_stocks()` | Full 548-stock TASE list from market.tase.co.il with security numbers. Supplements company_map for news matching. |
| 3 | `MayaMonitor.fetch_recent_reports(100)` | Last 100 Maya filings → `maya_*` Signal objects. Deduped by report ID. |
| 4 | `MayaMonitor.fetch_institutional_filings()` | Institutional/insider filings (filtered by Hebrew keywords). Top 2 get full text fetched for deal_size/stake_pct. |
| 5 | `EarningsCalendar.get_upcoming(days_ahead=10)` | Events within 10 days → `earnings_calendar` signals with `event_date`. |
| 6 | `DualListedMonitor.get_signals()` | 13 dual-listed stocks (TEVA, NICE, ICL, ESLT…) — US overnight move ≥2% → `dual_listed_move` signal. Best leading indicator for TASE open. |
| 7 | `IsraeliNewsMonitor.fetch_israeli_news()` | RSS (Ynet, Walla, Maariv) → company name regex match → `SignalEnricher` upgrade. |
| 8 | `ChromeNewsSearcher.fetch_all()` | Globes, Calcalist, TheMarker via headless Chromium → same pipeline as step 7. |
| 9 | `IsraeliNewsMonitor.fetch_global_news()` | Yahoo Finance, MarketWatch, WSJ headlines → text only (no signals, just LLM context). |
| 10 | `MacroContext.get()` | TA-125, S&P500, Nasdaq, VIX, USD/ILS, WTI (CL=F), US10Y (^TNX) via yfinance. |
| 11 | `SectorAnalyzer.get_sector_context()` | BULL+/BULL/NEUTRAL/BEAR/BEAR- per sector. 2-3 tickers per sector, 1M return + RSI. |

**Output:** `(pre_fetched_signals, macro_text, sector_context, companies)`

---

### 4.2 Phase 2: Parallel Sector Agents

**File:** `agents/base.py` → `SectorAgent.run()`
**Runs:** ThreadPoolExecutor with 4 workers

Each sector agent follows an identical 9-step flow:

```
Step 1: Filter pre_fetched_signals to this sector's tickers
         └─ _filter_signals() matches ticker_yf or bare ticker against sector list

Step 2: Technical scan on ALL sector tickers
         └─ MarketAnomalyDetector.scan_universe(sample_size=len(tickers))
            8 detectors: volume_spike, price_move, breakout, ma_crossover,
                         oversold_bounce, low_reversal, consecutive_momentum, relative_strength

Step 3: Sector-specific macro signals (overridden per subclass)
         └─ Banks:    KBE/XLF ETF move, IL10Y bond proxy
            TechDef:  LMT/RTX peers, AMAT/KLAC semis, VIX defense
            Energy:   WTI (CL=F), NG=F, Brent (BZ=F), NEE renewables
            Pharma:   XBI/IBB biotech ETFs, MOS potash proxy for ICL
            RealEst:  VNQ/IYR REIT ETFs, shekel move
            Telecom:  XLP/IYZ ETFs, shekel move
            Discovery: none (universe too diverse for sector macro)

Step 4: Preliminary convergence
         └─ ConvergenceEngine.group_by_ticker(all_signals)
            → {ticker: {signals, categories_hit, base_score, multiplier, final_score}}

Step 5: Filter to active tickers (final_score > 0)
         └─ "Discovery-first": only stocks WITH signals surface in recommendations

Step 6: Web news enrichment for top-5 by preliminary score
         └─ WebNewsSearcher.search_ticker(ticker, company_name, max_results=6)
            → LLMAnalyst.extract_web_news_signals() → new Signal objects
            → Update StockMemoryManager.update_news_summary()

Step 7: Re-run convergence with enriched signal set

Step 8: Deep analysis of top-8 by score
         └─ DeepStockAnalyzer.analyze(ticker_yf)
            → RSI-14, MA-20, MA-50, ma_trend, last_price, 52w_high/low,
               market_cap, revenue_growth_pct, income_growth_pct
            → StockMemoryManager.update_fundamentals() (cached 7 days)

Step 9: Store company_name in memory for ALL relevant stocks
         └─ StockMemoryManager.update_company_name(ticker, company_name)
            → extracted from Signal.company_name on any signal for this ticker
            → ensures bot can always display human-readable names

Step 10: Memory updates
          └─ update_signal_history() for all relevant tickers
             update_company_name() for all relevant tickers

Step 11: Build memory context strings for LLM
          └─ build_context_string(ticker) → compact ~800 char summary per ticker
             Contains: company_name, analyst_notes, LLM insights, signal history,
                       technicals, recent news, Maya history summary

Step 12: Sector LLM scoring
          └─ LLMAnalyst.score_sector(relevant, sector_domain, macro_text,
                                     technical_data, memory_context)
             → [{ticker, score 0-100, tier, rationale, key_catalyst,
                 technical_setup, main_risk, memory_update}]

Step 13: Write-back LLM output to memory
          └─ update_analyst_notes(ticker, rationale)  (per-stock LLM summary)
             update_llm_insights(ticker, memory_update)  (sentiment, risk, watch_for)
```

**Agent ticker lists** (as of 2026-03-27):

| Agent | Tickers (Yahoo Finance format) |
|-------|-------------------------------|
| BanksAgent | LUMI.TA, POLI.TA, MZTF.TA, DSCT.TA, FIBI.TA, PHOE.TA, HARL.TA, CLIS.TA, MISH.TA, ATRAF.TA, IDBH.TA, BVLB.TA, MLTM.TA, MRAP.TA, MSBI.TA |
| TechDefenseAgent | ESLT.TA, NICE.TA, NVMI.TA, TSEM.TA, CAMT.TA, AUDC.TA, ALLT.TA, NXSN.TA, MTRX.TA, SPEN.TA, MAGN.TA |
| EnergyAgent | DLEKG.TA, ENLT.TA, ORL.TA, PAZ.TA, NWMD.TA, OPCE.TA, AMZG.TA, SRAD.TA, GNRS.TA |
| PharmaAgent | KMDA.TA, TEVA.TA, ICL.TA, PRGO.TA, PPIL.TA |
| RealEstateAgent | AZRG.TA, AMOT.TA, BIG.TA, ELCO.TA, RAYA.TA, MELCO.TA, NKLT.TA, ARYT.TA, NVPT.TA, MTRX.TA, HLAN.TA, GKL.TA, IGLD.TA, AFHL.TA |
| TelecomConsumerAgent | BEZQ.TA, PTNR.TA, CEL.TA, SAE.TA, STRS.TA, ATID.TA, GOLF.TA, KCHM.TA |
| DiscoveryAgent | All TLV-listed equities from Yahoo Finance Screener (~400–500 stocks) |

**DiscoveryAgent special rules:**
- Universe source: `DynamicUniverseBuilder` (Yahoo Finance Screener, exchange=TLV)
- Validated via `fast_info.last_price > 0` — max 50 new validations per cycle
- Validation cache: valid tickers = 30d TTL, invalid = 7d TTL
- IPO handling: `maya_ipo` signals with `TASE{id}` pseudo-tickers passed through directly; web news searched by company name (Hebrew); scored without requiring a real .TA ticker

---

### 4.3 Phase 3: Manager LLM Arbitration

**File:** `agents/manager.py` → `ResearchManager._arbitrate()`

```
Input:  Full portfolio array from each sector agent (not just top-1)
        + macro_text + sector_context

LLM prompt (_MANAGER_SYSTEM) rules:
  • No 2 picks from same sector unless score > 90
  • Prioritise sector with strongest macro tailwind
  • Balance large-cap with at least one mid/small-cap
  • Best pick: hard catalyst + confirming technicals + macro alignment
  • Re-evaluate scores independently (do NOT anchor on sector LLM scores)

Output: {
  stock_of_the_week:  {ticker, name, score, full_rationale, key_catalyst,
                        technical_setup, main_risk, keywords},
  runners_up:         [{ticker, name, score, summary, key_catalyst}],
  macro_context:      str,
  week_theme:         str,
  sector_in_focus:    str
}
```

**Post-arbitration actions in `_run()`:**
1. `TelegramReporter.send_quick_alerts()` — top-N stocks via Telegram
2. `WeeklyAccumulator.add()` — add all new signals to weekly pool
3. `ExcelMemoryStore.save_memory()` — update 3-sheet Excel backup
4. `check_and_fire_alerts()` — fire any user-defined custom alerts
5. Weekly report (Thursday 17:00 IL): `LLMAnalyst.weekly_report()` → Telegram
6. Daily summary (daily after 17:00 IL): send today's best picks
7. `Maya history update` — `StockMemoryManager.update_maya_history()` for each Maya-type signal

---

## 5. Memory System

**File:** `analysis/memory.py` → `StockMemoryManager`

The memory system is the **analyst's notebook** — it accumulates knowledge about each stock across research cycles. Without memory, the LLM starts fresh every cycle. With memory, it recognises patterns like "third consecutive week of unusual volume" or "earnings beat but stock fell — sentiment shift?".

### 5.1 Memory Fields per Ticker

| Field | Updated by | Used by | TTL |
|-------|-----------|---------|-----|
| `company_name` | `update_company_name()` | Bot tools, web news search, ticker list | Never expires |
| `fundamentals` | `update_fundamentals()` | Sector LLM (memory_context string) | 7 days |
| `analyst_notes` | `update_analyst_notes()` (sector LLM output) | Next cycle's LLM, bot get_memory | Rolling: today's notes, yesterday's in prior_analyst_notes |
| `prior_analyst_notes` | Shifted from analyst_notes on day change | LLM (trend recognition across weeks) | 1 week |
| `llm_sentiment` | `update_llm_insights()` | Bot tracked_stocks, memory context | Rolling |
| `llm_memory_note` | `update_llm_insights()` | LLM next cycle, bot get_memory | Rolling |
| `llm_risk_flag` | `update_llm_insights()` | LLM next cycle, bot get_memory | Rolling |
| `llm_watch_for` | `update_llm_insights()` | LLM next cycle, bot get_memory | Rolling |
| `signal_history` | `update_signal_history()` | LLM, bot memory tool | Last 10 cycles |
| `consecutive_active` | `update_signal_history()` | LLM (pattern detection) | Rolling |
| `recent_news` | `update_news_summary()` | LLM context, bot get_memory | Rolling |
| `maya_history` | `update_maya_history()` | Bot get_maya_history, build_context_string | Last 30 filings |

### 5.2 Memory Flow — How It Connects

```
Research cycle N:
  Sector LLM receives memory_context[ticker] = build_context_string()
      ↓ LLM analyses signals + memory context
  LLM output includes memory_update = {sentiment, memory_note, risk_flag, watch_for}
      ↓ sector agent calls update_llm_insights(ticker, memory_update)
      ↓ sector agent calls update_analyst_notes(ticker, rationale)

Research cycle N+1:
  build_context_string() now includes N's analysis as "Latest analysis"
  + N-1's analysis as "Prior analysis" (trend recognition)
  + Maya history, signal pattern, technicals
```

### 5.3 Memory API

```python
mem = StockMemoryManager(state)

# Write
mem.update_company_name(ticker, "Teva Pharmaceutical Industries")
mem.update_fundamentals(ticker, tech_data_dict)
mem.update_signal_history(ticker, signals_list, final_score)
mem.update_analyst_notes(ticker, "LLM rationale text")
mem.update_llm_insights(ticker, {"memory_note": "...", "sentiment": "bullish",
                                   "risk_flag": "...", "watch_for": "..."})
mem.update_news_summary(ticker, articles_list)
mem.update_maya_history(ticker, signal_object)

# Read
mem.build_context_string(ticker)   # compact ~800 char summary for sector LLM
mem.get_full_briefing(ticker)      # full multi-section briefing for bot Q&A
mem.get_maya_history(ticker)       # list of filing dicts, newest first
mem.fundamentals_stale(ticker)     # True if fundamentals > 7 days old

# Maintenance
mem.prune_stale()                  # removes stocks inactive > 30 days
```

### 5.4 Excel Memory Backup

**File:** `analysis/excel_memory.py` → `ExcelMemoryStore`

3 sheets in `israel_researcher_memory.xlsx`:

| Sheet | Content | Purpose |
|-------|---------|---------|
| Sheet 1: Active Stock Memory | Full `stock_memory` dump | Restore if state wiped |
| Sheet 2: Buy/Watch Picks | Stocks in `buy` or `watch` tier | Quick human review |
| Sheet 3: Sent Alerts | Every Telegram alert ever sent (timestamp, ticker, score, catalyst) | Dedup recovery on restart |

On startup, `restore_sent_alerts()` reads today's rows from Sheet 3 to repopulate `alerted_today` — prevents re-sending the same alert after a restart.

---

## 6. Signal Scoring & Convergence

**File:** `analysis/convergence.py` → `ConvergenceEngine`

### 6.1 Scoring Formula

```
base_score = SUM(BASE_SCORES[signal_type] for each signal)
           + earnings_gradient (if earnings_calendar signal present)

earnings_gradient:
  dte=0  → +80   (earnings TODAY)
  dte=1  → +70
  dte=2  → +60
  dte=3  → +45
  dte≤7  → +25
  dte≤14 → +12

multiplier = best MULTIPLIER from MULTIPLIERS dict matching any 2-signal-type pair
           × 1.3 if 3+ independent signal categories converge

final_score = base_score × multiplier   (capped at some max in practice)
```

**Important:** `final_score` is NO LONGER sent to the LLM. The LLM receives `signal_strength` (= base_score) and `convergence_multiplier` as descriptive indicators only, then scores each stock independently (0–100) to avoid anchoring bias.

### 6.2 Key Convergence Multipliers

| Signal pair | Multiplier | Rationale |
|-------------|-----------|-----------|
| earnings_calendar + volume_spike | 2.5× | Pre-earnings accumulation — strongest setup |
| low_reversal + earnings_calendar | 2.4× | Earnings catalyst at technical floor |
| oversold_bounce + earnings_calendar | 2.3× | Mean-reversion + fundamental catalyst |
| earnings + volume_spike (web news) | 2.3× | Real earnings news + smart money |
| relative_strength + earnings_calendar | 2.2× | Momentum + catalyst = continuation |
| breakout + earnings | 2.0× | Technical breakout confirmed by fundamentals |
| maya_contract + volume_spike | 2.0× | Filing-confirmed + market awareness |

### 6.3 LLM Score Calibration

| Score range | Meaning | Requires |
|-------------|---------|---------|
| 85–100 | EXCEPTIONAL | Named hard catalyst + healthy RSI (30–65) + macro tailwind + convergence_multiplier ≥ 2.0 + 3+ categories. Max 1–2 per month. |
| 70–84 | STRONG BUY | Hard catalyst (contract, earnings, institutional) + one confirming technical |
| 52–69 | MODERATE / WATCH | Meaningful signal but macro neutral, RSI extended, or single source |
| 35–51 | MONITOR | Single soft signal. Worth tracking. |
| < 35 | WEAK | Sector-only or ambiguous signal |

---

## 7. Telegram Bot Interface

### 7.1 Threading Model

```
Main thread:  Research cycle — Playwright, ThreadPoolExecutor, state mutations
Bot thread:   Daemon — long-poll getUpdates (timeout=30s), no Playwright allowed
State:        threading.RLock; bot takes deepcopy under lock, releases immediately
Settings:     BotSettings — GIL-safe attribute assignment
```

**Critical rule:** The bot thread **never** imports `MayaMonitor`, `ChromeNewsSearcher`, or any Playwright code. Playwright is not thread-safe across threads.

### 7.2 Slash Commands (18 total)

**Settings (save to `bot_state.json` atomically):**

| Command | Validation | Effect |
|---------|-----------|--------|
| `/set_interval <min>` | 5–240 | `scan_interval_seconds = min * 60` |
| `/set_topn <n>` | 1–10 | `top_n_alerts = n` |
| `/set_volume <x>` | 1.5–10.0 | `volume_spike_x = x` |
| `/set_price <pct>` | 1.0–20.0 | `price_move_pct = pct` |
| `/set_language en\|he` | en or he | `language = lang` |
| `/set_sectors s1,s2,...` | subset of ALL_SECTORS | `enabled_sectors = [...]` |
| `/enable_alerts` | — | `alerts_enabled = True` |
| `/disable_alerts` | — | `alerts_enabled = False` |

Valid sector names: `Banks  TechDefense  Energy  PharmaBiotech  RealEstate  TelecomConsumer  Discovery`

**Status & data (read-only):**

| Command | Data source | Output |
|---------|-------------|--------|
| `/help` | Static text | Full command reference |
| `/status` | settings + state | Interval, language, alerts, signal counts, alerted today |
| `/macro` | `MacroContext()` — live yfinance | TA-125, S&P500, Nasdaq, USD/ILS, VIX, WTI, US10Y |
| `/earnings` | `state["weekly_signals"]` | Earnings events sorted by date |
| `/weekly` | `state["last_arbitration_report"]` | Stock of week + runners-up + theme + macro |
| `/sector <name>` | `SectorAnalyzer()` — live yfinance | BULL+/.../BEAR- + RSI + 1M return |

**Custom alerts:**

| Command | Effect |
|---------|--------|
| `/alert_add <type> [ticker]` | Add alert rule. Types: ipo, earnings, maya_filing, institutional, volume_spike, price_move, any_signal |
| `/alert_list` | Show all alerts for this chat |
| `/alert_del <id>` | Delete alert by 8-char hex ID |
| `/alert_history [ticker]` | Show Maya filing history for a stock |

### 7.3 Q&A Pipeline

**File:** `bot/qa_pipeline.py` → `QAPipeline`

Three LLM calls per free-text message:

```
Call 1: plan_intent(question, dynamic_ticker_list, TOOL_CATALOGUE)
        → {ticker, intent, tools[], language}

        Intent types:
          stock_analysis  — specific company question
          live_scan       — "is anything happening with X right now?"
          earnings_query  — earnings-related
          market_overview — macro / how is the market
          sector_query    — sector rotation question
          ipo_query       — new listings / IPOs
          maya_query      — TASE regulatory filings THIS WEEK
          maya_history    — filing timeline for a specific stock (all past cycles)
          recommendations — "what to buy today"
          tracker_query   — "what stocks are you tracking"
          alert_query     — "what alerts do I have set?"
          direct_answer   — no tools needed (conversational/conceptual)
          general_question — fallback

Call 2: Tool execution (SKIPPED for direct_answer)
        Each tool called sequentially; result appended to context string

        For stock_analysis / earnings_query with resolved ticker:
        CODE ENFORCES: get_stock_data + search_news + get_memory +
                       get_weekly_signals + get_maya_filings (always)

Call 3: chat_answer(question, context, language, history)
        → plain-text answer with Telegram markdown (**bold**, bullets)
```

**Tool registry (14 tools):**

| Tool | Network? | Returns |
|------|---------|---------|
| `get_macro` | yfinance | TA-125, S&P500, Nasdaq, USD/ILS, VIX, WTI, US10Y |
| `get_sector_context` | yfinance | BULL+/…/BEAR- per sector |
| `get_stock_data` | yfinance | Formatted text: RSI, MAs, price, 52w range, market cap, revenue growth |
| `run_live_scan` | yfinance | Real-time anomaly scan (volume spike, breakout, oversold, etc.) |
| `search_news` | Google News RSS | Up to 8 recent article titles + snippets |
| `get_weekly_signals` | state only | All signals this week for ticker, or top-20 |
| `get_maya_filings` | state only | Maya regulatory filings this week (IPOs, contracts, etc.) |
| `get_alerted_stocks` | state only | Stock-of-week + runners-up + alerted today |
| `get_recent_ipos` | state only | IPO/spinoff signals this week |
| `get_tracked_stocks` | state only | All memory stocks: sentiment, score, company name, watch-for |
| `get_memory` | state only | Full analyst briefing (uses `get_full_briefing()`) |
| `get_maya_history` | state only | Maya filing history for one ticker (all past cycles) |
| `get_user_alerts` | disk | User's custom alert rules |
| `get_ipo_watchlist` | state + disk | IPO signals this week + IPO memory history |

**Dynamic ticker list:**
`_build_dynamic_ticker_list(state)` merges 33 hardcoded tickers with all stocks from `state["stock_memory"]` that have a stored `company_name`. After a few research cycles, this grows to cover 100+ TASE stocks — dramatically improving Hebrew name resolution.

**Hebrew ticker resolution:**
When `plan_intent` returns `ticker=null` for a stock-specific intent:
1. Build company list from `state["tase_company_cache"]["companies"]` (up to 500 entries)
2. Call `llm.resolve_ticker(question, company_list_text)` → `{ticker, company_name, confidence}`
3. Accept if `confidence >= 0.6` (string: "high" or "medium")
4. Store `company_name` in `state["_bot_resolved_company"]` for use by `search_news`

### 7.4 Custom User Alerts

**File:** `bot/user_alerts.py`

```
UserAlert fields:
  alert_id:         str  (8-char hex UUID)
  chat_id:          str  (Telegram chat ID)
  alert_type:       str  (one of ALERT_TYPES)
  ticker:           str? (bare symbol, e.g. "TEVA")
  company_name:     str? (display name)
  created_at:       str  (ISO-8601)
  seen_signal_keys: list (dedup, capped at 200)
  description:      str  (human-readable label)

Alert types and what they match:
  ipo           → maya_ipo, ipo, maya_spinoff
  earnings      → maya_earnings, earnings, earnings_calendar
  maya_filing   → any maya_* signal type
  institutional → maya_institutional, institutional_investor, maya_buyback
  volume_spike  → volume_spike
  price_move    → price_move
  any_signal    → any signal at all
```

**Alert firing flow** (in `ResearchManager._run()` after Phase 2):
1. `load_user_alerts()` — read from `user_alerts.json`
2. `check_and_fire_alerts(alerts, all_new_signals)` — match, mutate `seen_signal_keys`
3. If any fired: `save_user_alerts(alerts)` then send notification via `TelegramReporter`

---

## 8. LLM Prompts Reference

**File:** `analysis/llm.py`

| Prompt constant | Used by | Purpose |
|----------------|---------|---------|
| `_QUICK_SYSTEM` | `score_signals()`, `score_grouped()` | Quick cross-sector scoring (early filter) |
| `_SECTOR_BASE_SYSTEM` | `score_sector()` (per sector) | Sector-specialized portfolio scoring. Includes {sector_domain} placeholder. |
| `_MANAGER_SYSTEM` | `arbitrate()` | CIO-style cross-sector pick. Includes geopolitical + portfolio rules. |
| `_WEEKLY_SYSTEM` | `weekly_report()` | Thursday weekly report generation |
| `_WEB_NEWS_SYSTEM` | `extract_web_news_signals()` | News article → structured signal extraction |
| `_INTENT_SYSTEM` | `plan_intent()` | Bot: question → {ticker, intent, tools, language} |
| `_CHAT_ANSWER_SYSTEM` | `chat_answer()` | Bot: synthesise tool results → Telegram-formatted answer |
| `_RESOLVE_TICKER_SYSTEM` | `resolve_ticker()` | Bot: Hebrew company name → TASE ticker |

**Key prompt design principles:**
- All scoring prompts include: Israeli geopolitical framework, macro rules, small-cap guidance, score calibration
- `final_score` removed from LLM input — avoids anchoring bias; LLM scores independently
- Memory context injected as compact strings (`build_context_string()`) to keep prompt size manageable
- `_CHAT_ANSWER_SYSTEM` specifies Telegram markdown formatting (**bold**, bullets)

---

## 9. Configuration Reference

**File:** `config.py`

```python
# API credentials
OPENAI_API_KEY   = "sk-..."
OPENAI_MODEL     = "gpt-4o-mini"    # change here to use GPT-4o
BOT_TOKEN        = "..."             # Telegram bot token
CHAT_ID          = "..."             # Telegram chat ID

# Detection thresholds (also overrideable at runtime via /set_volume, /set_price)
VOLUME_SPIKE_X   = 2.5              # Volume > 2.5× 20d avg → signal
PRICE_MOVE_PCT   = 3.5              # Abs daily move > 3.5% → signal

# State files
STATE_FILE            = Path("israel_researcher_state.json")
BOT_STATE_FILE        = Path("bot_state.json")
USER_ALERTS_FILE      = Path("user_alerts.json")
EXCEL_MEMORY_FILE     = Path("israel_researcher_memory.xlsx")

# Sector ticker lists (Yahoo Finance .TA format)
SECTOR_TICKERS = {
    "Banks":           ["LUMI.TA", "POLI.TA", ...],
    "TechDefense":     ["ESLT.TA", "NICE.TA", ...],
    "Energy":          ["DLEKG.TA", "ENLT.TA", ...],
    "PharmaBiotech":   ["KMDA.TA", "TEVA.TA", ...],
    "RealEstate":      ["AZRG.TA", "AMOT.TA", ...],
    "TelecomConsumer": ["BEZQ.TA", "PTNR.TA", ...],
}

# Dual-listed stocks monitored for US overnight moves
DUAL_LISTED_STOCKS = {
    "TEVA":  "TEVA",    # TEVA.TA ↔ TEVA (NYSE)
    "NICE":  "NICE",    # NICE.TA ↔ NICE (NASDAQ)
    ...
}
```

---

## 10. State & Persistence

### State lifecycle

```
startup:
  1. load_state() → read israel_researcher_state.json (or init empty)
  2. ExcelMemoryStore.restore_memory_to_state() → restore stock_memory from Excel
  3. ExcelMemoryStore.restore_sent_alerts() → repopulate alerted_today from Sheet 3

every cycle:
  4. ResearchManager._run() → mutates state dict in-place
  5. save_state() → atomic write (temp file + os.replace)
  6. ExcelMemoryStore.save_memory() → update Excel

bot thread:
  7. state_getter() under RLock → BotServer passes getter to QAPipeline
  8. QAPipeline takes deepcopy → LLM calls run outside lock
```

### Deduplication

- **Maya report IDs**: `state["seen_maya_report_ids"]` — persistent, never expires. Prevents same Maya filing from creating duplicate signals across cycles.
- **Signal keys**: `state["seen_signal_keys"]` — today only (cleaned to today's prefix each cycle). Prevents same technical signal firing twice in one day.
- **Alerted today**: `state["alerted_today"]` — resets each calendar day. Prevents spamming the same stock multiple times per day.
- **User alert dedup**: `UserAlert.seen_signal_keys` — per-alert list, capped at 200.

---

## 11. Adding a New Sector Agent

**Step 1:** Create `agents/my_sector.py`:

```python
from .base import SectorAgent
from ..models import Signal, now_iso
from ..config import OPENAI_API_KEY

class MySectorAgent(SectorAgent):
    sector_name = "MySector"
    tickers = [
        "ABCD.TA", "EFGH.TA", "IJKL.TA",   # Yahoo Finance format
    ]

    @property
    def _sector_domain(self) -> str:
        return """
You are a specialist in [describe sector].
Key drivers for this sector: [list 3-5 key drivers].
Israeli context: [any Israel-specific nuances].
Typical catalysts: [contract wins / regulatory approvals / earnings beats].
Macro sensitivity: [how does macro affect this sector].
"""

    def get_sector_signals(self) -> list[Signal]:
        """Return sector-specific macro-driven signals."""
        signals = []
        # Example: detect a US peer ETF move
        signals.extend(self._peer_move_signal(
            peer_ticker="XYZ",
            peer_label="XYZ ETF",
            threshold_pct=2.0,
            target_tickers=self.tickers,
            signal_type="sector_peer_move",
            direction_text="Israeli sector follows"
        ))
        return signals
```

**Step 2:** Add to `config.py`:

```python
SECTOR_TICKERS["MySector"] = ["ABCD.TA", "EFGH.TA", "IJKL.TA"]
```

**Step 3:** Register in `agents/manager.py`:

```python
from .my_sector import MySectorAgent

class ResearchManager:
    _AGENT_CLASSES = [
        BanksAgent,
        TechDefenseAgent,
        EnergyAgent,
        PharmaAgent,
        RealEstateAgent,
        TelecomConsumerAgent,
        MySectorAgent,    # ← add here
    ]
```

**Step 4:** Add to `bot/bot_state.py`:

```python
ALL_SECTORS = [
    "Banks", "TechDefense", "Energy", "PharmaBiotech",
    "RealEstate", "TelecomConsumer", "Discovery",
    "MySector",   # ← add here
]

SECTOR_AGENT_MAP = {
    ...
    "MySector": "MySectorAgent",   # ← add here
}
```

---

## 12. Adding a New Bot Tool

**Step 1:** Implement the tool function in `bot/qa_pipeline.py`:

```python
def _tool_my_new_tool(ticker: str | None, state: dict) -> str:
    """
    One-sentence description of what this tool returns.
    Best for: describe when to use it.
    """
    try:
        # Implementation — may read from state (fast) or call yfinance (network)
        data = state.get("my_data_key", {})
        if not data:
            return "No data available yet."
        # Return human-readable text so LLM can synthesise naturally
        return f"My tool result for {ticker}: ..."
    except Exception as e:
        return f"[my_new_tool error: {e}]"
```

**Step 2:** Register in `_TOOL_REGISTRY`:

```python
_TOOL_REGISTRY: dict[str, callable] = {
    ...
    "get_my_new_tool": _tool_my_new_tool,   # ← add
}
```

**Step 3:** Add to `TOOL_CATALOGUE` string:

```python
TOOL_CATALOGUE = """
...
RESEARCHER STATE (cont.):
  ...
  get_my_new_tool — Description of what it returns and when to use it
...
SELECTION RULES:
  ...
  • Relevant question type → get_my_new_tool (+ other tools)
"""
```

**Step 4:** Update `_INTENT_SYSTEM` in `analysis/llm.py` — add the tool to SELECTION RULES and relevant EXAMPLES so the LLM knows when to select it.

**Step 5:** (Optional) If a new intent type is needed, add it to:
- `_INTENT_SYSTEM` intent list + INTENT GUIDANCE section + EXAMPLES
- `_STOCK_INTENTS` set in `qa_pipeline.py` if it requires a resolved ticker

---

## 13. Running & Deployment

### Prerequisites

```bash
# Python 3.10+
pip install yfinance feedparser trafilatura openai pandas beautifulsoup4 \
            openpyxl playwright requests

playwright install chromium
```

### Environment

All credentials are **hardcoded in `config.py`** — no `.env` file required.
Required values: `OPENAI_API_KEY`, `OPENAI_MODEL`, `BOT_TOKEN`, `CHAT_ID`

### Running

```bash
# Activate virtual environment (Windows)
source venv/Scripts/activate

# Start the research agent (includes Telegram bot)
python -m israel_researcher

# The agent logs to stdout. Key log lines:
# [BotPoller] started
# [2026-03-27T14:30:00] ResearchManager cycle start...
# [Maya] 45 filing signals.
# [BanksAgent] Agent starting...
# [Manager] Stock of the week: ESLT
```

### Process Management (Windows)

For production, wrap in a shell loop or use Task Scheduler / NSSM:

```batch
:loop
python -m israel_researcher
echo Restarting in 30 seconds...
timeout /t 30
goto loop
```

### Key Files Created at Runtime

| File | Created by | Purpose |
|------|-----------|---------|
| `israel_researcher_state.json` | `save_state()` | Full research state — never delete |
| `bot_state.json` | `BotSettings.save()` | Bot settings — survives restarts |
| `user_alerts.json` | `save_user_alerts()` | Custom alert rules |
| `israel_researcher_memory.xlsx` | `ExcelMemoryStore` | Stock memory backup |
| `seen.json` | `news.py` | News deduplication |

---

## 14. Troubleshooting

### Bot not responding to messages

1. Check `last_offset` in `bot_state.json` — if very large, Telegram may have rotated it. Reset to 0.
2. Check `BOT_TOKEN` in `config.py` — verify with `https://api.telegram.org/bot{TOKEN}/getMe`
3. Bot requires at least one message to get its offset bootstrapped — send `/start`

### Maya filings not appearing

1. Maya requires a Playwright Chromium session. If Playwright is not installed: `playwright install chromium`
2. If `[Maya]` logs show 0 signals for many cycles: Maya WAF may have changed. Check `sources/maya.py` — the Incapsula bypass uses the Playwright context's cookies from the browser session.
3. Check `seen_maya_report_ids` — if it grew too large (>10,000 entries), prune it: `state["seen_maya_report_ids"] = []`

### All stocks getting high scores (score inflation)

The LLM should NOT receive `final_score` directly. Verify `to_llm_input()` in `convergence.py` returns `signal_strength` and `convergence_multiplier` — not `final_score`. See the calibration section in `_QUICK_SYSTEM` and `_SECTOR_BASE_SYSTEM`.

### Hebrew company names not resolving in bot

1. Check `state["tase_company_cache"]["companies"]` — should have 400+ entries. If empty: the Maya company list fetch failed. Run the agent once with network access.
2. Check `_resolve_ticker_from_state()` confidence threshold: it's 0.6. The LLM `resolve_ticker()` call may be failing — check `[LLM] resolve_ticker error` in logs.
3. After a few research cycles, `stock_memory` will contain company names for all tracked stocks — `_build_dynamic_ticker_list()` uses these, making resolution much more reliable over time.

### DiscoveryAgent not finding new stocks

1. Validation cache populates slowly — max 50 new validations per cycle. First full run of 500 stocks ≈ 10 cycles.
2. If `state["tase_universe_cache"]` is empty: Yahoo Finance Screener may be unavailable. Check `yf.Screener` — requires yfinance 0.2.37+.
3. Check `ticker_validation_cache` for stale invalid entries — they expire after 7 days automatically.

### Memory not persisting across restarts

1. `stock_memory` lives in `state` dict → `israel_researcher_state.json`. If this file is deleted, memory is lost.
2. Recovery: `ExcelMemoryStore.restore_memory_to_state()` runs on startup and restores from `israel_researcher_memory.xlsx` (Sheet 1).
3. If Excel file is also missing: fresh start — memory rebuilds over 2-4 cycles.

### yfinance SSL errors (Hebrew username path)

The `__init__.py` SSL fix copies certifi's CA bundle to `%TEMP%\brokai_cacert.pem` and sets three environment variables. If this fails, set manually:

```python
import os, certifi
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
```

---

## Appendix A: Signal Type Quick Reference

| Signal type | Score | Source | Notes |
|-------------|-------|--------|-------|
| `maya_ipo` | 50 | Maya filing | IPO prospectus filed — highest priority |
| `maya_spinoff` | 48 | Maya filing | Spinoff/rights offering |
| `maya_ma` | 45 | Maya filing | M&A / acquisition filed |
| `maya_contract` | 45 | Maya filing | Contract filing on Maya |
| `new_contract` | 45 | News/enricher | Contract mention in news |
| `government_defense` | 45 | News/enricher | Government/defense contract |
| `regulatory_approval` | 42 | News/enricher | FDA/EU/IL regulatory approval |
| `maya_buyback` | 42 | Maya filing | Share buyback program |
| `maya_institutional` | 40 | Maya filing | Institutional investor filing |
| `institutional_investor` | 40 | News/enricher | Institutional buy/sell news |
| `ipo` | 38 | Web news | IPO mentioned in web news |
| `breakout` | 35 | Technical | 52w high + volume |
| `dual_listed_move` | 35 | Market data | US overnight ≥2% move |
| `earnings` | 35 | Web news | Earnings news extracted |
| `maya_earnings` | 35 | Maya filing | Earnings report filed on Maya |
| `low_reversal` | 32 | Technical | Near 52w low + volume bounce |
| `maya_dividend` | 32 | Maya filing | Dividend announced |
| `shareholder_return` | 32 | News/enricher | Buyback/dividend news |
| `oversold_bounce` | 30 | Technical | RSI < 32 + rising volume |
| `buyback` | 30 | Web news | Buyback in web news |
| `dividend` | 28 | Web news | Dividend in web news |
| `ma_crossover` | 28 | Technical | MA20 crosses above MA50 |
| `defense_tailwind` | 28 | Sector macro | VIX > 22 (defense premium) |
| `partnership` | 30 | News/enricher | Partnership/JV announcement |
| `oil_correlation` | 25 | Sector macro | WTI moved > 2% |
| `financial_event` | 25 | News/enricher | Earnings/guidance news |
| `relative_strength` | 22 | Technical | Outperforms TA-125 by 5%+ over 20d |
| `sector_peer_move` | 22 | Sector macro | US sector ETF moved |
| `shekel_move` | 20 | Sector macro | USD/ILS moved > 1.5% |
| `consecutive_momentum` | 20 | Technical | 4+ up days with rising volume |
| `earnings_calendar` | 20 | EarningsCalendar | Upcoming earnings event |
| `management_change` | 18 | News/enricher | CEO/CFO change |
| `maya_management` | 18 | Maya filing | Management change on Maya |
| `maya_rights` | 22 | Maya filing | Rights issue |
| `maya_filing` | 10 | Maya filing | Generic Maya filing |
| `general_news` | 15 | Web news | General news mention |
| `israeli_news` | 12 | RSS | General Israeli news |
| `geopolitical` | varies | News/enricher | Geopolitical event |

---

## Appendix B: Convergence Multiplier Pairs (Top 20)

| Signal pair | Multiplier |
|-------------|-----------|
| earnings_calendar + volume_spike | 2.5× |
| low_reversal + earnings_calendar | 2.4× |
| oversold_bounce + earnings_calendar | 2.3× |
| earnings + volume_spike | 2.3× |
| relative_strength + earnings_calendar | 2.2× |
| breakout + earnings | 2.0× |
| breakout + institutional_investor | 2.0× |
| maya_contract + volume_spike | 2.0× |
| maya_institutional + volume_spike | 2.0× |
| ma_crossover + maya_earnings | 1.9× |
| dual_listed_move + volume_spike | 1.9× |
| maya_ipo + volume_spike | 1.8× |
| new_contract + earnings_calendar | 1.8× |
| regulatory_approval + volume_spike | 1.8× |
| institutional_investor + earnings | 1.7× |
| breakout + dual_listed_move | 1.7× |
| relative_strength + volume_spike | 1.7× |
| oversold_bounce + institutional_investor | 1.7× |
| maya_management + volume_spike | 1.6× |
| low_reversal + dual_listed_move | 1.6× |

**Three-category bonus:** +1.3× multiplier applied on top when 3+ independent signal categories converge (e.g. Maya filing + technical signal + news).

---

*End of Developer Guide*
