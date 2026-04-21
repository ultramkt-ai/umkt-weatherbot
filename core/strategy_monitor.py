from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
from typing import Any

from config import Config
from core.portfolio import apply_closed_trade_to_state
from core.risk_events import refresh_strategy_risk_state
from data.polymarket_clob_client import PolymarketClobClient
from data.polymarket_client import PolymarketClient
from models.trade import ClosedTrade, OpenTrade
from parallel_strategies import build_default_strategies
from storage.journal import log_blocked_close_attempt, log_closed_trade, log_runtime_event
from storage.strategy_journal import log_strategy_blocked_close_attempt, log_strategy_closed_trade
from storage.strategy_report import write_strategy_report
from storage.strategy_store import load_or_create_strategy_state, save_strategy_state
from utils.time_utils import now_iso


EXIT_RULES = {
    'NO_EXTREME': {'tp': 0.02, 'sl': -0.02},
    'YES_CONVEX': {'tp': 0.10, 'sl': -0.30},
    'MID_RANGE_BALANCED': {'tp': 0.10, 'sl': -0.10},
}


def calculate_hold_duration_hours(open_trade: OpenTrade, exit_time_iso: str) -> float:
    entry_dt = datetime.fromisoformat(open_trade.entry_time)
    exit_dt = datetime.fromisoformat(exit_time_iso)
    return (exit_dt - entry_dt).total_seconds() / 3600


def _should_close_trade(strategy_id: str, open_trade: OpenTrade, now_iso_value: str, trigger_roi: float | None) -> tuple[bool, str | None]:
    entry_dt = datetime.fromisoformat(open_trade.entry_time)
    now_dt_value = datetime.fromisoformat(now_iso_value)
    hold_hours = (now_dt_value - entry_dt).total_seconds() / 3600
    rules = EXIT_RULES.get(strategy_id, {'tp': 0.10, 'sl': -0.10, 'time_hours': 6})
    if trigger_roi is not None and trigger_roi >= rules['tp']:
        return True, 'tp_hit'
    if trigger_roi is not None and trigger_roi <= rules['sl']:
        return True, 'sl_hit'
    time_hours = rules.get('time_hours')
    if time_hours is not None and hold_hours >= time_hours:
        return True, 'time_stop'
    return False, None


def _clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, value))


def _json_list(raw_value: Any) -> list[Any]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        return raw_value
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _compact_market_status(market_status: dict[str, Any]) -> dict[str, Any]:
    return {
        'market_id': market_status.get('id'),
        'question': market_status.get('question'),
        'slug': market_status.get('slug'),
        'closed': market_status.get('closed'),
        'marketClosed': market_status.get('marketClosed'),
        'outcome': market_status.get('outcome'),
        'resolvedOutcome': market_status.get('resolvedOutcome'),
        'outcomes': _json_list(market_status.get('outcomes')),
        'outcomePrices': _json_list(market_status.get('outcomePrices')),
        'clobTokenIds': _json_list(market_status.get('clobTokenIds')),
        'endDate': market_status.get('endDate'),
        'endDateIso': market_status.get('endDateIso'),
    }


def _compact_book_snapshot(book: dict[str, Any]) -> dict[str, Any]:
    bids = book.get('bids') or []
    asks = book.get('asks') or []
    return {
        'asset_id': book.get('asset_id'),
        'market': book.get('market'),
        'timestamp': book.get('timestamp'),
        'hash': book.get('hash'),
        'last_trade_price': book.get('last_trade_price'),
        'best_bid': bids[0] if bids else None,
        'best_ask': asks[0] if asks else None,
        'bid_depth_levels': len(bids),
        'ask_depth_levels': len(asks),
    }


