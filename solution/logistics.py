from __future__ import annotations

from dataclasses import dataclass

from .actions import Action, ActionType
from .economy import DefenseBudget
from .models import Turn, Unit
from .movement import MoveIntent
from .rules import ROLE_STATION, ROLE_WALL, WEAPON_ROLE_TYPES


@dataclass(frozen=True, slots=True)
class LogisticsPlan:
    action: Action | None = None
    move: MoveIntent | None = None


def plan_upgrade_or_repair(
    turn: Turn,
    role: Unit,
    budget: DefenseBudget,
) -> LogisticsPlan:
    if role.pos is None:
        return LogisticsPlan()
    targets = tuple(
        unit for unit in turn.team_our.roles
        if unit.health > 0 and unit.pos is not None
    )

    carried_options: list[tuple[str, Unit, int]] = []
    for target in targets:
        if target.role_type in WEAPON_ROLE_TYPES and target.level in {1, 2}:
            carried_options.append((f"WeaponUpgradeVoucher{target.level}", target, 90))
        elif target.role_type == ROLE_STATION and target.level in {1, 2}:
            carried_options.append((f"StationUpgradeVoucher{target.level}", target, 100))
        elif target.role_type == ROLE_WALL and target.level in {1, 2}:
            carried_options.append((f"WallUpgradeVoucher{target.level}", target, 60))
            if target.health < 700:
                carried_options.append(("WallFixer", target, 85))

    available = [option for option in carried_options if option[0] in role.backpack]
    if available:
        name, target, priority = max(
            available,
            key=lambda option: (
                option[2],
                -role.pos.distance_to(option[1].pos),
                -option[1].unit_id,
            ),
        )
        if role.pos.distance_to(target.pos) <= 1:
            return LogisticsPlan(
                action=Action(role.unit_id, ActionType.USE, name=name, targets=(target.pos,))
            )
        return LogisticsPlan(
            move=MoveIntent(role.unit_id, tuple(target.pos.neighbours()), priority=priority)
        )

    if budget.offensive <= 0 or not turn.weapon_shop:
        return LogisticsPlan()
    desired: list[str] = []
    for target in targets:
        if target.role_type in WEAPON_ROLE_TYPES and target.level in {1, 2}:
            desired.append(f"WeaponUpgradeVoucher{target.level}")
        elif target.role_type == ROLE_STATION and target.level in {1, 2} and target.health < 1200:
            desired.append(f"StationUpgradeVoucher{target.level}")
        elif target.role_type == ROLE_WALL:
            if target.health < 700:
                desired.append("WallFixer")
            if target.level in {1, 2}:
                desired.append(f"WallUpgradeVoucher{target.level}")
    shop_items = {item.name: item.price for item in turn.weapon_shop}
    affordable = next(
        (
            name for name in desired
            if name in shop_items and 0 < shop_items[name] <= budget.offensive
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
    return LogisticsPlan(
        move=MoveIntent(
            role.unit_id,
            tuple(pos for shop in shops for pos in shop.neighbours()),
            priority=45,
        )
    )
