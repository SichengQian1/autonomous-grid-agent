from __future__ import annotations

from collections import Counter

from .actions import Action, ActionType, Decision
from .combat import CombatPlanner
from .defense import base_cells, controller_assignments, defensive_route
from .economy import EconomyPlanner
from .geometry import footprint_distance
from .models import Turn, Unit
from .planning import PlanningContext
from .rules import DAY_ROUNDS, ROUNDS_PER_DAY, ROLE_PIONEER, WEAPON_BUILD_COST, StrategyConfig
from .state import LlmBudget, WorldState
from .tasks import TaskManager


class BaselinePlanner:
    def __init__(self) -> None:
        self.tasks = TaskManager()
        self.generation = -1

    def plan(self, turn: Turn, state: WorldState, budget: LlmBudget,
             config: StrategyConfig, deadline: float) -> Decision:
        if not config.enabled:
            return Decision()
        if self.generation != state.generation:
            self.tasks = TaskManager()
            self.generation = state.generation
        self.tasks.observe(turn)
        ctx = PlanningContext(turn, config, state, deadline)
        # Consume next-turn news before acting, including replies across dusk.
        self.tasks.consume_news(ctx)
        station = turn.team_our.station()
        if station is None or not station.alive or not station.pos or not base_cells(turn):
            return Decision()
        roles = sorted((r for r in turn.team_our.roles if r.alive and r.is_human and r.pos),
                       key=lambda r: (r.role_type == ROLE_PIONEER, r.unit_id))[:3]
        economy = EconomyPlanner(ctx)
        remaining_day = DAY_ROUNDS - (max(1, turn.round_no) - 1) % ROUNDS_PER_DAY
        prompt, command = "", ""
        healed: set[int] = set()
        for role in roles:
            if economy.emergency_repair(role) or economy.heal(role):
                healed.add(role.unit_id)
        combat = CombatPlanner(turn, config, deadline) if not turn.is_day else None
        assignments = controller_assignments(
            turn, ctx.nav,
            fire_value=(lambda mapping: combat.value(combat.plan(mapping, excluded=frozenset(healed), admissible=ctx.can_add)))
            if combat is not None else None,
        )
        released: set[int] = set()
        if combat is not None:
            # Each release is tested cumulatively; two independently safe releases
            # must never accidentally remove all required firepower.
            for role in roles:
                if role.unit_id in healed or role.pos in ctx.nav.danger:
                    continue
                candidate = frozenset(released | healed | {role.unit_id})
                if combat.can_release(assignments, candidate, admissible=ctx.can_add):
                    released.add(role.unit_id)
            fire = combat.plan(assignments, excluded=frozenset(released | healed), admissible=ctx.can_add)
            for action in fire.actions:
                ctx.add(action)
            # Only commands actually committed to this response authorize departures.
            if released and not combat.can_release(assignments, frozenset(released | healed), committed=combat.accepted_fire(ctx.actions)):
                released.clear()
        occupied_roles = healed | {a.controller_id for a in ctx.actions if a.controller_id is not None}
        for role in roles:
            if ctx.expired:
                break
            if role.unit_id in occupied_roles:
                continue
            weapon = assignments.get(role.unit_id)
            home = defensive_route(turn, ctx.nav, role, weapon)
            return_distance = home.distance if home else 10**6
            must_return = ((turn.is_day and remaining_day <= return_distance + config.return_margin)
                           or (not turn.is_day and role.unit_id not in released))
            if must_return:
                if not ctx.move(role, home):
                    # Escape an immediate robot attack when its danger envelope
                    # encloses the usual defensive stand.
                    safe_cells = tuple(p for p in ctx.nav.routes(role, safe=False)
                                       if p not in ctx.nav.danger and footprint_distance(p, base_cells(turn)) <= 3)
                    ctx.move(role, ctx.nav.route(role, safe_cells, safe=False))
                continue
            max_trip = (max(0, (remaining_day - return_distance - config.return_margin) // 2)
                        if turn.is_day else config.night_trip_radius)
            if role.role_type == ROLE_PIONEER and turn.phase_task:
                task_output = self.tasks.active(ctx, role, budget)
                prompt, command = task_output.prompt, task_output.command
                if task_output.action:
                    if ctx.add(task_output.action):
                        self.tasks.submitted_this_task = True
                # Moving away would end the active task. Healing above remains legal.
                continue
            if turn.is_day and economy.build(role):
                continue
            if role.role_type == ROLE_PIONEER:
                if self._treasure(ctx, role, max_trip):
                    continue
                if turn.is_day and self._accept_task(ctx, role, return_distance, remaining_day):
                    continue
            if economy.supplies(role, max_trip):
                continue
            if economy.gather_or_sell(role, max_trip):
                continue
            ctx.move(role, home)
        if (not prompt and not command and not turn.phase_task and turn.is_day
                and not any(a.action_type == ActionType.ACCEPT_TASK for a in ctx.actions)
                and any(r.role_type == ROLE_PIONEER for r in roles)):
            prompt = self.tasks.news(ctx, budget)
        return Decision(tuple(ctx.actions), prompt, command)

    def _accept_task(self, ctx: PlanningContext, role: Unit, return_distance: int, remaining_day: int) -> bool:
        candidates = []
        for task in ctx.turn.team_our.player_tasks:
            if not task.is_valid or task.cooldown_rounds or task.task_position is None:
                continue
            route = ctx.nav.adjacent_route(role, task.task_position)
            if route is None:
                continue
            # Upper bound the return from the task via the current position.
            safety = 2 * route.distance + return_distance + ctx.config.return_margin
            available = remaining_day - safety
            minimum = min(task.timeout_rounds, ctx.config.task_min_rounds)
            if minimum <= 0 or available < minimum:
                continue
            # Keep enough time for the full timeout where possible; partial credit
            # is permitted only after at least the configured solving window.
            reward = task.score_reward + task.gold_reward
            value = reward / (route.distance + min(task.timeout_rounds, available) + 1)
            candidates.append((value, task.task_position, route))
        for _, _, route in sorted(candidates, key=lambda item: (-item[0], item[1])):
            if route.distance == 0:
                return ctx.add(Action(role.unit_id, ActionType.ACCEPT_TASK))
            if ctx.move(role, route):
                return True
        return False

    def _treasure(self, ctx: PlanningContext, role: Unit, max_trip: int) -> bool:
        treasure = self.tasks.treasure
        if treasure is None or self.tasks.treasure_finished:
            return False
        if ctx.turn.round_no > treasure.closes:
            self.tasks.treasure = None
            return False
        have, needed = Counter(role.backpack), Counter(treasure.items)
        missing = needed - have
        if missing:
            prices = {item.name: item.price for item in ctx.turn.weapon_shop}
            if any(name not in prices for name in missing):
                return False
            total_cost = sum(prices[name] * count for name, count in missing.items())
            reserve = max(0, 3 - sum(u.alive and u.is_weapon for u in ctx.turn.team_our.roles)) * WEAPON_BUILD_COST
            if total_cost > ctx.gold - reserve or len(role.backpack) + sum(missing.values()) > role.backpack_capacity:
                return False
            for shop in ctx.turn.zone_positions("weaponShop"):
                route = ctx.nav.adjacent_route(role, shop)
                if route and route.distance <= max_trip:
                    name = next(iter(missing))
                    if route.distance == 0:
                        return ctx.add(Action(role.unit_id, ActionType.BUY, name=name, quantity=missing[name]))
                    return ctx.move(role, route)
            return False
        route = ctx.nav.adjacent_route(role, treasure.pos)
        if route is None or route.distance > max_trip or ctx.turn.round_no + route.distance > treasure.closes:
            return False
        if route.distance:
            return ctx.move(role, route)
        if ctx.turn.round_no < treasure.opens:
            return False
        action = Action(role.unit_id, ActionType.SUMMON_TREASURE, targets=(treasure.pos,), items=treasure.items)
        if ctx.add(action):
            self.tasks.treasure_attempt_round = ctx.turn.round_no
            return True
        return False
