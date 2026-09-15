"""Small synthetic transition harness, not a competition rules engine.

Models economy and movement only. Combat geometry, platform scoring, enemy
strategy and task correctness must be checked separately.
"""
from __future__ import annotations

from collections import Counter

from solution.geometry import Pos, station_footprint
from tests.helpers import role
from tests.scenarios import arena


class EconomySimulation:
    def __init__(self, *, mirrored: bool = False):
        self.raw = arena()
        self.counts = Counter()
        self.events = []
        self.first_three_weapons = None
        if mirrored:
            self.raw["teamOur"]["type"] = "defender"
            for unit in self.raw["teamOur"]["roles"]:
                x, y = unit["pos"]["x"], unit["pos"]["y"]
                if unit["roleType"] == "station":
                    unit["pos"] = {"x": 22 - x, "y": 20 - y}
                else:
                    unit["pos"] = {"x": 23 - x, "y": 19 - y}
            for zone in self.raw["mapInfo"]["zones"]:
                zone["pos"] = {"x": 23 - zone["pos"]["x"], "y": 19 - zone["pos"]["y"]}

    def apply(self, response):
        raw = self.raw
        roles = {str(unit["id"]): unit for unit in raw["teamOur"]["roles"]}
        commands = response["roleCommandMap"]
        blocked = {tuple(z["pos"].values()) for z in raw["mapInfo"]["zones"]}
        for unit in roles.values():
            if unit["health"] <= 0:
                continue
            p = Pos.from_raw(unit["pos"])
            cells = station_footprint(p) if unit["roleType"] == "station" else (p,)
            blocked.update((p.x, p.y) for p in cells)
        reserved = set()
        for key, action in commands.items():
            unit = roles[key]
            kind = action["action"]
            target = Pos.from_raw(action["targetPos"][0]) if action.get("targetPos") else None
            if kind in {"move", "build"}:
                assert target is not None and Pos.from_raw(unit["pos"]).distance_to(target) == 1
                assert (target.x, target.y) not in blocked | reserved, (raw["roundNo"], kind, target)
                reserved.add((target.x, target.y))
            if kind == "move":
                unit["pos"] = target.to_raw()
            elif kind == "build":
                name = action["name"]
                if name == "wall":
                    unit["backpack"].remove("stone")
                else:
                    assert raw["teamOur"]["goldNum"] >= 25
                    raw["teamOur"]["goldNum"] -= 25
                new = role(max(int(k) for k in roles) + 100 + len(reserved), name, target.x, target.y, health=1000, level=1,
                           attack_range={"railgun": 6, "rocket": 10, "gatling": 3}.get(name, 0))
                new["attackPower"] = 20 if name == "rocket" else 10
                raw["teamOur"]["roles"].append(new)
            elif kind == "collect":
                zone = next(z for z in raw["mapInfo"]["zones"] if z["pos"] == target.to_raw())
                unit["backpack"].append(zone["neutralType"])
            elif kind == "sell":
                price = next(item["price"] for item in raw["vendorShopList"] if item["name"] == action["name"])
                for _ in range(action["num"]):
                    unit["backpack"].remove(action["name"])
                raw["teamOur"]["goldNum"] += price * action["num"]
            elif kind == "buy":
                price = next(item["price"] for item in raw["weaponShopList"] if item["name"] == action["name"])
                assert raw["teamOur"]["goldNum"] >= price * action["num"]
                raw["teamOur"]["goldNum"] -= price * action["num"]
                unit["backpack"].extend([action["name"]] * action["num"])
            elif kind == "use":
                unit["backpack"].remove(action["name"])
                if action["name"] == "Medicine":
                    unit["health"] = 200 if unit["roleType"] == "pioneer" else 220
                elif action["name"] == "WallFixer":
                    building = next(u for u in roles.values() if u["pos"] == target.to_raw())
                    building["health"] = {1: 1000, 2: 1500, 3: 2000}.get(building["level"], building["health"])
                elif action["name"].startswith("WallUpgradeVoucher"):
                    building = next(u for u in roles.values() if u["pos"] == target.to_raw())
                    building["level"] += 1
                    building["health"] = {2: 1500, 3: 2000}.get(building["level"], building["health"] + 500)
                else:
                    building = next(u for u in roles.values() if u["pos"] == target.to_raw())
                    building["level"] += 1
                    building["health"] += 500
                    building["attackRange"] += 2
                    if building["roleType"] == "railgun":
                        building["attackPower"] += 10
            else:
                raise AssertionError(f"Unsupported synthetic transition: {kind}")
            self.counts[kind] += 1
        self.events.append((raw["roundNo"], response["roleCommandMap"]))
        if self.first_three_weapons is None and sum(u["roleType"] in {"railgun", "rocket", "gatling"} for u in raw["teamOur"]["roles"]) == 3:
            self.first_three_weapons = raw["roundNo"]
        raw["lastRoundRoleActionResults"] = {key: True for key in commands}
        raw["roundNo"] += 1
