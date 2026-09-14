from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
import time
import unittest

from solution.models import Turn
from solution.planning import PlanningContext
from solution.rules import DEFAULT_CONFIG
from solution.state import LlmBudget, WorldState
from solution.tasks import TaskManager, json_object, parse_command_result, sandbox_command, validated_python
from tests.scenarios import arena


class TaskTests(unittest.TestCase):
    def context(self, raw):
        turn = Turn.from_raw(raw)
        state = WorldState()
        state.ingest(turn)
        return PlanningContext(turn, DEFAULT_CONFIG, state, time.monotonic() + 1)

    def test_command_result_parser(self):
        self.assertEqual(parse_command_result("[exitCode:0]\n42"), ("ok", "42"))
        self.assertEqual(parse_command_result("[exitCode:1]\ninvalid"), ("failed", "invalid"))
        self.assertEqual(parse_command_result("[TIMEOUT]\npartial")[0], "failed")
        self.assertEqual(parse_command_result("[JUDGER_ERROR]\nfailed")[0], "failed")
        self.assertEqual(parse_command_result("unframed text"), ("missing", ""))
        self.assertLessEqual(len(parse_command_result("[exitCode:0]\n" + "x" * 20000)[1]), 12000)

    def test_llm_output_cannot_be_translated_directly_to_shell(self):
        for code in ("import os\nos.system('echo no')", "open('file','w')", "eval('1+1')", "x.__class__", "from math import *", "print('x')\n" * 2000):
            self.assertIsNone(validated_python(code), code[:50])
        self.assertEqual(validated_python("import math\nprint(math.isqrt(144))"), "import math\nprint(math.isqrt(144))")

    def test_sandbox_wrapper_runs_only_trusted_synthetic_code_and_bounds_output(self):
        # Exercise a fixed synthetic snippet, never model-provided task code.
        parts = shlex.split(sandbox_command("print('x' * 60000)"))
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, *parts[1:]], cwd=directory, capture_output=True, timeout=12)
        self.assertLessEqual(len(result.stdout), 48000)
        self.assertLessEqual(len(result.stderr), 1000)

    def test_bad_json_and_oversized_llm_output(self):
        for text in ("plain words", "[]", "{broken", "x" * 40000):
            self.assertIsNone(json_object(text))
        self.assertEqual(json_object('```json\n{"answer": "42"}\n```'), {"answer": "42"})

    def test_correlated_task_solution_and_daily_budget(self):
        raw = arena(5, armed=True)
        raw["phaseTask"] = "Compute a synthetic sum."
        manager, budget = TaskManager(), LlmBudget()
        ctx = self.context(raw)
        budget.refresh(ctx.turn)
        manager.observe(ctx.turn)
        response = manager.active(ctx, ctx.turn.team_our.unit(3), budget)
        nonce = json.loads(response.prompt)["requestId"]
        self.assertEqual(budget.calls_used, 0)
        raw["roundNo"] = 6
        raw["llmResp"] = json.dumps({"requestId": nonce, "confidence": 1, "operation": "answer", "answer": "42"})
        ctx = self.context(raw)
        manager.observe(ctx.turn)
        answer = manager.active(ctx, ctx.turn.team_our.unit(3), budget)
        self.assertEqual(answer.action.task_answer, "42")

    def test_stale_low_confidence_and_missing_response_do_not_submit(self):
        for variant in ("nonce", "confidence", "missing", "late"):
            raw = arena(5, armed=True)
            raw["phaseTask"] = "Synthetic task"
            manager, budget = TaskManager(), LlmBudget()
            ctx = self.context(raw)
            budget.refresh(ctx.turn)
            manager.observe(ctx.turn)
            nonce = json.loads(manager.active(ctx, ctx.turn.team_our.unit(3), budget).prompt)["requestId"]
            raw["roundNo"] = 7 if variant == "late" else 6
            raw["llmResp"] = "" if variant == "missing" else json.dumps({"requestId": "wrong" if variant == "nonce" else nonce,
                "confidence": 0.2 if variant == "confidence" else 1, "operation": "answer", "answer": "42"})
            ctx = self.context(raw)
            manager.observe(ctx.turn)
            self.assertIsNone(manager.active(ctx, ctx.turn.team_our.unit(3), budget).action)

    def test_task_replacement_invalidates_pending_response(self):
        raw = arena(5)
        raw["phaseTask"] = "First synthetic task"
        manager, budget = TaskManager(), LlmBudget()
        ctx = self.context(raw)
        budget.refresh(ctx.turn)
        manager.observe(ctx.turn)
        nonce = json.loads(manager.active(ctx, ctx.turn.team_our.unit(3), budget).prompt)["requestId"]
        raw["roundNo"] = 6
        raw["phaseTask"] = "Different synthetic task"
        raw["llmResp"] = json.dumps({"requestId": nonce, "confidence": 1, "operation": "answer", "answer": "old"})
        ctx = self.context(raw)
        manager.observe(ctx.turn)
        self.assertIsNone(manager.active(ctx, ctx.turn.team_our.unit(3), budget).action)

    def test_treasure_probe_is_never_repeated_after_feedback(self):
        from solution.tasks import Treasure
        from solution.geometry import Pos
        manager = TaskManager()
        manager.treasure = Treasure(Pos(8, 8), ("SyntheticToken",), 1, 100)
        manager.treasure_attempt_round = 10
        raw = arena(11)
        raw["lastSummonTreasureResult"] = 3
        manager.observe(Turn.from_raw(raw))
        self.assertIsNone(manager.treasure)

    def test_missing_treasure_conditions_never_create_plan(self):
        raw = arena(5)
        raw["worldNews"] = {"folkLegends": "A synthetic incomplete clue with no offering list."}
        manager, budget = TaskManager(), LlmBudget()
        ctx = self.context(raw)
        budget.refresh(ctx.turn)
        manager.observe(ctx.turn)
        nonce = json.loads(manager.news(ctx, budget))["requestId"]
        raw["roundNo"] = 6
        raw["llmResp"] = json.dumps({"requestId": nonce, "confidence": 1, "pos": {"x": 8, "y": 8}})
        ctx = self.context(raw)
        manager.observe(ctx.turn)
        manager.news(ctx, budget)
        self.assertIsNone(manager.treasure)
