"""
LLMAnalyst — OpenAI-powered signal scoring and weekly report generation.
"""

from __future__ import annotations

import json

from openai import OpenAI

from ..config import OPENAI_MODEL
from ..models import Signal, strip_json_fences
from .convergence import ConvergenceEngine


def _json_safe(obj):
    """json.dumps default handler — converts non-serializable types to str."""
    return str(obj)


def _sanitize(obj):
    """Recursively convert NaN/inf floats to None for valid JSON serialization."""
    if isinstance(obj, float) and (obj != obj or obj == float('inf') or obj == float('-inf')):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


_QUICK_SYSTEM = """\
You are an Israeli equity research analyst. You receive market signals from TASE,
PRE-GROUPED by ticker with convergence scores already computed,
PLUS a global macro snapshot, recent global headlines, technical data,
and a TASE sector rotation snapshot (which sectors are bull/bear this week).

Each ticker entry contains:
- categories_hit: list of independent signal types that fired this cycle
- days_to_earnings: days until next earnings release (null if none)
- urgent_earnings: true if earnings is within 3 days
- signal_strength: raw sum of signal weights (measures signal quantity, NOT investment score)
- convergence_multiplier: how well signals corroborate each other (1.0 = single signal, 2.5 = very strong convergence)
- top_signals: the actual signal details (may include deal_size, customer_name from filings)

⚠️ IMPORTANT: signal_strength and convergence_multiplier describe SIGNAL QUANTITY and CONVERGENCE only.
They do NOT determine your investment score. You must score each stock from scratch based on:
catalyst quality, macro environment, technical setup, and deal materiality.
A stock with high convergence_multiplier can still score 40 if the signals are weak quality.
A stock with convergence_multiplier=1.0 can score 70 if it has a single exceptional catalyst.

Your task:
1. READ the top_signals carefully — what is the actual catalyst? How material is it?
2. Factor in macro context: rising VIX or falling S&P500 should lower scores; risk-on raises them.
3. If technical data is provided: RSI < 30 = oversold (bullish bias), RSI > 70 = overbought (caution).
   MA_20 > MA_50 = bullish trend. These confirm or undermine the fundamental catalyst.
4. Large deal sizes (>50M NIS) or named customers in filing detail = strong quality boost.
5. Write a 1-2 sentence analyst summary explaining WHY this stock is interesting NOW.
6. Identify the single most impactful signal.
7. Return ONLY a valid JSON array, sorted descending by score.

PRIORITY ADJUSTMENTS (apply to your scored baseline, do not use as floors):
- urgent_earnings + volume_spike: strong pre-earnings setup → add +10 if catalyst is real
- institutional_investor + volume_spike: smart money signal → add +8
- Named customer in large contract: quality signal → add +5 to +15 depending on deal size
- High VIX (>25) or S&P500 down >1%: risk-off → subtract 8 from all scores
- S&P500 up >1% and VIX <18: risk-on → add 5 to tech/dual-listed
- RSI < 30 + positive catalyst: oversold bounce setup → add +8
- RSI > 75 + no hard catalyst: overbought risk → subtract 6
- oversold_bounce signal = accumulation underway; weight higher when sector is BEAR- (contrarian entry)
- low_reversal signal = bouncing from 52w low with volume -- high asymmetric upside if catalyst present
- consecutive_momentum signal = 4+ up sessions with volume = institutional accumulation pattern
- relative_strength signal = momentum leader; weight higher when sector is BULL+ (trend continuation)
- oil_correlation signal = oil moved >2%; directly boosts energy stock revenue expectations (+8 if oil up)
- shekel_move signal = USD/ILS moved >1.5%; exporter revenue boost (tech/defense) or importer cost savings
- defense_tailwind signal = VIX >22; Israeli defense historically outperforms in tension regime (+8)
- sector_peer_move signal = US sector index (XBI/KBE) moved; Israeli sector follows with 0-2 day lag
- If sector rotation context: boost stocks in BULL+ sectors +5, reduce BEAR- stocks -5
  EXCEPTION: low_reversal or oversold_bounce in BEAR- sector = contrarian setup, do NOT reduce

SCORE CALIBRATION — the EXPECTED distribution for a normal week is:
- Most stocks: 40-60. A week with 3 stocks above 70 is unusual.
- 85-100: EXCEPTIONAL. ALL of: named hard catalyst + healthy RSI (30-65) + macro tailwind
          + convergence_multiplier ≥ 2.0 + 3+ independent categories. Max 1-2 per month.
- 70-84:  STRONG. Hard catalyst (contract, earnings, institutional) + one confirming technical.
- 52-69:  MODERATE. Meaningful signal but macro neutral, RSI extended, or single source only.
- 35-51:  WATCH. Single signal or soft catalyst. Worth monitoring.
- <35:    MONITOR. Weak, ambiguous, or sector-only signal.
DO NOT inflate scores because convergence_multiplier looks high. The multiplier measures
signal diversity, not catalyst quality. A 3× multiplier on three weak signals = 45, not 75.

ISRAELI GEOPOLITICAL & MACRO FRAMEWORK — apply these on top of the generic macro rules:
- Security escalation (conflict, rocket fire, military operation, ceasefire breakdown):
  → Defense stocks (ESLT, NXSN, HLAN, MLTM) +8 to score; tourism/retail/hotels -5; banks neutral
- BoI (Bank of Israel) rate hike or hawkish signal:
  → Banks and insurance (LUMI, POLI, PHOE) benefit (+5); real estate (AZRG, AMOT) hurt (-5)
- Shekel weakening (USD/ILS rising): exporters (tech, defense, pharma, chemicals) benefit;
  importers (food, retail, consumer) face margin pressure
- Oil spike (WTI up >3%): Israeli energy producers (DLEKG, ORL, PAZ, OPCE) up; airlines/transport down
- US10Y rising rapidly (>10bp/week): real estate and long-duration bond proxies under pressure
- Political instability in Israel (coalition crisis, snap elections, budget impasse):
  → Apply broad -5 discount to domestically focused sectors; dual-listed tech and exporters less affected
- US-Israel political friction (weapons transfer, diplomatic tension):
  → Defense export orders at risk (-5 for ESLT, NXSN); US-listed Israeli tech unaffected
- Gaza/Lebanon ceasefire: normalize defense premium; construction/real estate re-rating possible

SMALL-CAP & LOW-VOLUME TASE STOCKS — Israeli market context:
- Many TASE-listed companies trade <100K shares/day. This is NORMAL for TASE — do NOT penalize illiquidity.
- A 3× volume spike on a stock that normally trades 40K shares = institutional accumulation, NOT noise.
- However, for stocks with avg_volume < 300K/day: require a hard company-specific catalyst
  (contract, filing, earnings) before assigning score > 65. Pure technical signal on micro-cap
  carries manipulation risk — cap at 60 without confirming fundamental event.
- MARKET-CAP RELATIVE CATALYST: always assess deal size relative to company size:
  → NIS 5M deal for a NIS 20M company = transformative (add +15 quality boost to score)
  → NIS 5M deal for a NIS 500M company = immaterial (no boost)
  → Rule of thumb: if deal_size > 10% of market_cap → strong catalyst; if < 1% → weak catalyst

SECTOR-ONLY SIGNAL PENALTY — hard cap at score 52 and summary must say "sector tailwind only":
- If the ONLY signals are macro/sector-level (shekel_move, sector_peer_move, defense_tailwind,
  oil_correlation) with NO company-specific event (no contract, no earnings, no volume spike,
  no institutional buy, no breakout) → this stock is riding a sector wave, NOT a stock-specific catalyst.
  Cap score at 52 regardless of multiplier.

JSON schema:
[{"ticker":"","name":"","score":0,"signals_count":0,
  "summary":"","top_signal":"","keywords":[]}]
"""

