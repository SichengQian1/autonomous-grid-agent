from __future__ import annotations

import unittest

from solution.actions import Action, ActionType, Decision
from solution.defense import build_defense_layout
from solution.economy import defense_budget, weapon_build_objectives
from solution.geometry import Pos
from solution.models import Turn
from solution.logistics import plan_upgrade_or_repair
from solution.movement import schedule_moves
from solution.planner import CompetitionPlanner
from solution.opponent import OpponentModel, desired_boss_orders
from solution.rules import DEFAULT_CONFIG
from solution.state import WorldState
from tests.helpers import role, synthetic_turn


def opening_turn(*, defender: bool = False, gold: int = 75) -> Turn:
    raw = synthetic_turn(round_no=1)
    raw["teamOur"]["type"] = "defender" if defender else "challenger"
    raw["teamOur"]["goldNum"] = gold
    station = role(10, "station", 10, 1, health=1500, level=1) if defender else role(10, "station", 0, 9, health=1500, level=1)
    raw["teamOur"]["roles"] = [
        role(1, "worker", 2, 5),
        role(2, "worker", 3, 5),
        role(3, "pioneer", 1, 5),
        station,
    ]
    raw["teamOur"]["playerTasks"] = []
    raw["mapInfo"]["zones"] = []
    raw["robot"]["roles"] = []
    raw["phaseTask"] = ""
    raw["weaponShopList"].append({"name": "BossRobotSummonOrder", "price": 200})
    return Turn.from_raw(raw)


class DefenseGeometryTests(unittest.TestCase):
    def assert_normalized_orientation(self, turn: Turn) -> None:
        layout = build_defense_layout(turn)
        station = turn.team_our.station()
        normalized_station = layout.frame.normalize_cells(station.footprint())
        station_min = min(pos.x for pos in normalized_station)
        station_max = max(pos.x for pos in normalized_station)
        normalized_walls = tuple(layout.frame.normalize(pos) for pos in layout.wall_sites)
        normalized_exit = layout.frame.normalize(layout.rear_exit)
        self.assertTrue(normalized_walls)
        self.assertTrue(all(pos.x > station_max for pos in normalized_walls))
        self.assertLessEqual(normalized_exit.x, station_min)
        self.assertNotIn(layout.rear_exit, layout.wall_sites)
        self.assertTrue(set(layout.rear_corridor).isdisjoint(layout.wall_sites))

    def test_upper_left_base_threat_is_on_right(self) -> None:
        self.assert_normalized_orientation(opening_turn(defender=False))

    def test_lower_right_base_threat_is_on_left_but_normalizes_forward(self) -> None:
        self.assert_normalized_orientation(opening_turn(defender=True))

    def test_two_sides_have_mirrored_rear_exit(self) -> None:
        first = build_defense_layout(opening_turn(defender=False))
        second = build_defense_layout(opening_turn(defender=True))
        self.assertLess(first.rear_exit.x, 6)
        self.assertGreater(second.rear_exit.x, 6)

    def test_three_controller_routes_reserve_distinct_next_cells(self) -> None:
        raw = synthetic_turn(round_no=69)
        raw["phaseTask"] = ""
        raw["teamOur"]["roles"] = [
            role(1, "worker", 7, 1),
            role(2, "worker", 7, 2),
            role(3, "pioneer", 7, 3),
            role(10, "station", 0, 9, health=1500, level=1),
            role(11, "railgun", 2, 7, health=1000, level=1, attack_range=6),
            role(12, "railgun", 2, 8, health=1000, level=1, attack_range=6),
            role(13, "rocket", 2, 9, health=1000, level=1, attack_range=10),
        ]
        raw["mapInfo"]["zones"] = []
        turn = Turn.from_raw(raw)
        intents = CompetitionPlanner._controller_intents(turn, 120)
        moves = schedule_moves(turn, intents)
        destinations = [move.targets[0] for move in moves]
        self.assertEqual(len(destinations), len(set(destinations)))

    def test_recall_uses_distance_plus_safety_buffer(self) -> None:
        raw = synthetic_turn(round_no=69)
        raw["phaseTask"] = ""
        turn = Turn.from_raw(raw)
        layout = build_defense_layout(turn)
        self.assertTrue(CompetitionPlanner._recall_needed(turn, layout, DEFAULT_CONFIG))