def _position_mark_from_market_status(open_trade: OpenTrade, market_status: dict[str, Any]) -> tuple[float, str, dict[str, Any]] | None:
    outcome = str(market_status.get('outcome') or market_status.get('resolvedOutcome') or '').strip().lower()
    closed_flag = bool(market_status.get('closed')) or bool(market_status.get('marketClosed'))
    if closed_flag and outcome in {'yes', 'no'}:
        value = 1.0 if ((open_trade.side == 'YES' and outcome == 'yes') or (open_trade.side == 'NO' and outcome == 'no')) else 0.0
        return (
            value,
            'resolved_market_outcome',
            {
                'basis': 'resolved_outcome',
                'token_id': open_trade.token_id,
                'position_side': open_trade.side,
                'resolved_outcome': outcome,
                'market_closed': closed_flag,
                'market_status': _compact_market_status(market_status),
            },
        )

    if not open_trade.token_id:
        return None

    token_ids = [str(item) for item in _json_list(market_status.get('clobTokenIds'))]
    outcome_prices = _json_list(market_status.get('outcomePrices'))
    outcomes = [str(item).strip().lower() for item in _json_list(market_status.get('outcomes'))]

    if token_ids and outcome_prices and len(token_ids) == len(outcome_prices):
        try:
            idx = token_ids.index(str(open_trade.token_id))
            value = _clamp_probability(float(outcome_prices[idx]))
            return (
                value,
                'market_outcome_price_by_token',
                {
                    'basis': 'market_status_token_match',
                    'token_id': open_trade.token_id,
                    'token_index': idx,
                    'position_side': open_trade.side,
                    'matched_outcome_label': outcomes[idx] if idx < len(outcomes) else None,
                    'raw_price': outcome_prices[idx],
                    'market_status': _compact_market_status(market_status),
                },
            )
        except (ValueError, TypeError):
            pass

    if outcomes and outcome_prices and len(outcomes) == len(outcome_prices):
        try:
            idx = outcomes.index(open_trade.side.strip().lower())
            value = _clamp_probability(float(outcome_prices[idx]))
            return (
                value,
                'market_outcome_price_by_side',
                {
                    'basis': 'market_status_side_match',
                    'token_id': open_trade.token_id,
                    'token_index': idx,
                    'position_side': open_trade.side,
                    'matched_outcome_label': outcomes[idx],
                    'raw_price': outcome_prices[idx],
                    'market_status': _compact_market_status(market_status),
                },
            )
        except (ValueError, TypeError):
            pass

    return None


def _mark_trade_to_market(config: Config, open_trade: OpenTrade, clob_client: PolymarketClobClient, polymarket_client: PolymarketClient) -> tuple[float, str, dict[str, Any]]:
    market_status = polymarket_client.get_market(open_trade.market_id)
    if market_status:
        market_mark = _position_mark_from_market_status(open_trade, market_status)
        if market_mark is not None:
            return market_mark

    if open_trade.token_id:
        books = clob_client.get_book_map([open_trade.token_id])
        book = books.get(open_trade.token_id)
        if book:
            last_trade_price = float(book.get('last_trade_price') or 0.0)
            if 0.0 < last_trade_price < 1.0:
                value = _clamp_probability(last_trade_price)
                return (value, 'clob_last_trade_mark', {
                    'basis': 'clob_last_trade_price',
                    'token_id': open_trade.token_id,
                    'position_side': open_trade.side,
                    'last_trade_price': book.get('last_trade_price'),
                    'book_timestamp': book.get('timestamp'),
                    'book_snapshot': _compact_book_snapshot(book),
                    'market_status': _compact_market_status(market_status) if market_status else None,
                })

            bids = book.get('bids') or []
            asks = book.get('asks') or []
            bid = float(bids[0].get('price', 0.0)) if bids else 0.0
            ask = float(asks[0].get('price', 0.0)) if asks else 0.0
            if bid > 0 and ask > 0:
                value = _clamp_probability((bid + ask) / 2.0)
                return (value, 'clob_midpoint_mark', {
                    'basis': 'clob_midpoint',
                    'token_id': open_trade.token_id,
                    'position_side': open_trade.side,
                    'best_bid': bids[0],
                    'best_ask': asks[0],
                    'book_snapshot': _compact_book_snapshot(book),
                    'market_status': _compact_market_status(market_status) if market_status else None,
                })
            if bid > 0:
                value = _clamp_probability(bid)
                return (value, 'clob_best_bid_mark', {
                    'basis': 'clob_best_bid',
                    'token_id': open_trade.token_id,
                    'position_side': open_trade.side,
                    'best_bid': bids[0],
                    'book_snapshot': _compact_book_snapshot(book),
                    'market_status': _compact_market_status(market_status) if market_status else None,
                })
            if ask > 0:
                value = _clamp_probability(ask)
                return (value, 'clob_best_ask_mark', {
                    'basis': 'clob_best_ask',
                    'token_id': open_trade.token_id,
                    'position_side': open_trade.side,
                    'best_ask': asks[0],
                    'book_snapshot': _compact_book_snapshot(book),
                    'market_status': _compact_market_status(market_status) if market_status else None,
                })

    return (open_trade.entry_price, 'entry_price_fallback_mark', {
        'basis': 'entry_price_fallback',
        'token_id': open_trade.token_id,
        'position_side': open_trade.side,
        'entry_price': open_trade.entry_price,
        'market_status': _compact_market_status(market_status) if market_status else None,
    })


