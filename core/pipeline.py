from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from dataclasses import asdict
from datetime import datetime
from time import perf_counter
from typing import Any

from config import Config
from core.decision_engine import evaluate_temperature_outcome_for_entry
from core.multi_strategy_engine import evaluate_candidate_across_strategies
from core.normalizer import normalize_temperature_market
from core.paper_broker import create_open_trade
from core.portfolio import apply_open_trade_to_state
from core.risk_manager import evaluate_portfolio_protection
from core.scanner import scan_weather_us_markets
from data.alerts_client import AlertsClient
from data.geocoding_client import GeocodingClient
from data.polymarket_client import PolymarketClient
from data.polymarket_clob_client import PolymarketClobClient
from data.weather_catalog import WeatherMarketCatalog
from data.weather_client import WeatherClient
from models.state import BotState
from models.weather import WeatherContext
from storage.journal import (
    log_decision,
    log_market_candidate,
    log_open_trade,
    log_operable_candidate,
    log_rejection,
    log_runtime_event,
    log_watchlist_candidate,
    log_weather_failure,
    log_weather_timing,
)
from storage.funnel_report import write_funnel_report
from utils.time_utils import now_dt, now_iso


@dataclass
class WeatherContextBuildError(Exception):
    stage: str
    rejection_code: str
    detail: str
    original_error: str
    query: str | None = None

    def to_payload(self, market: Any, outcome: Any) -> dict[str, Any]:
        return {
            "timestamp": now_iso(),
            "market_id": market.market_id,
            "title": market.title,
            "city": market.city,
            "country": market.country,
            "outcome_label": outcome.outcome_label,
            "stage": self.stage,
            "rejection_code": self.rejection_code,
            "detail": self.detail,
            "original_error": self.original_error,
            "query": self.query,
        }


@dataclass
class WeatherTaskResult:
    weather: WeatherContext | None = None
    failure: dict[str, Any] | None = None
    timings_ms: dict[str, float] | None = None


def _build_stub_weather_context(market: Any, outcome: Any) -> WeatherContext:
    forecast_anchor = None
    if outcome.bucket_type in {"exact", "range"}:
        values = [value for value in [outcome.bucket_low, outcome.bucket_high] if value is not None]
        forecast_anchor = sum(values) / len(values) if values else 0.0
    elif outcome.bucket_type == "or_higher":
        forecast_anchor = (outcome.bucket_low or 0.0) - 4.5
    elif outcome.bucket_type == "or_below":
        forecast_anchor = (outcome.bucket_high or 0.0) + 4.5
    else:
        forecast_anchor = 0.0

    secondary_forecast = forecast_anchor + 0.6
    range_low = min(forecast_anchor, secondary_forecast) - 0.8
    range_high = max(forecast_anchor, secondary_forecast) + 0.8

    return WeatherContext(
        market_id=market.market_id,
        primary_source_name="stub-open-meteo",
        secondary_source_name="stub-weatherapi",
        alert_source_name="stub-nws",
        latitude=0.0,
        longitude=0.0,
        primary_forecast_value=forecast_anchor,
        secondary_forecast_value=secondary_forecast,
        forecast_unit="celsius",
        forecast_range_low=range_low,
        forecast_range_high=range_high,
        forecast_range_width=range_high - range_low,
        threshold_distance=0.0,
        range_buffer_value=4.5,
        source_diff_value=abs(forecast_anchor - secondary_forecast),
        severe_alert_flag=False,
        extreme_weather_flag=False,
        instability_flag=False,
        data_quality_ok=True,
        notes="stub weather context until real API integrations are wired",
    )


