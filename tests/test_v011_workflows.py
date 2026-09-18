"""Synthetic workflow regressions; no downloaded tasks, answers or credentials."""
import hashlib
import json
import tempfile
import threading
import unittest
import io
import subprocess
import sys
import shlex
from unittest.mock import patch
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit
from tests.test_task_procedures import run_procedure


class WorkflowTests(unittest.TestCase):
    def test_spec_repairs_directories_permissions_lines_and_preserves_checker(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root); w = p/'project_random'; w.mkdir()
            (p/'task_current.md').write_text('Repair project_random using spec.md and check. Submit JSON: {"token":"string"}')
            (w/'settings.cfg').write_text('wrong\n')
            (w/'worker.sh').write_bytes(b'#!/bin/sh\r\nexit 0\r\n')
            (w/'spec.md').write_text('cache/ 必须存在，权限为 755\nworker.sh 必须存在，权限为 755\n## settings.cfg\n第 1 行：`mode=ready`\n')
            proof=hashlib.sha256(root.encode()).hexdigest()
            checker=("#!/usr/bin/env python3\nfrom pathlib import Path\nimport os\n"
                     "assert Path('cache').is_dir()\nassert os.access('worker.sh',os.X_OK)\n"
                     "assert Path('settings.cfg').read_text().splitlines()[0]=='mode=ready'\n"
                     "assert b'\\r' not in Path('worker.sh').read_bytes()\nprint('TOKEN: "+proof+"')\n")
            (w/'check').write_text(checker); original=(w/'check').read_bytes()
            result=run_procedure({'kind':'bootstrap','base':root,'filename':'task_current.md','task_id':'T1'})
            self.assertTrue(result.get('checked'),result)
            self.assertTrue(result.get('schema_pass'))
            self.assertEqual(result['answer'],{'token':proof})
            self.assertEqual((w/'check').read_bytes(),original)

    def test_api_reads_real_nested_records_without_city_and_offset_pages(self):
        visits=[];credential=['synthetic-auth'];totals={'SampleTown':5,'NextTown':3,'LastTown':4}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                q=parse_qs(urlsplit(self.path).query);visits.append(q)
                if self.headers.get('Authorization')!='Bearer '+credential[0]:
                    self.send_response(401);self.end_headers();self.wfile.write(b'Use Authorization Bearer');return
                if 'location' not in q:
                    self.send_response(400);self.end_headers();self.wfile.write(b'required parameter: location');return
                total=totals.get(q['location'][0],0)
                offset=int(q.get('offset',['0'])[0]);rows=[{'id':i,'name':f'Item{i}','type':'example','era':str(i)} for i in range(offset,min(offset+2,total))]
                body=json.dumps({'data':{'records':rows,'pagination':{'total_count':total,'offset':offset,'limit':2}}}).encode()
                self.send_response(200);self.end_headers();self.wfile.write(body)
        with HTTPServer(('127.0.0.1',0),Handler) as server, tempfile.TemporaryDirectory() as root:
            t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            try:
                Path(root,'task_current.md').write_text('Query city: SampleTown\nAnswer JSON: {"city":"string","total_count":0,"types":[],"oldest_era":"string"}')
                Path(root,'api_docs.md').write_text(f'GET http://127.0.0.1:{server.server_port}/items?city=SampleTown\nX-API-Key: `synthetic-auth`')
                r=run_procedure(dict(kind='bootstrap',base=root,filename='task_current.md',task_id='T1'))
                first_requests=len(visits)
                for ordinal,city in enumerate(('NextTown','LastTown'),2):
                    credential[0]='synthetic-auth-'+str(ordinal)
                    Path(root,'task_current.md').write_text('Query city: '+city+'\nAnswer JSON: {"city":"string","total_count":0,"types":[],"oldest_era":"string"}')
                    Path(root,'api_docs.md').write_text(f'GET http://127.0.0.1:{server.server_port}/items\nX-API-Key: `'+credential[0]+'`')
                    before=len(visits)
                    follow=run_procedure(dict(kind='bootstrap',base=root,filename='task_current.md',task_id='T'+str(ordinal),method=r['method']))
                    self.assertEqual(follow['retrieval']['object'],city)
                    self.assertEqual(follow['retrieval']['count'],totals[city])
                    self.assertLess(len(visits)-before,first_requests)
            finally:server.shutdown();t.join()
        self.assertEqual(r.get('status'),'data_ready',r)
        self.assertEqual(len(r['retrieval']['records']),5)
        self.assertTrue(r['retrieval']['complete'])
        self.assertEqual(r['method']['query_parameter'],'location')
        self.assertNotIn('synthetic-auth',json.dumps(r.get('method')))
        self.assertGreaterEqual(len(visits),4)

    def test_new_task_clears_reuse_marker(self):
        from solution.task_series import TaskSeries
        s=TaskSeries();s.last_reuse={'used':True,'source':'old'};s.begin('new',1)
        self.assertFalse(s.last_reuse.get('used',False))

    def test_business_failure_not_reported_as_proof_format(self):
        with tempfile.TemporaryDirectory() as root:
            r=run_procedure(dict(kind='repair',base=root,edits=[],check=['python3','-c',"print('[FAIL] DIR output - expected exists,755')"],required={'token':'string'}))
        self.assertEqual(r['status'],'checker_reported_failure')

    def test_real_data_routes_to_one_model_then_submits_without_extra_command(self):
        from tests.test_v010_regressions import active_manager
        from solution.state import LlmBudget
        from solution.rules import DEFAULT_CONFIG
        from solution.models import Turn
        from tests.helpers import synthetic_turn
        result={'ok':True,'status':'data_ready','kind':'bootstrap','task_id':'T001',
            'retrieval':{'complete':True,'records_omitted':0,'records':[{'id':'one','type':'sample'}],
                         'object':'ExampleTown','count':1,'total':1,'reason':'total_matched',
                         'filter_evidence':'accepted_parameter_without_record_echo'},
            'documents':[{'path':'requirements.md','text':'Answer JSON: {"city":"string","total_count":0,"types":[]}', 'complete':True}]}
        m,t,s=active_manager(result=result);m.context.last_plan={'kind':'bootstrap'};m.llm_requested_round=None
        p=m.plan(t,s,LlmBudget(),DEFAULT_CONFIG,t.team_our.unit(2))
        self.assertTrue(m.context.data_ready);self.assertIn('actual records',p.prompt)
        self.assertFalse(p.execute_command)
        raw=synthetic_turn(round_no=14);raw['llmResp']=json.dumps({'answer':{'city':'ExampleTown','total_count':1,'types':['sample']}})
        t=Turn.from_raw(raw);p=m.plan(t,s,LlmBudget(),DEFAULT_CONFIG,t.team_our.unit(2))
        self.assertIsNotNone(p.action);self.assertEqual(p.action.action_type.value,'submitAnswer')

    def test_bootstrap_checker_proof_submits_in_result_turn(self):
        from tests.test_v010_regressions import active_manager
        from solution.state import LlmBudget
        from solution.rules import DEFAULT_CONFIG
        result={'ok':True,'checked':True,'status':'repair_checked','kind':'bootstrap','task_id':'T001',
                'answer':{'token':'synthetic-fresh'},'documents':[{'path':'task.md','text':'Submit JSON: {"token":"string"}','complete':True}]}
        m,t,s=active_manager(2,result=result);m.context.last_plan={'kind':'bootstrap'}
        p=m.plan(t,s,LlmBudget(),DEFAULT_CONFIG,t.team_our.unit(2))
        self.assertIsNotNone(p.action);self.assertFalse(p.prompt)

    def test_method_reuses_auth_and_query_only_after_current_execution(self):
        from solution.task_series import TaskSeries
        s=TaskSeries();s.begin('T1',1)
        method={'family':'api','auth_header':'Authorization','query_parameter':'location','records_path':'data.records','pagination':'offset_limit'}
        s.observe('T1',{'ok':True,'method':method,'retrieval':{'complete':True}})
        self.assertEqual(s.methods[(1,'bootstrap')]['level'],'observed')
        s.settle('T1','full');s.begin('T2',1)
        self.assertEqual(s.workflow_hint(1),method)
        self.assertFalse(s.last_reuse.get('used'))
        self.assertEqual(s.methods[(1,'bootstrap')]['level'],'platform_full')

    def test_data_candidate_invariants_and_no_cross_task_data(self):
        from solution.task_context import TaskContext
        c=TaskContext(required={'city':'string','total_count':'integer','types':'array'})
        c.retrieval={'complete':True,'records':[{'id':'a','type':'sample'}],'object':'Town','reason':'total_matched','filter_evidence':'record_field'}
        self.assertEqual(c.data_answer_error({'city':'Town','total_count':2,'types':['sample']}),'record_count_mismatch')
        self.assertEqual(c.data_answer_error({'city':'Elsewhere','total_count':1,'types':['sample']}),'query_object_mismatch')
        self.assertFalse(TaskContext().data_ready)

    def test_readable_trace_preserves_calculation_but_masks_credentials(self):
        from solution.task_audit import Redactor
        r=Redactor()
        text='X-API-Key: `synthetic-secret-value`\nTOKEN: synthetic-proof-value\nhttps://internal.invalid/data\nassert total_count == 17\n'
        result=r.readable(text,5000)['text']
        for secret in ('synthetic-secret-value','synthetic-proof-value','internal.invalid'):self.assertNotIn(secret,result)
        self.assertIn('total_count == 17',result)
        self.assertNotIn('private-session',r.readable({'headers':{'Cookie':'private-session'}})['text'])
        self.assertTrue(r.readable('x'*100,12)['truncated'])

    def test_trace_chunks_and_settlement_reserve(self):
        from solution.task_audit import TaskAudit
        from tests.helpers import synthetic_turn
        from solution.models import Turn
        a=TaskAudit();t=Turn.from_raw(synthetic_turn());a.start(t,t.team_our.player_tasks[0].task_position)
        a.artifact(2,'solver','print(42)\n'*400,8000)
        chunks=[e for e in a.events if e['kind']=='trace']
        self.assertGreater(len(chunks),1)
        self.assertEqual(''.join(e['text'] for e in chunks),'print(42)\n'*400)
        for _ in range(100):a.emit('trace',3,{'text':'x'*5000},True)
        a.emit('end',4,{'outcome':'zero'},True)
        self.assertEqual(a.events[-1]['kind'],'end');self.assertGreater(a.dropped,0)

    def test_unknown_contract_and_ambiguous_project_fall_back_without_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);(p/'task.md').write_text('Read a project. Answer JSON: {"token":"string"}')
            for name in ('one','two'):
                (p/name).mkdir();(p/name/'check').write_text('unchanged')
            r=run_procedure(dict(kind='bootstrap',base=root,filename='task.md'))
            self.assertFalse(r.get('checked'));self.assertEqual((p/'one/check').read_text(),'unchanged')

    def test_api_root_prefix_and_response_preview(self):
        from solution.task_api import run_api
        class Response(io.BytesIO):status=200
        class Opener:
            def open(self,*args,**kwargs):return Response(json.dumps({'data':{'records':[{'id':1,'city':'Town'}]}}).encode())
        with patch('urllib.request.build_opener',return_value=Opener()):
            r=run_api({'url':'http://localhost:1234/items','records_path':'$.data.records','unpaginated':True,
                       'filter':{'path':'city','value':'Town'},'fields':{'n':{'op':'count'}},'required':{'n':'integer'}},lambda:5)
        self.assertTrue(r['checked'],r)

    def test_stale_task_bootstrap_result_cannot_submit(self):
        from tests.test_v010_regressions import active_manager
        from solution.rules import DEFAULT_CONFIG
        from solution.state import LlmBudget
        m,t,s=active_manager(2,result={'task_id':'previous','ok':True,'checked':True,'answer':{'token':'old'}})
        p=m.plan(t,s,LlmBudget(),DEFAULT_CONFIG,t.team_our.unit(2))
        self.assertIsNone(p.action);self.assertEqual(m.diagnostic,'stale_task_result')

    def test_ignored_query_is_detected_even_with_http_success(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                data={'data':{'records':[{'id':1,'name':'One'}],'pagination':{'total_count':1,'offset':0,'limit':1}}}
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(data).encode())
        with HTTPServer(('127.0.0.1',0),Handler) as server,tempfile.TemporaryDirectory() as root:
            t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            try:
                Path(root,'task.md').write_text('Query city: SampleTown\nAnswer JSON: {"city":"string","total_count":0}')
                Path(root,'api_docs.md').write_text(f'GET http://127.0.0.1:{server.server_port}/items')
                r=run_procedure(dict(kind='bootstrap',base=root,filename='task.md'))
            finally:server.shutdown();t.join()
        self.assertEqual(r['retrieval']['reason'],'filter_not_applied');self.assertFalse(r['retrieval']['complete'])

    def test_new_proof_field_is_redacted_from_output_and_model_answer(self):
        from solution.task_audit import TaskAudit
        from solution.task_series import TaskSeries
        from solution.models import Turn
        from tests.helpers import synthetic_turn
        a=TaskAudit();t=Turn.from_raw(synthetic_turn());a.start(t,t.team_our.player_tasks[0].task_position)
        a.active['task_type']=2;a.active['required']={'approval_code':'string'}
        a.execution(t,{}, {'status':'script_ok','output':'{"approval_code":"private-dynamic-value"}'},TaskSeries())
        self.assertNotIn('private-dynamic-value',json.dumps(a.events))

    def test_production_transports_include_needed_helpers_and_fit_command_limit(self):
        from solution.task_programs import procedure_command
        from solution.tasking import safe_task_command
        for plan in ({'kind':'bootstrap','filename':'task.md'},{'kind':'python','code':'print(42)'}):
            with tempfile.TemporaryDirectory() as root:
                Path(root,'task.md').write_text('Unknown synthetic task.')
                command=procedure_command(plan)
                self.assertTrue(safe_task_command(command))
                source=shlex.split(command)[2]
                source=source.replace(';exec(',";options['base']="+repr(root)+';exec(')
                run=subprocess.run([sys.executable,'-c',source],capture_output=True,text=True,timeout=10)
                self.assertEqual(run.returncode,0,run.stderr)
                result=json.loads(run.stdout)['procedure_result']
                self.assertNotIn(result.get('status'),('NameError','UnboundLocalError'))


if __name__=='__main__':unittest.main()
