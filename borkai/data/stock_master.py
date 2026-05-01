"""
Stock Master Table
==================
Single source of truth for Israeli stock identity.

Schema (tase_stocks.csv):
  ticker          — TASE ticker without .TA suffix (may be empty for small-caps)
  name_en         — English company name
  sector          — sector string (yfinance / manual)
  market_cap_bucket — large / mid / small
  name_he         — canonical Hebrew name (used for Maya searches)
  security_number — TASE ני''ע number (informational)
  short_name      — shorter display name (subset of name_he, optional)
  last_updated    — ISO date of last enrichment

Public API:
  get_master_table()              → StockMasterTable singleton
  StockMasterTable.get_maya_name(ticker)      → Hebrew name for Maya searches
  StockMasterTable.lookup_by_ticker(ticker)   → StockRow | None
  StockMasterTable.lookup_by_name_he(name_he) → StockRow | None
  StockMasterTable.update_and_save(ticker, **updates)  → persist enrichments
  StockMasterTable.add_row(row)               → add new stock at runtime
  StockMasterTable.initial_enrichment()       → fill blanks from securities_mapper
"""
from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass, field, fields
from datetime import date
from typing import Dict, List, Optional

_DIR      = os.path.dirname(__file__)
_CSV_PATH = os.path.join(_DIR, "tase_stocks.csv")


def _log(msg: str) -> None:
    """Print safely, replacing unencodable chars so Windows console never crashes."""
    try:
        print(msg)
    except UnicodeEncodeError:
        safe = msg.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8", errors="replace"
        )
        print(safe)

_FIELDNAMES = [
    "ticker", "name_en", "sector", "market_cap_bucket",
    "name_he", "security_number", "short_name", "last_updated",
]


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class StockRow:
    ticker:            str = ""
    name_en:           str = ""
    sector:            str = ""
    market_cap_bucket: str = ""
    name_he:           str = ""
    security_number:   str = ""
    short_name:        str = ""
    last_updated:      str = ""

    def is_empty(self, col: str) -> bool:
        return not (getattr(self, col, "") or "").strip()


# ── Master table ──────────────────────────────────────────────────────────────

