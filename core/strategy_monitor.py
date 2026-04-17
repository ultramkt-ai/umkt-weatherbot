from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from config import Config
from core.monitor import calculate_hold_duration_hours
from core.portfolio import apply_closed_trade_to_state
from data.polymarket_clob_client import PolymarketClobClient
from data.polymarket_client import PolymarketClient
from models.trade import ClosedTrade, OpenTrade
from parallel_strategies import build_default_strategies
from storage.journal import log_closed_trade
from storage.strategy_journal import log_strategy_closed_trade
from storage.strategy_report import write_strategy_report
from storage.strategy_store import load_or_create_strategy_state, save_strategy_state
from utils.time_utils import now_iso


EXIT_RULES = {
    'NO_EXTREME': {'tp': 0.0125, 'sl': -0.01, 'time_hours': 3},
    'YES_CONVEX': {'tp': 0.50, 'sl': -0.30, 'time_hours': 8},
    'MID_RANGE_BALANCED': {'tp': 0.15, 'sl': -0.10, 'time_hours': 6},
}


def _should_close_trade(strategy_id: str, open_trade: OpenTrade, now_iso_value: str, marked_roi: float) -> bool:
    entry_dt = datetime.fromisoformat(open_trade.entry_time)
    now_dt_value = datetime.fromisoformat(now_iso_value)
    hold_hours = (now_dt_value - entry_dt).total_seconds() / 3600
    rules = EXIT_RULES.get(strategy_id, {'tp': 0.10, 'sl': -0.10, 'time_hours': 6})
    if marked_roi >= rules['tp']:
        return True
    if marked_roi <= rules['sl']:
        return True
    if hold_hours >= rules['time_hours']:
        return True
    return False


def _position_mark_from_yes_price(side: str, yes_price: float) -> float:
    yes_price = max(0.0, min(1.0, yes_price))
    return yes_price if side == 'YES' else 1.0 - yes_price


def _mark_trade_to_market(config: Config, open_trade: OpenTrade, clob_client: PolymarketClobClient, polymarket_client: PolymarketClient) -> tuple[float, str]:
    market_status = polymarket_client.get_market(open_trade.market_id)
    if market_status:
        closed_flag = bool(market_status.get('closed')) or bool(market_status.get('marketClosed'))
        outcome = str(market_status.get('outcome') or market_status.get('resolvedOutcome') or '').strip().lower()
        if closed_flag and outcome in {'yes', 'no'}:
            if open_trade.side == 'YES':
                return (1.0 if outcome == 'yes' else 0.0), 'resolved_market_outcome'
            return (1.0 if outcome == 'no' else 0.0), 'resolved_market_outcome'

    if open_trade.token_id:
        books = clob_client.get_book_map([open_trade.token_id])
        book = books.get(open_trade.token_id)
        if book:
            last_trade_price = float(book.get('last_trade_price') or 0.0)
            if 0.0 < last_trade_price < 1.0:
                return (_position_mark_from_yes_price(open_trade.side, last_trade_price), 'clob_last_trade_mark')

            bids = book.get('bids') or []
            asks = book.get('asks') or []
            bid = float(bids[0].get('price', 0.0)) if bids else 0.0
            ask = float(asks[0].get('price', 0.0)) if asks else 0.0
            if bid > 0 and ask > 0:
                return (_position_mark_from_yes_price(open_trade.side, (bid + ask) / 2.0), 'clob_midpoint_mark')
            if bid > 0:
                return (_position_mark_from_yes_price(open_trade.side, bid), 'clob_best_bid_mark')
            if ask > 0:
                return (_position_mark_from_yes_price(open_trade.side, ask), 'clob_best_ask_mark')

    return (open_trade.entry_price, 'entry_price_fallback_mark')


def _close_trade(config: Config, open_trade: OpenTrade, now_iso_value: str, clob_client: PolymarketClobClient, polymarket_client: PolymarketClient) -> ClosedTrade:
    resolution_value, source = _mark_trade_to_market(config, open_trade, clob_client, polymarket_client)
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
        resolution_source_value=resolution_value,
        drawdown_after_close=0.0,
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
        remaining_open = []
        for open_trade in state.open_trades:
            resolution_value, _ = _mark_trade_to_market(config, open_trade, clob_client, polymarket_client)
            gross_settlement_value = open_trade.contracts_qty * resolution_value
            net_pnl_abs = gross_settlement_value - open_trade.net_cost_usd
            marked_roi = net_pnl_abs / open_trade.capital_alocado_usd if open_trade.capital_alocado_usd else 0.0
            if not _should_close_trade(strategy.strategy_id, open_trade, now_value, marked_roi):
                remaining_open.append(open_trade)
                continue
            closed_trade = _close_trade(config, open_trade, now_value, clob_client, polymarket_client)
            state = apply_closed_trade_to_state(state, closed_trade)
            payload = asdict(closed_trade)
            closed_payloads.append(payload)
            closed_all_payloads.append(payload)
            log_closed_trade(config, payload)
            log_strategy_closed_trade(config, strategy.strategy_id, payload)
        state.open_trades = remaining_open
        state.open_trades_count = len(remaining_open)
        save_strategy_state(config, strategy.strategy_id, state)
        write_strategy_report(
            config,
            strategy.strategy_id,
            {
                "generated_at": now_value,
                "strategy_id": strategy.strategy_id,
                "closed_now": closed_payloads,
                "state_snapshot": {
                    "current_bankroll_usd": state.current_bankroll_usd,
                    "current_cash_usd": state.current_cash_usd,
                    "realized_pnl_total_usd": state.realized_pnl_total_usd,
                    "open_trades_count": state.open_trades_count,
                    "closed_trades_count": state.closed_trades_count,
                    "max_drawdown_pct": state.max_drawdown_pct,
                },
            },
        )
        summary.append(
            {
                "strategy_id": strategy.strategy_id,
                "closed_count": len(closed_payloads),
                "realized_pnl_total_usd": state.realized_pnl_total_usd,
                "closed_trades_count": state.closed_trades_count,
            }
        )
    return {
        "generated_at": now_value,
        "summary": summary,
    }, closed_all_payloads
