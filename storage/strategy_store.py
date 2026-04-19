from __future__ import annotations

import json
from pathlib import Path

from config import Config
from core.risk_events import refresh_strategy_risk_state
from models.serialization import dataclass_to_dict
from models.state import BotState
from models.trade import OpenTrade
from storage.ledger_db import build_strategy_snapshot, list_open_trade_models, migrate_legacy_trade_data
from storage.json_store import atomic_write_json, read_json_file
from utils.ids import generate_session_id
from utils.math_utils import calculate_drawdown_pct, calculate_open_exposure_pct
from utils.time_utils import now_iso


def _strategy_state_path(config: Config, strategy_id: str) -> Path:
    return config.storage.state_dir / "strategies" / f"{strategy_id.lower()}_state.json"


def load_or_create_strategy_state(config: Config, strategy_id: str) -> BotState:
    migrate_legacy_trade_data(config)
    path = _strategy_state_path(config, strategy_id)
    if path.exists():
        data = read_json_file(path)
        initial_bankroll = float(data.get("initial_bankroll_usd", config.risk.initial_bankroll_usd))
        snapshot = build_strategy_snapshot(config, strategy_id, initial_bankroll)
        data["open_trades"] = list_open_trade_models(config, strategy_id)
        data["open_trade_ids"] = [trade.trade_id for trade in data["open_trades"]]
        data["initial_bankroll_usd"] = initial_bankroll
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
        normalized = _normalize_strategy_state(state, config, snapshot)
        if dataclass_to_dict(normalized) != original_snapshot:
            save_strategy_state(config, strategy_id, normalized)
        return normalized
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
        mode="ACTIVE",
        can_open_new_trades=True,
        can_monitor_open_trades=True,
    )
    save_strategy_state(config, strategy_id, state)
    return state


def save_strategy_state(config: Config, strategy_id: str, state: BotState) -> None:
    path = _strategy_state_path(config, strategy_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_strategy_state(state, config)
    atomic_write_json(path, dataclass_to_dict(normalized))


def _normalize_strategy_state(state: BotState, config: Config, snapshot: dict | None = None) -> BotState:
    snapshot = snapshot or {
        "closed_trades": [],
        "realized_pnl_total_usd": state.realized_pnl_total_usd,
        "daily_pnl_usd": state.daily_pnl_usd,
        "weekly_pnl_usd": state.weekly_pnl_usd,
        "approved_trades_count": state.approved_trades_count,
        "approved_today": state.approved_today,
    }
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
    state.closed_trades_count = len(snapshot.get("closed_trades", []))
    state.approved_trades_count = int(snapshot.get("approved_trades_count", state.approved_trades_count))
    state.approved_today = int(snapshot.get("approved_today", state.approved_today))
    state.capital_alocado_aberto_usd = sum(trade.capital_alocado_usd for trade in unique_trades)
    state.gross_exposure_open_usd = sum(trade.capital_alocado_usd for trade in unique_trades)
    state.realized_pnl_total_usd = float(snapshot.get("realized_pnl_total_usd", state.realized_pnl_total_usd))
    state.daily_pnl_usd = float(snapshot.get("daily_pnl_usd", state.daily_pnl_usd))
    state.weekly_pnl_usd = float(snapshot.get("weekly_pnl_usd", state.weekly_pnl_usd))
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

    closed_trades = snapshot.get("closed_trades", [])
    rolling_equity = state.initial_bankroll_usd
    equity_peak = max(state.initial_bankroll_usd, rolling_equity)
    max_drawdown_pct = 0.0
    last_results: list[str] = []
    consecutive_wins = 0
    consecutive_losses = 0
    chronological_closed = sorted(
        closed_trades,
        key=lambda row: str(row.get("exit_time") or row.get("resolution_time") or row.get("entry_time") or ""),
    )
    for trade in chronological_closed:
        pnl = float(trade.get("net_pnl_abs") or 0.0)
        rolling_equity += pnl
        equity_peak = max(equity_peak, rolling_equity)
        drawdown = calculate_drawdown_pct(rolling_equity, equity_peak)
        max_drawdown_pct = max(max_drawdown_pct, drawdown)
        result = str(trade.get("result") or "")
        if result == "WIN":
            consecutive_wins += 1
            consecutive_losses = 0
            last_results.append("W")
        elif result == "LOSS":
            consecutive_losses += 1
            consecutive_wins = 0
            last_results.append("L")

    state.equity_peak_usd = equity_peak
    state.current_drawdown_pct = calculate_drawdown_pct(state.current_bankroll_usd, state.equity_peak_usd)
    state.max_drawdown_pct = max_drawdown_pct if chronological_closed else state.current_drawdown_pct
    state.last_10_closed_results = last_results[-10:]
    state.consecutive_wins = consecutive_wins
    state.consecutive_losses = consecutive_losses
    state = refresh_strategy_risk_state(state, config)
    return state


def strategy_log_path(config: Config, strategy_id: str, filename: str) -> Path:
    path = config.storage.logs_dir / "strategies" / strategy_id.lower() / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def strategy_report_path(config: Config, strategy_id: str, filename: str) -> Path:
    path = config.storage.reports_dir / "strategies" / strategy_id.lower() / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
