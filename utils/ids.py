from uuid import uuid4


def generate_session_id() -> str:
    return str(uuid4())


def generate_trade_id() -> str:
    return str(uuid4())


def generate_decision_id() -> str:
    return str(uuid4())