class StockMasterTable:
    """
    In-memory view of tase_stocks.csv with lazy load and auto-save.

    Indexes:
      _by_ticker  — ticker (upper, no .TA) → StockRow
      _by_name_he — name_he (stripped)     → StockRow
      _by_secnum  — security_number        → StockRow
    """

    def __init__(self) -> None:
        self._rows:       List[StockRow] = []
        self._by_ticker:  Dict[str, StockRow] = {}
        self._by_name_he: Dict[str, StockRow] = {}
        self._by_secnum:  Dict[str, StockRow] = {}
        self._loaded = False

    # ── Load / save ───────────────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._load()

    def _load(self) -> None:
        self._rows.clear()
        self._by_ticker.clear()
        self._by_name_he.clear()
        self._by_secnum.clear()

        if not os.path.exists(_CSV_PATH):
            self._loaded = True
            return

        try:
            with open(_CSV_PATH, newline="", encoding="utf-8") as f:
                for raw in csv.DictReader(f):
                    row = StockRow(
                        ticker            = (raw.get("ticker")            or "").strip(),
                        name_en           = (raw.get("name_en")           or "").strip(),
                        sector            = (raw.get("sector")            or "").strip(),
                        market_cap_bucket = (raw.get("market_cap_bucket") or "").strip(),
                        name_he           = (raw.get("name_he")           or "").strip(),
                        security_number   = (raw.get("security_number")   or "").strip(),
                        short_name        = (raw.get("short_name")        or "").strip(),
                        last_updated      = (raw.get("last_updated")      or "").strip(),
                    )
                    self._rows.append(row)
                    self._index(row)
        except Exception as exc:
            print(f"  [StockMaster] Load failed: {exc}")

        self._loaded = True
        print(f"  [StockMaster] Loaded {len(self._rows)} rows from tase_stocks.csv")

    def _index(self, row: StockRow) -> None:
        if row.ticker:
            key = row.ticker.upper().replace(".TA", "")
            if key not in self._by_ticker:
                self._by_ticker[key] = row
        if row.name_he:
            key = row.name_he.strip()
            if key not in self._by_name_he:
                self._by_name_he[key] = row
        if row.security_number:
            if row.security_number not in self._by_secnum:
                self._by_secnum[row.security_number] = row

    def save(self) -> None:
        """Write all rows back to tase_stocks.csv."""
        try:
            with open(_CSV_PATH, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
                writer.writeheader()
                for row in self._rows:
                    writer.writerow({fn: getattr(row, fn, "") for fn in _FIELDNAMES})
        except Exception as exc:
            print(f"  [StockMaster] Save failed: {exc}")

    # ── Lookup ────────────────────────────────────────────────────────────────

    def lookup_by_ticker(self, ticker: str) -> Optional[StockRow]:
        self._ensure_loaded()
        clean = ticker.upper().replace(".TA", "").strip()
        return self._by_ticker.get(clean)

    def lookup_by_name_he(self, name_he: str) -> Optional[StockRow]:
        self._ensure_loaded()
        return self._by_name_he.get(name_he.strip())

    def lookup_by_secnum(self, security_number: str) -> Optional[StockRow]:
        self._ensure_loaded()
        return self._by_secnum.get(security_number.strip())

    def all_rows(self) -> List[StockRow]:
        self._ensure_loaded()
        return list(self._rows)

    # ── Maya name resolution ──────────────────────────────────────────────────

    def get_maya_name(
        self,
        ticker: str,
        name_he_hint: Optional[str] = None,
        security_number: Optional[str] = None,
    ) -> Optional[str]:
        """
        Return the best Hebrew name to use for Maya TASE searches.

        Resolution order:
          1. Lookup by ticker → short_name or name_he from table
          2. Lookup by name_he_hint → name_he from table
          3. Lookup by security_number → name_he from table
          4. securities_mapper fuzzy resolve (words / normalized)
          5. Return name_he_hint as-is (caller's best guess)

        Debug output is always printed.
        """
        self._ensure_loaded()
        ticker_clean = ticker.upper().replace(".TA", "").strip() if ticker else ""

        # 1. By ticker
        row = self._by_ticker.get(ticker_clean) if ticker_clean else None
        if row:
            best = row.short_name or row.name_he
            _log(f"  [StockMaster] {ticker_clean} -> table match: "
                 f"name_he={row.name_he!r} short={row.short_name!r} -> using {best!r}")
            return best or name_he_hint

        # 2. By name_he_hint (exact)
        if name_he_hint:
            row = self._by_name_he.get(name_he_hint.strip())
            if row:
                best = row.short_name or row.name_he
                _log(f"  [StockMaster] name_he exact: {name_he_hint!r} -> {best!r}")
                return best

        # 3. By security_number
        if security_number:
            row = self._by_secnum.get(security_number.strip())
            if row:
                best = row.short_name or row.name_he
                _log(f"  [StockMaster] secnum match: {security_number} -> {best!r}")
                return best

        # 4. securities_mapper fuzzy resolve
        try:
            from .securities_mapper import resolve_maya_name
            entry = resolve_maya_name(name_he_hint, ticker_clean, security_number)
            if entry:
                _log(f"  [StockMaster] mapper fuzzy: {name_he_hint!r} -> {entry.canonical_maya_name!r}")
                return entry.canonical_maya_name
        except Exception as exc:
            _log(f"  [StockMaster] mapper error: {exc}")

        # 5. Fallback — return hint as-is
        _log(f"  [StockMaster] {ticker_clean}: no match -- using hint {name_he_hint!r}")
        return name_he_hint

    # ── Mutation ──────────────────────────────────────────────────────────────

    def update_and_save(self, ticker: str, *, save: bool = True, **updates) -> bool:
        """
        Update fields on an existing row (only fills missing values).
        Writes CSV if any field was changed.

        Returns True if any update was made.
        """
        self._ensure_loaded()
        ticker_clean = ticker.upper().replace(".TA", "").strip()
        row = self._by_ticker.get(ticker_clean)
        if row is None:
            print(f"  [StockMaster] update_and_save: ticker {ticker_clean!r} not in table")
            return False

        changed = False
        for col, val in updates.items():
            if not hasattr(row, col):
                continue
            if val and not getattr(row, col):
                setattr(row, col, str(val).strip())
                changed = True
                _log(f"  [StockMaster] {ticker_clean}.{col} <- {val!r}")

        if changed:
            row.last_updated = str(date.today())
            # Re-index any new identifiers
            self._index(row)
            if save:
                self.save()
        return changed

    def add_row(self, row: StockRow, *, save: bool = True) -> bool:
        """
        Add a new stock row at runtime (called when a new ticker is analysed).
        No-ops if the ticker is already present.
        Returns True if the row was added.
        """
        self._ensure_loaded()
        ticker_clean = row.ticker.upper().replace(".TA", "").strip() if row.ticker else ""
        if ticker_clean and ticker_clean in self._by_ticker:
            print(f"  [StockMaster] add_row: {ticker_clean} already exists, skipping")
            return False

        if not row.last_updated:
            row.last_updated = str(date.today())

        self._rows.append(row)
        self._index(row)
        if save:
            self.save()
        print(f"  [StockMaster] Added new row: ticker={row.ticker!r} name_he={row.name_he!r}")
        return True

    # ── Enrichment ────────────────────────────────────────────────────────────

    def initial_enrichment(self) -> int:
        """
        Fill missing short_name and security_number using securities_mapper.
        Saves the CSV after processing all rows.
        Returns the number of rows updated.
        """
        self._ensure_loaded()
        try:
            from .securities_mapper import resolve_maya_name
        except Exception as exc:
            print(f"  [StockMaster] initial_enrichment: cannot import mapper: {exc}")
            return 0

        updated = 0
        for row in self._rows:
            if row.short_name and row.security_number:
                continue

            entry = resolve_maya_name(
                row.name_he or None,
                row.ticker or None,
                row.security_number or None,
            )
            if not entry:
                continue

            changed = False
            if not row.short_name and entry.canonical_maya_name:
                # Only set short_name when the canonical differs from name_he
                # (it is meaningfully shorter / cleaner)
                cname = entry.canonical_maya_name
                if cname != row.name_he and len(cname) < len(row.name_he or ""):
                    row.short_name = cname
                    changed = True

            if not row.security_number and entry.security_number:
                row.security_number = entry.security_number
                changed = True

            if changed:
                row.last_updated = str(date.today())
                self._index(row)
                updated += 1

        if updated:
            self.save()
        print(f"  [StockMaster] initial_enrichment: {updated} rows updated")
        return updated


# ── Singleton ─────────────────────────────────────────────────────────────────

_MASTER: Optional[StockMasterTable] = None


def get_master_table() -> StockMasterTable:
    """Return the process-wide StockMasterTable singleton."""
    global _MASTER
    if _MASTER is None:
        _MASTER = StockMasterTable()
    return _MASTER


def invalidate_master_cache() -> None:
    """Force next call to reload from disk (call after external CSV edits)."""
    global _MASTER
    _MASTER = None
