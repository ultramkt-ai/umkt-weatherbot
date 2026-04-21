from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from config import load_config
from storage.ledger_db import list_closed_trades, list_open_trades, list_trade_events
from utils.time_utils import now_iso


AUDIT_FIELDS = (
    "trade_id",
    "strategy_id",
    "status",
    "market_id",
    "outcome_label",
    "side",
    "entry_time",
    "entry_price",
    "capital_alocado_usd",
    "contracts_qty",
    "exit_time",
    "gross_settlement_value_usd",
    "net_pnl_abs",
    "roi_on_allocated_capital",
    "result",
    "exit_reason",
    "resolution_source",
    "audit_status",
    "audit_bucket",
    "audit_notes",
)

SUSPECT_AUDIT_BUCKETS = {
    "pre_fix_suspect",
    "yes_token_mapping_suspect",
    "non_executable_exit_suspect",
    "copytrading_merge_proxy_exit",
    "copytrading_missing_exit_suspect",
}


def _compact_trade(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in AUDIT_FIELDS}


def _build_trade_lifecycle_row(
    strategy_id: str,
    trade: dict[str, Any],
    trade_events: list[dict[str, Any]],
) -> dict[str, Any]:
    open_event = next((item for item in sorted(trade_events, key=lambda x: str(x.get("event_time") or "")) if item.get("event_type") == "OPEN"), None)
    close_event = next((item for item in sorted(trade_events, key=lambda x: str(x.get("event_time") or ""), reverse=True) if item.get("event_type") == "CLOSE"), None)
    market_snapshot = trade.get("market_snapshot_at_entry") or {}
    weather_snapshot = trade.get("weather_snapshot_at_entry") or {}
    resolution_evidence = trade.get("resolution_source_value") or {}
    exit_time = trade.get("exit_time") or trade.get("resolution_time")
    status = trade.get("status") or ("CLOSED" if exit_time else "OPEN")

    return {
        "trade_id": trade.get("trade_id"),
        "strategy_id": strategy_id,
        "status": status,
        "bought": bool(trade.get("entry_time")),
        "sold": status == "CLOSED",
        "when_bought": trade.get("entry_time"),
        "when_sold": exit_time,
        "market_id": trade.get("market_id"),
        "parent_slug": trade.get("parent_slug"),
        "outcome_label": trade.get("outcome_label"),
        "side": trade.get("side"),
        "token_id": trade.get("token_id"),
        "entry_price": trade.get("entry_price"),
        "exit_price": trade.get("resolution_value"),
        "capital_alocado_usd": trade.get("capital_alocado_usd"),
        "contracts_qty": trade.get("contracts_qty"),
        "gross_settlement_value_usd": trade.get("gross_settlement_value_usd"),
        "net_pnl_abs": trade.get("net_pnl_abs"),
        "roi_on_allocated_capital": trade.get("roi_on_allocated_capital"),
        "result": trade.get("result"),
        "exit_reason": trade.get("exit_reason"),
        "resolution_source": trade.get("resolution_source"),
        "audit_status": trade.get("audit_status"),
        "audit_bucket": trade.get("audit_bucket"),
        "audit_notes": trade.get("audit_notes"),
        "hold_duration_hours": trade.get("hold_duration_hours"),
        "cluster_id": trade.get("cluster_id"),
        "city": trade.get("city"),
        "weather_type": trade.get("weather_type"),
        "approval_summary": trade.get("approval_summary"),
        "entry_log": {
            "event_time": open_event.get("event_time") if open_event else None,
            "event_type": open_event.get("event_type") if open_event else None,
        },
        "exit_log": {
            "event_time": close_event.get("event_time") if close_event else None,
            "event_type": close_event.get("event_type") if close_event else None,
        },
        "market_snapshot_at_entry": {
            "selected_side": market_snapshot.get("selected_side"),
            "selected_token_id": market_snapshot.get("selected_token_id"),
            "yes_token_id": market_snapshot.get("yes_token_id"),
            "no_token_id": market_snapshot.get("no_token_id"),
            "selected_entry_price": market_snapshot.get("selected_entry_price"),
            "no_price": market_snapshot.get("no_price"),
            "yes_price": market_snapshot.get("yes_price"),
            "spread": market_snapshot.get("spread"),
            "liquidity": market_snapshot.get("liquidity"),
            "origin_contracts_qty": market_snapshot.get("origin_contracts_qty"),
            "origin_notional_usd": market_snapshot.get("origin_notional_usd"),
            "local_notional_usd": market_snapshot.get("local_notional_usd"),
            "copy_ratio": market_snapshot.get("copy_ratio"),
            "copy_mode": market_snapshot.get("copy_mode"),
            "local_cap_brl": market_snapshot.get("local_cap_brl"),
            "origin_side": market_snapshot.get("side"),
        },
        "weather_snapshot_at_entry": {
            "primary_forecast_value": weather_snapshot.get("primary_forecast_value"),
            "secondary_forecast_value": weather_snapshot.get("secondary_forecast_value"),
            "forecast_range_low": weather_snapshot.get("forecast_range_low"),
            "forecast_range_high": weather_snapshot.get("forecast_range_high"),
            "threshold_distance": weather_snapshot.get("threshold_distance"),
            "source_diff_value": weather_snapshot.get("source_diff_value"),
            "severe_alert_flag": weather_snapshot.get("severe_alert_flag"),
            "extreme_weather_flag": weather_snapshot.get("extreme_weather_flag"),
            "instability_flag": weather_snapshot.get("instability_flag"),
        },
        "resolution_evidence": {
            "raw": resolution_evidence,
            "exit_activity_type": resolution_evidence.get("exit_activity", {}).get("type") if isinstance(resolution_evidence, dict) else None,
            "exit_activity_side": resolution_evidence.get("exit_activity", {}).get("side") if isinstance(resolution_evidence, dict) else None,
            "exit_activity_price": resolution_evidence.get("exit_activity", {}).get("price") if isinstance(resolution_evidence, dict) else None,
            "previous_remote_cur_price": resolution_evidence.get("previous_remote_position", {}).get("curPrice") if isinstance(resolution_evidence, dict) else None,
            "previous_remote_current_value": resolution_evidence.get("previous_remote_position", {}).get("currentValue") if isinstance(resolution_evidence, dict) else None,
            "previous_remote_size": resolution_evidence.get("previous_remote_position", {}).get("size") if isinstance(resolution_evidence, dict) else None,
            "previous_remote_mergeable": resolution_evidence.get("previous_remote_position", {}).get("mergeable") if isinstance(resolution_evidence, dict) else None,
            "previous_remote_redeemable": resolution_evidence.get("previous_remote_position", {}).get("redeemable") if isinstance(resolution_evidence, dict) else None,
        },
    }


