#!/usr/bin/env python3
"""Testa se o estado do copytrading está sendo lido corretamente pelo dashboard."""

from pathlib import Path
import json
from datetime import datetime, timedelta

STATE_FILE = Path("/home/rafael/.openclaw/workspace/weather_bot/data_runtime/state/copytrading_competitor_state.json")

def check_status():
    if not STATE_FILE.exists():
        print("❌ Arquivo de estado não encontrado")
        return
    
    with open(STATE_FILE) as f:
        state = json.load(f)
    
    bot_state = state.get('bot_state', {})
    last_cycle = bot_state.get('last_cycle_finished_at')
    
    print(f"📊 Estado do Copytrading:")
    print(f"   Wallet: {state.get('wallet', 'N/A')}")
    print(f"   Bankroll: ${state.get('bankroll_usd', 0):.2f}")
    print(f"   Trades copied: {state.get('trades_copied', 0)}")
    print(f"   Open trades: {bot_state.get('open_trades_count', 0)}")
    print(f"   Last cycle: {last_cycle}")
    
    if last_cycle:
        try:
            dt = datetime.fromisoformat(last_cycle)
            age = datetime.now() - dt
            print(f"   Age: {age.total_seconds():.0f}s")
            
            if age < timedelta(minutes=5):
                print("   ✅ Status: ATIVO (cycle recente)")
            elif age < timedelta(hours=2):
                print("   ⚠️  Status: ATIVO (cycle antigo)")
            else:
                print("   ❌ Status: PARADO (cycle >2h)")
        except Exception as e:
            print(f"   ❌ Erro ao parsear data: {e}")
    else:
        print("   ❌ Status: PARADO (sem last_cycle)")

if __name__ == "__main__":
    check_status()
