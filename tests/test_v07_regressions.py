"""Small synthetic reproductions of blocked delivery and task completion failures."""
import json
import unittest
from solution.geometry import Pos
from solution.models import Turn
from solution.movement import MoveIntent,schedule_moves
from solution.tasking import TaskManager,TaskPhase,safe_task_command
from solution.state import WorldState,LlmBudget
from solution.rules import DEFAULT_CONFIG
from solution.economy import DefenseBudget
from solution.logistics import LogisticsManager,Delivery
from tests.helpers import role,synthetic_turn
from tests.test_v05_regressions import developed
from tests.test_task_procedures import run_procedure

class V07RegressionTests(unittest.TestCase):
    def test_idle_role_yields_when_it_occupies_the_delivery_goal(self):
        raw=synthetic_turn();raw['mapInfo']={'width':7,'height':5,'zones':[]}
        raw['teamOur']['roles']=[role(1,'worker',1,2),role(2,'pioneer',3,2)]
        raw['teamEnemy']={'roles':[]};raw['robot']={'roles':[]}
        turn=Turn.from_raw(raw)
        moves=schedule_moves(turn,[MoveIntent(1,(Pos(3,2),),90),MoveIntent(2,(Pos(3,2),),0)])
        self.assertTrue(any(a.actor_id==2 for a in moves))

    def test_another_courier_does_not_block_owned_upgrade_delivery(self):
        raw=developed();raw['roundNo']=150
        raw['teamOur']['roles'][0]['backpack']=['StationUpgradeVoucher1']
        raw['teamOur']['roles'][0]['pos']={'x':12,'y':4}
        turn=Turn.from_raw(raw)
        manager=LogisticsManager(carrier_id=2,started=140,orders=[Delivery('WeaponUpgradeVoucher1',20,1)])
        result=manager.plan(turn,turn.team_our.unit(1),DefenseBudget(0,25,0,12),DEFAULT_CONFIG)
        self.assertIsNotNone(result.move)
        self.assertEqual(manager.carrier_id,2)

    def test_active_runtime_task_can_submit_at_estimated_deadline(self):
        raw=synthetic_turn(round_no=20)
        raw['lastCmdResult']='[exitCode:0]\n'+json.dumps({'procedure_result':{'ok':True,'checked':True,'answer':{'n':7}}})
        turn=Turn.from_raw(raw);state=WorldState();state.ingest(turn)
        manager=TaskManager(last_generation=state.generation,phase=TaskPhase.WAITING_COMMAND,
            pending_procedure=True,command_steps=2,accepted_round=10,timeout_rounds=10)
        plan=manager.plan(turn,state,LlmBudget(),DEFAULT_CONFIG,turn.team_our.unit(2))
        self.assertIsNotNone(plan.action)
        self.assertEqual(plan.action.action_type.value,'submitAnswer')

    def test_plain_python_solver_is_transported_without_shell_guessing(self):
        command=safe_task_command('import json\nprint(json.dumps({"value":sum(range(8))}))',workspace='.')
        self.assertTrue(command)

    def test_small_optional_repairs_do_not_consume_base_upgrade_fund(self):
        raw=developed();raw['roundNo']=160;raw['teamOur']['goldNum']=80
        raw['teamOur']['roles'][0]['pos']={'x':12,'y':5}
        next(u for u in raw['teamOur']['roles'] if u['roleType']=='rocket')['level']=2
        raw['teamOur']['roles'].append(role(60,'wall',8,10,health=600,level=1))
        raw['mapInfo']['zones']=[{'neutralType':'weaponShop','pos':{'x':13,'y':5}}]
        raw['weaponShopList']=[{'name':'StationUpgradeVoucher1','price':100},
            {'name':'WallUpgradeVoucher1','price':20},{'name':'WallFixer','price':10}]
        turn=Turn.from_raw(raw)
        result=LogisticsManager().plan(turn,turn.team_our.unit(1),DefenseBudget(0,25,55,12),DEFAULT_CONFIG)
        self.assertIsNone(result.action)

