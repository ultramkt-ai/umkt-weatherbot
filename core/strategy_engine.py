from __future__ import annotations

from dataclasses import asdict
from math import exp
from typing import Any

from config import Config
from core.cluster import build_cluster_id
from core.risk_manager import check_strategy_new_trade_risk
from core.scorer import score_temperature_outcome
from core.validator import validate_temperature_market
from models.decision import TradeDecision
from models.market import TemperatureMarket, TemperatureOutcomeCandidate
from models.state import BotState
from models.strategy import StrategySpec
from models.weather import WeatherContext


def _approval_details(
    market: TemperatureMarket,
    outcome: TemperatureOutcomeCandidate,
    strategy: StrategySpec,
    side: str,
    entry_price: float,
    score_result,
    adjusted_score: int,
    preferred_bonus: int,
    weather: WeatherContext,
    token_book_metrics: dict[str, Any] | None,
    modeled_yes_probability: float | None,
    modeled_no_probability: float | None,
    selected_edge: float | None,
    minimum_required_score: int,
) -> dict[str, Any]:
    return {
        "strategy_id": strategy.strategy_id,
        "selected_side": side,
        "selected_entry_price": round(entry_price, 6),
        "selected_token_id": outcome.no_token_id if side == "NO" else outcome.yes_token_id,
        "price_band_ok": strategy.min_price <= entry_price <= strategy.max_price,
        "preferred_band_ok": strategy.preferred_low <= entry_price <= strategy.preferred_high,
        "preferred_band_bonus": preferred_bonus,
        "hours_to_resolution_window": {
            "min": strategy.min_hours_to_resolution,
            "max": strategy.max_hours_to_resolution,
        },
        "microstructure": {
            "spread": market.spread,
            "best_bid": market.best_bid,
            "best_ask": market.best_ask,
            "bid_levels": market.bid_levels,
            "ask_levels": market.ask_levels,
            "liquidity": market.liquidity,
        },
        "token_book": token_book_metrics or {},
        "weather": {
            "primary_forecast_value": weather.primary_forecast_value,
            "secondary_forecast_value": weather.secondary_forecast_value,
            "threshold_distance": weather.threshold_distance,
            "source_diff_value": weather.source_diff_value,
            "forecast_range_low": weather.forecast_range_low,
            "forecast_range_high": weather.forecast_range_high,
            "modeled_yes_probability": modeled_yes_probability,
            "modeled_no_probability": modeled_no_probability,
            "selected_edge": selected_edge,
        },
        "score": {
            "adjusted_total": adjusted_score,
            "raw_total": score_result.total_score,
            "minimum_required": minimum_required_score,
            "price_score": score_result.price_score,
            "threshold_score": score_result.threshold_score,
            "liquidity_score": score_result.liquidity_score,
            "spread_score": score_result.spread_score,
            "stability_score": score_result.stability_score,
            "extreme_risk_score": score_result.extreme_risk_score,
            "clarity_score": score_result.clarity_score,
            "correlation_score": score_result.correlation_score,
        },
    }


