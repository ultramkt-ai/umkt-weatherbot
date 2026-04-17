from __future__ import annotations

import json
from typing import Any

from config import Config
from storage.strategy_store import strategy_report_path


def write_strategy_report(config: Config, strategy_id: str, payload: dict[str, Any]) -> None:
    path = strategy_report_path(config, strategy_id, "latest.json")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_comparison_report(config: Config, payload: dict[str, Any]) -> None:
    path = config.storage.reports_dir / "strategy_comparison_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
