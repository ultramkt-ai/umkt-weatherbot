from __future__ import annotations

import json
from pathlib import Path

from config import Config
from models.serialization import dataclass_to_dict
from models.state import BotState
from models.trade import OpenTrade
from storage.ledger_db import build_strategy_snapshot, list_open_trade_models, migrate_legacy_trade_data
from storage.json_store import atomic_write_json, read_json_file
from storage.state_store import load_or_create_state
from utils.ids import generate_session_id
from utils.math_utils import calculate_open_exposure_pct
from utils.time_utils import now_iso


def _strategy_state_path(config: Config, strategy_id: str) -> Path:
    return config.storage.state_dir / "strategies" / f"{strategy_id.lower()}_state.json"


def load_or_create_strategy_state(config: Config, strategy_id: str) -> BotState:
    migrate_legacy_trade_data(config)
    path = _strategy_state_path(config, strategy_id)
    if path.exists():
        data = read_json_file(path)
        snapshot = build_strategy_snapshot(config, strategy_id, data.get("initial_bankroll_usd", config.risk.initial_bankroll_usd))
        data["open_trades"] = list_open_trade_models(config, strategy_id)
        data["open_trade_ids"] = [trade.trade_id for trade in data["open_trades"]]
        for key in [
            "open_trades_count",
            "closed_trades_count",
            "approved_trades_count",
            "approved_today",
            "capital_alocado_aberto_usd",
            "gross_exposure_open_usd",
            "realized_pnl_total_usd",
            "daily_pnl_usd",
            "weekly_pnl_usd",
            "current_cash_usd",
            "current_bankroll_usd",
            "open_exposure_pct",
            "cluster_exposure_map_usd",
            "cluster_trade_count_map",
        ]:
            data[key] = snapshot[key]
        state = BotState(**data)
        original_snapshot = dataclass_to_dict(state)
        normalized = _normalize_strategy_state(state)
        if dataclass_to_dict(normalized) != original_snapshot:
            save_strategy_state(config, strategy_id, normalized)
        return normalized
    base_state = load_or_create_state(config)
    now = now_iso()
    initial = config.risk.initial_bankroll_usd
    state = BotState(
        session_id=f"strategy:{strategy_id.lower()}:{generate_session_id()}",
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
        mode=base_state.mode,
        can_open_new_trades=base_state.can_open_new_trades,
        can_monitor_open_trades=base_state.can_monitor_open_trades,
    )
    save_strategy_state(config, strategy_id, state)
    return state


def save_strategy_state(config: Config, strategy_id: str, state: BotState) -> None:
    path = _strategy_state_path(config, strategy_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, dataclass_to_dict(state))


def _normalize_strategy_state(state: BotState) -> BotState:
    unique_trades: list[OpenTrade] = []
    seen_keys: set[str] = set()

    for trade in state.open_trades:
        key = trade.token_id or f"{trade.market_id}:{trade.side}:{trade.outcome_label}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique_trades.append(trade)

    state.open_trades = unique_trades
    state.open_trade_ids = [trade.trade_id for trade in unique_trades]
    state.open_trades_count = len(unique_trades)
    state.capital_alocado_aberto_usd = sum(trade.capital_alocado_usd for trade in unique_trades)
    state.gross_exposure_open_usd = sum(trade.capital_alocado_usd for trade in unique_trades)
    state.current_cash_usd = max(
        0.0,
        state.initial_bankroll_usd + state.realized_pnl_total_usd - sum(trade.net_cost_usd for trade in unique_trades),
    )
    state.current_bankroll_usd = state.current_cash_usd + state.capital_alocado_aberto_usd
    state.open_exposure_pct = calculate_open_exposure_pct(state.capital_alocado_aberto_usd, state.current_bankroll_usd)
    state.cluster_exposure_map_usd = {}
    state.cluster_trade_count_map = {}
    for trade in unique_trades:
        state.cluster_exposure_map_usd[trade.cluster_id] = state.cluster_exposure_map_usd.get(trade.cluster_id, 0.0) + trade.capital_alocado_usd
        state.cluster_trade_count_map[trade.cluster_id] = state.cluster_trade_count_map.get(trade.cluster_id, 0) + 1
    return state


def strategy_log_path(config: Config, strategy_id: str, filename: str) -> Path:
    path = config.storage.logs_dir / "strategies" / strategy_id.lower() / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def strategy_report_path(config: Config, strategy_id: str, filename: str) -> Path:
    path = config.storage.reports_dir / "strategies" / strategy_id.lower() / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
