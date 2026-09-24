"""Synthetic regressions for the three changes authorized on the v0.18 baseline."""
import unittest
from unittest.mock import patch
from tests.test_v013_operations import world
from tests.test_v014_operations import unit, BUDGET
from tests.test_v015_operations import funded_shop
from solution.models import Turn
from solution.geometry import Pos
from solution.rules import DEFAULT_CONFIG
from solution.state import WorldState
from solution.economy import EconomyManager
from solution.wall_supply import wall_stock_plan, WallSupplyCycle, wall_target
from solution.maintenance import support_plan
from solution.defense import wall_support_post
from solution.economy import front_wall_number, side_wall_a
from solution.travel import TravelBudget
from solution.movement import schedule_moves


class RequestedFixes(unittest.TestCase):
    def test_miner_collects_across_midline_on_both_sides(self):
        for side in ('challenger','defender'):
            raw=world(790,side);frame=Turn.from_raw(raw).coordinate_frame
            unit(raw,7)['pos']=frame.denormalize(Pos(16,20)).to_raw()
            raw['mapInfo']['zones']=[{'neutralType':n,'pos':frame.denormalize(p).to_raw()} for n,p in
                                     [('copper',Pos(17,20)),('vendor',Pos(16,22))]]
            raw['vendorShopList']=[{'name':'copper','price':5}]
            turn=Turn.from_raw(raw);state=WorldState();state.ingest(turn)
            plan=EconomyManager(main_miner_id=7).plan(turn,turn.team_our.unit(7),state,DEFAULT_CONFIG,BUDGET)
            self.assertIsNotNone(plan.action)
            self.assertEqual(plan.action.action_type,'collect')
            self.assertEqual(plan.action.targets,(frame.denormalize(Pos(17,20)),))

    def test_builder_collects_stone_across_midline(self):
        from solution.engine import AgentEngine
        for side in ('challenger','defender'):
            raw=world(400,side);frame=Turn.from_raw(raw).coordinate_frame
            raw['teamOur']['roles']=[r for r in raw['teamOur']['roles'] if r['roleType']!='wall']
            unit(raw,1)['pos']=frame.denormalize(Pos(16,20)).to_raw()
            unit(raw,1)['backpack']=['WallFixer']
            unit(raw,7)['pos']=frame.denormalize(Pos(25,20)).to_raw()
            raw['mapInfo']['zones']=[{'neutralType':'stone','pos':frame.denormalize(Pos(17,20)).to_raw()}]
            response=AgentEngine().decide(raw)['roleCommandMap']
            self.assertEqual(response.get('1',{}).get('action'),'collect')

    def test_sell_ore_before_wall_vouchers_even_when_cash_is_sufficient(self):
        raw=funded_shop(6);raw['roundNo']=700
        raw['mapInfo']['zones'].append({'neutralType':'vendor','pos':{'x':11,'y':13}})
        raw['vendorShopList']=[{'name':'copper','price':5},{'name':'iron','price':3}]
        unit(raw,1)['backpack']=['WallFixer']*6+['copper']*41+['stone']*5
        turn=Turn.from_raw(raw);plan=wall_stock_plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertEqual((plan.action.action_type,plan.action.name,plan.action.quantity),('sell','copper',41))

    def test_funded_morning_keeps_late_procurement_timing(self):
        for day in (3,5,6):
            raw=funded_shop(day);raw['roundNo']=(day-1)*130+1
            turn=Turn.from_raw(raw);plan=wall_stock_plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
            self.assertFalse(plan.action or plan.move)


def supply_scene(day=6, side='challenger'):
    raw=world((day-1)*130+36,side);turn=Turn.from_raw(raw);frame=turn.coordinate_frame
    for r in raw['teamOur']['roles']:
        if r['roleType']=='wall':r.update(level=wall_target(turn,turn.team_our.unit(r['id'])),health=2000)
        if r['roleType']=='rocket':r['level']=3
        if r['roleType']=='station':r.update(level=3,health=4500)
    raw['mapInfo']['zones']=[{'neutralType':kind,'pos':frame.denormalize(p).to_raw()} for kind,p in
                             [('vendor',Pos(12,13)),('weaponShop',Pos(15,13))]]
    raw['vendorShopList']=[{'name':'copper','price':5},{'name':'iron','price':3},{'name':'stone','price':1}]
    unit(raw,1)['pos']=frame.denormalize(Pos(11,12)).to_raw()
    unit(raw,1)['backpack']=['stone']*5+['copper']*41+['iron']*12
    unit(raw,7)['pos']=frame.denormalize(Pos(11,14)).to_raw()
    raw['teamOur']['goldNum']=500
    return raw


