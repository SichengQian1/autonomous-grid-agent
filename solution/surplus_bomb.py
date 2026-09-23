"""One optional nightly item attack, after actual defense readiness checks."""
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
            self.pending=None

    def plan(self,turn,miner,engineer,budget,config,committed=0,repair_committed=False):
        self.status={'reason':'disabled_or_early','actor':getattr(miner,'unit_id',None)}
        def wait(reason):
            self.status['reason']=reason
            return LogisticsPlan(reason=reason)
        if not config.allow_surplus_bomb or turn.is_day or turn.day_index<config.bomb_start_day:return wait('disabled_or_early')
        if not miner or not miner.pos or not engineer or not engineer.alive or miner.unit_id==engineer.unit_id:return wait('no_spare_miner_or_engineer')
        if self.used_day==turn.day_index:return wait('nightly_bomb_already_used')
        base=turn.team_our.station()
        weapons=[w for w in turn.team_our.roles if w.is_weapon and w.alive]
        needs=wall_needs(turn,replace(engineer,backpack=()),config)
        if (not base or base.level<2 or base.health<estimated_max_health(base)//2
            or len(weapons)<config.max_weapon_count or any(w.level<3 for w in weapons)
            or needs['WallUpgradeVoucher1'] or needs['WallUpgradeVoucher2']):return wait('defense_not_ready')
        owned='Bomb' in miner.backpack
        stock=engineer.backpack.count('WallFixer')-int(repair_committed)
        required=config.pioneer_repair_stock if owned else config.surplus_repair_stock
        self.status.update(repair_stock=stock,required_stock=required)
        if stock<required:return wait('repair_stock_first')
        grid,danger=safe_grid(turn,config)
        if miner.pos in danger:return wait('miner_exposed')
        target,estimate=bomb_target(turn,config)
        self.status.update(target=target.to_raw() if target else None,estimate=estimate)
        if target is None:return wait('no_profitable_medium_cluster')
        if owned:
            self.status['reason']='bomb_use'
            return LogisticsPlan(action=Action(miner.unit_id,ActionType.USE,name='Bomb',targets=(target,)),reason='bomb_use')
        if self.bought_day==turn.day_index or any('Bomb' in r.backpack for r in turn.controllable):return wait('bomb_already_purchased_or_carried')
        price=next((i.price for i in turn.weapon_shop if i.name=='Bomb'),0)
        cash=max(0,turn.team_our.gold-committed-budget.mandatory-budget.emergency)
        self.status.update(price=price,spendable=cash)
        if price<=0 or cash<price or len(miner.backpack)>=miner.backpack_capacity:return wait('no_surplus_or_capacity')
        goals=tuple(p for s in turn.zone_positions('weaponShop') for p in interaction_cells(grid,s))
        path=shortest_path(grid,miner.pos,goals)
        left=130-(turn.round_no-1)%130
        if not path or len(path)+2>left:return wait('no_safe_purchase_window')
        if miner.pos in goals:
            self.status['reason']='bomb_purchase'
            return LogisticsPlan(action=Action(miner.unit_id,ActionType.BUY,name='Bomb',quantity=1),reason='bomb_purchase')
        self.status['reason']='bomb_safe_shop_trip'
        return LogisticsPlan(move=MoveIntent(miner.unit_id,goals,40,avoid_cells=danger),reason='bomb_safe_shop_trip')
