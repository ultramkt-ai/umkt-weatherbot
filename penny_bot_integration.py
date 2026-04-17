"""
penny_bot_integration.py — Integração do Penny-Bot no Weather Bot.

Fornece funções para obter dados do Penny-Bot sem precisar de servidor separado.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

# Adicionar polymarket-probability-bot ao path
PENNY_BOT_DIR = Path('/home/rafael/polymarket-probability-bot')
sys.path.insert(0, str(PENNY_BOT_DIR))

from state import StateManager

_db_path = '/home/rafael/polymarket-probability-bot/data/positions.db'
_state = None

def _get_state():
    global _state
    if _state is None:
        _state = StateManager(db_path=_db_path)
    return _state

def get_penny_bot_data() -> dict:
    """Retorna todos os dados do Penny-Bot para o dashboard."""
    try:
        state = _get_state()
        stats = state.get_stats_summary()
        open_positions = state.get_open_positions()
        active_markets = state.get_active_markets()
        
        # Calcular valores do portfolio
        positions_value = sum(
            (p.get("current_price") or p["entry_price"]) * p["shares"]
            for p in open_positions
        )
        
        initial_bankroll = 10_000.0
        invested = stats.get("total_invested", 0.0)
        realized_pnl = stats.get("total_pnl", 0.0)
        cash = initial_bankroll - invested + realized_pnl
        portfolio_value = cash + positions_value
        
        session_pnl = realized_pnl + sum(
            ((p.get("current_price") or p["entry_price"]) - p["entry_price"]) * p["shares"]
            for p in open_positions
        )
        
        # Enriquecer posições
        enriched_positions = []
        for p in open_positions[:50]:  # Limitar a 50 pra não pesar
            current_price = p.get("current_price") or p["entry_price"]
            market_value = current_price * p["shares"]
            pnl = (current_price - p["entry_price"]) * p["shares"]
            pnl_pct = (pnl / p["cost"]) * 100 if p["cost"] > 0 else 0
            potential_win = (1.0 - p["entry_price"]) * p["shares"]
            potential_win_pct = ((1.0 - p["entry_price"]) / p["entry_price"]) * 100 if p["entry_price"] > 0 else 0
            
            enriched_positions.append({
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
        
        # Trades recentes
        trades = []
        with state._connect() as conn:
            rows = conn.execute(
                """SELECT th.*, p.market_id, p.strategy, p.side
                   FROM trades_history th
                   JOIN positions p ON th.position_id = p.id
                   ORDER BY th.timestamp DESC
                   LIMIT 20""",
            ).fetchall()
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
        
        # Position cap
        penny_open = state.count_open_positions("penny")
        no_open = state.count_open_positions("no_systematic")
        
        return {
            "portfolio": {
                "cash": round(cash, 2),
                "positions_value": round(positions_value, 2),
                "portfolio_value": round(portfolio_value, 2),
                "session_pnl": round(session_pnl, 2),
                "total_invested": round(invested, 2),
                "total_pnl": round(realized_pnl, 2),
                "win_rate": stats.get("win_rate", 0.0),
                "closed_positions": stats.get("closed_positions", 0),
                "open_positions": len(open_positions),
                "monitored": len(active_markets),
                "last_update": datetime.now(timezone.utc).isoformat(),
            },
            "positions": enriched_positions,
            "trades": trades,
            "cap": {
                "penny_open": penny_open,
                "penny_target": 50,
                "no_open": no_open,
                "no_target": 50,
            },
            "status": "Rodando" if len(open_positions) > 0 or len(active_markets) > 0 else "Parado",
        }
    except Exception as e:
        return {
            "portfolio": {},
            "positions": [],
            "trades": [],
            "cap": {},
            "error": str(e),
            "status": "Erro",
        }
