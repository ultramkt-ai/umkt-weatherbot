from __future__ import annotations

from dataclasses import asdict
from typing import Any

from config import Config
from core.cluster import build_cluster_id
from core.risk_manager import check_new_trade_risk
from core.scorer import score_temperature_outcome
from core.validator import validate_temperature_market
from models.decision import TradeDecision
from models.market import TemperatureMarket, TemperatureOutcomeCandidate
from models.state import BotState
from models.strategy import StrategySpec
from models.weather import WeatherContext


def evaluate_outcome_for_strategy(
    market: TemperatureMarket,
    outcome: TemperatureOutcomeCandidate,
    weather: WeatherContext | None,
    state: BotState,
    config: Config,
    strategy: StrategySpec,
) -> TradeDecision:
    if outcome.token_id and any(open_trade.token_id == outcome.token_id for open_trade in state.open_trades):
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="duplicate_open_token",
        )

    market_validation = validate_temperature_market(market, config)
    if not market_validation.ok:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code=market_validation.reason_code,
        )

    side = _resolve_side(outcome, strategy)
    if side is None:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="strategy_side_mismatch",
        )

    entry_price = outcome.no_price if side == "NO" else outcome.yes_price
    if not (strategy.min_price <= entry_price <= strategy.max_price):
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="strategy_price_out_of_range",
            trade_side=side,
            entry_price=entry_price,
        )

    # ── Filtro 1: Horizonte temporal ──────────────────────────────────
    horizon_check = _check_horizon(market, strategy)
    if horizon_check is not None:
        return horizon_check

    # ── Filtro 2: Cidade exclusiva ─────────────────────────────────────
    city_check = _check_city(market, strategy)
    if city_check is not None:
        return city_check

    if weather is None:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="weather_context_unavailable",
            trade_side=side,
            entry_price=entry_price,
        )

    # ── Filtro 3: Distância do limiar ─────────────────────────────────
    distance_check = _check_distance_threshold(outcome, weather, strategy, market.market_id)
    if distance_check is not None:
        return distance_check

    cluster_id = build_cluster_id(market)
    risk_check = check_new_trade_risk(state, market, config)
    if not risk_check.ok:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code=risk_check.reason_code,
            cluster_id=cluster_id,
            trade_side=side,
            entry_price=entry_price,
        )

    score = score_temperature_outcome(market, outcome, weather, state, config, cluster_id)
    adjusted_score = score.total_score + strategy.score_bias + _preferred_band_bonus(entry_price, strategy)

    return TradeDecision(
        decision="approve",
        market_id=market.market_id,
        approved=True,
        score=adjusted_score,
        cluster_id=cluster_id,
        approval_summary=f"{strategy.strategy_id} aprovou {side} em faixa {entry_price:.3f}.",
        weather_context=weather,
        trade_side=side,
        entry_price=entry_price,
    )


def build_strategy_snapshot(strategy: StrategySpec, decision: TradeDecision) -> dict[str, Any]:
    return {
        "strategy": asdict(strategy),
        "decision": asdict(decision),
    }


def _resolve_side(outcome: TemperatureOutcomeCandidate, strategy: StrategySpec) -> str | None:
    if strategy.side_mode == "NO":
        return "NO"
    if strategy.side_mode == "YES":
        return "YES"
    if strategy.side_mode == "BOTH":
        candidates: list[tuple[str, float]] = []
        midpoint = (strategy.preferred_low + strategy.preferred_high) / 2
        for side, price in (("NO", outcome.no_price), ("YES", outcome.yes_price)):
            if not (strategy.min_price <= price <= strategy.max_price):
                continue
            preferred_bonus = 100 if strategy.preferred_low <= price <= strategy.preferred_high else 0
            distance_penalty = abs(price - midpoint)
            candidates.append((side, preferred_bonus - distance_penalty))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[1], reverse=True)
        return candidates[0][0]
    return None


def _preferred_band_bonus(price: float, strategy: StrategySpec) -> int:
    if strategy.preferred_low <= price <= strategy.preferred_high:
        return 8
    if strategy.min_price <= price <= strategy.max_price:
        return 3
    return 0


def _check_horizon(market: TemperatureMarket, strategy: StrategySpec) -> TradeDecision | None:
    """Recusa se o mercado não estiver no horizonte temporal da estratégia."""
    from datetime import datetime
    from utils.time_utils import now_dt
    try:
        resolution_time = datetime.fromisoformat(market.resolution_time)
    except ValueError:
        return None
    if resolution_time.tzinfo is None:
        resolution_time = resolution_time.replace(tzinfo=now_dt().tzinfo)
    hours_to_resolution = (resolution_time - now_dt()).total_seconds() / 3600
    if not (strategy.min_hours_to_resolution <= hours_to_resolution <= strategy.max_hours_to_resolution):
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="strategy_horizon_mismatch",
            trade_side=None,
            entry_price=None,
        )
    return None


def _check_city(market: TemperatureMarket, strategy: StrategySpec) -> TradeDecision | None:
    """Recusa se a cidade não for exclusiva da estratégia."""
    if not strategy.exclusive_cities:
        return None
    if market.city not in strategy.exclusive_cities:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="strategy_city_exclusive",
            trade_side=None,
            entry_price=None,
        )
    return None


def _distance_from_forecast(outcome, forecast_value: float) -> float:
    """Calcula distância em °C entre forecast e o limiar do outcome."""
    if outcome.bucket_type == "exact" and outcome.bucket_low is not None:
        return abs(forecast_value - outcome.bucket_low)
    if outcome.bucket_type in ("or_below", "range") and outcome.bucket_high is not None:
        return max(0.0, forecast_value - outcome.bucket_high)
    if outcome.bucket_type == "or_higher" and outcome.bucket_low is not None:
        return max(0.0, outcome.bucket_low - forecast_value)
    if outcome.bucket_type == "range" and outcome.bucket_low is not None and outcome.bucket_high is not None:
        if outcome.bucket_low <= forecast_value <= outcome.bucket_high:
            return 0.0
        return min(abs(forecast_value - outcome.bucket_low), abs(forecast_value - outcome.bucket_high))
    return 0.0


def _check_distance_threshold(
    outcome: TemperatureOutcomeCandidate,
    weather: WeatherContext,
    strategy: StrategySpec,
    market_id: str
) -> TradeDecision | None:
    """Recusa se a distância do forecast ao limiar não atender ao mínimo da estratégia."""
    if strategy.required_min_distance_threshold <= 0.0:
        return None
    distance = _distance_from_forecast(outcome, weather.primary_forecast_value)
    if distance < strategy.required_min_distance_threshold:
        return TradeDecision(
            decision="reject",
            market_id=market_id,
            approved=False,
            rejection_code="strategy_distance_threshold",
            trade_side=None,
            entry_price=None,
        )
    return None
