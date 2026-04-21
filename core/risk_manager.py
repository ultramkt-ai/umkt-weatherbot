from config import Config
from core.cluster import build_cluster_id, cluster_exposure_usd, cluster_trade_count
from models.decision import RiskCheckResult
from models.market import TemperatureMarket
from models.state import BotState
from utils.math_utils import calculate_open_exposure_pct


def evaluate_strategy_risk_protection(state: BotState, config: Config) -> tuple[bool, str | None]:
    if state.daily_pnl_usd <= (state.initial_bankroll_usd * config.risk.daily_stop_pct):
        return False, "daily_stop_limit"
    if state.weekly_pnl_usd <= (state.initial_bankroll_usd * config.risk.weekly_stop_pct):
        return False, "weekly_stop_limit"
    if state.current_drawdown_pct <= config.risk.kill_switch_pct:
        return False, "kill_switch_limit"
    return True, None


def check_strategy_new_trade_risk(state: BotState, market: TemperatureMarket, config: Config) -> RiskCheckResult:
    protection_ok, protection_reason = evaluate_strategy_risk_protection(state, config)
    if not protection_ok:
        return RiskCheckResult(ok=False, reason_code=protection_reason)

    if not state.can_open_new_trades:
        reason = state.pause_reason or "protection_pause_active"
        return RiskCheckResult(ok=False, reason_code=reason)

    if state.open_trades_count >= config.risk.max_open_trades:
        return RiskCheckResult(ok=False, reason_code="max_open_trades_reached")

    trade_capital_usd = state.current_bankroll_usd * config.risk.risk_per_trade_pct
    projected_capital = state.capital_alocado_aberto_usd + trade_capital_usd
    projected_exposure_pct = calculate_open_exposure_pct(projected_capital, state.current_bankroll_usd)
    if projected_exposure_pct > config.risk.max_total_exposure_pct:
        return RiskCheckResult(
            ok=False,
            reason_code="total_exposure_limit",
            projected_total_exposure_pct=projected_exposure_pct,
        )

    cluster_id = build_cluster_id(market)
    projected_cluster_trade_count = cluster_trade_count(state, cluster_id) + 1
    if projected_cluster_trade_count > config.risk.max_trades_per_cluster:
        return RiskCheckResult(
            ok=False,
            reason_code="cluster_limit",
            cluster_id=cluster_id,
            projected_total_exposure_pct=projected_exposure_pct,
        )

    projected_cluster_exposure_usd = cluster_exposure_usd(state, cluster_id) + trade_capital_usd
    projected_cluster_exposure_pct = calculate_open_exposure_pct(
        projected_cluster_exposure_usd,
        state.current_bankroll_usd,
    )
    if projected_cluster_exposure_pct > config.risk.max_cluster_exposure_pct:
        return RiskCheckResult(
            ok=False,
            reason_code="cluster_limit",
            cluster_id=cluster_id,
            projected_total_exposure_pct=projected_exposure_pct,
        )

    return RiskCheckResult(
        ok=True,
        cluster_id=cluster_id,
        projected_total_exposure_pct=projected_exposure_pct,
    )


# Backward-compatible aliases while the rest of the codebase migrates away from the old global naming.
evaluate_portfolio_protection = evaluate_strategy_risk_protection
check_new_trade_risk = check_strategy_new_trade_risk
