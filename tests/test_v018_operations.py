"""Synthetic regressions for scoped score stealing and final-night coverage."""
import unittest
from dataclasses import replace
from tests.test_v013_operations import world
from tests.test_v014_operations import unit, BUDGET
from tests.test_v015_operations import bomb_scene, protected_scene
from solution.models import Turn
from solution.rules import DEFAULT_CONFIG
from solution.actions import ActionType
from solution.geometry import Pos


class RaidTests(unittest.TestCase):
    def test_first_ten_night_turns_only_and_level_three(self):
        from solution.combat import raid_targets
        for side,enemy in [('challenger','defender'),('defender','challenger')]:
            for round_no,level,expected in [(201,3,False),(331,2,False),(331,3,True),(340,3,True),(341,3,False)]:
                raw=world(round_no,side)
                for r in raw['teamOur']['roles']:
                    if r['roleType']=='rocket':r['level']=level
                raw['robot']['roles']=[dict(id=90,roleType='middleRobot',pos={'x':15,'y':2},health=60,targetTeam=enemy)]
                robots,reason=raid_targets(Turn.from_raw(raw),DEFAULT_CONFIG)
                self.assertEqual(bool(robots),expected)

    def test_direct_base_threat_cancels_raid(self):
        from solution.combat import raid_targets
        raw=world(331)
        for r in raw['teamOur']['roles']:
            if r['roleType']=='rocket':r['level']=3
        raw['robot']['roles']=[dict(id=90,roleType='middleRobot',pos={'x':15,'y':2},health=60,targetTeam='defender'),dict(id=91,roleType='bossRobot',pos={'x':5,'y':13},health=800,targetTeam='challenger',attackRange=3,attackPower=40)]
        self.assertFalse(raid_targets(Turn.from_raw(raw),DEFAULT_CONFIG)[0])


