"""Synthetic treasure replies exercise execution, not natural-language grading."""
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from solution.actions import Action, ActionType
from solution.engine import AgentEngine
from solution.geometry import Pos
from solution.models import Turn
from solution.rules import DEFAULT_CONFIG
from solution.treasure import TreasureKnowledge
from tests.test_v013_operations import world
from tests.test_v014_operations import unit


def public_world(round_no=10, clue='圆槽旁有焦痕，商人还提到一块刻纹石片。'):
    raw = world(round_no)
    raw['teamOur']['goldNum'] = 1000
    for role in raw['teamOur']['roles']:
        if role['roleType'] in ('rocket', 'station'):
            role['level'] = 3
    unit(raw, 2)['pos'] = {'x': 11, 'y': 12}
    unit(raw, 7)['pos'] = {'x': 12, 'y': 12}
    raw['worldNews']['folkLegends'] = clue
    raw['weaponShopList'] += [{'name': 'BlueLamp', 'price': 15}, {'name': 'StoneSeal', 'price': 20}]
    raw['mapInfo']['zones'] = [{'neutralType': 'weaponShop', 'pos': {'x': 10, 'y': 13}}]
    return raw


def answer(knowledge, **updates):
    data = {'request_id': knowledge.request_id, 'mode': 'treasure',
            'materials': [{'item': 'BlueLamp', 'quantity': 2}],
            'location': {'x': 10, 'y': 12},
            'window': {'day': 1, 'end_day': 1, 'phase': 'day'}}
    data.update(updates)
    return data


def prepared(clue=None):
    raw = public_world() if clue is None else public_world(clue=clue)
    turn = Turn.from_raw(raw)
    knowledge = TreasureKnowledge()
    knowledge.observe(turn)
    knowledge.prompt()
    return turn, knowledge, answer(knowledge)


def ingest(knowledge, data):
    return knowledge.ingest_llm(json.dumps(data, ensure_ascii=False))


def prompt_data(prompt):
    return json.loads(prompt[prompt.rfind('\n{') + 1:])


