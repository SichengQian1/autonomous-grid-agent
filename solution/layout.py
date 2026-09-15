from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from itertools import product
import time

from .actions import Action, ActionType
from .ballistics import projectile_blockers
from .geometry import Pos, footprint_distance, footprint_ring, neighbours, ray_blocked
from .models import Robot, Turn, Unit
from .rules import (
    DEFENSE_LAYOUT_FRONTLINE,
    FRONT_DIRECTION_EAST,
    FRONT_DIRECTION_SHIFT_CONFIRM,
    FRONT_DIRECTION_WEST,
    FRONT_MIDLINE_MARGIN,
    LAYOUT_CONNECTIVITY_NODE_LIMIT,
    LAYOUT_TEST_POINT_LIMIT,
    ROLE_GATLING,
    ROLE_ROCKET,
    ROLE_WALL,
    DAY_ROUNDS,
    ROUNDS_PER_DAY,
    StrategyConfig,
    WALL_DELIVERY_TIMEOUT_ROUNDS,
    WALL_LEVEL_MAX_HP,
    WEAPON_LEVEL1_RANGE,
    WEAPON_BUILD_COST,
)


@dataclass(frozen=True, slots=True)
class WeaponPlacement:
    role_type: str
    pos: Pos
    controller_cells: tuple[Pos, ...]


@dataclass(frozen=True, slots=True)
class DefenseLayout:
    front: tuple[int, int]
    source: str
    weapons: tuple[WeaponPlacement, ...]
    front_walls: tuple[Pos, ...]
    flank_walls: tuple[Pos, ...]
    gates: tuple[Pos, ...]
    reason: str
    wall_order: tuple[Pos, ...] = ()
    corner_walls: tuple[Pos, ...] = ()
    required_wall_sites: tuple[Pos, ...] = ()
    wall_prerequisites: tuple[tuple[Pos, tuple[Pos, ...]], ...] = ()
    unfinished_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WallPlan:
    front_walls: tuple[Pos, ...]
    corner_walls: tuple[Pos, ...]
    flank_walls: tuple[Pos, ...]
    gates: tuple[Pos, ...]
    wall_order: tuple[Pos, ...]
    required_wall_sites: tuple[Pos, ...]
    wall_prerequisites: tuple[tuple[Pos, tuple[Pos, ...]], ...]
    unfinished_reasons: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class WallWork:
    kind: str
    target: Pos
    target_id: int | None
    item: str | None
    urgency: int
    expected_hp_gain: int
    gold_cost: int
    reason: str


@dataclass(frozen=True, slots=True)
class UnitHpSample:
    unit_id: int
    role_type: str
    pos: Pos
    level: int
    health: int
    round_no: int


@dataclass(slots=True)
class PendingBuy:
    role_id: int
    item: str
    price: int
    round_no: int
    backpack_count: int = 0


@dataclass(slots=True)
class DeliveryJob:
    role_id: int
    target_id: int
    target_pos: Pos
    item: str
    stage: str
    created_round: int
    expires_round: int


@dataclass(slots=True)
class FlankNightStats:
    peak_pressure: float = 0.0
    pressured_rounds: int = 0
    last_pressured_round: int = -1
    damaged: bool = False
    interior_entry: bool = False


@dataclass(slots=True)
class NightPressureSummary:
    game_day: int = -1
    sides: dict[str, FlankNightStats] = field(
        default_factory=lambda: {"neg": FlankNightStats(), "pos": FlankNightStats()}
    )
    samples_complete: bool = True
    last_sample_round: int = -1
    stale: bool = False


@dataclass(slots=True)
class DefenseMemory:
    layout: DefenseLayout | None = None
    weapons_frozen: bool = False
    front: tuple[int, int] | None = None
    front_source: str = ""
    observed_front: tuple[int, int] | None = None
    observed_shift_streak: int = 0
    last_observed_round: int = -1
    last_hp: dict[int, UnitHpSample] = field(default_factory=dict)
    damage_events: list[tuple[int, int, str, int]] = field(default_factory=list)
    last_robot_pos: dict[int, Pos] = field(default_factory=dict)
    pressure: dict[str, float] = field(default_factory=dict)
    front_robot_count: int = 0
    front_width: int = 0
    flank_pressure: dict[str, float] = field(default_factory=dict)
    day_index: int = -1
    start_gold: int = 0
    confirmed_income: int = 0
    confirmed_spend: int = 0
    reserved_spend: int = 0
    wall_spend: int = 0
    wall_reserved: int = 0
    last_gold: int = 0
    pending_buys: list[PendingBuy] = field(default_factory=list)
    deliveries: list[DeliveryJob] = field(default_factory=list)
    last_map_sig: tuple | None = None
    prior_mismatch: bool = False
    last_reason: str = ""
    current_night: NightPressureSummary | None = None
    last_night: NightPressureSummary | None = None

    def reset(self) -> None:
        self.layout = None
        self.weapons_frozen = False
        self.front = None
        self.front_source = ""
        self.observed_front = None
        self.observed_shift_streak = 0
        self.last_observed_round = -1
        self.last_hp.clear()
        self.damage_events.clear()
        self.last_robot_pos.clear()
        self.pressure.clear()
        self.front_robot_count = 0
        self.front_width = 0
        self.flank_pressure.clear()
        self.day_index = -1
        self.start_gold = 0
        self.confirmed_income = 0
        self.confirmed_spend = 0
        self.reserved_spend = 0
        self.wall_spend = 0
        self.wall_reserved = 0
        self.last_gold = 0
        self.pending_buys.clear()
        self.deliveries.clear()
        self.last_map_sig = None
        self.prior_mismatch = False
        self.last_reason = ""
        self.current_night = None
        self.last_night = None


def wall_max_health(unit: Unit) -> tuple[int, bool]:
    if unit.max_health > 0:
        return unit.max_health, False
    table = WALL_LEVEL_MAX_HP.get(unit.level, 0)
    return table, True


def observe_defense(turn: Turn, memory: DefenseMemory, config: StrategyConfig,
                    previous_actions: tuple[Action, ...] = ()) -> None:
    """Update bounded observations. Does not emit actions."""
    if config.defense_layout != DEFENSE_LAYOUT_FRONTLINE:
        return
    sig = _map_signature(turn)
    if memory.last_map_sig is not None and memory.last_map_sig != sig:
        memory.reset()
    memory.last_map_sig = sig
    if turn.round_no == memory.last_observed_round:
        return
    skipped = memory.last_observed_round >= 0 and turn.round_no > memory.last_observed_round + 1
    _observe_gold(turn, memory, previous_actions, skipped)
    _observe_damage(turn, memory, config, skipped)
    _observe_pressure(turn, memory, config, skipped)
    _observe_deliveries(turn, memory)
    if any(u.alive and u.is_weapon for u in turn.team_our.roles):
        memory.weapons_frozen = True
    memory.last_observed_round = turn.round_no