class SupplyTests(unittest.TestCase):
    def test_engineer_prebuys_day_five_without_visible_targets(self):
        from solution.surplus_bomb import SurplusBomb
        raw=bomb_scene();raw['roundNo']=561;raw['robot']['roles']=[]
        unit(raw,1)['pos']={'x':10,'y':12}
        t=Turn.from_raw(raw);p=SurplusBomb().plan(t,t.team_our.unit(1),t.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertEqual((p.action.actor_id,p.action.name),(1,'Bomb'))

    def test_last_day_stock_uses_surplus_and_reserves_defense(self):
        from solution.surplus_bomb import SurplusBomb
        raw=bomb_scene();raw['roundNo']=1201;unit(raw,1)['pos']={'x':10,'y':12}
        t=Turn.from_raw(raw);p=SurplusBomb().plan(t,t.team_our.unit(1),t.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertGreater(p.action.quantity,1)
        self.assertLess(p.action.quantity*100,t.team_our.gold)

    def test_side_wall_outside_upgrade_array_still_repaired(self):
        from solution.maintenance import support_plan
        from solution.wall_supply import wall_target
        raw=world(1241);t=Turn.from_raw(raw)
        wall=next(w for w in t.team_our.roles if w.role_type=='wall' and wall_target(t,w)==1)
        unit(raw,wall.unit_id)['health']=100
        frame=t.coordinate_frame;p=frame.normalize(wall.pos)
        # Stand on an inner cell next to the damaged flank.
        from solution.grid import OccupancyGrid,interaction_cells
        goals=interaction_cells(OccupancyGrid.from_turn(t,ignore_unit_ids=(1,7)),wall.pos)
        unit(raw,1)['pos']=goals[0].to_raw();unit(raw,1)['backpack']=['WallFixer']*6
        t=Turn.from_raw(raw);p=support_plan(t,t.team_our.unit(1),DEFAULT_CONFIG,())
        self.assertIsNotNone(p.action);self.assertEqual(p.action.targets,(wall.pos,))


class TreasureArrivalTests(unittest.TestCase):
    def test_preceding_night_is_departure_due_with_known_materials(self):
        from solution.treasure import TreasureKnowledge
        raw=world(461);unit(raw,2)['backpack']=['SyntheticRelic']
        t=Turn.from_raw(raw);k=TreasureKnowledge(materials={'SyntheticRelic':1},position=Pos(15,2),opening_day=5,end_day=5,phase='day',mode='treasure')
        self.assertTrue(k.departure_due(t,t.team_our.unit(2),DEFAULT_CONFIG))

    def test_guard_prefers_miner_and_confirms_observed_arrival(self):
        from solution.roles import GuardHandover
        raw=world(461);t=Turn.from_raw(raw);g=GuardHandover()
        assignments,moves,ready=g.coordinate(t,tuple(w for w in t.team_our.roles if w.is_weapon),DEFAULT_CONFIG,True,preferred_backup=7)
        self.assertEqual(g.backup_id,7);self.assertFalse(ready)
        self.assertTrue(all(a.controller.unit_id!=1 for a in assignments))

if __name__=='__main__':unittest.main()

class IntegratedTests(unittest.TestCase):
    def test_raid_fires_opponent_then_reverts_after_turn_ten(self):
        from solution.engine import AgentEngine
        from solution.defense import build_defense_layout
        for side,enemy in [('challenger','defender'),('defender','challenger')]:
            raw=world(331,side);t=Turn.from_raw(raw)
            for r in raw['teamOur']['roles']:
                if r['roleType']=='rocket':r['level']=3
            frame=t.coordinate_frame
            enemy_pos=frame.denormalize(Pos(22,3));home_pos=frame.denormalize(Pos(15,16))
            raw['robot']['roles']=[dict(id=90,roleType='middleRobot',pos=enemy_pos.to_raw(),health=60,targetTeam=enemy),dict(id=91,roleType='middleRobot',pos=home_pos.to_raw(),health=60,targetTeam=side)]
            engine=AgentEngine();commands=engine.decide(raw)['roleCommandMap']
            shots=[c for c in commands.values() if c['action']=='attack']
            self.assertEqual(len(shots),1)
            self.assertTrue(all(Pos.from_raw(p).distance_to(enemy_pos)<=1 for p in shots[0]['targetPos']))
            raw['roundNo']=341;commands=engine.decide(raw)['roleCommandMap']
            shots=[c for c in commands.values() if c['action']=='attack']
            self.assertTrue(shots)
            self.assertTrue(all(Pos.from_raw(p).distance_to(home_pos)<=1 for p in shots[0]['targetPos']))

    def test_final_night_two_workers_repair_different_walls(self):
        from solution.engine import AgentEngine
        from solution.economy import front_wall_number
        for side in ('challenger','defender'):
            raw=world(1241,side);t=Turn.from_raw(raw);frame=t.coordinate_frame
            for actor,number in ((1,2),(7,5)):
                wall=next(w for w in t.team_our.roles if front_wall_number(t,w)==number)
                p=frame.normalize(wall.pos)
                unit(raw,actor)['pos']=frame.denormalize(Pos(p.x-1,p.y)).to_raw()
                unit(raw,actor)['backpack']=['WallFixer']*5
                unit(raw,wall.unit_id)['health']=200
            engine=AgentEngine();commands=engine.decide(raw)['roleCommandMap']
            self.assertEqual(commands['1']['name'],'WallFixer')
            self.assertEqual(commands['7']['name'],'WallFixer')
            self.assertNotEqual(commands['1']['targetPos'],commands['7']['targetPos'])
            self.assertFalse(any(c['action']=='collect' for c in commands.values()))

    def test_helper_stock_live_price_and_engineer_reservation(self):
        from solution.wall_supply import final_helper_stock
        raw=bomb_scene();raw['roundNo']=1220;raw['teamOur']['goldNum']=35
        unit(raw,7)['pos']={'x':11,'y':12}
        t=Turn.from_raw(raw);p=final_helper_stock(t,t.team_our.unit(7),t.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertEqual(p.action.quantity,3)
        self.assertEqual(p.action.name,'WallFixer')
        unit(raw,1)['backpack']=[];t=Turn.from_raw(raw)
        p=final_helper_stock(t,t.team_our.unit(7),t.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertIsNone(p.action)

    def test_preceding_night_handoff_trip_and_first_dawn_open_both_sides(self):
        from solution.engine import AgentEngine
        from solution.treasure import TreasureKnowledge
        from solution.defense import build_defense_layout
        for side in ('challenger','defender'):
            raw=world(460,side);engine=AgentEngine();engine.decide(raw)
            raw['roundNo']=461;unit(raw,2)['backpack']=['SyntheticRelic']
            t=Turn.from_raw(raw);site=t.coordinate_frame.denormalize(Pos(14,4))
            engine.planner.treasure=TreasureKnowledge(materials={'SyntheticRelic':1},position=site,opening_day=5,end_day=5,phase='day',mode='treasure')
            raw['weaponShopList'].append({'name':'SyntheticRelic','price':1})
            miner=engine.planner.economy.main_miner_id;confirmed=False;arrived=None
            for r in range(461,522):
                raw['roundNo']=r
                response=engine.decide(raw)['roleCommandMap']
                if engine.planner.guard.away:
                    confirmed=True;self.assertEqual(engine.planner.guard.backup_id,miner)
                for aid,c in response.items():
                    if c['action']=='move':
                        if int(aid)==2 and engine.planner.treasure.reason=='travel_site':self.assertTrue(confirmed)
                        unit(raw,int(aid))['pos']=c['targetPos'][0]
                    if c['action']=='summonTreasure':self.assertEqual(r,521)
                if Pos.from_raw(unit(raw,2)['pos']).distance_to(site)==1 and arrived is None:arrived=r
                self.assertFalse(engine.planner.failure_count)
            self.assertTrue(confirmed);self.assertLess(arrived,521)
            self.assertEqual(response['2']['action'],'summonTreasure')


class ObservabilityTests(unittest.TestCase):
    def test_pioneer_report_does_not_count_missing_or_firing_as_idle(self):
        from tools.diagnostics.pioneer_report import summarize_pioneer
        role=[2,'pioneer',[4,4],200]
        events=[{'event':'turn','r':r,'d':1,'roles':[role],'commands':commands} for r,commands in [(1,[]),(2,[['10','attack','',0,[],2]]),(4,[])]]
        report=summarize_pioneer(events)
        self.assertEqual(report['days'][0]['activity']['firing'],1)
        self.assertEqual(report['days'][0]['missing_turns'],127)
        self.assertEqual([(x['start'],x['end']) for x in report['unassigned_intervals']],[(1,1),(4,4)])

    def test_final_night_survives_exhausted_normal_budget(self):
        from solution.telemetry import Telemetry,decode_event
        from unittest.mock import patch
        telemetry=Telemetry(DEFAULT_CONFIG.telemetry_byte_budget,DEFAULT_CONFIG.telemetry_reserve_bytes)
        records=[]
        with patch('solution.telemetry.LOGGER.info',side_effect=records.append):
            while telemetry.emit({'event':'noise','r':900,'data':'synthetic'},critical=True):pass
            records.clear()
            for r in range(1241,1301):
                telemetry.record_turn(Turn.from_raw(world(r)),{'roleCommandMap':{}},elapsed_ms=1,dropped_actions=0)
        self.assertEqual([decode_event(x)['r'] for x in records],list(range(1241,1301)))
        self.assertLessEqual(telemetry.used_bytes,telemetry.byte_budget)

class PriorityTests(unittest.TestCase):
    def test_urgent_wall_repair_precedes_carried_bomb(self):
        from solution.engine import AgentEngine
        from solution.economy import front_wall_number
        raw=bomb_scene();raw['roundNo']=732;t=Turn.from_raw(raw)
        wall=next(w for w in t.team_our.roles if front_wall_number(t,w)==3)
        unit(raw,1)['pos']={'x':wall.pos.x-1,'y':wall.pos.y}
        unit(raw,1)['backpack']+=['Bomb'];unit(raw,wall.unit_id)['health']=200
        response=AgentEngine().decide(raw)['roleCommandMap']
        self.assertEqual(response['1']['name'],'WallFixer')

    def test_final_bombs_can_repeat_only_after_confirmed_success(self):
        from solution.surplus_bomb import SurplusBomb
        raw=bomb_scene();raw['roundNo']=1241;unit(raw,1)['backpack']+=['Bomb']*3
        t=Turn.from_raw(raw);m=SurplusBomb()
        action=m.plan(t,t.team_our.unit(1),t.team_our.unit(1),BUDGET,DEFAULT_CONFIG).action
        m.issued(t,action)
        t=replace(t,round_no=1242,last_action_results={1:True});m.observe(t)
        self.assertEqual(m.plan(t,t.team_our.unit(1),t.team_our.unit(1),BUDGET,DEFAULT_CONFIG).action.name,'Bomb')
        m.issued(t,action);t=replace(t,round_no=1243,last_action_results={1:False});m.observe(t)
        self.assertEqual(m.plan(t,t.team_our.unit(1),t.team_our.unit(1),BUDGET,DEFAULT_CONFIG).reason,'bomb_use_unconfirmed_stop')

    def test_handover_route_cannot_cross_visible_unprotected_robots(self):
        from solution.roles import GuardHandover
        from solution.movement import schedule_moves
        raw=world(461);raw['robot']['roles']=[dict(id=99,roleType='middleRobot',pos={'x':11,'y':12},health=60,attackRange=3,targetTeam='challenger')]
        t=Turn.from_raw(raw);g=GuardHandover()
        assignments,moves,ready=g.coordinate(t,tuple(w for w in t.team_our.roles if w.is_weapon),DEFAULT_CONFIG,True,preferred_backup=7)
        self.assertFalse(ready)
        for move in moves:
            self.assertTrue(move.avoid_cells)
        for action in schedule_moves(t,moves):
            intent=next(i for i in moves if i.actor_id==action.actor_id)
            self.assertNotIn(action.targets[0],intent.avoid_cells)
