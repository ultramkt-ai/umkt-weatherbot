from config import Config
from models.serialization import dataclass_to_dict
from models.state import BotState
from storage.ledger_db import migrate_legacy_trade_data
from storage.json_store import atomic_write_json, read_json_file
from utils.ids import generate_session_id
from utils.time_utils import now_iso


def load_or_create_state(config: Config) -> BotState:
    config.storage.state_dir.mkdir(parents=True, exist_ok=True)
    migrate_legacy_trade_data(config)

    if config.storage.state_file.exists():
        data = read_json_file(config.storage.state_file)
        data["current_cash_usd"] = 0.0
        data["current_bankroll_usd"] = 0.0
        data["realized_pnl_total_usd"] = 0.0
        data["fees_paid_total_usd"] = 0.0
        data["equity_peak_usd"] = 0.0
        data["current_drawdown_pct"] = 0.0
        data["max_drawdown_pct"] = 0.0
        data["capital_alocado_aberto_usd"] = 0.0
        data["gross_exposure_open_usd"] = 0.0
        data["open_exposure_pct"] = 0.0
        data["open_trades_count"] = 0
        data["closed_trades_count"] = 0
        data["approved_trades_count"] = 0
        data["daily_pnl_usd"] = 0.0
        data["weekly_pnl_usd"] = 0.0
        data["open_trades"] = []
        data["open_trade_ids"] = []
        data["cluster_exposure_map_usd"] = {}
        data["cluster_trade_count_map"] = {}
        data["daily_stop_active"] = False
        data["weekly_stop_active"] = False
        data["kill_switch_active"] = False
        data["protection_pause_active"] = False
        data["pause_reason"] = None
        data["pause_started_at"] = None
        data["pause_until"] = None
        data["manual_review_required"] = False
        data["mode"] = "ACTIVE"
        data["can_open_new_trades"] = True
        return BotState(**data)

    now = now_iso()
    initial = 0.0
    return BotState(
        session_id=generate_session_id(),
        started_at=now,
        updated_at=now,
        last_cycle_started_at=None,
        last_cycle_finished_at=None,
        initial_bankroll_usd=initial,
        current_cash_usd=initial,
        current_bankroll_usd=initial,
        realized_pnl_total_usd=0.0,
        fees_paid_total_usd=0.0,
        equity_peak_usd=initial,
        current_drawdown_pct=0.0,
        max_drawdown_pct=0.0,
        capital_alocado_aberto_usd=0.0,
        gross_exposure_open_usd=0.0,
        open_exposure_pct=0.0,
        open_trades_count=0,
        closed_trades_count=0,
        approved_trades_count=0,
        rejected_markets_count=0,
        markets_scanned_today=0,
        approved_today=0,
        rejected_today=0,
        consecutive_losses=0,
        consecutive_wins=0,
    )


def save_state(config: Config, state: BotState) -> None:
    config.storage.state_dir.mkdir(parents=True, exist_ok=True)
    state.updated_at = now_iso()
    atomic_write_json(config.storage.state_file, dataclass_to_dict(state))
