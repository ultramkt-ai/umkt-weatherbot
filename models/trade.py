from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class OpenTrade:
    trade_id: str
    market_id: str
    parent_slug: str
    outcome_label: str
    bucket_type: str
    bucket_low: Optional[float]
    bucket_high: Optional[float]
    token_id: Optional[str]
    entry_time: str
    side: str
    entry_price: float
    capital_alocado_usd: float
    contracts_qty: float
    gross_cost_usd: float
    fees_paid_usd: float
    net_cost_usd: float
    max_loss_usd: float
    max_profit_usd: float
    risk_pct_of_bankroll: float
    score: int
    score_band: str
    weather_type: str
    city: Optional[str]
    state: Optional[str]
    cluster_id: str
    approval_summary: str
    market_snapshot_at_entry: dict[str, Any]
    weather_snapshot_at_entry: dict[str, Any]
    status: str
    audit_status: Optional[str] = None
    audit_bucket: Optional[str] = None
    audit_notes: Optional[str] = None


@dataclass
class ClosedTrade:
    trade_id: str
    market_id: str
    parent_slug: str
    outcome_label: str
    bucket_type: str
    bucket_low: Optional[float]
    bucket_high: Optional[float]
    token_id: Optional[str]
    entry_time: str
    exit_time: str
    resolution_time: str
    side: str
    entry_price: float
    resolution_value: float
    capital_alocado_usd: float
    contracts_qty: float
    gross_cost_usd: float
    fees_paid_usd: float
    gross_settlement_value_usd: float
    net_pnl_abs: float
    roi_on_allocated_capital: float
    result: str
    hold_duration_hours: float
    score: int
    weather_type: str
    cluster_id: str
    resolution_source: str
    resolution_source_value: Any
    drawdown_after_close: float
    exit_reason: Optional[str] = None
    audit_status: Optional[str] = None
    audit_bucket: Optional[str] = None
    audit_notes: Optional[str] = None
