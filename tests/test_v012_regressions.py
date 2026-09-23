"""Synthetic regressions for answer transport and scheduled defense."""
import json
import unittest
from tests.test_v010_regressions import active_manager
from tests.helpers import synthetic_turn, role
from solution.rules import DEFAULT_CONFIG
from solution.state import LlmBudget
from solution.models import Turn
from solution.economy import next_development_target, DefenseBudget
from solution.logistics import LogisticsManager

class AnswerTransportTests(unittest.TestCase):
    def test_current_api_answer_accepts_object_wrapped_and_serialized(self):
        answer={'city':'Sample','total_count':1,'types':['Bridge']}
        for response in (answer,{'answer':answer},{'answer':json.dumps(answer)},
                         {'answer':'```json\n'+json.dumps(answer)+'\n```'}):
            with self.subTest(response=response):
                m,t,s=active_manager(response=response,docs='Answer JSON: {"city":"string","total_count":0,"types":[]}')
                m.context.executed=True
                m.context.retrieval={'complete':True,'records':[{'id':'new','type':'Bridge'}],
                    'object':'Sample','reason':'total_matched','filter_evidence':'record_field'}
                p=m.plan(t,s,LlmBudget(),DEFAULT_CONFIG,t.team_our.unit(2))
                self.assertIsNotNone(p.action,m.diagnostic)
                self.assertEqual(json.loads(p.action.task_answer),answer)
                self.assertFalse(p.prompt)

    def test_raw_object_does_not_bypass_execution_or_field_validation(self):
        for ready,count in ((False,1),(True,2)):
            m,t,s=active_manager(response={'city':'Sample','total_count':count,'types':['Bridge']},
                docs='Answer JSON: {"city":"string","total_count":0,"types":[]}')
            m.context.executed=True
            m.context.retrieval={'complete':ready,'records':[{'id':'new','type':'Bridge'}],
                'object':'Sample','reason':'total_matched','filter_evidence':'record_field'}
            p=m.plan(t,s,LlmBudget(),DEFAULT_CONFIG,t.team_our.unit(2))
            self.assertIsNone(p.action)


def defense_raw(round_no=521):
    raw=synthetic_turn(round_no=round_no);raw['phaseTask']='';raw['robot']['roles']=[]
    raw['mapInfo']={'width':30,'height':24,'zones':[{'neutralType':'weaponShop','pos':{'x':9,'y':15}}]}
    raw['teamOur']['goldNum']=400
    raw['teamOur']['roles']=[role(1,'worker',7,16),role(2,'pioneer',9,16),role(3,'station',5,15,health=1500,level=1)]
    raw['teamOur']['roles'] += [role(10+i,'rocket',x,y,health=1500,level=2) for i,(x,y) in enumerate(((4,14),(5,13),(6,13)))]
    raw['teamOur']['roles'] += [role(20+i,'wall',8,18-i,health=1500,level=2) for i in range(1,7)]
    raw['weaponShopList']=[{'name':n,'price':p} for n,p in [('WeaponUpgradeVoucher2',150),('StationUpgradeVoucher1',100),('WallUpgradeVoucher1',20),('WallUpgradeVoucher2',30),('WallFixer',10)]]
    return raw

