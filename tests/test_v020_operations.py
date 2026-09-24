"""Synthetic regressions for rear access and sale-before-supply cycles."""
import unittest
from tests.test_v013_operations import world
from tests.test_v014_operations import unit, BUDGET
from tests.test_v015_operations import funded_shop
from solution.models import Turn
from solution.rules import DEFAULT_CONFIG
from solution.wall_supply import wall_stock_plan


class SupplyCycleIncidents(unittest.TestCase):
    def test_ore_is_sold_before_upgrade_basket(self):
        raw=funded_shop(6);raw['roundNo']=691
        raw['mapInfo']['zones'].append({'neutralType':'vendor','pos':{'x':11,'y':13}})
        raw['vendorShopList']=[{'name':'copper','price':5},{'name':'stone','price':1}]
        unit(raw,1)['backpack']=['WallFixer']*6+['copper']*47+['stone']*7
        turn=Turn.from_raw(raw)
        plan=wall_stock_plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertEqual((plan.action.action_type,plan.action.name,plan.action.quantity),('sell','copper',47))

    def test_later_day_missing_minimum_does_not_force_morning_shopping(self):
        raw=funded_shop(5);raw['roundNo']=521
        turn=Turn.from_raw(raw)
        plan=wall_stock_plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertFalse(plan.action or plan.move)



from dataclasses import replace
from tests.helpers import role
from solution.geometry import Pos
from solution.actions import Action, ActionType, Decision
from solution.wall_access import GateAccess, gate_sites, inside, planning_grid
from solution.grid import OccupancyGrid, shortest_path
from solution.movement import MoveIntent, schedule_moves
from solution.defense import build_defense_layout
from solution.travel import TravelBudget
from solution.validation import ActionValidator
from solution.wall_supply import WallSupplyCycle, wall_target


def gate_world(side='challenger', round_no=280, closed=True):
    raw=world(round_no,side);turn=Turn.from_raw(raw);frame=turn.coordinate_frame
    for ident,p in ((1,Pos(2,16)),(7,Pos(1,17))):
        unit(raw,ident)['pos']=frame.denormalize(p).to_raw()
        unit(raw,ident)['backpack']=['stone']*7
    if closed:
        for n,p in enumerate(gate_sites(turn,DEFAULT_CONFIG)):
            raw['teamOur']['roles'].append(role(50+n,'wall',p.x,p.y,level=1,health=1000))
    return raw


def apply_actions(raw,actions):
    """Independent, sequential-turn gate oracle: no teleport or stone refund."""
    turn=Turn.from_raw(raw)
    occupied={p for u in turn.team_our.roles+turn.team_enemy.roles for p in u.footprint()}
    destinations=set()
    for a in actions:
        actor=unit(raw,a.actor_id);target=a.targets[0]
        assert turn.team_our.unit(a.actor_id).pos.distance_to(target)==1
        if a.action_type=='remove':
            wall=next(u for u in raw['teamOur']['roles'] if u['roleType']=='wall' and u['pos']==target.to_raw())
            raw['teamOur']['roles'].remove(wall)
        elif a.action_type in ('move','build'):
            assert target not in occupied and target not in destinations
            destinations.add(target)
            if a.action_type=='move':actor['pos']=target.to_raw()
            else:
                assert turn.is_day and a.name=='wall' and 'stone' in actor['backpack']
                actor['backpack'].remove('stone')
                raw['teamOur']['roles'].append(role(max(u['id'] for u in raw['teamOur']['roles'])+1,'wall',target.x,target.y,level=1,health=1000))
        else:raise AssertionError(a)


