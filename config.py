from dataclasses import dataclass, field
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent
DATA_RUNTIME_DIR = BASE_DIR / "data_runtime"


@dataclass(frozen=True)
class ApiConfig:
    polymarket_base_url: str = os.getenv("POLYMARKET_BASE_URL", "https://gamma-api.polymarket.com")
    polymarket_clob_base_url: str = os.getenv("POLYMARKET_CLOB_BASE_URL", "https://clob.polymarket.com")
    polymarket_data_api_base_url: str = os.getenv("POLYMARKET_DATA_API_BASE_URL", "https://data-api.polymarket.com")
    open_meteo_base_url: str = os.getenv("OPEN_METEO_BASE_URL", "https://api.open-meteo.com")
    open_meteo_geocoding_url: str = os.getenv("OPEN_METEO_GEOCODING_URL", "https://geocoding-api.open-meteo.com")
    weatherapi_base_url: str = os.getenv("WEATHERAPI_BASE_URL", "https://api.weatherapi.com")
    weatherapi_key: str = os.getenv("WEATHERAPI_KEY", "")
    nws_base_url: str = os.getenv("NWS_BASE_URL", "https://api.weather.gov")
    geoapify_base_url: str = os.getenv("GEOAPIFY_BASE_URL", "https://api.geoapify.com")
    geoapify_key: str = os.getenv("GEOAPIFY_KEY", "")


@dataclass(frozen=True)
class RiskConfig:
    initial_bankroll_usd: float = 10_000.0
    risk_per_trade_pct: float = float(os.getenv("RISK_PER_TRADE_PCT", "0.01"))
    max_total_exposure_pct: float = float(os.getenv("RISK_MAX_TOTAL_EXPOSURE_PCT", "0.10"))
    max_open_trades: int = int(os.getenv("RISK_MAX_OPEN_TRADES", "30"))
    max_cluster_exposure_pct: float = float(os.getenv("RISK_MAX_CLUSTER_EXPOSURE_PCT", "0.03"))
    max_trades_per_cluster: int = int(os.getenv("RISK_MAX_TRADES_PER_CLUSTER", "3"))
    daily_stop_pct: float = float(os.getenv("RISK_DAILY_STOP_PCT", "-0.04"))
    weekly_stop_pct: float = float(os.getenv("RISK_WEEKLY_STOP_PCT", "-0.08"))
    kill_switch_pct: float = float(os.getenv("RISK_KILL_SWITCH_PCT", "-0.12"))


@dataclass(frozen=True)
class MarketConfig:
    min_no_price: float = float(os.getenv("MARKET_MIN_NO_PRICE", "0.95"))
    max_no_price: float = float(os.getenv("MARKET_MAX_NO_PRICE", "0.999"))
    preferred_no_price_low: float = float(os.getenv("MARKET_PREFERRED_NO_PRICE_LOW", "0.98"))
    preferred_no_price_high: float = float(os.getenv("MARKET_PREFERRED_NO_PRICE_HIGH", "0.999"))
    enable_yes_strategy: bool = os.getenv("MARKET_ENABLE_YES_STRATEGY", "true").lower() == "true"
    min_yes_price: float = float(os.getenv("MARKET_MIN_YES_PRICE", "0.00"))
    max_yes_price: float = float(os.getenv("MARKET_MAX_YES_PRICE", "0.90"))
    preferred_yes_price_low: float = float(os.getenv("MARKET_PREFERRED_YES_PRICE_LOW", "0.00"))
    preferred_yes_price_high: float = float(os.getenv("MARKET_PREFERRED_YES_PRICE_HIGH", "0.90"))
    min_score: int = int(os.getenv("MARKET_MIN_SCORE", "0"))
    high_price_min_score: int = int(os.getenv("MARKET_HIGH_PRICE_MIN_SCORE", "0"))
    min_liquidity_usd: float = float(os.getenv("MARKET_MIN_LIQUIDITY_USD", "750"))
    max_spread_pct: float = float(os.getenv("MARKET_MAX_SPREAD_PCT", "0.99"))
    min_hours_to_resolution: int = int(os.getenv("MARKET_MIN_HOURS_TO_RESOLUTION", "2"))
    max_days_to_resolution: int = int(os.getenv("MARKET_MAX_DAYS_TO_RESOLUTION", "3"))
    allowed_weather_types: tuple[str, ...] = (
        "temperature_exact",
        "temperature_range",
        "temperature_or_higher",
        "temperature_or_below",
    )
    target_temperature_cities: tuple[str, ...] = ()
    us_fahrenheit_cities: tuple[str, ...] = (
        "San Francisco",
        "Chicago",
        "Atlanta",
        "NYC",
        "Seattle",
        "Miami",
        "Los Angeles",
    )
    allowed_country_codes: tuple[str, ...] = ()
    min_book_levels: int = int(os.getenv("MARKET_MIN_BOOK_LEVELS", "0"))
    min_best_bid: float = float(os.getenv("MARKET_MIN_BEST_BID", "0.0"))
    max_best_ask: float = float(os.getenv("MARKET_MAX_BEST_ASK", "1.0"))
    relaxed_observe_mode: bool = os.getenv("MARKET_RELAXED_OBSERVE_MODE", "true").lower() == "true"


