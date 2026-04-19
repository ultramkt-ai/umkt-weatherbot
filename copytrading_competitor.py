from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
import json

from config import load_config
from copytrading import CopytradingMonitor
from data.polymarket_data_client import PolymarketDataClient
from models.trade import ClosedTrade, OpenTrade
from models.state import BotState
from models.serialization import dataclass_to_dict
from storage.ledger_db import COPYTRADING_STRATEGY_ID, build_strategy_snapshot, list_closed_trades, list_open_positions, list_open_trades, migrate_legacy_trade_data, record_closed_trade, record_open_trade
from utils.ids import generate_session_id
from utils.math_utils import calculate_drawdown_pct
from utils.time_utils import now_iso

DEFAULT_WALLET = '0x594edb9112f526fa6a80b8f858a6379c8a2c1c11'


def _state_path(config):
    return config.storage.state_dir / 'copytrading_competitor_state.json'


def _build_default_state(config) -> dict:
    now = now_iso()
    initial = config.risk.initial_bankroll_usd
    return {
        'wallet': DEFAULT_WALLET,
        'initial_bankroll_usd': initial,
        'copytrading_max_fill_brl': config.runtime.copytrading_max_fill_brl,
        'usd_brl_rate': config.runtime.usd_brl_rate,
        'bankroll_usd': initial,
        'trades_copied': 0,
        'last_run_at': None,
        'last_remote_positions': {},
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
    initial_bankroll = float(base.get('initial_bankroll_usd', config.risk.initial_bankroll_usd))
    snapshot = build_strategy_snapshot(config, COPYTRADING_STRATEGY_ID, initial_bankroll)
    raw_open_trades = list_open_trades(config, COPYTRADING_STRATEGY_ID)
    bot_state = base['bot_state']
    bot_state['initial_bankroll_usd'] = initial_bankroll
    bot_state['open_trades'] = raw_open_trades
    bot_state['open_trades_count'] = len(raw_open_trades)
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
    closed_positions = list_closed_trades(config, COPYTRADING_STRATEGY_ID)
    rolling_equity = initial_bankroll
    equity_peak = max(initial_bankroll, rolling_equity)
    max_drawdown_pct = 0.0
    chronological_closed = sorted(
        closed_positions,
        key=lambda row: str(row.get('exit_time') or row.get('resolution_time') or row.get('entry_time') or ''),
    )
    for trade in chronological_closed:
        pnl = float(trade.get('net_pnl_abs') or 0.0)
        rolling_equity += pnl
        equity_peak = max(equity_peak, rolling_equity)
        max_drawdown_pct = max(max_drawdown_pct, calculate_drawdown_pct(rolling_equity, equity_peak))
    bot_state['equity_peak_usd'] = equity_peak
    bot_state['current_drawdown_pct'] = calculate_drawdown_pct(bot_state['current_bankroll_usd'], equity_peak)
    bot_state['max_drawdown_pct'] = max_drawdown_pct if chronological_closed else bot_state.get('current_drawdown_pct', 0.0)
    state = base
    state['initial_bankroll_usd'] = initial_bankroll
    state['closed_positions'] = closed_positions
    state['bankroll_usd'] = snapshot['current_bankroll_usd']
    return state


def _save_state(config, state):
    path = _state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + '.tmp')
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    tmp_path.write_text(payload, encoding='utf-8')
    tmp_path.replace(path)


def _identity_key(identity: tuple[str, str, str]) -> str:
    return '||'.join(identity)


def _parse_identity_key(key: str) -> tuple[str, str, str]:
    parts = str(key).split('||', 2)
    while len(parts) < 3:
        parts.append('')
    return tuple(parts[:3])


def _remote_positions_to_state_map(wallet_positions: list[dict]) -> dict[str, dict]:
    return {
        _identity_key(_position_identity_from_remote(item)): item
        for item in wallet_positions
    }


def _iso_from_unix(timestamp_value) -> str:
    try:
        return datetime.fromtimestamp(float(timestamp_value)).astimezone().isoformat()
    except Exception:
        return now_iso()


