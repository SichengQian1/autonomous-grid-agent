from __future__ import annotations

from dataclasses import dataclass


DAY_ROUNDS = 70
NIGHT_ROUNDS = 60
ROUNDS_PER_DAY = DAY_ROUNDS + NIGHT_ROUNDS
NORMAL_TURN_BUDGET_SECONDS = 4.0
WEAPON_BUILD_COST = 25
MAX_WEAPON_COUNT = 3
MAX_WALL_COUNT = 20

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
        ROLE_ROCKET,
        ROLE_RAILGUN,
        ROLE_ROCKET,
    )
    comparison_weapon_loadout: tuple[str, str, str] = (
        ROLE_RAILGUN,
        ROLE_RAILGUN,
        ROLE_ROCKET,
    )
    weapon_build_cost: int = WEAPON_BUILD_COST
    max_weapon_count: int = MAX_WEAPON_COUNT
    max_wall_count: int = MAX_WALL_COUNT
    recall_safety_buffer: int = 4
    recall_traffic_buffer: int = 3
    second_day_front_upgrades: int = 3
    emergency_gold_reserve: int = 25
    cautious_defense_margin: int = 7
    critical_defense_margin: int = 3
    wall_stone_target: int = 10
    stone_batch_size: int = 10
    initial_wall_target: int = 10
    task_minimum_timeout: int = 4
    task_return_buffer: int = 4
    treasure_confidence_threshold: float = 0.95
    allow_unverified_night_economy: bool = True
    night_economy_failure_limit: int = 1
    allow_cross_map_fire: bool = False
    allow_summon_pressure: bool = False
    boss_summon_item: str = "BossRobotSummonOrder"
    minimum_opponent_observations: int = 2
    task_command_step_limit: int = 5
    task_command_output_limit: int = 16000
    task_response_wait: int = 3
    task_submit_limit: int = 3
    telemetry_byte_budget: int = 2 * 1024 * 1024
    telemetry_reserve_bytes: int = 256 * 1024
    mining_batch_size: int = 10
    mining_minimum_batch: int = 6
    first_night_wall_target: int = 16
    logistics_trip_limit: int = 40
    task_stall_limit: int = 3
    task_expected_rounds: int = 6
    treasure_gold_reserve: int = 125
    market_forecast_weight: float = 1.25
    local_mining_only: bool = True
    mining_home_radius: int = 10


DEFAULT_CONFIG = StrategyConfig()
