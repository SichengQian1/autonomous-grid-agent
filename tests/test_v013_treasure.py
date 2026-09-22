import json
import unittest
from dataclasses import replace
from tests.test_v013_operations import world
from solution.models import Turn
from solution.treasure import TreasureKnowledge
from solution.rules import DEFAULT_CONFIG
from solution.operation_audit import OperationAudit


def evidence(k,text):
    return [{'source':sid,'quote':text} for sid,s in k.sources.items() if text in s['text']][:1]


def prepared(text='Need 2 cold lights. Open at (10,12), day 3 night.',day=1):
    raw=world((day-1)*130+2)
    raw['worldNews']['folkLegends']=text
    raw['weaponShopList'] += [{'name':'BlueLamp','price':15,'description':'A lasting cold light.'}]
    t=Turn.from_raw(raw);k=TreasureKnowledge();k.observe(t);k.prompt()
    e=evidence(k,text)
    data={'mode':'treasure','materials':[{'item':'BlueLamp','quantity':2,'effect':'cold light','shop_quote':'lasting cold light','evidence':e,'quantity_evidence':e}],
          'kind_count':1,'total_quantity':2,'count_evidence':e,'materials_complete':True,
          'location':{'x':10,'y':12,'evidence':e},'window':{'day':3,'end_day':3,'phase':'night','evidence':e},'unknown':[],'conflicts':[]}
    return t,k,data

class TreasureTests(unittest.TestCase):
    def test_complete_single_day_does_not_require_two_days(self):
        t,k,d=prepared();k.ingest_llm(json.dumps({'treasure':d}))
        self.assertTrue(k.complete);self.assertEqual(k.items,('BlueLamp','BlueLamp'))
    def test_partial_individual_material_can_be_bought_without_location(self):
        t,k,d=prepared('Two cold lights are required. More requirements to follow.')
        d.update(location=None,window=None,materials_complete=False,unknown=['other materials'])
        k.ingest_llm(json.dumps({'treasure':d}));self.assertTrue(k.materials);self.assertFalse(k.complete)
        raw=world();raw['weaponShopList'] += [{'name':'BlueLamp','price':15,'description':'A lasting cold light.'}]
        raw['mapInfo']['zones']=[{'neutralType':'weaponShop','pos':{'x':10,'y':13}}]
        raw['teamOur']['roles'][1]['pos']={'x':10,'y':12}
        turn=Turn.from_raw(raw)
        p=k.plan(turn,turn.team_our.unit(2),DEFAULT_CONFIG,480)
        self.assertEqual(p.action.name,'BlueLamp');self.assertEqual(p.action.quantity,2)
    def test_confidence_alone_never_authorizes(self):
        t,k,d=prepared();k.ingest_llm(json.dumps({'treasure':{'x':10,'y':12,'day':1,'items':['BlueLamp'],'confidence':1.0}}))
        self.assertFalse(k.complete)
    def test_description_and_quantity_are_independently_required(self):
        for field,value in [('shop_quote','burning fire'),('quantity_evidence',[])]:
            t,k,d=prepared();d['materials'][0][field]=value;k.ingest_llm(json.dumps({'treasure':d}))
            self.assertFalse(k.materials)
    def test_distinct_count_is_not_total_count(self):
        t,k,d=prepared();d['kind_count']=2;k.ingest_llm(json.dumps({'treasure':d}));self.assertFalse(k.complete)
    def test_conflicting_and_revised_clues(self):
        t,k,d=prepared();d['conflicts']=['two incompatible sites'];k.ingest_llm(json.dumps({'treasure':d}));self.assertFalse(k.complete)
        k.observe(replace(t,world_news=replace(t.world_news,folk_legends='Correction: use (11,12) instead of the former site.')))
        k.prompt();d['conflicts']=[];d['location']={'x':11,'y':12,'evidence':evidence(k,'Correction: use (11,12) instead of the former site.')}
        k.ingest_llm(json.dumps({'treasure':d}));self.assertTrue(k.complete);self.assertEqual(k.position.x,11)
    def test_old_clue_can_be_recalled_after_more_than_8000_characters(self):
        t,k,d=prepared();old=next(iter(k.sources))
        for n in range(20):k.observe(replace(t,world_news=replace(t.world_news,folk_legends=f'Later report {n}. '+'ordinary sentence. '*100)))
        k.prompt();self.assertIn(old,k.sources)
        k.ingest_llm(json.dumps({'treasure':{'lookup':[old]}}))
        prompt=k.prompt();self.assertIn('Need 2 cold lights',prompt);self.assertIn(old,k.request_sources)
    def test_night_requires_confirmed_guard_and_window(self):
        t,k,d=prepared();k.ingest_llm(json.dumps({'treasure':d}))
        raw=world(331);raw['teamOur']['roles'][1].update(pos={'x':10,'y':11},backpack=['BlueLamp']*2)
        turn=Turn.from_raw(raw);pioneer=turn.team_our.unit(2)
        self.assertIsNone(k.plan(turn,pioneer,DEFAULT_CONFIG,480).action)
        p=k.plan(turn,pioneer,DEFAULT_CONFIG,480,guard_ready=True)
        self.assertEqual(p.action.action_type,'summonTreasure')
        k.issued(turn,p.action);k.apply_result(3)
        self.assertFalse(k.can_attempt(turn,pioneer,DEFAULT_CONFIG))
        k.apply_result(4);self.assertTrue(k.exhausted)
    def test_memory_and_log_budget_redaction(self):
        t,k,d=prepared();audit=OperationAudit(match_limit=20000,flow_limit=20000)
        audit.emit(t,'model_response',{'token':'synthetic-secret-123','output':'token=synthetic-secret-123'},flow='treasure',critical=True)
        output=json.dumps(audit.drain());self.assertNotIn('synthetic-secret-123',output)
        for n in range(100):audit.emit(t,'failure',{'n':n,'text':'x'*9000},critical=True)
        self.assertGreater(audit.dropped,0);self.assertLessEqual(audit.used,20000)

