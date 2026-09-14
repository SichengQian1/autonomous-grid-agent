"""Original, synthetic scenarios; no platform payloads or identifiers."""
from __future__ import annotations

from tests.helpers import role


def arena(round_no: int = 1, *, armed: bool = False) -> dict:
    roles = [role(1, "worker", 5, 15), role(2, "worker", 5, 16),
             role(3, "pioneer", 4, 17), role(4, "station", 3, 16, health=1500, level=1)]
    if armed:
        roles.extend([role(11, "railgun", 5, 14, attack_range=8, level=2),
                      role(12, "railgun", 3, 14, attack_range=8, level=2),
                      role(13, "rocket", 5, 17, attack_range=15, level=2)])
        roles[1]["pos"] = {"x": 2, "y": 14}
        for unit in roles:
            if unit["roleType"] in {"railgun", "rocket"}:
                unit["attackPower"] = 20
    return {
        "roundNo": round_no,
        "mapInfo": {"width": 24, "height": 20, "zones": [
            {"neutralType": "stone", "pos": {"x": 7, "y": 15}},
            {"neutralType": "iron", "pos": {"x": 8, "y": 17}},
            {"neutralType": "vendor", "pos": {"x": 8, "y": 14}},
            {"neutralType": "weaponShop", "pos": {"x": 7, "y": 18}},
            {"neutralType": "challengerTaskPoint1", "pos": {"x": 9, "y": 18}},
        ]},
        "teamOur": {"type": "challenger", "teamId": "synthetic", "goldNum": 75,
                    "roles": roles, "playerTasks": []},
        "teamEnemy": {"roles": []}, "robot": {"roles": []}, "phaseTask": "", "llmResp": "",
        "worldNews": {}, "weaponShopList": [{"name": "Medicine", "price": 10},
            {"name": "WeaponUpgradeVoucher1", "price": 100}, {"name": "WeaponUpgradeVoucher2", "price": 150},
            {"name": "StationUpgradeVoucher1", "price": 100}],
        "vendorShopList": [{"name": "stone", "price": 1}, {"name": "iron", "price": 3}],
        "lastRoundRoleActionResults": {}, "lastCmdResult": "", "errors": [],
    }


def robot(robot_id: int, x: int, y: int, health: int = 40, target: str = "challenger") -> dict:
    return {"id": robot_id, "pos": {"x": x, "y": y}, "health": health,
            "roleType": "smallRobot", "targetTeam": target}
