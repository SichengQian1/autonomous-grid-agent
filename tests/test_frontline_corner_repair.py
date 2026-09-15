from __future__ import annotations

from collections import deque
import time
import unittest

from solution.actions import Action, ActionType
from solution.combat import CombatPlanner
from solution.engine import AgentEngine
from solution.geometry import Pos, neighbours, station_footprint
from solution.layout import (
    DefenseMemory,
    observe_defense,
    plan_layout,
    remaining_wall_sites,
)
from solution.maintenance import rank_wall_work, try_jobs
from solution.models import Turn
from solution.planning import PlanningContext
from solution.state import WorldState
from tests.helpers import role
from tests.scenarios import arena, robot
from tests.simulation import EconomySimulation
from tests.test_layout import frontline_config, plan_for
from tools.diagnostics.defense_layout import _sample


FRONT_BODY = (Pos(6, 14), Pos(6, 15), Pos(6, 16), Pos(6, 17))
CORNERS = (Pos(6, 13), Pos(6, 18))
FIRST_FLANKS = (Pos(5, 13), Pos(5, 18))
FLANK_EXT = (Pos(4, 13), Pos(4, 18))
MIN_LINE = FRONT_BODY + CORNERS + FIRST_FLANKS


def prevent_config(**kwargs):
    return frontline_config(initial_flank_defense=True, initial_flank_depth=1, **kwargs)


def add_weapons(raw, layout):
    for index, weapon in enumerate(layout.weapons):
        raw["teamOur"]["roles"].append(
            role(11 + index, weapon.role_type, weapon.pos.x, weapon.pos.y, attack_range=10, level=1)
        )


def add_walls(raw, cells, start_id=40):
    for index, pos in enumerate(cells):
        raw["teamOur"]["roles"].append(
            role(start_id + index, "wall", pos.x, pos.y, health=1000, level=1)
        )


def eight_path(start: Pos, goal: Pos, blocked: set[Pos], bounds: tuple[int, int]) -> list[Pos] | None:
    width, height = bounds
    queue = deque([(start, [start])])
    seen = {start}
    while queue:
        point, path = queue.popleft()
        if point == goal:
            return path
        for nxt in neighbours(point):
            if nxt in seen or nxt in blocked:
                continue
            if not (0 <= nxt.x < width and 0 <= nxt.y < height):
                continue
            seen.add(nxt)
            queue.append((nxt, path + [nxt]))
    return None


class FirstNightEmptyFlankTests(unittest.TestCase):
    def test_zero_robots_plan_front_corners_and_first_flanks(self):
        layout, _, _ = plan_for(arena(), prevent_config())
        self.assertIsNotNone(layout)
        self.assertEqual(frozenset(layout.front_walls), frozenset(FRONT_BODY))
        self.assertEqual(frozenset(layout.corner_walls), frozenset(CORNERS))
        self.assertTrue(frozenset(FIRST_FLANKS).issubset(layout.flank_walls))
        self.assertTrue(frozenset(MIN_LINE).issubset(layout.required_wall_sites))
        remaining = remaining_wall_sites(Turn.from_raw(arena()), layout)
        self.assertEqual(frozenset(remaining), frozenset(layout.required_wall_sites))
        self.assertGreaterEqual(len(remaining), 8)
        self.assertNotEqual(frozenset(remaining), frozenset(FRONT_BODY))


