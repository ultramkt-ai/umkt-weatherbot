from models.market import TemperatureMarket
from models.state import BotState


def build_cluster_id(market: TemperatureMarket) -> str:
    event_date = market.event_start_time.split("T")[0]
    region = market.city or market.region_label or "unknown"
    return f"highest_temperature:{region}:{event_date}"


def cluster_trade_count(state: BotState, cluster_id: str) -> int:
    return state.cluster_trade_count_map.get(cluster_id, 0)


def cluster_exposure_usd(state: BotState, cluster_id: str) -> float:
    return state.cluster_exposure_map_usd.get(cluster_id, 0.0)
