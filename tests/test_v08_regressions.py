"""Synthetic failures in answer validation, workspace recovery and funding."""
import json
import tempfile
import unittest
from pathlib import Path

from solution.economy import DefenseBudget, next_development_target
from solution.logistics import LogisticsManager
from solution.models import Turn
from solution.rules import DEFAULT_CONFIG
from solution.state import LlmBudget, WorldState
from solution.tasking import TaskManager, TaskPhase
from tests.helpers import synthetic_turn, role
from tests.test_task_procedures import run_procedure
from tests.test_v05_regressions import developed


class TaskEvidenceTests(unittest.TestCase):
    def test_zero_scalar_answer_retains_fast_submission(self):
        with tempfile.TemporaryDirectory() as root:
            result=run_procedure(dict(kind='python',base=root,code='print(0)',submit_result=True,
                required='integer',verify='assert answer == sum([])'))
            self.assertTrue(result['checked'])
            raw=synthetic_turn(round_no=13);raw['lastCmdResult']='[exitCode:0]\n'+json.dumps({'procedure_result':result})
            manager=TaskManager(phase=TaskPhase.WAITING_COMMAND,command_steps=2,pending_procedure=True)
            self.assertEqual(self.plan(manager,raw).action.task_answer,'0')

    def test_unexecuted_or_constant_assertion_is_not_verification(self):
        with tempfile.TemporaryDirectory() as root:
            for verifier in ('def check():\n    assert answer["total"] == 17', 'assert True'):
                result=run_procedure(dict(kind='python',base=root,code='print(\'{"total":999}\')',
                    submit_result=True,required={'total':'integer'},verify=verifier))
                self.assertFalse(result['ok'])

    def test_identical_failed_program_is_not_executed_again(self):
        manager=TaskManager(command_steps=1)
        program={'kind':'python','code':'open("missing.json").read()'}
        raw=synthetic_turn(round_no=11);raw['llmResp']=json.dumps({'procedure':program})
        self.assertTrue(self.plan(manager,raw).execute_command)
        raw.update(roundNo=12,llmResp='',lastCmdResult='[exitCode:0]\n'+json.dumps({'procedure_result':{'ok':False,'status':'FileNotFoundError'}}))
        self.plan(manager,raw)
        raw.update(roundNo=13,lastCmdResult='',llmResp=json.dumps({'procedure':program},indent=2))
        self.assertFalse(self.plan(manager,raw).execute_command)
        self.assertEqual(manager.reject_reason,'duplicate_failed_program')

    def test_workspace_relative_inspection_reads_requested_source(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'nested').mkdir()
            Path(root,'nested','target.py').write_text('value = 417\n')
            result=run_procedure(dict(kind='inspect',base=root,cwd='nested',paths=['target.py']))
            self.assertEqual(result['documents'][0]['path'],'nested/target.py')

    def test_timeout_partial_credit_is_reported_without_answer_content(self):
        from tools.diagnostics.decode_match_log import task_outcomes
        events=[{'event':'turn','r':r,'gold':0,'score':0,'diagnostics':{'taskCompleted':0,'taskFailed':0},'commands':[]} for r in range(1,5)]
        events[0]['commands']=[['synthetic-actor','acceptTask','',0,[]]]
        events[1]['commands']=[['synthetic-actor','submitAnswer','',0,[]]]
        events[3].update(gold=16,score=16,diagnostics={'taskCompleted':0,'taskFailed':1})
        result=task_outcomes(events)
        self.assertEqual(result[0]['outcome'],'partial_observed')
        self.assertEqual(result[0]['goldDelta'],16)
        self.assertNotIn('synthetic-actor',str(result))

    def test_acceptance_does_not_reuse_previous_tasks_llm_program(self):
        manager=TaskManager()
        raw=synthetic_turn(round_no=10);raw['phaseTask']=''
        raw['llmResp']=json.dumps({'python':'raise RuntimeError("old task")'})
        self.assertEqual(self.plan(manager,raw).action.action_type.value,'acceptTask')
        raw.update(roundNo=11,phaseTask='Read fresh.md')
        plan=self.plan(manager,raw)
        self.assertIn('fresh.md',plan.execute_command)
        self.assertEqual(manager.command_kind,'bootstrap')

    def plan(self, manager, raw):
        turn=Turn.from_raw(raw); state=WorldState(); state.ingest(turn)
        manager.last_generation=state.generation
        return manager.plan(turn,state,LlmBudget(),DEFAULT_CONFIG,turn.team_our.unit(2))

    def test_rejected_json_cannot_be_resubmitted_with_different_spacing(self):
        manager=TaskManager(command_steps=1)
        raw=synthetic_turn(round_no=11); raw['llmResp']=json.dumps({'answer':{'a':3,'b':4}})
        self.assertIsNotNone(self.plan(manager,raw).action)
        raw.update(roundNo=12,errors=[{'errorCode':2}],llmResp=json.dumps({'answer':'{ "b": 4, "a": 3 }'}))
        self.assertIsNone(self.plan(manager,raw).action)
        self.assertEqual(manager.diagnostic,'duplicate_answer_blocked')

    def test_computed_candidate_can_salvage_deadline_but_not_repeat_rejection(self):
        manager=TaskManager(command_steps=2,accepted_round=10,timeout_rounds=10)
        manager.context.candidate={'total':17}; manager.context.schema_pass=True
        raw=synthetic_turn(round_no=19)
        self.assertIsNotNone(self.plan(manager,raw).action)
        raw.update(roundNo=20,errors=[{'errorCode':2}])
        self.assertIsNone(self.plan(manager,raw).action)

    def test_failed_latest_execution_does_not_submit_old_candidate_at_deadline(self):
        manager=TaskManager(command_steps=2,accepted_round=10,timeout_rounds=10)
        manager.context.candidate={'total':17}; manager.context.schema_pass=True
        manager.context.failed_execution=True
        self.assertIsNone(self.plan(manager,synthetic_turn(round_no=19)).action)

    def test_checker_text_extracts_actual_fresh_proof(self):
        import uuid
        with tempfile.TemporaryDirectory() as root:
            proof=uuid.uuid4().hex
            result=run_procedure(dict(kind='repair',base=root,edits=[],
                check=['python3','-c','print("VALIDATION_RESULT='+proof+'")'],
                answer_format='text',answer_pattern=r'VALIDATION_RESULT=([a-f0-9]+)'))
            self.assertTrue(result['checked']); self.assertEqual(result['answer'],proof)

    def test_text_extraction_requires_one_unambiguous_match(self):
        with tempfile.TemporaryDirectory() as root:
            result=run_procedure(dict(kind='repair',base=root,edits=[],
                check=['python3','-c','print("proof=1 proof=2")'],
                answer_format='text',answer_pattern=r'proof=(\d+)'))
            self.assertFalse(result['ok'])

    def test_independent_verification_submits_random_dataset_answer(self):
        import random
        values=random.Random().sample(range(10000),13)
        with tempfile.TemporaryDirectory() as root:
            Path(root,'values.json').write_text(json.dumps(values))
            result=run_procedure(dict(kind='python',base=root,
                code='import json\nv=json.load(open("values.json"))\nprint(json.dumps({"count":len(v),"total":sum(v)}))',
                submit_result=True,required={'count':'integer','total':'integer'},
                verify='v=json.load(open("values.json"))\nassert answer["count"] == len(v)\nassert answer["total"] == sum(v)'))
            self.assertTrue(result['checked'])
            raw=synthetic_turn(round_no=13);raw['lastCmdResult']='[exitCode:0]\n'+json.dumps({'procedure_result':result})
            manager=TaskManager(phase=TaskPhase.WAITING_COMMAND,command_steps=2,pending_procedure=True)
            self.assertEqual(json.loads(self.plan(manager,raw).action.task_answer),{'count':13,'total':sum(values)})

    def test_boolean_is_not_an_integer_answer(self):
        from solution.task_answers import shape_error
        self.assertEqual(shape_error({'count':True},{'count':'integer'}),'field_type')

    def test_computed_json_alone_does_not_autosubmit(self):
        raw = synthetic_turn(round_no=12)
        raw['lastCmdResult'] = '[exitCode:0]\n' + json.dumps({'procedure_result':
            {'ok': True, 'computed': True, 'answer': {'total': 999}}})
        turn = Turn.from_raw(raw); state = WorldState(); state.ingest(turn)
        manager = TaskManager(last_generation=state.generation,
            phase=TaskPhase.WAITING_COMMAND, command_steps=2, pending_procedure=True)
        plan = manager.plan(turn, state, LlmBudget(), DEFAULT_CONFIG, turn.team_our.unit(2))
        self.assertIsNone(plan.action)
        self.assertTrue(plan.prompt)

    def test_truncated_document_is_explicit_and_can_be_read_to_end(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'task.md').write_text('x' * 10000 + '\nRequired: final_total')
            result = run_procedure(dict(kind='inspect', base=root, filename='task.md'))
            doc = result['documents'][0]
            self.assertIn('complete', doc)
            if not doc['complete']:
                tail = run_procedure(dict(kind='inspect', base=root,
                    paths=['task.md'], offsets={'task.md': doc['next_offset']}))
                self.assertIn('final_total', tail['documents'][0]['text'])
            else:
                self.assertIn('final_total', doc['text'])

    def test_verifier_rejects_wrong_but_valid_json(self):
        with tempfile.TemporaryDirectory() as root:
            result = run_procedure(dict(kind='python', base=root,
                code='print(\'{"total":999}\')', submit_result=True,
                required={'total': 'integer'}, verify='assert answer["total"] == 17'))
            self.assertFalse(result['ok'])
            self.assertIn('answer', result)
        self.assertFalse(result.get('checked',False))

    def test_schema_rejects_missing_field_before_verification(self):
        with tempfile.TemporaryDirectory() as root:
            result = run_procedure(dict(kind='python', base=root,
                code='print(\'{"count":1}\')', submit_result=True,
                required={'count': 'integer', 'total': 'integer'}, verify='assert answer["count"] == 1'))
            self.assertFalse(result['ok'])

    def test_missing_file_returns_workspace_evidence_without_retrying_solver(self):
        with tempfile.TemporaryDirectory() as root:
            work = Path(root, 'nested'); work.mkdir()
            (work / 'values.json').write_text('[3, 8]')
            result = run_procedure(dict(kind='python', base=root, cwd='nested',
                code='open("absent.json").read()'))
            self.assertIn('files', result)
            self.assertIn('nested/values.json', result['files'])
            self.assertFalse(result['ok'])