def _trade_key(trade: dict) -> str:
    return str(trade.get('id') or trade.get('transactionHash') or trade.get('timestamp') or '')


def _map_side(trade: dict) -> str:
    return 'MIRROR'


def _fill_notional_usd(trade: dict) -> float:
    size = float(trade.get('size') or 0.0)
    price = float(trade.get('price') or 0.0)
    return max(0.0, size * price)


def _local_fill_budget_usd(state: dict, trade: dict) -> float:
    origin_notional = _fill_notional_usd(trade)
    local_cap_brl = float(state.get('copytrading_max_fill_brl') or 0.0)
    usd_brl_rate = float(state.get('usd_brl_rate') or 0.0)
    local_cap_usd = max(0.0, local_cap_brl / max(usd_brl_rate, 0.0001))
    return min(origin_notional, local_cap_usd)


def _open_copy_position(state: dict, trade: dict) -> OpenTrade:
    entry_price = float(trade.get('price') or 0.0)
    origin_contracts = float(trade.get('size') or 0.0)
    origin_notional = _fill_notional_usd(trade)
    capital = _local_fill_budget_usd(state, trade)
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
            'local_cap_brl': state.get('copytrading_max_fill_brl'),
        },
        weather_snapshot_at_entry={},
        status='OPEN',
    )


def _position_identity_from_trade_dict(trade: dict) -> tuple[str, str, str]:
    return (
        str(trade.get('market_id') or ''),
        str(trade.get('token_id') or ''),
        str(trade.get('outcome_label') or ''),
    )


def _position_identity_from_remote(position: dict) -> tuple[str, str, str]:
    return (
        str(position.get('conditionId') or position.get('market') or ''),
        str(position.get('asset') or ''),
        str(position.get('outcome') or position.get('title') or ''),
    )


def _remote_position_map(wallet_positions: list[dict]) -> dict[tuple[str, str, str], dict]:
    mapped: dict[tuple[str, str, str], dict] = {}
    for item in wallet_positions:
        mapped[_position_identity_from_remote(item)] = item
    return mapped


def _activity_matches_position(activity: dict, pos: dict) -> bool:
    activity_type = str(activity.get('type') or '').upper()
    if activity_type == 'TRADE':
        return (
            str(activity.get('asset') or '') == str(pos.get('token_id') or '')
            and str(activity.get('conditionId') or '') == str(pos.get('market_id') or '')
            and str(activity.get('outcome') or '') == str(pos.get('outcome_label') or '')
        )
    return str(activity.get('conditionId') or '') == str(pos.get('market_id') or '')


def _build_activity_index(activities: list[dict]) -> dict[str, list[dict]]:
    indexed: dict[str, list[dict]] = {}
    for item in activities:
        activity_type = str(item.get('type') or '').upper()
        asset = str(item.get('asset') or '')
        outcome = str(item.get('outcome') or '')
        condition_id = str(item.get('conditionId') or '')
        if activity_type == 'TRADE' and str(item.get('side') or '').upper() == 'SELL':
            key = _identity_key((condition_id, asset, outcome))
        else:
            key = _identity_key((condition_id, '', ''))
        indexed.setdefault(key, []).append(item)
    for key in indexed:
        indexed[key].sort(key=lambda row: float(row.get('timestamp') or 0.0))
    return indexed


def _entry_timestamp(pos: dict) -> float:
    try:
        return datetime.fromisoformat(str(pos.get('entry_time'))).timestamp()
    except Exception:
        return 0.0


def _find_exit_activity(activity_index: dict[str, list[dict]], pos: dict) -> dict | None:
    exact_key = _identity_key((str(pos.get('market_id') or ''), str(pos.get('token_id') or ''), str(pos.get('outcome_label') or '')))
    condition_key = _identity_key((str(pos.get('market_id') or ''), '', ''))
    entry_ts = _entry_timestamp(pos)

    for candidate in activity_index.get(exact_key, []):
        if float(candidate.get('timestamp') or 0.0) >= entry_ts and _activity_matches_position(candidate, pos):
            return candidate

    condition_candidates = [
        row for row in activity_index.get(condition_key, [])
        if float(row.get('timestamp') or 0.0) >= entry_ts and str(row.get('type') or '').upper() in {'REDEEM', 'MERGE'}
    ]
    return condition_candidates[0] if condition_candidates else None


