"""Synthetic operating specifications, independent of private match data."""
import unittest
from dataclasses import replace
from tests.helpers import synthetic_turn, role
from solution.models import Turn
from solution.rules import DEFAULT_CONFIG
from solution.defense import build_defense_layout
from solution.combat import assign_controllers, plan_attacks
from solution.economy import EconomyManager, DefenseBudget, due_defense_targets, front_wall_number
from solution.state import WorldState


def world(round_no=1, side='challenger'):
    raw=synthetic_turn(round_no=round_no)
    raw['phaseTask']=''; raw['teamOur']['playerTasks']=[]; raw['robot']['roles']=[]
    raw['teamEnemy']['roles']=[]
    raw['teamOur']['type']=side
    raw['mapInfo']={'width':30,'height':24,'zones':[]}
    raw['teamOur']['roles']=[role(3,'station',5,15,health=1500,level=1)]
    if side!='challenger':raw['teamOur']['roles'][0]['pos']={'x':23,'y':9}
    layout=build_defense_layout(Turn.from_raw(raw))
    post=layout.controller_sites[0]
    raw['teamOur']['roles'] += [role(2,'pioneer',post.x,post.y),role(1,'worker',10,12),role(7,'worker',11,12)]
    raw['teamOur']['roles'] += [role(10+i,'rocket',p.x,p.y,level=2,health=1500,attack_range=30) for i,p in enumerate(layout.weapon_sites[:3])]
    raw['teamOur']['roles'] += [role(20+i,'wall',p.x,p.y,level=2,health=1500) for i,p in enumerate(layout.wall_sites)]
    raw['teamOur']['goldNum']=480
    raw['weaponShopList']=[{'name':n,'price':p} for n,p in [('WeaponUpgradeVoucher1',100),('WeaponUpgradeVoucher2',150),('StationUpgradeVoucher1',100),('WallUpgradeVoucher1',20),('WallUpgradeVoucher2',30),('WallFixer',10)]]
    return raw

class LayoutTests(unittest.TestCase):
    def test_both_sides_one_common_post(self):
        for side in ('challenger','defender'):
            turn=Turn.from_raw(world(side=side));layout=build_defense_layout(turn)
            self.assertEqual(len(set(layout.controller_sites)),1)
            self.assertTrue(all(layout.controller_sites[0].distance_to(p)==1 for p in layout.weapon_sites[:3]))
            norm=[turn.coordinate_frame.normalize(p) for p in layout.weapon_sites[:3]]
            self.assertEqual(len({p.x for p in norm}),1)
            assigned=assign_controllers(turn,tuple(u for u in turn.team_our.roles if u.is_weapon))
            self.assertEqual(len(assigned),3)
            self.assertEqual({a.controller.unit_id for a in assigned},{2})
    def test_dead_pioneer_replaced_without_losing_two_guns(self):
        raw=world(71);raw['teamOur']['roles']=[r for r in raw['teamOur']['roles'] if r['id']!=2]
        t=Turn.from_raw(raw);a=assign_controllers(t,tuple(u for u in t.team_our.roles if u.is_weapon))
        self.assertEqual(len(a),3);self.assertEqual(len({i.controller.unit_id for i in a}),1)

class EconomyTests(unittest.TestCase):
    def plan(self,day,full=False):
        raw=world((day-1)*130+10)
        raw['mapInfo']['zones']=[{'pos':{'x':10,'y':13},'neutralType':'vendor'}, {'pos':{'x':11,'y':11},'neutralType':'iron'}]
        worker=next(r for r in raw['teamOur']['roles'] if r['id']==1)
        worker['backpack']=['iron']*10
        if full:worker['backPackCapability']=10
        t=Turn.from_raw(raw);s=WorldState();s.ingest(t);m=EconomyManager()
        return m.plan(t,t.team_our.unit(1),s,DEFAULT_CONFIG,DefenseBudget(0,0,480,12)),m
    def test_days_one_two_do_not_sell_at_vendor(self):
        for day in (1,2):
            p,m=self.plan(day)
            self.assertNotEqual(getattr(p.action,'action_type',None),'sell')
    def test_day_three_sells_actual_inventory(self):
        p,_=self.plan(3);self.assertEqual(p.action.action_type,'sell');self.assertEqual(p.action.quantity,10)

class MilestoneTests(unittest.TestCase):
    def test_day_six_front_four_and_side_are_due(self):
        raw=world(651);t=Turn.from_raw(raw)
        numbers={front_wall_number(t,w) for w in due_defense_targets(t,DEFAULT_CONFIG) if w.role_type=='wall'}
        self.assertTrue({1,2,3,4}<=numbers)
    def test_day_two_no_high_tier_development(self):
        from solution.logistics import _maintenance_options
        t=Turn.from_raw(world(131))
        names=[n for n,w,p in _maintenance_options(t)]
        self.assertNotIn('WeaponUpgradeVoucher2',names)
        self.assertNotIn('StationUpgradeVoucher1',names)

