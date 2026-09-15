from __future__ import annotations

from dataclasses import replace
import time
import unittest

from solution.actions import Action, ActionType, Decision
from solution.combat import CombatPlanner, shot_damage, angle_valid
from solution.defense import base_cells, build_cells, controller_assignments
from solution.geometry import Pos, footprint_distance, ray_entry
from solution.models import Turn
from solution.navigation import Navigator
from solution.rules import DEFAULT_CONFIG
from solution.validation import ActionValidator
from tests.scenarios import arena, robot
from tests.helpers import role


class NavigationTests(unittest.TestCase):
    def test_diagonal_corner_passage_and_obstacle_avoidance(self):
        raw = arena()
        raw["teamOur"]["roles"] = [role(1, "worker", 0, 0)]
        raw["mapInfo"]["zones"] = [{"neutralType": "stone", "pos": {"x": 1, "y": 0}},
                                       {"neutralType": "iron", "pos": {"x": 0, "y": 1}}]
        turn = Turn.from_raw(raw)
        nav = Navigator(turn, DEFAULT_CONFIG, time.monotonic() + 1)
        route = nav.route(turn.team_our.unit(1), (Pos(1, 1),))
        self.assertEqual(route.step, Pos(1, 1))
        self.assertEqual(route.distance, 1)

    def test_joint_next_step_reservations(self):
        raw = arena()
        raw["teamOur"]["roles"] = [role(1, "worker", 0, 0), role(2, "worker", 2, 0)]
        raw["mapInfo"]["zones"] = []
        turn = Turn.from_raw(raw)
        nav = Navigator(turn, DEFAULT_CONFIG, time.monotonic() + 1)
        first = nav.route(turn.team_our.unit(1), (Pos(1, 1),))
        nav.commit(first)
        self.assertIsNone(nav.route(turn.team_our.unit(2), (Pos(1, 1),)))
        self.assertIsNone(nav.route(turn.team_our.unit(2), (Pos(0, 0),)))

    def test_dynamic_obstacle_replans(self):
        raw = arena()
        raw["teamOur"]["roles"] = [role(1, "worker", 0, 0)]
        raw["mapInfo"]["zones"] = []
        turn = Turn.from_raw(raw)
        first = Navigator(turn, DEFAULT_CONFIG, time.monotonic() + 1).route(turn.team_our.unit(1), (Pos(3, 3),))
        raw["mapInfo"]["zones"].append({"neutralType": "stone", "pos": first.step.to_raw()})
        newer = Turn.from_raw(raw)
        second = Navigator(newer, DEFAULT_CONFIG, time.monotonic() + 1).route(newer.team_our.unit(1), (Pos(3, 3),))
        self.assertNotEqual(second.step, first.step)

    def test_build_rings_use_entire_station_footprint(self):
        turn = Turn.from_raw(arena())
        self.assertEqual(len(build_cells(turn, 1)), 12)
        self.assertEqual(len(build_cells(turn, 2)), 20)
        for radius in (1, 2):
            self.assertTrue(all(footprint_distance(p, base_cells(turn)) == radius for p in build_cells(turn, radius)))

    def test_path_deadline_is_bounded(self):
        turn = Turn.from_raw(arena())
        nav = Navigator(turn, DEFAULT_CONFIG, time.monotonic() - 1)
        reached = nav.routes(turn.team_our.unit(1))
        self.assertLess(len(reached), DEFAULT_CONFIG.path_node_limit)


