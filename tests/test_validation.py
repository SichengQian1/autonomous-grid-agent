from __future__ import annotations

import json
import unittest

from solution.actions import Action, ActionType, Decision
from solution.geometry import Pos
from solution.models import Turn
from solution.protocol import serialize_decision
from solution.validation import ActionValidator
from tests.helpers import synthetic_turn


class ActionValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.turn = Turn.from_raw(synthetic_turn(round_no=71))
        self.validator = ActionValidator()

    def validate(self, *actions: Action):
        return self.validator.validate(self.turn, Decision(actions=actions))

    def test_legal_move_is_accepted(self) -> None:
        result = self.validate(
            Action(1, ActionType.MOVE, targets=(Pos(1, 2),))
        )
        self.assertEqual(len(result.actions), 1)
        self.assertEqual(result.issues, ())

    def test_non_adjacent_move_is_dropped(self) -> None:
        result = self.validate(
            Action(1, ActionType.MOVE, targets=(Pos(3, 3),))
        )
        self.assertEqual(result.actions, ())
        self.assertIn("adjacent", result.issues[0].reason)

    def test_night_railgun_attack_is_accepted(self) -> None:
        result = self.validate(
            Action(
                4,
                ActionType.ATTACK,
                controller_id=1,
                targets=(Pos(7, 1),),
            )
        )
        self.assertEqual(len(result.actions), 1)

    def test_day_attack_is_dropped(self) -> None:
        turn = Turn.from_raw(synthetic_turn(round_no=1))
        result = self.validator.validate(
            turn,
            Decision(
                actions=(
                    Action(
                        4,
                        ActionType.ATTACK,
                        controller_id=1,
                        targets=(Pos(7, 1),),
                    ),
                )
            ),
        )
        self.assertEqual(result.actions, ())
        self.assertIn("daytime", result.issues[0].reason)

    def test_night_build_is_dropped(self) -> None:
        result = self.validate(
            Action(
                1,
                ActionType.BUILD,
                targets=(Pos(1, 2),),
                name="wall",
            )
        )
        self.assertEqual(result.actions, ())
        self.assertIn("night", result.issues[0].reason)

    def test_rocket_target_count_must_match_level(self) -> None:
        result = self.validate(
            Action(
                5,
                ActionType.ATTACK,
                controller_id=2,
                targets=(Pos(8, 8),),
            )
        )
        self.assertEqual(result.actions, ())
        self.assertIn("target count", result.issues[0].reason)

    def test_cooling_rocket_is_dropped(self) -> None:
        raw = synthetic_turn(round_no=71)
        next(role for role in raw["teamOur"]["roles"] if role["id"] == 5)[
            "cooldown"
        ] = 2
        turn = Turn.from_raw(raw)
        result = self.validator.validate(
            turn,
            Decision(
                actions=(
                    Action(
                        5,
                        ActionType.ATTACK,
                        controller_id=2,
                        targets=(Pos(8, 8), Pos(8, 8)),
                    ),
                )
            ),
        )
        self.assertEqual(result.actions, ())
        self.assertIn("cooling", result.issues[0].reason)

    def test_gatling_rejects_targets_wider_than_ninety_degrees(self) -> None:
        result = self.validate(
            Action(
                6,
                ActionType.ATTACK,
                controller_id=7,
                targets=(Pos(6, 4), Pos(2, 4)),
            )
        )
        self.assertEqual(result.actions, ())
        self.assertIn("90-degree", result.issues[0].reason)

    def test_one_controller_cannot_act_and_control_a_weapon(self) -> None:
        result = self.validate(
            Action(1, ActionType.MOVE, targets=(Pos(1, 2),)),
            Action(
                4,
                ActionType.ATTACK,
                controller_id=1,
                targets=(Pos(7, 1),),
            ),
        )
        self.assertEqual(len(result.actions), 1)
        self.assertIn("also has a role action", result.issues[0].reason)

    def test_collect_requires_a_known_resource(self) -> None:
        accepted = self.validate(
            Action(1, ActionType.COLLECT, targets=(Pos(2, 2),))
        )
        rejected = self.validate(
            Action(1, ActionType.COLLECT, targets=(Pos(1, 2),))
        )
        self.assertEqual(len(accepted.actions), 1)
        self.assertEqual(rejected.actions, ())

    def test_sacrificed_item_must_exist(self) -> None:
        result = self.validate(
            Action(
                2,
                ActionType.SUMMON_TREASURE,
                targets=(Pos(3, 3),),
                items=("Missing",),
            )
        )
        self.assertEqual(result.actions, ())
        self.assertIn("backpack", result.issues[0].reason)

    def test_serializer_uses_string_ids_and_controller(self) -> None:
        response, issues = serialize_decision(
            self.turn,
            Decision(
                actions=(
                    Action(
                        4,
                        ActionType.ATTACK,
                        controller_id=1,
                        targets=(Pos(7, 1),),
                    ),
                )
            ),
        )

        self.assertEqual(issues, ())
        self.assertEqual(response["roleCommandMap"]["4"]["controllerId"], "1")
        json.dumps(response)

    def test_shared_gold_and_weapon_limit_are_validated_across_actions(self) -> None:
        raw = synthetic_turn(round_no=1)
        raw["teamOur"]["goldNum"] = 50
        raw["mapInfo"]["zones"] = []
        raw["teamOur"]["roles"] = [
            {
                "id": actor_id,
                "pos": {"x": actor_id, "y": 1},
                "roleType": "worker",
                "health": 220,
                "backPackCapability": 100,
                "backpack": [],
            }
            for actor_id in (1, 2, 3)
        ]
        raw["teamOur"]["roles"].append({"id": 10, "roleType": "station", "pos": {"x": 2, "y": 4}, "health": 1500, "level": 1})
        turn = Turn.from_raw(raw)
        result = self.validator.validate(
            turn,
            Decision(
                tuple(
                    Action(
                        actor_id,
                        ActionType.BUILD,
                        targets=(Pos(actor_id, 2),),
                        name="railgun",
                    )
                    for actor_id in (1, 2, 3)
                )
            ),
        )
        self.assertEqual(len(result.actions), 2)
        self.assertIn("gold", result.issues[0].reason)


if __name__ == "__main__":
    unittest.main()
