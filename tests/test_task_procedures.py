from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from solution.task_programs import SANDBOX_PROGRAM, procedure_command
from solution.tasking import TaskManager, TaskPhase, parse_structured_llm
from solution.models import Turn
from solution.state import WorldState, LlmBudget
from solution.rules import DEFAULT_CONFIG
from tests.helpers import synthetic_turn


def run_procedure(options):
    source = 'options=' + repr(options) + '\n' + SANDBOX_PROGRAM
    process = subprocess.run([sys.executable, '-c', source], capture_output=True, text=True, timeout=12)
    if process.returncode:
        raise AssertionError(process.stderr)
    return json.loads(process.stdout)["procedure_result"]


class ProcedureTests(unittest.TestCase):
    def test_repair_runs_checker_and_returns_fresh_answer(self):
        for _ in range(2):
            with tempfile.TemporaryDirectory() as root:
                token = uuid.uuid4().hex
                Path(root,'calc.py').write_text('def add(a,b): return a-b\n')
                Path(root,'check.py').write_text('import json\nfrom calc import add\nassert add(4,7)==11\nprint(json.dumps({"proof":'+repr(token)+'}))\n')
                result = run_procedure(dict(kind='repair',base=root,
                    edits=[dict(path='calc.py',old='return a-b',new='return a+b')],check=["python3","check.py"]))
                self.assertTrue(result['checked'])
                self.assertEqual(result['answer'], {'proof':token})

    def test_failed_checker_does_not_produce_answer(self):
        with tempfile.TemporaryDirectory() as root:
            result = run_procedure(dict(kind='repair',base=root,edits=[],check=['python3','-c','raise SystemExit(1)']))
            self.assertFalse(result['ok'])
            self.assertNotIn('answer',result)

    def test_checker_output_is_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            result = run_procedure(dict(kind='repair',base=root,edits=[],
                check=['python3','-c','print("x"*200000)']))
            self.assertFalse(result['ok'])
            self.assertLessEqual(len(result.get('output','')),12000)

    def test_two_edits_to_same_file_are_both_applied(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'data.txt').write_text('first=1\nsecond=2\n')
            result=run_procedure(dict(kind='repair',base=root,
                edits=[dict(path='data.txt',old='first=1',new='first=3'),dict(path='data.txt',old='second=2',new='second=4')],
                check=['python3','-c','import json; from pathlib import Path; assert Path("data.txt").read_text()=="first=3\\nsecond=4\\n"; print(json.dumps({"checked":True}))']))
            self.assertTrue(result['ok'])

    def test_paths_cannot_escape_task_directory(self):
        with tempfile.TemporaryDirectory() as root:
            result = run_procedure(dict(kind='repair',base=root,edits=[dict(path='../escape',old='a',new='b')],check=['python3','-c','pass']))
            self.assertFalse(result['ok'])
        self.assertEqual(procedure_command({'kind':'inspect','base':'/outside'}), '')

    def test_paginated_api_is_fully_read_before_aggregation(self):
        visited=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                from urllib.parse import urlsplit, parse_qs
                page=int(parse_qs(urlsplit(self.path).query)['page'][0]); visited.append(page)
                records=[{'key':i,'amount':i*3,'flag':i%2==0,'tag':str(i%2)} for i in range(1,6)]
                data=json.dumps({'data':records[(page-1)*2:page*2],'total':len(records)}).encode()
                self.send_response(200); self.end_headers(); self.wfile.write(data)
            def log_message(self,*args): pass
        with HTTPServer(('127.0.0.1',0),Handler) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            try:
                result=run_procedure(dict(kind='api',url=f'http://127.0.0.1:{server.server_port}/records',records_path='data',
                    pagination=dict(parameter='page',start=1,size=2,total_path='total',id_path='key'),
                    fields=dict(count={'op':'count'}, flagged={'op':'count_equal','path':'flag','value':True},
                                total={'op':'sum','path':'amount'},largest={'op':'max_by','path':'amount','value_path':'key'})))
            finally:
                server.shutdown(); thread.join()
        self.assertEqual(visited,[1,2,3])
        self.assertEqual(result['answer'],{'count':5,'flagged':2,'total':45,'largest':5})

    def test_api_refuses_external_host(self):
        result=run_procedure(dict(kind='api',url='https://example.com/data'))
        self.assertFalse(result['ok'])


class RecoveryTests(unittest.TestCase):
    def test_fenced_json_is_supported_but_nonfinite_values_are_not(self):
        self.assertEqual(parse_structured_llm('```json\n{"answer":{"n":7}}\n```'),{'answer':{'n':7}})
        self.assertIsNone(parse_structured_llm('{"answer":NaN}'))

    def test_ten_round_task_is_not_rejected_by_travel_time(self):
        raw=synthetic_turn(round_no=1); raw['phaseTask']=''
        raw['teamOur']['playerTasks'][0]['timeoutRounds']=10
        turn=Turn.from_raw(raw)
        self.assertIsNotNone(TaskManager._choose_task(turn,turn.team_our.unit(2),DEFAULT_CONFIG))

    def test_failed_task_clears_evidence_and_accepts_another_task(self):
        raw=synthetic_turn(round_no=20); raw['phaseTask']=''
        turn=Turn.from_raw(raw); state=WorldState(); state.ingest(turn)
        manager=TaskManager(last_generation=state.generation,active_seen=True,phase=TaskPhase.FAILED,
                            command_steps=5,command_output='stale synthetic evidence',pending_answer='old')
        plan=manager.plan(turn,state,LlmBudget(),DEFAULT_CONFIG,turn.team_our.unit(2))
        self.assertEqual(plan.action.action_type.value,'acceptTask')
        self.assertEqual(manager.command_steps,0)
        self.assertEqual(manager.command_output,'')
        self.assertEqual(manager.failed,1)

    def test_procedure_result_can_submit_without_extra_llm_round(self):
        raw=synthetic_turn(round_no=14)
        raw['lastCmdResult']='[exitCode:0]\n'+json.dumps({'procedure_result':{'ok':True,'checked':True,'answer':{'value':37}}})
        turn=Turn.from_raw(raw); state=WorldState(); state.ingest(turn)
        manager=TaskManager(last_generation=state.generation,phase=TaskPhase.WAITING_COMMAND,
                            pending_procedure=True,command_steps=2)
        plan=manager.plan(turn,state,LlmBudget(),DEFAULT_CONFIG,turn.team_our.unit(2))
        self.assertEqual(json.loads(plan.action.task_answer),{'value':37})
        self.assertFalse(plan.prompt)