class CombatTests(unittest.TestCase):
    def make(self, robots, *, kind="railgun", power=50, level=1, cooldown=0):
        raw = arena(75)
        raw["teamOur"]["roles"] = [role(1, "worker", 5, 6), role(4, "station", 1, 5, health=1500, level=1),
                                     role(10, kind, 5, 5, attack_range=18, level=level, cooldown=cooldown)]
        raw["teamOur"]["roles"][-1]["attackPower"] = power
        raw["mapInfo"]["zones"] = []
        raw["robot"]["roles"] = robots
        turn = Turn.from_raw(raw)
        return turn, turn.team_our.unit(10)

    def test_railgun_energy_stops_after_current_health_consumption(self):
        turn, weapon = self.make([robot(30, 8, 5, 40), robot(31, 10, 5, 60)])
        damage = shot_damage(turn, weapon, Pos(10, 5), DEFAULT_CONFIG)
        self.assertEqual(damage, {30: 40, 31: 10})

    def test_gatling_hits_nearest_robot_on_ray(self):
        turn, weapon = self.make([robot(30, 8, 5, 40), robot(31, 10, 5, 60)], kind="gatling", power=10)
        self.assertEqual(shot_damage(turn, weapon, Pos(10, 5), DEFAULT_CONFIG), {30: 10})

    def test_rocket_splash_and_repeated_salvo(self):
        turn, weapon = self.make([robot(30, 10, 5, 40), robot(31, 11, 5, 60)], kind="rocket", power=20, level=2)
        self.assertEqual(shot_damage(turn, weapon, Pos(10, 5), DEFAULT_CONFIG), {30: 20, 31: 10})
        plan = CombatPlanner(turn, DEFAULT_CONFIG, time.monotonic() + 1).plan({1: weapon})
        self.assertEqual(len(plan.actions[0].targets), 2)
        self.assertEqual(ActionValidator().validate(turn, Decision(plan.actions)).issues, ())

    def test_rocket_cooldown_does_not_supply_cleanup_capacity(self):
        turn, weapon = self.make([robot(30, 10, 5, 10)], kind="rocket", power=20, cooldown=1)
        combat = CombatPlanner(turn, DEFAULT_CONFIG, time.monotonic() + 1)
        self.assertEqual(combat.plan({1: weapon}).actions, ())
        self.assertFalse(combat.can_release({1: weapon}, frozenset()))

    def test_multiple_gatling_targets_remain_in_ninety_degrees(self):
        turn, weapon = self.make([robot(30, 10, 5), robot(31, 0, 5), robot(32, 5, 10)], kind="gatling", power=10, level=3)
        plan = CombatPlanner(turn, DEFAULT_CONFIG, time.monotonic() + 1).plan({1: weapon})
        self.assertEqual(len(plan.actions[0].targets), 3)
        self.assertTrue(angle_valid(weapon.pos, plan.actions[0].targets))

    def test_building_blocker_is_conservative_and_configurable(self):
        turn, weapon = self.make([robot(30, 10, 5)])
        blocker = Turn.from_raw({"teamOur": {"roles": [role(21, "railgun", 7, 5)]}}).team_our.roles[0]
        turn = replace(turn, team_our=replace(turn.team_our, roles=turn.team_our.roles + (blocker,)))
        self.assertEqual(shot_damage(turn, weapon, Pos(10, 5), DEFAULT_CONFIG), {})
        self.assertEqual(shot_damage(turn, weapon, Pos(10, 5), replace(DEFAULT_CONFIG, projectile_building_blocking=False)), {30: 40})

    def test_small_wave_release_requires_remaining_staffed_firepower(self):
        turn, weapon = self.make([robot(30, 10, 5, 40)], power=50)
        combat = CombatPlanner(turn, DEFAULT_CONFIG, time.monotonic() + 1)
        self.assertTrue(combat.can_release({1: weapon}, frozenset({2})))
        self.assertFalse(combat.can_release({1: weapon}, frozenset({1})))

    def test_empty_night_can_release_but_not_spawn_boundary(self):
        turn, weapon = self.make([])
        self.assertTrue(CombatPlanner(turn, DEFAULT_CONFIG, time.monotonic() + 1).can_release({1: weapon}, frozenset({1})))
        first_night = replace(turn, round_no=71)
        self.assertFalse(CombatPlanner(first_night, DEFAULT_CONFIG, time.monotonic() + 1).can_release({1: weapon}, frozenset({1})))

    def test_low_count_high_health_is_not_safe(self):
        turn, weapon = self.make([robot(30, 10, 5, 800)], power=50)
        self.assertFalse(CombatPlanner(turn, DEFAULT_CONFIG, time.monotonic() + 1).can_release({1: weapon}, frozenset({2})))

    def test_missing_robot_observation_is_not_a_cleared_wave(self):
        turn, weapon = self.make([])
        turn = replace(turn, robots_observed=False)
        self.assertFalse(CombatPlanner(turn, DEFAULT_CONFIG, time.monotonic() + 1).can_release({1: weapon}, frozenset({1})))

    def test_joint_weapons_avoid_wasting_both_shots_on_one_kill(self):
        turn, weapon = self.make([robot(30, 10, 5, 40), robot(31, 10, 8, 40)], power=40)
        second = replace(weapon, unit_id=11, pos=Pos(5, 7))
        controller = replace(turn.team_our.unit(1), unit_id=2, pos=Pos(5, 8))
        turn = replace(turn, team_our=replace(turn.team_our, roles=turn.team_our.roles + (second, controller)))
        plan = CombatPlanner(turn, DEFAULT_CONFIG, time.monotonic() + 1).plan({1: weapon, 2: second})
        self.assertEqual(len(plan.actions), 2)
        self.assertGreaterEqual(plan.damage[30], 40)
        self.assertGreaterEqual(plan.damage[31], 40)

    def test_ray_square_intersection(self):
        self.assertIsNotNone(ray_entry(Pos(0, 0), Pos(4, 4), Pos(2, 2)))
        self.assertIsNone(ray_entry(Pos(0, 0), Pos(4, 4), Pos(3, 0)))
