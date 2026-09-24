from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import zlib
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping

from .models import Turn


from .log_crypto import seal, unseal, MAX_MESSAGE
from .log_keys import ACTIVE_KEY_ID, LOG_KEYS

LOGGER = logging.getLogger("aglog")
PREFIX = "AGLOG3 "
LEGACY_PREFIX = "AGLOG2 "
PREFIXES = (PREFIX, LEGACY_PREFIX)
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
    if len(raw)>MAX_MESSAGE:raise ValueError('log event too large')
    compressed=zlib.compress(raw,level=6)
    # Random across restarts and independent matches, unlike the old sequence nonce.
    nonce=secrets.token_bytes(12)
    header=(PREFIX+ACTIVE_KEY_ID+' ').encode('ascii')
    sealed=seal(LOG_KEYS[ACTIVE_KEY_ID],nonce,compressed,header)
    return header.decode('ascii')+base64.b85encode(nonce+sealed).decode('ascii')


def _inflate(raw: bytes) -> dict[str, Any]:
    decoder=zlib.decompressobj()
    plain=decoder.decompress(raw,MAX_MESSAGE+1)
    if len(plain)>MAX_MESSAGE or not decoder.eof or decoder.unused_data:
        raise ValueError('invalid or oversized log payload')
    value=json.loads(plain)
    if not isinstance(value,dict):raise ValueError('log payload must be an object')
    return value


def decode_event(line: str) -> dict[str, Any]:
    marker=line.find(PREFIX)
    if marker>=0:
        tokens=line[marker+len(PREFIX):].strip().split()
        if len(tokens)<2:raise ValueError('truncated AGLOG3 record')
        key_id,token=tokens[:2]
        if key_id not in LOG_KEYS:raise ValueError('unknown log key ID: '+key_id[:32])
        if len(token)>MAX_MESSAGE*2:raise ValueError('oversized AGLOG3 record')
        try:
            packed=base64.b85decode(token.encode('ascii'))
            if len(packed)<28:raise ValueError('truncated AGLOG3 payload')
            return _inflate(unseal(LOG_KEYS[key_id],packed[:12],packed[12:],(PREFIX+key_id+' ').encode('ascii')))
        except (ValueError,UnicodeError,zlib.error) as error:
            raise ValueError('invalid AGLOG3: '+str(error)) from error
    marker = line.find(LEGACY_PREFIX)
    if marker < 0:
        raise ValueError("not an AGLOG2 record")
    tokens = line[marker + len(LEGACY_PREFIX):].strip().split()
    if not tokens:
        raise ValueError("empty AGLOG2 record")
    token = tokens[0]
    if len(token)>MAX_MESSAGE*2:raise ValueError("oversized AGLOG2 record")
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
        value = _inflate(_xor_stream(cipher, nonce))
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
    from .economy import front_wall_number, wall_level_goal, due_defense_targets
    from .rules import DEFAULT_CONFIG
    from .maintenance import wall_damage_risk
    from .defense import own_threats
    station = turn.team_our.station()
    threats = own_threats(turn)
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
            targets = raw_command.get("targetPos")
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
        "agentVersion": "v0.19",
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
        "treasureResult": turn.last_summon_treasure_result,
        "map": {"width": turn.map_info.width, "height": turn.map_info.height},
        "defenseSchedule": {
            "due": [[u.role_type, front_wall_number(turn,u) if u.role_type=='wall' else None, u.level]
                    for u in due_defense_targets(turn,DEFAULT_CONFIG)],
            "frontWalls": [[front_wall_number(turn,u),u.health,u.level,wall_level_goal(turn,u),
                            *wall_damage_risk(u,DEFAULT_CONFIG,threats)]
                           for u in turn.team_our.roles if u.role_type=='wall' and u.alive and front_wall_number(turn,u)],
            "repairStock": {str(u.unit_id):u.backpack.count('WallFixer') for u in turn.controllable},
        },
        "readiness": {
            "weapons": sum(u.is_weapon and u.alive for u in turn.team_our.roles),
            "walls": sum(u.role_type == "wall" and u.alive for u in turn.team_our.roles),
        },
        "prices": {i.name:i.price for i in turn.vendor_shop if i.name in {"stone","iron","copper"}},
        "tasks": [{"position":_pos(t.task_position),"valid":t.is_valid,"cooldown":t.cooldown_rounds,
                   "timeout":t.timeout_rounds,"score":t.score_reward,"gold":t.gold_reward} for t in turn.team_our.player_tasks[:4]],
    }


@dataclass(slots=True)
class Telemetry:
    byte_budget: int
    reserve_bytes: int
    used_bytes: int = 0
    sequence: int = 0
    generation: int = -1
    zone_signature: tuple = ()
    dropped_events: int = 0

    def emit(self, event: Mapping[str, Any], *, critical: bool = False) -> bool:
        try:
            line = encode_event(self.sequence, event)
            size = len(line.encode("utf-8")) + 64  # Include logging prefix/newline.
            normal_limit = max(0, self.byte_budget - self.reserve_bytes)
            limit = self.byte_budget if critical else normal_limit
            # Keep a separate part of the existing budget for all 60 final-night
            # turns. Earlier "critical" traces must not consume this reserve.
            final_turn=event.get('event')=='turn' and event.get('r',0)>=1241
            if critical and not final_turn and self.byte_budget>=256*1024:
                limit=min(limit,self.byte_budget-min(self.reserve_bytes*3//4,192*1024))
            if self.used_bytes + size > limit:
                self.dropped_events += 1
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
        diagnostics: Mapping[str, Any] | None = None,
    ) -> None:
        critical = bool(turn.errors) or turn.round_in_day in {1, 70, 71, 130} or turn.round_no>=1241
        if turn.team_our.station() is None and not critical and turn.round_no % 30:
            return
        event = build_turn_event(
            turn,
            response,
            elapsed_ms=elapsed_ms,
            dropped_actions=dropped_actions,
        )
        event["diagnostics"] = dict(diagnostics or {})
        event['logDroppedEvents']=self.dropped_events
        # Distribute the budget across the match instead of spending it in opening nights.
        allowance = 32000 + (self.byte_budget-self.reserve_bytes)*min(turn.round_no,1300)//1300
        if self.used_bytes > allowance and not critical:
            for key in ("robots","enemyBuildings","robotCounts","map","tasks"):
                event.pop(key,None)
            event["roles"] = [u for u in event["roles"] if u[1] != "wall"]
            event["detail"] = "compact"
        zones = tuple(sorted((z.neutral_type, z.pos.x, z.pos.y) for z in turn.map_info.zones if z.pos is not None))
        if turn.round_in_day == 1 or zones != self.zone_signature:
            event["zones"] = [[z.neutral_type, _pos(z.pos)] for z in turn.map_info.zones][:100]
        emitted = self.emit(event, critical=critical)
        if emitted:
            self.zone_signature = zones
        if not emitted and turn.round_no % 30 == 0:
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
