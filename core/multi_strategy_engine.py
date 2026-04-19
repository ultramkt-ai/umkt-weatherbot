from __future__ import annotations

from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from config import Config
from core.portfolio import apply_open_trade_to_state
from core.risk_events import refresh_strategy_risk_state
from core.paper_broker import create_open_trade
from core.strategy_engine import evaluate_outcome_for_strategy
from models.market import TemperatureMarket, TemperatureOutcomeCandidate
from models.weather import WeatherContext
from parallel_strategies import build_default_strategies
from storage.strategy_journal import log_strategy_cycle, log_strategy_decision, log_strategy_error, log_strategy_open_trade
from storage.strategy_report import write_strategy_report
from storage.strategy_store import load_or_create_strategy_state, save_strategy_state
from utils.time_utils import now_iso


def _refresh_strategy_runtime_state(state, config: Config):
    state.current_bankroll_usd = state.current_cash_usd + state.capital_alocado_aberto_usd
    state = refresh_strategy_risk_state(state, config)
    return state


def _evaluate_candidate_for_single_strategy(
    market: TemperatureMarket,
    outcome: TemperatureOutcomeCandidate,
    weather: WeatherContext | None,
    config: Config,
    strategy,
) -> dict[str, Any]:
    state = load_or_create_strategy_state(config, strategy.strategy_id)
    try:
        decision = evaluate_outcome_for_strategy(market, outcome, weather, state, config, strategy)
        decision_payload = {
            "captured_at": now_iso(),
            "strategy_id": strategy.strategy_id,
            "market_id": market.market_id,
            "market_title": market.title,
            "outcome_label": outcome.outcome_label,
            "decision": asdict(decision),
        }
        log_strategy_decision(config, strategy.strategy_id, decision_payload)

        open_trade_payload = None
        status = "approved" if decision.approved else "rejected"
        if decision.approved:
            open_trade = create_open_trade(
                market=market,
                outcome=outcome,
                weather=weather,
                cluster_id=decision.cluster_id or "unknown",
                score=decision.score or 0,
                approval_summary=decision.approval_summary or f"Approved by {strategy.strategy_id}",
                config=config,
                bankroll_usd=state.current_bankroll_usd,
                side=decision.trade_side or "NO",
                entry_price=decision.entry_price,
            )
            state = apply_open_trade_to_state(state, open_trade)
            open_trade_payload = asdict(open_trade)
            log_strategy_open_trade(config, strategy.strategy_id, open_trade_payload)
        else:
            state.rejected_today += 1

        state.markets_scanned_today += 1
        state.last_cycle_finished_at = now_iso()
        state = _refresh_strategy_runtime_state(state, config)
        save_strategy_state(config, strategy.strategy_id, state)

        cycle_payload = {
            "captured_at": now_iso(),
            "strategy_id": strategy.strategy_id,
            "market_id": market.market_id,
            "status": status,
            "approved": decision.approved,
            "trade_side": decision.trade_side,
            "entry_price": decision.entry_price,
            "score": decision.score,
            "rejection_code": decision.rejection_code,
        }
        log_strategy_cycle(config, strategy.strategy_id, cycle_payload)
        write_strategy_report(
            config,
            strategy.strategy_id,
            {
                "generated_at": now_iso(),
                "strategy_id": strategy.strategy_id,
                "latest_market_id": market.market_id,
                "latest_market_title": market.title,
                "status": status,
                "latest_decision": decision_payload,
                "latest_open_trade": open_trade_payload,
                "state_snapshot": {
                    "current_bankroll_usd": state.current_bankroll_usd,
                    "current_cash_usd": state.current_cash_usd,
                    "open_trades_count": state.open_trades_count,
                    "approved_trades_count": state.approved_trades_count,
                    "markets_scanned_today": state.markets_scanned_today,
                    "approved_today": state.approved_today,
                    "rejected_today": state.rejected_today,
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
        return {
            "strategy_id": strategy.strategy_id,
            "status": status,
            "decision": decision_payload,
            "open_trade": open_trade_payload,
        }
    except Exception as exc:
        state.last_cycle_finished_at = now_iso()
        state.last_error_code = "strategy_cycle_exception"
        state.last_error_at = now_iso()
        save_strategy_state(config, strategy.strategy_id, state)
        error_payload = {
            "captured_at": now_iso(),
            "strategy_id": strategy.strategy_id,
            "market_id": market.market_id,
            "market_title": market.title,
            "outcome_label": outcome.outcome_label,
            "status": "failed",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
        log_strategy_error(config, strategy.strategy_id, error_payload)
        log_strategy_cycle(config, strategy.strategy_id, error_payload)
        write_strategy_report(
            config,
            strategy.strategy_id,
            {
                "generated_at": now_iso(),
                "strategy_id": strategy.strategy_id,
                "latest_market_id": market.market_id,
                "latest_market_title": market.title,
                "status": "failed",
                "error": error_payload,
                "state_snapshot": {
                    "mode": state.mode,
                    "can_open_new_trades": state.can_open_new_trades,
                    "daily_stop_active": state.daily_stop_active,
                    "weekly_stop_active": state.weekly_stop_active,
                    "kill_switch_active": state.kill_switch_active,
                    "protection_pause_active": state.protection_pause_active,
                    "pause_reason": state.pause_reason,
                },
            },
        )
        return {
            "strategy_id": strategy.strategy_id,
            "status": "failed",
            "error": error_payload,
            "decision": None,
            "open_trade": None,
        }


def evaluate_candidate_across_strategies(
    market: TemperatureMarket,
    outcome: TemperatureOutcomeCandidate,
    weather: WeatherContext | None,
    config: Config,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    strategies = build_default_strategies()
    with ThreadPoolExecutor(max_workers=len(strategies) or 1) as executor:
        futures = [
            executor.submit(
                _evaluate_candidate_for_single_strategy,
                market,
                outcome,
                weather,
                config,
                strategy,
            )
            for strategy in strategies
        ]
        for future in as_completed(futures):
            results.append(future.result())
    return {
        "captured_at": now_iso(),
        "market_id": market.market_id,
        "market_title": market.title,
        "results": results,
    }