class DayTwoMissingCornerTests(unittest.TestCase):
    def test_four_front_walls_and_high_flank_pressure_fill_corners_first(self):
        raw = arena()
        layout, memory, _ = plan_for(raw, prevent_config())
        add_weapons(raw, layout)
        add_walls(raw, FRONT_BODY)
        raw["roundNo"] = 2
        turn = Turn.from_raw(raw)
        observe_defense(turn, memory, prevent_config())
        memory.flank_pressure = {"neg": 100.0, "pos": 100.0}
        layout = plan_layout(turn, memory, prevent_config(), time.monotonic() + 1)
        remaining = remaining_wall_sites(turn, layout)
        self.assertIn(Pos(6, 13), remaining)
        self.assertIn(Pos(6, 18), remaining)
        self.assertTrue(frozenset(CORNERS).issubset(layout.corner_walls))
        corner_ranks = [remaining.index(p) for p in CORNERS]
        later = [p for p in remaining if p in FIRST_FLANKS + FLANK_EXT]
        self.assertTrue(later)
        self.assertLess(max(corner_ranks), min(remaining.index(p) for p in later))

    def test_existing_flank_without_corner_emits_corner_build(self):
        raw = arena(20, armed=True)
        raw["teamOur"]["roles"][0]["backpack"] = ["stone"]
        add_walls(raw, FRONT_BODY + (Pos(5, 13),))
        raw["teamOur"]["goldNum"] = 400
        state = WorldState()
        turn = Turn.from_raw(raw)
        observe_defense(turn, state.defense, prevent_config())
        state.defense.flank_pressure = {"neg": 80.0, "pos": 0.0}
        ctx = PlanningContext(turn, prevent_config(), state, time.monotonic() + 1)
        ctx.layout = plan_layout(turn, state.defense, ctx.config, ctx.deadline)
        self.assertIn(Pos(6, 13), ctx.layout.corner_walls)
        jobs = rank_wall_work(ctx, ctx.layout)
        build_targets = [j.target for j in jobs if j.kind == "build"]
        self.assertIn(Pos(6, 13), build_targets)
        self.assertLess(build_targets.index(Pos(6, 13)),
                        build_targets.index(Pos(5, 18)) if Pos(5, 18) in build_targets else 10**6)
        raw["teamOur"]["roles"][0]["pos"] = {"x": 6, "y": 14}
        turn = Turn.from_raw(raw)
        ctx = PlanningContext(turn, prevent_config(), state, time.monotonic() + 1)
        ctx.layout = plan_layout(turn, state.defense, ctx.config, ctx.deadline)
        ctx.wall_jobs = rank_wall_work(ctx, ctx.layout)
        self.assertTrue(try_jobs(ctx, ctx.turn.team_our.unit(1), ctx.wall_jobs, 20, urgent=True))
        self.assertEqual(ctx.actions[0].action_type, ActionType.BUILD)
        self.assertEqual(ctx.actions[0].targets, (Pos(6, 13),))