def _build_weather_context(
    market: Any,
    outcome: Any,
    config: Config,
    geocoding_client: GeocodingClient,
    weather_client: WeatherClient,
    alerts_client: AlertsClient,
    weather_cache: dict[str, WeatherContext],
) -> WeatherContext:
    timings_ms: dict[str, float] = {}

    cache_key = f"{market.city}|{market.country}|{market.event_date_label}|{outcome.outcome_label}"
    if cache_key in weather_cache:
        timings_ms["pipeline_cache_hit"] = 1.0
        timings_ms["geocode_cache_hit"] = 1.0
        timings_ms["primary_forecast_cache_hit"] = 1.0
        timings_ms["secondary_forecast_cache_hit"] = 1.0
        setattr(weather_cache[cache_key], "_weather_timings_ms", timings_ms)
        return weather_cache[cache_key]

    query_parts = [market.city]
    country = (market.country or "").strip()
    if country and len(country) > 3:
        query_parts.append(country)
    query = ", ".join(part for part in query_parts if part)
    timings_ms["pipeline_cache_hit"] = 0.0
    timings_ms["geocode_cache_hit"] = 1.0 if geocoding_client.is_cached(query) else 0.0

    geocoding_started = perf_counter()
    try:
        geocoding = geocoding_client.geocode(query)
        timings_ms["geocode"] = round((perf_counter() - geocoding_started) * 1000, 2)
    except Exception as exc:
        timings_ms["geocode"] = round((perf_counter() - geocoding_started) * 1000, 2)
        raise WeatherContextBuildError(
            stage="geocoding",
            rejection_code="geocoding_failed",
            detail=f"Falha ao geocodificar {query}",
            original_error=repr(exc),
            query=query,
        ) from exc

    primary_started = perf_counter()
    try:
        timings_ms["primary_forecast_cache_hit"] = 1.0 if weather_client.is_primary_cached(market, geocoding["latitude"], geocoding["longitude"]) else 0.0
        primary_forecast = weather_client.fetch_primary_forecast(market, geocoding["latitude"], geocoding["longitude"])
        timings_ms["primary_forecast"] = round((perf_counter() - primary_started) * 1000, 2)
    except Exception as exc:
        timings_ms["primary_forecast"] = round((perf_counter() - primary_started) * 1000, 2)
        raise WeatherContextBuildError(
            stage="primary_forecast",
            rejection_code="primary_forecast_failed",
            detail=f"Falha no forecast primário para {market.city}",
            original_error=repr(exc),
            query=query,
        ) from exc

    secondary_started = perf_counter()
    try:
        timings_ms["secondary_forecast_cache_hit"] = 1.0 if weather_client.is_secondary_cached(market, geocoding["latitude"], geocoding["longitude"]) else 0.0
        secondary_forecast = weather_client.fetch_secondary_forecast(market, geocoding["latitude"], geocoding["longitude"])
        timings_ms["secondary_forecast"] = round((perf_counter() - secondary_started) * 1000, 2)
    except Exception as exc:
        timings_ms["secondary_forecast"] = round((perf_counter() - secondary_started) * 1000, 2)
        raise WeatherContextBuildError(
            stage="secondary_forecast",
            rejection_code="secondary_forecast_failed",
            detail=f"Falha no forecast secundário para {market.city}",
            original_error=repr(exc),
            query=query,
        ) from exc

    alerts_started = perf_counter()
    try:
        alert_summary = alerts_client.fetch_alerts(geocoding["latitude"], geocoding["longitude"])
        timings_ms["alerts"] = round((perf_counter() - alerts_started) * 1000, 2)
    except Exception as exc:
        timings_ms["alerts"] = round((perf_counter() - alerts_started) * 1000, 2)
        raise WeatherContextBuildError(
            stage="alerts",
            rejection_code="alerts_failed",
            detail=f"Falha ao consultar alertas para {market.city}",
            original_error=repr(exc),
            query=query,
        ) from exc

    build_started = perf_counter()
    try:
        weather = weather_client.build_weather_context(market, outcome, geocoding, primary_forecast, secondary_forecast, alert_summary)
        timings_ms["weather_build"] = round((perf_counter() - build_started) * 1000, 2)
    except Exception as exc:
        timings_ms["weather_build"] = round((perf_counter() - build_started) * 1000, 2)
        raise WeatherContextBuildError(
            stage="context_build",
            rejection_code="weather_context_build_failed",
            detail=f"Falha ao montar weather context para {market.city}",
            original_error=repr(exc),
            query=query,
        ) from exc

    timings_ms["total"] = round(sum(value for key, value in timings_ms.items() if not key.endswith("_cache_hit")), 2)
    setattr(weather, "_weather_timings_ms", timings_ms)
    weather_cache[cache_key] = weather
    return weather


