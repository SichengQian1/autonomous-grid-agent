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
from .route_safety import safe_grid, escape_intent
from dataclasses import replace
import math
from .actions import Action, ActionType
from .movement import MoveIntent
from .travel import TravelBudget
from .defense import own_threats, build_defense_layout
from .wall_access import planning_grid, return_distances, gate_sites, inside


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


def upgrade_item(target: Unit | None) -> str:
    if target is None: return ''
    prefix = {'station':'Station', 'wall':'Wall'}.get(target.role_type, 'Weapon')
    return f'{prefix}UpgradeVoucher{target.level}'


def front_walls(turn: Turn) -> list[Unit]:
    station=turn.team_our.station()
    if station is None: return []
    frame=turn.coordinate_frame
    cells=[frame.normalize(p) for p in station.footprint()]
    if not cells: return []
    front=max(p.x for p in cells)+2
    center=sum(p.y for p in cells)/len(cells)
    priority={y:rank for rank,y in enumerate((max(p.y for p in cells),min(p.y for p in cells),max(p.y for p in cells)+1,max(p.y for p in cells)+2,min(p.y for p in cells)-1,min(p.y for p in cells)-2))}
    return sorted((u for u in turn.team_our.roles if u.role_type=='wall' and u.alive and u.pos is not None and frame.normalize(u.pos).x==front),
                  key=lambda u:(priority.get(frame.normalize(u.pos).y,99),u.unit_id))


def front_wall_number(turn: Turn, wall: Unit) -> int | None:
    station = turn.team_our.station()
    if not station or not wall.pos: return None
    cells = turn.coordinate_frame.normalize_cells(station.footprint())
    pos = turn.coordinate_frame.normalize(wall.pos)
    if pos.x != max(p.x for p in cells) + 2: return None
    number = max(p.y for p in cells) + 3 - pos.y
    return number if 1 <= number <= 6 else None


def side_wall_a(turn: Turn, wall: Unit) -> bool:
    station=turn.team_our.station()
    if not station or not wall.pos:return False
    cells=turn.coordinate_frame.normalize_cells(station.footprint())
    return turn.coordinate_frame.normalize(wall.pos)==Pos(max(p.x for p in cells)+1,max(p.y for p in cells)+2)


def wall_level_goal(turn: Turn, wall: Unit) -> int:
    number=front_wall_number(turn,wall)
    if number in (1,2,3,4,5) or side_wall_a(turn,wall):return 3
    return 2


def due_defense_targets(turn: Turn, config: StrategyConfig) -> list[Unit]:
    targets=[];station=turn.team_our.station()
    if turn.day_index>=config.base_level_two_day and station and station.level<2:targets.append(station)
    if turn.day_index>=config.first_core_wall_day:
        core=[w for w in front_walls(turn) if front_wall_number(turn,w) in (2,3)]
        needed=2 if turn.day_index>=config.both_core_walls_day else 1
        missing=max(0,needed-sum(w.level>=3 for w in core))
        targets.extend(sorted((w for w in core if w.level<3),key=lambda w:(-w.level,front_wall_number(turn,w)!=3))[:missing])
    if turn.day_index>=config.both_core_walls_day:
        for w in turn.team_our.roles:
            number=front_wall_number(turn,w) if w.role_type=='wall' else None
            goal=wall_level_goal(turn,w)
            if w.role_type=='wall' and w.alive and (number or side_wall_a(turn,w)) and w.level<goal and w not in targets:
                targets.append(w)
    return targets


def scheduled_targets(turn: Turn, config: StrategyConfig) -> list[Unit]:
    """Procurement lookahead; use/repair deadlines remain based on current day."""
    from dataclasses import replace
    if turn.is_day and turn.rounds_until_night>config.procurement_lead_rounds:
        return due_defense_targets(turn,config)
    # Plan the next day's requirements before the long night/shop round trip.
    future=replace(turn,round_no=turn.day_index*130+1)
    return due_defense_targets(future,config)


