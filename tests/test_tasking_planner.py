from __future__ import annotations

import json
import unittest

from solution.engine import AgentEngine
from solution.geometry import Pos
from solution.models import Turn
from solution.rules import DEFAULT_CONFIG
from solution.state import LlmBudget, WorldState
from solution.tasking import (
    TaskManager,
    TaskPhase,
    TreasureKnowledge,
    parse_sandbox_result,
    parse_structured_llm,
    safe_calculation_command,
)
from tests.helpers import synthetic_turn


class TaskStateTests(unittest.TestCase):
    def test_malformed_llm_is_rejected(self) -> None:
        self.assertIsNone(parse_structured_llm("not json"))
        self.assertIsNone(parse_structured_llm("[]"))

    def test_safe_calculation_command_is_narrow(self) -> None:
        self.assertEqual(safe_calculation_command('python3 -c "print(2+3)"'), 'python3 -c "print(2+3)"')
        self.assertEqual(safe_calculation_command("python3 -c \"__import__('os').system('id')\""), "")

    def test_sandbox_timeout_and_truncation(self) -> None:
        timeout = parse_sandbox_result("[TIMEOUT]\npartial")
        truncated = parse_sandbox_result("[exitCode:0]\nok\n[TRUNCATED]")
        self.assertEqual(timeout.status, "timeout")
        self.assertTrue(truncated.truncated)

    def test_active_task_requests_structured_llm(self) -> None:
        turn = Turn.from_raw(synthetic_turn(round_no=10))
        state = WorldState()
        state.ingest(turn)
        budget = LlmBudget()
        budget.refresh(turn)
        pioneer = turn.team_our.unit(2)
        plan = TaskManager().plan(turn, state, budget, DEFAULT_CONFIG, pioneer)
        self.assertIn("strict JSON", plan.prompt)

    def test_llm_answer_becomes_validated_submit_action(self) -> None:
        raw = synthetic_turn(round_no=11)
        raw["llmResp"] = json.dumps({"answer": "42"})
        turn = Turn.from_raw(raw)
        state = WorldState()
        state.ingest(turn)
        budget = LlmBudget()
        budget.refresh(turn)
        manager = TaskManager(last_generation=state.generation, phase=TaskPhase.WAITING_LLM)
        plan = manager.plan(turn, state, budget, DEFAULT_CONFIG, turn.team_our.unit(2))
        self.assertEqual(plan.action.task_answer, "42")

    def test_missing_task_timeout_does_not_crash(self) -> None:
        raw = synthetic_turn(round_no=1)
        del raw["teamOur"]["playerTasks"][0]["timeoutRounds"]
        raw["phaseTask"] = ""
        turn = Turn.from_raw(raw)
        state = WorldState()
        state.ingest(turn)
        plan = TaskManager().plan(turn, state, LlmBudget(), DEFAULT_CONFIG, turn.team_our.unit(2))
        self.assertIsNotNone(plan)

    def test_failed_accept_recovers_without_crash(self) -> None:
        raw = synthetic_turn(round_no=2)
        raw["phaseTask"] = ""
        raw["lastRoundRoleActionResults"] = {"2": False}
        turn = Turn.from_raw(raw)
        state = WorldState()
        state.ingest(turn)
        manager = TaskManager(last_generation=state.generation, phase=TaskPhase.ACCEPTING)
        plan = manager.plan(turn, state, LlmBudget(), DEFAULT_CONFIG, turn.team_our.unit(2))
        self.assertEqual(manager.phase, TaskPhase.FAILED)
        self.assertIsNone(plan.action)

    def test_active_task_times_out_safely(self) -> None:
        turn = Turn.from_raw(synthetic_turn(round_no=15))
        state = WorldState()
        state.ingest(turn)
        manager = TaskManager(
            last_generation=state.generation,
            phase=TaskPhase.WAITING_LLM,
            accepted_round=10,
            timeout_rounds=5,
        )
        plan = manager.plan(turn, state, LlmBudget(), DEFAULT_CONFIG, turn.team_our.unit(2))
        self.assertEqual(manager.phase, TaskPhase.FAILED)
        self.assertEqual(plan.prompt, "")

    def test_successful_exact_task_answer_can_be_reused(self) -> None:
        state = WorldState()
        completed_raw = synthetic_turn(round_no=20)
        completed_raw["phaseTask"] = ""
        completed_raw["lastRoundRoleActionResults"] = {"2": True}
        completed = Turn.from_raw(completed_raw)
        state.ingest(completed)
        manager = TaskManager(
            last_generation=state.generation,
            phase=TaskPhase.WAITING_RESULT,
            pending_answer="known-answer",
            task_signature=__import__("hashlib").sha256(b"same task").hexdigest(),
        )
        manager.plan(completed, state, LlmBudget(), DEFAULT_CONFIG, completed.team_our.unit(2))
        active_raw = synthetic_turn(round_no=21)
        active_raw["phaseTask"] = "same task"
        active = Turn.from_raw(active_raw)
        plan = manager.plan(active, state, LlmBudget(), DEFAULT_CONFIG, active.team_our.unit(2))
        self.assertEqual(plan.action.task_answer, "known-answer")