class MilestoneTests(unittest.TestCase):
    def test_day_five_base_precedes_remaining_weapon_upgrade(self):
        t=Turn.from_raw(defense_raw())
        self.assertEqual(next_development_target(t,DEFAULT_CONFIG).role_type,'station')
        p=LogisticsManager().plan(t,t.team_our.unit(2),DefenseBudget(0,25,375,12),DEFAULT_CONFIG)
        self.assertEqual(p.action.name,'StationUpgradeVoucher1')

    def test_fourth_day_still_develops_weapons(self):
        t=Turn.from_raw(defense_raw(400))
        self.assertEqual(next_development_target(t,DEFAULT_CONFIG).role_type,'rocket')

    def test_one_core_wall_by_fifth_night_both_by_sixth(self):
        raw=defense_raw();raw['teamOur']['roles'][2]['level']=2
        t=Turn.from_raw(raw);target=next_development_target(t,DEFAULT_CONFIG)
        self.assertIn(target.unit_id,(22,23))
        for u in raw['teamOur']['roles']:
            if u['id']==target.unit_id:u['level']=3
        self.assertEqual(next_development_target(Turn.from_raw(raw),DEFAULT_CONFIG).role_type,'rocket')
        raw['roundNo']=651
        self.assertIn(next_development_target(Turn.from_raw(raw),DEFAULT_CONFIG).unit_id,(22,23))

    def test_owned_milestone_wall_is_used_at_night_while_healthy(self):
        from solution.maintenance import support_plan
        raw=defense_raw(591);raw['teamOur']['roles'][2]['level']=2
        raw['teamOur']['roles'][0]['backpack']=['WallUpgradeVoucher2']
        t=Turn.from_raw(raw);p=support_plan(t,t.team_our.unit(1),DEFAULT_CONFIG,())
        self.assertIsNotNone(p.action);self.assertEqual(p.action.name,'WallUpgradeVoucher2')

class MaintenanceTests(unittest.TestCase):
    def test_numbering_and_deadlines_are_side_normalized(self):
        from solution.economy import front_wall_number
        raw=defense_raw()
        first=Turn.from_raw(raw)
        for u in raw['teamOur']['roles']:
            # Anchor transformation differs from a single-cell role for a station.
            if u['roleType']=='station':u['pos']={'x':23,'y':9}
            else:u['pos']={'x':29-u['pos']['x'],'y':23-u['pos']['y']}
        raw['teamOur']['type']='defender'
        other=Turn.from_raw(raw)
        for number in range(1,7):
            self.assertEqual(front_wall_number(first,first.team_our.unit(20+number)),number)
            self.assertEqual(front_wall_number(other,other.team_our.unit(20+number)),number)

    def test_wall_one_prefers_upgrade_heal_in_final_array(self):
        from solution.maintenance import support_plan
        raw=defense_raw(461)
        raw['teamOur']['roles'][0].update(pos={'x':7,'y':16},backpack=['WallUpgradeVoucher2','WallFixer'])
        for u in raw['teamOur']['roles']:
            if u['id']==21:u['health']=100
            if u['id']==23:u['health']=350
        t=Turn.from_raw(raw);p=support_plan(t,t.team_our.unit(1),DEFAULT_CONFIG,())
        self.assertEqual(p.action.name,'WallUpgradeVoucher2')
        self.assertEqual(p.action.targets[0],t.team_our.unit(21).pos)

    def test_damage_risk_can_trigger_heal_above_fixed_threshold(self):
        from solution.maintenance import support_plan
        raw=defense_raw(591)
        raw['teamOur']['roles'][0].update(pos={'x':7,'y':16},backpack=['WallUpgradeVoucher2'])
        for u in raw['teamOur']['roles']:
            if u['id']==23:u['health']=700
        raw['robot']['roles']=[dict(id=100+i,roleType='bossRobot',health=800,pos={'x':10,'y':15},attackPower=100,attackRange=3,targetTeam='challenger') for i in range(4)]
        t=Turn.from_raw(raw);p=support_plan(t,t.team_our.unit(1),DEFAULT_CONFIG,t.robots)
        self.assertEqual(p.action.name,'WallUpgradeVoucher2')
        self.assertEqual(p.action.targets[0],t.team_our.unit(23).pos)

    def test_support_worker_stocks_six_without_spending_basic_weapon_reserve(self):
        from tests.test_v014_operations import WallSupplyTests,unit
        from solution.logistics import plan_repair_stock
        raw=WallSupplyTests().scene();raw['teamOur']['goldNum']=160;unit(raw,10)['level']=1
        t=Turn.from_raw(raw);p=plan_repair_stock(t,t.team_our.unit(1),DefenseBudget(0,25,135,12),DEFAULT_CONFIG)
        self.assertEqual((p.action.name,p.action.quantity),('WallFixer',6))
        raw['teamOur']['goldNum']=100;t=Turn.from_raw(raw)
        self.assertIsNone(plan_repair_stock(t,t.team_our.unit(1),DefenseBudget(0,25,75,12),DEFAULT_CONFIG).action)

    def test_healthy_carried_wall_voucher_does_not_block_purchase(self):
        raw=defense_raw(270);raw['teamOur']['roles'][1]['backpack']=['WallUpgradeVoucher1']
        for u in raw['teamOur']['roles']:
            if u['roleType']=='wall':u.update(level=1,health=1000)
        t=Turn.from_raw(raw);p=LogisticsManager().plan(t,t.team_our.unit(2),DefenseBudget(0,25,375,12),DEFAULT_CONFIG)
        self.assertEqual(p.action.name,'WeaponUpgradeVoucher2')

    def test_day_five_replaces_unpurchased_weapon_order(self):
        from solution.logistics import Delivery
        raw=defense_raw();t=Turn.from_raw(raw)
        manager=LogisticsManager(carrier_id=2,orders=[Delivery('WeaponUpgradeVoucher2',10,2)],started=515)
        p=manager.plan(t,t.team_our.unit(2),DefenseBudget(0,25,375,12),DEFAULT_CONFIG)
        self.assertEqual(p.action.name,'StationUpgradeVoucher1')