def next_development_target(turn: Turn, config: StrategyConfig) -> Unit | None:
    """Weapons first until scheduled base/wall readiness becomes due."""
    if not config.protect_development_fund: return None
    due = due_defense_targets(turn, config)
    if due: return due[0]
    weapons = existing_weapons(turn)
    if len(weapons) < config.max_weapon_count: return None
    prices = {i.name:i.price for i in turn.weapon_shop}
    basic = next((w for w in sorted(weapons,key=lambda w:(w.level,w.role_type!='rocket',w.unit_id))
                  if w.level < (2 if turn.day_index<=config.ore_hold_days else 3) and (prices.get(upgrade_item(w),0)>0 or not prices)),None)
    if basic is not None: return basic
    station = turn.team_our.station()
    if station is not None and station.level < 2 and turn.day_index>config.ore_hold_days: return station
    wall = next((w for w in front_walls(turn)+[w for w in existing_walls(turn) if side_wall_a(turn,w)] if w.level < wall_level_goal(turn,w)),None)
    if wall: return wall
    return station if station is not None and station.level < 3 and turn.day_index>config.ore_hold_days else None


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


def weapon_stock_cost(turn: Turn, config: StrategyConfig) -> int:
    """Unfunded battery upgrades, discounting usable vouchers held by living roles."""
    goal=2 if turn.day_index<=config.ore_hold_days else 3
    need=Counter(f'WeaponUpgradeVoucher{level}' for w in existing_weapons(turn)
                 for level in range(max(w.level,1),goal))
    owned=Counter(item for role in turn.controllable for item in role.backpack)
    prices={item.name:item.price for item in turn.weapon_shop}
    return sum(prices.get(name,100000)*quantity for name,quantity in (need-owned).items())


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
    affordable = min(len(missing), config.max_weapon_count-len(weapons), turn.team_our.gold // config.weapon_build_cost)
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
    if worker.backpack.count('stone')<=1 and inside(turn,worker.pos) and any(w.pos in gate_sites(turn,config) for w in existing_walls(turn)):
        return None
    standing = {wall.pos for wall in existing_walls(turn)}
    occupied = {
        cell for unit in turn.team_our.roles + turn.team_enemy.roles for cell in unit.footprint()
    }
    reserved = reserved_sites or set()
    grid = planning_grid(turn,worker,config)
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
            and wall_preserves_access(turn, layout, site, reserved,config)
        ):
            return BuildObjective(ROLE_WALL, site, 70 - index)
    return None


