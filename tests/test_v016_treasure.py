"""Synthetic folklore and catalog hypotheses; no match answers or source IDs."""
import json
import unittest
from dataclasses import replace
from tests.test_v013_treasure import prepared,evidence
from solution.treasure import TreasureKnowledge
from solution.rules import DEFAULT_CONFIG
from tests.test_v013_operations import world
from tests.test_v014_operations import unit
from solution.models import Turn


def candidate(empty=False):
    t,k,d=prepared()
    if empty:
        t=replace(t,weapon_shop=tuple(replace(i,description='') for i in t.weapon_shop))
        k=TreasureKnowledge();k.observe(t);k.prompt()
    d['materials'][0].update(object='cold lights',object_quote='cold lights',effect_quote='cold light',
        derivation='The lamp name suggests the cited light effect; this is a hypothesis.')
    d['location']['derivation']={'kind':'coordinate_literal'}
    return t,k,d


class CandidateLifecycleTests(unittest.TestCase):
    def test_five_separate_arrivals_accumulate_then_become_actionable(self):
        clues=['Bring ceremonial lights.','These ceremonial lights must provide cold light.',
               'Bring 2 ceremonial lights; this is one kind, two pieces total.',
               'The exact site is (10,12).','Open tomorrow during daytime.']
        raw=public_world(2,clues[0]);t=Turn.from_raw(raw);k=TreasureKnowledge();k.observe(t);k.prompt()
        k.ingest_llm(json.dumps({'treasure':{'mode':'unknown'}}))
        for index,round_no in ((1,132),(2,262),(3,392),(4,522)):
            raw['roundNo']=round_no;raw['worldNews']['folkLegends']=clues[index]
            t=Turn.from_raw(raw);k.observe(t);k.prompt()
            d={'mode':'treasure'}
            if index==2:
                d.update(materials=[{'item':'BlueLamp','quantity':2,'object_quote':'ceremonial lights',
                    'effect':'cold light','effect_quote':'cold light','derivation':'Name-based hypothesis.',
                    'evidence':evidence(k,clues[0])+evidence(k,clues[1]),'quantity_evidence':evidence(k,clues[2])}],
                    materials_complete=True,kind_count=1,total_quantity=2,count_evidence=evidence(k,clues[2]))
            if index==3:d['location']={'x':10,'y':12,'derivation':{'kind':'coordinate_literal'},'evidence':evidence(k,clues[3])}
            if index==4:d['window']={'day':6,'end_day':6,'phase':'day','evidence':evidence(k,clues[4])}
            k.ingest_llm(json.dumps({'request_id':k.request_id,'treasure':d}))
            if index>=2:self.assertEqual(k.materials,{'BlueLamp':2})
            if index==2:self.assertEqual(k.plan(t,t.team_our.unit(2),DEFAULT_CONFIG,1000).action.name,'BlueLamp')
        self.assertEqual(len(k.sources),5);self.assertEqual(k.reason,'candidate_ready')
        raw['roundNo']=652;unit(raw,2)['backpack']=['BlueLamp']*2;t=Turn.from_raw(raw)
        self.assertTrue(k.can_attempt(t,t.team_our.unit(2),DEFAULT_CONFIG))

    def test_phase_requires_evidence_but_nearby_landmark_does_not_erase_exact_site(self):
        t,k,d=candidate();clue='Open exactly at (10,12); nearby is a shop. Open day 3.'
        k.observe(replace(t,world_news=replace(t.world_news,folk_legends=clue)));k.prompt()
        d['location']['evidence']=evidence(k,clue);d['window']['evidence']=evidence(k,clue)
        k.ingest_llm(json.dumps({'treasure':d}));self.assertEqual(k.position.x,10)
        self.assertIn('window_phase_unsupported',[f['reason'] for f in k.validation_failures])

    def test_initial_exclusion_and_justified_material_retraction(self):
        t,k,d=candidate(True);raw=public_world(10,'Bring 2 cold lights, not flames.')
        k=TreasureKnowledge();k.observe(Turn.from_raw(raw));k.prompt()
        self.assertEqual(k.correction_version,0)
        d=public_answer(k,raw['worldNews']['folkLegends'])['treasure'];d.pop('location');d.pop('window')
        k.ingest_llm(json.dumps({'treasure':d}));self.assertTrue(k.materials)
        k.prompt();k.ingest_llm(json.dumps({'treasure':{'mode':'treasure','materials':None,
            'retractions':[{'field':'materials','reason':'Re-evaluate the offering.',
                'evidence':evidence(k,raw['worldNews']['folkLegends'])}]}}))
        self.assertFalse(k.materials)
        self.assertNotIn('material_shape',[f['reason'] for f in k.validation_failures])

    def test_empty_description_is_inferred_not_rejected(self):
        t,k,d=candidate(True);k.ingest_llm(json.dumps({'treasure':d}))
        self.assertEqual(k.materials,{'BlueLamp':2})
        self.assertEqual(k.material_claims['BlueLamp']['binding'],'inferred')
        self.assertTrue(k.available(t));self.assertTrue(k.complete)

    def test_latency_keeps_valid_old_snapshot_facts(self):
        t,k,d=candidate(True)
        k.observe(replace(t,round_no=t.round_no+1,world_news=replace(t.world_news,folk_legends='Additional report: the road is quiet.')))
        k.ingest_llm(json.dumps({'treasure':d}))
        self.assertEqual(k.materials,{'BlueLamp':2});self.assertNotEqual(k.reason,'stale_response')
        self.assertTrue(k.needs_analysis())

    def test_new_catalog_request_does_not_revalidate_old_materials(self):
        t,k,d=candidate(True);k.ingest_llm(json.dumps({'treasure':d}));self.assertTrue(k.available(t))
        t=replace(t,weapon_shop=tuple(replace(i,description='A warm flame.') if i.name=='BlueLamp' else i for i in t.weapon_shop))
        k.observe(t);k.prompt()
        self.assertFalse(k.available(t))

    def test_catalog_changed_during_latency_requires_new_binding(self):
        t,k,d=candidate(True)
        t=replace(t,weapon_shop=tuple(replace(i,description='A warm flame.') if i.name=='BlueLamp' else i for i in t.weapon_shop))
        k.observe(t);k.ingest_llm(json.dumps({'treasure':d}))
        self.assertFalse(k.available(t))
        self.assertEqual(k.last_validation_failure['reason'],'catalog_changed_during_request')

    def test_unknown_preserves_supported_constraints(self):
        t,k,d=candidate();k.ingest_llm(json.dumps({'treasure':d}));k.prompt()
        k.ingest_llm(json.dumps({'treasure':{'mode':'unknown'}}))
        self.assertEqual(k.materials,{'BlueLamp':2});self.assertEqual(k.position.x,10)

    def test_coordinate_quote_does_not_authorize_other_coordinate(self):
        t,k,d=candidate();d['location']['x']=11;k.ingest_llm(json.dumps({'treasure':d}))
        self.assertIsNone(k.position)

    def test_unrelated_effect_is_not_description_verified(self):
        t,k,d=candidate();d['materials'][0]['effect']='poisonous smoke'
        k.ingest_llm(json.dumps({'treasure':d}));self.assertFalse(k.materials)

    def test_expired_candidate_not_purchase_worthy(self):
        t,k,d=candidate();k.ingest_llm(json.dumps({'treasure':d}))
        self.assertFalse(k.available(replace(t,round_no=521)))

    def test_bad_material_skips_dependent_count_failures(self):
        t,k,d=candidate(True);d['materials'][0]['item']='MissingItem'
        k.ingest_llm(json.dumps({'treasure':d}))
        self.assertEqual(k.last_validation_failure['reason'],'out_of_catalog')
        event=k.events[-1];self.assertEqual(event['dependent_checks_skipped'],['kind_count','total_quantity'])
        self.assertEqual(len(event['failures']),1)

    def test_provenance_and_quantity_failure_reasons(self):
        for change,reason in [('citation','invalid_source_quote'),('quantity','quantity_unsupported')]:
            t,k,d=candidate(True)
            if change=='citation':d['materials'][0]['evidence']=[]
            else:d['materials'][0]['quantity']=7
            k.ingest_llm(json.dumps({'treasure':d}))
            self.assertEqual(k.last_validation_failure['reason'],reason)

    def test_description_mismatch_and_unrelated_source_are_not_verified(self):
        t,k,d=candidate();d['materials'][0]['shop_quote']='hot sparks'
        k.ingest_llm(json.dumps({'treasure':d}));self.assertFalse(k.materials)
        t,k,d=candidate();d['materials'][0]['evidence']=evidence(k,'Open at (10,12), day 3 night.')
        k.ingest_llm(json.dumps({'treasure':d}));self.assertFalse(k.materials)

    def test_effect_translation_is_explicit_inference(self):
        t,k,d=candidate(True);m=d['materials'][0];m['effect']='蓝色光芒'
        m['effect_relation']={'claim':m['effect'],'quote':m['effect_quote'],'reason':'A proposed translation; not independent verification.'}
        k.ingest_llm(json.dumps({'treasure':d}));self.assertEqual(k.material_claims['BlueLamp']['binding'],'inferred')
        m['effect']='warm smoke';k.prompt();k.ingest_llm(json.dumps({'treasure':d}));self.assertFalse(k.materials)

    def test_exact_bounds_and_approximate_location(self):
        for text,x,reason in [('Open near (10,12) day 3 night.',10,'approximate_location'),
                              ('Open at (99,12) day 3 night.',99,'location_out_of_bounds')]:
            t,k,d=candidate();k.observe(replace(t,world_news=replace(t.world_news,folk_legends=text)));k.prompt()
            d['location']={'x':x,'y':12,'derivation':{'kind':'coordinate_literal'},'evidence':evidence(k,text)}
            k.ingest_llm(json.dumps({'treasure':d}));self.assertIsNone(k.position)
            self.assertIn(reason,[f['reason'] for f in k.validation_failures])

    def test_source_day_relative_window_and_bad_date(self):
        t,k,d=candidate(True);new=replace(t,round_no=392,world_news=replace(t.world_news,folk_legends='Open tomorrow during daytime.'))
        k.observe(new);k.prompt();d['window']={'day':5,'end_day':5,'phase':'day','evidence':evidence(k,'Open tomorrow during daytime.')}
        k.ingest_llm(json.dumps({'treasure':d}),{1,4});self.assertEqual(k.opening_day,5)
        self.assertFalse(k.available(replace(new,round_no=591))) # Day-five window has ended.
        d['window']['day']=d['window']['end_day']=1;k.prompt();k.ingest_llm(json.dumps({'treasure':d}),{1,4})
        self.assertIn('window_date_mismatch',[f['reason'] for f in k.validation_failures])

    def test_source_day_argument_is_checked(self):
        t,k,d=candidate();k.ingest_llm(json.dumps({'treasure':d}),{4})
        self.assertIn('window_source_day_invalid',[f['reason'] for f in k.validation_failures])

    def test_unprocessed_correction_blocks_old_candidate_even_after_unknown(self):
        t,k,d=candidate();k.ingest_llm(json.dumps({'treasure':d}))
        t=replace(t,world_news=replace(t.world_news,folk_legends='Correction: the former location is wrong.'))
        k.observe(t);self.assertFalse(k.available(t));k.prompt()
        k.ingest_llm(json.dumps({'treasure':{'mode':'unknown'}}));self.assertFalse(k.available(t))
        self.assertTrue(k.materials)

    def test_news_only_cannot_clear_treasure(self):
        t,k,d=candidate();k.ingest_llm(json.dumps({'treasure':d}))
        k.prompt('Ore price changes tomorrow.',1,purpose='market_only')
        k.ingest_llm(json.dumps({'market':[],'treasure':{'mode':'none','materials':[]}}))
        self.assertEqual(k.materials,{'BlueLamp':2});self.assertEqual(k.mode,'treasure')

    def test_no_description_inference_has_purchase_budget(self):
        t,k,d=candidate(True);k.ingest_llm(json.dumps({'treasure':d}))
        raw=public_world(10,'');raw['weaponShopList'][-1]['price']=100
        turn=Turn.from_raw(raw);plan=k.plan(turn,turn.team_our.unit(2),DEFAULT_CONFIG,1000)
        self.assertFalse(plan.action);self.assertEqual(k.reason,'inferred_purchase_budget')

    def test_vendor_only_is_unverified_not_purchase_route(self):
        t,k,d=candidate();t=replace(t,vendor_shop=t.weapon_shop,weapon_shop=())
        k.observe(t);k.prompt();k.ingest_llm(json.dumps({'treasure':d}))
        self.assertFalse(k.materials)
        self.assertTrue(k.validation_failures[0]['vendor_only_unverified'])

    def test_quantity_does_not_borrow_other_object_count(self):
        from solution.treasure_claims import quantity_supported
        self.assertFalse(quantity_supported(2,['Provide 2 lamps and 1 seal.'],('seal',)))
        self.assertTrue(quantity_supported(1,['Each of the three materials requires one piece.'],('lamp',)))
        self.assertFalse(quantity_supported(3,['Each of the three materials requires one piece.'],('lamp',)))

    def test_structurally_malformed_update_can_recover(self):
        t,k,d=candidate(True);k.ingest_llm(json.dumps({'treasure':{'mode':'treasure','materials':True}}))
        k.prompt();k.ingest_llm(json.dumps({'treasure':d}));self.assertEqual(k.materials,{'BlueLamp':2})

    def test_timeout_requires_response_identity(self):
        t,k,d=candidate(True);k.response_id_required=True
        k.ingest_llm(json.dumps({'treasure':d}));self.assertFalse(k.materials)
        self.assertEqual(k.last_validation_failure['reason'],'request_id_missing_after_timeout')
        k.ingest_llm(json.dumps({'request_id':k.request_id,'treasure':d}));self.assertTrue(k.materials)

    def test_inferred_attempts_are_bounded(self):
        t,k,d=candidate(True);k.ingest_llm(json.dumps({'treasure':d}));k.inferred_attempts=2
        self.assertFalse(k.inference_allowed())

    def test_checked_coordinate_offset(self):
        t,k,d=candidate();clue='Use anchor (8,13), with x+2 y-1. Open day 3 night.'
        k.observe(replace(t,world_news=replace(t.world_news,folk_legends=clue)));k.prompt()
        d['location']={'x':10,'y':12,'evidence':evidence(k,clue),'derivation':{'kind':'offset','anchor':[8,13],'delta':[2,-1],'offset_quote':'x+2 y-1'}}
        k.ingest_llm(json.dumps({'treasure':d}));self.assertEqual(k.position.x,10)

    def test_explicit_no_treasure_requires_and_records_evidence(self):
        t,k,d=candidate();k.ingest_llm(json.dumps({'treasure':d}));k.prompt()
        k.ingest_llm(json.dumps({'treasure':{'mode':'none'}}));self.assertTrue(k.materials)
        clue='Correction: there is no treasure here.'
        k.observe(replace(t,world_news=replace(t.world_news,folk_legends=clue)));k.prompt()
        k.ingest_llm(json.dumps({'treasure':{'mode':'none','reason':'Explicit withdrawal.','mode_evidence':evidence(k,clue)}}))
        self.assertFalse(k.materials);self.assertEqual(k.mode,'none')


