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
            max_price=0.97,
            preferred_low=0.90,
            preferred_high=0.92,
            max_entries_per_market=2,
            score_bias=8,
            notes="Inspirada em wallets NO high-confidence. Teste de calibração em 2026-04-18: faixa ampliada para NO 0.90-0.97 e cidades liberadas, mantendo viés de resolução longa e distância do limiar ≥2.5°C.",
            min_hours_to_resolution=48.0,
            max_hours_to_resolution=99999.0,
            required_min_distance_threshold=2.5,
            exclusive_cities=(),
        ),
        StrategySpec(
            strategy_id="YES_CONVEX",
            side_mode="YES",
            min_price=0.04,
            max_price=0.60,
            preferred_low=0.06,
            preferred_high=0.25,
            max_entries_per_market=4,
            score_bias=5,
            notes="Inspirada em wallets YES convexas. Teste de calibração em 2026-04-18: faixa ampliada para YES 0.04-0.60, janela 4h-30h e cidades liberadas, mantendo perfil de resolução curta.",
            min_hours_to_resolution=4.0,
            max_hours_to_resolution=30.0,
            required_min_distance_threshold=0.0,
            exclusive_cities=(),
        ),
        StrategySpec(
            strategy_id="MID_RANGE_BALANCED",
            side_mode="BOTH",
            min_price=0.30,
            max_price=0.90,
            preferred_low=0.55,
            preferred_high=0.70,
            max_entries_per_market=10,
            score_bias=2,
            notes="Ajustada em 2026-04-19: faixa ampliada para 0.30-0.90, até 10 entradas por mercado, janela mínima reduzida para 4h e cidades liberadas globalmente. Mantidos preferred band e score bias porque ainda afetam seleção e score no motor atual.",
            min_hours_to_resolution=4.0,
            max_hours_to_resolution=72.0,
            required_min_distance_threshold=0.0,
            exclusive_cities=(),
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