class SupplyCycleTests(unittest.TestCase):
    def test_sale_purchase_return_cycle_on_both_sides(self):
        for side in ('challenger','defender'):
            raw=supply_scene(side=side);cycle=WallSupplyCycle();events=[];returned=False
            for _ in range(35):
                turn=Turn.from_raw(raw);worker=turn.team_our.unit(1)
                plan=cycle.plan(turn,worker,BUDGET,DEFAULT_CONFIG)
                self.assertNotEqual(plan.reason,'mine_before_wall_procurement')
                if plan.action:
                    a=plan.action;events.append((a.action_type,a.name,a.quantity))
                    if a.action_type=='sell':
                        for _ in range(a.quantity):unit(raw,1)['backpack'].remove(a.name)
                        raw['teamOur']['goldNum']+=a.quantity*next(i.price for i in turn.vendor_shop if i.name==a.name)
                    else:
                        unit(raw,1)['backpack'] += [a.name]*a.quantity
                        raw['teamOur']['goldNum']-=a.quantity*next(i.price for i in turn.weapon_shop if i.name==a.name)
                elif plan.move:
                    for a in schedule_moves(turn,[plan.move]):unit(raw,1)['pos']=a.targets[0].to_raw()
                if plan.reason=='wall_cycle_return' and Pos.from_raw(unit(raw,1)['pos'])==wall_support_post(turn,DEFAULT_CONFIG):
                    returned=True;break
                raw['roundNo']+=1
            self.assertEqual(events[:2],[('sell','copper',41),('sell','iron',12)])
            self.assertTrue(all(e[0]=='buy' for e in events[2:]))
            self.assertEqual(unit(raw,1)['backpack'].count('stone'),5)
            self.assertEqual(unit(raw,1)['backpack'].count('WallFixer'),15)
            self.assertTrue(returned)
            self.assertTrue(Turn.from_raw(raw).is_day)

    def test_shortfall_waits_then_returns_by_deadline(self):
        raw=supply_scene();unit(raw,1)['backpack']=['stone']*5;raw['teamOur']['goldNum']=0
        turn=Turn.from_raw(raw);cycle=WallSupplyCycle(day=6,active={1})
        plan=cycle.plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertEqual(plan.move.goals,(turn.team_our.unit(1).pos,))
        raw['roundNo']=719;turn=Turn.from_raw(raw)
        plan=cycle.plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertEqual(plan.reason,'wall_cycle_return_shortfall')
        self.assertEqual(plan.move.goals,(wall_support_post(turn,DEFAULT_CONFIG),))

    def test_helper_sells_before_final_day_purchase(self):
        raw=supply_scene(day=10);unit(raw,1)['backpack']=['WallFixer']*15
        raw['roundNo']=1210
        unit(raw,7)['backpack']=['copper']*50+['stone']*5
        turn=Turn.from_raw(raw);plan=WallSupplyCycle().plan(turn,turn.team_our.unit(7),BUDGET,DEFAULT_CONFIG,helper=True,engineer=turn.team_our.unit(1))
        self.assertEqual((plan.action.action_type,plan.action.name,plan.action.quantity),('sell','copper',50))

    def test_first_two_days_do_not_run_wall_procurement(self):
        for day in (1,2):
            raw=supply_scene(day);turn=Turn.from_raw(raw)
            plan=WallSupplyCycle().plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
            self.assertFalse(plan.action or plan.move)

    def test_full_trip_includes_sales_and_return_before_buying(self):
        raw=supply_scene();raw['roundNo']=719
        turn=Turn.from_raw(raw);plan=wall_stock_plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertFalse(plan.action or plan.move)
        self.assertEqual(plan.reason,'wall_stock_return_deadline')


def support_scene(side='challenger'):
    raw=world(851,side);turn=Turn.from_raw(raw)
    for r in raw['teamOur']['roles']:
        if r['roleType']=='wall':
            level=wall_target(turn,turn.team_our.unit(r['id']));r.update(level=level,health=500+500*level)
    unit(raw,1)['pos']=wall_support_post(turn,DEFAULT_CONFIG).to_raw()
    unit(raw,1)['backpack']=['WallFixer']*6
    return raw


