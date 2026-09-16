from __future__ import annotations

import contextlib
import io
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from solution.turncrypto import TurnLogCipher, chacha20_xor, derive_keys
from solution.turnlog import ENV_TURN_LOG_KEY, TurnLogger
from tests.scenarios import arena

ROOT = Path(__file__).resolve().parents[1]
DECRYPT_TOOL = ROOT / "tools" / "diagnostics" / "decrypt_turnlog.py"
REPLAY_TOOL = ROOT / "tools" / "diagnostics" / "replay.py"

# RFC 8439 section 2.4.3
_RFC_KEY = bytes(range(32))
_RFC_NONCE = bytes.fromhex("000000000000004a00000000")
_RFC_PLAINTEXT = (
    b"Ladies and Gentlemen of the class of '99: If I could offer you "
    b"only one tip for the future, sunscreen would be it."
)
_RFC_CIPHERTEXT = bytes.fromhex(
    "6e2e359a2568f98041ba0728dd0d6981e97e7aec1d4360c20a27afccfd9fae0b"
    "f91b65c5524733ab8f593dabcd62b3571639d624e65152ab8f530c359f0861d8"
    "07ca0dbf500d6a6156a38e088a22b65e52bc514d16ccf806818ce91ab7793736"
    "5af90bbf74a35be6b40b8eedf2785e42874d"
)


class ChaCha20Tests(unittest.TestCase):
    def test_rfc8439_encryption_vector(self):
        self.assertEqual(
            chacha20_xor(_RFC_KEY, _RFC_NONCE, _RFC_PLAINTEXT, counter=1),
            _RFC_CIPHERTEXT,
        )

    def test_xor_roundtrip_and_counter_wrapping(self):
        data = bytes(range(256)) * 9
        key, nonce = b"k" * 32, b"n" * 12
        encrypted = chacha20_xor(key, nonce, data, counter=0xFFFFFFFE)
        self.assertNotEqual(encrypted, data)
        self.assertEqual(chacha20_xor(key, nonce, encrypted, counter=0xFFFFFFFE), data)

    def test_rejects_bad_key_and_nonce_sizes(self):
        with self.assertRaises(ValueError):
            chacha20_xor(b"short", b"n" * 12, b"data")
        with self.assertRaises(ValueError):
            chacha20_xor(b"k" * 32, b"short", b"data")


class TurnLogCipherTests(unittest.TestCase):
    def test_header_roundtrip_and_decrypt(self):
        cipher = TurnLogCipher.from_passphrase("correct horse battery staple")
        header = cipher.header()
        self.assertEqual(header["turnlog"]["enc"], "chacha20-hmac-sha256")
        restored = TurnLogCipher.from_header("correct horse battery staple", header)
        for seq in range(3):
            record = cipher.encrypt(seq, f"payload-{seq}".encode())
            self.assertEqual(restored.decrypt(record), f"payload-{seq}".encode())

    def test_wrong_passphrase_fails_authentication(self):
        cipher = TurnLogCipher.from_passphrase("right")
        record = cipher.encrypt(0, b"secret")
        other = TurnLogCipher.from_passphrase("wrong")
        with self.assertRaises(ValueError):
            other.decrypt(record)

    def test_tampered_ciphertext_fails_authentication(self):
        cipher = TurnLogCipher.from_passphrase("pw")
        record = cipher.encrypt(0, b"secret")
        raw = bytearray(record["ct"].encode())
        raw[-2] = ord("A") if raw[-2] != ord("A") else ord("B")
        record["ct"] = raw.decode()
        with self.assertRaises(ValueError):
            cipher.decrypt(record)

    def test_sequence_mismatch_fails_authentication(self):
        cipher = TurnLogCipher.from_passphrase("pw")
        record = dict(cipher.encrypt(0, b"first"))
        record["seq"] = 1
        with self.assertRaises(ValueError):
            cipher.decrypt(record)

    def test_scrypt_unavailable_falls_back_to_pbkdf2(self):
        with mock.patch.object(hashlib, "scrypt", side_effect=ValueError("unsupported")):
            enc_key, mac_key, info = derive_keys("pw", b"s" * 16)
        self.assertEqual(info["kdf"], "pbkdf2-hmac-sha256")
        self.assertEqual(len(enc_key), 32)
        self.assertEqual(len(mac_key), 32)


def _payload(round_no: int, team_id: str = "synthetic") -> dict:
    raw = arena(round_no)
    raw["teamOur"]["teamId"] = team_id
    return raw


