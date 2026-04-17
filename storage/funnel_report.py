from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from config import Config


FUNNEL_REPORT_FILENAME = "latest_funnel_report.json"


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def build_funnel_report(cycle_stats: dict[str, Any]) -> dict[str, Any]:
    scanned = list(cycle_stats.get("scanned_candidates") or [])
    normalization_failures = list(cycle_stats.get("normalization_failures") or [])
    decisions = list(cycle_stats.get("decisions") or [])
    operable = list(cycle_stats.get("operable") or [])
    watchlist = list(cycle_stats.get("watchlist") or [])
    executable_experiment = list(cycle_stats.get("executable_experiment") or [])
    opened_trades = list(cycle_stats.get("opened_trades") or [])

    decision_counts = Counter()
    class_counts = Counter()
    price_bucket_counts = Counter()
    book_quality_counts = Counter()
    rejection_by_price_bucket = Counter()
    experiment_reason_counts = Counter()

    for row in decisions:
        decision_counts[row.get("rejection_code") or "approved"] += 1
        class_counts[row.get("candidate_class") or "UNCLASSIFIED"] += 1
        price_bucket = row.get("price_bucket") or "unknown"
        book_bucket = row.get("book_quality_bucket") or "unknown"
        price_bucket_counts[price_bucket] += 1
        book_quality_counts[book_bucket] += 1
        if not row.get("approved"):
            rejection_by_price_bucket[f"{row.get('rejection_code') or 'unknown'}::{price_bucket}"] += 1

    for row in executable_experiment:
        experiment_reason_counts[row.get("watch_reason") or "unknown"] += 1

    report = {
        "cycle_started_at": cycle_stats.get("cycle_started_at"),
        "cycle_finished_at": cycle_stats.get("cycle_finished_at"),
        "totals": {
            "raw_scanned": _safe_int(cycle_stats.get("raw_scanned")) or 0,
            "weather_scanned": len(scanned),
            "normalized_ok": len(decisions),
            "normalization_failed": len(normalization_failures),
            "approved": decision_counts.get("approved", 0),
            "operable": len(operable),
            "watchlist": len(watchlist),
            "executable_experiment": len(executable_experiment),
            "opened_trades": len(opened_trades),
            "rejected": sum(count for reason, count in decision_counts.items() if reason != "approved"),
        },
        "decision_counts": dict(decision_counts),
        "candidate_class_counts": dict(class_counts),
        "price_bucket_counts": dict(price_bucket_counts),
        "book_quality_bucket_counts": dict(book_quality_counts),
        "rejection_by_price_bucket": dict(rejection_by_price_bucket),
        "experiment_reason_counts": dict(experiment_reason_counts),
        "samples": {
            "operable": operable[:20],
            "watchlist": watchlist[:40],
            "executable_experiment": executable_experiment[:40],
            "opened_trades": opened_trades[:20],
            "normalization_failures": normalization_failures[:20],
            "rejections": [row for row in decisions if not row.get("approved")][:40],
        },
        "metrics": {
            "approved_but_not_operable": max(0, decision_counts.get("approved", 0) - len(operable)),
            "approval_rate_vs_weather_scan": round((decision_counts.get("approved", 0) / len(scanned)) * 100, 2) if scanned else 0.0,
            "operable_rate_vs_weather_scan": round((len(operable) / len(scanned)) * 100, 2) if scanned else 0.0,
            "experimental_rate_vs_weather_scan": round((len(executable_experiment) / len(scanned)) * 100, 2) if scanned else 0.0,
            "opened_rate_vs_approved": round((len(opened_trades) / decision_counts.get("approved", 0)) * 100, 2) if decision_counts.get("approved", 0) else 0.0,
        },
    }
    return report


def write_funnel_report(config: Config, cycle_stats: dict[str, Any]) -> Path:
    report = build_funnel_report(cycle_stats)
    config.storage.reports_dir.mkdir(parents=True, exist_ok=True)
    path = config.storage.reports_dir / FUNNEL_REPORT_FILENAME
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
