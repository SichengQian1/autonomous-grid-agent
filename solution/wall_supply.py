"""Engineer-owned wall inventory, timed procurement and safe nighttime use."""
from collections import Counter
from dataclasses import replace, dataclass, field
from .actions import Action, ActionType
from .economy import front_wall_number, side_wall_a, due_defense_targets, wall_level_goal
from .defense import existing_weapons, existing_walls, build_defense_layout
from .grid import interaction_cells
from .logistics import LogisticsPlan, estimated_max_health
from .movement import MoveIntent
from .travel import TravelBudget


def wall_target(turn, wall):
    number=front_wall_number(turn,wall)
    return wall_level_goal(turn,wall) if number or side_wall_a(turn,wall) else 1


def wall_needs(turn, role, config):
    """Remaining vouchers, not a fresh fixed basket each day; missing walls count."""
    need=Counter()
    existing={w.pos:w for w in existing_walls(turn)}
    for pos in build_defense_layout(turn).wall_sites:
        wall=existing.get(pos)
        if wall is None:
            from .models import Unit
            wall=Unit(unit_id=-1,role_type='wall',pos=pos,health=1000,level=1)
        goal=wall_target(turn,wall)
        if turn.day_index<config.advanced_wall_day:goal=min(goal,2)
        for level in range(max(1,wall.level),goal):need[f'WallUpgradeVoucher{level}']+=1
    need['WallFixer']=config.pioneer_repair_stock if turn.day_index>=config.repair_stock_day else config.wall_stock_early
    if turn.day_index>=config.surplus_repair_day:need['WallFixer']=config.surplus_repair_stock
    return +(need-Counter(role.backpack))


def _sale_before_stock(turn,role,trip,goals,purchases,config,force_trip=False):
    """Budget vendor sales, shopping actions and the observed return route."""
    prices={i.name:i.price for i in turn.vendor_shop}
    ore=Counter(n for n in role.backpack if n in ('iron','copper') and prices.get(n,0)>0)
    vendors=tuple(p for v in turn.zone_positions('vendor') for p in interaction_cells(trip.grid,v))
    stops=(((vendors,len(ore)),) if ore else ())+((goals,purchases),)
    cost=trip.cost(stops)
    evidence=(('route_actions',cost),('sale_actions',len(ore)),('gold',turn.team_our.gold))
    if not force_trip and turn.rounds_until_night>cost+config.mining_batch_size+trip.margin:
        return LogisticsPlan(reason='mine_before_wall_procurement',evidence=evidence)
    if not trip.fits(stops):
        return LogisticsPlan(reason='wall_stock_return_deadline',evidence=evidence)
    if ore:
        if role.pos in vendors:
            name=max(ore,key=lambda n:(prices[n]*ore[n],n))
            return LogisticsPlan(action=Action(role.unit_id,ActionType.SELL,name=name,quantity=ore[name]),reason='wall_stock_sell_ore',evidence=evidence)
        return LogisticsPlan(move=MoveIntent(role.unit_id,vendors,97),reason='wall_stock_liquidate_trip',evidence=evidence)
    return LogisticsPlan(reason='wall_stock_purchase_window',evidence=evidence)


