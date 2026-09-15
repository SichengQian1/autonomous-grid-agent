#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from solution.engine import AgentEngine


def unit(
    unit_id: int,
    role_type: str,
    x: int,
    y: int,
    *,
    health: int = 220,
    level: int = 0,
    attack_power: int = 0,
    attack_range: int = 0,
    backpack: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": unit_id,
        "pos": {"x": x, "y": y},
        "roleType": role_type,
        "health": health,
        "attackPower": attack_power,
        "attackRange": attack_range,
        "backPackCapability": 100,
        "backpack": list(backpack or ()),
        "level": level,
        "cooldown": 0,
    }


@dataclass
class ReplayStats:
    rounds: int = 0
    active_rounds: int = 0
    invalid_responses: int = 0
    max_decision_ms: float = 0.0
    minimum_gold: int = 10**9
    failed_actions: int = 0
    final_weapon_count: int = 0


class SyntheticWorld:
    """Small deterministic harness, not an official game simulation."""

    def __init__(self, side: str = "challenger") -> None:
        mirrored = side == "defender"
        self.side = side
        station = unit(10, "station", 10 if mirrored else 0, 1 if mirrored else 9, health=1500, level=1)
        self.roles = [
            unit(1, "worker", 7 if mirrored else 3, 4, backpack=["stone", "stone"]),
            unit(2, "worker", 8 if mirrored else 2, 5),
            unit(3, "pioneer", 9 if mirrored else 1, 5),
            station,
        ]
        self.robots: list[dict[str, Any]] = []
        self.gold = 75
        self.feedback: dict[str, bool] = {}
        self.next_id = 100

    def request(self, round_no: int) -> dict[str, Any]:
        round_in_day = (round_no - 1) % 130 + 1
        if round_in_day == 71:
            spawn_x = 1 if self.side == "defender" else 10
            self.robots = [
                {
                    "id": 5000 + round_no,
                    "pos": {"x": spawn_x, "y": 8 if self.side == "defender" else 7},
                    "roleType": "bossRobot" if round_no >= 461 else "smallRobot",
                    "health": 120 if round_no >= 461 else 40,
                    "attackPower": 40 if round_no >= 461 else 5,
                    "attackRange": 3,
                    "abnormalState": "",
                    "targetTeam": self.side,
                }
            ]
        elif round_in_day == 1:
            self.robots = []
        return {
            "roundNo": round_no,
            "mapInfo": {
                "width": 12,
                "height": 10,
                "zones": [
                    {"pos": {"x": 5, "y": 2}, "neutralType": "stone"},
                    {"pos": {"x": 5, "y": 5}, "neutralType": "iron"},
                    {"pos": {"x": 6, "y": 4}, "neutralType": "vendor"},
                    {"pos": {"x": 6, "y": 6}, "neutralType": "weaponShop"},
                ],
            },
            "teamOur": {
                "type": self.side,
                "teamId": "synthetic",
                "teamName": "Synthetic",
                "goldNum": self.gold,
                "totalScore": 0,
                "playerTasks": [],
                "roles": self.roles,
            },
            "teamEnemy": {"roles": []},
            "robot": {"roles": self.robots},
            "phaseTask": "",
            "lastRoundRoleActionResults": self.feedback,
            "lastSummonTreasureResult": 0,
            "llmResp": "",
            "worldNews": {"officialNews": "", "folkLegends": ""},
            "lastCmdResult": "",
            "vendorShopList": [
                {"name": "stone", "price": 1},
                {"name": "iron", "price": 3},
            ],
            "weaponShopList": [
                {"name": "WeaponUpgradeVoucher1", "price": 100},
                {"name": "BossRobotSummonOrder", "price": 200},
            ],
            "errors": [],
        }

    def apply(self, response: dict[str, Any]) -> None:
        commands = response.get("roleCommandMap", {})
        self.feedback = {str(actor_id): True for actor_id in commands}
        by_id = {str(role["id"]): role for role in self.roles}
        for actor_id, command in commands.items():
            actor = by_id.get(actor_id)
            action = command.get("action")
            if actor is not None and action == "move":
                actor["pos"] = dict(command["targetPos"][0])
            elif actor is not None and action == "build":
                name = command.get("name")
                target = command["targetPos"][0]
                if name in {"gatling", "railgun", "rocket"} and self.gold >= 25:
                    self.gold -= 25
                    self.roles.append(
                        unit(
                            self.next_id,
                            name,
                            target["x"],
                            target["y"],
                            health=1000,
                            level=1,
                            attack_power=20 if name == "rocket" else 10,
                            attack_range=10 if name == "rocket" else 7,
                        )
                    )
                    self.next_id += 1
                elif name == "wall" and "stone" in actor["backpack"]:
                    actor["backpack"].remove("stone")
                    self.roles.append(unit(self.next_id, "wall", target["x"], target["y"], health=1000, level=1))
                    self.next_id += 1
                else:
                    self.feedback[actor_id] = False
            elif actor is not None and action == "collect":
                actor["backpack"].append("stone")
            elif actor is not None and action == "sell":
                name = command.get("name", "")
                quantity = min(command.get("num", 0), actor["backpack"].count(name))
                for _ in range(quantity):
                    actor["backpack"].remove(name)
                self.gold += quantity * (3 if name == "iron" else 1)
            elif action == "attack" and self.robots:
                damage = 20 if by_id.get(actor_id, {}).get("roleType") == "rocket" else 10
                self.robots[0]["health"] = max(0, self.robots[0]["health"] - damage)
                self.robots = [robot for robot in self.robots if robot["health"] > 0]


def run_synthetic_match(rounds: int = 1300, side: str = "challenger") -> ReplayStats:
    world = SyntheticWorld(side)
    engine = AgentEngine()
    stats = ReplayStats()
    for round_no in range(1, rounds + 1):
        started = time.perf_counter()
        response = engine.decide(world.request(round_no))
        elapsed_ms = (time.perf_counter() - started) * 1000
        stats.max_decision_ms = max(stats.max_decision_ms, elapsed_ms)
        stats.rounds += 1
        try:
            json.dumps(response)
            valid = isinstance(response, dict) and isinstance(response.get("roleCommandMap"), dict)
        except (TypeError, ValueError):
            valid = False
        if not valid:
            stats.invalid_responses += 1
            continue
        if response["roleCommandMap"] or response.get("prompt") or response.get("executeCmd"):
            stats.active_rounds += 1
        world.apply(response)
        stats.minimum_gold = min(stats.minimum_gold, world.gold)
        stats.failed_actions += sum(1 for succeeded in world.feedback.values() if not succeeded)
    stats.final_weapon_count = sum(
        1 for role in world.roles if role["roleType"] in {"gatling", "railgun", "rocket"}
    )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a synthetic protocol regression, not an official simulator.")
    parser.add_argument("--rounds", type=int, default=1300)
    parser.add_argument("--side", choices=("challenger", "defender"), default="challenger")
    args = parser.parse_args()
    stats = run_synthetic_match(max(1, min(args.rounds, 1300)), args.side)
    print(json.dumps(stats.__dict__, sort_keys=True))
    return 0 if stats.invalid_responses == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
