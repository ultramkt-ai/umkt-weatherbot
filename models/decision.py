from dataclasses import dataclass
from typing import Optional

from models.weather import WeatherContext


@dataclass
class ValidationResult:
    ok: bool
    reason_code: Optional[str] = None
    reason_detail: Optional[str] = None


@dataclass
class RiskCheckResult:
    ok: bool
    reason_code: Optional[str] = None
    reason_detail: Optional[str] = None
    cluster_id: Optional[str] = None
    projected_total_exposure_pct: float = 0.0


@dataclass
class ScoreResult:
    total_score: int
    price_score: int
    threshold_score: int
    liquidity_score: int
    spread_score: int
    stability_score: int
    extreme_risk_score: int
    clarity_score: int
    correlation_score: int
    required_min_score: int
    passed: bool


@dataclass
class TradeDecision:
    decision: str
    market_id: str
    approved: bool
    rejection_code: Optional[str] = None
    score: Optional[int] = None
    cluster_id: Optional[str] = None
    approval_summary: Optional[str] = None
    weather_context: Optional[WeatherContext] = None
    trade_side: Optional[str] = None
    entry_price: Optional[float] = None
