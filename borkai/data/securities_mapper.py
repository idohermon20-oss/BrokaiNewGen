"""
TASE Securities Mapper
======================
Provides canonical Hebrew name resolution for Maya TASE filings lookups.

Data sources (tried in order):
  1. StockList.xlsx  — user's curated TASE stock list (project root)
  2. tase_stocks.csv — enriched master table (borkai/data/, name_he + security_number cols)

Both sources have the same 3-column structure:
  שם / name_he   — Hebrew company/security name (canonical Maya search name for stocks)
  מס' ני''ע      — TASE security number (informational; ≠ Maya companyId)
  type           — מניות (stocks) — only stock entries are indexed

The canonical Maya search name is the exact Hebrew name from the source file.
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

_DIR = os.path.dirname(__file__)
# Primary source: user's curated list at project root
_XLSX_PATH = os.path.normpath(os.path.join(_DIR, "..", "..", "StockList.xlsx"))
# Fallback: master CSV (has name_he + security_number columns)
_CSV_PATH  = os.path.join(_DIR, "tase_stocks.csv")

# ── Normalization ─────────────────────────────────────────────────────────────

_SUFFIX_RE = re.compile(
    r"\s*[\(\[]?"
    r"(?:בע[\"'\u05f4\u05f3]מ|בעמ|בע\.מ|ltd\.?|inc\.?|corp\.?|plc\.?)"
    r"[\)\]]?\s*$",
    re.IGNORECASE,
)
_QUOTE_NORM = re.compile(r'["\'\u05f4\u05f3]')
_MULTI_SPACE = re.compile(r"\s+")


def _normalize(name: str) -> str:
    if not name:
        return ""
    n = _SUFFIX_RE.sub("", name.strip())
    n = _QUOTE_NORM.sub("", n)
    return _MULTI_SPACE.sub(" ", n).strip()


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class SecuritiesEntry:
    name_he: str
    security_number: str
    security_type: str
    canonical_maya_name: str   # = name_he  (exact name to use for Maya searches)


# ── Lazy indexes ──────────────────────────────────────────────────────────────

_IndexType = Tuple[
    Dict[str, SecuritiesEntry],   # by_exact   (stripped name → entry)
    Dict[str, SecuritiesEntry],   # by_norm    (normalized  → entry)
    Dict[str, SecuritiesEntry],   # by_secnum  (security #  → entry)
    List[SecuritiesEntry],        # all_stocks
]
_INDEX: Optional[_IndexType] = None


def _load_from_xlsx() -> List[tuple]:
    """Load (name_he, security_number) pairs from StockList.xlsx."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(_XLSX_PATH)
        ws = wb.active
        entries = []
        for row in ws.iter_rows(values_only=True):
            name_he = (row[0] or "").strip()
            sec_num = str(row[1]).strip() if row[1] is not None else ""
            if name_he and sec_num:
                entries.append((name_he, sec_num, "מניות"))
        return entries
    except Exception as exc:
        print(f"  [SecuritiesMapper] XLSX load failed ({exc}), trying CSV")
        return []


def _load_from_csv() -> List[tuple]:
    """Load (name_he, security_number) pairs from tase_stocks.csv."""
    entries = []
    if not os.path.exists(_CSV_PATH):
        return entries
    try:
        with open(_CSV_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name_he = (row.get("name_he") or "").strip()
                sec_num = (row.get("security_number") or "").strip()
                if name_he:
                    entries.append((name_he, sec_num, "מניות"))
    except Exception as exc:
        print(f"  [SecuritiesMapper] CSV load failed: {exc}")
    return entries


def _load_index() -> _IndexType:
    global _INDEX
    if _INDEX is not None:
        return _INDEX

    by_exact:  Dict[str, SecuritiesEntry] = {}
    by_norm:   Dict[str, SecuritiesEntry] = {}
    by_secnum: Dict[str, SecuritiesEntry] = {}
    all_stocks: List[SecuritiesEntry] = []

    # Try XLSX first, then CSV
    raw = _load_from_xlsx()
    source = "StockList.xlsx"
    if not raw:
        raw = _load_from_csv()
        source = "tase_stocks.csv"

    for name_he, sec_num, sec_type in raw:
        entry = SecuritiesEntry(
            name_he=name_he,
            security_number=sec_num,
            security_type=sec_type,
            canonical_maya_name=name_he,
        )
        all_stocks.append(entry)
        if sec_num and sec_num not in by_secnum:
            by_secnum[sec_num] = entry
        exact_key = name_he.strip()
        if exact_key not in by_exact:
            by_exact[exact_key] = entry
        norm_key = _normalize(name_he)
        if norm_key and norm_key not in by_norm:
            by_norm[norm_key] = entry

    print(f"  [SecuritiesMapper] Loaded {len(all_stocks)} entries from {source}")
    _INDEX = (by_exact, by_norm, by_secnum, all_stocks)
    return _INDEX


# ── Word-level matching helpers ───────────────────────────────────────────────

def _word_match(csv_word: str, query_word: str) -> bool:
    if csv_word == query_word:
        return True
    if len(query_word) > 1 and query_word[0] == "ה" and query_word[1:] == csv_word:
        return True
    return False


def _all_entry_words_in_query(entry_name: str, query_name: str) -> bool:
    entry_words = _normalize(entry_name).split()
    query_words = _normalize(query_name).split()
    if not entry_words or not query_words:
        return False
    for ew in entry_words:
        if len(ew) < 2:
            continue
        if not any(_word_match(ew, qw) for qw in query_words):
            return False
    return any(len(ew) >= 3 for ew in entry_words)


# ── Public API ────────────────────────────────────────────────────────────────

def resolve_maya_name(
    name_he: Optional[str],
    ticker_clean: Optional[str] = None,
    security_number: Optional[str] = None,
) -> Optional[SecuritiesEntry]:
    """
    Resolve the canonical Maya search name from the TASE securities data.

    Matching strategy:
      1. Security-number exact match
      2. Exact name match
      3. Normalized name match  (strips legal suffixes, geresh/quotes)
      4. Word-phrase containment ("בנק הפועלים" → "פועלים", "נייס מערכות" → "נייס")

    Returns None when no confident match found.
    """
    by_exact, by_norm, by_secnum, all_stocks = _load_index()

    if not all_stocks:
        return None

    # 1. Security-number
    if security_number:
        entry = by_secnum.get(security_number.strip())
        if entry:
            return entry

    if not name_he:
        return None

    # 2. Exact
    entry = by_exact.get(name_he.strip())
    if entry:
        return entry

    # 3. Normalized
    norm_input = _normalize(name_he)
    if norm_input:
        entry = by_norm.get(norm_input)
        if entry:
            return entry

    # 4. Word-phrase containment (entry words ⊆ query words)
    query_words = [w for w in norm_input.split() if len(w) >= 2]
    best: Optional[SecuritiesEntry] = None
    best_score = 0
    for entry in all_stocks:
        entry_words = [w for w in _normalize(entry.name_he).split() if len(w) >= 2]
        if len(entry_words) > len(query_words):
            continue
        if not _all_entry_words_in_query(entry.name_he, name_he):
            continue
        score = sum(len(w) for w in entry_words if len(w) >= 3)
        if score > best_score:
            best_score = score
            best = entry

    if best and best_score >= 3:
        return best

    return None


def invalidate_cache() -> None:
    """Force next call to reload the index (call after tase_stocks.csv is updated)."""
    global _INDEX
    _INDEX = None
