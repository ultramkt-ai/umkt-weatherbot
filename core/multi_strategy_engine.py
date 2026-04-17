from __future__ import annotations

from dataclasses import asdict
from typing import Any

from config import Config
from core.paper_broker import create_open_trade
from core.strategy_engine import evaluate_outcome_for_strategy
from models.market import TemperatureMarket, TemperatureOutcomeCandidate
from models.weather import WeatherContext
from parallel_strategies import build_default_strategies
from storage.strategy_journal import log_strategy_cycle, log_strategy_decision, log_strategy_open_trade
from storage.strategy_report import write_strategy_report
from storage.strategy_store import load_or_create_strategy_state, save_strategy_state
from utils.time_utils import now_iso


def evaluate_candidate_across_strategies(
    market: TemperatureMarket,
    outcome: TemperatureOutcomeCandidate,
    weather: WeatherContext | None,
    config: Config,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for strategy in build_default_strategies():
        state = load_or_create_strategy_state(config, strategy.strategy_id)
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
            state.open_trades.append(open_trade)
            state.open_trades_count = len(state.open_trades)
            state.approved_trades_count += 1
            state.approved_today += 1
            state.current_cash_usd -= open_trade.net_cost_usd
            state.capital_alocado_aberto_usd += open_trade.capital_alocado_usd
            state.current_bankroll_usd = state.current_cash_usd + state.capital_alocado_aberto_usd
            open_trade_payload = asdict(open_trade)
            log_strategy_open_trade(config, strategy.strategy_id, open_trade_payload)
        else:
            state.rejected_today += 1

        state.markets_scanned_today += 1
        state.last_cycle_finished_at = now_iso()
        save_strategy_state(config, strategy.strategy_id, state)

        cycle_payload = {
            "captured_at": now_iso(),
            "strategy_id": strategy.strategy_id,
            "market_id": market.market_id,
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
                },
            },
        )
        results.append(
            {
                "strategy_id": strategy.strategy_id,
                "decision": decision_payload,
                "open_trade": open_trade_payload,
            }
        )
    return {
        "captured_at": now_iso(),
        "market_id": market.market_id,
        "market_title": market.title,
        "results": results,
    }
