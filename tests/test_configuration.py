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

    def test_invalid_settings_fail_explicitly(self):
        for data in ({"typo": 1}, {"night_gathering": "false"}, {"normal_turn_budget_seconds": 6},
                     {"primary_weapon_loadout": ["unknown"]}, {"return_margin": -1}):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.json"
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    load_config(str(path))
