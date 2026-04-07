"""
Core data structures shared across the agent layer.
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class AgentBrief:
    """
    Defines a single expert agent's assignment.
    Created by the orchestrator's agent_designer.
    """
    name: str          # e.g. "Supply Chain Risk Analyst"
    domain: str        # e.g. "supply_chain"
    scope: str         # Detailed description of what to cover
    key_question: str  # The single most important question to answer
    out_of_scope: str  # Explicit boundaries — what NOT to analyze


@dataclass
class EvidenceItem:
    """
    A single piece of evidence evaluated by an agent.
    Keeps facts, interpretations, and uncertainty clearly separated.
    """
    fact: str            # The raw, sourced observation
    source: str          # Where it came from (e.g. "yfinance financials", "news headline")
    relevance: str       # high | medium | low
    reliability: str     # high | medium | low
    direction: str       # bullish | bearish | neutral
    interpretation: str  # What this means for the thesis


@dataclass
class AgentOutput:
    """
    Structured output from a single expert agent.
    This is the unit of information passed to the committee.
    """
    agent_name: str
    domain: str
    key_finding: str           # One-paragraph executive summary
    stance: str                # bullish | bearish | neutral | mixed
    confidence: str            # low | moderate | high
    evidence: List[EvidenceItem] = field(default_factory=list)
    key_unknowns: List[str] = field(default_factory=list)
    flags_for_committee: List[str] = field(default_factory=list)
    full_reasoning: str = ""   # Full analytical narrative
