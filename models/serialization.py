from dataclasses import asdict, is_dataclass
from typing import Any, Type, TypeVar

T = TypeVar("T")


def dataclass_to_dict(instance: Any) -> Any:
    if is_dataclass(instance):
        return {k: dataclass_to_dict(v) for k, v in asdict(instance).items()}
    if isinstance(instance, list):
        return [dataclass_to_dict(item) for item in instance]
    if isinstance(instance, dict):
        return {k: dataclass_to_dict(v) for k, v in instance.items()}
    return instance
