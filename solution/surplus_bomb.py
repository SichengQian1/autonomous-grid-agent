"""Engineer-owned daytime bomb stock; wall rescue always precedes item attacks."""
from dataclasses import dataclass, field, replace
from .actions import Action, ActionType
from .grid import interaction_cells, shortest_path
from .logistics import LogisticsPlan, estimated_max_health
from .movement import MoveIntent
from .route_safety import safe_grid
from .rules import TEAM_CHALLENGER, TEAM_DEFENDER
from .wall_supply import wall_needs


def bomb_target(turn,config):
    # Accumulate all 3x3 centers in O(9*n); no quadratic full-map search.
    scores={}
    opponent={TEAM_CHALLENGER:TEAM_DEFENDER,TEAM_DEFENDER:TEAM_CHALLENGER}.get(turn.team_our.team_type)
    if not opponent:return None,()
    for robot in turn.robots:
        if not robot.pos or robot.health<=0 or robot.target_team!=opponent:continue
        for pos in (robot.pos,)+robot.pos.neighbours():
            if not (0<=pos.x<turn.map_info.width and 0<=pos.y<turn.map_info.height):continue
            score=scores.setdefault(pos,[0,0,0])
            medium=robot.role_type=='middleRobot'
            score[0]+=int(medium and robot.health<=config.bomb_damage)
            score[1]+=int(medium)
            score[2]+=min(robot.health,config.bomb_damage)
    if not scores:return None,()
    pos=max(scores,key=lambda p:(*scores[p],-p.x,-p.y))
    score=scores[pos]
    return (pos if score[0]>=config.bomb_minimum_medium_kills else None),tuple(score)


@dataclass(slots=True)
class SurplusBomb:
    bought_day: int = 0
    used_day: int = 0
    failed_use_day: int = 0
    pending: tuple | None = None
    status: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)

    def issued(self,turn,action):
        if action.name!='Bomb' or action.action_type not in (ActionType.BUY,ActionType.USE):return
        if action.action_type==ActionType.USE:self.used_day=turn.day_index
        else:self.bought_day=turn.day_index
        self.pending=(turn.round_no,action.actor_id,action.action_type.value,turn.day_index)

    def observe(self,turn):
        if self.pending and turn.round_no>self.pending[0]:
            round_no,actor,kind,day=self.pending
            outcome=turn.last_action_results.get(actor) if turn.round_no==round_no+1 else None
            self.result={'issued_round':round_no,'day':day,'actor':actor,'action':kind,
                         'success':outcome,'attribution':'action_feedback_only_no_kill_claim'}
            if kind==ActionType.USE.value and outcome is not True:self.failed_use_day=day
            self.pending=None

    def plan(self,turn,actor,engineer,budget,config,committed=0,repair_committed=False):
        self.status={'reason':'disabled_or_early','actor':getattr(actor,'unit_id',None)}
        def wait(reason):
            self.status['reason']=reason
            return LogisticsPlan(reason=reason)
        if not config.allow_surplus_bomb or turn.day_index<config.bomb_start_day:return wait('disabled_or_early')
        if not actor or not actor.pos or not engineer or actor.unit_id!=engineer.unit_id:return wait('engineer_owns_bombs')
        if repair_committed:return wait('wall_rescue_first')
        owned=actor.backpack.count('Bomb')
        if not turn.is_day:
            if not owned:return wait('no_carried_bomb')
            if self.failed_use_day==turn.day_index:return wait('bomb_use_unconfirmed_stop')
            if turn.day_index<config.final_defense_day and self.used_day==turn.day_index:return wait('nightly_bomb_already_used')
            target,estimate=bomb_target(turn,config)
            self.status.update(target=target.to_raw() if target else None,estimate=estimate)
            if target is None:return wait('no_profitable_medium_cluster')
            self.status['reason']='bomb_use'
            return LogisticsPlan(action=Action(actor.unit_id,ActionType.USE,name='Bomb',targets=(target,)),reason='bomb_use')
        base=turn.team_our.station()
        weapons=[w for w in turn.team_our.roles if w.is_weapon and w.alive]
        if (not base or base.level<2 or base.health<estimated_max_health(base)//2
            or len(weapons)<config.max_weapon_count or any(w.level<3 for w in weapons)):
            return wait('defense_not_ready')
        # Held vouchers cover planned future upgrade-heals. Do not require their
        # premature use merely to enable a shop purchase.
        needs=wall_needs(turn,engineer,config)
        self.status.update(repair_stock=engineer.backpack.count('WallFixer'),wall_needs=dict(needs))
        if needs:return wait('wall_supplies_first')
        if self.bought_day==turn.day_index:return wait('bomb_already_purchased_or_carried')
        final=turn.day_index>=config.final_defense_day
        if owned and not final:return wait('bomb_already_purchased_or_carried')
        prices={i.name:i.price for i in turn.weapon_shop};price=prices.get('Bomb',0)
        reserve=budget.mandatory+budget.emergency
        if final:
            helper=next((r for r in turn.controllable if r.role_type=='worker' and r.unit_id!=engineer.unit_id),None)
            if helper:reserve+=max(0,config.final_helper_repairs-helper.backpack.count('WallFixer'))*prices.get('WallFixer',100000)
        cash=max(0,turn.team_our.gold-committed-reserve)
        capacity=max(0,actor.backpack_capacity-len(actor.backpack))
        quantity=min(capacity,cash//price) if price>0 else 0
        if not final:quantity=min(quantity,1)
        self.status.update(price=price,spendable=cash,reserved=reserve)
        if quantity<=0:return wait('no_surplus_or_capacity')
        from .travel import TravelBudget
        trip=TravelBudget.for_role(turn,actor,config,wall_support=True)
        goals=tuple(p for s in turn.zone_positions('weaponShop') for p in interaction_cells(trip.grid,s))
        if not goals or not trip.fits(((goals,1),)):return wait('no_safe_purchase_window')
        if actor.pos in goals:
            self.status['reason']='bomb_purchase'
            return LogisticsPlan(action=Action(actor.unit_id,ActionType.BUY,name='Bomb',quantity=quantity),reason='bomb_purchase')
        # Combine with the late wall-supply trip; do not send the engineer on an
        # extra early round trip while it could still be mining or rebuilding.
        if turn.rounds_until_night>trip.cost(((goals,1),))+config.mining_batch_size+trip.margin:
            return wait('mine_before_bomb_procurement')
        self.status['reason']='bomb_shop_trip'
        return LogisticsPlan(move=MoveIntent(actor.unit_id,goals,94),reason='bomb_shop_trip')
