from __future__ import annotations

from typing import Any

from config import Config
from storage.ledger_db import record_closed_trade, record_open_trade
from storage.jsonl_store import append_jsonl
from storage.strategy_store import strategy_log_path


def log_strategy_decision(config: Config, strategy_id: str, payload: dict[str, Any]) -> None:
    append_jsonl(strategy_log_path(config, strategy_id, "decisions.jsonl"), payload)


def log_strategy_open_trade(config: Config, strategy_id: str, payload: dict[str, Any]) -> None:
    append_jsonl(strategy_log_path(config, strategy_id, "open_trades.jsonl"), payload)
    record_open_trade(config, strategy_id, payload)


def log_strategy_closed_trade(config: Config, strategy_id: str, payload: dict[str, Any]) -> None:
    append_jsonl(strategy_log_path(config, strategy_id, "closed_trades.jsonl"), payload)
    record_closed_trade(config, strategy_id, payload)


def log_strategy_blocked_close_attempt(config: Config, strategy_id: str, payload: dict[str, Any]) -> None:
    append_jsonl(strategy_log_path(config, strategy_id, "blocked_close_attempts.jsonl"), payload)


def log_strategy_cycle(config: Config, strategy_id: str, payload: dict[str, Any]) -> None:
    append_jsonl(strategy_log_path(config, strategy_id, "cycles.jsonl"), payload)


def log_strategy_error(config: Config, strategy_id: str, payload: dict[str, Any]) -> None:
    append_jsonl(strategy_log_path(config, strategy_id, "errors.jsonl"), payload)
