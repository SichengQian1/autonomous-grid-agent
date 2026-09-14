from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from .actions import Action, ActionType, Decision
from .geometry import Pos, footprint_distance
from .navigation import occupied_cells
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
    MAX_WEAPONS,
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
        reserved_targets: set[Pos] = set()
        gold_left = turn.team_our.gold
        weapon_count = sum(unit.alive and unit.is_weapon for unit in turn.team_our.roles)
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
            cost = 0
            if action.action_type in {ActionType.MOVE, ActionType.BUILD}:
                if action.targets[0] in reserved_targets:
                    issues.append(ValidationIssue(action.actor_id, "destination already reserved"))
                    continue
            if action.action_type == ActionType.BUY:
                cost = next(item.price for item in turn.weapon_shop if item.name == action.name) * (action.quantity or 1)
            if action.action_type == ActionType.BUILD and action.name in WEAPON_ROLE_TYPES:
                if weapon_count >= MAX_WEAPONS:
                    issues.append(ValidationIssue(action.actor_id, "weapon limit reached"))
                    continue
                cost = WEAPON_BUILD_COST
            if cost > gold_left:
                issues.append(ValidationIssue(action.actor_id, "shared gold budget exceeded"))
                continue
            gold_left -= cost
            accepted.append(action)
            if action.action_type in {ActionType.MOVE, ActionType.BUILD}:
                reserved_targets.add(action.targets[0])
            if action.action_type == ActionType.BUILD and action.name in WEAPON_ROLE_TYPES:
                weapon_count += 1
            if action.controller_id is not None:
                reserved_controllers.add(action.controller_id)

        return ValidationResult(tuple(accepted), tuple(issues))

    def _validate_action(
        self,
        turn: Turn,
        action: Action,
        proposed_role_actors: set[int],
        reserved_controllers: set[int],
    ) -> str:
        actor = turn.team_our.unit(action.actor_id)
        if action.actor_id < 0 or actor is None or not actor.alive or actor.pos is None:
            return "actor is missing, dead, or has no position"
        if not turn.map_info.contains(actor.pos):
            return "actor is outside the map"
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
        if action.targets[0] in occupied_cells(turn, except_actor=actor.unit_id):
            return "move destination is occupied"
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
            or controller.pos.distance_to(actor.pos) != 1
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
        if len(actor.backpack) + action.quantity > actor.backpack_capacity:
            return "backpack capacity exceeded"
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
        station = turn.team_our.station()
        required_distance = 2 if action.name == ROLE_WALL else 1
        if station is None or footprint_distance(action.targets[0], station.footprint()) != required_distance:
            return "build target is outside its permitted ring"
        if action.targets[0] in occupied_cells(turn):
            return "build target is occupied"
        if action.name == ROLE_WALL and "stone" not in actor.backpack:
            return "wall requires stone"
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
            and task.cooldown_rounds == 0
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
        del proposed_role_actors, reserved_controllers
        if not self._human(actor):
            return "only a controllable role can use an item"
        if not action.name or action.name not in actor.backpack:
            return "used item is not present in the backpack"
        if action.name in TARGETED_USE_ITEMS:
            if len(action.targets) != 1:
                return "targeted item requires exactly one target"
            building = next((unit for unit in turn.team_our.roles if unit.alive and action.targets[0] in unit.footprint()), None)
            if "UpgradeVoucher" in action.name or action.name == "WallFixer":
                if building is None:
                    return "item requires a living friendly building"
                if action.name.startswith("Weapon") and not building.is_weapon:
                    return "weapon voucher requires a weapon"
                if action.name.startswith("Station") and building.role_type != "station":
                    return "station voucher requires a station"
                if action.name.startswith("Wall") and building.role_type != ROLE_WALL:
                    return "wall item requires a wall"
                if "UpgradeVoucher" in action.name and building.level != int(action.name[-1]):
                    return "voucher does not match building level"
            if (
                action.name in ADJACENT_USE_ITEMS
                and actor.pos is not None
                and (footprint_distance(actor.pos, building.footprint()) if building else actor.pos.distance_to(action.targets[0])) > 1
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
        if len(actor.backpack) >= actor.backpack_capacity:
            return "backpack is full"
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
