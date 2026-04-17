from models.state import BotState
from models.trade import ClosedTrade, OpenTrade
from utils.math_utils import calculate_drawdown_pct, calculate_open_exposure_pct


def apply_open_trade_to_state(state: BotState, trade: OpenTrade) -> BotState:
    state.current_cash_usd -= trade.net_cost_usd
    state.capital_alocado_aberto_usd += trade.capital_alocado_usd
    state.gross_exposure_open_usd += trade.capital_alocado_usd
    state.open_trades.append(trade)
    state.open_trade_ids.append(trade.trade_id)
    state.open_trades_count = len(state.open_trades)
    state.open_exposure_pct = calculate_open_exposure_pct(
        state.capital_alocado_aberto_usd,
        state.current_bankroll_usd,
    )
    state.approved_trades_count += 1
    state.approved_today += 1
    state.last_score_approved = trade.score
    state.cluster_exposure_map_usd[trade.cluster_id] = state.cluster_exposure_map_usd.get(trade.cluster_id, 0.0) + trade.capital_alocado_usd
    state.cluster_trade_count_map[trade.cluster_id] = state.cluster_trade_count_map.get(trade.cluster_id, 0) + 1
    return state


def apply_closed_trade_to_state(state: BotState, closed_trade: ClosedTrade) -> BotState:
    state.current_cash_usd += closed_trade.gross_settlement_value_usd
    state.capital_alocado_aberto_usd -= closed_trade.capital_alocado_usd
    state.gross_exposure_open_usd -= closed_trade.capital_alocado_usd
    state.realized_pnl_total_usd += closed_trade.net_pnl_abs
    state.fees_paid_total_usd += closed_trade.fees_paid_usd
    state.daily_pnl_usd += closed_trade.net_pnl_abs
    state.weekly_pnl_usd += closed_trade.net_pnl_abs
    state.current_bankroll_usd = state.current_cash_usd + state.capital_alocado_aberto_usd
    state.equity_peak_usd = max(state.equity_peak_usd, state.current_bankroll_usd)
    state.current_drawdown_pct = calculate_drawdown_pct(state.current_bankroll_usd, state.equity_peak_usd)
    state.max_drawdown_pct = max(state.max_drawdown_pct, state.current_drawdown_pct)
    state.open_trades = [trade for trade in state.open_trades if trade.trade_id != closed_trade.trade_id]
    state.open_trade_ids = [trade_id for trade_id in state.open_trade_ids if trade_id != closed_trade.trade_id]
    state.open_trades_count = len(state.open_trades)
    state.open_exposure_pct = calculate_open_exposure_pct(
        state.capital_alocado_aberto_usd,
        state.current_bankroll_usd,
    )
    state.closed_trades_count += 1
    if closed_trade.result == "WIN":
        state.consecutive_wins += 1
        state.consecutive_losses = 0
        state.last_10_closed_results.append("W")
    else:
        state.consecutive_losses += 1
        state.consecutive_wins = 0
        state.last_10_closed_results.append("L")
    state.last_10_closed_results = state.last_10_closed_results[-10:]
    state.cluster_exposure_map_usd[closed_trade.cluster_id] = max(
        0.0,
        state.cluster_exposure_map_usd.get(closed_trade.cluster_id, 0.0) - closed_trade.capital_alocado_usd,
    )
    state.cluster_trade_count_map[closed_trade.cluster_id] = max(
        0,
        state.cluster_trade_count_map.get(closed_trade.cluster_id, 0) - 1,
    )
    return state
