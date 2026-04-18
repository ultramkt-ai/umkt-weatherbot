import json
from threading import Lock
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import Config


class AlertsClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._cache_lock = Lock()
        self._cache: dict[str, dict] = {}

    def fetch_alerts(self, latitude: float, longitude: float) -> dict:
        """Fetch normalized alert information for the target area.

        Output shape:
        {
            "source_name": str,
            "severe_alert_flag": bool,
            "extreme_weather_flag": bool,
            "instability_flag": bool,
            "headline": str | None,
            "raw_alerts": list,
            "blocking_reason": str | None,
            "raw_alert_count": int,
        }
        """
        cache_key = f"{latitude:.4f}|{longitude:.4f}"
        with self._cache_lock:
            cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        if not self.config.api.weatherapi_key:
            raise ValueError("WEATHERAPI_KEY ausente. Não é possível consultar alertas reais.")

        params = {
            "key": self.config.api.weatherapi_key,
            "q": f"{latitude:.6f},{longitude:.6f}",
        }
        url = f"{self.config.api.weatherapi_base_url.rstrip('/')}/v1/alerts.json?{urlencode(params)}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "weather-bot-mvp/0.1"})

        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            detail = self._extract_api_error(body)
            raise ValueError(f"WeatherAPI alerts falhou ({exc.code}): {detail}") from exc

        if payload.get("error"):
            raise ValueError(f"WeatherAPI alerts retornou erro: {payload['error']}")

        alerts_wrapper = payload.get("alerts") or {}
        raw_alerts = alerts_wrapper.get("alert") or []
        headline = raw_alerts[0].get("headline") if raw_alerts else None
        severe = any(self._is_severe_alert(alert) for alert in raw_alerts)
        extreme = any(self._is_extreme_alert(alert) for alert in raw_alerts)
        instability = bool(raw_alerts)

        blocking_reason = None
        if extreme:
            blocking_reason = "weather_alert_extreme"
        elif severe:
            blocking_reason = "weather_alert_severe"
        elif instability:
            blocking_reason = "weather_alert_active"

        normalized = {
            "source_name": "weatherapi-alerts",
            "severe_alert_flag": severe,
            "extreme_weather_flag": extreme,
            "instability_flag": instability,
            "headline": headline,
            "raw_alerts": raw_alerts,
            "blocking_reason": blocking_reason,
            "raw_alert_count": len(raw_alerts),
        }
        with self._cache_lock:
            self._cache[cache_key] = normalized
        return normalized

    def _is_severe_alert(self, alert: dict) -> bool:
        severity = str(alert.get("severity") or "").strip().lower()
        event = str(alert.get("event") or "").strip().lower()
        headline = str(alert.get("headline") or "").strip().lower()
        text = " ".join([severity, event, headline])
        severe_terms = (
            "severe",
            "major",
            "extreme",
            "hurricane",
            "tornado",
            "flood warning",
            "flash flood",
            "red flag warning",
            "blizzard",
            "ice storm",
            "excessive heat",
        )
        return any(term in text for term in severe_terms)

    def _is_extreme_alert(self, alert: dict) -> bool:
        severity = str(alert.get("severity") or "").strip().lower()
        event = str(alert.get("event") or "").strip().lower()
        headline = str(alert.get("headline") or "").strip().lower()
        text = " ".join([severity, event, headline])
        extreme_terms = (
            "extreme",
            "catastrophic",
            "tornado emergency",
            "hurricane warning",
            "flash flood emergency",
        )
        return any(term in text for term in extreme_terms)

    def _extract_api_error(self, body: str) -> str:
        try:
            payload = json.loads(body)
        except Exception:
            return body[:300]
        error = payload.get("error")
        if not error:
            return body[:300]
        return str(error)
