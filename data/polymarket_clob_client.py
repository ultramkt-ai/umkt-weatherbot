from __future__ import annotations

from typing import Any
import json
from urllib.request import Request, urlopen

from config import Config


class PolymarketClobClient:
    def __init__(self, config: Config) -> None:
        self.config = config

    def _request_json(self, url: str, payload: Any | None = None) -> Any:
        data = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "weather-bot-mvp/0.1",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url, data=data, headers=headers)
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_books(self, token_ids: list[str]) -> list[dict[str, Any]]:
        if not token_ids:
            return []
        payload = [{"token_id": token_id} for token_id in token_ids if token_id]
        if not payload:
            return []
        url = f"{self.config.api.polymarket_clob_base_url}/books"
        data = self._request_json(url, payload=payload)
        return data if isinstance(data, list) else []

    def get_prices(self, requests: list[dict[str, str]]) -> dict[str, dict[str, float]]:
        if not requests:
            return {}
        payload = [
            {"token_id": item["token_id"], "side": item["side"]}
            for item in requests
            if item.get("token_id") and item.get("side")
        ]
        if not payload:
            return {}
        url = f"{self.config.api.polymarket_clob_base_url}/prices"
        data = self._request_json(url, payload=payload)
        return data if isinstance(data, dict) else {}

    def get_book_map(self, token_ids: list[str]) -> dict[str, dict[str, Any]]:
        books = self.get_books(token_ids)
        mapped: dict[str, dict[str, Any]] = {}
        for book in books:
            asset_id = str(book.get("asset_id") or "")
            if asset_id:
                mapped[asset_id] = book
        return mapped
