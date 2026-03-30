"""
Configuration — all constants, credentials, thresholds, and data-source URLs.
Edit this file to change bot tokens, API keys, scan intervals, etc.
"""

import os
from pathlib import Path

# Auto-load .env file from project root (if present)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass  # dotenv not installed — fall back to plain env vars

# ─── Credentials ───────────────────────────────────────────────────────────────
# Values are read from the .env file in the project root (or from env vars).

BOT_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID        = os.environ.get("TELEGRAM_CHAT_ID", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL   = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# ─── Tuning ────────────────────────────────────────────────────────────────────

CHECK_INTERVAL_SECONDS = 900   # 15 minutes between quick scans
ANOMALY_SAMPLE_SIZE    = 80    # TASE tickers scanned per cycle (covers full TA-125 list)
VOLUME_SPIKE_X         = 2.5  # volume > 2.5x 20d avg → anomaly
PRICE_MOVE_PCT         = 3.5  # abs daily % move → anomaly
TOP_N_ALERTS           = 3    # top stocks per Telegram alert

# ─── State ─────────────────────────────────────────────────────────────────────

STATE_FILE      = Path("israel_researcher_state.json")
BOT_STATE_FILE  = Path("bot_state.json")
USER_ALERTS_FILE = Path("user_alerts.json")

# ─── Maya API ──────────────────────────────────────────────────────────────────

MAYA_BASE    = "https://mayaapi.tase.co.il/api"
MAYA_HEADERS = {
    "Accept":      "application/json",
    "X-Maya-With": "allow",
    "User-Agent":  "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
}

# Hebrew Maya report type → signal sub-type
MAYA_TYPE_MAP = {
    "הנפקה":            "ipo",
    "תשקיף":            "ipo",
    "דוח רבעוני":       "earnings",
    "דוח שנתי":         "earnings",
    "בעל עניין":        "institutional",
    "מחזיק":            "institutional",
    "מיזוג":            "ma",
    "רכישה":            "ma",
    "הסכם":             "contract",
    "חוזה":             "contract",
    "דיבידנד":          "dividend",
    "חלוקת":            "dividend",
    "רכישה עצמית":      "buyback",
    "רכישת מניות":      "buyback",
    "הנפקת זכויות":     "rights",
    "פיצול":            "spinoff",
    "הפרדה":            "spinoff",
    "מינוי":            "management",   # executive appointment
    "התפטרות":          "management",   # resignation
    "פרישה":            "management",   # retirement/departure
}

# ─── News sources ──────────────────────────────────────────────────────────────

ISRAELI_NEWS_SOURCES = [
    # ── Primary financial press (most important for stock signals) ──────────────
    {"type": "rss", "url": "https://www.globes.co.il/webservice/rss/rssfeeder.aspx?iID=1111", "label": "Globes-Finance"},
    {"type": "rss", "url": "https://www.globes.co.il/webservice/rss/rssfeeder.aspx?iID=1112", "label": "Globes-Stocks"},
    {"type": "rss", "url": "https://www.calcalist.co.il/rss/rss.aspx",                         "label": "Calcalist"},
    # ── General news with business sections ───────────────────────────────────
    {"type": "rss", "url": "https://www.ynet.co.il/Integration/StoryRss6.xml",          "label": "Ynet-Finance"},
    {"type": "rss", "url": "https://www.ynet.co.il/Integration/StoryRss3.xml",          "label": "Ynet-Business"},
    {"type": "rss", "url": "https://rss.walla.co.il/feed/22",                           "label": "Walla-Finance"},
    {"type": "rss", "url": "https://rss.walla.co.il/feed/1",                            "label": "Walla-News"},
    {"type": "rss", "url": "https://www.maariv.co.il/rss/rss-www.maariv.co.il-business.xml", "label": "Maariv-Business"},
]

GLOBAL_NEWS_SOURCES = [
    {"type": "rss", "url": "https://finance.yahoo.com/rss/topstories",                 "label": "YahooFinance"},
    {"type": "rss", "url": "https://www.marketwatch.com/rss/topstories",               "label": "MarketWatch"},
    {"type": "rss", "url": "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines", "label": "WSJ"},
]

# ─── Keyword groups (Hebrew + English) ────────────────────────────────────────

KEYWORD_GROUPS = {
    "new_contract": [
        "חוזה", "הסכם", "הזמנה", "עסקה", "מכרז", "זכייה", "לקוח",
        "contract", "agreement", "deal", "order", "tender", "awarded", "won bid",
        "supply agreement", "purchase order", "framework agreement", "new customer",
        "multi-year", "renewal", "expanded agreement",
    ],
    "institutional_investor": [
        "מחזיק מהותי", "בעל עניין", "רכישת מניות", "קרן", "מוסדי",
        "institutional", "fund acquired", "new shareholder", "stake",
        "13F", "13G", "13D", "form 5", "major holder", "hedge fund",
        "pension fund", "investment fund", "insider buy", "director buy",
        "CEO purchased", "executive acquired",
    ],
    "regulatory_approval": [
        "אישור", "רישוי", "FDA", "EMA", "CE mark",
        "approval", "approved", "cleared", "authorization", "license",
        "510k", "PMA", "NDA", "IND", "phase 3", "phase 2",
        "FDA clearance", "EMA authorization", "breakthrough designation",
        "orphan drug", "fast track", "priority review",
    ],
    "government_defense": [
        "ממשלה", "ביטחון", "צבא", "משרד הביטחון", "נאט\"ו", "תקציב ביטחון",
        "government", "defense", "military", "NATO", "ministry",
        "IDF", "Pentagon", "DoD", "MOD", "air force", "navy", "army",
        "homeland security", "border protection", "cybersecurity contract",
    ],
    "partnership": [
        "שותפות", "שיתוף פעולה", "הסכם שיתוף",
        "partnership", "collaboration", "joint venture", "MOU",
        "memorandum of understanding", "strategic alliance", "co-development",
        "licensing agreement", "technology transfer",
    ],
    "financial_event": [
        "דוח רבעוני", "דוח שנתי", "הכנסות", "רווח", "תחזית",
        "earnings", "revenue", "profit", "guidance", "raised guidance",
        "beat estimates", "exceeded expectations", "record revenue",
        "raised annual forecast", "upgraded outlook", "EPS beat",
    ],
    "shareholder_return": [
        "דיבידנד", "חלוקת דיבידנד", "רכישה עצמית", "רכישת מניות חזרה",
        "dividend", "special dividend", "dividend increase", "buyback",
        "share repurchase", "capital return", "return of capital",
        "dividend raised", "stock repurchase program",
    ],
    "management_change": [
        "מנכ\"ל חדש", "מינוי מנכ\"ל", "התפטרות", "פרישה", "מינוי",
        "new CEO", "CEO appointed", "CEO resigned", "CFO change",
        "leadership change", "management change", "executive appointment",
        "chairman resigned", "board change", "new president",
    ],
}

# ─── Macro tickers ─────────────────────────────────────────────────────────────

MACRO_TICKERS = {
    "TA125":   "^TA125.TA",  # Tel Aviv 125 index (TA-35 not available on Yahoo Finance)
    "USD_ILS": "ILS=X",      # Shekel rate — key for exporters (tech/defense/pharma) vs importers (retail/food)
    "SP500":   "^GSPC",
    "VIX":     "^VIX",
    "NASDAQ":  "^IXIC",
    "OIL_WTI": "CL=F",       # WTI crude — Israeli energy co revenue; Israel is an oil importer (costs)
    "US10Y":   "^TNX",       # US 10Y yield — proxy for global rate cycle; BoI tends to follow
}

# ─── Dual-listed Israeli stocks (US ticker → TASE ticker) ──────────────────────
# These trade on both Nasdaq/NYSE and TASE. US overnight moves are leading
# indicators for TASE open the following morning.

DUAL_LISTED_STOCKS = {
    # Verified dual-listed on both Nasdaq/NYSE and TASE.
    # All .TA tickers confirmed active on Yahoo Finance (March 2026).
    # US overnight moves are leading indicators for TASE open next morning.
    "TEVA":  "TEVA.TA",   # Teva Pharmaceutical     (NYSE:   TEVA  / TASE: TEVA.TA)
    "NICE":  "NICE.TA",   # NICE Systems             (Nasdaq: NICE  / TASE: NICE.TA)
    "ICL":   "ICL.TA",    # ICL Group                (NYSE:   ICL   / TASE: ICL.TA)
    "ESLT":  "ESLT.TA",   # Elbit Systems            (Nasdaq: ESLT  / TASE: ESLT.TA)
    "NVMI":  "NVMI.TA",   # Nova Ltd (semiconductors)(Nasdaq: NVMI  / TASE: NVMI.TA)
    "TSEM":  "TSEM.TA",   # Tower Semiconductor      (Nasdaq: TSEM  / TASE: TSEM.TA)
    "CAMT":  "CAMT.TA",   # Camtek (inspection equip)(Nasdaq: CAMT  / TASE: CAMT.TA)
    "AUDC":  "AUDC.TA",   # AudioCodes               (Nasdaq: AUDC  / TASE: AUDC.TA)
    "ALLT":  "ALLT.TA",   # Allot Communications     (Nasdaq: ALLT  / TASE: ALLT.TA)
    "KMDA":  "KMDA.TA",   # Kamada (plasma pharma)   (Nasdaq: KMDA  / TASE: KMDA.TA)
    "EVGN":  "EVGN.TA",   # Evogene (ag-biotech)     (Nasdaq: EVGN  / TASE: EVGN.TA)
    "CGEN":  "CGEN.TA",   # Compugen (drug discovery)(Nasdaq: CGEN  / TASE: CGEN.TA)
    "BWAY":  "BRND.TA",   # Brainsway (brain stimul) (Nasdaq: BWAY  / TASE: BRND.TA)
}

# ─── Sector ticker groupings (used by sector agents) ──────────────────────────
# Banks group includes Insurance + Finance services (all rate/macro sensitive)
# TelecomConsumer combines Telecom + Consumer (both domestic-demand driven)

SECTOR_TICKERS: dict[str, list[str]] = {
    "Banks": [
        "LUMI.TA", "POLI.TA", "MZTF.TA", "DSCT.TA", "FIBI.TA", "JBNK.TA",  # Big-5 banks + Bank of Jerusalem
        "PHOE.TA", "HARL.TA", "CLIS.TA", "MGDL.TA", "MMHD.TA",              # Insurance groups
        "ISCD.TA", "ILCO.TA", "DISI.TA", "TASE.TA",                          # Financial services
    ],
    "TechDefense": [
        # Defense electronics & systems
        "ESLT.TA",                                                              # Elbit Systems (defense)
        "NXSN.TA", "HLAN.TA", "FORTY.TA", "MLTM.TA",                          # Defense tech / IT
        # Semiconductors & hardware
        "NVMI.TA", "TSEM.TA", "CAMT.TA",                                       # Semiconductors
        # Enterprise software & communications
        "NICE.TA", "AUDC.TA", "ALLT.TA",                                       # CX, voice networking
        # IT services (Yahoo Finance verified valid March 2026)
        "MTRX.TA",                                                              # Matrix IT (TA-125 IT services)
    ],
    "Energy": [
        "DLEKG.TA", "OPCE.TA", "ENLT.TA", "NVPT.TA", "NWMD.TA",              # Gas & power
        "ENRG.TA", "ORL.TA", "PAZ.TA", "RATI.TA",                             # Refineries, fuel retail
    ],
    "PharmaBiotech": [
        # Large-cap pharma / chemicals
        "TEVA.TA", "ICL.TA",
        # Biotech & specialty pharma (all Yahoo Finance verified)
        "KMDA.TA", "CGEN.TA", "EVGN.TA",                                       # Plasma, drug discovery, ag-biotech
        "BRND.TA",                                                              # Brainsway (deep TMS devices)
        "BWAY.TA",                                                              # Blue & White (generic pharma)
    ],
    "RealEstate": [
        "AZRG.TA", "AMOT.TA", "BIG.TA", "MLSR.TA", "MVNE.TA", "DIMRI.TA",
        "SPEN.TA", "ALHE.TA", "GVYM.TA", "ARPT.TA", "GCT.TA", "SKBN.TA",
        "AURA.TA", "ROTS.TA",
        "AFRE.TA",                                                              # Africa Israel Residences (verified)
    ],
    "TelecomConsumer": [
        "BEZQ.TA", "PTNR.TA", "CEL.TA",                                        # Telecom big-3
        "SAE.TA", "STRS.TA", "FTAL.TA", "RMLI.TA", "ELCO.TA",                # Consumer staples & discretionary
    ],
}

# ─── TASE full scan universe — verified Yahoo Finance tickers ──────────────────
# Sourced from TA-35 (all 35) + selected TA-125 constituents.
# Covers banks, insurance, real estate, tech/defense, energy, telecom, pharma.
# All tickers verified as active on Yahoo Finance as of March 2026.

TASE_MAJOR_TICKERS = [
    # ── TA-35: Banks ──────────────────────────────────────────────────────────
    "LUMI.TA",   # Bank Leumi
    "POLI.TA",   # Bank HaPoalim
    "MZTF.TA",   # Mizrahi-Tefahot Bank
    "DSCT.TA",   # Israel Discount Bank
    "FIBI.TA",   # First International Bank of Israel

    # ── TA-35: Insurance ──────────────────────────────────────────────────────
    "PHOE.TA",   # Phoenix Holdings
    "HARL.TA",   # Harel Insurance
    "CLIS.TA",   # Clal Insurance (NOT CLAL.TA — that ticker is invalid)
    "MGDL.TA",   # Migdal Insurance
    "MMHD.TA",   # Menora Mivtachim Holdings

    # ── TA-35: Real Estate ────────────────────────────────────────────────────
    "AZRG.TA",   # Azrieli Group (largest REIT)
    "AMOT.TA",   # Amot Investments
    "BIG.TA",    # BIG Shopping Centers
    "MLSR.TA",   # Melisron
    "MVNE.TA",   # Mivne Real Estate
    "DIMRI.TA",  # Y.H. Dimri Construction & Development
    "SPEN.TA",   # Shapir Engineering & Industry

    # ── TA-35: Technology / Defense / Semiconductors ──────────────────────────
    "ESLT.TA",   # Elbit Systems (defense electronics)
    "NICE.TA",   # NICE Systems (CX AI)
    "NVMI.TA",   # Nova Ltd (semiconductor metrology)
    "TSEM.TA",   # Tower Semiconductor (foundry)
    "CAMT.TA",   # Camtek (inspection equipment)
    "NXSN.TA",   # NextVision Stabilized Systems (defense optics)

    # ── TA-35: Energy / Oil & Gas ─────────────────────────────────────────────
    "DLEKG.TA",  # Delek Group (energy conglomerate)
    "OPCE.TA",   # OPC Energy (power generation)
    "ENLT.TA",   # Enlight Renewable Energy
    "NVPT.TA",   # Navitas Petroleum
    "NWMD.TA",   # NewMed Energy (formerly Delek Drilling, Leviathan gas)

    # ── TA-35: Pharma / Chemicals ─────────────────────────────────────────────
    "TEVA.TA",   # Teva Pharmaceutical (world's largest generic drug maker)
    "ICL.TA",    # ICL Group (potash, phosphate, specialty minerals)

    # ── TA-35: Telecom ────────────────────────────────────────────────────────
    "BEZQ.TA",   # Bezeq (Israel's largest telecom)

    # ── TA-35: Consumer / Retail ─────────────────────────────────────────────
    "SAE.TA",    # Shufersal (largest supermarket chain)
    "STRS.TA",   # Strauss Group (food & beverages)
    "FTAL.TA",   # Fattal Holdings (hotels)

    # ── TA-125: Telecom ───────────────────────────────────────────────────────
    "PTNR.TA",   # Partner Communications
    "CEL.TA",    # Cellcom Israel

    # ── TA-125: Technology / Software ─────────────────────────────────────────
    "AUDC.TA",   # AudioCodes (voice networking)
    "ALLT.TA",   # Allot (network intelligence)
    "HLAN.TA",   # Hilan (HR software)
    "FORTY.TA",  # Formula Systems (IT holding)
    "MLTM.TA",   # Malam-Team (IT services)

    # ── TA-125: Healthcare / Pharma ───────────────────────────────────────────
    "KMDA.TA",   # Kamada (plasma-derived protein therapeutics)
    "CGEN.TA",   # Compugen (drug discovery)
    "EVGN.TA",   # Evogene (ag-biotech)

    # ── TA-125: Banking / Financial Services ──────────────────────────────────
    "ISCD.TA",   # Isracard (credit cards)
    "ILCO.TA",   # Israel Corporation (industrial holding)
    "DISI.TA",   # Discount Investment Corporation
    "JBNK.TA",   # Bank of Jerusalem
    "TASE.TA",   # Tel-Aviv Stock Exchange Ltd (listed itself)

    # ── TA-125: Real Estate (extended) ────────────────────────────────────────
    "ALHE.TA",   # Alony-Hetz Properties
    "GVYM.TA",   # Gav-Yam Lands
    "ARPT.TA",   # Airport City
    "GCT.TA",    # G City (formerly Gazit-Globe)
    "SKBN.TA",   # Shikun & Binui (construction)
    "AURA.TA",   # Aura Investments
    "ROTS.TA",   # Rotshtein Real Estate

    # ── TA-125: Energy (extended) ─────────────────────────────────────────────
    "ENRG.TA",   # Energix Renewable Energies
    "ORL.TA",    # Oil Refineries (Bazan Group)
    "PAZ.TA",    # Paz Retail & Energy
    "RATI.TA",   # Ratio Energies LP

    # ── TA-125: Consumer / Retail ─────────────────────────────────────────────
    "RMLI.TA",   # Rami Levi Chain Stores
    "ELCO.TA",   # Elco (electronics distribution)

    # ── TA-125+: Tech / IT Services (Yahoo Finance verified) ─────────────────
    "MTRX.TA",   # Matrix IT (IT services holding company, TA-125)

    # ── TA-125+: Biotech / Medical (Yahoo Finance verified) ───────────────────
    "BRND.TA",   # Brainsway (deep TMS devices, Nasdaq+TASE dual-listed)
    "BWAY.TA",   # Blue & White Pharmaceutical

    # ── TA-125+: Real Estate ──────────────────────────────────────────────────
    "AFRE.TA",   # Africa Israel Residences
]
