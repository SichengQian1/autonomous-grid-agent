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
    yield_cells: tuple[Pos, ...] | None = None


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
    # Only roles explicitly offered to this scheduler may yield. Attacking,
    # task-locked and building roles have no movement intent and stay untouched.
    by_actor = {intent.actor_id: intent for intent in ordered}
    relaxed = OccupancyGrid.from_turn(turn, ignore_unit_ids=tuple(by_actor))
    routes = {intent.actor_id: shortest_path(relaxed, roles[intent.actor_id].pos, intent.goals)
              for intent in ordered if intent.actor_id in roles}
    yield_actions: dict[int, Action] = {}
    for intent in ordered:
        route = routes.get(intent.actor_id, ())
        for blocker_id, blocker in roles.items():
            held = by_actor.get(blocker_id)
            if (not held or blocker_id == intent.actor_id or blocker.pos not in route[1:]
                    or blocker.pos not in held.goals or held.priority >= intent.priority):
                continue
            grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=(blocker_id,))
            candidates = [p for p in grid.neighbours(blocker.pos)
                          if p not in current_positions and p not in reserved and p not in route
                          and (held.yield_cells is None or p in held.yield_cells)]
            if candidates and blocker_id not in yield_actions:
                # Prefer the far side of a choke; keep the approach lane clear.
                target = min(candidates, key=lambda p: (min(p.distance_to(g) for g in intent.goals), p))
                yield_actions[blocker_id] = Action(blocker_id, ActionType.MOVE, targets=(target,))
                reserved.add(target)
    actions.extend(yield_actions.values())
    seen: set[int] = set()
    for intent in ordered:
        if intent.actor_id in yield_actions:
            continue
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
        if step in intent.goals and any(
            other.priority > intent.priority and step in routes.get(other.actor_id, ())[1:3]
            for other in ordered if other.actor_id != intent.actor_id
        ):
            continue
        if step in reserved or step in current_positions:
            continue
        reserved.add(step)
        actions.append(Action(role.unit_id, ActionType.MOVE, targets=(step,)))
    return tuple(actions)
