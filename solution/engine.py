from __future__ import annotations

import logging
import hashlib
import json
import copy
import threading
import time
from typing import Any

from .actions import Decision
from .models import Turn
from .protocol import safe_response, serialize_decision
from .rules import DEFAULT_CONFIG, StrategyConfig
from .state import LlmBudget, WorldState
from .validation import ActionValidator
from .strategy import BaselinePlanner


LOGGER = logging.getLogger(__name__)


class AgentEngine:
    def __init__(self, config: StrategyConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self.state = WorldState()
        self.llm_budget = LlmBudget()
        self.validator = ActionValidator()
        self.planner = BaselinePlanner()
        self._cached_key = ""
        self._cached_response: dict[str, Any] = {}
        self._lock = threading.Lock()

    def decide(self, payload: dict[str, Any]) -> dict[str, Any]:
        started_at = time.monotonic()
        if not self._lock.acquire(blocking=False):
            LOGGER.warning("concurrent turn request returned the safe fallback")
            return safe_response()
        try:
            cache_key = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if cache_key == self._cached_key:
                return copy.deepcopy(self._cached_response)
            turn = Turn.from_raw(payload)
            if (turn.map_info.width > 256 or turn.map_info.height > 256 or len(turn.robots) > 2048
                    or len(turn.map_info.zones) > 8192 or len(turn.team_our.roles) > 1024):
                return safe_response()
            incoming_key = (turn.team_our.team_id, turn.team_our.team_type)
            if incoming_key == self.state.match_key and 1 < turn.round_no < self.state.last_round_no:
                return safe_response()
            generation = self.state.generation
            self.state.ingest(turn)
            if generation != self.state.generation:
                self.llm_budget = LlmBudget()
            self.llm_budget.refresh(turn)
            if turn.llm_response:
                self.llm_budget.mark_response_received()

            decision = self._plan(turn, started_at)
            response, issues = serialize_decision(turn, decision, self.validator)
            self.state.previous_actions = self.validator.validate(turn, decision).actions
            if issues:
                LOGGER.warning(
                    "dropped %d unsafe action(s) at round %d",
                    len(issues),
                    turn.round_no,
                )
            self._cached_key, self._cached_response = cache_key, copy.deepcopy(response)
            return response
        finally:
            self._lock.release()

    def _plan(self, turn: Turn, started_at: float) -> Decision:
        if self._deadline_reached(started_at):
            return Decision()
        return self.planner.plan(turn, self.state, self.llm_budget, self.config,
                                 started_at + self.config.normal_turn_budget_seconds)

    def _deadline_reached(self, started_at: float) -> bool:
        return time.monotonic() - started_at >= self.config.normal_turn_budget_seconds


_ENGINE = AgentEngine()


def configure_engine(config: StrategyConfig) -> None:
    global _ENGINE
    _ENGINE = AgentEngine(config)


def decide_payload(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return _ENGINE.decide(payload)
    except Exception:
        LOGGER.exception("decision engine failed")
        return safe_response()
