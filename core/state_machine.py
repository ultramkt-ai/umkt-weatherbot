from datetime import datetime, timedelta

from config import Config
from models.state import BotState
from utils.time_utils import now_dt, now_iso


STATE_PRIORITY = [
    "KILL_SWITCH",
    "WEEKLY_STOP",
    "DAILY_STOP",
    "ERROR_SAFE_MODE",
    "PAUSED",
    "ACTIVE",
]


def apply_pause(state: BotState, reason: str, hours: int = 12) -> BotState:
    now = now_dt()
    state.protection_pause_active = True
    state.pause_reason = reason
    state.pause_started_at = now.isoformat()
    state.pause_until = (now + timedelta(hours=hours)).isoformat()
    return refresh_bot_mode(state)


def apply_error_safe_mode(state: BotState, reason: str) -> BotState:
    state.error_safe_mode_active = True
    state.last_error_code = reason
    state.last_error_at = now_iso()
    return refresh_bot_mode(state)


def refresh_bot_mode(state: BotState) -> BotState:
    now = now_dt()

    if state.pause_until:
        pause_until = datetime.fromisoformat(state.pause_until)
        if now >= pause_until:
            state.protection_pause_active = False
            state.pause_reason = None
            state.pause_started_at = None
            state.pause_until = None

    candidates: list[str] = []
    if state.kill_switch_active:
        candidates.append("KILL_SWITCH")
    if state.weekly_stop_active:
        candidates.append("WEEKLY_STOP")
    if state.daily_stop_active:
        candidates.append("DAILY_STOP")
    if state.error_safe_mode_active:
        candidates.append("ERROR_SAFE_MODE")
    if state.protection_pause_active:
        candidates.append("PAUSED")
    if not candidates:
        candidates.append("ACTIVE")

    state.mode = sorted(candidates, key=lambda item: STATE_PRIORITY.index(item))[0]
    state.can_open_new_trades = state.mode == "ACTIVE"
    state.can_monitor_open_trades = True
    return state
