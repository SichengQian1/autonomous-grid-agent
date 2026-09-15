from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .actions import Decision
from .models import Turn
from .planner import CompetitionPlanner
from .protocol import safe_response, serialize_decision
from .rules import DEFAULT_CONFIG, StrategyConfig
from .state import LlmBudget, WorldState
from .telemetry import Telemetry
from .validation import ActionValidator


LOGGER = logging.getLogger(__name__)


class AgentEngine:
    def __init__(self, config: StrategyConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self.state = WorldState()
        self.llm_budget = LlmBudget()
        self.validator = ActionValidator()
        self.planner = CompetitionPlanner()
        self.telemetry = Telemetry(
            config.telemetry_byte_budget,
            config.telemetry_reserve_bytes,
        )
        self._lock = threading.Lock()

    def decide(self, payload: dict[str, Any]) -> dict[str, Any]:
        started_at = time.monotonic()
        if not self._lock.acquire(blocking=False):
            LOGGER.warning("concurrent turn request returned the safe fallback")
            return safe_response()
        try:
            turn = Turn.from_raw(payload)
            self.state.ingest(turn)
            self.llm_budget.refresh(turn)
            if turn.llm_response:
                self.llm_budget.mark_response_received()

            decision = self._plan(turn, started_at)
            response, issues = serialize_decision(turn, decision, self.validator)
            if issues:
                LOGGER.warning(
                    "dropped %d unsafe action(s) at round %d",
                    len(issues),
                    turn.round_no,
                )
            accepted_ids = {int(actor_id) for actor_id in response["roleCommandMap"]}
            accepted = Decision(
                actions=tuple(
                    action for action in decision.actions if action.actor_id in accepted_ids
                ),
                prompt=decision.prompt,
                execute_command=decision.execute_command,
            )
            self.state.record_decision(turn, accepted)
            try:
                if self.telemetry.generation != self.state.generation:
                    self.telemetry = Telemetry(self.config.telemetry_byte_budget, self.config.telemetry_reserve_bytes,
                                               generation=self.state.generation)
                self.telemetry.record_turn(
                    turn, response,
                    elapsed_ms=int((time.monotonic() - started_at) * 1000),
                    dropped_actions=len(issues),
                    diagnostics={
                        "taskPhase": str(getattr(self.planner.tasks, "phase", "unknown")),
                        "taskCommandSteps": getattr(self.planner.tasks, "command_steps", 0),
                        "failedBuildSites": [[p.x,p.y] for p in sorted(self.state.failed_build_sites)][:32],
                        "validation": [i.reason for i in issues][:6],
                        "rearThreat": self.state.rear_threat_observed,
                    },
                )
            except Exception:
                pass  # Observability failures must not erase valid actions.
            return response
        finally:
            self._lock.release()

    def _plan(self, turn: Turn, started_at: float) -> Decision:
        if self._deadline_reached(started_at):
            return Decision()
        return self.planner.plan(
            turn,
            self.state,
            self.llm_budget,
            self.config,
            lambda: self._deadline_reached(started_at),
        )

    def _deadline_reached(self, started_at: float) -> bool:
        return time.monotonic() - started_at >= self.config.normal_turn_budget_seconds


_ENGINE = AgentEngine()


def decide_payload(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return _ENGINE.decide(payload)
    except Exception:
        LOGGER.exception("decision engine failed")
        return safe_response()