def public_world(round_no=10,clue='Need 2 cold lights. Open at (10,12), day 1 daytime.'):
    raw=world(round_no);raw['teamOur']['goldNum']=1000
    for r in raw['teamOur']['roles']:
        if r['roleType'] in ('rocket','station'):r['level']=3
    unit(raw,2)['pos']={'x':11,'y':12}
    unit(raw,7)['pos']={'x':12,'y':12}
    raw['worldNews']['folkLegends']=clue
    raw['weaponShopList'].append({'name':'BlueLamp','price':15})
    raw['mapInfo']['zones']=[{'neutralType':'weaponShop','pos':{'x':10,'y':13}}]
    return raw


def public_answer(k,clue):
    e=evidence(k,clue)
    return {'request_id':k.request_id,'treasure':{'mode':'treasure',
        'materials':[{'item':'BlueLamp','quantity':2,'object':'cold lights','object_quote':'cold lights',
            'effect':'cold light','effect_quote':'cold light','derivation':'Catalog-name mapping is an inference.',
            'evidence':e,'quantity_evidence':e}],
        'kind_count':1,'total_quantity':2,'count_evidence':e,'materials_complete':True,
        'location':{'x':10,'y':12,'derivation':{'kind':'coordinate_literal'},'evidence':e},
        'window':{'day':1,'end_day':1,'phase':'day','evidence':e},'unknown':[],'conflicts':[]}}


