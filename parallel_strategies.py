from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from config import load_config
from models.strategy import StrategySpec
from utils.time_utils import now_iso


def build_default_strategies() -> list[StrategySpec]:
    return [
        StrategySpec(
            strategy_id="NO_EXTREME",
            side_mode="NO",
            min_price=0.90,
            max_price=0.94,
            preferred_low=0.90,
            preferred_high=0.92,
            max_entries_per_market=2,
            score_bias=8,
            notes="Inspirada em wallets NO high-confidence. Faixa ajustada em 2026-04-14 para casar com o que o mercado oferece (NO 0.90-0.94). Diferenciação: só mercados com resolução >48h e distância do limiar ≥2.5°C.",
            min_hours_to_resolution=48.0,
            max_hours_to_resolution=99999.0,
            required_min_distance_threshold=2.5,
            exclusive_cities=("London", "Paris", "New York", "Chicago", "Los Angeles", "Toronto", "Berlin", "Amsterdam"),
        ),
        StrategySpec(
            strategy_id="YES_CONVEX",
            side_mode="YES",
            min_price=0.06,
            max_price=0.50,
            preferred_low=0.06,
            preferred_high=0.25,
            max_entries_per_market=4,
            score_bias=5,
            notes="Inspirada em wallets YES convexas. Faixa ajustada em 2026-04-14 para casar com o que o mercado oferece (YES 0.06-0.50). Diferenciação: só mercados com resolução <24h e distância do limiar <2.0°C.",
            min_hours_to_resolution=6.0,
            max_hours_to_resolution=24.0,
            required_min_distance_threshold=0.0,
            exclusive_cities=("Miami", "Houston", "Phoenix", "Dallas", "Tampa", "Orlando", "Las Vegas", "San Antonio"),
        ),
        StrategySpec(
            strategy_id="MID_RANGE_BALANCED",
            side_mode="BOTH",
            min_price=0.45,
            max_price=0.80,
            preferred_low=0.55,
            preferred_high=0.70,
            max_entries_per_market=3,
            score_bias=2,
            notes="Inspirada em wallets mid-range. Faixa ajustada em 2026-04-14 para casar com o que o mercado oferece (0.45-0.80). Diferenciação: resolução entre 24-72h, qualquer cidade que não seja das outras duas listas.",
            min_hours_to_resolution=24.0,
            max_hours_to_resolution=72.0,
            required_min_distance_threshold=0.0,
            exclusive_cities=("Sao Paulo", "Buenos Aires", "Mexico City", "Bogota", "Lima", "Santiago", "Guadalajara", "Cairo", "Johannesburg", "Dubai", "Mumbai", "Bangkok"),
        ),
    ]


class ParallelStrategyRegistry:
    def __init__(self) -> None:
        self.config = load_config()
        self.path = self.config.storage.state_dir / "parallel_strategies.json"

    def save_default_registry(self) -> dict:
        strategies = build_default_strategies()
        payload = {
            "generated_at": now_iso(),
            "strategies": [asdict(item) for item in strategies],
            "comparison_notes": [
                "Cada estratégia deve operar com bankroll virtual próprio.",
                "Comparação final deve considerar PnL, drawdown, win rate, volume executado e robustez operacional.",
                "Critério sugerido: pelo menos 200 decisões elegíveis por estratégia antes de declarar vencedora.",
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return payload


if __name__ == "__main__":
    registry = ParallelStrategyRegistry()
    print(json.dumps(registry.save_default_registry(), ensure_ascii=False, indent=2))
