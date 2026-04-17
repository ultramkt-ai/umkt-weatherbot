from datetime import datetime
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def now_dt() -> datetime:
    return datetime.now(DEFAULT_TIMEZONE)


def now_iso() -> str:
    return now_dt().isoformat()
