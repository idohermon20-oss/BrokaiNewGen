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

### Hybrid News Analysis Engine (`data/fetcher.py`)

`assess_article_impacts()` uses a 4-phase hybrid approach — LLM is NOT called for every article:

**Phase 1 — Rule-based classifier** (`_rule_classify`) runs on ALL articles instantly:
- 4 keyword tiers: `_RULE_STRONG_BULL`, `_RULE_BULL`, `_RULE_STRONG_BEAR`, `_RULE_BEAR`
- Returns `(sentiment, event_type, impact_score, confidence, rule_hits)`
- Confidence: 0.90 for strong tier matches, 0.80 for normal, 0.55 for neutral (intentionally low), 0.45 for conflicts

**Phase 2 — Selective LLM** (`_llm_classify_batch`) called for ≤ 5 articles only, triggered when:
- `confidence < 0.70` (unclear or conflicting signals)
- `impact_score >= 4` (high-importance article worth verifying)
- Suspicious neutral: classified neutral but contains direction keywords (`_RULE_ANTINEUTRAL_BULL/BEAR`)
- Articles sorted by ascending confidence then descending impact — most uncertain + most important go first

**Phase 3 — Validation pass** (`_validate_article`):
- Catches any remaining neutral articles that contain strong bullish/bearish signals
- `_RULE_STRONG_BULL` hit → reclassify neutral → `"bullish"`
- `_RULE_STRONG_BEAR` hit → reclassify neutral → `"bearish"`
- 2+ anti-neutral keywords → reclassify in the matching direction

**Phase 4 — Assemble** `ArticleImpact` objects with legacy `impact` field preserved for backward compat.

`ArticleImpact` now has a `confidence: float = 0.75` field (rule=0.55–0.90, LLM=0.88). This flows into the scoring engine.

LLM results override rule results when merged. `confidence = 0.88` for LLM-assessed articles.

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

### Analyst Risk Severity System (`scoring_engine.py`)

Risk severity is classified by keyword content, not analyst stance:

| Severity | Multiplier | Examples |
|----------|-----------|---------|
| HIGH | ×2.5 | unsustainable debt, covenant breach, bankruptcy, regulatory ban, structural weakness, fraud |
| MEDIUM | ×1.5 | margin pressure, slowing growth, customer concentration, refinancing risk, geopolitical |
| LOW | ×1.0 | valuation concerns, high PE, competition, volatility — no penalty, reduces conviction only |

**`_classify_risk_severity(text)`** — keyword-based, checks HIGH → MEDIUM → LOW → default LOW.

**`_compute_analyst_risk_profile(agent_outputs)`** — scans all sources in priority order:
1. `flags_for_committee` (explicit committee warnings)
2. `key_unknowns` (identified gaps/dangers)
3. `key_finding` + `full_reasoning` for bearish/mixed/neutral analysts only

Returns `{max_severity, high_signals, medium_signals, low_signals, analyst_severity_map}`.

**In `_score_consensus()`** — severity amplifies bearish contributions:
- `contribution = direction × eq × conv × sev_mult` (sev_mult applies only when direction ≤ 0)
- HIGH severity cap: 2+ analysts → consensus capped at 9.0; 1 analyst → capped at 11.0
- Cap appears as `! Consensus capped at X.X` in signals

**In `_score_risk_adjustment()`** — analyst risks add direct penalties:
- 1 HIGH signal → −2.0; 2+ HIGH signals → −4.0 (max)
- MEDIUM signals → −0.5 per analyst up to −1.5
- LOW risks: no penalty, only logged in signals
- `agent_outputs` is now an optional 4th parameter

### Direction / Recommendation Consistency (`committee/committee.py`)

Direction has 4 values — `"conditional_up"` was added to separate "bullish with risks" from genuine two-sided uncertainty:

| Value | Meaning | Typical score |
|-------|---------|---------------|
| `up` | Majority positive, no major contradiction | ≥ 65 |
| `conditional_up` | Positive dominant, but one meaningful risk could change outcome | 50–70 |
| `mixed` | Strong signals on **both** sides — genuine two-sided uncertainty | 40–60 |
| `down` | Majority negative | < 45 |

**Key rule:** risks do NOT create `"mixed"`. They reduce conviction and may produce `"conditional_up"`. `"mixed"` is reserved for truly two-sided situations.

