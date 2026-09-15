from __future__ import annotations

from collections import Counter

from .actions import Action, ActionType
from .geometry import Pos, footprint_distance, neighbours
from .layout import (
    DefenseLayout,
    WallWork,
    built_or_submitted_walls,
    _remembered_flank,
    register_delivery,
    register_wall_buy,
    remaining_wall_sites,
    site_build_ready,
    unit_recent_damage,
    wall_budget_cap,
    wall_max_health,
    wall_pressure,
    defensive_reserve,
)
from .models import Unit
from .planning import PlanningContext
from .rules import (
    ROLE_PIONEER,
    ROLE_WALL,
    ROLE_WORKER,
    WALL_LEVEL_MAX_HP,
    WALL_ACTION_GOLD_EQUIVALENT,
)


def rank_wall_work(ctx: PlanningContext, layout: DefenseLayout | None) -> tuple[WallWork, ...]:
    if layout is None:
        return ()
    turn, config, memory = ctx.turn, ctx.config, ctx.state.defense
    jobs: list[WallWork] = []
    existing = [u for u in turn.team_our.roles if u.alive and u.role_type == ROLE_WALL and u.pos]
    front_set = set(layout.front_walls)
    flank_set = set(layout.flank_walls)
    horizon = turn.round_no - config.wall_emergency_horizon
    last_night = turn.round_no - 60
    for wall in existing:
        pos = wall.pos
        assert pos is not None
        max_hp, estimated = wall_max_health(wall)
        if max_hp <= 0:
            continue
        recent = unit_recent_damage(memory, wall.unit_id, horizon)
        night = unit_recent_damage(memory, wall.unit_id, last_night)
        nearby = wall_pressure(turn, layout.front, memory, pos)
        is_front = pos in front_set
        is_flank = pos in flank_set
        is_corner = pos in set(layout.corner_walls)
        if not is_front and not is_flank and not is_corner and nearby <= 0 and recent <= 0 and night <= 0:
            continue
        urgency = 0
        if recent > 0 and nearby > 0:
            eta = _hold_rounds(wall.health, recent / max(1, config.wall_emergency_horizon))
            if eta <= config.wall_emergency_horizon:
                urgency = 4
        classified = is_front or is_flank or is_corner
        if urgency == 0 and night > 0 and (classified or nearby > 0):
            urgency = 3
        if urgency == 0 and classified and nearby > 0:
            urgency = 2
        if urgency == 0 and classified and wall.health < max_hp:
            urgency = 1
        if urgency == 0:
            continue
        jobs.extend(_repair_and_upgrade(wall, max_hp, estimated, urgency, ctx))
    if turn.is_day:
        jobs.extend(_build_jobs(ctx, layout, existing))
    order = {p: i for i, p in enumerate(layout.wall_order or layout.front_walls + layout.corner_walls + layout.flank_walls)}
    def score(work: WallWork) -> tuple:
        # Carried items cost no new gold, but delivery still consumes actions.
        held = [u for u in turn.team_our.roles if u.alive and work.item in u.backpack]
        price = 0 if held else work.gold_cost
        actors = held or [u for u in turn.team_our.roles if u.alive and u.role_type == ROLE_WORKER]
        trips = []
        for actor in actors:
            route = ctx.nav.adjacent_route(actor, work.target)
            if route:
                distance = route.distance + 1
                if work.item and not held:
                    shops = [ctx.nav.adjacent_route(actor, p) for p in turn.zone_positions('weaponShop')]
                    shop_trip = min((r.distance for r in shops if r), default=10**6)
                    distance += 2 * shop_trip + 1
                trips.append(distance)
        actions = min(trips, default=10**6)
        value = work.expected_hp_gain / max(1, price + actions * WALL_ACTION_GOLD_EQUIVALENT)
        target = turn.team_our.unit(work.target_id) if work.target_id is not None else None
        recent_loss = unit_recent_damage(memory, work.target_id, horizon) if work.target_id is not None else 0
        # When only one repair option can cover the observed short-term loss,
        # survival takes precedence over its cheaper alternative.
        insufficient = bool(work.urgency == 4 and target is not None
                            and target.health + work.expected_hp_gain < recent_loss)
        pressure = -wall_pressure(turn, layout.front, memory, work.target)
        sequence = order.get(work.target, 10**6)
        kind_rank = 0 if work.kind != "build" else 1
        if work.kind == "build":
            return (-work.urgency, kind_rank, sequence, pressure, insufficient, -value,
                    turn.coordinate_frame.normalize(work.target), work.kind)
        return (-work.urgency, kind_rank, pressure, insufficient, -value, sequence,
                turn.coordinate_frame.normalize(work.target), work.kind)
    jobs.sort(key=score)
    return tuple(jobs[:24])


