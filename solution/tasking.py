from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum

from .actions import Action, ActionType
from .geometry import Pos
from .models import PlayerTask, Turn, Unit
from .movement import MoveIntent
from .rules import StrategyConfig
from .state import LlmBudget, WorldState


class TaskPhase(str, Enum):
    IDLE = "IDLE"
    TRAVEL = "TRAVEL"
    ACCEPTING = "ACCEPTING"
    WAITING_LLM = "WAITING_LLM"
    SUBMITTING = "SUBMITTING"
    WAITING_RESULT = "WAITING_RESULT"
    COOLDOWN = "COOLDOWN"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class SandboxResult:
    status: str
    exit_code: int | None
    output: str
    truncated: bool


def parse_sandbox_result(raw: str, limit: int = 4096) -> SandboxResult:
    text = (raw or "")[:limit]
    truncated = "[TRUNCATED]" in text or len(raw or "") > limit
    if text.startswith("[TIMEOUT]"):
        return SandboxResult("timeout", None, text.partition("\n")[2], truncated)
    if text.startswith("[JUDGER_ERROR]"):
        return SandboxResult("judger_error", None, text.partition("\n")[2], truncated)
    match = re.match(r"\[exitCode:(-?\d+)\](?:\n|$)", text)
    if match:
        return SandboxResult(
            "ok" if int(match.group(1)) == 0 else "error",
            int(match.group(1)),
            text[match.end():],
            truncated,
        )
    return SandboxResult("unknown", None, text, truncated)


def parse_structured_llm(raw: str) -> dict[str, object] | None:
    if not raw or len(raw) > 64 * 1024:
        return None
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def safe_calculation_command(command: object) -> str:
    """Allow only a tiny arithmetic Python command, never arbitrary LLM code."""

    if not isinstance(command, str) or len(command) > 256 or "\n" in command:
        return ""
    prefix = "python3 -c "
    if not command.startswith(prefix):
        return ""
    expression = command[len(prefix):].strip().strip('"').strip("'")
    if not re.fullmatch(r"print\([0-9+\-*/%()., ]+\)", expression):
        return ""
    return f'python3 -c "{expression}"'


@dataclass(frozen=True, slots=True)
class AdvancedPlan:
    action: Action | None = None
    move: MoveIntent | None = None
    prompt: str = ""
    execute_command: str = ""


