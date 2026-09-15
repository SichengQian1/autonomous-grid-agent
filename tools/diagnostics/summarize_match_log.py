#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


MAX_BYTES = 16 * 1024 * 1024


def records_from_file(path: Path, max_records: int) -> Iterable[dict[str, Any]]:
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError(f"log exceeds the {MAX_BYTES}-byte safety limit")
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, list):
        candidates = value
    elif isinstance(value, dict):
        candidates = [value]
    else:
        candidates = []
        for line in text.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                candidates.append(item)
            if len(candidates) >= max_records:
                break
    yield from (item for item in candidates[:max_records] if isinstance(item, dict))


def summarize(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    sides: Counter[str] = Counter()
    target_team = Counter()
    errors: Counter[str] = Counter()
    action_results = Counter()
    waves: dict[int, Counter[str]] = defaultdict(Counter)
    spawns: dict[int, list[dict[str, int]]] = defaultdict(list)
    first_positions: dict[int, list[list[dict[str, int]]]] = defaultdict(list)
    first_boss_day: int | None = None
    cooldowns: dict[int, list[int]] = defaultdict(list)
    health_min: dict[int, dict[str, int]] = defaultdict(dict)
    build_results: list[dict[str, object]] = []
    previous_builds: dict[str, dict[str, object]] = {}
    own_clear_round: dict[int, int] = {}
    enemy_clear_round: dict[int, int] = {}
    count = 0

    for record in records:
        payload = record.get("request", record)
        if not isinstance(payload, dict):
            continue
        response = record.get("response") if isinstance(record.get("response"), dict) else {}
        count += 1
        round_no = _integer(payload.get("roundNo"))
        day = max(round_no - 1, 0) // 130 + 1
        round_in_day = max(round_no - 1, 0) % 130 + 1
        team = payload.get("teamOur") if isinstance(payload.get("teamOur"), dict) else {}
        side = team.get("type")
        if isinstance(side, str):
            sides[side] += 1
        robots_box = payload.get("robot") if isinstance(payload.get("robot"), dict) else {}
        robots = robots_box.get("roles") if isinstance(robots_box.get("roles"), list) else []
        if 71 <= round_in_day <= 130:
            own_present = False
            enemy_present = False
            for robot in robots:
                if not isinstance(robot, dict):
                    continue
                kind = robot.get("roleType") if isinstance(robot.get("roleType"), str) else "unknown"
                waves[day][kind] += 1
                if kind == "bossRobot" and first_boss_day is None:
                    first_boss_day = day
                team_value = robot.get("targetTeam")
                target_team["present" if isinstance(team_value, str) and team_value else "missing"] += 1
                if isinstance(team_value, str) and team_value:
                    if team_value == side:
                        own_present = True
                    else:
                        enemy_present = True
            if own_present:
                own_clear_round[day] = round_in_day
            if enemy_present:
                enemy_clear_round[day] = round_in_day
            positions = [robot.get("pos") for robot in robots if isinstance(robot, dict) and isinstance(robot.get("pos"), dict)]
            if round_in_day == 71:
                spawns[day] = positions[:20]
            if round_in_day <= 75:
                first_positions[day].append(positions[:20])
        roles = team.get("roles") if isinstance(team.get("roles"), list) else []
        for role in roles:
            if not isinstance(role, dict):
                continue
            kind = role.get("roleType") if isinstance(role.get("roleType"), str) else "unknown"
            health = _integer(role.get("health"))
            if kind in {"station", "wall", "gatling", "railgun", "rocket"}:
                prior = health_min[day].get(kind)
                health_min[day][kind] = health if prior is None else min(prior, health)
            if kind == "rocket":
                cooldowns[day].append(_integer(role.get("cooldown")))
        feedback = payload.get("lastRoundRoleActionResults")
        if isinstance(feedback, dict):
            for actor_id, succeeded in feedback.items():
                if isinstance(succeeded, bool):
                    action_results["success" if succeeded else "failure"] += 1
                    build = previous_builds.get(str(actor_id))
                    if build is not None and len(build_results) < 50:
                        build_results.append({**build, "success": succeeded})
        error_list = payload.get("errors")
        if isinstance(error_list, list):
            for error in error_list:
                if isinstance(error, dict):
                    errors[str(_integer(error.get("errorCode")))] += 1
        commands = response.get("roleCommandMap") if isinstance(response, dict) else None
        previous_builds = {}
        if isinstance(commands, dict):
            for actor_id, command in commands.items():
                if not isinstance(command, dict) or command.get("action") != "build":
                    continue
                targets = command.get("targetPos")
                if isinstance(targets, list) and targets and isinstance(targets[0], dict):
                    previous_builds[str(actor_id)] = {
                        "round": round_no,
                        "name": command.get("name", "unknown"),
                        "position": {
                            "x": _integer(targets[0].get("x")),
                            "y": _integer(targets[0].get("y")),
                        },
                    }

    return {
        "records": count,
        "sides": dict(sides),
        "targetTeam": dict(target_team),
        "actionResults": dict(action_results),
        "errorCodes": dict(errors),
        "firstBossDay": first_boss_day,
        "nightWaveTypeObservations": {str(day): dict(counts) for day, counts in sorted(waves.items())},
        "spawnPositions": {str(day): values for day, values in sorted(spawns.items())},
        "firstFiveNightPositions": {str(day): values for day, values in sorted(first_positions.items())},
        "minimumKeyHealth": {str(day): values for day, values in sorted(health_min.items())},
        "rocketCooldownSamples": {
            str(day): values[:30] for day, values in sorted(cooldowns.items())
        },
        "lastObservedOwnThreatRoundInNight": {str(day): value for day, value in sorted(own_clear_round.items())},
        "lastObservedEnemyThreatRoundInNight": {str(day): value for day, value in sorted(enemy_clear_round.items())},
        "buildResults": build_results,
        "note": "Sanitized bounded summary; no team IDs, names, prompts, or raw error descriptions are emitted.",
    }


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only bounded summary of JSON or JSONL match requests.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--max-records", type=int, default=2000)
    args = parser.parse_args()
    if not args.path.is_file():
        parser.error("path must be an existing log file")
    try:
        result = summarize(records_from_file(args.path, max(1, min(args.max_records, 5000))))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
