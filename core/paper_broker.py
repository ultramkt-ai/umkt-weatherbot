from config import Config
from models.market import TemperatureMarket, TemperatureOutcomeCandidate
from models.trade import OpenTrade
from models.weather import WeatherContext
from utils.ids import generate_trade_id
from utils.time_utils import now_iso


def _compact_contract_rules(contract_rules: str | None) -> dict:
    raw = (contract_rules or "").strip()
    if not raw:
        return {"present": False}
    compact = " ".join(raw.split())
    return {
        "present": True,
        "chars": len(raw),
        "excerpt": compact[:240],
    }


def _compact_order_book_snapshot(market: TemperatureMarket, side: str, selected_entry_price: float) -> dict:
    return {
        "spread": market.spread,
        "best_bid": market.best_bid,
        "best_ask": market.best_ask,
        "bid_levels": market.bid_levels,
        "ask_levels": market.ask_levels,
        "selected_side": side,
        "selected_entry_price": selected_entry_price,
    }


def create_open_trade(
    market: TemperatureMarket,
    outcome: TemperatureOutcomeCandidate,
    weather: WeatherContext,
    cluster_id: str,
    score: int,
    approval_summary: str,
    config: Config,
    bankroll_usd: float,
    side: str = "NO",
    entry_price: float | None = None,
    approval_details: dict | None = None,
) -> OpenTrade:
    capital_alocado_usd = bankroll_usd * config.risk.risk_per_trade_pct
    fees_paid_usd = 0.0
    gross_cost_usd = capital_alocado_usd
    net_cost_usd = gross_cost_usd + fees_paid_usd
    selected_entry_price = entry_price if entry_price is not None else (outcome.no_price if side == "NO" else outcome.yes_price)
    selected_token_id = outcome.no_token_id if side == "NO" else outcome.yes_token_id
    if not selected_token_id:
        selected_token_id = outcome.token_id
    contracts_qty = capital_alocado_usd / selected_entry_price
    max_loss_usd = net_cost_usd
    max_profit_usd = contracts_qty - net_cost_usd

    return OpenTrade(
        trade_id=generate_trade_id(),
        market_id=market.market_id,
        parent_slug=market.slug,
        outcome_label=outcome.outcome_label,
        bucket_type=outcome.bucket_type,
        bucket_low=outcome.bucket_low,
        bucket_high=outcome.bucket_high,
        token_id=selected_token_id,
        entry_time=now_iso(),
        side=side,
        entry_price=selected_entry_price,
        capital_alocado_usd=capital_alocado_usd,
        contracts_qty=contracts_qty,
        gross_cost_usd=gross_cost_usd,
        fees_paid_usd=fees_paid_usd,
        net_cost_usd=net_cost_usd,
        max_loss_usd=max_loss_usd,
        max_profit_usd=max_profit_usd,
        risk_pct_of_bankroll=config.risk.risk_per_trade_pct,
        score=score,
        score_band=("excellent" if score >= 90 else "acceptable"),
        weather_type=outcome.weather_type,
        city=market.city,
        state=market.state,
        cluster_id=cluster_id,
        approval_summary=approval_summary,
        market_snapshot_at_entry={
            "timestamp": now_iso(),
            "market_title": market.title,
            "outcome_label": outcome.outcome_label,
            "no_price": outcome.no_price,
            "yes_price": outcome.yes_price,
            "selected_entry_price": selected_entry_price,
            "selected_side": side,
            "selected_token_id": selected_token_id,
            "yes_token_id": outcome.yes_token_id,
            "no_token_id": outcome.no_token_id,
            "liquidity": market.liquidity,
            "order_book": _compact_order_book_snapshot(market, side, selected_entry_price),
            "contract_rules": _compact_contract_rules(market.contract_rules),
            "resolution_source": market.resolution_source,
            "approval_details": approval_details or {},
        },
        weather_snapshot_at_entry={
            "primary_source_name": weather.primary_source_name,
            "secondary_source_name": weather.secondary_source_name,
            "alert_source_name": weather.alert_source_name,
            "primary_forecast_value": weather.primary_forecast_value,
            "secondary_forecast_value": weather.secondary_forecast_value,
            "forecast_range_low": weather.forecast_range_low,
            "forecast_range_high": weather.forecast_range_high,
            "threshold_distance": weather.threshold_distance,
            "range_buffer_value": weather.range_buffer_value,
            "source_diff_value": weather.source_diff_value,
            "severe_alert_flag": weather.severe_alert_flag,
            "extreme_weather_flag": weather.extreme_weather_flag,
            "instability_flag": weather.instability_flag,
        },
        status="OPEN",
    )