def _build_weather_task(
    market: Any,
    outcome: Any,
    config: Config,
    geocoding_client: GeocodingClient,
    weather_client: WeatherClient,
    alerts_client: AlertsClient,
    weather_cache: dict[str, WeatherContext],
) -> WeatherTaskResult:
    try:
        weather = _build_weather_context(market, outcome, config, geocoding_client, weather_client, alerts_client, weather_cache)
        return WeatherTaskResult(weather=weather, timings_ms=getattr(weather, "_weather_timings_ms", None))
    except WeatherContextBuildError as exc:
        return WeatherTaskResult(failure=exc.to_payload(market, outcome), timings_ms=None)
    except Exception as exc:
        return WeatherTaskResult(
            failure={
                "timestamp": now_iso(),
                "market_id": market.market_id,
                "title": market.title,
                "city": market.city,
                "country": market.country,
                "outcome_label": outcome.outcome_label,
                "stage": "unexpected",
                "rejection_code": "weather_context_unexpected_error",
                "detail": "Falha inesperada ao montar weather context",
                "original_error": repr(exc),
                "query": ", ".join(part for part in [market.city, market.country] if part),
            },
            timings_ms=None,
        )


def _is_market_in_operational_window(raw_market: dict[str, Any], config: Config) -> bool:
    resolution_time_raw = raw_market.get("resolution_time") or raw_market.get("event_end_time") or raw_market.get("event_start_time")
    if not resolution_time_raw:
        return False

    try:
        resolution_time = datetime.fromisoformat(str(resolution_time_raw))
    except ValueError:
        return False

    now = now_dt()
    if resolution_time.tzinfo is None:
        resolution_time = resolution_time.replace(tzinfo=now.tzinfo)

    hours_to_resolution = (resolution_time - now).total_seconds() / 3600
    return config.market.min_hours_to_resolution <= hours_to_resolution <= config.market.max_days_to_resolution * 24


def _price_bucket(price: float) -> str:
    if price < 0.90:
        return "lt_0.90"
    if price < 0.94:
        return "0.90_0.94"
    if price <= 0.98:
        return "0.94_0.98"
    if price <= 0.995:
        return "0.98_0.995"
    return "gt_0.995"


def _book_quality_bucket(market: Any) -> str:
    best_bid = market.best_bid or 0.0
    best_ask = market.best_ask or 0.0
    bid_levels = market.bid_levels or 0
    ask_levels = market.ask_levels or 0
    spread = market.spread if market.spread is not None else 1.0

    if best_bid >= 0.05 and best_ask and best_ask <= 0.95 and bid_levels >= 2 and ask_levels >= 2 and spread <= 0.10:
        return "operable"
    if bid_levels > 0 and ask_levels > 0:
        return "two_sided_bad"
    if bid_levels > 0 and ask_levels == 0:
        return "bid_only"
    if ask_levels > 0 and bid_levels == 0:
        return "ask_only"
    return "empty_book"


