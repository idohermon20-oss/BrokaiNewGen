"""
Borkai — Adaptive Institutional-Grade Stock Intelligence

Entry point. Runs a full analysis for a given ticker and time horizon.
Output is always in Hebrew. Sector news is fetched and analyzed automatically.

Usage:
    python main.py ESLT medium il       # Israeli stock (TASE)
    python main.py BEZQ short il
    python main.py TEVA long il
    python main.py AAPL medium          # US stock (English internal, Hebrew output)

Time horizons: short (1-4 weeks) | medium (1-6 months) | long (1-3 years)
Markets:       us (default) | il (Israel / TASE)
"""
import sys
import os
import io
import openai
from datetime import date
from typing import Optional, Callable

from borkai.config import load_config
from borkai.data.fetcher import fetch_stock_data, assess_article_impacts
from borkai.data.sector_news import fetch_sector_news
from borkai.orchestrator.profiler import build_stock_profile
from borkai.orchestrator.relevance_mapper import build_relevance_map
from borkai.orchestrator.agent_designer import design_agent_team
from borkai.orchestrator.sector_analyzer import analyze_sector_news
from borkai.agents.agent_runner import run_all_agents
from borkai.committee.synthesizer import synthesize_agent_outputs
from borkai.committee.committee import run_investment_committee
from borkai.report.report_generator import AnalysisResult, generate_report


def _normalize_ticker(ticker: str, market: str) -> str:
    ticker = ticker.upper()
    if market == "il" and not ticker.endswith(".TA"):
        ticker = ticker + ".TA"
    return ticker


def translate_to_hebrew(report: str, client: openai.OpenAI, config) -> str:
    """
    Translate a Borkai markdown report to Hebrew.
    Splits on top-level section boundaries (## headers / --- dividers) so that
    each LLM call stays well within the token limit, then stitches results back.
    """
    _SYSTEM = (
        "You are a professional financial translator. "
        "Translate the following investment research report chunk from English to Hebrew. "
        "Preserve ALL Markdown formatting exactly (headers, bold, bullet points, blockquotes, tables, links). "
        "Keep ticker symbols, numbers, percentages, URLs, and proper nouns (company names) in their original form. "
        "The translation must read naturally in Hebrew, as if written by a native Hebrew-speaking analyst. "
        "Return only the translated text — no commentary, no preamble."
    )

    # Split into chunks at top-level section boundaries (~4000 chars each)
    _CHUNK_SIZE = 4000

    def _translate_chunk(chunk: str) -> str:
        if not chunk.strip():
            return chunk
        resp = client.chat.completions.create(
            model=config.models.report,
            max_tokens=8192,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": chunk},
            ],
        )
        return resp.choices[0].message.content

    # Split by top-level "## " headers to keep sections together
    import re
    # Find all section-start positions
    parts = re.split(r'(?=\n## )', report)

    chunks: list[str] = []
    current = ""
    for part in parts:
        if len(current) + len(part) <= _CHUNK_SIZE:
            current += part
        else:
            if current:
                chunks.append(current)
            # If a single part is bigger than chunk_size, split it further by paragraphs
            if len(part) > _CHUNK_SIZE:
                paragraphs = part.split("\n\n")
                sub = ""
                for para in paragraphs:
                    if len(sub) + len(para) + 2 <= _CHUNK_SIZE:
                        sub += para + "\n\n"
                    else:
                        if sub:
                            chunks.append(sub)
                        sub = para + "\n\n"
                if sub:
                    chunks.append(sub)
                current = ""
            else:
                current = part
    if current:
        chunks.append(current)

    print(f"  מתרגם {len(chunks)} חלקים...")
    translated_parts = []
    for i, chunk in enumerate(chunks, 1):
        print(f"  חלק {i}/{len(chunks)}...")
        translated_parts.append(_translate_chunk(chunk))

    return "".join(translated_parts)


