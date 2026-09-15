from __future__ import annotations

import unittest

from tools.diagnostics.summarize_match_log import summarize


class DiagnosticSummaryTests(unittest.TestCase):
    def test_summary_is_bounded_and_omits_identifiers(self) -> None:
        records = [
            {
                "request": {
                    "roundNo": 71,
                    "teamOur": {
                        "type": "challenger",
                        "teamId": "must-not-appear",
                        "teamName": "must-not-appear",
                        "roles": [],
                    },
                    "robot": {
                        "roles": [
                            {
                                "pos": {"x": 10, "y": 8},
                                "roleType": "bossRobot",
                                "targetTeam": "challenger",
                            }
                        ]
                    },
                    "errors": [],
                },
                "response": {
                    "roleCommandMap": {
                        "1": {
                            "action": "build",
                            "name": "railgun",
                            "targetPos": [{"x": 3, "y": 8}],
                        }
                    }
                },
            },
            {
                "request": {
                    "roundNo": 72,
                    "teamOur": {"type": "challenger", "roles": []},
                    "robot": {"roles": []},
                    "lastRoundRoleActionResults": {"1": True},
                    "errors": [],
                }
            },
        ]
        result = summarize(records)
        rendered = str(result)
        self.assertNotIn("must-not-appear", rendered)
        self.assertEqual(result["firstBossDay"], 1)
        self.assertEqual(result["buildResults"][0]["success"], True)


if __name__ == "__main__":
    unittest.main()
