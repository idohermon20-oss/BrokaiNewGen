"""
Stage 4: Agent Reasoning

Each agent is given its brief, the stock data, and the analyst context.
Agents produce structured analysis — NOT raw data summaries.
Each agent must take a stance, support it with evidence, and flag uncertainties.
"""
from typing import List
import openai

from ..config import Config
from ..agents.base_agent import AgentBrief, AgentOutput, EvidenceItem
from ..orchestrator.profiler import StockProfile
from ..orchestrator.relevance_mapper import RelevanceMap
from ..data.fetcher import StockData, format_stock_data_for_llm
from ..utils.llm import call_llm, parse_json_response

VALID_STANCES = {"bullish", "bearish", "neutral", "mixed"}
VALID_CONFIDENCE = {"low", "moderate", "high"}
VALID_RELEVANCE = {"high", "medium", "low"}
VALID_DIRECTION = {"bullish", "bearish", "neutral"}


# ── Date helpers ───────────────────────────────────────────────────────────────

def _parse_date_for_sort(date_str: str) -> str:
    """
    Parse any date string into a sortable ISO-format string (YYYY-MM-DD HH:MM:SS).
    Returns "" for unparseable/empty input so those sort to the bottom.
    Handles: ISO, RFC 2822, Unix timestamp, and common variants.
    """
    if not date_str or not str(date_str).strip():
        return ""
    s = str(date_str).strip()

    # Already looks like ISO (YYYY-MM-DD...)
    if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
        return s[:19]

    # Unix timestamp (integer or float)
    try:
        import datetime as _dt
        ts = float(s)
        if 1_000_000_000 < ts < 9_999_999_999:
            return _dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        pass

    # RFC 2822 / email date format ("Thu, 14 Mar 2024 12:00:00 +0000")
    try:
        import email.utils as _eu
        parsed = _eu.parsedate_to_datetime(s)
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    # ISO with T separator
    try:
        import datetime as _dt
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M",
                    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return _dt.datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
    except Exception:
        pass

    return s   # fallback: return as-is; lexicographic sort may still work


def _recency_label(iso_date: str) -> str:
    """
    Return a recency weight tag based on days since publication.
      ≤3 days  → [HIGH RECENCY]
      ≤14 days → [MED RECENCY]
      older    → "" (no tag — low weight)
    """
    if not iso_date:
        return ""
    try:
        import datetime as _dt
        dt = _dt.datetime.fromisoformat(iso_date[:10])
        days_old = (_dt.datetime.now() - dt).days
        if days_old <= 3:
            return "[HIGH RECENCY]"
        elif days_old <= 14:
            return "[MED RECENCY]"
    except Exception:
        pass
    return ""


