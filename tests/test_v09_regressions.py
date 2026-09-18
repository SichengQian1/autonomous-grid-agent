"""Synthetic regression specifications for the v0.9 operating changes."""
import json
import tempfile
import unittest
from pathlib import Path
from solution.models import Turn
from solution.defense import build_defense_layout
from solution.rules import DEFAULT_CONFIG
from solution.task_context import TaskContext
from tests.helpers import synthetic_turn, role
from tests.test_task_procedures import run_procedure

class ObservedFailures(unittest.TestCase):
    def test_auxiliary_verifier_error_preserves_computed_candidate(self):
        with tempfile.TemporaryDirectory() as root:
            result=run_procedure(dict(kind='python',base=root,code='print(\'{"total":7}\')',
                submit_result=True,required={'total':'integer'},verify='assert answer["total"] == missing_variable'))
        ctx=TaskContext();ctx.ingest({'procedure_result':result},'',True)
        self.assertEqual(ctx.candidate,{'total':7})
        self.assertTrue(ctx.schema_pass)
        self.assertFalse(ctx.candidate_checked)

    def test_project_checker_can_be_a_local_executable(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'project').mkdir()
            check=Path(root,'project','verify');check.write_text('#!/bin/sh\nprintf \'{"proof":"synthetic-fresh"}\\n\'\n');check.chmod(0o700)
            result=run_procedure(dict(kind='repair',base=root,cwd='project',edits=[],check=['./verify']))
            self.assertTrue(result.get('checked'),result)

    def test_requested_three_rockets_and_four_open_rear_cells(self):
        raw=synthetic_turn(round_no=1)
        raw['mapInfo']={'width':41,'height':32,'zones':[]}
        raw['teamOur']['roles']=[role(1,'station',9,23,health=1500,level=1)]
        turn=Turn.from_raw(raw);layout=build_defense_layout(turn)
        self.assertEqual(DEFAULT_CONFIG.primary_weapon_loadout,('rocket',)*3)
        self.assertEqual(len(layout.wall_sites),16)
        self.assertEqual(len(set(layout.controller_sites)),2)
        self.assertEqual(DEFAULT_CONFIG.recall_safety_buffer+DEFAULT_CONFIG.recall_traffic_buffer,2)

