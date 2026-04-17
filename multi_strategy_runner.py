from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
import json

from config import load_config
from core.state_machine import refresh_bot_mode
from messaging.status_publisher import build_cycle_status_message
from parallel_strategies import build_default_strategies
from storage.state_store import load_or_create_state, save_state
from utils.time_utils import now_dt, now_iso


def build_multi_strategy_stub_report() -> dict:
    strategies = [asdict(item) for item in build_default_strategies()]
    return {
        "generated_at": now_iso(),
        "mode": "design_scaffold",
        "strategies": strategies,
        "notes": [
            "Runner inicial criado para preparar o estado comparativo das estratégias.",
            "Próximo passo é integrar cada estratégia ao pipeline com execução paralela real.",
            "O pipeline base atual segue preservado até a integração completa da camada multi-estratégia.",
        ],
    }


def main() -> None:
    config = load_config()
    state = load_or_create_state(config)
    state.last_cycle_started_at = now_iso()
    state = refresh_bot_mode(state)

    report = build_multi_strategy_stub_report()
    report_path = config.storage.reports_dir / "multi_strategy_latest.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    now = now_dt()
    state.next_market_scan_at = (now + timedelta(minutes=config.scheduling.market_scan_interval_min)).isoformat()
    state.next_open_trades_check_at = (now + timedelta(minutes=config.scheduling.open_trades_check_interval_min)).isoformat()
    state.last_cycle_status_message = build_cycle_status_message(state)
    state.last_cycle_finished_at = now_iso()
    save_state(config, state)

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