class NightPressureMemoryTests(unittest.TestCase):
    def test_expired_summary_cannot_leak_through_live_pressure(self):
        from solution.layout import _remembered_flank
        memory = DefenseMemory()
        raw = arena(80)
        raw["robot"]["roles"] = [robot(100, 5, 12)]
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        raw["roundNo"] = 261
        raw["robot"]["roles"] = []
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        self.assertTrue(memory.last_night.stale)
        self.assertEqual(_remembered_flank(memory, "neg"), 0)

    def test_previous_night_is_not_reused_in_new_night(self):
        from solution.layout import _remembered_flank
        memory = DefenseMemory()
        raw = arena(80)
        raw["robot"]["roles"] = [robot(100, 5, 12)]
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        raw["roundNo"] = 131
        raw["robot"]["roles"] = []
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        self.assertGreater(_remembered_flank(memory, "neg"), 0)
        raw["roundNo"] = 201
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        self.assertEqual(_remembered_flank(memory, "neg"), 0)

    def test_empty_end_of_night_clears_live_pressure_but_keeps_summary(self):
        config = prevent_config()
        memory = DefenseMemory()
        raw = arena(80, armed=True)
        raw["robot"]["roles"] = [robot(1, 5, 12)]
        observe_defense(Turn.from_raw(raw), memory, config)
        live = max(memory.flank_pressure.values() or [0.0])
        self.assertGreater(live, 0.0)
        raw["roundNo"] = 81
        raw["robot"]["roles"] = []
        observe_defense(Turn.from_raw(raw), memory, config)
        self.assertEqual(max(memory.flank_pressure.values() or [0.0]), 0.0)
        night = memory.current_night
        self.assertIsNotNone(night)
        peak = max(night.sides[side].peak_pressure for side in ("neg", "pos"))
        self.assertGreaterEqual(peak, live)
        raw["roundNo"] = 131
        observe_defense(Turn.from_raw(raw), memory, config)
        self.assertEqual(max(memory.flank_pressure.values() or [0.0]), 0.0)
        self.assertIsNotNone(memory.last_night)
        self.assertIsNone(memory.current_night)
        self.assertFalse(memory.last_night.stale)
        remembered = max(memory.last_night.sides[side].peak_pressure for side in ("neg", "pos"))
        self.assertGreater(remembered, 0.0)
        raw["roundNo"] = 132
        turn = Turn.from_raw(raw)
        layout = plan_layout(turn, memory, config, time.monotonic() + 1)
        remaining = remaining_wall_sites(turn, layout)
        self.assertTrue(frozenset(CORNERS).issubset(set(remaining) | set(layout.corner_walls)))
        self.assertTrue(any(p in remaining for p in CORNERS + FIRST_FLANKS))

    def test_duplicate_round_does_not_double_pressured_rounds(self):
        memory = DefenseMemory()
        raw = arena(80, armed=True)
        raw["robot"]["roles"] = [robot(1, 5, 12)]
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        once = memory.current_night.sides["neg"].pressured_rounds
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        self.assertEqual(memory.current_night.sides["neg"].pressured_rounds, once)

    def test_skipped_night_rounds_are_incomplete_not_filled_in(self):
        memory = DefenseMemory()
        raw = arena(80, armed=True)
        raw["robot"]["roles"] = [robot(1, 5, 12)]
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        first = memory.current_night.sides["neg"].pressured_rounds
        raw["roundNo"] = 90
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        self.assertFalse(memory.current_night.samples_complete)
        self.assertEqual(memory.current_night.sides["neg"].pressured_rounds, first + 1)

    def test_missing_robot_field_is_not_recorded_as_no_threat(self):
        memory = DefenseMemory()
        raw = arena(80, armed=True)
        raw["robot"]["roles"] = [robot(1, 5, 12)]
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        peak = max(memory.flank_pressure.values())
        raw["roundNo"] = 81
        raw["robot"] = {}
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        self.assertFalse(memory.current_night.samples_complete)
        self.assertGreaterEqual(max(memory.flank_pressure.values() or [0.0]), peak)

    def test_skip_across_dawn_promotes_summary(self):
        memory = DefenseMemory()
        raw = arena(80, armed=True)
        raw["robot"]["roles"] = [robot(1, 5, 12)]
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        raw["roundNo"] = 131
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        self.assertIsNone(memory.current_night)
        self.assertIsNotNone(memory.last_night)
        self.assertGreater(max(s.peak_pressure for s in memory.last_night.sides.values()), 0.0)

    def test_new_match_clears_summaries(self):
        memory = DefenseMemory()
        raw = arena(80, armed=True)
        raw["robot"]["roles"] = [robot(1, 5, 12)]
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        raw["mapInfo"]["width"] = 30
        raw["roundNo"] = 131
        raw["robot"]["roles"] = []
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        self.assertIsNone(memory.current_night)
        self.assertIsNone(memory.last_night)

    def test_old_summary_is_marked_stale(self):
        memory = DefenseMemory()
        raw = arena(80, armed=True)
        raw["robot"]["roles"] = [robot(1, 5, 12)]
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        raw["roundNo"] = 261
        raw["robot"]["roles"] = []
        observe_defense(Turn.from_raw(raw), memory, prevent_config())
        self.assertIsNotNone(memory.last_night)
        self.assertTrue(memory.last_night.stale)

    def test_night_release_uses_live_robots_not_last_night_summary(self):
        config = prevent_config()
        memory = DefenseMemory()
        raw = arena(72, armed=True)
        raw["robot"]["roles"] = [robot(1, 5, 12)]
        observe_defense(Turn.from_raw(raw), memory, config)
        raw["roundNo"] = 73
        raw["robot"]["roles"] = []
        observe_defense(Turn.from_raw(raw), memory, config)
        self.assertGreater(max(s.peak_pressure for s in memory.current_night.sides.values()), 0.0)
        combat = CombatPlanner(Turn.from_raw(raw), config, time.monotonic() + 1)
        self.assertTrue(combat.can_release({}, frozenset()))