def plan_layout(turn: Turn, memory: DefenseMemory, config: StrategyConfig,
                deadline: float) -> DefenseLayout | None:
    if config.defense_layout != DEFENSE_LAYOUT_FRONTLINE:
        memory.last_reason = "legacy_mode"
        return None
    if time.monotonic() >= deadline:
        return memory.layout if _layout_structurally_ok(memory.layout, turn) else None
    sub_deadline = min(deadline, time.monotonic() + config.layout_search_budget_ms / 1000.0)
    front, source, reason = _resolve_front(turn, memory, config)
    if front is None:
        memory.last_reason = reason
        memory.layout = None
        return None
    memory.front = front
    memory.front_source = source
    if memory.weapons_frozen and _layout_structurally_ok(memory.layout, turn):
        refreshed = _refresh_walls(turn, memory.layout, memory, config, sub_deadline)
        if refreshed is not None:
            memory.layout = refreshed
            memory.last_reason = refreshed.reason
            return refreshed
    planned = _search_layout(turn, memory, config, front, source, sub_deadline)
    if planned is None:
        if _layout_structurally_ok(memory.layout, turn):
            memory.last_reason = "reuse_last_valid"
            return memory.layout
        memory.last_reason = memory.last_reason or "no_feasible_layout"
        return None
    memory.layout = planned
    memory.last_reason = planned.reason
    if any(u.alive and u.is_weapon for u in turn.team_our.roles):
        memory.weapons_frozen = True
    return planned


def remaining_weapon_placements(turn: Turn, layout: DefenseLayout) -> tuple[WeaponPlacement, ...]:
    unmatched = [u for u in turn.team_our.roles if u.alive and u.is_weapon and u.pos is not None]
    remaining: list[WeaponPlacement] = []
    for placement in layout.weapons:
        exact = next((u for u in unmatched
                      if u.pos == placement.pos and u.role_type == placement.role_type), None)
        if exact is not None:
            unmatched.remove(exact)
            continue
        by_type = next((u for u in unmatched if u.role_type == placement.role_type), None)
        if by_type is not None:
            unmatched.remove(by_type)
            continue
        remaining.append(placement)
    return tuple(remaining)


def remaining_wall_sites(turn: Turn, layout: DefenseLayout) -> tuple[Pos, ...]:
    existing = {u.pos for u in turn.team_our.roles if u.alive and u.role_type == ROLE_WALL and u.pos}
    order = layout.wall_order or layout.front_walls + layout.corner_walls + layout.flank_walls
    return tuple(p for p in order if p not in existing)


def submitted_wall_positions(actions: tuple[Action, ...] | list[Action]) -> set[Pos]:
    return {action.targets[0] for action in actions
            if action.action_type == ActionType.BUILD and action.name == ROLE_WALL and action.targets}


def wall_prereqs(layout: DefenseLayout, site: Pos) -> tuple[Pos, ...]:
    for pos, deps in layout.wall_prerequisites:
        if pos == site:
            return deps
    return ()


def built_or_submitted_walls(turn: Turn, actions: tuple[Action, ...] | list[Action] = ()) -> set[Pos]:
    cells = {u.pos for u in turn.team_our.roles if u.alive and u.role_type == ROLE_WALL and u.pos}
    cells |= submitted_wall_positions(actions)
    return cells


def site_build_ready(layout: DefenseLayout, site: Pos, built: set[Pos]) -> bool:
    return _dependencies_ready(site, built, dict(layout.wall_prerequisites))


def _dependencies_ready(site: Pos, built: set[Pos], dependencies: dict[Pos, tuple[Pos, ...]]) -> bool:
    pending = list(dependencies.get(site, ()))
    seen: set[Pos] = set()
    while pending:
        dep = pending.pop()
        if dep == site or dep not in built:
            return False
        if dep not in seen:
            seen.add(dep)
            pending.extend(dependencies.get(dep, ()))
    return True


def _map_signature(turn: Turn) -> tuple:
    station = turn.team_our.station()
    anchor = station.pos if station is not None else None
    return (turn.map_info.width, turn.map_info.height, anchor, turn.team_our.team_id)


def _base_cells(turn: Turn) -> tuple[Pos, ...]:
    station = turn.team_our.station()
    return station.footprint() if station is not None else ()


def _ring(turn: Turn, radius: int) -> tuple[Pos, ...]:
    return tuple(cell for cell in footprint_ring(_base_cells(turn), radius)
                 if turn.map_info.contains(cell))


def _resolve_front(turn: Turn, memory: DefenseMemory, config: StrategyConfig
                   ) -> tuple[tuple[int, int] | None, str, str]:
    if config.front_direction == FRONT_DIRECTION_EAST:
        return (1, 0), "user_prior", "explicit_east"
    if config.front_direction == FRONT_DIRECTION_WEST:
        return (-1, 0), "user_prior", "explicit_west"
    geometric = _geometric_front(turn)
    if geometric is None:
        return None, "legacy", "midline_or_invalid_base"
    if memory.weapons_frozen and memory.front is not None:
        return memory.front, memory.front_source or "user_prior", "frozen_weapons"
    if (memory.observed_front is not None
            and memory.observed_shift_streak >= FRONT_DIRECTION_SHIFT_CONFIRM):
        if memory.observed_front != geometric:
            memory.prior_mismatch = True
        return memory.observed_front, "observed", "observed_front"
    return geometric, "user_prior", "geometric_prior"


def _geometric_front(turn: Turn) -> tuple[int, int] | None:
    if turn.map_info.width <= 0 or turn.map_info.height <= 0:
        return None
    cells = _base_cells(turn)
    if len(cells) < 2:
        return None
    xs = [p.x for p in cells]
    mid = (turn.map_info.width - 1) / 2.0
    if max(xs) < mid - FRONT_MIDLINE_MARGIN:
        return (1, 0)
    if min(xs) > mid + FRONT_MIDLINE_MARGIN:
        return (-1, 0)
    return None


def _normalized_front(turn: Turn, front: tuple[int, int]) -> tuple[int, int]:
    frame = turn.coordinate_frame
    origin = frame.normalize(Pos(0, 0))
    stepped = frame.normalize(Pos(front[0], front[1]))
    return (stepped.x - origin.x, stepped.y - origin.y)


def _forward(pos: Pos, nfront: tuple[int, int], edge: int, turn: Turn) -> int:
    np = turn.coordinate_frame.normalize(pos)
    return np.x * nfront[0] + np.y * nfront[1] - edge


def _lateral(pos: Pos, nfront: tuple[int, int], origin: float, turn: Turn) -> float:
    np = turn.coordinate_frame.normalize(pos)
    return np.x * (-nfront[1]) + np.y * nfront[0] - origin


def _front_frame(cells: tuple[Pos, ...], front: tuple[int, int], turn: Turn) -> tuple[tuple[int, int], int, float]:
    nfront = _normalized_front(turn, front)
    ncells = [turn.coordinate_frame.normalize(p) for p in cells]
    edge = max(p.x * nfront[0] + p.y * nfront[1] for p in ncells)
    origin = sum(p.x * (-nfront[1]) + p.y * nfront[0] for p in ncells) / len(ncells)
    return nfront, edge, origin


def _static_blocked(turn: Turn) -> set[Pos]:
    cells = {zone.pos for zone in turn.map_info.zones if zone.pos is not None}
    for unit in turn.team_our.roles + turn.team_enemy.roles:
        if unit.alive and not unit.is_human:
            cells.update(unit.footprint())
    return cells


