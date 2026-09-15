from __future__ import annotations

from dataclasses import replace
import time
import unittest

from solution.engine import AgentEngine
from solution.geometry import Pos
from solution.layout import DefenseMemory, observe_defense, plan_layout
from solution.maintenance import rank_wall_work, try_wall_work
from solution.models import Turn
from solution.planning import PlanningContext
from solution.state import WorldState
from tests.helpers import role
from tests.scenarios import arena, robot
from tests.simulation import EconomySimulation
from tests.test_layout import frontline_config


class WallMaintenanceTests(unittest.TestCase):
    def _context(self, raw, config=None, memory=None):
        config = config or frontline_config()
        turn = Turn.from_raw(raw)
        state = WorldState()
        state.ingest(turn)
        if memory is not None:
            state.defense = memory
        observe_defense(turn, state.defense, config)
        ctx = PlanningContext(turn, config, state, time.monotonic() + 1)
        ctx.layout = plan_layout(turn, state.defense, config, ctx.deadline)
        ctx.wall_jobs = rank_wall_work(ctx, ctx.layout)
        return ctx

    def test_pressured_front_beats_low_rear_wall(self):
        raw = arena(20, armed=True)
        raw["teamOur"]["roles"].extend([
            role(40, "wall", 6, 15, health=200, level=1),
            role(41, "wall", 1, 16, health=50, level=1),
        ])
        raw["teamOur"]["goldNum"] = 400
        raw["weaponShopList"] += [{"name": "WallFixer", "price": 20}, {"name": "WallUpgradeVoucher1", "price": 40}]
        ctx = self._context(raw)
        ctx.state.defense.damage_events.append((19, 40, "E", 400))
        ctx.state.defense.front_robot_count = 4
        ctx.state.defense.flank_pressure = {"neg": 0.0, "pos": 0.0}
        ctx.layout = plan_layout(ctx.turn, ctx.state.defense, ctx.config, ctx.deadline)
        if ctx.layout is not None:
            ctx.layout = replace(ctx.layout, front_walls=(Pos(6, 15),) + tuple(p for p in ctx.layout.front_walls if p != Pos(6, 15)))
            ctx.layout = replace(ctx.layout, flank_walls=tuple(p for p in ctx.layout.flank_walls if p != Pos(1, 16)))
        jobs = rank_wall_work(ctx, ctx.layout)
        self.assertTrue(jobs)
        self.assertEqual(jobs[0].target, Pos(6, 15))

    def test_upgrade_counts_restore_and_skips_full_unpressured(self):
        raw = arena(20, armed=True)
        raw["teamOur"]["roles"].extend([
            role(40, "wall", 6, 15, health=200, level=1),
            role(41, "wall", 6, 16, health=1000, level=1),
        ])
        raw["weaponShopList"] += [{"name": "WallFixer", "price": 20}, {"name": "WallUpgradeVoucher1", "price": 40}]
        ctx = self._context(raw)
        if ctx.layout is not None:
            ctx.layout = replace(ctx.layout, front_walls=(Pos(6, 15), Pos(6, 16)))
        ctx.state.defense.front_robot_count = 3
        ctx.state.defense.damage_events.append((19, 40, "E", 300))
        jobs = rank_wall_work(ctx, ctx.layout)
        damaged = [j for j in jobs if j.target == Pos(6, 15) and j.kind == "upgrade"]
        self.assertTrue(damaged)
        self.assertGreaterEqual(damaged[0].expected_hp_gain, 1300)
        full = [j for j in jobs if j.target == Pos(6, 16) and j.kind == "repair"]
        self.assertFalse(full)

    def test_unknown_and_max_level_are_skipped(self):
        raw = arena(20, armed=True)
        raw["teamOur"]["roles"].extend([
            role(40, "wall", 6, 15, health=100, level=0),
            role(41, "wall", 6, 16, health=500, level=3),
        ])
        raw["weaponShopList"] += [{"name": "WallFixer", "price": 20},
                                  {"name": "WallUpgradeVoucher1", "price": 40},
                                  {"name": "WallUpgradeVoucher2", "price": 40}]
        ctx = self._context(raw)
        if ctx.layout:
            ctx.layout = replace(ctx.layout, front_walls=(Pos(6, 15), Pos(6, 16)))
        ctx.state.defense.front_robot_count = 2
        jobs = rank_wall_work(ctx, ctx.layout)
        self.assertFalse(any(j.target_id == 40 for j in jobs))
        self.assertFalse(any(j.kind == "upgrade" and j.target_id == 41 for j in jobs))

    def test_budget_and_duplicate_purchase_guards(self):
        raw = arena(10, armed=True)
        raw["teamOur"]["goldNum"] = 400
        raw["teamOur"]["roles"].extend([role(40, "wall", 6, 15, health=100, level=1)])
        raw["weaponShopList"] += [{"name": "WallFixer", "price": 30}]
        raw["teamOur"]["roles"][0]["pos"] = {"x": 6, "y": 18}
        ctx = self._context(raw)
        ctx.state.defense.start_gold = 400
        ctx.state.defense.last_gold = 400
        if ctx.layout:
            ctx.layout = replace(ctx.layout, front_walls=(Pos(6, 15),))
        ctx.state.defense.front_robot_count = 3
        ctx.state.defense.damage_events.append((9, 40, "E", 200))
        jobs = rank_wall_work(ctx, ctx.layout)
        work = next((j for j in jobs if j.kind == "repair"), None)
        self.assertIsNotNone(work)
        worker = ctx.turn.team_our.unit(1)
        self.assertTrue(try_wall_work(ctx, worker, work, 20))
        self.assertIn(("buy", "WallFixer"), ctx.claimed)
        other = ctx.turn.team_our.unit(2)
        self.assertFalse(try_wall_work(ctx, other, work, 20))

    def test_held_voucher_is_not_bought_again(self):
        raw = arena(10)
        raw["teamOur"]["roles"][0]["backpack"] = ["WallFixer"]
        raw["teamOur"]["roles"].extend([role(40, "wall", 5, 16, health=100, level=1)])
        raw["weaponShopList"] += [{"name": "WallFixer", "price": 30}]
        ctx = self._context(raw)
        if ctx.layout:
            ctx.layout = replace(ctx.layout, front_walls=(Pos(5, 16),))
        ctx.state.defense.front_robot_count = 2
        jobs = rank_wall_work(ctx, ctx.layout)
        work = next(j for j in jobs if j.kind == "repair")
        worker = ctx.turn.team_our.unit(1)
        try_wall_work(ctx, worker, work, 20)
        self.assertNotIn(("buy", "WallFixer"), ctx.claimed)

    def test_controller_does_not_leave_to_repair_at_night(self):
        raw = arena(80, armed=True)
        raw["teamOur"]["roles"].extend([role(40, "wall", 6, 15, health=100, level=1)])
        raw["teamOur"]["roles"][0]["backpack"] = ["WallFixer"]
        raw["robot"]["roles"] = [robot(100, 10, 15, 80)]
        result = AgentEngine(frontline_config()).decide(raw)
        attacks = [a for a in result["roleCommandMap"].values() if a.get("action") == "attack"]
        self.assertTrue(attacks)
        controllers = {a["controllerId"] for a in attacks}
        uses = [int(k) for k, a in result["roleCommandMap"].items() if a.get("action") == "use"]
        self.assertFalse(set(uses) & controllers)

    def test_new_match_clears_budget_and_damage(self):
        raw = arena(20)
        ctx = self._context(raw)
        ctx.state.defense.wall_spend = 40
        ctx.state.defense.damage_events.append((19, 1, "E", 9))
        restarted = arena(1)
        restarted["teamOur"]["teamId"] = "other-synthetic"
        ctx.state.ingest(Turn.from_raw(restarted))
        self.assertEqual(ctx.state.defense.wall_spend, 0)
        self.assertEqual(ctx.state.defense.damage_events, [])

    def test_duplicate_round_does_not_double_damage(self):
        raw = arena(72, armed=True)
        raw["teamOur"]["roles"].extend([role(40, "wall", 6, 15, health=800, level=1)])
        memory = DefenseMemory()
        turn = Turn.from_raw(raw)
        observe_defense(turn, memory, frontline_config())
        raw["teamOur"]["roles"][-1]["health"] = 500
        raw["roundNo"] = 73
        observe_defense(Turn.from_raw(raw), memory, frontline_config())
        once = sum(e[3] for e in memory.damage_events if e[1] == 40)
        observe_defense(Turn.from_raw(raw), memory, frontline_config())
        self.assertEqual(sum(e[3] for e in memory.damage_events if e[1] == 40), once)

    def test_frontline_economy_builds_weapons_then_front_walls(self):
        sim, engine = EconomySimulation(), AgentEngine(frontline_config())
        for _ in range(80):
            sim.apply(engine.decide(sim.raw))
        kinds = [u["roleType"] for u in sim.raw["teamOur"]["roles"]]
        self.assertEqual(kinds.count("railgun"), 2)
        self.assertEqual(kinds.count("rocket"), 1)
        self.assertGreaterEqual(kinds.count("wall"), 1)
        station = next(u for u in sim.raw["teamOur"]["roles"] if u["roleType"] == "station")
        walls = [u for u in sim.raw["teamOur"]["roles"] if u["roleType"] == "wall"]
        self.assertTrue(any(Pos.from_raw(w["pos"]).x > station["pos"]["x"] + 1 for w in walls))