class GeometryAndCapacityTests(unittest.TestCase):
    def test_blocked_connection_never_allows_an_isolated_flank(self):
        from solution.layout import site_build_ready, wall_prereqs
        for obstacle in (Pos(6, 13), Pos(6, 14)):
            with self.subTest(obstacle=obstacle):
                raw = arena(20, armed=True)
                built = set(FRONT_BODY) - {obstacle}
                add_walls(raw, built)
                raw["mapInfo"]["zones"].append({"neutralType": "stone", "pos": obstacle.to_raw()})
                layout, _, turn = plan_for(raw, prevent_config())
                self.assertNotIn(Pos(5, 13), remaining_wall_sites(turn, layout))
                self.assertEqual(wall_prereqs(layout, Pos(5, 13)), (Pos(6, 13),))
                self.assertFalse(site_build_ready(layout, Pos(5, 13), built))
                self.assertFalse(site_build_ready(layout, Pos(4, 13), built | {Pos(5, 13)}))
                self.assertIn("dependency", layout.unfinished_reasons)

    def test_small_front_quota_still_requires_real_connectors(self):
        from solution.layout import wall_prereqs
        layout, _, _ = plan_for(arena(), prevent_config(front_wall_target_count=2))
        self.assertTrue(set(MIN_LINE).issubset(layout.required_wall_sites))
        self.assertEqual(wall_prereqs(layout, Pos(6, 13)), (Pos(6, 14),))

    def test_missing_corner_is_a_local_entrance_until_filled(self):
        blocked = set(station_footprint(Pos(3, 16))) | set(FRONT_BODY) | set(FIRST_FLANKS)
        start, goal = Pos(7, 13), Pos(5, 14)
        path = eight_path(start, goal, blocked, (24, 20))
        self.assertIsNotNone(path)
        self.assertIn(Pos(6, 13), path)
        closed = eight_path(start, goal, blocked | {Pos(6, 13)}, (24, 20))
        self.assertTrue(closed is None or Pos(6, 13) not in closed)
        if closed is not None:
            self.assertTrue(any(point.y <= 12 or point.x <= 4 for point in closed))

    def test_right_side_minimum_line_matches_normalized_left(self):
        left, _, left_turn = plan_for(arena(), prevent_config())
        right, _, right_turn = plan_for(_sample("right"), prevent_config())

        def classified(layout, turn):
            frame = turn.coordinate_frame
            return (
                sorted(frame.normalize(p) for p in layout.front_walls),
                sorted(frame.normalize(p) for p in layout.corner_walls),
                sorted(frame.normalize(p) for p in layout.flank_walls),
            )

        self.assertEqual(classified(left, left_turn), classified(right, right_turn))
        self.assertEqual(len(left.corner_walls), 2)
        self.assertEqual(len(right.corner_walls), 2)
        self.assertTrue(frozenset(FIRST_FLANKS).issubset(left.flank_walls))

    def test_map_edge_keeps_legal_subset_and_exits(self):
        raw = arena()
        raw["teamOur"]["roles"][3]["pos"] = {"x": 0, "y": 10}
        layout, _, turn = plan_for(raw, prevent_config())
        self.assertIsNotNone(layout)
        self.assertTrue(layout.gates)
        cells = layout.front_walls + layout.corner_walls + layout.flank_walls
        self.assertTrue(all(turn.map_info.contains(cell) for cell in cells))
        self.assertTrue(all(cell not in layout.gates for cell in cells))

    def test_max_walls_degrades_without_raising_the_cap(self):
        layout, _, turn = plan_for(arena(), prevent_config(max_walls=6))
        remaining = remaining_wall_sites(turn, layout)
        self.assertLessEqual(len(remaining), 6)
        self.assertGreaterEqual(len(layout.required_wall_sites), 8)
        self.assertIn("max_walls", layout.unfinished_reasons)
        self.assertTrue(frozenset(CORNERS).issubset(layout.required_wall_sites))

    def test_legacy_frontline_without_flag_still_starts_with_front_body(self):
        layout, _, turn = plan_for(arena(), frontline_config())
        remaining = remaining_wall_sites(turn, layout)
        self.assertEqual(frozenset(remaining), frozenset(FRONT_BODY))
        self.assertFalse(layout.corner_walls)


