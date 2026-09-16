from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from unittest import mock

import solution.engine as engine_module
from solution.actions import Action, ActionType, Decision
from solution.engine import AgentEngine, decide_payload
from solution.geometry import Pos
from solution.main import AgentServer, RequestHandler
from solution.models import Turn
from solution.turnlog import TurnLogger
from tests.scenarios import arena

ROOT = Path(__file__).resolve().parents[1]


def _payload(round_no: int, team_id: str = "synthetic") -> dict:
    raw = arena(round_no)
    raw["teamOur"]["teamId"] = team_id
    return raw


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class TurnLoggerEnvTests(unittest.TestCase):
    def test_unset_env_disables_logging(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("AGENT_TURN_LOG", None)
            logger = TurnLogger.from_env()
        self.assertIsNone(logger._directory)
        self.assertFalse(logger._console)

    def test_off_env_disables_logging(self):
        with mock.patch.dict(os.environ, {"AGENT_TURN_LOG": "off"}):
            logger = TurnLogger.from_env()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(logger._directory)
            logger.record(_payload(1), {"roleCommandMap": {}}, {"round": 1})
            self.assertFalse(list(Path(directory).iterdir()))
        self.assertEqual(stderr.getvalue(), "")

    def test_stderr_env_enables_console_only(self):
        with mock.patch.dict(os.environ, {"AGENT_TURN_LOG": "stderr"}):
            logger = TurnLogger.from_env()
        self.assertIsNone(logger._directory)
        self.assertTrue(logger._console)

    def test_env_directory_enables_file_sink(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"AGENT_TURN_LOG": directory}):
                logger = TurnLogger.from_env()
            self.assertEqual(logger._directory, Path(directory))
            self.assertFalse(logger._console)


