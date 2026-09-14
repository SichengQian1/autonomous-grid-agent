from __future__ import annotations

import json
import time
import unittest
from unittest.mock import patch

from solution.actions import ActionType
from solution.engine import AgentEngine
from solution.geometry import Pos
from solution.models import Turn
from solution.planning import PlanningContext
from solution.rules import DEFAULT_CONFIG
from solution.state import LlmBudget, WorldState
from solution.tasks import TaskManager, Treasure
from tests.scenarios import arena, robot


class AuditRegressionTests(unittest.TestCase):
    def test_commit_time_rejection_cancels_all_releases(self):
        raw = arena(80, armed=True)
        raw['robot']['roles'] = [robot(100, 12, 15, 20)]
        original_add = PlanningContext.add

        def reject_attacks(ctx, action):
            return False if action.action_type == ActionType.ATTACK else original_add(ctx, action)

        with patch.object(PlanningContext, 'add', reject_attacks):
            result = AgentEngine().decide(raw)
        # All three are already at their defensive stands. A failed commit must
        # leave them there rather than allowing economy actions or departures.
        self.assertEqual(result['roleCommandMap'], {})

    def test_rejected_cleanup_attack_cannot_authorize_supply_runs(self):
        raw = arena(80, armed=True)
        raw['robot']['roles'] = [robot(100, 12, 15, 20)]
        engine = AgentEngine()
        first = engine.decide(raw)
        attack = next(k for k, a in first['roleCommandMap'].items() if a['action'] == 'attack')
        raw['roundNo'] = 81
        raw['lastRoundRoleActionResults'] = {attack: False}
        result = engine.decide(raw)
        # The blocked rocket cannot justify a departure. The ready railgun must
        # remain staffed and provide the actual 20 damage needed for cleanup.
        self.assertNotIn(attack, result['roleCommandMap'])
        self.assertEqual(result['roleCommandMap']['11']['action'], 'attack')
        self.assertEqual(result['roleCommandMap']['11']['controllerId'], '1')

    def test_survivor_uses_ready_weapon_instead_of_cooling_higher_level(self):
        raw = arena(80, armed=True)
        raw['teamOur']['roles'] = [u for u in raw['teamOur']['roles'] if u['id'] not in {2, 3, 12}]
        for unit in raw['teamOur']['roles']:
            if unit['id'] == 13:
                unit['level'], unit['cooldown'] = 3, 3
            if unit['id'] == 11:
                unit['level'], unit['attackPower'] = 1, 10
        raw['robot']['roles'] = [robot(100, 10, 14, 40)]
        result = AgentEngine().decide(raw)
        self.assertEqual(result['roleCommandMap']['11']['action'], 'attack')
        self.assertEqual(result['roleCommandMap']['11']['controllerId'], '1')

    def test_closed_high_price_mine_is_not_collected(self):
        raw = arena(131, armed=True)
        raw['teamOur']['goldNum'] = 0
        raw['teamOur']['roles'][0]['pos'] = {'x': 7, 'y': 16}
        raw['worldNews'] = {'officialNews': 'Synthetic notice: iron mining is suspended today and tomorrow.'}
        raw['vendorShopList'] = [{'name': 'iron', 'price': 99}, {'name': 'stone', 'price': 1}]
        result = AgentEngine().decide(raw)
        self.assertNotEqual(result['roleCommandMap'].get('1'),
                            {'action': 'collect', 'targetPos': [{'x': 8, 'y': 17}]})

    def test_night_treasure_is_summoned_when_clear_and_ready(self):
        raw = arena(79, armed=True)
        raw['teamOur']['goldNum'] = 0
        raw['teamOur']['roles'][2]['backpack'] = ['SyntheticToken']
        engine = AgentEngine()
        engine.decide(raw)
        engine.planner.tasks.treasure = Treasure(Pos(3, 18), ('SyntheticToken',), 80, 85)
        raw['roundNo'] = 80
        self.assertEqual(engine.decide(raw)['roleCommandMap']['3']['action'], 'summonTreasure')

    def test_night_treasure_still_obeys_safety_time_and_inventory(self):
        for variant in ('spawn', 'threat', 'early', 'expired', 'missing'):
            with self.subTest(variant=variant):
                raw = arena(70 if variant == 'spawn' else 79, armed=True)
                raw['teamOur']['goldNum'] = 0
                raw['teamOur']['roles'][2]['backpack'] = [] if variant == 'missing' else ['SyntheticToken']
                engine = AgentEngine()
                engine.decide(raw)
                engine.planner.tasks.treasure = Treasure(Pos(3, 18), ('SyntheticToken',),
                    81 if variant == 'early' else 71, 79 if variant == 'expired' else 85)
                raw['roundNo'] += 1
                if variant == 'threat':
                    raw['robot']['roles'] = [robot(100, 6, 16, 10000)]
                actions = engine.decide(raw)['roleCommandMap'].values()
                self.assertNotIn('summonTreasure', [a['action'] for a in actions])

    def test_treasure_reply_across_dusk_is_preserved_for_safe_night(self):
        raw = arena(70, armed=True)
        raw['teamOur']['goldNum'] = 0
        raw['teamOur']['roles'][2]['backpack'] = ['SyntheticToken']
        evidence = 'Synthetic clue for a nighttime treasure window.'
        raw['worldNews'] = {'folkLegends': evidence}
        engine = AgentEngine()
        engine.decide(raw)
        nonce = engine.planner.tasks.pending_id
        self.assertTrue(nonce)
        raw['roundNo'] = 71
        raw['llmResp'] = json.dumps({'requestId': nonce, 'confidence': 1,
            'pos': {'x': 3, 'y': 18}, 'items': ['SyntheticToken'],
            'opensRound': 72, 'closesRound': 85, 'evidence': evidence})
        result = engine.decide(raw)
        self.assertNotIn('summonTreasure', [a['action'] for a in result['roleCommandMap'].values()])
        self.assertIsNotNone(engine.planner.tasks.treasure)
        raw['roundNo'], raw['llmResp'] = 72, ''
        self.assertEqual(engine.decide(raw)['roleCommandMap']['3']['action'], 'summonTreasure')

    def test_terminal_treasure_ignores_pending_reply_and_resets_next_match(self):
        raw = arena(10, armed=True)
        evidence = 'Synthetic complete clue retained for correlation.'
        raw['worldNews'] = {'folkLegends': evidence}
        engine = AgentEngine()
        engine.decide(raw)
        nonce = engine.planner.tasks.pending_id
        raw['roundNo'] = 11
        raw['lastSummonTreasureResult'] = 4
        raw['llmResp'] = json.dumps({'requestId': nonce, 'confidence': 1,
            'pos': {'x': 3, 'y': 18}, 'items': ['SyntheticToken'],
            'opensRound': 11, 'closesRound': 85, 'evidence': evidence})
        engine.decide(raw)
        self.assertTrue(engine.planner.tasks.treasure_finished)
        self.assertIsNone(engine.planner.tasks.treasure)
        engine.decide(arena(1))
        self.assertFalse(engine.planner.tasks.treasure_finished)

    def test_failed_treasure_probe_does_not_end_entire_match_search(self):
        for code in (2, 3):
            manager = TaskManager()
            manager.treasure_attempt_round = 10
            raw = arena(11)
            raw['lastSummonTreasureResult'] = code
            manager.observe(Turn.from_raw(raw))
            self.assertFalse(manager.treasure_finished)

    def test_terminal_treasure_result_survives_new_legends(self):
        for result_code in (1, 4):
            with self.subTest(result=result_code):
                manager, state, budget = TaskManager(), WorldState(), LlmBudget()
                manager.treasure = Treasure(Pos(3, 18), ('SyntheticToken',), 20, 200)
                manager.treasure_attempt_round = 20
                raw = arena(21, armed=True)
                raw['lastSummonTreasureResult'] = result_code
                turn = Turn.from_raw(raw)
                state.ingest(turn)
                manager.observe(turn)
                raw['roundNo'] = 131
                raw['lastSummonTreasureResult'] = 0
                raw['worldNews'] = {'folkLegends': 'Synthetic repeated clue about the same treasure.'}
                turn = Turn.from_raw(raw)
                state.ingest(turn)
                budget.refresh(turn)
                manager.observe(turn)
                ctx = PlanningContext(turn, DEFAULT_CONFIG, state, time.monotonic() + 1)
                self.assertEqual(manager.news(ctx, budget), '')
                self.assertIsNone(manager.treasure)
