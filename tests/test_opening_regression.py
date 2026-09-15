"""Synthetic regression for the failed opening; never a win-rate simulator."""
from __future__ import annotations

import unittest
from collections import Counter

from solution.engine import AgentEngine
from solution.models import Turn
from solution.defense import build_defense_layout
from tools.diagnostics.synthetic_replay import SyntheticWorld, unit


class RestrictedOpeningWorld(SyntheticWorld):
    """Independent fixture: permit weapons on ring 1 and walls on ring 2 only."""

    def __init__(self, side="challenger"):
        super().__init__(side)
        self.roles = [unit(1, "worker", 5, 11), unit(2, "worker", 6, 11),
                      unit(3, "pioneer", 7, 11),
                      unit(10, "station", 5, 13, health=1500, level=1)]
        self.zones = [
            {"pos": {"x": 3, "y": 7}, "neutralType": "stone"},
            {"pos": {"x": 5, "y": 9}, "neutralType": "copper"},
            {"pos": {"x": 10, "y": 10}, "neutralType": "vendor"},
            {"pos": {"x": 11, "y": 12}, "neutralType": "weaponShop"},
        ]
        if side == "defender":
            for role in self.roles:
                p = role["pos"]
                role["pos"] = {"x": 23-p["x"], "y": 19-p["y"]}
                if role["roleType"] == "station":
                    role["pos"]["x"] -= 1
                    role["pos"]["y"] += 1
            for zone in self.zones:
                p = zone["pos"]
                zone["pos"] = {"x": 23-p["x"], "y": 19-p["y"]}
        self.build_attempts = []
        self.round_no = 0

    def request(self, round_no):
        self.round_no = round_no
        raw = super().request(round_no)
        raw["mapInfo"] = {"width": 24, "height": 20, "zones": self.zones}
        raw["vendorShopList"].append({"name": "copper", "price": 5})
        return raw

    def ring(self, target):
        station = next(r for r in self.roles if r["roleType"] == "station")["pos"]
        return min(max(abs(target["x"]-x), abs(target["y"]-y))
                   for x in (station["x"], station["x"]+1)
                   for y in (station["y"]-1, station["y"]))

    def apply(self, response):
        accepted = {}
        rejected = {}
        by_id = {str(r["id"]): r for r in self.roles}
        for actor, cmd in response["roleCommandMap"].items():
            if cmd["action"] == "build":
                correct = self.ring(cmd["targetPos"][0]) == (2 if cmd["name"] == "wall" else 1)
                self.build_attempts.append((self.round_no, cmd["name"], correct))
                if not correct:
                    rejected[actor] = False
                    continue
            if cmd["action"] == "collect":
                # Do not repeat the old simulator's bug of turning every ore into stone.
                zone = next(z for z in self.zones if z["pos"] == cmd["targetPos"][0])
                by_id[actor]["backpack"].append(zone["neutralType"])
                rejected[actor] = True
                continue
            accepted[actor] = cmd
        super().apply({"roleCommandMap": accepted})
        self.feedback.update(rejected)


class OpeningRegressionTests(unittest.TestCase):
    def test_candidates_respect_independent_build_zone_oracle(self):
        for side in ("challenger", "defender"):
            world = RestrictedOpeningWorld(side)
            layout = build_defense_layout(Turn.from_raw(world.request(1)))
            self.assertTrue(all(world.ring(p.to_raw()) == 1 for p in layout.weapon_sites))
            self.assertTrue(all(world.ring(p.to_raw()) == 2 for p in layout.wall_sites))

    def test_first_night_has_weapons_walls_and_controllers(self):
        for side in ("challenger", "defender"):
            with self.subTest(side=side):
                world, engine = RestrictedOpeningWorld(side), AgentEngine()
                for r in range(1, 71):
                    response = engine.decide(world.request(r))
                    commands = response["roleCommandMap"].values()
                    builds = {tuple(c["targetPos"][0].values()) for c in commands if c["action"] == "build"}
                    moves = {tuple(c["targetPos"][0].values()) for c in commands if c["action"] == "move"}
                    self.assertFalse(builds & moves)
                    world.apply(response)
                    if r == 12:
                        self.assertEqual(sum(u["roleType"] in {"rocket", "railgun"} for u in world.roles), 3)
                self.assertTrue(all(ok for _, _, ok in world.build_attempts))
                counts = Counter(u["roleType"] for u in world.roles)
                self.assertEqual((counts["rocket"], counts["railgun"]), (2, 1))
                self.assertGreaterEqual(counts["wall"], 10)
                from solution.combat import assign_controllers
                turn = Turn.from_raw(world.request(70))
                weapons = tuple(u for u in turn.team_our.roles if u.is_weapon)
                self.assertTrue(all(a.controller.pos.distance_to(a.weapon.pos) <= 1
                                    for a in assign_controllers(turn, weapons)))
