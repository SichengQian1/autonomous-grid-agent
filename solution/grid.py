from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable

from .geometry import Pos
from .models import Turn


@dataclass(frozen=True, slots=True)
class OccupancyGrid:
    width: int
    height: int
    blocked: frozenset[Pos]

    @classmethod
    def from_turn(
        cls,
        turn: Turn,
        *,
        ignore_unit_ids: Iterable[int] = (),
    ) -> OccupancyGrid:
        ignored = set(ignore_unit_ids)
        blocked: set[Pos] = {
            zone.pos for zone in turn.map_info.zones if zone.pos is not None
        }
        for unit in turn.team_our.roles + turn.team_enemy.roles:
            if unit.unit_id not in ignored:
                blocked.update(unit.footprint())
        blocked.update(robot.pos for robot in turn.robots if robot.pos is not None and robot.health > 0)
        return cls(turn.map_info.width, turn.map_info.height, frozenset(blocked))

    def contains(self, pos: Pos) -> bool:
        return 0 <= pos.x < self.width and 0 <= pos.y < self.height

    def passable(self, pos: Pos, extra_blocked: Iterable[Pos] = ()) -> bool:
        return self.contains(pos) and pos not in self.blocked and pos not in set(extra_blocked)

    def neighbours(self, pos: Pos, extra_blocked: Iterable[Pos] = ()) -> tuple[Pos, ...]:
        extra = set(extra_blocked)
        # Deliberately no corner-cutting prohibition: diagonal movement between two
        # orthogonal obstacles is legal in this game.
        return tuple(
            candidate
            for candidate in pos.neighbours()
            if self.contains(candidate)
            and candidate not in self.blocked
            and candidate not in extra
        )


def shortest_path(
    grid: OccupancyGrid,
    start: Pos,
    goals: Iterable[Pos],
    *,
    extra_blocked: Iterable[Pos] = (),
    max_nodes: int = 4096,
) -> tuple[Pos, ...]:
    targets = {goal for goal in goals if grid.contains(goal)}
    if start in targets:
        return (start,)
    if not targets or not grid.contains(start):
        return ()

    blocked = set(extra_blocked)
    blocked.discard(start)
    frontier: deque[Pos] = deque([start])
    previous: dict[Pos, Pos | None] = {start: None}
    reached: Pos | None = None

    while frontier and len(previous) <= max_nodes:
        current = frontier.popleft()
        neighbours = sorted(
            grid.neighbours(current, blocked),
            key=lambda pos: (
                min(pos.distance_to(goal) for goal in targets),
                pos.x,
                pos.y,
            ),
        )
        for candidate in neighbours:
            if candidate in previous:
                continue
            previous[candidate] = current
            if candidate in targets:
                reached = candidate
                frontier.clear()
                break
            frontier.append(candidate)

    if reached is None:
        return ()
    path: list[Pos] = []
    cursor: Pos | None = reached
    while cursor is not None:
        path.append(cursor)
        cursor = previous[cursor]
    path.reverse()
    return tuple(path)


def interaction_cells(grid: OccupancyGrid, target: Pos) -> tuple[Pos, ...]:
    return tuple(pos for pos in target.neighbours() if grid.contains(pos) and pos not in grid.blocked)


def distance_field(grid: OccupancyGrid, starts: Iterable[Pos], *, max_nodes: int = 4096) -> dict[Pos, int]:
    """One bounded flood fill for many route-cost queries in the same turn."""
    distances = {p: 0 for p in starts if grid.contains(p) and p not in grid.blocked}
    queue = deque(distances)
    while queue and len(distances) < max_nodes:
        current = queue.popleft()
        for other in current.neighbours():
            if grid.contains(other) and other not in grid.blocked and other not in distances:
                distances[other] = distances[current] + 1
                queue.append(other)
    return distances
