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
from .travel import TravelBudget


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


def next_development_target(turn: Turn, config: StrategyConfig) -> Unit | None:
    """Protect one permanent defensive improvement from incidental spending."""
    if not config.protect_development_fund:
        return None
    weapons=existing_weapons(turn)
    if len(weapons)<config.max_weapon_count:
        return None
    rockets=sorted((w for w in weapons if w.role_type=="rocket"),key=lambda w:w.unit_id)
    if rockets and not any(w.level>=2 for w in rockets):
        return rockets[0]
    station=turn.team_our.station()
    if station is not None and station.level==1 and turn.day_index>=2:
        return station
    return next(iter(sorted((w for w in weapons if w.level==1),
                            key=lambda w:(w.role_type!="rocket",w.unit_id))),None)


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
        travel = TravelBudget.for_role(turn,worker,config)
        grid = travel.grid
        vendor_goals = tuple(p for v in turn.zone_positions("vendor") for p in interaction_cells(grid,v))
        if not vendor_goals:
            self.activity[worker.unit_id]="no_vendor_route"
            return EconomyPlan()
        home=turn.team_our.station()
        prices={item.name:item.price for item in turn.vendor_shop}
        inventory=resource_inventory(worker);count=sum(inventory.values())
        value=sum(prices.get(n,0)*qty for n,qty in inventory.items())
        developed=bool(home and home.level>=2 and len(existing_weapons(turn))==3
                       and all(w.level>=2 for w in existing_weapons(turn)))
        can_wait=developed and turn.team_our.gold>=config.treasure_gold_reserve and budget.margin>3
        rising=can_wait and any(state.market.will_rise(n,turn.day_index) for n in inventory)
        development=next_development_target(turn,config)
        item="StationUpgradeVoucher1" if development and development.role_type=="station" else "WeaponUpgradeVoucher1"
        cash_goal=next((i.price for i in turn.weapon_shop if i.name==item),100)
        if development is None and any(w.role_type=="rocket" and w.level>=2 for w in existing_weapons(turn)):
            cash_goal+=budget.emergency
        team_stock=sum(prices.get(item,0) for r in turn.controllable for item in r.backpack)
        urgent_cash=turn.team_our.gold<cash_goal<=turn.team_our.gold+team_stock
        sale_stops=((vendor_goals,max(len(inventory),1)),)
        sale_cost=travel.cost(sale_stops)
        can_sell=count>0 and travel.fits(sale_stops)
        sale_rate=value/max(sale_cost,1)
        if not count: self.selling.discard(worker.unit_id)
        previous_pos=self.mines.get(worker.unit_id)
        depleted=previous_pos is not None and not any(z.pos==previous_pos for z in turn.map_info.zones)
        ranked=[]
        for zone in turn.map_info.zones:
            if zone.pos is None or zone.neutral_type not in RESOURCE_ZONE_TYPES or state.market.closed(zone.neutral_type,turn.day_index):
                continue
            if config.local_mining_only and turn.coordinate_frame.normalize(zone.pos).x>(turn.map_info.width-1)//2:
                continue
            goals=interaction_cells(grid,zone.pos)
            price=state.market.expected_price(zone.neutral_type,prices.get(zone.neutral_type,0),turn.day_index,can_wait=can_wait)
            if can_wait and state.market.will_rise(zone.neutral_type,turn.day_index):price*=config.market_forecast_weight
            capacity=max(0,worker.backpack_capacity-len(worker.backpack))
            remaining=max(1,state.mine_remaining.get(zone.pos,10))
            batch=min(config.mining_batch_size,remaining,capacity)
            sale_actions=len(set(inventory)|{zone.neutral_type})
            base_cost=travel.cost(((goals,0),(vendor_goals,sale_actions)))
            if travel.daytime:batch=min(batch,max(0,travel.remaining-travel.margin-base_cost-1))
            if batch<=0:continue
            cost=base_cost+batch
            if cost>=10000:continue
            rate=(value+price*batch)/max(cost,1)
            if zone.pos in {p for actor,p in self.mines.items() if actor!=worker.unit_id}:rate*=0.8
            ranked.append((rate,zone,goals))
        best=max(ranked,key=lambda item:(item[0],-item[1].pos.x,-item[1].pos.y),default=None)
        should_sell=can_sell and (worker.unit_id in self.selling or backpack_full(worker)
            or (not rising and (count>=config.mining_batch_size or worker.pos in vendor_goals or urgent_cash
                or (depleted and count>=config.mining_minimum_batch) or best is None or sale_rate>=best[0])))
        if should_sell:
            self.selling.add(worker.unit_id);self.mines.pop(worker.unit_id,None)
            self.activity[worker.unit_id]="sell_batch"
            if worker.pos in vendor_goals:
                name=max(inventory,key=lambda n:(prices.get(n,0)*inventory[n],n))
                return EconomyPlan(action=Action(worker.unit_id,ActionType.SELL,name=name,quantity=inventory[name]))
            return EconomyPlan(move=MoveIntent(worker.unit_id,vendor_goals,35))
        if best is None:
            self.mines.pop(worker.unit_id,None)
            self.activity[worker.unit_id]="no_complete_income_trip"
            return EconomyPlan()
        previous=next((item for item in ranked if item[1].pos==previous_pos),None)
        if previous is not None and previous[0]*1.2>=best[0]:best=previous
        _,zone,goals=best;self.mines[worker.unit_id]=zone.pos
        if worker.pos.distance_to(zone.pos)<=1:
            self.activity[worker.unit_id]="collect_"+zone.neutral_type
            return EconomyPlan(action=Action(worker.unit_id,ActionType.COLLECT,targets=(zone.pos,)))
        self.activity[worker.unit_id]="travel_"+zone.neutral_type
        return EconomyPlan(move=MoveIntent(worker.unit_id,goals,30))
