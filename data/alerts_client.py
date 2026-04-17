from config import Config


class AlertsClient:
    def __init__(self, config: Config) -> None:
        self.config = config

    def fetch_alerts(self, latitude: float, longitude: float) -> dict:
        """Fetch normalized alert information for the target area.

        Expected output shape:
        {
            "severe_alert_flag": bool,
            "extreme_weather_flag": bool,
            "instability_flag": bool,
            "headline": str | None,
            "raw_alerts": list,
        }
        """
        raise NotImplementedError("NWS alerts integration is pending")