def _format_price_reaction_context(
    stock_data,
    article_impacts: list,
    maya_reports: list,
) -> str:
    """
    Build a PRICE REACTION ANALYSIS block injected into every agent.

    Finds the most recent significant events (last 30 days, bullish/bearish)
    and compares them to the stock's 1-month price performance.
    Highlights divergences — positive events + falling price, or vice versa.
    """
    if stock_data is None or stock_data.price_change_1m is None:
        return ""

    import datetime as _dt
    now = _dt.datetime.now()
    significant = []

    for a in (article_impacts or []):
        if a.impact in ("bullish", "bearish") and a.published:
            try:
                days_old = (now - _dt.datetime.fromisoformat(a.published[:10])).days
                if days_old <= 30:
                    significant.append((days_old, a.impact, a.title[:90], "news"))
            except Exception:
                pass

    for r in (maya_reports or []):
        if r.impact in ("bullish", "bearish") and r.published:
            try:
                days_old = (now - _dt.datetime.fromisoformat(r.published[:10])).days
                if days_old <= 30:
                    significant.append((days_old, r.impact, r.title[:90], "filing"))
            except Exception:
                pass

    if not significant:
        return ""

    significant.sort(key=lambda x: x[0])  # newest first
    significant = significant[:4]

    price_1m = stock_data.price_change_1m
    price_dir = "UP" if price_1m > 2 else "DOWN" if price_1m < -2 else "FLAT"
    sign = "+" if price_1m > 0 else ""

    bull_count = sum(1 for _, t, _, _ in significant if t == "bullish")
    bear_count = sum(1 for _, t, _, _ in significant if t == "bearish")
    dominant = "bullish" if bull_count >= bear_count else "bearish"

    if dominant == "bullish" and price_dir == "UP":
        reaction = "Price is confirming positive events — bullish signal alignment."
    elif dominant == "bullish" and price_dir == "DOWN":
        reaction = ("DIVERGENCE: Positive recent events, yet price is falling. "
                    "Either sellers are in control, the news was already priced in, "
                    "or the market doubts the impact. Investigate cause.")
    elif dominant == "bullish" and price_dir == "FLAT":
        reaction = ("Positive events but muted price reaction. "
                    "Market may be skeptical or waiting for confirmation.")
    elif dominant == "bearish" and price_dir == "DOWN":
        reaction = "Price is confirming negative events — bearish signal alignment."
    elif dominant == "bearish" and price_dir == "UP":
        reaction = ("DIVERGENCE: Negative recent events, yet price is rising. "
                    "Market may be showing resilience or has already priced in the risk. "
                    "Could indicate strong underlying bid or trapped shorts.")
    elif dominant == "bearish" and price_dir == "FLAT":
        reaction = ("Negative events but muted price reaction. "
                    "Market may be discounting the severity of the risk.")
    else:
        reaction = "Mixed signals — no clear correlation between events and price direction."

    lines = [
        "\n--- PRICE REACTION ANALYSIS (factor this into your reasoning) ---",
        f"  1-Month price performance: {sign}{price_1m:.1f}%  [{price_dir}]",
        f"  Recent significant events (last 30 days):",
    ]
    for days_old, impact, title, kind in significant:
        lines.append(f"    [{impact.upper()}|{kind}] ~{days_old}d ago: {title}")
    lines.append(f"  >> INTERPRETATION: {reaction}")
    lines.append(
        "  If your domain is affected by this divergence — call it out explicitly."
    )
    return "\n".join(lines)


_SYSTEM = """You are a specialized investment analyst. You have been assigned to analyze
one specific aspect of a stock for an investment committee.

Your job is to:
1. Analyze ONLY your assigned domain — do not stray into other analysts' territory
2. Produce reasoning, not just data summaries
3. Take a clear stance — do not be wishy-washy
4. Clearly separate facts from your interpretations
5. Explicitly state what you don't know
6. Flag anything the investment committee must pay attention to

You are writing for professional investors. Be direct, specific, and honest.
Return only valid JSON. No prose outside the JSON object."""


def _age_tag(published: str) -> str:
    """Return a human-readable age tag for a filing/article date."""
    if not published:
        return ""
    try:
        import datetime as _dt
        days = (_dt.datetime.now() - _dt.datetime.fromisoformat(published[:10])).days
        if days <= 3:
            return " *** LATEST (<=3d) ***"
        if days <= 14:
            return f" [recent: {days}d ago]"
        if days <= 90:
            return f" [{days}d ago]"
        return f" [OLD: {days}d ago]"
    except Exception:
        return ""


_SENTIMENT_BADGE = {
    "strong_bullish": "STRONG BULL",
    "bullish":        "BULLISH",
    "neutral":        "NEUTRAL",
    "bearish":        "BEARISH",
    "strong_bearish": "STRONG BEAR",
}


