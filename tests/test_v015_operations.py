"""Synthetic reproductions: funded top-ups and protected wall support."""
import unittest
from dataclasses import replace
from tests.test_v013_operations import world
from tests.test_v014_operations import unit, BUDGET
from solution.models import Turn, Robot
from solution.geometry import Pos
from solution.rules import DEFAULT_CONFIG
from solution.logistics import LogisticsManager
from solution.maintenance import support_plan
from solution.economy import front_wall_number, side_wall_a
from solution.wall_supply import wall_needs, wall_stock_plan, wall_target


def funded_shop(day=3):
    raw=world((day-1)*130+10)
    raw['teamOur']['goldNum']=1000
    raw['mapInfo']['zones']=[{'neutralType':'weaponShop','pos':{'x':10,'y':13}}]
    unit(raw,2)['pos']={'x':10,'y':12}
    unit(raw,3)['level']=2
    return raw


def protected_scene(side='challenger'):
    raw=world(851,side);turn=Turn.from_raw(raw)
    wall=next(w for w in turn.team_our.roles if front_wall_number(turn,w)==3)
    frame=turn.coordinate_frame;p=frame.normalize(wall.pos)
    unit(raw,1)['pos']=frame.denormalize(Pos(p.x-1,p.y)).to_raw()
    unit(raw,1)['backpack']=['WallFixer']*6
    unit(raw,wall.unit_id).update(level=3,health=1800)
    robot=Robot(robot_id=90,role_type='middleRobot',pos=frame.denormalize(Pos(p.x+2,p.y)),health=60,attack_power=10,attack_range=3)
    return raw,wall.unit_id,robot