def _weapon_range(role_type: str, existing: Unit | None) -> int:
    if existing is not None and existing.attack_range > 0:
        return existing.attack_range
    return WEAPON_LEVEL1_RANGE.get(role_type, 0)


def _covers(origin: Pos, target: Pos, reach: int, blockers: set[Pos], rocket: bool) -> bool:
    if origin == target or origin.distance_to(target) > reach or reach <= 0:
        return False
    if rocket:
        return True
    occupied = set(blockers)
    occupied.discard(origin)
    occupied.discard(target)
    return not ray_blocked(origin, target, occupied)


def _test_points(turn: Turn, front: tuple[int, int], base: tuple[Pos, ...],
                 front_walls: tuple[Pos, ...]) -> tuple[Pos, ...]:
    fx, fy = front
    lx, ly = -fy, fx
    raw_edge = max(p.x * fx + p.y * fy for p in base)
    face = [p for p in base if p.x * fx + p.y * fy == raw_edge]
    anchor = min(face, key=turn.coordinate_frame.normalize)
    cx, cy = anchor.x, anchor.y
    points: list[Pos] = []
    for dx, dy in ((3 * fx, 3 * fy), (3 * fx - 2 * lx, 3 * fy - 2 * ly),
                   (3 * fx + 2 * lx, 3 * fy + 2 * ly)):
        points.append(Pos(cx + dx, cy + dy))
    for wall in front_walls[:4]:
        points.append(Pos(wall.x + fx, wall.y + fy))
    points.append(Pos(cx + fx - 3 * lx, cy + fy - 3 * ly))
    points.append(Pos(cx + fx + 3 * lx, cy + fy + 3 * ly))
    unique: list[Pos] = []
    seen: set[Pos] = set()
    zones = {zone.pos for zone in turn.map_info.zones if zone.pos is not None}
    for point in points:
        if point in seen or point in zones or not turn.map_info.contains(point):
            continue
        if footprint_distance(point, base) < 2:
            continue
        seen.add(point)
        unique.append(point)
        if len(unique) >= LAYOUT_TEST_POINT_LIMIT:
            break
    return tuple(unique)


def _reachable(start: Pos, blocked: set[Pos], turn: Turn, base: tuple[Pos, ...],
               *, goal: Pos | None = None, outside: bool = False,
               limit: int = LAYOUT_CONNECTIVITY_NODE_LIMIT) -> bool | None:
    if start is None:
        return False
    walkable = set(blocked)
    walkable.discard(start)
    if outside and footprint_distance(start, base) >= 3:
        return True
    if goal is not None and start == goal:
        return True
    queue = deque([start])
    seen = {start}
    while queue and len(seen) < limit:
        point = queue.popleft()
        if outside and footprint_distance(point, base) >= 3:
            return True
        if goal is not None and point == goal:
            return True
        for nxt in neighbours(point):
            if nxt in seen or nxt in walkable or not turn.map_info.contains(nxt):
                continue
            seen.add(nxt)
            queue.append(nxt)
    if outside and any(footprint_distance(p, base) >= 3 for p in seen):
        return True
    if goal is not None and goal in seen:
        return True
    return None if len(seen) >= limit else False


def _controllers_for(sites: tuple[Pos, ...], banned: set[Pos], turn: Turn,
                     nfront: tuple[int, int], edge: int) -> tuple[tuple[Pos, ...], ...] | None:
    options: list[list[Pos]] = []
    for site in sites:
        cells = [n for n in neighbours(site)
                 if n not in banned and turn.map_info.contains(n)]
        cells.sort(key=lambda p: (_forward(p, nfront, edge, turn), turn.coordinate_frame.normalize(p)))
        if not cells:
            return None
        options.append(cells[:6])
    for combo in product(*options):
        if len(set(combo)) == len(combo):
            return tuple((cell,) for cell in combo)
    return None


def _layout_structurally_ok(layout: DefenseLayout | None, turn: Turn) -> bool:
    if layout is None:
        return False
    base = _base_cells(turn)
    if not base:
        return False
    for placement in layout.weapons:
        if not turn.map_info.contains(placement.pos):
            return False
        if footprint_distance(placement.pos, base) != 1:
            return False
        occupant = next((u for u in turn.team_our.roles
                         if u.alive and not u.is_human and u.pos == placement.pos), None)
        if occupant is not None and occupant.role_type != placement.role_type:
            return False
    for cell in layout.front_walls + layout.corner_walls + layout.flank_walls + layout.gates:
        if not turn.map_info.contains(cell) or footprint_distance(cell, base) != 2:
            return False
    return True


def _existing_weapon_at(turn: Turn, pos: Pos) -> Unit | None:
    return next((u for u in turn.team_our.roles
                 if u.alive and u.is_weapon and u.pos == pos), None)


def _coverage(turn: Turn, weapons: tuple[WeaponPlacement, ...], blockers: set[Pos],
              points: tuple[Pos, ...], config: StrategyConfig) -> tuple[bool, int]:
    if not points:
        return False, 0
    covered = 0
    front_ok = False
    for index, point in enumerate(points):
        hit = False
        for weapon in weapons:
            reach = _weapon_range(weapon.role_type, _existing_weapon_at(turn, weapon.pos))
            rocket = weapon.role_type == ROLE_ROCKET or not config.projectile_building_blocking
            if _covers(weapon.pos, point, reach, blockers, rocket):
                hit = True
                break
        if hit:
            covered += 1
            if index == 0:
                front_ok = True
    return front_ok, covered


def _connectivity(turn: Turn, weapons: tuple[WeaponPlacement, ...], walls: set[Pos],
                  gates: set[Pos], blocked: set[Pos]) -> bool:
    base = _base_cells(turn)
    closed = set(blocked) | {w.pos for w in weapons} | walls
    for gate in gates:
        closed.discard(gate)
    for placement in weapons:
        for cell in placement.controller_cells:
            if _reachable(cell, closed, turn, base, outside=True) is not True:
                return False
    for role in turn.team_our.roles:
        if role.alive and role.is_human and role.pos is not None:
            if _reachable(role.pos, closed, turn, base, outside=True) is not True:
                return False
    for wall in walls:
        if not any(n not in closed and turn.map_info.contains(n) for n in neighbours(wall)):
            return False
    return True


def _prefix_connectivity(turn: Turn, weapons: tuple[WeaponPlacement, ...],
                         ordered_walls: list[Pos], gates: set[Pos], blocked: set[Pos]) -> bool:
    built: list[Pos] = []
    for wall in ordered_walls:
        built.append(wall)
        if not _connectivity(turn, weapons, set(built), gates, blocked):
            return False
    return True


