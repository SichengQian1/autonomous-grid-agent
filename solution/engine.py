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
from .validation import ActionValidator


LOGGER = logging.getLogger(__name__)


class AgentEngine:
    def __init__(self, config: StrategyConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self.state = WorldState()
        self.llm_budget = LlmBudget()
        self.validator = ActionValidator()
        self.planner = CompetitionPlanner()
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