def analyze(
    ticker: str,
    time_horizon: str,
    market: str = "us",
    save_report: bool = True,
    output_dir: str = ".",
    progress_callback: Optional[Callable[[int, str, str], None]] = None,
) -> tuple:
    """
    Run a full Borkai analysis for a stock.

    progress_callback(stage: int, label: str, detail: str) is called at each stage
    so callers (e.g. Streamlit) can show live progress.

    Returns (report_en: str, report_he: str, result: AnalysisResult).
    Saves only the Hebrew report when save_report=True.
    """
    def _cb(stage: int, label: str, detail: str = ""):
        print(f"[{stage}/8] {label}" + (f"  — {detail}" if detail else ""))
        if progress_callback:
            progress_callback(stage, label, detail)

    time_horizon = time_horizon.lower()
    if time_horizon not in {"short", "medium", "long"}:
        raise ValueError("time_horizon must be 'short', 'medium', or 'long'")

    market = market.lower()
    ticker = _normalize_ticker(ticker, market)

    config = load_config(market=market)
    client = openai.OpenAI(api_key=config.openai_api_key)

    market_label = "TASE (Israel)" if market == "il" else "US"
    print(f"\n{'='*60}")
    print(f"  BORKAI: {ticker}  |  {time_horizon.upper()}  |  {market_label}")
    print(f"{'='*60}\n")

    # Stage 1: Fetch data
    _cb(1, "שליפת נתוני שוק", "")
    stock_data = fetch_stock_data(ticker)
    print(f"      {stock_data.company_name} | {stock_data.sector} | {stock_data.industry}")

    # Stage 1b: Assess per-article impact
    if stock_data.article_contents or stock_data.recent_news:
        print("      Assessing article impacts...")
        try:
            stock_data.article_impacts = assess_article_impacts(
                stock_data.article_contents,
                stock_data.recent_news,
                ticker,
                stock_data.company_name,
                client,
                config,
            )
            print(f"      {len(stock_data.article_impacts)} articles assessed")
        except Exception as e:
            print(f"      Article impact assessment skipped: {e}")

    # Stage 2: Sector news + company Maya reports
    sector_analysis = None
    maya_reports = []
    if config.sector_news_enabled:
        _cb(2, "איסוף חדשות סקטור", stock_data.sector)
        news_items = fetch_sector_news(
            company_name=stock_data.company_name,
            sector=stock_data.sector,
            max_items=config.sector_news_max_items,
        )
        print(f"      {len(news_items)} news items fetched")
        sector_analysis = analyze_sector_news(
            news_items=news_items,
            company_name=stock_data.company_name,
            sector=stock_data.sector,
            ticker=ticker,
            time_horizon=time_horizon,
            market_context=config.market_context,
            client=client,
            config=config,
        )
        print(f"      Sector sentiment: {sector_analysis.market_sentiment}")
    else:
        _cb(2, "דילוג על חדשות סקטור", "(מצב סריקה)")

    # Stage 2b: Fetch company-specific Maya/TASE reports
    try:
        from borkai.data.maya_fetcher import fetch_company_reports, assess_company_report_impacts
        print(f"      Fetching Maya reports for {stock_data.company_name}...")
        maya_reports = fetch_company_reports(stock_data.company_name, ticker, max_items=8)
        if maya_reports:
            maya_reports = assess_company_report_impacts(
                maya_reports, ticker, stock_data.company_name, client, config
            )
            print(f"      {len(maya_reports)} Maya reports found")
    except Exception as e:
        print(f"      Maya reports skipped: {e}")
        maya_reports = []

    # Stage 3: Build stock profile
    _cb(3, "בניית פרופיל מנייה", "")
    profile = build_stock_profile(ticker, time_horizon, stock_data, client, config)
    print(f"      Phase: {profile.phase}")
    _cb(3, "בניית פרופיל מנייה", f"שלב: {profile.phase}")

    # Stage 4: Map relevance
    _cb(4, "מיפוי רלוונטיות", "")
    relevance_map = build_relevance_map(profile, client, config)
    core = relevance_map.core_domains
    print(f"      Core domains: {', '.join(core)}")
    _cb(4, "מיפוי רלוונטיות", f"תחומי ליבה: {', '.join(core[:3])}")

    # Stage 5: Design agent team
    _cb(5, "עיצוב צוות אנליסטים", "")
    agent_briefs = design_agent_team(profile, relevance_map, client, config)
    print(f"      {len(agent_briefs)} analysts:")
    for brief in agent_briefs:
        print(f"        • {brief.name}")
    _cb(5, "עיצוב צוות אנליסטים", f"{len(agent_briefs)} אנליסטים")

    # Stage 6: Run agents
    _cb(6, "הרצת אנליסטים", f"{len(agent_briefs)} אנליסטים פועלים...")
    agent_outputs = run_all_agents(
        agent_briefs, stock_data, profile, relevance_map, client, config, verbose=True,
        article_impacts=stock_data.article_impacts,
        maya_reports=maya_reports,
    )

    # Stage 7: Synthesize
    _cb(7, "סינתזה", "")
    synthesis = synthesize_agent_outputs(agent_outputs, profile, client, config)
    print(f"      Overall lean: {synthesis.overall_lean.upper()}")
    _cb(7, "סינתזה", f"כיוון כללי: {synthesis.overall_lean.upper()}")

    # Stage 8: Investment committee
    _cb(8, "ועדת השקעות", "")
    decision = run_investment_committee(
        agent_outputs, synthesis, profile, relevance_map, client, config
    )
    print(f"      Direction: {decision.direction.upper()}")
    print(f"      Conviction: {decision.conviction.upper()}")
    print(f"      Return Score: {decision.return_score}/100")
    _cb(8, "ועדת השקעות", f"ציון: {decision.return_score}/100 | {decision.invest_recommendation}")

    # Assemble result
    result = AnalysisResult(
        ticker=ticker,
        time_horizon=time_horizon,
        analysis_date=str(date.today()),
        profile=profile,
        relevance_map=relevance_map,
        agent_outputs=agent_outputs,
        synthesis=synthesis,
        decision=decision,
        sector_analysis=sector_analysis,
        article_impacts=stock_data.article_impacts,
        maya_reports=maya_reports,
    )

    # Generate English report
    report_en = generate_report(result)

    # Always translate to Hebrew
    print("\nמתרגם לעברית...")
    report_he = translate_to_hebrew(report_en, client, config)

    # Save — Hebrew only
    saved_path = None
    if save_report:
        os.makedirs(output_dir, exist_ok=True)
        filename_he = os.path.join(
            output_dir,
            f"report_{ticker.replace('.', '_')}_{time_horizon}_{date.today()}_he.md"
        )
        with open(filename_he, "w", encoding="utf-8") as f:
            f.write(report_he)
        print(f"דוח נשמר: {filename_he}")
        saved_path = filename_he

    print(f"\n{'='*60}")
    print(f"  פסיקה: {decision.direction.upper()} | {decision.conviction.upper()} | ציון {decision.return_score}/100")
    print(f"{'='*60}\n")

    # Telegram notification (optional — only fires if TELEGRAM_BOT_TOKEN is set in .env)
    try:
        from borkai.utils.telegram import send_report_summary
        highlights_lines = []
        for line in report_he.split("\n"):
            if line.startswith("- ") and any(e in line for e in ["🟢", "🔴", "⚪"]):
                highlights_lines.append(line)
            if len(highlights_lines) >= 5:
                break
        sent = send_report_summary(
            ticker=ticker,
            company_name=stock_data.company_name,
            verdict=decision.invest_recommendation,
            direction=decision.direction,
            return_score=decision.return_score,
            conviction=decision.conviction,
            horizon=time_horizon,
            highlights="\n".join(highlights_lines),
            report_path=saved_path,
        )
        if sent:
            print("  ✓ Telegram notification sent")
    except Exception:
        pass

    return report_en, report_he, result


def main():
    if len(sys.argv) < 3:
        print("Usage: python main.py <TICKER> <horizon> [market]")
        print("       horizon: short | medium | long")
        print("       market:  us (default) | il")
        print("\nExamples:")
        print("       python main.py ESLT medium il")
        print("       python main.py BEZQ short il")
        sys.exit(1)

    ticker = sys.argv[1]
    horizon = sys.argv[2]
    market = sys.argv[3] if len(sys.argv) > 3 else "us"

    _, report_he, _ = analyze(ticker, horizon, market=market)
    print(report_he)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
