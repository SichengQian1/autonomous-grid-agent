from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from solution.actions import Action, ActionType, Decision
from solution.geometry import Pos
from solution.models import Turn
from solution.state import WorldState
from tests.helpers import synthetic_turn
from tools.diagnostics.synthetic_replay import run_synthetic_match


class FeedbackTests(unittest.TestCase):
    def test_failed_night_economy_pauses_only_failed_role(self) -> None:
        state = WorldState()
        turn = Turn.from_raw(synthetic_turn(round_no=100))
        state.ingest(turn)
        state.record_decision(
            turn,
            Decision((Action(1, ActionType.COLLECT, targets=(Pos(2, 2),)),)),
        )
        raw = synthetic_turn(round_no=101)
        raw["lastRoundRoleActionResults"] = {"1": False}
        state.ingest(Turn.from_raw(raw))
        self.assertFalse(state.night_economy_disabled)
        self.assertEqual(state.night_role_pauses,{1:104})

    def test_new_match_clears_failed_sites_and_old_state(self) -> None:
        state = WorldState()
        state.ingest(Turn.from_raw(synthetic_turn(round_no=5)))
        state.failed_build_sites.add(Pos(1, 1))
        raw = synthetic_turn(round_no=1)
        raw["teamOur"]["teamId"] = "different-synthetic-team"
        state.ingest(Turn.from_raw(raw))
        self.assertEqual(state.failed_build_sites, set())

    def test_robot_behind_normalized_base_invalidates_fixed_opening(self) -> None:
        raw = synthetic_turn(round_no=71)
        station = next(item for item in raw["teamOur"]["roles"] if item["roleType"] == "station")
        station["pos"] = {"x": 3, "y": 9}
        raw["robot"]["roles"][0]["pos"] = {"x": 0, "y": 8}
        state = WorldState()
        state.ingest(Turn.from_raw(raw))
        self.assertTrue(state.rear_threat_observed)


class SyntheticReplayTests(unittest.TestCase):
    def test_strategy_fallback_is_counted_as_a_replay_failure(self):
        with patch('solution.planner.CompetitionPlanner._day',side_effect=ValueError('synthetic')):
            with patch('solution.planner.LOGGER.warning'):
                stats=run_synthetic_match(2)
        self.assertEqual(stats.planner_failures,2)

    def test_full_ten_day_replay_has_no_protocol_failures(self) -> None:
        for side in ("challenger", "defender"):
            stats = run_synthetic_match(1300, side)
            self.assertEqual(stats.rounds, 1300)
            self.assertEqual(stats.invalid_responses, 0)
            self.assertEqual(stats.dropped_actions, 0)
            self.assertEqual(stats.failed_actions, 0)
            self.assertEqual(stats.planner_failures, 0)
            self.assertGreater(stats.active_rounds, 0)
            self.assertEqual(stats.final_weapon_count, 3)
            self.assertGreaterEqual(stats.minimum_gold, 0)
            self.assertLess(stats.max_decision_ms, 1000)
            json.dumps(stats.__dict__)


if __name__ == "__main__":
    unittest.main()
