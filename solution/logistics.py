from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter

from .actions import Action, ActionType
from .economy import DefenseBudget, next_development_target, upgrade_item, front_walls, due_defense_targets, wall_level_goal
from .models import Turn, Unit
from .movement import MoveIntent
from .grid import OccupancyGrid, distance_field, interaction_cells
from .travel import TravelBudget
from .rules import (
    DEFAULT_CONFIG,
    ROLE_RAILGUN,
    ROLE_ROCKET,
    ROLE_STATION,
    ROLE_WALL,
    WEAPON_ROLE_TYPES,
    StrategyConfig,
)


@dataclass(frozen=True, slots=True)
class LogisticsPlan:
    action: Action | None = None
    move: MoveIntent | None = None


# Runtime payloads do not expose maxHealth. These values only rank choices and
# remain replaceable after platform logs provide better evidence.
_MAX_HEALTH = {
    ROLE_STATION: (0, 1500, 3000, 4500),
    ROLE_WALL: (0, 1000, 1500, 2000),
    ROLE_RAILGUN: (0, 1000, 1500, 2000),
    ROLE_ROCKET: (0, 1000, 1500, 2000),
    "gatling": (0, 1000, 1500, 2000),
}


def estimated_max_health(unit: Unit) -> int:
    values = _MAX_HEALTH.get(unit.role_type, (0, max(unit.health, 1)))
    index = min(max(unit.level, 1), len(values) - 1)
    return max(values[index], unit.health, 1)


def critically_damaged(unit: Unit) -> bool:
    return unit.health * (3 if unit.role_type == ROLE_WALL else 2) < estimated_max_health(unit)


def upgrade_value(turn: Turn, target: Unit) -> int:
    """Rank an upgrade including its user-observed full-heal value."""

    if target.level not in {1, 2}:
        return -1
    missing_health = max(0, estimated_max_health(target) - target.health)
    if target.role_type == ROLE_ROCKET:
        combat = 4200 if target.level == 2 else 1900
    elif target.role_type == ROLE_RAILGUN:
        combat = 1800 if target.level == 1 else 900
    elif target.role_type == ROLE_STATION:
        combat = 1500 + 250 * turn.day_index
    elif target.role_type == ROLE_WALL:
        combat = 350
    else:
        combat = 800
    return combat + missing_health * 2


@dataclass(frozen=True, slots=True)
class Delivery:
    item: str
    target_id: int
    level: int


