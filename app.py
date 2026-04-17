from datetime import timedelta
import signal

from config import load_config
from core.monitor import monitor_open_trades
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
    previous_handler = signal.getsignal(signal.SIGALRM)
    timeout_seconds = max(0, config.runtime.cycle_timeout_seconds)
    try:
        if timeout_seconds:
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout_seconds)

        state.last_cycle_started_at = now_iso()
        state = refresh_bot_mode(state)
        closed_main_trades = []

        if state.can_open_new_trades:
            state = run_market_scan_cycle(state, config)

        if state.can_monitor_open_trades:
            state, closed_main_trades = monitor_open_trades(state, config, now_iso())

        # Monitora trades abertas e fecha posições por TP/SL/Time-out
        _, closed_trades = monitor_strategy_open_trades(config)
        if closed_trades:
            closed_ids = {trade["trade_id"] for trade in closed_trades}
            state.open_trades = [t for t in state.open_trades if t.trade_id not in closed_ids]
            state.open_trades_count = len(state.open_trades)
            state.closed_trades_count += len(closed_trades)
            state.current_cash_usd += sum(float(trade.get("gross_settlement_value_usd") or 0.0) for trade in closed_trades)
            state.realized_pnl_total_usd += sum(float(trade.get("net_pnl_abs") or 0.0) for trade in closed_trades)
            state.capital_alocado_aberto_usd = sum(t.capital_alocado_usd for t in state.open_trades)
            state.gross_exposure_open_usd = state.capital_alocado_aberto_usd
            state.current_bankroll_usd = state.current_cash_usd + state.capital_alocado_aberto_usd
            state.open_exposure_pct = (state.gross_exposure_open_usd / state.current_bankroll_usd) if state.current_bankroll_usd else 0.0

        if state.can_monitor_open_trades and closed_main_trades:
            state.last_open_trades_check_at = now_iso()

        now = now_dt()
        state.next_market_scan_at = (now + timedelta(minutes=config.scheduling.market_scan_interval_min)).isoformat()
        state.next_open_trades_check_at = (now + timedelta(minutes=config.scheduling.open_trades_check_interval_min)).isoformat()

        status_message = build_cycle_status_message(state)
        state.last_cycle_status_message = status_message
        state.last_cycle_finished_at = now_iso()
        state.last_error_code = None
        state.last_error_at = None
        save_state(config, state)

        print(status_message)
    except CycleTimeoutError:
        message = f"Run aborted: cycle timeout after {timeout_seconds}s."
        state.last_error_code = "cycle_timeout"
        state.last_error_at = now_iso()
        state.last_cycle_finished_at = now_iso()
        state.last_cycle_status_message = message
        save_state(config, state)
        log_runtime_event(config, {
            "timestamp": now_iso(),
            "event": "market_scan_cycle_timeout",
            "timeout_seconds": timeout_seconds,
            "message": message,
        })
        print(message)
        raise SystemExit(124)
    except Exception:
        state.last_error_code = "cycle_runtime_exception"
        state.last_error_at = now_iso()
        save_state(config, state)
        raise
    finally:
        if timeout_seconds:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)
        lock.release()


if __name__ == "__main__":
    main()
