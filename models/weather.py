from dataclasses import dataclass
from typing import Optional


@dataclass
class WeatherContext:
    market_id: str
    primary_source_name: str
    secondary_source_name: str
    alert_source_name: str
    latitude: float
    longitude: float
    primary_forecast_value: float
    secondary_forecast_value: float
    forecast_unit: str
    forecast_range_low: float
    forecast_range_high: float
    forecast_range_width: float
    threshold_distance: float
    range_buffer_value: float
    source_diff_value: float
    severe_alert_flag: bool
    extreme_weather_flag: bool
    instability_flag: bool
    data_quality_ok: bool
    notes: Optional[str] = None
