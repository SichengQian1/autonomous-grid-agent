from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .defense import DefenseLayout, existing_walls, existing_weapons
from .geometry import Pos
from .models import Turn, Unit, Zone
from .rules import RESOURCE_ZONE_TYPES, ROLE_WALL, StrategyConfig
from .state import WorldState


@dataclass(frozen=True, slots=True)
class DefenseBudget:
    mandatory: int
    emergency: int
    offensive: int
    margin: int


@dataclass(frozen=True, slots=True)
class BuildObjective:
    name: str
    site: Pos
    priority: int


def defense_budget(
    turn: Turn,
    config: StrategyConfig,
    threat_health: int = 0,
    contact_turns: int = 12,
) -> DefenseBudget:
    weapons = existing_weapons(turn)
    missing = max(0, config.max_weapon_count - len(weapons))
    mandatory = missing * config.weapon_build_cost
    station = turn.team_our.station()
    damaged_key_structures = sum(
        1
        for unit in (station,) + weapons
        if unit is not None and unit.health > 0 and unit.health < 500
    )
    emergency = config.emergency_gold_reserve * (1 + damaged_key_structures)
    estimated_dps = sum(max(weapon.attack_power, 10) for weapon in weapons)
    clear_turns = (threat_health + max(estimated_dps, 1) - 1) // max(estimated_dps, 1)
    margin = max(0, contact_turns) - clear_turns
    reserved = mandatory + emergency
    offensive = max(0, turn.team_our.gold - reserved)
    return DefenseBudget(mandatory, emergency, offensive, margin)


def weapon_build_objectives(
    turn: Turn,
    layout: DefenseLayout,
    state: WorldState,
    config: StrategyConfig,
) -> tuple[BuildObjective, ...]:
    weapons = existing_weapons(turn)
    if len(weapons) >= config.max_weapon_count:
        return ()
    counts = Counter(weapon.role_type for weapon in weapons)
    missing: list[str] = []
    for name in config.primary_weapon_loadout:
        if counts[name] > 0:
            counts[name] -= 1
        else:
            missing.append(name)
    if not missing or turn.team_our.gold < config.weapon_build_cost:
        return ()

    occupied = {
        cell for unit in turn.team_our.roles + turn.team_enemy.roles for cell in unit.footprint()
    }
    occupied.update(zone.pos for zone in turn.map_info.zones if zone.pos is not None)
    available = [
        site
        for site in layout.weapon_sites
        if site not in occupied and site not in state.failed_build_sites
    ]
    affordable = min(len(missing), turn.team_our.gold // config.weapon_build_cost)
    return tuple(
        BuildObjective(name, site, 100 - index)
        for index, (name, site) in enumerate(zip(missing[:affordable], available))
    )


def wall_build_objective(
    turn: Turn,
    worker: Unit,
    layout: DefenseLayout,
    state: WorldState,
    config: StrategyConfig,
    reserved_sites: set[Pos] | None = None,
) -> BuildObjective | None:
    if worker.backpack.count("stone") <= 0 or len(existing_walls(turn)) >= config.max_wall_count:
        return None
    standing = {wall.pos for wall in existing_walls(turn)}
    occupied = {
        cell for unit in turn.team_our.roles + turn.team_enemy.roles for cell in unit.footprint()
    }
    reserved = reserved_sites or set()
    for index, site in enumerate(layout.wall_sites):
        if (
            site not in standing
            and site not in occupied
            and site not in state.failed_build_sites
            and site not in reserved
        ):
            return BuildObjective(ROLE_WALL, site, 70 - index)
    return None


def resource_value(turn: Turn, zone: Zone, worker: Unit) -> float:
    if zone.pos is None or zone.neutral_type not in RESOURCE_ZONE_TYPES or worker.pos is None:
        return float("-inf")
    price = next(
        (item.price for item in turn.vendor_shop if item.name == zone.neutral_type),
        0,
    )
    distance = worker.pos.distance_to(zone.pos)
    vendor_distance = min(
        (zone.pos.distance_to(vendor) for vendor in turn.zone_positions("vendor")),
        default=distance,
    )
    station = turn.team_our.station()
    return_distance = zone.pos.distance_to(station.pos) if station is not None and station.pos is not None else 0
    recall_penalty = return_distance if turn.is_day and turn.rounds_until_night <= return_distance + 8 else 0
    stone_bonus = 5 if zone.neutral_type == "stone" and worker.backpack.count("stone") < 4 else 0
    return price * 8 + stone_bonus - distance - 0.5 * vendor_distance - recall_penalty


def best_resource(turn: Turn, worker: Unit) -> Zone | None:
    candidates = [
        zone for zone in turn.map_info.zones
        if zone.pos is not None and zone.neutral_type in RESOURCE_ZONE_TYPES
    ]
    return max(candidates, key=lambda zone: resource_value(turn, zone, worker), default=None)


def resource_inventory(worker: Unit) -> Counter[str]:
    return Counter(item for item in worker.backpack if item in RESOURCE_ZONE_TYPES)


def backpack_full(worker: Unit) -> bool:
    return worker.backpack_capacity > 0 and len(worker.backpack) >= worker.backpack_capacity