class GatePassageTests(unittest.TestCase):
    def step(self,raw,access,goals):
        turn=Turn.from_raw(raw)
        actions,intents=access.apply(turn,[],[MoveIntent(k,(p,),110) for k,p in goals.items()],DEFAULT_CONFIG,1)
        actions+=schedule_moves(turn,intents,occupied_destinations=[p for a in actions if a.action_type=='build' for p in a.targets])
        validated=ActionValidator().validate(turn,Decision(tuple(actions)))
        self.assertFalse(validated.issues)
        apply_actions(raw,actions)
        raw['roundNo']+=1
        return actions

    def test_closed_geometry_blocks_entry_but_keeps_three_gun_post(self):
        for side in ('challenger','defender'):
            turn=Turn.from_raw(gate_world(side));layout=build_defense_layout(turn)
            grid=OccupancyGrid.from_turn(turn,ignore_unit_ids=(1,7))
            frame=turn.coordinate_frame
            self.assertEqual(set(gate_sites(turn,DEFAULT_CONFIG)),{frame.denormalize(Pos(3,15)),frame.denormalize(Pos(3,16))})
            self.assertFalse(shortest_path(grid,turn.team_our.unit(1).pos,(frame.denormalize(Pos(7,16)),)))
            self.assertTrue(all(layout.controller_sites[0].distance_to(w)==1 for w in layout.weapon_sites[:3]))
            self.assertNotIn(layout.controller_sites[0],gate_sites(turn,DEFAULT_CONFIG))

    def test_both_sides_enter_reseal_exit_reseal(self):
        for side in ('challenger','defender'):
            raw=gate_world(side);frame=Turn.from_raw(raw).coordinate_frame;access=GateAccess();history=[]
            for goal in (Pos(7,16),Pos(1,17)):
                # Keep the second worker clear of the exit destination.
                unit(raw,7)['pos']=frame.denormalize(Pos(1,19)).to_raw()
                for _ in range(20):
                    history.extend(self.step(raw,access,{1:frame.denormalize(goal)}))
                    if unit(raw,1)['pos']==frame.denormalize(goal).to_raw() and access.actor is None:break
                self.assertEqual(unit(raw,1)['pos'],frame.denormalize(goal).to_raw())
                self.assertEqual(sum(w.pos in gate_sites(Turn.from_raw(raw),DEFAULT_CONFIG) for w in Turn.from_raw(raw).team_our.roles if w.role_type=='wall'),2)
            self.assertEqual(sum(a.action_type=='remove' for a in history),2)
            self.assertEqual(sum(a.action_type=='build' for a in history),2)
            self.assertEqual(unit(raw,1)['backpack'].count('stone'),5)

    def test_day_ten_helper_queues_and_both_finish_inside(self):
        for side in ('challenger','defender'):
            raw=gate_world(side,1210);frame=Turn.from_raw(raw).coordinate_frame;access=GateAccess();history=[]
            goals={1:frame.denormalize(Pos(7,16)),7:frame.denormalize(Pos(7,15))}
            for _ in range(25):history.extend(self.step(raw,access,goals))
            self.assertTrue(all(unit(raw,i)['pos']==p.to_raw() for i,p in goals.items()))
            self.assertEqual(sum(a.action_type=='remove' for a in history),2)
            self.assertEqual(sum(a.action_type=='build' for a in history),2)
            self.assertEqual([unit(raw,i)['backpack'].count('stone') for i in (1,7)],[6,6])

    def test_enemy_near_gate_prevents_deliberate_opening(self):
        raw=gate_world();raw['teamEnemy']['roles']=[role(90,'worker',2,18)]
        actions=self.step(raw,GateAccess(),{1:Pos(7,16)})
        self.assertFalse(any(a.action_type=='remove' for a in actions))

    def test_night_and_late_day_do_not_open_for_normal_trip(self):
        for r in (330,331):
            raw=gate_world(round_no=r)
            actions=self.step(raw,GateAccess(),{1:Pos(7,16)})
            self.assertFalse(any(a.action_type in ('remove','build') for a in actions))

    def test_gate_never_builds_on_intruder_and_failed_crossing_is_bounded(self):
        raw=gate_world();access=GateAccess()
        self.step(raw,access,{1:Pos(7,16)})
        raw['teamEnemy']['roles']=[role(90,'worker',access.gate.x,access.gate.y)]
        for _ in range(8):
            actions=self.step(raw,access,{1:Pos(7,16)})
            self.assertFalse(any(a.action_type=='build' for a in actions))
        self.assertIsNone(access.actor)
        self.assertTrue(access.retry_after)

    def test_no_stone_no_removal_and_no_enemy_wall_demolition(self):
        raw=gate_world();unit(raw,1)['backpack']=[]
        self.assertFalse(any(a.action_type=='remove' for a in self.step(raw,GateAccess(),{1:Pos(7,16)})))
        raw['teamEnemy']['roles']=[role(90,'wall',1,16)]
        turn=Turn.from_raw(raw)
        result=ActionValidator().validate(turn,Decision((Action(1,ActionType.REMOVE,targets=(Pos(1,16),)),)))
        self.assertFalse(result.actions);self.assertTrue(result.issues)

    def test_builds_two_level_one_shutters_without_enclosing_pioneer(self):
        raw=gate_world(closed=False);access=GateAccess()
        for _ in range(8):self.step(raw,access,{})
        turn=Turn.from_raw(raw);gates=[w for w in turn.team_our.roles if w.pos in gate_sites(turn,DEFAULT_CONFIG)]
        self.assertEqual(len(gates),2);self.assertTrue(all(w.level==1 and wall_target(turn,w)==1 for w in gates))
        raw=gate_world(closed=False);unit(raw,2)['pos']={'x':7,'y':16}
        self.assertFalse(any(a.action_type=='build' for a in self.step(raw,GateAccess(),{1:Pos(2,16)})))

    def test_route_cost_includes_remove_and_rebuild_and_helper_queue(self):
        raw=gate_world();turn=Turn.from_raw(raw);worker=turn.team_our.unit(1)
        trip=TravelBudget.for_role(turn,worker,DEFAULT_CONFIG,wall_support=True)
        path=shortest_path(trip.grid,worker.pos,trip.goals)
        self.assertEqual(trip.cost(),len(path)-1+2)
        raw['roundNo']=1210;final=Turn.from_raw(raw)
        self.assertEqual(TravelBudget.for_role(final,final.team_our.unit(1),DEFAULT_CONFIG,wall_support=True).margin,trip.margin+4)


