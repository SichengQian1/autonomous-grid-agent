from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .actions import Action, ActionType
from .geometry import Pos
from .grid import OccupancyGrid, shortest_path
from .models import Turn, Unit


@dataclass(frozen=True, slots=True)
class MoveIntent:
    actor_id: int
    goals: tuple[Pos, ...]
    priority: int = 0


def schedule_moves(
    turn: Turn,
    intents: Iterable[MoveIntent],
    *,
    occupied_destinations: Iterable[Pos] = (),
) -> tuple[Action, ...]:
    """Plan one conservative, collision-free step for each requested role."""

    roles: Mapping[int, Unit] = {
        role.unit_id: role for role in turn.controllable if role.pos is not None
    }
    current_positions = {role.pos for role in roles.values() if role.pos is not None}
    reserved = set(occupied_destinations)
    actions: list[Action] = []

    ordered = sorted(intents, key=lambda item: (-item.priority, item.actor_id))
    seen: set[int] = set()
    for intent in ordered:
        if intent.actor_id in seen:
            continue
        seen.add(intent.actor_id)
        role = roles.get(intent.actor_id)
        if role is None or role.pos is None:
            continue
        if role.pos in intent.goals:
            continue

        grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=(role.unit_id,))
        # Treat every other role's current cell as occupied even if it may move. This
        # conservative rule prevents same-cell contention, swaps, and following into
        # a cell that fails to vacate.
        extra_blocked = (current_positions - {role.pos}) | reserved
        path = shortest_path(grid, role.pos, intent.goals, extra_blocked=extra_blocked)
        if len(path) < 2:
            continue
        step = path[1]
        if step in reserved or step in current_positions:
            continue
        reserved.add(step)
        actions.append(Action(role.unit_id, ActionType.MOVE, targets=(step,)))
    return tuple(actions)
