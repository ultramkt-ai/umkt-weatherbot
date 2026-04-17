#!/usr/bin/env python3
"""
run_copytrading_loop.py — Loop contínuo de copytrading.

Roda o copytrading competitor em loop, atualizando estado e relatórios
para o dashboard weather_bot.

Uso:
    python3 run_copytrading_loop.py
    
Ou como serviço systemd (recomendado).
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from copytrading_competitor import DEFAULT_WALLET, run_copytrading_competitor, _load_state, _save_state, _build_default_state
from config import load_config


# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# Intervalo entre ciclos de copytrading (segundos)
COPYTRADING_INTERVAL_SECONDS = int(
    Path(__file__).parent.joinpath(".copytrading_interval").read_text().strip()
    if Path(__file__).parent.joinpath(".copytrading_interval").exists()
    else "60"  # default: 60 segundos
)


# ─── Main Loop ───────────────────────────────────────────────────────────────

def run_loop() -> None:
    """Loop infinito de copytrading."""
    config = load_config()
    
    logger.info("Iniciando copytrading loop (wallet=%s, interval=%ds)", DEFAULT_WALLET, COPYTRADING_INTERVAL_SECONDS)
    
    # Carregar ou criar estado inicial
    state = _load_state(config)
    state['bot_state']['updated_at'] = datetime.now().isoformat()
    state['bot_state']['last_cycle_finished_at'] = datetime.now().isoformat()
    _save_state(config, state)
    
    logger.info("Estado inicial carregado: bankroll=$%.2f, trades_copied=%d", 
                state.get('bankroll_usd', 0), state.get('trades_copied', 0))
    
    cycle_count = 0
    
    while True:
        try:
            cycle_start = datetime.now()
            cycle_count += 1
            
            logger.info("=== COPYTRADING CYCLE %d ===", cycle_count)
            
            # Atualizar estado antes do ciclo
            state['bot_state']['last_cycle_started_at'] = cycle_start.isoformat()
            state['bot_state']['updated_at'] = cycle_start.isoformat()
            _save_state(config, state)
            
            # Executar copytrading
            report = run_copytrading_competitor(DEFAULT_WALLET)
            
            # Atualizar estado após ciclo
            cycle_end = datetime.now()
            state['bot_state']['last_cycle_finished_at'] = cycle_end.isoformat()
            state['bot_state']['updated_at'] = cycle_end.isoformat()
            state['last_run_at'] = cycle_end.isoformat()
            
            # Atualizar métricas do report
            if report:
                state['bankroll_usd'] = report.get('bankroll_usd', state.get('bankroll_usd', 0))
                state['trades_copied'] = report.get('trades_copied_total', state.get('trades_copied', 0))
                state['trades_copied_total'] = report.get('trades_copied_total', 0)
                state['open_positions_count'] = report.get('open_positions_count', 0)
                state['capital_open_usd'] = report.get('capital_open_usd', 0)
                state['cash_usd'] = report.get('cash_usd', 0)
                state['realized_pnl_usd'] = report.get('realized_pnl_usd', 0)
                
            _save_state(config, state)
            
            logger.info("Cycle %d completed in %.2fs | bankroll=$%.2f | trades_copied=%d | open=%d",
                       cycle_count, (cycle_end - cycle_start).total_seconds(),
                       state.get('bankroll_usd', 0), 
                       state.get('trades_copied', 0),
                       state.get('open_positions_count', 0))
            
        except Exception as e:
            logger.exception("Erro no ciclo de copytrading: %s", e)
            state['bot_state']['last_error'] = str(e)
            state['bot_state']['last_error_at'] = datetime.now().isoformat()
            _save_state(config, state)
        
        # Sleep até próximo ciclo
        time.sleep(COPYTRADING_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        run_loop()
    except KeyboardInterrupt:
        logger.info("Shutdown solicitado pelo usuário")
        sys.exit(0)