def build_trade_lifecycle_report(strategy_id: str | None = None) -> dict[str, Any]:
    config = load_config()
    strategies = [strategy_id] if strategy_id else sorted({
        item["strategy_id"] for item in list_trade_events(config, limit=5000)
    })

    report: dict[str, Any] = {
        "generated_at": now_iso(),
        "strategies": {},
        "summary": {
            "strategies": len(strategies),
            "rows": 0,
            "open_rows": 0,
            "closed_rows": 0,
        },
    }

    for current_strategy in strategies:
        open_trades = list_open_trades(config, current_strategy)
        closed_trades = list_closed_trades(config, current_strategy)
        events = list_trade_events(config, strategy_id=current_strategy, limit=5000)
        by_trade: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            by_trade[str(event.get("trade_id"))].append(event)

        rows = [
            _build_trade_lifecycle_row(current_strategy, trade, by_trade.get(str(trade.get("trade_id")), []))
            for trade in [*open_trades, *closed_trades]
        ]
        rows.sort(key=lambda item: (str(item.get("when_bought") or ""), str(item.get("trade_id") or "")), reverse=True)

        report["strategies"][current_strategy] = {
            "rows": rows,
            "counts": {
                "rows": len(rows),
                "open": sum(1 for item in rows if item.get("status") == "OPEN"),
                "closed": sum(1 for item in rows if item.get("status") == "CLOSED"),
                "trusted": sum(1 for item in rows if item.get("audit_bucket") not in {
                    *SUSPECT_AUDIT_BUCKETS,
                }),
                "suspect": sum(1 for item in rows if item.get("audit_bucket") in {
                    *SUSPECT_AUDIT_BUCKETS,
                }),
            },
        }
        report["summary"]["rows"] += len(rows)
        report["summary"]["open_rows"] += report["strategies"][current_strategy]["counts"]["open"]
        report["summary"]["closed_rows"] += report["strategies"][current_strategy]["counts"]["closed"]

    return report