class ConstructionAndBudgetTests(unittest.TestCase):
    def test_initial_gold_allocates_exactly_three_weapons(self) -> None:
        turn = opening_turn(gold=75)
        objectives = weapon_build_objectives(turn, build_defense_layout(turn), WorldState(), DEFAULT_CONFIG)
        self.assertEqual(tuple(item.name for item in objectives), ("railgun", "railgun", "rocket"))
        self.assertEqual(len({item.site for item in objectives}), 3)

    def test_existing_weapon_is_not_overwritten(self) -> None:
        raw = synthetic_turn(round_no=1)
        raw["teamOur"]["roles"] = [
            role(1, "worker", 2, 5), role(2, "worker", 3, 5),
            role(3, "pioneer", 1, 5), role(10, "station", 0, 9, health=1500, level=1),
            role(11, "railgun", 2, 7, health=1000, level=1, attack_range=6),
        ]
        raw["mapInfo"]["zones"] = []
        raw["teamOur"]["playerTasks"] = []
        raw["phaseTask"] = ""
        turn = Turn.from_raw(raw)
        objectives = weapon_build_objectives(turn, build_defense_layout(turn), WorldState(), DEFAULT_CONFIG)
        self.assertEqual(tuple(item.name for item in objectives), ("railgun", "rocket"))
        self.assertNotIn(Pos(2, 7), {item.site for item in objectives})

    def test_failed_build_site_is_blacklisted(self) -> None:
        turn = opening_turn()
        state = WorldState()
        site = build_defense_layout(turn).weapon_sites[0]
        state.failed_build_sites.add(site)
        objectives = weapon_build_objectives(turn, build_defense_layout(turn), state, DEFAULT_CONFIG)
        self.assertNotIn(site, {item.site for item in objectives})

    def test_feedback_blacklists_failed_build(self) -> None:
        turn = opening_turn()
        state = WorldState()
        state.ingest(turn)
        site = build_defense_layout(turn).weapon_sites[0]
        state.record_decision(turn, Decision((Action(1, ActionType.BUILD, targets=(site,), name="railgun"),)))
        raw = synthetic_turn(round_no=2)
        raw["teamOur"] = synthetic_turn(round_no=1)["teamOur"]
        raw["teamOur"]["teamId"] = turn.team_our.team_id
        raw["lastRoundRoleActionResults"] = {"1": False}
        state.ingest(Turn.from_raw(raw))
        self.assertIn(site, state.failed_build_sites)

    def test_defense_reserve_blocks_boss_purchase(self) -> None:
        turn = opening_turn(gold=199)
        budget = defense_budget(turn, DEFAULT_CONFIG, threat_health=800)
        opponent = OpponentModel(observations=10, late_threat_turns=10)
        self.assertEqual(desired_boss_orders(turn, budget, opponent, DEFAULT_CONFIG), 0)

    def test_upgrade_purchase_uses_only_offensive_budget(self) -> None:
        raw = synthetic_turn(round_no=20)
        raw["phaseTask"] = ""
        raw["teamOur"]["goldNum"] = 100
        raw["weaponShopList"].append({"name": "WeaponUpgradeVoucher1", "price": 100})
        pioneer = next(item for item in raw["teamOur"]["roles"] if item["roleType"] == "pioneer")
        pioneer["pos"] = {"x": 7, "y": 6}
        turn = Turn.from_raw(raw)
        blocked = plan_upgrade_or_repair(turn, turn.team_our.unit(2), defense_budget(turn, DEFAULT_CONFIG))
        allowed = plan_upgrade_or_repair(turn, turn.team_our.unit(2), type(defense_budget(turn, DEFAULT_CONFIG))(0, 0, 100, 10))
        self.assertIsNone(blocked.action)
        self.assertIsNotNone(allowed.action)

    def test_wall_repair_item_can_be_bought_from_runtime_shop(self) -> None:
        raw = synthetic_turn(round_no=20)
        raw["phaseTask"] = ""
        raw["teamOur"]["goldNum"] = 100
        raw["weaponShopList"].append({"name": "WallFixer", "price": 10})
        raw["teamOur"]["roles"].append(role(40, "wall", 6, 6, health=400, level=1))
        pioneer = next(item for item in raw["teamOur"]["roles"] if item["roleType"] == "pioneer")
        pioneer["pos"] = {"x": 7, "y": 6}
        turn = Turn.from_raw(raw)
        budget = type(defense_budget(turn, DEFAULT_CONFIG))(0, 0, 100, 10)
        plan = plan_upgrade_or_repair(turn, turn.team_our.unit(2), budget)
        self.assertEqual(plan.action.name, "WallFixer")


if __name__ == "__main__":
    unittest.main()
