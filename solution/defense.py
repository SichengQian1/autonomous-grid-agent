from __future__ import annotations

from itertools import combinations, permutations
from typing import Callable

from .geometry import Pos, footprint_distance, footprint_ring, neighbours
from .models import Turn, Unit
from .navigation import Navigator, Route


def base_cells(turn: Turn) -> tuple[Pos, ...]:
    station = turn.team_our.station()
    return station.footprint() if station is not None else ()


def build_cells(turn: Turn, radius: int) -> tuple[Pos, ...]:
    return tuple(cell for cell in footprint_ring(base_cells(turn), radius)
                 if turn.map_info.contains(cell))


def weapon_sites(turn: Turn) -> tuple[Pos, ...]:
    """Choose a compact front-facing trio, ranked in normalized coordinates."""
    cells = build_cells(turn, 1)
    frame = turn.coordinate_frame
    centre = frame.denormalize(Pos(turn.map_info.width // 2, turn.map_info.height // 2))
    ordered = sorted(cells, key=lambda p: (p.distance_to(centre), frame.normalize(p)))
    chosen: list[Pos] = []
    for cell in ordered:
        if all(cell.distance_to(other) >= 2 for other in chosen):
            chosen.append(cell)
        if len(chosen) == 3:
            break
    for cell in ordered:
        if len(chosen) == 3:
            break
        if cell not in chosen:
            chosen.append(cell)
    return tuple(chosen)


def wall_sites(turn: Turn, limit: int) -> tuple[Pos, ...]:
    cells = build_cells(turn, 2)
    frame = turn.coordinate_frame
    centre = frame.denormalize(Pos(turn.map_info.width // 2, turn.map_info.height // 2))
    # Keep two neighbouring cells open as a permanent entrance/exit.
    ordered = sorted(cells, key=lambda p: (p.distance_to(centre), frame.normalize(p)))
    gates = set(ordered[:1])
    if ordered:
        adjacent = [p for p in ordered[1:] if p.distance_to(ordered[0]) == 1]
        gates.update(adjacent[:1])
    return tuple(p for p in ordered if p not in gates)[:limit]


def controller_assignments(turn: Turn, nav: Navigator, *,
                           fire_value: Callable[[dict[int, Unit]], float] | None = None) -> dict[int, Unit]:
    roles = sorted((r for r in turn.team_our.roles if r.alive and r.is_human and r.pos),
                   key=lambda r: r.unit_id)[:3]
    weapons = sorted((w for w in turn.team_our.roles if w.alive and w.is_weapon and w.pos),
                     key=lambda w: (-w.level, -w.attack_power, w.unit_id))[:3]
    if not roles or not weapons:
        return {}
    best: tuple[tuple[float, int, float], dict[int, Unit]] | None = None
    routes = {(r.unit_id, w.unit_id): defensive_route(turn, nav, r, w) for r in roles for w in weapons}
    count = min(len(roles), len(weapons))
    # Enumerate weapon subsets as well as role subsets after casualties.
    for selected in combinations(roles, count):
        for selected_weapons in permutations(weapons, count):
            mapping = {r.unit_id: w for r, w in zip(selected, selected_weapons)}
            cost, ready = 0.0, 0
            for role, weapon in zip(selected, selected_weapons):
                route = routes[role.unit_id, weapon.unit_id]
                distance = route.distance if route else 10000
                cost += distance if turn.is_day else max(distance, weapon.cooldown)
                if (not turn.is_day and role.pos.distance_to(weapon.pos) == 1 and weapon.cooldown == 0
                        and weapon.attack_power > 0 and any(r.health > 0 and r.pos is not None
                        and weapon.pos.distance_to(r.pos) <= weapon.attack_range for r in turn.robots)):
                    ready += 1
            value = fire_value(mapping) if fire_value is not None else 0.0
            score = (value, ready, -cost)
            if best is None or score > best[0]:
                best = score, mapping
    return best[1] if best else {}


def defensive_route(turn: Turn, nav: Navigator, role: Unit, weapon: Unit | None) -> Route | None:
    cells = neighbours(weapon.pos) if weapon and weapon.pos else build_cells(turn, 1)
    # First prefer controller cells inside the wall ring, away from robots.
    inner = tuple(p for p in cells if footprint_distance(p, base_cells(turn)) <= 1)
    return nav.route(role, inner) or nav.route(role, cells)