class MinimalContractTests(unittest.TestCase):
    def test_quantity_bounds_and_duplicate_entries_are_structural_only(self):
        for quantity in (0, -1, 41, True, 1.5, '2'):
            t,k,d=prepared();d['materials']=[{'item':'BlueLamp','quantity':quantity}]
            ingest(k,d);self.assertFalse(k.materials);self.assertEqual(k.last_validation_failure['reason'],'quantity_shape')
        t,k,d=prepared();d['materials'] += [{'item':'BlueLamp','quantity':40}, {'item':'StoneSeal','quantity':1}]
        ingest(k,d);self.assertEqual(k.materials,{'BlueLamp':2,'StoneSeal':1})
        self.assertEqual(k.last_validation_failure['reason'],'duplicate_material')
    def test_chinese_prose_does_not_need_lexical_proof(self):
        for clue in ('一个小孔，孔壁有烧焦痕迹。', '商人说，那几样是旅客留下的。',
                     '石台朝山脚方向，明日开放。'):
            turn, k, data = prepared(clue)
            ingest(k, data)
            self.assertTrue(k.complete)
            self.assertEqual(k.materials, {'BlueLamp': 2})
            self.assertEqual(k.position, Pos(10, 12))
            self.assertTrue(k.available(turn))

    def test_invalid_material_entries_do_not_reject_valid_entries(self):
        t, k, d = prepared()
        d['materials'] += [{'item': 'Absent', 'quantity': 1}, {'item': [], 'quantity': 1},
                           {'item': 'StoneSeal', 'quantity': True}, {'item': 'StoneSeal', 'quantity': 41}]
        ingest(k, d)
        self.assertEqual(k.materials, {'BlueLamp': 2})
        self.assertTrue(k.complete)
        self.assertEqual(k.last_validation_failure['reason'], 'out_of_catalog')

    def test_null_and_missing_preserve_but_empty_materials_clear(self):
        t, k, d = prepared(); ingest(k, d)
        k.prompt(); ingest(k, {'request_id': k.request_id, 'mode': 'unknown', 'materials': None,
                              'location': None, 'window': None})
        self.assertTrue(k.complete)
        k.prompt(); ingest(k, {'request_id': k.request_id, 'mode': 'treasure', 'materials': []})
        self.assertFalse(k.materials); self.assertFalse(k.complete)
        self.assertEqual(k.position, Pos(10, 12))

    def test_invalid_coordinates_and_window_clear_old_value(self):
        for invalid in ({'x': 30, 'y': 12}, {'x': True, 'y': 12}, {'x': 1.0, 'y': 12}, []):
            t, k, d = prepared(); ingest(k, d); k.prompt()
            ingest(k, {'request_id': k.request_id, 'mode': 'treasure', 'location': invalid})
            self.assertIsNone(k.position); self.assertFalse(k.complete)
        for w in ({'day': 5, 'end_day': 4, 'phase': 'day'}, {'day': True, 'end_day': 1, 'phase': 'day'},
                  {'day': 0, 'end_day': 11, 'phase': 'night'}, {'day': 1, 'end_day': 1, 'phase': []}):
            t, k, d = prepared(); ingest(k, d); k.prompt()
            ingest(k, {'request_id': k.request_id, 'mode': 'treasure', 'window': w})
            self.assertIsNone(k.opening_day); self.assertFalse(k.complete)

    def test_none_clears_and_invalid_mode_is_unknown(self):
        t, k, d = prepared(); ingest(k, d); k.prompt()
        ingest(k, {'request_id': k.request_id, 'mode': 'none', 'reason': 'No treasure inferred.'})
        self.assertFalse(k.materials); self.assertIsNone(k.position); self.assertIsNone(k.opening_day)
        k.prompt(); ingest(k, answer(k, mode=['bad']))
        self.assertEqual(k.mode, 'unknown'); self.assertTrue(k.complete)

    def test_unknown_keeps_facts_and_preparation_but_defers_opening_to_model(self):
        t,k,d=prepared();d['mode']='unknown';ingest(k,d)
        self.assertTrue(k.complete)
        self.assertEqual(k.plan(t,t.team_our.unit(2),DEFAULT_CONFIG,1000).action.name,'BlueLamp')
        pioneer=replace(t.team_our.unit(2),backpack=('BlueLamp','BlueLamp'))
        self.assertFalse(k.can_attempt(t,pioneer,DEFAULT_CONFIG))
        k.prompt();ingest(k,{'request_id':k.request_id,'mode':'treasure'})
        self.assertTrue(k.can_attempt(t,pioneer,DEFAULT_CONFIG))

    def test_request_identity_and_malformed_reply_have_one_retry(self):
        t, k, d = prepared()
        for value in (None, True, k.request_id + 1):
            ingest(k, {**d, 'request_id': value})
            self.assertFalse(k.materials)
            self.assertEqual(k.last_validation_failure['reason'], 'request_id_mismatch')
        t, k, d = prepared(); k.ingest_llm('{ broken')
        self.assertTrue(k.retry_pending); k.prompt(); k.ingest_llm('{ broken')
        self.assertFalse(k.needs_analysis())
        self.assertEqual(k.last_validation_failure['reason'], 'invalid_json_schema')