class ApiSopTests(unittest.TestCase):
    def api(self,mode,**overrides):
        import threading
        from http.server import BaseHTTPRequestHandler,HTTPServer
        from urllib.parse import parse_qs,urlsplit
        visits=[]
        records=[{'id':i,'place':'NewTown','heritage':i%2==0,'kind':'a' if i<3 else 'b','year':-i*100,'era':f'era-{i}'} for i in range(1,6)]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                q=parse_qs(urlsplit(self.path).query);page=int(q.get('page',['1'])[0]);visits.append(page)
                selected=records[(page-1)*2:page*2]
                if mode=='repeat':selected=records[:2]
                if mode=='overlap':selected=records[max(0,page-1):page+1]
                if mode=='ignored_filter':selected=[dict(r,place='OtherTown') for r in selected]
                body={'rows':selected,'total':len(records),'more':page*2<len(records)}
                if mode=='no_total':body.pop('total')
                if mode=='wrong_total':body['total']=6
                if mode=='changed_structure':body={'items':selected}
                if mode=='auth':self.send_response(401);self.end_headers();return
                data=json.dumps(body).encode();self.send_response(200);self.end_headers();self.wfile.write(data)
            def log_message(self,*args):pass
        with HTTPServer(('127.0.0.1',0),Handler) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                plan=dict(kind='api',url=f'http://127.0.0.1:{server.server_port}/data',query={'city':'NewTown'},
                    filter={'path':'place','value':'NewTown'},records_path='rows',
                    pagination={'parameter':'page','size':100,'size_parameter':'limit','id_path':'id','total_path':'total'},
                    required={'city':'string','total_count':'integer','world_heritage_count':'integer','types':'array','oldest_era':'string'},
                    fields={'city':{'op':'constant','value':'NewTown','source':'requirement'},'total_count':{'op':'count'},
                    'world_heritage_count':{'op':'count_equal','path':'heritage','value':True},
                    'types':{'op':'unique','path':'kind','sort':'ascending'},
                    'oldest_era':{'op':'min_by','path':'year','value_path':'era','comparison':'numeric'}})
                plan.update(overrides)
                result=run_procedure(plan)
            finally:server.shutdown();thread.join()
        return result,visits

    def test_ignored_size_does_not_stop_on_short_page(self):
        result,visits=self.api('normal');self.assertEqual(visits,[1,2,3]);self.assertTrue(result['checked'])
        self.assertEqual(result['answer'],dict(city='NewTown',total_count=5,world_heritage_count=2,types=['a','b'],oldest_era='era-5'))
    def test_overlapping_pages_are_deduplicated_by_record_identity(self):
        result,visits=self.api('overlap');self.assertTrue(result['checked'])
        self.assertEqual(result['answer']['total_count'],5);self.assertEqual(visits,[1,2,3,4])
    def test_explicit_rebinding_recovers_changed_response_structure(self):
        result,visits=self.api('changed_structure',records_path='items',pagination={'parameter':'page','id_path':'id','empty_is_end':True})
        self.assertTrue(result['checked']);self.assertEqual(visits,[1,2,3,4])
    def test_http_success_with_ignored_filter_is_not_checked(self):
        result,_=self.api('ignored_filter');self.assertEqual(result['status'],'filter_not_applied')
    def test_auth_failure_is_separate(self):
        result,_=self.api('auth');self.assertEqual(result['status'],'authentication_failed')
    def test_repeated_page_is_detected(self):
        result,visits=self.api('repeat');self.assertEqual(result['status'],'repeated_page');self.assertEqual(len(visits),2)
    def test_no_total_uses_documented_end_marker(self):
        result,_=self.api('no_total',pagination={'parameter':'page','size':100,'id_path':'id','end_path':'more','end_value':False})
        self.assertTrue(result['checked'])
    def test_total_mismatch_is_not_success(self):
        result,_=self.api('wrong_total',pagination={'parameter':'page','size':100,'id_path':'id','total_path':'total','end_path':'more','end_value':False})
        self.assertEqual(result['status'],'total_mismatch')
    def test_schema_change_requests_new_binding(self):
        result,_=self.api('changed_structure');self.assertEqual(result['status'],'parse_or_compute_failed')
        self.assertEqual(result['evidence']['requests'][0]['structure']['items']['type'],'array')
    def test_value_type_mismatch_not_silently_zero_count(self):
        result,_=self.api('normal',fields={'count':{'op':'count_equal','path':'heritage','value':'true'}})
        self.assertEqual(result['status'],'field_value_type')
    def test_unknown_era_comparison_does_not_use_lexical_min(self):
        result,_=self.api('normal',fields={'oldest_era':{'op':'min_by','path':'era','value_path':'era'}})
        self.assertFalse(result['checked']);self.assertEqual(result['evidence']['detail'],'comparison_rule_missing')
    def test_partial_data_retains_candidate_but_not_complete_label(self):
        result,_=self.api('no_total',pagination={'parameter':'page','size':100,'id_path':'id','max_pages':1})
        self.assertEqual(result['status'],'incomplete_pages');self.assertEqual(result['answer']['total_count'],2)
        self.assertTrue(result['schema_pass']);self.assertFalse(result['checked'])

