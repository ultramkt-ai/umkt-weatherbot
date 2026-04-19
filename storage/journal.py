from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from config import Config
from storage.jsonl_store import append_jsonl


def _to_payload(item: Any) -> dict:
    if is_dataclass(item):
        return asdict(item)
    if isinstance(item, dict):
        return item
    raise TypeError("Unsupported payload type for journal")


def log_market_candidate(config: Config, payload: Any) -> None:
    append_jsonl(config.storage.logs_dir / "market_candidates.jsonl", _to_payload(payload))


def log_decision(config: Config, payload: Any) -> None:
    append_jsonl(config.storage.logs_dir / "trade_decisions.jsonl", _to_payload(payload))


def log_rejection(config: Config, payload: Any) -> None:
    append_jsonl(config.storage.logs_dir / "rejections.jsonl", _to_payload(payload))


def log_open_trade(config: Config, payload: Any) -> None:
    normalized = _to_payload(payload)
    append_jsonl(config.storage.trades_dir / "open_trades.jsonl", normalized)


def log_closed_trade(config: Config, payload: Any) -> None:
    normalized = _to_payload(payload)
    append_jsonl(config.storage.trades_dir / "closed_trades.jsonl", normalized)


def log_risk_event(config: Config, payload: Any) -> None:
    append_jsonl(config.storage.logs_dir / "risk_events.jsonl", _to_payload(payload))


def log_watchlist_candidate(config: Config, payload: Any) -> None:
    append_jsonl(config.storage.logs_dir / "watchlist_candidates.jsonl", _to_payload(payload))


def log_operable_candidate(config: Config, payload: Any) -> None:
    append_jsonl(config.storage.logs_dir / "operable_candidates.jsonl", _to_payload(payload))


def log_weather_failure(config: Config, payload: Any) -> None:
    append_jsonl(config.storage.logs_dir / "weather_failures.jsonl", _to_payload(payload))


def log_weather_timing(config: Config, payload: Any) -> None:
    append_jsonl(config.storage.logs_dir / "weather_timings.jsonl", _to_payload(payload))


def log_runtime_event(config: Config, payload: Any) -> None:
    append_jsonl(config.storage.logs_dir / "runtime_events.jsonl", _to_payload(payload))
