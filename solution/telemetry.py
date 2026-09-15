from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import zlib
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping

from .models import Turn


LOGGER = logging.getLogger("aglog")
PREFIX = "AGLOG2 "
# This is a private wire format, not cryptographic secrecy: the decoder and key
# ship with the public agent so that every competition log remains recoverable.
_CODEC_KEY = hashlib.sha256(b"autonomous-grid-agent-v0.2-log-format").digest()


def _xor_stream(data: bytes, nonce: bytes) -> bytes:
    output = bytearray(len(data))
    offset = 0
    counter = 0
    while offset < len(data):
        block = hashlib.blake2s(
            nonce + counter.to_bytes(4, "big"), key=_CODEC_KEY, digest_size=32
        ).digest()
        for byte in block:
            if offset >= len(data):
                break
            output[offset] = data[offset] ^ byte
            offset += 1
        counter += 1
    return bytes(output)


def encode_event(sequence: int, event: Mapping[str, Any]) -> str:
    raw = json.dumps(event, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    compressed = zlib.compress(raw, level=6)
    nonce = max(0, sequence).to_bytes(8, "big", signed=False)
    cipher = _xor_stream(compressed, nonce)
    tag = hashlib.blake2s(nonce + cipher, key=_CODEC_KEY, digest_size=12).digest()
    return PREFIX + base64.b85encode(nonce + tag + cipher).decode("ascii")


def decode_event(line: str) -> dict[str, Any]:
    marker = line.find(PREFIX)
    if marker < 0:
        raise ValueError("not an AGLOG2 record")
    token = line[marker + len(PREFIX):].strip().split()[0]
    try:
        packed = base64.b85decode(token.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise ValueError("invalid AGLOG2 encoding") from error
    if len(packed) < 21:
        raise ValueError("truncated AGLOG2 record")
    nonce, tag, cipher = packed[:8], packed[8:20], packed[20:]
    expected = hashlib.blake2s(nonce + cipher, key=_CODEC_KEY, digest_size=12).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("AGLOG2 integrity check failed")
    try:
        value = json.loads(zlib.decompress(_xor_stream(cipher, nonce)))
    except (ValueError, zlib.error, json.JSONDecodeError) as error:
        raise ValueError("invalid AGLOG2 payload") from error
    if not isinstance(value, dict):
        raise ValueError("AGLOG2 payload must be an object")
    return value


def _pos(pos: object) -> list[int] | None:
    if pos is None:
        return None
    return [getattr(pos, "x"), getattr(pos, "y")]


def build_turn_event(
    turn: Turn,
    response: Mapping[str, Any],
    *,
    elapsed_ms: int,
    dropped_actions: int,
) -> dict[str, Any]:
    station = turn.team_our.station()
    living_robots = tuple(robot for robot in turn.robots if robot.health > 0)
    robot_counts = Counter(
        f"{robot.role_type}:{robot.target_team or '?'}" for robot in living_robots
    )
    roles = [
        [
            unit.unit_id,
            unit.role_type,
            _pos(unit.pos),
            unit.health,
            unit.level,
            unit.attack_power,
            unit.attack_range,
            unit.cooldown,
            dict(sorted(Counter(unit.backpack).items())),
        ]
        for unit in turn.team_our.roles
        if unit.health > 0
    ]
    robots = [
        [
            robot.robot_id,
            robot.role_type,
            _pos(robot.pos),
            robot.health,
            robot.attack_power,
            robot.attack_range,
            robot.target_team or "?",
        ]
        for robot in living_robots[:40]
    ]
    enemy_buildings = [
        [unit.role_type, _pos(unit.pos), unit.health, unit.level]
        for unit in turn.team_enemy.roles
        if unit.health > 0
    ][:24]
    commands: list[list[Any]] = []
    command_map = response.get("roleCommandMap", {})
    if isinstance(command_map, Mapping):
        for actor, raw_command in command_map.items():
            if not isinstance(raw_command, Mapping):
                continue
            # Answers, prompts and command text are intentionally never logged.
            targets = raw_command.get("targets")
            safe_targets = targets if isinstance(targets, list) else []
            commands.append(
                [
                    actor,
                    raw_command.get("action", ""),
                    raw_command.get("name", ""),
                    raw_command.get("num", 0),
                    safe_targets[:3],
                    raw_command.get("controllerId", -1),
                ]
            )
    return {
        "v": 2,
        "agentVersion": "v0.2",
        "event": "turn",
        "r": turn.round_no,
        "d": turn.day_index,
        "phase": "day" if turn.is_day else "night",
        "gold": turn.team_our.gold,
        "score": turn.team_our.total_score,
        "station": [station.health, station.level] if station is not None else None,
        "roles": roles,
        "robotCounts": dict(sorted(robot_counts.items())),
        "robots": robots,
        "enemyBuildings": enemy_buildings,
        "commands": commands,
        "results": dict(turn.last_action_results),
        "errors": [error.error_code for error in turn.errors],
        "signals": {
            "task": bool(turn.phase_task),
            "llm": bool(turn.llm_response),
            "sandbox": bool(turn.last_command_result),
        },
        "elapsedMs": max(0, elapsed_ms),
        "dropped": max(0, dropped_actions),
    }


@dataclass(slots=True)
class Telemetry:
    byte_budget: int
    reserve_bytes: int
    used_bytes: int = 0
    sequence: int = 0

    def emit(self, event: Mapping[str, Any], *, critical: bool = False) -> bool:
        try:
            line = encode_event(self.sequence, event)
            size = len(line.encode("utf-8")) + 1
            normal_limit = max(0, self.byte_budget - self.reserve_bytes)
            limit = self.byte_budget if critical else normal_limit
            if self.used_bytes + size > limit:
                return False
            LOGGER.info(line)
            self.used_bytes += size
            self.sequence += 1
            return True
        except Exception:
            # Diagnostics must never change a game decision.
            return False

    def record_turn(
        self,
        turn: Turn,
        response: Mapping[str, Any],
        *,
        elapsed_ms: int,
        dropped_actions: int,
    ) -> None:
        critical = bool(turn.errors) or turn.round_in_day in {1, 70, 71, 130}
        event = build_turn_event(
            turn,
            response,
            elapsed_ms=elapsed_ms,
            dropped_actions=dropped_actions,
        )
        if not self.emit(event, critical=critical) and turn.round_no % 30 == 0:
            self.emit(
                {
                    "v": 2,
                    "event": "checkpoint",
                    "r": turn.round_no,
                    "gold": turn.team_our.gold,
                    "score": turn.team_our.total_score,
                    "errors": [error.error_code for error in turn.errors],
                },
                critical=True,
            )
