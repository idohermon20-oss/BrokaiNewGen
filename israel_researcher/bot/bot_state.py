"""
BotSettings — persistent user preferences for the interactive Telegram bot.

Stored in bot_state.json (separate from research state so settings survive
research state resets). Atomic write via temp-file rename.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from ..config import BOT_STATE_FILE

ALL_SECTORS = [
    "Banks", "TechDefense", "Energy", "PharmaBiotech",
    "RealEstate", "TelecomConsumer", "TourismTransport", "Construction", "Discovery",
]

# Map from user-facing sector name → agent class name suffix (for filtering)
SECTOR_AGENT_MAP = {
    "Banks":            "BanksAgent",
    "TechDefense":      "TechDefenseAgent",
    "Energy":           "EnergyAgent",
    "PharmaBiotech":    "PharmaAgent",
    "RealEstate":       "RealEstateAgent",
    "TelecomConsumer":  "TelecomConsumerAgent",
    "TourismTransport": "TourismTransportAgent",
    "Construction":     "ConstructionAgent",
    "Discovery":        "DiscoveryAgent",
}


@dataclass
class BotSettings:
    language: str = "en"                   # "en" | "he"
    alerts_enabled: bool = True
    scan_interval_seconds: int = 900       # 15 minutes
    top_n_alerts: int = 3                  # top stocks per quick alert
    volume_spike_x: float = 2.5            # volume > N× 20d avg → anomaly
    price_move_pct: float = 3.5            # abs daily % move → anomaly
    enabled_sectors: list = field(default_factory=lambda: list(ALL_SECTORS))
    last_offset: int = 0                   # Telegram getUpdates offset
    last_updated: str = ""

    def save(self) -> None:
        """Atomic write: serialise to temp file then rename."""
        self.last_updated = datetime.now(timezone.utc).isoformat()
        data = asdict(self)
        path = BOT_STATE_FILE.resolve()
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent),
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, str(path))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def load_bot_settings() -> BotSettings:
    """Load BotSettings from bot_state.json, or return defaults if missing/corrupt."""
    path = BOT_STATE_FILE
    if path.exists():
        try:
            with open(str(path), encoding="utf-8") as f:
                data = json.load(f)
            # Validate enabled_sectors against known sectors
            sectors = data.get("enabled_sectors", list(ALL_SECTORS))
            sectors = [s for s in sectors if s in ALL_SECTORS] or list(ALL_SECTORS)
            data["enabled_sectors"] = sectors
            return BotSettings(**{k: v for k, v in data.items() if k in BotSettings.__dataclass_fields__})
        except Exception as e:
            print(f"[BotState] Could not load {path}: {e} — using defaults")
    settings = BotSettings()
    settings.save()
    return settings
