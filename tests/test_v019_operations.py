"""Synthetic incidents for income, persistent development and rescue scheduling."""
import unittest
from dataclasses import replace

from tests.test_v013_operations import world
from tests.test_v014_operations import unit
from tests.test_v015_operations import funded_shop, protected_scene
from tests.test_treasure import prepared, ingest
from solution.models import Turn
from solution.rules import DEFAULT_CONFIG
from solution.economy import EconomyManager, defense_budget, front_wall_number, side_wall_a
from solution.logistics import LogisticsManager
from solution.state import WorldState
from solution.planner import CompetitionPlanner
from solution.route_safety import danger_cells, escape_intent
from solution.wall_supply import wall_stock_plan, wall_use_item, worker_medicine_plan
from solution.travel import TravelBudget
from solution.maintenance import support_plan
from solution.geometry import Pos


class OperatingIncidents(unittest.TestCase):
    def test_miner_can_choose_only_available_resource_across_midline(self):
        for side in ('challenger', 'defender'):
            raw=world(791,side);turn=Turn.from_raw(raw)
            mine=turn.coordinate_frame.denormalize(Pos(17,12))
            raw['mapInfo']['zones']=[{'neutralType':'iron','pos':mine.to_raw()},
                                    {'neutralType':'vendor','pos':{'x':15,'y':17}}]
            turn=Turn.from_raw(raw);state=WorldState();state.ingest(turn)
            manager=EconomyManager(main_miner_id=7)
            plan=manager.plan(turn,turn.team_our.unit(7),state,DEFAULT_CONFIG,defense_budget(turn,DEFAULT_CONFIG))
            self.assertTrue(plan.action or plan.move)
            self.assertEqual(manager.mines[7],mine)

    def test_late_main_miner_is_recalled_without_wall_duties(self):
        raw=world(848);unit(raw,7)['pos']={'x':18,'y':2}
        turn=Turn.from_raw(raw);state=WorldState();state.ingest(turn)
        intents=CompetitionPlanner._individual_recall(turn,state,DEFAULT_CONFIG,1)
        self.assertIn(7,{i.actor_id for i in intents})

    def test_wall_deadlines_do_not_remove_funded_weapon_topup(self):
        raw=funded_shop(6);raw['teamOur']['goldNum']=362
        for u in raw['teamOur']['roles']:
            if u['roleType']=='rocket':u.update(level=3,health=2000)
        unit(raw,10).update(level=2,health=1500)
        turn=Turn.from_raw(raw)
        plan=LogisticsManager(weapon_buyer_id=2,support_id=1).plan(
            turn,turn.team_our.unit(2),defense_budget(turn,DEFAULT_CONFIG),DEFAULT_CONFIG)
        self.assertIsNotNone(plan.action)
        self.assertEqual((plan.action.name,plan.action.quantity),('WeaponUpgradeVoucher2',1))

    def test_third_day_minimum_wall_inventory_is_five(self):
        raw=funded_shop();turn=Turn.from_raw(raw)
        plan=wall_stock_plan(turn,turn.team_our.unit(1),defense_budget(turn,DEFAULT_CONFIG),DEFAULT_CONFIG)
        self.assertEqual((plan.action.name,plan.action.quantity),('WallFixer',5))

    def test_minimum_stock_liquidates_ore_and_keeps_rebuild_stones(self):
        raw=funded_shop();raw['teamOur']['goldNum']=0
        raw['mapInfo']['zones'].append({'neutralType':'vendor','pos':{'x':11,'y':13}})
        raw['vendorShopList']=[{'name':'iron','price':7},{'name':'stone','price':3}]
        unit(raw,1)['backpack']=['iron']*10+['stone']*5
        turn=Turn.from_raw(raw)
        plan=wall_stock_plan(turn,turn.team_our.unit(1),defense_budget(turn,DEFAULT_CONFIG),DEFAULT_CONFIG)
        self.assertEqual((plan.action.action_type,plan.action.name,plan.action.quantity),('sell','iron',10))

    def test_minimum_stock_has_priority_even_with_missing_wall(self):
        from solution.engine import AgentEngine
        raw=funded_shop();raw['teamOur']['roles']=[u for u in raw['teamOur']['roles'] if u['id']!=20]
        unit(raw,1)['backpack']=['stone']*5
        engine=AgentEngine();out=engine.decide(raw)['roleCommandMap']
        self.assertEqual(out['1']['name'],'WallFixer')
        self.assertEqual(out['1']['num'],5)
        self.assertEqual(engine.planner.failure_count,0)

    def test_small_stock_can_fit_when_whole_wall_basket_cannot(self):
        raw=funded_shop();unit(raw,1)['backpack']=['WallFixer']*4
        turn=Turn.from_raw(raw);worker=turn.team_our.unit(1)
        trip=TravelBudget.for_role(turn,worker,DEFAULT_CONFIG,wall_support=True)
        remaining=trip.cost((((worker.pos,),1),))+trip.margin+1
        raw['roundNo']=331-remaining
        turn=Turn.from_raw(raw)
        plan=wall_stock_plan(turn,turn.team_our.unit(1),defense_budget(turn,DEFAULT_CONFIG),DEFAULT_CONFIG)
        self.assertEqual((plan.action.name,plan.action.quantity),('WallFixer',1))

    def test_full_wall_basket_waits_for_rebuilding_after_minimum_stock(self):
        raw=funded_shop();unit(raw,1)['backpack']=['WallFixer']*5
        turn=Turn.from_raw(raw)
        plan=wall_stock_plan(turn,turn.team_our.unit(1),defense_budget(turn,DEFAULT_CONFIG),DEFAULT_CONFIG,minimum_only=True)
        self.assertFalse(plan.action or plan.move)

    def test_returning_worker_yields_occupied_gun_goal(self):
        from solution.movement import MoveIntent, schedule_moves
        raw=world(850);unit(raw,2)['pos']={'x':22,'y':12};unit(raw,7)['pos']={'x':22,'y':14}
        turn=Turn.from_raw(raw)
        # The worker is crossing the gun destination, and its own nearest
        # refuge lies on the gunner's approach. It must make room off that path.
        moves=schedule_moves(turn,[MoveIntent(2,(Pos(22,14),),120),
                                   MoveIntent(7,(Pos(22,13),),110)])
        worker_move=next(a for a in moves if a.actor_id==7)
        self.assertNotEqual(worker_move.targets[0],Pos(22,13))
        self.assertEqual(turn.team_our.unit(7).pos.distance_to(worker_move.targets[0]),1)

    def test_gun_topup_does_not_consume_minimum_repair_reserve(self):
        raw=funded_shop();raw['teamOur']['goldNum']=170
        turn=Turn.from_raw(raw)
        plan=LogisticsManager(weapon_buyer_id=2,support_id=1).plan(
            turn,turn.team_our.unit(2),defense_budget(turn,DEFAULT_CONFIG),DEFAULT_CONFIG)
        self.assertFalse(plan.action and plan.action.action_type=='buy')

    def test_arrival_keeps_rescue_when_distance_threshold_shrinks(self):
        for side in ('challenger','defender'):
            raw,wall_id,robot=protected_scene(side)
            unit(raw,wall_id).update(level=1,health=430)
            turn=Turn.from_raw(raw);worker=turn.team_our.unit(1);wall=turn.team_our.unit(wall_id)
            self.assertEqual(wall_use_item(turn,wall,worker,DEFAULT_CONFIG,150,1),'WallFixer')
            self.assertEqual(wall_use_item(turn,wall,worker,DEFAULT_CONFIG,150,0),'')
            robot=replace(robot,attack_power=150)
            plan=support_plan(turn,worker,DEFAULT_CONFIG,(robot,),committed_id=wall_id)
            self.assertEqual(plan.action.name,'WallFixer')
            unsafe=support_plan(turn,worker,DEFAULT_CONFIG,(robot,),committed_id=wall_id,recent_damage=10)
            self.assertIsNone(unsafe.action)
            self.assertEqual(unsafe.reason,'support_recent_damage_retreat')

    def test_no_income_trip_returns_to_refuge(self):
        raw=world(791);turn=Turn.from_raw(raw);state=WorldState();state.ingest(turn)
        plan=EconomyManager(main_miner_id=7).plan(turn,turn.team_our.unit(7),state,DEFAULT_CONFIG,defense_budget(turn,DEFAULT_CONFIG))
        self.assertIsNotNone(plan.move)
        self.assertEqual(plan.move.goals,TravelBudget.for_role(turn,turn.team_our.unit(7),DEFAULT_CONFIG,worker_refuge=True).goals)

    def test_medicine_uses_only_surplus_and_does_not_route_to_shop(self):
        raw=funded_shop();raw['weaponShopList'].append({'name':'Medicine','price':15})
        turn=Turn.from_raw(raw)
        def plan(raw):
            t=Turn.from_raw(raw)
            return worker_medicine_plan(t,t.team_our.unit(7),t.team_our.unit(1),defense_budget(t,DEFAULT_CONFIG),DEFAULT_CONFIG)
        stocked=plan(raw);self.assertEqual((stocked.action.name,stocked.action.quantity),('Medicine',2))
        raw['teamOur']['goldNum']=160
        self.assertIsNone(plan(raw).action)
        raw['teamOur']['goldNum']=1000;unit(raw,7)['pos']={'x':20,'y':20}
        self.assertIsNone(plan(raw).move);self.assertIsNone(plan(raw).action)

    def test_worker_consumes_medicine_after_safe_return(self):
        raw=world(791);unit(raw,7).update(health=120,backpack=['Medicine'])
        turn=Turn.from_raw(raw);state=WorldState();state.ingest(turn)
        plan=EconomyManager(main_miner_id=7).plan(turn,turn.team_our.unit(7),state,DEFAULT_CONFIG,defense_budget(turn,DEFAULT_CONFIG))
        self.assertEqual((plan.action.action_type,plan.action.name),('use','Medicine'))

    def test_partial_treasure_cannot_spend_before_location_and_window(self):
        turn,k,data=prepared();data.update(location=None,window=None);ingest(k,data)
        plan=k.plan(turn,turn.team_our.unit(2),DEFAULT_CONFIG,1000)
        self.assertFalse(plan.action or plan.move)

    def test_escape_can_cross_equal_clearance_plateau(self):
        raw=world(851);unit(raw,7)['pos']={'x':20,'y':8}
        raw['robot']['roles']=[dict(id=90+i,roleType='middleRobot',health=60,
            pos={'x':x,'y':8},attackRange=3,targetTeam='challenger') for i,x in enumerate((18,22))]
        turn=Turn.from_raw(raw);worker=turn.team_our.unit(7)
        move=escape_intent(turn,worker,DEFAULT_CONFIG,danger_cells(turn,DEFAULT_CONFIG))
        self.assertIsNotNone(move)
        self.assertEqual(worker.pos.distance_to(move.goals[0]),1)

    def test_fully_boxed_escape_does_not_invent_a_move(self):
        raw=world(851);unit(raw,7)['pos']={'x':20,'y':8}
        raw['robot']['roles']=[dict(id=90+i,roleType='middleRobot',health=60,
            pos=p.to_raw(),attackRange=3) for i,p in enumerate(Pos(20,8).neighbours())]
        turn=Turn.from_raw(raw)
        self.assertIsNone(escape_intent(turn,turn.team_our.unit(7),DEFAULT_CONFIG,danger_cells(turn,DEFAULT_CONFIG)))


if __name__=='__main__':
    unittest.main()
