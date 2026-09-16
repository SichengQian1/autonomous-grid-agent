from __future__ import annotations

import unittest
from solution.economy import EconomyManager, DefenseBudget
from solution.logistics import LogisticsManager
from solution.market import MarketMemory
from solution.models import Turn
from solution.movement import schedule_moves
from solution.rules import DEFAULT_CONFIG
from solution.state import WorldState
from solution.tasking import TreasureKnowledge
from tests.test_operations_v04 import campus
from tests.helpers import role


class EconomicOperationsTests(unittest.TestCase):
    def test_base_delivery_reaches_target_anchor_before_using_voucher(self):
        raw=self.raw()
        raw['teamOur']['roles'][0]['pos']={'x':7,'y':9}
        raw['teamOur']['roles'][0]['backpack']=['StationUpgradeVoucher1']
        raw['roundNo']=131
        turn=Turn.from_raw(raw)
        plan=LogisticsManager().plan(turn,turn.team_our.unit(1),DefenseBudget(0,25,0,12),DEFAULT_CONFIG)
        self.assertIsNone(plan.action)
        self.assertIsNotNone(plan.move)

    def test_emergency_reserve_can_purchase_critical_wall_repair(self):
        raw=self.raw(); raw['teamOur']['roles'][0]['pos']={'x':13,'y':5}
        raw['teamOur']['roles'].append(role(20,'wall',8,8,health=100,level=3))
        raw['weaponShopList']=[{'name':'WallFixer','price':10}]
        raw['teamOur']['goldNum']=10
        turn=Turn.from_raw(raw)
        plan=LogisticsManager().plan(turn,turn.team_our.unit(1),DefenseBudget(0,25,0,-3),DEFAULT_CONFIG)
        self.assertEqual((plan.action.name,plan.action.quantity),('WallFixer',1))

    def test_malformed_interpretations_are_ignored_without_interrupting_defense(self):
        import json
        from solution.task_programs import procedure_command
        MarketMemory().ingest_interpretation([dict(ore={},evidence='synthetic news')],'synthetic news',1)
        for bad in ({},[],None):
            self.assertEqual(procedure_command({'kind':bad}), '')
            TreasureKnowledge().ingest_llm(json.dumps({'treasure':dict(x=1,y=2,day=3,confidence=1,items=['key'],phase=bad)}))

    def raw(self):
        raw=campus()
        raw['teamOur']['roles'][0]['pos']={'x':2,'y':3}
        raw['mapInfo']['zones']=[{'neutralType':'copper','pos':{'x':3,'y':3}},
                               {'neutralType':'vendor','pos':{'x':14,'y':3}},
                               {'neutralType':'weaponShop','pos':{'x':14,'y':5}}]
        raw['vendorShopList']=[{'name':'copper','price':5},{'name':'iron','price':3}]
        return raw

    def test_batch_mining_completes_sale_with_fewer_trips(self):
        raw=self.raw(); manager=EconomyManager(); state=WorldState(); sales=[]; collected=0; moves=0
        raw['teamOur']['goldNum']=0  # Test ordinary batching, not a nearly funded upgrade.
        for r in range(1,45):
            raw['roundNo']=r; turn=Turn.from_raw(raw); state.ingest(turn)
            plan=manager.plan(turn,turn.team_our.unit(1),state,DEFAULT_CONFIG,DefenseBudget(0,25,0,12))
            if plan.action:
                if plan.action.action_type.value=='collect':
                    raw['teamOur']['roles'][0]['backpack'].append('copper'); collected+=1
                elif plan.action.action_type.value=='sell':
                    sales.append(plan.action.quantity)
                    for _ in range(plan.action.quantity): raw['teamOur']['roles'][0]['backpack'].remove('copper')
            if plan.move:
                actions=schedule_moves(turn,[plan.move])
                if actions:
                    raw['teamOur']['roles'][0]['pos']=actions[0].targets[0].to_raw(); moves+=1
        self.assertTrue(sales)
        self.assertGreaterEqual(sales[0],6)
        self.assertGreaterEqual(sum(sales)*5,50)
        self.assertGreater(collected,10)
        self.assertLess(moves,35)

    def test_current_runtime_price_and_future_window_are_separate(self):
        market=MarketMemory(); market.observe('days 7-8 iron price=11; day 6 copper closed',5)
        self.assertEqual(market.expected_price('iron',3,6,can_wait=True),11)
        self.assertEqual(market.expected_price('iron',3,6,can_wait=False),3)
        self.assertEqual(market.expected_price('iron',3,8,can_wait=True),3)
        self.assertTrue(market.closed('copper',6)); self.assertFalse(market.closed('copper',7))
        market.observe('iron prices might rise someday',6)
        self.assertEqual(len(market.windows),2)

    def test_narrative_interpretation_requires_source_evidence(self):
        source='Synthetic notice: tomorrow iron extraction stops for two days; existing stock becomes more valuable.'
        entry=dict(ore='iron',start_day=6,end_day=7,closed=True,rising=True,price=999,
                   evidence='tomorrow iron extraction stops for two days',confidence=0.99)
        market=MarketMemory(); market.ingest_interpretation([entry],source,5)
        self.assertTrue(market.closed('iron',6))
        self.assertTrue(market.will_rise('iron',5))
        self.assertEqual(market.expected_price('iron',3,5,can_wait=True),3)
        market=MarketMemory(); entry['evidence']='made up evidence not present'
        market.ingest_interpretation([entry],source,5); self.assertFalse(market.windows)

    def test_relative_dates_are_not_hard_coded_to_an_early_day(self):
        market=MarketMemory(); market.observe('明日铁矿关闭，持续2天，价格上涨',6)
        self.assertTrue(market.closed('iron',7))
        self.assertTrue(market.closed('iron',8))
        self.assertFalse(market.closed('iron',3))

    def test_official_news_drives_memory_but_folk_text_does_not(self):
        raw=self.raw(); raw['worldNews']={'official_news':'','folkLegends':'days 2-3 iron price=50'}
        state=WorldState(); state.ingest(Turn.from_raw(raw)); self.assertEqual(state.market.windows,[])
        raw['worldNews']['official_news']='ignored wrong field'
        raw['worldNews']['official_news']=''
        raw['worldNews']['officialNews']='第2天至第3天铁矿价格为9'
        state.ingest(Turn.from_raw(raw)); self.assertEqual(state.market.windows[0].price,9)

    def test_basket_purchase_then_delivery_uses_inventory_feedback(self):
        raw=self.raw(); raw['teamOur']['roles'][0]['pos']={'x':13,'y':5}
        raw['teamOur']['roles'] += [role(20,'rocket',4,8,health=1000,level=1,attack_range=10),
                                   role(21,'rocket',4,11,health=1000,level=1,attack_range=10)]
        raw['weaponShopList']=[{'name':'WeaponUpgradeVoucher1','price':100}]
        raw['teamOur']['goldNum']=225
        manager=LogisticsManager(); budget=DefenseBudget(0,25,200,12)
        turn=Turn.from_raw(raw); plan=manager.plan(turn,turn.team_our.unit(1),budget,DEFAULT_CONFIG)
        self.assertEqual((plan.action.name,plan.action.quantity),('WeaponUpgradeVoucher1',2))
        raw['teamOur']['roles'][0]['backpack']=['WeaponUpgradeVoucher1']*2
        raw['teamOur']['goldNum']=25; raw['roundNo']=2
        turn=Turn.from_raw(raw); plan=manager.plan(turn,turn.team_our.unit(1),DefenseBudget(0,25,0,12),DEFAULT_CONFIG)
        self.assertIsNotNone(plan.move); self.assertEqual(manager.stage,'deliver')
        target=turn.team_our.unit(manager.orders[0].target_id)
        raw['teamOur']['roles'][0]['pos']={'x':target.pos.x-1,'y':target.pos.y}
        raw['roundNo']=3; turn=Turn.from_raw(raw)
        plan=manager.plan(turn,turn.team_our.unit(1),DefenseBudget(0,25,0,12),DEFAULT_CONFIG)
        self.assertEqual(plan.action.action_type.value,'use')

    def test_treasure_requires_known_multiple_day_evidence_and_owned_items(self):
        import json
        knowledge=TreasureKnowledge()
        data={'treasure':{'x':3,'y':4,'day':2,'end_day':4,'phase':'day','items':['SyntheticKey'],
                          'evidence_days':[1,2],'confidence':1.0}}
        knowledge.ingest_llm(json.dumps(data),{1}); self.assertIsNone(knowledge.position)
        knowledge.ingest_llm(json.dumps(data),{1,2})
        raw=self.raw(); raw['roundNo']=131
        raw['teamOur']['roles'][2]['pos']={'x':3,'y':5}
        raw['weaponShopList']=[{'name':'SyntheticKey','price':10}]
        turn=Turn.from_raw(raw); pioneer=turn.team_our.unit(3)
        self.assertIsNone(knowledge.action(turn,pioneer,DEFAULT_CONFIG))
        self.assertIsNone(knowledge.plan(turn,pioneer,DEFAULT_CONFIG,100).action)
        raw['teamOur']['roles'][2]['backpack']=['SyntheticKey']; turn=Turn.from_raw(raw)
        self.assertEqual(knowledge.action(turn,turn.team_our.unit(3),DEFAULT_CONFIG).action_type.value,'summonTreasure')
