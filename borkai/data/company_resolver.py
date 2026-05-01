"""
Company Identity Resolver
=========================

Turns any stock query (ticker, English name, Hebrew name, ISIN, partial name)
into a canonical CompanyIdentity that carries all known stable identifiers.

The resolver is IDENTIFIER-FIRST: it prefers precise stable keys (ticker, Maya
companyId) over free-text name matching, so downstream lookups are reliable even
when a company's name appears differently in English vs Hebrew sources.

Resolution chain (first match wins, confidence stated explicitly):

  1. csv:ticker_exact     — exact ticker in tase_stocks.csv           → 1.00
  2. csv:he_exact         — exact Hebrew name in tase_stocks.csv      → 1.00
  3. csv:en_exact         — exact English name (case-insensitive)      → 0.95
  4. csv:ticker_partial   — query is a prefix of a ticker or vice-versa→ 0.80
  5. csv:en_partial       — query appears anywhere in English name     → 0.75
  6. csv:he_partial       — query appears anywhere in Hebrew name      → 0.75
  7. ids_json:he_exact    — exact Hebrew name in maya_company_ids.json → 0.90
  8. unresolved           — keeps whatever fragments were found        → 0.30

Usage
-----
    from borkai.data.company_resolver import resolve_company

    identity = resolve_company("Elbit Systems")
    # or resolve_company("ESLT")
    # or resolve_company("אלביט מערכות")

    print(identity.maya_id)        # 1040
    print(identity.name_he)        # "אלביט מערכות"
    print(identity.resolution_path)# "csv:ticker_exact"
    print(identity.news_variants)  # ["Elbit Systems", "ESLT", "אלביט מערכות"]
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_DIR       = os.path.dirname(__file__)
_TASE_CSV  = os.path.join(_DIR, "tase_stocks.csv")
_IDS_JSON  = os.path.join(_DIR, "maya_company_ids.json")


# ── Canonical identity ────────────────────────────────────────────────────────

@dataclass
class CompanyIdentity:
    """
    All known stable identifiers for a TASE-listed company.

    Populated by resolve_company(); individual fields may be None when unknown.
    """
    # Core identifiers
    ticker:   Optional[str] = None   # clean ticker without .TA suffix ("ESLT")
    name_en:  Optional[str] = None   # English name ("Elbit Systems")
    name_he:  Optional[str] = None   # Hebrew name ("אלביט מערכות")
    maya_id:  Optional[int] = None   # Maya internal companyId (1040)
    sector:   Optional[str] = None   # Sector string from CSV

    # Resolution metadata
    confidence:      float = 0.0     # 0.0 – 1.0
    resolution_path: str  = "unresolved"
    # Human-readable explanation of how the identity was resolved
    resolution_note: str  = ""

    # ── Derived helpers ───────────────────────────────────────────────────────

    @property
    def display_name(self) -> str:
        """Best human-readable name for logging/display."""
        return self.name_en or self.name_he or self.ticker or "Unknown"

    @property
    def maya_search_term(self) -> str:
        """
        Best search term for Maya / TASE disclosure retrieval.
        Hebrew name is preferred because Maya indexes Hebrew names natively.
        Falls back to English name, then ticker.
        """
        return self.name_he or self.name_en or self.ticker or ""

    @property
    def news_variants(self) -> List[str]:
        """
        Ordered list of query variants for web / news / DDG search.
        Using multiple variants maximises recall across Hebrew and English sources.

        Order: English name first (most broadly indexed), then ticker, then Hebrew.
        """
        seen:     set  = set()
        variants: List[str] = []

        def _add(v: Optional[str]) -> None:
            if v and v.strip() and v.strip() not in seen:
                seen.add(v.strip())
                variants.append(v.strip())

        _add(self.name_en)
        if self.ticker:
            _add(self.ticker.replace(".TA", "").strip())
        _add(self.name_he)

        return variants

    @property
    def is_resolved(self) -> bool:
        return self.confidence >= 0.7

    def summary(self) -> str:
        """One-line debug summary."""
        parts = [
            f"ticker={self.ticker or '?'}",
            f"name_en={self.name_en or '?'}",
            f"name_he={self.name_he or '?'}",
            f"maya_id={self.maya_id or '?'}",
            f"confidence={self.confidence:.2f}",
            f"path={self.resolution_path}",
        ]
        if self.resolution_note:
            parts.append(f"note={self.resolution_note!r}")
        return "CompanyIdentity(" + ", ".join(parts) + ")"


# ── CSV / JSON cache ──────────────────────────────────────────────────────────

# Loaded once per process
_CSV_ROWS:  Optional[List[Dict[str, str]]] = None
_IDS_MAP:   Optional[Dict[str, int]]       = None  # name_he → maya_id


def _load_csv() -> List[Dict[str, str]]:
    global _CSV_ROWS
    if _CSV_ROWS is None:
        rows: List[Dict[str, str]] = []
        try:
            with open(_TASE_CSV, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        except Exception:
            pass
        _CSV_ROWS = rows
    return _CSV_ROWS


def _load_ids() -> Dict[str, int]:
    global _IDS_MAP
    if _IDS_MAP is None:
        mapping: Dict[str, int] = {}
        try:
            with open(_IDS_JSON, encoding="utf-8") as f:
                raw = json.load(f)
            for k, v in raw.items():
                if k != "comment" and isinstance(v, int):
                    mapping[k] = v
        except Exception:
            pass
        _IDS_MAP = mapping
    return _IDS_MAP


def _row_to_identity(row: Dict[str, str], path: str, confidence: float, note: str = "") -> CompanyIdentity:
    """Build a CompanyIdentity from a tase_stocks.csv row."""
    ticker  = row.get("ticker", "").strip().upper().replace(".TA", "")
    name_en = row.get("name", "").strip() or None
    name_he = row.get("name_he", "").strip() or None
    sector  = row.get("sector", "").strip() or None

    # Supplement with Maya ID from JSON
    maya_id = None
    ids = _load_ids()
    if name_he and name_he in ids:
        maya_id = ids[name_he]
    if maya_id is None and name_he:
        # Try partial match in IDs map
        for k, v in ids.items():
            if name_he in k or k in name_he:
                maya_id = v
                break

    return CompanyIdentity(
        ticker=ticker or None,
        name_en=name_en,
        name_he=name_he,
        maya_id=maya_id,
        sector=sector,
        confidence=confidence,
        resolution_path=path,
        resolution_note=note,
    )


# ── Resolution strategies ─────────────────────────────────────────────────────

def _try_csv(query: str) -> Optional[CompanyIdentity]:
    """
    Try all CSV lookup strategies in confidence order.
    Returns the first (best) match or None.
    """
    rows    = _load_csv()
    q       = query.strip()
    q_upper = q.upper().replace(".TA", "")
    q_lower = q.lower()

    # 1. Exact ticker
    for row in rows:
        if row.get("ticker", "").strip().upper() == q_upper:
            return _row_to_identity(row, "csv:ticker_exact", 1.0,
                                    f"query {q!r} matched ticker exactly")

    # 2. Exact Hebrew name
    for row in rows:
        if row.get("name_he", "").strip() == q:
            return _row_to_identity(row, "csv:he_exact", 1.0,
                                    f"query {q!r} matched Hebrew name exactly")

    # 3. Exact English name (case-insensitive)
    for row in rows:
        if row.get("name", "").strip().lower() == q_lower:
            return _row_to_identity(row, "csv:en_exact", 0.95,
                                    f"query {q!r} matched English name (case-insensitive)")

    # 4. Ticker prefix/contains
    for row in rows:
        t = row.get("ticker", "").strip().upper()
        if q_upper and (t.startswith(q_upper) or q_upper.startswith(t)):
            return _row_to_identity(row, "csv:ticker_partial", 0.80,
                                    f"query {q!r} ~ ticker {t!r} (prefix match)")

    # 5. English name contains query (or vice-versa)
    matches_en: List[Tuple[float, Dict[str, str]]] = []
    for row in rows:
        en = row.get("name", "").strip().lower()
        if q_lower and (q_lower in en or en in q_lower):
            # Longer overlap = higher confidence
            overlap = len(set(q_lower.split()) & set(en.split()))
            score   = 0.75 + (0.05 * overlap)
            matches_en.append((score, row))
    if matches_en:
        best_score, best_row = max(matches_en, key=lambda x: x[0])
        return _row_to_identity(best_row, "csv:en_partial", min(best_score, 0.85),
                                f"query {q!r} found inside English name {best_row.get('name')!r}")

    # 6. Hebrew name contains query
    if q:
        for row in rows:
            he = row.get("name_he", "").strip()
            if he and (q in he or he in q):
                return _row_to_identity(row, "csv:he_partial", 0.75,
                                        f"query {q!r} found inside Hebrew name {he!r}")

    return None


def _try_ids_json(query: str) -> Optional[CompanyIdentity]:
    """Check maya_company_ids.json for an exact Hebrew name match."""
    ids = _load_ids()
    q   = query.strip()
    if q in ids:
        return CompanyIdentity(
            name_he=q,
            maya_id=ids[q],
            confidence=0.90,
            resolution_path="ids_json:he_exact",
            resolution_note=f"Hebrew name {q!r} matched in maya_company_ids.json (no CSV row)",
        )
    return None


def _build_partial(query: str) -> CompanyIdentity:
    """
    Build an unresolved identity that still preserves whatever we know from
    the raw query (e.g. if it looks like a ticker, store it as ticker).
    """
    q_upper = query.strip().upper().replace(".TA", "")
    # Treat short all-caps strings as a ticker guess
    looks_like_ticker = q_upper.isalpha() and len(q_upper) <= 6
    return CompanyIdentity(
        ticker=q_upper if looks_like_ticker else None,
        name_en=None if looks_like_ticker else query.strip(),
        confidence=0.30,
        resolution_path="unresolved",
        resolution_note=f"Could not match {query!r} in any lookup table",
    )


# ── Public API ────────────────────────────────────────────────────────────────

def resolve_company(query: str) -> CompanyIdentity:
    """
    Resolve any stock query into a canonical CompanyIdentity.

    The query can be any of:
      - TASE ticker ("ESLT", "ESLT.TA")
      - English company name ("Elbit Systems", "Elbit")
      - Hebrew company name ("אלביט מערכות")
      - Partial name ("Elbit", "הפועלים")

    Returns a CompanyIdentity.  Check .confidence and .resolution_path to
    understand how the identity was resolved.  Always returns *something* —
    never raises.
    """
    if not query or not query.strip():
        return CompanyIdentity(resolution_path="empty_query", resolution_note="Empty query")

    # Strategy 1 + 2 + 3 + 4 + 5 + 6: CSV lookup (most reliable)
    identity = _try_csv(query)
    if identity:
        return identity

    # Strategy 7: IDs JSON (Hebrew exact, no CSV match)
    identity = _try_ids_json(query)
    if identity:
        return identity

    # Strategy 8: unresolved
    return _build_partial(query)


def resolve_from_ticker_and_name(ticker: str, name_en: str) -> CompanyIdentity:
    """
    Convenience wrapper for callers that already have ticker + English name
    (e.g. from yfinance).  Attempts CSV lookup first, then builds identity
    from provided data.
    """
    # Try by ticker first
    identity = resolve_company(ticker)
    if identity.is_resolved:
        # Supplement English name from yfinance if CSV is missing it
        if not identity.name_en and name_en:
            identity.name_en = name_en
        return identity

    # Try by English name
    identity = resolve_company(name_en)
    if identity.is_resolved:
        return identity

    # Build from what we have
    ticker_clean = ticker.upper().replace(".TA", "").strip()
    ids = _load_ids()
    return CompanyIdentity(
        ticker=ticker_clean or None,
        name_en=name_en or None,
        confidence=0.40,
        resolution_path="provided:ticker+name",
        resolution_note=f"Used caller-provided ticker={ticker!r} name={name_en!r}",
    )
