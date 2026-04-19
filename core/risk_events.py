from config import Config
from core.state_machine import apply_pause, refresh_bot_mode
from models.state import BotState


def refresh_strategy_risk_state(state: BotState, config: Config) -> BotState:
    bankroll_base = state.initial_bankroll_usd
    state.daily_stop_active = state.daily_pnl_usd <= (bankroll_base * config.risk.daily_stop_pct)
    state.weekly_stop_active = state.weekly_pnl_usd <= (bankroll_base * config.risk.weekly_stop_pct)
    state.kill_switch_active = state.max_drawdown_pct >= abs(config.risk.kill_switch_pct)

    if state.consecutive_losses >= 2:
        state = apply_pause(state, reason="2 perdas consecutivas")

    return refresh_bot_mode(state)
