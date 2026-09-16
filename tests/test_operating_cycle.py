"""Integration of task income with procurement; prescribed replies are not an LLM benchmark."""
from __future__ import annotations

import json
import unittest

from solution.engine import AgentEngine
from solution.models import Turn
from solution.combat import assign_controllers
from tests.test_opening_regression import RestrictedOpeningWorld


class IncomeWorld(RestrictedOpeningWorld):
    def __init__(self,side):
        super().__init__(side)
        # Keep interaction areas distinct: acceptTask has no target selector.
        points=[{'x':10,'y':15},{'x':13,'y':13}]
        if side=='defender': points=[{'x':23-p['x'],'y':19-p['y']} for p in points]
        self.points=points
        self.zones.extend({'neutralType':side+'TaskPoint','pos':p} for p in points)
        self.stock=[2,2]; self.ready=[1,1]; self.active=None
        self.answer=0; self.command_result=''; self.llm_result=''; self.task_income=0
        self.completed=0; self.purchases=[]; self.upgrades=[]

    def request(self,r):
        raw=super().request(r)
        raw['teamOur']['playerTasks']=[dict(taskType='synthetic',taskPosition=p,isValid=self.stock[i]>0 and r>=self.ready[i],
                                           coldDownRounds=max(0,self.ready[i]-r),scoreReward=20,goldReward=80,timeoutRounds=10)
                                       for i,p in enumerate(self.points)]
        raw['phaseTask']='Read synthetic_task.md and return its computed value.' if self.active is not None else ''
        raw['llmResp']=self.llm_result; raw['lastCmdResult']=self.command_result
        self.llm_result=self.command_result=''
        return raw

    def apply(self,response):
        super().apply(response)
        for actor,cmd in response['roleCommandMap'].items():
            if cmd['action']=='acceptTask':
                pioneer=next(u for u in self.roles if u['roleType']=='pioneer')
                index=next(i for i,p in enumerate(self.points) if max(abs(p[k]-pioneer['pos'][k]) for k in ('x','y'))<=1)
                if self.stock[index]<=0 or self.round_no<self.ready[index]:
                    raise AssertionError('accepted an unavailable synthetic task')
                self.active=index; self.answer=self.round_no*17+index
            elif cmd['action']=='submitAnswer':
                if self.active is None or json.loads(cmd['taskAnswer'])!={'value':self.answer}:
                    raise AssertionError('incorrect dynamic synthetic answer')
                self.gold+=80; self.task_income+=80; self.completed+=1
                self.stock[self.active]-=1; self.ready[self.active]=self.round_no+30; self.active=None
            elif cmd['action']=='buy': self.purchases.append((self.round_no,cmd['name'],cmd['num']))
            elif cmd['action']=='use' and 'UpgradeVoucher' in cmd['name']:
                self.upgrades.append((self.round_no,cmd['name']))
        if response.get('executeCmd') and self.active is not None:
            self.command_result='[exitCode:0]\n'+json.dumps({'documents':[{'text':'synthetic dynamic task input'}]})
        if response.get('prompt') and self.active is not None:
            self.llm_result=json.dumps({'answer':{'value':self.answer}})


class OperatingCycleTests(unittest.TestCase):
    def test_delayed_news_request_does_not_consume_a_task_answer(self):
        world=IncomeWorld('challenger'); engine=AgentEngine()
        raw=world.request(1); raw['phaseTask']='Read synthetic_task.md and solve it.'
        engine.decide(raw)
        engine.planner.treasure_prompt_pending=True
        raw=world.request(2); raw['phaseTask']='Read synthetic_task.md and solve it.'
        raw['llmResp']=json.dumps({'answer':{'value':917}})
        response=engine.decide(raw)
        pioneer=next(u for u in raw['teamOur']['roles'] if u['roleType']=='pioneer')
        self.assertEqual(response['roleCommandMap'][str(pioneer['id'])]['action'],'submitAnswer')

    def test_cleared_night_keeps_active_pioneer_task_ahead_of_shopping(self):
        world=IncomeWorld('challenger'); raw=world.request(90)
        raw['robot']={'roles':[]}
        raw['phaseTask']='Read synthetic_task.md and solve it.'
        pioneer=next(u for u in raw['teamOur']['roles'] if u['roleType']=='pioneer')
        pioneer['backpack']=['StationUpgradeVoucher1']
        pioneer['pos']={'x':4,'y':12}
        raw['teamOur']['roles']=[u for u in raw['teamOur']['roles'] if u['roleType']!='worker']
        response=AgentEngine().decide(raw)
        self.assertTrue(response.get('executeCmd'))
        self.assertNotIn(str(pioneer['id']),response['roleCommandMap'])

    def test_task_income_becomes_weapon_upgrade_before_night_on_both_sides(self):
        for side in ('challenger','defender'):
            with self.subTest(side=side):
                world=IncomeWorld(side); engine=AgentEngine()
                for r in range(1,71):
                    response=engine.decide(world.request(r)); world.apply(response)
                    self.assertFalse(any(value is False for value in world.feedback.values()))
                    self.assertGreaterEqual(world.gold,0)
                self.assertGreaterEqual(world.completed,2)
                self.assertGreaterEqual(world.task_income,160)
                self.assertTrue(world.upgrades)
                self.assertTrue(any(u['roleType']=='rocket' and u['level']>=2 for u in world.roles))
                turn=Turn.from_raw(world.request(71))
                assignments=assign_controllers(turn,tuple(u for u in turn.team_our.roles if u.is_weapon))
                self.assertEqual(len(assignments),3)
                self.assertTrue(all(a.controller.pos.distance_to(a.weapon.pos)<=1 for a in assignments))
