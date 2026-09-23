"""Engineer-owned wall inventory, timed procurement and safe nighttime use."""
from collections import Counter
from dataclasses import replace
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
        # Prepare first upgrades for night three, then both tiers for subsequent
        # healing opportunities and the fifth-night completion deadline.
        if turn.day_index<4:goal=min(goal,2)
        for level in range(max(1,wall.level),goal):need[f'WallUpgradeVoucher{level}']+=1
    need['WallFixer']=config.pioneer_repair_stock if turn.day_index>=config.repair_stock_day else config.wall_stock_early
    return +(need-Counter(role.backpack))


def wall_stock_plan(turn, role, budget, config):
    if role.role_type!='worker' or not turn.is_day or turn.day_index<config.night_support_day or not role.pos:
        return LogisticsPlan()
    need=wall_needs(turn,role,config)
    if not need:return LogisticsPlan(reason='wall_stock_ready')
    trip=TravelBudget.for_role(turn,role,config,wall_support=True)
    goals=tuple(p for shop in turn.zone_positions('weaponShop') for p in interaction_cells(trip.grid,shop))
    if not goals:return LogisticsPlan(reason='wall_stock_no_shop')
    cost=trip.cost(((goals,len(need)),))
    evidence=tuple(sorted(need.items()))+(('route_actions',cost),('gold',turn.team_our.gold))
    # Leave one working batch before the latest physical shopping/return trip.
    if turn.rounds_until_night>cost+config.mining_batch_size+trip.margin:
        return LogisticsPlan(reason='mine_before_wall_procurement',evidence=evidence)
    if not trip.fits(((goals,len(need)),)):
        return LogisticsPlan(reason='wall_stock_return_deadline',evidence=evidence)
    prices={i.name:i.price for i in turn.weapon_shop}
    owned=Counter(i for r in turn.controllable for i in r.backpack)
    weapons=existing_weapons(turn)
    reserve=budget.mandatory
    reserve+=max(0,sum(w.level<2 for w in weapons)-owned['WeaponUpgradeVoucher1'])*prices.get('WeaponUpgradeVoucher1',100)
    base=turn.team_our.station()
    if turn.day_index>=config.base_level_two_day and base and base.level<2 and not owned['StationUpgradeVoucher1']:
        reserve+=prices.get('StationUpgradeVoucher1',100)
    cash=max(0,turn.team_our.gold-reserve)
    capacity=max(0,role.backpack_capacity-len(role.backpack))
    # A small immediate repair reserve first; then upgrade-heals, then replenish
    # the full repair stock. After night five the six-item reserve comes first.
    order=['WallFixer','WallUpgradeVoucher1','WallUpgradeVoucher2'] if turn.day_index>=config.repair_stock_day or role.backpack.count('WallFixer')==0 else ['WallUpgradeVoucher1','WallUpgradeVoucher2','WallFixer']
    for name in order:
        price=prices.get(name,0)
        qty=min(need[name],capacity,cash//price) if price>0 else 0
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
    deadline=wall.unit_id in due or (wall.unit_id in ahead and left<=16+steps)
    if wall.level<wall_target(turn,wall) and item in role.backpack and (low or deadline):return item
    if low and missing>=maximum*config.wall_repair_min_damage and 'WallFixer' in role.backpack:return 'WallFixer'
    return ''