def wall_preserves_access(turn: Turn, layout: DefenseLayout, site: Pos, reserved: set[Pos],config=None) -> bool:
    """Reject a wall that seals a control cell or a living role into a pocket."""
    if layout.rear_exit is None:
        return False
    grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
    blocked = grid.blocked | set(layout.weapon_sites[:3]) | reserved | {site}
    if config:blocked-=set(gate_sites(turn,config))
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
    evidence: dict[int, dict] = field(default_factory=dict)
    previous_robots: dict = field(default_factory=dict)
    returning_roles: set[int] = field(default_factory=set)
    reserve_stone: dict[int, int] = field(default_factory=dict)
    main_miner_id: int | None = None

    def plan(self, turn: Turn, worker: Unit, state: WorldState, config: StrategyConfig, budget: DefenseBudget) -> EconomyPlan:
        if worker.pos is None:
            return EconomyPlan()
        travel = TravelBudget.for_role(turn,worker,config,wall_support=worker.unit_id in self.returning_roles,
                                       worker_refuge=worker.unit_id not in self.returning_roles)
        grid,danger=safe_grid(turn,config,self.previous_robots)
        grid=planning_grid(turn,worker,config,grid)
        travel.grid=grid
        if travel.daytime:travel.home=return_distances(turn,grid,travel.goals,config)
        threats=tuple(r for r in turn.robots if r.health>0) if not turn.is_day else ()
        self.evidence[worker.unit_id]={'danger_cells':len(danger),'return_required':travel.daytime,'day_three_release':turn.day_index==3}
        if worker.pos in danger:
            self.activity[worker.unit_id]='retreat_from_robot'
            return EconomyPlan(move=escape_intent(turn,worker,config,danger))
        if turn.is_day and travel.cost()+travel.margin>=travel.remaining:
            self.activity[worker.unit_id]='worker_safety_return'
            return EconomyPlan(move=MoveIntent(worker.unit_id,travel.goals,119))
        if 'Medicine' in worker.backpack and worker.health<=config.worker_heal_health:
            self.activity[worker.unit_id]='worker_recovery'
            return EconomyPlan(action=Action(worker.unit_id,ActionType.USE,name='Medicine'))
        if not turn.is_day and state.night_role_pauses.get(worker.unit_id,0)>turn.round_no:
            self.activity[worker.unit_id]='bounded_night_failure_pause'
            return EconomyPlan()
        vendor_goals = tuple(p for v in turn.zone_positions("vendor") for p in interaction_cells(grid,v))
        home=turn.team_our.station()
        prices={item.name:item.price for item in turn.vendor_shop}
        inventory=resource_inventory(worker)
        inventory["stone"]=max(0,inventory["stone"]-self.reserve_stone.get(worker.unit_id,0))
        inventory=+inventory;count=sum(inventory.values())
        value=sum(prices.get(n,0)*qty for n,qty in inventory.items())
        developed=bool(home and home.level>=2 and len(existing_weapons(turn))==3
                       and all(w.level>=2 for w in existing_weapons(turn)))
        hoarding=turn.day_index<=config.ore_hold_days
        can_wait=(hoarding or developed) and turn.team_our.gold>=config.treasure_gold_reserve and budget.margin>3
        rising=can_wait and any(state.market.will_rise(n,turn.day_index) for n in inventory)
        development=next_development_target(turn,config)
        item=upgrade_item(development)
        cash_goal=next((i.price for i in turn.weapon_shop if i.name==item),100)
        if development is None and any(w.role_type=="rocket" and w.level>=2 for w in existing_weapons(turn)):
            cash_goal+=budget.emergency
        # One miner's actual sale must close the gap. Counting everybody's stock
        # sent several workers on tiny sales that did not fund the purchase.
        owned_upgrade=bool(item) and any(item in r.backpack for r in turn.controllable)
        urgent_cash=not owned_upgrade and turn.team_our.gold<cash_goal<=turn.team_our.gold+value
        if development is not None and not owned_upgrade and turn.team_our.gold<cash_goal:
            can_wait=False
            rising=False
        sale_stops=((vendor_goals,max(len(inventory),1)),)
        sale_cost=travel.cost(sale_stops)
        can_sell=bool(vendor_goals) and count>0 and sale_cost<10000 and travel.fits(sale_stops)
        sale_rate=value/max(sale_cost,1)
        if not count: self.selling.discard(worker.unit_id)
        previous_pos=self.mines.get(worker.unit_id)
        depleted=previous_pos is not None and not any(z.pos==previous_pos for z in turn.map_info.zones)
        ranked=[]
        for zone in turn.map_info.zones:
            if zone.pos is None or zone.neutral_type not in RESOURCE_ZONE_TYPES or state.market.closed(zone.neutral_type,turn.day_index):
                continue
            goals=interaction_cells(grid,zone.pos)
            if threats:goals=tuple(p for p in goals if p not in danger)
            if not goals:continue
            price=state.market.expected_price(zone.neutral_type,prices.get(zone.neutral_type,0),turn.day_index,can_wait=can_wait,horizon=max(1,config.ore_hold_days+1-turn.day_index) if hoarding else 1)
            if can_wait and state.market.will_rise(zone.neutral_type,turn.day_index):price*=config.market_forecast_weight
            capacity=max(0,worker.backpack_capacity-len(worker.backpack))
            remaining=max(0,state.mine_remaining.get(zone.pos,10))
            batch=min(config.mining_batch_size,remaining,capacity)
            sale_actions=len(set(inventory)|{zone.neutral_type})
            # Value the eventual complete trip, but only require collection and
            # defensive return to fit today. Selling may wait until a safe window.
            work_cost=travel.cost(((goals,0),))
            if work_cost>=10000:continue
            if travel.daytime:batch=min(batch,max(0,travel.remaining-travel.margin-work_cost-1))
            if batch<=0:continue
            base_cost=travel.cost(((goals,0),(vendor_goals,sale_actions))) if vendor_goals else 10000
            cost=(work_cost+max(4,len(inventory)+1) if base_cost>=10000 else base_cost)+batch
            rate=(value+price*batch)/max(cost,1)
            if zone.pos in {p for actor,p in self.mines.items() if actor!=worker.unit_id}:rate*=0.8
            ranked.append((rate,zone,goals))
        # Only the main miner on day two follows a supported future-price
        # opportunity. Safety, reachable paths and capacity still gate candidates.
        if turn.day_index==1 and worker.unit_id==self.main_miner_id:
            income_ores=[entry for entry in ranked if entry[1].neutral_type in ('iron','copper')]
            if income_ores:ranked=income_ores
        forecast=set()
        if turn.day_index==2 and worker.unit_id==self.main_miner_id:
            for window in state.market.windows:
                if window.source_day==2 and window.start_day>=3 and window.end_day>=3 and not window.recovery and (window.rising or window.closed or (window.price or 0)>prices.get(window.ore,0)):
                    forecast.add(window.ore)
            preferred=[entry for entry in ranked if entry[1].neutral_type in forecast]
            if preferred:
                ranked=preferred
                self.evidence[worker.unit_id]['day_two_forecast']=sorted(forecast)
                self.evidence[worker.unit_id]['forecast_basis']='current_news_price_or_supply_window_not_guaranteed_sale_price'
        best=max(ranked,key=lambda item:(item[0],-item[1].pos.x,-item[1].pos.y),default=None)
        should_sell=can_sell and (worker.unit_id in self.selling or backpack_full(worker)
            or (not rising and (count>=config.mining_batch_size or worker.pos in vendor_goals or urgent_cash
                or (depleted and count>=config.mining_minimum_batch) or best is None or sale_rate>=best[0])))
        quantity_limit=None
        if hoarding:
            # Early cash is for actual minimum defense deficits, not ordinary
            # level-three development. Stock already carried counts as funded.
            owned=Counter(i for r in turn.controllable for i in r.backpack)
            shop={i.name:i.price for i in turn.weapon_shop}
            weapons=existing_weapons(turn)
            missing=max(0,config.max_weapon_count-len(weapons))
            basic=max(0,sum(w.level<2 for w in weapons)+missing-owned['WeaponUpgradeVoucher1'])
            need=missing*config.weapon_build_cost+basic*shop.get('WeaponUpgradeVoucher1',100)
            # Give normal first-day task income time to arrive; later shortfalls
            # and a damaged base justify a bounded emergency conversion.
            base=turn.team_our.station()
            crisis=bool(base and base.health<500)
            abnormal=(turn.day_index==2 or turn.rounds_until_night<=20 or crisis)
            gap=max(0,need-turn.team_our.gold) if abnormal else 0
            should_sell=can_sell and (gap>0 or crisis)
            self.evidence[worker.unit_id].update(hold=True,defense_gap=gap,crisis=crisis,full=backpack_full(worker))
            if should_sell:
                quantity_limit=max(1,gap)  # Converted to units at actual price below.
                self.activity[worker.unit_id]='emergency_defense_sale'
            elif backpack_full(worker) and can_sell:
                # Explicit user-approved capacity exception: one small working
                # batch only, then return to hoarding instead of draining the bag.
                should_sell=True
                quantity_limit=-min(config.mining_minimum_batch,count)
                self.activity[worker.unit_id]='capacity_minimum_sale'
            elif backpack_full(worker):
                self.activity[worker.unit_id]='hoard_full_no_safe_vendor'
                return EconomyPlan()
            else:self.selling.discard(worker.unit_id)
        if should_sell:
            self.selling.add(worker.unit_id);self.mines.pop(worker.unit_id,None)
            if not hoarding:self.activity[worker.unit_id]="sell_batch"
            if worker.pos in vendor_goals:
                name=max(inventory,key=lambda n:(prices.get(n,0)*inventory[n],n))
                return EconomyPlan(action=Action(worker.unit_id,ActionType.SELL,name=name,quantity=min(inventory[name],(-quantity_limit if quantity_limit<0 else math.ceil(quantity_limit/max(prices.get(name,0),1)))) if quantity_limit is not None else inventory[name]))
            return EconomyPlan(move=MoveIntent(worker.unit_id,vendor_goals,35,avoid_cells=danger))
        if best is None:
            self.mines.pop(worker.unit_id,None)
            self.activity[worker.unit_id]="no_complete_income_trip"
            return EconomyPlan(move=MoveIntent(worker.unit_id,travel.goals,30)) if turn.is_day else EconomyPlan()
        previous=next((item for item in ranked if item[1].pos==previous_pos),None)
        if previous is not None and previous[0]*1.2>=best[0]:best=previous
        rate,zone,goals=best;self.mines[worker.unit_id]=zone.pos
        self.evidence[worker.unit_id].update(rate=round(rate,3),target=[zone.pos.x,zone.pos.y],ore=zone.neutral_type,held=hoarding,route="safe_collection_then_sale",vendor_reachable=bool(vendor_goals),return_cost=travel.cost(((goals,1),)))
        if worker.pos.distance_to(zone.pos)<=1:
            self.activity[worker.unit_id]="collect_"+zone.neutral_type
            return EconomyPlan(action=Action(worker.unit_id,ActionType.COLLECT,targets=(zone.pos,)))
        self.activity[worker.unit_id]="travel_"+zone.neutral_type
        return EconomyPlan(move=MoveIntent(worker.unit_id,goals,30,avoid_cells=danger))
