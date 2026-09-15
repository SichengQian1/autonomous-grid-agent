from __future__ import annotations

from dataclasses import dataclass, field

from .actions import Action, ActionType, Decision
from .geometry import Pos
from .models import ErrorFeedback, Turn


@dataclass(slots=True)
class WorldState:
    match_key: tuple[str, str] | None = None
    last_round_no: int = 0
    turns_seen: int = 0
    official_news_history: list[tuple[int, str]] = field(default_factory=list)
    folk_legend_history: list[tuple[int, str]] = field(default_factory=list)
    last_action_results: dict[int, bool] = field(default_factory=dict)
    last_errors: tuple[ErrorFeedback, ...] = ()
    last_command_result: str = ""
    last_treasure_result: int = 0
    generation: int = 0
    pending_actions: dict[int, tuple[int, Action, bool]] = field(default_factory=dict)
    failed_build_sites: set[Pos] = field(default_factory=set)
    failed_move_counts: dict[int, int] = field(default_factory=dict)
    night_economy_failures: int = 0
    night_economy_disabled: bool = False
    rear_threat_observed: bool = False
    previous_station_health: int | None = None
    recall_day: int = -1

    def reset(self, turn: Turn) -> None:
        self.generation += 1
        self.match_key = (turn.team_our.team_id, turn.team_our.team_type)
        self.last_round_no = 0
        self.turns_seen = 0
        self.official_news_history.clear()
        self.folk_legend_history.clear()
        self.last_action_results.clear()
        self.last_errors = ()
        self.last_command_result = ""
        self.last_treasure_result = 0
        self.pending_actions.clear()
        self.failed_build_sites.clear()
        self.failed_move_counts.clear()
        self.night_economy_failures = 0
        self.night_economy_disabled = False
        self.rear_threat_observed = False
        self.previous_station_health = None
        self.recall_day = -1

    def ingest(self, turn: Turn) -> None:
        incoming_key = (turn.team_our.team_id, turn.team_our.team_type)
        new_match = self.match_key != incoming_key
        restarted_rounds = (
            self.match_key == incoming_key
            and self.last_round_no > 1
            and turn.round_no <= 1
        )
        if new_match or restarted_rounds:
            self.reset(turn)

        self.match_key = incoming_key
        if turn.round_no < self.last_round_no:
            return
        if turn.round_no > self.last_round_no:
            self.turns_seen += 1
        self.last_round_no = turn.round_no
        self.last_action_results = dict(turn.last_action_results)
        self.last_errors = turn.errors
        self.last_command_result = turn.last_command_result
        self.last_treasure_result = turn.last_summon_treasure_result
        self._consume_action_feedback(turn)
        self._observe_rear_threat(turn)
        self._append_unique(
            self.official_news_history,
            turn.round_no,
            turn.world_news.official_news,
        )
        self._append_unique(
            self.folk_legend_history,
            turn.round_no,
            turn.world_news.folk_legends,
        )

        station = turn.team_our.station()
        self.previous_station_health = station.health if station is not None else None

    def record_decision(self, turn: Turn, decision: Decision) -> None:
        for action in decision.actions:
            self.pending_actions[action.actor_id] = (
                turn.round_no,
                action,
                not turn.is_day,
            )

    def _consume_action_feedback(self, turn: Turn) -> None:
        self.pending_actions = {
            actor_id: pending
            for actor_id, pending in self.pending_actions.items()
            if turn.round_no - pending[0] <= 2
        }
        if not turn.last_action_results:
            return
        for actor_id, succeeded in turn.last_action_results.items():
            pending = self.pending_actions.pop(actor_id, None)
            if pending is None:
                continue
            _, action, was_night = pending
            if succeeded:
                self.failed_move_counts.pop(actor_id, None)
                continue
            if action.action_type == ActionType.BUILD and action.targets:
                self.failed_build_sites.add(action.targets[0])
            if action.action_type == ActionType.MOVE:
                self.failed_move_counts[actor_id] = self.failed_move_counts.get(actor_id, 0) + 1
            if was_night and action.action_type in {
                ActionType.COLLECT,
                ActionType.SELL,
                ActionType.BUY,
            }:
                self.night_economy_failures += 1
                self.night_economy_disabled = True

    def _observe_rear_threat(self, turn: Turn) -> None:
        station = turn.team_our.station()
        if station is None or station.pos is None:
            return
        frame = turn.coordinate_frame
        station_x = max(frame.normalize(cell).x for cell in station.footprint())
        if (
            self.previous_station_health is not None
            and station.health < self.previous_station_health
            and not any(
                robot.pos is not None
                and frame.normalize(robot.pos).x > station_x
                for robot in turn.robots
                if robot.health > 0
                and (not robot.target_team or robot.target_team == turn.team_our.team_type)
            )
        ):
            self.rear_threat_observed = True
        for robot in turn.robots:
            if robot.health <= 0 or robot.pos is None:
                continue
            if robot.target_team and robot.target_team != turn.team_our.team_type:
                continue
            if frame.normalize(robot.pos).x < station_x - 1:
                self.rear_threat_observed = True
                return

    @staticmethod
    def _append_unique(
        history: list[tuple[int, str]],
        round_no: int,
        value: str,
    ) -> None:
        if not value:
            return
        if not history or history[-1][1] != value:
            history.append((round_no, value))


@dataclass(slots=True)
class LlmBudget:
    day_index: int = -1
    calls_used: int = 0
    pending_since_round: int | None = None

    def refresh(self, turn: Turn) -> None:
        current_day = max(turn.round_no - 1, 0) // 130
        if current_day != self.day_index:
            self.day_index = current_day
            self.calls_used = 0
            self.pending_since_round = None
        elif (
            self.pending_since_round is not None
            and turn.round_no > self.pending_since_round
        ):
            # A missing or empty response must not block future calls forever.
            self.pending_since_round = None

    def can_call(self, task_active: bool) -> bool:
        return self.pending_since_round is None and (
            task_active or self.calls_used < 3
        )

    def mark_requested(self, task_active: bool, round_no: int) -> None:
        self.pending_since_round = round_no
        if not task_active:
            self.calls_used += 1

    def mark_response_received(self) -> None:
        self.pending_since_round = None
