import json
from threading import Lock
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import Config
from storage.json_store import atomic_write_json, read_json_file


class GeocodingClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._cache_file = self.config.storage.state_dir / "geocoding_cache.json"
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

    def geocode(self, query: str) -> dict:
        cache_key = query.strip().lower()
        with self._cache_lock:
            cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        candidates = [query.strip()]
        if "," in query:
            fallback = query.split(",", 1)[0].strip()
            if fallback and fallback.lower() != cache_key:
                candidates.append(fallback)

        for candidate in candidates:
            params = {
                "name": candidate,
                "count": 1,
                "language": "en",
                "format": "json",
            }
            url = f"{self.config.api.open_meteo_geocoding_url}/v1/search?{urlencode(params)}"
            request = Request(url, headers={"Accept": "application/json", "User-Agent": "weather-bot-mvp/0.1"})
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))

            results = payload.get("results") or []
            if not results:
                continue

            top = results[0]
            normalized = {
                "query": candidate,
                "city": top.get("name") or candidate,
                "state": top.get("admin1"),
                "country_code": top.get("country_code"),
                "latitude": float(top["latitude"]),
                "longitude": float(top["longitude"]),
                "timezone": top.get("timezone"),
            }
            with self._cache_lock:
                self._cache[cache_key] = normalized
                atomic_write_json(self._cache_file, self._cache)
            return normalized

        raise ValueError(f"Location not found: {query}")

    def is_cached(self, query: str) -> bool:
        cache_key = query.strip().lower()
        with self._cache_lock:
            return cache_key in self._cache