def evaluate_outcome_for_strategy(
    market: TemperatureMarket,
    outcome: TemperatureOutcomeCandidate,
    weather: WeatherContext | None,
    state: BotState,
    config: Config,
    strategy: StrategySpec,
    token_book_map: dict[str, dict[str, Any]] | None = None,
) -> TradeDecision:
    market_validation = validate_temperature_market(market, config)
    if not market_validation.ok:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code=market_validation.reason_code,
        )

    horizon_check = _check_horizon(market, strategy)
    if horizon_check is not None:
        return horizon_check

    city_check = _check_city(market, strategy)
    if city_check is not None:
        return city_check

    if weather is None:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="weather_context_unavailable",
        )

    distance_check = _check_distance_threshold(outcome, weather, strategy, market.market_id)
    if distance_check is not None:
        return distance_check

    side_selection = _resolve_side(outcome, strategy, weather, token_book_map or {})
    if side_selection is None:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="strategy_side_mismatch",
        )

    side = str(side_selection["side"])
    entry_price = float(side_selection["entry_price"])
    selected_token_id = side_selection.get("token_id")
    token_book_metrics = side_selection.get("token_book_metrics") or {}
    modeled_yes_probability = side_selection.get("modeled_yes_probability")
    modeled_no_probability = side_selection.get("modeled_no_probability")
    selected_edge = side_selection.get("selected_edge")

    if selected_token_id and any(open_trade.token_id == selected_token_id for open_trade in state.open_trades):
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="duplicate_open_token",
        )

    market_entry_check = _check_strategy_market_exposure(state, market, strategy, side)
    if market_entry_check is not None:
        return market_entry_check

    if not (strategy.min_price <= entry_price <= strategy.max_price):
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="strategy_price_out_of_range",
            trade_side=side,
            entry_price=entry_price,
        )

    microstructure_check = _check_strategy_microstructure(market, outcome, strategy, side, token_book_metrics)
    if microstructure_check is not None:
        return microstructure_check

    cluster_id = build_cluster_id(market)
    risk_check = check_strategy_new_trade_risk(state, market, config)
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

    score = score_temperature_outcome(
        market,
        outcome,
        weather,
        state,
        config,
        cluster_id,
        side=side,
        entry_price=entry_price,
    )
    preferred_bonus = _preferred_band_bonus(entry_price, strategy)
    adjusted_score = score.total_score + strategy.score_bias + preferred_bonus
    minimum_required_score = _required_min_score(strategy, entry_price)
    if adjusted_score < minimum_required_score:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="strategy_score_below_threshold",
            score=adjusted_score,
            cluster_id=cluster_id,
            weather_context=weather,
            trade_side=side,
            entry_price=entry_price,
        )

    approval_details = _approval_details(
        market,
        outcome,
        strategy,
        side,
        entry_price,
        score,
        adjusted_score,
        preferred_bonus,
        weather,
        token_book_metrics,
        modeled_yes_probability,
        modeled_no_probability,
        selected_edge,
        minimum_required_score,
    )

    return TradeDecision(
        decision="approve",
        market_id=market.market_id,
        approved=True,
        score=adjusted_score,
        cluster_id=cluster_id,
        approval_summary=f"{strategy.strategy_id} aprovou {side} em faixa {entry_price:.3f}.",
        approval_details=approval_details,
        weather_context=weather,
        trade_side=side,
        entry_price=entry_price,
    )


def build_strategy_snapshot(strategy: StrategySpec, decision: TradeDecision) -> dict[str, Any]:
    return {
        "strategy": asdict(strategy),
        "decision": asdict(decision),
    }


def _token_book_metrics(book: dict[str, Any] | None) -> dict[str, Any]:
    if not book:
        return {}
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    best_bid = float(bids[0].get("price", 0.0)) if bids else 0.0
    best_ask = float(asks[0].get("price", 0.0)) if asks else 0.0
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "bid_levels": len(bids),
        "ask_levels": len(asks),
        "spread": (best_ask - best_bid) if best_bid > 0.0 and best_ask > 0.0 else None,
        "last_trade_price": float(book.get("last_trade_price") or 0.0),
    }


def _estimate_yes_probability(outcome: TemperatureOutcomeCandidate, weather: WeatherContext) -> float:
    sigma = max(0.75, weather.forecast_range_width / 2.0, weather.source_diff_value + 0.5)
    forecast = weather.primary_forecast_value
    if outcome.bucket_type == "exact" and outcome.bucket_low is not None:
        distance = abs(forecast - outcome.bucket_low)
        probability = exp(-0.5 * ((distance / sigma) ** 2))
        return max(0.02, min(0.98, probability))
    if outcome.bucket_type == "range" and outcome.bucket_low is not None and outcome.bucket_high is not None:
        center = (outcome.bucket_low + outcome.bucket_high) / 2.0
        half_width = max(0.5, (outcome.bucket_high - outcome.bucket_low) / 2.0)
        distance = abs(forecast - center)
        if outcome.bucket_low <= forecast <= outcome.bucket_high:
            proximity_bonus = max(0.0, 1.0 - (distance / (half_width + sigma)))
            return max(0.10, min(0.96, 0.60 + 0.30 * proximity_bonus))
        outside_distance = min(abs(forecast - outcome.bucket_low), abs(forecast - outcome.bucket_high))
        probability = 0.45 * exp(-0.5 * ((outside_distance / sigma) ** 2))
        return max(0.02, min(0.90, probability))
    if outcome.bucket_type == "or_higher" and outcome.bucket_low is not None:
        z = (forecast - outcome.bucket_low) / sigma
        probability = 1.0 / (1.0 + exp(-1.35 * z))
        return max(0.02, min(0.98, probability))
    if outcome.bucket_type == "or_below" and outcome.bucket_high is not None:
        z = (outcome.bucket_high - forecast) / sigma
        probability = 1.0 / (1.0 + exp(-1.35 * z))
        return max(0.02, min(0.98, probability))
    return 0.5


