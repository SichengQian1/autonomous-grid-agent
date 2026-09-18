"""Synthetic task-pipeline regressions from the v0.9 failure classes."""
import json
import tempfile
import unittest
from pathlib import Path
from tests.helpers import synthetic_turn
from tests.test_task_procedures import run_procedure
from solution.models import Turn
from solution.state import WorldState,LlmBudget
from solution.rules import DEFAULT_CONFIG
from solution.tasking import TaskManager,TaskPhase


def active_manager(category=1, response=None, result=None, docs=''):
    raw=synthetic_turn(round_no=13)
    if response is not None:raw['llmResp']=json.dumps(response)
    if result is not None:raw['lastCmdResult']='[exitCode:0]\n'+json.dumps({'procedure_result':result})
    turn=Turn.from_raw(raw);state=WorldState();state.ingest(turn)
    m=TaskManager(phase=TaskPhase.WAITING_COMMAND if result else TaskPhase.WAITING_SYNTHESIS,
        pending_procedure=bool(result),command_steps=1,accepted_round=10,timeout_rounds=15,
        last_generation=state.generation,llm_requested_round=12)
    m.audit.start(turn,turn.team_our.player_tasks[0].task_position);m.audit.active['task_type']=category
    if docs:m.context.documents={'requirements.md':docs}
    return m,turn,state

class KnownPipelineFailures(unittest.TestCase):
    def test_current_document_contract_completes_api_plan(self):
        m,t,s=active_manager(response={'procedure':{'kind':'api','url':'http://127.0.0.1:1/data','query':{},'fields':{'n':{'op':'count'}}}},
            docs='Required answer JSON: {"n": 4}')
        p=m.plan(t,s,LlmBudget(),DEFAULT_CONFIG,t.team_our.unit(2))
        self.assertTrue(p.execute_command)
        self.assertEqual(m.context.required,{'n':'integer'})

    def test_missing_contract_has_an_explicit_rejection_event(self):
        m,t,s=active_manager(response={'procedure':{'kind':'api','url':'http://127.0.0.1:1/data','fields':{}}})
        p=m.plan(t,s,LlmBudget(),DEFAULT_CONFIG,t.team_our.unit(2))
        self.assertFalse(p.execute_command)
        self.assertEqual(m.reject_reason,'answer_contract_missing')
        self.assertTrue(any(e['kind']=='plan_rejected' for e in m.audit.events))

    def test_empty_generic_statistics_cannot_fast_submit(self):
        result={'task_id':'T001','ok':True,'checked':True,'computed':True,'schema_pass':True,
                'answer':{'total_count':0},'kind':'python'}
        m,t,s=active_manager(result=result,docs='Answer JSON: {"total_count": 3}')
        m.context.last_plan={'kind':'python'}
        p=m.plan(t,s,LlmBudget(),DEFAULT_CONFIG,t.team_our.unit(2))
        self.assertIsNone(p.action)
        self.assertFalse(m.context.candidate_checked)

    def test_repair_scalar_uses_current_document_submission_object(self):
        result={'task_id':'T001','kind':'repair','ok':True,'checked':True,'answer':'synthetic-fresh-proof'}
        m,t,s=active_manager(2,result=result,docs='Submit JSON: {"certificate":"the checker value"}')
        p=m.plan(t,s,LlmBudget(),DEFAULT_CONFIG,t.team_our.unit(2))
        self.assertEqual(json.loads(p.action.task_answer),{'certificate':'synthetic-fresh-proof'})

    def test_existing_crlf_shebang_checker_can_run_without_modification(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root,'verify.sh');content=b'#!/bin/sh\r\nprintf \'{"proof":"synthetic"}\\n\'\n'
            p.write_bytes(content);p.chmod(0o700)
            r=run_procedure(dict(kind='repair',base=root,edits=[],check=['./verify.sh']))
            self.assertTrue(r.get('checked'),r)
            self.assertEqual(p.read_bytes(),content)

    def test_patch_retry_after_failed_check_does_not_repeat_old_replacement(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'settings').write_text('mode=old\n')
            Path(root,'verify.py').write_text('raise SystemExit(1)')
            options=dict(kind='repair',base=root,task_id='T001',edits=[{'path':'settings','old':'mode=old','new':'mode=new'}],check=['python3','verify.py'])
            first=run_procedure(options);second=run_procedure(options)
            self.assertEqual(first['status'],'check_failed')
            self.assertEqual(second['status'],'check_failed')
            self.assertTrue(any(e.get('already_applied') for e in second['patch_evidence']))

    def test_document_events_are_not_reported_as_failures(self):
        from tools.diagnostics.task_report import summarize_tasks
        r=summarize_tasks([dict(event='task',kind='execution',task_id='T001',task_type=1,status='unknown',documents=[{'complete':True}])])
        self.assertEqual(r['failures'],{})

