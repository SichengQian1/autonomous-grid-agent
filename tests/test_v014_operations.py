"""Synthetic regressions for role ownership and wall maintenance."""
import unittest
from dataclasses import replace
from tests.test_v013_operations import world
from solution.models import Turn
from solution.rules import DEFAULT_CONFIG
from solution.economy import EconomyManager, DefenseBudget, front_wall_number
from solution.logistics import LogisticsManager
from solution.state import WorldState
from solution.maintenance import support_plan

BUDGET=DefenseBudget(0,0,480,12)

def unit(raw,i):return next(r for r in raw['teamOur']['roles'] if r['id']==i)

def economy(raw,**kwargs):
 t=Turn.from_raw(raw);s=WorldState();s.ingest(t);m=EconomyManager(**kwargs)
 return m.plan(t,t.team_our.unit(1),s,DEFAULT_CONFIG,BUDGET),m

class RegressionTests(unittest.TestCase):
 def test_worker_does_not_buy_weapon_voucher(self):
  raw=world(150);unit(raw,10)['level']=1
  raw['mapInfo']['zones']=[{'neutralType':'weaponShop','pos':{'x':10,'y':13}}]
  t=Turn.from_raw(raw);p=LogisticsManager(support_id=7).plan(t,t.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
  self.assertFalse(p.action and p.action.name.startswith('WeaponUpgrade'))
 def test_no_vendor_route_does_not_block_safe_night_collection(self):
  raw=world(80);raw['mapInfo']['zones']=[{'neutralType':'iron','pos':{'x':11,'y':11}}]
  p,m=economy(raw)
  self.assertIsNotNone(p.action);self.assertEqual(p.action.action_type,'collect')
 def test_partial_day_work_without_same_day_sale(self):
  raw=world(310);raw['mapInfo']['zones']=[{'neutralType':'iron','pos':{'x':11,'y':11}}, {'neutralType':'vendor','pos':{'x':28,'y':1}}]
  p,m=economy(raw,returning_roles={1})
  self.assertIsNotNone(p.action);self.assertEqual(p.action.action_type,'collect')
 def test_due_wall_never_repairs_full_health(self):
  raw=world(721);t=Turn.from_raw(raw)
  w=next(w for w in t.team_our.roles if front_wall_number(t,w)==3)
  unit(raw,1)['pos']={'x':w.pos.x-1,'y':w.pos.y};unit(raw,1)['backpack']=['WallFixer']*6
  t=Turn.from_raw(raw);p=support_plan(t,t.team_our.unit(1),DEFAULT_CONFIG,())
  self.assertIsNone(p.action)
 def test_low_wall_prefers_upgrade(self):
  raw=world(341);t=Turn.from_raw(raw);w=next(w for w in t.team_our.roles if front_wall_number(t,w)==3)
  unit(raw,w.unit_id).update(health=250,level=1)
  unit(raw,1)['pos']={'x':w.pos.x-1,'y':w.pos.y};unit(raw,1)['backpack']=['WallUpgradeVoucher1','WallFixer']
  t=Turn.from_raw(raw);p=support_plan(t,t.team_our.unit(1),DEFAULT_CONFIG,())
  self.assertEqual(p.action.name,'WallUpgradeVoucher1')

class WallSupplyTests(unittest.TestCase):
 def scene(self,r=567):
  raw=world(r);unit(raw,3)['level']=2
  for u in raw['teamOur']['roles']:
   if u['roleType']=='rocket':u['level']=3
  raw['mapInfo']['zones']=[{'neutralType':'weaponShop','pos':{'x':10,'y':13}}]
  return raw
 def test_fifth_day_stock_six_uses_live_price(self):
  from solution.wall_supply import wall_stock_plan
  raw=self.scene();raw['teamOur']['goldNum']=132
  t=Turn.from_raw(raw);p=wall_stock_plan(t,t.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
  self.assertEqual((p.action.name,p.action.quantity),('WallFixer',6))
 def test_early_day_does_not_send_engineer_shopping(self):
  from solution.wall_supply import wall_stock_plan
  raw=self.scene(521);unit(raw,1)['backpack']=['WallFixer']*6
  t=Turn.from_raw(raw);p=wall_stock_plan(t,t.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
  self.assertIsNone(p.action);self.assertIsNone(p.move)
  self.assertEqual(p.reason,'mine_before_wall_procurement')
 def test_voucher_counts_follow_actual_levels_and_backpack(self):
  from solution.wall_supply import wall_needs
  raw=self.scene()
  for u in raw['teamOur']['roles']:
   if u['roleType']=='wall':u.update(level=1,health=1000)
  t=Turn.from_raw(raw);need=wall_needs(t,t.team_our.unit(1),DEFAULT_CONFIG)
  self.assertEqual(need['WallUpgradeVoucher1'],7);self.assertEqual(need['WallUpgradeVoucher2'],6)
  unit(raw,1)['backpack']=['WallUpgradeVoucher1']*3+['WallUpgradeVoucher2']
  t=Turn.from_raw(raw);need=wall_needs(t,t.team_our.unit(1),DEFAULT_CONFIG)
  self.assertEqual(need['WallUpgradeVoucher1'],4);self.assertEqual(need['WallUpgradeVoucher2'],5)
 def test_destroyed_wall_reopens_both_upgrade_requirements(self):
  from solution.wall_supply import wall_needs,wall_target
  raw=self.scene()
  t=Turn.from_raw(raw)
  for u in raw['teamOur']['roles']:
   if u['roleType']=='wall':u['level']=wall_target(t,t.team_our.unit(u['id']))
  t=Turn.from_raw(raw);w=next(w for w in t.team_our.roles if front_wall_number(t,w)==3)
  raw['teamOur']['roles']=[u for u in raw['teamOur']['roles'] if u['id']!=w.unit_id]
  t=Turn.from_raw(raw);need=wall_needs(t,t.team_our.unit(1),DEFAULT_CONFIG)
  self.assertEqual(need['WallUpgradeVoucher1'],1);self.assertEqual(need['WallUpgradeVoucher2'],1)
 def test_no_repeat_vouchers_after_target_levels_reached(self):
  from solution.wall_supply import wall_needs,wall_target
  raw=self.scene();t=Turn.from_raw(raw)
  for u in raw['teamOur']['roles']:
   if u['roleType']=='wall':u['level']=wall_target(t,t.team_our.unit(u['id']))
  unit(raw,1)['backpack']=['WallFixer']*6;t=Turn.from_raw(raw)
  self.assertFalse(wall_needs(t,t.team_our.unit(1),DEFAULT_CONFIG))
 def test_daytime_never_spends_wall_items(self):
  from solution.wall_supply import wall_use_item
  raw=self.scene();t=Turn.from_raw(raw);w=next(w for w in t.team_our.roles if front_wall_number(t,w)==3)
  unit(raw,w.unit_id)['health']=1;unit(raw,1)['backpack']=['WallFixer','WallUpgradeVoucher2']
  t=Turn.from_raw(raw)
  self.assertEqual(wall_use_item(t,t.team_our.unit(w.unit_id),t.team_our.unit(1),DEFAULT_CONFIG),'')
 def test_clear_night_does_not_waste_last_repair_on_half_damage(self):
  from solution.wall_supply import wall_use_item
  raw=self.scene(380);t=Turn.from_raw(raw);w=next(w for w in t.team_our.roles if front_wall_number(t,w)==3)
  unit(raw,w.unit_id).update(health=800,level=2);unit(raw,1)['backpack']=['WallFixer']
  t=Turn.from_raw(raw)
  self.assertEqual(wall_use_item(t,t.team_our.unit(w.unit_id),t.team_our.unit(1),DEFAULT_CONFIG),'')
 def test_previous_night_deadline_uses_upgrade_without_waiting_for_damage(self):
  from solution.wall_supply import wall_use_item
  raw=self.scene(645);t=Turn.from_raw(raw);w=next(w for w in t.team_our.roles if front_wall_number(t,w)==1)
  unit(raw,1)['backpack']=['WallUpgradeVoucher2'];t=Turn.from_raw(raw)
  self.assertEqual(wall_use_item(t,w,t.team_our.unit(1),DEFAULT_CONFIG),'WallUpgradeVoucher2')
 def test_insufficient_gold_preserves_basic_weapon_fund(self):
  from solution.wall_supply import wall_stock_plan
  raw=self.scene();unit(raw,10)['level']=1;raw['teamOur']['goldNum']=110
  t=Turn.from_raw(raw);p=wall_stock_plan(t,t.team_our.unit(1),BUDGET,DEFAULT_CONFIG)
  self.assertEqual(p.action.quantity,1)

class MiningAndOwnershipTests(unittest.TestCase):
 def test_day_two_forecast_only_affects_main_miner(self):
  from solution.market import PriceWindow
  raw=world(150);raw['mapInfo']['zones']=[{'neutralType':'copper','pos':{'x':11,'y':11}}, {'neutralType':'iron','pos':{'x':1,'y':3}}, {'neutralType':'vendor','pos':{'x':10,'y':13}}]
  raw['vendorShopList']=[{'name':'copper','price':20},{'name':'iron','price':3}]
  t=Turn.from_raw(raw);s=WorldState();s.ingest(t)
  s.market.windows=[PriceWindow('iron',3,4,9,rising=True,evidence='synthetic notice',source_day=2)]
  m=EconomyManager(main_miner_id=1);m.plan(t,t.team_our.unit(1),s,DEFAULT_CONFIG,BUDGET)
  self.assertEqual(m.evidence[1]['ore'],'iron')
  m=EconomyManager(main_miner_id=7);m.plan(t,t.team_our.unit(1),s,DEFAULT_CONFIG,BUDGET)
  self.assertEqual(m.evidence[1]['ore'],'copper')
  t=replace(t,round_no=275);m=EconomyManager(main_miner_id=1);m.plan(t,t.team_our.unit(1),s,DEFAULT_CONFIG,BUDGET)
  self.assertEqual(m.evidence[1]['ore'],'copper')
 def test_opening_main_miner_prefers_income_ore_to_construction_stone(self):
  raw=world(10);raw['mapInfo']['zones']=[{'neutralType':'stone','pos':{'x':11,'y':11}}, {'neutralType':'iron','pos':{'x':1,'y':2}}, {'neutralType':'vendor','pos':{'x':10,'y':13}}]
  raw['vendorShopList']=[{'name':'stone','price':1},{'name':'iron','price':3}]
  p,m=economy(raw,main_miner_id=1);self.assertEqual(m.evidence[1]['ore'],'iron')
 def test_no_forecast_does_not_guess_ore(self):
  raw=world(150);raw['mapInfo']['zones']=[{'neutralType':'copper','pos':{'x':11,'y':11}}, {'neutralType':'vendor','pos':{'x':10,'y':13}}]
  raw['vendorShopList']=[{'name':'copper','price':5}]
  p,m=economy(raw,main_miner_id=1);self.assertEqual(m.evidence[1]['ore'],'copper');self.assertNotIn('day_two_forecast',m.evidence[1])
 def test_news_context_uses_source_day_not_fixed_day(self):
  from solution.market import MarketMemory
  m=MarketMemory();m.observe('Copper mine inspection. 明日全面停工。',4)
  self.assertTrue(m.closed('copper',5));self.assertFalse(m.closed('copper',3));self.assertIsNone(m.windows[0].price)
 def test_engineer_five_stones_not_sold(self):
  raw=world(275);raw['mapInfo']['zones']=[{'neutralType':'vendor','pos':{'x':10,'y':13}}];unit(raw,1)['backpack']=['stone']*8
  p,m=economy(raw,reserve_stone={1:5});self.assertEqual((p.action.name,p.action.quantity),('stone',3))
 def test_daytime_controller_assignment_releases_worker_at_post(self):
  from solution.combat import assign_controllers
  raw=world(280);post=unit(raw,2)['pos'];unit(raw,1)['pos']=post;unit(raw,2)['pos']={'x':11,'y':12}
  t=Turn.from_raw(raw);a=assign_controllers(t,tuple(w for w in t.team_our.roles if w.is_weapon))
  self.assertEqual({x.controller.unit_id for x in a},{2})
 def test_rebuilding_precedes_shopping_and_reserves_stone(self):
  from solution.engine import AgentEngine
  for side in ('challenger','defender'):
   raw=world(651,side);t=Turn.from_raw(raw);w=next(w for w in t.team_our.roles if front_wall_number(t,w)==3)
   raw['teamOur']['roles']=[u for u in raw['teamOur']['roles'] if u['id']!=w.unit_id]
   inside=t.coordinate_frame.denormalize(replace(t.coordinate_frame.normalize(w.pos),x=t.coordinate_frame.normalize(w.pos).x-1))
   unit(raw,1)['pos']=inside.to_raw();unit(raw,1)['backpack']=['stone']*5+['WallFixer']*6
   engine=AgentEngine();out=engine.decide(raw)['roleCommandMap'];self.assertEqual(engine.planner.engineer_id,1)
   self.assertEqual(out['1']['action'],'build');self.assertEqual(out['1']['targetPos'],[w.pos.to_raw()]);self.assertEqual(engine.planner.economy.reserve_stone[1],7)

class WallLifecycleTests(unittest.TestCase):
 def test_stock_then_night_only_upgrade_completes_array_on_both_sides(self):
  from solution.wall_supply import wall_stock_plan,wall_target
  from solution.movement import schedule_moves
  for side in ('challenger','defender'):
   raw=world(420,side);raw['teamOur']['goldNum']=1000;unit(raw,3)['level']=2
   for u in raw['teamOur']['roles']:
    if u['roleType']=='wall':u.update(level=1,health=1000)
    if u['roleType']=='rocket':u['level']=3
   t=Turn.from_raw(raw);worker=unit(raw,1)
   shop=t.coordinate_frame.denormalize(__import__('solution.geometry',fromlist=['Pos']).Pos(11,10))
   worker['pos']={'x':shop.x-1,'y':shop.y}
   raw['mapInfo']['zones']=[{'neutralType':'weaponShop','pos':shop.to_raw()}]
   prices={i['name']:i['price'] for i in raw['weaponShopList']};uses=[];purchases=[]
   for r in range(420,651):
    raw['roundNo']=r;t=Turn.from_raw(raw);w=t.team_our.unit(1)
    p=wall_stock_plan(t,w,BUDGET,DEFAULT_CONFIG) if t.is_day else support_plan(t,w,DEFAULT_CONFIG,())
    a=p.action or (next(iter(schedule_moves(t,[p.move])),None) if p.move else None)
    if not a:continue
    if a.action_type=='move':worker['pos']=a.targets[0].to_raw()
    elif a.action_type=='buy':
     self.assertGreaterEqual(raw['teamOur']['goldNum'],prices[a.name]*a.quantity)
     raw['teamOur']['goldNum']-=prices[a.name]*a.quantity;worker['backpack'] += [a.name]*a.quantity;purchases.append((r,a.name,a.quantity))
    elif a.action_type=='use':
     self.assertFalse(t.is_day);self.assertIn(a.name,worker['backpack']);self.assertLessEqual(w.pos.distance_to(a.targets[0]),1)
     target=next(u for u in raw['teamOur']['roles'] if u['pos']==a.targets[0].to_raw())
     worker['backpack'].remove(a.name);target['level']+=1;target['health']=1000+500*(target['level']-1);uses.append((r,a.name))
   t=Turn.from_raw(raw)
   for w in t.team_our.roles:
    if w.role_type=='wall':self.assertGreaterEqual(w.level,wall_target(t,w),(side,front_wall_number(t,w),uses,purchases))
   self.assertGreaterEqual(worker['backpack'].count('WallFixer'),6)
   self.assertEqual(sum(q for _,n,q in purchases if n=='WallUpgradeVoucher1'),7)
   self.assertEqual(sum(q for _,n,q in purchases if n=='WallUpgradeVoucher2'),6)


class DiagnosticTests(unittest.TestCase):
 def test_turn_records_recover_worker_idle_and_item_timeline_without_operations(self):
  from tools.diagnostics.operation_report import summarize_operations
  events=[{'event':'turn','r':275,'d':3,'roles':[[1,'worker'],[2,'pioneer']], 'commands':[], 'diagnostics':{'economy':{'1':'no_complete_income_trip'}}},
          {'event':'turn','r':276,'d':3,'roles':[[1,'worker']], 'commands':[['1','buy','WallFixer',6,[],-1]], 'gold':70,'diagnostics':{'wallSupply':{'reason':'wall_stock_purchase'}}}]
  events.append({'event':'turn','r':277,'d':3,'roles':[[1,'worker',[1,1],0]],'commands':[]})
  report=summarize_operations(events,day=3,role=1)
  self.assertEqual(report['worker_days'][0]['actions']['dead'],1)
  self.assertEqual(report['worker_days'][0]['idle_reasons'],{'no_complete_income_trip':1})
  self.assertEqual(report['maintenance_timeline'][0]['quantity'],6)
 def test_mining_context_does_not_turn_road_closure_into_ore_closure(self):
  from solution.market import MarketMemory
  m=MarketMemory();m.observe('Copper mining proceeds. day 3 road closed.',2)
  self.assertFalse(m.windows)
 def test_unused_worker_voucher_does_not_steal_pioneer_upgrade_action(self):
  from solution.engine import AgentEngine
  raw=world(80);unit(raw,1)['backpack']=['WeaponUpgradeVoucher2'];unit(raw,1)['pos']={'x':3,'y':15}
  raw['robot']['roles']=[{'id':99,'roleType':'smallRobot','health':40,'pos':{'x':12,'y':15},'attackRange':3,'attackPower':5,'targetTeam':'challenger'}]
  out=AgentEngine().decide(raw)['roleCommandMap']
  self.assertFalse(out.get('1',{}).get('name','').startswith('WeaponUpgrade'))

class TwoDayOwnershipCycle(unittest.TestCase):
 def test_pioneer_funds_and_upgrades_all_guns_before_second_night(self):
  from tests.test_operating_cycle import IncomeWorld
  from solution.engine import AgentEngine
  for side in ('challenger','defender'):
   world=IncomeWorld(side);engine=AgentEngine()
   for r in range(1,201):
    raw=world.request(r);response=engine.decide(raw)
    workers={str(u['id']) for u in raw['teamOur']['roles'] if u['roleType']=='worker'}
    for actor,c in response['roleCommandMap'].items():
     if actor in workers:self.assertFalse(c.get('action') in ('buy','use') and c.get('name','').startswith('WeaponUpgrade'))
    world.apply(response)
    self.assertFalse(any(ok is False for ok in world.feedback.values()))
   self.assertEqual([u['level'] for u in world.roles if u['roleType']=='rocket'],[2,2,2],side)
