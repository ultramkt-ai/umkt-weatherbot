import json
from datetime import datetime
from threading import Lock
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import Config
from models.market import TemperatureMarket, TemperatureOutcomeCandidate
from models.weather import WeatherContext
from storage.json_store import atomic_write_json, read_json_file


class WeatherClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._cache_file = self.config.storage.state_dir / "forecast_cache.json"
        self._cache_lock = Lock()
        self._cache = self._load_cache()

    def _load_cache(self) -> dict:
        self.config.storage.state_dir.mkdir(parents=True, exist_ok=True)
        if self._cache_file.exists():
            return read_json_file(self._cache_file, default={})
        return {}

    def _save_cache(self) -> None:
        with self._cache_lock:
            atomic_write_json(self._cache_file, self._cache)

    def build_weather_context(
        self,
        market: TemperatureMarket,
        outcome: TemperatureOutcomeCandidate,
        geocoding: dict,
        primary_forecast: dict,
        secondary_forecast: dict,
        alert_summary: dict,
    ) -> WeatherContext:
        primary_value = float(primary_forecast["forecast_value"])
        secondary_value = float(secondary_forecast["forecast_value"])
        range_low = min(float(primary_forecast["range_low"]), float(secondary_forecast["range_low"]))
        range_high = max(float(primary_forecast["range_high"]), float(secondary_forecast["range_high"]))
        range_width = range_high - range_low
        source_diff = abs(primary_value - secondary_value)

        threshold_distance = self._threshold_distance(outcome, primary_value)
        range_buffer_value = max(1.0, range_width / 2)
        blocking_reason = alert_summary.get("blocking_reason")
        data_quality_ok = True

        return WeatherContext(
            market_id=market.market_id,
            primary_source_name=primary_forecast.get("source_name", "open-meteo"),
            secondary_source_name=secondary_forecast.get("source_name", "weatherapi-forecast"),
            alert_source_name=alert_summary.get("source_name", "weatherapi-alerts"),
            latitude=float(geocoding["latitude"]),
            longitude=float(geocoding["longitude"]),
            primary_forecast_value=primary_value,
            secondary_forecast_value=secondary_value,
            forecast_unit=str(primary_forecast["unit"]),
            forecast_range_low=range_low,
            forecast_range_high=range_high,
            forecast_range_width=range_width,
            threshold_distance=threshold_distance,
            range_buffer_value=range_buffer_value,
            source_diff_value=source_diff,
            severe_alert_flag=bool(alert_summary.get("severe_alert_flag", False)),
            extreme_weather_flag=bool(alert_summary.get("extreme_weather_flag", False)),
            instability_flag=bool(alert_summary.get("instability_flag", False)),
            data_quality_ok=data_quality_ok,
            notes=alert_summary.get("headline") or blocking_reason,
            alert_headline=alert_summary.get("headline"),
            blocking_reason=blocking_reason,
            raw_alert_count=int(alert_summary.get("raw_alert_count") or 0),
        )

    def _threshold_distance(self, outcome: TemperatureOutcomeCandidate, forecast_value: float) -> float:
        if outcome.bucket_type == "exact" and outcome.bucket_low is not None:
            return abs(forecast_value - outcome.bucket_low)
        if outcome.bucket_type == "range" and outcome.bucket_low is not None and outcome.bucket_high is not None:
            if outcome.bucket_low <= forecast_value <= outcome.bucket_high:
                return 0.0
            if forecast_value < outcome.bucket_low:
                return outcome.bucket_low - forecast_value
            return forecast_value - outcome.bucket_high
        if outcome.bucket_type == "or_higher" and outcome.bucket_low is not None:
            return max(0.0, outcome.bucket_low - forecast_value)
        if outcome.bucket_type == "or_below" and outcome.bucket_high is not None:
            return max(0.0, forecast_value - outcome.bucket_high)
        return 0.0

    def fetch_primary_forecast(self, market: TemperatureMarket, latitude: float, longitude: float) -> dict:
        start_date = self._market_date_iso(market)
        cache_key = self._forecast_cache_key("primary", market, latitude, longitude, start_date)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "temperature_2m",
            "timezone": "UTC",
            "start_date": start_date,
            "end_date": start_date,
        }
        url = f"{self.config.api.open_meteo_base_url}/v1/forecast?{urlencode(params)}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "weather-bot-mvp/0.1"})
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))

        hourly = payload.get("hourly") or {}
        temps = hourly.get("temperature_2m") or []
        if not temps:
            raise ValueError(f"Open-Meteo returned no hourly temperature data for {market.city}")

        temps = [float(value) for value in temps]
        normalized = {
            "source_name": "open-meteo",
            "forecast_value": max(temps),
            "range_low": min(temps),
            "range_high": max(temps),
            "unit": "celsius",
            "forecast_target_date": start_date,
        }
        self._set_cached(cache_key, normalized)
        return normalized

    def fetch_secondary_forecast(self, market: TemperatureMarket, latitude: float, longitude: float) -> dict:
        if not self.config.api.weatherapi_key:
            raise ValueError("WEATHERAPI_KEY ausente. Não é possível consultar forecast secundário real.")

        start_date = self._market_date_iso(market)
        cache_key = self._forecast_cache_key("secondary", market, latitude, longitude, start_date)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        params = {
            "key": self.config.api.weatherapi_key,
            "q": f"{latitude:.6f},{longitude:.6f}",
            "days": 1,
            "dt": start_date,
            "alerts": "no",
            "aqi": "no",
        }
        url = f"{self.config.api.weatherapi_base_url.rstrip('/')}/v1/forecast.json?{urlencode(params)}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "weather-bot-mvp/0.1"})

        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            detail = self._extract_api_error(body)
            raise ValueError(f"WeatherAPI forecast falhou ({exc.code}): {detail}") from exc

        if payload.get("error"):
            raise ValueError(f"WeatherAPI forecast retornou erro: {payload['error']}")

        forecast_days = ((payload.get("forecast") or {}).get("forecastday") or [])
        if not forecast_days:
            raise ValueError(f"WeatherAPI returned no forecastday data for {market.city} on {start_date}")

        target = None
        for item in forecast_days:
            if item.get("date") == start_date:
                target = item
                break
        if target is None:
            target = forecast_days[0]

        day = target.get("day") or {}
        maxtemp_c = day.get("maxtemp_c")
        mintemp_c = day.get("mintemp_c")
        avgtemp_c = day.get("avgtemp_c")
        if maxtemp_c is None or mintemp_c is None:
            raise ValueError(f"WeatherAPI returned incomplete daily forecast for {market.city} on {start_date}")

        normalized = {
            "source_name": "weatherapi-forecast",
            "forecast_value": float(maxtemp_c),
            "range_low": float(mintemp_c),
            "range_high": float(maxtemp_c),
            "unit": "celsius",
            "forecast_target_date": target.get("date", start_date),
            "avgtemp_c": float(avgtemp_c) if avgtemp_c is not None else None,
        }
        self._set_cached(cache_key, normalized)
        return normalized

    def _market_date_iso(self, market: TemperatureMarket) -> str:
        parsed = datetime.strptime(f"{market.event_date_label} 2026", "%B %d %Y")
        return parsed.strftime("%Y-%m-%d")

    def is_primary_cached(self, market: TemperatureMarket, latitude: float, longitude: float) -> bool:
        start_date = self._market_date_iso(market)
        cache_key = self._forecast_cache_key("primary", market, latitude, longitude, start_date)
        return self._is_cached(cache_key)

    def is_secondary_cached(self, market: TemperatureMarket, latitude: float, longitude: float) -> bool:
        start_date = self._market_date_iso(market)
        cache_key = self._forecast_cache_key("secondary", market, latitude, longitude, start_date)
        return self._is_cached(cache_key)

    def _forecast_cache_key(self, kind: str, market: TemperatureMarket, latitude: float, longitude: float, start_date: str) -> str:
        return f"{kind}|{market.city}|{latitude:.4f}|{longitude:.4f}|{start_date}"

    def _get_cached(self, cache_key: str) -> dict | None:
        with self._cache_lock:
            return self._cache.get(cache_key)

    def _set_cached(self, cache_key: str, value: dict) -> None:
        with self._cache_lock:
            self._cache[cache_key] = value
            atomic_write_json(self._cache_file, self._cache)

    def _is_cached(self, cache_key: str) -> bool:
        with self._cache_lock:
            return cache_key in self._cache

    def _extract_api_error(self, body: str) -> str:
        try:
            payload = json.loads(body)
        except Exception:
            return body[:300]
        error = payload.get("error")
        if not error:
            return body[:300]
        return str(error)