def try_wall_work(ctx: PlanningContext, role: Unit, work: WallWork, max_trip: int | None) -> bool:
    turn = ctx.turn
    if role.pos is None:
        return False
    if work.kind == "build":
        if role.role_type != ROLE_WORKER or not turn.is_day or "stone" not in role.backpack:
            return False
        if ctx.layout is not None and not site_build_ready(
                ctx.layout, work.target, built_or_submitted_walls(turn, ctx.actions)):
            return False
        from .economy import EconomyPlanner
        controllers = tuple(p for w in ctx.layout.weapons for p in w.controller_cells) if ctx.layout else ()
        if not EconomyPlanner(ctx)._preserves_exit(work.target, extra_starts=controllers):
            return False
        return _travel(ctx, role, work.target,
                       Action(role.unit_id, ActionType.BUILD, targets=(work.target,), name="wall"),
                       max_trip)
    item = work.item
    target_id = work.target_id
    if item is None or target_id is None:
        return False
    target = turn.team_our.unit(target_id)
    if target is None or not target.alive or target.pos is None:
        return False
    if target.pos != work.target:
        return False
    if target.role_type != ROLE_WALL or (item.startswith('WallUpgradeVoucher') and item[-1:] != str(target.level)):
        return False
    if ('upgrade', target_id) in ctx.claimed:
        return False
    if any(job.target_id == target_id and job.role_id != role.unit_id for job in ctx.state.defense.deliveries):
        return False
    if role.role_type == ROLE_PIONEER and item not in role.backpack:
        return False
    if item in role.backpack:
        goals = tuple(p for cell in target.footprint() for p in neighbours(cell))
        route = ctx.nav.route(role, goals)
        if route is None or (max_trip is not None and route.distance > max_trip):
            return False
        action = Action(role.unit_id, ActionType.USE, name=item, targets=(target.pos,))
        if route.distance == 0:
            if ctx.add(action):
                ctx.claimed.add(("upgrade", target.unit_id))
                register_delivery(ctx.state.defense, role.unit_id, target, item, turn.round_no, "done")
                return True
            return False
        if ctx.move(role, route):
            ctx.claimed.add(("upgrade", target.unit_id))
            register_delivery(ctx.state.defense, role.unit_id, target, item, turn.round_no, "travel")
            return True
        return False
    if not ctx.config.wall_maintenance_enabled or not turn.is_day:
        return False
    if not _may_buy(ctx, role, item, work):
        return False
    prices = {entry.name: entry.price for entry in turn.weapon_shop}
    price = prices.get(item)
    if price is None:
        return False
    for shop in turn.zone_positions("weaponShop"):
        if ctx.nav.adjacent_route(role, target.pos) is None:
            return False
        route = ctx.nav.adjacent_route(role, shop)
        if route is None or (max_trip is not None and route.distance > max_trip):
            continue
        action = Action(role.unit_id, ActionType.BUY, name=item, quantity=1)
        bought = route.distance == 0
        if (ctx.add(action) if bought else ctx.move(role, route)):
            ctx.claimed.add(("buy", item))
            ctx.claimed.add(("upgrade", target.unit_id))
            if bought:
                register_wall_buy(ctx.state.defense, role.unit_id, item, price, turn.round_no,
                                  role.backpack.count(item))
            register_delivery(ctx.state.defense, role.unit_id, target, item, turn.round_no,
                              "buy" if bought else "approach")
            return True
    return False


def try_jobs(ctx: PlanningContext, role: Unit, jobs: tuple[WallWork, ...],
             max_trip: int | None, *, urgent: bool) -> bool:
    claimed_targets = {key[1] for key in ctx.claimed if isinstance(key, tuple) and key and key[0] == "upgrade"}
    for work in jobs:
        if urgent and work.urgency < 3:
            continue
        if not urgent and work.urgency >= 3 and work.kind != "build":
            continue
        if work.target_id is not None and work.target_id in claimed_targets:
            continue
        if work.kind == "build" and (work.target in ctx.nav.occupied or work.target in ctx.claimed):
            continue
        if try_wall_work(ctx, role, work, max_trip):
            if work.kind == "build":
                ctx.claimed.add(work.target)
            return True
    return False


def _travel(ctx: PlanningContext, role: Unit, target: Pos, action: Action,
            max_trip: int | None) -> bool:
    station = ctx.turn.team_our.station()
    base = station.footprint() if station is not None else ()
    if not ctx.turn.is_day and footprint_distance(target, base) > ctx.config.night_trip_radius:
        return False
    route = ctx.nav.adjacent_route(role, target)
    if route is None or (max_trip is not None and route.distance > max_trip):
        return False
    if route.distance == 0:
        return ctx.add(action)
    return ctx.move(role, route)