def write_trade_lifecycle_report(strategy_id: str | None = None) -> dict[str, Any]:
    config = load_config()
    report = build_trade_lifecycle_report(strategy_id)

    reports_dir = config.storage.reports_dir / "audit"
    reports_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = config.storage.logs_dir / "audit"
    logs_dir.mkdir(parents=True, exist_ok=True)

    latest_path = reports_dir / (f"trade_lifecycle_{strategy_id.lower()}_latest.json" if strategy_id else "trade_lifecycle_latest.json")
    latest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    jsonl_path = logs_dir / (f"trade_lifecycle_{strategy_id.lower()}.jsonl" if strategy_id else "trade_lifecycle_all.jsonl")
    with jsonl_path.open("a", encoding="utf-8") as handle:
        for current_strategy, payload in report["strategies"].items():
            for row in payload.get("rows", []):
                handle.write(json.dumps({
                    "generated_at": report["generated_at"],
                    "strategy_id": current_strategy,
                    "row": row,
                }, ensure_ascii=False) + "\n")

    manifest_path = logs_dir / "trade_lifecycle_runs.jsonl"
    with manifest_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "generated_at": report["generated_at"],
            "strategy_id": strategy_id,
            "report_path": str(latest_path),
            "rows": report["summary"]["rows"],
            "open_rows": report["summary"]["open_rows"],
            "closed_rows": report["summary"]["closed_rows"],
        }, ensure_ascii=False) + "\n")

    return report


