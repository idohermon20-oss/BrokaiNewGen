# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running Analyses

```bash
# Single stock analysis (CLI)
python main.py ESLT medium il       # Israeli stock — medium horizon
python main.py BEZQ short il
python main.py AAPL medium          # US stock (default market)

# Time horizons: short (1-4 weeks) | medium (1-6 months) | long (1-3 years)
# Markets:       us (default) | il (Israel / TASE)

# TASE scanner — run across many Israeli stocks
python scan_tase.py --horizons medium
python scan_tase.py --horizons short medium long --top-n 15
python scan_tase.py --horizons medium --size large --resume
python scan_tase.py --horizons short --no-articles    # skip articles (faster)

# Web UI
streamlit run app.py
```

## Environment Setup

Copy `.env.example` to `.env` and fill in:
- `OPENAI_API_KEY` — required
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — optional push notifications

Install deps: `pip install -r requirements.txt`

## Architecture

The pipeline runs in 8 sequential stages, all orchestrated by `main.py::analyze()`:

| Stage | Module | What it does |
|-------|--------|--------------|
| 1 | `data/fetcher.py` | yfinance data + RSI/MA/volume technicals + macro snapshot (^TA125, VIX, ILS=X, oil) |
| 2 | `data/article_fetcher.py` | 3-stage news: DDG English news → DDG text filtered → Google RSS Hebrew |
| 3 | `data/maya_fetcher.py` | TASE regulatory filings via `site:maya.tase.co.il` DDG search |
| 4 | `data/sector_news.py` | Sector-level news context |
| 5 | `orchestrator/profiler.py` | LLM builds `StockProfile` (phase, situation, market focus) |
| 6 | `orchestrator/relevance_mapper.py` | LLM defines key investment questions for this stock |
| 7 | `orchestrator/agent_designer.py` | LLM designs 5–10 specialist analysts for this stock/sector |
| 8 | `agents/agent_runner.py` | Each analyst runs independently, returns `AgentOutput` |
| 9 | `committee/synthesizer.py` | Finds agreements/disagreements across analysts |
| 10 | `committee/committee.py` | Final committee verdict: invest/no/conditional, score 0-100 |
| 11 | `report/report_generator.py` | Assembles markdown report |
| 12 | `main.py::translate_to_hebrew()` | Chunked GPT-4o translation (splits on `## ` boundaries) |

### Key Data Structures

- `StockData` (`data/fetcher.py`) — price history, financials, technicals, macro context
- `StockProfile` (`orchestrator/profiler.py`) — phase, situation, sector, horizon implications
- `AgentBrief` / `AgentOutput` (`agents/base_agent.py`) — analyst assignment + structured output
- `SynthesisResult` (`committee/synthesizer.py`) — agreements, disagreements, overall lean
- `CommitteeDecision` (`committee/committee.py`) — verdict, scenarios, score, factors
- `AnalysisResult` (`report/report_generator.py`) — everything assembled for report generation

### LLM Models (configurable in `config.py`)

- **Orchestrator / committee / report**: `gpt-4o`
- **Individual agents**: `gpt-4o-mini` (faster/cheaper, still strong)

All LLM calls go through `utils/llm.py::call_llm()` and `parse_json_response()`.

### Article Pipeline (`data/article_fetcher.py`)

Strict filtering to get only real news (not stock data pages or social media):
- `_JUNK_DOMAINS` — blocklist (facebook, reddit, linkedin, skyscrapercity, digrin, etc.)
- `_STOCK_DATA_DOMAINS` — blocklist (fintel, finbox, stockanalysis, macrotrends, etc.)
- `_is_news_url()` — URL path filter for `/quote/`, `/symbols/`, `/financials/`, etc.
- Hebrew news uses Google RSS only (DDG Hebrew queries throw `DecodeError`)

### Maya/TASE Filings (`data/maya_fetcher.py`)

Maya API is blocked by Imperva. Filings are discovered via DDG `site:maya.tase.co.il` search. Only URLs matching `re.search(r'/reports/(details/)?\d+', url)` are accepted (numeric filing IDs only).

### Sector Intelligence (`orchestrator/agent_designer.py`)

`_SECTOR_INTELLIGENCE` dict maps 8 sectors → domain-specific analyst hints injected into the agent design prompt (e.g., BOI policy for banks, USD/ILS for tech, order backlog for defense).

### Report Format (`report/report_generator.py`)

Visual compact format:
- Verdict dashboard with ASCII score bar (`▓░`), conviction stars (`★★☆`)
- Analyst vote row (`🟢🟢🔴⚪`) + markdown table with one-sentence findings
- Scenario probability bars in code block
- Sections: Highlights → Stock Overview → Analyst Team → Synthesis → Committee Verdict → Articles → Maya Filings → Conviction Rationale

### Scanner (`scan_tase.py`)

Loads TASE universe from CSV, runs `analyze()` per stock in reduced-agent mode (4–7 agents), saves dated output tree under `reports/YYYY-MM-DD/`.

### Notifications (`utils/telegram.py`)

Optional. Reads `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` from env. Silently no-ops if not configured.
