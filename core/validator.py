from datetime import datetime

from config import Config
from models.decision import ValidationResult
from models.market import TemperatureMarket, TemperatureOutcomeCandidate
from utils.time_utils import now_dt


def validate_temperature_market(market: TemperatureMarket, config: Config) -> ValidationResult:
    if config.market.target_temperature_cities and market.city not in config.market.target_temperature_cities:
        return ValidationResult(ok=False, reason_code="city_out_of_scope")
    if config.market.allowed_country_codes and market.country and market.country not in config.market.allowed_country_codes:
        return ValidationResult(ok=False, reason_code="non_supported_country")
    if market.liquidity < config.market.min_liquidity_usd:
        return ValidationResult(ok=False, reason_code="low_liquidity")
    if not market.contract_rules.strip():
        return ValidationResult(ok=False, reason_code="ambiguous_contract")
    if not market.city:
        return ValidationResult(ok=False, reason_code="missing_location")
    if market.observed_metric != "highest_temperature":
        return ValidationResult(ok=False, reason_code="invalid_market_type")

    now = now_dt()
    try:
        resolution_time = datetime.fromisoformat(market.resolution_time)
    except ValueError:
        return ValidationResult(ok=False, reason_code="invalid_resolution_window")

    if resolution_time.tzinfo is None:
        resolution_time = resolution_time.replace(tzinfo=now.tzinfo)

    hours_to_resolution = (resolution_time - now).total_seconds() / 3600
    if hours_to_resolution < config.market.min_hours_to_resolution:
        return ValidationResult(ok=False, reason_code="invalid_resolution_window")
    if hours_to_resolution > config.market.max_days_to_resolution * 24:
        return ValidationResult(ok=False, reason_code="invalid_resolution_window")

    return ValidationResult(ok=True)


def validate_temperature_outcome(outcome: TemperatureOutcomeCandidate, config: Config) -> ValidationResult:
    if outcome.weather_type not in config.market.allowed_weather_types:
        return ValidationResult(ok=False, reason_code="invalid_market_type")
    if not (config.market.min_no_price <= outcome.no_price <= config.market.max_no_price):
        return ValidationResult(ok=False, reason_code="price_out_of_range")
    return ValidationResult(ok=True)