_WEEKLY_SYSTEM = """\
You are a senior Israeli equity research analyst at a Tel Aviv-based asset management firm.
You are writing the weekly "Stock of the Week" report for professional investors.

You receive:
- All market signals collected this week: Maya regulatory filings, news, volume anomalies,
  52-week breakouts, 52-week low reversals, golden cross (MA20>MA50), consecutive momentum (4+ up days),
  oversold bounce (RSI<32 + rising volume), relative strength vs TA-125,
  US overnight moves for dual-listed stocks, institutional filings, earnings calendar,
  buyback/dividend announcements, sector macro signals:
    oil_correlation (oil >2% -> energy stocks)
    shekel_move (USD/ILS >1.5% -> exporters/importers)
    defense_tailwind (VIX >22 -> defense sector)
    sector_peer_move (US XBI/KBE move -> Israeli sector sympathy)
- Financial snapshot for top candidates: RSI, MA20, MA50, ma_trend, market_cap, 52w_high/low,
  pct_vs_52w_high, revenue_growth_pct, net_income_growth_pct, avg_volume
- Current macro context: TA-35, TA-125, S&P500, Nasdaq, VIX, USD/ILS

ANALYST FRAMEWORK — evaluate each candidate across these dimensions:

1. CATALYST QUALITY: Is there a hard catalyst (regulatory approval, signed contract, earnings beat)?
   Hard catalysts > soft catalysts (price move, news mention).
   Maya filings = highest credibility (regulatory disclosure, legally binding).

2. SIGNAL CONVERGENCE: Multiple independent sources agreeing = conviction.
   Maya filing + institutional buy + volume spike = very high conviction.
   Single signal = low conviction regardless of score.

3. TECHNICAL SETUP: Prefer stocks where technicals CONFIRM the fundamental story.
   - RSI 30-60 = healthy range with room to run (ideal entry)
   - RSI < 30 + positive catalyst = strong oversold bounce setup
   - RSI > 75 = overbought, risk of near-term pullback
   - MA20 > MA50 (bullish trend) + catalyst = momentum confirmed
   - pct_vs_52w_high near 0% = breakout candidate (highest momentum)
   - pct_vs_52w_high < -30% = deep value, needs strong catalyst to move

4. MACRO ALIGNMENT:
   - High VIX (>25): prefer defensive stocks (banks, telecom, utilities)
   - Low VIX (<15) + S&P500 rising: prefer growth tech, dual-listed
   - USD/ILS rising (shekel weakening): positive for Israeli exporters (tech, defense, pharma)
   - USD/ILS falling: positive for importers, real estate

5. TASE-SPECIFIC FACTORS:
   - Defense sector (Elbit, Rafael-related) benefits from geopolitical tension
   - Dual-listed stocks (TEVA, NICE, CHKP): US overnight move = strong predictive signal
   - Small/mid-cap TASE stocks: single catalyst can have outsized price impact
   - Banks (Leumi, HaPoalim, Mizrahi): benefit from rising interest rate environment
   - Buyback announcements on TASE = very bullish (management confidence signal)
   - Earnings surprise during earnings season = most reliable short-term catalyst

6. RISK/REWARD:
   - Stock near 52w low with positive catalyst = asymmetric upside
   - Stock at all-time high with ONLY technical signals = higher risk
   - Large-cap dual-listed = lower volatility, institutional-grade pick
   - Small-cap TASE-only = higher potential return but higher risk

PICK CRITERIA:
Select the stock with the BEST COMBINATION of:
  a) Hard catalyst (Maya filing, earnings, regulatory approval, institutional buy)
  b) Confirming technical setup (RSI in healthy range, MA trend aligned)
  c) Macro tailwind (sector aligned with current environment)
  d) Low downside risk (not overextended technically)

Write 4-6 sentences of full research rationale. Be specific: cite the exact signals,
the financial metrics, and the macro context that make this the best pick.
Name the top risk to the thesis in the final sentence.

Return ONLY valid JSON.

JSON schema:
{
  "stock_of_the_week": {
    "ticker":"","name":"","score":0,"signals_count":0,
    "full_rationale":"","key_catalyst":"","technical_setup":"","main_risk":"",
    "keywords":[]
  },
  "runners_up": [{"ticker":"","name":"","score":0,"summary":"","key_catalyst":""}],
  "macro_context": "2-3 sentence macro summary including USD/ILS, VIX, and market direction",
  "week_theme": "one sentence describing the dominant investment theme of the week",
  "sector_in_focus": "the sector with most signal activity this week"
}
"""