class SchedulingTests(unittest.TestCase):
    def threat(self,raw):
        raw['robot']['roles']=[dict(id=90,roleType='bossRobot',health=9000,pos={'x':23,'y':17},attackRange=2,attackPower=40,targetTeam='challenger')]
    def test_actual_cooldown_gives_three_shots_then_gap(self):
        raw=world(71);self.threat(raw);shots=[]
        for n in range(9):
            raw['roundNo']=71+n;t=Turn.from_raw(raw)
            actions=plan_attacks(t,assign_controllers(t,tuple(w for w in t.team_our.roles if w.is_weapon)),t.robots)
            self.assertLessEqual(len(actions),1)
            shots.append(actions[0].actor_id if actions else None)
            for w in raw['teamOur']['roles']:
                if w['roleType']=='rocket':w['cooldown']=3 if actions and w['id']==actions[0].actor_id else max(0,w['cooldown']-1)
        self.assertEqual(shots,[10,11,12,None,10,11,12,None,10])
    def test_guard_confirmed_only_after_observed_arrival_and_returns(self):
        from solution.roles import GuardHandover
        from solution.movement import schedule_moves
        from solution.grid import OccupancyGrid
        raw=world(71);guard=GuardHandover();confirmed=False;phases=set()
        for n in range(24):
            raw['roundNo']=71+n;t=Turn.from_raw(raw);weapons=tuple(w for w in t.team_our.roles if w.is_weapon)
            a,intents,confirmed=guard.coordinate(t,weapons,DEFAULT_CONFIG,True)
            phases.add(guard.phase)
            if confirmed:
                self.assertEqual(t.team_our.unit(guard.backup_id).pos,build_defense_layout(t).controller_sites[0]);break
            self.assertTrue(any(r.pos.distance_to(w.pos)<=1 for w in weapons for r in t.controllable))
            for action in schedule_moves(t,intents):next(u for u in raw['teamOur']['roles'] if u['id']==action.actor_id)['pos']=action.targets[0].to_raw()
        self.assertTrue(confirmed,phases)
        for n in range(10):
            t=Turn.from_raw(raw);a,intents,away=guard.coordinate(t,weapons,DEFAULT_CONFIG,False)
            if guard.phase=='pioneer_confirmed':break
            for action in schedule_moves(t,intents):next(u for u in raw['teamOur']['roles'] if u['id']==action.actor_id)['pos']=action.targets[0].to_raw()
        self.assertEqual(guard.phase,'pioneer_confirmed')
    def test_third_night_main_miner_still_collects_while_one_supports(self):
        from solution.engine import AgentEngine
        raw=world(331);self.threat(raw)
        raw['mapInfo']['zones']=[{'neutralType':'iron','pos':{'x':12,'y':12}},{'neutralType':'vendor','pos':{'x':12,'y':14}}]
        next(u for u in raw['teamOur']['roles'] if u['id']==1)['backpack']=['WallUpgradeVoucher2']
        engine=AgentEngine();response=engine.decide(raw)
        self.assertEqual(engine.planner.support_id,1)
        self.assertEqual(response['roleCommandMap'].get('7',{}).get('action'),'collect')
        self.assertTrue(any(c['action']=='attack' and str(c['controllerId'])=='2' for c in response['roleCommandMap'].values()))
    def test_main_miner_not_recalled_solely_for_day_three(self):
        from solution.planner import CompetitionPlanner
        raw=world(270);t=Turn.from_raw(raw);s=WorldState();s.ingest(t)
        self.assertNotIn(7,{i.actor_id for i in CompetitionPlanner._individual_recall(t,s,DEFAULT_CONFIG,1)})
    def test_upgrade_and_attack_do_not_share_actor(self):
        from solution.engine import AgentEngine
        raw=world(71);self.threat(raw)
        next(u for u in raw['teamOur']['roles'] if u['id']==2)['backpack']=['WeaponUpgradeVoucher2']
        out=AgentEngine().decide(raw)['roleCommandMap']
        if out.get('2',{}).get('action')=='use':self.assertFalse(any(c.get('controllerId')==2 for c in out.values()))

