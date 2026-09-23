"""Synthetic reproductions of operational failures; no private match content."""
import unittest
import json
import shlex
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch
from solution.defense import build_defense_layout
from solution.economy import EconomyManager, DefenseBudget
from solution.engine import AgentEngine
from solution.logistics import Delivery, LogisticsManager
from solution.models import Turn
from solution.rules import DEFAULT_CONFIG
from solution.state import WorldState
from solution.tasking import safe_task_command, TaskManager, TaskPhase, sandbox_category, parse_sandbox_result
from solution.state import LlmBudget
from solution.telemetry import Telemetry, decode_event
from tests.helpers import role, synthetic_turn
from tests.test_operations_v04 import campus


def developed():
    raw=campus(); raw['mapInfo']['width']=30
    raw['teamOur']['goldNum']=0
    layout=build_defense_layout(Turn.from_raw(raw))
    for i,(kind,p) in enumerate(zip(('rocket','railgun','rocket'),layout.weapon_sites[:3])):
        raw['teamOur']['roles'].append(role(20+i,kind,p.x,p.y,level=1,health=1000,attack_range=10))
    return raw


class V05RegressionTests(unittest.TestCase):
    def test_local_ore_is_preferred_to_enemy_side_windfall(self):
        raw=developed()
        raw['teamOur']['roles'][0]['pos']={'x':4,'y':4}
        raw['mapInfo']['zones']=[{'neutralType':'iron','pos':{'x':3,'y':4}},
                                {'neutralType':'copper','pos':{'x':23,'y':4}},
                                {'neutralType':'vendor','pos':{'x':14,'y':4}}]
        raw['vendorShopList']=[{'name':'iron','price':3},{'name':'copper','price':100}]
        for side in ('challenger','defender'):
            if side == 'defender':
                raw['teamOur']['type']=side
                for obj in raw['teamOur']['roles']+raw['mapInfo']['zones']:
                    obj['pos']={'x':29-obj['pos']['x'],'y':17-obj['pos']['y']}
                    if obj.get('roleType')=='station':
                        obj['pos']['x']-=1; obj['pos']['y']+=1
            turn=Turn.from_raw(raw); state=WorldState(); state.ingest(turn)
            result=EconomyManager().plan(turn,turn.team_our.unit(1),state,DEFAULT_CONFIG,DefenseBudget(0,25,0,10))
            self.assertIsNotNone(result.action)
            expected={'x':3,'y':4} if side=='challenger' else {'x':26,'y':13}
            self.assertEqual(result.action.targets[0].to_raw(),expected)

    def test_distant_recall_does_not_stop_nearby_wall_builder(self):
        raw=developed(); raw['roundNo']=52
        raw['teamOur']['roles'][0]['backpack']=['stone']*4
        raw['teamOur']['roles'][0]['pos']={'x':7,'y':10}
        raw['teamOur']['roles'][1]['pos']={'x':28,'y':3}
        engine=AgentEngine(); engine.state.ingest(Turn.from_raw(raw))
        engine.planner.last_generation=engine.state.generation; engine.planner.engineer_id=1
        result=engine.decide(raw)['roleCommandMap']
        self.assertEqual(result['1']['action'],'build')
        self.assertEqual(result['2']['action'],'move')

    def test_engineer_preserves_carried_repair_for_night(self):
        raw=developed();raw['roundNo']=261
        raw['teamOur']['roles'][0]['backpack']=['WallFixer']
        raw['teamOur']['roles'][0]['pos']={'x':7,'y':10}
        raw['teamOur']['roles'].append(role(40,'wall',8,10,health=50,level=1))
        engine=AgentEngine();result=engine.decide(raw)['roleCommandMap']
        self.assertFalse(any(c.get('action')=='use' and c.get('name')=='WallFixer' for c in result.values()))

    def test_local_cd_and_multiline_solver_are_accepted(self):
        self.assertTrue(safe_task_command("cd /tmp/selfEvolutionTask && python3 check.py"))
        command=safe_task_command("python3 - <<'PY'\nprint(7)\nPY")
        self.assertTrue(command)
        self.assertNotIn('\n',command)
        self.assertTrue(safe_task_command("python3 -c 'import json\nprint(json.dumps(7))'"))

    def test_multiline_transport_executes_and_result_reaches_submission(self):
        with tempfile.TemporaryDirectory() as root:
            token = uuid.uuid4().hex
            Path(root, 'input.txt').write_text(token)
            script = "cd .\npython3 - <<'PY'\nimport json\nfrom pathlib import Path\nprint(json.dumps({'proof':Path('input.txt').read_text()}))\nPY"
            raw = synthetic_turn(round_no=14)
            raw['llmResp'] = json.dumps({'script':script})
            turn = Turn.from_raw(raw); state = WorldState(); state.ingest(turn)
            manager = TaskManager(last_generation=state.generation, phase=TaskPhase.WAITING_LLM)
            plan = manager.plan(turn,state,LlmBudget(),DEFAULT_CONFIG,turn.team_our.unit(2))
            self.assertTrue(plan.execute_command)
            self.assertNotIn('\n',plan.execute_command)
            # The harness relocates only the sandbox root. Execute the actual wire payload.
            source = shlex.split(plan.execute_command)[2]
            source = source.replace(';exec(', ';options["base"]='+repr(root)+';exec(', 1)
            process = subprocess.run([sys.executable,'-c',source], capture_output=True,text=True,timeout=12)
            self.assertEqual(process.returncode,0,process.stderr)
            envelope = json.loads(process.stdout)['procedure_result']
            self.assertTrue(envelope['ok'])
            self.assertEqual(json.loads(envelope['output']),{'proof':token})
            raw['roundNo']=15; raw['llmResp']=''; raw['lastCmdResult']='[exitCode:0]\n'+process.stdout
            turn=Turn.from_raw(raw)
            synthesis=manager.plan(turn,state,LlmBudget(),DEFAULT_CONFIG,turn.team_our.unit(2))
            self.assertIn(token,synthesis.prompt)
            self.assertIsNone(synthesis.action)  # A successful script alone is not a verified answer.
            raw['roundNo']=17; raw['llmResp']=json.dumps({'answer':json.loads(envelope['output'])})
            turn=Turn.from_raw(raw)
            submit=manager.plan(turn,state,LlmBudget(),DEFAULT_CONFIG,turn.team_our.unit(2))
            self.assertEqual(json.loads(submit.action.task_answer),{'proof':token})

    def test_command_failure_category_contains_no_output(self):
        result=parse_sandbox_result('[exitCode:1]\nFileNotFoundError: synthetic-private-value')
        self.assertEqual(sandbox_category(result),'missing_file')

    def test_missing_task_feedback_is_not_reported_as_success(self):
        raw=synthetic_turn(round_no=20); raw['phaseTask']=''; raw['lastRoundRoleActionResults']={}
        turn=Turn.from_raw(raw); state=WorldState(); state.ingest(turn)
        manager=TaskManager(last_generation=state.generation,phase=TaskPhase.WAITING_RESULT,
                            active_seen=True,submit_attempts=1)
        manager.plan(turn,state,LlmBudget(),DEFAULT_CONFIG,turn.team_our.unit(2))
        self.assertEqual(manager.completed,0)
        self.assertEqual(manager.failed,1)

    def test_mine_change_is_logged_between_day_boundaries(self):
        telemetry=Telemetry(100000,10000); records=[]; raw=synthetic_turn(round_no=12)
        with patch('solution.telemetry.LOGGER.info',side_effect=records.append):
            telemetry.record_turn(Turn.from_raw(raw),{'roleCommandMap':{}},elapsed_ms=0,dropped_actions=0)
            raw['roundNo']=13; raw['mapInfo']['zones'].append({'neutralType':'iron','pos':{'x':1,'y':1}})
            telemetry.record_turn(Turn.from_raw(raw),{'roleCommandMap':{}},elapsed_ms=0,dropped_actions=0)
        self.assertIn(['iron',[1,1]],decode_event(records[-1])['zones'])

    def test_early_cheap_repairs_do_not_spend_first_rocket_fund(self):
        raw=developed(); raw['roundNo']=111; raw['teamOur']['goldNum']=90
        raw['teamOur']['roles'][0]['pos']={'x':12,'y':5}
        raw['teamOur']['roles'].append(role(40,'wall',8,10,health=500,level=1))
        raw['mapInfo']['zones']=[{'neutralType':'weaponShop','pos':{'x':13,'y':5}}]
        raw['weaponShopList']=[{'name':'WallFixer','price':10},{'name':'WallUpgradeVoucher1','price':20},
                               {'name':'WeaponUpgradeVoucher1','price':100}]
        turn=Turn.from_raw(raw)
        result=LogisticsManager(weapon_buyer_id=1).plan(turn,turn.team_our.unit(1),DefenseBudget(0,25,65,12),DEFAULT_CONFIG)
        self.assertIsNone(result.action)

        raw['teamOur']['goldNum']=100
        turn=Turn.from_raw(raw)
        funded=LogisticsManager(weapon_buyer_id=1).plan(turn,turn.team_our.unit(1),DefenseBudget(0,25,75,12),DEFAULT_CONFIG)
        self.assertEqual(funded.action.name,'WeaponUpgradeVoucher1')

        raw['teamOur']['goldNum']=90
        raw['teamOur']['roles'][-1]['health']=50
        turn=Turn.from_raw(raw)
        urgent=LogisticsManager(weapon_buyer_id=1).plan(turn,turn.team_our.unit(1),DefenseBudget(0,25,65,12),DEFAULT_CONFIG)
        self.assertIsNone(urgent.action)  # Gun operator no longer owns wall procurement.
