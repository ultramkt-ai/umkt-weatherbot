from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from config import Config
from core.portfolio import apply_closed_trade_to_state
from data.polymarket_clob_client import PolymarketClobClient
from data.polymarket_client import PolymarketClient
from models.state import BotState
from models.trade import ClosedTrade, OpenTrade
from storage.journal import log_closed_trade


MAIN_EXIT_RULES = {
    "tp": 0.02,
    "sl": -0.03,
    "time_hours": 12,
}


def calculate_hold_duration_hours(open_trade: OpenTrade, exit_time_iso: str) -> float:
    entry_dt = datetime.fromisoformat(open_trade.entry_time)
    exit_dt = datetime.fromisoformat(exit_time_iso)
    return (exit_dt - entry_dt).total_seconds() / 3600


def _should_close_trade(open_trade: OpenTrade, now_iso_value: str, marked_roi: float, config: Config) -> tuple[bool, str | None]:
    entry_dt = datetime.fromisoformat(open_trade.entry_time)
    now_dt_value = datetime.fromisoformat(now_iso_value)
    hold_hours = (now_dt_value - entry_dt).total_seconds() / 3600
    
    rules = config.exit
    if marked_roi >= rules.tp:
        return True, "tp_hit"
    if marked_roi <= rules.sl:
        return True, "sl_hit"
    if hold_hours >= rules.time_hours:
        return True, "time_stop"
    return False, None


def _position_mark_from_yes_price(side: str, yes_price: float) -> float:
    yes_price = max(0.0, min(1.0, yes_price))
    return yes_price if side == "YES" else 1.0 - yes_price


def _mark_trade_to_market(
    open_trade: OpenTrade,
    clob_client: PolymarketClobClient,
    polymarket_client: PolymarketClient,
) -> tuple[float, str]:
    market_status = polymarket_client.get_market(open_trade.market_id)
    if market_status:
        closed_flag = bool(market_status.get("closed")) or bool(market_status.get("marketClosed"))
        outcome = str(market_status.get("outcome") or market_status.get("resolvedOutcome") or "").strip().lower()
        if closed_flag and outcome in {"yes", "no"}:
            if open_trade.side == "YES":
                return (1.0 if outcome == "yes" else 0.0), "resolved_market_outcome"
            return (1.0 if outcome == "no" else 0.0), "resolved_market_outcome"

    if open_trade.token_id:
        books = clob_client.get_book_map([open_trade.token_id])
        book = books.get(open_trade.token_id)
        if book:
            last_trade_price = float(book.get("last_trade_price") or 0.0)
            if 0.0 < last_trade_price < 1.0:
                return (_position_mark_from_yes_price(open_trade.side, last_trade_price), "clob_last_trade_mark")

            bids = book.get("bids") or []
            asks = book.get("asks") or []
            bid = float(bids[0].get("price", 0.0)) if bids else 0.0
            ask = float(asks[0].get("price", 0.0)) if asks else 0.0
            if bid > 0 and ask > 0:
                return (_position_mark_from_yes_price(open_trade.side, (bid + ask) / 2.0), "clob_midpoint_mark")
            if bid > 0:
                return (_position_mark_from_yes_price(open_trade.side, bid), "clob_best_bid_mark")
            if ask > 0:
                return (_position_mark_from_yes_price(open_trade.side, ask), "clob_best_ask_mark")

    return (open_trade.entry_price, "entry_price_fallback_mark")


def _close_trade(
    open_trade: OpenTrade,
    now_iso_value: str,
    clob_client: PolymarketClobClient,
    polymarket_client: PolymarketClient,
    exit_reason: str | None = None,
) -> ClosedTrade:
    resolution_value, source = _mark_trade_to_market(open_trade, clob_client, polymarket_client)
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
        exit_reason=exit_reason,
    )


def monitor_open_trades(state: BotState, config: Config, now_iso_value: str) -> tuple[BotState, list[dict]]:
    if not state.open_trades:
        return state, []

    closed_payloads: list[dict] = []
    clob_client = PolymarketClobClient(config)
    polymarket_client = PolymarketClient(config)

    for open_trade in list(state.open_trades):
        resolution_value, _ = _mark_trade_to_market(open_trade, clob_client, polymarket_client)
        gross_settlement_value = open_trade.contracts_qty * resolution_value
        net_pnl_abs = gross_settlement_value - open_trade.net_cost_usd
        marked_roi = net_pnl_abs / open_trade.capital_alocado_usd if open_trade.capital_alocado_usd else 0.0
        
        should_close, reason = _should_close_trade(open_trade, now_iso_value, marked_roi, config)
        if not should_close:
            continue
            
        closed_trade = _close_trade(open_trade, now_iso_value, clob_client, polymarket_client, exit_reason=reason)
        state = apply_closed_trade_to_state(state, closed_trade)
        payload = asdict(closed_trade)
        closed_payloads.append(payload)
        log_closed_trade(config, payload)

    return state, closed_payloads