def _repair_and_upgrade(wall: Unit, max_hp: int, estimated: bool, urgency: int,
                        ctx: PlanningContext) -> list[WallWork]:
    assert wall.pos is not None
    jobs: list[WallWork] = []
    prices = {item.name: item.price for item in ctx.turn.weapon_shop}
    missing = max(0, max_hp - wall.health)
    held = {item for unit in ctx.turn.team_our.roles if unit.alive for item in unit.backpack}
    if missing > 0 and ("WallFixer" in prices or "WallFixer" in held):
        jobs.append(WallWork("repair", wall.pos, wall.unit_id, "WallFixer", urgency, missing,
                             prices.get("WallFixer", 0), "repair_missing_hp"))
    if wall.level in {1, 2}:
        next_hp = WALL_LEVEL_MAX_HP.get(wall.level + 1, 0)
        gain = max(0, next_hp - wall.health)
        item = f"WallUpgradeVoucher{wall.level}"
        if gain > 0 and (item in prices or item in held):
            jobs.append(WallWork("upgrade", wall.pos, wall.unit_id, item, urgency, gain,
                                 prices.get(item, 0), "upgrade_includes_restore" if missing else "upgrade"))
    elif wall.level >= 3:
        pass
    if estimated and wall.level not in WALL_LEVEL_MAX_HP:
        return []
    if missing <= 0 and urgency < 2:
        return [job for job in jobs if job.kind == "upgrade" and urgency >= 2]
    return jobs


def _build_jobs(ctx: PlanningContext, layout: DefenseLayout, existing: list[Unit]) -> list[WallWork]:
    queued = sum(a.action_type == ActionType.BUILD and a.name == ROLE_WALL for a in ctx.actions)
    if len(existing) + queued >= ctx.config.max_walls:
        return []
    built = {u.pos for u in existing}
    sites = [p for p in remaining_wall_sites(ctx.turn, layout) if p not in built]
    memory = ctx.state.defense
    jobs: list[WallWork] = []
    front_built = sum(1 for p in layout.front_walls if p in built)
    required = set(layout.required_wall_sites)
    remembered = any(_remembered_flank(memory, side) > 0 for side in ("neg", "pos"))
    for site in sites:
        if site in ctx.nav.occupied or site in ctx.claimed:
            continue
        is_front = site in layout.front_walls
        nearby = wall_pressure(ctx.turn, layout.front, memory, site)
        if site in required:
            urgency = 4 if nearby > 0 else 2
            reason = "required_gap" if nearby > 0 else "required_connection"
        elif is_front and front_built < ctx.config.front_wall_target_count:
            urgency = 4 if nearby > 0 else 2
            reason = "front_gap" if nearby > 0 else "first_front_segment"
        elif nearby > 0:
            urgency = 4
            reason = "pressured_flank_gap"
        else:
            if front_built >= ctx.config.front_wall_target_count and not remembered:
                continue
            urgency = 1
            reason = "optional_expand"
        jobs.append(WallWork("build", site, None, None, urgency, 1000, 0, reason))
    return jobs


def _hold_rounds(health: int, dpr: float) -> int:
    if dpr <= 0:
        return 10**6
    return int(health / dpr)


def _may_buy(ctx: PlanningContext, role: Unit, item: str, work: WallWork) -> bool:
    if len(role.backpack) >= role.backpack_capacity:
        return False
    held = Counter(entry for unit in ctx.turn.team_our.roles for entry in unit.backpack)
    if held[item]:
        return False
    if ("buy", item) in ctx.claimed:
        return False
    memory = ctx.state.defense
    if any((job.item == item or job.target_id == work.target_id)
           and (job.role_id != role.unit_id or job.stage != "approach") for job in memory.deliveries):
        return False
    if any(pending.item == item for pending in memory.pending_buys):
        return False
    prices = {entry.name: entry.price for entry in ctx.turn.weapon_shop}
    price = prices.get(item)
    if price is None:
        return False
    cap = wall_budget_cap(ctx.turn, memory, ctx.config)
    if memory.wall_spend + memory.wall_reserved + price > cap:
        return False
    reserve = defensive_reserve(ctx.turn, ctx.config, tuple(ctx.actions))
    # ctx.gold already includes purchases committed this turn. Older unresolved
    # purchases still reserve cash until receipt/failure/expiry resolves them.
    pending_cash = sum(p.price for p in memory.pending_buys if p.round_no < ctx.turn.round_no)
    if price > ctx.gold - reserve - pending_cash:
        return False
    return True
