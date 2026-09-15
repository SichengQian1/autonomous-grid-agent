from __future__ import annotations

import json
import unittest

from solution.models import Turn
from solution.telemetry import Telemetry, build_turn_event, decode_event, encode_event
from tests.helpers import synthetic_turn


class TelemetryTests(unittest.TestCase):
    def test_codec_round_trip_and_tamper_rejection(self) -> None:
        line = encode_event(7, {"event": "turn", "r": 12, "value": "synthetic"})
        self.assertEqual(decode_event(line)["r"], 12)
        replacement = "0" if line[-1] != "0" else "1"
        with self.assertRaises(ValueError):
            decode_event(line[:-1] + replacement)

    def test_turn_event_omits_sensitive_text_and_identifiers(self) -> None:
        raw = synthetic_turn(round_no=12)
        raw["phaseTask"] = "SECRET TASK TEXT"
        raw["llmResp"] = "SECRET LLM ANSWER"
        raw["lastCmdResult"] = "SECRET COMMAND OUTPUT"
        turn = Turn.from_raw(raw)
        event = build_turn_event(
            turn,
            {"roleCommandMap": {"2": {"action": "submitAnswer", "taskAnswer": "SECRET"}}},
            elapsed_ms=3,
            dropped_actions=0,
        )
        encoded = json.dumps(event)
        self.assertNotIn("synthetic-team", encoded)
        self.assertNotIn("SECRET", encoded)
        self.assertTrue(event["signals"]["task"])

    def test_byte_budget_keeps_reserved_space_for_critical_events(self) -> None:
        telemetry = Telemetry(byte_budget=400, reserve_bytes=200)
        while telemetry.emit({"event": "normal", "data": "x" * 40}):
            pass
        used_before = telemetry.used_bytes
        self.assertTrue(telemetry.emit({"event": "critical", "r": 70}, critical=True))
        self.assertGreater(telemetry.used_bytes, used_before)


if __name__ == "__main__":
    unittest.main()
