from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .defense import DefenseLayout, existing_walls, existing_weapons
from .geometry import Pos
from .models import Turn, Unit, Zone
from .rules import RESOURCE_ZONE_TYPES, ROLE_WALL, StrategyConfig
from .state import WorldState
from .grid import OccupancyGrid, distance_field
from .grid import interaction_cells
from .actions import Action, ActionType
from .movement import MoveIntent


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
        cell for unit in turn.team_our.roles + turn.team_enemy.roles
        if not unit.is_human for cell in unit.footprint()
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
    grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
    distances = distance_field(grid,(worker.pos,)) if worker.pos is not None else {}
    station = turn.team_our.station()
    front = max((layout.frame.normalize(p).x for p in station.footprint()),default=0)+2 if station else 0
    def order(item):
        index,site = item
        travel = min((distances.get(p,10000) for p in interaction_cells(grid,site)),default=10000)
        # Complete the front first, then nearby side walls without zigzagging
        # between opposite faces after every stone.
        return (0 if layout.frame.normalize(site).x == front else 1,travel,index)
    for index, site in sorted(enumerate(layout.wall_sites),key=order):
        if (
            site not in standing
            and site not in occupied
            and site not in state.failed_build_sites
            and site not in reserved
            and any(p in distances for p in interaction_cells(grid,site))
            and wall_preserves_access(turn, layout, site, reserved)
        ):
            return BuildObjective(ROLE_WALL, site, 70 - index)
    return None


def wall_preserves_access(turn: Turn, layout: DefenseLayout, site: Pos, reserved: set[Pos]) -> bool:
    """Reject a wall that seals a control cell or a living role into a pocket."""
    if layout.rear_exit is None:
        return False
    grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
    blocked = grid.blocked | set(layout.weapon_sites[:3]) | reserved | {site}
    reachable = distance_field(OccupancyGrid(grid.width, grid.height, frozenset(blocked)), (layout.rear_exit,))
    required = list(layout.controller_sites)
    required.extend(r.pos for r in turn.controllable if r.pos is not None and r.pos not in blocked)
    return all(p in reachable for p in required)


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


@dataclass(frozen=True, slots=True)
class EconomyPlan:
    action: Action | None = None
    move: MoveIntent | None = None


@dataclass(slots=True)
class EconomyManager:
    mines: dict[int, Pos] = field(default_factory=dict)
    selling: set[int] = field(default_factory=set)
    activity: dict[int, str] = field(default_factory=dict)

    def plan(self, turn: Turn, worker: Unit, state: WorldState, config: StrategyConfig, budget: DefenseBudget) -> EconomyPlan:
        if worker.pos is None:
            return EconomyPlan()
        grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
        distances = distance_field(grid, (worker.pos,))
        vendor_goals = tuple(p for v in turn.zone_positions("vendor") for p in interaction_cells(grid, v))
        vendor_distance = min((distances.get(p, 10000) for p in vendor_goals), default=10000)
        home = turn.team_our.station()
        home_goals = tuple(p for c in home.footprint() for p in interaction_cells(grid, c)) if home else ()
        home_distance = min((distances.get(p, 10000) for p in home_goals), default=10000)
        prices = {item.name: item.price for item in turn.vendor_shop}
        inventory = resource_inventory(worker)
        count = sum(inventory.values())
        value = sum(prices.get(name, 0) * n for name, n in inventory.items())
        # Hoarding is allowed only after basic defense and working capital exist.
        developed = bool(home and home.level >= 2 and len(existing_weapons(turn)) == 3
                         and all(w.level >= 2 for w in existing_weapons(turn)))
        can_wait = developed and turn.team_our.gold >= config.treasure_gold_reserve and budget.margin > 3
        rising = any((can_wait and state.market.will_rise(n,turn.day_index)) or state.market.expected_price(n, prices.get(n, 0), turn.day_index, can_wait=can_wait) > prices.get(n, 0)
                     for n in inventory)
        urgent_cash = turn.team_our.gold < 100 + budget.emergency <= turn.team_our.gold + value
        near_dusk = turn.is_day and turn.rounds_until_night <= vendor_distance + home_distance + config.recall_safety_buffer + 2
        if count == 0:
            self.selling.discard(worker.unit_id)
        if count and (backpack_full(worker) or worker.unit_id in self.selling
                      or (not rising and (count >= config.mining_batch_size
                          or (count >= config.mining_minimum_batch and (urgent_cash or near_dusk))
                          or vendor_distance == 0))):
            if vendor_distance < 10000:
                self.selling.add(worker.unit_id)
                self.activity[worker.unit_id] = "sell_batch"
                if vendor_distance == 0:
                    name = max(inventory, key=lambda n: (prices.get(n, 0)*inventory[n], n))
                    return EconomyPlan(action=Action(worker.unit_id, ActionType.SELL, name=name, quantity=inventory[name]))
                return EconomyPlan(move=MoveIntent(worker.unit_id, vendor_goals, 35))
        vendor_map = distance_field(grid, vendor_goals)
        ranked = []
        for zone in turn.map_info.zones:
            if zone.pos is None or zone.neutral_type not in RESOURCE_ZONE_TYPES or state.market.closed(zone.neutral_type, turn.day_index):
                continue
            goals = interaction_cells(grid, zone.pos)
            travel = min((distances.get(p, 10000) for p in goals), default=10000)
            sell_travel = min((vendor_map.get(p, 10000) for p in goals), default=10000)
            if travel >= 10000 or sell_travel >= 10000:
                continue
            price = state.market.expected_price(zone.neutral_type, prices.get(zone.neutral_type, 0), turn.day_index, can_wait=can_wait)
            if can_wait and state.market.will_rise(zone.neutral_type,turn.day_index):
                price *= config.market_forecast_weight
            batch = max(1, min(config.mining_batch_size, worker.backpack_capacity-len(worker.backpack)))
            rate = price * batch / (travel + batch + sell_travel + 1)
            if zone.pos in {p for actor,p in self.mines.items() if actor != worker.unit_id}:
                rate *= 0.8
            ranked.append((rate, zone, goals))
        if not ranked:
            self.activity[worker.unit_id] = "no_reachable_mine"
            return EconomyPlan()
        best = max(ranked, key=lambda item: (item[0], -item[1].pos.x, -item[1].pos.y))
        previous = next((item for item in ranked if item[1].pos == self.mines.get(worker.unit_id)), None)
        if previous is not None and previous[0] * 1.4 >= best[0]:
            best = previous
        _, zone, goals = best
        self.mines[worker.unit_id] = zone.pos
        if worker.pos.distance_to(zone.pos) <= 1:
            self.activity[worker.unit_id] = "collect_" + zone.neutral_type
            return EconomyPlan(action=Action(worker.unit_id, ActionType.COLLECT, targets=(zone.pos,)))
        self.activity[worker.unit_id] = "travel_" + zone.neutral_type
        return EconomyPlan(move=MoveIntent(worker.unit_id, goals, 30))
