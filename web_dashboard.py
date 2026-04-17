"""
web_dashboard.py — Dashboard local para Weather Bot + Copytrading + Penny-Bot.
Sidebar de módulos. Leitura apenas. Sem alteração de lógica de robôs.
"""
from __future__ import annotations
from datetime import datetime, timezone
from errno import EADDRINUSE
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import sqlite3

TZ = ZoneInfo('America/Sao_Paulo')
WB_DIR = Path('/home/rafael/.openclaw/workspace/weather_bot')
PB_DB = '/home/rafael/polymarket-probability-bot/data/positions.db'


def _get_weather_bot_data() -> dict:
    """Lê dados do Weather Bot (state + DB + reports)."""
    try:
        state_path = WB_DIR / 'data_runtime' / 'state' / 'bot_state.json'
        state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
        
        db_path = WB_DIR / 'data' / 'positions.db'
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM positions WHERE status='open'")
        open_positions = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM positions WHERE status='closed'")
        closed_positions = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM market_cache WHERE active=1")
        markets_monitored = cursor.fetchone()[0]
        
        conn.close()
        
        # Strategy comparison
        strategy_comp_path = WB_DIR / 'data_runtime' / 'reports' / 'strategy_comparison_latest.json'
        strategies = []
        if strategy_comp_path.exists():
            sc = json.loads(strategy_comp_path.read_text(encoding='utf-8'))
            strategies = sc.get('strategies', [])
        
        # Funnel report
        funnel_path = WB_DIR / 'data_runtime' / 'reports' / 'latest_funnel_report.json'
        funnel = {}
        if funnel_path.exists():
            funnel = json.loads(funnel_path.read_text(encoding='utf-8'))
        
        return {
            'status': 'Rodando' if state.get('last_cycle_finished_at') else 'Parado',
            'bankroll': round(state.get('current_bankroll_usd', 0), 2),
            'cash': round(state.get('current_cash_usd', 0), 2),
            'open_positions': open_positions,
            'closed_positions': closed_positions,
            'markets_monitored': markets_monitored,
            'realized_pnl': round(state.get('realized_pnl_total_usd', 0), 2),
            'drawdown': round(state.get('max_drawdown_pct', 0) * 100, 2),
            'last_cycle': state.get('last_cycle_finished_at', 'N/A'),
            'strategies': strategies,
            'funnel': funnel,
        }
    except Exception as e:
        return {'status': 'Erro', 'error': str(e)}


def _get_copytrading_data() -> dict:
    """Lê dados do Copytrading."""
    try:
        path = WB_DIR / 'data_runtime' / 'reports' / 'copytrading_latest.json'
        if not path.exists():
            return {'status': 'Sem dados'}
        data = json.loads(path.read_text(encoding='utf-8'))
        return {'status': 'OK', 'data': data}
    except Exception as e:
        return {'status': 'Erro', 'error': str(e)}