class DevelopmentTests(unittest.TestCase):
    def ready(self):
        raw = developed(); raw['roundNo'] = 280
        for unit in raw['teamOur']['roles']:
            if unit['roleType'] in ('rocket', 'railgun', 'station'): unit['level'] = 2
        raw['weaponShopList'] = [{'name':'WeaponUpgradeVoucher2','price':150},
            {'name':'WallUpgradeVoucher1','price':20}, {'name':'WallFixer','price':10}]
        raw['mapInfo']['zones'] = [{'neutralType':'weaponShop','pos':{'x':13,'y':5}}]
        raw['teamOur']['roles'][0]['pos'] = {'x':12,'y':5}
        return raw

    def test_saves_toward_third_level_rocket_after_basic_development(self):
        raw = self.ready(); raw['teamOur']['goldNum'] = 120
        raw['teamOur']['roles'].append(role(60, 'wall', 8, 10, health=700, level=2))
        turn = Turn.from_raw(raw)
        self.assertEqual(next_development_target(turn, DEFAULT_CONFIG).role_type, 'rocket')
        plan = LogisticsManager(weapon_buyer_id=1).plan(turn, turn.team_our.unit(1),
            DefenseBudget(0,25,95,12), DEFAULT_CONFIG)
        self.assertIsNone(plan.action)

    def test_engineer_repair_reserve_precedes_optional_tier_three(self):
        from tests.test_v014_operations import WallSupplyTests
        from solution.wall_supply import wall_stock_plan
        raw=WallSupplyTests().scene();raw['teamOur']['goldNum']=10
        for u in raw['teamOur']['roles']:
            if u['roleType']=='rocket':u['level']=2
        turn=Turn.from_raw(raw)
        plan=wall_stock_plan(turn,turn.team_our.unit(1),DefenseBudget(0,25,0,-3),DEFAULT_CONFIG)
        self.assertEqual((plan.action.name,plan.action.quantity),('WallFixer',1))

    def test_current_price_funds_third_level_purchase(self):
        raw=self.ready();raw['teamOur']['goldNum']=175
        raw['teamOur']['roles'][1]['backpack']=['WallFixer']*5
        turn=Turn.from_raw(raw)
        plan=LogisticsManager(weapon_buyer_id=1).plan(turn,turn.team_our.unit(1),DefenseBudget(0,25,150,12),DEFAULT_CONFIG)
        self.assertEqual(plan.action.name,'WeaponUpgradeVoucher2')

    def test_remaining_weapons_precede_key_walls(self):
        raw=self.ready();raw['roundNo']=410
        rocket=next(u for u in raw['teamOur']['roles'] if u['roleType']=='rocket');rocket['level']=3
        raw['teamOur']['roles'].append(role(60,'wall',8,10,health=1500,level=2))
        raw['weaponShopList'].append({'name':'WallUpgradeVoucher2','price':30})
        turn=Turn.from_raw(raw)
        self.assertEqual(next_development_target(turn,DEFAULT_CONFIG).role_type,'rocket')

    def test_other_workers_stock_does_not_trigger_one_ore_sale(self):
        from solution.economy import EconomyManager
        raw=self.ready();raw['teamOur']['goldNum']=100
        raw['teamOur']['roles'][0].update(pos={'x':2,'y':3},backpack=['copper'])
        raw['teamOur']['roles'][1]['backpack']=['copper']*10
        raw['mapInfo']['zones']=[{'neutralType':'copper','pos':{'x':3,'y':3}},
                                {'neutralType':'vendor','pos':{'x':14,'y':3}}]
        raw['vendorShopList']=[{'name':'copper','price':5}]
        turn=Turn.from_raw(raw);state=WorldState();state.ingest(turn)
        manager=EconomyManager()
        plan=manager.plan(turn,turn.team_our.unit(1),state,DEFAULT_CONFIG,DefenseBudget(0,25,75,12))
        self.assertEqual(plan.action.action_type.value,'collect')

    def test_price_forecast_does_not_delay_funding_ready_upgrade(self):
        from solution.economy import EconomyManager
        raw=self.ready();raw['teamOur']['goldNum']=125
        raw['teamOur']['roles'][0].update(pos={'x':2,'y':3},backpack=['copper']*5)
        raw['mapInfo']['zones']=[{'neutralType':'copper','pos':{'x':3,'y':3}},
                                {'neutralType':'vendor','pos':{'x':14,'y':3}}]
        raw['vendorShopList']=[{'name':'copper','price':5}]
        turn=Turn.from_raw(raw);state=WorldState();state.ingest(turn)
        state.market.observe('days 4-5 copper price=12',3)
        manager=EconomyManager()
        manager.plan(turn,turn.team_our.unit(1),state,DEFAULT_CONFIG,DefenseBudget(0,25,100,12))
        self.assertEqual(manager.activity[1],'sell_batch')
