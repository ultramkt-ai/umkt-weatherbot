#!/usr/bin/env python3
"""
run_penny_bot_server.py — Inicializa o servidor Flask do dashboard do Penny-Bot.

Este script registra o blueprint do Penny-Bot no servidor Flask e roda na porta 5001.
Use em conjunto com o weather bot (porta 8789).

Uso:
    python3 run_penny_bot_server.py
    → Dashboard disponível em http://127.0.0.1:5001
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Adicionar o diretório do penny-bot ao path (prioridade)
# NOVO LOCAL: polymarket-probability-bot
PENNY_BOT_DIR = Path('/home/rafael/polymarket-probability-bot')
sys.path.insert(0, str(PENNY_BOT_DIR))

from flask import Flask

# Importar o módulo do dashboard (que já importa do penny-bot config)
from penny_bot_dashboard import penny_bp, setup_penny_bot_dashboard


def create_app() -> Flask:
    """Cria e configura o app Flask do Penny-Bot."""
    app = Flask(__name__)
    
    # CORS manual (sem flask_cors)
    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
    
    app.register_blueprint(penny_bp)
    return app


def main() -> None:
    """Inicializa e roda o servidor."""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logger = logging.getLogger(__name__)

    # Setup do StateManager
    db_path = PENNY_BOT_DIR / 'data' / 'positions.db'
    setup_penny_bot_dashboard(db_path='/home/rafael/polymarket-probability-bot/data/positions.db')

    # Criar app e rodar
    app = create_app()

    logger.info(f"Penny-Bot Dashboard server starting on http://127.0.0.1:5001")
    logger.info(f"Database: {db_path}")
    logger.info(f"Standalone dashboard: http://127.0.0.1:5001/penny-bot/")

    app.run(host='127.0.0.1', port=5001, debug=False)


if __name__ == '__main__':
    main()
