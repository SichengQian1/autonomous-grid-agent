from __future__ import annotations

from collections import Counter

from .actions import Action, ActionType
from .defense import base_cells, weapon_sites, wall_sites
from .geometry import Pos, footprint_distance, neighbours
from .layout import (
    built_or_submitted_walls,
    remaining_weapon_placements,
    remaining_wall_sites,
    site_build_ready,
)
from .models import Unit
from .planning import PlanningContext
from .rules import (
    DEFENSE_LAYOUT_FRONTLINE,
    RESOURCE_ZONE_TYPES,
    ROLE_ROCKET,
    ROLE_WORKER,
    WEAPON_BUILD_COST,
)


class EconomyPlanner:
    def __init__(self, context: PlanningContext) -> None:
        self.ctx = context
        self.turn, self.config, self.nav = context.turn, context.config, context.nav

    def _travel(self, role: Unit, target: Pos, action: Action, max_trip: int | None = None) -> bool:
        if not self.turn.is_day and footprint_distance(target, base_cells(self.turn)) > self.config.night_trip_radius:
            return False
        route = self.nav.adjacent_route(role, target)
        if route is None or (max_trip is not None and route.distance > max_trip):
            return False
        if route.distance == 0:
            return self.ctx.add(action)
        return self.ctx.move(role, route)

    def heal(self, role: Unit) -> bool:
        if role.health < self.config.heal_below and "Medicine" in role.backpack:
            return self.ctx.add(Action(role.unit_id, ActionType.USE, name="Medicine"))
        return False

    def emergency_repair(self, role: Unit) -> bool:
        station = self.turn.team_our.station()
        if (station is None or station.pos is None or not station.alive
                or station.health >= self.config.base_emergency_health or station.level not in {1, 2}):
            return False
        item = f"StationUpgradeVoucher{station.level}"
        key = ("upgrade", station.unit_id)
        if key in self.ctx.claimed or item not in role.backpack or role.pos is None:
            return False
        if footprint_distance(role.pos, station.footprint()) > 1:
            return False
        if self.ctx.add(Action(role.unit_id, ActionType.USE, name=item, targets=(station.pos,))):
            self.ctx.claimed.add(key)
            return True
        return False

    def build(self, role: Unit) -> bool:
        return self.build_weapons(role) or self.build_planned_walls(role)

    def build_weapons(self, role: Unit) -> bool:
        if role.role_type != ROLE_WORKER or not self.turn.is_day:
            return False
        weapons = [w for w in self.turn.team_our.roles if w.alive and w.is_weapon]
        queued = [a for a in self.ctx.actions if a.action_type == ActionType.BUILD and a.name != "wall"]
        needed = list(self.config.primary_weapon_loadout)
        for name in [w.role_type for w in weapons] + [a.name for a in queued]:
            if name in needed:
                needed.remove(name)
        if len(weapons) + len(queued) >= 3 or not needed or self.ctx.gold < WEAPON_BUILD_COST:
            return False
        layout = self.ctx.layout
        if self.config.defense_layout == DEFENSE_LAYOUT_FRONTLINE and layout is not None:
            for placement in remaining_weapon_placements(self.turn, layout):
                if placement.pos in self.nav.occupied or placement.pos in self.ctx.claimed:
                    continue
                action = Action(role.unit_id, ActionType.BUILD, targets=(placement.pos,),
                                name=placement.role_type)
                if self._travel(role, placement.pos, action):
                    self.ctx.claimed.add(placement.pos)
                    return True
            return False
        for site in weapon_sites(self.turn):
            if site in self.nav.occupied or site in self.ctx.claimed:
                continue
            action = Action(role.unit_id, ActionType.BUILD, targets=(site,), name=needed[0])
            if self._travel(role, site, action):
                self.ctx.claimed.add(site)
                return True
        return False

    def build_planned_walls(self, role: Unit) -> bool:
        if role.role_type != ROLE_WORKER or not self.turn.is_day:
            return False
        weapons = [w for w in self.turn.team_our.roles if w.alive and w.is_weapon]
        queued = [a for a in self.ctx.actions if a.action_type == ActionType.BUILD and a.name != "wall"]
        if len(weapons) + len(queued) < min(3, len(self.config.primary_weapon_loadout)):
            return False
        if "stone" not in role.backpack:
            return False
        layout = self.ctx.layout
        if self.config.defense_layout == DEFENSE_LAYOUT_FRONTLINE and layout is not None:
            extra = set(layout.gates)
            built = built_or_submitted_walls(self.turn, self.ctx.actions)
            for site in remaining_wall_sites(self.turn, layout):
                if site in self.nav.occupied or site in self.ctx.claimed or site in extra:
                    continue
                if not site_build_ready(layout, site, built):
                    continue
                route = self.nav.adjacent_route(role, site)
                if route is None:
                    continue
                controllers = tuple(cell for w in layout.weapons for cell in w.controller_cells)
                if route.distance == 0 and not self._preserves_exit(site, extra_starts=controllers):
                    continue
                if self._travel(role, site, Action(role.unit_id, ActionType.BUILD, targets=(site,), name="wall")):
                    self.ctx.claimed.add(site)
                    return True
            return False
        for site in wall_sites(self.turn, self.config.max_walls):
            if site in self.nav.occupied or site in self.ctx.claimed:
                continue
            # Do not wall a controller into an isolated pocket. A build is allowed only
            # while all living roles can still reach the permanent ring entrance.
            route = self.nav.adjacent_route(role, site)
            if route is None:
                continue
            if route.distance == 0 and not self._preserves_exit(site):
                continue
            if self._travel(role, site, Action(role.unit_id, ActionType.BUILD, targets=(site,), name="wall")):
                self.ctx.claimed.add(site)
                return True
        return False

    def _preserves_exit(self, site: Pos, extra_starts: tuple[Pos, ...] = ()) -> bool:
        from collections import deque
        blocked = self.nav.occupied | self.nav.reserved | {site}
        starts = [role.pos for role in self.turn.team_our.roles
                  if role.alive and role.is_human and role.pos is not None]
        starts.extend(cell for cell in extra_starts if cell not in blocked or cell == site)
        if not starts:
            return True
        for start in starts:
            if start is None:
                continue
            queue = deque([start])
            seen = {start}
            escaped = False
            while queue and len(seen) < 128:
                point = queue.popleft()
                if footprint_distance(point, base_cells(self.turn)) >= 3:
                    escaped = True
                    break
                for nxt in neighbours(point):
                    if nxt not in blocked and nxt not in seen and self.turn.map_info.contains(nxt):
                        seen.add(nxt)
                        queue.append(nxt)
            if not escaped:
                return False
        return True

    def supplies(self, role: Unit, max_trip: int | None = None) -> bool:
        # Deliver already-owned vouchers before buying another copy.
        for item in role.backpack:
            if item == "WallFixer":
                if self.config.wall_maintenance_enabled:
                    continue
                targets = [u for u in self.turn.team_our.roles if u.alive and u.role_type == "wall" and u.health < 500]
            elif "UpgradeVoucher" in item and item[-1:] in {"1", "2"}:
                targets = [u for u in self.turn.team_our.roles if u.alive and u.level == int(item[-1])
                           and ((item.startswith("Weapon") and u.is_weapon)
                                or (item.startswith("Station") and u.role_type == "station")
                                or (item.startswith("Wall") and u.role_type == "wall" and not self.config.wall_maintenance_enabled))]
            else:
                continue
            for target in sorted(targets, key=lambda u: (u.health, u.unit_id)):
                key = ("upgrade", target.unit_id)
                if target.pos is None or key in self.ctx.claimed:
                    continue
                # Use the station's raw anchor, while allowing adjacency to any footprint cell.
                goals = tuple(p for cell in target.footprint() for p in neighbours(cell))
                route = self.nav.route(role, goals)
                if route and (max_trip is None or route.distance <= max_trip):
                    action = Action(role.unit_id, ActionType.USE, name=item, targets=(target.pos,))
                    if (self.ctx.add(action) if route.distance == 0 else self.ctx.move(role, route)):
                        self.ctx.claimed.add(key)
                        return True
        desired = self._desired_purchase(role)
        if desired is None:
            return False
        item, price = desired
        for shop in self.turn.zone_positions("weaponShop"):
            action = Action(role.unit_id, ActionType.BUY, name=item, quantity=1)
            if self._travel(role, shop, action, max_trip):
                self.ctx.claimed.add(("buy", item))
                return True
        return False

    def _desired_purchase(self, role: Unit) -> tuple[str, int] | None:
        if len(role.backpack) >= role.backpack_capacity:
            return None
        weapons = [w for w in self.turn.team_our.roles if w.alive and w.is_weapon]
        reserve = max(0, 3 - len(weapons)) * WEAPON_BUILD_COST
        station = self.turn.team_our.station()
        desired = []
        if role.health < self.config.heal_below and "Medicine" not in role.backpack:
            desired.append("Medicine")
        if station and station.level in {1, 2} and station.health < self.config.base_emergency_health:
            desired.append(f"StationUpgradeVoucher{station.level}")
        for weapon in sorted(weapons, key=lambda w: (w.level, w.role_type != ROLE_ROCKET, w.unit_id)):
            if weapon.level in {1, 2}:
                desired.append(f"WeaponUpgradeVoucher{weapon.level}")
        if station and station.level in {1, 2}:
            desired.append(f"StationUpgradeVoucher{station.level}")
        if "Medicine" not in role.backpack:
            desired.append("Medicine")
        held = Counter(item for unit in self.turn.team_our.roles for item in unit.backpack)
        prices = {item.name: item.price for item in self.turn.weapon_shop}
        for item in desired:
            if (item != "Medicine" and held[item]) or ("buy", item) in self.ctx.claimed:
                continue
            price = prices.get(item)
            if price is not None and price <= self.ctx.gold - reserve:
                return item, price
        return None

    def gather_or_sell(self, role: Unit, max_trip: int | None = None) -> bool:
        resources = Counter(item for item in role.backpack if item in RESOURCE_ZONE_TYPES)
        full = len(role.backpack) >= role.backpack_capacity
        wall_need = self._wall_need()
        reserve = self.config.stone_reserve if wall_need else 0
        sale = {name: count - (reserve if name == "stone" else 0) for name, count in resources.items()}
        sale = {name: count for name, count in sale.items() if count > 0}
        if sale and (full or sum(sale.values()) >= self.config.sell_batch or role.role_type != ROLE_WORKER):
            for vendor in self.turn.zone_positions("vendor"):
                name = max(sale, key=lambda name: sale[name])
                if self._travel(role, vendor, Action(role.unit_id, ActionType.SELL, name=name, quantity=sale[name]), max_trip):
                    return True
        if role.role_type != ROLE_WORKER or full:
            return False
        prices = {item.name: item.price for item in self.turn.vendor_shop}
        mines = []
        for zone in self.turn.map_info.zones:
            if zone.neutral_type not in RESOURCE_ZONE_TYPES or zone.pos is None:
                continue
            if not self.ctx.state.mining.available(zone.neutral_type, self.turn.round_no):
                continue
            if not self.turn.is_day and footprint_distance(zone.pos, base_cells(self.turn)) > self.config.night_trip_radius:
                continue
            route = self.nav.adjacent_route(role, zone.pos)
            if route is None or (max_trip is not None and route.distance > max_trip):
                continue
            value = prices.get(zone.neutral_type, 1)
            if zone.neutral_type == "stone" and resources["stone"] < reserve:
                value += 8
            if self.ctx.state.action_blocked(Action(role.unit_id, ActionType.COLLECT, targets=(zone.pos,)), self.turn.round_no):
                continue
            score = value / (route.distance + self.config.sell_batch)
            mines.append((score, zone.pos, route))
        for _, pos, route in sorted(mines, key=lambda item: (-item[0], item[1])):
            if route.distance == 0:
                if self.ctx.add(Action(role.unit_id, ActionType.COLLECT, targets=(pos,))):
                    return True
            elif self.ctx.move(role, route):
                return True
        # Small inventories are still worth selling if no mine is reachable.
        if sale:
            for vendor in self.turn.zone_positions("vendor"):
                name = max(sale, key=lambda name: sale[name])
                if self._travel(role, vendor, Action(role.unit_id, ActionType.SELL, name=name, quantity=sale[name]), max_trip):
                    return True
        return False

    def _wall_need(self) -> bool:
        if not self.turn.is_day:
            return False
        layout = self.ctx.layout
        if self.config.defense_layout == DEFENSE_LAYOUT_FRONTLINE and layout is not None:
            built = built_or_submitted_walls(self.turn, self.ctx.actions)
            if len(built) >= self.config.max_walls:
                return False
            # Keep infeasible required sites for diagnostics, not endless stone reserves.
            needed = remaining_wall_sites(self.turn, layout)
            return any(site not in built for site in needed)
        return any(p not in self.nav.occupied for p in wall_sites(self.turn, self.config.max_walls))
