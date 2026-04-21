from config import Config
from models.decision import ScoreResult
from models.market import TemperatureMarket, TemperatureOutcomeCandidate
from models.state import BotState
from models.weather import WeatherContext


def _price_score(selected_price: float, side: str | None = None) -> int:
    if side == "YES":
        if 0.04 <= selected_price <= 0.12:
            return 15
        if 0.12 < selected_price <= 0.20:
            return 11
        if 0.20 < selected_price <= 0.35:
            return 6
        return 0
    if 0.94 <= selected_price <= 0.98:
        return 15
    if 0.84 <= selected_price < 0.94:
        return 11
    if 0.55 <= selected_price < 0.84:
        return 6
    return 0


def _liquidity_score(liquidity: float) -> int:
    if liquidity >= 50_000:
        return 10
    if liquidity >= 20_000:
        return 8
    if liquidity >= 5_000:
        return 6
    return 0


def _spread_score(spread: float) -> int:
    if spread <= 0.005:
        return 10
    if spread <= 0.010:
        return 8
    if spread <= 0.015:
        return 5
    return 0


def _clarity_score(market: TemperatureMarket) -> int:
    if market.contract_rules and market.city and market.event_date_label:
        return 10
    return 0


def _correlation_score(state: BotState, cluster_id: str) -> int:
    cluster_count = state.cluster_trade_count_map.get(cluster_id, 0)
    if cluster_count == 0:
        return 5
    if cluster_count == 1:
        return 3
    if cluster_count == 2:
        return 1
    return 0


def _distance_from_forecast(outcome: TemperatureOutcomeCandidate, forecast_value: float) -> float:
    if outcome.bucket_type == "exact" and outcome.bucket_low is not None:
        return abs(forecast_value - outcome.bucket_low)
    if outcome.bucket_type == "range" and outcome.bucket_low is not None and outcome.bucket_high is not None:
        if outcome.bucket_low <= forecast_value <= outcome.bucket_high:
            return 0.0
        if forecast_value < outcome.bucket_low:
            return outcome.bucket_low - forecast_value
        return forecast_value - outcome.bucket_high
    if outcome.bucket_type == "or_higher" and outcome.bucket_low is not None:
        return max(0.0, outcome.bucket_low - forecast_value)
    if outcome.bucket_type == "or_below" and outcome.bucket_high is not None:
        return max(0.0, forecast_value - outcome.bucket_high)
    return 0.0


def _bucket_score(outcome: TemperatureOutcomeCandidate, weather: WeatherContext) -> int:
    distance = _distance_from_forecast(outcome, weather.primary_forecast_value)
    if weather.range_buffer_value <= 0:
        return 0
    if distance >= 4.0:
        return 20
    if distance >= 2.5:
        return 16
    if distance >= 1.5:
        return 10
    return 0


def _stability_score(weather: WeatherContext) -> int:
    if weather.severe_alert_flag or weather.extreme_weather_flag or weather.instability_flag:
        return 0
    if weather.source_diff_value <= 1.0 and weather.forecast_range_width <= 2.0:
        return 15
    if weather.source_diff_value <= 2.0 and weather.forecast_range_width <= 3.0:
        return 11
    if weather.source_diff_value <= 2.5 and weather.forecast_range_width <= 4.0:
        return 7
    return 0


def _extreme_risk_score(weather: WeatherContext) -> int:
    if weather.severe_alert_flag or weather.extreme_weather_flag or weather.instability_flag:
        return 0
    return 15


def score_temperature_outcome(
    market: TemperatureMarket,
    outcome: TemperatureOutcomeCandidate,
    weather: WeatherContext,
    state: BotState,
    config: Config,
    cluster_id: str,
    side: str | None = None,
    entry_price: float | None = None,
) -> ScoreResult:
    selected_side = side or "NO"
    selected_price = entry_price if entry_price is not None else (outcome.yes_price if selected_side == "YES" else outcome.no_price)
    price_score = _price_score(selected_price, selected_side)
    threshold_score = _bucket_score(outcome, weather)
    liquidity_score = _liquidity_score(market.liquidity)
    spread_score = _spread_score(market.spread)
    stability_score = _stability_score(weather)
    extreme_risk_score = _extreme_risk_score(weather)
    clarity_score = _clarity_score(market)
    correlation_score = _correlation_score(state, cluster_id)

    total_score = (
        price_score
        + threshold_score
        + liquidity_score
        + spread_score
        + stability_score
        + extreme_risk_score
        + clarity_score
        + correlation_score
    )
    required_min_score = 0

    return ScoreResult(
        total_score=total_score,
        price_score=price_score,
        threshold_score=threshold_score,
        liquidity_score=liquidity_score,
        spread_score=spread_score,
        stability_score=stability_score,
        extreme_risk_score=extreme_risk_score,
        clarity_score=clarity_score,
        correlation_score=correlation_score,
        required_min_score=required_min_score,
        passed=(total_score >= required_min_score),
    )
