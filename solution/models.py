from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .geometry import CoordinateFrame, Pos, station_footprint
from .rules import (
    HUMAN_ROLE_TYPES,
    RESOURCE_ZONE_TYPES,
    ROLE_STATION,
    WEAPON_ROLE_TYPES,
    is_day_round,
    ROBOT_DEFAULTS,
)


def _mapping(raw: object) -> Mapping[str, Any]:
    return raw if isinstance(raw, Mapping) else {}


def _list(raw: object) -> list[Any]:
    return raw if isinstance(raw, list) else []


def _string(raw: object, default: str = "") -> str:
    return raw if isinstance(raw, str) else default


def _integer(raw: object, default: int = 0) -> int:
    if isinstance(raw, bool):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError, OverflowError):
        return default


def _boolean(raw: object, default: bool = False) -> bool:
    return raw if isinstance(raw, bool) else default


@dataclass(frozen=True, slots=True)
class Zone:
    pos: Pos | None = None
    neutral_type: str = ""

    @classmethod
    def from_raw(cls, raw: object) -> Zone:
        data = _mapping(raw)
        return cls(
            pos=Pos.from_raw(data.get("pos")),
            neutral_type=_string(data.get("neutralType")),
        )


@dataclass(frozen=True, slots=True)
class MapInfo:
    width: int = 0
    height: int = 0
    zones: tuple[Zone, ...] = ()

    @classmethod
    def from_raw(cls, raw: object) -> MapInfo:
        data = _mapping(raw)
        return cls(
            width=max(0, _integer(data.get("width"))),
            height=max(0, _integer(data.get("height"))),
            zones=tuple(Zone.from_raw(item) for item in _list(data.get("zones"))),
        )

    def contains(self, pos: Pos) -> bool:
        return 0 <= pos.x < self.width and 0 <= pos.y < self.height

    def zones_of_type(self, *zone_types: str) -> tuple[Zone, ...]:
        accepted = set(zone_types)
        return tuple(zone for zone in self.zones if zone.neutral_type in accepted)


@dataclass(frozen=True, slots=True)
class Unit:
    unit_id: int = -1
    pos: Pos | None = None
    role_type: str = ""
    health: int = 0
    attack_power: int = 0
    attack_range: int = 0
    backpack_capacity: int = 0
    backpack: tuple[str, ...] = ()
    level: int = 0
    cooldown: int = 0
    max_health: int = 0

    @classmethod
    def from_raw(cls, raw: object) -> Unit:
        data = _mapping(raw)
        max_health = 0
        for key in ("maxHealth", "maxHp", "healthMax"):
            if key in data:
                max_health = max(0, _integer(data.get(key)))
                break
        return cls(
            unit_id=_integer(data.get("id"), -1),
            pos=Pos.from_raw(data.get("pos")),
            role_type=_string(data.get("roleType")),
            health=_integer(data.get("health")),
            attack_power=_integer(data.get("attackPower")),
            attack_range=_integer(data.get("attackRange")),
            backpack_capacity=max(0, _integer(data.get("backPackCapability"))),
            backpack=tuple(
                item for item in _list(data.get("backpack")) if isinstance(item, str)
            ),
            level=max(0, _integer(data.get("level"))),
            cooldown=max(0, _integer(data.get("cooldown"))),
            max_health=max_health,
        )

    @property
    def alive(self) -> bool:
        return self.health > 0

    @property
    def is_human(self) -> bool:
        return self.role_type in HUMAN_ROLE_TYPES

    @property
    def is_weapon(self) -> bool:
        return self.role_type in WEAPON_ROLE_TYPES

    def footprint(self) -> tuple[Pos, ...]:
        if self.pos is None:
            return ()
        if self.role_type == ROLE_STATION:
            return station_footprint(self.pos)
        return (self.pos,)


