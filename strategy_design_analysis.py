from __future__ import annotations

from dataclasses import asdict
import json

from config import load_config
from wallet_intelligence import WalletIntelligence

WALLETS = [
    "0x594edb9112f526fa6a80b8f858a6379c8a2c1c11",
    "0x15ceffed7bf820cd2d90f90ea24ae9909f5cd5fa",
    "0x1f66796b45581868376365aef54b51eb84184c8d",
    "0x331bf91c132af9d921e1908ca0979363fc47193f",
    "0xb40e89677d59665d5188541ad860450a6e2a7cc9",
]


def main() -> None:
    config = load_config()
    intel = WalletIntelligence(config)
    payload = []
    for wallet in WALLETS:
        report = intel.analyze_wallet(wallet, target_count=2000)
        patterns = intel.analyze_market_patterns(wallet, target_count=2000)
        payload.append({
            "wallet": wallet,
            "report": asdict(report),
            "patterns": asdict(patterns),
        })
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