def _format_article_impacts_for_trend(article_impacts: list, max_items: int = 6) -> str:
    """
    Format article impacts for trend/sentiment analysts.
    Articles are assumed to be pre-sorted newest-first by main.py.
    Shows at most max_items articles; older articles beyond this are excluded.

    v2 fields (sentiment, impact_score, event_type, event_reasoning) are shown
    when available, giving agents richer context than the legacy 3-level impact.
    """
    if not article_impacts:
        return ""
    shown = article_impacts[:max_items]
    skipped = len(article_impacts) - len(shown)
    lines = [f"\n--- ASSESSED ARTICLE IMPACTS (newest first, showing {len(shown)} of {len(article_impacts)}) ---"]
    for a in shown:
        # Use v2 sentiment badge when available, fall back to legacy impact
        sentiment    = getattr(a, "sentiment", "") or ""
        impact_score = getattr(a, "impact_score", 0) or 0
        event_type   = getattr(a, "event_type", "") or ""
        event_reason = getattr(a, "event_reasoning", "") or ""

        if sentiment in _SENTIMENT_BADGE:
            badge = _SENTIMENT_BADGE[sentiment]
            score_tag = f"|{impact_score}/5" if impact_score else ""
            type_tag  = f" ({event_type})" if event_type else ""
            badge_str = f"[{badge}{score_tag}]{type_tag}"
        else:
            badge_str = f"[{a.impact.upper()}]"

        date_str = f"[{(a.published or '')[:10]}]" if a.published else "[no date]"
        age      = _age_tag(a.published or "")
        url_ref  = f" | {a.url}" if a.url else ""
        lines.append(f"  {date_str}{age} {badge_str} {a.title} ({a.source}){url_ref}")
        # Show event reasoning first (concise causal sentence), then impact summary
        if event_reason:
            lines.append(f"    >> {event_reason[:120]}")
        elif a.impact_summary:
            lines.append(f"    >>{a.impact_summary}")
    if skipped:
        lines.append(f"  [... {skipped} older article(s) not shown — focus on the above]")
    return "\n".join(lines)


def _filing_age_days(r) -> int:
    """Return age in days of a filing, or 9999 if unparseable."""
    try:
        import datetime as _dt
        return (_dt.datetime.now() - _dt.datetime.fromisoformat((r.published or "")[:10])).days
    except Exception:
        return 9999


def _format_maya_reports_for_trend(maya_reports: list, max_items: int = 5) -> str:
    """
    Format Maya/TASE filings for fundamental/trend analysts.
    Filings are assumed to be pre-sorted newest-first by main.py.

    CRITICAL: Only the most recent max_items filings are shown.
    When recent filings exist (< 90 days), filings older than 365 days
    are automatically excluded so they cannot dilute the analysis.
    The newest filing is explicitly flagged so agents cannot miss it.
    """
    if not maya_reports:
        return ""

    total = len(maya_reports)
    # Check if any recent filings exist (< 90 days)
    has_recent = any(_filing_age_days(r) < 90 for r in maya_reports)

    # Filter: if recent filings exist, drop anything older than 365 days
    if has_recent:
        candidates = [r for r in maya_reports if _filing_age_days(r) < 365]
        suppressed_old = total - len(candidates)
    else:
        candidates = maya_reports
        suppressed_old = 0

    # Take only the most recent max_items
    shown = candidates[:max_items]
    skipped = total - len(shown) - suppressed_old

    newest = shown[0]
    newest_date = (newest.published or "unknown")[:10]

    lines = [
        f"\n--- MAYA / TASE REGULATORY FILINGS (newest first, showing {len(shown)} of {total}) ---",
        f"  NEWEST FILING: [{newest_date}] {newest.title[:80]}",
        f"  Your analysis MUST reflect this filing. Do NOT base conclusions on older filings if this one is material.",
        "",
    ]
    for r in shown:
        badge = r.impact.upper()
        date_str = f"[{(r.published or '')[:10]}]" if r.published else "[no date]"
        age = _age_tag(r.published or "")
        link_ref = f" | {r.link}" if r.link else ""
        lines.append(f"  {date_str}{age} [{badge}] {r.title} ({r.report_type}){link_ref}")
        if r.impact_reason:
            lines.append(f"    >>{r.impact_reason}")
    if suppressed_old:
        lines.append(
            f"  [... {suppressed_old} filing(s) older than 365 days suppressed — "
            f"recent filings exist, do not use outdated data]"
        )
    if skipped:
        lines.append(f"  [... {skipped} additional filing(s) not shown — focus on the above]")
    return "\n".join(lines)