class TreasureIntegrationTests(unittest.TestCase):
    def test_incremental_location_preserves_verified_materials(self):
        t,k,d=prepared();d.update(location=None,window=None,materials_complete=False,unknown=['site'])
        k.ingest_llm(json.dumps({'treasure':d}))
        clue='The site is (10,12), open day 3 night.'
        k.observe(replace(t,world_news=replace(t.world_news,folk_legends=clue)))
        k.prompt();e=evidence(k,clue)
        k.ingest_llm(json.dumps({'treasure':{'mode':'treasure','location':{'x':10,'y':12,'evidence':e},
            'window':{'day':3,'end_day':3,'phase':'night','evidence':e},'materials_complete':True,'unknown':[]}}))
        self.assertEqual(k.materials,{'BlueLamp':2});self.assertTrue(k.complete)
    def test_price_change_does_not_repeat_semantic_analysis(self):
        t,k,d=prepared();k.ingest_llm(json.dumps({'treasure':d}))
        turn=replace(t,weapon_shop=tuple(replace(i,price=i.price+1) for i in t.weapon_shop))
        k.observe(turn);self.assertFalse(k.needs_analysis())
    def test_far_future_window_keeps_pioneer_available(self):
        t,k,d=prepared();k.ingest_llm(json.dumps({'treasure':d}))
        p=replace(t.team_our.unit(2),backpack=('BlueLamp','BlueLamp'))
        plan=k.plan(t,p,DEFAULT_CONFIG,480)
        self.assertIsNone(plan.move);self.assertEqual(k.reason,'future_window_departure_not_due')
    def test_treasure_gold_removes_concurrent_sale(self):
        from types import SimpleNamespace
        from solution.economy import EconomyManager
        from solution.logistics import LogisticsManager
        from solution.roles import GuardHandover
        t,k,d=prepared();audit=OperationAudit()
        planner=SimpleNamespace(treasure=k,guard=GuardHandover(),support_id=1,engineer_id=1,economy=EconomyManager(),logistics=LogisticsManager())
        audit.record(t,{'roleCommandMap':{'2':{'action':'summonTreasure'},'1':{'action':'sell','name':'iron','num':2}}},planner)
        audit.drain()
        next_turn=replace(t,round_no=t.round_no+1,team_our=replace(t.team_our,gold=t.team_our.gold+206),last_action_results={1:True,2:True},last_summon_treasure_result=1)
        audit.record(next_turn,{'roleCommandMap':{}},planner)
        e=next(e for e in audit.drain() if e['stage']=='settlement')
        self.assertEqual(json.loads(e['detail']['text'])['gold'],200)
    def test_background_prompt_cannot_interrupt_active_task(self):
        from solution.planner import CompetitionPlanner
        from solution.state import LlmBudget,WorldState
        from solution.tasking import AdvancedPlan
        t,k,d=prepared();t=replace(t,phase_task='Synthetic active task')
        p=CompetitionPlanner(treasure=k);s=WorldState();s.ingest(t)
        self.assertEqual(p._background_prompt(t,s,LlmBudget(),AdvancedPlan()),'')
    def test_readonly_report_filters_day_role_stage(self):
        from tools.diagnostics.operation_report import summarize_operations
        events=[{'event':'operation','day':2,'role':1,'stage':'role','detail':{}}, {'event':'operation','day':3,'role':7,'stage':'role','detail':{}}]
        self.assertEqual(summarize_operations(events,3,7,'role')['events'],1)

class MalformedEvidenceTests(unittest.TestCase):
    def test_non_string_source_reference_is_rejected(self):
        t,k,d=prepared()
        d['materials'][0]['evidence']=[{'source':[],'quote':'invalid reference'}]
        k.ingest_llm(json.dumps({'treasure':d}))
        self.assertFalse(k.materials)
    def test_non_string_item_and_quote_do_not_interrupt_next_prompt(self):
        t,k,d=prepared();d['materials'][0].update(item=[],shop_quote=[])
        k.ingest_llm(json.dumps({'treasure':d}));self.assertFalse(k.materials)
        self.assertIn('sources',k.prompt())
