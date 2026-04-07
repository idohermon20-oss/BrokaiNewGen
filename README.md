# Brokai — Israeli Stock Research Agent

AI-powered research system for the Tel Aviv Stock Exchange (TASE). Scans the full TASE universe every 15 minutes, reads Maya filings in real-time, scores stocks using LLM analysis, and delivers alerts via Telegram.

---

## What it does

- **Reads Maya TASE filings** — IPOs, earnings, contracts, institutional buyers, buybacks, dividends — the moment they are published, before any news outlet picks them up
- **Scans 500+ TASE stocks** every cycle for volume spikes, breakouts, oversold bounces, MA crossovers, and relative strength
- **Runs 8 sector agents in parallel** — Banks, Tech/Defense, Energy, Pharma, Real Estate, Telecom/Consumer, Tourism, and a Discovery agent that covers the full universe
- **Cross-references global macro** — WTI oil, USD/ILS, US10Y, VIX, S&P500 — injected into every LLM call
- **Uses GPT to score and rank** every stock, thinking like a buy-side analyst: what is the catalyst, how material is it relative to market cap, is it already priced in
- **Sends Telegram alerts** — top 3 stocks every cycle, daily summary at 17:00, weekly Stock of the Week on Thursday
- **Interactive Telegram bot** — ask questions in Hebrew or English: "מה קורה עם טבע?", "show me the top buys this week", "/macro", "/sector Banks"

---

## Repository layout

```
BorsaProject/
├── israel_researcher/   ← Active: TASE research engine (Shai)
│   ├── agents/          ← 8 sector agents + ResearchManager
│   ├── sources/         ← Maya, market data, news, web search
│   ├── analysis/        ← LLM scoring, convergence engine, memory
│   └── bot/             ← Telegram bot server + Q&A pipeline
├── portfolio/           ← Planned: portfolio management (Developer 2)
├── shared/              ← Shared utilities for both developers
│   ├── stocks.py        ← find_top_stocks(), filter_signals_by_score()
│   ├── analytics.py     ← calc_pnl(), sector_weights(), find_max_stock()
│   └── reports.py       ← parse_financial_report(), summarize_filing()
├── data/                ← Runtime state, memory, mappings (shared)
│   ├── israel_researcher_state.json
│   ├── israel_researcher_memory.xlsx
│   └── maya_company_mapping.json   ← 238 Maya companyId → .TA ticker mappings
├── utils/               ← Standalone scripts (run directly)
│   ├── fetch_maya_companies.py     ← Rebuild Maya company universe
│   ├── fetch_tase_universe.py      ← Rebuild YF equity universe
│   ├── build_llm_mapping.py        ← Expand Maya → ticker mapping via GPT
│   ├── make_pdf.py                 ← Generate docs/israel_researcher_docs.pdf
│   └── make_pptx.py                ← Generate docs/israel_researcher_overview.pptx
└── docs/                ← Generated documentation
```

---

## Setup

```bash
# 1. Clone and activate virtual environment
git clone https://github.com/idohermon20-oss/BrokaiNewGen.git
cd BrokaiNewGen
source venv/Scripts/activate   # Windows
# source venv/bin/activate      # Linux/Mac

# 2. Install dependencies
pip install yfinance feedparser trafilatura openai pandas openpyxl \
            beautifulsoup4 playwright python-dotenv
playwright install chromium

# 3. Create .env at project root
OPENAI_API_KEY=sk-...
BOT_TOKEN=...          # Telegram bot token
CHAT_ID=...            # Telegram chat ID
OPENAI_MODEL=gpt-4o-mini
```

---

## Running

```bash
# Start the research loop + Telegram bot (runs every 15 minutes)
python -m israel_researcher

# One-off utilities (run from project root)
python utils/fetch_maya_companies.py    # Refresh Maya company universe (~5 min, Playwright)
python utils/fetch_tase_universe.py     # Refresh TASE equity list from Yahoo Finance
python utils/build_llm_mapping.py       # Expand Maya companyId→.TA mappings via GPT
python utils/make_pdf.py                # Regenerate PDF docs → docs/
python utils/make_pptx.py              # Regenerate slide deck → docs/
```

---

## Telegram bot commands

| Command | Description |
|---------|-------------|
| `/status` | Last scan time, alerts enabled, active sectors |
| `/macro` | Live: TA-125, S&P500, USD/ILS, WTI oil, VIX, US10Y |
| `/weekly` | Stock of the week + runners-up |
| `/earnings` | Upcoming earnings events |
| `/sector <name>` | Sector trend: BULL+/BULL/NEUTRAL/BEAR/BEAR- |
| `/set_interval <min>` | Change scan interval (5–240 min) |
| `/set_language en\|he` | Switch reply language |
| `/enable_alerts` / `/disable_alerts` | Toggle Telegram alerts |
| Free text | Ask anything — the bot uses GPT to answer with live data |

---

## Architecture overview

```
Every 15 minutes:
  Phase 1 — Cross-sector data (sequential)
    Maya filings → Signal objects
    Israeli news RSS → matched to companies
    Dual-listed US overnight moves → leading indicators
    Earnings calendar → upcoming events
    Macro snapshot → injected into all LLM calls

  Phase 2 — Sector agents (parallel, 4 workers)
    Each agent: technicals → macro signals → web news → LLM scoring
    Discovery agent covers full 500+ ticker universe

  Phase 3 — Manager LLM arbitration
    Picks Stock of the Week across all sectors
    Enforces: no 2 from same sector, at least one small/mid cap, macro alignment

  → Telegram alert: top 3 stocks with score, catalyst, risk
```

---

## Key data files

| File | Purpose | Rebuilt with |
|------|---------|-------------|
| `data/israel_researcher_state.json` | Live state: signals, dedup, ticker cache | Auto-managed |
| `data/israel_researcher_memory.xlsx` | Persistent analyst notes per stock | Auto-managed |
| `data/maya_company_mapping.json` | 238 Maya companyId → .TA ticker mappings | `utils/build_llm_mapping.py` |
| `data/tase_ticker_names.json` | English names for 426 TASE tickers | `utils/fetch_tase_universe.py` |

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| LLM | OpenAI GPT-4o-mini |
| Market data | yfinance |
| Maya scraping | Playwright (headless Chromium, WAF bypass) |
| News | feedparser, Google News RSS, trafilatura |
| Alerts | Telegram Bot API |
| Memory | pandas, openpyxl (Excel) |
| Language | Python 3.8+ |