def _choose_gates(yellow: tuple[Pos, ...], nfront: tuple[int, int], edge: int,
                  origin: float, blocked: set[Pos], turn: Turn) -> tuple[Pos, ...]:
    frame = turn.coordinate_frame
    rear = [p for p in yellow if _forward(p, nfront, edge, turn) <= -1 and p not in blocked]
    rear.sort(key=lambda p: (_forward(p, nfront, edge, turn), abs(_lateral(p, nfront, origin, turn)),
                             frame.normalize(p)))
    if not rear:
        side = [p for p in yellow if _forward(p, nfront, edge, turn) <= 0 and p not in blocked]
        side.sort(key=lambda p: (_forward(p, nfront, edge, turn), frame.normalize(p)))
        rear = side
    if not rear:
        return ()
    gates = [rear[0]]
    adjacent = [p for p in rear[1:] if p.distance_to(rear[0]) == 1]
    if adjacent:
        gates.append(adjacent[0])
    elif len(rear) > 1:
        gates.append(rear[1])
    return tuple(gates[:2])


def _edge_neighbours(pos: Pos) -> tuple[Pos, ...]:
    return (Pos(pos.x + 1, pos.y), Pos(pos.x - 1, pos.y),
            Pos(pos.x, pos.y + 1), Pos(pos.x, pos.y - 1))


def _game_day(round_no: int) -> int:
    return max(0, round_no - 1) // ROUNDS_PER_DAY


def _remembered_flank(memory: DefenseMemory, side: str) -> float:
    value = float(memory.flank_pressure.get(side, 0.0))
    for summary in (memory.current_night, memory.last_night):
        if summary is None or summary.stale:
            continue
        stats = summary.sides.get(side)
        if stats is not None:
            value = max(value, stats.peak_pressure)
    return value


def _side_of(pos: Pos, nfront: tuple[int, int], origin: float, turn: Turn) -> str:
    return "neg" if _lateral(pos, nfront, origin, turn) < 0 else "pos"


def wall_pressure(turn: Turn, front: tuple[int, int], memory: DefenseMemory, pos: Pos) -> float:
    nfront, edge, origin = _front_frame(_base_cells(turn), front, turn)
    damage = _wall_recent_damage(memory, pos)
    side = _side_of(pos, nfront, origin, turn)
    layout = memory.layout
    if layout is not None and pos in layout.corner_walls:
        return _remembered_flank(memory, side) + damage
    if _forward(pos, nfront, edge, turn) >= 2:
        return float(memory.front_robot_count + damage)
    return _remembered_flank(memory, side) + damage


def _ring_classes(turn: Turn, front: tuple[int, int], gates: set[Pos]
                  ) -> tuple[tuple[Pos, ...], dict[str, Pos], dict[str, list[Pos]],
                             tuple[int, int], int, float]:
    base = _base_cells(turn)
    yellow = _ring(turn, 2)
    nfront, edge, origin = _front_frame(base, front, turn)
    frame = turn.coordinate_frame
    usable = [p for p in yellow if p not in gates]
    if not usable:
        return (), {}, {"neg": [], "pos": []}, nfront, edge, origin
    max_fwd = max(_forward(p, nfront, edge, turn) for p in usable)
    front_edge = [p for p in usable if _forward(p, nfront, edge, turn) == max_fwd]
    front_edge.sort(key=lambda p: (_lateral(p, nfront, origin, turn), frame.normalize(p)))
    corners: dict[str, Pos] = {}
    body: tuple[Pos, ...]
    if len(front_edge) >= 2:
        corners[_side_of(front_edge[0], nfront, origin, turn)] = front_edge[0]
        corners[_side_of(front_edge[-1], nfront, origin, turn)] = front_edge[-1]
        if _side_of(front_edge[0], nfront, origin, turn) == _side_of(front_edge[-1], nfront, origin, turn):
            corners = {"neg": front_edge[0], "pos": front_edge[-1]}
        body = tuple(front_edge[1:-1])
    elif len(front_edge) == 1:
        corners[_side_of(front_edge[0], nfront, origin, turn)] = front_edge[0]
        body = ()
    else:
        body = ()
    yellow_set = set(yellow)
    chains: dict[str, list[Pos]] = {"neg": [], "pos": []}
    for side, corner in corners.items():
        current = corner
        seen = {corner}
        chain: list[Pos] = []
        while True:
            options = []
            for nxt in _edge_neighbours(current):
                if nxt not in yellow_set or nxt in seen or nxt in gates:
                    continue
                if _forward(nxt, nfront, edge, turn) >= _forward(current, nfront, edge, turn):
                    continue
                options.append(nxt)
            if not options:
                break
            options.sort(key=lambda p: (-_forward(p, nfront, edge, turn),
                                        abs(_lateral(p, nfront, origin, turn) - _lateral(corner, nfront, origin, turn)),
                                        frame.normalize(p)))
            current = options[0]
            seen.add(current)
            chain.append(current)
        chains[side] = chain
    return body, corners, chains, nfront, edge, origin


def _adjacent_body(corner: Pos, body: tuple[Pos, ...]) -> Pos | None:
    for cell in body:
        if abs(cell.x - corner.x) + abs(cell.y - corner.y) == 1:
            return cell
    return None


def _unique(cells: list[Pos]) -> list[Pos]:
    seen: set[Pos] = set()
    ordered: list[Pos] = []
    for cell in cells:
        if cell in seen:
            continue
        seen.add(cell)
        ordered.append(cell)
    return ordered


