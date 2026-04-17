from __future__ import annotations

from dataclasses import asdict
import json

from config import load_config
from copytrading import CopytradingMonitor
from utils.time_utils import now_iso

DEFAULT_WALLET = '0x594edb9112f526fa6a80b8f858a6379c8a2c1c11'


def run_copytrading_experiment(wallet: str = DEFAULT_WALLET) -> dict:
    config = load_config()
    monitor = CopytradingMonitor(config)
    snapshot = monitor.poll_wallet(wallet)
    report = {
        'generated_at': now_iso(),
        'wallet': wallet,
        'new_trades_count': snapshot.get('new_trades_count', 0),
        'cursor_trade_ids': snapshot.get('cursor_trade_ids', []),
        'sample_new_trades': snapshot.get('new_trades', [])[:20],
    }
    path = config.storage.reports_dir / 'copytrading_latest.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    print(json.dumps(run_copytrading_experiment(), ensure_ascii=False, indent=2))
