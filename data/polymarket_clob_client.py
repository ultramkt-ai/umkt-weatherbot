from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import json
import socket
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import Config


@dataclass
class ClobRequestError(RuntimeError):
    endpoint: str
    reason: str
    attempts: int
    retryable: bool
    original_error: str

    def __str__(self) -> str:
        return (
            f"CLOB request failed for {self.endpoint} after {self.attempts} attempt(s): "
            f"{self.reason} ({self.original_error})"
        )


class PolymarketClobClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.request_timeout_seconds = 20
        self.max_attempts = 3
        self.retry_backoff_seconds = (0.75, 1.5)

    def _classify_request_error(self, exc: Exception) -> tuple[str, bool]:
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return ("timeout", True)
        if isinstance(exc, HTTPError):
            status = exc.code
            if status in {408, 425, 429, 500, 502, 503, 504}:
                return (f"http_{status}", True)
            return (f"http_{status}", False)
        if isinstance(exc, URLError):
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                return ("timeout", True)
            return ("network_error", True)
        return (exc.__class__.__name__.lower(), False)

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
        attempts = 0
        last_error: Exception | None = None
        last_reason = "unknown"
        last_retryable = False

        while attempts < self.max_attempts:
            attempts += 1
            try:
                with urlopen(request, timeout=self.request_timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                last_error = exc
                last_reason, last_retryable = self._classify_request_error(exc)
                should_retry = last_retryable and attempts < self.max_attempts
                if should_retry:
                    backoff_index = min(attempts - 1, len(self.retry_backoff_seconds) - 1)
                    sleep(self.retry_backoff_seconds[backoff_index])
                    continue
                break

        raise ClobRequestError(
            endpoint=url,
            reason=last_reason,
            attempts=attempts,
            retryable=last_retryable,
            original_error=repr(last_error) if last_error else "unknown",
        )

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
