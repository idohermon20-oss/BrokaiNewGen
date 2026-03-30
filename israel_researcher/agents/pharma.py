"""
PharmaAgent — covers Israeli pharma, biotech, and specialty chemicals.

Domain expertise:
  - TEVA: generic drug giant — patent cliffs, generic competition, opioid settlement
  - ICL: specialty chemicals/potash — follow fertilizer prices (MOS proxy)
  - KMDA: plasma-derived therapeutics — niche BLA/IND regulatory pipeline
  - CGEN/EVGN: clinical-stage biotech — binary catalyst risk (milestone or partnership)
  - BRND (Brainsway): FDA-cleared deep TMS — regulatory approvals, new indications
  - ITRN (Ituran): fleet safety / location technology — not pharma but dual-listed
  - PRGO (Perrigo): OTC pharma / consumer health — dual-listed
"""

from __future__ import annotations

from ..config import SECTOR_TICKERS
from ..models import Signal
from .base import SectorAgent


class PharmaAgent(SectorAgent):
    sector_name = "PharmaBiotech"
    tickers     = SECTOR_TICKERS["PharmaBiotech"]  # type: ignore[assignment]

    @property
    def _sector_domain(self) -> str:
        return (
            "SECTOR: Israeli Pharmaceuticals, Biotech, and Life Sciences.\n\n"
            "KEY FACTORS:\n"
            "- TEVA (dual-listed NYSE+TASE): world's largest generic drug maker. "
            "Watch generic pipeline approvals, patent cliff management, biosimilar launches, "
            "and litigation settlements. US ADR overnight move = TASE next-day predictor.\n"
            "- ICL Group (dual-listed NYSE+TASE): specialty chemicals, potash, phosphate. "
            "Follow fertilizer prices (MOS/CF proxy) and specialty minerals demand. "
            "Shekel move = revenue impact (exports in USD).\n"
            "- KMDA (Kamada, dual-listed Nasdaq+TASE): plasma-derived therapeutics. "
            "Small-cap, niche. BLA/NDA regulatory approvals or BARDA contracts = top catalyst.\n"
            "- CGEN (Compugen): clinical-stage drug discovery. Partnership/licensing deal = "
            "binary catalyst with outsized price impact. Low volume = illiquid.\n"
            "- EVGN (Evogene): ag-biotech. Product commercialization milestone = catalyst.\n"
            "- BRND (Brainsway, dual-listed Nasdaq+TASE): FDA-cleared deep TMS devices. "
            "New indication approvals (PTSD, OCD, addiction) = strong catalysts. "
            "Hospital system adoption data matters — clinical partnership = positive signal.\n"
            "- ITRN (Ituran Location, dual-listed Nasdaq+TASE): fleet management and stolen-vehicle "
            "recovery. Not pure pharma — evaluate on contract wins, subscriber growth, and emerging "
            "markets expansion (Latin America is key revenue driver).\n"
            "- PRGO (Perrigo, dual-listed Nasdaq+TASE): OTC consumer health. "
            "Regulatory divestitures and pipeline FDA decisions = key catalysts.\n"
            "- US Biotech index (XBI/IBB): sentiment leading indicator for the entire sector.\n\n"
            "SCORING ADJUSTMENTS:\n"
            "+ XBI up >3%: apply +8 to KMDA, CGEN, EVGN, BRND\n"
            "+ TEVA US ADR overnight move: EXTREME priority for TEVA.TA next day\n"
            "+ Maya regulatory_approval filing: +15 (highest quality catalyst for any biotech)\n"
            "+ MOS (Mosaic) up >3%: apply +8 to ICL (potash correlation)\n"
            "+ Partnership/licensing deal for CGEN/EVGN/BRND: +12 (transforms valuation)\n"
            "+ ITRN new regional contract (LatAm/Africa): +8 (subscriber base expansion)\n"
            "- Small-cap biotech with only technical signal: max score 50 (binary risk)\n"
            "- Generic drug competition news for TEVA: -8\n"
            "- PRGO regulatory recall or FDA warning letter: -15"
        )

    def get_sector_signals(self) -> list[Signal]:
        signals: list[Signal] = []

        # XBI: US biotech ETF — primary sentiment indicator
        signals.extend(self._peer_move_signal(
            peer_ticker    = "XBI",
            peer_label     = "US Biotech ETF (XBI)",
            threshold_pct  = 3.0,
            target_tickers = self.tickers,
            signal_type    = "sector_peer_move",
            direction_text = "Israeli pharma/biotech sector sympathy",
        ))

        # IBB: broader iShares biotech (more weight on large-cap like TEVA)
        signals.extend(self._peer_move_signal(
            peer_ticker    = "IBB",
            peer_label     = "iShares Biotech (IBB)",
            threshold_pct  = 2.5,
            target_tickers = ["TEVA.TA", "KMDA.TA"],
            signal_type    = "sector_peer_move",
            direction_text = "Global pharma sentiment shift",
        ))

        # MOS (Mosaic): potash/fertilizer price proxy for ICL
        signals.extend(self._peer_move_signal(
            peer_ticker    = "MOS",
            peer_label     = "Mosaic (MOS) — potash proxy",
            threshold_pct  = 3.0,
            target_tickers = ["ICL.TA"],
            signal_type    = "sector_peer_move",
            direction_text = "Potash/fertilizer price tailwind for ICL",
        ))

        # Shekel move: these all report in USD — weaker shekel boosts ILS revenue
        signals.extend(self._peer_move_signal(
            peer_ticker    = "ILS=X",
            peer_label     = "USD/ILS (shekel weakening)",
            threshold_pct  = 1.5,
            target_tickers = ["TEVA.TA", "ICL.TA", "KMDA.TA", "BRND.TA", "CGEN.TA", "EVGN.TA"],
            signal_type    = "shekel_move",
            direction_text = "USD-denominated pharma/biotech revenue tailwind",
        ))

        return signals