class MemoryAndPromptTests(unittest.TestCase):
    def test_public_property_hints_are_filtered_and_runtime_description_wins(self):
        raw=public_world();raw['weaponShopList'].append({'name':'StarSand','price':23})
        t=Turn.from_raw(raw);k=TreasureKnowledge();k.observe(t)
        p=prompt_data(k.prompt());catalog={i['name']:i for i in p['shop_catalog']}
        self.assertEqual(catalog['StarSand']['description_source'],'public_rule_hint')
        self.assertEqual(catalog['StarSand']['price'],23)
        self.assertNotIn('AcientTablet',catalog)
        self.assertEqual(catalog['BlueLamp']['description_source'],'unavailable')
        raw['weaponShopList'][-1]['description']='Synthetic map-specific description.'
        k.observe(Turn.from_raw(raw));p=prompt_data(k.prompt())
        entry=next(i for i in p['shop_catalog'] if i['name']=='StarSand')
        self.assertEqual(entry['description'],'Synthetic map-specific description.')
        self.assertEqual(entry['description_source'],'runtime')

    def test_previous_result_is_typed_and_request_numbers_increase(self):
        t,k,d=prepared();ingest(k,d);first=k.request_id
        p=prompt_data(k.prompt())
        self.assertEqual(p['request_id'],first+1)
        self.assertEqual(p['previous_result']['materials'],[{'item':'BlueLamp','quantity':2}])
        self.assertEqual(p['previous_result']['location'],{'x':10,'y':12})

    def test_price_changes_do_not_repeat_interpretation(self):
        t,k,d=prepared();ingest(k,d)
        k.observe(replace(t,weapon_shop=tuple(replace(i,price=i.price+1) for i in t.weapon_shop)))
        self.assertFalse(k.needs_analysis())

    def test_persistent_broadcast_keeps_original_source_day(self):
        t,k,d=prepared('明天开放的消息。');k.observe(replace(t,round_no=131))
        self.assertEqual(k.folk_legends[1],'明天开放的消息。')
        self.assertEqual(k.folk_legends[2],'')
        self.assertEqual(prompt_data(k.prompt())['current_day'],2)

    def test_raw_chinese_accumulates_by_source_day_without_repeat(self):
        t, k, d = prepared('第一天的原始中文。'); version = k.version
        k.observe(t); self.assertEqual(k.version, version)
        k.observe(replace(t, world_news=replace(t.world_news, folk_legends='同一天新增的中文。')))
        k.observe(replace(t, round_no=131, world_news=replace(t.world_news, folk_legends='第二天的原始中文。')))
        self.assertEqual(k.folk_legends[1], '第一天的原始中文。\n同一天新增的中文。')
        self.assertEqual(k.folk_legends[2], '第二天的原始中文。')
        p = prompt_data(k.prompt()); self.assertEqual(p['current_day'], 2)
        self.assertEqual(p['folk_legends']['1'], k.folk_legends[1])
        self.assertEqual(p['map'], {'width': 30, 'height': 24})

    def test_day_limits_preserve_all_days_and_report_omissions(self):
        raw = public_world(); k = TreasureKnowledge()
        for day in range(1, 11):
            raw['roundNo'] = (day - 1) * 130 + 1
            raw['worldNews']['folkLegends'] = f'第{day}天的新传闻。' + '甲乙丙丁' * 2000
            k.observe(Turn.from_raw(raw))
        p = prompt_data(k.prompt())
        self.assertEqual(set(p['folk_legends']), {str(n) for n in range(1, 11)})
        self.assertTrue(all(len(v) == 6000 for v in p['folk_legends'].values()))
        self.assertGreater(k.omitted, 0); self.assertLessEqual(k.memory_bytes, 240000)
        self.assertTrue(all(p['folklore_limits'][str(n)]['truncated'] for n in range(1, 11)))

    def test_catalog_removal_clears_materials_and_requires_analysis(self):
        t, k, d = prepared(); ingest(k, d)
        t = replace(t, weapon_shop=tuple(i for i in t.weapon_shop if i.name != 'BlueLamp'))
        k.observe(t)
        self.assertFalse(k.materials); self.assertTrue(k.needs_analysis())
        self.assertEqual(k.last_validation_failure['reason'], 'catalog_item_removed')

    def test_delayed_reply_preserves_facts_and_new_clue_needs_analysis(self):
        t, k, d = prepared()
        k.observe(replace(t, round_no=11, world_news=replace(t.world_news, folk_legends='刚收到后续时间线索。')))
        ingest(k, d)
        self.assertTrue(k.complete); self.assertTrue(k.needs_analysis())
        k.prompt(); ingest(k, {'request_id': k.request_id, 'mode': 'unknown'})
        self.assertTrue(k.complete)

    def test_market_only_reply_cannot_erase_treasure(self):
        t, k, d = prepared(); ingest(k, d)
        p = prompt_data(k.prompt('ore news', 1, purpose='market_only'))
        self.assertNotIn('folk_legends', p)
        ingest(k, {'request_id': k.request_id, 'mode': 'none', 'materials': [], 'market': []})
        self.assertTrue(k.complete)


