from __future__ import annotations

import unittest
from dataclasses import replace

from solution.combat import ControllerAssignment, controllers_needed, plan_attacks
from solution.defense import own_threats
from solution.economy import DefenseBudget
from solution.geometry import Pos
from solution.models import Turn
from solution.opponent import OpponentModel, StrategyMode, choose_mode, desired_boss_orders
from solution.rules import DEFAULT_CONFIG
from tests.helpers import role, synthetic_turn


def combat_turn(*, rocket_level: int = 2, rocket_cooldown: int = 0) -> Turn:
    raw = synthetic_turn(round_no=71)
    raw["teamOur"]["roles"] = [
        role(1, "worker", 3, 3),
        role(2, "worker", 3, 4),
        role(3, "pioneer", 4, 3),
        role(10, "station", 0, 9, health=1500, level=1),
        role(11, "railgun", 4, 4, health=1000, level=2, attack_range=10),
        role(12, "rocket", 5, 3, health=1000, level=rocket_level, cooldown=rocket_cooldown, attack_range=20),
    ]
    raw["robot"]["roles"] = []
    raw["phaseTask"] = ""
    return Turn.from_raw(raw)


def robot(robot_id: int, x: int, y: int, health: int, kind: str = "smallRobot", target: str = "challenger") -> dict:
    return {
        "id": robot_id,
        "pos": {"x": x, "y": y},
        "roleType": kind,
        "health": health,
        "attackPower": 40 if kind == "bossRobot" else 5,
        "attackRange": 3,
        "targetTeam": target,
    }


class CombatTests(unittest.TestCase):
    def test_partial_controller_release(self) -> None:
        turn = combat_turn()
        weapons = tuple(unit for unit in turn.team_our.roles if unit.is_weapon)
        one_small = Turn.from_raw({**synthetic_turn(round_no=71), "robot": {"roles": [robot(1, 7, 7, 10)]}}).robots
        self.assertEqual(controllers_needed(weapons, one_small), 1)
        self.assertEqual(controllers_needed(weapons, ()), 0)

    def test_cooling_rocket_does_not_attack(self) -> None:
        turn = combat_turn(rocket_cooldown=2)
        rocket_unit = turn.team_our.unit(12)
        pioneer = turn.team_our.unit(3)
        raw = synthetic_turn(round_no=71)
        raw["robot"]["roles"] = [robot(30, 7, 3, 100, "largeRobot")]
        robots = Turn.from_raw(raw).robots
        actions = plan_attacks(turn, (ControllerAssignment(rocket_unit, pioneer),), robots)
        self.assertEqual(actions, ())

    def test_rocket_level_two_can_overlap_on_boss(self) -> None:
        turn = combat_turn(rocket_level=2)
        rocket_unit = turn.team_our.unit(12)
        pioneer = turn.team_our.unit(3)
        raw = synthetic_turn(round_no=71)
        raw["robot"]["roles"] = [robot(30, 8, 3, 800, "bossRobot")]
        robots = Turn.from_raw(raw).robots
        action = plan_attacks(turn, (ControllerAssignment(rocket_unit, pioneer),), robots)[0]
        self.assertEqual(action.targets, (Pos(8, 3), Pos(8, 3)))

    def test_railgun_prefers_penetrating_line(self) -> None:
        turn = combat_turn()
        railgun = turn.team_our.unit(11)
        worker = turn.team_our.unit(2)
        raw = synthetic_turn(round_no=71)
        raw["robot"]["roles"] = [
            robot(31, 6, 4, 10),
            robot(32, 8, 4, 40, "middleRobot"),
            robot(33, 5, 7, 40),
        ]
        robots = Turn.from_raw(raw).robots
        action = plan_attacks(turn, (ControllerAssignment(railgun, worker),), robots)[0]
        self.assertEqual(action.targets[0].y, 4)

    def test_two_weapons_avoid_wasting_both_shots_on_two_lethal_targets(self) -> None:
        raw = synthetic_turn(round_no=71)
        raw["teamOur"]["roles"] = [
            role(1, "worker", 2, 2),
            role(2, "worker", 2, 4),
            role(10, "station", 0, 9, health=1500, level=1),
            role(11, "railgun", 3, 2, health=1000, level=1, attack_range=10),
            role(12, "railgun", 3, 4, health=1000, level=1, attack_range=10),
        ]
        raw["robot"]["roles"] = [robot(31, 6, 2, 10), robot(32, 6, 5, 10)]
        turn = Turn.from_raw(raw)
        assignments = (
            ControllerAssignment(turn.team_our.unit(11), turn.team_our.unit(1)),
            ControllerAssignment(turn.team_our.unit(12), turn.team_our.unit(2)),
        )
        actions = plan_attacks(turn, assignments, turn.robots)
        self.assertEqual(len(actions), 2)
        self.assertNotEqual(actions[0].targets, actions[1].targets)

    def test_boss_threat_outweighs_small_robot_at_similar_distance(self) -> None:
        turn = combat_turn()
        railgun = turn.team_our.unit(11)
        worker = turn.team_our.unit(2)
        raw = synthetic_turn(round_no=71)
        raw["robot"]["roles"] = [
            robot(31, 7, 4, 40, "smallRobot"),
            robot(32, 7, 5, 800, "bossRobot"),
        ]
        robots = Turn.from_raw(raw).robots
        action = plan_attacks(turn, (ControllerAssignment(railgun, worker),), robots)[0]
        self.assertEqual(action.targets[0], Pos(7, 5))

    def test_missing_target_team_is_not_used_for_cross_map_guess(self) -> None:
        raw = synthetic_turn(round_no=71)
        raw["robot"]["roles"] = [robot(31, 11, 0, 40, target="")]
        turn = Turn.from_raw(raw)
        self.assertEqual(own_threats(turn), ())


