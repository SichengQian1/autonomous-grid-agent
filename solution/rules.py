from __future__ import annotations

from dataclasses import dataclass


DAY_ROUNDS = 70
NIGHT_ROUNDS = 60
ROUNDS_PER_DAY = DAY_ROUNDS + NIGHT_ROUNDS
NORMAL_TURN_BUDGET_SECONDS = 4.0
WEAPON_BUILD_COST = 25
MAX_WEAPONS = 3
MAX_BUILDING_LEVEL = 3
ROBOT_DEFAULTS = {
    "smallRobot": (5, 3, 1),
    "middleRobot": (10, 3, 2),
    "largeRobot": (20, 3, 4),
    "bossRobot": (40, 3, 10),
}

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

# Documented wall hit points by level; runtime maxHealth overrides this table.
WALL_LEVEL_MAX_HP = {1: 1000, 2: 1500, 3: 2000}
# Level-1 coverage estimates used only when a planned weapon is not yet built.
# Values match the existing synthetic construction harness, not live platform stats.
WEAPON_LEVEL1_RANGE = {ROLE_GATLING: 3, ROLE_RAILGUN: 6, ROLE_ROCKET: 10}
WEAPON_LEVEL1_POWER = {ROLE_GATLING: 10, ROLE_RAILGUN: 10, ROLE_ROCKET: 20}
# Consecutive night snapshots required before the recorded approach may change.
FRONT_DIRECTION_SHIFT_CONFIRM = 3
# Stuck wall deliveries are replanned inside one daytime window of 70 rounds.
WALL_DELIVERY_TIMEOUT_ROUNDS = 40
# Initial opportunity-cost estimate for wall work, in gold per role action.
WALL_ACTION_GOLD_EQUIVALENT = 1.0
# Auto front is unreliable when the footprint sits this close to the midline.
FRONT_MIDLINE_MARGIN = 1
LAYOUT_CONNECTIVITY_NODE_LIMIT = 128
LAYOUT_TEST_POINT_LIMIT = 8
DEFENSE_LAYOUT_LEGACY = "legacy"
DEFENSE_LAYOUT_FRONTLINE = "frontline"
FRONT_DIRECTION_AUTO = "auto"
FRONT_DIRECTION_EAST = "east"
FRONT_DIRECTION_WEST = "west"


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
    enabled: bool = True
    return_margin: int = 5
    path_node_limit: int = 8192
    stone_reserve: int = 4
    sell_batch: int = 8
    max_walls: int = 10
    task_min_rounds: int = 10
    task_retry_rounds: int = 3
    max_task_calls: int = 12
    night_gathering: bool = True
    night_trip_radius: int = 8
    night_small_wave: int = 3
    heal_below: int = 120
    base_emergency_health: int = 800
    projectile_building_blocking: bool = True
    allow_score_stealing: bool = False
    combat_candidate_limit: int = 128
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
    defense_layout: str = DEFENSE_LAYOUT_LEGACY
    front_direction: str = FRONT_DIRECTION_AUTO
    front_wall_target_count: int = 4
    initial_flank_defense: bool = False
    initial_flank_depth: int = 1
    wall_maintenance_enabled: bool = False
    wall_budget_fraction: float = 0.25
    wall_emergency_horizon: int = 3
    wall_observation_history_rounds: int = 130
    front_observation_limit: int = 64
    layout_candidate_limit: int = 128
    layout_search_budget_ms: int = 100


DEFAULT_CONFIG = StrategyConfig()
