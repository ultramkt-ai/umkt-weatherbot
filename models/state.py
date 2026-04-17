from dataclasses import dataclass, field
from typing import Optional

from models.trade import OpenTrade


@dataclass
class BotState:
    session_id: str
    started_at: str
    updated_at: str
    last_cycle_started_at: Optional[str]
    last_cycle_finished_at: Optional[str]
    initial_bankroll_usd: float
    current_cash_usd: float
    current_bankroll_usd: float
    realized_pnl_total_usd: float
    fees_paid_total_usd: float
    equity_peak_usd: float
    current_drawdown_pct: float
    max_drawdown_pct: float
    capital_alocado_aberto_usd: float
    gross_exposure_open_usd: float
    open_exposure_pct: float
    open_trades_count: int
    closed_trades_count: int
    approved_trades_count: int
    rejected_markets_count: int
    markets_scanned_today: int
    approved_today: int
    rejected_today: int
    consecutive_losses: int
    consecutive_wins: int
    last_10_closed_results: list[str] = field(default_factory=list)
    daily_pnl_usd: float = 0.0
    weekly_pnl_usd: float = 0.0
    last_daily_reset_date: Optional[str] = None
    open_trades: list[OpenTrade] = field(default_factory=list)
    open_trade_ids: list[str] = field(default_factory=list)
    cluster_exposure_map_usd: dict[str, float] = field(default_factory=dict)
    cluster_trade_count_map: dict[str, int] = field(default_factory=dict)
    daily_stop_active: bool = False
    weekly_stop_active: bool = False
    kill_switch_active: bool = False
    protection_pause_active: bool = False
    error_safe_mode_active: bool = False
    pause_reason: Optional[str] = None
    pause_started_at: Optional[str] = None
    pause_until: Optional[str] = None
    manual_review_required: bool = False
    mode: str = "ACTIVE"
    can_open_new_trades: bool = True
    can_monitor_open_trades: bool = True
    last_market_scan_at: Optional[str] = None
    last_open_trades_check_at: Optional[str] = None
    last_successful_weather_fetch_at: Optional[str] = None
    last_successful_alert_fetch_at: Optional[str] = None
    last_error_code: Optional[str] = None
    last_error_at: Optional[str] = None
    last_cycle_status_message: Optional[str] = None
    last_score_approved: Optional[int] = None
    next_market_scan_at: Optional[str] = None
    next_open_trades_check_at: Optional[str] = None
    report_generated_for_100_trades: bool = False