class PublicEntryTests(unittest.TestCase):
    def test_response_counts_and_failure_survive_audit_deduplication(self):
        from solution.engine import AgentEngine
        from solution.telemetry import Telemetry
        from tools.diagnostics.operation_report import summarize_operations
        from unittest.mock import patch
        events=[]
        def capture(_self,event,**kwargs):events.append(event);return True
        with patch.object(Telemetry,'emit',capture):
            engine=AgentEngine();raw=public_world();engine.decide(raw)
            for n in range(2):
                raw['roundNo']+=1;raw['llmResp']='{ broken';engine.decide(raw)
            raw['roundNo']+=1;raw['llmResp']='';engine.decide(raw)
        report=summarize_operations(events)
        self.assertEqual(report['treasure_responses'],2)
        self.assertEqual(report['treasure_requests'],2)
        self.assertEqual(report['treasure_validation_reasons']['invalid_json_schema'],2)
        self.assertEqual(report['last_treasure_validation_failure']['reason'],'invalid_json_schema')
        self.assertEqual(engine.planner.treasure.reason,'await_evidence')

    def test_new_clue_each_turn_preserves_progress_and_later_opens(self):
        from solution.engine import AgentEngine
        clues=['The offering is cold lights.','The required effect is cold light.',
               'Provide 2 cold lights; use one kind and 2 pieces in total.',
               'Open at (10,12), day 2 daytime.']
        engine=AgentEngine();raw=public_world(10,clues[0]);engine.decide(raw);k=engine.planner.treasure
        for index in (1,2):
            reply={'request_id':k.request_id,'treasure':{'mode':'treasure','materials_complete':False,'unknown':['quantities']}}
            raw['roundNo']+=1;raw['worldNews']['folkLegends']=clues[index];raw['llmResp']=json.dumps(reply)
            self.assertIn('prompt',engine.decide(raw))
        answer=public_answer(k,clues[0]);m=answer['treasure']['materials'][0]
        m['evidence']=evidence(k,clues[0])+evidence(k,clues[1]);m['quantity_evidence']=evidence(k,clues[2])
        answer['treasure']['count_evidence']=evidence(k,clues[2]);answer['treasure'].pop('location');answer['treasure'].pop('window')
        raw['roundNo']+=1;raw['worldNews']['folkLegends']=clues[3];raw['llmResp']=json.dumps(answer)
        response=engine.decide(raw)
        self.assertEqual(response['roleCommandMap']['2']['name'],'BlueLamp')
        self.assertEqual(k.materials,{'BlueLamp':2});self.assertNotEqual(k.reason,'stale_response')
        self.assertGreater(k.version,k.analyzed_version)
        unit(raw,2)['backpack']=['BlueLamp']*2;raw['llmResp']='';raw['roundNo']=131
        self.assertIn('prompt',engine.decide(raw))
        e=evidence(k,clues[3]);raw['roundNo']=132
        raw['llmResp']=json.dumps({'request_id':k.request_id,'treasure':{'mode':'treasure','materials_complete':True,'unknown':[],
            'location':{'x':10,'y':12,'derivation':{'kind':'coordinate_literal'},'evidence':e},
            'window':{'day':2,'end_day':2,'phase':'day','evidence':e}}})
        response=engine.decide(raw);self.assertEqual(response['roleCommandMap']['2']['action'],'summonTreasure')
        raw['roundNo']+=1;raw['llmResp']='';raw['lastSummonTreasureResult']=1;unit(raw,2)['backpack']=[]
        engine.decide(raw);self.assertEqual(k.material_claims['BlueLamp']['platform'],'opening_success')

    def test_engine_empty_catalog_description_buys_and_opens_then_uses_feedback(self):
        from solution.engine import AgentEngine
        engine=AgentEngine();raw=public_world();clue=raw['worldNews']['folkLegends']
        self.assertIn('prompt',engine.decide(raw));k=engine.planner.treasure
        raw['roundNo']+=1;raw['llmResp']=json.dumps(public_answer(k,clue))
        response=engine.decide(raw)
        self.assertEqual(response['roleCommandMap']['2']['action'],'buy')
        self.assertEqual(response['roleCommandMap']['2']['num'],2)
        unit(raw,2)['backpack']=['BlueLamp']*2;raw['roundNo']+=1;raw['llmResp']=''
        raw['teamOur']['goldNum']-=30
        response=engine.decide(raw);self.assertEqual(response['roleCommandMap']['2']['action'],'summonTreasure')
        raw['roundNo']+=1;raw['lastSummonTreasureResult']=3;unit(raw,2)['backpack']=[]
        response=engine.decide(raw)
        self.assertNotIn(response['roleCommandMap'].get('2',{}).get('action'),('buy','summonTreasure'))
        self.assertEqual(k.last_validation_failure['reason'],'wrong_materials')
        self.assertEqual(k.inferred_attempts,1);self.assertEqual(k.inferred_spent,30)

    def test_engine_malformed_response_retries_and_partial_response_keeps_facts(self):
        from solution.engine import AgentEngine
        engine=AgentEngine();raw=public_world();clue=raw['worldNews']['folkLegends'];engine.decide(raw)
        raw['roundNo']+=1;raw['llmResp']='{ broken'
        response=engine.decide(raw);k=engine.planner.treasure
        self.assertIn('prompt',response);self.assertEqual(k.last_validation_failure['reason'],'invalid_json_schema')
        raw['roundNo']+=1;answer=public_answer(k,clue);answer['treasure'].pop('window');answer['treasure'].pop('location')
        answer['treasure']['materials_complete']=False;raw['llmResp']=json.dumps(answer)
        response=engine.decide(raw);self.assertEqual(response['roleCommandMap']['2']['action'],'buy')
        self.assertFalse(k.complete);self.assertTrue(k.materials);self.assertEqual(k.responses,2)

    def test_engine_invalid_source_cannot_buy_and_reason_survives_wait(self):
        from solution.engine import AgentEngine
        engine=AgentEngine();raw=public_world();engine.decide(raw);k=engine.planner.treasure
        answer=public_answer(k,raw['worldNews']['folkLegends']);answer['treasure']['materials'][0]['evidence']=[]
        raw['roundNo']+=1;raw['llmResp']=json.dumps(answer);response=engine.decide(raw)
        self.assertNotEqual(response['roleCommandMap'].get('2',{}).get('name'),'BlueLamp')
        raw['roundNo']+=1;raw['llmResp']='';engine.decide(raw)
        self.assertEqual(k.last_validation_failure['reason'],'invalid_source_quote')

    def test_standing_on_site_moves_adjacent_before_opening(self):
        from solution.engine import AgentEngine
        engine=AgentEngine();raw=public_world();engine.decide(raw);k=engine.planner.treasure
        raw['roundNo']+=1;raw['llmResp']=json.dumps(public_answer(k,raw['worldNews']['folkLegends']))
        unit(raw,2)['pos']={'x':10,'y':12};unit(raw,2)['backpack']=['BlueLamp']*2
        response=engine.decide(raw)
        self.assertEqual(response['roleCommandMap']['2']['action'],'move')


if __name__=='__main__':unittest.main()