def _resolution_from_previous_remote(previous_remote_position: dict | None) -> float | None:
    if not previous_remote_position:
        return None
    size = float(previous_remote_position.get('size') or 0.0)
    current_value = float(previous_remote_position.get('currentValue') or 0.0)
    cur_price = float(previous_remote_position.get('curPrice') or 0.0)
    if size > 0 and current_value >= 0:
        return current_value / size
    if cur_price >= 0:
        return cur_price
    return None


def _close_copied_position(pos: dict, previous_remote_position: dict | None, exit_activity: dict | None, exit_time_iso: str, exit_reason: str) -> dict:
    contracts_qty = float(pos.get('contracts_qty') or 0.0)
    entry_price = float(pos.get('entry_price') or 0.0)
    activity_type = str((exit_activity or {}).get('type') or '').upper()
    activity_price = float((exit_activity or {}).get('price') or 0.0)
    previous_resolution_value = _resolution_from_previous_remote(previous_remote_position)
    if activity_type == 'TRADE' and str((exit_activity or {}).get('side') or '').upper() == 'SELL' and activity_price > 0:
        resolution_value = activity_price
    elif previous_resolution_value is not None:
        resolution_value = previous_resolution_value
    else:
        resolution_value = entry_price
    gross_settlement = contracts_qty * resolution_value
    net_cost = float(pos.get('net_cost_usd') or 0.0)
    capital = float(pos.get('capital_alocado_usd') or 0.0)
    net_pnl = gross_settlement - net_cost
    roi = (net_pnl / capital) if capital else 0.0
    result = 'WIN' if net_pnl > 0 else ('LOSS' if net_pnl < 0 else 'BREAKEVEN')
    hold_hours = 0.0
    try:
        hold_hours = (datetime.fromisoformat(exit_time_iso) - datetime.fromisoformat(str(pos.get('entry_time')))).total_seconds() / 3600
    except Exception:
        hold_hours = 0.0
    closed = asdict(ClosedTrade(
        trade_id=str(pos.get('trade_id')),
        market_id=str(pos.get('market_id')),
        parent_slug=str(pos.get('parent_slug')),
        outcome_label=str(pos.get('outcome_label')),
        bucket_type=str(pos.get('bucket_type')),
        bucket_low=pos.get('bucket_low'),
        bucket_high=pos.get('bucket_high'),
        token_id=pos.get('token_id'),
        entry_time=str(pos.get('entry_time')),
        exit_time=exit_time_iso,
        resolution_time=exit_time_iso,
        side=str(pos.get('side')),
        entry_price=entry_price,
        resolution_value=resolution_value,
        capital_alocado_usd=capital,
        contracts_qty=contracts_qty,
        gross_cost_usd=float(pos.get('gross_cost_usd') or 0.0),
        fees_paid_usd=float(pos.get('fees_paid_usd') or 0.0),
        gross_settlement_value_usd=gross_settlement,
        net_pnl_abs=net_pnl,
        roi_on_allocated_capital=roi,
        result=result,
        hold_duration_hours=hold_hours,
        score=int(pos.get('score') or 50),
        weather_type=str(pos.get('weather_type') or 'copytrading'),
        cluster_id=str(pos.get('cluster_id') or 'copytrading'),
        resolution_source='target_wallet_position_reconciled',
        resolution_source_value={
            'exit_reason': exit_reason,
            'exit_activity': exit_activity or {},
            'previous_remote_position': previous_remote_position or {},
        },
        drawdown_after_close=0.0,
        exit_reason=exit_reason,
    ))
    return closed


def _list_recent_activity(client: PolymarketDataClient, wallet: str, min_timestamp: float, max_pages: int = 20, page_size: int = 100) -> list[dict]:
    activities: list[dict] = []
    offset = 0
    for _ in range(max_pages):
        try:
            batch = client.list_activity(user=wallet, limit=page_size, offset=offset)
        except Exception:
            break
        if not batch:
            break
        activities.extend(batch)
        oldest_ts = min(float(item.get('timestamp') or 0.0) for item in batch)
        if oldest_ts and oldest_ts < min_timestamp:
            break
        offset += len(batch)
    return activities