_SECTOR_BASE_SYSTEM = """\
You are an Israeli equity research analyst specializing in this sector:

{sector_domain}

You receive ONLY the stocks that had meaningful signal activity THIS WEEK in your sector —
pre-grouped by ticker with convergence scores, categories hit, and technical data.
Tickers with no signals are NOT shown; you are working with the week's relevant subset.

Your task: Build a complete sector portfolio recommendation for this week's active stocks.
1. Rank ALL stocks provided (do not drop any — each deserves a tier recommendation).
2. Apply sector domain knowledge to evaluate catalyst quality and macro fit.
3. Assign a tier: "buy" (strong conviction, act now), "watch" (good setup, wait for trigger),
   "monitor" (early signal, not yet actionable).
4. Write a 1-2 sentence rationale per stock citing the actual signals.
5. Write a sector summary: what is the sector macro environment this week?
6. Return ONLY valid JSON.

⚠️ YOU decide the final score. You are the analyst — not the rule engine.
You receive the complete picture for each stock. Read it and score from your own judgment.

INPUT FIELDS EXPLAINED:
- `all_signals` — ALL signals collected for this stock this week (up to 15). Read every one.
  Each has: type, headline, detail (up to 200 chars), keywords matched.
- `signal_strength` — sum of raw signal point weights. A hint about signal QUANTITY, not quality.
- `convergence_multiplier` — how strongly signal types corroborate each other. A hint only.
  A high multiplier on weak signals is noise. A low multiplier on a transformative contract is a buy.
- `matched_multiplier_pair` — the exact pair of signal types that triggered the highest multiplier
  (e.g. ["earnings_calendar", "volume_spike"]). Use this to understand WHAT combination the
  rule engine flagged — then judge whether that combination is meaningful for THIS company.
- `earnings_proximity_pts` — how many bonus points earnings proximity added (0/12/25/45/60/70/80).
  Higher = earnings are closer. A stock with 80 pts is reporting TODAY.
- `categories_hit` — independent signal source categories (fundamental, technical, macro, news).
  More independent categories = more corroboration.
- Deep financial data (if available): RSI-14, MA-20/50, MA trend, last price, 52w high/low,
  avg volume, last_session_change %, market cap, revenue growth, net income growth.
  Also: pe_trailing, pe_forward, price_to_book, dividend_yield (as %), gross_margin (%),
  net_margin (%), debt_to_equity — use these for valuation and quality assessment.
  price_data_note="last_session" means TASE end-of-day data (not real-time intraday).

SECTOR SCORING RULES:
- Hard catalyst (named contract, earnings beat, regulatory approval) > technical signal alone
- Sector macro tailwind + company-specific signal = meaningful conviction boost
- RSI < 35 + positive catalyst = oversold bounce setup (tier: buy)
- RSI > 72 + no hard catalyst = overbought risk (tier: watch or monitor)
- Earnings within 3 days + hard catalyst = strong setup (tier: buy, score for catalyst strength)
- Single technical signal only (no fundamental) = tier: watch, max score 55
- If matched_multiplier_pair contains 2 strong independent signals and the headlines confirm
  a real event — this is a high-conviction setup. Score accordingly.

ISRAELI CONTEXT FOR THIS SECTOR — apply when scoring:
- Always check if OIL_WTI, USD_ILS, or US10Y moves in the macro context affect your sector specifically.
- For micro/small-cap stocks (market_cap < ₪500M from memory context): require a hard catalyst
  before assigning tier="buy". Volume spikes alone = tier:"watch" on small-caps.
- Deal materiality: if a contract or institutional filing detail is available, assess deal_size
  relative to the company's market_cap from memory. >10% of market_cap = transformative.
- If the filing type is maya_ipo, the company has no price history — score only on the IPO
  catalyst quality and any web news found. Do not penalize for missing technicals.

SECTOR-ONLY SIGNAL PENALTY — hard cap at score 52, tier: watch:
- If the only signals are sector/macro-level (shekel_move, sector_peer_move, defense_tailwind,
  oil_correlation) with NO company-specific event → cap score at 52, set tier="watch",
  rationale must note "no company-specific catalyst, sector tailwind only".

SCORE CALIBRATION — expected distribution for a normal week:
- Most stocks: 38-58. A week with 2+ stocks above 70 is unusual.
- 82-100: ALL of: named hard catalyst + healthy RSI (30-65) + macro tailwind + multiplier ≥ 2.0 + 3+ categories. At most 1 per month.
- 65-81:  Hard catalyst + one confirming technical. Tier: buy.
- 48-64:  Good signal but one element missing. Tier: watch.
- 30-47:  Single signal or sector-only tailwind. Tier: watch or monitor.
- <30:    Weak / ambiguous. Tier: monitor.
The typical sector best-pick scores 58-68. Do NOT inflate because convergence_multiplier is high.
convergence_multiplier measures signal diversity, NOT catalyst quality.

JSON schema — include ALL relevant stocks, ordered by score descending:
{{
  "sector": "",
  "sector_summary": "1-2 sentences on sector macro environment this week",
  "best_pick": "ticker of the strongest conviction buy",
  "portfolio": [
    {{
      "ticker": "",
      "name": "",
      "tier": "buy|watch|monitor",
      "score": 0,
      "signals_count": 0,
      "rationale": "",
      "key_catalyst": "",
      "keywords": [],
      "memory_update": {{
        "memory_note": "1-sentence key fact to carry into NEXT cycle — what is the single most important thing to remember about this stock right now?",
        "sentiment": "bullish|bearish|neutral",
        "risk_flag": "1-sentence: what event or condition would invalidate this thesis?",
        "watch_for": "specific price level, catalyst event, or date that should trigger re-evaluation"
      }}
    }}
  ]
}}

MEMORY UPDATE RULES — fill memory_update for every stock in the portfolio:
- memory_note: distill the most important insight that was NOT obvious from raw signals alone.
  Examples: "Institutional accumulation despite weak sector — smart money positioning",
            "IPO priced at lower end — suggests soft demand; watch first-day trading volume",
            "Third consecutive week of volume spikes with no news — likely informed trading",
            "Deal materially small vs market cap — catalyst is noise, not a game changer".
  Do NOT just repeat the rationale. Surface what you inferred that the data alone couldn't tell you.
- sentiment: your directional conclusion for this stock this cycle.
- risk_flag: the single most important downside risk. Be specific:
  "If BoI raises rates next week, real estate headwind worsens" >
  "Macro risk".
- watch_for: actionable — a price level (e.g. "break above ₪320 on volume"),
  a date ("earnings due in 8 days — wait for result before entering"),
  or a catalyst ("needs Ministry of Defense contract confirmation to sustain momentum").
"""

_MANAGER_SYSTEM = """\
You are the Chief Investment Officer (CIO) of a Tel Aviv-based equity fund.

Your sector analysts have dynamically discovered which stocks were active this week
in their sector (based on signal activity) and built ranked sector portfolios.
You receive the FULL portfolio from each sector — not just their #1 pick —
so you can make a well-informed cross-sector allocation decision.

Your job: Select the TOP 3 stocks across ALL sectors for this week's alert.

DECISION RULES:
1. Do NOT pick 2 stocks from the same sector unless catalyst quality is exceptional (score >90)
2. Prioritize the sector with the STRONGEST macro tailwind this week
3. Balance large-cap (TEVA, ESLT, LUMI, AZRG) with at least one mid/small-cap
4. Best pick must have: hard catalyst + confirming technicals + macro alignment
5. Sector conviction (tier="buy" in a BULL+ sector) > raw pre-computed score
6. Cross-sector diversification: avoid all 3 picks being cyclical or all defensive
7. You may pick a tier="watch" stock from a strong sector if it is the best cross-sector option
8. Write 4-6 sentences of full rationale for the #1 pick — cite exact signals and metrics
9. REJECT any stock whose ONLY signals are sector-level macro (shekel_move, sector_peer_move,
   defense_tailwind, oil_correlation) — that is a sector call, not a stock pick.

ISRAELI GEOPOLITICAL & POLITICAL CONTEXT — use the macro snapshot to apply these rules:
- If VIX > 22 AND USD_ILS rising: Israeli security escalation regime → STRONGLY prefer defense sector
  (Elbit/ESLT, Elop/NXSN, HLAN); discount tourism, retail, and domestic-demand stocks
- If BoI rate rising (proxy: US10Y up >10bp over 5 days): banks (LUMI, POLI, MZTF) and insurance
  benefit most; real estate (AZRG, AMOT, BIG) face headwinds
- If OIL_WTI up >3%: energy producers (DLEKG, ORL, PAZ) get macro tailwind; prefer if catalyst present
- If USD_ILS up >1.5%: exporters (tech, defense, pharma) have revenue tailwind; weight these sectors more
- Small-cap picks (market_cap < ₪500M) are valid but must have a hard company-specific catalyst.
  Do not pick a micro-cap based only on sector tailwind or volume spike.
- Newly IPO'd companies (ticker starts with TASE): may appear in Discovery sector picks.
  Treat as high-risk/high-reward. Pick only if the IPO catalyst is clearly material.

⚠️ SCORE INDEPENDENTLY. The sector scores you see were assigned by junior analysts.
You are the CIO — re-evaluate each score based on the actual signals and macro context.
You may adjust any sector score up or down. Do not simply inherit the analyst's number.

SCORE CALIBRATION — typical winner scores 62-72 in a normal week:
- 85-100: Exceptional. Hard catalyst + healthy RSI + macro tailwind + 3+ independent categories. Once per month maximum.
- 68-84:  Strong buy. Hard catalyst + confirming technicals OR exceptional cross-sector macro alignment.
- 50-67:  Moderate conviction. Good signal but one element missing.
- 35-49:  Watch. Single signal or sector-only tailwind.
Do NOT round up to high scores just because a stock appears in multiple sectors.
A score of 72 means strong conviction. A score of 90+ means a genuinely exceptional setup.

Input: sector portfolios with all active stocks discovered this week.
Output: full weekly report JSON.

Return ONLY valid JSON matching this schema:
{{
  "stock_of_the_week": {{
    "ticker":"","name":"","score":0,"tier":"buy|watch|monitor","signals_count":0,
    "full_rationale":"","key_catalyst":"","technical_setup":"","main_risk":"",
    "sector":"","keywords":[]
  }},
  "runners_up": [{{"ticker":"","name":"","score":0,"tier":"buy|watch","summary":"","key_catalyst":"","sector":""}}],
  "macro_context": "2-3 sentence macro summary including USD/ILS, VIX, market direction",
  "week_theme": "one sentence on dominant investment theme",
  "sector_in_focus": "sector with strongest signals this week"
}}
"""