@dataclass(slots=True)
class LogisticsManager:
    carrier_id: int | None = None
    orders: list[Delivery] = field(default_factory=list)
    started: int = 0
    stage: str = "idle"
    retry_after: dict[int, int] = field(default_factory=dict)

    def plan(self, turn: Turn, role: Unit, budget: DefenseBudget, config: StrategyConfig) -> LogisticsPlan:
        if role.pos is None:
            return LogisticsPlan()
        if self.carrier_id is not None:
            carrier = turn.team_our.unit(self.carrier_id)
            if carrier is None or not carrier.alive or turn.round_no-self.started > config.logistics_trip_limit:
                if carrier is None or not any(i=="WallFixer" or "UpgradeVoucher" in i for i in carrier.backpack):
                    self.retry_after[self.carrier_id] = turn.round_no+5
                self.carrier_id, self.orders, self.stage = None, [], "expired"
        if self.carrier_id is not None and self.carrier_id != role.unit_id:
            # Procurement ownership cannot strand goods already carried by another role.
            return plan_upgrade_or_repair(turn, role, budget, config, allow_move=True, owned_only=True)
        if self.retry_after.get(role.unit_id, 0) > turn.round_no:
            return LogisticsPlan()
        grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
        distances = distance_field(grid, (role.pos,))
        def goals(target):
            # The wire action addresses the building anchor, including a 2x2 base.
            return interaction_cells(grid, target.pos)
        def distance(target):
            return min((distances.get(p,10000) for p in goals(target)),default=10000)
        options = _maintenance_options(turn,config)
        due_ids = {u.unit_id for u in due_defense_targets(turn,config)}
        first_rocket = any(u.role_type == ROLE_ROCKET and u.level >= 2 and u.alive for u in turn.team_our.roles)
        if not first_rocket:
            # Fund the first power increase before buying optional small items.
            options = [o for o in options if o[0] in role.backpack or critically_damaged(o[1])
                       or o[1].unit_id in due_ids or (o[1].role_type == ROLE_ROCKET and o[1].level == 1)]
        development=next_development_target(turn,config)
        development_id=development.unit_id if development else None
        development_item=upgrade_item(development)
        owned_development=any(development_item in r.backpack for r in turn.controllable)
        reserve=next((i.price for i in turn.weapon_shop if i.name==development_item),0) if development and not owned_development else 0
        first_levels = any(u.is_weapon and u.level == 1 for u in turn.team_our.roles)
        def value(option):
            name,target,score = option
            if target.unit_id in due_ids: score += 60000
            if target.unit_id==development_id: score += 50000
            if first_levels and target.is_weapon and target.level == 1: score += 3000
            if name == "WallFixer" and target.health < estimated_max_health(target)//3: score += 3000
            if target.role_type != ROLE_WALL and critically_damaged(target): score += 6000
            if critically_damaged(target): score += 200000
            return score - distance(target)*20
        if due_ids:
            # Do not spend the deadline basket on another weapon or base level 3.
            # Carried off-duty vouchers must not pin a pre-deadline shopping order.
            options = [o for o in options if o[1].unit_id in due_ids or critically_damaged(o[1])]
        options = [o for o in options if not (turn.is_day and o[1].role_type == ROLE_WALL
                   and o[1].unit_id not in due_ids and o[0] in role.backpack
                   and o[1].health > estimated_max_health(o[1])*config.wall_heal_fraction)]
        options = sorted((o for o in options if distance(o[1]) < 10000), key=value, reverse=True)
        self.orders = [order for order in self.orders if any(
            name == order.item and target.unit_id == order.target_id and target.level == order.level
            for name,target,_ in options)]
        if not self.orders:
            self.carrier_id = None
            # Inventory is authoritative. A voucher from an interrupted trip gets a new destination.
            carried = [(name,target) for name,target,_ in options if name in role.backpack]
            if carried:
                name,target = carried[0]
                self.orders = [Delivery(name,target.unit_id,target.level)]
            else:
                prices = {i.name:i.price for i in turn.weapon_shop}
                committed = 0
                owned = Counter(item for r in turn.controllable for item in r.backpack)
                for name,target,_ in options:
                    if any(o.target_id == target.unit_id for o in self.orders): continue
                    if owned[name]:
                        owned[name] -= 1
                        continue
                    price = prices.get(name,0)
                    urgent = critically_damaged(target) or target.unit_id in due_ids or target.unit_id==development_id or (not first_rocket and target.role_type == ROLE_ROCKET)
                    allowance = max(budget.offensive, turn.team_our.gold-budget.mandatory) if urgent else budget.offensive
                    if not urgent and not any(o.target_id==development_id for o in self.orders):
                        allowance=max(0,allowance-reserve)
                    if 0 < price <= allowance-committed and len(self.orders) < 3:
                        self.orders.append(Delivery(name,target.unit_id,target.level))
                        committed += price
                if not self.orders:
                    self.stage = "unfunded"
                    return LogisticsPlan()
            self.carrier_id, self.started = role.unit_id, turn.round_no
        # Purchased weapon vouchers travel with the role until defensive recall.
        # Release courier ownership so holding a voucher does not stop production.
        if config.defer_weapon_delivery and turn.is_day and any(o.item.startswith('WeaponUpgradeVoucher') and o.item in role.backpack for o in self.orders):
            held=next(o for o in self.orders if o.item.startswith('WeaponUpgradeVoucher') and o.item in role.backpack)
            target=turn.team_our.unit(held.target_id)
            if target and distance(target)==0:
                self.orders=[];self.carrier_id=None;self.stage='use_on_route'
                return LogisticsPlan(action=Action(role.unit_id,ActionType.USE,name=held.item,targets=(target.pos,)))
            self.orders=[];self.carrier_id=None;self.stage='carry_until_recall'
            return LogisticsPlan()
        if turn.is_day and any(o.item in role.backpack and (o.item=='WallFixer' or o.item.startswith('WallUpgradeVoucher')) for o in self.orders):
            owned=next(o for o in self.orders if o.item in role.backpack)
            target=turn.team_our.unit(owned.target_id)
            if target and target.unit_id not in due_ids and target.health>estimated_max_health(target)*config.wall_heal_fraction:
                self.orders=[];self.carrier_id=None;self.stage='carry_wall_reserve';return LogisticsPlan()
        # Buy a planned basket, then deliver without re-ranking it every turn.
        needed = Counter(o.item for o in self.orders) - Counter(role.backpack)
        shop_goals = tuple(p for s in turn.zone_positions("weaponShop") for p in interaction_cells(grid,s))
        shop_distance = min((distances.get(p,10000) for p in shop_goals),default=10000)
        delivery = next((o for o in self.orders if o.item in role.backpack),None)
        # Deliver immediately when adjacent, or when the remaining basket is no longer affordable.
        prices = {i.name:i.price for i in turn.weapon_shop}
        missing_cost = sum(prices.get(name,100000)*n for name,n in needed.items())
        # Reserves can fund critical repairs and the first rocket power increase.
        emergency_order = any((target := turn.team_our.unit(o.target_id)) is not None and (critically_damaged(target)
                              or target.unit_id in due_ids or target.unit_id==development_id or (not first_rocket and target.role_type == ROLE_ROCKET))
                              for o in self.orders)
        spending = max(budget.offensive, turn.team_our.gold-budget.mandatory) if emergency_order else budget.offensive
        target = turn.team_our.unit(delivery.target_id) if delivery else None
        if target is not None and (distance(target)==0 or not needed or missing_cost > spending or shop_distance >= 10000):
            self.stage = "deliver"
            if distance(target)==0:
                return LogisticsPlan(action=Action(role.unit_id,ActionType.USE,name=delivery.item,targets=(target.pos,)))
            return LogisticsPlan(move=MoveIntent(role.unit_id,goals(target),90))
        if needed and missing_cost <= spending and shop_distance < 10000:
            trip=TravelBudget.for_role(turn,role,config)
            stops=[(shop_goals,len(needed))]
            stops.extend((goals(target),1) for order in self.orders
                         if (target:=turn.team_our.unit(order.target_id)) is not None and not (config.defer_weapon_delivery and order.item.startswith('WeaponUpgradeVoucher')))
            if any(o.item.startswith('WeaponUpgradeVoucher') for o in self.orders):stops.append((trip.goals,max(1,sum(o.item.startswith('WeaponUpgradeVoucher') for o in self.orders))))
            next_task=min((t.cooldown_rounds for t in turn.team_our.player_tasks if t.cooldown_rounds>0),default=10000)
            task_conflict=False
            if not trip.fits(stops) and len(self.orders)>1:
                # Try the development item alone before dropping the whole basket.
                order=next((o for o in self.orders if o.target_id==development_id),self.orders[0])
                target=turn.team_our.unit(order.target_id)
                short=[(shop_goals,1),(goals(target),1)]
                if trip.fits(short):
                    self.orders=[order];needed=Counter([order.item])-Counter(role.backpack);stops=short
            if not trip.fits(stops) or task_conflict:
                self.orders=[order for order in self.orders if order.item in role.backpack]
                if not self.orders:self.carrier_id=None
                self.stage="defer_return_deadline"
                return LogisticsPlan()
            self.stage = "purchase"
            if shop_distance == 0:
                name = next(iter(needed))
                quantity = needed[name]
                if first_rocket and name == "WallFixer" and prices[name] * (quantity+1) <= max(0,budget.offensive-reserve):
                    quantity += 1  # Carry one spare for the next damage event.
                quantity = min(quantity, max(0,role.backpack_capacity-len(role.backpack)))
                if quantity:
                    return LogisticsPlan(action=Action(role.unit_id,ActionType.BUY,name=name,quantity=quantity))
                self.orders = []
                return LogisticsPlan()
            return LogisticsPlan(move=MoveIntent(role.unit_id,shop_goals,85))
        self.orders, self.carrier_id, self.stage = [], None, "unfunded"
        return LogisticsPlan()


