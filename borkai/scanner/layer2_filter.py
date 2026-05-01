"""
Layer 2: Smart Filtering (Light AI)
====================================

Takes top candidates from Layer 1 and applies a fast intelligence pass:

1. Quick DDG news search  — 3-5 headlines per stock, no full content
2. Quick Maya DDG count   — how many recent filings exist
3. GPT-4o-mini batch classification — all candidates in ONE LLM call

Adds 0-5 points to the Layer 1 score based on:
  event_score    (0-2)  Real event detected (contract / earnings / regulatory)
  sentiment_score (0-2) Positive / negative sentiment from headlines
  alignment_score (0-1) Multiple signals (price + volume + news + filings) align

Output: List[Layer2Result] sorted by combined_score descending.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import List, Optional

import openai


VALID_IMPACTS    = {"HIGH", "MEDIUM", "LOW", "NONE"}
VALID_SENTIMENTS = {"bullish", "bearish", "neutral"}
VALID_ALIGNMENTS = {"strong", "moderate", "weak"}
VALID_EVENT_TYPES = {
    "contract", "earnings", "acquisition", "regulatory",
    "dividend", "appointment", "bond", "guidance", "other", "none",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Layer2Result:
    ticker: str
    name: str
    sector: str
    market_cap_bucket: str = ""

    # Scores carried from Layer 1
    layer1_score: int = 0
    layer1_signals: List[str] = field(default_factory=list)

    # Layer 2 intelligence
    recent_headlines: List[str] = field(default_factory=list)
    maya_filing_count: int = 0

    # LLM classification
    event_detected: bool = False
    event_type: str = "none"        # contract/earnings/regulatory/...
    event_impact: str = "NONE"      # HIGH/MEDIUM/LOW/NONE
    sentiment: str = "neutral"      # bullish/bearish/neutral
    alignment: str = "weak"         # strong/moderate/weak (multi-signal)
    llm_reasoning: str = ""

    # Layer 2 component scores
    event_score: int = 0      # 0-2
    sentiment_score: int = 0  # 0-2
    alignment_score: int = 0  # 0-1
    layer2_score: int = 0     # 0-5

    # Combined
    combined_score: int = 0   # layer1_score + layer2_score

    # All signals (layer1 + layer2)
    all_signals: List[str] = field(default_factory=list)

    # Recommendation
    recommendation: str = "WATCH"  # DEEP_ANALYSIS / WATCH / SKIP
    reasoning: str = ""

    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Quick DDG helpers (no content fetching — titles only)
# ---------------------------------------------------------------------------

def _quick_news_headlines(
    ticker: str,
    name: str,
    name_he: Optional[str] = None,
    max_results: int = 5,
) -> List[str]:
    """
    Fetch 3-5 recent news headlines from DuckDuckGo.
    Returns only titles — no full article fetching (fast).
    """
    headlines = []
    seen: set = set()

    try:
        from ddgs import DDGS
        ddgs = DDGS()
        ticker_clean = ticker.replace(".TA", "").replace(".ta", "")
        queries = [f'"{name}" stock news', f'"{ticker_clean}" TASE news']
        if name_he:
            queries.insert(0, f'"{name_he}" בורסה')

        for query in queries:
            if len(headlines) >= max_results:
                break
            try:
                for r in ddgs.news(query, max_results=3):
                    title = (r.get("title") or "").strip()
                    if title and title not in seen:
                        seen.add(title)
                        headlines.append(title)
                        if len(headlines) >= max_results:
                            break
            except Exception:
                continue
    except Exception:
        pass

    return headlines


def _quick_maya_count(
    ticker: str,
    name: str,
    name_he: Optional[str] = None,
    max_results: int = 5,
) -> int:
    """
    Count recent Maya TASE filings via DDG site search.
    Returns number of filing URLs found (0-max_results).
    """
    import re
    _MAYA_RE = re.compile(r'maya\.tase\.co\.il.*/reports/(?:details/)?\d{6,}')

    try:
        from ddgs import DDGS
        ddgs = DDGS()
        ticker_clean = ticker.replace(".TA", "").replace(".ta", "")
        queries = [f'site:maya.tase.co.il "{name}"']
        if name_he:
            queries.insert(0, f'site:maya.tase.co.il "{name_he}"')
        else:
            queries.append(f'site:maya.tase.co.il {ticker_clean}')

        count = 0
        for query in queries:
            try:
                for r in ddgs.text(query, max_results=max_results):
                    href = r.get("href") or r.get("url") or ""
                    if _MAYA_RE.search(href):
                        count += 1
            except Exception:
                continue
            time.sleep(0.3)
    except Exception:
        count = 0

    return count


# ---------------------------------------------------------------------------
# Batch LLM classification
# ---------------------------------------------------------------------------

_LAYER2_SYSTEM = """You are a rapid-fire stock screening analyst.
You receive a list of Israeli stocks with recent news headlines and volume/price activity.
For each stock, quickly determine:
- Is there a real event (contract, earnings, regulatory, acquisition, etc.)?
- What is the event impact: HIGH, MEDIUM, LOW, or NONE?
- What is the overall news sentiment: bullish, bearish, or neutral?
- Do multiple signals align (price move + volume spike + news event)?