class OpponentTests(unittest.TestCase):
    def test_missing_observations_never_buy_boss(self) -> None:
        raw = synthetic_turn(round_no=1)
        raw["weaponShopList"].append({"name": "BossRobotSummonOrder", "price": 200})
        raw["teamOur"]["goldNum"] = 1000
        turn = Turn.from_raw(raw)
        budget = DefenseBudget(0, 25, 975, 10)
        self.assertEqual(desired_boss_orders(turn, budget, OpponentModel(), DEFAULT_CONFIG), 0)

    def test_one_boss_when_one_is_enough(self) -> None:
        raw = synthetic_turn(round_no=1)
        raw["weaponShopList"].append({"name": "BossRobotSummonOrder", "price": 200})
        turn = Turn.from_raw(raw)
        opponent = OpponentModel(observations=3, late_threat_turns=2)
        enabled = replace(DEFAULT_CONFIG, allow_summon_pressure=True)
        self.assertEqual(desired_boss_orders(turn, DefenseBudget(0, 25, 500, 9), opponent, enabled), 1)

    def test_two_boss_burst_requires_more_weakness_and_capital(self) -> None:
        raw = synthetic_turn(round_no=1)
        raw["weaponShopList"].append({"name": "BossRobotSummonOrder", "price": 200})
        turn = Turn.from_raw(raw)
        opponent = OpponentModel(observations=5, late_threat_turns=4)
        enabled = replace(DEFAULT_CONFIG, allow_summon_pressure=True)
        self.assertEqual(desired_boss_orders(turn, DefenseBudget(0, 25, 500, 9), opponent, enabled), 2)

    def test_mode_switches_to_defend_on_critical_margin(self) -> None:
        turn = combat_turn()
        mode = choose_mode(turn, DefenseBudget(0, 25, 0, 1), 3, OpponentModel(), DEFAULT_CONFIG)
        self.assertEqual(mode, StrategyMode.DEFEND)

    def test_mode_switches_to_pressure_only_with_evidence(self) -> None:
        turn = combat_turn()
        opponent = OpponentModel(observations=5, late_threat_turns=3)
        mode = choose_mode(turn, DefenseBudget(0, 25, 500, 10), 0, opponent, DEFAULT_CONFIG)
        self.assertEqual(mode, StrategyMode.PRESSURE)

    def test_opponent_damage_rate_is_estimated_from_runtime_health(self) -> None:
        model = OpponentModel()
        raw = synthetic_turn(round_no=100)
        raw["robot"]["roles"] = [robot(31, 8, 8, 100, "largeRobot", "defender")]
        model.update(Turn.from_raw(raw), generation=1)
        raw = synthetic_turn(round_no=101)
        raw["robot"]["roles"] = [robot(31, 8, 8, 70, "largeRobot", "defender")]
        model.update(Turn.from_raw(raw), generation=1)
        self.assertEqual(model.estimated_dps, 30.0)


if __name__ == "__main__":
    unittest.main()
