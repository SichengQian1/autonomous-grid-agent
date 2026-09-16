"""Synthetic incident regressions; no match payloads, task answers or identities."""
import json
import unittest
from solution.geometry import Pos
from solution.models import Turn
from solution.movement import MoveIntent, schedule_moves
from solution.tasking import TaskManager,TaskPhase
from solution.state import WorldState,LlmBudget
from solution.rules import DEFAULT_CONFIG
from solution.economy import EconomyManager,DefenseBudget
from solution.logistics import LogisticsManager
from tests.helpers import role,synthetic_turn
from tests.test_operations_v04 import campus
from tests.test_v05_regressions import developed

class V06Regressions(unittest.TestCase):
    def test_distant_future_route_does_not_reserve_delivery_cell_now(self):
        raw=campus();raw['teamOur']['roles']=[role(1,'worker',1,3),role(2,'pioneer',7,3)]
        turn=Turn.from_raw(raw)
        moves=schedule_moves(turn,[MoveIntent(1,(Pos(2,3),),90),MoveIntent(2,(Pos(2,3),),120)])
        self.assertTrue(any(a.actor_id==1 and a.targets==(Pos(2,3),) for a in moves))

    def test_task_document_survives_a_later_command_error(self):
        raw=synthetic_turn(round_no=10);state=WorldState();state.ingest(Turn.from_raw(raw))
        manager=TaskManager(last_generation=state.generation,phase=TaskPhase.WAITING_COMMAND,command_steps=1,pending_procedure=True)
        raw['lastCmdResult']='[exitCode:0]\n'+json.dumps({'procedure_result':{'documents':[{'path':'random/task.md','text':'Required field: computed_total'}],'workspace':'random','files':['random/check.py']}})
        turn=Turn.from_raw(raw);manager.plan(turn,state,LlmBudget(),DEFAULT_CONFIG,turn.team_our.unit(2))
        raw['roundNo']=13;raw['lastCmdResult']='[exitCode:1]\nFileNotFoundError: synthetic'
        manager.phase=TaskPhase.WAITING_COMMAND;manager.command_steps=2
        turn=Turn.from_raw(raw);result=manager.plan(turn,state,LlmBudget(),DEFAULT_CONFIG,turn.team_our.unit(2))
        self.assertIn('computed_total',result.prompt)
        self.assertIn('FileNotFoundError',result.prompt)

    def test_failed_procedure_does_not_allow_unverified_answer(self):
        raw=synthetic_turn(round_no=13);state=WorldState();state.ingest(Turn.from_raw(raw))
        manager=TaskManager(last_generation=state.generation,phase=TaskPhase.WAITING_COMMAND,command_steps=2,pending_procedure=True)
        raw['lastCmdResult']='[exitCode:0]\n'+json.dumps({'procedure_result':{'ok':False,'status':'check_failed'}})
        raw['llmResp']=json.dumps({'answer':{'result':123}})
        turn=Turn.from_raw(raw);result=manager.plan(turn,state,LlmBudget(),DEFAULT_CONFIG,turn.team_our.unit(2))
        self.assertIsNone(result.action)

    def test_nine_ores_are_sold_instead_of_chasing_a_remote_replacement(self):
        raw=developed();raw['roundNo']=275
        raw['teamOur']['roles'][0].update(pos={'x':5,'y':4},backpack=['copper']*9)
        raw['mapInfo']['zones']=[{'neutralType':'copper','pos':{'x':0,'y':16}}, {'neutralType':'vendor','pos':{'x':6,'y':4}}]
        raw['vendorShopList']=[{'name':'copper','price':5}]
        # A slightly farther vendor still beats a long detour for one extra ore.
        raw['mapInfo']['zones'][1]['pos']={'x':8,'y':4}
        turn=Turn.from_raw(raw);state=WorldState();state.ingest(turn)
        manager=EconomyManager();p=manager.plan(turn,turn.team_our.unit(1),state,DEFAULT_CONFIG,DefenseBudget(0,25,0,12))
        self.assertTrue(manager.activity[1].startswith('sell'))

    def test_day_two_front_wall_upgrade_is_planned_before_it_is_critical(self):
        raw=developed();raw['roundNo']=160;raw['teamOur']['goldNum']=100
        raw['teamOur']['roles'][0]['pos']={'x':12,'y':5}
        raw['teamOur']['roles'][3]['level']=2
        next(u for u in raw['teamOur']['roles'] if u['roleType']=='rocket')['level']=2
        raw['teamOur']['roles'].append(role(60,'wall',8,10,health=900,level=1))
        raw['mapInfo']['zones']=[{'neutralType':'weaponShop','pos':{'x':13,'y':5}}]
        raw['weaponShopList']=[{'name':'WallUpgradeVoucher1','price':20},{'name':'WeaponUpgradeVoucher1','price':100}]
        turn=Turn.from_raw(raw)
        result=LogisticsManager().plan(turn,turn.team_our.unit(1),DefenseBudget(0,25,75,12),DEFAULT_CONFIG)
        self.assertIsNotNone(result.action)
        self.assertEqual(result.action.name,'WallUpgradeVoucher1')