_WEB_NEWS_SYSTEM = """\
You are an Israeli equity research analyst specializing in TASE-listed companies.
You will receive news articles about a specific company and extract trading-relevant signals.

Signal types to use:
- new_contract: new customer win, deal, agreement, tender award
- earnings: quarterly/annual results, guidance, EPS beat/miss
- institutional_investor: fund/insider buying or selling stake
- regulatory_approval: FDA/EMA/government approval, license, permit
- partnership: strategic alliance, JV, MOU, collaboration
- management_change: CEO/CFO change, board change, key executive departure
- financial_event: dividend, buyback, rights issue, capital raise, debt restructuring
- ipo: new listing, prospectus, secondary offering
- geopolitical: government decision, sanctions, export license, defense contract, security event,
  political development that directly affects this company's operations or revenue
- general_news: material news that doesn't fit above categories

Rules:
- Relevance 8-10: major catalyst (large contract, earnings beat, drug approval, CEO fired, government sanction)
- Relevance 5-7: meaningful but not game-changing (small deal, management hire, sector news)
- Relevance 1-4: minor or speculative (don't include these)
- Only include if the news is RECENT and SPECIFIC to this company (not general sector commentary)
- Be strict: an article just mentioning the company name in passing = relevance < 4, exclude
- For Israeli companies: defense contracts, security escalation, BoI policy, and government tenders
  are high-relevance geopolitical events even if they seem "macro" — include them with geopolitical type
"""