def _format_latest_context(
    article_impacts: list,
    maya_reports: list,
    max_items: int = 6,
) -> str:
    """
    Build a compact 'LATEST COMPANY EVENTS' block injected into EVERY agent prompt.

    Combines Maya filings + assessed news articles, sorted newest-first.
    Kept intentionally brief so it does not dominate the prompt; domain-specific
    agents receive full detail separately.

    Returns empty string if there is nothing to show.
    """
    events = []

    for r in (maya_reports or []):
        dt = _parse_date_for_sort(r.published or "")
        label = f"[FILING:{r.report_type.upper()}]"
        impact = f"[{r.impact.upper()}]" if r.impact != "neutral" else ""
        summary = r.impact_reason if r.impact_reason else ""
        date_display = dt[:10] if dt else "unknown date"
        events.append((dt, date_display, label, impact, r.title, summary))

    for a in (article_impacts or []):
        dt = _parse_date_for_sort(a.published or "")
        label = "[NEWS]"
        # Use v2 sentiment badge when available
        _sentiment = getattr(a, "sentiment", "") or ""
        _iscore    = getattr(a, "impact_score", 0) or 0
        _etype     = getattr(a, "event_type", "") or ""
        if _sentiment and _sentiment != "neutral" and _sentiment in _SENTIMENT_BADGE:
            _stag = f"|{_iscore}/5" if _iscore else ""
            _ttag = f" ({_etype})" if _etype else ""
            impact = f"[{_SENTIMENT_BADGE[_sentiment]}{_stag}]{_ttag}"
        elif a.impact != "neutral":
            impact = f"[{a.impact.upper()}]"
        else:
            impact = ""
        summary = getattr(a, "event_reasoning", "") or a.impact_summary or ""
        date_display = dt[:10] if dt else "unknown date"
        events.append((dt, date_display, label, impact, a.title, summary))

    if not events:
        return ""

    # Sort newest first; empty dates go last
    events.sort(key=lambda x: x[0] if x[0] else "0", reverse=True)
    events = events[:max_items]

    lines = ["", "--- LATEST COMPANY EVENTS (newest first — WEIGHT BY RECENCY) ---"]
    lines.append("  Recency weight: [HIGH RECENCY]=≤3d  [MED RECENCY]=≤14d  older=low weight")
    for dt, date_display, label, impact, title, summary in events:
        impact_str = f" {impact}" if impact else ""
        recency = _recency_label(dt)
        recency_str = f" {recency}" if recency else ""
        lines.append(f"  [{date_display}]{recency_str} {label}{impact_str} {title}")
        if summary:
            lines.append(f"    >> {summary}")
    lines.append(
        "CRITICAL: Events marked [HIGH RECENCY] happened in the last 3 days and MUST dominate your analysis. "
        "[MED RECENCY] events (last 2 weeks) are highly relevant. "
        "Do not let older data override recent material events."
    )
    return "\n".join(lines)


def _format_sector_news_for_agents(sector_news: list, max_items: int = 8) -> str:
    """
    Format sector/market news as a backdrop context block injected into every agent.

    This is intentionally kept short — it provides macro/sector colour only.
    Agents must NOT confuse sector headlines with company-specific signals.
    """
    if not sector_news:
        return ""
    shown = sector_news[:max_items]
    lines = [
        f"\n--- SECTOR & MARKET BACKDROP ({len(shown)} items) ---",
        "  These are sector/market-level headlines. Use for macro context ONLY.",
        "  Do NOT treat sector news as company-specific signals for this stock.",
    ]
    for i, item in enumerate(shown, 1):
        source_str = f"[{item.source}] " if getattr(item, "source", "") else ""
        date_str   = f"[{str(item.published)[:10]}] " if getattr(item, "published", "") else ""
        title      = getattr(item, "title", str(item))
        summary    = getattr(item, "summary", "")
        lines.append(f"  {i}. {date_str}{source_str}{title}")
        if summary:
            lines.append(f"     {summary[:200]}")
    return "\n".join(lines)