class ContractAndRecoveryTests(unittest.TestCase):
    def test_request_example_cannot_become_answer_contract(self):
        from solution.task_contracts import current_contract
        required,_=current_contract({'a':'Request JSON: {"secret":"synthetic"}\nSubmit JSON: {"result":4}'})
        self.assertEqual(required,{'result':'integer'})

    def test_conflicting_document_types_require_clarification(self):
        from solution.task_contracts import current_contract
        required,source=current_contract({'a':'Answer JSON: {"n":4}\nAnswer JSON: {"n":[]}'})
        self.assertFalse(required);self.assertEqual(source['status'],'conflicting_document_contracts')

    def test_binding_progress_is_task_local_and_explicitly_resettable(self):
        from solution.task_context import TaskContext
        ctx=TaskContext()
        plan={'kind':'api','url':'http://127.0.0.1:1/data','headers':{'X-Token':'synthetic-current'},'query':{'location':'Synthetic'}}
        ctx.keep_api_progress(plan,{'status':'records_shape','evidence':{'requests':[{'status':200}]}})
        fixed=ctx.restore_api_progress(dict(plan,headers={'X-Token':'wrong'},records_path='data.rows'))
        self.assertEqual(fixed['headers'],plan['headers'])
        reset=ctx.restore_api_progress(dict(plan,headers={'X-Token':'new'},reset_request=True))
        self.assertEqual(reset['headers']['X-Token'],'new')
        self.assertFalse(TaskContext().api_bindings)
        ctx.keep_api_progress(plan,{'status':'authentication_failed'})
        self.assertFalse(ctx.api_bindings)

    def test_contract_only_reply_resumes_retained_procedure(self):
        m,t,s=active_manager(response={'required':{'n':'integer'}})
        m.context.blocked_plan={'kind':'api','url':'http://127.0.0.1:1/data','query':{},'fields':{'n':{'op':'count'}}}
        p=m.plan(t,s,LlmBudget(),DEFAULT_CONFIG,t.team_our.unit(2))
        self.assertTrue(p.execute_command);self.assertFalse(m.context.blocked_plan)

    def test_generic_candidate_is_retained_at_deadline(self):
        result={'task_id':'T001','ok':True,'checked':True,'computed':True,'schema_pass':True,'answer':{'n':0},'kind':'python'}
        m,t,s=active_manager(result=result,docs='Answer JSON: {"n":1}')
        m.accepted_round=-1;m.context.last_plan={'kind':'python'}
        p=m.plan(t,s,LlmBudget(),DEFAULT_CONFIG,t.team_our.unit(2))
        self.assertEqual(json.loads(p.action.task_answer),{'n':0})
        self.assertEqual(m.diagnostic,'deadline_candidate')
        self.assertFalse(m.context.candidate_checked)

    def test_known_wrong_business_assertion_remains_blocked(self):
        result={'task_id':'T001','ok':False,'checked':False,'computed':True,'schema_pass':True,'answer':{'n':0},
                'kind':'python','status':'verification_failed','verification_kind':'assertion'}
        m,t,s=active_manager(result=result,docs='Answer JSON: {"n":1}')
        m.accepted_round=-1;m.context.last_plan={'kind':'python'}
        p=m.plan(t,s,LlmBudget(),DEFAULT_CONFIG,t.team_our.unit(2))
        self.assertIsNone(p.action)

    def test_changed_file_invalidates_patch_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root,'settings');p.write_text('mode=old\n')
            options=dict(kind='repair',base=root,task_id='T001',edits=[{'path':'settings','old':'mode=old','new':'mode=new'}],check=['python3','-c','print("{}")'])
            self.assertTrue(run_procedure(options)['checked'])
            p.write_text('mode=other\n')
            self.assertEqual(run_procedure(options)['reason'],'non_unique_patch')

    def test_patch_receipt_does_not_cross_tasks(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'settings').write_text('mode=old\n')
            options=dict(kind='repair',base=root,task_id='T001',edits=[{'path':'settings','old':'mode=old','new':'mode=new'}],check=['python3','-c','print("{}")'])
            run_procedure(options)
            self.assertEqual(run_procedure(dict(options,task_id='T002'))['reason'],'non_unique_patch')

    def test_text_extraction_requires_current_label_not_arbitrary_output(self):
        from solution.task_contracts import extract_proof
        self.assertIsNone(extract_proof('unlabeled-secret',{'certificate':'string'}))
        self.assertIsNone(extract_proof('certificate=alpha\ncertificate=beta',{'certificate':'string'}))
        self.assertEqual(extract_proof('certificate=alpha',{'certificate':'string'}),{'certificate':'alpha'})

