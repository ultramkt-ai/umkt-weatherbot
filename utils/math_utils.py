def safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def calculate_open_exposure_pct(open_exposure_usd: float, bankroll_usd: float) -> float:
    return safe_div(open_exposure_usd, bankroll_usd)


def calculate_drawdown_pct(current_equity: float, equity_peak: float) -> float:
    if equity_peak <= 0:
        return 0.0
    return max(0.0, (equity_peak - current_equity) / equity_peak)
