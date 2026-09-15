from __future__ import annotations

from dataclasses import dataclass

from .actions import Action, ActionType
from .economy import DefenseBudget
from .models import Turn, Unit
from .movement import MoveIntent
from .rules import (
    DEFAULT_CONFIG,
    ROLE_RAILGUN,
    ROLE_ROCKET,
    ROLE_STATION,
    ROLE_WALL,
    WEAPON_ROLE_TYPES,
    StrategyConfig,
)


@dataclass(frozen=True, slots=True)
class LogisticsPlan:
    action: Action | None = None
    move: MoveIntent | None = None


# Runtime payloads do not expose maxHealth. These values only rank choices and
# remain replaceable after platform logs provide better evidence.
_MAX_HEALTH = {
    ROLE_STATION: (0, 1500, 3000, 4500),
    ROLE_WALL: (0, 1000, 1500, 2000),
    ROLE_RAILGUN: (0, 1000, 1500, 2000),
    ROLE_ROCKET: (0, 1000, 1500, 2000),
    "gatling": (0, 1000, 1500, 2000),
}


def estimated_max_health(unit: Unit) -> int:
    values = _MAX_HEALTH.get(unit.role_type, (0, max(unit.health, 1)))
    index = min(max(unit.level, 1), len(values) - 1)
    return max(values[index], unit.health, 1)


def upgrade_value(turn: Turn, target: Unit) -> int:
    """Rank an upgrade including its user-observed full-heal value."""

    if target.level not in {1, 2}:
        return -1
    missing_health = max(0, estimated_max_health(target) - target.health)
    if target.role_type == ROLE_ROCKET:
        combat = 4200 if target.level == 2 else 1900
    elif target.role_type == ROLE_RAILGUN:
        combat = 1800 if target.level == 1 else 900
    elif target.role_type == ROLE_STATION:
        combat = 1500 + 250 * turn.day_index
    elif target.role_type == ROLE_WALL:
        combat = 350
    else:
        combat = 800
    return combat + missing_health * 2


def _maintenance_options(turn: Turn) -> list[tuple[str, Unit, int]]:
    result: list[tuple[str, Unit, int]] = []
    for target in turn.team_our.roles:
        if target.health <= 0 or target.pos is None:
            continue
        max_health = estimated_max_health(target)
        missing = max(0, max_health - target.health)
        if target.role_type in WEAPON_ROLE_TYPES and target.level in {1, 2}:
            result.append(
                (f"WeaponUpgradeVoucher{target.level}", target, upgrade_value(turn, target))
            )
        elif target.role_type == ROLE_STATION and target.level in {1, 2}:
            if turn.day_index >= 2 or missing >= max_health // 5:
                result.append(
                    (f"StationUpgradeVoucher{target.level}", target, upgrade_value(turn, target))
                )
        elif target.role_type == ROLE_WALL:
            if target.level in {1, 2} and missing >= max_health // 5:
                result.append(
                    (f"WallUpgradeVoucher{target.level}", target, upgrade_value(turn, target))
                )
            if missing >= max_health // 3:
                result.append(("WallFixer", target, 1000 + missing * 2))
    result.sort(key=lambda option: option[2], reverse=True)
    return result


def plan_upgrade_or_repair(
    turn: Turn,
    role: Unit,
    budget: DefenseBudget,
    config: StrategyConfig = DEFAULT_CONFIG,
    *,
    allow_move: bool = True,
    critical_only: bool = False,
) -> LogisticsPlan:
    del config
    if role.pos is None:
        return LogisticsPlan()

    options = _maintenance_options(turn)
    if critical_only:
        options = [
            option
            for option in options
            if option[1].health * 2 < estimated_max_health(option[1])
            or (option[1].role_type == ROLE_ROCKET and option[1].level == 2)
        ]
    options.sort(
        key=lambda option: (
            option[2],
            -role.pos.distance_to(option[1].pos),
            -option[1].unit_id,
        ),
        reverse=True,
    )
    for name, target, priority in options:
        if name not in role.backpack:
            continue
        if role.pos.distance_to(target.pos) <= 1:
            return LogisticsPlan(
                action=Action(role.unit_id, ActionType.USE, name=name, targets=(target.pos,))
            )
        if allow_move:
            return LogisticsPlan(
                move=MoveIntent(role.unit_id, tuple(target.pos.neighbours()), priority=priority)
            )

    if budget.offensive <= 0 or not turn.weapon_shop:
        return LogisticsPlan()
    shop_items = {item.name: item.price for item in turn.weapon_shop}
    affordable = next(
        (
            name for name, _target, _priority in options
            if name in shop_items and 0 < shop_items[name] <= budget.offensive
            and not any(name in unit.backpack for unit in turn.controllable)
        ),
        None,
    )
    if affordable is None:
        return LogisticsPlan()
    shops = turn.zone_positions("weaponShop")
    if any(role.pos.distance_to(shop) <= 1 for shop in shops):
        return LogisticsPlan(
            action=Action(role.unit_id, ActionType.BUY, name=affordable, quantity=1)
        )
    if not allow_move:
        return LogisticsPlan()
    return LogisticsPlan(
        move=MoveIntent(
            role.unit_id,
            tuple(pos for shop in shops for pos in shop.neighbours()),
            priority=75,
        )
    )