class SupplyCycleTests(unittest.TestCase):
    def test_latched_cycle_sells_both_ores_before_any_purchase(self):
        raw=funded_shop(6);raw['roundNo']=691
        raw['mapInfo']['zones'].append({'neutralType':'vendor','pos':{'x':11,'y':13}})
        raw['vendorShopList']=[{'name':'copper','price':5},{'name':'iron','price':3},{'name':'stone','price':1}]
        worker=unit(raw,1);worker['backpack']=['copper']*37+['iron']*8+['stone']*7+['Medicine']*2
        cycle=WallSupplyCycle();sold=[]
        for _ in range(2):
            turn=Turn.from_raw(raw);plan=cycle.plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
            self.assertEqual(plan.action.action_type,'sell');sold.append(plan.action.name)
            for _ in range(plan.action.quantity):worker['backpack'].remove(plan.action.name)
            raw['roundNo']+=1
        self.assertEqual(set(sold),{'iron','copper'});self.assertEqual(worker['backpack'].count('stone'),7)
        turn=Turn.from_raw(raw);plan=cycle.plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertEqual(plan.action.action_type,'buy');self.assertEqual(plan.action.name,'WallFixer')

    def test_full_basket_returns_instead_of_starting_new_mining_trip(self):
        raw=funded_shop(6);raw['roundNo']=700;cycle=WallSupplyCycle(active={1},day=6)
        unit(raw,1)['backpack']=['WallFixer']*15+['WallUpgradeVoucher1']*7+['WallUpgradeVoucher2']*6+['stone']*7
        turn=Turn.from_raw(raw);plan=cycle.plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertEqual(plan.reason,'wall_cycle_return');self.assertTrue(plan.move)
        self.assertIn(1,cycle.finished)

    def test_no_budget_waits_only_until_return_deadline(self):
        raw=funded_shop(6);raw['roundNo']=700;raw['teamOur']['goldNum']=0
        cycle=WallSupplyCycle(active={1},day=6)
        turn=Turn.from_raw(raw);plan=cycle.plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertEqual(plan.reason,'wall_stock_funding_gap')
        raw['roundNo']=717;turn=Turn.from_raw(raw)
        plan=cycle.plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertEqual(plan.reason,'wall_cycle_return_shortfall')