@dataclass(frozen=True)
class SchedulingConfig:
    market_scan_interval_min: int = 5
    open_trades_check_interval_min: int = 5
    near_resolution_check_interval_min: int = 3
    final_hour_check_interval_min: int = 1
    near_resolution_hours: int = 6
    final_hour_hours: int = 1


@dataclass(frozen=True)
class RuntimeConfig:
    timezone: str = "America/Sao_Paulo"
    internal_temperature_unit: str = "celsius"
    internal_precipitation_unit: str = "mm"
    fees_enabled: bool = False
    estimated_fee_pct: float = 0.0
    slippage_enabled: bool = False
    estimated_slippage_pct: float = 0.0
    report_after_closed_trades: int = 100
    debug_timing: bool = os.getenv("RUNTIME_DEBUG_TIMING", "false").lower() == "true"
    max_candidates_per_cycle: int = int(os.getenv("RUNTIME_MAX_CANDIDATES_PER_CYCLE", "120"))
    weather_parallel_workers: int = int(os.getenv("RUNTIME_WEATHER_PARALLEL_WORKERS", "6"))
    cycle_timeout_seconds: int = int(os.getenv("RUNTIME_CYCLE_TIMEOUT_SECONDS", "240"))
    copytrading_max_fill_brl: float = float(os.getenv("COPYTRADING_MAX_FILL_BRL", "100"))
    usd_brl_rate: float = float(os.getenv("USD_BRL_RATE", "5.0"))


@dataclass(frozen=True)
class StorageConfig:
    state_dir: Path = DATA_RUNTIME_DIR / "state"
    logs_dir: Path = DATA_RUNTIME_DIR / "logs"
    trades_dir: Path = DATA_RUNTIME_DIR / "trades"
    reports_dir: Path = DATA_RUNTIME_DIR / "reports"
    state_file: Path = DATA_RUNTIME_DIR / "state" / "bot_state.json"
    ledger_db_file: Path = DATA_RUNTIME_DIR / "state" / "portfolio_ledger.sqlite3"


@dataclass(frozen=True)
class ExitConfig:
    tp: float = float(os.getenv("EXIT_TP", "0.02"))
    sl: float = float(os.getenv("EXIT_SL", "-0.03"))
    time_hours: int = int(os.getenv("EXIT_TIME_HOURS", "12"))


@dataclass(frozen=True)
class Config:
    api: ApiConfig = field(default_factory=ApiConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    market: MarketConfig = field(default_factory=MarketConfig)
    scheduling: SchedulingConfig = field(default_factory=SchedulingConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    exit: ExitConfig = field(default_factory=ExitConfig)


def load_config() -> Config:
    return Config()
