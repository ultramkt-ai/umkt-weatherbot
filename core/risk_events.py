from config import Config
from core.state_machine import apply_pause, refresh_bot_mode
from models.state import BotState


NO_EXTREME_PAUSE_LOSS_STREAK = 3
NO_EXTREME_PAUSE_DAILY_PNL_PCT = -0.02
DEFAULT_PAUSE_LOSS_STREAK = 2


def _strategy_id_from_state(state: BotState) -> str:
    session_id = state.session_id or ""
    if session_id.startswith("strategy:"):
        parts = session_id.split(":")
        if len(parts) >= 2:
            return parts[1].upper()
    return ""


def refresh_strategy_risk_state(state: BotState, config: Config) -> BotState:
    bankroll_base = state.initial_bankroll_usd
    state.daily_stop_active = state.daily_pnl_usd <= (bankroll_base * config.risk.daily_stop_pct)
    state.weekly_stop_active = state.weekly_pnl_usd <= (bankroll_base * config.risk.weekly_stop_pct)
    state.kill_switch_active = state.max_drawdown_pct >= abs(config.risk.kill_switch_pct)

    strategy_id = _strategy_id_from_state(state)
    if strategy_id == "NO_EXTREME":
        daily_loss_pct = (state.daily_pnl_usd / bankroll_base) if bankroll_base else 0.0
        meets_no_extreme_pause = (
            state.consecutive_losses >= NO_EXTREME_PAUSE_LOSS_STREAK
            and daily_loss_pct <= NO_EXTREME_PAUSE_DAILY_PNL_PCT
        )
        if meets_no_extreme_pause:
            state = apply_pause(
                state,
                reason=f"{NO_EXTREME_PAUSE_LOSS_STREAK} perdas consecutivas com perda diária >= 2%",
                hours=6,
            )
        elif state.pause_reason == "2 perdas consecutivas":
            state.protection_pause_active = False
            state.pause_reason = None
            state.pause_started_at = None
            state.pause_until = None
    elif state.consecutive_losses >= DEFAULT_PAUSE_LOSS_STREAK:
        state = apply_pause(state, reason="2 perdas consecutivas")

    return refresh_bot_mode(state)