class PlannerIntegrationTests(unittest.TestCase):
    def test_sale_supply_return_and_both_final_workers_use_sealed_entry(self):
        from solution.engine import AgentEngine
        from tools.diagnostics.synthetic_replay import SyntheticWorld
        from copy import deepcopy
        for side in ('challenger','defender'):
            for day in (6,10):
                with self.subTest(side=side,day=day):
                    start=(day-1)*130+25
                    raw=gate_world(side,start);turn=Turn.from_raw(raw);frame=turn.coordinate_frame
                    unit(raw,1)['pos']=frame.denormalize(Pos(7,16)).to_raw()
                    unit(raw,1)['backpack']+=['copper']*43+['iron']*4
                    unit(raw,7)['backpack']+=['copper']*6
                    for u in raw['teamOur']['roles']:
                        if u['roleType']=='wall':u['level']=wall_target(turn,turn.team_our.unit(u['id']))
                        if u['roleType'] in ('rocket','station'):u['level']=3
                    raw['mapInfo']['zones']=[{'neutralType':n,'pos':frame.denormalize(p).to_raw()} for n,p in
                                            [('vendor',Pos(10,12)),('weaponShop',Pos(11,14)),('stone',Pos(1,19)),('copper',Pos(1,20))]]
                    raw['vendorShopList']=[{'name':'copper','price':5},{'name':'iron','price':3},{'name':'stone','price':1}]
                    world= SyntheticWorld(side);world.roles=deepcopy(raw['teamOur']['roles']);world.gold=raw['teamOur']['goldNum']
                    world.map_width=30;world.map_height=24;world.zones=raw['mapInfo']['zones'];world.robots=[]
                    world.shop={i['name']:i['price'] for i in raw['weaponShopList']};world.prices={'copper':5,'iron':3,'stone':1};world.next_id=100
                    engine=AgentEngine();history=[];issues=[]
                    class Validator(ActionValidator):
                        def validate(self,t,d):
                            result=super().validate(t,d);issues.extend(result.issues);return result
                    engine.validator=Validator()
                    for r in range(start,(day-1)*130+71):
                        raw['roundNo']=r;raw['teamOur']['roles']=world.roles;raw['teamOur']['goldNum']=world.gold
                        world.round_no=r
                        response=engine.decide(raw)
                        history.extend((r,int(actor),c['action'],c.get('name','')) for actor,c in response['roleCommandMap'].items())
                        world.apply(response)
                        self.assertFalse(any(ok is False for ok in world.feedback.values()),(r,response))
                    self.assertFalse(issues);self.assertEqual(engine.planner.failure_count,0)
                    turn=Turn.from_raw(raw)
                    self.assertTrue(all(any(w.role_type=='wall' and w.pos==p for w in turn.team_our.roles) for p in gate_sites(turn,DEFAULT_CONFIG)),engine.planner.wall_access.status)
                    engineer=turn.team_our.unit(engine.planner.engineer_id)
                    self.assertTrue(inside(turn,engineer.pos),(engineer.pos,history[-15:]))
                    self.assertEqual(engineer.backpack.count('WallFixer'),15)
                    self.assertFalse(any(n in engineer.backpack for n in ('copper','iron')))
                    for ore in ('copper','iron'):
                        self.assertLess(next(r for r,a,c,n in history if a==engineer.unit_id and c=='sell' and n==ore),next(r for r,a,c,n in history if a==engineer.unit_id and c=='buy'))
                    if day==10:
                        helper=turn.team_our.unit(engine.planner.economy.main_miner_id)
                        self.assertTrue(inside(turn,helper.pos),(helper.pos,history[-15:]))
                        self.assertEqual(helper.backpack.count('WallFixer'),5)
                        self.assertEqual(engine.planner.economy.reserve_stone[helper.unit_id],7)
                        self.assertTrue(any(a==helper.unit_id and c=='remove' for r,a,c,n in history))

class EmptyHandedHelperTests(unittest.TestCase):
    def test_final_helper_collects_stone_before_closed_gate_recall(self):
        from solution.engine import AgentEngine
        raw=gate_world(round_no=1171)
        unit(raw,1)['backpack']+=['WallFixer']*15+['WallUpgradeVoucher2']*6
        unit(raw,7)['backpack']=[];unit(raw,7)['pos']={'x':1,'y':18}
        raw['mapInfo']['zones']=[{'neutralType':'stone','pos':{'x':1,'y':19}}]
        engine=AgentEngine()
        for count in range(7):
            raw['roundNo']=1171+count
            response=engine.decide(raw)['roleCommandMap']
            self.assertEqual(response.get('7',{}).get('action'),'collect',(count,response))
            unit(raw,7)['backpack'].append('stone')
        self.assertEqual(unit(raw,7)['backpack'].count('stone'),7)
        self.assertEqual(engine.planner.failure_count,0)

    def test_full_helper_backpack_liquidates_ore_before_getting_gate_stone(self):
        from solution.wall_supply import gate_stone_plan
        raw=gate_world(round_no=1171)
        unit(raw,7)['pos']={'x':1,'y':18};unit(raw,7)['backpack']=['copper']*100
        raw['mapInfo']['zones']=[{'neutralType':'stone','pos':{'x':1,'y':19}},{'neutralType':'vendor','pos':{'x':2,'y':18}}]
        raw['vendorShopList']=[{'name':'copper','price':5}]
        turn=Turn.from_raw(raw);plan=gate_stone_plan(turn,turn.team_our.unit(7),DEFAULT_CONFIG)
        self.assertEqual((plan.action.action_type,plan.action.name,plan.action.quantity),('sell','copper',100))

    def test_ordinary_miner_refuge_never_targets_virtual_gate_cells(self):
        raw=gate_world(round_no=1100);turn=Turn.from_raw(raw)
        trip=TravelBudget.for_role(turn,turn.team_our.unit(7),DEFAULT_CONFIG,worker_refuge=True)
        self.assertTrue(trip.goals)
        self.assertFalse(set(trip.goals)&set(gate_sites(turn,DEFAULT_CONFIG)))
