#!/usr/bin/env python3
"""
copytrading_cycle.py — Executa UM ciclo de copytrading.

Usado pelo cron do OpenClaw para rodar copytrading periodicamente.
Diferente do run_copytrading_loop.py, este script roda UMA vez e sai.

Uso:
    python3 copytrading_cycle.py
    
Ou via cron do OpenClaw.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

# Adicionar weather_bot ao path
WB_DIR = Path(__file__).parent
sys.path.insert(0, str(WB_DIR))

from copytrading_competitor import DEFAULT_WALLET, run_copytrading_competitor, _load_state, _save_state
from config import load_config
from storage.journal import log_runtime_event
from utils.process_lock import ProcessLock


# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("copytrading_cycle")


# ─── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    """Executa um ciclo de copytrading. Retorna 0 se sucesso, 1 se erro."""
    config = load_config()
    cycle_lock = ProcessLock(config.storage.state_dir / 'copytrading_cycle.lock')
    if not cycle_lock.acquire():
        logger.warning("Run skipped: another copytrading cycle is still active.")
        log_runtime_event(config, {
            'timestamp': datetime.now().isoformat(),
            'event': 'copytrading_cycle_skipped_due_to_lock',
            'message': 'Run skipped: another copytrading cycle is still active.',
        })
        return 0
    try:
        cycle_start = datetime.now()
        
        logger.info("=== COPYTRADING CYCLE ===")
        logger.info("Iniciando ciclo (wallet=%s)", DEFAULT_WALLET)
        log_runtime_event(config, {
            'timestamp': cycle_start.isoformat(),
            'event': 'copytrading_cycle_started',
            'wallet': DEFAULT_WALLET,
        })
        
        # Carregar estado atual
        state = _load_state(config)
        state['bot_state']['last_cycle_started_at'] = cycle_start.isoformat()
        state['bot_state']['updated_at'] = cycle_start.isoformat()
        _save_state(config, state)
        
        # Executar copytrading
        report = run_copytrading_competitor(DEFAULT_WALLET)

        # Recarregar estado após a execução para não sobrescrever alterações
        # persistidas durante o ciclo principal do copytrading.
        state = _load_state(config)

        # Atualizar estado após ciclo
        cycle_end = datetime.now()
        state['bot_state']['last_cycle_finished_at'] = cycle_end.isoformat()
        state['bot_state']['updated_at'] = cycle_end.isoformat()
        state['bot_state']['last_error'] = None
        state['bot_state']['last_error_at'] = None
        state['bot_state']['last_cycle_duration_seconds'] = round((cycle_end - cycle_start).total_seconds(), 3)
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
        
        # Gerar report para o dashboard
        from storage.ledger_db import COPYTRADING_STRATEGY_ID, build_strategy_snapshot
        import json
        
        initial_bankroll_usd = float(state.get('initial_bankroll_usd') or config.risk.initial_bankroll_usd)
        snapshot = build_strategy_snapshot(config, COPYTRADING_STRATEGY_ID, initial_bankroll_usd)
        
        dashboard_report = {
            'generated_at': cycle_end.isoformat(),
            'wallet': DEFAULT_WALLET,
            'bankroll_usd': snapshot.get('current_bankroll_usd', 0),
            'cash_usd': snapshot.get('current_cash_usd', 0),
            'capital_open_usd': snapshot.get('capital_alocado_aberto_usd', 0),
            'realized_pnl_usd': snapshot.get('realized_pnl_total_usd', 0),
            'open_positions_count': snapshot.get('open_trades_count', 0),
            'closed_positions_count': snapshot.get('closed_trades_count', 0),
            'trades_copied_total': state.get('trades_copied_total', 0),
            'sample_open_positions': snapshot.get('open_trades', [])[:10],
            'sample_closed_positions': snapshot.get('closed_trades', [])[:10],
        }
        
        # Salvar report para o dashboard
        reports_dir = config.storage.reports_dir
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / 'copytrading_latest.json'
        with open(report_path, 'w') as f:
            json.dump(dashboard_report, f, indent=2, default=str)
        
        logger.info("Report salvo em %s", report_path)
        
        duration = (cycle_end - cycle_start).total_seconds()
        logger.info(
            "Cycle completed in %.2fs | bankroll=$%.2f | trades_copied=%d | open=%d",
            duration,
            state.get('bankroll_usd', 0),
            state.get('trades_copied', 0),
            state.get('open_positions_count', 0)
        )
        log_runtime_event(config, {
            'timestamp': cycle_end.isoformat(),
            'event': 'copytrading_cycle_completed',
            'wallet': DEFAULT_WALLET,
            'duration_seconds': round(duration, 3),
            'bankroll_usd': state.get('bankroll_usd', 0),
            'trades_copied_total': state.get('trades_copied_total', 0),
            'open_positions_count': state.get('open_positions_count', 0),
        })
        
        return 0
        
    except Exception as e:
        logger.exception("Erro no ciclo de copytrading: %s", e)
        log_runtime_event(config, {
            'timestamp': datetime.now().isoformat(),
            'event': 'copytrading_cycle_runtime_exception',
            'wallet': DEFAULT_WALLET,
            'error_type': e.__class__.__name__,
            'message': str(e),
        })
        
        # Tentar salvar erro no estado
        try:
            config = load_config()
            state = _load_state(config)
            state['bot_state']['last_error'] = str(e)
            state['bot_state']['last_error_at'] = datetime.now().isoformat()
            _save_state(config, state)
        except Exception:
            pass

        return 1
    finally:
        cycle_lock.release()


if __name__ == "__main__":
    sys.exit(main())