class RepairAndExperienceTests(unittest.TestCase):
    def test_distinct_doc_project_directories_recover_unique_file(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'instructions').mkdir();Path(root,'app_v2').mkdir()
            Path(root,'instructions','task.md').write_text('Read the project spec before fixing it.')
            Path(root,'app_v2','settings').write_text('mode=off')
            Path(root,'app_v2','check.py').write_text('import json\nfrom pathlib import Path\nassert Path("settings").read_text()=="mode=on"\nprint(json.dumps({"proof":"fresh-task-only"}))')
            read=run_procedure(dict(kind='inspect',base=root,filename='task.md'))
            self.assertIn('app_v2/settings',read['files'])
            result=run_procedure(dict(kind='repair',base=root,cwd='app_v2',edits=[dict(path='old/settings',old='mode=off',new='mode=on')],check=['python3','check.py']))
            self.assertTrue(result['checked']);self.assertTrue(any(p.get('method')=='unique_basename' for p in result['path_evidence']))
    def test_nonunique_patch_and_checker_edits_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'config').write_text('a a');Path(root,'check.py').write_text('print(7)')
            result=run_procedure(dict(kind='repair',base=root,edits=[dict(path='config',old='a',new='b')],check=['python3','check.py']))
            self.assertEqual(result['reason'],'non_unique_patch')
            result=run_procedure(dict(kind='repair',base=root,edits=[dict(path='check.py',old='7',new='9')],check=['python3','check.py']))
            self.assertFalse(result['ok']);self.assertEqual(Path(root,'check.py').read_text(),'print(7)')
    def test_match_methods_never_keep_answers_auth_or_object_constants(self):
        from solution.task_series import TaskSeries
        series=TaskSeries()
        plan={'kind':'api','url':'http://127.0.0.1:1/current','headers':{'Authorization':'secret-runtime'},
              'query':{'place':'old-object'},'filter':{'path':'place','value':'old-object'},
              'required':{'city':'string','n':'integer'},'compatibility':{'contract':'c','schema':'v1'},
              'fields':{'city':{'op':'constant','value':'old-object'},'n':{'op':'count'}},'records_path':'rows'}
        series.prepare(plan,'T001',1);series.observe('T001',{'ok':True,'checked':True});series.settle('T001','partial')
        text=series.prompt(1);self.assertNotIn('secret-runtime',text);self.assertNotIn('old-object',text)
        self.assertNotIn('platform_full',text)
        for index in (2,3):
            fresh={'kind':'api','reuse':True,'url':'http://127.0.0.1:2/new','query':{'place':str(index)},
              'filter':{'path':'place','value':str(index)},'required':plan['required'],
              'compatibility':plan['compatibility'],'fields':{'city':{'op':'constant','value':str(index)}}}
            prepared=series.prepare(fresh,f'T00{index}',1)
            self.assertEqual(prepared['fields']['n'],{'op':'count'})
            self.assertEqual(prepared['fields']['city']['value'],str(index))
            series.observe(f'T00{index}',{'ok':True,'checked':True});series.settle(f'T00{index}','full')
        self.assertEqual(series.hits,2);self.assertIn('platform_full',series.prompt(1))
        fresh['compatibility']={'contract':'c','schema':'v2'}
        with self.assertRaisesRegex(ValueError,'contract_changed'):series.prepare(fresh,'T004',1)
        self.assertEqual(series.invalidations,1)
        self.assertFalse(TaskSeries().methods)

class AuditTests(unittest.TestCase):
    def test_type_uses_zone_position_not_task_array_index(self):
        from solution.task_audit import task_category
        from solution.geometry import Pos
        raw=synthetic_turn();raw['mapInfo']['zones']=[{'neutralType':'challengerTaskPoint2','pos':{'x':3,'y':3}}]
        raw['teamOur']['playerTasks'].reverse()
        self.assertEqual(task_category(Turn.from_raw(raw),Pos(3,3)),2)
    def test_sensitive_proof_and_auth_never_leak_through_program_output_answer(self):
        from solution.task_audit import TaskAudit
        from solution.task_series import TaskSeries
        audit=TaskAudit();turn=Turn.from_raw(synthetic_turn());audit.start(turn,turn.team_our.player_tasks[0].task_position)
        audit.active['task_type']=2
        result={'kind':'repair','checked':True,'ok':True,'answer':{'unknown_proof_key':'VERY_PRIVATE_TOKEN'},
                'output':'expected VERY_PRIVATE_TOKEN actual PASSWORD_123\nFile "/private/account/main.py", line 4\nValueError',
                'cwd':'/private/account/project'}
        audit.execution(turn,{'code':'key="VERY_PRIVATE_TOKEN"\nprint(key)','headers':{'Authorization':'PASSWORD_123'}},result,TaskSeries())
        text=json.dumps(audit.events)
        for secret in ('VERY_PRIVATE_TOKEN','PASSWORD_123','/private/account','unknown_proof_key'):
            if secret=='unknown_proof_key':continue
            self.assertNotIn(secret,text)
        self.assertIn('ValueError',text);self.assertIn('line',text)
    def test_arbitrary_output_keys_are_anonymized(self):
        from solution.task_audit import Redactor
        redactor=Redactor()
        value=redactor.structure({'synthetic-private-account':{'synthetic-proof-as-key':'value'},'total_count':8})
        text=json.dumps(value)
        self.assertNotIn('synthetic-private-account',text)
        self.assertNotIn('synthetic-proof-as-key',text)
        self.assertIn('total_count',text)

    def test_budget_preserves_settlement_and_reports_drops(self):
        from solution.task_audit import TaskAudit
        audit=TaskAudit(task_limit=4000);turn=Turn.from_raw(synthetic_turn());audit.start(turn,turn.team_our.player_tasks[0].task_position)
        for _ in range(20):audit.emit('execution',71,{'detail':'x'*500})
        audit.emit('end',80,{'outcome':'zero'},True)
        self.assertGreater(audit.dropped,0);self.assertEqual(audit.events[-1]['kind'],'end')
    def test_mixed_sale_is_subtracted_from_task_reward(self):
        from solution.task_audit import TaskAudit
        from solution.task_series import TaskSeries
        audit=TaskAudit();raw=synthetic_turn(round_no=10);raw['teamOur']['playerTasks'][0]['goldReward']=80
        turn=Turn.from_raw(raw);audit.start(turn,turn.team_our.player_tasks[0].task_position);audit.active['seen']=True
        audit.previous={'r':10,'gold':0,'commands':{'1':{'action':'sell','name':'copper','num':10}},'vendor':{'copper':5},'shop':{}}
        raw.update(roundNo=11,phaseTask='');raw['teamOur']['goldNum']=66
        audit.observe(Turn.from_raw(raw),TaskSeries())
        end=audit.events[-1];self.assertEqual(end['outcome'],'partial');self.assertEqual(end['task_gold'],16)
        from tools.diagnostics.task_report import summarize_tasks
        report=summarize_tasks(audit.events,'T001')
        self.assertEqual(report['by_type']['0']['partial'],1)