class DeliveryCycleTests(unittest.TestCase):
    def test_pioneer_base_delivery_finishes_without_purchasing_worker_wall_items(self):
        from solution.movement import schedule_moves
        raw=defense_raw();raw['teamOur']['goldNum']=180
        for unit in raw['teamOur']['roles']:
            if unit['roleType']=='wall':unit.update(level=1,health=1000)
        manager=LogisticsManager();actions=[]
        prices={x['name']:x['price'] for x in raw['weaponShopList']}
        for r in range(521,591):
            raw['roundNo']=r;t=Turn.from_raw(raw);pioneer=t.team_our.unit(2)
            plan=manager.plan(t,pioneer,DefenseBudget(0,25,max(0,t.team_our.gold-25),12),DEFAULT_CONFIG)
            action=plan.action
            if not action and plan.move:
                action=next(iter(schedule_moves(t,[plan.move])),None)
            if action:
                actions.append((r,action.action_type.value,action.name))
                actor=next(u for u in raw['teamOur']['roles'] if u['id']==2)
                if action.action_type.value=='move':
                    actor['pos']={'x':action.targets[0].x,'y':action.targets[0].y}
                elif action.action_type.value=='buy':
                    self.assertLessEqual(prices[action.name]*action.quantity,raw['teamOur']['goldNum'])
                    raw['teamOur']['goldNum']-=prices[action.name]*action.quantity
                    actor['backpack'] += [action.name]*action.quantity
                elif action.action_type.value=='use':
                    target=next(u for u in raw['teamOur']['roles'] if u['pos']=={'x':action.targets[0].x,'y':action.targets[0].y})
                    self.assertIn(action.name,actor['backpack'])
                    self.assertLessEqual(pioneer.pos.distance_to(action.targets[0]),1)
                    actor['backpack'].remove(action.name);target['level']+=1
                    target['health']=3000 if target['roleType']=='station' else 1000+500*(target['level']-1)
            station=raw['teamOur']['roles'][2]
            if station['level']>=2:break
        self.assertLess(r,591,actions)
        self.assertEqual(station['level'],2,actions)
        self.assertFalse(any(name.startswith('Wall') for _,_,name in actions),actions)
        self.assertFalse(any(name=='WeaponUpgradeVoucher2' for _,_,name in actions),actions)

if __name__=='__main__':unittest.main()
