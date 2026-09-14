import unittest

from solution.engine import AgentEngine
from solution.main import decide, parse_port
from solution.protocol import safe_response


class MainTests(unittest.TestCase):
    def test_safe_response_is_fresh_and_empty(self) -> None:
        first = safe_response()
        second = safe_response()

        self.assertEqual(first, {"roleCommandMap": {}})
        self.assertEqual(second, {"roleCommandMap": {}})
        self.assertIsNot(first, second)

    def test_empty_strategy_returns_safe_response(self) -> None:
        self.assertEqual(decide({"roundNo": 1}), {"roleCommandMap": {}})

    def test_malformed_optional_payload_still_returns_safe_response(self) -> None:
        self.assertEqual(
            decide({"roundNo": "bad", "mapInfo": None, "teamOur": []}),
            {"roleCommandMap": {}},
        )

    def test_concurrent_turn_returns_fallback_without_waiting(self) -> None:
        engine = AgentEngine()
        engine._lock.acquire()
        try:
            self.assertEqual(engine.decide({"roundNo": 1}), safe_response())
        finally:
            engine._lock.release()

    def test_parse_port(self) -> None:
        self.assertEqual(parse_port(["main.py", "8000"]), 8000)

    def test_parse_port_rejects_invalid_range(self) -> None:
        with self.assertRaises(SystemExit):
            parse_port(["main.py", "0"])

    def test_parse_port_requires_one_argument(self) -> None:
        with self.assertRaises(SystemExit):
            parse_port(["main.py"])


if __name__ == "__main__":
    unittest.main()
