from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
import json

from config import load_config
from copytrading import CopytradingMonitor
from models.trade import ClosedTrade, OpenTrade
from models.state import BotState
from models.serialization import dataclass_to_dict
from storage.ledger_db import COPYTRADING_STRATEGY_ID, build_strategy_snapshot, list_closed_trades, list_open_positions, migrate_legacy_trade_data, record_closed_trade, record_open_trade
from utils.ids import generate_session_id
from utils.time_utils import now_iso

DEFAULT_WALLET = '0x594edb9112f526fa6a80b8f858a6379c8a2c1c11'


def _state_path(config):
    return config.storage.state_dir / 'copytrading_competitor_state.json'


def _build_default_state(config) -> dict:
    now = now_iso()
    initial = config.risk.initial_bankroll_usd
    return {
        'wallet': DEFAULT_WALLET,
        'bankroll_usd': initial,
        'trades_copied': 0,
        'last_run_at': None,
        'bot_state': dataclass_to_dict(BotState(
            session_id=f'copytrading:{generate_session_id()}',
            started_at=now,
            updated_at=now,
            last_cycle_started_at=None,
            last_cycle_finished_at=None,
            initial_bankroll_usd=initial,
            current_cash_usd=initial,
            current_bankroll_usd=initial,
            realized_pnl_total_usd=0.0,
            fees_paid_total_usd=0.0,
            equity_peak_usd=initial,
            current_drawdown_pct=0.0,
            max_drawdown_pct=0.0,
            capital_alocado_aberto_usd=0.0,
            gross_exposure_open_usd=0.0,
            open_exposure_pct=0.0,
            open_trades_count=0,
            closed_trades_count=0,
            approved_trades_count=0,
            rejected_markets_count=0,
            markets_scanned_today=0,
            approved_today=0,
            rejected_today=0,
            consecutive_losses=0,
            consecutive_wins=0,
        )),
        'closed_positions': [],
    }


def _load_state(config):
    migrate_legacy_trade_data(config)
    path = _state_path(config)
    base = _build_default_state(config)
    if path.exists():
        loaded = json.loads(path.read_text(encoding='utf-8'))
        base.update(loaded)
    snapshot = build_strategy_snapshot(config, COPYTRADING_STRATEGY_ID, config.risk.initial_bankroll_usd)
    bot_state = base['bot_state']
    bot_state['open_trades'] = snapshot['open_trades']
    bot_state['open_trades_count'] = snapshot['open_trades_count']
    bot_state['closed_trades_count'] = snapshot['closed_trades_count']
    bot_state['approved_trades_count'] = snapshot['approved_trades_count']
    bot_state['approved_today'] = snapshot['approved_today']
    bot_state['capital_alocado_aberto_usd'] = snapshot['capital_alocado_aberto_usd']
    bot_state['gross_exposure_open_usd'] = snapshot['gross_exposure_open_usd']
    bot_state['realized_pnl_total_usd'] = snapshot['realized_pnl_total_usd']
    bot_state['current_cash_usd'] = snapshot['current_cash_usd']
    bot_state['current_bankroll_usd'] = snapshot['current_bankroll_usd']
    bot_state['open_exposure_pct'] = snapshot['open_exposure_pct']
    bot_state['cluster_exposure_map_usd'] = snapshot['cluster_exposure_map_usd']
    bot_state['cluster_trade_count_map'] = snapshot['cluster_trade_count_map']
    state = base
    state['closed_positions'] = list_closed_trades(config, COPYTRADING_STRATEGY_ID)
    state['bankroll_usd'] = snapshot['current_bankroll_usd']
    return state


def _save_state(config, state):
    _state_path(config).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def _trade_key(trade: dict) -> str:
    return str(trade.get('id') or trade.get('transactionHash') or trade.get('timestamp') or '')


def _map_side(trade: dict) -> str:
    return 'MIRROR'


def _fill_notional_usd(trade: dict) -> float:
    size = float(trade.get('size') or 0.0)
    price = float(trade.get('price') or 0.0)
    return max(0.0, size * price)


def _local_fill_budget_usd(config, trade: dict) -> float:
    origin_notional = _fill_notional_usd(trade)
    local_cap_usd = max(0.0, config.runtime.copytrading_max_fill_brl / max(config.runtime.usd_brl_rate, 0.0001))
    return min(origin_notional, local_cap_usd)


def _open_copy_position(config, trade: dict) -> OpenTrade:
    entry_price = float(trade.get('price') or 0.0)
    origin_contracts = float(trade.get('size') or 0.0)
    origin_notional = _fill_notional_usd(trade)
    capital = _local_fill_budget_usd(config, trade)
    contracts = (capital / entry_price) if entry_price > 0 else 0.0
    risk_pct = 0.0
    return OpenTrade(
        trade_id=f"copy-{_trade_key(trade)}",
        market_id=str(trade.get('conditionId') or trade.get('market') or trade.get('slug') or ''),
        parent_slug=str(trade.get('slug') or trade.get('eventSlug') or ''),
        outcome_label=str(trade.get('outcome') or trade.get('title') or trade.get('slug') or ''),
        bucket_type='copytrading',
        bucket_low=None,
        bucket_high=None,
        token_id=str(trade.get('asset') or ''),
        entry_time=now_iso(),
        side=_map_side(trade),
        entry_price=entry_price,
        capital_alocado_usd=capital,
        contracts_qty=contracts,
        gross_cost_usd=capital,
        fees_paid_usd=0.0,
        net_cost_usd=capital,
        max_loss_usd=capital,
        max_profit_usd=max(0.0, contracts - capital),
        risk_pct_of_bankroll=risk_pct,
        score=50,
        score_band='COPY',
        weather_type='copytrading',
        city=None,
        state=None,
        cluster_id=str(trade.get('eventSlug') or trade.get('slug') or 'copytrading'),
        approval_summary='Posição espelhada da carteira alvo por fill proporcional',
        market_snapshot_at_entry={
            **trade,
            'origin_contracts_qty': origin_contracts,
            'origin_notional_usd': origin_notional,
            'local_notional_usd': capital,
            'copy_ratio': (capital / origin_notional) if origin_notional > 0 else 0.0,
            'copy_mode': 'fill_proportional_capped_brl',
            'local_cap_brl': config.runtime.copytrading_max_fill_brl,
        },
        weather_snapshot_at_entry={},
        status='OPEN',
    )


