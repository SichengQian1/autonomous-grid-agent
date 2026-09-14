from __future__ import annotations

from dataclasses import dataclass


DAY_ROUNDS = 70
NIGHT_ROUNDS = 60
ROUNDS_PER_DAY = DAY_ROUNDS + NIGHT_ROUNDS
NORMAL_TURN_BUDGET_SECONDS = 4.0

TEAM_CHALLENGER = "challenger"
TEAM_DEFENDER = "defender"

ROLE_STATION = "station"
ROLE_GATLING = "gatling"
ROLE_RAILGUN = "railgun"
ROLE_ROCKET = "rocket"
ROLE_WALL = "wall"
ROLE_PIONEER = "pioneer"
ROLE_WORKER = "worker"

HUMAN_ROLE_TYPES = frozenset({ROLE_PIONEER, ROLE_WORKER})
WEAPON_ROLE_TYPES = frozenset({ROLE_GATLING, ROLE_RAILGUN, ROLE_ROCKET})
BUILDING_ROLE_TYPES = frozenset(
    {ROLE_STATION, ROLE_GATLING, ROLE_RAILGUN, ROLE_ROCKET, ROLE_WALL}
)

RESOURCE_ZONE_TYPES = frozenset({"stone", "iron", "copper"})
TASK_POINT_SUFFIX = "TaskPoint"

BUILD_NAMES = frozenset({ROLE_GATLING, ROLE_RAILGUN, ROLE_ROCKET, ROLE_WALL})

TARGETED_USE_ITEMS = frozenset(
    {
        "WallFixer",
        "DizzyWeapon",
        "Bomb",
        "WeaponUpgradeVoucher1",
        "WeaponUpgradeVoucher2",
        "WallUpgradeVoucher1",
        "WallUpgradeVoucher2",
        "StationUpgradeVoucher1",
        "StationUpgradeVoucher2",
    }
)

ADJACENT_USE_ITEMS = frozenset(
    {
        "WallFixer",
        "WeaponUpgradeVoucher1",
        "WeaponUpgradeVoucher2",
        "WallUpgradeVoucher1",
        "WallUpgradeVoucher2",
        "StationUpgradeVoucher1",
        "StationUpgradeVoucher2",
    }
)

UNTARGETED_USE_ITEMS = frozenset(
    {
        "Medicine",
        "SmallRobotSummonOrder",
        "MiddleRobotSummonOrder",
        "LargeRobotSummonOrder",
        "BossRobotSummonOrder",
    }
)


def is_day_round(round_no: int) -> bool:
    """Return the documented phase for one-based round numbers.

    Round zero or a negative value is treated as the first daytime round. This
    defensive default prevents malformed input from enabling a night-only action.
    """

    safe_round = max(round_no, 1)
    return (safe_round - 1) % ROUNDS_PER_DAY < DAY_ROUNDS


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    normal_turn_budget_seconds: float = NORMAL_TURN_BUDGET_SECONDS
    primary_weapon_loadout: tuple[str, str, str] = (
        ROLE_RAILGUN,
        ROLE_RAILGUN,
        ROLE_ROCKET,
    )
    comparison_weapon_loadout: tuple[str, str, str] = (
        ROLE_GATLING,
        ROLE_RAILGUN,
        ROLE_ROCKET,
    )


DEFAULT_CONFIG = StrategyConfig()
