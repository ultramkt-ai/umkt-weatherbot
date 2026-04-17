from config import Config
from models.market import TemperatureMarket, TemperatureOutcomeCandidate
from models.trade import OpenTrade
from models.weather import WeatherContext
from utils.ids import generate_trade_id
from utils.time_utils import now_iso


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
) -> OpenTrade:
    capital_alocado_usd = bankroll_usd * config.risk.risk_per_trade_pct
    fees_paid_usd = 0.0
    gross_cost_usd = capital_alocado_usd
    net_cost_usd = gross_cost_usd + fees_paid_usd
    selected_entry_price = entry_price if entry_price is not None else (outcome.no_price if side == "NO" else outcome.yes_price)
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
        token_id=outcome.token_id,
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
            "spread": market.spread,
            "liquidity": market.liquidity,
            "contract_rules": market.contract_rules,
            "resolution_source": market.resolution_source,
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