def _plan_walls(turn: Turn, weapons: tuple[WeaponPlacement, ...], front: tuple[int, int],
                memory: DefenseMemory, config: StrategyConfig, blocked: set[Pos],
                deadline: float) -> WallPlan:
    yellow = _ring(turn, 2)
    nfront, edge, origin = _front_frame(_base_cells(turn), front, turn)
    frame = turn.coordinate_frame
    controllers = {cell for weapon in weapons for cell in weapon.controller_cells}
    gates = _choose_gates(yellow, nfront, edge, origin, blocked | controllers, turn)
    gate_set = set(gates)
    body, corners, chains, nfront, edge, origin = _ring_classes(turn, front, gate_set)
    existing = {u.pos for u in turn.team_our.roles if u.alive and u.role_type == ROLE_WALL and u.pos}
    body_sorted = sorted(body, key=lambda p: (abs(_lateral(p, nfront, origin, turn)),
                                              _lateral(p, nfront, origin, turn), frame.normalize(p)))
    body_target = tuple(body_sorted[:config.front_wall_target_count])
    pressures = {side: _remembered_flank(memory, side) for side in ("neg", "pos")}
    takes = {"neg": 0, "pos": 0}
    needed = {"neg": False, "pos": False}
    disconnected = {"neg": False, "pos": False}
    for side in ("neg", "pos"):
        chain = chains[side]
        corner = corners.get(side)
        disconnected[side] = bool(chain) and any(cell in existing for cell in chain) and (
            corner is None or corner not in existing)
        needed[side] = bool(config.initial_flank_defense or pressures[side] > 0 or disconnected[side])
        if not needed[side]:
            continue
        take = config.initial_flank_depth if config.initial_flank_defense else 0
        if pressures[side] > 0:
            take = max(take, sum(1 for cell in chain if 0 <= _forward(cell, nfront, edge, turn) < 2))
        if disconnected[side]:
            last = max((index for index, cell in enumerate(chain) if cell in existing), default=-1)
            take = max(take, last + 1)
        takes[side] = min(len(chain), max(take, 1 if needed[side] else 0))
    body_chains = {
        side: sorted((p for p in body if _side_of(p, nfront, origin, turn) == side),
                     key=lambda p: (abs(_lateral(p, nfront, origin, turn)), frame.normalize(p)))
        for side in ("neg", "pos")
    }
    # Connectors are structural requirements, even with a smaller ordinary front quota.
    body_target = tuple(_unique(list(body_target) + [p for side in ("neg", "pos")
                                                   if needed[side] for p in body_chains[side]]))
    dependencies: dict[Pos, tuple[Pos, ...]] = {}
    for side in ("neg", "pos"):
        segment = list(body_chains[side])
        if side in corners:
            segment.append(corners[side])
        segment.extend(chains[side])
        for previous, cell in zip(segment, segment[1:]):
            dependencies[cell] = (previous,)
    required: list[Pos] = list(body_target)
    for side in ("neg", "pos"):
        if not needed[side]:
            continue
        corner = corners.get(side)
        if corner is not None:
            required.append(corner)
        required.extend(chains[side][:takes[side]])
    required = _unique(required)

    def side_segment(side: str, include_body: bool) -> list[Pos]:
        cells: list[Pos] = []
        corner = corners.get(side)
        if include_body and corner is not None:
            cells.extend(body_chains[side])
        if needed[side] and corner is not None:
            cells.append(corner)
        if needed[side]:
            cells.extend(chains[side][:takes[side]])
        return cells

    hot_neg = pressures["neg"] > 0 or disconnected["neg"]
    hot_pos = pressures["pos"] > 0 or disconnected["pos"]
    if hot_neg and not hot_pos:
        desired = side_segment("neg", True) + [cell for cell in body_target]
        desired.extend(side_segment("pos", False))
    elif hot_pos and not hot_neg:
        desired = side_segment("pos", True) + [cell for cell in body_target]
        desired.extend(side_segment("neg", False))
    else:
        desired = list(body_target)
        for side in ("neg", "pos"):
            corner = corners.get(side)
            if needed[side] and corner is not None:
                desired.append(corner)
        for side in ("neg", "pos"):
            if needed[side] and chains[side][:1]:
                desired.append(chains[side][0])
        hotter = sorted(("neg", "pos"), key=lambda side: -pressures[side])
        for side in hotter:
            if takes[side] > 1:
                desired.extend(chains[side][1:takes[side]])
    desired = _unique(desired)
    required_set = set(required)
    capacity = max(0, config.max_walls - len(existing))
    selected: list[Pos] = []
    reasons: list[str] = []
    for cell in desired:
        if cell in existing or cell in selected:
            continue
        if time.monotonic() >= deadline:
            if cell in required_set:
                reasons.append("deadline")
            break
        if len(selected) >= capacity:
            if cell in required_set:
                reasons.append("max_walls")
            continue
        if not _dependencies_ready(cell, existing | set(selected), dependencies):
            if cell in required_set:
                reasons.append("dependency")
            continue
        if cell in blocked or cell in controllers or cell in gate_set:
            if cell in required_set:
                reasons.append("occupied")
            continue
        if not turn.map_info.contains(cell):
            if cell in required_set:
                reasons.append("map_edge")
            continue
        trial = selected + [cell]
        if not _connectivity(turn, weapons, set(trial) | existing, gate_set, blocked):
            if cell in required_set:
                reasons.append("connectivity")
            continue
        selected.append(cell)
    chain_cells = set(chains["neg"]) | set(chains["pos"])
    geom = set(body) | set(corners.values()) | chain_cells
    classified = (existing | set(selected)) & geom
    fronts = tuple(sorted(classified & set(body), key=frame.normalize))
    corner_walls = tuple(sorted(classified & set(corners.values()), key=frame.normalize))
    flanks = tuple(sorted(classified & chain_cells, key=frame.normalize))
    order = tuple(selected) + tuple(sorted(existing & geom, key=frame.normalize))
    # Retain missing predecessors; filtering them out would recreate corner gaps.
    deps = tuple(dependencies.items())
    unfinished = [cell for cell in required if cell not in existing and cell not in selected]
    if unfinished and capacity <= len(selected) and "max_walls" not in reasons:
        reasons.append("max_walls")
    reason = "frontline"
    if selected:
        first = selected[0]
        if first in chain_cells or first in set(corners.values()):
            reason = "frontline_flank_priority"
    return WallPlan(fronts, corner_walls, flanks, gates, order, tuple(required),
                    tuple(deps), tuple(dict.fromkeys(reasons)), reason)


def _rank_cells(cells: list[Pos], role_type: str, turn: Turn, front: tuple[int, int],
                nfront: tuple[int, int], edge: int, origin: float, base: tuple[Pos, ...],
                blocked: set[Pos], config: StrategyConfig) -> list[Pos]:
    frame = turn.coordinate_frame
    center = _test_points(turn, front, base, ())[:1]
    target = center[0] if center else None

    def key(pos: Pos) -> tuple:
        fwd = _forward(pos, nfront, edge, turn)
        lat = abs(_lateral(pos, nfront, origin, turn))
        covers = 0
        if target is not None:
            reach = WEAPON_LEVEL1_RANGE.get(role_type, 0)
            rocket = role_type == ROLE_ROCKET or not config.projectile_building_blocking
            covers = int(_covers(pos, target, reach, projectile_blockers(turn), rocket))
        if role_type == ROLE_ROCKET:
            return (fwd, lat, frame.normalize(pos))
        if role_type == ROLE_GATLING:
            return (-covers, fwd, lat, frame.normalize(pos))
        return (-covers, abs(fwd) if fwd > 0 else -fwd, lat, frame.normalize(pos))

    ranked = sorted((p for p in cells if p not in blocked), key=key)
    if role_type == ROLE_GATLING:
        covering = [p for p in ranked if target is not None
                    and _covers(p, target, WEAPON_LEVEL1_RANGE[ROLE_GATLING],
                                projectile_blockers(turn), not config.projectile_building_blocking)]
        if covering:
            return covering
    return ranked