def build_audit_snapshot(strategy_id: str | None = None) -> dict[str, Any]:
    config = load_config()
    strategies = [strategy_id] if strategy_id else sorted({
        item["strategy_id"] for item in list_trade_events(config, limit=5000)
    })

    snapshot: dict[str, Any] = {
        "generated_at": None,
        "strategies": {},
        "consistency": {
            "ok": True,
            "issues": [],
        },
    }

    for current_strategy in strategies:
        open_trades = list_open_trades(config, current_strategy)
        closed_trades = list_closed_trades(config, current_strategy)
        events = list_trade_events(config, strategy_id=current_strategy, limit=5000)
        by_trade: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            by_trade[str(event.get("trade_id"))].append(event)

        issues: list[str] = []
        closed_index = {str(item.get("trade_id")): item for item in closed_trades}
        open_index = {str(item.get("trade_id")): item for item in open_trades}
        for trade_id, trade_events in by_trade.items():
            event_types = [str(item.get("event_type")) for item in trade_events]
            if event_types.count("OPEN") > 1:
                issues.append(f"{trade_id}: múltiplos eventos OPEN")
            if event_types.count("CLOSE") > 1:
                issues.append(f"{trade_id}: múltiplos eventos CLOSE")
            if "CLOSE" in event_types and trade_id not in closed_index:
                issues.append(f"{trade_id}: evento CLOSE sem linha CLOSED no ledger")
            if "OPEN" in event_types and trade_id not in open_index and trade_id not in closed_index:
                issues.append(f"{trade_id}: evento OPEN sem linha correspondente no ledger")

        strategy_snapshot = {
            "open_trades": [_compact_trade(item) for item in open_trades],
            "closed_trades": [_compact_trade(item) for item in closed_trades],
            "lifecycle_closed_trades": [
                {
                    "trade_id": item.get("trade_id"),
                    "strategy_id": item.get("strategy_id"),
                    "entry_time": item.get("entry_time"),
                    "exit_time": item.get("exit_time"),
                    "side": item.get("side"),
                    "entry_price": item.get("entry_price"),
                    "resolution_value": item.get("resolution_value"),
                    "net_pnl_abs": item.get("net_pnl_abs"),
                    "result": item.get("result"),
                    "exit_reason": item.get("exit_reason"),
                    "resolution_source": item.get("resolution_source"),
                    "audit_bucket": item.get("audit_bucket"),
                    "audit_status": item.get("audit_status"),
                }
                for item in closed_trades
            ],
            "trusted_post_fix_closed_trades": [
                _compact_trade(item) for item in closed_trades if item.get("audit_bucket") == "post_fix_trusted"
            ],
            "pre_fix_suspect_closed_trades": [
                _compact_trade(item) for item in closed_trades if item.get("audit_bucket") == "pre_fix_suspect"
            ],
            "yes_token_mapping_suspect_closed_trades": [
                _compact_trade(item) for item in closed_trades if item.get("audit_bucket") == "yes_token_mapping_suspect"
            ],
            "non_executable_exit_suspect_closed_trades": [
                _compact_trade(item) for item in closed_trades if item.get("audit_bucket") == "non_executable_exit_suspect"
            ],
            "copytrading_merge_proxy_exit_closed_trades": [
                _compact_trade(item) for item in closed_trades if item.get("audit_bucket") == "copytrading_merge_proxy_exit"
            ],
            "copytrading_missing_exit_suspect_closed_trades": [
                _compact_trade(item) for item in closed_trades if item.get("audit_bucket") == "copytrading_missing_exit_suspect"
            ],
            "pre_fix_other_closed_trades": [
                _compact_trade(item) for item in closed_trades if item.get("audit_bucket") == "pre_fix_other"
            ],
            "recent_events": [
                {
                    "strategy_id": item.get("strategy_id"),
                    "trade_id": item.get("trade_id"),
                    "event_type": item.get("event_type"),
                    "event_time": item.get("event_time"),
                }
                for item in events[:50]
            ],
            "counts": {
                "open": len(open_trades),
                "closed": len(closed_trades),
                "events": len(events),
                "trusted_post_fix_closed": sum(1 for item in closed_trades if item.get("audit_bucket") == "post_fix_trusted"),
                "pre_fix_suspect_closed": sum(1 for item in closed_trades if item.get("audit_bucket") == "pre_fix_suspect"),
                "yes_token_mapping_suspect_closed": sum(1 for item in closed_trades if item.get("audit_bucket") == "yes_token_mapping_suspect"),
                "non_executable_exit_suspect_closed": sum(1 for item in closed_trades if item.get("audit_bucket") == "non_executable_exit_suspect"),
                "copytrading_merge_proxy_exit_closed": sum(1 for item in closed_trades if item.get("audit_bucket") == "copytrading_merge_proxy_exit"),
                "copytrading_missing_exit_suspect_closed": sum(1 for item in closed_trades if item.get("audit_bucket") == "copytrading_missing_exit_suspect"),
                "pre_fix_other_closed": sum(1 for item in closed_trades if item.get("audit_bucket") == "pre_fix_other"),
            },
            "issues": issues,
        }
        snapshot["strategies"][current_strategy] = strategy_snapshot
        snapshot["generated_at"] = events[0].get("event_time") if events else snapshot["generated_at"]
        if issues:
            snapshot["consistency"]["ok"] = False
            snapshot["consistency"]["issues"].extend([f"{current_strategy}: {issue}" for issue in issues])

    return snapshot


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    command = args[0] if args and args[0] in {"snapshot", "lifecycle", "write-lifecycle"} else "snapshot"
    target_strategy = None
    if command == "snapshot":
        target_strategy = args[0] if args and args[0] not in {"snapshot", "lifecycle", "write-lifecycle"} else (args[1] if len(args) > 1 else None)
        print(json.dumps(build_audit_snapshot(target_strategy), ensure_ascii=False, indent=2))
    elif command == "lifecycle":
        target_strategy = args[1] if len(args) > 1 else None
        print(json.dumps(build_trade_lifecycle_report(target_strategy), ensure_ascii=False, indent=2))
    else:
        target_strategy = args[1] if len(args) > 1 else None
        print(json.dumps(write_trade_lifecycle_report(target_strategy), ensure_ascii=False, indent=2))
