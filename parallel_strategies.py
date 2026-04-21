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
            min_price=0.84,
            max_price=0.90,
            preferred_low=0.85,
            preferred_high=0.88,
            max_entries_per_market=10,
            score_bias=5,
            notes="Cenário A aplicado em 2026-04-21: NO premium mais seletivo sem matar totalmente o volume. Faixa 0.84-0.90, banda preferida 0.85-0.88, no máximo 2 entradas por mercado, janela 8h-24h e distância mínima de 2.0°C, além de filtro microestrutural para evitar livro praticamente morto.",
            min_hours_to_resolution=8.0,
            max_hours_to_resolution=24.0,
            required_min_distance_threshold=2.0,
            min_score=50,
            high_price_min_score=55,
            high_price_threshold=0.88,
            exclusive_cities=(),
        ),
        StrategySpec(
            strategy_id="YES_CONVEX",
            side_mode="YES",
            min_price=0.04,
            max_price=0.35,
            preferred_low=0.06,
            preferred_high=0.18,
            max_entries_per_market=10,
            score_bias=5,
            notes="Recalibrada em 2026-04-21: YES exato só entra barato e com microestrutura minimamente negociável. Faixa 0.04-0.35, banda preferida 0.06-0.18, no máximo 2 entradas por mercado, janela 4h-24h e distância mínima do forecast de 1.0°C para evitar pagar caro em livro morto.",
            min_hours_to_resolution=4.0,
            max_hours_to_resolution=24.0,
            required_min_distance_threshold=1.0,
            min_score=38,
            high_price_min_score=44,
            high_price_threshold=0.20,
            exclusive_cities=(),
        ),
        StrategySpec(
            strategy_id="MID_RANGE_BALANCED",
            side_mode="BOTH",
            min_price=0.30,
            max_price=0.82,
            preferred_low=0.42,
            preferred_high=0.68,
            max_entries_per_market=10,
            score_bias=0,
            notes="Reescrita em 2026-04-21: escolha de lado orientada por edge e executabilidade real do token. Faixa 0.30-0.82, banda preferida 0.42-0.68, no máximo 1 entrada por mercado, janela 4h-36h, sem aceitar lados opostos no mesmo mercado, com score mínimo real e filtro token-specific de book.",
            min_hours_to_resolution=4.0,
            max_hours_to_resolution=36.0,
            required_min_distance_threshold=0.0,
            min_score=40,
            high_price_min_score=48,
            high_price_threshold=0.70,
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
