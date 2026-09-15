from __future__ import annotations

from .geometry import Pos
from .models import Turn
from .rules import ROLE_STATION, ROLE_WALL


def projectile_blockers(turn: Turn, except_actor: int | None = None) -> set[Pos]:
    """Walls and bases permit weapon fire; weapon buildings retain occlusion."""
    return {cell for unit in turn.team_our.roles + turn.team_enemy.roles
            if unit.alive and not unit.is_human and unit.role_type not in {ROLE_WALL, ROLE_STATION}
            and unit.unit_id != except_actor for cell in unit.footprint()}
