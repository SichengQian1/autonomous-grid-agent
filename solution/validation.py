from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from .actions import Action, ActionType, Decision
from .geometry import Pos
from .models import Turn, Unit
from .rules import (
    ADJACENT_USE_ITEMS,
    BUILD_NAMES,
    HUMAN_ROLE_TYPES,
    RESOURCE_ZONE_TYPES,
    ROLE_GATLING,
    ROLE_PIONEER,
    ROLE_RAILGUN,
    ROLE_ROCKET,
    ROLE_WALL,
    ROLE_WORKER,
    TARGETED_USE_ITEMS,
    UNTARGETED_USE_ITEMS,
    WEAPON_ROLE_TYPES,
    WEAPON_BUILD_COST,
    MAX_WEAPON_COUNT,
)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    actor_id: int
    reason: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    actions: tuple[Action, ...]
    issues: tuple[ValidationIssue, ...]


class ActionValidator:
    def validate(self, turn: Turn, decision: Decision) -> ValidationResult:
        accepted: list[Action] = []
        issues: list[ValidationIssue] = []
        seen_actors: set[int] = set()
        reserved_controllers: set[int] = set()
        remaining_gold = turn.team_our.gold
        projected_weapon_count = sum(
            1 for unit in turn.team_our.roles if unit.role_type in WEAPON_ROLE_TYPES
        )
        reserved_items: Counter[tuple[int, str]] = Counter()
        proposed_role_actors = {
            action.actor_id
            for action in decision.actions
            if (turn.team_our.unit(action.actor_id) or Unit()).is_human
        }

        for action in decision.actions:
            if action.actor_id in seen_actors:
                issues.append(ValidationIssue(action.actor_id, "duplicate actor"))
                continue
            seen_actors.add(action.actor_id)

            reason = self._validate_action(
                turn,
                action,
                proposed_role_actors,
                reserved_controllers,
            )
            if reason:
                issues.append(ValidationIssue(action.actor_id, reason))
                continue
            budget_reason, gold_cost, weapon_delta, item_costs = self._budget_check(
                turn,
                action,
                remaining_gold,
                projected_weapon_count,
                reserved_items,
            )
            if budget_reason:
                issues.append(ValidationIssue(action.actor_id, budget_reason))
                continue
            accepted.append(action)
            remaining_gold -= gold_cost
            projected_weapon_count += weapon_delta
            reserved_items.update(item_costs)
            if action.controller_id is not None:
                reserved_controllers.add(action.controller_id)

        return ValidationResult(tuple(accepted), tuple(issues))

    @staticmethod
    def _budget_check(
        turn: Turn,
        action: Action,
        remaining_gold: int,
        projected_weapon_count: int,
        reserved_items: Counter[tuple[int, str]],
    ) -> tuple[str, int, int, Counter[tuple[int, str]]]:
        gold_cost = 0
        weapon_delta = 0
        item_costs: Counter[tuple[int, str]] = Counter()
        if action.action_type == ActionType.BUY:
            price = next(
                (item.price for item in turn.weapon_shop if item.name == action.name),
                0,
            )
            gold_cost = price * max(action.quantity or 0, 0)
        elif action.action_type == ActionType.BUILD:
            if action.name in WEAPON_ROLE_TYPES:
                gold_cost = WEAPON_BUILD_COST
                weapon_delta = 1
                if projected_weapon_count >= MAX_WEAPON_COUNT:
                    return "weapon limit would be exceeded", 0, 0, item_costs
            elif action.name == ROLE_WALL:
                item_costs[(action.actor_id, "stone")] += 1
        elif action.action_type in {ActionType.USE, ActionType.DROP}:
            item_costs[(action.actor_id, action.name)] += 1
        elif action.action_type == ActionType.SUMMON_TREASURE:
            for item in action.items:
                item_costs[(action.actor_id, item)] += 1

        if gold_cost > remaining_gold:
            return "shared gold budget would be exceeded", 0, 0, Counter()
        actor = turn.team_our.unit(action.actor_id)
        if actor is not None:
            inventory = Counter(actor.backpack)
            for key, count in item_costs.items():
                already_reserved = reserved_items[key]
                if inventory[key[1]] < already_reserved + count:
                    return "reserved item budget would be exceeded", 0, 0, Counter()
        return "", gold_cost, weapon_delta, item_costs

    def _validate_action(
        self,
        turn: Turn,
        action: Action,
        proposed_role_actors: set[int],
        reserved_controllers: set[int],
    ) -> str:
        actor = turn.team_our.unit(action.actor_id)
        if actor is None or not actor.alive or actor.pos is None:
            return "actor is missing, dead, or has no position"
        if not isinstance(action.action_type, ActionType):
            return "unknown action"
        if any(not turn.map_info.contains(target) for target in action.targets):
            return "target is outside the map"

        handlers = {
            ActionType.MOVE: self._validate_move,
            ActionType.ATTACK: self._validate_attack,
            ActionType.SELL: self._validate_sell,
            ActionType.BUY: self._validate_buy,
            ActionType.BUILD: self._validate_build,
            ActionType.REMOVE: self._validate_remove,
            ActionType.ACCEPT_TASK: self._validate_accept_task,
            ActionType.SUBMIT_ANSWER: self._validate_submit_answer,
            ActionType.SUMMON_TREASURE: self._validate_summon_treasure,
            ActionType.USE: self._validate_use,
            ActionType.DROP: self._validate_drop,
            ActionType.COLLECT: self._validate_collect,
        }
        return handlers[action.action_type](
            turn,
            actor,
            action,
            proposed_role_actors,
            reserved_controllers,
        )

    @staticmethod
    def _human(actor: Unit) -> bool:
        return actor.role_type in HUMAN_ROLE_TYPES

    @staticmethod
    def _single_adjacent_target(actor: Unit, action: Action) -> bool:
        return (
            actor.pos is not None
            and len(action.targets) == 1
            and actor.pos.distance_to(action.targets[0]) == 1
        )

    def _validate_move(
        self,
        turn: Turn,
        actor: Unit,
        action: Action,
        proposed_role_actors: set[int],
        reserved_controllers: set[int],
    ) -> str:
        del proposed_role_actors, reserved_controllers
        if not self._human(actor):
            return "only a controllable role can move"
        if not self._single_adjacent_target(actor, action):
            return "move requires one adjacent target"
        target = action.targets[0]
        if any(
            target in unit.footprint()
            for unit in turn.team_our.roles + turn.team_enemy.roles
            if unit.unit_id != actor.unit_id
        ):
            return "move target is occupied by a visible unit"
        if any(zone.pos == target for zone in turn.map_info.zones):
            return "move target is an occupied neutral cell"
        if any(robot.pos == target and robot.health > 0 for robot in turn.robots):
            return "move target is occupied by a robot"
        return ""

    def _validate_attack(
        self,
        turn: Turn,
        actor: Unit,
        action: Action,
        proposed_role_actors: set[int],
        reserved_controllers: set[int],
    ) -> str:
        if turn.is_day:
            return "attack is unavailable during daytime"
        if actor.role_type not in WEAPON_ROLE_TYPES:
            return "attack actor is not a weapon"
        if actor.role_type == ROLE_ROCKET and actor.cooldown > 0:
            return "rocket is cooling down"
        if action.controller_id is None:
            return "attack requires a controller"
        controller = turn.team_our.unit(action.controller_id)
        if (
            controller is None
            or not controller.alive
            or not controller.is_human
            or controller.pos is None
            or actor.pos is None
            or controller.pos.distance_to(actor.pos) > 1
        ):
            return "controller is unavailable or not adjacent"
        if action.controller_id in reserved_controllers:
            return "controller already controls another weapon"
        if action.controller_id in proposed_role_actors:
            return "controller also has a role action"

        required_targets = 1
        if actor.role_type in {ROLE_GATLING, ROLE_ROCKET}:
            required_targets = max(actor.level, 1)
        if len(action.targets) != required_targets:
            return "weapon target count does not match its level"
        if actor.attack_range <= 0:
            return "weapon has no authoritative positive range"
        if any(actor.pos.distance_to(target) > actor.attack_range for target in action.targets):
            return "attack target exceeds runtime range"
        if actor.role_type == ROLE_GATLING and not self._gatling_angle_valid(
            actor.pos, action.targets
        ):
            return "gatling targets exceed the 90-degree constraint"
        if actor.role_type == ROLE_RAILGUN and len(action.targets) != 1:
            return "railgun requires exactly one target"
        return ""

    @staticmethod
    def _gatling_angle_valid(origin: Pos, targets: tuple[Pos, ...]) -> bool:
        vectors = tuple((target.x - origin.x, target.y - origin.y) for target in targets)
        if any(dx == 0 and dy == 0 for dx, dy in vectors):
            return False
        return all(
            first[0] * second[0] + first[1] * second[1] >= 0
            for index, first in enumerate(vectors)
            for second in vectors[index + 1 :]
        )

    def _validate_sell(
        self,
        turn: Turn,
        actor: Unit,
        action: Action,
        proposed_role_actors: set[int],
        reserved_controllers: set[int],
    ) -> str:
        del proposed_role_actors, reserved_controllers
        if not self._human(actor):
            return "only a controllable role can sell"
        if not action.name or action.quantity is None or action.quantity <= 0:
            return "sell requires a positive quantity and item name"
        if Counter(actor.backpack)[action.name] < action.quantity:
            return "sell quantity exceeds backpack inventory"
        if action.name not in {item.name for item in turn.vendor_shop}:
            return "item is not present in the runtime vendor list"
        if not self._adjacent_to_zone(turn, actor, "vendor"):
            return "seller is not adjacent to a vendor"
        return ""

    def _validate_buy(
        self,
        turn: Turn,
        actor: Unit,
        action: Action,
        proposed_role_actors: set[int],
        reserved_controllers: set[int],
    ) -> str:
        del proposed_role_actors, reserved_controllers
        if not self._human(actor):
            return "only a controllable role can buy"
        if not action.name or action.quantity is None or action.quantity <= 0:
            return "buy requires a positive quantity and item name"
        if action.name not in {item.name for item in turn.weapon_shop}:
            return "item is not present in the runtime shop"
        price = next(item.price for item in turn.weapon_shop if item.name == action.name)
        if price * action.quantity > turn.team_our.gold:
            return "purchase exceeds available gold"
        if actor.backpack_capacity and len(actor.backpack) + action.quantity > actor.backpack_capacity:
            return "purchase exceeds backpack capacity"
        if not self._adjacent_to_zone(turn, actor, "weaponShop"):
            return "buyer is not adjacent to a weapon shop"
        return ""

    def _validate_build(
        self,
        turn: Turn,
        actor: Unit,
        action: Action,
        proposed_role_actors: set[int],
        reserved_controllers: set[int],
    ) -> str:
        del proposed_role_actors, reserved_controllers
        if actor.role_type != ROLE_WORKER:
            return "only a worker can build"
        if not turn.is_day:
            return "build is unavailable at night"
        if not action.name or action.name not in BUILD_NAMES:
            return "build name is not recognized"
        if not self._single_adjacent_target(actor, action):
            return "build requires one adjacent target"
        target = action.targets[0]
        if any(target in unit.footprint() for unit in turn.team_our.roles + turn.team_enemy.roles):
            return "build target is already occupied"
        if any(zone.pos == target for zone in turn.map_info.zones):
            return "build target is an occupied neutral cell"
        if action.name == ROLE_WALL and "stone" not in actor.backpack:
            return "wall build requires stone"
        if action.name in WEAPON_ROLE_TYPES:
            if turn.team_our.gold < WEAPON_BUILD_COST:
                return "weapon build requires sufficient gold"
            if sum(1 for unit in turn.team_our.roles if unit.role_type in WEAPON_ROLE_TYPES) >= MAX_WEAPON_COUNT:
                return "weapon limit has been reached"
        return ""

    def _validate_remove(
        self,
        turn: Turn,
        actor: Unit,
        action: Action,
        proposed_role_actors: set[int],
        reserved_controllers: set[int],
    ) -> str:
        del proposed_role_actors, reserved_controllers
        if actor.role_type != ROLE_WORKER:
            return "only a worker can remove a wall"
        if not self._single_adjacent_target(actor, action):
            return "remove requires one adjacent target"
        if not any(
            unit.role_type == ROLE_WALL and unit.pos == action.targets[0]
            for unit in turn.team_our.roles + turn.team_enemy.roles
        ):
            return "remove target is not a visible wall"
        return ""

    def _validate_accept_task(
        self,
        turn: Turn,
        actor: Unit,
        action: Action,
        proposed_role_actors: set[int],
        reserved_controllers: set[int],
    ) -> str:
        del proposed_role_actors, reserved_controllers
        if actor.role_type != ROLE_PIONEER:
            return "only the pioneer can accept a task"
        if action.targets or action.name or action.task_answer or action.items:
            return "acceptTask contains unsupported fields"
        if actor.pos is None or not any(
            task.is_valid
            and task.task_position is not None
            and actor.pos.distance_to(task.task_position) <= 1
            for task in turn.team_our.player_tasks
        ):
            return "pioneer is not adjacent to an available task"
        return ""

    def _validate_submit_answer(
        self,
        turn: Turn,
        actor: Unit,
        action: Action,
        proposed_role_actors: set[int],
        reserved_controllers: set[int],
    ) -> str:
        del proposed_role_actors, reserved_controllers
        if actor.role_type != ROLE_PIONEER:
            return "only the pioneer can submit an answer"
        if not turn.phase_task or not action.task_answer:
            return "submitAnswer requires an active task and non-empty answer"
        return ""

    def _validate_summon_treasure(
        self,
        turn: Turn,
        actor: Unit,
        action: Action,
        proposed_role_actors: set[int],
        reserved_controllers: set[int],
    ) -> str:
        del turn, proposed_role_actors, reserved_controllers
        if actor.role_type != ROLE_PIONEER:
            return "only the pioneer can summon treasure"
        if not self._single_adjacent_target(actor, action):
            return "summonTreasure requires one adjacent target"
        if not action.items:
            return "summonTreasure requires at least one item"
        backpack = Counter(actor.backpack)
        if any(backpack[item] < count for item, count in Counter(action.items).items()):
            return "sacrificed items are not present in the backpack"
        return ""

    def _validate_use(
        self,
        turn: Turn,
        actor: Unit,
        action: Action,
        proposed_role_actors: set[int],
        reserved_controllers: set[int],
    ) -> str:
        del turn, proposed_role_actors, reserved_controllers
        if not self._human(actor):
            return "only a controllable role can use an item"
        if not action.name or action.name not in actor.backpack:
            return "used item is not present in the backpack"
        if action.name in TARGETED_USE_ITEMS:
            if len(action.targets) != 1:
                return "targeted item requires exactly one target"
            if (
                action.name in ADJACENT_USE_ITEMS
                and actor.pos is not None
                and actor.pos.distance_to(action.targets[0]) > 1
            ):
                return "item target is not adjacent"
        elif action.name in UNTARGETED_USE_ITEMS:
            if action.targets:
                return "untargeted item must not include a target"
        else:
            return "unknown item use requirements"
        return ""

    def _validate_drop(
        self,
        turn: Turn,
        actor: Unit,
        action: Action,
        proposed_role_actors: set[int],
        reserved_controllers: set[int],
    ) -> str:
        del turn, proposed_role_actors, reserved_controllers
        if not self._human(actor):
            return "only a controllable role can drop an item"
        if not action.name or action.name not in actor.backpack:
            return "dropped item is not present in the backpack"
        return ""

    def _validate_collect(
        self,
        turn: Turn,
        actor: Unit,
        action: Action,
        proposed_role_actors: set[int],
        reserved_controllers: set[int],
    ) -> str:
        del proposed_role_actors, reserved_controllers
        if actor.role_type != ROLE_WORKER:
            return "only a worker can collect"
        if actor.backpack_capacity and len(actor.backpack) >= actor.backpack_capacity:
            return "collector backpack is full"
        if not self._single_adjacent_target(actor, action):
            return "collect requires one adjacent target"
        if not any(
            zone.pos == action.targets[0] and zone.neutral_type in RESOURCE_ZONE_TYPES
            for zone in turn.map_info.zones
        ):
            return "collect target is not a known resource zone"
        return ""

    @staticmethod
    def _adjacent_to_zone(turn: Turn, actor: Unit, zone_type: str) -> bool:
        if actor.pos is None:
            return False
        return any(
            zone.pos is not None
            and zone.neutral_type == zone_type
            and actor.pos.distance_to(zone.pos) <= 1
            for zone in turn.map_info.zones
        )