class ExecutionTests(unittest.TestCase):
    def test_owned_items_adjacency_and_window_are_required(self):
        t, k, d = prepared(); ingest(k, d)
        self.assertFalse(k.can_attempt(t, t.team_our.unit(2), DEFAULT_CONFIG))
        p = replace(t.team_our.unit(2), backpack=('BlueLamp', 'BlueLamp'))
        self.assertTrue(k.can_attempt(t, p, DEFAULT_CONFIG))
        self.assertFalse(k.can_attempt(t, replace(p, pos=Pos(10, 12)), DEFAULT_CONFIG))
        self.assertFalse(k.can_attempt(replace(t, round_no=71), p, DEFAULT_CONFIG))
        self.assertFalse(k.available(replace(t, round_no=71)))
        self.assertIsNone(k.plan(replace(t, round_no=71), p, DEFAULT_CONFIG, 1000).action)
        self.assertEqual(k.reason, 'window_expired')

    def test_partial_preparation_and_shop_interaction(self):
        t, k, d = prepared(); d.update(location=None, window=None); ingest(k, d)
        plan = k.plan(t, t.team_our.unit(2), DEFAULT_CONFIG, 1000)
        self.assertEqual(plan.action.name, 'BlueLamp'); self.assertFalse(k.complete)
        p = replace(t.team_our.unit(2), pos=Pos(14, 12))
        plan = k.plan(t, p, DEFAULT_CONFIG, 1000)
        self.assertIsNone(plan.action); self.assertIsNotNone(plan.move)

    def test_capacity_and_defense_reserve_survive(self):
        t, k, d = prepared(); ingest(k, d)
        p = replace(t.team_our.unit(2), backpack_capacity=1, backpack=('other',))
        self.assertIsNone(k.plan(t, p, DEFAULT_CONFIG, 1000).action)
        self.assertEqual(k.reason, 'material_capacity')
        self.assertIsNone(k.plan(t, t.team_our.unit(2), DEFAULT_CONFIG, 125).action)
        self.assertEqual(k.reason, 'material_funding_gap')

    def test_gold_cap_is_cumulative_and_uses_current_prices(self):
        t, k, d = prepared(); ingest(k, d)
        cfg = replace(DEFAULT_CONFIG, treasure_material_gold_cap=50)
        action = k.plan(t, t.team_our.unit(2), cfg, 1000).action
        k.issued(t, action); self.assertEqual(k.material_spent, 30)
        self.assertIsNone(k.plan(t, t.team_our.unit(2), cfg, 1000).action)
        self.assertEqual(k.reason, 'material_gold_cap')
        k.material_spent = 0
        t = replace(t, weapon_shop=tuple(replace(i, price=30) if i.name=='BlueLamp' else i for i in t.weapon_shop))
        k.observe(t)
        self.assertIsNone(k.plan(t, t.team_our.unit(2), cfg, 1000).action)
        self.assertEqual(k.reason, 'material_gold_cap')

    def test_far_future_does_not_occupy_pioneer_and_night_needs_guard(self):
        t, k, d = prepared(); d['window']={'day': 3, 'end_day': 3, 'phase': 'night'}; ingest(k, d)
        p = replace(t.team_our.unit(2), backpack=('BlueLamp', 'BlueLamp'))
        plan = k.plan(t, p, DEFAULT_CONFIG, 1000)
        self.assertIsNone(plan.move); self.assertEqual(k.reason, 'future_window_departure_not_due')
        night = replace(t, round_no=331)
        self.assertIsNone(k.plan(night, p, DEFAULT_CONFIG, 1000).action)
        self.assertEqual(k.reason, 'await_guard_handover')
        self.assertEqual(k.plan(night, p, DEFAULT_CONFIG, 1000, guard_ready=True).action.action_type, ActionType.SUMMON_TREASURE)

    def test_feedback_uses_issued_candidate_not_later_model_update(self):
        t, k, d = prepared(); ingest(k, d)
        k.issued(t, Action(2, ActionType.SUMMON_TREASURE, targets=(k.position,), items=k.items))
        k.prompt(); ingest(k, answer(k, materials=[{'item':'StoneSeal','quantity':1}]))
        k.apply_result(3)
        self.assertIn(('BlueLamp','BlueLamp'), k.rejected_material_sets)
        self.assertNotIn(('StoneSeal',), k.rejected_material_sets)
        self.assertTrue(k.available(t))
        p = prompt_data(k.prompt())
        self.assertEqual(p['platform_feedback'][-1]['result_code'], 3)
        self.assertEqual(p['platform_feedback'][-1]['materials'][0]['item'], 'BlueLamp')

    def test_site_blacklist_needs_changed_site_or_time_and_max_two_attempts(self):
        t, k, d = prepared(); ingest(k, d)
        k.issued(t, Action(2, ActionType.SUMMON_TREASURE, targets=(k.position,), items=k.items)); k.apply_result(2)
        k.prompt(); ingest(k, answer(k, materials=[{'item':'StoneSeal','quantity':1}]))
        self.assertFalse(k.available(t))
        k.prompt(); ingest(k, answer(k, location={'x':12,'y':13}, materials=[{'item':'StoneSeal','quantity':1}]))
        self.assertTrue(k.available(t))
        k.issued(t, Action(2, ActionType.SUMMON_TREASURE, targets=(k.position,), items=k.items)); k.apply_result(3)
        self.assertEqual(k.attempt_count, 2); self.assertFalse(k.needs_analysis())
        k.prompt(); ingest(k, answer(k, location={'x':13,'y':13}))
        self.assertFalse(k.available(t)); self.assertEqual(k.plan(t,t.team_our.unit(2),DEFAULT_CONFIG,1000).action, None)
        self.assertEqual(k.reason, 'attempt_limit')

    def test_success_and_already_taken_exhaust_without_further_procurement(self):
        for result in (1,4):
            t,k,d=prepared(); ingest(k,d)
            k.issued(t,Action(2,ActionType.SUMMON_TREASURE,targets=(k.position,),items=k.items));k.apply_result(result)
            self.assertTrue(k.exhausted);self.assertFalse(k.available(t));self.assertFalse(k.needs_analysis())


