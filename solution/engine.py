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
                        "taskReason": str(getattr(self.planner.tasks, "diagnostic", "unknown")),
                        "taskCommandExit": self.planner.tasks.command_exit,
                        "taskCommandCategory": self.planner.tasks.command_category,
                        "taskCommandKind": self.planner.tasks.command_kind,
                        "taskRejectReason": self.planner.tasks.reject_reason,
                        "taskWorkspaceReady": self.planner.tasks.context.resolved,
                        "taskDocumentCount": len(self.planner.tasks.context.documents),
                        "taskEvidenceReady": self.planner.tasks.context.executed,
                        "taskStage": self.planner.tasks.task_stage,
                        "taskAnswerChecked": self.planner.tasks.context.candidate_checked,
                        "taskSchemaPass": self.planner.tasks.context.schema_pass,
                        "taskIncompleteDocuments": len(self.planner.tasks.context.incomplete),
                        "taskRejectedAnswers": len(self.planner.tasks.rejected_answers),
                        "taskCompleted": getattr(self.planner.tasks, "completed", 0),
                        "taskFailed": getattr(self.planner.tasks, "failed", 0),
                        "economy": dict(self.planner.economy.activity),
                        "mineTargets": {str(actor):[p.x,p.y] for actor,p in self.planner.economy.mines.items()},
                        "recalledRoles": sorted(actor for actor,day in self.state.recalled_roles.items() if day==turn.day_index),
                        "engineer": self.planner.engineer_id,
                        "carrier": self.planner.logistics.carrier_id,
                        "plannerFailures": self.planner.failure_count,
                        "logisticsStage": self.planner.logistics.stage,
                        "deliveryCount": len(self.planner.logistics.orders),
                        "marketWindows": [[w.ore,w.start_day,w.end_day,w.price,w.closed,w.rising] for w in self.state.market.windows],
                        "weapons": self._weapon_diagnostics(turn, response),
                    },
                )
            except Exception:
                pass  # Observability failures must not erase valid actions.
            return response
        finally:
            self._lock.release()

    @staticmethod
    def _weapon_diagnostics(turn, response):
        from .defense import own_threats
        threats = own_threats(turn)
        result = []
        for weapon in turn.team_our.roles:
            if not weapon.is_weapon or not weapon.alive or weapon.pos is None:
                continue
            if str(weapon.unit_id) in response["roleCommandMap"]:
                reason = "firing"
            elif turn.is_day:
                reason = "day"
            elif not threats:
                reason = "clear"
            elif not any(r.pos and r.pos.distance_to(weapon.pos)<=1 for r in turn.controllable):
                reason = "no_operator"
            elif weapon.cooldown:
                reason = "cooldown"
            elif not any(r.pos and r.pos.distance_to(weapon.pos)<=weapon.attack_range for r in threats):
                reason = "out_of_range"
            else:
                reason = "allocation_or_validation"
            result.append([weapon.role_type,[weapon.pos.x,weapon.pos.y],reason])
        return result

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