def _side_edge_score(
    outcome: TemperatureOutcomeCandidate,
    strategy: StrategySpec,
    side: str,
    weather: WeatherContext,
    token_book_map: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    entry_price = outcome.no_price if side == "NO" else outcome.yes_price
    if not (strategy.min_price <= entry_price <= strategy.max_price):
        return None

    yes_probability = _estimate_yes_probability(outcome, weather)
    no_probability = max(0.02, min(0.98, 1.0 - yes_probability))
    selected_probability = yes_probability if side == "YES" else no_probability
    selected_token_id = outcome.no_token_id if side == "NO" else outcome.yes_token_id
    if not selected_token_id:
        selected_token_id = outcome.token_id

    token_metrics = _token_book_metrics(token_book_map.get(selected_token_id)) if selected_token_id else {}
    best_bid = float(token_metrics.get("best_bid") or 0.0)
    best_ask = float(token_metrics.get("best_ask") or 0.0)
    spread = token_metrics.get("spread")
    bid_levels = int(token_metrics.get("bid_levels") or 0)
    ask_levels = int(token_metrics.get("ask_levels") or 0)

    edge = selected_probability - entry_price
    selection_score = edge
    if strategy.preferred_low <= entry_price <= strategy.preferred_high:
        selection_score += 0.02
    if best_bid > 0.0:
        selection_score -= max(0.0, entry_price - best_bid) * 0.60
    else:
        selection_score -= 0.25
    if spread is not None:
        selection_score -= spread * 0.10
    if bid_levels < 2 or ask_levels < 2:
        selection_score -= 0.05
    if best_ask > 0.0 and best_ask >= 0.98:
        selection_score -= 0.03

    return {
        "side": side,
        "entry_price": entry_price,
        "token_id": selected_token_id,
        "token_book_metrics": token_metrics,
        "modeled_yes_probability": round(yes_probability, 6),
        "modeled_no_probability": round(no_probability, 6),
        "selected_edge": round(edge, 6),
        "selection_score": round(selection_score, 6),
    }


def _resolve_side(
    outcome: TemperatureOutcomeCandidate,
    strategy: StrategySpec,
    weather: WeatherContext,
    token_book_map: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if strategy.side_mode == "NO":
        return _side_edge_score(outcome, strategy, "NO", weather, token_book_map)
    if strategy.side_mode == "YES":
        return _side_edge_score(outcome, strategy, "YES", weather, token_book_map)
    if strategy.side_mode == "BOTH":
        candidates: list[dict[str, Any]] = []
        for side in ("NO", "YES"):
            selected = _side_edge_score(outcome, strategy, side, weather, token_book_map)
            if selected is not None:
                candidates.append(selected)
        if not candidates:
            return None
        candidates.sort(key=lambda item: item["selection_score"], reverse=True)
        best = candidates[0]
        if strategy.strategy_id == "MID_RANGE_BALANCED" and float(best["selected_edge"]) <= 0.03:
            return None
        return best
    return None


def _preferred_band_bonus(price: float, strategy: StrategySpec) -> int:
    if strategy.preferred_low <= price <= strategy.preferred_high:
        return 8
    if strategy.min_price <= price <= strategy.max_price:
        return 3
    return 0


def _check_horizon(market: TemperatureMarket, strategy: StrategySpec) -> TradeDecision | None:
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
    market_id: str,
) -> TradeDecision | None:
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


def _check_strategy_microstructure(
    market: TemperatureMarket,
    outcome: TemperatureOutcomeCandidate,
    strategy: StrategySpec,
    side: str,
    token_book_metrics: dict[str, Any] | None = None,
) -> TradeDecision | None:
    entry_price = outcome.no_price if side == "NO" else outcome.yes_price

    spread_limit = None
    best_bid_min = None
    min_bid_levels = None
    min_ask_levels = None

    if strategy.strategy_id == "YES_CONVEX" and side == "YES":
        spread_limit = 0.20
        best_bid_min = 0.03
        min_bid_levels = 2
        min_ask_levels = 2
    elif strategy.strategy_id == "NO_EXTREME" and side == "NO":
        spread_limit = 0.20
        best_bid_min = 0.03
        min_bid_levels = 2
        min_ask_levels = 2
    elif strategy.strategy_id == "MID_RANGE_BALANCED":
        if not token_book_metrics:
            return TradeDecision(
                decision="reject",
                market_id=market.market_id,
                approved=False,
                rejection_code="strategy_token_book_unavailable",
                trade_side=side,
                entry_price=entry_price,
            )
        token_best_bid = float(token_book_metrics.get("best_bid") or 0.0)
        token_best_ask = float(token_book_metrics.get("best_ask") or 0.0)
        token_spread = token_book_metrics.get("spread")
        token_bid_levels = int(token_book_metrics.get("bid_levels") or 0)
        token_ask_levels = int(token_book_metrics.get("ask_levels") or 0)

        if token_best_bid < 0.05:
            return TradeDecision(
                decision="reject",
                market_id=market.market_id,
                approved=False,
                rejection_code="strategy_token_best_bid_too_low",
                trade_side=side,
                entry_price=entry_price,
            )
        if token_best_ask <= 0.0 or token_best_ask >= 0.98:
            return TradeDecision(
                decision="reject",
                market_id=market.market_id,
                approved=False,
                rejection_code="strategy_token_best_ask_hostile",
                trade_side=side,
                entry_price=entry_price,
            )
        if token_spread is None or token_spread > 0.25:
            return TradeDecision(
                decision="reject",
                market_id=market.market_id,
                approved=False,
                rejection_code="strategy_token_spread_too_wide",
                trade_side=side,
                entry_price=entry_price,
            )
        if token_bid_levels < 2 or token_ask_levels < 2:
            return TradeDecision(
                decision="reject",
                market_id=market.market_id,
                approved=False,
                rejection_code="strategy_token_depth_too_thin",
                trade_side=side,
                entry_price=entry_price,
            )
        if (entry_price - token_best_bid) > 0.15:
            return TradeDecision(
                decision="reject",
                market_id=market.market_id,
                approved=False,
                rejection_code="strategy_token_execution_gap_too_wide",
                trade_side=side,
                entry_price=entry_price,
            )
        return None
    else:
        return None

    if market.spread is not None and market.spread > spread_limit:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="strategy_microstructure_spread_too_wide",
            trade_side=side,
            entry_price=entry_price,
        )

    if (market.best_bid or 0.0) < best_bid_min:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="strategy_microstructure_best_bid_too_low",
            trade_side=side,
            entry_price=entry_price,
        )

    if market.bid_levels < min_bid_levels or market.ask_levels < min_ask_levels:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="strategy_microstructure_depth_too_thin",
            trade_side=side,
            entry_price=entry_price,
        )

    return None


def _check_strategy_market_exposure(
    state: BotState,
    market: TemperatureMarket,
    strategy: StrategySpec,
    side: str,
) -> TradeDecision | None:
    same_market_trades = [trade for trade in state.open_trades if trade.market_id == market.market_id]
    if len(same_market_trades) >= strategy.max_entries_per_market:
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="strategy_market_entry_limit",
            trade_side=side,
            entry_price=None,
        )
    if strategy.strategy_id == "MID_RANGE_BALANCED" and any(trade.side != side for trade in same_market_trades):
        return TradeDecision(
            decision="reject",
            market_id=market.market_id,
            approved=False,
            rejection_code="strategy_opposite_side_open",
            trade_side=side,
            entry_price=None,
        )
    return None


def _required_min_score(strategy: StrategySpec, entry_price: float) -> int:
    if strategy.high_price_min_score and entry_price >= strategy.high_price_threshold:
        return strategy.high_price_min_score
    return strategy.min_score
