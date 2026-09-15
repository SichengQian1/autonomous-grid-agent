from __future__ import annotations

from dataclasses import dataclass

from .evidence import EvidenceLevel
from .geometry import CoordinateFrame, Pos
from .models import Robot, Turn, Unit
from .rules import ROLE_WALL, WEAPON_ROLE_TYPES


@dataclass(frozen=True, slots=True)
class DefenseLayout:
    frame: CoordinateFrame
    weapon_sites: tuple[Pos, ...]
    wall_sites: tuple[Pos, ...]
    rear_exit: Pos | None
    rear_corridor: tuple[Pos, ...]
    controller_sites: tuple[Pos, ...]
    threat_evidence: EvidenceLevel


def build_defense_layout(turn: Turn, *, conservative: bool = False) -> DefenseLayout:
    station = turn.team_our.station()
    frame = turn.coordinate_frame
    if station is None or station.pos is None:
        return DefenseLayout(frame, (), (), None, (), (), EvidenceLevel.USER_OBSERVED)

    normalized_station = frame.normalize_cells(station.footprint())
    xmin = min(pos.x for pos in normalized_station)
    xmax = max(pos.x for pos in normalized_station)
    ymin = min(pos.y for pos in normalized_station)
    ymax = max(pos.y for pos in normalized_station)
    mid_y = (ymin + ymax) // 2

    # User-observed V1 relationship: normalized threat is from +x, and the fixed
    # activity opening is on -x. Exact legal build cells remain platform-unverified.
    weapon_norm = (
        Pos(xmax + 1, ymax),
        Pos(xmax + 1, mid_y),
        Pos(xmax + 1, ymin),
        Pos(xmax + 1, ymax + 1),
        Pos(xmax + 1, ymin - 1),
        Pos(xmax + 2, mid_y),
        Pos(xmax, ymax + 2),
        Pos(xmax, ymin - 2),
        Pos(xmin, ymax + 1),
        Pos(xmin, ymin - 1),
        Pos(xmin - 1, ymax + 1),
        Pos(xmin - 1, ymin - 1),
    )
    front_x = xmax + 3
    first_layer = tuple(Pos(front_x, y) for y in range(ymin - 2, ymax + 3))
    second_layer = tuple(
        Pos(front_x + 1, y) for y in range(ymin - 1, ymax + 2, 2)
    )
    side_caps = (Pos(xmax + 2, ymin - 2), Pos(xmax + 2, ymax + 2))
    wall_norm = first_layer + second_layer + side_caps
    if conservative:
        wall_norm += (
            Pos(xmin - 2, ymin - 2),
            Pos(xmin - 2, ymax + 2),
        )

    neutral = {frame.normalize(zone.pos) for zone in turn.map_info.zones if zone.pos is not None}

    def legal_normalized(pos: Pos) -> bool:
        raw = frame.denormalize(pos)
        return turn.map_info.contains(raw) and pos not in normalized_station and pos not in neutral

    exit_candidates = (
        Pos(xmin - 2, mid_y),
        Pos(xmin - 1, ymin - 2),
        Pos(xmin - 1, ymax + 2),
        Pos(xmin, ymin - 2),
        Pos(xmin, ymax + 2),
    )
    exit_norm = next((pos for pos in exit_candidates if legal_normalized(pos)), None)
    if exit_norm is None:
        corridor_norm: tuple[Pos, ...] = ()
    elif exit_norm.x < xmin:
        corridor_norm = (
            exit_norm,
            Pos(xmin - 1, mid_y),
            Pos(xmin, mid_y),
        )
    else:
        step_y = 1 if exit_norm.y < ymin else -1
        corridor_norm = (
            exit_norm,
            Pos(exit_norm.x, exit_norm.y + step_y),
        )
    forbidden = set(normalized_station) | set(corridor_norm)

    unique_weapon_norm: list[Pos] = []
    for pos in weapon_norm:
        if (
            legal_normalized(pos)
            and pos not in forbidden
            and pos not in unique_weapon_norm
        ):
            unique_weapon_norm.append(pos)
    weapon_sites = tuple(frame.denormalize(pos) for pos in unique_weapon_norm)
    wall_sites = tuple(
        frame.denormalize(pos) for pos in wall_norm if legal_normalized(pos) and pos not in forbidden
    )
    rear_corridor = tuple(
        frame.denormalize(pos)
        for pos in corridor_norm
        if turn.map_info.contains(frame.denormalize(pos))
    )
    controller_sites = _controller_sites(turn, weapon_sites, rear_corridor)
    return DefenseLayout(
        frame=frame,
        weapon_sites=weapon_sites,
        wall_sites=wall_sites,
        rear_exit=frame.denormalize(exit_norm) if exit_norm is not None else None,
        rear_corridor=rear_corridor,
        controller_sites=controller_sites,
        threat_evidence=EvidenceLevel.USER_OBSERVED,
    )


def own_threats(turn: Turn) -> tuple[Robot, ...]:
    station = turn.team_our.station()
    if station is None:
        return ()
    explicit = tuple(
        robot
        for robot in turn.robots
        if robot.health > 0 and robot.target_team == turn.team_our.team_type
    )
    if explicit:
        return explicit
    if any(robot.target_team for robot in turn.robots):
        return ()
    # Missing targetTeam: do not guess cross-map ownership. Defensively retain only
    # robots closer to our base than the map's opposite corner would be.
    footprint = station.footprint()
    return tuple(
        robot
        for robot in turn.robots
        if robot.health > 0
        and robot.pos is not None
        and min(robot.pos.distance_to(cell) for cell in footprint)
        <= max(turn.map_info.width, turn.map_info.height) // 2
    )


def existing_weapons(turn: Turn) -> tuple[Unit, ...]:
    return tuple(
        unit for unit in turn.team_our.roles if unit.role_type in WEAPON_ROLE_TYPES and unit.health > 0
    )


def existing_walls(turn: Turn) -> tuple[Unit, ...]:
    return tuple(
        unit for unit in turn.team_our.roles if unit.role_type == ROLE_WALL and unit.health > 0
    )


def estimated_contact_turns(turn: Turn, robots: tuple[Robot, ...]) -> int:
    station = turn.team_our.station()
    if station is None or not robots:
        return 12
    distances = []
    for robot in robots:
        if robot.pos is None:
            continue
        distance = min(robot.pos.distance_to(cell) for cell in station.footprint())
        distances.append(max(0, distance - max(robot.attack_range, 1)))
    return min(distances, default=12)


def _controller_sites(
    turn: Turn,
    weapon_sites: tuple[Pos, ...],
    rear_corridor: tuple[Pos, ...],
) -> tuple[Pos, ...]:
    blocked = {cell for unit in turn.team_our.roles + turn.team_enemy.roles for cell in unit.footprint()}
    blocked.update(zone.pos for zone in turn.map_info.zones if zone.pos is not None)
    result: list[Pos] = []
    corridor = set(rear_corridor)
    for weapon in weapon_sites[:3]:
        candidates = [
            pos for pos in weapon.neighbours()
            if turn.map_info.contains(pos) and pos not in blocked and pos not in result
        ]
        candidates.sort(
            key=lambda pos: (
                0 if pos in corridor else 1,
                turn.coordinate_frame.normalize(pos).x,
                pos.y,
            )
        )
        if candidates:
            result.append(candidates[0])
    return tuple(result)
