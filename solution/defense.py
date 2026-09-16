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

    # The map's blue ring is distance 1 from the entire 2x2 base footprint;
    # yellow wall cells are distance 2.  Normalized threat is from positive x.
    weapon_norm = (
        Pos(xmin - 1, ymin - 1),
        Pos(xmin - 1, ymin),
        Pos(xmin - 1, ymax + 1),
        Pos(xmin, ymax + 1),
        Pos(xmax, ymin - 1),
        Pos(xmax, ymax + 1),
        Pos(xmax + 1, ymin - 1),
        Pos(xmax + 1, ymax + 1),
        Pos(xmax + 1, ymin),
        Pos(xmax + 1, ymax),
    )
    front_x = xmax + 2
    # Build the centre of the front face first, then extend it and add side
    # protection.  A partial rear face is allowed, but the two central rear
    # lanes below are never candidates for a wall.
    front_order = (mid_y, ymax, ymin, ymax + 1, ymin - 1, ymax + 2, ymin - 2)
    first_layer = tuple(Pos(front_x, y) for y in front_order)
    side_faces = tuple(
        Pos(x, y)
        for x in range(front_x - 1, xmin - 2, -1)
        for y in (ymin - 2, ymax + 2)
    )
    rear_face = tuple(Pos(xmin - 2, y) for y in (ymin - 2, ymin - 1, ymax + 1, ymax + 2))
    wall_norm = first_layer + side_faces + rear_face
    if conservative:
        wall_norm = rear_face + first_layer + side_faces

    neutral = {frame.normalize(zone.pos) for zone in turn.map_info.zones if zone.pos is not None}

    def legal_normalized(pos: Pos) -> bool:
        raw = frame.denormalize(pos)
        return turn.map_info.contains(raw) and pos not in normalized_station and pos not in neutral

    rear_lanes = (mid_y, min(mid_y + 1, ymax))
    # Two permanent OUTER gates; retain one inner passage above the railgun.
    # Reserving both inner cells previously pushed the middle gun onto a flank.
    corridor_candidates = tuple(Pos(xmin - 2, y) for y in rear_lanes) + (Pos(xmin - 1, ymax),)
    corridor_norm = tuple(pos for pos in corridor_candidates if legal_normalized(pos))
    # On an unexpectedly edge-hugging map retain a two-cell side opening.  This
    # is a compatibility fallback, not a second side-specific strategy.
    if len(corridor_norm) < 2:
        side_candidates = tuple(
            Pos(xmax, y)
            for y in (ymin - 1, ymin - 2, ymax + 1, ymax + 2)
        )
        corridor_norm = tuple(pos for pos in side_candidates if legal_normalized(pos))[:2]
    exit_norm = corridor_norm[0] if corridor_norm else None
    forbidden = set(normalized_station) | set(corridor_norm)

    unique_weapon_norm: list[Pos] = []
    for pos in weapon_norm:
        if (
            legal_normalized(pos)
            and pos not in forbidden
            and pos not in unique_weapon_norm
            and min(pos.distance_to(cell) for cell in normalized_station) == 1
        ):
            unique_weapon_norm.append(pos)
    weapon_sites = tuple(frame.denormalize(pos) for pos in unique_weapon_norm)
    unique_wall_norm: list[Pos] = []
    for pos in wall_norm:
        if legal_normalized(pos) and pos not in forbidden and pos not in unique_wall_norm:
            unique_wall_norm.append(pos)
    wall_sites = tuple(frame.denormalize(pos) for pos in unique_wall_norm)
    rear_corridor = tuple(
        frame.denormalize(pos)
        for pos in corridor_norm
        if turn.map_info.contains(frame.denormalize(pos))
    )
    controller_sites = _controller_sites(turn, weapon_sites, rear_corridor, wall_sites)
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
    wall_sites: tuple[Pos, ...] = (),
) -> tuple[Pos, ...]:
    blocked = {cell for unit in turn.team_our.roles + turn.team_enemy.roles
               if not unit.is_human for cell in unit.footprint()}
    blocked.update(zone.pos for zone in turn.map_info.zones if zone.pos is not None)
    blocked.update(weapon_sites[:3])
    blocked.update(wall_sites)
    result: list[Pos] = []
    corridor = set(rear_corridor)
    if len(weapon_sites) >= 3:
        norm = [turn.coordinate_frame.normalize(p) for p in weapon_sites[:3]]
        if len({p.x for p in norm}) == 1:
            low, middle, high = norm
            slots = (Pos(low.x-1, middle.y), Pos(middle.x, middle.y+1), Pos(high.x-1, high.y-1))
            raw = tuple(turn.coordinate_frame.denormalize(p) for p in slots)
            if len(set(raw)) == 3 and all(turn.map_info.contains(p) and p not in blocked for p in raw):
                return raw
    for weapon in weapon_sites[:3]:
        candidates = [
            pos for pos in weapon.neighbours()
            if turn.map_info.contains(pos)
            and pos not in blocked
            and pos not in result
            and pos not in corridor
        ]
        candidates.sort(
            key=lambda pos: (
                turn.coordinate_frame.normalize(pos).x,
                pos.y,
            )
        )
        if candidates:
            result.append(candidates[0])
    return tuple(result)