def _maybe_close_positions(config, state: dict, wallet_positions: list[dict], previous_remote_positions: dict[str, dict], recent_activities: list[dict]) -> None:
    now_dt = datetime.fromisoformat(now_iso())
    bot_state = state['bot_state']
    open_positions = bot_state.get('open_trades', [])
    remote_positions_by_identity = _remote_position_map(wallet_positions)
    activity_index = _build_activity_index(recent_activities)
    still_open = []
    for pos in open_positions:
        entry_dt = datetime.fromisoformat(pos['entry_time'])
        identity = _position_identity_from_trade_dict(pos)
        identity_key = _identity_key(identity)
        remote_position = remote_positions_by_identity.get(identity)
        previous_remote_position = previous_remote_positions.get(identity_key)
        # Manter posição aberta por pelo menos 10 minutos (evita flip-flop)
        if now_dt - entry_dt < timedelta(minutes=10):
            still_open.append(pos)
            continue

        if remote_position is not None:
            still_open.append(pos)
            continue

        exit_activity = _find_exit_activity(activity_index, pos)
        if exit_activity is None and previous_remote_position is None:
            still_open.append(pos)
            continue

        exit_type = str((exit_activity or {}).get('type') or 'MISSING').upper()
        if exit_type in {'REDEEM', 'MERGE'} and previous_remote_position is None:
            still_open.append(pos)
            continue

        exit_time_iso = _iso_from_unix((exit_activity or {}).get('timestamp')) if exit_activity else now_iso()
        closed = _close_copied_position(
            pos,
            previous_remote_position,
            exit_activity,
            exit_time_iso,
            f'target_wallet_position_closed_{exit_type.lower()}',
        )
        record_closed_trade(config, COPYTRADING_STRATEGY_ID, closed)
        bot_state['current_cash_usd'] += float(closed['gross_settlement_value_usd'])
        bot_state['capital_alocado_aberto_usd'] -= float(closed['capital_alocado_usd'])
        bot_state['realized_pnl_total_usd'] += float(closed['net_pnl_abs'])
        bot_state['closed_trades_count'] += 1
        state.setdefault('closed_positions', []).append(closed)
        
    bot_state['open_trades'] = still_open
    bot_state['open_trades_count'] = len(still_open)
    bot_state['current_bankroll_usd'] = bot_state['current_cash_usd'] + bot_state['capital_alocado_aberto_usd']
    state['bankroll_usd'] = bot_state['current_bankroll_usd']


def run_copytrading_competitor(wallet: str = DEFAULT_WALLET) -> dict:
    config = load_config()
    monitor = CopytradingMonitor(config)
    data_client = PolymarketDataClient(config)
    snapshot = monitor.poll_wallet(wallet)
    wallet_positions = data_client.list_positions(user=wallet, limit=500, offset=0)
    state = _load_state(config)
    bot_state = state['bot_state']
    previous_remote_positions = state.get('last_remote_positions') or {}
    open_entry_timestamps = [_entry_timestamp(pos) for pos in bot_state.get('open_trades', [])]
    min_entry_timestamp = min(open_entry_timestamps) if open_entry_timestamps else 0.0
    recent_activities = _list_recent_activity(data_client, wallet, min_entry_timestamp)

    _maybe_close_positions(config, state, wallet_positions, previous_remote_positions, recent_activities)

    seen_open_ids = {pos['trade_id'] for pos in bot_state.get('open_trades', [])}
    new_trades = snapshot.get('new_trades', [])
    copied_now = 0
    for trade in new_trades:
        trade_id = f"copy-{_trade_key(trade)}"
        if trade_id in seen_open_ids:
            continue
        pos = _open_copy_position(state, trade)
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
    state['last_remote_positions'] = _remote_positions_to_state_map(wallet_positions)
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
    return report


if __name__ == '__main__':
    print(json.dumps(run_copytrading_competitor(), ensure_ascii=False, indent=2))
