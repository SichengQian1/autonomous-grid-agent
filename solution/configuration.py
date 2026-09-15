from __future__ import annotations

from dataclasses import fields, replace
import json
import math
import os
from pathlib import Path

from .rules import (
    DEFAULT_CONFIG,
    DEFENSE_LAYOUT_FRONTLINE,
    StrategyConfig,
    WEAPON_ROLE_TYPES,
)


_ENUM_FIELDS = {
    "defense_layout": frozenset({"legacy", "frontline"}),
    "front_direction": frozenset({"auto", "east", "west"}),
}
_BOOL_FIELDS = frozenset({
    "enabled",
    "night_gathering",
    "projectile_building_blocking",
    "allow_score_stealing",
    "wall_maintenance_enabled",
})
_FLOAT_FIELDS = {
    "normal_turn_budget_seconds": (0.0, 4.0),
    "wall_budget_fraction": (0.0, 1.0),
}
_INT_FIELDS = {
    "return_margin": (0, 8192),
    "path_node_limit": (0, 8192),
    "stone_reserve": (0, 8192),
    "sell_batch": (0, 8192),
    "max_walls": (0, 8192),
    "task_min_rounds": (0, 8192),
    "task_retry_rounds": (0, 8192),
    "max_task_calls": (0, 8192),
    "night_trip_radius": (0, 8192),
    "night_small_wave": (0, 8192),
    "heal_below": (0, 8192),
    "base_emergency_health": (0, 8192),
    "combat_candidate_limit": (0, 8192),
    "front_wall_target_count": (0, 10),
    "wall_emergency_horizon": (1, 20),
    "wall_observation_history_rounds": (1, 260),
    "front_observation_limit": (1, 256),
    "layout_candidate_limit": (1, 512),
    "layout_search_budget_ms": (10, 500),
}
_TUPLE_FIELDS = frozenset({"primary_weapon_loadout", "comparison_weapon_loadout"})


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
    parsed: dict[str, object] = {}
    for name, value in data.items():
        if name not in defaults:
            raise ValueError("unknown strategy setting")
        parsed[name] = _checked_value(name, value)
    config = replace(DEFAULT_CONFIG, **parsed)
    if (config.defense_layout == DEFENSE_LAYOUT_FRONTLINE
            and config.front_wall_target_count > config.max_walls):
        raise ValueError("front_wall_target_count cannot exceed max_walls")
    return config


def _checked_value(name: str, value: object) -> object:
    if name in _TUPLE_FIELDS:
        if (not isinstance(value, list) or len(value) != 3
                or any(item not in WEAPON_ROLE_TYPES for item in value)):
            raise ValueError("weapon composition must contain three known weapon types")
        return tuple(value)
    if name in _ENUM_FIELDS:
        if type(value) is not str or value not in _ENUM_FIELDS[name]:
            raise ValueError(f"{name} must be one of {sorted(_ENUM_FIELDS[name])}")
        return value
    if name in _BOOL_FIELDS:
        if type(value) is not bool:
            raise ValueError("strategy switch must be a boolean")
        return value
    if name in _FLOAT_FIELDS:
        low, high = _FLOAT_FIELDS[name]
        if type(value) is bool or type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{name} must be a finite number between {low} and {high}")
        return float(value)
    if name in _INT_FIELDS:
        low, high = _INT_FIELDS[name]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{name} must be an integer between {low} and {high}")
        return value
    raise ValueError("unknown strategy setting")