class EngineTests(unittest.TestCase):
    def test_night_opening_waits_for_observed_backup_arrival(self):
        from solution.defense import build_defense_layout
        raw=public_world(70);layout=build_defense_layout(Turn.from_raw(raw));post=layout.controller_sites[0]
        unit(raw,2)['pos']=post.to_raw();engine=AgentEngine();engine.decide(raw);k=engine.planner.treasure
        unit(raw,2)['backpack']=['BlueLamp']*2;opened=False
        for r in range(71,111):
            raw['roundNo']=r
            raw['llmResp']=json.dumps(answer(k,window={'day':1,'end_day':1,'phase':'night'})) if r==71 else ''
            response=engine.decide(raw)
            opening=response['roleCommandMap'].get('2',{}).get('action')=='summonTreasure'
            if opening:
                self.assertTrue(engine.planner.guard.away)
                self.assertEqual(unit(raw,engine.planner.guard.backup_id)['pos'],post.to_raw())
                opened=True;break
            if r==71:self.assertFalse(opening)
            for actor,command in response['roleCommandMap'].items():
                if command['action']=='move':unit(raw,int(actor))['pos']=command['targetPos'][0]
        self.assertTrue(opened);self.assertEqual(engine.planner.failure_count,0)

    def test_full_ten_day_text_survives_public_prompt_serialization(self):
        engine=AgentEngine();raw=public_world()
        for day in range(1,11):
            raw['roundNo']=(day-1)*130+1;raw['worldNews']['folkLegends']=f'第{day}批消息。'+'山川变化。'*1400
            response=engine.decide(raw)
        p=prompt_data(response['prompt']);self.assertEqual(len(p['folk_legends']),10)
        self.assertEqual(sum(len(v) for v in p['folk_legends'].values()),60000)
        self.assertEqual(engine.planner.failure_count,0)

    def test_buy_travel_open_reject_change_combination_then_open(self):
        engine=AgentEngine();raw=public_world();self.assertIn('prompt',engine.decide(raw));k=engine.planner.treasure
        raw['roundNo']+=1;raw['llmResp']=json.dumps(answer(k,location={'x':15,'y':12}))
        response=engine.decide(raw);self.assertEqual(response['roleCommandMap']['2']['action'],'buy')
        unit(raw,2)['backpack']=['BlueLamp']*2;raw['teamOur']['goldNum']-=30
        moved=False
        for _ in range(12):
            raw['roundNo']+=1;raw['llmResp']='';response=engine.decide(raw);command=response['roleCommandMap'].get('2',{})
            if command.get('action')=='summonTreasure':break
            self.assertEqual(command.get('action'),'move');unit(raw,2)['pos']=command['targetPos'][0];moved=True
        else:self.fail('did not open')
        self.assertTrue(moved);self.assertEqual(k.attempt_count,1)
        raw['roundNo']+=1;raw['lastSummonTreasureResult']=3;unit(raw,2)['backpack']=[]
        response=engine.decide(raw);self.assertIn('prompt',response)
        self.assertNotIn(response['roleCommandMap'].get('2',{}).get('action'),('buy','summonTreasure'))
        data=prompt_data(response['prompt']);self.assertEqual(data['platform_feedback'][-1]['result_code'],3)
        raw['roundNo']+=1;raw['lastSummonTreasureResult']=0
        raw['llmResp']=json.dumps(answer(k,location={'x':15,'y':12},materials=[{'item':'StoneSeal','quantity':1}]))
        bought=False
        for _ in range(24):
            response=engine.decide(raw);command=response['roleCommandMap'].get('2',{})
            if command.get('action')=='move':unit(raw,2)['pos']=command['targetPos'][0]
            elif command.get('action')=='buy':
                self.assertEqual(command['name'],'StoneSeal');unit(raw,2)['backpack']=['StoneSeal'];raw['teamOur']['goldNum']-=20;bought=True
            elif command.get('action')=='summonTreasure':break
            raw['roundNo']+=1;raw['llmResp']=''
        else:self.fail('second opening did not happen')
        self.assertTrue(bought);self.assertEqual(k.attempt_count,2);self.assertEqual(k.material_spent,50)
        raw['roundNo']+=1;raw['llmResp']='';raw['lastSummonTreasureResult']=1
        engine.decide(raw);self.assertTrue(k.exhausted);self.assertEqual(engine.planner.failure_count,0)

    def test_malformed_partial_and_unknown_replies_preserve_progress(self):
        engine=AgentEngine();raw=public_world();engine.decide(raw);k=engine.planner.treasure
        raw['roundNo']+=1;raw['llmResp']='{ broken';response=engine.decide(raw)
        self.assertIn('prompt',response);self.assertEqual(k.last_validation_failure['reason'],'invalid_json_schema')
        raw['roundNo']+=1;raw['llmResp']=json.dumps(answer(k,location=None,window=None))
        response=engine.decide(raw);self.assertEqual(response['roleCommandMap']['2']['name'],'BlueLamp')
        unit(raw,2)['backpack']=['BlueLamp']*2;raw['roundNo']+=1;raw['llmResp']=''
        raw['worldNews']['folkLegends']='后续线索来了，但尚不知道祭坛在哪。';response=engine.decide(raw)
        self.assertIn('prompt',response);raw['roundNo']+=1;raw['llmResp']=json.dumps({'request_id':k.request_id,'mode':'unknown'})
        response=engine.decide(raw);self.assertEqual(k.materials,{'BlueLamp':2})
        self.assertNotEqual(response['roleCommandMap'].get('2',{}).get('action'),'summonTreasure')
        self.assertEqual(k.responses,3)

    def test_continuous_new_clues_with_delayed_replies_do_not_stall(self):
        engine=AgentEngine();raw=public_world();engine.decide(raw);k=engine.planner.treasure
        raw['roundNo']+=1;raw['llmResp']=json.dumps(answer(k,location=None,window=None));raw['worldNews']['folkLegends']='又来一条消息。'
        response=engine.decide(raw);self.assertEqual(response['roleCommandMap']['2']['action'],'buy')
        unit(raw,2)['backpack']=['BlueLamp']*2
        raw['roundNo']+=1;raw['llmResp']=json.dumps(answer(k,materials=None));raw['worldNews']['folkLegends']='今天还有补充。'
        response=engine.decide(raw);self.assertEqual(response['roleCommandMap']['2']['action'],'summonTreasure')
        self.assertGreater(k.version,k.analyzed_version)

    def test_wrong_request_cannot_purchase_and_diagnostic_persists(self):
        engine=AgentEngine();raw=public_world();engine.decide(raw);k=engine.planner.treasure
        raw['roundNo']+=1;raw['llmResp']=json.dumps(answer(k,request_id=0));response=engine.decide(raw)
        self.assertNotEqual(response['roleCommandMap'].get('2',{}).get('name'),'BlueLamp')
        raw['roundNo']+=1;raw['llmResp']='';engine.decide(raw)
        self.assertEqual(k.last_validation_failure['reason'],'request_id_mismatch')

    def test_timeout_requires_current_request_identity(self):
        engine=AgentEngine();raw=public_world();engine.decide(raw);k=engine.planner.treasure;old=answer(k)
        raw['roundNo']+=5;response=engine.decide(raw);self.assertIn('prompt',response)
        raw['roundNo']+=1;raw['llmResp']=json.dumps(old);response=engine.decide(raw)
        self.assertFalse(k.materials);self.assertEqual(k.last_validation_failure['reason'],'request_id_mismatch')

    def test_new_match_resets_memory_budget_and_blacklists(self):
        engine=AgentEngine();raw=public_world();engine.decide(raw);old=engine.planner.treasure
        old.material_spent=200;old.attempt_count=2;old.rejected_material_sets.add(('BlueLamp',))
        raw=public_world(1,'新对局的另一段原文。');engine.decide(raw);k=engine.planner.treasure
        self.assertIsNot(k,old);self.assertEqual(k.material_spent,0);self.assertEqual(k.attempt_count,0)
        self.assertFalse(k.rejected_material_sets);self.assertNotIn(old.folk_legends[1],k.folk_legends[1])

    def test_task_and_daily_quota_gates(self):
        from solution.planner import CompetitionPlanner
        from solution.state import WorldState,LlmBudget
        from solution.tasking import AdvancedPlan
        t,k,d=prepared();p=CompetitionPlanner(treasure=k);s=WorldState();s.ingest(t);budget=LlmBudget();budget.refresh(t)
        active=replace(t,phase_task='Synthetic active task')
        self.assertEqual(p._background_prompt(active,s,budget,AdvancedPlan()),'')
        self.assertEqual(p._background_prompt(t,s,budget,AdvancedPlan(action=Action(2,ActionType.ACCEPT_TASK))),'')
        for _ in range(3):
            p.treasure_prompt_pending=False;k.version+=1
            self.assertTrue(p._background_prompt(t,s,budget,AdvancedPlan()))
            budget.mark_response_received()
        p.treasure_prompt_pending=False;k.version+=1
        self.assertFalse(p._background_prompt(t,s,budget,AdvancedPlan()))
        next_day=replace(t,round_no=131);budget.refresh(next_day)
        self.assertTrue(p._background_prompt(next_day,s,budget,AdvancedPlan()))


