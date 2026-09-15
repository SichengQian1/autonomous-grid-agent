from __future__ import annotations

import time

from .actions import Action, ActionType, Decision
from .models import Turn, Unit
from .navigation import Navigator, Route
from .rules import StrategyConfig, WEAPON_BUILD_COST, WEAPON_ROLE_TYPES, ROLE_WALL
from .state import WorldState
from .validation import ActionValidator


class PlanningContext:
    def __init__(self, turn: Turn, config: StrategyConfig, state: WorldState, deadline: float) -> None:
        self.turn, self.config, self.state, self.deadline = turn, config, state, deadline
        self.nav = Navigator(turn, config, deadline)
        self.actions: list[Action] = []
        self.validator = ActionValidator()
        self.claimed: set[object] = set()
        self.gold = turn.team_our.gold
        self.layout = None
        self.wall_jobs = ()

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self.deadline

    def can_add(self, action: Action) -> bool:
        if self.expired or self.state.action_blocked(action, self.turn.round_no):
            return False
        if action.action_type == ActionType.BUILD and action.name == ROLE_WALL:
            built = sum(u.alive and u.role_type == ROLE_WALL for u in self.turn.team_our.roles)
            queued = sum(a.action_type == ActionType.BUILD and a.name == ROLE_WALL for a in self.actions)
            if built + queued >= self.config.max_walls:
                return False
        proposed = Decision(tuple(self.actions) + (action,))
        return not self.validator.validate(self.turn, proposed).issues

    def add(self, action: Action) -> bool:
        if not self.can_add(action):
            return False
        self.actions.append(action)
        if action.action_type in {ActionType.MOVE, ActionType.BUILD}:
            self.nav.reserve(action.targets[0])
        if action.action_type == ActionType.BUY:
            price = next(item.price for item in self.turn.weapon_shop if item.name == action.name)
            self.gold -= price * (action.quantity or 1)
        elif action.action_type == ActionType.BUILD and action.name in WEAPON_ROLE_TYPES:
            self.gold -= WEAPON_BUILD_COST
        return True

    def move(self, role: Unit, route: Route | None) -> bool:
        if route is None:
            return False
        if route.step is None:
            self.nav.claimed_goals.add(route.destination)
            return True
        if self.add(Action(role.unit_id, ActionType.MOVE, targets=(route.step,))):
            self.nav.claimed_goals.add(route.destination)
            return True
        return False