class LivePathReuseTests(unittest.TestCase):
    def test_plain_script_success_is_learned_and_next_two_proofs_skip_llm(self):
        from solution.task_series import TaskSeries
        import uuid
        series=TaskSeries()
        for index in range(1,4):
            proof=uuid.uuid4().hex
            with tempfile.TemporaryDirectory() as root:
                result=run_procedure(dict(kind='script',base=root,task_id=f'T00{index}',script=f"printf 'certificate={proof}\\n'"))
            m,t,s=active_manager(2,result=result,docs='Submit JSON: {"certificate":"checker output"}')
            m.audit.active['task_id']=f'T00{index}';m.series=series;series.begin(f'T00{index}',2)
            m.context.last_plan={'command':'sh ./current-check'}
            p=m.plan(t,s,LlmBudget(),DEFAULT_CONFIG,t.team_our.unit(2))
            self.assertEqual(json.loads(p.action.task_answer),{'certificate':proof})
            self.assertFalse(p.prompt)
            series.settle(f'T00{index}','full')
            self.assertNotIn(proof,series.prompt(2))
        self.assertEqual(series.hits,2)
        self.assertIsNone(series.workflow_for(2,{'different':'string'}))
        self.assertFalse(TaskSeries().methods)

    def test_partial_script_result_not_promoted_to_full_method(self):
        from solution.task_series import TaskSeries
        series=TaskSeries();series.begin('T001',2)
        series.record_script_proof('T001',{'proof':'string'},{'command':'python3 current.py'},{'proof':'synthetic'})
        series.settle('T001','partial')
        self.assertEqual(series.workflow_for(2,{'proof':'string'})['level'],'executed')
        self.assertNotIn('synthetic',series.prompt(2))

    def test_api_methods_do_not_require_model_authored_compatibility(self):
        from solution.task_series import TaskSeries
        series=TaskSeries()
        first={'kind':'api','url':'http://127.0.0.1:1/old','query':{'city':'Old'},'filter':{'path':'city','value':'Old'},
               'records_path':'rows','required':{'n':'integer'},'fields':{'n':{'op':'count'}}}
        series.prepare(first,'T001',1);series.observe('T001',{'ok':True,'checked':True});series.settle('T001','full')
        for index in (2,3):
            current=dict(first,url='http://127.0.0.1:2/new',query={'city':str(index)},filter={'path':'city','value':str(index)})
            out=series.prepare(current,f'T00{index}',1)
            self.assertEqual(out['filter']['value'],str(index));self.assertTrue(series.last_reuse['used'])
        self.assertEqual(series.hits,2)
        changed=dict(first,records_path='different')
        series.prepare(changed,'T004',1);self.assertFalse(series.last_reuse['used'])

    def test_validator_and_launch_evidence_are_sanitized_but_distinguishable(self):
        from solution.task_audit import TaskAudit
        from solution.task_series import TaskSeries
        audit=TaskAudit();turn=Turn.from_raw(synthetic_turn());audit.start(turn,turn.team_our.player_tasks[0].task_position)
        audit.execution(turn,{'verify':"assert answer['total_count'] == 7",'headers':{'Authorization':'synthetic-secret'}},
                        {'status':'FileNotFoundError','execution_evidence':{'errno':2,'failed_path':'/private/account/tool','interpreter':'/private/account/python','shebang_crlf':True}},TaskSeries())
        event=audit.events[-1];text=json.dumps(event)
        self.assertIn('verifier_program',event);self.assertEqual(event['execution']['errno'],2)
        self.assertNotIn('/private/account',text);self.assertNotIn('synthetic-secret',text)

