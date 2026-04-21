from dataclasses import dataclass


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    side_mode: str
    min_price: float
    max_price: float
    preferred_low: float
    preferred_high: float
    max_entries_per_market: int
    score_bias: int = 0
    notes: str = ""
    # Diferenciação por horizonte temporal (horas até resolução)
    min_hours_to_resolution: float = 0.0
    max_hours_to_resolution: float = 99999.0
    # Diferenciação por distância do limiar (°C)
    required_min_distance_threshold: float = 0.0
    # Score mínimo real para aprovar entrada
    min_score: int = 0
    high_price_min_score: int = 0
    high_price_threshold: float = 1.0
    # Cidades exclusivas por estratégia (vazio = todas permitidas)
    exclusive_cities: tuple = tuple()
