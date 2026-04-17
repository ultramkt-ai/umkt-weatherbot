from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any
import json
import re

from config import Config, load_config
from data.polymarket_data_client import PolymarketDataClient
from utils.time_utils import now_iso

WEATHER_TITLE_RE = re.compile(
    r"Will the highest temperature in (?P<city>.+?) be (?P<bucket>.+?) on (?P<date_label>.+?)\?",
    re.IGNORECASE,
)
PRICE_BANDS = [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.98, 0.995, 1.01]


@dataclass
class WalletAuditReport:
    wallet: str
    generated_at: str
    sample_trades: int
    unique_markets: int
    unique_weather_markets: int
    weather_trade_ratio: float
    side_frequency: dict[str, int]
    city_frequency: dict[str, int]
    price_band_frequency: dict[str, int]
    bucket_frequency: dict[str, int]
    avg_position_usdc: float
    avg_position_tokens: float
    open_vs_closed_markets: dict[str, int]
    top_cities: list[dict[str, Any]]
    top_buckets: list[dict[str, Any]]
    notes: list[str]


@dataclass
class MarketPatternReport:
    wallet: str
    generated_at: str
    weather_fill_count: int
    consolidated_weather_markets: int
    avg_fills_per_market: float
    avg_market_usdc: float
    avg_market_tokens: float
    dominant_side_by_market: dict[str, int]
    dominant_price_band_by_market: dict[str, int]
    top_cities_by_markets: list[dict[str, Any]]
    top_buckets_by_markets: list[dict[str, Any]]
    top_scaled_markets: list[dict[str, Any]]
    heuristic_summary: list[str]
    notes: list[str]