def _search_layout(turn: Turn, memory: DefenseMemory, config: StrategyConfig,
                   front: tuple[int, int], source: str, deadline: float) -> DefenseLayout | None:
    base = _base_cells(turn)
    if not base:
        memory.last_reason = "missing_base"
        return None
    blue = list(_ring(turn, 1))
    if not blue:
        memory.last_reason = "empty_weapon_ring"
        return None
    blocked = _static_blocked(turn)
    nfront, edge, origin = _front_frame(base, front, turn)
    loadout = config.primary_weapon_loadout
    pools = {
        role: _rank_cells(blue, role, turn, front, nfront, edge, origin, base, blocked, config)
        for role in set(loadout)
    }
    if ROLE_ROCKET in pools and not pools[ROLE_ROCKET]:
        pools[ROLE_ROCKET] = _rank_cells(blue, ROLE_ROCKET, turn, front, nfront, edge, origin, base, blocked, config)
    living = {u.pos: u.role_type for u in turn.team_our.roles if u.alive and u.is_weapon and u.pos}
    prelim: list[tuple[tuple, DefenseLayout]] = []
    count = 0
    types = list(loadout)

    def rec(index: int, used: set[Pos], acc: list[Pos]) -> None:
        nonlocal count
        if time.monotonic() >= deadline or count >= config.layout_candidate_limit:
            return
        if index == len(types):
            count += 1
            layout = _evaluate_weapons(turn, config, front, source, tuple(acc), types, blocked)
            if layout is None:
                return
            prelim.append((_weapon_score(turn, layout, front, nfront, edge, blocked, config), layout))
            return
        role = types[index]
        locked = next((pos for pos, kind in living.items() if kind == role and pos not in used), None)
        choices = [locked] if locked is not None else pools.get(role, blue)
        for cell in choices:
            if cell is None or cell in used:
                continue
            used.add(cell)
            acc.append(cell)
            rec(index + 1, used, acc)
            acc.pop()
            used.remove(cell)
            if time.monotonic() >= deadline or count >= config.layout_candidate_limit:
                return

    rec(0, set(), [])
    if not prelim:
        memory.last_reason = "no_feasible_layout"
        return None
    prelim.sort(key=lambda item: item[0], reverse=True)
    best: tuple[tuple, DefenseLayout] | None = None
    for _, skeleton in prelim[:8]:
        if time.monotonic() >= deadline:
            break
        layout = _with_walls(turn, memory, config, skeleton, blocked, deadline)
        if layout is None:
            continue
        score = _weapon_score(turn, layout, front, nfront, edge, blocked, config) + (len(layout.front_walls),)
        if best is None or score > best[0]:
            best = score, layout
    if best is None:
        memory.last_reason = "no_feasible_layout"
        return None
    return best[1]


def _weapon_score(turn: Turn, layout: DefenseLayout, front: tuple[int, int],
                  nfront: tuple[int, int], edge: int, blocked: set[Pos],
                  config: StrategyConfig) -> tuple:
    base = _base_cells(turn)
    points = _test_points(turn, front, base, layout.front_walls)
    blockers = projectile_blockers(turn) | {w.pos for w in layout.weapons}
    front_ok, covered = _coverage(turn, layout.weapons, blockers, points, config)
    short_ok = 0
    if points:
        for weapon in layout.weapons:
            reach = _weapon_range(weapon.role_type, _existing_weapon_at(turn, weapon.pos))
            rocket = weapon.role_type == ROLE_ROCKET or not config.projectile_building_blocking
            if _covers(weapon.pos, points[0], reach, blockers, rocket):
                short_ok += 2 if weapon.role_type == ROLE_GATLING else 1
    rocket_rear = sum(_forward(w.pos, nfront, edge, turn) for w in layout.weapons if w.role_type == ROLE_ROCKET)
    ctrl_rear = sum(_forward(w.controller_cells[0], nfront, edge, turn) for w in layout.weapons if w.controller_cells)
    return (int(front_ok), short_ok, covered, -rocket_rear, -ctrl_rear,
            tuple(sorted(turn.coordinate_frame.normalize(w.pos) for w in layout.weapons)))


def _evaluate_weapons(turn: Turn, config: StrategyConfig, front: tuple[int, int], source: str,
                      sites: tuple[Pos, ...], types: list[str], blocked: set[Pos]) -> DefenseLayout | None:
    if len(set(sites)) != len(sites):
        return None
    if any(not turn.map_info.contains(site) or footprint_distance(site, _base_cells(turn)) != 1
           for site in sites):
        return None
    base = _base_cells(turn)
    nfront, edge, _origin = _front_frame(base, front, turn)
    wall_ban = set(blocked) | set(sites) | set(base)
    controllers = _controllers_for(sites, wall_ban, turn, nfront, edge)
    if controllers is None:
        return None
    weapons = tuple(WeaponPlacement(role, pos, cells)
                    for role, pos, cells in zip(types, sites, controllers))
    points = _test_points(turn, front, base, ())
    blockers = projectile_blockers(turn) | set(sites)
    front_ok, _ = _coverage(turn, weapons, blockers, points, config)
    if not front_ok:
        return None
    return DefenseLayout(front, source, weapons, (), (), (), "weapons_only")


def _apply_wall_plan(skeleton: DefenseLayout, plan: WallPlan) -> DefenseLayout:
    return replace(
        skeleton,
        front_walls=plan.front_walls,
        flank_walls=plan.flank_walls,
        gates=plan.gates,
        reason=plan.reason,
        wall_order=plan.wall_order,
        corner_walls=plan.corner_walls,
        required_wall_sites=plan.required_wall_sites,
        wall_prerequisites=plan.wall_prerequisites,
        unfinished_reasons=plan.unfinished_reasons,
    )


def _with_walls(turn: Turn, memory: DefenseMemory, config: StrategyConfig,
                skeleton: DefenseLayout, blocked: set[Pos], deadline: float) -> DefenseLayout | None:
    plan = _plan_walls(turn, skeleton.weapons, skeleton.front, memory, config, blocked, deadline)
    layout = _apply_wall_plan(skeleton, plan)
    base = _base_cells(turn)
    blockers = projectile_blockers(turn) | {w.pos for w in layout.weapons}
    front_ok, _ = _coverage(turn, layout.weapons, blockers,
                            _test_points(turn, layout.front, base, plan.front_walls), config)
    if not front_ok:
        layout = replace(layout, front_walls=(), flank_walls=(), wall_order=(), corner_walls=(),
                         required_wall_sites=(), wall_prerequisites=(), unfinished_reasons=(),
                         reason="coverage_limited")
        front_ok, _ = _coverage(turn, layout.weapons, projectile_blockers(turn) | {w.pos for w in layout.weapons},
                                _test_points(turn, layout.front, base, ()), config)
        if not front_ok:
            return None
    walls = set(layout.front_walls) | set(layout.corner_walls) | set(layout.flank_walls)
    if not _connectivity(turn, layout.weapons, walls, set(layout.gates), blocked):
        return None
    return layout


def _refresh_walls(turn: Turn, layout: DefenseLayout, memory: DefenseMemory,
                   config: StrategyConfig, deadline: float) -> DefenseLayout | None:
    blocked = _static_blocked(turn)
    plan = _plan_walls(turn, layout.weapons, layout.front, memory, config, blocked, deadline)
    refreshed = _apply_wall_plan(layout, plan)
    if not _layout_structurally_ok(refreshed, turn):
        return None
    walls = set(plan.front_walls) | set(plan.corner_walls) | set(plan.flank_walls)
    if not _connectivity(turn, refreshed.weapons, walls, set(plan.gates), blocked):
        return layout
    return refreshed


def _threatens_us(turn: Turn, robot: Robot, base: tuple[Pos, ...]) -> bool:
    return (robot.target_team in {"", turn.team_our.team_type}
            or (robot.pos is not None and footprint_distance(robot.pos, base) <= robot.attack_range + 4))