class NestedApiRecoveryTests(unittest.TestCase):
    def test_nested_records_recovery_still_checks_filter_total_and_all_pages(self):
        from http.server import BaseHTTPRequestHandler,HTTPServer
        from urllib.parse import parse_qs,urlsplit
        import threading
        visits=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                page=int(parse_qs(urlsplit(self.path).query)['page'][0]);visits.append(page)
                if self.headers.get('X-Key')!='synthetic':self.send_response(401);self.end_headers();return
                rows=[{'id':page,'place':'Town'}] if page<=2 else []
                body=json.dumps({'data':{'rows':rows,'total':2}}).encode()
                self.send_response(200);self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        with HTTPServer(('127.0.0.1',0),Handler) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                plan=dict(kind='api',url=f'http://127.0.0.1:{server.server_port}/data',headers={'X-Key':'synthetic'},
                    query={'location':'Town'},records_path='data',filter={'path':'place','value':'Town'},
                    pagination={'parameter':'page','total_path':'data.total','id_path':'id'},
                    required={'n':'integer'},fields={'n':{'op':'count'}})
                result=run_procedure(plan)
            finally:server.shutdown();thread.join()
        self.assertTrue(result['checked'],result);self.assertEqual(result['answer'],{'n':2})
        self.assertEqual(visits,[1,2]);self.assertEqual(result['evidence']['resolved_records_path'],'data.rows')

    def test_checker_return_scalar_packaged_before_schema_check(self):
        with tempfile.TemporaryDirectory() as root:
            result=run_procedure(dict(kind='repair',base=root,edits=[],check=['python3','-c','import json; print(json.dumps({"proof":"synthetic-proof"}))'],
                answer_path='proof',required={'certificate':'string'}))
        self.assertTrue(result['checked'],result);self.assertEqual(result['answer'],{'certificate':'synthetic-proof'})

class ContractSyntaxTests(unittest.TestCase):
    def test_json_schema_nested_properties_are_not_conflicting_examples(self):
        from solution.task_contracts import current_contract
        value={'type':'object','properties':{'quantity':{'type':'integer'}},'required':['quantity']}
        required,_=current_contract({'r':'Answer JSON schema: '+json.dumps(value)})
        self.assertEqual(required,{'quantity':'integer'})

    def test_quoted_field_type_rows(self):
        from solution.task_contracts import current_contract
        required,_=current_contract({'r':'提交格式：\n"quantity": integer\n"labels": array\n'})
        self.assertEqual(required,{'quantity':'integer','labels':'array'})

class EvidenceBudgetTests(unittest.TestCase):
    def test_large_program_details_do_not_drop_failure_event(self):
        from solution.task_audit import TaskAudit
        audit=TaskAudit();turn=Turn.from_raw(synthetic_turn());audit.start(turn,turn.team_our.player_tasks[0].task_position)
        audit.emit('execution',13,{'status':'check_failed','execution':{'errno':2},'plan_structure':{'detail':'x'*9000}},True)
        event=audit.events[-1]
        self.assertEqual(event['kind'],'execution');self.assertEqual(event['execution']['errno'],2)
        self.assertIn('plan_structure',event['omitted_fields'])

class ContractBoundaryTests(unittest.TestCase):
    def test_pretty_json_schema_is_not_misread_as_field_table(self):
        from solution.task_contracts import current_contract
        schema={'type':'object','properties':{'quantity':{'type':'integer'}},'required':['quantity']}
        required,_=current_contract({'a':'Answer JSON schema:\n'+json.dumps(schema,indent=2)})
        self.assertEqual(required,{'quantity':'integer'})

    def test_union_schema_does_not_raise(self):
        from solution.task_contracts import current_contract
        schema={'type':'object','properties':{'label':{'type':['string','null']}},'required':['label']}
        required,_=current_contract({'a':'Answer JSON schema: '+json.dumps(schema)})
        self.assertEqual(required,{'label':['string','null']})

    def test_checker_explicit_failure_cannot_fast_extract_token(self):
        from solution.task_contracts import extract_proof
        self.assertIsNone(extract_proof('{"success":false,"token":"synthetic"}',{'token':'string'}))