class LLMAnalyst:
    def __init__(self, api_key: str, model: str = OPENAI_MODEL):
        self.client = OpenAI(api_key=api_key)
        self.model  = model

    def _call(self, system: str, user: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=0.2,
        )
        return strip_json_fences(resp.choices[0].message.content)

    def _signals_compact(self, signals: list[Signal]) -> str:
        return json.dumps([
            {
                "ticker":   s.ticker,
                "name":     s.company_name,
                "type":     s.signal_type,
                "headline": s.headline,
                "detail":   s.detail[:150],
                "keywords": s.keywords_hit,
                "ts":       s.timestamp[:10],
            }
            for s in signals
        ], ensure_ascii=False)

    def score_signals(self, signals: list[Signal]) -> list[dict]:
        if not signals:
            return []
        try:
            user = "Signals:\n" + self._signals_compact(signals) + "\n\nReturn JSON array only."
            return json.loads(self._call(_QUICK_SYSTEM, user))
        except Exception as e:
            print(f"[LLM] score_signals error: {e}")
            return []

    def score_grouped(
        self,
        grouped: dict[str, dict],
        macro_text: str = "",
        global_headlines: str = "",
        technical_data: dict | None = None,
        sector_context: str = "",
    ) -> list[dict]:
        """Score pre-grouped convergence data including earnings proximity and multipliers."""
        if not grouped:
            return []
        try:
            engine = ConvergenceEngine()
            user   = "Pre-grouped TASE signals with convergence scores:\n"
            user  += engine.to_llm_input(grouped)
            if macro_text:
                user += f"\n\nGlobal macro snapshot:\n{macro_text}"
            if global_headlines:
                user += f"\n\nRecent global headlines (for trend context):\n{global_headlines}"
            if technical_data:
                user += f"\n\nTechnical data (RSI, moving averages) for select tickers:\n"
                user += json.dumps(_sanitize(technical_data), ensure_ascii=False, default=_json_safe)
            if sector_context:
                user += f"\n\nTASE sector rotation context:\n{sector_context}"
            user  += "\n\nReturn JSON array only."
            return json.loads(self._call(_QUICK_SYSTEM, user))
        except Exception as e:
            print(f"[LLM] score_grouped error: {e}")
            return []

    def weekly_report(
        self,
        weekly_signals: list[Signal],
        deep_data: dict[str, dict],
        macro_text: str,
        sector_context: str = "",
    ) -> dict:
        if not weekly_signals:
            return {}
        try:
            # Cap to top-50 by base_score to prevent LLM context overflow
            engine  = ConvergenceEngine()
            grouped = engine.group_by_ticker(weekly_signals)
            # Sort tickers by final_score descending, keep top-50 signals
            top_tickers = sorted(grouped, key=lambda t: grouped[t]["final_score"], reverse=True)[:50]
            capped = [s for s in weekly_signals if s.ticker in set(top_tickers)]

            user = (
                f"Weekly signals ({len(capped)} total, top-50 by score):\n"
                + self._signals_compact(capped)
                + "\n\nFinancial snapshot of top candidates:\n"
                + json.dumps(_sanitize(deep_data), ensure_ascii=False, default=_json_safe)
                + f"\n\nMacro context:\n{macro_text}"
            )
            if sector_context:
                user += f"\n\nTASE sector rotation context:\n{sector_context}"
            user += "\n\nReturn JSON only."
            return json.loads(self._call(_WEEKLY_SYSTEM, user))
        except Exception as e:
            print(f"[LLM] weekly_report error: {e}")
            return {}

    def score_sector(
        self,
        grouped:        dict[str, dict],
        sector_domain:  str,
        macro_text:     str = "",
        technical_data: dict | None = None,
        memory_context: dict[str, str] | None = None,
    ) -> list[dict]:
        """
        Sector-specialized portfolio scoring. Used by each SectorAgent.
        `grouped` contains ONLY the week's relevant tickers (tickers with signals).
        `memory_context` maps ticker -> compact memory string from StockMemoryManager.
        Returns the portfolio list from the sector JSON response.
        """
        if not grouped:
            return []
        try:
            system = _SECTOR_BASE_SYSTEM.format(sector_domain=sector_domain)
            engine = ConvergenceEngine()
            user   = f"Active stocks in sector this week ({len(grouped)} discovered):\n"
            user  += engine.to_llm_input(grouped)

            # Inject per-stock memory context — historical analyst notes, signal patterns,
            # recent news headlines, and cached technicals from prior cycles.
            if memory_context:
                mem_lines = [
                    f"  {tkr}: {ctx}"
                    for tkr, ctx in memory_context.items()
                    if ctx
                ]
                if mem_lines:
                    user += "\n\nPer-stock memory (historical context from prior cycles):\n"
                    user += "\n".join(mem_lines)

            if macro_text:
                user += f"\n\nMacro context:\n{macro_text}"
            if technical_data:
                user += "\n\nDeep financial data for relevant stocks:\n"
                user += json.dumps(_sanitize(technical_data), ensure_ascii=False, default=_json_safe)
            user += "\n\nReturn JSON only (full portfolio schema)."
            raw = json.loads(self._call(system, user))
            if isinstance(raw, dict):
                return raw.get("portfolio", [])
            return raw
        except Exception as e:
            print(f"[LLM] score_sector error: {e}")
            return []

    def extract_web_news_signals(
        self,
        ticker:       str,
        company_name: str,
        articles:     list[dict],
    ) -> list[dict]:
        """
        Given web news articles about a specific ticker, use the LLM to extract
        structured trading signals.

        Returns a list of signal dicts:
          [{signal_type, headline, detail, sentiment, relevance}]
        where relevance is 1-10 (10 = major catalyst).

        Only signals with relevance >= 4 and sentiment != "neutral" are returned.
        Kept as dicts (not Signal objects) so the caller decides how to construct Signals.
        """
        if not articles:
            return []
        try:
            articles_text = "\n\n".join(
                f"[{i+1}] {a['title']}\n{a.get('snippet','')}"
                for i, a in enumerate(articles)
            )
            user = (
                f"Company: {company_name} | Ticker: {ticker}\n\n"
                f"News articles:\n{articles_text}\n\n"
                "Extract trading-relevant signals. Return a JSON array of objects.\n"
                "Each object must have:\n"
                '  "signal_type": choose EXACTLY ONE from: new_contract, earnings, institutional_investor, '
                'regulatory_approval, partnership, management_change, financial_event, '
                'buyback, dividend, ipo, geopolitical, general_news\n'
                '  "headline": one sentence\n'
                '  "detail": 2-3 sentences with key facts\n'
                '  "sentiment": exactly one of: bullish, bearish, neutral\n'
                '  "relevance": integer 1-10\n\n'
                "Include only signals with relevance >= 4. Return [] if nothing material."
            )
            raw = json.loads(self._call(_WEB_NEWS_SYSTEM, user))
            if not isinstance(raw, list):
                return []
            return [s for s in raw if s.get("relevance", 0) >= 4 and s.get("sentiment") != "neutral"]
        except Exception as e:
            print(f"[LLM] extract_web_news_signals error for {ticker}: {e}")
            return []

    # ── Interactive bot: Q&A methods ─────────────────────────────────────────

    _INTENT_SYSTEM = """\
You are the tool-routing brain of an Israeli stock research Telegram bot.
The bot has a live research pipeline that scans all TASE stocks every 15 minutes
using Maya regulatory filings, yfinance data, and Google News.

Your job: read the user's question and decide ONE of:
  A) Answer directly from your own knowledge — return tools: []
  B) Call 1–4 tools from the registry to fetch live data, then synthesise

Known tickers (BARE symbol → company name):
{ticker_list}

{tool_catalogue}

Return ONLY valid JSON — no prose, no markdown, no code fences:
{{
  "ticker":   "<BARE symbol e.g. TEVA, ESLT — or null if no specific stock>",
  "intent":   "<stock_analysis|market_overview|sector_query|ipo_query|maya_query|maya_history|recommendations|tracker_query|live_scan|alert_query|top_movers_query|financial_query|screening_query|action_intent|direct_answer|general_question>",
  "tools":    ["<tool1>", "<tool2>"],
  "language": "<en|he>"
}}

WHEN TO USE tools: [] (direct_answer) — ONLY these cases:
- Conversational / greeting ("hello", "thanks", "שלום")
- Follow-up fully answered by conversation history ("what did you just say?", "explain that again")
- General finance / investment concepts ("what is RSI?", "explain P/E ratio")
- Questions about how the bot works ("what can you do?", "how do you pick stocks?")
- Simple arithmetic or definitions that need no market data

⚠️ NEVER use direct_answer for ANY of these — they ALWAYS need tools:
- Current price, RSI, moving averages, volume, market cap for any specific stock
- How much a stock went up or down (today, this week, this month, this year, ever)
- Recent performance, returns, percentage change of any stock or index
- Top movers, biggest gainers, biggest losers, most active stocks (any timeframe)
- Recent news, today's news, latest filings about a company
- Whether a stock is moving right now, any anomaly or spike
- What to buy, researcher picks, best stocks this week
- Market overview, macro snapshot, sector rotation
CRITICAL: Your training data is months old. NEVER answer these from training knowledge.
Always call the appropriate tool — get_top_movers, get_stock_data, get_macro, etc.
A wrong live-data answer from training knowledge is worse than saying "fetching...".

WHEN TO USE TOOLS (all data questions):
- Current price, RSI, volume, news for any stock
- Market overview, sector rotation, macro snapshot
- Researcher picks, Maya filings, signal history, filing history, custom alerts

TICKER RESOLUTION RULES:
- If "Prior conversation" context is provided, resolve ticker references like
  "it", "this stock", "the company", "same one", "its RSI", "what about it" from
  the most recent assistant turn that mentioned a specific stock.
- Hebrew stock name → map to bare symbol (e.g. "טבע"→"TEVA", "אלביט"→"ESLT", "בזק"→"BEZQ")
- English company name → map to bare symbol (e.g. "Teva"→"TEVA", "Elbit"→"ESLT")
- Already a symbol → use as-is without .TA suffix
- If you cannot confidently identify the company → null

LANGUAGE DETECTION:
- If ANY Hebrew character (U+05D0–U+05EA) appears in the question → "he"
- Otherwise → "en"

INTENT GUIDANCE:
- stock_analysis   → question about a SPECIFIC company's price, news, signals, current outlook
- market_overview  → broad market, macro, how is the market doing
- sector_query     → about a sector (banks, tech, energy, real estate...)
- ipo_query        → new listings, IPOs, הנפקות, new companies listing on TASE
- maya_query       → THIS WEEK'S regulatory filings, institutional buys, contracts filed on TASE
- maya_history     → HISTORICAL filing timeline for a specific stock across all past cycles
- recommendations  → "what to buy", "best pick", "stock of the week", today's alerts
- tracker_query    → "what stocks are you watching", "show me all bullish stocks"
- earnings_query   → upcoming earnings events: "when does X report?", "what earnings are coming
                     this week?", "מתי הדיווח הרבעוני?", "earnings calendar", "when does TEVA report?"
                     Use for earnings-specific questions (gets stock data + weekly signals + memory)
- live_scan        → "is anything happening with X right now", real-time anomaly
- alert_query      → user asking about THEIR OWN custom alerts ("what alerts do I have?", "show my alerts")
- top_movers_query → "what went up most today?", "biggest gainers today", "top losers today",
                     "what stocks fell the most?", "מה עלה הכי הרבה היום?", "מה ירד הכי הרבה?",
                     "top X stocks up today", "best performers today" — NO ticker needed
- financial_query  → user asks about revenue, profit, earnings, EPS, balance sheet FOR A SPECIFIC STOCK
                     (e.g. "what was Ayalon's revenue last year?", "מה הרווח של בזק ברבעון?", "TEVA EPS 2024")
                     ALWAYS requires a ticker. Use get_financials tool.
- screening_query  → user asks BROAD comparison across ALL stocks without specifying one stock
                     (e.g. "cheapest stock by P/E", "highest dividend yield on TASE", "best revenue growth",
                     "מה הכי זול?", "מניה עם הצמיחה הגבוהה ביותר") — NO ticker needed
- direct_answer    → answer from own knowledge, NO tools needed (tools: [])
- general_question → needs tools but doesn't fit above categories
- action_intent   → user wants to SET AN ALERT, DELETE an alert, or CHANGE A SETTING
                    (e.g. "alert me when X rises 5%", "notify me of IPOs", "תתריע לי כש...")
                    Return tools: [] — action handling is done separately by the bot.

TOOL SELECTION RULES BY INTENT:
- stock_analysis   → get_stock_data + search_news + get_memory + get_weekly_signals + get_maya_filings
                     (+ run_live_scan if asking about right now)
- market_overview  → get_macro + get_sector_context
- sector_query     → get_sector_context + get_macro
- ipo_query        → get_ipo_watchlist + get_macro
- maya_query       → get_maya_filings (+ get_memory if specific ticker known)
- maya_history     → get_maya_history (requires ticker)
- recommendations  → get_alerted_stocks + get_macro
- tracker_query    → get_tracked_stocks
- earnings_query   → get_weekly_signals + get_stock_data + get_memory
- live_scan        → run_live_scan + get_stock_data + get_memory
- alert_query      → get_user_alerts
- top_movers_query → get_top_movers
- financial_query  → get_financials + get_stock_data  (revenue, profit, EPS, balance sheet for one stock)
- screening_query  → screen_stocks + get_macro  (ranking/comparison across all stocks)
- general_question → get_macro OR get_weekly_signals (pick most relevant)

EXAMPLES:
  "What is happening with Teva?" → stock_analysis, TEVA, ["get_stock_data","search_news","get_memory","get_weekly_signals","get_maya_filings"]
  "מה קורה עם אלביט?" → stock_analysis, ESLT, ["get_stock_data","search_news","get_memory","get_weekly_signals","get_maya_filings"]
  "Tell me about NVMI" → stock_analysis, NVMI, ["get_stock_data","search_news","get_memory","get_weekly_signals","get_maya_filings"]
  "מה המצב של בזק?" → stock_analysis, BEZQ, ["get_stock_data","search_news","get_memory","get_weekly_signals","get_maya_filings"]
  "How much is Teva up today?" → stock_analysis, TEVA, ["get_stock_data","search_news","get_memory","get_weekly_signals","get_maya_filings"]
  "כמה עלה אלביט היום?" → stock_analysis, ESLT, ["get_stock_data","search_news","get_memory","get_weekly_signals","get_maya_filings"]
  "מה השינוי של ICL החודש?" → stock_analysis, ICL, ["get_stock_data","search_news","get_memory","get_weekly_signals","get_maya_filings"]
  "What is Teva's P/E ratio?" → stock_analysis, TEVA, ["get_stock_data","search_news","get_memory","get_weekly_signals","get_maya_filings"]
  "מהו מכפיל הרווח של טבע?" → stock_analysis, TEVA, ["get_stock_data","search_news","get_memory","get_weekly_signals","get_maya_filings"]
  "מה מכפיל ה-P/E של אלביט?" → stock_analysis, ESLT, ["get_stock_data","search_news","get_memory","get_weekly_signals","get_maya_filings"]
  "What is Bezeq's dividend yield?" → stock_analysis, BEZQ, ["get_stock_data","search_news","get_memory","get_weekly_signals","get_maya_filings"]
  "When is Teva's next earnings date?" → stock_analysis, TEVA, ["get_stock_data","get_weekly_signals","get_memory","get_maya_filings"]
  "מתי הדיווח הרבעוני הבא של אלביט?" → stock_analysis, ESLT, ["get_stock_data","get_weekly_signals","get_memory","get_maya_filings"]
  "When does LUMI report earnings?" → stock_analysis, LUMI, ["get_stock_data","get_weekly_signals","get_memory","get_maya_filings"]
  "How is the market today?" → market_overview, null, ["get_macro","get_sector_context"]
  "What should I buy today?" → recommendations, null, ["get_alerted_stocks","get_macro"]
  "Any new IPOs this week?" → ipo_query, null, ["get_ipo_watchlist","get_macro"]
  "Show me all IPOs" → ipo_query, null, ["get_ipo_watchlist"]
  "יש הנפקות חדשות?" → ipo_query, null, ["get_ipo_watchlist","get_macro"]
  "What Maya filings came in today?" → maya_query, null, ["get_maya_filings"]
  "Any institutional buys this week?" → maya_query, null, ["get_maya_filings"]
  "What has TEVA filed on Maya?" → maya_query, TEVA, ["get_maya_filings","get_memory"]
  "What did the Borsa publish today?" → maya_query, null, ["get_maya_filings"]
  "What are the last messages from the Borsa?" → maya_query, null, ["get_maya_filings"]
  "Show me the latest TASE announcements" → maya_query, null, ["get_maya_filings"]
  "מה הבורסה פרסמה היום?" → maya_query, null, ["get_maya_filings"]
  "מה ההודעות האחרונות מהבורסה?" → maya_query, null, ["get_maya_filings"]
  "אילו דיווחים הוגשו לבורסה השבוע?" → maya_query, null, ["get_maya_filings"]
  "Show me TEVA's filing history" → maya_history, TEVA, ["get_maya_history"]
  "What has Elbit filed over the past months?" → maya_history, ESLT, ["get_maya_history"]
  "היסטוריית הגשות של בנק לאומי" → maya_history, LUMI, ["get_maya_history"]
  "What stocks are you tracking?" → tracker_query, null, ["get_tracked_stocks"]
  "Show me bullish stocks" → tracker_query, null, ["get_tracked_stocks"]
  "Is Elbit moving right now?" → live_scan, ESLT, ["run_live_scan","get_stock_data","get_memory"]
  "What happened this week?" → market_overview, null, ["get_weekly_signals","get_alerted_stocks","get_macro"]
  "What alerts do I have?" → alert_query, null, ["get_user_alerts"]
  "Show my alerts" → alert_query, null, ["get_user_alerts"]
  "מה ההתראות שלי?" → alert_query, null, ["get_user_alerts"]
  "Do I have any active alerts?" → alert_query, null, ["get_user_alerts"]
  "Alert me when TEVA rises 5%" → action_intent, TEVA, []
  "תתריע לי כשאיילון עולה 5%" → action_intent, null, []
  "Notify me of any IPOs" → action_intent, null, []
  "Alert me when there's a volume spike on Elbit" → action_intent, ESLT, []
  "I want an alert for Bezeq earnings" → action_intent, BEZQ, []
  "What was Ayalon's revenue last year?" → financial_query, AYALON, ["get_financials","get_stock_data"]
  "מה הרווח של בזק ברבעון הראשון?" → financial_query, BEZQ, ["get_financials","get_stock_data"]
  "TEVA EPS 2024" → financial_query, TEVA, ["get_financials","get_stock_data"]
  "What is the cheapest stock on TASE by P/E?" → screening_query, null, ["screen_stocks","get_macro"]
  "Which stock has the highest dividend yield?" → screening_query, null, ["screen_stocks","get_macro"]
  "מה המניה עם הצמיחה הגבוהה ביותר בהכנסות?" → screening_query, null, ["screen_stocks","get_macro"]
  "מה הכי זול בבורסה?" → screening_query, null, ["screen_stocks","get_macro"]
  "What stock went up the most today?" → top_movers_query, null, ["get_top_movers"]
  "What are the top 5 gainers today?" → top_movers_query, null, ["get_top_movers"]
  "מה עלה הכי הרבה היום?" → top_movers_query, null, ["get_top_movers"]
  "מה ירד הכי הרבה היום?" → top_movers_query, null, ["get_top_movers"]
  "What stocks fell the most today?" → top_movers_query, null, ["get_top_movers"]
  "Show me top 3 losers today" → top_movers_query, null, ["get_top_movers"]
  "Best performers today on TASE" → top_movers_query, null, ["get_top_movers"]
  "Remove my alert for TEVA" → action_intent, TEVA, []
  "Stop alerting me about IPOs" → action_intent, null, []
  "Hello, how are you?" → direct_answer, null, []
  "What is RSI?" → direct_answer, null, []
  "מה זה יחס P/E?" → direct_answer, null, []
  "What can you do?" → direct_answer, null, []
  "Thanks!" → direct_answer, null, []
  "Explain what you just said" → direct_answer, null, []

Note: "מה זה P/E?" = direct_answer (explain the concept). "מה ה-P/E של טבע?" = stock_analysis (fetch live data).
Pick 1–5 tools when using tools (stock questions may need up to 5). Use [] for direct answers.
"""

    _CHAT_ANSWER_SYSTEM = """\
You are a senior Israeli equity research analyst answering questions in a Telegram chat.
Use conversation history from prior turns — if the user says "what about its RSI?" you know
which stock from prior context.

━━━ TWO MODES ━━━

MODE 1 — Research context provided:
  • Use the data given. Cite specific numbers (RSI, price, score, dates, period returns).
  • Synthesise into an analytical view — do not just list raw data.
  • Structure: start with the key takeaway, then supporting evidence, then risk/watchpoint.
  • NEVER say "I'm not familiar with this stock" or "I don't have historical data" when
    context was provided — even partial context. Use whatever IS there, then note any gaps.
  • If Yahoo Finance returned no price data: say so in one line, then pivot to news/signals/memory.
  • Period returns (1W, 1M, 3M, 1Y) are now included in live data — always cite them when present.

MODE 2 — No research context (direct_answer — concepts and general knowledge only):
  • Use ONLY for: greetings, definitions (what is RSI?), how the bot works, financial concepts.
  • For well-known Israeli companies: you may describe the business model, sector, typical
    drivers — but NEVER state a current price, today's change, or recent performance from
    training knowledge. If asked for current data with no context, say you need to fetch it.
  • Be educational and direct. Use conversation history for coherence.

━━━ DATA COVERAGE RULES ━━━
  • NEVER refuse to answer by saying "I'm not familiar" — always give the best answer possible
    from the combination of live research context + your own knowledge.
  • For Israeli small-cap / micro-cap TASE stocks: acknowledge limited data availability but
    still analyse whatever signals, news, or filings are present in the context.
  • If historical performance is asked but no returns data was fetched: explain the live data
    showed no return history from Yahoo Finance, and describe what you CAN see (RSI, range, etc.).
  • For questions about % gains/losses, always look for "Returns:" line in context first.
  • TASE intraday data limitation: Yahoo Finance does NOT provide real-time intraday data for
    TASE (.TA) stocks. The "last session" change in context is the most recent completed trading
    session's move — NOT the current intraday move. When answering "how much is X moving today?",
    cite the last session figure and note it reflects the last completed session, not live ticks.
    If price_data_note says "last_session", say "last session" not "today" in your answer.

⛔ HARD RULE — NEVER USE TRAINING DATA FOR CURRENT MARKET DATA:
  • NEVER state a current stock price, today's % change, this week's return, or any live
    market figure from your training knowledge. Your training data is months old — any price
    or movement figure from training will be WRONG and misleading.
  • For "top movers", "biggest gainers/losers", "what went up/down today": ONLY cite numbers
    from the [get_top_movers] or [get_stock_data] tool context. If those tools returned no data,
    say "I couldn't fetch live data from Yahoo Finance right now" — do NOT guess or fabricate.
  • If a tool returned an error or empty result: say so explicitly ("Yahoo Finance returned no
    data for this ticker") rather than filling the gap with training knowledge.
  • This rule overrides the "never refuse" rule — for CURRENT PRICES AND MOVEMENTS, refusing to
    hallucinate is always correct.

━━━ FORMATTING RULES (Telegram) ━━━
  • Use **bold** for stock tickers, company names, and key numbers (Telegram renders this).
  • Use bullet lists (• or -) for multiple signals, risks, or comparison points.
  • Keep responses 3–8 sentences for simple questions; up to 12 for "tell me everything".
  • Always mention the company name alongside the ticker (e.g. "**TEVA** (Teva Pharmaceutical)").
  • When describing a technical setup: RSI < 30 = oversold (bullish bias), RSI > 70 = overbought.
  • When presenting Maya filings: label the type clearly (earnings, contract, institutional buy).
  • End with a concrete "Watch for:" or "Risk:" line when relevant — gives actionable takeaway.

━━━ ANALYTICAL DEPTH ━━━
  • Signal convergence: multiple independent signals on one stock = stronger conviction.
  • Catalyst quality: Maya filing > web news > pure technical.
  • Macro context always matters: rising VIX → reduce conviction; risk-on → amplify.
  • Small-cap TASE stocks: volume spike on low float = potentially significant even at 3× avg.
  • Score context: 65+ = strong buy candidate; 50–64 = watch; 35–49 = monitor only.

━━━ FINANCIAL DATA FORMATTING ━━━
  • Revenue/income: always show currency (₪ for ILS) and scale (M for millions, B for billions).
    Compare periods: "Revenue grew X% YoY from ₪YM (2023) to ₪ZM (2024)."
  • For screening questions: present as ranked list with the key differentiating metric highlighted.
  • Valuation context for TASE:
    - Banks (LUMI, POLI, MZTF, DSCT): normal P/E 6–10×; P/B 0.5–1.2×
    - Tech/Defense (ESLT, NICE, NVMI): normal P/E 15–30×
    - REITs (AZRG, AMOT, BIG): normal P/E 12–20×; dividend yield 3–6%
    - Telecom (BEZQ): normal dividend yield 5–8%
    - Consumer staples (SAE, RMLI): normal P/E 12–18×
  • If get_financials returned "No … data available": say so, then use get_stock_data revenue growth % as proxy.
  • NEVER fabricate specific revenue or earnings numbers — only cite what appears in the tool context.

If language is Hebrew, respond entirely in Hebrew (including labels and numbers).
"""

    _RESOLVE_TICKER_SYSTEM = """\
You are a TASE stock identifier. The user mentioned a company in Hebrew or English but we
couldn't match it to a known ticker symbol.

Your job: given the user's question and a list of all TASE-listed companies (ID: Hebrew name),
identify which company the user is asking about and return a JSON object.

Return ONLY valid JSON — no prose:
{{"ticker": "<BARE symbol e.g. TEVA — or null if this is not a real .TA ticker>",
  "company_name": "<Hebrew company name as it appears in the list — or best guess>",
  "tase_id": "<TASE company ID from the list — or null if not found>",
  "confidence": "<high|medium|low>"}}

Rules:
- ticker: fill only if you are confident this is a well-known .TA stock (TEVA, ESLT, LUMI, etc.)
- company_name: always fill with the best match from the company list
- tase_id: fill from the company list if found
- If you truly cannot identify any company → set all fields to null, confidence=low
"""

    def plan_intent(self, question: str, ticker_list: str, tool_catalogue: str = "",
                    history: list | None = None) -> dict:
        """
        Call 1 of the Q&A pipeline: detect intent + which tools to call.
        Returns {ticker, intent, tools, language}.
        tool_catalogue is the full TOOL_CATALOGUE string from qa_pipeline.py.
        history: last N messages [{role, content}] — used to resolve follow-up ticker references.
        """
        try:
            system = self._INTENT_SYSTEM.format(
                ticker_list=ticker_list,
                tool_catalogue=tool_catalogue,
            )
            # If conversation history is available, prepend last 2 turns so the LLM
            # can resolve pronouns/references ("its RSI", "the same stock", "it") and
            # carry forward the ticker from the prior question.
            if history:
                prior = history[-4:]   # last 2 turns (4 messages)
                prior_lines = [
                    f"{m['role'].upper()}: {str(m.get('content', ''))[:150]}"
                    for m in prior
                ]
                user_msg = "Prior conversation (use to resolve 'it'/'this stock' references):\n"
                user_msg += "\n".join(prior_lines)
                user_msg += f"\n\nCurrent question: {question}"
            else:
                user_msg = question
            raw = self._call(system, user_msg)
            result = json.loads(raw)
            # Ensure required keys with safe defaults
            result.setdefault("ticker", None)
            result.setdefault("intent", "general_question")
            result.setdefault("tools", None)   # None → decide below
            result.setdefault("language", "en")
            # Empty string ticker → None
            if not result["ticker"]:
                result["ticker"] = None
            # If tools is None (missing key) — default based on intent
            if result["tools"] is None:
                if result["intent"] == "direct_answer":
                    result["tools"] = []
                else:
                    result["tools"] = ["get_macro"]
            # Hebrew heuristic override (no extra API call)
            if any("\u05d0" <= ch <= "\u05ea" for ch in question):
                result["language"] = "he"
            return result
        except Exception as e:
            print(f"[LLM] plan_intent error: {e}")
            lang = "he" if any("\u05d0" <= ch <= "\u05ea" for ch in question) else "en"
            return {"ticker": None, "intent": "general_question", "tools": ["get_macro"], "language": lang}

    def chat_answer(
        self,
        question:  str,
        context:   str,
        language:  str = "en",
        history:   list[dict] | None = None,
    ) -> str:
        """
        Call 2 of the Q&A pipeline: synthesise an answer from tool outputs.
        history: list of {"role": "user"|"assistant", "content": str} for prior turns.
        Returns plain-text answer in the requested language.
        """
        try:
            if context:
                user_msg = (
                    f"Language: {language}\n\n"
                    f"Research context for this question:\n{context}\n\n"
                    f"Current question: {question}"
                )
            else:
                # Direct answer — no tool data, LLM uses own knowledge + history
                user_msg = (
                    f"Language: {language}\n\n"
                    f"[No research data was fetched — answer from your own knowledge.]\n\n"
                    f"Question: {question}"
                )
            messages = [{"role": "system", "content": self._CHAT_ANSWER_SYSTEM}]
            if history:
                messages.extend(history[-8:])   # keep last 4 turns (8 messages)
            messages.append({"role": "user", "content": user_msg})
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,
            )
            return strip_json_fences(resp.choices[0].message.content)
        except Exception as e:
            print(f"[LLM] chat_answer error: {e}")
            if language == "he":
                return "מצטער, אירעה שגיאה בעת עיבוד השאלה שלך. נסה שנית."
            return "Sorry, an error occurred while processing your question. Please try again."

    def resolve_ticker(self, question: str, company_list_text: str) -> dict:
        """
        Fallback ticker resolver: when plan_intent couldn't identify the company,
        ask the LLM with the full TASE company list to find the match.
        Returns {ticker, company_name, tase_id, confidence}.
        """
        try:
            user = (
                f"User question: {question}\n\n"
                f"TASE company list (ID: Hebrew name):\n{company_list_text}\n\n"
                "Which company is the user asking about? Return JSON only."
            )
            raw = self._call(self._RESOLVE_TICKER_SYSTEM, user)
            result = json.loads(raw)
            result.setdefault("ticker", None)
            result.setdefault("company_name", None)
            result.setdefault("tase_id", None)
            result.setdefault("confidence", "low")
            if not result["ticker"]:
                result["ticker"] = None
            return result
        except Exception as e:
            print(f"[LLM] resolve_ticker error: {e}")
            return {"ticker": None, "company_name": None, "tase_id": None, "confidence": "low"}

    # ── Action intent parser ──────────────────────────────────────────────────

    _ACTION_SYSTEM = """\
You are parsing a Telegram message to extract a bot action request.
The user is asking an Israeli stock research bot to DO something — set an alert,
remove an alert, or change a bot setting. Hebrew and English are both valid.

Extract the action and return ONLY valid JSON — no prose, no markdown:
{
  "action": "add_alert|delete_alert|change_setting|none",
  "alert_type": "price_move|volume_spike|earnings|maya_filing|institutional|ipo|any_signal",
  "ticker": "<BARE symbol e.g. AYLN, TEVA — or null>",
  "company_name": "<human-readable name from the message — or null>",
  "threshold": <float percentage for price_move, e.g. 5.0 — or null>,
  "direction": "up|down|any",
  "setting_name": "<language|interval|topn|volume|price|alerts_on|alerts_off|sectors — or null>",
  "setting_value": "<new value as a string — or null>",
  "confirm_en": "<one-sentence English confirmation to show the user>",
  "confirm_he": "<one-sentence Hebrew confirmation to show the user>"
}

Alert types:
  price_move    — stock rises or falls by a specific percentage
  volume_spike  — unusual volume / trading activity spike
  earnings      — earnings report or upcoming earnings event
  maya_filing   — any regulatory filing on Maya (IPO, contract, buyback, etc.)
  institutional — institutional investor / insider stake change
  ipo           — new IPO / company listing filed on TASE
  any_signal    — any research signal for the ticker (catch-all)

Setting names (for change_setting):
  language   — "en" or "he"  (2–240 chars)
  interval   — integer minutes 5–240
  topn       — integer 1–10 (how many stocks per alert)
  volume     — float 1.5–10.0 (volume spike multiplier)
  price      — float 1.0–20.0 (price move % threshold)
  alerts_on  — no value needed (enable Telegram delivery)
  alerts_off — no value needed (disable Telegram delivery)
  sectors    — comma-separated subset of: Banks,TechDefense,Energy,PharmaBiotech,RealEstate,TelecomConsumer,Discovery

Rules:
- "alert me when X rises 5%" → add_alert, price_move, threshold=5.0, direction=up
- "alert me when X drops 3%" → add_alert, price_move, threshold=3.0, direction=down
- "notify me of IPOs" → add_alert, ipo, ticker=null
- "alert on earnings for TEVA" → add_alert, earnings, ticker=TEVA
- "volume spike alert for Elbit" → add_alert, volume_spike, ticker=ESLT
- "remove my TEVA alert" / "stop alerting me about TEVA" → delete_alert, ticker=TEVA
- "switch to Hebrew" / "שנה שפה לעברית" → change_setting, setting_name=language, setting_value=he
- "scan every 20 minutes" / "סרוק כל 20 דקות" → change_setting, setting_name=interval, setting_value=20
- "send me top 5 picks" → change_setting, setting_name=topn, setting_value=5
- "set volume spike to 3x" → change_setting, setting_name=volume, setting_value=3.0
- "price threshold 4%" → change_setting, setting_name=price, setting_value=4.0
- "disable alerts" / "כבה התראות" → change_setting, setting_name=alerts_off, setting_value=null
- "enable alerts" / "הפעל התראות" → change_setting, setting_name=alerts_on, setting_value=null
- "scan only Banks and Energy" → change_setting, setting_name=sectors, setting_value=Banks,Energy
- If the message isn't a clear action request → action=none

confirm_en / confirm_he: phrase as a yes/no question the bot will send to the user.
  Good: "Add a price alert for Ayalon (AYLN) when it rises >=5%?"
  Good: "Set a volume spike alert for Elbit Systems (ESLT)?"
  Good: "Switch the bot language to Hebrew?"
  Good: "Set scan interval to 20 minutes?"
  Good: "Disable Telegram alert delivery?"
  Good (Hebrew): "להוסיף התראת מחיר לאיילון (AYLN) כשתעלה 5%?"
  Good (Hebrew): "לשנות את שפת הבוט לעברית?"
  Good (Hebrew): "לכבות שליחת התראות?"
"""

    def parse_action_intent(self, question: str, ticker_list: str = "") -> dict:
        """
        Parse an action request from free text (Hebrew or English).
        Returns structured action dict with confirm_en / confirm_he.
        Called when plan_intent returns action_intent.
        """
        try:
            context = f"Known tickers:\n{ticker_list}\n\n" if ticker_list else ""
            user    = f"{context}User message: {question}"
            raw     = self._call(self._ACTION_SYSTEM, user)
            result  = json.loads(raw)
            # Normalise
            result.setdefault("action",        "none")
            result.setdefault("alert_type",    "any_signal")
            result.setdefault("ticker",        None)
            result.setdefault("company_name",  None)
            result.setdefault("threshold",     None)
            result.setdefault("direction",     "any")
            result.setdefault("setting_name",  None)
            result.setdefault("setting_value", None)
            result.setdefault("confirm_en",    "Confirm this action?")
            result.setdefault("confirm_he",    "לאשר פעולה זו?")
            return result
        except Exception as e:
            print(f"[LLM] parse_action_intent error: {e}")
            return {"action": "none"}

    def arbitrate(
        self,
        sector_results: list[dict],
        macro_text: str = "",
        sector_context: str = "",
    ) -> dict:
        """
        Manager/CIO arbitration. Receives top picks from each sector agent
        and selects the best 3 across all sectors.
        Returns the same schema as weekly_report() so TelegramReporter works unchanged.
        """
        if not sector_results:
            return {}
        try:
            user  = "Sector analyst reports:\n"
            user += json.dumps(_sanitize(sector_results), ensure_ascii=False, default=_json_safe)
            if macro_text:
                user += f"\n\nGlobal macro:\n{macro_text}"
            if sector_context:
                user += f"\n\nSector rotation:\n{sector_context}"
            user += "\n\nReturn JSON only."
            return json.loads(self._call(_MANAGER_SYSTEM, user))
        except Exception as e:
            print(f"[LLM] arbitrate error: {e}")
            return {}
