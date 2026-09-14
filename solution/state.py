from __future__ import annotations

from dataclasses import dataclass, field

from .models import ErrorFeedback, Turn
from .actions import Action
from .rules import ROUNDS_PER_DAY
from .resources import MiningCalendar


@dataclass(slots=True)
class WorldState:
    generation: int = 0
    match_key: tuple[str, str] | None = None
    last_round_no: int = 0
    turns_seen: int = 0
    official_news_history: list[tuple[int, str]] = field(default_factory=list)
    folk_legend_history: list[tuple[int, str]] = field(default_factory=list)
    last_action_results: dict[int, bool] = field(default_factory=dict)
    last_errors: tuple[ErrorFeedback, ...] = ()
    last_command_result: str = ""
    last_treasure_result: int = 0
    previous_actions: tuple[Action, ...] = ()
    blocked_actions: dict[Action, int] = field(default_factory=dict)
    mining: MiningCalendar = field(default_factory=MiningCalendar)

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
        self.previous_actions = ()
        self.blocked_actions.clear()
        self.mining = MiningCalendar()

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
        self.mining.observe(turn.round_no, turn.world_news.official_news)
        for action in self.previous_actions:
            if turn.last_action_results.get(action.actor_id) is False:
                self.blocked_actions[action] = turn.round_no + 8
        self.blocked_actions = {a: until for a, until in self.blocked_actions.items() if until > turn.round_no}
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

    @staticmethod
    def _append_unique(
        history: list[tuple[int, str]],
        round_no: int,
        value: str,
    ) -> None:
        if not value:
            return
        value = value[:16000]
        if not history or history[-1][1] != value:
            history.append((round_no, value))
            del history[:-256]

    def action_blocked(self, action: Action, round_no: int) -> bool:
        return self.blocked_actions.get(action, 0) > round_no


@dataclass(slots=True)
class LlmBudget:
    day_index: int = -1
    calls_used: int = 0
    pending_since_round: int | None = None

    def refresh(self, turn: Turn) -> None:
        current_day = max(turn.round_no - 1, 0) // ROUNDS_PER_DAY
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