class RocketOperationsTests(unittest.TestCase):
    def scene(self,side='challenger',round_no=71):
        from tests.test_operations_v04 import campus
        raw=campus(side);raw['roundNo']=round_no
        turn=Turn.from_raw(raw);layout=build_defense_layout(turn)
        for i,pos in enumerate(layout.weapon_sites[:3]):
            raw['teamOur']['roles'].append(role(20+i,'rocket',pos.x,pos.y,health=1000,level=1,attack_range=30))
        for u,pos in zip(raw['teamOur']['roles'][:3],(layout.controller_sites[0],layout.rear_corridor[-1],layout.controller_sites[1])):u['pos']=pos.to_raw()
        return raw
    def test_one_controller_alternates_two_ready_rockets_on_both_sides(self):
        from solution.combat import assign_controllers,plan_attacks
        for side in ('challenger','defender'):
            raw=self.scene(side);turn=Turn.from_raw(raw)
            center=turn.coordinate_frame.denormalize(__import__('solution.geometry',fromlist=['Pos']).Pos(12,10))
            raw['robot']={'roles':[dict(id=90,roleType='bossRobot',pos=center.to_raw(),health=800,targetTeam=side)]}
            fired=set()
            for _ in range(4):
                turn=Turn.from_raw(raw);assignments=assign_controllers(turn,tuple(w for w in turn.team_our.roles if w.is_weapon))
                self.assertEqual(len({a.controller.unit_id for a in assignments}),2)
                # Seat assigned operators at the chosen posts in this firing-only test.
                for a in assignments:next(u for u in raw['teamOur']['roles'] if u['id']==a.controller.unit_id)['pos']=a.control_pos.to_raw()
                turn=Turn.from_raw(raw);assignments=assign_controllers(turn,tuple(w for w in turn.team_our.roles if w.is_weapon))
                attacks=plan_attacks(turn,assignments,turn.robots)
                self.assertEqual(len(attacks),len({a.controller_id for a in attacks}))
                fired.update(a.actor_id for a in attacks)
                for u in raw['teamOur']['roles']:
                    u['cooldown']=3 if u['id'] in {a.actor_id for a in attacks} else max(0,u['cooldown']-1)
            self.assertEqual(fired,{20,21,22})
    def test_pair_layout_has_exact_requested_relative_cells(self):
        from solution.geometry import Pos
        for side in ('challenger','defender'):
            turn=Turn.from_raw(self.scene(side));layout=build_defense_layout(turn)
            cells=layout.frame.normalize_cells(turn.team_our.station().footprint())
            x=max(p.x for p in cells);y=max(p.y for p in cells)
            expected=[Pos(x-1,y-2),Pos(x-2,y),Pos(x-2,y-1)]
            self.assertEqual([layout.frame.normalize(p) for p in layout.weapon_sites[:3]],expected)
            self.assertEqual(len(layout.wall_sites),16)
    def test_early_spare_worker_can_mine_while_two_operators_defend(self):
        from solution.engine import AgentEngine
        raw=self.scene();layout=build_defense_layout(Turn.from_raw(raw))
        raw['teamOur']['roles'][0]['pos']=layout.controller_sites[0].to_raw()
        raw['teamOur']['roles'][2]['pos']=layout.controller_sites[1].to_raw()
        raw['teamOur']['roles'][1]['pos']={'x':1,'y':1}
        raw['teamOur']['goldNum']=0
        raw['mapInfo']['zones']=[{'neutralType':'copper','pos':{'x':2,'y':1}},{'neutralType':'vendor','pos':{'x':3,'y':1}}]
        raw['vendorShopList']=[{'name':'copper','price':5}]
        raw['robot']={'roles':[dict(id=90,roleType='smallRobot',pos={'x':13,'y':10},health=40,targetTeam='challenger')]}
        response=AgentEngine().decide(raw)
        self.assertEqual(response['roleCommandMap'].get('2',{}).get('action'),'collect')
        self.assertTrue(any(v['action']=='attack' for v in response['roleCommandMap'].values()))
    def test_front_support_uses_real_adjacency_and_retreats_without_goods(self):
        from solution.maintenance import support_plan
        from solution.defense import own_threats
        raw=self.scene(round_no=331);layout=build_defense_layout(Turn.from_raw(raw))
        for i,p in enumerate(layout.wall_sites[:6]):raw['teamOur']['roles'].append(role(50+i,'wall',p.x,p.y,health=1000,level=1))
        # priority index one is wall four; from behind wall two a move is required.
        raw['teamOur']['roles'][-5]['health']=200
        raw['teamOur']['roles'][1].update(pos={'x':7,'y':11},backpack=['WallUpgradeVoucher1'])
        turn=Turn.from_raw(raw);plan=support_plan(turn,turn.team_our.unit(2),DEFAULT_CONFIG,())
        self.assertIsNotNone(plan.move);self.assertIsNone(plan.action)
        raw['teamOur']['roles'][1]['backpack']=[];raw['teamOur']['roles'][-5]['health']=5
        turn=Turn.from_raw(raw);plan=support_plan(turn,turn.team_our.unit(2),DEFAULT_CONFIG,())
        self.assertIsNotNone(plan.move);self.assertNotEqual(plan.move.goals,(__import__('solution.geometry',fromlist=['Pos']).Pos(7,11),))
    def test_weapon_voucher_does_not_force_a_daytime_delivery_trip(self):
        from solution.logistics import LogisticsManager
        from solution.economy import defense_budget
        raw=self.scene(round_no=20);raw['teamOur']['roles'][1].update(pos={'x':1,'y':1},backpack=['WeaponUpgradeVoucher1'])
        turn=Turn.from_raw(raw);manager=LogisticsManager()
        plan=manager.plan(turn,turn.team_our.unit(2),defense_budget(turn,DEFAULT_CONFIG),DEFAULT_CONFIG)
        self.assertIsNone(plan.move);self.assertEqual(manager.stage,'carry_until_recall')