@dataclass(frozen=True, slots=True)
class PlayerTask:
    task_type: str = ""
    task_position: Pos | None = None
    cooldown_rounds: int = 0
    score_reward: int = 0
    gold_reward: int = 0
    is_valid: bool = False
    timeout_rounds: int = 0

    @classmethod
    def from_raw(cls, raw: object) -> PlayerTask:
        data = _mapping(raw)
        return cls(
            task_type=_string(data.get("taskType")),
            task_position=Pos.from_raw(data.get("taskPosition")),
            cooldown_rounds=max(0, _integer(data.get("coldDownRounds"))),
            score_reward=max(0, _integer(data.get("scoreReward"))),
            gold_reward=max(0, _integer(data.get("goldReward"))),
            is_valid=_boolean(data.get("isValid")),
            timeout_rounds=max(0, _integer(data.get("timeoutRounds"))),
        )


@dataclass(frozen=True, slots=True)
class TeamOur:
    team_type: str = ""
    team_id: str = ""
    team_name: str = ""
    gold: int = 0
    total_score: int = 0
    player_tasks: tuple[PlayerTask, ...] = ()
    roles: tuple[Unit, ...] = ()

    @classmethod
    def from_raw(cls, raw: object) -> TeamOur:
        data = _mapping(raw)
        return cls(
            team_type=_string(data.get("type")),
            team_id=_string(data.get("teamId")),
            team_name=_string(data.get("teamName")),
            gold=max(0, _integer(data.get("goldNum"))),
            total_score=max(0, _integer(data.get("totalScore"))),
            player_tasks=tuple(
                PlayerTask.from_raw(item)
                for item in _list(data.get("playerTasks"))
            ),
            roles=tuple(Unit.from_raw(item) for item in _list(data.get("roles"))),
        )

    def unit(self, unit_id: int) -> Unit | None:
        return next((unit for unit in self.roles if unit.unit_id == unit_id), None)

    def units_of_type(self, *role_types: str) -> tuple[Unit, ...]:
        accepted = set(role_types)
        return tuple(unit for unit in self.roles if unit.role_type in accepted)

    def station(self) -> Unit | None:
        return next((unit for unit in self.roles if unit.role_type == ROLE_STATION), None)


@dataclass(frozen=True, slots=True)
class TeamEnemy:
    roles: tuple[Unit, ...] = ()

    @classmethod
    def from_raw(cls, raw: object) -> TeamEnemy:
        data = _mapping(raw)
        return cls(
            roles=tuple(Unit.from_raw(item) for item in _list(data.get("roles")))
        )


@dataclass(frozen=True, slots=True)
class Robot:
    robot_id: int = -1
    pos: Pos | None = None
    role_type: str = ""
    health: int = 0
    abnormal_state: str = ""
    target_team: str = ""
    attack_power: int = 0
    attack_range: int = 3
    kill_score: int = 0

    @classmethod
    def from_raw(cls, raw: object) -> Robot:
        data = _mapping(raw)
        power, reach, score = ROBOT_DEFAULTS.get(_string(data.get("roleType")), (40, 3, 0))
        return cls(
            robot_id=_integer(data.get("id"), -1),
            pos=Pos.from_raw(data.get("pos")),
            role_type=_string(data.get("roleType")),
            health=_integer(data.get("health")),
            abnormal_state=_string(data.get("abnormalState")),
            target_team=_string(data.get("targetTeam")),
            attack_power=max(0, _integer(data.get("attackPower"), power)),
            attack_range=max(0, _integer(data.get("attackRange"), reach)),
            kill_score=max(0, _integer(data.get("score"), score)),
        )


@dataclass(frozen=True, slots=True)
class WorldNews:
    official_news: str = ""
    folk_legends: str = ""

    @classmethod
    def from_raw(cls, raw: object) -> WorldNews:
        data = _mapping(raw)
        return cls(
            official_news=_string(data.get("officialNews")),
            folk_legends=_string(data.get("folkLegends")),
        )