class V07OperatingTests(unittest.TestCase):
    def test_python_solver_submits_fresh_output_without_synthesis_round(self):
        import tempfile,subprocess,shlex,sys,random
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            values=random.Random().sample(range(1000),7)
            work=Path(root,'randomized','work');work.mkdir(parents=True)
            (work/'numbers.json').write_text(json.dumps(values))
            raw=synthetic_turn(round_no=12)
            raw['llmResp']=json.dumps({'python':'import json\nfrom pathlib import Path\nvalues=json.loads(Path("numbers.json").read_text())\nprint(json.dumps({"total":sum(values)}))','submit_result':True})
            turn=Turn.from_raw(raw);state=WorldState();state.ingest(turn)
            manager=TaskManager(last_generation=state.generation,phase=TaskPhase.WAITING_LLM,command_steps=1)
            manager.context.workspace='randomized/work';manager.context.resolved=True
            plan=manager.plan(turn,state,LlmBudget(),DEFAULT_CONFIG,turn.team_our.unit(2))
            self.assertTrue(plan.execute_command)
            source=shlex.split(plan.execute_command)[2].replace(';exec(', ';options["base"]='+repr(root)+';exec(',1)
            process=subprocess.run([sys.executable,'-c',source],capture_output=True,text=True,timeout=12)
            self.assertEqual(process.returncode,0,process.stderr)
            raw.update(roundNo=13,llmResp='',lastCmdResult='[exitCode:0]\n'+process.stdout)
            turn=Turn.from_raw(raw)
            submit=manager.plan(turn,state,LlmBudget(),DEFAULT_CONFIG,turn.team_our.unit(2))
            self.assertEqual(json.loads(submit.action.task_answer),{'total':sum(values)})
            self.assertEqual(manager.diagnostic,'procedure_computed')
            self.assertFalse(submit.prompt)

    def test_failed_or_non_json_computation_is_not_submitted(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            for code in ('raise RuntimeError("synthetic")','print("not a final JSON answer")'):
                result=run_procedure({'kind':'python','base':root,'code':code,'submit_result':True})
                self.assertFalse(result['ok']);self.assertNotIn('answer',result)

    def test_repair_accepts_workspace_relative_path_and_runs_real_checker(self):
        import tempfile,uuid
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            work=Path(root,'nested');work.mkdir();proof=uuid.uuid4().hex
            (work/'value.txt').write_text('broken')
            result=run_procedure({'kind':'repair','base':root,'cwd':'nested',
                'edits':[{'path':'value.txt','old':'broken','new':'fixed'}],
                'check':['python3','-c','import json;from pathlib import Path;assert Path("value.txt").read_text()=="fixed";print(json.dumps({"proof":'+repr(proof)+'}))']})
            self.assertTrue(result['checked']);self.assertEqual(result['answer'],{'proof':proof})

    def test_saved_program_survives_failure_and_resets_between_tasks(self):
        manager=TaskManager();manager.context.remember({'python':'print("synthetic computation")'})
        manager.context.ingest({'procedure_result':{'ok':False}},'check failed',True)
        self.assertIn('synthetic computation',manager.context.prompt())
        manager.reset(1);self.assertFalse(manager.context.programs)

    def test_exact_base_price_can_fund_the_day_two_milestone(self):
        raw=developed();raw['roundNo']=160;raw['teamOur']['goldNum']=100
        raw['teamOur']['roles'][0]['pos']={'x':12,'y':5}
        next(u for u in raw['teamOur']['roles'] if u['roleType']=='rocket')['level']=2
        raw['mapInfo']['zones']=[{'neutralType':'weaponShop','pos':{'x':13,'y':5}}]
        raw['weaponShopList']=[{'name':'StationUpgradeVoucher1','price':100},{'name':'WeaponUpgradeVoucher1','price':100}]
        turn=Turn.from_raw(raw)
        result=LogisticsManager().plan(turn,turn.team_our.unit(1),DefenseBudget(0,25,75,12),DEFAULT_CONFIG)
        self.assertEqual(result.action.name,'StationUpgradeVoucher1')

    def test_idle_pioneer_stages_near_shop_without_displacing_active_task(self):
        from solution.engine import AgentEngine
        raw=developed();raw['roundNo']=150
        for u in raw['teamOur']['roles']:
            if u['roleType'] in ('station','rocket','railgun'):u['level']=2
        raw['mapInfo']['zones']=[{'neutralType':'weaponShop','pos':{'x':13,'y':5}}]
        raw['weaponShopList']=[{'name':'WeaponUpgradeVoucher2','price':150}]
        result=AgentEngine().decide(raw)['roleCommandMap']
        self.assertEqual(result['3']['action'],'move')
        raw['phaseTask']='synthetic active task'
        raw['teamOur']['roles'][2]['pos']={'x':10,'y':4}
        result=AgentEngine().decide(raw)['roleCommandMap']
        self.assertNotIn('3',result)