class TaskIntegrationTests(unittest.TestCase):
    def test_real_execution_candidate_survives_verifier_exception_until_deadline(self):
        from solution.tasking import TaskManager,TaskPhase
        from solution.state import WorldState,LlmBudget
        with tempfile.TemporaryDirectory() as root:
            result=run_procedure(dict(kind='python',base=root,code='print(\'{"n":7}\')',submit_result=True,
                                     required={'n':'integer'},verify='assert answer["n"]==undefined_name'))
        raw=synthetic_turn(round_no=19);raw['lastCmdResult']='[exitCode:0]\n'+json.dumps({'procedure_result':result})
        manager=TaskManager(phase=TaskPhase.WAITING_COMMAND,pending_procedure=True,command_steps=2,accepted_round=10,timeout_rounds=10)
        turn=Turn.from_raw(raw);state=WorldState();state.ingest(turn);manager.last_generation=state.generation
        plan=manager.plan(turn,state,LlmBudget(),DEFAULT_CONFIG,turn.team_our.unit(2))
        self.assertEqual(json.loads(plan.action.task_answer),{'n':7});self.assertEqual(manager.diagnostic,'deadline_candidate')
    def test_old_task_envelope_cannot_supply_new_proof(self):
        from solution.tasking import TaskManager,TaskPhase
        from solution.state import WorldState,LlmBudget
        raw=synthetic_turn(round_no=13)
        raw['lastCmdResult']='[exitCode:0]\n'+json.dumps({'procedure_result':{'task_id':'T-old','ok':True,'checked':True,'answer':'old-proof'}})
        turn=Turn.from_raw(raw);state=WorldState();state.ingest(turn)
        manager=TaskManager(phase=TaskPhase.WAITING_COMMAND,pending_procedure=True,command_steps=2,accepted_round=10,last_generation=state.generation)
        manager.audit.start(turn,turn.team_our.player_tasks[0].task_position)
        plan=manager.plan(turn,state,LlmBudget(),DEFAULT_CONFIG,turn.team_our.unit(2))
        self.assertIsNone(plan.action);self.assertEqual(manager.diagnostic,'stale_task_result')
    def test_successful_current_repair_proof_submits_immediately(self):
        import uuid
        from solution.tasking import TaskManager,TaskPhase
        from solution.state import WorldState,LlmBudget
        for _ in range(2):
            proof=uuid.uuid4().hex
            with tempfile.TemporaryDirectory() as root:
                result=run_procedure(dict(kind='repair',base=root,task_id='T001',edits=[],
                    check=['python3','-c',f'import json; print(json.dumps({{"proof":{proof!r}}}))'],answer_path='proof'))
            raw=synthetic_turn(round_no=13);raw['lastCmdResult']='[exitCode:0]\n'+json.dumps({'procedure_result':result})
            turn=Turn.from_raw(raw);state=WorldState();state.ingest(turn)
            manager=TaskManager(phase=TaskPhase.WAITING_COMMAND,pending_procedure=True,command_steps=2,accepted_round=10,last_generation=state.generation)
            manager.audit.start(turn,turn.team_our.player_tasks[0].task_position);manager.audit.active['task_type']=2
            plan=manager.plan(turn,state,LlmBudget(),DEFAULT_CONFIG,turn.team_our.unit(2))
            self.assertEqual(plan.action.task_answer,proof);self.assertFalse(plan.prompt)
            self.assertNotIn(proof,json.dumps(manager.audit.events))
    def test_specific_schema_reason_and_failed_line_are_readable_without_secrets(self):
        from solution.task_audit import TaskAudit
        from solution.task_series import TaskSeries
        with tempfile.TemporaryDirectory() as root:
            result=run_procedure(dict(kind='python',base=root,code='print(\'{"total_count":"bad"}\')',submit_result=True,required={'total_count':'integer'}))
        audit=TaskAudit();turn=Turn.from_raw(synthetic_turn());audit.start(turn,turn.team_our.player_tasks[0].task_position)
        audit.execution(turn,{'kind':'python'},result,TaskSeries())
        detail=audit.events[-1]['schema_details']
        self.assertEqual(detail,{'reason':'field_type','field':'total_count','expected':'integer','actual':'str'})
    def test_response_shapes_and_record_mapping_can_be_rebound_after_change(self):
        from solution.task_series import TaskSeries
        series=TaskSeries();plan={'kind':'api','compatibility':{'schema':'old'},'records_path':'rows','fields':{'n':{'op':'count'}},'required':{'n':'integer'}}
        series.prepare(plan,'T1',1);series.observe('T1',{'ok':True,'checked':True});series.settle('T1','full')
        series.prepare(dict(plan,records_path='rows'), 'T2',1)
        series.observe('T2',{'ok':False,'status':'parse_or_compute_failed'})
        self.assertFalse(series.methods)
        fresh=dict(plan,records_path='items',compatibility={'schema':'new'})
        self.assertEqual(series.prepare(fresh,'T2',1)['records_path'],'items')

