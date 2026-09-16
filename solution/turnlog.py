from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import sys
import threading
import time
from typing import Any, TextIO

from .turncrypto import TurnLogCipher


LOGGER = logging.getLogger(__name__)
ENV_TURN_LOG = "AGENT_TURN_LOG"
ENV_TURN_LOG_KEY = "AGENT_TURN_LOG_KEY"
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_ENCRYPTED_RECORD_BYTES = 1024 * 1024
_DISABLED_VALUES = frozenset({"off", "0", "none", "false", "no"})
_CONSOLE_VALUES = frozenset({"stderr", "-"})
_SLUG_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
_TRUNCATED_LINE = '{"meta":{"truncated":true}}\n'


def _integer(raw: object, default: int = 0) -> int:
    if isinstance(raw, bool):
        return default
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


def _team(payload: dict[str, Any]) -> dict[str, Any]:
    team = payload.get("teamOur")
    return team if isinstance(team, dict) else {}


def _match_key(payload: dict[str, Any]) -> tuple[str, str]:
    team = _team(payload)
    return (str(team.get("teamId") or ""), str(team.get("type") or ""))


def _team_slug(payload: dict[str, Any]) -> str:
    slug = _SLUG_PATTERN.sub("-", str(_team(payload).get("teamId") or "unknown")).strip("-.")
    return (slug or "unknown")[:32]


class TurnLogger:
    """Bounded per-turn recorder writing one JSON envelope per request/response pair.

    When a key is configured every record is encrypted; each match file starts
    with a plaintext header carrying the salt and key-derivation parameters.
    """

    def __init__(
        self,
        directory: Path | None = None,
        *,
        console: bool = True,
        max_file_bytes: int = MAX_FILE_BYTES,
        key: str | None = None,
    ) -> None:
        self._directory = directory
        self._console = console
        self._max_file_bytes = max_file_bytes
        self._key = key or None
        self._cipher: TurnLogCipher | None = None
        self._record_seq = 0
        self._lock = threading.Lock()
        self._stream: TextIO | None = None
        self._file_bytes = 0
        self._file_disabled = False
        self._match_key: tuple[str, str] | None = None
        self._last_round = 0
        self._match_seq = 0
        self._warned: set[str] = set()

    @classmethod
    def from_env(cls) -> TurnLogger:
        raw = os.environ.get(ENV_TURN_LOG, "").strip()
        if not raw or raw.lower() in _DISABLED_VALUES:
            return cls(console=False)
        key = os.environ.get(ENV_TURN_LOG_KEY, "").strip() or None
        if key is None:
            LOGGER.warning("turn log is not encrypted; set %s to enable encryption", ENV_TURN_LOG_KEY)
        if raw.lower() in _CONSOLE_VALUES:
            return cls(directory=None, console=True, key=key)
        return cls(Path(raw).expanduser(), console=False, key=key)

    def record(self, payload: object, response: object, meta: dict[str, Any] | None) -> None:
        if not isinstance(payload, dict) or (not self._console and self._directory is None):
            return
        try:
            plain = json.dumps(
                {"meta": meta or {}, "request": payload, "response": response},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            self._warn_once("turn log serialization failed")
            return
        with self._lock:
            if self._advance_match(payload):
                self._begin_match(payload)
            wire = self._encode(plain)
            if wire is None:
                return
            self._write_console(wire)
            self._write_file(payload, wire)

    def close(self) -> None:
        with self._lock:
            self._close_stream()

    def _encode(self, plain: str) -> str | None:
        if self._key is None:
            return plain
        if self._cipher is None:
            self._warn_once("turn log encryption is unavailable; record skipped")
            return None
        data = plain.encode("utf-8")
        if len(data) > MAX_ENCRYPTED_RECORD_BYTES:
            self._warn_once("encrypted turn log record exceeds its byte limit")
            return None
        try:
            record = self._cipher.encrypt(self._record_seq, data)
        except Exception:
            self._warn_once("turn log encryption failed")
            return None
        self._record_seq += 1
        return json.dumps(record, separators=(",", ":"))

    def _advance_match(self, payload: dict[str, Any]) -> bool:
        key = _match_key(payload)
        round_no = max(0, _integer(payload.get("roundNo")))
        crossed = key != self._match_key or (self._last_round > 1 and round_no <= 1)
        self._match_key, self._last_round = key, round_no
        return crossed

    def _begin_match(self, payload: dict[str, Any]) -> None:
        self._close_stream()
        self._file_disabled = False
        self._file_bytes = 0
        self._record_seq = 0
        if self._key is None:
            self._cipher = None
            return
        try:
            self._cipher = TurnLogCipher.from_passphrase(self._key)
        except Exception:
            self._cipher = None
            self._warn_once("turn log encryption is unavailable")
            return
        header = json.dumps(self._cipher.header(), ensure_ascii=False, separators=(",", ":"))
        self._write_console(header)
        self._write_file(payload, header)

    def _write_console(self, line: str) -> None:
        if not self._console:
            return
        try:
            print(line, file=sys.stderr, flush=True)
        except Exception:
            self._console = False
            self._warn_once("turn log console output disabled")

    def _write_file(self, payload: dict[str, Any], line: str) -> None:
        if self._directory is None or self._file_disabled:
            return
        try:
            if self._stream is None:
                self._open_stream(payload)
            encoded = len(line.encode("utf-8")) + 1
            if self._file_bytes + encoded > self._max_file_bytes:
                if self._file_bytes + len(_TRUNCATED_LINE) <= self._max_file_bytes:
                    self._stream.write(_TRUNCATED_LINE)
                    self._stream.flush()
                self._file_disabled = True
                self._warn_once("turn log file reached its byte limit")
                return
            self._stream.write(line + "\n")
            self._stream.flush()
            self._file_bytes += encoded
        except OSError:
            self._file_disabled = True
            self._close_stream()
            self._warn_once("turn log file output disabled")

    def _open_stream(self, payload: dict[str, Any]) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        self._match_seq += 1
        stamp = f"{time.strftime('%Y%m%d-%H%M%S')}.{int(time.time() * 1000) % 1000:03d}"
        slug = _team_slug(payload)
        for attempt in range(100):
            suffix = f"-{attempt}" if attempt else ""
            path = self._directory / f"match-{stamp}-{self._match_seq:03d}-{slug}{suffix}.jsonl"
            try:
                self._stream = path.open("x", encoding="utf-8")
                self._file_bytes = 0
                return
            except FileExistsError:
                continue
        raise OSError("could not create a unique turn log file")

    def _close_stream(self) -> None:
        if self._stream is None:
            return
        try:
            self._stream.close()
        except OSError:
            pass
        self._stream = None

    def _warn_once(self, message: str) -> None:
        if message in self._warned:
            return
        self._warned.add(message)
        try:
            LOGGER.warning("%s", message)
        except Exception:
            pass