**`_enforce_direction(direction, invest_recommendation, score, conviction)`** — post-LLM enforcement:
- score ≥ 70 → force `"up"` or `"conditional_up"`; lift NO → CONDITIONAL
- score 55–69 → disallow `"down"`; refine `"mixed"` → `"conditional_up"` when score ≥ 62
- score < 40 → force `"down"`; lower YES → CONDITIONAL
- Corrections are appended to `conviction_rationale` with `[AUTO-CORRECTED: ...]` tag

Report label map: `up` → `BULLISH ↑`, `conditional_up` → `COND. BULLISH ↑`, `mixed` → `MIXED ↔`, `down` → `BEARISH ↓`

### Notifications (`utils/telegram.py`)

Optional. Reads `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` from env. Silently no-ops if not configured.

---

## Scoring Engine (`borkai/scoring/scoring_engine.py`)

The scoring engine combines 6 components into a 0–100 score. Each component has its own max and weight.

| Component | Max | Key driver |
|-----------|-----|------------|
| Financial Health | 15 | PE, margins, D/E, revenue trend |
| Maya Events | 20 | Filing tier × magnitude × recency |
| News Sentiment | 10 | Event-based 5-level sentiment × impact score |
| Sector Heat | 10 | Structural tier + keyword-assessed news |
| Growth Potential | 15 | Fundamentals + filings + news growth signals |
| Analyst Consensus | 15 | Evidence-weighted analyst signals |
| Risk Adjustment | -10–0 | Leverage, dilution, negative margins, VIX |

### Maya Filing Tiers (`_classify_filing_tier`)

Three-tier system replacing flat magnitude map:
- **Tier 1** (magnitude 10): acquisitions, mergers, NVIDIA/big-tech partnerships, defense contracts, IPOs, breakthrough tech
- **Tier 2** (magnitude 6): earnings beats, guidance raises, product launches, significant contracts
- **Tier 3** (magnitude 2): appointments, dividends, administrative, annual meetings

Cluster detection (`_detect_event_cluster`): multiple strong events in same period earn bonus (+1.5 to +5.0).
Validation floors: 2+ Tier-1 bullish → score ≥ 15; 1 Tier-1 bullish → score ≥ 12.

### News Sentiment Engine (`ArticleImpact` v2)

5-level sentiment: `strong_bullish` / `bullish` / `neutral` / `bearish` / `strong_bearish`

LLM uses mandatory 3-step reasoning: identify event → explain financial impact → assign sentiment.
Each article also gets `impact_score` (0–5) and `event_type`.

Scoring path: `direction × (impact_score / 5) × recency_weight`

`sentiment = ""` (empty string) = legacy article sentinel. Non-empty = v2 assessed. Do NOT default to `"neutral"` — that silences legacy bullish articles.

Validation floor: ≥1 high-impact bullish article with net bullish majority → score ≥ 6.0.

### Sector Heat Scoring (`_score_sector_heat`)

4-layer structure:
1. **Structural baseline** by sector tier: T1 (AI/semi/defense/cyber) = 4.0, T2 (cloud/software) = 2.5, neutral = 2.0, cold (real estate) = 1.0
2. **Sector news direction** via `_assess_sector_item_direction()` — keyword-based since `SectorNewsItem` has no pre-assessed `impact` field
3. **Macro overlay** — VIX + index performance
4. **Validation floors** — T1 sector + ≥2 positive news → floor 7.0; T1 with no clear negative → floor 6.0

Short keywords (`"ai"`, `"chip"`) use word-boundary matching (`\b`) to avoid false matches inside words like "retail" or "championship".

Company-sector alignment fast path: if sector keyword appears in `industry` field → alignment = 1.0 (no penalty).

### Double-Counting Prevention (`scoring_engine.py`)

Each signal has one **primary** component that scores it at full weight. Secondary uses are discounted.

**Secondary source discounts in `_score_growth()`:**
- Maya filings layer (`maya_pts`): ×0.6 discount — `_score_events()` is primary
- News articles layer (`news_pts`): ×0.5 discount — `_score_news()` is primary
- Positive-signal threshold checks use the undiscounted value; only the score contribution is discounted

**`_apply_boost_deduplication(b_event, b_growth, b_align, b_sector, b_news_momentum, b_news_cross)`:**
Three sibling rules (boosts that share a primary signal source):

| Rule | Sibling pair | Reduction |
|------|-------------|-----------|
| 1 | News Momentum + News Cross-Component | Cross-Component ×0.5 |
| 2 | Event Momentum + Growth Confirmation | Growth Confirmation ×0.6 |
| 3 | News Momentum + Growth Confirmation (no Event) | Growth Confirmation ×0.7 (partial) |

