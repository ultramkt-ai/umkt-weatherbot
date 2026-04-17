#!/bin/bash
echo "🔪 Matando processos antigos..."
pkill -9 -f "web_dashboard.py" 2>/dev/null
sleep 2

echo "🚀 Iniciando Weather Bot com Penny-Bot integrado..."
cd /home/rafael/.openclaw/workspace/weather_bot
rm -rf __pycache__
python3 web_dashboard.py &
sleep 3

echo ""
echo "📊 Testando API..."
curl -s http://localhost:8789/api/dashboard | python3 -c "
import sys, json
d = json.load(sys.stdin)
pb = d.get('pennyBot', {})
p = pb.get('portfolio', {})
print(f'Penny-Bot no payload: {\"✅\" if p else \"❌\"}')
print(f'  Posições: {p.get(\"open_positions\", 0)}')
print(f'  Investido: \${p.get(\"total_invested\", 0):.2f}')
print(f'  Status: {pb.get(\"status\", \"N/A\")}')
" 2>/dev/null || echo "❌ Erro na API"

echo ""
echo "🌐 Dashboard: http://localhost:8789/"