class WorkerAndEconomyTests(unittest.TestCase):
    def test_wall_cap_does_not_reserve_stone_for_unbuildable_required_sites(self):
        from solution.economy import EconomyPlanner
        config = prevent_config(max_walls=6)
        raw = arena(20, armed=True)
        add_walls(raw, FRONT_BODY + CORNERS)
        turn = Turn.from_raw(raw)
        state = WorldState()
        observe_defense(turn, state.defense, config)
        ctx = PlanningContext(turn, config, state, time.monotonic() + 1)
        ctx.layout = plan_layout(turn, state.defense, config, ctx.deadline)
        self.assertFalse(EconomyPlanner(ctx)._wall_need())

    def test_two_workers_do_not_share_a_cell_and_honor_submitted_deps(self):
        from solution.layout import built_or_submitted_walls, site_build_ready

        raw = arena(20, armed=True)
        raw["teamOur"]["roles"][0]["backpack"] = ["stone"]
        raw["teamOur"]["roles"][1]["backpack"] = ["stone"]
        raw["teamOur"]["roles"][0]["pos"] = {"x": 7, "y": 14}
        raw["teamOur"]["roles"][1]["pos"] = {"x": 7, "y": 17}
        add_walls(raw, FRONT_BODY)
        state = WorldState()
        turn = Turn.from_raw(raw)
        observe_defense(turn, state.defense, prevent_config())
        ctx = PlanningContext(turn, prevent_config(), state, time.monotonic() + 1)
        ctx.layout = plan_layout(turn, state.defense, ctx.config, ctx.deadline)
        remaining = remaining_wall_sites(turn, ctx.layout)
        self.assertTrue(site_build_ready(ctx.layout, Pos(6, 13), built_or_submitted_walls(turn, ())))
        self.assertFalse(site_build_ready(ctx.layout, Pos(5, 13), built_or_submitted_walls(turn, ())))
        self.assertTrue(site_build_ready(
            ctx.layout, Pos(5, 13),
            built_or_submitted_walls(turn, (Action(1, ActionType.BUILD, targets=(Pos(6, 13),), name="wall"),)),
        ))
        jobs = rank_wall_work(ctx, ctx.layout)
        self.assertTrue(try_jobs(ctx, ctx.turn.team_our.unit(1), jobs, 20, urgent=False))
        self.assertTrue(try_jobs(ctx, ctx.turn.team_our.unit(2), jobs, 20, urgent=False))
        built = [a.targets[0] for a in ctx.actions if a.action_type == ActionType.BUILD]
        self.assertEqual(len(built), 2)
        self.assertEqual(len(set(built)), 2)
        self.assertTrue(set(built).issubset(set(remaining)))

    def test_standard_and_resource_rich_days_complete_minimum_line_before_night(self):
        for rich in (False, True):
            with self.subTest(resource_rich=rich):
                sim = EconomySimulation()
                if rich:
                    sim.raw["teamOur"]["goldNum"] = 300
                    sim.raw["teamOur"]["roles"][0]["backpack"] = ["stone"] * 6
                    sim.raw["teamOur"]["roles"][1]["backpack"] = ["stone"] * 6
                engine = AgentEngine(prevent_config())
                while sim.raw["roundNo"] < 71:
                    sim.apply(engine.decide(sim.raw))
                walls = {Pos.from_raw(u["pos"]) for u in sim.raw["teamOur"]["roles"] if u["roleType"] == "wall"}
                self.assertTrue(frozenset(MIN_LINE).issubset(walls), walls)
                self.assertEqual(sum(u["roleType"] == "railgun" for u in sim.raw["teamOur"]["roles"]), 2)
                self.assertEqual(sum(u["roleType"] == "rocket" for u in sim.raw["teamOur"]["roles"]), 1)

    def test_stone_shortage_keeps_required_sites_for_the_next_day(self):
        sim = EconomySimulation()
        sim.raw["teamOur"]["goldNum"] = 300
        sim.raw["mapInfo"]["zones"] = [z for z in sim.raw["mapInfo"]["zones"] if z["neutralType"] != "stone"]
        sim.raw["teamOur"]["roles"][0]["backpack"] = ["stone", "stone"]
        engine = AgentEngine(prevent_config())
        while sim.raw["roundNo"] < 71:
            sim.apply(engine.decide(sim.raw))
        walls = [u for u in sim.raw["teamOur"]["roles"] if u["roleType"] == "wall"]
        self.assertLess(len(walls), 8)
        self.assertLessEqual(len(walls), 2)
        layout = engine.state.defense.layout
        self.assertIsNotNone(layout)
        built = {Pos.from_raw(u["pos"]) for u in walls}
        missing = [p for p in layout.required_wall_sites if p not in built]
        self.assertTrue(missing)
        while sim.raw["roundNo"] < 131:
            sim.apply(engine.decide(sim.raw))
        sim.raw["teamOur"]["roles"][0]["backpack"] = ["stone"] * 6
        sim.raw["teamOur"]["roles"][1]["backpack"] = ["stone"] * 6
        sim.raw["teamOur"]["roles"][0]["pos"] = {"x": missing[0].x + 1, "y": missing[0].y}
        if len(missing) > 1:
            sim.raw["teamOur"]["roles"][1]["pos"] = {"x": missing[1].x + 1, "y": missing[1].y}
        while sim.raw["roundNo"] < 201:
            sim.apply(engine.decide(sim.raw))
        later = {Pos.from_raw(u["pos"]) for u in sim.raw["teamOur"]["roles"] if u["roleType"] == "wall"}
        self.assertGreater(len(later), len(built))
        self.assertTrue(any(cell in later for cell in missing))
