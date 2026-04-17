from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config import Config
from utils.time_utils import now_dt


CATALOG_FILENAME = "weather_market_catalog.json"
CATALOG_TTL_MINUTES = 45


@dataclass
class CatalogSnapshot:
    generated_at: str
    expires_at: str
    markets: list[dict[str, Any]]


class WeatherMarketCatalog:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.path: Path = self.config.storage.state_dir / CATALOG_FILENAME

    def load_valid_markets(self) -> list[dict[str, Any]]:
        snapshot = self._load_snapshot()
        if not snapshot:
            return []

        now = now_dt()
        try:
            expires_at = datetime.fromisoformat(snapshot.generated_at if not snapshot.expires_at else snapshot.expires_at)
        except ValueError:
            return []

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=now.tzinfo)

        if expires_at <= now:
            return []

        return list(snapshot.markets)

    def save_markets(self, markets: list[dict[str, Any]]) -> None:
        self.config.storage.state_dir.mkdir(parents=True, exist_ok=True)
        now = now_dt()
        expires_at = now + timedelta(minutes=CATALOG_TTL_MINUTES)
        snapshot = CatalogSnapshot(
            generated_at=now.isoformat(),
            expires_at=expires_at.isoformat(),
            markets=markets,
        )
        self.path.write_text(json.dumps(snapshot.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_snapshot(self) -> CatalogSnapshot | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(raw, dict):
            return None
        markets = raw.get("markets") or []
        if not isinstance(markets, list):
            markets = []
        return CatalogSnapshot(
            generated_at=str(raw.get("generated_at") or ""),
            expires_at=str(raw.get("expires_at") or ""),
            markets=markets,
        )