def _get_penny_bot_data() -> dict:
    """Lê dados do Penny-Bot (SQLite)."""
    try:
        conn = sqlite3.connect(PB_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM market_cache WHERE active=1")
        monitored = cursor.fetchone()[0]
        
        def get_stats(sn: str) -> dict:
            cursor.execute("SELECT COUNT(*) as c, SUM(cost) as i FROM positions WHERE status='open' AND strategy=?", (sn,))
            row = cursor.fetchone()
            return {'open': row['c'], 'invested': row['i'] or 0.0}
        
        penny_stats = get_stats('penny')
        no_stats = get_stats('no_systematic')
        
        def get_positions(sn: str) -> list:
            cursor.execute("SELECT * FROM positions WHERE status='open' AND strategy=? ORDER BY opened_at DESC LIMIT 50", (sn,))
            result = []
            for p in cursor.fetchall():
                cp = p['current_price'] or p['entry_price']
                pnl = (cp - p['entry_price']) * p['shares']
                result.append({
                    'id': p['id'], 'market_id': p['market_id'],
                    'question': p['market_question'] or '',
                    'slug': p['market_id'].split('/')[-1] if '/' in p['market_id'] else p['market_id'][:40],
                    'side': p['side'], 'shares': round(p['shares'], 4),
                    'entry_price': p['entry_price'], 'current_price': cp,
                    'pnl': round(pnl, 2), 'pnl_pct': round((pnl / p['cost']) * 100 if p['cost'] > 0 else 0, 2),
                    'strategy': p['strategy'],
                })
            return result
        
        total_open = penny_stats['open'] + no_stats['open']
        total_invested = penny_stats['invested'] + no_stats['invested']
        
        result = {
            'status': 'Rodando' if total_open > 0 else 'Parado',
            'monitored': monitored,
            'combined': {
                'open_positions': total_open, 'total_invested': round(total_invested, 2),
                'cash': round(10000.0 - total_invested, 2), 'portfolio_value': 10000.0,
            },
            'penny': {
                'name': 'Penny YES≤4¢', 'description': 'Compra YES a 1-4¢, payoff 25-100x',
                'open_positions': penny_stats['open'], 'total_invested': round(penny_stats['invested'], 2),
                'positions': get_positions('penny'),
                'cap': {'open': penny_stats['open'], 'target': 50},
            },
            'no_systematic': {
                'name': 'NO Sistemático NO≤50¢', 'description': 'Compra NO a 1-50¢, saída em 50% do TP',
                'open_positions': no_stats['open'], 'total_invested': round(no_stats['invested'], 2),
                'positions': get_positions('no_systematic'),
                'cap': {'open': no_stats['open'], 'target': 50},
            },
        }
        
        conn.close()
        return result
    except Exception as e:
        return {'status': 'Erro', 'monitored': 0, 'combined': {}, 'penny': {}, 'no_systematic': {}, 'error': str(e)}


def build_dashboard_payload() -> dict:
    return {
        'generated_at': datetime.now(TZ).strftime('%Y-%m-%d %H:%M GMT-3'),
        'modules': [
            {'id': 'weather-bot', 'label': 'Weather Bot', 'icon': '🌤️'},
            {'id': 'copytrading', 'label': 'Copytrading', 'icon': '📊'},
            {'id': 'penny-bot', 'label': 'Penny Bot', 'icon': '🦞'},
        ],
        'weatherBot': _get_weather_bot_data(),
        'copytrading': _get_copytrading_data(),
        'pennyBot': _get_penny_bot_data(),
    }


STATIC_HTML = """<!doctype html>
<html lang='pt-BR'>
<head>
  <meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
  <title>Dashboard Ultra</title>
  <style>
    :root{--bg:#08101f;--sidebar:#0f172a;--panel:rgba(15,23,42,.86);--text:#e8eefc;--muted:#91a4c4;--good:#22c55e;--bad:#ef4444;--line:rgba(148,163,184,.16);--panel-solid:#111b31;--accent:#3b82f6}
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:Inter,system-ui,sans-serif;background:var(--bg);color:var(--text);display:flex;min-height:100vh}
    .sidebar{width:240px;background:var(--sidebar);padding:24px 16px;border-right:1px solid var(--line);position:fixed;height:100vh;overflow-y:auto}
    .sidebar h1{font-size:18px;font-weight:700;margin-bottom:24px;color:var(--text)}
    .sidebar nav{display:flex;flex-direction:column;gap:8px}
    .sidebar button{padding:12px 16px;background:transparent;border:1px solid var(--line);border-radius:8px;color:var(--text);cursor:pointer;font-weight:600;text-align:left;display:flex;align-items:center;gap:12px}
    .sidebar button:hover{background:var(--panel-solid)}
    .sidebar button.active{background:var(--panel-solid);border-color:var(--accent)}
    .main{margin-left:240px;flex:1;padding:24px}
    .module{display:none}.module.active{display:block}
    .panel{background:var(--panel);border-radius:18px;padding:24px;margin-bottom:24px}
    .summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:16px;margin-top:16px}
    .stat{background:rgba(15,23,42,.6);border-radius:12px;padding:16px;text-align:center}
    .stat-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:1px}
    .stat-value{font-size:24px;font-weight:700;margin-top:8px}
    .card{background:var(--panel);border-radius:18px;padding:24px;margin-bottom:24px}
    table{width:100%;border-collapse:collapse}th,td{padding:12px;text-align:left;border-bottom:1px solid var(--line)}
    th{font-size:11px;color:var(--muted);text-transform:uppercase}
    .good{color:var(--good)}.bad{color:var(--bad)}.muted{color:var(--muted)}
    .pill{display:inline-block;padding:4px 12px;border-radius:20px;font-size:12px;background:var(--good);color:#fff}
    .tabs{margin:20px 0;border-bottom:1px solid var(--line);padding-bottom:0;display:flex;gap:8px}
    .tabs button{padding:10px 16px;background:transparent;border:none;border-radius:8px 8px 0 0;color:var(--text);cursor:pointer;font-weight:600}
    .tabs button.active{background:var(--panel-solid)}
    .strategy-card{background:rgba(15,23,42,.4);border-radius:12px;padding:16px;margin-bottom:12px;border:1px solid var(--line)}
    .strategy-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
    .strategy-name{font-weight:600;font-size:14px}
    .strategy-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;font-size:12px;color:var(--muted)}
  </style>
</head>
<body>
  <aside class="sidebar">
    <h1>🦞 Dashboard Ultra</h1>
    <nav>
      <button onclick="switchModule('weather-bot')" id="btn-weather-bot" class="active">
        <span>🌤️</span> Weather Bot
      </button>
      <button onclick="switchModule('copytrading')" id="btn-copytrading">
        <span>📊</span> Copytrading
      </button>
      <button onclick="switchModule('penny-bot')" id="btn-penny-bot">
        <span>🦞</span> Penny Bot
      </button>
    </nav>
  </aside>
  
  <main class="main">
    <div id="module-weather-bot" class="module active"></div>
    <div id="module-copytrading" class="module"></div>
    <div id="module-penny-bot" class="module"></div>
  </main>
  
  <script>
    let activePennyTab = 'penny';
    
    async function loadDashboard() {
      const res = await fetch('/api/dashboard');
      const data = await res.json();
      renderWeatherBot(data.weatherBot || {});
      renderCopytrading(data.copytrading || {});
      renderPennyBot(data.pennyBot || {});
    }
    
    function switchModule(moduleId) {
      document.querySelectorAll('.module').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.sidebar button').forEach(el => el.classList.remove('active'));
      document.getElementById('module-' + moduleId).classList.add('active');
      document.getElementById('btn-' + moduleId).classList.add('active');
    }
    
    function renderWeatherBot(wb) {
      if (wb.error) {
        document.getElementById('module-weather-bot').innerHTML = '<div class="panel"><h3>Weather Bot</h3><p class="bad">Erro: ' + wb.error + '</p></div>';
        return;
      }
      const lastCycle = wb.last_cycle !== 'N/A' ? new Date(wb.last_cycle).toLocaleString('pt-BR', {timeZone: 'America/Sao_Paulo'}) : 'N/A';
      
      let strategiesHtml = '';
      if (wb.strategies && wb.strategies.length > 0) {
        strategiesHtml = '<h4 style="margin:20px 0 12px">Estratégias</h4>';
        wb.strategies.forEach(s => {
          const strat = s.strategy || {};
          const state = s.state || {};
          const m = s.metrics || {};
          const name = strat.strategy_id || strat.name || 'Unknown';
          const side = strat.side_mode || 'N/A';
          const priceRange = (strat.min_price || 0) + '-' + (strat.max_price || 0);
          const bankroll = (state.current_bankroll_usd || 0).toFixed(2);
          const cash = (state.current_cash_usd || 0).toFixed(2);
          const pnl = (m.realized_pnl_total_usd || 0).toFixed(2);
          const pnlClass = pnl >= 0 ? 'good' : 'bad';
          const winRate = ((m.win_rate_closed_only || 0) * 100).toFixed(1);
          const trades = (m.closed_trades_logged || 0);
          const openTrades = (m.open_trades_logged || 0);
          const approvalRate = ((m.approval_rate || 0) * 100).toFixed(3);
          const scanned = m.markets_scanned_today || 0;
          const profitFactor = (m.profit_factor || 0).toFixed(4);
          const grossProfit = (m.gross_profit_closed_usd || 0).toFixed(2);
          const grossLoss = (m.gross_loss_closed_usd || 0).toFixed(2);
          const avgHoldHours = (m.avg_hold_hours_closed_only || 0).toFixed(1);
          const roi = ((m.roi_vs_initial_bankroll || 0) * 100).toFixed(2);
          const drawdown = ((state.max_drawdown_pct || 0) * 100).toFixed(2);
          const decisions = m.decisions_logged || 0;
          const approved = m.approved_decisions_logged || 0;
          const avgScore = (m.avg_decision_score || 0).toFixed(1);
          const cities = strat.exclusive_cities || [];
          const citiesStr = cities.length > 0 ? cities.slice(0, 3).join(', ') + (cities.length > 3 ? '...' : '') : 'Todas';
          
          strategiesHtml += '<div class="strategy-card">';
          strategiesHtml += '<div class="strategy-header">';
          strategiesHtml += '<span class="strategy-name">' + name + '</span>';
          strategiesHtml += '<span class="pill" style="background:' + (side === 'YES' ? 'var(--good)' : side === 'NO' ? 'var(--bad)' : '#64748b') + '">' + side + '</span>';
          strategiesHtml += '</div>';
          
          strategiesHtml += '<div class="summary-grid" style="margin-top:12px">';
          strategiesHtml += '<div class="stat"><div class="stat-label">Bankroll</div><div class="stat-value">$' + bankroll + '</div></div>';
          strategiesHtml += '<div class="stat"><div class="stat-label">Cash</div><div class="stat-value">$' + cash + '</div></div>';
          strategiesHtml += '<div class="stat"><div class="stat-label">PnL Realizado</div><div class="stat-value ' + pnlClass + '">$' + pnl + '</div></div>';
          strategiesHtml += '<div class="stat"><div class="stat-label">ROI</div><div class="stat-value ' + (roi >= 0 ? 'good' : 'bad') + '">' + roi + '%</div></div>';
          strategiesHtml += '<div class="stat"><div class="stat-label">Drawdown</div><div class="stat-value">' + drawdown + '%</div></div>';
          strategiesHtml += '<div class="stat"><div class="stat-label">Profit Factor</div><div class="stat-value ' + (profitFactor >= 1 ? 'good' : 'bad') + '">' + profitFactor + '</div></div>';
          strategiesHtml += '</div>';
          
          strategiesHtml += '<div class="summary-grid" style="margin-top:12px">';
          strategiesHtml += '<div class="stat"><div class="stat-label">Trades (Fechados)</div><div class="stat-value">' + trades + '</div></div>';
          strategiesHtml += '<div class="stat"><div class="stat-label">Trades (Abertos)</div><div class="stat-value">' + openTrades + '</div></div>';
          strategiesHtml += '<div class="stat"><div class="stat-label">Win Rate</div><div class="stat-value">' + winRate + '%</div></div>';
          strategiesHtml += '<div class="stat"><div class="stat-label">Avg Hold</div><div class="stat-value">' + avgHoldHours + 'h</div></div>';
          strategiesHtml += '<div class="stat"><div class="stat-label">Approval Rate</div><div class="stat-value">' + approvalRate + '%</div></div>';
          strategiesHtml += '<div class="stat"><div class="stat-label">Mercados (Hoje)</div><div class="stat-value">' + scanned + '</div></div>';
          strategiesHtml += '</div>';
          
          strategiesHtml += '<div class="summary-grid" style="margin-top:12px">';
          strategiesHtml += '<div class="stat"><div class="stat-label">Gross Profit</div><div class="stat-value good">$' + grossProfit + '</div></div>';
          strategiesHtml += '<div class="stat"><div class="stat-label">Gross Loss</div><div class="stat-value bad">$' + grossLoss + '</div></div>';
          strategiesHtml += '<div class="stat"><div class="stat-label">Decisões</div><div class="stat-value">' + decisions + '</div></div>';
          strategiesHtml += '<div class="stat"><div class="stat-label">Aprovadas</div><div class="stat-value">' + approved + '</div></div>';
          strategiesHtml += '<div class="stat"><div class="stat-label">Avg Score</div><div class="stat-value">' + avgScore + '</div></div>';
          strategiesHtml += '<div class="stat"><div class="stat-label">Price Range</div><div class="stat-value" style="font-size:14px">' + priceRange + '</div></div>';
          strategiesHtml += '</div>';
          
          strategiesHtml += '<div class="strategy-stats" style="margin-top:12px">';
          strategiesHtml += '<div>Cidades: ' + citiesStr + '</div>';
          strategiesHtml += '<div>Score Bias: ' + (strat.score_bias || 0) + '</div>';
          strategiesHtml += '<div>Max Entries: ' + (strat.max_entries_per_market || 0) + '</div>';
          strategiesHtml += '<div>Min Hours Res: ' + (strat.min_hours_to_resolution || 0) + 'h</div>';
          strategiesHtml += '<div>Distance Threshold: ' + (strat.required_min_distance_threshold || 0) + '°C</div>';
          strategiesHtml += '</div>';
          strategiesHtml += '</div>';
        });
      }
      
      let funnelHtml = '';
      if (wb.funnel && Object.keys(wb.funnel).length > 0) {
        const totals = wb.funnel.totals || {};
        funnelHtml = '<h4 style="margin:20px 0 12px">Funnel (Último Ciclo)</h4>';
        funnelHtml += '<div class="summary-grid">';
        funnelHtml += '<div class="stat"><div class="stat-label">Markets Scanned</div><div class="stat-value">' + (totals.markets_scanned || 0) + '</div></div>';
        funnelHtml += '<div class="stat"><div class="stat-label">Candidates</div><div class="stat-value">' + (totals.candidates || 0) + '</div></div>';
        funnelHtml += '<div class="stat"><div class="stat-label">Approved</div><div class="stat-value">' + (totals.approved || 0) + '</div></div>';
        funnelHtml += '<div class="stat"><div class="stat-label">Rejected</div><div class="stat-value">' + (totals.rejected || 0) + '</div></div>';
        funnelHtml += '</div>';
      }
      
      document.getElementById('module-weather-bot').innerHTML = 
        '<div class="panel">' +
          '<h3>Weather Bot</h3>' +
          '<p class="muted">Status: ' + (wb.status || 'N/A') + '</p>' +
          '<div class="summary-grid">' +
            '<div class="stat"><div class="stat-label">Bankroll</div><div class="stat-value">$' + (wb.bankroll || 0) + '</div></div>' +
            '<div class="stat"><div class="stat-label">Cash</div><div class="stat-value">$' + (wb.cash || 0) + '</div></div>' +
            '<div class="stat"><div class="stat-label">Posições Abertas</div><div class="stat-value">' + (wb.open_positions || 0) + '</div></div>' +
            '<div class="stat"><div class="stat-label">Posições Fechadas</div><div class="stat-value">' + (wb.closed_positions || 0) + '</div></div>' +
            '<div class="stat"><div class="stat-label">Mercados</div><div class="stat-value">' + (wb.markets_monitored || 0) + '</div></div>' +
            '<div class="stat"><div class="stat-label">PnL Realizado</div><div class="stat-value ' + (wb.realized_pnl >= 0 ? 'good' : 'bad') + '">$' + (wb.realized_pnl || 0) + '</div></div>' +
            '<div class="stat"><div class="stat-label">Drawdown Máx</div><div class="stat-value">' + (wb.drawdown || 0) + '%</div></div>' +
            '<div class="stat"><div class="stat-label">Último Ciclo</div><div class="stat-value muted" style="font-size:14px">' + lastCycle + '</div></div>' +
          '</div>' +
        '</div>' +
        strategiesHtml +
        funnelHtml;
    }
    
    function renderCopytrading(ct) {
      if (ct.status === 'Sem dados') {
        document.getElementById('module-copytrading').innerHTML = '<div class="panel"><h3>Copytrading</h3><p class="muted">Sem dados disponíveis</p></div>';
        return;
      }
      if (ct.error) {
        document.getElementById('module-copytrading').innerHTML = '<div class="panel"><h3>Copytrading</h3><p class="bad">Erro: ' + ct.error + '</p></div>';
        return;
      }
      const data = ct.data || {};
      document.getElementById('module-copytrading').innerHTML = '<div class="panel"><h3>Copytrading</h3><p class="muted">Dados carregados. Em desenvolvimento.</p><pre class="muted" style="margin-top:16px;font-size:11px">' + JSON.stringify(data, null, 2).slice(0, 500) + '...</pre></div>';
    }
    
    function renderPennyBot(pb) {
      if (pb.error) {
        document.getElementById('module-penny-bot').innerHTML = '<div class="panel"><h3>Penny Bot</h3><p class="bad">Erro: ' + pb.error + '</p></div>';
        return;
      }
      
      const active = activePennyTab === 'penny' ? pb.penny : pb.no_systematic;
      const combined = pb.combined || {};
      
      const monitored = pb.monitored || 0;
      const openPos = active.open_positions || 0;
      const invested = (active.total_invested || 0).toFixed(2);
      const capOpen = active.cap ? active.cap.open : 0;
      const capTarget = active.cap ? active.cap.target : 50;
      const combInvested = (combined.total_invested || 0).toFixed(2);
      const combOpen = combined.open_positions || 0;
      const name = active.name || 'Penny-Bot';
      const desc = active.description || '';
      
      const positions = active.positions || [];
      
      let posRows = '';
      if (positions.length === 0) {
        posRows = '<p class="muted">Sem posições abertas</p>';
      } else {
        posRows = '<table><thead><tr><th>Market</th><th>Side</th><th>Size</th><th>Avg Paid</th><th>Current</th><th>Market Value</th><th>PnL</th><th>Pot. Win</th></tr></thead><tbody>';
        positions.forEach(p => {
          const mv = p.current_price * p.shares;
          const pw = (1.0 - p.entry_price) * p.shares;
          const pwPct = ((1.0 - p.entry_price) / p.entry_price) * 100;
          const pnlClass = p.pnl >= 0 ? 'good' : 'bad';
          const pnlSign = p.pnl >= 0 ? '+' : '';
          posRows += '<tr>';
          posRows += '<td><div>' + (p.question || '-') + '</div><div class="muted" style="font-size:11px;font-family:monospace">' + (p.slug || '') + '</div></td>';
          posRows += '<td><span class="pill">' + p.side + '</span></td>';
          posRows += '<td>' + p.shares.toFixed(4) + '</td>';
          posRows += '<td>$' + p.entry_price.toFixed(4) + '</td>';
          posRows += '<td>$' + p.current_price.toFixed(4) + '</td>';
          posRows += '<td>$' + mv.toFixed(2) + '</td>';
          posRows += '<td class="' + pnlClass + '">$' + p.pnl.toFixed(2) + '<br><span style="font-size:11px">' + pnlSign + p.pnl_pct.toFixed(2) + '%</span></td>';
          posRows += '<td class="good">$' + pw.toFixed(2) + '<br><span style="font-size:11px">+' + pwPct.toFixed(2) + '%</span></td>';
          posRows += '</tr>';
        });
        posRows += '</tbody></table>';
      }
      
      const pennyBtnClass = activePennyTab === 'penny' ? 'active' : '';
      const noBtnClass = activePennyTab === 'no_systematic' ? 'active' : '';
      
      document.getElementById('module-penny-bot').innerHTML = 
        '<div class="panel">' +
          '<h3>' + name + '</h3>' +
          '<p class="muted">' + desc + '</p>' +
          '<div class="tabs">' +
            '<button onclick="switchPennyTab(\\'penny\\')" class="' + pennyBtnClass + '">Penny YES≤4¢</button>' +
            '<button onclick="switchPennyTab(\\'no_systematic\\')" class="' + noBtnClass + '">NO Sistemático NO≤50¢</button>' +
          '</div>' +
          '<div class="summary-grid">' +
            '<div class="stat"><div class="stat-label">Monitored</div><div class="stat-value">' + monitored + '</div></div>' +
            '<div class="stat"><div class="stat-label">Open Positions</div><div class="stat-value">' + openPos + '</div></div>' +
            '<div class="stat"><div class="stat-label">Invested</div><div class="stat-value">$' + invested + '</div></div>' +
            '<div class="stat"><div class="stat-label">Position Cap</div><div class="stat-value">' + capOpen + '/' + capTarget + '</div></div>' +
            '<div class="stat"><div class="stat-label">Combined Invested</div><div class="stat-value">$' + combInvested + '</div></div>' +
            '<div class="stat"><div class="stat-label">Total Open</div><div class="stat-value">' + combOpen + '</div></div>' +
          '</div>' +
        '</div>' +
        '<article class="card">' +
          '<div class="card-header"><h3>Open Positions - ' + name + '</h3></div>' +
          posRows +
        '</article>';
    }
    
    function switchPennyTab(tab) {
      activePennyTab = tab;
      loadDashboard();
    }
    
    loadDashboard();
    setInterval(loadDashboard, 15000);
  </script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in {'/', '/index.html'}:
            html = STATIC_HTML.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return
        if self.path == '/api/dashboard':
            payload = json.dumps(build_dashboard_payload(), ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'Not found')

    def log_message(self, format, *args):
        pass


def main() -> None:
    try:
        server = HTTPServer(('127.0.0.1', 8789), DashboardHandler)
    except OSError as exc:
        if exc.errno == EADDRINUSE:
            print('Dashboard já rodando em http://127.0.0.1:8789')
            return
        raise
    print('Dashboard rodando em http://127.0.0.1:8789')
    server.serve_forever()


if __name__ == '__main__':
    main()