class CacheAndBoundaryTests(unittest.TestCase):
    def test_recalculation_reuses_only_current_tasks_complete_data(self):
        import threading
        from http.server import BaseHTTPRequestHandler,HTTPServer
        visits=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                visits.append(self.path);body=json.dumps({'rows':[{'id':1,'place':'SyntheticTown'}],'total':1}).encode()
                self.send_response(200);self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        with tempfile.TemporaryDirectory() as root, HTTPServer(('127.0.0.1',0),Handler) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                plan=dict(kind='api',base=root,task_id='T1',cache_namespace='synthetic-match',url=f'http://127.0.0.1:{server.server_port}/rows',
                    records_path='rows',filter={'path':'place','value':'SyntheticTown'},pagination={'total_path':'total','id_path':'id'},
                    required={'n':'integer'},fields={'n':{'op':'sum','path':'missing'}})
                self.assertFalse(run_procedure(plan)['ok'])
                plan['fields']={'n':{'op':'count'}}
                second=run_procedure(plan);self.assertTrue(second['checked']);self.assertEqual(len(visits),1)
                self.assertEqual(second['evidence']['cache'],'current_task_binding_match')
                plan['task_id']='T2';self.assertTrue(run_procedure(plan)['checked']);self.assertEqual(len(visits),2)
                plan['cache_namespace']='another-match';self.assertTrue(run_procedure(plan)['checked']);self.assertEqual(len(visits),3)
            finally:server.shutdown();thread.join()
    def test_known_false_business_assertion_is_not_deadline_auto_submission(self):
        from solution.task_context import TaskContext
        with tempfile.TemporaryDirectory() as root:
            result=run_procedure(dict(kind='python',base=root,code='print(\'{"n":99}\')',submit_result=True,
                                     required={'n':'integer'},verify='assert answer["n"]==7'))
        context=TaskContext();context.ingest({'procedure_result':result},'',True)
        self.assertEqual(context.candidate,{'n':99});self.assertEqual(context.candidate_failure,'business_assertion_failed')
    def test_checker_launch_error_and_reported_failure_are_distinct(self):
        with tempfile.TemporaryDirectory() as root:
            missing=run_procedure(dict(kind='repair',base=root,edits=[],check=['./missing-check']))
            failed=run_procedure(dict(kind='repair',base=root,edits=[],check=['python3','-c','print(\'{"success":false}\')']))
            self.assertEqual(missing['status'],'FileNotFoundError');self.assertEqual(failed['status'],'checker_reported_failure')
    def test_early_free_worker_with_weapon_voucher_is_recalled(self):
        from solution.planner import CompetitionPlanner
        from solution.state import WorldState
        raw=RocketOperationsTests().scene(round_no=69)
        raw['teamOur']['roles'][1].update(pos={'x':1,'y':1},backpack=['WeaponUpgradeVoucher1'])
        turn=Turn.from_raw(raw);state=WorldState();state.ingest(turn)
        intents=CompetitionPlanner._individual_recall(turn,state,DEFAULT_CONFIG)
        self.assertIn(2,{i.actor_id for i in intents})