def run_agent(
    brief: AgentBrief,
    stock_data: StockData,
    profile: StockProfile,
    relevance_map: RelevanceMap,
    client: openai.OpenAI,
    config: Config,
    article_impacts: list = None,
    maya_reports: list = None,
    sector_news: list = None,
) -> AgentOutput:
    """
    Run a single expert agent and return its structured output.
    """
    stock_text = format_stock_data_for_llm(stock_data, config.currency_symbol)

    # ── Build context layers ───────────────────────────────────────────────────
    # Layer 1: Compact latest events — injected into EVERY agent so all analysts
    #          are aware of the most recent filings and news.
    latest_ctx = _format_latest_context(article_impacts or [], maya_reports or [])

    # Layer 2: Full shared context — ALL agents receive the same complete set of
    # articles and filings. No analyst works from a partial evidence base.
    domain_detail = (
        _format_article_impacts_for_trend(article_impacts or [], max_items=15)
        + _format_maya_reports_for_trend(maya_reports or [], max_items=15)
    )

    # Layer 3: Sector/market backdrop — shared across all agents for macro context.
    sector_ctx = _format_sector_news_for_agents(sector_news or [])

    # Layer 4: Price reaction analysis — how has the stock reacted to recent events?
    price_reaction_ctx = _format_price_reaction_context(
        stock_data, article_impacts or [], maya_reports or []
    )

    # All agents: compact latest context first, domain-specific full detail,
    # sector backdrop, then price reaction
    trend_extra = latest_ctx + domain_detail + sector_ctx + price_reaction_ctx

    key_questions_text = "\n".join(
        f"  {i+1}. {q}" for i, q in enumerate(relevance_map.key_questions)
    )

    prompt = f"""{config.market_context}
You are: {brief.name}
Your domain: {brief.domain}

OVERALL ANALYSIS CONTEXT:
- Stock: {profile.ticker} ({profile.company_name})
- Phase: {profile.phase}
- Time Horizon: {profile.time_horizon.upper()}
- Current situation: {profile.current_situation}
- What market is focused on: {profile.what_market_is_focused_on}

THE INVESTMENT COMMITTEE'S KEY QUESTIONS:
{key_questions_text}

YOUR SPECIFIC ASSIGNMENT:
Scope: {brief.scope}
Your key question to answer: {brief.key_question}
Out of scope for you (do NOT cover this): {brief.out_of_scope}

AVAILABLE DATA:
{stock_text}{trend_extra}

Analyze {profile.ticker} through your specific lens. Focus only on your domain.

Return a JSON object with exactly these fields:
{{
  "key_finding": "<One paragraph: your most important analytical finding — take a clear position>",
  "stance": "<bullish | bearish | neutral | mixed>",
  "confidence": "<low | moderate | high>",
  "evidence": [
    {{
      "fact": "<a specific, sourced observation from the data>",
      "source": "<where this came from: e.g. 'income statement', 'news headline', 'price data'>",
      "relevance": "<high | medium | low>",
      "reliability": "<high | medium | low>",
      "direction": "<bullish | bearish | neutral>",
      "interpretation": "<what does this mean for your domain thesis?>"
    }}
  ],
  "key_unknowns": [
    "<specific things you need to know but cannot determine from available data>"
  ],
  "flags_for_committee": [
    "<important observations, conflicts, or surprises the investment committee must weigh>"
  ],
  "full_reasoning": "<full analytical narrative — 2-4 paragraphs. Walk through your reasoning step by step. Be specific to {profile.ticker}. Do not summarize the company — analyze it.>"
}}

RULES:
- Evidence items must reference actual data from the dataset, not invented facts
- Stance must reflect your overall view for the assigned time horizon
- Do not hedge everything — take a position while acknowledging uncertainty
- If you genuinely cannot form a view, state why explicitly in key_unknowns
- full_reasoning should read like an analyst memo section, not a chatbot answer
- key_finding MUST be 1-3 complete sentences. Never end mid-sentence. Prioritize the most recent events.
- If recent events [HIGH RECENCY] or [MED RECENCY] exist, they MUST be reflected in key_finding
- Call out any price reaction divergence if you observed one in the PRICE REACTION ANALYSIS block

MANDATORY EVIDENCE REQUIREMENTS — YOU MUST FOLLOW THESE:
1. You MUST reference at least one specific Maya/TASE filing from the MAYA / TASE REGULATORY FILINGS block in your evidence or reasoning. If no filings are available, state that explicitly.
2. You MUST reference at least one specific news article from the ASSESSED ARTICLE IMPACTS block in your evidence or reasoning. If no articles are available, state that explicitly.
3. You MUST acknowledge the SECTOR & MARKET BACKDROP context in your full_reasoning — explain whether the sector trend helps or hurts {profile.ticker} from your domain's perspective.
4. Your full_reasoning MUST name at least one specific filing title OR article headline. Generic references like "recent news" or "recent filings" are NOT acceptable — cite the actual title.
5. If the evidence contradicts your prior assumptions, call it out explicitly rather than ignoring it."""

    for _attempt in range(2):
        raw = call_llm(
            client=client,
            model=config.models.agent,
            system=_SYSTEM,
            prompt=prompt,
            max_tokens=8192,
            expect_json=True,
        )
        try:
            data = parse_json_response(raw)
            break
        except ValueError:
            if _attempt == 0:
                # Retry with a reminder to be concise
                prompt = prompt + "\n\nIMPORTANT: Return ONLY a valid JSON object. Keep evidence to 3 items max. Be concise."
            else:
                # Give up — return a minimal stub so the pipeline doesn't crash
                data = {
                    "key_finding": "Analysis could not be completed due to a response formatting error.",
                    "stance": "neutral",
                    "confidence": "low",
                    "evidence": [],
                    "key_unknowns": ["LLM response was malformed — retry recommended."],
                    "flags_for_committee": ["This agent's output is unreliable — treat as missing."],
                    "full_reasoning": "Response parsing failed after 2 attempts.",
                }

    # Parse evidence items
    evidence: List[EvidenceItem] = []
    for e in data.get("evidence", []):
        relevance = e.get("relevance", "medium")
        if relevance not in VALID_RELEVANCE:
            relevance = "medium"
        reliability = e.get("reliability", "medium")
        if reliability not in VALID_RELEVANCE:
            reliability = "medium"
        direction = e.get("direction", "neutral")
        if direction not in VALID_DIRECTION:
            direction = "neutral"
        evidence.append(EvidenceItem(
            fact=e.get("fact", ""),
            source=e.get("source", ""),
            relevance=relevance,
            reliability=reliability,
            direction=direction,
            interpretation=e.get("interpretation", ""),
        ))

    stance = data.get("stance", "neutral")
    if stance not in VALID_STANCES:
        stance = "neutral"

    confidence = data.get("confidence", "low")
    if confidence not in VALID_CONFIDENCE:
        confidence = "low"

    return AgentOutput(
        agent_name=brief.name,
        domain=brief.domain,
        key_finding=data.get("key_finding", ""),
        stance=stance,
        confidence=confidence,
        evidence=evidence,
        key_unknowns=data.get("key_unknowns", []),
        flags_for_committee=data.get("flags_for_committee", []),
        full_reasoning=data.get("full_reasoning", ""),
    )


def run_all_agents(
    briefs: List[AgentBrief],
    stock_data: StockData,
    profile: StockProfile,
    relevance_map: RelevanceMap,
    client: openai.OpenAI,
    config: Config,
    verbose: bool = False,
    article_impacts: list = None,
    maya_reports: list = None,
    sector_news: list = None,
) -> List[AgentOutput]:
    """Run all agents sequentially and return their outputs."""
    outputs: List[AgentOutput] = []
    for brief in briefs:
        if verbose:
            print(f"  Running agent: {brief.name}...")
        output = run_agent(
            brief, stock_data, profile, relevance_map, client, config,
            article_impacts=article_impacts,
            maya_reports=maya_reports,
            sector_news=sector_news,
        )
        if verbose:
            print(f"    Stance: {output.stance} | Confidence: {output.confidence}")
        outputs.append(output)
    return outputs