class WalletIntelligence:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = PolymarketDataClient(config)
        self.runtime_dir = config.storage.reports_dir / "wallet_intelligence"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def fetch_recent_trades(self, wallet: str, target_count: int = 2000) -> list[dict[str, Any]]:
        return self.client.list_trades_until(user=wallet, target_count=target_count)

    def analyze_wallet(self, wallet: str, target_count: int = 2000) -> WalletAuditReport:
        trades = self.fetch_recent_trades(wallet=wallet, target_count=target_count)
        positions = self.client.list_positions(user=wallet, limit=500, offset=0)

        weather_trades = [trade for trade in trades if self._is_weather_trade(trade)]
        unique_markets = {self._market_key(trade) for trade in trades if self._market_key(trade)}
        unique_weather_markets = {self._market_key(trade) for trade in weather_trades if self._market_key(trade)}

        side_counter: Counter[str] = Counter()
        city_counter: Counter[str] = Counter()
        price_band_counter: Counter[str] = Counter()
        bucket_counter: Counter[str] = Counter()
        position_usdc: list[float] = []
        position_tokens: list[float] = []

        for trade in weather_trades:
            side_counter[self._extract_side(trade)] += 1
            city = self._extract_city(trade)
            if city:
                city_counter[city] += 1
            bucket = self._extract_bucket_label(trade)
            if bucket:
                bucket_counter[bucket] += 1
            price_band_counter[self._price_band(self._extract_price(trade))] += 1

            usdc_size = self._extract_usdc_size(trade)
            token_size = self._extract_token_size(trade)
            if usdc_size > 0:
                position_usdc.append(usdc_size)
            if token_size > 0:
                position_tokens.append(token_size)

        open_closed = self._classify_positions_open_closed(positions)

        notes = []
        if trades and len(trades) < target_count:
            notes.append(f"A carteira retornou apenas {len(trades)} trades, abaixo da meta de {target_count}.")
        notes.append("Amostra operacional baseada em trades brutos. Para inferência estatística séria, agregue depois por mercado/evento único.")
        notes.append("/trades foi tratado como fonte primária do histórico. /positions foi usado só para snapshot de aberto vs encerrado.")

        report = WalletAuditReport(
            wallet=wallet,
            generated_at=now_iso(),
            sample_trades=len(trades),
            unique_markets=len(unique_markets),
            unique_weather_markets=len(unique_weather_markets),
            weather_trade_ratio=(len(weather_trades) / len(trades)) if trades else 0.0,
            side_frequency=dict(side_counter.most_common()),
            city_frequency=dict(city_counter.most_common()),
            price_band_frequency=dict(price_band_counter.most_common()),
            bucket_frequency=dict(bucket_counter.most_common()),
            avg_position_usdc=mean(position_usdc) if position_usdc else 0.0,
            avg_position_tokens=mean(position_tokens) if position_tokens else 0.0,
            open_vs_closed_markets=open_closed,
            top_cities=[{"city": city, "trades": count} for city, count in city_counter.most_common(15)],
            top_buckets=[{"bucket": bucket, "trades": count} for bucket, count in bucket_counter.most_common(20)],
            notes=notes,
        )
        market_patterns = self.analyze_market_patterns_from_trades(wallet=wallet, trades=trades)
        self._persist_report(report, market_patterns, trades, positions)
        return report

    def analyze_market_patterns(self, wallet: str, target_count: int = 2000) -> MarketPatternReport:
        trades = self.fetch_recent_trades(wallet=wallet, target_count=target_count)
        return self.analyze_market_patterns_from_trades(wallet=wallet, trades=trades)

    def analyze_market_patterns_from_trades(self, wallet: str, trades: list[dict[str, Any]]) -> MarketPatternReport:
        weather_trades = [trade for trade in trades if self._is_weather_trade(trade)]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for trade in weather_trades:
            key = self._market_key(trade)
            if key:
                grouped[key].append(trade)

        city_counter: Counter[str] = Counter()
        bucket_counter: Counter[str] = Counter()
        side_counter: Counter[str] = Counter()
        price_band_counter: Counter[str] = Counter()
        fills_per_market: list[int] = []
        usdc_per_market: list[float] = []
        tokens_per_market: list[float] = []
        top_scaled_markets: list[dict[str, Any]] = []

        for market_key, market_trades in grouped.items():
            fills_per_market.append(len(market_trades))
            total_usdc = sum(self._extract_usdc_size(trade) for trade in market_trades)
            total_tokens = sum(self._extract_token_size(trade) for trade in market_trades)
            usdc_per_market.append(total_usdc)
            tokens_per_market.append(total_tokens)

            city = self._extract_city(market_trades[0])
            bucket = self._extract_bucket_label(market_trades[0])
            if city:
                city_counter[city] += 1
            if bucket:
                bucket_counter[bucket] += 1

            side_totals: Counter[str] = Counter()
            price_band_totals: Counter[str] = Counter()
            for trade in market_trades:
                side_totals[self._extract_side(trade)] += self._extract_usdc_size(trade)
                price_band_totals[self._price_band(self._extract_price(trade))] += self._extract_usdc_size(trade)

            dominant_side = side_totals.most_common(1)[0][0] if side_totals else "UNKNOWN"
            dominant_band = price_band_totals.most_common(1)[0][0] if price_band_totals else "unknown"
            side_counter[dominant_side] += 1
            price_band_counter[dominant_band] += 1

            top_scaled_markets.append(
                {
                    "market": market_key,
                    "title": self._extract_question(market_trades[0]),
                    "city": city,
                    "bucket": bucket,
                    "fills": len(market_trades),
                    "total_usdc": round(total_usdc, 2),
                    "total_tokens": round(total_tokens, 2),
                    "dominant_side": dominant_side,
                    "dominant_price_band": dominant_band,
                    "avg_price": round(mean(self._extract_price(trade) for trade in market_trades), 4),
                }
            )

        top_scaled_markets.sort(key=lambda item: (item["fills"], item["total_usdc"]), reverse=True)
        heuristics = self._build_heuristic_summary(grouped, city_counter, bucket_counter, side_counter, price_band_counter)

        return MarketPatternReport(
            wallet=wallet,
            generated_at=now_iso(),
            weather_fill_count=len(weather_trades),
            consolidated_weather_markets=len(grouped),
            avg_fills_per_market=mean(fills_per_market) if fills_per_market else 0.0,
            avg_market_usdc=mean(usdc_per_market) if usdc_per_market else 0.0,
            avg_market_tokens=mean(tokens_per_market) if tokens_per_market else 0.0,
            dominant_side_by_market=dict(side_counter.most_common()),
            dominant_price_band_by_market=dict(price_band_counter.most_common()),
            top_cities_by_markets=[{"city": city, "markets": count} for city, count in city_counter.most_common(20)],
            top_buckets_by_markets=[{"bucket": bucket, "markets": count} for bucket, count in bucket_counter.most_common(20)],
            top_scaled_markets=top_scaled_markets[:25],
            heuristic_summary=heuristics,
            notes=[
                "Este relatório consolida fills por mercado único para reduzir a ilusão de independência estatística.",
                "Dominância por side e price band foi calculada por capital agregado no mercado, não só contagem bruta de fills.",
            ],
        )

    def _build_heuristic_summary(
        self,
        grouped: dict[str, list[dict[str, Any]]],
        city_counter: Counter[str],
        bucket_counter: Counter[str],
        side_counter: Counter[str],
        price_band_counter: Counter[str],
    ) -> list[str]:
        heuristics: list[str] = []
        if grouped:
            avg_fills = mean(len(trades) for trades in grouped.values())
            heuristics.append(f"Média de {avg_fills:.2f} fills por mercado weather, sinal de execução frequentemente parcelada.")
        if side_counter:
            top_side, top_side_count = side_counter.most_common(1)[0]
            heuristics.append(f"O lado dominante por mercado foi {top_side}, em {top_side_count} mercados consolidados.")
        if price_band_counter:
            band, count = price_band_counter.most_common(1)[0]
            heuristics.append(f"A faixa de preço dominante por mercado foi {band}, em {count} mercados consolidados.")
        if city_counter:
            city, count = city_counter.most_common(1)[0]
            heuristics.append(f"A cidade mais recorrente por mercado foi {city}, com {count} mercados únicos.")
        if bucket_counter:
            bucket, count = bucket_counter.most_common(1)[0]
            heuristics.append(f"O bucket mais recorrente por mercado foi {bucket}, com {count} mercados únicos.")
        heuristics.append("Para o bot, isso favorece score por mercado consolidado, execução escalonada e priorização por cidade/bucket recorrentes.")
        return heuristics

    def _persist_report(
        self,
        report: WalletAuditReport,
        market_patterns: MarketPatternReport,
        trades: list[dict[str, Any]],
        positions: list[dict[str, Any]],
    ) -> None:
        slug = report.wallet.lower()
        payload = {
            "report": asdict(report),
            "market_patterns": asdict(market_patterns),
            "sample_weather_trades": trades[:50],
            "positions_snapshot": positions[:100],
        }
        latest_path = self.runtime_dir / f"{slug}_latest.json"
        stamped_path = self.runtime_dir / f"{slug}_{report.generated_at.replace(':', '-')}" \
            ".json"
        for path in [latest_path, stamped_path]:
            with path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

    def _market_key(self, trade: dict[str, Any]) -> str:
        return str(
            trade.get("market")
            or trade.get("market_slug")
            or trade.get("slug")
            or trade.get("question")
            or ""
        ).strip()

    def _is_weather_trade(self, trade: dict[str, Any]) -> bool:
        text = " ".join(
            str(trade.get(field) or "")
            for field in ["question", "market_slug", "slug", "title", "event_title"]
        ).lower()
        return "highest temperature" in text

    def _extract_question(self, trade: dict[str, Any]) -> str:
        return str(
            trade.get("question")
            or trade.get("title")
            or trade.get("market_question")
            or trade.get("event_title")
            or ""
        ).strip()

    def _extract_city(self, trade: dict[str, Any]) -> str | None:
        question = self._extract_question(trade)
        match = WEATHER_TITLE_RE.search(question)
        if match:
            return match.group("city").strip()
        return None

    def _extract_bucket_label(self, trade: dict[str, Any]) -> str | None:
        question = self._extract_question(trade)
        match = WEATHER_TITLE_RE.search(question)
        if match:
            return match.group("bucket").strip()
        outcome = trade.get("outcome") or trade.get("side")
        if outcome:
            return str(outcome)
        return None

    def _extract_side(self, trade: dict[str, Any]) -> str:
        for key in ["outcome", "side", "position", "maker_side"]:
            value = str(trade.get(key) or "").strip().upper()
            if value in {"YES", "NO", "BUY", "SELL"}:
                return "YES" if value in {"YES", "BUY"} and str(trade.get("outcome") or "").strip().lower() == "yes" else (
                    "NO" if value in {"NO"} or (value == "BUY" and str(trade.get("outcome") or "").strip().lower() == "no") else value
                )
        return "UNKNOWN"

    def _extract_price(self, trade: dict[str, Any]) -> float:
        for key in ["price", "price_paid", "avg_price", "trade_price"]:
            value = trade.get(key)
            try:
                if value is not None:
                    return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0

    def _extract_usdc_size(self, trade: dict[str, Any]) -> float:
        for key in ["amount", "total_usdc", "value", "volume", "usdc_size"]:
            value = trade.get(key)
            try:
                if value is not None:
                    return abs(float(value))
            except (TypeError, ValueError):
                continue
        price = self._extract_price(trade)
        tokens = self._extract_token_size(trade)
        return abs(price * tokens)

    def _extract_token_size(self, trade: dict[str, Any]) -> float:
        for key in ["size", "token_size", "shares", "quantity", "asset_amount"]:
            value = trade.get(key)
            try:
                if value is not None:
                    return abs(float(value))
            except (TypeError, ValueError):
                continue
        usdc_size = 0.0
        for key in ["amount", "total_usdc", "value", "volume", "usdc_size"]:
            value = trade.get(key)
            try:
                if value is not None:
                    usdc_size = abs(float(value))
                    break
            except (TypeError, ValueError):
                continue
        price = self._extract_price(trade)
        if price > 0 and usdc_size > 0:
            return usdc_size / price
        return 0.0

    def _price_band(self, price: float) -> str:
        if price <= 0:
            return "unknown"
        lower = 0.0
        for upper in PRICE_BANDS:
            if price < upper:
                return f"{lower:.3f}-{upper:.3f}"
            lower = upper
        return ">=1.000"

    def _classify_positions_open_closed(self, positions: list[dict[str, Any]]) -> dict[str, int]:
        open_count = 0
        closed_count = 0
        for position in positions:
            size = 0.0
            for key in ["size", "amount", "currentValue", "cashPnl"]:
                value = position.get(key)
                try:
                    if value is not None:
                        size = float(value)
                        break
                except (TypeError, ValueError):
                    continue
            if abs(size) > 0:
                open_count += 1
            else:
                closed_count += 1
        return {
            "open": open_count,
            "closed_or_zeroed_snapshot": closed_count,
        }


def run_coldmath_audit(wallet: str = "0x594edb9112f526fa6a80b8f858a6379c8a2c1c11") -> WalletAuditReport:
    config = load_config()
    intelligence = WalletIntelligence(config)
    return intelligence.analyze_wallet(wallet=wallet, target_count=2000)


if __name__ == "__main__":
    config = load_config()
    intelligence = WalletIntelligence(config)
    report = intelligence.analyze_wallet("0x594edb9112f526fa6a80b8f858a6379c8a2c1c11", target_count=2000)
    market_patterns = intelligence.analyze_market_patterns("0x594edb9112f526fa6a80b8f858a6379c8a2c1c11", target_count=2000)
    print(json.dumps({"report": asdict(report), "market_patterns": asdict(market_patterns)}, ensure_ascii=False, indent=2))
