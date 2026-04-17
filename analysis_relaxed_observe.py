from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import json

from config import load_config
from core.decision_engine import evaluate_temperature_outcome_for_entry
from core.normalizer import normalize_temperature_market
from core.pipeline import _build_stub_weather_context
from data.polymarket_client import PolymarketClient
from data.polymarket_clob_client import PolymarketClobClient
from storage.state_store import load_or_create_state


def main() -> None:
    config = load_config()
    state = load_or_create_state(config)
    state.open_trades = []
    state.open_trade_ids = []
    state.open_trades_count = 0
    state.capital_alocado_aberto_usd = 0.0
    state.gross_exposure_open_usd = 0.0
    state.open_exposure_pct = 0.0
    state.cluster_exposure_map_usd = {}
    state.cluster_trade_count_map = {}
    state.current_cash_usd = state.initial_bankroll_usd
    state.current_bankroll_usd = state.initial_bankroll_usd

    client = PolymarketClient(config)
    clob = PolymarketClobClient(config)

    slugs = client.discover_weather_event_slugs()

    seen_market_ids: set[str] = set()
    raw_markets: list[dict] = []
    for slug in slugs[:80]:
        event = client.get_event_by_slug(slug)
        for market_payload in event.get("markets") or []:
            normalized = client.normalize_market_payload(market_payload)
            market_id = str(normalized.get("market_id") or "")
            if not market_id or market_id in seen_market_ids:
                continue
            seen_market_ids.add(market_id)
            raw_markets.append(normalized)

    counts = Counter()
    approved: list[dict] = []
    near_misses: list[dict] = []
    blocked_by_book: list[dict] = []
    operable: list[dict] = []
    watchlist: list[dict] = []

    for raw in raw_markets[:220]:
        try:
            market = normalize_temperature_market(raw, config)
        except Exception as exc:
            counts[f"normalize:{exc}"] += 1
            continue

        outcome = market.outcomes[0]
        book_map = clob.get_book_map([outcome.token_id] if outcome.token_id else [])
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

        weather = _build_stub_weather_context(market, outcome)
        decision = evaluate_temperature_outcome_for_entry(market, outcome, weather, state, config)
        reason = decision.rejection_code or "approved"
        counts[reason] += 1

        row = {
            "city": market.city,
            "title": market.title,
            "outcome_label": outcome.outcome_label,
            "no_price": outcome.no_price,
            "yes_price": outcome.yes_price,
            "liquidity": market.liquidity,
            "spread": market.spread,
            "best_bid": market.best_bid,
            "best_ask": market.best_ask,
            "bid_levels": market.bid_levels,
            "ask_levels": market.ask_levels,
            "resolution_time": market.resolution_time,
            "decision": reason,
            "score": decision.score,
        }

        if decision.approved:
            approved.append(row)
            if (
                row["best_bid"] is not None and row["best_bid"] >= 0.05
                and row["best_ask"] is not None and row["best_ask"] <= 0.95
                and row["bid_levels"] >= 2 and row["ask_levels"] >= 2
                and row["spread"] <= 0.10
            ):
                operable.append(row)
            else:
                watchlist.append({**row, "watch_reason": "approved_but_bad_book"})
        elif reason in {"thin_order_book", "weak_best_bid", "hostile_best_ask"}:
            blocked_by_book.append(row)
            if 0.90 <= row["no_price"] <= 0.99:
                watchlist.append({**row, "watch_reason": reason})
        elif reason == "score_rejected" or reason == "price_out_of_range":
            near_misses.append(row)

    output = {
        "counts": dict(counts),
        "operable": operable[:20],
        "watchlist": watchlist[:40],
        "approved": approved[:20],
        "near_misses": near_misses[:30],
        "blocked_by_book": blocked_by_book[:30],
    }

    config.storage.reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = config.storage.reports_dir / "relaxed_observe_report.json"
    report_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report_path)
    print(json.dumps(output["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
