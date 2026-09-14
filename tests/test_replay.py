from __future__ import annotations

import unittest

from solution.engine import AgentEngine
from solution.geometry import Pos
from tests.scenarios import robot
from tests.simulation import EconomySimulation


class SyntheticReplayTests(unittest.TestCase):
    def test_both_sides_build_trade_and_upgrade_across_two_days(self):
        for mirrored in (False, True):
            with self.subTest(mirrored=mirrored):
                sim, engine = EconomySimulation(mirrored=mirrored), AgentEngine()
                for _ in range(260):
                    sim.apply(engine.decide(sim.raw))
                self.assertLessEqual(sim.first_three_weapons, 12)
                self.assertGreater(sim.counts["collect"], 50)
                self.assertGreater(sim.counts["sell"], 3)
                self.assertGreater(sim.counts["use"], 0)
                self.assertGreaterEqual(sim.raw["teamOur"]["goldNum"], 0)
                kinds = [u["roleType"] for u in sim.raw["teamOur"]["roles"]]
                self.assertEqual(kinds.count("railgun"), 2)
                self.assertEqual(kinds.count("rocket"), 1)

    def test_first_night_has_three_staffed_weapons(self):
        sim, engine = EconomySimulation(), AgentEngine()
        for _ in range(70):
            sim.apply(engine.decide(sim.raw))
        humans = [u for u in sim.raw["teamOur"]["roles"] if u["roleType"] in {"worker", "pioneer"}]
        weapons = [u for u in sim.raw["teamOur"]["roles"] if u["roleType"] in {"railgun", "rocket", "gatling"}]
        self.assertTrue(all(any(Pos.from_raw(h["pos"]).distance_to(Pos.from_raw(w["pos"])) == 1 for h in humans) for w in weapons))
        sim.raw["robot"]["roles"] = [robot(1000, 10, 15), robot(1001, 10, 14), robot(1002, 11, 13), robot(1003, 12, 11)]
        actions = engine.decide(sim.raw)["roleCommandMap"]
        self.assertEqual(sum(a["action"] == "attack" for a in actions.values()), 3)
        self.assertEqual(len({a["controllerId"] for a in actions.values() if a["action"] == "attack"}), 3)