def _execution_price_for_close(config: Config, open_trade: OpenTrade, clob_client: PolymarketClobClient, polymarket_client: PolymarketClient) -> tuple[float, str, dict[str, Any]] | None:
    market_status = polymarket_client.get_market(open_trade.market_id)
    if market_status:
        resolved_mark = _position_mark_from_market_status(open_trade, market_status)
        if resolved_mark is not None and resolved_mark[1] == 'resolved_market_outcome':
            return resolved_mark

    if not open_trade.token_id:
        return None

    books = clob_client.get_book_map([open_trade.token_id])
    book = books.get(open_trade.token_id)
    if not book:
        return None

    bids = book.get('bids') or []
    if bids:
        bid = float(bids[0].get('price', 0.0))
        if bid > 0.0:
            value = _clamp_probability(bid)
            return (value, 'clob_best_bid_execution', {
                'basis': 'clob_best_bid_executable',
                'token_id': open_trade.token_id,
                'position_side': open_trade.side,
                'best_bid': bids[0],
                'book_snapshot': _compact_book_snapshot(book),
                'market_status': _compact_market_status(market_status) if market_status else None,
            })

    return None


def _build_blocked_close_attempt_payload(
    strategy_id: str,
    open_trade: OpenTrade,
    now_iso_value: str,
    exit_reason: str | None,
    marked_resolution_value: float,
    marked_source: str,
    marked_source_value: dict[str, Any],
    marked_roi: float,
    error_message: str,
) -> dict[str, Any]:
    return {
        'captured_at': now_iso_value,
        'strategy_id': strategy_id,
        'trade_id': open_trade.trade_id,
        'market_id': open_trade.market_id,
        'parent_slug': open_trade.parent_slug,
        'outcome_label': open_trade.outcome_label,
        'side': open_trade.side,
        'token_id': open_trade.token_id,
        'entry_time': open_trade.entry_time,
        'attempted_exit_time': now_iso_value,
        'entry_price': open_trade.entry_price,
        'capital_alocado_usd': open_trade.capital_alocado_usd,
        'contracts_qty': open_trade.contracts_qty,
        'cluster_id': open_trade.cluster_id,
        'weather_type': open_trade.weather_type,
        'exit_reason': exit_reason,
        'marked_resolution_value': marked_resolution_value,
        'marked_resolution_source': marked_source,
        'marked_resolution_source_value': marked_source_value,
        'marked_roi': marked_roi,
        'blocked_reason': 'missing_executable_exit_price',
        'error_message': error_message,
    }


def _close_trade(config: Config, open_trade: OpenTrade, now_iso_value: str, clob_client: PolymarketClobClient, polymarket_client: PolymarketClient, exit_reason: str | None = None) -> ClosedTrade:
    execution_result = _execution_price_for_close(config, open_trade, clob_client, polymarket_client)
    if execution_result is None:
        raise RuntimeError(
            f"Sem preço executável para fechamento de {open_trade.trade_id} ({open_trade.side}/{open_trade.token_id})"
        )
    resolution_value, source, source_value = execution_result
    final_exit_reason = exit_reason or ("market_resolved" if source == "resolved_market_outcome" else "mark_to_market_close")
    gross_settlement_value = open_trade.contracts_qty * resolution_value
    net_pnl_abs = gross_settlement_value - open_trade.net_cost_usd
    roi = net_pnl_abs / open_trade.capital_alocado_usd if open_trade.capital_alocado_usd else 0.0
    win = net_pnl_abs > 0
    return ClosedTrade(
        trade_id=open_trade.trade_id,
        market_id=open_trade.market_id,
        parent_slug=open_trade.parent_slug,
        outcome_label=open_trade.outcome_label,
        bucket_type=open_trade.bucket_type,
        bucket_low=open_trade.bucket_low,
        bucket_high=open_trade.bucket_high,
        token_id=open_trade.token_id,
        entry_time=open_trade.entry_time,
        exit_time=now_iso_value,
        resolution_time=now_iso_value,
        side=open_trade.side,
        entry_price=open_trade.entry_price,
        resolution_value=resolution_value,
        capital_alocado_usd=open_trade.capital_alocado_usd,
        contracts_qty=open_trade.contracts_qty,
        gross_cost_usd=open_trade.gross_cost_usd,
        fees_paid_usd=open_trade.fees_paid_usd,
        gross_settlement_value_usd=gross_settlement_value,
        net_pnl_abs=net_pnl_abs,
        roi_on_allocated_capital=roi,
        result="WIN" if win else "LOSS",
        hold_duration_hours=calculate_hold_duration_hours(open_trade, now_iso_value),
        score=open_trade.score,
        weather_type=open_trade.weather_type,
        cluster_id=open_trade.cluster_id,
        resolution_source=source,
        resolution_source_value=source_value,
        drawdown_after_close=0.0,
        exit_reason=final_exit_reason,
    )