class TaskWorkspaceIntegration(unittest.TestCase):
    def test_discover_fail_repair_check_and_submit_in_random_workspace(self):
        import shlex
        import subprocess
        import sys
        import tempfile
        import uuid
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            relative='tasks/'+uuid.uuid4().hex
            work=Path(root,relative);work.mkdir(parents=True)
            proof=uuid.uuid4().hex
            (work/'task.md').write_text('Repair add and run check.py. Submit its proof field.')
            (work/'calc.py').write_text('def add(a,b): return a-b\n')
            (work/'check.py').write_text('import json\nfrom calc import add\nassert add(4,7)==11\nprint(json.dumps({"proof":'+repr(proof)+'}))\n')
            raw=synthetic_turn(round_no=10);raw['phaseTask']='Read task.md and solve.'
            state=WorldState();state.ingest(Turn.from_raw(raw));manager=TaskManager();budget=LlmBudget()
            def step(round_no, response='', output=''):
                raw.update(roundNo=round_no,llmResp=response,lastCmdResult=output)
                turn=Turn.from_raw(raw);budget.refresh(turn)
                return manager.plan(turn,state,budget,DEFAULT_CONFIG,turn.team_our.unit(2))
            def execute(plan):
                self.assertTrue(plan.execute_command)
                source=shlex.split(plan.execute_command)[2]
                source=source.replace(';exec(', ';options["base"]='+repr(root)+';exec(',1)
                # Avoid cached bytecode across same-size repairs on sub-second tests.
                import os
                env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
                result=subprocess.run([sys.executable,'-c',source],env=env,capture_output=True,text=True,timeout=12)
                self.assertEqual(result.returncode,0,result.stderr)
                return '[exitCode:0]\n'+result.stdout
            probe=execute(step(10))
            prompt=step(11,output=probe)
            self.assertEqual(manager.context.workspace,relative)
            self.assertIn('Repair add',prompt.prompt)
            failed=execute(step(12,json.dumps({'procedure':{'kind':'repair','edits':[],'check':['python3','check.py']}})))
            rejected=step(13,json.dumps({'answer':{'proof':'unsupported'}}),failed)
            self.assertIsNone(rejected.action)
            self.assertIn('Repair add',rejected.prompt)
            repaired=execute(step(14,json.dumps({'procedure':{'kind':'repair',
                'edits':[{'path':relative+'/calc.py','old':'return a-b','new':'return a+b'}],
                'check':['python3','check.py']}})))
            submit=step(15,output=repaired)
            self.assertEqual(json.loads(submit.action.task_answer),{'proof':proof})
            manager.reset(state.generation+1)
            self.assertFalse(manager.context.documents)
            self.assertFalse(manager.context.resolved)

    def test_relative_multiline_script_uses_discovered_workspace(self):
        import tempfile
        import shlex
        import subprocess
        import sys
        from pathlib import Path
        from solution.tasking import safe_task_command
        with tempfile.TemporaryDirectory() as root:
            work=Path(root,'nested');work.mkdir();(work/'input.txt').write_text('17 31')
            command=safe_task_command("python3 - <<'PY'\nfrom pathlib import Path\nprint(sum(map(int,Path('input.txt').read_text().split())))\nPY", 'nested')
            source=shlex.split(command)[2].replace(';exec(', ';options["base"]='+repr(root)+';exec(',1)
            result=subprocess.run([sys.executable,'-c',source],capture_output=True,text=True,timeout=12)
            data=json.loads(result.stdout)['procedure_result']
            self.assertTrue(data['ok']);self.assertEqual(data['output'].strip(),'48')

    def test_malformed_procedure_envelope_does_not_crash(self):
        from solution.task_context import TaskContext
        context=TaskContext()
        context.ingest({'procedure_result':[]},'malformed',False)
        self.assertTrue(context.failed_execution)