Hard cap: total boost points ≤ 18. If exceeded, all boosts are scaled proportionally.
Deduplication notes appear in `score_gaps` in the report output.

### News Integration into Final Score (`scoring_engine.py`)

News affects the final score through four mechanisms:

**1. Component contribution** — `_score_news()` now uses `direction × magnitude × recency × confidence`. Confidence comes from `ArticleImpact.confidence` (0.75 default). High-confidence LLM-assessed articles (0.88) outweigh uncertain rule-classified ones.

**2. News Momentum Boost** — `_boost_news_momentum()`: fires when 2+ high-impact (≥4/5) bullish articles cluster:
- 2 articles → +2.0 pts
- 3 articles → +4.0 pts
- 4+ articles → +6.0 pts
- Reduced by 2 pts if ≥2 high-impact bearish counterbalance. Requires `news_score ≥ 5.0`.

**3. News Cross-Component Amplifier** — `_boost_news_cross_component()`: fires when bullish news content aligns with other strong components:
- Growth news (≥2 articles) + growth score ≥8 → +2.0
- Partnership/contract news + events score ≥8 → +2.0
- Sector/AI news + sector score ≥7 → +1.5
- Cap: +5.0. Requires `news_score ≥ 5.0`.

**4. Bearish penalty** — `_news_bearish_penalty()`: applied when strong negative news exists:
- 1 high-impact bearish → −2.0
- 2 high-impact bearish → −3.5
- 3+ high-impact bearish → −5.0
- Halved if counterbalanced by equal bullish count. Not applied if `news_score < 3.5` (already reflected). Added to `score_gaps` in output.

All three boosts fire in `compute_score()` alongside existing boosts. The penalty is a separate deduction applied in step 5 (pre-calibration).

### Growth Potential Scoring (`_score_growth`)

Measures real business direction: financial momentum + strategic moves + market opportunity. No penalties for high PE or risk factors (those belong to Risk Adjustment).

**Four independent signal layers:**

| Layer | Max | Key signals |
|-------|-----|-------------|
| Financial momentum | 5 | fwd/trailing PE ratio, 1Y/3M price change, quarterly earnings trend, operating margin |
| Maya growth signals | 4 | guidance/earnings filings (tier-aware), expansion/contract/partnership titles |
| News growth signals | 4 | v2 sentiment × impact score × recency, AI/innovation exposure, expansion hits |
| Analyst signals | 3 | growth keyword density in `full_reasoning` + `key_finding` |

**Growth tiers** (based on how many layers are positive):
- 3–4 layers → `STRONG GROWTH` (floored at 11.0)
- 2 layers → `MODERATE GROWTH`
- 1 layer → `WEAK GROWTH`
- 0 layers → `NO CLEAR GROWTH`

**Validation floor:** financial momentum + (AI/innovation OR expansion signals) → score ≥ 9.0

**Base shift:** raw sum + 2.0 so a company with zero signals lands near 6.0 (not 0).

Maya filings reuse `_classify_filing_tier` — Tier-1 filings contribute more (+1.5 vs +1.0). News path uses v2 sentiment when available; falls back to legacy `impact` field.

### Analyst Consensus Scoring (`_score_consensus` + `_compute_analyst_eq`)

Evidence-weighted formula — analysts with concrete data references outweigh weak generic opinions.

**Per-analyst EQ score (0–5)** via `_compute_analyst_eq`:
- Evidence list: count-based base (0→0, 1→0.5, 2→1.0, 3+→1.5) + source quality bonus (maya/filing/financial → +0.4) + high relevance (+0.2). Cap 3.5.
- Keyword density in `full_reasoning` + `key_finding`: 22 financial terms × 0.15 each. Cap 1.5.

**Per-analyst contribution**: `direction × eq × conviction`
- direction: bullish=+1, bearish=−1, neutral/mixed=0
- conviction: high=1.0, moderate=0.75, low=0.5

**Aggregation**: `net_lean = bull_strength − bear_strength`; `max_net = max(n×3.5, 10.0)`; `score = 7.5 + (net_lean / max_net) × 7.5`

Tension penalty is proportional and reduced by 40% when strong consensus exists (`|net_lean| > max_net × 0.4`).

Report signals include top-3 analysts by EQ with stance, EQ score, conviction, and weighted contribution.

`AgentOutput` fields used: `agent_name`, `stance`, `confidence`, `evidence` (List[EvidenceItem]), `full_reasoning`, `key_finding`. There is **no** `analysis` field — do not access `out.analysis`.
