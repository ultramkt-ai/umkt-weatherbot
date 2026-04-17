from config import Config
from core.state_machine import apply_pause, refresh_bot_mode
from models.state import BotState


def refresh_risk_flags_after_close(state: BotState, config: Config) -> BotState:
    state.daily_stop_active = state.daily_pnl_usd <= (config.risk.initial_bankroll_usd * config.risk.daily_stop_pct)
    state.weekly_stop_active = state.weekly_pnl_usd <= (config.risk.initial_bankroll_usd * config.risk.weekly_stop_pct)
    state.kill_switch_active = state.max_drawdown_pct >= abs(config.risk.kill_switch_pct)

    if state.consecutive_losses >= 2:
        state = apply_pause(state, reason="2 perdas consecutivas")

    return refresh_bot_mode(state)
