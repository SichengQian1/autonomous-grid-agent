from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time

from .geometry import Pos, neighbours
from .models import Turn, Unit
from .rules import StrategyConfig


def occupied_cells(turn: Turn, *, except_actor: int | None = None) -> set[Pos]:
    cells = {zone.pos for zone in turn.map_info.zones if zone.pos is not None}
    for unit in turn.team_our.roles + turn.team_enemy.roles:
        if unit.alive and unit.unit_id != except_actor:
            cells.update(unit.footprint())
    cells.update(robot.pos for robot in turn.robots if robot.health > 0 and robot.pos is not None)
    return cells


def danger_cells(turn: Turn, deadline: float = float("inf")) -> set[Pos]:
    """Avoid both current attacks and one-step robot movement on human routes."""
    cells: set[Pos] = set()
    if turn.is_day:
        return cells
    for robot in turn.robots:
        if time.monotonic() >= deadline:
            break
        if robot.health <= 0 or robot.pos is None:
            continue
        radius = min(max(turn.map_info.width, turn.map_info.height), robot.attack_range + 1)
        for x in range(max(0, robot.pos.x - radius), min(turn.map_info.width, robot.pos.x + radius + 1)):
            if time.monotonic() >= deadline:
                break
            for y in range(max(0, robot.pos.y - radius), min(turn.map_info.height, robot.pos.y + radius + 1)):
                cells.add(Pos(x, y))
    return cells


@dataclass(frozen=True, slots=True)
class Route:
    destination: Pos
    distance: int
    step: Pos | None


class Navigator:
    def __init__(self, turn: Turn, config: StrategyConfig, deadline: float) -> None:
        self.turn = turn
        self.config = config
        self.deadline = deadline
        self.occupied = occupied_cells(turn)
        self.danger = danger_cells(turn, deadline)
        self.reserved: set[Pos] = set()
        self.claimed_goals: set[Pos] = set()
        self._cache: dict[tuple[int, bool], dict[Pos, tuple[int, Pos | None]]] = {}

    def reserve(self, cell: Pos) -> None:
        self.reserved.add(cell)
        self._cache.clear()

    def routes(self, role: Unit, *, safe: bool = True) -> dict[Pos, tuple[int, Pos | None]]:
        key = (role.unit_id, safe)
        if key in self._cache:
            return self._cache[key]
        if role.pos is None or time.monotonic() >= self.deadline:
            return {}
        blocked = self.occupied | self.reserved
        # Nobody enters another role's current cell, even if it plans to leave.
        # This conservative rule also prevents swaps and cascaded move failures.
        blocked.discard(role.pos)
        if safe:
            blocked |= self.danger
        seen: dict[Pos, tuple[int, Pos | None]] = {role.pos: (0, None)}
        queue = deque([role.pos])
        while queue and len(seen) < self.config.path_node_limit:
            if time.monotonic() >= self.deadline:
                break
            current = queue.popleft()
            distance, first = seen[current]
            for cell in sorted(neighbours(current), key=self.turn.coordinate_frame.normalize):
                if cell in blocked or cell in seen or not self.turn.map_info.contains(cell):
                    continue
                seen[cell] = (distance + 1, first or cell)
                queue.append(cell)
        self._cache[key] = seen
        return seen

    def route(self, role: Unit, goals: tuple[Pos, ...] | list[Pos], *, safe: bool = True) -> Route | None:
        reached = self.routes(role, safe=safe)
        options = [cell for cell in goals if cell in reached and cell not in self.claimed_goals]
        if not options:
            return None
        goal = min(options, key=lambda cell: (reached[cell][0], self.turn.coordinate_frame.normalize(cell)))
        distance, step = reached[goal]
        return Route(goal, distance, step)

    def adjacent_route(self, role: Unit, target: Pos) -> Route | None:
        return self.route(role, neighbours(target))

    def commit(self, route: Route) -> Pos | None:
        self.claimed_goals.add(route.destination)
        if route.step is not None:
            self.reserve(route.step)
        return route.step