class TurnLoggerFileTests(unittest.TestCase):
    def test_record_writes_envelope_line(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = TurnLogger(Path(directory), console=False)
            request, response = _payload(7), {"roleCommandMap": {"1": {"action": "collect"}}}
            meta = {"round": 7, "ms": 1.5, "issues": []}
            logger.record(request, response, meta)
            logger.close()
            files = list(Path(directory).glob("*.jsonl"))
            self.assertEqual(len(files), 1)
            envelope = _lines(files[0])[0]
            self.assertEqual(envelope["request"], request)
            self.assertEqual(envelope["response"], response)
            self.assertEqual(envelope["meta"]["round"], 7)
            self.assertEqual(Turn.from_raw(envelope["request"]).round_no, 7)

    def test_new_match_and_round_reset_split_files(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = TurnLogger(Path(directory), console=False)
            logger.record(_payload(1, "team-a"), {}, {})
            logger.record(_payload(2, "team-a"), {}, {})
            logger.record(_payload(1, "team-b"), {}, {})
            logger.record(_payload(3, "team-b"), {}, {})
            logger.record(_payload(1, "team-b"), {}, {})
            logger.close()
            files = sorted(Path(directory).glob("*.jsonl"))
            self.assertEqual(len(files), 3)
            self.assertEqual(len(_lines(files[0])), 2)
            self.assertEqual(len(_lines(files[1])), 2)
            self.assertEqual(len(_lines(files[2])), 1)
            self.assertIn("team-a", files[0].name)
            self.assertIn("team-b", files[1].name)

    def test_file_byte_cap_stops_appending(self):
        small = {"roundNo": 0, "teamOur": {"teamId": "t", "type": "challenger"}}
        with tempfile.TemporaryDirectory() as directory:
            logger = TurnLogger(Path(directory), console=False, max_file_bytes=200)
            for round_no in (1, 2, 3):
                small["roundNo"] = round_no
                logger.record(dict(small), {"roleCommandMap": {}}, {"round": round_no})
            logger.close()
            (path,) = Path(directory).glob("*.jsonl")
            records = _lines(path)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[-1], {"meta": {"truncated": True}})
            self.assertLessEqual(path.stat().st_size, 200)

    def test_unwritable_directory_fails_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            blocker = Path(directory) / "occupied"
            blocker.write_text("not a directory")
            logger = TurnLogger(blocker / "logs", console=False)
            logger.record(_payload(1), {}, {})
            logger.record(_payload(2), {}, {})
            logger.close()
            self.assertTrue(blocker.is_file())
            self.assertFalse((blocker / "logs").exists())
            self.assertEqual(blocker.read_text(), "not a directory")

    def test_console_prints_envelope_line(self):
        logger = TurnLogger(console=True)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            logger.record(_payload(4), {"roleCommandMap": {}}, {"round": 4})
        envelope = json.loads(stderr.getvalue())
        self.assertEqual(envelope["request"]["roundNo"], 4)
        self.assertIn("response", envelope)
        self.assertIn("meta", envelope)


class EngineMetaTests(unittest.TestCase):
    def test_meta_reports_decision_summary(self):
        engine = AgentEngine()
        meta: dict = {}
        response = engine.decide(arena(1), meta)
        self.assertIsInstance(response["roleCommandMap"], dict)
        self.assertEqual(meta["round"], 1)
        self.assertIs(meta["cacheHit"], False)
        self.assertIs(meta["newMatch"], True)
        self.assertIsInstance(meta["ms"], float)
        self.assertIsInstance(meta["proposed"], list)
        self.assertIsInstance(meta["issues"], list)
        self.assertIsInstance(meta["accepted"], int)
        self.assertIs(meta["prompt"], "prompt" in response)
        self.assertIs(meta["cmd"], "executeCmd" in response)

    def test_meta_marks_cache_hit_and_rejections(self):
        engine = AgentEngine()
        meta: dict = {}
        engine.decide(arena(1))
        engine.decide(arena(1), meta)
        self.assertIs(meta["cacheHit"], True)
        self.assertEqual(meta["round"], 1)

        engine = AgentEngine()
        engine.decide(arena(20))
        engine.decide(arena(14), meta)
        self.assertEqual(meta["rejected"], "staleRound")

        meta.clear()
        oversized = {"roundNo": 1, "robot": {"roles": [{}] * 2049}}
        self.assertEqual(engine.decide(oversized, meta), {"roleCommandMap": {}})
        self.assertEqual(meta["rejected"], "payloadLimits")

        engine._lock.acquire()
        try:
            engine.decide(arena(1), meta)
        finally:
            engine._lock.release()
        self.assertEqual(meta["rejected"], "concurrent")

    def test_meta_lists_dropped_actions(self):
        engine = AgentEngine()
        engine.planner.plan = lambda *args, **kwargs: Decision(
            actions=(Action(actor_id=1, action_type=ActionType.MOVE, targets=(Pos(0, 0),)),)
        )
        meta: dict = {}
        engine.decide(arena(1), meta)
        self.assertGreater(len(meta["issues"]), 0)
        self.assertEqual(meta["proposed"], [{"actor": 1, "action": "move"}])
        self.assertEqual(meta["accepted"], 0)

    def test_decide_payload_marks_engine_errors(self):
        meta: dict = {}
        with mock.patch.object(engine_module, "_ENGINE", object()):
            self.assertEqual(decide_payload(arena(1), meta), {"roleCommandMap": {}})
        self.assertEqual(meta["error"], "AttributeError")


class TurnLogHttpTests(unittest.TestCase):
    def test_server_records_request_response_and_meta(self):
        with tempfile.TemporaryDirectory() as directory:
            server = AgentServer(("127.0.0.1", 0), RequestHandler)
            server.turn_logger = TurnLogger(Path(directory), console=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_address[1]}/",
                    data=json.dumps(arena(1)).encode("utf-8"),
                    method="POST",
                )
                with opener.open(request, timeout=5) as reply:
                    response = json.loads(reply.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                server.turn_logger.close()
                thread.join(timeout=5)
            self.assertIsInstance(response.get("roleCommandMap"), dict)
            deadline = time.monotonic() + 2
            paths: list[Path] = []
            while time.monotonic() < deadline:
                paths = list(Path(directory).glob("*.jsonl"))
                if paths:
                    break
                time.sleep(0.01)
            self.assertEqual(len(paths), 1)
            envelope = _lines(paths[0])[0]
            self.assertEqual(envelope["request"]["roundNo"], 1)
            self.assertEqual(envelope["response"], response)
            self.assertEqual(envelope["meta"]["round"], 1)

    def test_http_response_returns_before_logging_finishes(self):
        started = threading.Event()
        release = threading.Event()

        class BlockingLogger:
            def record(self, payload, response, meta):
                del payload, response, meta
                started.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("log was not released")

        server = AgentServer(("127.0.0.1", 0), RequestHandler)
        server.turn_logger = BlockingLogger()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_address[1]}/",
                data=json.dumps(arena(1)).encode("utf-8"),
                method="POST",
            )
            with opener.open(request, timeout=2) as reply:
                body = json.loads(reply.read().decode("utf-8"))
            self.assertIsInstance(body.get("roleCommandMap"), dict)
            self.assertTrue(started.wait(timeout=2))
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_server_without_logger_still_responds(self):
        server = AgentServer(("127.0.0.1", 0), RequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_address[1]}/",
                data=b'{"roundNo": 1}',
                method="POST",
            )
            with opener.open(request, timeout=5) as reply:
                self.assertEqual(json.loads(reply.read()), {"roleCommandMap": {}})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class TurnLogReplayTests(unittest.TestCase):
    def test_replay_accepts_envelope_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = TurnLogger(Path(directory), console=False)
            for round_no in (1, 2, 3):
                logger.record(_payload(round_no), {"roleCommandMap": {}}, {"round": round_no})
            logger.close()
            (path,) = Path(directory).glob("*.jsonl")
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "diagnostics" / "replay.py"),
                 str(path), "--limit", "10"],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["records"], 3)
            self.assertEqual(report["round_max"], 3)

    def test_replay_skips_truncated_marker(self):
        small = {"roundNo": 0, "teamOur": {"teamId": "t", "type": "challenger"}}
        with tempfile.TemporaryDirectory() as directory:
            logger = TurnLogger(Path(directory), console=False, max_file_bytes=200)
            for round_no in (1, 2, 3):
                small["roundNo"] = round_no
                logger.record(dict(small), {"roleCommandMap": {}}, {"round": round_no})
            logger.close()
            (path,) = Path(directory).glob("*.jsonl")
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "diagnostics" / "replay.py"),
                 str(path), "--limit", "10"],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["records"], 1)


if __name__ == "__main__":
    unittest.main()