Be concise and decisive. Return ONLY valid JSON. No prose outside the JSON."""


def _classify_batch(
    candidates: List[Layer2Result],
    client: openai.OpenAI,
    model: str = "gpt-4o-mini",
) -> List[dict]:
    """
    Classify all candidates in a single LLM call.
    Returns list of classification dicts in same order as candidates.
    """
    # Build the input block
    items = []
    for i, c in enumerate(candidates):
        headlines_text = "\n  ".join(c.recent_headlines) if c.recent_headlines else "(no recent headlines)"
        items.append(
            f"Stock {i} — {c.ticker} ({c.name}, sector: {c.sector})\n"
            f"  Layer1 signals: {', '.join(c.layer1_signals) or 'none'}\n"
            f"  Maya filings found: {c.maya_filing_count}\n"
            f"  Recent headlines:\n  {headlines_text}"
        )

    prompt = (
        "Analyze these Israeli stocks and return a JSON array with one object per stock.\n\n"
        + "\n\n".join(items)
        + "\n\nFor each stock return:\n"
        "{\n"
        '  "event_detected": true/false,\n'
        '  "event_type": "contract|earnings|acquisition|regulatory|dividend|appointment|bond|guidance|other|none",\n'
        '  "event_impact": "HIGH|MEDIUM|LOW|NONE",\n'
        '  "sentiment": "bullish|bearish|neutral",\n'
        '  "alignment": "strong|moderate|weak",\n'
        '  "reasoning": "<one sentence: why this stock is interesting or not>"\n'
        "}\n\n"
        f"Return a JSON array of exactly {len(candidates)} objects in the same order as the input stocks.\n"
        "Be decisive — do not hedge. If there is no event, say so directly."
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _LAYER2_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=200 * len(candidates),
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        raw = json.loads(resp.choices[0].message.content)

        # The model might wrap in {"results": [...]} or return array directly
        if isinstance(raw, list):
            classifications = raw
        elif isinstance(raw, dict):
            # Try common wrapper keys
            for key in ("results", "stocks", "classifications", "items", "data"):
                if key in raw and isinstance(raw[key], list):
                    classifications = raw[key]
                    break
            else:
                # Fallback: find the first list value
                classifications = next(
                    (v for v in raw.values() if isinstance(v, list)), []
                )
        else:
            classifications = []

        # Pad or trim to match candidate count
        while len(classifications) < len(candidates):
            classifications.append({})
        return classifications[:len(candidates)]

    except Exception as e:
        print(f"[L2] LLM batch classification failed: {e}")
        return [{} for _ in candidates]


# ---------------------------------------------------------------------------
# Layer 2 scoring
# ---------------------------------------------------------------------------

def _compute_layer2_score(result: Layer2Result) -> None:
    """Compute event_score, sentiment_score, alignment_score from LLM output."""
    # Event score
    if result.event_impact == "HIGH":
        result.event_score = 2
    elif result.event_impact == "MEDIUM":
        result.event_score = 1
    else:
        result.event_score = 0

    # Sentiment score
    if result.sentiment == "bullish":
        result.sentiment_score = 2
    elif result.sentiment == "bearish":
        # Bearish is still interesting for short sellers, but flag it
        result.sentiment_score = 1
    else:
        result.sentiment_score = 0

    # Alignment score
    if result.alignment == "strong":
        result.alignment_score = 1
    else:
        result.alignment_score = 0

    result.layer2_score = result.event_score + result.sentiment_score + result.alignment_score
    result.combined_score = result.layer1_score + result.layer2_score


def _build_recommendation(result: Layer2Result) -> None:
    """Assign DEEP_ANALYSIS / WATCH / SKIP based on combined score."""
    combined = result.combined_score
    event_high = result.event_impact == "HIGH"

    if combined >= 7 or (combined >= 5 and event_high):
        result.recommendation = "DEEP_ANALYSIS"
    elif combined >= 4:
        result.recommendation = "WATCH"
    else:
        result.recommendation = "SKIP"

    # Build all_signals
    sigs = list(result.layer1_signals)
    if result.event_detected and result.event_type != "none":
        sigs.append(f"{result.event_type} event [{result.event_impact} impact]")
    if result.maya_filing_count > 0:
        sigs.append(f"{result.maya_filing_count} Maya filing(s) found")
    if result.sentiment != "neutral":
        sigs.append(f"news sentiment: {result.sentiment}")
    result.all_signals = sigs


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def run_layer2(
    layer1_results: list,
    client: openai.OpenAI,
    top_n: int = 30,
    model: str = "gpt-4o-mini",
    name_he_map: Optional[dict] = None,
    verbose: bool = True,
) -> List[Layer2Result]:
    """
    Run Layer 2 filtering on the top candidates from Layer 1.

    Args:
        layer1_results: output from run_layer1(), sorted best-first
        client:         OpenAI client
        top_n:          how many top Layer 1 stocks to process
        model:          LLM model for classification
        name_he_map:    ticker -> Hebrew name, for better Maya/news searches
        verbose:        print progress

    Returns:
        List[Layer2Result] sorted by combined_score descending.
    """
    from .layer1_fast_scan import Layer1Result

    # Take top N from Layer 1 (filter out errors)
    valid_l1 = [r for r in layer1_results if r.error is None][:top_n]

    if not valid_l1:
        if verbose:
            print("[L2] No valid Layer 1 results to process.")
        return []

    if verbose:
        print(f"[L2] Processing top {len(valid_l1)} candidates from Layer 1...")

    name_he_map = name_he_map or {}

    # ── Step 1: Fetch headlines and Maya count for each candidate ──────────
    candidates: List[Layer2Result] = []
    for i, r1 in enumerate(valid_l1, 1):
        if verbose:
            print(f"  [L2] {i}/{len(valid_l1)} {r1.ticker} — fetching headlines...")

        name_he = name_he_map.get(r1.ticker.replace(".TA", "").upper())

        c = Layer2Result(
            ticker=r1.ticker,
            name=r1.name,
            sector=r1.sector,
            market_cap_bucket=r1.market_cap_bucket,
            layer1_score=r1.total_score,
            layer1_signals=list(r1.signals),
        )

        # Quick DDG news (3-5 titles only)
        try:
            c.recent_headlines = _quick_news_headlines(
                r1.ticker, r1.name, name_he, max_results=5
            )
        except Exception as e:
            c.recent_headlines = []

        # Quick Maya filing count
        try:
            c.maya_filing_count = _quick_maya_count(
                r1.ticker, r1.name, name_he, max_results=5
            )
        except Exception:
            c.maya_filing_count = 0

        candidates.append(c)
        time.sleep(0.3)  # polite DDG rate limiting

    # ── Step 2: Batch LLM classification (single API call) ─────────────────
    if verbose:
        print(f"[L2] Running batch LLM classification ({len(candidates)} stocks)...")

    classifications = _classify_batch(candidates, client, model=model)

    # ── Step 3: Apply classifications and compute scores ───────────────────
    for candidate, clf in zip(candidates, classifications):
        event_type = (clf.get("event_type") or "none").lower()
        if event_type not in VALID_EVENT_TYPES:
            event_type = "other"

        event_impact = (clf.get("event_impact") or "NONE").upper()
        if event_impact not in VALID_IMPACTS:
            event_impact = "NONE"

        sentiment = (clf.get("sentiment") or "neutral").lower()
        if sentiment not in VALID_SENTIMENTS:
            sentiment = "neutral"

        alignment = (clf.get("alignment") or "weak").lower()
        if alignment not in VALID_ALIGNMENTS:
            alignment = "weak"

        candidate.event_detected = bool(clf.get("event_detected", False))
        candidate.event_type = event_type
        candidate.event_impact = event_impact
        candidate.sentiment = sentiment
        candidate.alignment = alignment
        candidate.llm_reasoning = (clf.get("reasoning") or "").strip()

        _compute_layer2_score(candidate)
        _build_recommendation(candidate)

    # ── Step 4: Sort by combined score ─────────────────────────────────────
    candidates.sort(key=lambda c: c.combined_score, reverse=True)

    if verbose:
        deep = sum(1 for c in candidates if c.recommendation == "DEEP_ANALYSIS")
        watch = sum(1 for c in candidates if c.recommendation == "WATCH")
        skip = sum(1 for c in candidates if c.recommendation == "SKIP")
        print(f"[L2] Done: {deep} DEEP_ANALYSIS, {watch} WATCH, {skip} SKIP")

    return candidates
