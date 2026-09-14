from __future__ import annotations

import unittest

from solution.geometry import CoordinateFrame, Pos, station_footprint
from solution.models import Turn
from solution.rules import TEAM_CHALLENGER, TEAM_DEFENDER, is_day_round
from tests.helpers import synthetic_turn


class GeometryTests(unittest.TestCase):
    def test_chebyshev_distance(self) -> None:
        self.assertEqual(Pos(1, 1).distance_to(Pos(4, 3)), 3)

    def test_station_footprint_uses_top_left_anchor(self) -> None:
        self.assertEqual(
            set(station_footprint(Pos(5, 6))),
            {Pos(5, 6), Pos(6, 6), Pos(5, 5), Pos(6, 5)},
        )

    def test_side_normalization_round_trips(self) -> None:
        challenger = CoordinateFrame(41, 32, TEAM_CHALLENGER)
        defender = CoordinateFrame(41, 32, TEAM_DEFENDER)
        point = Pos(3, 7)

        self.assertEqual(challenger.normalize(point), point)
        self.assertEqual(defender.normalize(point), Pos(37, 24))
        self.assertEqual(
            defender.denormalize(defender.normalize(point)),
            point,
        )


class TurnParsingTests(unittest.TestCase):
    def test_full_synthetic_turn_is_parsed(self) -> None:
        turn = Turn.from_raw(synthetic_turn())

        self.assertEqual(turn.round_no, 71)
        self.assertFalse(turn.is_day)
        self.assertEqual(turn.map_info.width, 12)
        self.assertEqual(turn.team_our.gold, 75)
        self.assertEqual(turn.team_our.unit(1).backpack, ("stone", "stone"))
        self.assertEqual(turn.robots[0].target_team, "challenger")
        self.assertEqual(turn.last_action_results, {1: True})
        self.assertEqual(turn.vendor_shop[1].price, 3)

    def test_missing_and_wrong_optional_fields_are_safe(self) -> None:
        turn = Turn.from_raw(
            {
                "roundNo": "bad",
                "mapInfo": {"width": None, "height": 10, "zones": "bad"},
                "teamOur": {"roles": [None, {"unknown": 1}]},
                "robot": None,
                "errors": {},
                "futureField": {"ignored": True},
            }
        )

        self.assertEqual(turn.round_no, 0)
        self.assertEqual(turn.map_info.width, 0)
        self.assertEqual(turn.map_info.zones, ())
        self.assertEqual(len(turn.team_our.roles), 2)
        self.assertEqual(turn.robots, ())
        self.assertTrue(turn.is_day)

    def test_day_night_boundaries(self) -> None:
        self.assertTrue(is_day_round(1))
        self.assertTrue(is_day_round(70))
        self.assertFalse(is_day_round(71))
        self.assertFalse(is_day_round(130))
        self.assertTrue(is_day_round(131))


if __name__ == "__main__":
    unittest.main()