def _classify_candidate(market: Any, outcome: Any, decision: Any) -> tuple[str, str | None]:
    best_bid = market.best_bid or 0.0
    best_ask = market.best_ask or 0.0
    spread = market.spread if market.spread is not None else 1.0
    selected_price = decision.entry_price if getattr(decision, "entry_price", None) is not None else outcome.no_price
    in_target_band = 0.94 <= selected_price <= 0.98
    in_extended_band = 0.90 <= selected_price <= 0.995
    has_some_book = (market.bid_levels or 0) > 0 or (market.ask_levels or 0) > 0

    if decision.approved:
        if best_bid >= 0.05 and (best_ask == 0.0 or best_ask <= 0.95) and market.bid_levels >= 2 and market.ask_levels >= 2 and spread <= 0.10:
            return "OPERABLE", None
        if in_target_band and has_some_book:
            return "EXECUTABLE_EXPERIMENT", "approved_but_bad_book"
        return "WATCHLIST", "approved_but_bad_book"

    if decision.rejection_code in {"thin_order_book", "weak_best_bid", "hostile_best_ask"} and in_extended_band:
        return "EXECUTABLE_EXPERIMENT", decision.rejection_code

    if decision.rejection_code == "price_out_of_range" and in_extended_band and has_some_book:
        return "EXECUTABLE_EXPERIMENT", "price_near_band"

    if decision.rejection_code in {"thin_order_book", "weak_best_bid", "hostile_best_ask", "price_out_of_range", "score_rejected"} and in_extended_band:
        return "WATCHLIST", decision.rejection_code

    return "REJECTED", decision.rejection_code


def _debug_timing(config: Config, cycle_stats: dict[str, Any], stage: str, started_at: float) -> None:
    if not config.runtime.debug_timing:
        return
    cycle_stats.setdefault("timings", []).append({
        "stage": stage,
        "elapsed_sec": round(perf_counter() - started_at, 3),
        "captured_at": now_iso(),
    })