def wall_stock_plan(turn, role, budget, config, *, force_trip=False):
    if role.role_type!='worker' or not turn.is_day or turn.day_index<config.night_support_day or not role.pos:
        return LogisticsPlan()
    need=wall_needs(turn,role,config)
    if not need:return LogisticsPlan(reason='wall_stock_ready')
    trip=TravelBudget.for_role(turn,role,config,wall_support=True)
    goals=tuple(p for shop in turn.zone_positions('weaponShop') for p in interaction_cells(trip.grid,shop))
    if not goals:return LogisticsPlan(reason='wall_stock_no_shop')
    baseline=config.pioneer_repair_stock if turn.day_index>=config.repair_stock_day else config.wall_stock_early
    baseline_gap=max(0,baseline-role.backpack.count('WallFixer'))
    purchases=len(need)+int(0<baseline_gap<need.get('WallFixer',0))
    route=_sale_before_stock(turn,role,trip,goals,purchases,config,force_trip)
    evidence=tuple(sorted(need.items()))+route.evidence
    if route.reason!='wall_stock_purchase_window':return replace(route,evidence=evidence)
    prices={i.name:i.price for i in turn.weapon_shop}
    owned=Counter(i for r in turn.controllable for i in r.backpack)
    weapons=existing_weapons(turn)
    reserve=budget.mandatory
    reserve+=max(0,sum(w.level<2 for w in weapons)-owned['WeaponUpgradeVoucher1'])*prices.get('WeaponUpgradeVoucher1',100)
    # The third-day liquidation funds the entire battery before optional wall
    # stock. Later emergency repair stock keeps its established priority.
    if turn.day_index==config.advanced_rocket_day:
        reserve+=max(0,sum(w.level<3 for w in weapons)-owned['WeaponUpgradeVoucher2'])*prices.get('WeaponUpgradeVoucher2',150)
    base=turn.team_our.station()
    if turn.day_index>=config.base_level_two_day and base and base.level<2 and not owned['StationUpgradeVoucher1']:
        reserve+=prices.get('StationUpgradeVoucher1',100)
    cash=max(0,turn.team_our.gold-reserve)
    capacity=max(0,role.backpack_capacity-len(role.backpack))
    # A small immediate repair reserve first; then upgrade-heals, then replenish
    # the full repair stock. After night five the six-item reserve comes first.
    upgrades=[('WallUpgradeVoucher1',need['WallUpgradeVoucher1']),('WallUpgradeVoucher2',need['WallUpgradeVoucher2'])]
    repair=[('WallFixer',baseline_gap)]
    order=repair+upgrades if turn.day_index>=config.repair_stock_day or role.backpack.count('WallFixer')==0 else upgrades+repair
    # Surplus repairs never consume money needed by the remaining wall basket.
    order += [('WallFixer',max(0,need['WallFixer']-baseline_gap))]
    for index,(name,wanted) in enumerate(order):
        price=prices.get(name,0)
        spending=cash
        if index==len(order)-1:
            spending=max(0,cash-sum(prices.get(n,100000)*q for n,q in upgrades)-baseline_gap*prices.get('WallFixer',100000))
        qty=min(wanted,capacity,spending//price) if price>0 else 0
        if qty<=0:continue
        if role.pos in goals:
            return LogisticsPlan(action=Action(role.unit_id,ActionType.BUY,name=name,quantity=qty),reason='wall_stock_purchase',evidence=evidence)
        return LogisticsPlan(move=MoveIntent(role.unit_id,goals,96),reason='wall_stock_trip',evidence=evidence)
    return LogisticsPlan(reason='wall_stock_funding_gap',evidence=evidence+(('reserved_gold',reserve),))


def wall_use_item(turn,wall,role,config,incoming=0,steps=0):
    """Repair never inherits an upgrade deadline; upgrades are night-only."""
    if turn.is_day:return ''
    maximum=estimated_max_health(wall)
    missing=maximum-wall.health
    low=wall.health<=max(maximum*config.wall_heal_fraction,incoming*(steps+2))
    item=f'WallUpgradeVoucher{wall.level}'
    next_turn=replace(turn,round_no=turn.day_index*130+1)
    due={w.unit_id for w in due_defense_targets(turn,config)}
    ahead={w.unit_id for w in due_defense_targets(next_turn,config)}
    # Use the last part of the preceding night to meet the next night's target,
    # even if healing opportunity never arrives. Leave travel/actions explicit.
    left=130-(turn.round_no-1)%130
    pending=[w for w in turn.team_our.roles if w.role_type=='wall' and w.alive and w.unit_id in ahead]
    # Enlarging the array also enlarges the last-night completion trip. Count
    # remaining tier actions plus transit; do not retain the old 16-turn cutoff.
    lead=max(16,sum(max(0,wall_target(turn,w)-w.level) for w in pending)+2*len(pending)+config.recall_safety_buffer)
    deadline=wall.unit_id in due or (wall.unit_id in ahead and left<=lead+steps)
    if wall.level<wall_target(turn,wall) and item in role.backpack and (low or deadline):return item
    if low and missing>=maximum*config.wall_repair_min_damage and 'WallFixer' in role.backpack:return 'WallFixer'
    return ''


def final_helper_stock(turn,role,engineer,budget,config, *, force_trip=False):
    """A second repair carrier for the final night, without taking engineer funds."""
    if not turn.is_day or turn.day_index<config.final_defense_day or not role or not role.pos:
        return LogisticsPlan()
    trip=TravelBudget.for_role(turn,role,config,wall_support=True,support_helper=True)
    goals=tuple(p for s in turn.zone_positions('weaponShop') for p in interaction_cells(trip.grid,s))
    need=max(0,config.final_helper_repairs-role.backpack.count('WallFixer'))
    if need and goals:
        route=_sale_before_stock(turn,role,trip,goals,1,config,force_trip)
        if route.reason!='wall_stock_purchase_window':return route
    prices={i.name:i.price for i in turn.weapon_shop};price=prices.get('WallFixer',0)
    engineer_cost=sum(prices.get(n,100000)*q for n,q in wall_needs(turn,engineer,config).items()) if engineer else 0
    cash=max(0,turn.team_our.gold-budget.mandatory-engineer_cost)
    quantity=min(need,max(0,role.backpack_capacity-len(role.backpack)),cash//price) if price else 0
    if quantity and goals and trip.fits(((goals,1),)):
        if force_trip or turn.rounds_until_night<=trip.cost(((goals,1),))+config.mining_batch_size+trip.margin:
            if role.pos in goals:
                return LogisticsPlan(action=Action(role.unit_id,ActionType.BUY,name='WallFixer',quantity=quantity),reason='final_helper_purchase')
            return LogisticsPlan(move=MoveIntent(role.unit_id,goals,97),reason='final_helper_shop_trip')
    if trip.cost()+trip.margin>=turn.rounds_until_night:
        return LogisticsPlan(move=MoveIntent(role.unit_id,trip.goals,119),reason='final_helper_return')
    return LogisticsPlan(reason='mine_before_final_helper_trip')


@dataclass(slots=True)
class WallSupplyCycle:
    """Keep a late-day sale/shop trip committed through the return home."""
    day: int = 0
    active: set[int] = field(default_factory=set)
    finished: set[int] = field(default_factory=set)

    def plan(self,turn,role,budget,config,*,helper=False,engineer=None):
        if self.day!=turn.day_index:
            self.day=turn.day_index;self.active.clear();self.finished.clear()
        if not role or not turn.is_day or turn.day_index<(config.final_defense_day if helper else config.night_support_day):
            return LogisticsPlan()
        trip=TravelBudget.for_role(turn,role,config,wall_support=True,support_helper=helper)
        def back(reason):
            self.active.discard(role.unit_id);self.finished.add(role.unit_id)
            return LogisticsPlan(move=MoveIntent(role.unit_id,trip.goals,119),reason=reason)
        if role.unit_id in self.finished:return back('wall_cycle_return')
        active=role.unit_id in self.active
        if helper:
            if active and role.backpack.count('WallFixer')>=config.final_helper_repairs:return back('wall_cycle_return')
            plan=final_helper_stock(turn,role,engineer,budget,config,force_trip=active)
        else:plan=wall_stock_plan(turn,role,budget,config,force_trip=active)
        if plan.action or plan.move:
            self.active.add(role.unit_id)
            return plan
        if active:
            if plan.reason=='wall_stock_ready':return back('wall_cycle_return')
            if plan.reason=='wall_stock_return_deadline' or trip.cost()+trip.margin>=turn.rounds_until_night:
                return back('wall_cycle_return_shortfall')
            return LogisticsPlan(move=MoveIntent(role.unit_id,(role.pos,),97),reason=plan.reason,evidence=plan.evidence)
        return plan