@dataclass(frozen=True, slots=True)
class ShopItem:
    name: str = ""
    price: int = 0

    @classmethod
    def from_raw(cls, raw: object) -> ShopItem:
        data = _mapping(raw)
        return cls(
            name=_string(data.get("name")),
            price=max(0, _integer(data.get("price"))),
        )


@dataclass(frozen=True, slots=True)
class ErrorFeedback:
    error_code: int = 0
    description: str = ""

    @classmethod
    def from_raw(cls, raw: object) -> ErrorFeedback:
        data = _mapping(raw)
        return cls(
            error_code=_integer(data.get("errorCode")),
            description=_string(data.get("description")),
        )


@dataclass(frozen=True, slots=True)
class Turn:
    round_no: int = 0
    map_info: MapInfo = field(default_factory=MapInfo)
    team_our: TeamOur = field(default_factory=TeamOur)
    team_enemy: TeamEnemy = field(default_factory=TeamEnemy)
    robots: tuple[Robot, ...] = ()
    robots_observed: bool = False
    phase_task: str = ""
    last_action_results: Mapping[int, bool] = field(default_factory=dict)
    last_summon_treasure_result: int = 0
    llm_response: str = ""
    world_news: WorldNews = field(default_factory=WorldNews)
    last_command_result: str = ""
    vendor_shop: tuple[ShopItem, ...] = ()
    weapon_shop: tuple[ShopItem, ...] = ()
    errors: tuple[ErrorFeedback, ...] = ()

    @classmethod
    def from_raw(cls, raw: object) -> Turn:
        data = _mapping(raw)
        robot_data = _mapping(data.get("robot"))
        action_results: dict[int, bool] = {}
        for raw_key, raw_value in _mapping(
            data.get("lastRoundRoleActionResults")
        ).items():
            role_id = _integer(raw_key, -1)
            if role_id >= 0 and isinstance(raw_value, bool):
                action_results[role_id] = raw_value

        return cls(
            round_no=max(0, _integer(data.get("roundNo"))),
            map_info=MapInfo.from_raw(data.get("mapInfo")),
            team_our=TeamOur.from_raw(data.get("teamOur")),
            team_enemy=TeamEnemy.from_raw(data.get("teamEnemy")),
            robots=tuple(
                Robot.from_raw(item) for item in _list(robot_data.get("roles"))
            ),
            robots_observed=isinstance(robot_data.get("roles"), list),
            phase_task=_string(data.get("phaseTask")),
            last_action_results=action_results,
            last_summon_treasure_result=_integer(
                data.get("lastSummonTreasureResult")
            ),
            llm_response=_string(data.get("llmResp")),
            world_news=WorldNews.from_raw(data.get("worldNews")),
            last_command_result=_string(data.get("lastCmdResult")),
            vendor_shop=tuple(
                ShopItem.from_raw(item) for item in _list(data.get("vendorShopList"))
            ),
            weapon_shop=tuple(
                ShopItem.from_raw(item) for item in _list(data.get("weaponShopList"))
            ),
            errors=tuple(
                ErrorFeedback.from_raw(item) for item in _list(data.get("errors"))
            ),
        )

    @property
    def is_day(self) -> bool:
        return is_day_round(self.round_no)

    @property
    def coordinate_frame(self) -> CoordinateFrame:
        return CoordinateFrame(
            width=self.map_info.width,
            height=self.map_info.height,
            team_type=self.team_our.team_type,
        )

    def resource_at(self, pos: Pos) -> bool:
        return any(
            zone.pos == pos and zone.neutral_type in RESOURCE_ZONE_TYPES
            for zone in self.map_info.zones
        )

    def zone_positions(self, zone_type: str) -> tuple[Pos, ...]:
        return tuple(
            zone.pos
            for zone in self.map_info.zones
            if zone.neutral_type == zone_type and zone.pos is not None
        )