@dataclass(slots=True)
class TaskManager:
    phase: TaskPhase = TaskPhase.IDLE
    task_position: Pos | None = None
    accepted_round: int | None = None
    last_submit_round: int | None = None
    pending_answer: str = ""
    pending_command: str = ""
    last_generation: int = -1
    llm_requested_round: int | None = None
    timeout_rounds: int = 0
    task_signature: str = ""
    reusable_answers: dict[str, str] = field(default_factory=dict)

    def reset(self, generation: int) -> None:
        self.phase = TaskPhase.IDLE
        self.task_position = None
        self.accepted_round = None
        self.last_submit_round = None
        self.pending_answer = ""
        self.pending_command = ""
        self.last_generation = generation
        self.llm_requested_round = None
        self.timeout_rounds = 0
        self.task_signature = ""
        self.reusable_answers.clear()

    def plan(
        self,
        turn: Turn,
        state: WorldState,
        budget: LlmBudget,
        config: StrategyConfig,
        pioneer: Unit | None,
    ) -> AdvancedPlan:
        if state.generation != self.last_generation:
            self.reset(state.generation)
        if pioneer is None or pioneer.pos is None:
            return AdvancedPlan()
        if any(error.error_code in {1, 2, 4, 5} for error in turn.errors):
            self.phase = TaskPhase.FAILED
            self.pending_answer = ""
            self.pending_command = ""
        if (
            self.phase == TaskPhase.ACCEPTING
            and turn.last_action_results.get(pioneer.unit_id) is False
        ):
            self.phase = TaskPhase.FAILED
            return AdvancedPlan()

        if turn.phase_task:
            signature = hashlib.sha256(turn.phase_task.encode("utf-8")).hexdigest()
            self.task_signature = signature
            if self.accepted_round is None:
                self.accepted_round = turn.round_no
            if (
                self.timeout_rounds > 0
                and turn.round_no - self.accepted_round >= self.timeout_rounds
            ):
                self.phase = TaskPhase.FAILED
                self.pending_answer = ""
                return AdvancedPlan()
            reusable = self.reusable_answers.get(signature)
            if reusable and not self.pending_answer:
                self.pending_answer = reusable
            return self._plan_active(turn, budget, pioneer)

        if self.phase in {
            TaskPhase.WAITING_LLM,
            TaskPhase.SUBMITTING,
            TaskPhase.WAITING_RESULT,
        }:
            if (
                self.phase == TaskPhase.WAITING_RESULT
                and self.task_signature
                and self.pending_answer
                and turn.last_action_results.get(pioneer.unit_id) is not False
                and not turn.errors
            ):
                self.reusable_answers[self.task_signature] = self.pending_answer
            self.phase = TaskPhase.COOLDOWN
            self.pending_answer = ""
            self.pending_command = ""

        task = self._choose_task(turn, pioneer, config)
        if task is None or task.task_position is None:
            if self.phase != TaskPhase.FAILED:
                self.phase = TaskPhase.IDLE
            return AdvancedPlan()
        self.task_position = task.task_position
        self.timeout_rounds = task.timeout_rounds
        if pioneer.pos.distance_to(task.task_position) <= 1:
            self.phase = TaskPhase.ACCEPTING
            self.accepted_round = turn.round_no
            return AdvancedPlan(
                action=Action(pioneer.unit_id, ActionType.ACCEPT_TASK)
            )
        self.phase = TaskPhase.TRAVEL
        return AdvancedPlan(
            move=MoveIntent(
                pioneer.unit_id,
                tuple(task.task_position.neighbours()),
                priority=60,
            )
        )

    def _plan_active(
        self,
        turn: Turn,
        budget: LlmBudget,
        pioneer: Unit,
    ) -> AdvancedPlan:
        if self.task_position is not None and pioneer.pos is not None and pioneer.pos.distance_to(self.task_position) > 1:
            return AdvancedPlan(
                move=MoveIntent(
                    pioneer.unit_id,
                    tuple(self.task_position.neighbours()),
                    priority=95,
                )
            )
        if turn.last_command_result:
            result = parse_sandbox_result(turn.last_command_result)
            if result.status == "ok" and result.output.strip():
                self.pending_answer = result.output.strip()[:4096]
            elif result.status in {"timeout", "judger_error", "error"}:
                self.pending_command = ""

        if turn.llm_response:
            parsed = parse_structured_llm(turn.llm_response)
            if parsed is not None:
                answer = parsed.get("answer")
                if isinstance(answer, (str, int, float, bool)):
                    self.pending_answer = str(answer)[:8192]
                self.pending_command = safe_calculation_command(parsed.get("command"))

        if self.phase == TaskPhase.WAITING_RESULT:
            feedback = turn.last_action_results.get(pioneer.unit_id)
            if feedback is not False:
                return AdvancedPlan()
            self.pending_answer = ""
            self.phase = TaskPhase.FAILED
            return AdvancedPlan()

        if self.pending_answer and self.last_submit_round != turn.round_no:
            self.phase = TaskPhase.WAITING_RESULT
            self.last_submit_round = turn.round_no
            return AdvancedPlan(
                action=Action(
                    pioneer.unit_id,
                    ActionType.SUBMIT_ANSWER,
                    task_answer=self.pending_answer,
                )
            )
        if self.pending_command:
            command = self.pending_command
            self.pending_command = ""
            return AdvancedPlan(execute_command=command)
        if budget.can_call(task_active=True):
            if self.llm_requested_round is not None and turn.round_no - self.llm_requested_round < 3:
                return AdvancedPlan()
            self.phase = TaskPhase.WAITING_LLM
            budget.mark_requested(task_active=True, round_no=turn.round_no)
            self.llm_requested_round = turn.round_no
            task_text = turn.phase_task[:6000]
            return AdvancedPlan(
                prompt=(
                    "Solve the active task. Return strict JSON only: "
                    '{"answer":"final answer"}. If arithmetic is required, you may '
                    'also include "command":"python3 -c \\\"print(expression)\\\"". '
                    f"Task: {task_text}"
                )
            )
        return AdvancedPlan()

    @staticmethod
    def _choose_task(turn: Turn, pioneer: Unit, config: StrategyConfig) -> PlayerTask | None:
        candidates: list[tuple[float, PlayerTask]] = []
        for task in turn.team_our.player_tasks:
            if not task.is_valid or task.task_position is None:
                continue
            if task.timeout_rounds <= 0:
                # A missing deadline cannot be converted into a safe travel budget.
                continue
            distance = pioneer.pos.distance_to(task.task_position) if pioneer.pos else 10**6
            if task.timeout_rounds < max(config.task_minimum_timeout, distance + 2):
                continue
            if turn.is_day and turn.rounds_until_night <= distance + config.task_return_buffer:
                continue
            value = task.score_reward * 3 + task.gold_reward - distance
            candidates.append((value, task))
        return max(candidates, key=lambda item: item[0], default=(0.0, None))[1]


@dataclass(slots=True)
class TreasureKnowledge:
    position: Pos | None = None
    opening_day: int | None = None
    items: tuple[str, ...] = ()
    confidence: float = 0.0
    exhausted: bool = False
    attempted: set[tuple[Pos, int, tuple[str, ...]]] = field(default_factory=set)

    def apply_result(self, result_code: int) -> None:
        if result_code == 1 or result_code == 4:
            self.exhausted = True
        elif result_code in {2, 3}:
            self.confidence = 0.0

    def ingest_llm(self, raw: str) -> None:
        parsed = parse_structured_llm(raw)
        data = parsed.get("treasure") if parsed else None
        if not isinstance(data, dict):
            return
        try:
            position = Pos(int(data["x"]), int(data["y"]))
            opening_day = int(data["day"])
            confidence = float(data["confidence"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return
        items = data.get("items")
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            return
        self.position = position
        self.opening_day = opening_day
        self.items = tuple(sorted(items))
        self.confidence = max(0.0, min(confidence, 1.0))

    def can_attempt(self, turn: Turn, pioneer: Unit, config: StrategyConfig) -> bool:
        if (
            self.exhausted
            or self.position is None
            or self.opening_day is None
            or turn.day_index < self.opening_day
            or self.confidence < config.treasure_confidence_threshold
            or pioneer.pos is None
            or pioneer.pos.distance_to(self.position) > 1
        ):
            return False
        inventory = list(pioneer.backpack)
        for item in self.items:
            if item not in inventory:
                return False
            inventory.remove(item)
        signature = (self.position, self.opening_day, self.items)
        return signature not in self.attempted

    def action(self, turn: Turn, pioneer: Unit, config: StrategyConfig) -> Action | None:
        if not self.can_attempt(turn, pioneer, config) or self.position is None:
            return None
        signature = (self.position, self.opening_day or 0, self.items)
        self.attempted.add(signature)
        return Action(
            pioneer.unit_id,
            ActionType.SUMMON_TREASURE,
            targets=(self.position,),
            items=self.items,
        )
