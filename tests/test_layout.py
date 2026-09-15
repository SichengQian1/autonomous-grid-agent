from __future__ import annotations

from dataclasses import replace
import time
import unittest

from solution.engine import AgentEngine
from solution.geometry import Pos, footprint_distance
from solution.layout import DefenseMemory, observe_defense, plan_layout, remaining_weapon_placements
from solution.models import Turn
from solution.rules import DEFAULT_CONFIG, ROLE_GATLING, ROLE_RAILGUN, ROLE_ROCKET
from tests.scenarios import arena, robot


def frontline_config(**kwargs):
    return replace(DEFAULT_CONFIG, defense_layout="frontline", wall_maintenance_enabled=True, **kwargs)


def plan_for(raw, config=None, memory=None, deadline=None):
    turn = Turn.from_raw(raw)
    memory = memory or DefenseMemory()
    config = config or frontline_config()
    observe_defense(turn, memory, config)
    layout = plan_layout(turn, memory, config, deadline if deadline is not None else time.monotonic() + 1)
    return layout, memory, turn


class FrontlineLayoutTests(unittest.TestCase):
    def test_left_base_faces_east_and_right_faces_west(self):
        left, _, left_turn = plan_for(arena())
        self.assertIsNotNone(left)
        self.assertEqual(left.front, (1, 0))
        self.assertEqual(left.source, "user_prior")
        raw = arena()
        raw["teamOur"]["type"] = "defender"
        for unit in raw["teamOur"]["roles"]:
            x, y = unit["pos"]["x"], unit["pos"]["y"]
            if unit["roleType"] == "station":
                unit["pos"] = {"x": 22 - x, "y": 20 - y}
            else:
                unit["pos"] = {"x": 23 - x, "y": 19 - y}
        for zone in raw["mapInfo"]["zones"]:
            zone["pos"] = {"x": 23 - zone["pos"]["x"], "y": 19 - zone["pos"]["y"]}
        right, _, right_turn = plan_for(raw)
        self.assertIsNotNone(right)
        self.assertEqual(right.front, (-1, 0))
        left_norm = [left_turn.coordinate_frame.normalize(w.pos) for w in left.weapons]
        right_norm = [right_turn.coordinate_frame.normalize(w.pos) for w in right.weapons]
        self.assertEqual(sorted(left_norm), sorted(right_norm))

    def test_midline_and_missing_map_fall_back(self):
        raw = arena()
        raw["teamOur"]["roles"][3]["pos"] = {"x": 11, "y": 10}
        layout, memory, _ = plan_for(raw)
        self.assertIsNone(layout)
        self.assertEqual(memory.last_reason, "midline_or_invalid_base")
        raw["mapInfo"]["width"] = 0
        layout, memory, _ = plan_for(raw)
        self.assertIsNone(layout)

    def test_rocket_is_rearward_and_railguns_cover_front(self):
        layout, _, turn = plan_for(arena())
        self.assertIsNotNone(layout)
        rocket = next(w for w in layout.weapons if w.role_type == ROLE_ROCKET)
        rails = [w for w in layout.weapons if w.role_type == ROLE_RAILGUN]
        station = turn.team_our.station()
        edge = max(p.x for p in station.footprint())
        self.assertLessEqual(rocket.pos.x, min(r.pos.x for r in rails) + 1)
        self.assertLess(rocket.pos.x, edge)
        front_point = Pos(edge + 3, sum(p.y for p in station.footprint()) // 4)
        self.assertTrue(any(w.pos.distance_to(front_point) <= 6 for w in rails))
        self.assertEqual(len({cell for w in layout.weapons for cell in w.controller_cells}), 3)
        self.assertTrue(layout.gates)
        self.assertTrue(all(footprint_distance(p, station.footprint()) == 2 for p in layout.front_walls))

    def test_gatling_is_not_pushed_out_of_level_one_range(self):
        layout, _, turn = plan_for(arena(), frontline_config(primary_weapon_loadout=(ROLE_GATLING, ROLE_RAILGUN, ROLE_ROCKET)))
        self.assertIsNotNone(layout)
        gatling = next(w for w in layout.weapons if w.role_type == ROLE_GATLING)
        station = turn.team_our.station()
        front = Pos(max(p.x for p in station.footprint()) + 3, sum(p.y for p in station.footprint()) // 4)
        self.assertLessEqual(gatling.pos.distance_to(front), 3)

    def test_planned_buildings_are_included_in_coverage(self):
        layout, _, turn = plan_for(arena())
        self.assertIsNotNone(layout)
        from solution.geometry import ray_blocked
        station = set(turn.team_our.station().footprint())
        rails = [w for w in layout.weapons if w.role_type == ROLE_RAILGUN]
        front = Pos(max(p.x for p in station) + 3, sum(p.y for p in station) // 4)
        self.assertTrue(any(not ray_blocked(w.pos, front, {o.pos for o in layout.weapons if o is not w})
                            and w.pos.distance_to(front) <= 6
                            for w in rails))

    def test_no_rear_space_still_returns_legal_sites(self):
        raw = arena()
        raw["teamOur"]["roles"][3]["pos"] = {"x": 0, "y": 10}
        layout, _, turn = plan_for(raw)
        self.assertIsNotNone(layout)
        self.assertEqual(layout.front, (1, 0))
        self.assertTrue(all(turn.map_info.contains(w.pos) for w in layout.weapons))
        self.assertTrue(all(footprint_distance(w.pos, turn.team_our.station().footprint()) == 1 for w in layout.weapons))

    def test_non_square_map_does_not_crash(self):
        raw = arena()
        raw["mapInfo"]["width"] = 18
        raw["mapInfo"]["height"] = 28
        layout, _, _ = plan_for(raw)
        self.assertIsNotNone(layout)
        self.assertEqual(layout.front, (1, 0))

    def test_first_weapon_freezes_direction_against_stray_flankers(self):
        raw = arena(80, armed=True)
        memory = DefenseMemory()
        layout, memory, _ = plan_for(raw, memory=memory)
        self.assertTrue(memory.weapons_frozen)
        frozen = layout.front
        raw["robot"]["roles"] = [robot(1, 2, 18, target="challenger"), robot(2, 1, 19, target="challenger")]
        raw["roundNo"] = 81
        layout, memory, _ = plan_for(raw, memory=memory)
        self.assertEqual(layout.front, frozen)
        self.assertEqual(tuple(w.pos for w in layout.weapons), tuple(w.pos for w in memory.layout.weapons))

    def test_distant_opponent_robots_do_not_set_our_front(self):
        raw = arena(80)
        raw["robot"]["roles"] = [robot(9, 22, 2, target="defender")]
        layout, memory, _ = plan_for(raw)
        self.assertEqual(layout.front, (1, 0))
        self.assertLess(memory.front_robot_count, 1)

    def test_crowding_can_prioritize_a_front_flank_without_flipping_front(self):
        raw = arena()
        memory = DefenseMemory()
        first, memory, _ = plan_for(raw, memory=memory)
        self.assertIsNotNone(first)
        raw["roundNo"] = 71
        raw["robot"]["roles"] = [robot(i, 8, 14 + i % 3) for i in range(6)] + [robot(20, 6, 12), robot(21, 7, 12)]
        observe_defense(Turn.from_raw(raw), memory, frontline_config())
        raw2 = arena(72)
        raw2["robot"]["roles"] = raw["robot"]["roles"]
        layout, memory, _ = plan_for(raw2, memory=memory)
        self.assertEqual(layout.front, (1, 0))
        self.assertGreaterEqual(memory.front_robot_count, 1)
        self.assertTrue(layout.flank_walls)
        self.assertTrue(set(layout.flank_walls).issubset(layout.wall_order))

    def test_night_engine_does_not_build_walls(self):
        raw = arena(80, armed=True)
        raw["teamOur"]["roles"][0]["backpack"] = ["stone", "stone"]
        result = AgentEngine(frontline_config()).decide(raw)
        self.assertFalse(any(a.get("action") == "build" for a in result["roleCommandMap"].values()))

    def test_opening_uses_typed_weapon_sites(self):
        engine = AgentEngine(frontline_config())
        raw = arena()
        layout, _, turn = plan_for(raw)
        wanted = {p.role_type: p.pos for p in remaining_weapon_placements(turn, layout)}
        found = None
        for step in range(1, 16):
            raw["roundNo"] = step
            result = engine.decide(raw)
            for key, command in result["roleCommandMap"].items():
                unit = next(u for u in raw["teamOur"]["roles"] if u["id"] == int(key))
                if command["action"] == "move":
                    unit["pos"] = command["targetPos"][0]
                if command["action"] == "build":
                    found = command
                    break
            raw["lastRoundRoleActionResults"] = {k: True for k in result["roleCommandMap"]}
            if found:
                break
        self.assertIsNotNone(found)
        site = Pos.from_raw(found["targetPos"][0])
        self.assertIn(found["name"], wanted)
        self.assertEqual(footprint_distance(site, Turn.from_raw(arena()).team_our.station().footprint()), 1)

    def test_expired_search_does_not_adopt_a_partial_plan(self):
        layout, memory, _ = plan_for(arena(), deadline=time.monotonic() - 1)
        self.assertIsNone(layout)
        self.assertIsNone(memory.layout)

    def test_legacy_config_does_not_create_frontline_layout(self):
        layout, memory, _ = plan_for(arena(), DEFAULT_CONFIG)
        self.assertIsNone(layout)
        self.assertEqual(memory.last_reason, "legacy_mode")
