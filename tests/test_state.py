from __future__ import annotations

import unittest

from solution.models import Turn
from solution.state import LlmBudget, WorldState
from tests.helpers import synthetic_turn


class WorldStateTests(unittest.TestCase):
    def test_repeated_news_is_stored_once(self) -> None:
        state = WorldState()
        state.ingest(Turn.from_raw(synthetic_turn(round_no=1)))
        state.ingest(Turn.from_raw(synthetic_turn(round_no=2)))

        self.assertEqual(len(state.official_news_history), 1)
        self.assertEqual(len(state.folk_legend_history), 1)
        self.assertEqual(state.turns_seen, 2)

    def test_new_match_resets_history(self) -> None:
        state = WorldState()
        state.ingest(Turn.from_raw(synthetic_turn(round_no=5)))
        restarted = synthetic_turn(round_no=1)
        restarted["worldNews"]["officialNews"] = "new synthetic match"
        state.ingest(Turn.from_raw(restarted))

        self.assertEqual(state.official_news_history, [(1, "new synthetic match")])
        self.assertEqual(state.turns_seen, 1)


class LlmBudgetTests(unittest.TestCase):
    def test_normal_calls_are_limited_to_three_per_day(self) -> None:
        budget = LlmBudget()
        turn = Turn.from_raw(synthetic_turn(round_no=1))
        budget.refresh(turn)

        for round_no in range(1, 4):
            self.assertTrue(budget.can_call(task_active=False))
            budget.mark_requested(task_active=False, round_no=round_no)
            budget.refresh(Turn.from_raw(synthetic_turn(round_no=round_no + 1)))
        self.assertFalse(budget.can_call(task_active=False))
        self.assertTrue(budget.can_call(task_active=True))

    def test_empty_delayed_response_does_not_block_forever(self) -> None:
        budget = LlmBudget()
        budget.refresh(Turn.from_raw(synthetic_turn(round_no=10)))
        budget.mark_requested(task_active=False, round_no=10)
        self.assertFalse(budget.can_call(task_active=False))

        budget.refresh(Turn.from_raw(synthetic_turn(round_no=11)))
        self.assertTrue(budget.can_call(task_active=False))

    def test_budget_resets_on_next_day(self) -> None:
        budget = LlmBudget()
        budget.refresh(Turn.from_raw(synthetic_turn(round_no=1)))
        budget.calls_used = 3
        self.assertFalse(budget.can_call(task_active=False))

        budget.refresh(Turn.from_raw(synthetic_turn(round_no=131)))
        self.assertEqual(budget.calls_used, 0)
        self.assertTrue(budget.can_call(task_active=False))


if __name__ == "__main__":
    unittest.main()