def _maybe_close_positions(state: dict) -> None:
    now_dt = datetime.fromisoformat(now_iso())
    bot_state = state['bot_state']
    open_positions = bot_state.get('open_trades', [])
    still_open = []
    for pos in open_positions:
        entry_dt = datetime.fromisoformat(pos['entry_time'])
        # Manter posição aberta por pelo menos 10 minutos (evita flip-flop)
        if now_dt - entry_dt < timedelta(minutes=10):
            still_open.append(pos)
            continue
        
        # TODO: Implementar lógica de saída baseada em preço de mercado
        # Por enquanto, mantém todas as posições abertas
        # Isso evita fechamentos prematuros sem sinal claro de saída
        still_open.append(pos)
        continue
        
        # Código de fechamento por resolução (comentado até ter sinal de saída confiável)
        # resolution_value = pos['entry_price']
        # gross_settlement = pos['contracts_qty'] * resolution_value
        # net_pnl = gross_settlement - pos['net_cost_usd']
        # closed = asdict(ClosedTrade(...))
        # state['closed_positions'].append(closed)
        # record_closed_trade(config, COPYTRADING_STRATEGY_ID, closed)
        # bot_state['current_cash_usd'] += gross_settlement
        # bot_state['capital_alocado_aberto_usd'] -= pos['capital_alocado_usd']
        # bot_state['realized_pnl_total_usd'] += net_pnl
        # bot_state['closed_trades_count'] += 1
        
    bot_state['open_trades'] = still_open
    bot_state['open_trades_count'] = len(still_open)
    bot_state['current_bankroll_usd'] = bot_state['current_cash_usd'] + bot_state['capital_alocado_aberto_usd']
    state['bankroll_usd'] = bot_state['current_bankroll_usd']


def run_copytrading_competitor(wallet: str = DEFAULT_WALLET) -> dict:
    config = load_config()
    monitor = CopytradingMonitor(config)
    snapshot = monitor.poll_wallet(wallet)
    state = _load_state(config)
    bot_state = state['bot_state']

    _maybe_close_positions(state)

    seen_open_ids = {pos['trade_id'] for pos in bot_state.get('open_trades', [])}
    new_trades = snapshot.get('new_trades', [])
    copied_now = 0
    for trade in new_trades:
        trade_id = f"copy-{_trade_key(trade)}"
        if trade_id in seen_open_ids:
            continue
        pos = _open_copy_position(config, trade)
        bot_state.setdefault('open_trades', []).append(asdict(pos))
        record_open_trade(config, COPYTRADING_STRATEGY_ID, asdict(pos))
        bot_state['open_trades_count'] = len(bot_state['open_trades'])
        bot_state['approved_trades_count'] += 1
        bot_state['approved_today'] += 1
        bot_state['current_cash_usd'] -= pos.net_cost_usd
        bot_state['capital_alocado_aberto_usd'] += pos.capital_alocado_usd
        bot_state['current_bankroll_usd'] = bot_state['current_cash_usd'] + bot_state['capital_alocado_aberto_usd']
        state['trades_copied'] += 1
        copied_now += 1
        seen_open_ids.add(trade_id)

    state['wallet'] = wallet
    state['last_run_at'] = now_iso()
    bot_state['updated_at'] = now_iso()
    state['bankroll_usd'] = bot_state['current_bankroll_usd']
    _save_state(config, state)

    report = {
        'generated_at': now_iso(),
        'wallet': wallet,
        'new_trades_count': snapshot.get('new_trades_count', 0),
        'trades_copied_now': copied_now,
        'trades_copied_total': state['trades_copied'],
        'bankroll_usd': bot_state['current_bankroll_usd'],
        'cash_usd': bot_state['current_cash_usd'],
        'capital_open_usd': bot_state['capital_alocado_aberto_usd'],
        'realized_pnl_usd': bot_state['realized_pnl_total_usd'],
        'open_positions_count': bot_state['open_trades_count'],
        'closed_positions_count': bot_state['closed_trades_count'],
        'sample_new_trades': new_trades[:20],
        'sample_open_positions': list_open_positions(config, COPYTRADING_STRATEGY_ID)[:10],
        'sample_closed_positions': list_closed_trades(config, COPYTRADING_STRATEGY_ID, limit=10),
    }
    report_path = config.storage.reports_dir / 'copytrading_latest.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    from strategy_comparison import build_comparison_snapshot
    build_comparison_snapshot()
    return report


if __name__ == '__main__':
    print(json.dumps(run_copytrading_competitor(), ensure_ascii=False, indent=2))