def _maintenance_options(turn: Turn, config: StrategyConfig = DEFAULT_CONFIG) -> list[tuple[str, Unit, int]]:
    result: list[tuple[str, Unit, int]] = []
    station=turn.team_our.station()
    front_targets=set()
    if station is not None and turn.day_index>=2:
        frame=turn.coordinate_frame
        cells=[frame.normalize(p) for p in station.footprint()]
        front=max(p.x for p in cells)+2
        center=sum(p.y for p in cells)/len(cells)
        walls=[u for u in turn.team_our.roles if u.role_type==ROLE_WALL and u.alive and u.pos is not None
               and frame.normalize(u.pos).x==front]
        quota=max(0,config.second_day_front_upgrades-sum(u.level>=2 for u in walls))
        front_targets={u.unit_id for u in sorted((u for u in walls if u.level==1),
                        key=lambda u:(u.health,abs(frame.normalize(u.pos).y-center)))[:quota]}
    prioritized={u.unit_id:i for i,u in enumerate(front_walls(turn)[:4])}
    due_ids={u.unit_id for u in due_defense_targets(turn,config)}
    for target in turn.team_our.roles:
        if target.health <= 0 or target.pos is None:
            continue
        max_health = estimated_max_health(target)
        missing = max(0, max_health - target.health)
        if target.role_type in WEAPON_ROLE_TYPES and target.level in {1, 2}:
            result.append(
                (f"WeaponUpgradeVoucher{target.level}", target, upgrade_value(turn, target))
            )
        elif target.role_type == ROLE_STATION and target.level in {1, 2}:
            if turn.day_index >= 2 or missing >= max_health // 5:
                result.append(
                    (f"StationUpgradeVoucher{target.level}", target, upgrade_value(turn, target))
                )
        elif target.role_type == ROLE_WALL:
            front_upgrade=target.unit_id in front_targets or (turn.day_index>=config.night_support_day and target.unit_id in prioritized)
            if target.level in {1, 2} and target.level < wall_level_goal(turn,target) and (missing >= max_health // 5 or front_upgrade or target.unit_id in due_ids):
                result.append(
                    (f"WallUpgradeVoucher{target.level}", target, upgrade_value(turn, target)
                     + (2400 if front_upgrade else 0) + (3000 if critically_damaged(target) else 0))
                )
            if missing >= max_health // 3 or (turn.day_index>=config.night_support_day and target.unit_id in prioritized):
                result.append(("WallFixer", target, 1000 + missing * 2))
    result.sort(key=lambda option: option[2], reverse=True)
    return result


def plan_upgrade_or_repair(
    turn: Turn,
    role: Unit,
    budget: DefenseBudget,
    config: StrategyConfig = DEFAULT_CONFIG,
    *,
    allow_move: bool = True,
    critical_only: bool = False,
    owned_only: bool = False,
) -> LogisticsPlan:
    if role.pos is None:
        return LogisticsPlan()

    options = _maintenance_options(turn,config)
    due_ids={u.unit_id for u in due_defense_targets(turn,config)}
    options=[(name,target,priority+(100000 if target.unit_id in due_ids and 'UpgradeVoucher' in name else 0)+(200000 if critically_damaged(target) else 0)) for name,target,priority in options]
    if critical_only:
        options = [
            option
            for option in options
            if option[1].health * 2 < estimated_max_health(option[1])
            or (option[1].role_type == ROLE_ROCKET and option[1].level == 2)
        ]
    options.sort(
        key=lambda option: (
            option[2],
            -role.pos.distance_to(option[1].pos),
            -option[1].unit_id,
        ),
        reverse=True,
    )
    for name, target, priority in options:
        if name not in role.backpack:
            continue
        if target.role_type==ROLE_WALL and target.unit_id not in due_ids and target.health>estimated_max_health(target)*config.wall_heal_fraction:
            continue
        if role.pos.distance_to(target.pos) <= 1:
            return LogisticsPlan(
                action=Action(role.unit_id, ActionType.USE, name=name, targets=(target.pos,))
            )
        if allow_move:
            return LogisticsPlan(
                move=MoveIntent(role.unit_id, tuple(target.pos.neighbours()), priority=priority)
            )

    if owned_only or budget.offensive <= 0 or not turn.weapon_shop:
        return LogisticsPlan()
    shop_items = {item.name: item.price for item in turn.weapon_shop}
    affordable = next(
        (
            name for name, _target, _priority in options
            if name in shop_items and 0 < shop_items[name] <= budget.offensive
            and not any(name in unit.backpack for unit in turn.controllable)
        ),
        None,
    )
    if affordable is None:
        return LogisticsPlan()
    shops = turn.zone_positions("weaponShop")
    if any(role.pos.distance_to(shop) <= 1 for shop in shops):
        return LogisticsPlan(
            action=Action(role.unit_id, ActionType.BUY, name=affordable, quantity=1)
        )
    if not allow_move:
        return LogisticsPlan()
    return LogisticsPlan(
        move=MoveIntent(
            role.unit_id,
            tuple(pos for shop in shops for pos in shop.neighbours()),
            priority=75,
        )
    )


def plan_repair_stock(turn: Turn, role: Unit, budget: DefenseBudget, config: StrategyConfig) -> LogisticsPlan:
    """Daytime pioneer reserve, funded only after the next development purchase."""
    if not turn.is_day or turn.day_index < config.repair_stock_day or role.role_type != 'pioneer' or not role.pos:
        return LogisticsPlan()
    if due_defense_targets(turn,config): return LogisticsPlan()
    missing = max(0, config.pioneer_repair_stock - role.backpack.count('WallFixer'))
    capacity = max(0,role.backpack_capacity-len(role.backpack))
    prices = {i.name:i.price for i in turn.weapon_shop}
    price = prices.get('WallFixer',0)
    target = next_development_target(turn,config)
    item = upgrade_item(target)
    reserve = prices.get(item,0) if item and not any(item in r.backpack for r in turn.controllable) else 0
    quantity = min(missing,capacity,max(0,budget.offensive-reserve)//price) if price > 0 else 0
    if quantity <= 0: return LogisticsPlan()
    grid = OccupancyGrid.from_turn(turn,ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
    goals = tuple(p for shop in turn.zone_positions('weaponShop') for p in interaction_cells(grid,shop))
    if not goals or not TravelBudget.for_role(turn,role,config).fits([(goals,1)]): return LogisticsPlan()
    if role.pos in goals:
        return LogisticsPlan(action=Action(role.unit_id,ActionType.BUY,name='WallFixer',quantity=quantity))
    return LogisticsPlan(move=MoveIntent(role.unit_id,goals,86))