class ProjectRootRecoveryTests(unittest.TestCase):
    def test_checker_location_corrects_document_cwd_before_patch_and_launch(self):
        for project,filename,value in [('project_a','settings.ini','blue'),('project_b','options.cfg','green')]:
            with tempfile.TemporaryDirectory() as root:
                Path(root,'docs').mkdir();Path(root,project).mkdir()
                Path(root,project,filename).write_text('color=wrong')
                Path(root,project,'verify.py').write_text(f'import json\nfrom pathlib import Path\nassert Path({filename!r}).read_text()=={"color="+value!r}\nprint(json.dumps({{"proof":"generated-in-current-project"}}))')
                result=run_procedure(dict(kind='repair',base=root,cwd='docs',edits=[dict(path=filename,old='wrong',new=value)],check=['python3','verify.py']))
                self.assertTrue(result['checked'],result);self.assertEqual(result['cwd'],project)
    def test_two_same_named_checkers_do_not_guess_project(self):
        with tempfile.TemporaryDirectory() as root:
            for directory in ('a','b'):
                Path(root,directory).mkdir();Path(root,directory,'verify.py').write_text('print(1)')
            result=run_procedure(dict(kind='repair',base=root,edits=[],check=['python3','verify.py']))
            self.assertEqual(result['status'],'FileNotFoundError')

class ContractCompatibilityTests(unittest.TestCase):
    def test_type_names_are_normalized_without_coercing_answer_values(self):
        from solution.task_answers import shape_error,shape_details
        self.assertEqual(shape_error({'city':'Synthetic','types':['a'],'n':3},{'city':'str','types':'list[str]','n':{'type':'integer'}}),'')
        self.assertEqual(shape_error({'n':'3'},{'n':'int'}),'field_type')
        self.assertEqual(shape_details({'n':'3'},{'n':'int'})['field'],'n')
        self.assertEqual(shape_error({'types':[3]},{'types':'list[str]'}),'field_type')
