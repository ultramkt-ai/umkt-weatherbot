import re
from typing import Any


TEMPERATURE_CARD_RE = re.compile(r"\bhighest temperature in\b", re.IGNORECASE)
TEMPERATURE_BINARY_MARKET_RE = re.compile(r"^will the highest temperature in\b", re.IGNORECASE)


def _looks_like_temperature_market(title: str) -> bool:
    normalized = title.strip()
    return bool(TEMPERATURE_CARD_RE.search(normalized) or TEMPERATURE_BINARY_MARKET_RE.search(normalized))


def scan_weather_us_markets(raw_markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Temperature-only discovery for Polymarket weather markets."""
    candidates: list[dict[str, Any]] = []
    for market in raw_markets:
        title = str(market.get("title", ""))
        if _looks_like_temperature_market(title):
            candidates.append(market)
    return candidates