def _sector(dx: int, dy: int) -> str:
    if dx == 0 and dy == 0:
        return "C"
    sx = 0 if abs(dx) * 2 < abs(dy) else (1 if dx > 0 else -1)
    sy = 0 if abs(dy) * 2 < abs(dx) else (1 if dy > 0 else -1)
    if sx == 0 and sy == 0:
        sx = 1 if dx > 0 else (-1 if dx < 0 else 0)
        sy = 1 if dy > 0 else (-1 if dy < 0 else 0)
    return {(1, 0): "E", (1, 1): "NE", (0, 1): "N", (-1, 1): "NW",
            (-1, 0): "W", (-1, -1): "SW", (0, -1): "S", (1, -1): "SE"}.get((sx, sy), "C")


def _mark_summary_stale(memory: DefenseMemory, day: int) -> None:
    if memory.last_night is not None and memory.last_night.game_day < day - 1:
        memory.last_night.stale = True


def _refresh_night_phase(turn: Turn, memory: DefenseMemory, skipped: bool) -> None:
    day = _game_day(turn.round_no)
    if skipped and memory.current_night is not None:
        memory.current_night.samples_complete = False
    if turn.is_day:
        memory.flank_pressure = {}
        if memory.current_night is not None:
            memory.last_night = memory.current_night
            memory.current_night = None
        _mark_summary_stale(memory, day)
        return
    if memory.current_night is None or memory.current_night.game_day != day:
        memory.flank_pressure = {}
        if memory.current_night is not None and memory.current_night.game_day < day:
            memory.last_night = memory.current_night
        memory.current_night = NightPressureSummary(game_day=day)
        if skipped or turn.round_no != day * ROUNDS_PER_DAY + DAY_ROUNDS + 1:
            memory.current_night.samples_complete = False
    if memory.last_night is not None:
        memory.last_night.stale = True  # Previous-night evidence applies only to the next daytime.
    _mark_summary_stale(memory, day)


def _record_night_sample(turn: Turn, memory: DefenseMemory, flanks: dict[str, float],
                         interior: dict[str, bool], nfront: tuple[int, int], origin: float) -> None:
    night = memory.current_night
    if night is None or night.last_sample_round == turn.round_no:
        return
    night.last_sample_round = turn.round_no
    night_start = night.game_day * ROUNDS_PER_DAY + DAY_ROUNDS
    for side in ("neg", "pos"):
        stats = night.sides.setdefault(side, FlankNightStats())
        value = flanks.get(side, 0.0)
        if value > stats.peak_pressure:
            stats.peak_pressure = value
        if value > 0:
            stats.pressured_rounds += 1
            stats.last_pressured_round = turn.round_no
        if interior.get(side):
            stats.interior_entry = True
    for round_no, unit_id, _sector, _amount in memory.damage_events:
        if round_no <= night_start:
            continue
        sample = memory.last_hp.get(unit_id)
        if sample is None or sample.role_type != ROLE_WALL or sample.pos is None:
            continue
        side = _side_of(sample.pos, nfront, origin, turn)
        night.sides.setdefault(side, FlankNightStats()).damaged = True


