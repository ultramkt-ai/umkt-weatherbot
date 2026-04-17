from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from config import load_config
from parallel_strategies import build_default_strategies
from storage.ledger_db import COPYTRADING_STRATEGY_ID, build_strategy_snapshot, migrate_legacy_trade_data
from storage.strategy_report import write_comparison_report
from storage.strategy_store import load_or_create_strategy_state, strategy_log_path
from utils.time_utils import now_iso


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _build_strategy_metrics(config, strategy_id: str, state) -> dict:
    decisions = _read_jsonl(strategy_log_path(config, strategy_id, 'decisions.jsonl'))
    snapshot = build_strategy_snapshot(config, strategy_id, state.initial_bankroll_usd)
    open_trades = snapshot.get('open_trades', [])
    closed_trades = snapshot.get('closed_trades', [])
    cycles = _read_jsonl(strategy_log_path(config, strategy_id, 'cycles.jsonl'))

    approved_decisions = [row for row in decisions if row.get('decision', {}).get('approved')]
    rejected_decisions = [row for row in decisions if not row.get('decision', {}).get('approved')]
    decision_scores = [row.get('decision', {}).get('score') for row in decisions if row.get('decision', {}).get('score') is not None]
    approved_entry_prices = [row.get('decision', {}).get('entry_price') for row in approved_decisions if row.get('decision', {}).get('entry_price') is not None]
    approved_sides = [row.get('decision', {}).get('trade_side') for row in approved_decisions if row.get('decision', {}).get('trade_side')]
    approved_yes = sum(1 for side in approved_sides if side == 'YES')
    approved_no = sum(1 for side in approved_sides if side == 'NO')
    wins = [row for row in closed_trades if row.get('result') == 'WIN']
    losses = [row for row in closed_trades if row.get('result') == 'LOSS']
    gross_profit = sum(float(row.get('net_pnl_abs') or 0.0) for row in wins)
    gross_loss = abs(sum(float(row.get('net_pnl_abs') or 0.0) for row in losses))
    hold_times = [float(row.get('hold_duration_hours') or 0.0) for row in closed_trades]
    resolution_sources: dict[str, int] = {}
    for row in closed_trades:
        source = str(row.get('resolution_source') or 'unknown')
        resolution_sources[source] = resolution_sources.get(source, 0) + 1

    return {
        'decisions_logged': len(decisions),
        'approved_decisions_logged': len(approved_decisions),
        'rejected_decisions_logged': len(rejected_decisions),
        'approval_rate': (len(approved_decisions) / len(decisions)) if decisions else 0.0,
        'open_trades_logged': len(open_trades),
        'closed_trades_logged': len(closed_trades),
        'cycles_logged': len(cycles),
        'avg_decision_score': (sum(decision_scores) / len(decision_scores)) if decision_scores else 0.0,
        'avg_entry_price_approved_only': (sum(approved_entry_prices) / len(approved_entry_prices)) if approved_entry_prices else 0.0,
        'approved_yes_count': approved_yes,
        'approved_no_count': approved_no,
        'win_rate_closed_only': (len(wins) / len(closed_trades)) if closed_trades else 0.0,
        'profit_factor': (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
        'avg_hold_hours_closed_only': (sum(hold_times) / len(hold_times)) if hold_times else 0.0,
        'gross_profit_closed_usd': gross_profit,
        'gross_loss_closed_usd': gross_loss,
        'resolution_sources': resolution_sources,
        'realized_pnl_total_usd': state.realized_pnl_total_usd,
        'current_bankroll_usd': state.current_bankroll_usd,
        'current_cash_usd': state.current_cash_usd,
        'capital_alocado_aberto_usd': state.capital_alocado_aberto_usd,
        'open_trades_count': state.open_trades_count,
        'closed_trades_count': state.closed_trades_count,
        'approved_trades_count': state.approved_trades_count,
        'markets_scanned_today': state.markets_scanned_today,
        'approved_today': state.approved_today,
        'rejected_today': state.rejected_today,
        'open_exposure_pct': state.open_exposure_pct,
        'max_drawdown_pct': state.max_drawdown_pct,
        'roi_vs_initial_bankroll': ((state.current_bankroll_usd - state.initial_bankroll_usd) / state.initial_bankroll_usd) if state.initial_bankroll_usd else 0.0,
    }


def _build_copytrading_row(config) -> dict | None:
    migrate_legacy_trade_data(config)
    snapshot = build_strategy_snapshot(config, COPYTRADING_STRATEGY_ID, config.risk.initial_bankroll_usd)
    closed = snapshot.get('closed_trades', [])
    open_positions = snapshot.get('open_trades', [])
    wins = [row for row in closed if row.get('result') == 'WIN']
    losses = [row for row in closed if row.get('result') == 'LOSS']
    gross_profit = sum(float(row.get('net_pnl_abs') or 0.0) for row in wins)
    gross_loss = abs(sum(float(row.get('net_pnl_abs') or 0.0) for row in losses))
    hold_times = [float(row.get('hold_duration_hours') or 0.0) for row in closed]
    outcome_counts: dict[str, int] = {}
    for row in open_positions:
        outcome = str(row.get('outcome_label') or 'UNKNOWN')
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
    outcome_summary = ' · '.join(f"{name}:{count}" for name, count in sorted(outcome_counts.items(), key=lambda item: (-item[1], item[0]))[:4])
    return {
        'strategy': {
            'strategy_id': 'COPYTRADING_COLDMATH',
            'side_mode': 'MIRROR',
            'min_price': 0.0,
            'max_price': 1.0,
            'preferred_low': 0.0,
            'preferred_high': 1.0,
            'max_entries_per_market': 1,
            'score_bias': 0,
            'notes': 'Replica fills reais da carteira ColdMath com notional proporcional por fill. Não depende de clima para disparar entradas.',
        },
        'state': {
            'session_id': 'copytrading:coldmath',
            'current_bankroll_usd': snapshot.get('current_bankroll_usd', 10000.0),
            'current_cash_usd': snapshot.get('current_cash_usd', 10000.0),
            'realized_pnl_total_usd': snapshot.get('realized_pnl_total_usd', 0.0),
            'open_trades_count': snapshot.get('open_trades_count', 0),
            'closed_trades_count': snapshot.get('closed_trades_count', 0),
            'approved_trades_count': snapshot.get('approved_trades_count', 0),
            'markets_scanned_today': 0,
            'approved_today': snapshot.get('approved_today', 0),
            'rejected_today': 0,
            'open_exposure_pct': snapshot.get('open_exposure_pct', 0.0),
            'max_drawdown_pct': 0.0,
            'last_score_approved': None,
        },
        'metrics': {
            'decisions_logged': snapshot.get('approved_trades_count', 0),
            'approved_decisions_logged': snapshot.get('open_trades_count', 0),
            'signals_copied_total': snapshot.get('approved_trades_count', 0),
            'rejected_decisions_logged': 0,
            'approval_rate': (snapshot.get('open_trades_count', 0) / snapshot.get('approved_trades_count', 1)) if snapshot.get('approved_trades_count', 0) else 0.0,
            'open_trades_logged': snapshot.get('open_trades_count', 0),
            'closed_trades_logged': len(closed),
            'cycles_logged': snapshot.get('approved_trades_count', 0),
            'avg_decision_score': 50.0,
            'avg_entry_price_approved_only': (sum(float(row.get('entry_price') or 0.0) for row in open_positions) / len(open_positions)) if open_positions else 0.0,
            'approved_yes_count': 0,
            'approved_no_count': 0,
            'open_outcome_count': len(outcome_counts),
            'open_outcome_summary': outcome_summary,
            'win_rate_closed_only': (len(wins) / len(closed)) if closed else 0.0,
            'profit_factor': (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
            'avg_hold_hours_closed_only': (sum(hold_times) / len(hold_times)) if hold_times else 0.0,
            'gross_profit_closed_usd': gross_profit,
            'gross_loss_closed_usd': gross_loss,
            'resolution_sources': {},
            'realized_pnl_total_usd': snapshot.get('realized_pnl_total_usd', 0.0),
            'current_bankroll_usd': snapshot.get('current_bankroll_usd', 10000.0),
            'current_cash_usd': snapshot.get('current_cash_usd', 10000.0),
            'capital_alocado_aberto_usd': snapshot.get('capital_alocado_aberto_usd', 0.0),
            'open_trades_count': snapshot.get('open_trades_count', 0),
            'closed_trades_count': len(closed),
            'approved_trades_count': snapshot.get('approved_trades_count', 0),
            'markets_scanned_today': 0,
            'approved_today': snapshot.get('approved_today', 0),
            'rejected_today': 0,
            'open_exposure_pct': snapshot.get('open_exposure_pct', 0.0),
            'max_drawdown_pct': 0.0,
            'roi_vs_initial_bankroll': ((snapshot.get('current_bankroll_usd', 10000.0) - 10000.0) / 10000.0),
        },
    }


def build_comparison_snapshot() -> dict:
    config = load_config()
    strategies = build_default_strategies()
    rows = []
    for strategy in strategies:
        state = load_or_create_strategy_state(config, strategy.strategy_id)
        rows.append(
            {
                "strategy": asdict(strategy),
                "state": {
                    "session_id": state.session_id,
                    "current_bankroll_usd": state.current_bankroll_usd,
                    "current_cash_usd": state.current_cash_usd,
                    "realized_pnl_total_usd": state.realized_pnl_total_usd,
                    "open_trades_count": state.open_trades_count,
                    "closed_trades_count": state.closed_trades_count,
                    "approved_trades_count": state.approved_trades_count,
                    "markets_scanned_today": state.markets_scanned_today,
                    "approved_today": state.approved_today,
                    "rejected_today": state.rejected_today,
                    "open_exposure_pct": state.open_exposure_pct,
                    "max_drawdown_pct": state.max_drawdown_pct,
                    "last_score_approved": state.last_score_approved,
                },
                "metrics": _build_strategy_metrics(config, strategy.strategy_id, state),
            }
        )
    copy_row = _build_copytrading_row(config)
    if copy_row:
        rows.append(copy_row)

    payload = {
        "generated_at": now_iso(),
        "strategies": rows,
        "ranking_hint": sorted(
            [
                {
                    'strategy_id': row['strategy']['strategy_id'],
                    'roi_vs_initial_bankroll': row['metrics']['roi_vs_initial_bankroll'],
                    'approved_decisions_logged': row['metrics']['approved_decisions_logged'],
                    'open_trades_logged': row['metrics']['open_trades_logged'],
                }
                for row in rows
            ],
            key=lambda item: (item['roi_vs_initial_bankroll'], item['approved_decisions_logged'], item['open_trades_logged']),
            reverse=True,
        ),
        "notes": [
            "Comparador inicial por estratégia criado antes da integração completa do fechamento de trades por estratégia.",
            "Enquanto os trades ainda estiverem majoritariamente abertos, ROI e PnL realizado terão pouco sinal. Approval rate e exposição ajudam a interpretar o comportamento interim.",
        ],
    }
    write_comparison_report(config, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(build_comparison_snapshot(), ensure_ascii=False, indent=2))
