from __future__ import annotations

from dataclasses import fields, replace
import json
import math
import os
from pathlib import Path

from .rules import DEFAULT_CONFIG, StrategyConfig, WEAPON_ROLE_TYPES


def load_config(path: str | None = None) -> StrategyConfig:
    """Load an explicit local JSON override; invalid settings fail at startup."""
    path = path if path is not None else os.environ.get("AGENT_CONFIG", "")
    if not path:
        return DEFAULT_CONFIG
    with Path(path).open("rb") as stream:
        data = json.loads(stream.read(16385))
    if not isinstance(data, dict):
        raise ValueError("strategy configuration must be an object")
    defaults = {field.name: getattr(DEFAULT_CONFIG, field.name) for field in fields(StrategyConfig)}
    for name, value in tuple(data.items()):
        if name not in defaults:
            raise ValueError("unknown strategy setting")
        default = defaults[name]
        if isinstance(default, tuple):
            if not isinstance(value, list) or len(value) != 3 or any(item not in WEAPON_ROLE_TYPES for item in value):
                raise ValueError("weapon composition must contain three known weapon types")
            data[name] = tuple(value)
        elif isinstance(default, bool):
            if type(value) is not bool:
                raise ValueError("strategy switch must be a boolean")
        elif isinstance(default, float):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 4:
                raise ValueError("turn budget must be between zero and four seconds")
        elif type(value) is not int or not 0 <= value <= 8192:
            raise ValueError("strategy count must be an integer between zero and 8192")
    return replace(DEFAULT_CONFIG, **data)
