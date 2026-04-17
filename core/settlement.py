from models.trade import ClosedTrade, OpenTrade
from utils.time_utils import now_iso


def settle_open_trade(
    trade: OpenTrade,
    resolution_value: float,
    resolution_source: str,
    resolution_source_value: object,
    hold_duration_hours: float,
    drawdown_after_close: float,
) -> ClosedTrade:
    gross_settlement_value_usd = trade.contracts_qty * resolution_value
    net_pnl_abs = gross_settlement_value_usd - trade.net_cost_usd
    roi_on_allocated_capital = net_pnl_abs / trade.capital_alocado_usd if trade.capital_alocado_usd else 0.0
    result = "WIN" if resolution_value == 1.0 else "LOSS"

    return ClosedTrade(
        trade_id=trade.trade_id,
        market_id=trade.market_id,
        parent_slug=trade.parent_slug,
        outcome_label=trade.outcome_label,
        bucket_type=trade.bucket_type,
        bucket_low=trade.bucket_low,
        bucket_high=trade.bucket_high,
        token_id=trade.token_id,
        entry_time=trade.entry_time,
        exit_time=now_iso(),
        resolution_time=now_iso(),
        side=trade.side,
        entry_price=trade.entry_price,
        resolution_value=resolution_value,
        capital_alocado_usd=trade.capital_alocado_usd,
        contracts_qty=trade.contracts_qty,
        gross_cost_usd=trade.gross_cost_usd,
        fees_paid_usd=trade.fees_paid_usd,
        gross_settlement_value_usd=gross_settlement_value_usd,
        net_pnl_abs=net_pnl_abs,
        roi_on_allocated_capital=roi_on_allocated_capital,
        result=result,
        hold_duration_hours=hold_duration_hours,
        score=trade.score,
        weather_type=trade.weather_type,
        cluster_id=trade.cluster_id,
        resolution_source=resolution_source,
        resolution_source_value=resolution_source_value,
        drawdown_after_close=drawdown_after_close,
    )