class SchedulingIntegration(unittest.TestCase):
    def test_task_acceptance_includes_obstacle_detour_and_return_margin(self):
        from solution.travel import TravelBudget
        raw=developed();raw['roundNo']=44
        raw['teamOur']['roles'][2]['pos']={'x':17,'y':10}
        raw['teamOur']['roles'] += [role(100+y,'wall',10,y) for y in range(17)]
        raw['teamOur']['playerTasks']=[{'taskType':'synthetic','taskPosition':{'x':18,'y':10},'isValid':True,
            'timeoutRounds':10,'goldReward':80,'scoreReward':80,'coldDownRounds':0}]
        turn=Turn.from_raw(raw);pioneer=turn.team_our.unit(3)
        budget=TravelBudget.for_role(turn,pioneer,DEFAULT_CONFIG)
        self.assertGreater(budget.cost()+budget.margin+7,turn.rounds_until_night)
        self.assertIsNone(TaskManager._choose_task(turn,pioneer,DEFAULT_CONFIG))

    def test_idle_controller_uses_owned_upgrade_but_firing_takes_priority(self):
        from solution.combat import assign_controllers
        from solution.engine import AgentEngine
        raw=developed();raw['roundNo']=80
        turn=Turn.from_raw(raw)
        assignments=assign_controllers(turn,tuple(u for u in turn.team_our.roles if u.is_weapon))
        by_id={r['id']:r for r in raw['teamOur']['roles']}
        for a in assignments: by_id[a.controller.unit_id]['pos']=a.control_pos.to_raw()
        a=next(a for a in assignments if a.weapon.role_type=='rocket')
        by_id[a.controller.unit_id]['backpack']=['WeaponUpgradeVoucher1']
        robot=role(70,'smallRobot',a.weapon.pos.x-2,a.weapon.pos.y,health=50,attack_range=1)
        robot['targetTeam']='challenger';raw['robot']['roles']=[robot]
        by_id[a.weapon.unit_id]['cooldown']=3
        result=AgentEngine().decide(raw)['roleCommandMap']
        self.assertEqual(result[str(a.controller.unit_id)]['action'],'use')
        self.assertNotIn(str(a.weapon.unit_id),result)
        by_id[a.weapon.unit_id]['cooldown']=0
        result=AgentEngine().decide(raw)['roleCommandMap']
        self.assertEqual(result[str(a.weapon.unit_id)]['action'],'attack')
        self.assertNotIn(str(a.controller.unit_id),result)

    def test_stock_is_converted_to_cash_before_recall(self):
        raw=developed();raw['roundNo']=300
        raw['teamOur']['roles'][0].update(pos={'x':5,'y':4},backpack=['copper']*9)
        raw['mapInfo']['zones']=[{'neutralType':'copper','pos':{'x':0,'y':16}}, {'neutralType':'vendor','pos':{'x':8,'y':4}}]
        raw['vendorShopList']=[{'name':'copper','price':5}]
        manager=EconomyManager();state=WorldState()
        for r in range(300,310):
            raw['roundNo']=r;turn=Turn.from_raw(raw);state.ingest(turn)
            plan=manager.plan(turn,turn.team_our.unit(1),state,DEFAULT_CONFIG,DefenseBudget(0,25,0,12))
            if plan.action and plan.action.action_type.value=='sell':
                raw['teamOur']['goldNum']+=plan.action.quantity*5
                break
            if plan.move:
                moves=schedule_moves(turn,[plan.move])
                if moves:raw['teamOur']['roles'][0]['pos']=moves[0].targets[0].to_raw()
        self.assertEqual(raw['teamOur']['goldNum'],45)
        self.assertLess(r,310)

    def test_second_day_front_upgrade_quota_is_normalized_on_both_sides(self):
        from solution.defense import build_defense_layout
        from solution.logistics import _maintenance_options
        for side in ('challenger','defender'):
            raw=campus(side);raw['roundNo']=160
            layout=build_defense_layout(Turn.from_raw(raw))
            for i,p in enumerate(layout.wall_sites):raw['teamOur']['roles'].append(role(100+i,'wall',p.x,p.y,health=1000,level=1))
            turn=Turn.from_raw(raw)
            upgrades=[u for item,u,value in _maintenance_options(turn) if item=='WallUpgradeVoucher1']
            self.assertEqual(len(upgrades),3)
            front=max(layout.frame.normalize(p).x for p in turn.team_our.station().footprint())+2
            self.assertTrue(all(layout.frame.normalize(u.pos).x==front for u in upgrades))