def run_market_scan_cycle(state: BotState, config: Config) -> BotState:
    cycle_started_perf = perf_counter()
    now = now_dt()
    today = now.date().isoformat()
    
    # Reset diário explícito à meia-noite
    if state.last_daily_reset_date != today:
        state.daily_pnl_usd = 0.0
        state.daily_stop_active = False
        state.last_daily_reset_date = today
        log_runtime_event(config, {"event": "daily_reset", "date": today, "reason": "midnight_reset"})
    
    cycle_stats: dict[str, Any] = {
        "cycle_started_at": now_iso(),
        "cycle_finished_at": None,
        "raw_scanned": 0,
        "scanned_candidates": [],
        "normalization_failures": [],
        "decisions": [],
        "watchlist": [],
        "operable": [],
        "executable_experiment": [],
        "opened_trades": [],
    }
    protection_ok, protection_reason = evaluate_portfolio_protection(state, config)
    if not protection_ok:
        state.can_open_new_trades = False
        state.pause_reason = protection_reason
        state.daily_stop_active = protection_reason == "daily_stop_limit"
        state.weekly_stop_active = protection_reason == "weekly_stop_limit"
        state.kill_switch_active = protection_reason == "kill_switch_limit"
    else:
        state.can_open_new_trades = True
        state.daily_stop_active = False
        state.weekly_stop_active = False
        state.kill_switch_active = False
        if state.pause_reason in {"daily_stop_limit", "weekly_stop_limit", "kill_switch_limit"}:
            state.pause_reason = None

    client = PolymarketClient(config)
    clob_client = PolymarketClobClient(config)
    geocoding_client = GeocodingClient(config)
    weather_client = WeatherClient(config)
    alerts_client = AlertsClient(config)
    catalog = WeatherMarketCatalog(config)
    weather_cache: dict[str, WeatherContext] = {}
    _debug_timing(config, cycle_stats, "clients_initialized", cycle_started_perf)

    scanned_candidates = [
        item for item in catalog.load_valid_markets()
        if _is_market_in_operational_window(item, config)
    ]
    raw_markets: list[dict[str, Any]] = []

    if not scanned_candidates:
        discovery_started = perf_counter()
        page_size = 200
        max_pages = 10
        next_cursor: str | None = None
        for _ in range(max_pages):
            batch, next_cursor = client.fetch_open_markets_keyset(
                limit=page_size,
                after_cursor=next_cursor,
                order="liquidity_num",
                ascending=False,
            )
            if not batch:
                break
            raw_markets.extend(batch)
            if not next_cursor:
                break

        scanned_candidates = [
            item for item in scan_weather_us_markets(raw_markets)
            if _is_market_in_operational_window(item, config)
        ]

        weather_event_slugs = client.discover_weather_event_slugs()
        if weather_event_slugs:
            hydrated_markets: list[dict[str, Any]] = []
            seen_market_ids: set[str] = {
                str(item.get("market_id") or item.get("id") or "") for item in scanned_candidates if item.get("market_id") or item.get("id")
            }
            for slug in weather_event_slugs[:80]:
                event = client.get_event_by_slug(slug)
                for market_payload in event.get("markets") or []:
                    normalized_payload = client.normalize_market_payload(market_payload)
                    market_id = str(normalized_payload.get("market_id") or "")
                    if not market_id or market_id in seen_market_ids:
                        continue
                    seen_market_ids.add(market_id)
                    hydrated_markets.append(normalized_payload)
            if hydrated_markets:
                scanned_candidates.extend(
                    item for item in scan_weather_us_markets(hydrated_markets)
                    if _is_market_in_operational_window(item, config)
                )

        deduped_candidates: list[dict[str, Any]] = []
        seen_market_ids: set[str] = set()
        for item in scanned_candidates:
            market_id = str(item.get("market_id") or item.get("id") or "")
            if not market_id or market_id in seen_market_ids:
                continue
            seen_market_ids.add(market_id)
            deduped_candidates.append(item)
        scanned_candidates = deduped_candidates
        catalog.save_markets(scanned_candidates)
        _debug_timing(config, cycle_stats, "discovery_and_catalog_refresh", discovery_started)

    state.last_market_scan_at = now_iso()
    state.markets_scanned_today += len(scanned_candidates)
    cycle_stats["raw_scanned"] = len(raw_markets)
    cycle_stats["scanned_candidates"] = [
        {
            "market_id": item.get("market_id") or item.get("id"),
            "title": item.get("title"),
            "slug": item.get("slug"),
            "liquidity": item.get("liquidity"),
            "spread": item.get("spread"),
        }
        for item in scanned_candidates
    ]

    candidate_limit = max(1, config.runtime.max_candidates_per_cycle)
    _debug_timing(config, cycle_stats, "pre_candidate_loop", cycle_started_perf)

    prepared_markets: list[Any] = []
    weather_futures: dict[tuple[str, int], Future[WeatherTaskResult]] = {}
    weather_pool_started = perf_counter()

    with ThreadPoolExecutor(max_workers=max(1, config.runtime.weather_parallel_workers), thread_name_prefix="weather") as weather_executor:
        for raw_market in scanned_candidates[:candidate_limit]:
            candidate_log = {
                "timestamp": now_iso(),
                "market_id": raw_market.get("market_id") or raw_market.get("id"),
                "title": raw_market.get("title"),
                "slug": raw_market.get("slug"),
                "liquidity": raw_market.get("liquidity"),
                "spread": raw_market.get("spread"),
            }
            log_market_candidate(config, candidate_log)

            try:
                market = normalize_temperature_market(raw_market, config)
            except Exception as exc:
                state.rejected_markets_count += 1
                state.rejected_today += 1
                rejection = {
                    "timestamp": now_iso(),
                    "market_id": raw_market.get("market_id") or raw_market.get("id"),
                    "title": raw_market.get("title"),
                    "reason_code": "normalization_failed",
                    "reason_detail": str(exc),
                }
                cycle_stats["normalization_failures"].append(rejection)
                log_rejection(config, rejection)
                continue

            if not market.outcomes:
                state.rejected_markets_count += 1
                state.rejected_today += 1
                rejection = {
                    "timestamp": now_iso(),
                    "market_id": market.market_id,
                    "title": market.title,
                    "reason_code": "no_temperature_outcomes",
                }
                cycle_stats["normalization_failures"].append(rejection)
                log_rejection(config, rejection)
                continue

            prepared_markets.append(market)

            for outcome in market.outcomes:
                if outcome.token_id and any(open_trade.token_id == outcome.token_id for open_trade in state.open_trades):
                    continue

                book_map = clob_client.get_book_map([outcome.token_id] if outcome.token_id else [])
                book = book_map.get(outcome.token_id or "")
                if book:
                    bids = book.get("bids") or []
                    asks = book.get("asks") or []
                    best_bid = float(bids[0].get("price", 0.0)) if bids else 0.0
                    best_ask = float(asks[0].get("price", 0.0)) if asks else 0.0
                    market.best_bid = best_bid if bids else None
                    market.best_ask = best_ask if asks else None
                    market.bid_levels = len(bids)
                    market.ask_levels = len(asks)
                    if best_bid and best_ask:
                        market.spread = max(0.0, best_ask - best_bid)
                    last_trade_price = float(book.get("last_trade_price") or 0.0)
                    if last_trade_price > 0:
                        outcome.yes_price = last_trade_price
                        outcome.no_price = max(0.0, 1.0 - last_trade_price)

                if market.liquidity < config.market.min_liquidity_usd:
                    continue
                if not (config.market.min_no_price <= outcome.no_price <= config.market.max_no_price) and not (
                    config.market.enable_yes_strategy and config.market.min_yes_price <= outcome.yes_price <= config.market.max_yes_price
                ):
                    continue

                weather_futures[(market.market_id, outcome.outcome_index)] = weather_executor.submit(
                    _build_weather_task,
                    market,
                    outcome,
                    config,
                    geocoding_client,
                    weather_client,
                    alerts_client,
                    weather_cache,
                )

        _debug_timing(config, cycle_stats, "weather_pool_prefetch", weather_pool_started)

        for market in prepared_markets:
            for outcome in market.outcomes:
                if outcome.token_id and any(open_trade.token_id == outcome.token_id for open_trade in state.open_trades):
                    continue

                cheap_rejection = None
                if market.liquidity < config.market.min_liquidity_usd:
                    cheap_rejection = "low_liquidity"
                elif not (config.market.min_no_price <= outcome.no_price <= config.market.max_no_price) and not (
                    config.market.enable_yes_strategy and config.market.min_yes_price <= outcome.yes_price <= config.market.max_yes_price
                ):
                    cheap_rejection = "price_out_of_range"

                if cheap_rejection:
                    decision = type("CheapDecision", (), {
                        "approved": False,
                        "rejection_code": cheap_rejection,
                        "score": None,
                        "cluster_id": None,
                        "trade_side": None,
                        "entry_price": None,
                        "approval_summary": None,
                    })()
                    weather = None
                    weather_failure = None
                else:
                    weather_started = perf_counter()
                    weather_failure = None
                    weather_timings = None
                    weather_result = weather_futures.get((market.market_id, outcome.outcome_index))
                    if weather_result is None:
                        weather = None
                        weather_failure = {
                            "timestamp": now_iso(),
                            "market_id": market.market_id,
                            "title": market.title,
                            "city": market.city,
                            "country": market.country,
                            "outcome_label": outcome.outcome_label,
                            "stage": "prefetch",
                            "rejection_code": "weather_prefetch_missing",
                            "detail": "Futuro de weather não encontrado para o candidato elegível.",
                            "original_error": None,
                            "query": ", ".join(part for part in [market.city, market.country] if part),
                        }
                        log_weather_failure(config, weather_failure)
                        decision = type("WeatherFailureDecision", (), {
                            "approved": False,
                            "rejection_code": "weather_prefetch_missing",
                            "score": None,
                            "cluster_id": None,
                            "trade_side": None,
                            "entry_price": None,
                            "approval_summary": None,
                        })()
                    else:
                        weather_payload = weather_result.result()
                        weather = weather_payload.weather
                        weather_failure = weather_payload.failure
                        weather_timings = weather_payload.timings_ms or (getattr(weather, "_weather_timings_ms", None) if weather is not None else None)
                        if weather is not None:
                            state.last_successful_weather_fetch_at = now_iso()
                            state.last_successful_alert_fetch_at = now_iso()
                            log_weather_timing(config, {
                                "timestamp": now_iso(),
                                "market_id": market.market_id,
                                "city": market.city,
                                "country": market.country,
                                "outcome_label": outcome.outcome_label,
                                "timings_ms": weather_timings or {},
                            })
                            decision = evaluate_temperature_outcome_for_entry(market, outcome, weather, state, config)
                        else:
                            if weather_failure is not None and weather_timings is not None:
                                weather_failure["timings_ms"] = weather_timings
                            log_weather_failure(config, weather_failure)
                            decision = type("WeatherFailureDecision", (), {
                                "approved": False,
                                "rejection_code": weather_failure["rejection_code"],
                                "score": None,
                                "cluster_id": None,
                                "trade_side": None,
                                "entry_price": None,
                                "approval_summary": None,
                            })()
                    _debug_timing(config, cycle_stats, f"weather_context:{market.market_id}", weather_started)

                candidate_class, watch_reason = _classify_candidate(market, outcome, decision)
                decision_log = {
                    "timestamp": now_iso(),
                    "market_id": market.market_id,
                    "title": market.title,
                    "city": market.city,
                    "outcome_label": outcome.outcome_label,
                    "token_id": outcome.token_id,
                    "approved": decision.approved,
                    "rejection_code": decision.rejection_code,
                    "score": decision.score,
                    "cluster_id": decision.cluster_id,
                    "candidate_class": candidate_class,
                    "watch_reason": watch_reason,
                    "no_price": outcome.no_price,
                    "yes_price": outcome.yes_price,
                    "trade_side": getattr(decision, "trade_side", None),
                    "entry_price": getattr(decision, "entry_price", None),
                    "price_bucket": _price_bucket(getattr(decision, "entry_price", None) if getattr(decision, "entry_price", None) is not None else outcome.no_price),
                    "book_quality_bucket": _book_quality_bucket(market),
                    "liquidity": market.liquidity,
                    "spread": market.spread,
                    "best_bid": market.best_bid,
                    "best_ask": market.best_ask,
                    "bid_levels": market.bid_levels,
                    "ask_levels": market.ask_levels,
                    "resolution_time": market.resolution_time,
                    "weather_data_quality_ok": getattr(weather, "data_quality_ok", None) if weather else None,
                    "weather_primary_source": getattr(weather, "primary_source_name", None) if weather else None,
                    "weather_secondary_source": getattr(weather, "secondary_source_name", None) if weather else None,
                    "weather_alert_source": getattr(weather, "alert_source_name", None) if weather else None,
                    "weather_alert_headline": getattr(weather, "alert_headline", None) if weather else None,
                    "weather_blocking_reason": getattr(weather, "blocking_reason", None) if weather else None,
                    "weather_raw_alert_count": getattr(weather, "raw_alert_count", None) if weather else None,
                    "weather_severe_alert_flag": getattr(weather, "severe_alert_flag", None) if weather else None,
                    "weather_extreme_flag": getattr(weather, "extreme_weather_flag", None) if weather else None,
                    "weather_instability_flag": getattr(weather, "instability_flag", None) if weather else None,
                    "weather_threshold_distance": getattr(weather, "threshold_distance", None) if weather else None,
                    "weather_range_width": getattr(weather, "forecast_range_width", None) if weather else None,
                    "weather_source_diff": getattr(weather, "source_diff_value", None) if weather else None,
                    "weather_error_stage": weather_failure.get("stage") if weather_failure else None,
                    "weather_error_detail": weather_failure.get("detail") if weather_failure else None,
                    "weather_error_original": weather_failure.get("original_error") if weather_failure else None,
                    "weather_query": weather_failure.get("query") if weather_failure else None,
                    "weather_timing_geocode_ms": (weather_timings or {}).get("geocode") if 'weather_timings' in locals() else None,
                    "weather_timing_primary_forecast_ms": (weather_timings or {}).get("primary_forecast") if 'weather_timings' in locals() else None,
                    "weather_timing_secondary_forecast_ms": (weather_timings or {}).get("secondary_forecast") if 'weather_timings' in locals() else None,
                    "weather_timing_alerts_ms": (weather_timings or {}).get("alerts") if 'weather_timings' in locals() else None,
                    "weather_timing_build_ms": (weather_timings or {}).get("weather_build") if 'weather_timings' in locals() else None,
                    "weather_timing_total_ms": (weather_timings or {}).get("total") if 'weather_timings' in locals() else None,
                }
                cycle_stats["decisions"].append(decision_log)
                log_decision(config, decision_log)

                multi_started = perf_counter()
                multi_strategy_result = evaluate_candidate_across_strategies(
                    market=market,
                    outcome=outcome,
                    weather=weather,
                    config=config,
                )
                _debug_timing(config, cycle_stats, f"multi_strategy:{market.market_id}", multi_started)
                decision_log["multi_strategy"] = {
                    "approved_count": sum(1 for item in multi_strategy_result["results"] if item["decision"]["decision"]["approved"]),
                    "strategies": [
                        {
                            "strategy_id": item["strategy_id"],
                            "approved": item["decision"]["decision"]["approved"],
                            "trade_side": item["decision"]["decision"].get("trade_side"),
                            "entry_price": item["decision"]["decision"].get("entry_price"),
                            "rejection_code": item["decision"]["decision"].get("rejection_code"),
                            "score": item["decision"]["decision"].get("score"),
                        }
                        for item in multi_strategy_result["results"]
                    ],
                }

                if candidate_class == "WATCHLIST":
                    cycle_stats["watchlist"].append(decision_log)
                    log_watchlist_candidate(config, decision_log)

                if candidate_class == "EXECUTABLE_EXPERIMENT":
                    cycle_stats["executable_experiment"].append(decision_log)
                    log_watchlist_candidate(config, {**decision_log, "watch_reason": watch_reason or "executable_experiment"})

                if candidate_class == "OPERABLE":
                    cycle_stats["operable"].append(decision_log)
                    log_operable_candidate(config, decision_log)

                if not decision.approved:
                    state.rejected_markets_count += 1
                    state.rejected_today += 1
                    log_rejection(config, decision_log)
                    continue

                if candidate_class not in {"OPERABLE", "WATCHLIST", "EXECUTABLE_EXPERIMENT"}:
                    continue

                open_trade = create_open_trade(
                    market=market,
                    outcome=outcome,
                    weather=weather,
                    cluster_id=decision.cluster_id or "unknown",
                    score=decision.score or 0,
                    approval_summary=decision.approval_summary or "Approved by pipeline",
                    config=config,
                    bankroll_usd=state.current_bankroll_usd,
                    side=decision.trade_side or "NO",
                    entry_price=decision.entry_price,
                )
                state = apply_open_trade_to_state(state, open_trade)
                open_trade_payload = asdict(open_trade)
                cycle_stats["opened_trades"].append(open_trade_payload)
                log_open_trade(config, open_trade_payload)
                break

    state.current_bankroll_usd = state.current_cash_usd + state.capital_alocado_aberto_usd
    _debug_timing(config, cycle_stats, "cycle_total", cycle_started_perf)
    cycle_stats["cycle_finished_at"] = now_iso()
    write_funnel_report(config, cycle_stats)
    return state
