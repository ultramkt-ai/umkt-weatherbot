from __future__ import annotations

from typing import Any
from urllib.parse import urlencode
import json
from urllib.request import Request, urlopen

from config import Config


class PolymarketDataClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.base_url = getattr(config.api, "polymarket_data_api_base_url", "https://data-api.polymarket.com")

    def _build_query(self, params: dict[str, Any]) -> str:
        normalized: list[tuple[str, str]] = []
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, bool):
                normalized.append((key, str(value).lower()))
            elif isinstance(value, (list, tuple)):
                for item in value:
                    normalized.append((key, str(item)))
            else:
                normalized.append((key, str(value)))
        return urlencode(normalized)

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        query = self._build_query(params or {})
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "weather-bot-mvp/0.1"})
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def list_trades(
        self,
        user: str,
        limit: int = 500,
        offset: int = 0,
        market: str | None = None,
    ) -> list[dict[str, Any]]:
        data = self._get_json(
            "/trades",
            {
                "user": user,
                "limit": limit,
                "offset": offset,
                "market": market,
            },
        )
        return data if isinstance(data, list) else []

    def list_positions(
        self,
        user: str,
        limit: int = 500,
        offset: int = 0,
        size_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        data = self._get_json(
            "/positions",
            {
                "user": user,
                "limit": limit,
                "offset": offset,
                "sizeThreshold": size_threshold,
            },
        )
        return data if isinstance(data, list) else []

    def list_activity(
        self,
        user: str,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        data = self._get_json(
            "/activity",
            {
                "user": user,
                "limit": limit,
                "offset": offset,
            },
        )
        return data if isinstance(data, list) else []

    def list_trades_until(self, user: str, target_count: int = 2000, page_size: int = 500) -> list[dict[str, Any]]:
        trades: list[dict[str, Any]] = []
        offset = 0
        while len(trades) < target_count:
            batch = self.list_trades(user=user, limit=min(page_size, target_count - len(trades)), offset=offset)
            if not batch:
                break
            trades.extend(batch)
            if len(batch) < min(page_size, target_count - len(trades) + len(batch)):
                break
            offset += len(batch)
        return trades[:target_count]