class FundingTests(unittest.TestCase):
    def test_held_voucher_does_not_block_new_sale_money(self):
        raw=funded_shop();unit(raw,2)['backpack']=['WeaponUpgradeVoucher2']
        turn=Turn.from_raw(raw)
        plan=LogisticsManager(weapon_buyer_id=2).plan(turn,turn.team_our.unit(2),BUDGET,DEFAULT_CONFIG)
        self.assertIsNotNone(plan.action)
        self.assertEqual((plan.action.name,plan.action.quantity),('WeaponUpgradeVoucher2',2))

    def test_wall_basket_has_seven_first_six_second_from_day_three(self):
        raw=funded_shop()
        for r in raw['teamOur']['roles']:
            if r['roleType']=='wall':r['level']=1
        turn=Turn.from_raw(raw);need=wall_needs(turn,turn.team_our.unit(1),DEFAULT_CONFIG)
        self.assertEqual((need['WallUpgradeVoucher1'],need['WallUpgradeVoucher2']),(7,6))

    def test_sixth_day_surplus_stock_cap_fifteen(self):
        raw=funded_shop(6)
        turn=Turn.from_raw(raw)
        for r in raw['teamOur']['roles']:
            if r['roleType']=='wall':r['level']=wall_target(turn,turn.team_our.unit(r['id']))
            if r['roleType']=='rocket':r['level']=3
        unit(raw,1)['backpack']=['WallFixer']*6
        turn=Turn.from_raw(raw)
        self.assertEqual(wall_needs(turn,turn.team_our.unit(1),DEFAULT_CONFIG)['WallFixer'],9)

    def test_complete_basket_releases_pioneer_without_repeat_purchase(self):
        raw=funded_shop();unit(raw,2)['backpack']=['WeaponUpgradeVoucher2']*3
        turn=Turn.from_raw(raw);manager=LogisticsManager(weapon_buyer_id=2)
        plan=manager.plan(turn,turn.team_our.unit(2),BUDGET,DEFAULT_CONFIG)
        self.assertFalse(plan.action or plan.move);self.assertEqual(manager.stage,'carry_until_recall')

    def test_low_cash_topup_uses_live_price_without_duplicate_stock(self):
        raw=funded_shop();raw['teamOur']['goldNum']=249
        raw['weaponShopList'][1]['price']=200
        unit(raw,2)['backpack']=['WeaponUpgradeVoucher2']
        turn=Turn.from_raw(raw);plan=LogisticsManager(weapon_buyer_id=2).plan(turn,turn.team_our.unit(2),BUDGET,DEFAULT_CONFIG)
        self.assertEqual(plan.action.quantity,1)

    def test_late_topup_does_not_miss_return(self):
        raw=funded_shop();raw['roundNo']=330;unit(raw,2)['backpack']=['WeaponUpgradeVoucher2']
        turn=Turn.from_raw(raw);plan=LogisticsManager(weapon_buyer_id=2).plan(turn,turn.team_our.unit(2),BUDGET,DEFAULT_CONFIG)
        self.assertFalse(plan.action and plan.action.action_type=='buy')

    def test_day_three_funded_wall_procurement_can_begin_early(self):
        raw=funded_shop();turn=Turn.from_raw(raw)
        plan=wall_stock_plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertEqual(plan.action.name,'WallFixer')

    def test_wall_upgrades_precede_extra_repairs_after_baseline(self):
        raw=funded_shop(6);raw['roundNo']=700;unit(raw,1)['backpack']=['WallFixer']*6
        turn=Turn.from_raw(raw);plan=wall_stock_plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertEqual(plan.action.name,'WallUpgradeVoucher2')

    def test_surplus_repairs_stop_at_cash_and_capacity(self):
        raw=bomb_scene();raw['roundNo']=700;raw['teamOur']['goldNum']=47
        unit(raw,1)['pos']={'x':10,'y':12};unit(raw,1)['backpack']=['WallFixer']*6
        turn=Turn.from_raw(raw);plan=wall_stock_plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertEqual((plan.action.name,plan.action.quantity),('WallFixer',4))
        unit(raw,1)['backPackCapability']=8;turn=Turn.from_raw(raw)
        plan=wall_stock_plan(turn,turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
        self.assertEqual(plan.action.quantity,2)


class SupportTests(unittest.TestCase):
    def test_wall_protection_does_not_trigger_range_only_retreat(self):
        for side in ('challenger','defender'):
            raw,wall_id,robot=protected_scene(side);turn=Turn.from_raw(raw)
            plan=support_plan(turn,turn.team_our.unit(1),DEFAULT_CONFIG,(robot,))
            self.assertNotIn('retreat',plan.reason)
            self.assertIn(turn.team_our.unit(1).pos,plan.move.goals)

    def test_fixers_do_not_make_exposed_worker_invulnerable(self):
        raw,wall_id,robot=protected_scene();turn=Turn.from_raw(raw)
        robot=replace(robot,pos=turn.team_our.unit(1).pos.neighbours()[0],attack_power=300)
        plan=support_plan(turn,turn.team_our.unit(1),DEFAULT_CONFIG,(robot,))
        self.assertIn('retreat',plan.reason)

    def test_low_adjacent_wall_still_repaired_first(self):
        raw,wall_id,robot=protected_scene();unit(raw,wall_id)['health']=300
        turn=Turn.from_raw(raw);plan=support_plan(turn,turn.team_our.unit(1),DEFAULT_CONFIG,(robot,))
        self.assertEqual(plan.action.name,'WallFixer')

    def test_breach_and_unusable_vouchers_still_retreat(self):
        raw,wall_id,robot=protected_scene();raw['teamOur']['roles']=[u for u in raw['teamOur']['roles'] if u['id']!=wall_id]
        turn=Turn.from_raw(raw)
        self.assertIn('retreat',support_plan(turn,turn.team_our.unit(1),DEFAULT_CONFIG,(robot,)).reason)
        raw,wall_id,robot=protected_scene();unit(raw,wall_id)['health']=10
        unit(raw,1)['backpack']=['WallUpgradeVoucher1']
        turn=Turn.from_raw(raw)
        self.assertIn('retreat',support_plan(turn,turn.team_our.unit(1),DEFAULT_CONFIG,(robot,)).reason)

    def test_protected_wait_then_heal_without_retreat_cycle(self):
        for side in ('challenger','defender'):
            raw,wall_id,robot=protected_scene(side)
            # Repeated pressure changes HP while the intact wall blocks approach.
            reasons=[]
            for hp in (1800,1500,1200,900,700):
                unit(raw,wall_id)['health']=hp;turn=Turn.from_raw(raw)
                plan=support_plan(turn,turn.team_our.unit(1),DEFAULT_CONFIG,(robot,));reasons.append(plan.reason)
            self.assertTrue(all('retreat' not in r for r in reasons))
            self.assertEqual(plan.action.name,'WallFixer')

    def test_observed_worker_damage_overrides_screening_estimate(self):
        raw,wall_id,robot=protected_scene();turn=Turn.from_raw(raw)
        plan=support_plan(turn,turn.team_our.unit(1),DEFAULT_CONFIG,(robot,),recent_damage=20)
        self.assertEqual(plan.reason,'support_recent_damage_retreat')

    def test_repair_waiting_for_damage_is_not_confused_with_missing_supplies(self):
        raw,wall_id,robot=protected_scene();turn=Turn.from_raw(raw)
        robots=tuple(replace(robot,robot_id=i) for i in range(100))
        plan=support_plan(turn,turn.team_our.unit(1),DEFAULT_CONFIG,robots)
        self.assertNotIn('retreat',plan.reason)
        self.assertIsNone(plan.action) # Only 200 damage; retain the full-heal item.

    def test_rescue_routing_avoids_unscreened_cells(self):
        from solution.maintenance import support_danger_cells
        raw,wall_id,robot=protected_scene();turn=Turn.from_raw(raw)
        walls=[w for w in turn.team_our.roles if w.role_type=='wall']
        danger=support_danger_cells(turn,walls,(robot,),DEFAULT_CONFIG)
        self.assertNotIn(turn.team_our.unit(1).pos,danger)
        self.assertIn(robot.pos,danger)
        self.assertIn(robot.pos.neighbours()[0],danger)


def bomb_scene():
    raw=funded_shop(6);raw['roundNo']=721;turn=Turn.from_raw(raw)
    for r in raw['teamOur']['roles']:
        if r['roleType']=='wall':r['level']=wall_target(turn,turn.team_our.unit(r['id']));r['health']=2000
        if r['roleType']=='rocket':r['level']=3
    unit(raw,1)['backpack']=['WallFixer']*15
    unit(raw,7)['pos']={'x':11,'y':12}
    raw['weaponShopList'].append({'name':'Bomb','price':100})
    raw['robot']['roles']=[{'id':90+i,'roleType':'middleRobot','pos':{'x':24+i,'y':5},'health':60,'targetTeam':'defender','attackRange':3} for i in range(2)]
    return raw


class BombTests(unittest.TestCase):
    def plan(self,raw,manager=None,**kwargs):
        from solution.surplus_bomb import SurplusBomb
        turn=Turn.from_raw(raw);manager=manager or SurplusBomb()
        return manager.plan(turn,turn.team_our.unit(7),turn.team_our.unit(1),BUDGET,DEFAULT_CONFIG,**kwargs),manager,turn

    def test_only_spare_miner_buys_one_then_uses_global_target(self):
        raw=bomb_scene();plan,m,t=self.plan(raw)
        self.assertEqual((plan.action.actor_id,plan.action.name,plan.action.quantity),(7,'Bomb',1))
        m.issued(t,plan.action);raw['roundNo']+=1;unit(raw,7)['backpack']=['Bomb'];t=Turn.from_raw(raw)
        m.observe(t);self.assertIsNone(m.result['success'])
        plan,m,t=self.plan(raw,m);self.assertEqual(plan.action.action_type,'use')
        self.assertGreater(t.team_our.unit(7).pos.distance_to(plan.action.targets[0]),3)
        from solution.protocol import serialize_decision
        from solution.actions import Decision
        from solution.validation import ActionValidator
        response,issues=serialize_decision(t,Decision((plan.action,)),ActionValidator())
        self.assertFalse(issues);self.assertEqual(response['roleCommandMap']['7']['name'],'Bomb')
        m.issued(t,plan.action);raw['roundNo']+=1;unit(raw,7)['backpack']=[]
        plan,m,t=self.plan(raw,m);self.assertIsNone(plan.action);self.assertEqual(plan.reason,'nightly_bomb_already_used')

    def test_readiness_requires_actual_walls_not_carried_vouchers(self):
        raw=bomb_scene();turn=Turn.from_raw(raw);wall=next(w for w in turn.team_our.roles if side_wall_a(turn,w))
        unit(raw,wall.unit_id)['level']=2;unit(raw,1)['backpack']+=['WallUpgradeVoucher2']
        self.assertEqual(self.plan(raw)[0].reason,'defense_not_ready')
        raw['teamOur']['roles']=[r for r in raw['teamOur']['roles'] if r['id']!=wall.unit_id]
        self.assertEqual(self.plan(raw)[0].reason,'defense_not_ready')

    def test_fourteen_repairs_or_same_turn_use_blocks_purchase(self):
        raw=bomb_scene();self.assertEqual(self.plan(raw,repair_committed=True)[0].reason,'repair_stock_first')
        unit(raw,1)['backpack'].pop();self.assertEqual(self.plan(raw)[0].reason,'repair_stock_first')

    def test_no_own_unknown_or_nonlethal_cluster(self):
        for team,health in [('challenger',60),('',60),('unknown',60),('defender',500)]:
            raw=bomb_scene()
            for r in raw['robot']['roles']:r.update(targetTeam=team,health=health)
            self.assertEqual(self.plan(raw)[0].reason,'no_profitable_medium_cluster')

    def test_bomb_opponent_identity_on_both_sides(self):
        from solution.surplus_bomb import bomb_target
        for side,enemy in [('challenger','defender'),('defender','challenger')]:
            raw=bomb_scene();raw['teamOur']['type']=side
            for r in raw['robot']['roles']:r['targetTeam']=enemy
            target,estimate=bomb_target(Turn.from_raw(raw),DEFAULT_CONFIG)
            self.assertIsNotNone(target);self.assertEqual(estimate[0],2)

    def test_live_price_budget_and_existing_orders(self):
        raw=bomb_scene();raw['teamOur']['goldNum']=100
        self.assertEqual(self.plan(raw,committed=1)[0].reason,'no_surplus_or_capacity')
        raw['weaponShopList'][-1]['price']=101
        self.assertEqual(self.plan(raw)[0].reason,'no_surplus_or_capacity')

    def test_same_night_failed_purchase_is_not_repeated(self):
        raw=bomb_scene();plan,m,t=self.plan(raw);m.issued(t,plan.action)
        raw['roundNo']+=1;t=replace(Turn.from_raw(raw),last_action_results={7:False});m.observe(t)
        self.assertFalse(m.result['success'])
        self.assertEqual(self.plan(raw,m)[0].reason,'bomb_already_purchased_or_carried')
        raw['roundNo']+=130;self.assertEqual(self.plan(raw,m)[0].action.name,'Bomb')

    def test_full_engine_uses_miner_without_stealing_gun_or_support_action(self):
        from solution.engine import AgentEngine
        raw=bomb_scene();turn=Turn.from_raw(raw)
        wall=next(w for w in turn.team_our.roles if front_wall_number(turn,w)==3)
        unit(raw,1)['pos']={'x':wall.pos.x-1,'y':wall.pos.y}
        # Own wave must keep the pioneer firing while the miner buys remotely.
        raw['robot']['roles'].append({'id':95,'roleType':'smallRobot','pos':{'x':wall.pos.x+3,'y':wall.pos.y},'health':40,'targetTeam':'challenger','attackRange':3})
        raw['mapInfo']['zones']=[{'neutralType':'weaponShop','pos':{'x':10,'y':4}}]
        unit(raw,7)['pos']={'x':11,'y':4}
        unit(raw,2)['pos']=world(721)['teamOur']['roles'][1]['pos']
        engine=AgentEngine();response=engine.decide(raw)['roleCommandMap']
        self.assertEqual(response['7']['name'],'Bomb')
        self.assertTrue(any(c.get('action')=='attack' for c in response.values()))
        self.assertEqual(engine.planner.surplus_bomb.bought_day,6)

    def test_diagnostic_recovers_bomb_reason_and_action(self):
        from tools.diagnostics.operation_report import summarize_operations
        events=[{'event':'turn','r':721,'d':6,'commands':[['7','buy','Bomb',1]],
                 'diagnostics':{'surplusBomb':{'reason':'bomb_purchase'}}}]
        report=summarize_operations(events,day=6)
        self.assertEqual(report['bomb_commands'],{'buy':1})
        self.assertEqual(report['maintenance_timeline'][0]['item'],'Bomb')


class ThirdNightFlowTests(unittest.TestCase):
    def test_new_income_tops_up_then_operator_upgrades_all_three_on_both_sides(self):
        from solution.engine import AgentEngine
        for side in ('challenger','defender'):
            raw=world(261,side);turn=Turn.from_raw(raw);frame=turn.coordinate_frame
            shop=frame.denormalize(Pos(11,10))
            raw['mapInfo']['zones']=[{'neutralType':'weaponShop','pos':shop.to_raw()}]
            unit(raw,2)['pos']=frame.denormalize(Pos(10,10)).to_raw()
            unit(raw,1)['pos']=frame.denormalize(Pos(10,11)).to_raw()
            unit(raw,1)['backpack']=['stone']*5
            unit(raw,7)['pos']=frame.denormalize(Pos(12,11)).to_raw()
            raw['teamOur']['goldNum']=175;engine=AgentEngine();uses=[];purchases=[]
            prices={i['name']:i['price'] for i in raw['weaponShopList']}
            for r in range(261,332):
                raw['roundNo']=r
                if r==262:raw['teamOur']['goldNum']+=900 # Synthetic external sale settlement.
                out=engine.decide(raw)['roleCommandMap'];raw['lastRoundRoleActionResults']={}
                for actor,c in out.items():
                    u=unit(raw,int(actor));name=c.get('name');action=c['action']
                    raw['lastRoundRoleActionResults'][actor]=True
                    if action=='move':u['pos']=c['targetPos'][0]
                    if action=='buy':
                        raw['teamOur']['goldNum']-=prices[name]*c['num'];u['backpack'] += [name]*c['num'];purchases.append((r,int(actor),name,c['num']))
                    if action=='use':
                        self.assertIn(name,u['backpack']);u['backpack'].remove(name)
                        target=next(x for x in raw['teamOur']['roles'] if x['pos']==c['targetPos'][0])
                        if 'UpgradeVoucher' in name:target['level']+=1
                        uses.append((r,int(actor),name))
            guns=[u for u in raw['teamOur']['roles'] if u['roleType']=='rocket']
            self.assertEqual([u['level'] for u in guns],[3,3,3],(side,purchases,uses))
            self.assertEqual([(r,n) for r,a,item,n in purchases if item=='WeaponUpgradeVoucher2'],[(261,1),(262,2)])
            self.assertEqual({a for _,a,item in uses if item.startswith('WeaponUpgradeVoucher')},{2})
            self.assertEqual(engine.planner.failure_count,0)


if __name__=='__main__':unittest.main()
