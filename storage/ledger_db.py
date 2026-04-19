from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config import Config
from models.trade import OpenTrade
from utils.math_utils import calculate_open_exposure_pct
from utils.time_utils import now_dt

RUNTIME_STATE_ID = "WEATHER_BOT_MAIN"
COPYTRADING_STRATEGY_ID = "COPYTRADING_COLDMATH"
_LEGACY_MIGRATION_DONE = False


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def ensure_schema(config: Config) -> None:
    with _connect(config.storage.ledger_db_file) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trades (
                strategy_id TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                market_id TEXT,
                parent_slug TEXT,
                outcome_label TEXT,
                bucket_type TEXT,
                bucket_low REAL,
                bucket_high REAL,
                token_id TEXT,
                entry_time TEXT,
                side TEXT,
                entry_price REAL,
                capital_alocado_usd REAL,
                contracts_qty REAL,
                gross_cost_usd REAL,
                fees_paid_usd REAL,
                net_cost_usd REAL,
                max_loss_usd REAL,
                max_profit_usd REAL,
                risk_pct_of_bankroll REAL,
                score REAL,
                score_band TEXT,
                weather_type TEXT,
                city TEXT,
                state TEXT,
                cluster_id TEXT,
                approval_summary TEXT,
                market_snapshot_at_entry TEXT,
                weather_snapshot_at_entry TEXT,
                status TEXT NOT NULL DEFAULT 'OPEN',
                exit_time TEXT,
                resolution_time TEXT,
                resolution_value REAL,
                gross_settlement_value_usd REAL,
                net_pnl_abs REAL,
                roi_on_allocated_capital REAL,
                result TEXT,
                hold_duration_hours REAL,
                resolution_source TEXT,
                resolution_source_value TEXT,
                drawdown_after_close REAL,
                exit_reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (strategy_id, trade_id)
            );
            CREATE INDEX IF NOT EXISTS idx_trades_strategy_status ON trades(strategy_id, status);
            CREATE INDEX IF NOT EXISTS idx_trades_strategy_entry_time ON trades(strategy_id, entry_time);
            """
        )


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _runtime_tz(config: Config) -> ZoneInfo:
    try:
        return ZoneInfo(config.runtime.timezone)
    except Exception:
        return ZoneInfo("America/Sao_Paulo")


def _parse_trade_dt(value: Any, tz: ZoneInfo) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _week_start_date(now: datetime) -> datetime.date:
    return now.date() - timedelta(days=now.date().isoweekday() - 1)


def record_open_trade(config: Config, strategy_id: str, trade: dict[str, Any]) -> None:
    ensure_schema(config)
    with _connect(config.storage.ledger_db_file) as conn:
        conn.execute(
            """
            INSERT INTO trades (
                strategy_id, trade_id, market_id, parent_slug, outcome_label, bucket_type, bucket_low, bucket_high,
                token_id, entry_time, side, entry_price, capital_alocado_usd, contracts_qty, gross_cost_usd,
                fees_paid_usd, net_cost_usd, max_loss_usd, max_profit_usd, risk_pct_of_bankroll, score,
                score_band, weather_type, city, state, cluster_id, approval_summary,
                market_snapshot_at_entry, weather_snapshot_at_entry, status, updated_at
            ) VALUES (
                :strategy_id, :trade_id, :market_id, :parent_slug, :outcome_label, :bucket_type, :bucket_low, :bucket_high,
                :token_id, :entry_time, :side, :entry_price, :capital_alocado_usd, :contracts_qty, :gross_cost_usd,
                :fees_paid_usd, :net_cost_usd, :max_loss_usd, :max_profit_usd, :risk_pct_of_bankroll, :score,
                :score_band, :weather_type, :city, :state, :cluster_id, :approval_summary,
                :market_snapshot_at_entry, :weather_snapshot_at_entry, 'OPEN', CURRENT_TIMESTAMP
            )
            ON CONFLICT(strategy_id, trade_id) DO UPDATE SET
                market_id=excluded.market_id,
                parent_slug=excluded.parent_slug,
                outcome_label=excluded.outcome_label,
                token_id=excluded.token_id,
                entry_time=excluded.entry_time,
                side=excluded.side,
                entry_price=excluded.entry_price,
                capital_alocado_usd=excluded.capital_alocado_usd,
                contracts_qty=excluded.contracts_qty,
                gross_cost_usd=excluded.gross_cost_usd,
                fees_paid_usd=excluded.fees_paid_usd,
                net_cost_usd=excluded.net_cost_usd,
                max_loss_usd=excluded.max_loss_usd,
                max_profit_usd=excluded.max_profit_usd,
                risk_pct_of_bankroll=excluded.risk_pct_of_bankroll,
                score=excluded.score,
                score_band=excluded.score_band,
                weather_type=excluded.weather_type,
                city=excluded.city,
                state=excluded.state,
                cluster_id=excluded.cluster_id,
                approval_summary=excluded.approval_summary,
                market_snapshot_at_entry=excluded.market_snapshot_at_entry,
                weather_snapshot_at_entry=excluded.weather_snapshot_at_entry,
                status='OPEN',
                updated_at=CURRENT_TIMESTAMP
            """,
            {
                **trade,
                "strategy_id": strategy_id,
                "market_snapshot_at_entry": _json(trade.get("market_snapshot_at_entry")),
                "weather_snapshot_at_entry": _json(trade.get("weather_snapshot_at_entry")),
            },
        )


def record_closed_trade(config: Config, strategy_id: str, trade: dict[str, Any]) -> None:
    ensure_schema(config)
    with _connect(config.storage.ledger_db_file) as conn:
        conn.execute(
            """
            UPDATE trades SET
                status='CLOSED',
                exit_time=:exit_time,
                resolution_time=:resolution_time,
                resolution_value=:resolution_value,
                gross_settlement_value_usd=:gross_settlement_value_usd,
                net_pnl_abs=:net_pnl_abs,
                roi_on_allocated_capital=:roi_on_allocated_capital,
                result=:result,
                hold_duration_hours=:hold_duration_hours,
                resolution_source=:resolution_source,
                resolution_source_value=:resolution_source_value,
                drawdown_after_close=:drawdown_after_close,
                exit_reason=:exit_reason,
                updated_at=CURRENT_TIMESTAMP
            WHERE strategy_id=:strategy_id AND trade_id=:trade_id
            """,
            {
                **trade,
                "strategy_id": strategy_id,
                "resolution_source_value": _json(trade.get("resolution_source_value")),
            },
        )


def list_open_trades(config: Config, strategy_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    ensure_schema(config)
    sql = "SELECT * FROM trades WHERE strategy_id=? AND status='OPEN'"
    params: list[Any] = [strategy_id]
    if strategy_id == COPYTRADING_STRATEGY_ID:
        sql += " AND trade_id NOT LIKE 'position:%'"
    sql += " ORDER BY entry_time ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    with _connect(config.storage.ledger_db_file) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_trade_dict(row) for row in rows]


def list_open_positions(config: Config, strategy_id: str) -> list[dict[str, Any]]:
    open_trades = list_open_trades(config, strategy_id)
    if strategy_id != COPYTRADING_STRATEGY_ID:
        return open_trades

    grouped: dict[str, dict[str, Any]] = {}
    for item in open_trades:
        key = str(item.get("token_id") or f"{item.get('market_id')}:{item.get('side')}")
        capital = float(item.get("capital_alocado_usd") or 0.0)
        contracts = float(item.get("contracts_qty") or 0.0)
        gross_cost = float(item.get("gross_cost_usd") or 0.0)
        fees = float(item.get("fees_paid_usd") or 0.0)
        net_cost = float(item.get("net_cost_usd") or 0.0)
        if key not in grouped:
            grouped[key] = {
                **item,
                "_fills": 0,
                "capital_alocado_usd": 0.0,
                "contracts_qty": 0.0,
                "gross_cost_usd": 0.0,
                "fees_paid_usd": 0.0,
                "net_cost_usd": 0.0,
                "max_loss_usd": 0.0,
                "max_profit_usd": 0.0,
            }
            grouped[key]["trade_id"] = f"position:{strategy_id}:{key}"
            grouped[key]["approval_summary"] = f"Posição agregada de {strategy_id}"
        else:
            grouped[key]["entry_time"] = min(grouped[key].get("entry_time") or item.get("entry_time"), item.get("entry_time"))
        grouped[key]["_fills"] += 1
        grouped[key]["capital_alocado_usd"] = float(grouped[key].get("capital_alocado_usd") or 0.0) + capital
        grouped[key]["contracts_qty"] = float(grouped[key].get("contracts_qty") or 0.0) + contracts
        grouped[key]["gross_cost_usd"] = float(grouped[key].get("gross_cost_usd") or 0.0) + gross_cost
        grouped[key]["fees_paid_usd"] = float(grouped[key].get("fees_paid_usd") or 0.0) + fees
        grouped[key]["net_cost_usd"] = float(grouped[key].get("net_cost_usd") or 0.0) + net_cost
        grouped[key]["max_loss_usd"] = grouped[key]["net_cost_usd"]
        if grouped[key]["contracts_qty"] > 0:
            grouped[key]["entry_price"] = grouped[key]["net_cost_usd"] / grouped[key]["contracts_qty"]
            grouped[key]["max_profit_usd"] = max(0.0, grouped[key]["contracts_qty"] - grouped[key]["net_cost_usd"])
        grouped[key]["market_snapshot_at_entry"] = {"fills": grouped[key]["_fills"]}
    return list(grouped.values())


def list_closed_trades(config: Config, strategy_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    ensure_schema(config)
    sql = "SELECT * FROM trades WHERE strategy_id=? AND status='CLOSED' ORDER BY COALESCE(exit_time, updated_at) DESC"
    params: list[Any] = [strategy_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    with _connect(config.storage.ledger_db_file) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_trade_dict(row) for row in rows]


def build_strategy_snapshot(config: Config, strategy_id: str, initial_bankroll_usd: float) -> dict[str, Any]:
    raw_open_trades = list_open_trades(config, strategy_id)
    open_trades = list_open_positions(config, strategy_id)
    closed_trades = list_closed_trades(config, strategy_id)
    capital_open = sum(float(item.get("capital_alocado_usd") or 0.0) for item in open_trades)
    realized_pnl = sum(float(item.get("net_pnl_abs") or 0.0) for item in closed_trades)
    tz = _runtime_tz(config)
    now = now_dt().astimezone(tz)
    today = now.date()
    week_start = _week_start_date(now)
    daily_pnl = 0.0
    weekly_pnl = 0.0
    for item in closed_trades:
        exit_time = item.get("exit_time") or item.get("resolution_time")
        exit_dt = _parse_trade_dt(exit_time, tz)
        if not exit_dt:
            continue
        pnl = float(item.get("net_pnl_abs") or 0.0)
        if exit_dt.date() == today:
            daily_pnl += pnl
        if week_start <= exit_dt.date() <= today:
            weekly_pnl += pnl
    cash = max(0.0, initial_bankroll_usd - sum(float(item.get("net_cost_usd") or 0.0) for item in open_trades) + realized_pnl)
    bankroll = cash + capital_open
    cluster_exposure: dict[str, float] = {}
    cluster_count: dict[str, int] = {}
    for item in open_trades:
        cluster_id = str(item.get("cluster_id") or "unknown")
        cluster_exposure[cluster_id] = cluster_exposure.get(cluster_id, 0.0) + float(item.get("capital_alocado_usd") or 0.0)
        cluster_count[cluster_id] = cluster_count.get(cluster_id, 0) + 1
    return {
        "open_trades": open_trades,
        "closed_trades": closed_trades,
        "open_trades_count": len(open_trades),
        "raw_open_trades_count": len(raw_open_trades),
        "closed_trades_count": len(closed_trades),
        "approved_trades_count": len(raw_open_trades) + len(closed_trades),
        "approved_today": len(raw_open_trades),
        "capital_alocado_aberto_usd": capital_open,
        "gross_exposure_open_usd": capital_open,
        "realized_pnl_total_usd": realized_pnl,
        "daily_pnl_usd": daily_pnl,
        "weekly_pnl_usd": weekly_pnl,
        "current_cash_usd": cash,
        "current_bankroll_usd": bankroll,
        "open_exposure_pct": calculate_open_exposure_pct(capital_open, bankroll),
        "cluster_exposure_map_usd": cluster_exposure,
        "cluster_trade_count_map": cluster_count,
    }




def migrate_legacy_trade_data(config: Config) -> None:
    global _LEGACY_MIGRATION_DONE
    if _LEGACY_MIGRATION_DONE:
        return

    ensure_schema(config)
    from storage.json_store import read_json_file

    main_state = read_json_file(config.storage.state_file, default={})
    for trade in main_state.get("open_trades", []) or []:
        record_open_trade(config, RUNTIME_STATE_ID, trade)

    strategies_dir = config.storage.state_dir / "strategies"
    if strategies_dir.exists():
        for path in strategies_dir.glob("*_state.json"):
            strategy_id = path.stem.replace("_state", "").upper()
            data = read_json_file(path, default={})
            for trade in data.get("open_trades", []) or []:
                record_open_trade(config, strategy_id, trade)

    copy_state = read_json_file(config.storage.state_dir / "copytrading_competitor_state.json", default={})
    bot_state = copy_state.get("bot_state", {})
    for trade in bot_state.get("open_trades", []) or copy_state.get("open_positions", []) or []:
        record_open_trade(config, COPYTRADING_STRATEGY_ID, trade)
    for trade in copy_state.get("closed_positions", []) or []:
        if trade.get("trade_id"):
            record_closed_trade(config, COPYTRADING_STRATEGY_ID, trade)
    normalize_copytrading_fills(config)
    _LEGACY_MIGRATION_DONE = True


def normalize_copytrading_fills(config: Config) -> None:
    ensure_schema(config)
    with _connect(config.storage.ledger_db_file) as conn:
        conn.execute("DELETE FROM trades WHERE strategy_id=? AND trade_id LIKE 'position:%'", (COPYTRADING_STRATEGY_ID,))
        rows = conn.execute("SELECT trade_id, market_snapshot_at_entry FROM trades WHERE strategy_id=? AND status='OPEN'", (COPYTRADING_STRATEGY_ID,)).fetchall()
        for row in rows:
            snapshot_raw = row[1]
            if not snapshot_raw:
                continue
            try:
                snapshot = json.loads(snapshot_raw)
            except Exception:
                continue
            size = float(snapshot.get("size") or 0.0)
            price = float(snapshot.get("price") or 0.0)
            origin_notional = size * price
            if size <= 0 or price <= 0 or origin_notional <= 0:
                continue
            local_cap_usd = max(0.0, config.runtime.copytrading_max_fill_brl / max(config.runtime.usd_brl_rate, 0.0001))
            local_notional = min(origin_notional, local_cap_usd)
            local_contracts = (local_notional / price) if price > 0 else 0.0
            snapshot["origin_contracts_qty"] = size
            snapshot["origin_notional_usd"] = origin_notional
            snapshot["local_notional_usd"] = local_notional
            snapshot["copy_ratio"] = (local_notional / origin_notional) if origin_notional > 0 else 0.0
            snapshot["copy_mode"] = "fill_proportional_capped_brl"
            snapshot["local_cap_brl"] = config.runtime.copytrading_max_fill_brl
            conn.execute(
                """
                UPDATE trades
                SET contracts_qty=?,
                    entry_price=?,
                    outcome_label=?,
                    side='MIRROR',
                    capital_alocado_usd=?,
                    gross_cost_usd=?,
                    net_cost_usd=?,
                    max_loss_usd=?,
                    max_profit_usd=?,
                    market_snapshot_at_entry=?,
                    risk_pct_of_bankroll=0.0,
                    updated_at=CURRENT_TIMESTAMP
                WHERE strategy_id=? AND trade_id=?
                """,
                (local_contracts, price, str(snapshot.get("outcome") or snapshot.get("title") or "UNKNOWN"), local_notional, local_notional, local_notional, local_notional, max(0.0, local_contracts - local_notional), json.dumps(snapshot, ensure_ascii=False, sort_keys=True), COPYTRADING_STRATEGY_ID, row[0]),
            )


def _row_to_trade_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    for key in ["market_snapshot_at_entry", "weather_snapshot_at_entry", "resolution_source_value"]:
        raw = item.get(key)
        if raw:
            try:
                item[key] = json.loads(raw)
            except Exception:
                pass
    return item


def list_open_trade_models(config: Config, strategy_id: str) -> list[OpenTrade]:
    allowed = set(OpenTrade.__dataclass_fields__.keys())
    return [OpenTrade(**{k: v for k, v in item.items() if k in allowed}) for item in list_open_positions(config, strategy_id)]
