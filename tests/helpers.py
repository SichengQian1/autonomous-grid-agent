from __future__ import annotations

from typing import Any


def synthetic_turn(*, round_no: int = 71) -> dict[str, Any]:
    return {
        "roundNo": round_no,
        "mapInfo": {
            "width": 12,
            "height": 10,
            "zones": [
                {"pos": {"x": 2, "y": 2}, "neutralType": "stone"},
                {"pos": {"x": 4, "y": 4}, "neutralType": "vendor"},
                {"pos": {"x": 7, "y": 7}, "neutralType": "weaponShop"},
            ],
        },
        "teamOur": {
            "type": "challenger",
            "teamId": "synthetic-team",
            "teamName": "Synthetic",
            "goldNum": 75,
            "totalScore": 0,
            "playerTasks": [
                {
                    "taskType": "synthetic-task",
                    "taskPosition": {"x": 3, "y": 3},
                    "coldDownRounds": 0,
                    "scoreReward": 10,
                    "goldReward": 5,
                    "isValid": True,
                    "timeoutRounds": 20,
                }
            ],
            "roles": [
                role(1, "worker", 1, 1, backpack=["stone", "stone"]),
                role(2, "pioneer", 3, 2, backpack=["Token", "Medicine"]),
                role(3, "station", 0, 9, health=1500, level=1),
                role(4, "railgun", 2, 1, attack_range=6, level=1),
                role(5, "rocket", 4, 2, attack_range=10, level=2),
                role(6, "gatling", 4, 4, attack_range=5, level=2),
                role(7, "worker", 4, 3),
            ],
        },
        "teamEnemy": {
            "roles": [role(20, "wall", 9, 1, health=1000, level=1)]
        },
        "robot": {
            "roles": [
                {
                    "id": 30,
                    "pos": {"x": 8, "y": 8},
                    "roleType": "smallRobot",
                    "health": 40,
                    "abnormalState": "",
                    "targetTeam": "challenger",
                }
            ]
        },
        "phaseTask": "synthetic active task",
        "lastRoundRoleActionResults": {"1": True},
        "lastSummonTreasureResult": 0,
        "llmResp": "",
        "worldNews": {
            "officialNews": "synthetic official news",
            "folkLegends": "synthetic legend",
        },
        "lastCmdResult": "",
        "vendorShopList": [
            {"name": "stone", "price": 1},
            {"name": "iron", "price": 3},
        ],
        "weaponShopList": [
            {"name": "Medicine", "price": 10},
            {"name": "Bomb", "price": 100},
        ],
        "errors": [],
    }


def role(
    unit_id: int,
    role_type: str,
    x: int,
    y: int,
    *,
    health: int = 200,
    attack_range: int = 0,
    level: int = 0,
    cooldown: int = 0,
    backpack: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": unit_id,
        "pos": {"x": x, "y": y},
        "roleType": role_type,
        "health": health,
        "attackPower": 0,
        "attackRange": attack_range,
        "backPackCapability": 100,
        "backpack": backpack or [],
        "level": level,
        "cooldown": cooldown,
    }
