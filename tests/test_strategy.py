from __future__ import annotations

import copy
from dataclasses import replace
import json
import time
import unittest

from solution.actions import Action, ActionType, Decision
from solution.engine import AgentEngine
from solution.geometry import Pos, footprint_distance, neighbours
from solution.models import Turn
from solution.rules import DEFAULT_CONFIG
from solution.validation import ActionValidator
from tests.helpers import role
from tests.scenarios import arena, robot


class StrategyTests(unittest.TestCase):
    def test_opening_constructs_valid_weapons(self):
        raw = arena()
        engine = AgentEngine()
        result = engine.decide(raw)
        self.assertTrue(result["roleCommandMap"])
        self.assertTrue(any(a["action"] in {"build", "move"} for a in result["roleCommandMap"].values()))
        self.assertEqual(ActionValidator().validate(Turn.from_raw(raw), Decision(engine.state.previous_actions)).issues, ())

    def test_feature_flag_preserves_safe_fallback(self):
        self.assertEqual(AgentEngine(replace(DEFAULT_CONFIG, enabled=False)).decide(arena()), {"roleCommandMap": {}})

    def test_critical_base_uses_one_matching_voucher_before_combat(self):
        raw = arena(80, armed=True)
        raw["teamOur"]["roles"][3]["health"] = 200
        raw["teamOur"]["roles"][0]["backpack"] = ["StationUpgradeVoucher1"]
        raw["teamOur"]["roles"][2]["backpack"] = ["StationUpgradeVoucher1"]
        raw["robot"]["roles"] = [robot(100, 10, 15, 800)]
        result = AgentEngine().decide(raw)
        repairs = [a for a in result["roleCommandMap"].values() if a.get("name") == "StationUpgradeVoucher1"]
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["action"], "use")

    def test_identical_retry_does_not_mutate_state(self):
        engine = AgentEngine()
        raw = arena()
        raw["worldNews"] = {"folkLegends": "synthetic clues that do not identify a complete treasure"}
        first = engine.decide(raw)
        calls, turns = engine.llm_budget.calls_used, engine.state.turns_seen
        second = engine.decide(raw)
        self.assertEqual(first, second)
        self.assertEqual((calls, turns), (engine.llm_budget.calls_used, engine.state.turns_seen))
        second["roleCommandMap"].clear()
        self.assertEqual(first, engine.decide(raw))

    def test_out_of_order_request_is_ignored(self):
        engine = AgentEngine()
        engine.decide(arena(15))
        self.assertEqual(engine.decide(arena(14)), {"roleCommandMap": {}})
        self.assertEqual(engine.state.last_round_no, 15)

    def test_new_match_resets_llm_budget(self):
        engine = AgentEngine()
        engine.decide(arena(20))
        engine.llm_budget.calls_used = 3
        raw = arena(1)
        raw["teamOur"]["teamId"] = "another-synthetic"
        engine.decide(raw)
        self.assertEqual(engine.llm_budget.calls_used, 0)

    def test_no_night_construction_and_cleared_wave_resumes_economy(self):
        raw = arena(80, armed=True)
        result = AgentEngine().decide(raw)
        actions = list(result["roleCommandMap"].values())
        self.assertTrue(actions)
        self.assertFalse(any(a["action"] in {"build", "attack"} for a in actions))
        self.assertTrue(any(a["action"] in {"move", "collect", "buy"} for a in actions))

    def test_dusk_does_not_accept_task(self):
        raw = arena(69, armed=True)
        raw["teamOur"]["roles"][2]["pos"] = {"x": 9, "y": 17}
        raw["teamOur"]["playerTasks"] = [{"taskType": "test", "taskPosition": {"x": 9, "y": 18},
                                           "isValid": True, "timeoutRounds": 20, "scoreReward": 100}]
        result = AgentEngine().decide(raw)
        self.assertFalse(any(a["action"] == "acceptTask" for a in result["roleCommandMap"].values()))

    def test_small_wave_keeps_a_controller_and_recalls_collectors_on_danger(self):
        raw = arena(80, armed=True)
        raw["robot"]["roles"] = [robot(100, 12, 15, 20)]
        engine = AgentEngine()
        actions = engine.decide(raw)["roleCommandMap"]
        self.assertTrue(any(a["action"] == "attack" for a in actions.values()))
        self.assertTrue(any(a["action"] in {"move", "collect", "buy"} for a in actions.values()))
        raw["roundNo"] = 81
        raw["robot"]["roles"] = [robot(100, 6, 11, 800)]
        actions = engine.decide(raw)["roleCommandMap"]
        self.assertFalse(any(a["action"] in {"collect", "buy", "sell"} for a in actions.values()))

    def test_affordable_task_is_accepted_and_pioneer_stays_for_solution(self):
        raw = arena(10, armed=True)
        raw["teamOur"]["roles"][2]["pos"] = {"x": 9, "y": 17}
        raw["teamOur"]["playerTasks"] = [{"taskType": "test", "taskPosition": {"x": 9, "y": 18},
                                           "isValid": True, "timeoutRounds": 20, "scoreReward": 100}]
        engine = AgentEngine()
        self.assertEqual(engine.decide(raw)["roleCommandMap"]["3"]["action"], "acceptTask")
        raw["roundNo"] = 11
        raw["phaseTask"] = "Compute 17 plus 25 and return a decimal integer."
        response = engine.decide(raw)
        self.assertIn("prompt", response)
        self.assertNotIn("3", response["roleCommandMap"])
        nonce = json.loads(response["prompt"])["requestId"]
        raw["roundNo"] = 12
        raw["llmResp"] = json.dumps({"requestId": nonce, "confidence": 1, "operation": "answer", "answer": "42"})
        self.assertEqual(engine.decide(raw)["roleCommandMap"]["3"], {"action": "submitAnswer", "taskAnswer": "42"})

    def test_weapon_rebuild_budget_does_not_overspend(self):
        raw = arena()
        raw["teamOur"]["goldNum"] = 25
        engine = AgentEngine()
        for step in range(1, 12):
            raw["roundNo"] = step
            result = engine.decide(raw)
            builds = [a for a in result["roleCommandMap"].values() if a["action"] == "build"]
            self.assertLessEqual(len(builds), 1)
            if builds:
                break
            for key, command in result["roleCommandMap"].items():
                if command["action"] == "move":
                    next(u for u in raw["teamOur"]["roles"] if u["id"] == int(key))["pos"] = command["targetPos"][0]
        else:
            self.fail("opening did not reach any build site")

    def test_failed_action_is_not_reissued_immediately(self):
        engine = AgentEngine()
        raw = arena()
        first = engine.decide(raw)["roleCommandMap"]
        raw["roundNo"] = 2
        raw["lastRoundRoleActionResults"] = {k: False for k in first}
        second = engine.decide(raw)["roleCommandMap"]
        for key, action in first.items():
            self.assertNotEqual(second.get(key), action)

    def test_zero_budget_returns_immediately(self):
        started = time.monotonic()
        self.assertEqual(AgentEngine(replace(DEFAULT_CONFIG, normal_turn_budget_seconds=0)).decide(arena()), {"roleCommandMap": {}})
        self.assertLess(time.monotonic() - started, 0.1)


