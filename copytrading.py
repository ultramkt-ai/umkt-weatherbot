from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json

from config import Config, load_config
from data.polymarket_data_client import PolymarketDataClient
from storage.jsonl_store import append_jsonl
from utils.time_utils import now_iso


@dataclass
class CopytradingSnapshot:
    wallet: str
    captured_at: str
    new_trades_count: int
    cursor_trade_ids: list[str]


class CopytradingMonitor:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = PolymarketDataClient(config)
        self.state_path = config.storage.state_dir / "copytrading_state.json"
        self.log_path = config.storage.logs_dir / "copytrading_snapshots.jsonl"

    def load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"wallets": {}}
        with self.state_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def poll_wallet(self, wallet: str, limit: int = 100) -> dict[str, Any]:
        state = self.load_state()
        wallet_state = state.setdefault("wallets", {}).setdefault(wallet.lower(), {"seen_trade_ids": []})
        seen_trade_ids = set(wallet_state.get("seen_trade_ids", []))

        trades = self.client.list_trades(user=wallet, limit=limit, offset=0)
        new_trades = []
        for trade in trades:
            trade_id = str(trade.get("id") or trade.get("transaction_hash") or trade.get("timestamp") or "").strip()
            if not trade_id or trade_id in seen_trade_ids:
                continue
            new_trades.append(trade)

        current_ids = []
        for trade in trades[:500]:
            trade_id = str(trade.get("id") or trade.get("transaction_hash") or trade.get("timestamp") or "").strip()
            if trade_id:
                current_ids.append(trade_id)

        wallet_state["seen_trade_ids"] = current_ids
        wallet_state["last_polled_at"] = now_iso()
        wallet_state["last_new_trade_count"] = len(new_trades)
        self.save_state(state)

        snapshot = {
            "wallet": wallet,
            "captured_at": now_iso(),
            "new_trades_count": len(new_trades),
            "cursor_trade_ids": current_ids[:20],
            "new_trades": new_trades,
        }
        append_jsonl(self.log_path, snapshot)
        return snapshot


def poll_copytrading_wallet(wallet: str) -> dict[str, Any]:
    config = load_config()
    monitor = CopytradingMonitor(config)
    return monitor.poll_wallet(wallet)


if __name__ == "__main__":
    import sys

    wallet = sys.argv[1] if len(sys.argv) > 1 else "0x594edb9112f526fa6a80b8f858a6379c8a2c1c11"
    print(json.dumps(poll_copytrading_wallet(wallet), ensure_ascii=False, indent=2))
