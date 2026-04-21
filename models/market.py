from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TemperatureOutcomeCandidate:
    market_id: str
    parent_slug: str
    outcome_label: str
    weather_type: str
    bucket_type: str
    bucket_low: Optional[float]
    bucket_high: Optional[float]
    threshold_unit: str
    contract_direction: str
    no_price: float
    yes_price: float
    token_id: Optional[str]
    outcome_index: int
    yes_token_id: Optional[str] = None
    no_token_id: Optional[str] = None


@dataclass
class TemperatureMarket:
    market_id: str
    title: str
    slug: str
    country: str
    state: Optional[str]
    city: Optional[str]
    region_label: Optional[str]
    observed_metric: str
    event_date_label: str
    event_start_time: str
    event_end_time: str
    resolution_time: str
    liquidity: float
    spread: float
    contract_rules: str
    resolution_source: str
    is_us_market: bool
    is_allowed_market_type: bool
    outcomes: list[TemperatureOutcomeCandidate] = field(default_factory=list)
    raw_market: Optional[dict[str, Any]] = None
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    bid_levels: int = 0
    ask_levels: int = 0
