from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from solution.configuration import load_config


class ConfigurationTests(unittest.TestCase):
    def test_balanced_variant_is_loadable(self):
        path = Path(__file__).resolve().parents[1] / "config" / "balanced.json"
        self.assertEqual(load_config(str(path)).primary_weapon_loadout, ("gatling", "railgun", "rocket"))

    def test_frontline_variants_are_loadable(self):
        root = Path(__file__).resolve().parents[1] / "config"
        frontline = load_config(str(root / "frontline.json"))
        self.assertEqual(frontline.defense_layout, "frontline")
        self.assertTrue(frontline.wall_maintenance_enabled)
        self.assertEqual(frontline.primary_weapon_loadout, ("railgun", "railgun", "rocket"))
        balanced = load_config(str(root / "frontline-balanced.json"))
        self.assertEqual(balanced.primary_weapon_loadout, ("gatling", "railgun", "rocket"))

    def test_legacy_max_walls_zero_still_loads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"max_walls": 0}))
            config = load_config(str(path))
            self.assertEqual(config.max_walls, 0)
            self.assertEqual(config.defense_layout, "legacy")

    def test_invalid_settings_fail_explicitly(self):
        for data in ({"typo": 1}, {"night_gathering": "false"}, {"normal_turn_budget_seconds": 6},
                     {"primary_weapon_loadout": ["unknown"]}, {"return_margin": -1},
                     {"defense_layout": "sideways"}, {"wall_budget_fraction": True},
                     {"wall_budget_fraction": float("nan")}, {"front_direction": ["east"]},
                     {"layout_search_budget_ms": 5},
                     {"defense_layout": "frontline", "max_walls": 2, "front_wall_target_count": 4}):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.json"
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    load_config(str(path))
