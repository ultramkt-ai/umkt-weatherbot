#!/bin/bash
pkill -9 -f "web_dashboard.py" 2>/dev/null
pkill -9 -f "run_penny_bot_server" 2>/dev/null
sleep 2
cd /home/rafael/.openclaw/workspace/weather_bot
nohup python3 run_penny_bot_server.py > /tmp/penny-server.log 2>&1 &
sleep 3
nohup python3 web_dashboard.py > /tmp/weather-bot.log 2>&1 &
sleep 3
echo "✅ Dashboards iniciados"
curl -s http://localhost:8789/api/dashboard | python3 -c "import sys,json; d=json.load(sys.stdin); print('Modules:', [m['id'] for m in d.get('modules',[])])" 2>/dev/null
