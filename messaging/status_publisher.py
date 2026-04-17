from datetime import datetime

from models.state import BotState


MODE_LABELS = {
    "ACTIVE": "ATIVO",
    "PAUSED": "PAUSADO",
    "DAILY_STOP": "STOP DIÁRIO",
    "WEEKLY_STOP": "STOP SEMANAL",
    "KILL_SWITCH": "KILL SWITCH",
    "ERROR_SAFE_MODE": "MODO SEGURO",
}


def _format_usd(value: float) -> str:
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"US$ {text}"


def _format_pct(value: float) -> str:
    return f"{value * 100:.1f}%".replace(".", ",")


def _format_clock(value: str | None) -> str:
    if not value:
        return "n/d"
    try:
        return datetime.fromisoformat(value).strftime("%H:%M")
    except ValueError:
        return value


def build_cycle_status_message(state: BotState) -> str:
    mode_label = MODE_LABELS.get(state.mode, state.mode)
    protection = "desligada"
    if state.kill_switch_active:
        protection = "kill switch ativo"
    elif state.weekly_stop_active:
        protection = "stop semanal ativo"
    elif state.daily_stop_active:
        protection = "stop diário ativo"
    elif state.protection_pause_active:
        protection = "pausa ativa"
    elif state.error_safe_mode_active:
        protection = "modo seguro ativo"

    last_score = state.last_score_approved if state.last_score_approved is not None else "n/d"
    next_scan = _format_clock(state.next_market_scan_at)
    next_check = _format_clock(state.next_open_trades_check_at)

    lines = [
        "🦞 Polymarket Weather Bot MVP",
        f"📍 Modo: {mode_label}",
        f"💵 Banca atual: {_format_usd(state.current_bankroll_usd)}",
        f"💰 Caixa livre: {_format_usd(state.current_cash_usd)}",
        f"📈 PnL realizado: {_format_usd(state.realized_pnl_total_usd)}",
        f"🧱 Capital aberto: {_format_usd(state.capital_alocado_aberto_usd)}",
        f"📊 Exposição aberta: {_format_pct(state.open_exposure_pct)}",
        f"🎯 Trades abertos: {state.open_trades_count}",
        f"✅ Trades fechados: {state.closed_trades_count}",
        f"🌦️ Mercados analisados hoje: {state.markets_scanned_today}",
        f"🟢 Aprovados hoje: {state.approved_today}",
        f"🔴 Rejeitados hoje: {state.rejected_today}",
        f"🧠 Último score aprovado: {last_score}",
        f"⏱ Próximo scan: {next_scan}",
        f"🔎 Próxima checagem: {next_check}",
        f"⚠️ Proteção: {protection}",
    ]

    if state.pause_reason:
        lines.append(f"🛑 Motivo: {state.pause_reason}")

    return "\n".join(lines)