def _decrypt_file(path: Path, passphrase: str) -> tuple[list[dict], dict]:
    result = subprocess.run(
        [sys.executable, str(DECRYPT_TOOL), str(path)],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, ENV_TURN_LOG_KEY: passphrase},
    )
    lines = [json.loads(line) for line in result.stdout.splitlines() if line]
    return lines, result


class EncryptedTurnLogTests(unittest.TestCase):
    def test_records_are_encrypted_and_decryptable(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = TurnLogger(Path(directory), console=False, key="pw")
            logger.record(_payload(1), {"roleCommandMap": {"1": {"action": "collect"}}}, {"round": 1})
            logger.record(_payload(2), {"roleCommandMap": {}}, {"round": 2})
            logger.close()
            (path,) = Path(directory).glob("*.jsonl")
            raw_lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(raw_lines), 3)
            self.assertIn('"turnlog"', raw_lines[0])
            self.assertNotIn("roleCommandMap", path.read_text(encoding="utf-8"))
            self.assertNotIn('"request"', raw_lines[1])

            envelopes, result = _decrypt_file(path, "pw")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(envelopes), 2)
            self.assertEqual(envelopes[0]["request"]["roundNo"], 1)
            self.assertEqual(envelopes[0]["response"], {"roleCommandMap": {"1": {"action": "collect"}}})
            self.assertEqual(envelopes[1]["meta"]["round"], 2)

    def test_wrong_key_decrypts_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = TurnLogger(Path(directory), console=False, key="right")
            logger.record(_payload(1), {}, {})
            logger.close()
            (path,) = Path(directory).glob("*.jsonl")
            envelopes, result = _decrypt_file(path, "wrong")
            self.assertEqual(envelopes, [])
            self.assertEqual(result.returncode, 1)
            self.assertIn('"failed": 1', result.stderr)

    def test_console_and_file_share_encrypted_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = TurnLogger(Path(directory), console=True, key="pw")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                logger.record(_payload(5), {}, {})
            logger.close()
            console_lines = stderr.getvalue().splitlines()
            (path,) = Path(directory).glob("*.jsonl")
            file_lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(console_lines, file_lines)
            self.assertTrue(all(line.startswith("{") for line in console_lines))
            self.assertIn('"turnlog"', console_lines[0])
            self.assertIn('"ct"', console_lines[1])

    def test_oversized_record_is_skipped_when_encrypted(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = TurnLogger(Path(directory), console=False, key="pw")
            with mock.patch("solution.turnlog.MAX_ENCRYPTED_RECORD_BYTES", 100):
                logger.record(_payload(1), {}, {})
            logger.close()
            (path,) = Path(directory).glob("*.jsonl")
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertIn('"turnlog"', lines[0])

    def test_decrypted_requests_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = TurnLogger(Path(directory), console=False, key="pw")
            for round_no in (1, 2, 3):
                logger.record(_payload(round_no), {"roleCommandMap": {}}, {})
            logger.close()
            (path,) = Path(directory).glob("*.jsonl")
            plain = Path(directory) / "requests.jsonl"
            result = subprocess.run(
                [sys.executable, str(DECRYPT_TOOL), str(path), "--requests"],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, ENV_TURN_LOG_KEY: "pw"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            plain.write_text(result.stdout, encoding="utf-8")
            replay = subprocess.run(
                [sys.executable, str(REPLAY_TOOL), str(plain), "--limit", "10"],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(replay.returncode, 0, replay.stderr)
            self.assertEqual(json.loads(replay.stdout)["records"], 3)

    def test_env_key_enables_encryption(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(
                os.environ, {"AGENT_TURN_LOG": directory, ENV_TURN_LOG_KEY: "pw"}
            ):
                logger = TurnLogger.from_env()
            self.assertEqual(logger._key, "pw")
            self.assertEqual(logger._directory, Path(directory))
            self.assertFalse(logger._console)
            logger.close()

    def test_replay_rejects_encrypted_log(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = TurnLogger(Path(directory), console=False, key="pw")
            logger.record(_payload(1), {"roleCommandMap": {}}, {})
            logger.close()
            (path,) = Path(directory).glob("*.jsonl")
            replay = subprocess.run(
                [sys.executable, str(REPLAY_TOOL), str(path), "--limit", "10"],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(replay.returncode, 2)
            self.assertIn("decrypt", replay.stderr.lower())
            self.assertNotIn("roleCommandMap", replay.stdout)


if __name__ == "__main__":
    unittest.main()
