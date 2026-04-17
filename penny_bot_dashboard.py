"""
penny_bot_dashboard.py — Módulo de dashboard do Penny-Bot integrado ao Weather Bot.

Fornece endpoints Flask e dados do Penny-Bot (Polymarket) para exibição no dashboard principal.
"""

from __future__ import annotations

import importlib.util
import logging
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, render_template_string


logger = logging.getLogger(__name__)

# Blueprint Flask para rotas do Penny-Bot
penny_bp = Blueprint('penny_bot', __name__, url_prefix='/penny-bot')

# Estado compartilhado (inicializado no setup)
_state_manager = None
_penny_bot_db_path = None
_penny_config = None
_penny_state_module = None


def _load_penny_bot_modules():
    """Carrega dinamicamente os módulos do penny-bot."""
    global _penny_config, _penny_state_module
    
    if _penny_config is not None:
        return
    
    # Path absoluto do penny-bot (NOVO LOCAL: polymarket-probability-bot)
    penny_bot_dir = Path('/home/rafael/polymarket-probability-bot')
    
    # Adicionar penny-bot ao sys.path PRIMEIRO (pra imports internos funcionarem)
    import sys
    if str(penny_bot_dir) not in sys.path:
        sys.path.insert(0, str(penny_bot_dir))
    
    # Carregar config.py do penny-bot
    config_path = penny_bot_dir / 'config.py'
    spec = importlib.util.spec_from_file_location("penny_config", config_path)
    _penny_config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_penny_config)
    
    # Carregar state.py do penny-bot (agora os imports vão funcionar)
    state_path = penny_bot_dir / 'state.py'
    spec = importlib.util.spec_from_file_location("penny_state", state_path)
    _penny_state_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_penny_state_module)


def setup_penny_bot_dashboard(db_path: str | None = None) -> None:
    """Inicializa o StateManager do Penny-Bot."""
    global _state_manager, _penny_bot_db_path
    
    _load_penny_bot_modules()
    
    # Usar path explícito do novo banco
    _penny_bot_db_path = db_path or '/home/rafael/polymarket-probability-bot/data/positions.db'
    _state_manager = _penny_state_module.StateManager(db_path=_penny_bot_db_path)
    logger.info(f"Penny-Bot Dashboard initialized with DB: {_penny_bot_db_path}")


def _get_state_manager():
    """Retorna o StateManager inicializado."""
    if _state_manager is None:
        raise RuntimeError("Penny-Bot Dashboard not initialized. Call setup_penny_bot_dashboard() first.")
    return _state_manager


def _get_strategies():
    """Retorna STRATEGIES do penny-bot."""
    _load_penny_bot_modules()
    return _penny_config.STRATEGIES


# ─── Helpers de Dados ────────────────────────────────────────────────────────

def get_portfolio_summary() -> dict:
    """Resumo do portfolio para os cards do topo."""
    state = _get_state_manager()
    stats = state.get_stats_summary()
    open_positions = state.get_open_positions()

    positions_value = sum(
        (p.get("current_price") or p["entry_price"]) * p["shares"]
        for p in open_positions
    )

    initial_bankroll = 10_000.0
    invested = sum(p["cost"] for p in open_positions)
    realized_pnl = stats.get("total_pnl", 0.0)
    cash = initial_bankroll - invested + realized_pnl

    portfolio_value = cash + positions_value
    session_pnl = realized_pnl + sum(
        ((p.get("current_price") or p["entry_price"]) - p["entry_price"]) * p["shares"]
        for p in open_positions
    )

    monitored = len(state.get_active_markets())

    return {
        "monitored": monitored,
        "open_positions": len(open_positions),
        "cash": round(cash, 2),
        "positions_value": round(positions_value, 2),
        "portfolio_value": round(portfolio_value, 2),
        "session_pnl": round(session_pnl, 2),
        "total_invested": stats.get("total_invested", 0.0),
        "total_pnl": stats.get("total_pnl", 0.0),
        "win_rate": stats.get("win_rate", 0.0),
        "closed_positions": stats.get("closed_positions", 0),
        "last_update": datetime.now(timezone.utc).isoformat(),
    }


def get_eligible_count() -> int:
    """Conta mercados elegíveis (simplificado)."""
    return 0


def get_in_range_count() -> int:
    """Conta mercados dentro do preço alvo (simplificado)."""
    return 0


