import re
from datetime import datetime
from typing import Any

from zoneinfo import ZoneInfo

from config import Config
from models.market import TemperatureMarket, TemperatureOutcomeCandidate


TITLE_RE = re.compile(
    r"will the highest temperature in\s+([A-Za-z .'-]+?)\s+be\s+(.+?)\s+on\s+([A-Za-z]+\s+\d{1,2})\??$",
    re.IGNORECASE,
)
SIGNED_NUMBER_RE = r"-?\d+(?:\.\d+)?"
EXACT_BUCKET_RE = re.compile(rf"^({SIGNED_NUMBER_RE})\s*°?\s*([FC])$", re.IGNORECASE)
RANGE_BUCKET_RE = re.compile(rf"^(?:between\s+)?({SIGNED_NUMBER_RE})-({SIGNED_NUMBER_RE})\s*°?\s*([FC])$", re.IGNORECASE)
OR_HIGHER_BUCKET_RE = re.compile(rf"^({SIGNED_NUMBER_RE})\s*°?\s*([FC])\s+or\s+higher$", re.IGNORECASE)
OR_BELOW_BUCKET_RE = re.compile(rf"^({SIGNED_NUMBER_RE})\s*°?\s*([FC])\s+or\s+below$", re.IGNORECASE)


def _f_to_c(value_f: float) -> float:
    return (value_f - 32) * 5 / 9


def _normalize_temp(value: float, unit: str) -> float:
    return _f_to_c(value) if unit.upper() == "F" else value


def _parse_outcome_label(label: str) -> tuple[str, str, float | None, float | None, str, str]:
    if match := RANGE_BUCKET_RE.match(label.strip()):
        low = _normalize_temp(float(match.group(1)), match.group(3))
        high = _normalize_temp(float(match.group(2)), match.group(3))
        return "temperature_range", "range", low, high, "celsius", "range"
    if match := OR_HIGHER_BUCKET_RE.match(label.strip()):
        low = _normalize_temp(float(match.group(1)), match.group(2))
        return "temperature_or_higher", "or_higher", low, None, "celsius", "or_higher"
    if match := OR_BELOW_BUCKET_RE.match(label.strip()):
        high = _normalize_temp(float(match.group(1)), match.group(2))
        return "temperature_or_below", "or_below", None, high, "celsius", "or_below"
    if match := EXACT_BUCKET_RE.match(label.strip()):
        exact = _normalize_temp(float(match.group(1)), match.group(2))
        return "temperature_exact", "exact", exact, exact, "celsius", "exact"
    raise ValueError(f"Unsupported temperature outcome format: {label}")


def _derive_weather_resolution_time(event_date_label: str, fallback_iso: str) -> str:
    try:
        parsed = datetime.strptime(f"{event_date_label} 2026 23:59:59", "%B %d %Y %H:%M:%S")
        return parsed.replace(tzinfo=ZoneInfo("UTC")).isoformat()
    except ValueError:
        return fallback_iso


def normalize_temperature_market(raw_market: dict[str, Any], config: Config) -> TemperatureMarket:
    title = raw_market.get("title", "")
    if not title:
        raise ValueError("Missing market title")

    title_match = TITLE_RE.search(title.strip())
    if not title_match:
        raise ValueError("Unsupported temperature market title format")

    city = title_match.group(1).strip()
    threshold_label = title_match.group(2).strip()
    event_date_label = title_match.group(3).strip()
    if config.market.target_temperature_cities and city not in config.market.target_temperature_cities:
        raise ValueError("City outside configured MVP scope")

    weather_type, bucket_type, bucket_low, bucket_high, threshold_unit, contract_direction = _parse_outcome_label(threshold_label)

    raw_market_payload = raw_market.get("raw_market", {})
    clob_token_ids = raw_market.get("clob_token_ids", [])

    yes_token_id = clob_token_ids[0] if len(clob_token_ids) > 0 else None
    no_token_id = clob_token_ids[1] if len(clob_token_ids) > 1 else None
    yes_price = float(raw_market.get("yes_price", 0.0))
    no_price = float(raw_market.get("no_price", 0.0))

    outcome_candidates: list[TemperatureOutcomeCandidate] = [
        TemperatureOutcomeCandidate(
            market_id=str(raw_market.get("market_id", raw_market.get("id", ""))),
            parent_slug=raw_market.get("slug", ""),
            outcome_label=threshold_label,
            weather_type=weather_type,
            bucket_type=bucket_type,
            bucket_low=bucket_low,
            bucket_high=bucket_high,
            threshold_unit=threshold_unit,
            contract_direction=contract_direction,
            no_price=no_price,
            yes_price=yes_price,
            token_id=no_token_id,
            yes_token_id=yes_token_id,
            no_token_id=no_token_id,
            outcome_index=1,
        )
    ]

    derived_resolution_time = _derive_weather_resolution_time(
        event_date_label=event_date_label,
        fallback_iso=raw_market.get("resolution_time", ""),
    )

    return TemperatureMarket(
        market_id=str(raw_market.get("market_id", raw_market.get("id", ""))),
        title=title,
        slug=raw_market.get("slug", ""),
        country="US" if city in config.market.us_fahrenheit_cities else raw_market.get("country", ""),
        state=raw_market.get("state"),
        city=city,
        region_label=city,
        observed_metric="highest_temperature",
        event_date_label=event_date_label,
        event_start_time=raw_market.get("event_start_time", ""),
        event_end_time=raw_market.get("event_end_time", ""),
        resolution_time=derived_resolution_time,
        liquidity=float(raw_market.get("liquidity", 0.0)),
        spread=float(raw_market.get("spread", 0.0)),
        contract_rules=raw_market.get("contract_rules", raw_market.get("title", "")),
        resolution_source=raw_market.get("resolution_source", ""),
        is_us_market=city in config.market.us_fahrenheit_cities,
        is_allowed_market_type=True,
        outcomes=outcome_candidates,
        raw_market=raw_market_payload,
    )
