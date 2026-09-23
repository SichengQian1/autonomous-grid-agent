from __future__ import annotations

import json
import unittest
from dataclasses import replace

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
    safe_task_command,
)
from tests.helpers import synthetic_turn


class TaskStateTests(unittest.TestCase):
    def test_chinese_filename_probe_and_five_turn_task_cycle(self):
        manager, state, budget = TaskManager(), WorldState(), LlmBudget()
        def step(r, **fields):
            raw = synthetic_turn(round_no=r)
            raw["phaseTask"] = "请阅读fixture_notes.md，获取任务信息"
            raw.update(fields)
            turn = Turn.from_raw(raw)
            state.ingest(turn)
            budget.refresh(turn)
            return manager.plan(turn, state, budget, DEFAULT_CONFIG, turn.team_our.unit(2))
        self.assertIn("fixture_notes.md", step(10).execute_command)
        self.assertTrue(step(11, lastCmdResult="[exitCode:0]\nfixture data").prompt)
        self.assertTrue(step(12, llmResp=json.dumps({"command": 'python3 -c "print(42)"'})).execute_command)
        # Equal text is a distinct result when it belongs to a new command.
        self.assertTrue(step(13, lastCmdResult="[exitCode:0]\nfixture data").prompt)
        plan = step(14, llmResp=json.dumps({"answer": {"value": 42, "checked": True}}))
        self.assertEqual(json.loads(plan.action.task_answer), {"value": 42, "checked": True})

    def test_missing_command_result_recovers_after_bounded_wait(self):
        turn = Turn.from_raw(synthetic_turn(round_no=15))
        state = WorldState()
        state.ingest(turn)
        manager = TaskManager(last_generation=state.generation, phase=TaskPhase.WAITING_COMMAND,
                              command_requested_round=10, command_steps=1)
        plan = manager.plan(turn, state, LlmBudget(), DEFAULT_CONFIG, turn.team_our.unit(2))
        self.assertIn("No sandbox result", plan.prompt)

    def test_rejected_answer_retries_are_bounded(self):
        state, budget, manager = WorldState(), LlmBudget(), TaskManager()
        submitted = 0
        for r in range(10,20):
            raw = synthetic_turn(round_no=r)
            raw["llmResp"] = json.dumps({"answer": "attempt-" + str(r)})
            raw["errors"] = [{"errorCode":2}]
            turn = Turn.from_raw(raw)
            state.ingest(turn); budget.refresh(turn)
            plan = manager.plan(turn,state,budget,DEFAULT_CONFIG,turn.team_our.unit(2))
            submitted += plan.action is not None
        self.assertEqual(submitted, DEFAULT_CONFIG.task_submit_limit)

    def test_malformed_llm_is_rejected(self) -> None:
        self.assertIsNone(parse_structured_llm("not json"))
        self.assertIsNone(parse_structured_llm("[]"))

    def test_safe_calculation_command_is_narrow(self) -> None:
        self.assertEqual(safe_calculation_command('python3 -c "print(2+3)"'), 'python3 -c "print(2+3)"')
        self.assertEqual(safe_calculation_command("python3 -c \"__import__('os').system('id')\""), "")

    def test_task_command_guard_allows_local_work_but_blocks_dangerous_commands(self) -> None:
        self.assertTrue(safe_task_command("find /tmp/selfEvolutionTask -type f"))
        self.assertEqual(safe_task_command("rm -rf /tmp/selfEvolutionTask"), "")
        self.assertEqual(safe_task_command("curl https://example.com"), "")

    def test_named_task_file_is_probed_before_first_llm_call(self) -> None:
        raw = synthetic_turn(round_no=10)
        raw["phaseTask"] = "Read puzzle.md and answer the question."
        turn = Turn.from_raw(raw)
        state = WorldState()
        state.ingest(turn)
        plan = TaskManager().plan(turn, state, LlmBudget(), DEFAULT_CONFIG, turn.team_our.unit(2))
        self.assertIn("/tmp/selfEvolutionTask", plan.execute_command)
        self.assertEqual(plan.prompt, "")

    def test_sandbox_output_is_synthesized_not_submitted_raw(self) -> None:
        raw = synthetic_turn(round_no=11)
        raw["lastCmdResult"] = "[exitCode:0]\nraw evidence"
        turn = Turn.from_raw(raw)
        state = WorldState()
        state.ingest(turn)
        manager = TaskManager(
            last_generation=state.generation,
            phase=TaskPhase.WAITING_COMMAND,
            command_steps=1,
        )
        budget = LlmBudget()
        budget.refresh(turn)
        plan = manager.plan(turn, state, budget, DEFAULT_CONFIG, turn.team_our.unit(2))
        self.assertIsNone(plan.action)
        self.assertIn("raw evidence", plan.prompt)

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

    def test_live_task_phase_wins_over_estimated_timeout(self) -> None:
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
        self.assertEqual(manager.phase, TaskPhase.WAITING_LLM)
        self.assertTrue(plan.prompt)
        self.assertIn("Estimated task turns left: 0",plan.prompt)

    def test_same_task_text_does_not_reuse_an_old_dynamic_answer(self) -> None:
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
        self.assertIsNone(plan.action)
        self.assertTrue(plan.prompt)


class TreasureTests(unittest.TestCase):
    def test_incomplete_candidate_never_sacrifices_items(self) -> None:
        turn = Turn.from_raw(synthetic_turn(round_no=131))
        pioneer = turn.team_our.unit(2)
        knowledge = TreasureKnowledge(position=Pos(3, 3), opening_day=1)
        self.assertIsNone(knowledge.action(turn, pioneer, DEFAULT_CONFIG))

    def test_result_code_updates_state(self) -> None:
        knowledge = TreasureKnowledge()
        knowledge.apply_result(4)
        self.assertTrue(knowledge.exhausted)
        knowledge = TreasureKnowledge()
        knowledge.apply_result(3)
        self.assertFalse(knowledge.materials)


class ActivePlannerTests(unittest.TestCase):
    def test_task_waiting_role_does_not_walk_to_shop(self):
        raw = synthetic_turn(round_no=15)
        raw["teamOur"]["goldNum"] = 300
        raw["weaponShopList"].append({"name":"WeaponUpgradeVoucher1","price":100})
        response = AgentEngine().decide(raw)
        self.assertNotIn("2", response["roleCommandMap"])
        self.assertTrue(response.get("prompt"))

    def test_cooling_launcher_controller_stays_until_wave_is_clear(self):
        from tests.helpers import role
        raw = synthetic_turn(round_no=71)
        raw["phaseTask"] = ""
        raw["mapInfo"]["zones"] = []
        raw["teamOur"]["roles"] = [role(1,"worker",2,3),role(2,"pioneer",4,3),role(3,"worker",6,3),
            role(10,"rocket",2,4,health=1000,level=1,attack_range=10,cooldown=2),
            role(11,"rocket",4,4,health=1000,level=1,attack_range=10,cooldown=2),
            role(12,"railgun",6,4,health=1000,level=1,attack_range=6),
            role(13,"station",3,7,health=1500,level=1)]
        response = AgentEngine().decide(raw)
        self.assertTrue(any(a["action"]=="attack" for a in response["roleCommandMap"].values()))
        self.assertFalse(any(a["action"] in ("move","collect","sell") for a in response["roleCommandMap"].values()))

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
        response = AgentEngine(replace(DEFAULT_CONFIG, allow_cross_map_fire=True)).decide(raw)
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
