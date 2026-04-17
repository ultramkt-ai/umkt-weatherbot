from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlencode
import http.client
import json
import time
from urllib.request import Request, urlopen

from config import Config


class PolymarketClient:
    def __init__(self, config: Config) -> None:
        self.config = config

    def _get_json(self, url: str, retries: int = 2) -> Any:
        """Fetch JSON from URL with retry logic for network errors."""
        attempt = 0
        last_error = None
        
        while attempt <= retries:
            try:
                request = Request(url, headers={"Accept": "application/json", "User-Agent": "weather-bot-mvp/0.1"})
                with urlopen(request, timeout=20) as response:
                    return json.loads(response.read().decode("utf-8"))
            except http.client.IncompleteRead as e:
                last_error = e
                attempt += 1
                if attempt <= retries:
                    time.sleep(1.0 * attempt)
                    continue
            except (TimeoutError, OSError) as e:
                last_error = e
                attempt += 1
                if attempt <= retries:
                    time.sleep(1.0 * attempt)
                    continue
        
        raise RuntimeError(f"Failed to fetch {url} after {retries + 1} attempts: {last_error}")

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

    def list_markets(self, limit: int = 100, closed: bool = False, offset: int = 0) -> list[dict]:
        query = self._build_query(
            {
                "limit": limit,
                "offset": offset,
                "closed": closed,
            }
        )
        url = f"{self.config.api.polymarket_base_url}/markets?{query}"
        data = self._get_json(url)
        return data if isinstance(data, list) else []

    def list_markets_keyset(
        self,
        limit: int = 200,
        closed: bool = False,
        after_cursor: str | None = None,
        order: str = "liquidity_num",
        ascending: bool = False,
        include_tag: bool = True,
        tag_id: int | None = None,
        related_tags: bool | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        query = self._build_query(
            {
                "limit": limit,
                "closed": closed,
                "after_cursor": after_cursor,
                "order": order,
                "ascending": ascending,
                "include_tag": include_tag,
                "tag_id": tag_id,
                "related_tags": related_tags,
            }
        )
        url = f"{self.config.api.polymarket_base_url}/markets/keyset?{query}"
        data = self._get_json(url)
        if not isinstance(data, dict):
            return [], None
        markets = data.get("markets")
        next_cursor = data.get("next_cursor")
        return (markets if isinstance(markets, list) else []), (str(next_cursor) if next_cursor else None)

    def get_market(self, market_id: str) -> dict:
        url = f"{self.config.api.polymarket_base_url}/markets/{market_id}"
        data = self._get_json(url)
        return data if isinstance(data, dict) else {}

    def get_market_by_slug(self, slug: str) -> dict[str, Any]:
        url = f"{self.config.api.polymarket_base_url}/markets/slug/{slug}"
        data = self._get_json(url)
        return data if isinstance(data, dict) else {}

    def get_event_by_slug(self, slug: str) -> dict[str, Any]:
        url = f"{self.config.api.polymarket_base_url}/events/slug/{slug}"
        data = self._get_json(url)
        return data if isinstance(data, dict) else {}

    def list_events_keyset(
        self,
        limit: int = 100,
        after_cursor: str | None = None,
        title_search: str | None = None,
        closed: bool = False,
        order: str | None = None,
        ascending: bool | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        query = self._build_query(
            {
                "limit": limit,
                "after_cursor": after_cursor,
                "title_search": title_search,
                "closed": closed,
                "order": order,
                "ascending": ascending,
            }
        )
        url = f"{self.config.api.polymarket_base_url}/events/keyset?{query}"
        data = self._get_json(url)
        if not isinstance(data, dict):
            return [], None
        events = data.get("events")
        next_cursor = data.get("next_cursor")
        return (events if isinstance(events, list) else []), (str(next_cursor) if next_cursor else None)

    def list_tags(self, limit: int = 500) -> list[dict[str, Any]]:
        query = self._build_query({"limit": limit})
        url = f"{self.config.api.polymarket_base_url}/tags?{query}"
        data = self._get_json(url)
        return data if isinstance(data, list) else []

    def search_public(
        self,
        query_text: str,
        limit_per_type: int = 25,
        page: int = 1,
        optimized: bool = True,
    ) -> dict[str, Any]:
        query = self._build_query(
            {
                "q": query_text,
                "limit_per_type": limit_per_type,
                "page": page,
                "optimized": optimized,
            }
        )
        url = f"{self.config.api.polymarket_base_url}/public-search?{query}"
        data = self._get_json(url)
        return data if isinstance(data, dict) else {}

    def fetch_open_markets(self, limit: int = 100, offset: int = 0) -> list[dict]:
        markets = self.list_markets(limit=limit, closed=False, offset=offset)
        return [self.normalize_market_payload(market) for market in markets]

    def fetch_open_markets_keyset(
        self,
        limit: int = 200,
        after_cursor: str | None = None,
        order: str = "liquidity_num",
        ascending: bool = False,
    ) -> tuple[list[dict[str, Any]], str | None]:
        markets, next_cursor = self.list_markets_keyset(
            limit=limit,
            closed=False,
            after_cursor=after_cursor,
            order=order,
            ascending=ascending,
            include_tag=True,
        )
        normalized = [self.normalize_market_payload(market) for market in markets]
        return normalized, next_cursor

    def discover_weather_event_slugs(self, queries: list[str] | None = None) -> list[str]:
        slugs: list[str] = []
        seen: set[str] = set()

        after_cursor: str | None = None
        for _ in range(5):
            events, after_cursor = self.list_events_keyset(
                limit=100,
                after_cursor=after_cursor,
                title_search="highest temperature",
                closed=False,
            )
            for event in events:
                slug = str(event.get("slug") or "").strip()
                if slug and slug not in seen:
                    seen.add(slug)
                    slugs.append(slug)
            if not after_cursor:
                break

        if slugs:
            return slugs

        fallback_queries = queries or ["highest temperature", "temperature"]
        weather_terms = ("temperature", "highest temperature")
        for query_text in fallback_queries:
            payload = self.search_public(query_text=query_text)
            for event in payload.get("events") or []:
                slug = str(event.get("slug") or "").strip()
                title = str(event.get("title") or "").strip().lower()
                subtitle = str(event.get("subtitle") or "").strip().lower()
                description = str(event.get("description") or "").strip().lower()
                haystack = " ".join([title, subtitle, description])
                if not slug:
                    continue
                if not any(term in haystack for term in weather_terms):
                    continue
                if slug in seen:
                    continue
                seen.add(slug)
                slugs.append(slug)
        return slugs

    def normalize_market_payload(self, market: dict[str, Any]) -> dict[str, Any]:
        clob_token_ids = self._json_list(market.get("clobTokenIds"))
        outcome_prices = self._json_list(market.get("outcomePrices"))
        outcomes = self._json_list(market.get("outcomes"))

        no_price = 0.0
        yes_price = 0.0
        for index, outcome in enumerate(outcomes):
            outcome_name = str(outcome).strip().lower()
            price = float(outcome_prices[index]) if index < len(outcome_prices) else 0.0
            if outcome_name == "no":
                no_price = price
            elif outcome_name == "yes":
                yes_price = price

        spread = self._derive_spread(market)
        resolution_source = market.get("resolutionSource") or ""
        contract_rules = market.get("description") or market.get("question") or ""
        return {
            "id": market.get("id"),
            "market_id": market.get("id"),
            "title": market.get("question", ""),
            "slug": market.get("slug", ""),
            "no_price": no_price,
            "yes_price": yes_price,
            "liquidity": float(market.get("liquidityNum") or market.get("liquidity") or 0.0),
            "spread": spread,
            "event_start_time": self._normalize_datetime(market.get("startDateIso") or market.get("startDate") or ""),
            "event_end_time": self._normalize_datetime(market.get("endDateIso") or market.get("endDate") or ""),
            "resolution_time": self._normalize_datetime(market.get("endDateIso") or market.get("endDate") or ""),
            "contract_rules": contract_rules,
            "resolution_source": resolution_source,
            "resolution_source_missing": not bool(resolution_source),
            "clob_token_ids": clob_token_ids,
            "raw_market": market,
        }

    def _json_list(self, raw_value: Any) -> list[Any]:
        if raw_value is None:
            return []
        if isinstance(raw_value, list):
            return raw_value
        if isinstance(raw_value, str):
            try:
                parsed = json.loads(raw_value)
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return []
        return []

    def _derive_spread(self, market: dict) -> float:
        best_bid = market.get("bestBid")
        best_ask = market.get("bestAsk")
        if best_bid is None or best_ask is None:
            spread = market.get("spread")
            return float(spread) if spread is not None else 0.0
        try:
            return float(best_ask) - float(best_bid)
        except (TypeError, ValueError):
            return 0.0

    def _normalize_datetime(self, value: str) -> str:
        if not value:
            return ""
        if "T" in value:
            return value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(value).strftime("%Y-%m-%dT00:00:00+00:00")
        except ValueError:
            return value