def _observe_pressure(turn: Turn, memory: DefenseMemory, config: StrategyConfig,
                      skipped: bool = False) -> None:
    _refresh_night_phase(turn, memory, skipped)
    base = _base_cells(turn)
    if not base or turn.is_day:
        return
    if not turn.robots_observed:
        if memory.current_night is not None:
            memory.current_night.samples_complete = False
        return
    centroid = Pos(sum(p.x for p in base) // len(base), sum(p.y for p in base) // len(base))
    front = memory.front or _geometric_front(turn) or (1, 0)
    nfront, edge, origin = _front_frame(base, front, turn)
    scores: dict[str, float] = {}
    samples = 0
    front_robots: list[Pos] = []
    flanks = {"neg": 0.0, "pos": 0.0}
    interior = {"neg": False, "pos": False}
    majority = {"E": 0.0, "W": 0.0}
    _, corners, _, _, _, _ = _ring_classes(turn, front, set())
    span = max((abs(_lateral(cell, nfront, origin, turn)) for cell in corners.values()), default=0.0)
    for robot in turn.robots:
        if samples >= config.front_observation_limit:
            break
        if robot.health <= 0 or robot.pos is None:
            continue
        close = footprint_distance(robot.pos, base) <= robot.attack_range + 6
        if not _threatens_us(turn, robot, base) and not close:
            continue
        samples += 1
        weight = (1.0 + robot.attack_power) / (footprint_distance(robot.pos, base) + 1)
        prev = memory.last_robot_pos.get(robot.robot_id)
        if prev is not None and footprint_distance(robot.pos, base) < footprint_distance(prev, base):
            weight *= 1.4
        sector = _sector(robot.pos.x - centroid.x, robot.pos.y - centroid.y)
        scores[sector] = scores.get(sector, 0.0) + weight
        fwd = _forward(robot.pos, nfront, edge, turn)
        lat = _lateral(robot.pos, nfront, origin, turn)
        if fwd >= 0:
            front_robots.append(robot.pos)
            if sector in {"E", "NE", "SE"}:
                majority["E"] += weight
            if sector in {"W", "NW", "SW"}:
                majority["W"] += weight
        yellow = _ring(turn, 2)
        near_flank = any(_forward(cell, nfront, edge, turn) >= 0 and robot.pos.distance_to(cell) <= 2
                         and abs(_lateral(cell, nfront, origin, turn)) >= 1.5
                         for cell in yellow)
        if near_flank or (fwd >= 0 and abs(lat) >= 2 and footprint_distance(robot.pos, base) <= 6):
            key = "neg" if lat < 0 else "pos"
            flanks[key] += weight
        if 0 <= fwd < 2 and span and abs(lat) + 1e-6 < span:
            interior["neg" if lat < 0 else "pos"] = True
        memory.last_robot_pos[robot.robot_id] = robot.pos
    memory.pressure = scores
    memory.front_robot_count = len(front_robots)
    if front_robots:
        lats = [_lateral(p, nfront, origin, turn) for p in front_robots]
        memory.front_width = int(max(lats) - min(lats))
    else:
        memory.front_width = 0
    memory.flank_pressure = flanks
    _record_night_sample(turn, memory, flanks, interior, nfront, origin)
    observed = None
    if majority["E"] > majority["W"] * 1.5 and majority["E"] > 0:
        observed = (1, 0)
    elif majority["W"] > majority["E"] * 1.5 and majority["W"] > 0:
        observed = (-1, 0)
    if observed is None:
        memory.observed_shift_streak = 0
        return
    if memory.observed_front == observed:
        memory.observed_shift_streak += 1
    else:
        memory.observed_front = observed
        memory.observed_shift_streak = 1
    if memory.front is not None and observed != memory.front:
        memory.prior_mismatch = True


def _observe_damage(turn: Turn, memory: DefenseMemory, config: StrategyConfig,
                    skipped: bool) -> None:
    window = config.wall_observation_history_rounds
    if skipped:
        memory.last_hp.clear()
    current: dict[int, UnitHpSample] = {}
    for unit in turn.team_our.roles:
        if not unit.pos:
            continue
        if unit.health <= 0:
            continue
        sample = UnitHpSample(unit.unit_id, unit.role_type, unit.pos, unit.level,
                              unit.health, turn.round_no)
        current[unit.unit_id] = sample
        previous = memory.last_hp.get(unit.unit_id)
        if previous is None or skipped:
            continue
        if (previous.role_type != unit.role_type or previous.pos != unit.pos
                or previous.level != unit.level or previous.round_no != turn.round_no - 1):
            continue
        lost = max(0, previous.health - unit.health)
        if lost:
            sector = _sector(unit.pos.x - _centroid(turn).x, unit.pos.y - _centroid(turn).y)
            memory.damage_events.append((turn.round_no, unit.unit_id, sector, lost))
    memory.last_hp = current
    cutoff = turn.round_no - window
    memory.damage_events = [e for e in memory.damage_events if e[0] > cutoff]


def _centroid(turn: Turn) -> Pos:
    cells = _base_cells(turn)
    if not cells:
        return Pos(0, 0)
    return Pos(sum(p.x for p in cells) // len(cells), sum(p.y for p in cells) // len(cells))


def _wall_recent_damage(memory: DefenseMemory, pos: Pos) -> int:
    return sum(amount for _, unit_id, _, amount in memory.damage_events
               if (sample := memory.last_hp.get(unit_id)) is not None and sample.pos == pos)


def unit_recent_damage(memory: DefenseMemory, unit_id: int, after_round: int) -> int:
    return sum(amount for round_no, uid, _, amount in memory.damage_events
               if uid == unit_id and round_no > after_round)


def _observe_gold(turn: Turn, memory: DefenseMemory, previous_actions: tuple[Action, ...],
                  skipped: bool) -> None:
    day = max(0, turn.round_no - 1) // ROUNDS_PER_DAY
    gold = turn.team_our.gold
    new_day = day != memory.day_index
    if new_day:
        memory.day_index = day
        memory.start_gold = gold
        memory.confirmed_income = memory.confirmed_spend = memory.wall_spend = 0
    still: list[PendingBuy] = []
    for pending in memory.pending_buys:
        actor = turn.team_our.unit(pending.role_id)
        gained = actor is not None and actor.backpack.count(pending.item) > pending.backpack_count
        failed = turn.round_no == pending.round_no + 1 and turn.last_action_results.get(pending.role_id) is False
        expired = turn.round_no > pending.round_no + WALL_DELIVERY_TIMEOUT_ROUNDS
        if gained:
            if (pending.round_no - 1) // ROUNDS_PER_DAY == day:
                memory.wall_spend += pending.price
        elif not failed and not expired and actor is not None and actor.alive:
            still.append(pending)
    memory.pending_buys = still
    memory.wall_reserved = sum(p.price for p in still)
    memory.reserved_spend = memory.wall_reserved
    if not new_day and not skipped:
        delta = gold - memory.last_gold
        sold = 0
        prices = {item.name: item.price for item in turn.vendor_shop}
        for action in previous_actions:
            if action.action_type == ActionType.SELL and turn.last_action_results.get(action.actor_id) is True:
                sold += prices.get(action.name, 0) * (action.quantity or 0)
        if delta > 0 and sold > 0:
            memory.confirmed_income += min(delta, sold)
        shop = {item.name: item.price for item in turn.weapon_shop}
        for action in previous_actions:
            if turn.last_action_results.get(action.actor_id) is not True:
                continue
            if action.action_type == ActionType.BUILD and action.name != ROLE_WALL:
                memory.confirmed_spend += WEAPON_BUILD_COST
            elif action.action_type == ActionType.BUY and (action.name == 'Medicine' or action.name.startswith('StationUpgradeVoucher')):
                memory.confirmed_spend += shop.get(action.name, 0) * (action.quantity or 1)
    memory.last_gold = gold


def _observe_deliveries(turn: Turn, memory: DefenseMemory) -> None:
    living = {u.unit_id: u for u in turn.team_our.roles if u.alive}
    kept: list[DeliveryJob] = []
    for job in memory.deliveries:
        actor, target = living.get(job.role_id), living.get(job.target_id)
        if (turn.round_no > job.expires_round or actor is None or target is None
                or target.pos != job.target_pos or target.role_type != ROLE_WALL):
            continue
        if job.item.startswith('WallUpgradeVoucher') and job.item[-1:] != str(target.level):
            continue
        if job.item in actor.backpack:
            job.stage = 'travel'
        elif job.stage == 'buy':
            if not any(p.role_id == job.role_id and p.item == job.item for p in memory.pending_buys):
                job.stage = 'approach'  # Failed purchase can be retried by its owner.
        elif job.stage != 'approach':
            continue
        kept.append(job)
    memory.deliveries = kept


def defensive_reserve(turn: Turn, config: StrategyConfig, actions: tuple[Action, ...] = ()) -> int:
    weapons = sum(u.alive and u.is_weapon for u in turn.team_our.roles)
    weapons += sum(a.action_type == ActionType.BUILD and a.name != ROLE_WALL for a in actions)
    reserve = max(0, 3 - weapons) * WEAPON_BUILD_COST
    prices = {item.name: item.price for item in turn.weapon_shop}
    station = turn.team_our.station()
    station_queued = any(a.action_type in {ActionType.BUY, ActionType.USE}
                         and a.name.startswith('StationUpgradeVoucher') for a in actions)
    if station and station.alive and station.health < config.base_emergency_health and station.level in {1, 2}:
        voucher = f'StationUpgradeVoucher{station.level}'
        held = any(u.alive and voucher in u.backpack for u in turn.team_our.roles)
        if not held and not station_queued:
            reserve += prices.get(voucher, 0)
    healed = {a.actor_id for a in actions if a.action_type == ActionType.USE and a.name == 'Medicine'}
    medicine_queued = {a.actor_id for a in actions if a.action_type == ActionType.BUY and a.name == 'Medicine'}
    medicine_need = sum(u.alive and u.is_human and u.health < config.heal_below
                        and u.unit_id not in healed | medicine_queued and 'Medicine' not in u.backpack
                        for u in turn.team_our.roles)
    reserve += medicine_need * prices.get('Medicine', 0)
    return reserve


def wall_budget_cap(turn: Turn, memory: DefenseMemory, config: StrategyConfig) -> int:
    reserve = defensive_reserve(turn, config)
    base = max(0, memory.start_gold + memory.confirmed_income - memory.confirmed_spend - reserve)
    return int(config.wall_budget_fraction * base)


def register_wall_buy(memory: DefenseMemory, role_id: int, item: str, price: int, round_no: int,
                      backpack_count: int = 0) -> None:
    memory.pending_buys.append(PendingBuy(role_id, item, price, round_no, backpack_count))
    memory.reserved_spend += price
    memory.wall_reserved += price


def register_delivery(memory: DefenseMemory, role_id: int, target: Unit, item: str,
                      round_no: int, stage: str) -> None:
    if target.pos is None:
        return
    previous = next((job for job in memory.deliveries if job.role_id == role_id and job.target_id == target.unit_id and job.item == item), None)
    memory.deliveries = [job for job in memory.deliveries
                         if not (job.role_id == role_id and job.target_id == target.unit_id)]
    memory.deliveries.append(DeliveryJob(
        role_id, target.unit_id, target.pos, item, stage, previous.created_round if previous else round_no,
        previous.expires_round if previous else round_no + WALL_DELIVERY_TIMEOUT_ROUNDS,
    ))