class WallPostTests(unittest.TestCase):
    def test_return_budget_targets_third_wall_on_both_sides(self):
        for side in ('challenger','defender'):
            raw=support_scene(side);raw['roundNo']=840;turn=Turn.from_raw(raw)
            core=next(w for w in turn.team_our.roles if front_wall_number(turn,w)==3)
            wall=turn.coordinate_frame.normalize(core.pos);post=wall_support_post(turn,DEFAULT_CONFIG)
            self.assertEqual(turn.coordinate_frame.normalize(post),Pos(wall.x-1,wall.y))
            self.assertEqual(TravelBudget.for_role(turn,turn.team_our.unit(1),DEFAULT_CONFIG,wall_support=True).goals,(post,))

    def test_upgraded_wall_precedes_unupgraded_without_imminent_collapse(self):
        raw=support_scene();turn=Turn.from_raw(raw)
        core=next(w for w in turn.team_our.roles if front_wall_number(turn,w)==3)
        other=next(w for w in turn.team_our.roles if front_wall_number(turn,w)==2)
        unit(raw,core.unit_id)['health']=600
        unit(raw,other.unit_id).update(level=1,health=250)
        turn=Turn.from_raw(raw);plan=support_plan(turn,turn.team_our.unit(1),DEFAULT_CONFIG,())
        self.assertEqual(plan.action.targets,(core.pos,))

    def test_imminent_lower_level_wall_still_wins(self):
        raw=support_scene();turn=Turn.from_raw(raw)
        core=next(w for w in turn.team_our.roles if front_wall_number(turn,w)==3)
        other=next(w for w in turn.team_our.roles if front_wall_number(turn,w)==2)
        unit(raw,core.unit_id)['health']=600;unit(raw,other.unit_id).update(level=1,health=100)
        risk=lambda w,*_: (60,60) if w.unit_id==other.unit_id else ((30,30) if w.unit_id==core.unit_id else (0,0))
        turn=Turn.from_raw(raw)
        with patch('solution.maintenance.wall_damage_risk',side_effect=risk):
            plan=support_plan(turn,turn.team_our.unit(1),DEFAULT_CONFIG,())
        self.assertEqual(plan.action.targets,(other.pos,))

    def test_defer_side_trip_if_core_cannot_survive_return_then_repair_and_return(self):
        for side in ('challenger','defender'):
            raw=support_scene(side);turn=Turn.from_raw(raw)
            core=next(w for w in turn.team_our.roles if front_wall_number(turn,w)==3)
            flank=next(w for w in turn.team_our.roles if side_wall_a(turn,w))
            unit(raw,core.unit_id)['health']=900;unit(raw,flank.unit_id)['health']=300
            risk=lambda w,*_: (250,250) if w.unit_id==core.unit_id else ((10,10) if w.unit_id==flank.unit_id else (0,0))
            with patch('solution.maintenance.wall_damage_risk',side_effect=risk):
                turn=Turn.from_raw(raw);plan=support_plan(turn,turn.team_our.unit(1),DEFAULT_CONFIG,())
                self.assertEqual(plan.reason,'support_hold_protected')
                unit(raw,core.unit_id)['health']=700;turn=Turn.from_raw(raw)
                plan=support_plan(turn,turn.team_our.unit(1),DEFAULT_CONFIG,())
                self.assertEqual(plan.action.targets,(core.pos,))
                unit(raw,core.unit_id)['health']=2000;turn=Turn.from_raw(raw)
                plan=support_plan(turn,turn.team_our.unit(1),DEFAULT_CONFIG,())
                self.assertEqual(plan.reason,'reachable_wall_rescue')
            repaired=False;returned=False
            for _ in range(12):
                turn=Turn.from_raw(raw);plan=support_plan(turn,turn.team_our.unit(1),DEFAULT_CONFIG,())
                if plan.action:
                    self.assertEqual(plan.action.targets,(flank.pos,));unit(raw,flank.unit_id)['health']=2000;repaired=True
                elif plan.move:
                    for a in schedule_moves(turn,[plan.move]):unit(raw,1)['pos']=a.targets[0].to_raw()
                if repaired and Pos.from_raw(unit(raw,1)['pos'])==wall_support_post(turn,DEFAULT_CONFIG):returned=True;break
            self.assertTrue(repaired and returned)

    def test_occupied_post_does_not_displace_helper(self):
        raw=support_scene();turn=Turn.from_raw(raw);post=wall_support_post(turn,DEFAULT_CONFIG)
        unit(raw,7)['pos']=post.to_raw();p=turn.coordinate_frame.normalize(post)
        unit(raw,1)['pos']=turn.coordinate_frame.denormalize(Pos(p.x,p.y+1)).to_raw()
        turn=Turn.from_raw(raw);plan=support_plan(turn,turn.team_our.unit(1),DEFAULT_CONFIG,())
        self.assertNotIn(post,plan.move.goals)

    def test_planner_returns_to_post_even_after_wave_clears(self):
        from solution.engine import AgentEngine
        raw=support_scene();turn=Turn.from_raw(raw);post=wall_support_post(turn,DEFAULT_CONFIG)
        p=turn.coordinate_frame.normalize(post)
        unit(raw,1)['pos']=turn.coordinate_frame.denormalize(Pos(p.x,p.y+1)).to_raw()
        engine=AgentEngine();out=engine.decide(raw)['roleCommandMap']
        self.assertEqual(engine.planner.economy.activity[1],'support_return_to_post')
        self.assertEqual(out['1']['action'],'move')
        self.assertEqual(out['1']['targetPos'],[post.to_raw()])