class MiningSafetyTests(unittest.TestCase):
    def test_near_iron_can_beat_far_copper(self):
        raw=world(275);raw['mapInfo']['zones']=[{'neutralType':'iron','pos':{'x':11,'y':12}}, {'neutralType':'copper','pos':{'x':1,'y':1}}, {'neutralType':'vendor','pos':{'x':10,'y':14}}]
        raw['vendorShopList']=[{'name':'iron','price':3},{'name':'copper','price':5}]
        t=Turn.from_raw(raw);s=WorldState();s.ingest(t);m=EconomyManager()
        p=m.plan(t,t.team_our.unit(1),s,DEFAULT_CONFIG,DefenseBudget(0,0,480,12))
        self.assertEqual(m.evidence[1]['ore'],'iron');self.assertEqual(p.action.action_type,'collect')
    def test_route_not_just_mine_endpoint_avoids_robot(self):
        from solution.movement import schedule_moves
        from solution.route_safety import danger_cells
        raw=world(331);raw['teamOur']['roles'][2]['pos']={'x':1,'y':2}
        raw['mapInfo']['zones']=[{'neutralType':'iron','pos':{'x':13,'y':2}}, {'neutralType':'vendor','pos':{'x':14,'y':4}}]
        raw['robot']['roles']=[dict(id=90,roleType='smallRobot',health=30,pos={'x':7,'y':2},attackRange=2,targetTeam='defender')]
        t=Turn.from_raw(raw);s=WorldState();s.ingest(t);m=EconomyManager()
        p=m.plan(t,t.team_our.unit(1),s,DEFAULT_CONFIG,DefenseBudget(0,0,480,12))
        if p.move:
            danger=danger_cells(t,DEFAULT_CONFIG)
            self.assertEqual(p.move.avoid_cells,danger)
            for a in schedule_moves(t,[p.move]):self.assertNotIn(a.targets[0],danger)
    def test_full_backpack_sells_only_small_capacity_batch(self):
        p,m=EconomyTests().plan(1,True)
        self.assertEqual(p.action.quantity,DEFAULT_CONFIG.mining_minimum_batch)
        self.assertEqual(m.activity[1],'capacity_minimum_sale')
    def test_no_sale_stone_reserved_for_rebuilding(self):
        raw=world(275);raw['mapInfo']['zones']=[{'neutralType':'vendor','pos':{'x':10,'y':13}}]
        next(r for r in raw['teamOur']['roles'] if r['id']==1)['backpack']=['stone']*4
        t=Turn.from_raw(raw);s=WorldState();s.ingest(t);m=EconomyManager(reserve_stone={1:4})
        p=m.plan(t,t.team_our.unit(1),s,DEFAULT_CONFIG,DefenseBudget(0,0,480,12))
        self.assertIsNone(p.action)
    def test_emergency_sale_uses_runtime_gap_and_price(self):
        raw=world(180);raw['teamOur']['goldNum']=95
        next(w for w in raw['teamOur']['roles'] if w['id']==10)['level']=1
        next(r for r in raw['teamOur']['roles'] if r['id']==1)['backpack']=['iron']*20
        raw['mapInfo']['zones']=[{'neutralType':'vendor','pos':{'x':10,'y':13}}]
        t=Turn.from_raw(raw);s=WorldState();s.ingest(t);m=EconomyManager()
        p=m.plan(t,t.team_our.unit(1),s,DEFAULT_CONFIG,DefenseBudget(0,0,95,12))
        self.assertEqual(p.action.quantity,2);self.assertEqual(m.evidence[1]['defense_gap'],5)
    def test_market_recovery_ends_overlapping_closure(self):
        from solution.market import MarketMemory
        m=MarketMemory();m.observe('days 2-5 iron closed',1);m.observe('day 3 iron reopened price=6',2)
        self.assertTrue(m.closed('iron',2));self.assertFalse(m.closed('iron',3));self.assertFalse(m.closed('iron',4))

class DeadlineTests(unittest.TestCase):
    def test_side_a_and_late_day_fixed_array(self):
        from solution.economy import side_wall_a,wall_level_goal
        for side in ('challenger','defender'):
            raw=world(651,side);t=Turn.from_raw(raw)
            sidewall=next(w for w in t.team_our.roles if w.role_type=='wall' and side_wall_a(t,w))
            self.assertEqual(wall_level_goal(t,sidewall),3)
            t=replace(t,round_no=1041)
            self.assertEqual(wall_level_goal(t,sidewall),3)
            for w in t.team_our.roles:
                if front_wall_number(t,w) in (1,2,3,4,5):self.assertEqual(wall_level_goal(t,w),3)
                if front_wall_number(t,w) ==6:self.assertEqual(wall_level_goal(t,w),2)
    def test_future_deadline_is_visible_during_previous_day(self):
        from solution.economy import scheduled_targets
        t=Turn.from_raw(world(430))
        self.assertTrue(any(w.role_type=='station' for w in scheduled_targets(t,DEFAULT_CONFIG)))

class ReplacementTests(unittest.TestCase):
    def test_dead_pioneer_replacement_is_kept_even_during_clear_night(self):
        from solution.engine import AgentEngine
        raw=world(80);raw['teamOur']['roles']=[r for r in raw['teamOur']['roles'] if r['id']!=2]
        engine=AgentEngine();engine.decide(raw)
        self.assertIsNotNone(engine.planner.guard.backup_id)
        self.assertEqual(engine.planner.guard.phase,'enter_common_post')

class ProcurementPriorityTests(unittest.TestCase):
    def test_prior_day_deadline_purchase_precedes_optional_weapon_tier(self):
        from solution.logistics import LogisticsManager
        raw=world(430);raw['teamOur']['goldNum']=130
        raw['mapInfo']['zones']=[{'neutralType':'weaponShop','pos':{'x':10,'y':13}}]
        next(u for u in raw['teamOur']['roles'] if u['id']==1)['roleType']='pioneer'
        t=Turn.from_raw(raw)
        p=LogisticsManager().plan(t,t.team_our.unit(1),DefenseBudget(0,0,130,12),DEFAULT_CONFIG)
        self.assertEqual(p.action.name,'StationUpgradeVoucher1')
