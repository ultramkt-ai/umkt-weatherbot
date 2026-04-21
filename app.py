from datetime import datetime, timedelta
import signal

from config import load_config
from data.polymarket_clob_client import ClobRequestError
from core.strategy_monitor import monitor_strategy_open_trades
from core.pipeline import run_market_scan_cycle
from core.state_machine import refresh_bot_mode
from messaging.status_publisher import build_cycle_status_message
from storage.journal import log_runtime_event
from storage.state_store import load_or_create_state, save_state
from utils.process_lock import ProcessLock
from utils.time_utils import now_dt, now_iso


class CycleTimeoutError(TimeoutError):
    pass


def _timeout_handler(signum, frame):
    raise CycleTimeoutError("Market scan cycle exceeded the configured timeout.")


def _is_due(next_run_iso: str | None, now_value: datetime) -> bool:
    if not next_run_iso:
        return True
    try:
        return datetime.fromisoformat(next_run_iso) <= now_value
    except Exception:
        return True


def _normalize_scheduler_state(state, config, now: datetime):
    today = now.date()

    def _safe_parse(value: str | None):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    last_scan_dt = _safe_parse(state.last_market_scan_at)
    next_scan_dt = _safe_parse(state.next_market_scan_at)
    last_open_dt = _safe_parse(state.last_open_trades_check_at)
    next_open_dt = _safe_parse(state.next_open_trades_check_at)

    if last_scan_dt and last_scan_dt.date() != today:
        state.last_market_scan_at = None
    if next_scan_dt and next_scan_dt.date() != today:
        state.next_market_scan_at = now.isoformat()

    if last_open_dt and last_open_dt > now:
        state.last_open_trades_check_at = None
    if next_open_dt and next_open_dt > now:
        state.next_open_trades_check_at = now.isoformat()

    if state.next_market_scan_at and not _is_due(state.next_market_scan_at, now):
        parsed = _safe_parse(state.next_market_scan_at)
        if parsed and parsed.date() != today:
            state.next_market_scan_at = now.isoformat()

    if state.last_daily_reset_date != today.isoformat():
        state.last_market_scan_at = None
        state.next_market_scan_at = now.isoformat()

    return state


def main() -> None:
    config = load_config()
    lock = ProcessLock(config.storage.state_dir / "market_scan.lock")
    if not lock.acquire():
        message = "Run skipped: another market scan cycle is still active."
        log_runtime_event(config, {
            "timestamp": now_iso(),
            "event": "market_scan_skipped_due_to_lock",
            "message": message,
        })
        print(message)
        return

    state = load_or_create_state(config)
    cycle_started_at = now_dt()
    previous_handler = signal.getsignal(signal.SIGALRM)
    timeout_seconds = max(0, config.runtime.cycle_timeout_seconds)
    try:
        if timeout_seconds:
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout_seconds)

        state.last_cycle_started_at = cycle_started_at.isoformat()
        state = _normalize_scheduler_state(state, config, now_dt())
        state = refresh_bot_mode(state)
        log_runtime_event(config, {
            "timestamp": cycle_started_at.isoformat(),
            "event": "market_scan_cycle_started",
            "cycle_timeout_seconds": timeout_seconds,
        })
        closed_trades = []
        now = now_dt()
        market_scan_due = _is_due(state.next_market_scan_at, now)
        open_trades_due = state.can_monitor_open_trades and _is_due(state.next_open_trades_check_at, now)

        if market_scan_due:
            state = run_market_scan_cycle(state, config)
            state.last_market_scan_at = now_iso()

        if open_trades_due:
            _, closed_trades = monitor_strategy_open_trades(config)
            state.last_open_trades_check_at = now_iso()

        now = now_dt()
        if market_scan_due:
            state.next_market_scan_at = (now + timedelta(minutes=config.scheduling.market_scan_interval_min)).isoformat()
        if open_trades_due:
            state.next_open_trades_check_at = (now + timedelta(minutes=config.scheduling.open_trades_check_interval_min)).isoformat()

        status_message = build_cycle_status_message(state)
        state.last_cycle_status_message = status_message
        finished_at = now_dt()
        state.last_cycle_finished_at = finished_at.isoformat()
        state.last_cycle_duration_seconds = round((finished_at - cycle_started_at).total_seconds(), 3)
        state.last_error_code = None
        state.last_error_at = None
        save_state(config, state)
        log_runtime_event(config, {
            "timestamp": finished_at.isoformat(),
            "event": "market_scan_cycle_completed",
            "duration_seconds": state.last_cycle_duration_seconds,
            "market_scan_due": market_scan_due,
            "open_trades_due": open_trades_due,
            "closed_trades_count": len(closed_trades),
            "markets_scanned_today": state.markets_scanned_today,
            "approved_today": state.approved_today,
            "rejected_today": state.rejected_today,
        })

        print(status_message)
    except CycleTimeoutError:
        message = f"Run aborted: cycle timeout after {timeout_seconds}s."
        timeout_at = now_dt()
        state.last_error_code = "cycle_timeout"
        state.last_error_at = timeout_at.isoformat()
        state.last_cycle_finished_at = timeout_at.isoformat()
        state.last_cycle_status_message = message
        state.next_market_scan_at = (timeout_at + timedelta(minutes=config.scheduling.market_scan_interval_min)).isoformat()
        state.next_open_trades_check_at = (timeout_at + timedelta(minutes=config.scheduling.open_trades_check_interval_min)).isoformat()
        save_state(config, state)
        log_runtime_event(config, {
            "timestamp": timeout_at.isoformat(),
            "event": "market_scan_cycle_timeout",
            "timeout_seconds": timeout_seconds,
            "message": message,
        })
        print(message)
        raise SystemExit(124)
    except ClobRequestError as exc:
        error_at = now_dt().isoformat()
        state.last_error_code = f"clob_fetch_failed:{exc.reason}"
        state.last_error_at = error_at
        state.last_cycle_finished_at = error_at
        state.last_cycle_status_message = (
            f"Run aborted: CLOB fetch failed after {exc.attempts} attempt(s), reason={exc.reason}."
        )
        save_state(config, state)
        log_runtime_event(config, {
            "timestamp": error_at,
            "event": "market_scan_cycle_aborted_clob_failure",
            "reason": exc.reason,
            "attempts": exc.attempts,
            "retryable": exc.retryable,
            "endpoint": exc.endpoint,
            "original_error": exc.original_error,
            "message": str(exc),
        })
        raise
    except Exception as exc:
        error_at = now_dt().isoformat()
        state.last_error_code = "cycle_runtime_exception"
        state.last_error_at = error_at
        state.last_cycle_finished_at = error_at
        save_state(config, state)
        log_runtime_event(config, {
            "timestamp": error_at,
            "event": "market_scan_cycle_runtime_exception",
            "error_type": exc.__class__.__name__,
            "message": str(exc),
        })
        raise
    finally:
        if timeout_seconds:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)
        lock.release()


if __name__ == "__main__":
    main()