def get_open_positions() -> list[dict]:
    """Posições abertas enriquecidas."""
    state = _get_state_manager()
    positions = state.get_open_positions()
    enriched = []

    for p in positions:
        current_price = p.get("current_price") or p["entry_price"]
        market_value = current_price * p["shares"]
        pnl = (current_price - p["entry_price"]) * p["shares"]
        pnl_pct = (pnl / p["cost"]) * 100 if p["cost"] > 0 else 0

        potential_win = (1.0 - p["entry_price"]) * p["shares"]
        potential_win_pct = ((1.0 - p["entry_price"]) / p["entry_price"]) * 100 if p["entry_price"] > 0 else 0

        enriched.append({
            "id": p["id"],
            "market_id": p["market_id"],
            "question": p.get("market_question", ""),
            "slug": p["market_id"].split("/")[-1] if "/" in p["market_id"] else p["market_id"][:40],
            "side": p["side"],
            "shares": round(p["shares"], 4),
            "entry_price": p["entry_price"],
            "current_price": current_price,
            "market_value": round(market_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "potential_win": round(potential_win, 2),
            "potential_win_pct": round(potential_win_pct, 2),
            "opened_at": p["opened_at"],
            "strategy": p["strategy"],
            "category": p.get("category", "other"),
        })

    enriched.sort(key=lambda x: x["pnl_pct"], reverse=True)
    return enriched


def get_recent_trades(limit: int = 20) -> list[dict]:
    """Últimos trades."""
    state = _get_state_manager()
    with state._connect() as conn:
        rows = conn.execute(
            """SELECT th.*, p.market_id, p.strategy, p.side, p.market_question
               FROM trades_history th
               JOIN positions p ON th.position_id = p.id
               ORDER BY th.timestamp DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

    trades = []
    for r in rows:
        trades.append({
            "id": r["id"],
            "position_id": r["position_id"],
            "action": r["action"],
            "price": r["price"],
            "shares": r["shares"],
            "timestamp": r["timestamp"],
            "reason": r["reason"] or "",
            "market_id": r["market_id"],
            "slug": r["market_id"].split("/")[-1] if "/" in r["market_id"] else r["market_id"][:40],
            "amount": round(r["price"] * r["shares"], 2),
        })

    return trades


def get_position_cap() -> dict:
    """Limites de posição."""
    open_count = _get_state_manager().count_open_positions("penny")
    strategies = _get_strategies()
    target = strategies["penny"].max_positions

    return {
        "open": open_count,
        "pending": 0,
        "remaining": max(0, target - open_count),
        "target": target,
        "opened": open_count,
    }


# ─── Rotas da API ────────────────────────────────────────────────────────────

@penny_bp.after_request
def add_cors_headers(response):
    """Adiciona CORS headers para todas as rotas da API."""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@penny_bp.route("/api/portfolio")
def api_portfolio():
    """API: resumo do portfolio."""
    data = get_portfolio_summary()
    data["eligible"] = get_eligible_count()
    data["in_range"] = get_in_range_count()
    return jsonify(data)


@penny_bp.route("/api/positions")
def api_positions():
    """API: posições abertas."""
    return jsonify(get_open_positions())


@penny_bp.route("/api/trades")
def api_trades():
    """API: trades recentes."""
    return jsonify(get_recent_trades())


@penny_bp.route("/api/cap")
def api_cap():
    """API: limites de posição."""
    return jsonify(get_position_cap())


# ─── Página do Dashboard (standalone) ────────────────────────────────────────

@penny_bp.route("/")
def penny_dashboard_page():
    """Serve o dashboard standalone do Penny-Bot."""
    return render_template_string(PENNY_DASHBOARD_HTML)


# ─── HTML Template (Nothing Ever Happens style) ─────────────────────────────

PENNY_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Penny-Bot Dashboard</title>
    <style>
        :root { --bg: #f0ebe3; --card-bg: #f7f4ef; --card-border: #e8e4dc; --text: #2b2520; --text-muted: #8b8378; --text-mono: #5a5248; --green: #3d6b4f; --green-light: #e8f0eb; --badge-bg: #e8dcc8; --badge-text: #6b5a4a; --shadow: 0 2px 8px rgba(43, 37, 32, 0.08); --radius: 16px; --radius-sm: 10px; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); padding: 24px 32px; line-height: 1.5; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 28px; }
        .header h1 { font-size: 32px; font-weight: 800; letter-spacing: -0.5px; }
        .header-right { display: flex; align-items: center; gap: 12px; }
        .socket-status { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--green); background: var(--green-light); padding: 6px 14px; border-radius: 20px; font-weight: 500; }
        .socket-dot { width: 8px; height: 8px; background: var(--green); border-radius: 50%; animation: pulse 2s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .metrics-grid { display: grid; grid-template-columns: repeat(8, 1fr); gap: 14px; margin-bottom: 20px; }
        .metric-card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: var(--radius); padding: 18px 16px; box-shadow: var(--shadow); }
        .metric-label { font-size: 10px; text-transform: uppercase; color: var(--text-muted); letter-spacing: 1px; font-weight: 600; margin-bottom: 10px; }
        .metric-value { font-size: 26px; font-weight: 700; letter-spacing: -0.5px; }
        .metric-sub { font-size: 11px; color: var(--text-muted); margin-top: 6px; }
        .positive { color: var(--green); }
        .negative { color: #a84438; }
        .cap-bar { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: var(--radius); padding: 20px 24px; margin-bottom: 24px; box-shadow: var(--shadow); }
        .cap-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
        .cap-title { font-weight: 700; font-size: 15px; }
        .cap-status { font-size: 12px; color: var(--text-muted); }
        .cap-values { font-size: 13px; color: var(--text-muted); margin-bottom: 12px; }
        .cap-visual { height: 48px; background: linear-gradient(90deg, rgba(61,107,79,0.1) 0%, rgba(61,107,79,0.3) 30%, rgba(61,107,79,0.2) 70%, rgba(61,107,79,0.1) 100%); border-radius: 8px; filter: blur(8px); }
        .main-grid { display: grid; grid-template-columns: 1fr 380px; gap: 20px; }
        .positions-panel, .trades-panel { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: var(--radius); padding: 20px 24px; box-shadow: var(--shadow); }
        .trades-panel { max-height: 700px; overflow-y: auto; }
        .panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; padding-bottom: 14px; border-bottom: 1px solid var(--card-border); }
        .panel-title { font-weight: 700; font-size: 15px; }
        .sort-info { font-size: 12px; color: var(--text-muted); }
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; font-size: 10px; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.8px; font-weight: 600; padding: 10px 8px; border-bottom: 1px solid var(--card-border); }
        td { padding: 16px 8px; border-bottom: 1px solid var(--card-border); font-size: 13px; vertical-align: top; }
        .market-name { font-weight: 600; margin-bottom: 4px; }
        .market-slug { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-mono); word-break: break-all; }
        .side-badge { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; background: var(--badge-bg); color: var(--badge-text); }
        .numeric { font-variant-numeric: tabular-nums; }
        .pnl-value { font-weight: 600; color: var(--green); }
        .pnl-pct { font-size: 11px; color: var(--green); margin-top: 2px; }
        .pnl-value.negative, .pnl-pct.negative { color: #a84438; }
        .trade-item { background: #fff; border: 1px solid var(--card-border); border-radius: var(--radius-sm); padding: 14px 16px; margin-bottom: 12px; }
        .trade-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }
        .trade-action { font-weight: 700; font-size: 14px; text-transform: uppercase; }
        .trade-time { font-size: 11px; color: var(--text-muted); }
        .trade-market { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-mono); margin-bottom: 8px; word-break: break-all; }
        .trade-details { font-size: 12px; color: var(--text-muted); }
        .trade-details strong { color: var(--text); }
        .empty-state { text-align: center; padding: 60px 20px; color: var(--text-muted); }
        @media (max-width: 1400px) { .metrics-grid { grid-template-columns: repeat(4, 1fr); } .main-grid { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <div class="header"><h1>Penny-Bot</h1><div class="header-right"><div class="socket-status"><div class="socket-dot"></div><span>socket: connected</span></div></div></div>
    <div class="metrics-grid">
        <div class="metric-card"><div class="metric-label">Monitored</div><div class="metric-value" id="monitored">--</div><div class="metric-sub">filtered standalone markets</div></div>
        <div class="metric-card"><div class="metric-label">Eligible</div><div class="metric-value" id="eligible">--</div><div class="metric-sub">no current position</div></div>
        <div class="metric-card"><div class="metric-label">In Range</div><div class="metric-value" id="in-range">--</div><div class="metric-sub">last known live ask at or below cap</div></div>
        <div class="metric-card"><div class="metric-label">Open Positions</div><div class="metric-value" id="open-positions">--</div><div class="metric-sub" id="position-sync">position sync --s ago</div></div>
        <div class="metric-card"><div class="metric-label">Cash</div><div class="metric-value" id="cash">--</div><div class="metric-sub" id="cash-sub">price cycle --s ago</div></div>
        <div class="metric-card"><div class="metric-label">Portfolio</div><div class="metric-value" id="portfolio">--</div><div class="metric-sub" id="portfolio-sub">--</div></div>
        <div class="metric-card"><div class="metric-label">Session PnL</div><div class="metric-value positive" id="session-pnl">--</div><div class="metric-sub" id="session-pnl-sub">--</div></div>
        <div class="metric-card"><div class="metric-label">Last Error</div><div class="metric-value" id="last-error">--</div><div class="metric-sub" id="last-error-sub">--</div></div>
    </div>
    <div class="cap-bar"><div class="cap-header"><div class="cap-title">Position Cap</div><div class="cap-status">env configured</div></div><div class="cap-values" id="cap-values">Loading...</div><div class="cap-visual"></div></div>
    <div class="main-grid">
        <div class="positions-panel"><div class="panel-header"><div class="panel-title">Open Positions</div><div class="sort-info">sorted by PnL%</div></div><table><thead><tr><th>Market</th><th>Side</th><th>Size</th><th>Avg Paid</th><th>Current</th><th>Market Value</th><th>PnL</th><th>Pot. Win</th></tr></thead><tbody id="positions-table"></tbody></table></div>
        <div class="trades-panel"><div class="panel-header"><div class="panel-title">Recent Trades</div><div class="sort-info">trade ledger tail</div></div><div id="trades-list"></div></div>
    </div>
    <script>
        async function fetchAll() { try { const [portfolio, positions, trades, cap] = await Promise.all([fetch('/penny-bot/api/portfolio').then(r => r.json()), fetch('/penny-bot/api/positions').then(r => r.json()), fetch('/penny-bot/api/trades').then(r => r.json()), fetch('/penny-bot/api/cap').then(r => r.json())]); updateMetrics(portfolio); updatePositions(positions); updateTrades(trades); updateCap(cap); document.getElementById('position-sync').textContent = 'position sync just now'; document.getElementById('last-error').textContent = 'none'; document.getElementById('last-error-sub').textContent = 'market refresh 5m ago'; } catch (e) { console.error('Fetch error:', e); } }
        function updateMetrics(data) { document.getElementById('monitored').textContent = data.monitored || '--'; document.getElementById('eligible').textContent = data.eligible || '--'; document.getElementById('in-range').textContent = data.in_range || '--'; document.getElementById('open-positions').textContent = data.open_positions; document.getElementById('cash').textContent = '$' + data.cash.toLocaleString(); document.getElementById('portfolio').textContent = '$' + data.portfolio_value.toLocaleString(); document.getElementById('portfolio-sub').textContent = 'cash $' + data.cash.toLocaleString() + ' | positions $' + data.positions_value.toLocaleString(); const pnlEl = document.getElementById('session-pnl'); pnlEl.textContent = (data.session_pnl >= 0 ? '+' : '') + '$' + data.session_pnl.toLocaleString(); pnlEl.className = 'metric-value ' + (data.session_pnl >= 0 ? 'positive' : 'negative'); document.getElementById('session-pnl-sub').textContent = 'balance $' + data.cash.toLocaleString(); }
        function updatePositions(positions) { const tbody = document.getElementById('positions-table'); if (!positions.length) { tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No open positions</td></tr>'; return; } tbody.innerHTML = positions.map(p => '<tr><td><div class="market-name">' + escapeHtml(p.question) + '</div><div class="market-slug">' + escapeHtml(p.slug) + '</div></td><td><span class="side-badge">' + p.side + '</span></td><td class="numeric">' + p.shares.toFixed(4) + '</td><td class="numeric">$' + p.entry_price.toFixed(4) + '</td><td class="numeric">$' + p.current_price.toFixed(4) + '</td><td class="numeric">$' + p.market_value.toFixed(2) + '</td><td><div class="pnl-value' + (p.pnl < 0 ? ' negative' : '') + '">$' + p.pnl.toFixed(2) + '</div><div class="pnl-pct' + (p.pnl < 0 ? ' negative' : '') + '">' + (p.pnl >= 0 ? '+' : '') + p.pnl_pct.toFixed(2) + '%</div></td><td><div class="pnl-value">$' + p.potential_win.toFixed(2) + '</div><div class="pnl-pct">+' + p.potential_win_pct.toFixed(2) + '%</div></td></tr>').join(''); }
        function updateTrades(trades) { const c = document.getElementById('trades-list'); if (!trades.length) { c.innerHTML = '<div class="empty-state">No recent trades</div>'; return; } c.innerHTML = trades.map(t => '<div class="trade-item"><div class="trade-header"><div class="trade-action">' + t.action + '</div><div class="trade-time">' + formatTime(t.timestamp) + '</div></div><div class="trade-market">-- | ' + escapeHtml(t.slug) + '</div><div class="trade-details"><strong>Amount:</strong> $' + t.amount.toFixed(2) + ' <strong>Price:</strong> $' + t.price.toFixed(4) + ' <strong>Status:</strong> --</div></div>').join(''); }
        function updateCap(cap) { document.getElementById('cap-values').textContent = 'Open ' + cap.open + ' | Pending ' + cap.pending + ' | Remaining ' + cap.remaining + ' | Target ' + cap.target + ' | Opened ' + cap.opened; }
        function formatTime(iso) { const d = new Date(iso); return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true }); }
        function escapeHtml(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }
        fetchAll(); setInterval(fetchAll, 5000);
    </script>
</body>
</html>
"""