class JointValidationTests(unittest.TestCase):
    def test_collision_and_swap_are_rejected(self):
        raw = arena()
        raw["teamOur"]["roles"] = [role(1, "worker", 0, 0), role(2, "worker", 2, 0)]
        turn = Turn.from_raw(raw)
        validator = ActionValidator()
        result = validator.validate(turn, Decision((Action(1, ActionType.MOVE, targets=(Pos(1, 0),)),
                                                    Action(2, ActionType.MOVE, targets=(Pos(1, 0),)))))
        self.assertEqual(len(result.actions), 1)
        raw["teamOur"]["roles"][1]["pos"] = {"x": 1, "y": 0}
        result = validator.validate(Turn.from_raw(raw), Decision((Action(1, ActionType.MOVE, targets=(Pos(1, 0),)),
                                                                Action(2, ActionType.MOVE, targets=(Pos(0, 0),)))))
        self.assertEqual(result.actions, ())

    def test_shared_purchase_budget_and_capacity(self):
        raw = arena()
        raw["teamOur"]["goldNum"] = 10
        raw["teamOur"]["roles"][0]["pos"] = {"x": 6, "y": 18}
        raw["teamOur"]["roles"][1]["pos"] = {"x": 6, "y": 17}
        actions = tuple(Action(i, ActionType.BUY, name="Medicine", quantity=1) for i in (1, 2))
        validator = ActionValidator()
        self.assertEqual(len(validator.validate(Turn.from_raw(raw), Decision(actions)).actions), 1)
        raw["teamOur"]["roles"][0]["backPackCapability"] = 0
        self.assertEqual(validator.validate(Turn.from_raw(raw), Decision(actions[:1])).actions, ())

    def test_build_ring_and_material_validation(self):
        raw = arena()
        validator = ActionValidator()
        turn = Turn.from_raw(raw)
        self.assertEqual(validator.validate(turn, Decision((Action(1, ActionType.BUILD, targets=(Pos(6, 15),), name="railgun"),))).actions, ())
        self.assertEqual(validator.validate(turn, Decision((Action(1, ActionType.BUILD, targets=(Pos(6, 15),), name="wall"),))).actions, ())
        raw["teamOur"]["roles"][0]["backpack"] = ["stone"]
        self.assertEqual(len(validator.validate(Turn.from_raw(raw), Decision((Action(1, ActionType.BUILD, targets=(Pos(6, 15),), name="wall"),))).actions), 1)

    def test_wrong_level_voucher_does_not_execute(self):
        raw = arena(20, armed=True)
        raw["teamOur"]["roles"][0]["backpack"] = ["WeaponUpgradeVoucher1"]
        result = ActionValidator().validate(Turn.from_raw(raw), Decision((Action(1, ActionType.USE, targets=(Pos(5, 14),), name="WeaponUpgradeVoucher1"),)))
        self.assertEqual(result.actions, ())
