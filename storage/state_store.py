import json

from config import Config
from models.serialization import dataclass_to_dict
from models.state import BotState
from models.trade import OpenTrade
from storage.ledger_db import MAIN_STRATEGY_ID, build_strategy_snapshot, list_open_trade_models, migrate_legacy_trade_data
from storage.json_store import atomic_write_json, read_json_file
from utils.ids import generate_session_id
from utils.time_utils import now_iso


def _restore_open_trades(raw_open_trades: list[dict]) -> list[OpenTrade]:
    return [OpenTrade(**item) for item in raw_open_trades]


def load_or_create_state(config: Config) -> BotState:
    config.storage.state_dir.mkdir(parents=True, exist_ok=True)
    migrate_legacy_trade_data(config)

    if config.storage.state_file.exists():
        data = read_json_file(config.storage.state_file)
        snapshot = build_strategy_snapshot(config, MAIN_STRATEGY_ID, data.get("initial_bankroll_usd", config.risk.initial_bankroll_usd))
        data["open_trades"] = list_open_trade_models(config, MAIN_STRATEGY_ID)
        data["open_trade_ids"] = [trade.trade_id for trade in data["open_trades"]]
        data["open_trades_count"] = snapshot["open_trades_count"]
        data["closed_trades_count"] = snapshot["closed_trades_count"]
        data["approved_trades_count"] = snapshot["approved_trades_count"]
        data["approved_today"] = snapshot["approved_today"]
        data["capital_alocado_aberto_usd"] = snapshot["capital_alocado_aberto_usd"]
        data["gross_exposure_open_usd"] = snapshot["gross_exposure_open_usd"]
        data["realized_pnl_total_usd"] = snapshot["realized_pnl_total_usd"]
        data["daily_pnl_usd"] = snapshot["daily_pnl_usd"]
        data["weekly_pnl_usd"] = snapshot["weekly_pnl_usd"]
        data["current_cash_usd"] = snapshot["current_cash_usd"]
        data["current_bankroll_usd"] = snapshot["current_bankroll_usd"]
        data["open_exposure_pct"] = snapshot["open_exposure_pct"]
        data["cluster_exposure_map_usd"] = snapshot["cluster_exposure_map_usd"]
        data["cluster_trade_count_map"] = snapshot["cluster_trade_count_map"]
        return BotState(**data)

    now = now_iso()
    initial = config.risk.initial_bankroll_usd
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
