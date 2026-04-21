from config import Config
from core.cluster import build_cluster_id
from core.risk_manager import check_strategy_new_trade_risk
from core.scorer import score_temperature_outcome
from core.validator import validate_temperature_market, validate_temperature_outcome
from models.decision import TradeDecision
from models.market import TemperatureMarket, TemperatureOutcomeCandidate
from models.state import BotState
from models.weather import WeatherContext


def validate_weather_context(weather: WeatherContext | None) -> str | None:
    if weather is None:
        return "weather_context_unavailable"
    if weather.extreme_weather_flag:
        return "extreme_weather_risk"
    if weather.severe_alert_flag:
        return "weather_alert"
    if weather.instability_flag:
        return weather.blocking_reason or "forecast_instability"
    if not weather.data_quality_ok:
        return weather.blocking_reason or "missing_weather_data"
    return None


def evaluate_temperature_outcome_for_entry(
    market: TemperatureMarket,
    outcome: TemperatureOutcomeCandidate,
    weather: WeatherContext,
    state: BotState,
    config: Config,
) -> TradeDecision:
    market_validation = validate_temperature_market(market, config)
    if not market_validation.ok:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code=market_validation.reason_code,
        )

    outcome_validation = validate_temperature_outcome(outcome, config)
    if not outcome_validation.ok:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code=outcome_validation.reason_code,
        )

    weather_rejection = validate_weather_context(weather)
    if weather_rejection:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code=weather_rejection,
            weather_context=weather,
        )

    cluster_id = build_cluster_id(market)
    risk_check = check_strategy_new_trade_risk(state, market, config)
    if not risk_check.ok:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code=risk_check.reason_code,
            cluster_id=cluster_id,
            weather_context=weather,
        )

    score = score_temperature_outcome(market, outcome, weather, state, config, cluster_id)

    trade_side = None
    entry_price = None
    if config.market.min_no_price <= outcome.no_price <= config.market.max_no_price:
        trade_side = "NO"
        entry_price = outcome.no_price
    elif config.market.enable_yes_strategy and config.market.min_yes_price <= outcome.yes_price <= config.market.max_yes_price:
        trade_side = "YES"
        entry_price = outcome.yes_price
    else:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="price_out_of_range",
            score=score.total_score,
            cluster_id=cluster_id,
            weather_context=weather,
        )

    return TradeDecision(
        decision="approve",
        market_id=market.market_id,
        approved=True,
        score=score.total_score,
        cluster_id=cluster_id,
        approval_summary=f"Outcome {outcome.outcome_label} aprovado por estar no range extremo compatível com a estratégia base.",
        weather_context=weather,
        trade_side=trade_side,
        entry_price=entry_price,
    )