class PlannerCycleTests(unittest.TestCase):
    def test_engineer_and_final_helper_finish_sale_supply_and_return(self):
        from copy import deepcopy
        from solution.engine import AgentEngine
        from solution.validation import ActionValidator
        from tools.diagnostics.synthetic_replay import SyntheticWorld
        for side in ('challenger','defender'):
            for day in (6,10):
                raw=supply_scene(day,side);start=(day-1)*130+25
                turn=Turn.from_raw(raw)
                unit(raw,1)['pos']=wall_support_post(turn,DEFAULT_CONFIG).to_raw()
                unit(raw,1)['backpack']+=['WallFixer']
                unit(raw,7)['backpack']=['copper']*17
                world=SyntheticWorld(side);world.roles=deepcopy(raw['teamOur']['roles']);world.gold=raw['teamOur']['goldNum']
                world.map_width=30;world.map_height=24;world.zones=raw['mapInfo']['zones'];world.robots=[]
                world.shop={i['name']:i['price'] for i in raw['weaponShopList']};world.prices={'copper':5,'iron':3,'stone':1};world.next_id=100
                engine=AgentEngine();history=[];issues=[]
                class Validator(ActionValidator):
                    def validate(self,t,d):
                        result=super().validate(t,d);issues.extend(result.issues);return result
                engine.validator=Validator()
                for r in range(start,(day-1)*130+71):
                    raw['roundNo']=r;raw['teamOur']['roles']=world.roles;raw['teamOur']['goldNum']=world.gold
                    raw['lastRoundRoleActionResults']=world.feedback;world.round_no=r
                    response=engine.decide(raw)
                    history.extend((r,int(actor),c['action'],c.get('name','')) for actor,c in response['roleCommandMap'].items())
                    world.apply(response)
                    self.assertFalse(any(ok is False for ok in world.feedback.values()),(r,response))
                self.assertFalse(issues);self.assertEqual(engine.planner.failure_count,0)
                turn=Turn.from_raw(raw);engineer=turn.team_our.unit(engine.planner.engineer_id)
                self.assertLessEqual(engineer.pos.distance_to(wall_support_post(turn,DEFAULT_CONFIG)),1,(side,day,engineer.pos,engineer.backpack,history[-25:],engine.planner.economy.activity))
                self.assertEqual(engineer.backpack.count('WallFixer'),15)
                self.assertEqual(engineer.backpack.count('stone'),5)
                self.assertFalse(any(n in engineer.backpack for n in ('copper','iron')))
                for ore in ('copper','iron'):
                    self.assertLess(next(r for r,a,c,n in history if a==engineer.unit_id and c=='sell' and n==ore),next(r for r,a,c,n in history if a==engineer.unit_id and c=='buy'))
                if day==10:
                    helper=turn.team_our.unit(engine.planner.economy.main_miner_id)
                    self.assertLessEqual(helper.pos.distance_to(wall_support_post(turn,DEFAULT_CONFIG)),1)
                    self.assertEqual(helper.backpack.count('WallFixer'),5)
                    self.assertNotIn('copper',helper.backpack)
