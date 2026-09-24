"""Engineer-owned wall inventory, timed procurement and safe nighttime use."""
from collections import Counter
from dataclasses import replace, dataclass, field
from .actions import Action, ActionType
from .economy import front_wall_number, side_wall_a, due_defense_targets, wall_level_goal, weapon_stock_cost, scheduled_targets
from .defense import existing_weapons, existing_walls, build_defense_layout
from .grid import interaction_cells, OccupancyGrid, shortest_path
from .logistics import LogisticsPlan, estimated_max_health
from .movement import MoveIntent
from .travel import TravelBudget


def gate_stone_plan(turn,role,config):
    """Acquire a resealing stone before a closed gate makes recall unreachable."""
    from .wall_access import gate_sites, inside
    if not turn.is_day or not role or not role.pos or not gate_sites(turn,config) or inside(turn,role.pos):
        return LogisticsPlan()
    # Before the final day keep a stone for the following morning's exit too.
    minimum=1 if turn.day_index>=config.final_defense_day else 2
    need=minimum-role.backpack.count('stone')
    if need<=0:return LogisticsPlan()
    grid=OccupancyGrid.from_turn(turn,ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
    projected=replace(role,backpack=role.backpack+('stone',)*need)
    trip=TravelBudget.for_role(turn,projected,config,wall_support=True)
    if len(role.backpack)+need>role.backpack_capacity:
        prices={i.name:i.price for i in turn.vendor_shop}
        ores=Counter(n for n in role.backpack if n in ('iron','copper') and prices.get(n,0)>0)
        vendors=tuple(p for z in turn.zone_positions('vendor') for p in interaction_cells(grid,z))
        sale_path=shortest_path(grid,role.pos,vendors)
        if not ores or not sale_path:return LogisticsPlan()
        routes=[shortest_path(grid,sale_path[-1],interaction_cells(grid,z.pos))
                for z in turn.map_info.zones if z.neutral_type=='stone' and z.pos]
        if not any(p and len(sale_path)-1+len(ores)+len(p)-1+need+trip.home.get(p[-1],10000)+trip.margin<turn.rounds_until_night for p in routes):
            return LogisticsPlan()
        if role.pos in vendors:
            name=max(ores,key=lambda n:prices[n]*ores[n])
            return LogisticsPlan(action=Action(role.unit_id,ActionType.SELL,name=name,quantity=ores[name]),reason='gate_stone_capacity_sale')
        return LogisticsPlan(move=MoveIntent(role.unit_id,vendors,121),reason='gate_stone_capacity_sale')
    paths=[(shortest_path(grid,role.pos,interaction_cells(grid,z.pos)),z.pos)
           for z in turn.map_info.zones if z.neutral_type=='stone' and z.pos]
    paths=[(p,z) for p,z in paths if p and len(p)-1+need+trip.home.get(p[-1],10000)+trip.margin<turn.rounds_until_night]
    if not paths:return LogisticsPlan()
    path,stone=min(paths,key=lambda item:len(item[0])+trip.home.get(item[0][-1],10000))
    if role.pos.distance_to(stone)==1:
        return LogisticsPlan(action=Action(role.unit_id,ActionType.COLLECT,targets=(stone,)),reason='gate_stone_before_return')
    return LogisticsPlan(move=MoveIntent(role.unit_id,interaction_cells(grid,stone),121),reason='gate_stone_before_return')


def wall_target(turn, wall):
    number=front_wall_number(turn,wall)
    return wall_level_goal(turn,wall) if number or side_wall_a(turn,wall) else 1


def minimum_repair_stock(turn,config):
    if turn.day_index<config.night_support_day:return 0
    return config.pioneer_repair_stock if turn.day_index>=config.repair_stock_day else config.wall_stock_early


def minimum_repair_cost(turn,config,role=None):
    workers=[r for r in turn.controllable if r.role_type=='worker']
    held=role.backpack.count('WallFixer') if role else max((r.backpack.count('WallFixer') for r in workers),default=0)
    price=next((i.price for i in turn.weapon_shop if i.name=='WallFixer'),0)
    return max(0,minimum_repair_stock(turn,config)-held)*price if workers else 0


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


def wall_stock_plan(turn, role, budget, config, *, minimum_only=False, force_trip=False, helper=False, engineer=None):
    """Reserve a vendor -> shop -> defense cycle, then sell every non-stone ore."""
    if role.role_type!='worker' or not turn.is_day or turn.day_index<config.night_support_day or not role.pos:
        return LogisticsPlan()
    baseline=config.final_helper_repairs if helper else minimum_repair_stock(turn,config)
    need=Counter(WallFixer=max(0,baseline-role.backpack.count('WallFixer'))) if helper else wall_needs(turn,role,config)
    need=+need
    if minimum_only:need=Counter(WallFixer=max(0,baseline-role.backpack.count('WallFixer')));need=+need
    sale_prices={i.name:i.price for i in turn.vendor_shop}
    ore=Counter(n for n in role.backpack if n in ('iron','copper') and sale_prices.get(n,0)>0)
    if not need and not ore:return LogisticsPlan(reason='wall_stock_ready')
    trip=TravelBudget.for_role(turn,role,config,wall_support=True)
    shops=tuple(p for shop in turn.zone_positions('weaponShop') for p in interaction_cells(trip.grid,shop))
    vendors=tuple(p for vendor in turn.zone_positions('vendor') for p in interaction_cells(trip.grid,vendor))
    gap=max(0,baseline-role.backpack.count('WallFixer'))
    split_repairs=0<gap<need.get('WallFixer',0) and any(need.get(n,0) for n in ('WallUpgradeVoucher1','WallUpgradeVoucher2'))
    stops=(((vendors,len(ore)),) if ore else ())+(((shops,len(need)+int(split_repairs)),) if need else ())
    cost=trip.cost(stops)
    evidence=tuple(sorted(need.items()))+(('route_actions',cost),('sale_actions',len(ore)),('gold',turn.team_our.gold))
    # Day three retains the initial rescue-stock objective. Later days use the
    # full sale/shopping/return route, and a latched trip never returns to mining.
    if not force_trip and turn.day_index>config.night_support_day and turn.rounds_until_night>cost+config.mining_batch_size+trip.margin:
        return LogisticsPlan(reason='mine_before_wall_procurement',evidence=evidence)
    if not trip.fits(stops):
        # A small basket may still fit, but do not silently skip ore liquidation.
        small=(((vendors,len(ore)),) if ore else ())+(((shops,1),) if need else ())
        if not trip.fits(small):return LogisticsPlan(reason='wall_stock_return_deadline',evidence=evidence)
    if ore:
        if not vendors:return LogisticsPlan(reason='wall_stock_no_vendor',evidence=evidence)
        if role.pos in vendors:
            name=max(ore,key=lambda n:(sale_prices[n]*ore[n],n))
            return LogisticsPlan(action=Action(role.unit_id,ActionType.SELL,name=name,quantity=ore[name]),reason='wall_stock_sell_ore',evidence=evidence)
        return LogisticsPlan(move=MoveIntent(role.unit_id,vendors,97),reason='wall_stock_liquidate_trip',evidence=evidence)
    if not shops:return LogisticsPlan(reason='wall_stock_no_shop',evidence=evidence)
    prices={i.name:i.price for i in turn.weapon_shop}
    owned=Counter(i for r in turn.controllable for i in r.backpack)
    basic=max(0,sum(w.level<2 for w in existing_weapons(turn))-owned['WeaponUpgradeVoucher1'])*prices.get('WeaponUpgradeVoucher1',100)
    reserve=budget.mandatory+basic
    base=turn.team_our.station()
    if base and base.level<2 and base.unit_id in {u.unit_id for u in scheduled_targets(turn,config)} and not owned['StationUpgradeVoucher1']:
        reserve+=prices.get('StationUpgradeVoucher1',100)
    if helper and engineer:
        reserve+=sum(prices.get(n,100000)*q for n,q in wall_needs(turn,engineer,config).items())
    cash=max(0,turn.team_our.gold-reserve)
    capacity=max(0,role.backpack_capacity-len(role.backpack))
    gap=max(0,baseline-role.backpack.count('WallFixer'))
    order=[('WallFixer',min(gap,need['WallFixer']))]
    order += [('WallUpgradeVoucher1',need['WallUpgradeVoucher1']),('WallUpgradeVoucher2',need['WallUpgradeVoucher2'])]
    order += [('WallFixer',max(0,need['WallFixer']-gap))]
    for index,(name,wanted) in enumerate(order):
        spending=cash if index==0 and not helper else max(0,cash-max(0,weapon_stock_cost(turn,config)-basic))
        if index==3:spending=max(0,spending-sum(prices.get(n,100000)*q for n,q in order[1:3]))
        price=prices.get(name,0)
        qty=min(wanted,capacity,spending//price) if price>0 else 0
        if qty<=0:continue
        if index==0 and not any(q for n,q in order[1:3]) and qty==wanted:
            # Same item can be bought in one action after the upgrade basket is
            # covered, while its surplus still respects unfinished gun funding.
            extra_cash=max(0,cash-max(0,weapon_stock_cost(turn,config)-basic)-qty*price)
            qty+=min(order[3][1],capacity-qty,extra_cash//price)
        if role.pos in shops:
            return LogisticsPlan(action=Action(role.unit_id,ActionType.BUY,name=name,quantity=qty),reason='wall_stock_purchase',evidence=evidence+(('reserved_gold',reserve),))
        return LogisticsPlan(move=MoveIntent(role.unit_id,shops,97),reason='wall_stock_trip',evidence=evidence)
    return LogisticsPlan(reason='wall_stock_funding_gap',evidence=evidence+(('reserved_gold',reserve),))


@dataclass(slots=True)
class WallSupplyCycle:
    day: int = 0
    active: set[int] = field(default_factory=set)
    finished: set[int] = field(default_factory=set)

    def plan(self,turn,role,budget,config,*,helper=False,engineer=None):
        if self.day!=turn.day_index:
            self.day=turn.day_index;self.active.clear();self.finished.clear()
        if not role or not turn.is_day or turn.day_index<config.night_support_day:return LogisticsPlan()
        trip=TravelBudget.for_role(turn,role,config,wall_support=True)
        if role.unit_id in self.finished:
            return LogisticsPlan(move=MoveIntent(role.unit_id,trip.goals,119),reason='wall_cycle_return')
        plan=wall_stock_plan(turn,role,budget,config,force_trip=role.unit_id in self.active,helper=helper,engineer=engineer)
        if plan.action or plan.move:
            self.active.add(role.unit_id)
            return plan
        if role.unit_id in self.active:
            if plan.reason=='wall_stock_ready':
                self.active.discard(role.unit_id)
                # An early third-day initial basket still leaves a working day.
                if turn.day_index==config.night_support_day and trip.cost()+trip.margin+config.mining_batch_size<turn.rounds_until_night:return plan
                self.finished.add(role.unit_id)
                return LogisticsPlan(move=MoveIntent(role.unit_id,trip.goals,119),reason='wall_cycle_return',evidence=plan.evidence)
            if (turn.day_index==config.night_support_day and plan.reason=='wall_stock_funding_gap'
                    and trip.cost()+trip.margin+config.mining_batch_size<turn.rounds_until_night):
                self.active.discard(role.unit_id)
                return plan
            if plan.reason=='wall_stock_return_deadline' or trip.cost()+trip.margin>=turn.rounds_until_night:
                self.finished.add(role.unit_id)
                return LogisticsPlan(move=MoveIntent(role.unit_id,trip.goals,119),reason='wall_cycle_return_shortfall',evidence=plan.evidence)
            return LogisticsPlan(move=MoveIntent(role.unit_id,(role.pos,),97),reason=plan.reason,evidence=plan.evidence)
        return plan


def wall_use_item(turn,wall,role,config,incoming=0,steps=0,committed=False):
    """Repair never inherits an upgrade deadline; upgrades are night-only."""
    if turn.is_day:return ''
    maximum=estimated_max_health(wall)
    missing=maximum-wall.health
    low=wall.health<=max(maximum*config.wall_heal_fraction,incoming*(steps+2))
    low=low or (committed and incoming>0 and missing>=maximum*config.wall_repair_min_damage)
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


def final_helper_stock(turn,role,engineer,budget,config):
    if not turn.is_day or turn.day_index<config.final_defense_day or not role:return LogisticsPlan()
    return wall_stock_plan(turn,role,budget,config,helper=True,engineer=engineer)


def worker_medicine_plan(turn,role,engineer,budget,config):
    """Optional stock only while already at the shop with time to return."""
    if not turn.is_day or role.role_type!='worker' or not role.pos:
        return LogisticsPlan()
    missing=max(0,config.worker_medicine_stock-role.backpack.count('Medicine'))
    prices={i.name:i.price for i in turn.weapon_shop};price=prices.get('Medicine',0)
    if not missing or price<=0:return LogisticsPlan()
    trip=TravelBudget.for_role(turn,role,config,worker_refuge=role!=engineer,wall_support=role==engineer)
    if not any(role.pos.distance_to(s)<=1 for s in turn.zone_positions('weaponShop')) or not trip.fits((((role.pos,),1),)):
        return LogisticsPlan()
    wall_cost=sum(prices.get(n,100000)*q for n,q in wall_needs(turn,engineer,config).items()) if engineer else 0
    base_cost=sum(prices.get(f'StationUpgradeVoucher{u.level}',100000) for u in due_defense_targets(turn,config) if u.role_type=='station')
    cash=max(0,turn.team_our.gold-budget.mandatory-budget.emergency-weapon_stock_cost(turn,config)-wall_cost-base_cost)
    qty=min(missing,max(0,role.backpack_capacity-len(role.backpack)),cash//price)
    if qty:return LogisticsPlan(action=Action(role.unit_id,ActionType.BUY,name='Medicine',quantity=qty),reason='worker_medicine_stock')
    return LogisticsPlan()