class TreasureTests(unittest.TestCase):
    def test_low_confidence_never_sacrifices_items(self) -> None:
        turn = Turn.from_raw(synthetic_turn(round_no=131))
        pioneer = turn.team_our.unit(2)
        knowledge = TreasureKnowledge(Pos(3, 3), 1, ("Token",), 0.5)
        self.assertIsNone(knowledge.action(turn, pioneer, DEFAULT_CONFIG))

    def test_result_code_updates_state(self) -> None:
        knowledge = TreasureKnowledge(confidence=1.0)
        knowledge.apply_result(4)
        self.assertTrue(knowledge.exhausted)
        knowledge = TreasureKnowledge(confidence=1.0)
        knowledge.apply_result(3)
        self.assertEqual(knowledge.confidence, 0.0)


class ActivePlannerTests(unittest.TestCase):
    def test_day_one_is_not_permanently_empty(self) -> None:
        raw = synthetic_turn(round_no=1)
        raw["phaseTask"] = ""
        response = AgentEngine().decide(raw)
        self.assertTrue(response["roleCommandMap"] or response.get("prompt"))

    def test_night_with_threat_issues_attack_or_recall(self) -> None:
        raw = synthetic_turn(round_no=71)
        raw["phaseTask"] = ""
        response = AgentEngine().decide(raw)
        actions = tuple(response["roleCommandMap"].values())
        self.assertTrue(any(action["action"] in {"attack", "move"} for action in actions))

    def test_cross_map_fire_requires_explicit_target_team(self) -> None:
        raw = synthetic_turn(round_no=721)
        raw["phaseTask"] = ""
        raw["robot"]["roles"][0]["targetTeam"] = "defender"
        raw["robot"]["roles"][0]["pos"] = {"x": 7, "y": 2}
        response = AgentEngine().decide(raw)
        self.assertTrue(any(
            action["action"] == "attack"
            for action in response["roleCommandMap"].values()
        ))

    def test_every_response_serializes(self) -> None:
        engine = AgentEngine()
        for round_no in (1, 70, 71, 130, 131, 650, 1300):
            raw = synthetic_turn(round_no=round_no)
            raw["phaseTask"] = ""
            json.dumps(engine.decide(raw))

    def test_advanced_module_failure_keeps_basic_night_defense(self) -> None:
        class FailingTasks:
            def reset(self, generation: int) -> None:
                del generation

            def plan(self, *args, **kwargs):
                del args, kwargs
                raise RuntimeError("synthetic task failure")

        raw = synthetic_turn(round_no=71)
        raw["phaseTask"] = "synthetic active"
        next(role for role in raw["teamOur"]["roles"] if role["roleType"] == "rocket")["cooldown"] = 2
        raw["robot"]["roles"][0]["health"] = 10
        engine = AgentEngine()
        engine.planner.tasks = FailingTasks()
        response = engine.decide(raw)
        self.assertTrue(
            any(action["action"] == "attack" for action in response["roleCommandMap"].values())
        )


if __name__ == "__main__":
    unittest.main()