def monitor_strategy_open_trades(config: Config) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    now_value = now_iso()
    summary: list[dict[str, Any]] = []
    closed_all_payloads: list[dict[str, Any]] = []
    clob_client = PolymarketClobClient(config)
    polymarket_client = PolymarketClient(config)
    for strategy in build_default_strategies():
        state = load_or_create_strategy_state(config, strategy.strategy_id)
        closed_payloads: list[dict[str, Any]] = []
        blocked_close_attempts: list[dict[str, Any]] = []
        remaining_open = []
        for open_trade in state.open_trades:
            resolution_value, marked_source, marked_source_value = _mark_trade_to_market(config, open_trade, clob_client, polymarket_client)
            gross_settlement_value = open_trade.contracts_qty * resolution_value
            net_pnl_abs = gross_settlement_value - open_trade.net_cost_usd
            marked_roi = net_pnl_abs / open_trade.capital_alocado_usd if open_trade.capital_alocado_usd else 0.0
            execution_result = _execution_price_for_close(config, open_trade, clob_client, polymarket_client)
            executable_roi = None
            if execution_result is not None:
                executable_value = execution_result[0]
                executable_settlement = open_trade.contracts_qty * executable_value
                executable_pnl = executable_settlement - open_trade.net_cost_usd
                executable_roi = executable_pnl / open_trade.capital_alocado_usd if open_trade.capital_alocado_usd else 0.0
            should_close, exit_reason = _should_close_trade(strategy.strategy_id, open_trade, now_value, executable_roi)
            if not should_close:
                remaining_open.append(open_trade)
                continue
            try:
                closed_trade = _close_trade(config, open_trade, now_value, clob_client, polymarket_client, exit_reason=exit_reason)
            except RuntimeError as exc:
                blocked_payload = _build_blocked_close_attempt_payload(
                    strategy.strategy_id,
                    open_trade,
                    now_value,
                    exit_reason,
                    resolution_value,
                    marked_source,
                    marked_source_value,
                    marked_roi,
                    str(exc),
                )
                blocked_close_attempts.append(blocked_payload)
                log_blocked_close_attempt(config, blocked_payload)
                log_strategy_blocked_close_attempt(config, strategy.strategy_id, blocked_payload)
                log_runtime_event(config, {
                    'captured_at': now_value,
                    'event': 'blocked_close_attempt',
                    'strategy_id': strategy.strategy_id,
                    'trade_id': open_trade.trade_id,
                    'market_id': open_trade.market_id,
                    'side': open_trade.side,
                    'token_id': open_trade.token_id,
                    'exit_reason': exit_reason,
                    'blocked_reason': 'missing_executable_exit_price',
                    'error_message': str(exc),
                })
                remaining_open.append(open_trade)
                continue
            state = apply_closed_trade_to_state(state, closed_trade)
            payload = asdict(closed_trade)
            closed_payloads.append(payload)
            closed_all_payloads.append(payload)
            log_closed_trade(config, payload)
            log_strategy_closed_trade(config, strategy.strategy_id, payload)
        state.open_trades = remaining_open
        state.open_trades_count = len(remaining_open)
        state.last_cycle_finished_at = now_value
        state = refresh_strategy_risk_state(state, config)
        save_strategy_state(config, strategy.strategy_id, state)
        write_strategy_report(
            config,
            strategy.strategy_id,
            {
                "generated_at": now_value,
                "strategy_id": strategy.strategy_id,
                "status": "closed_monitor_cycle",
                "closed_now": closed_payloads,
                "blocked_close_attempts": blocked_close_attempts,
                "state_snapshot": {
                    "current_bankroll_usd": state.current_bankroll_usd,
                    "current_cash_usd": state.current_cash_usd,
                    "realized_pnl_total_usd": state.realized_pnl_total_usd,
                    "open_trades_count": state.open_trades_count,
                    "closed_trades_count": state.closed_trades_count,
                    "max_drawdown_pct": state.max_drawdown_pct,
                    "daily_stop_active": state.daily_stop_active,
                    "weekly_stop_active": state.weekly_stop_active,
                    "kill_switch_active": state.kill_switch_active,
                    "protection_pause_active": state.protection_pause_active,
                    "pause_reason": state.pause_reason,
                    "mode": state.mode,
                    "can_open_new_trades": state.can_open_new_trades,
                },
            },
        )
        summary.append(
            {
                "strategy_id": strategy.strategy_id,
                "closed_count": len(closed_payloads),
                "blocked_close_attempts_count": len(blocked_close_attempts),
                "realized_pnl_total_usd": state.realized_pnl_total_usd,
                "closed_trades_count": state.closed_trades_count,
            }
        )
    return {
        "generated_at": now_value,
        "summary": summary,
    }, closed_all_payloads