class DiagnosticTests(unittest.TestCase):
    def test_failure_counts_preserve_missing_response_and_dedup_distinction(self):
        from solution.telemetry import Telemetry
        from tools.diagnostics.operation_report import summarize_operations
        events=[]
        def capture(_self,event,**kw):events.append(event);return True
        with patch.object(Telemetry,'emit',capture):
            engine=AgentEngine();raw=public_world();engine.decide(raw)
            for _ in range(2):
                raw['roundNo']+=1;raw['llmResp']='{ broken';engine.decide(raw)
            raw['roundNo']+=1;raw['llmResp']='';engine.decide(raw)
        report=summarize_operations(events)
        self.assertEqual(report['treasure_requests'],2);self.assertEqual(report['treasure_responses'],2)
        self.assertEqual(report['treasure_validation_reasons']['invalid_json_schema'],2)
        self.assertEqual(report['last_treasure_validation_failure']['reason'],'invalid_json_schema')

    def test_redaction_and_logging_budgets(self):
        from solution.operation_audit import OperationAudit
        t,k,d=prepared();audit=OperationAudit(match_limit=20000,flow_limit=20000)
        audit.emit(t,'model_response',{'token':'synthetic-secret-123','output':'token=synthetic-secret-123'},flow='treasure',critical=True)
        self.assertNotIn('synthetic-secret-123',json.dumps(audit.drain()))
        for n in range(100):audit.emit(t,'validation',{'n':n,'text':'x'*9000},flow='treasure',critical=True)
        self.assertGreater(audit.dropped,0);self.assertLessEqual(audit.used,20000)

    def test_treasure_reward_removes_concurrent_sale(self):
        from types import SimpleNamespace
        from solution.economy import EconomyManager
        from solution.logistics import LogisticsManager
        from solution.operation_audit import OperationAudit
        from solution.roles import GuardHandover
        t,k,d=prepared();audit=OperationAudit()
        planner=SimpleNamespace(treasure=k,guard=GuardHandover(),support_id=1,engineer_id=1,economy=EconomyManager(),logistics=LogisticsManager())
        audit.record(t,{'roleCommandMap':{'2':{'action':'summonTreasure'},'1':{'action':'sell','name':'iron','num':2}}},planner);audit.drain()
        nxt=replace(t,round_no=t.round_no+1,team_our=replace(t.team_our,gold=t.team_our.gold+206),last_action_results={1:True,2:True},last_summon_treasure_result=1)
        audit.record(nxt,{'roleCommandMap':{}},planner)
        e=next(e for e in audit.drain() if e['stage']=='settlement')
        self.assertEqual(json.loads(e['detail']['text'])['gold'],200)

    def test_readonly_report_filters_day_role_stage(self):
        from tools.diagnostics.operation_report import summarize_operations
        events=[{'event':'operation','day':2,'role':1,'stage':'role','detail':{}}, {'event':'operation','day':3,'role':7,'stage':'role','detail':{}}]
        self.assertEqual(summarize_operations(events,3,7,'role')['events'],1)


if __name__ == '__main__':
    unittest.main()
