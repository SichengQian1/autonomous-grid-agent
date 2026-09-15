from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .economy import DefenseBudget
from .models import Turn
from .rules import ROLE_STATION, StrategyConfig


class StrategyMode(str, Enum):
    DEFEND = "DEFEND"
    DEVELOP = "DEVELOP"
    SCORE_RACE = "SCORE_RACE"
    PRESSURE = "PRESSURE"
    FINISH = "FINISH"


@dataclass(slots=True)
class OpponentModel:
    observations: int = 0
    late_threat_turns: int = 0
    previous_enemy_base_health: int | None = None
    enemy_base_damage_events: int = 0
    last_generation: int = -1
    previous_enemy_robot_health: dict[int, int] = field(default_factory=dict)
    observed_damage: int = 0
    damage_samples: int = 0
    last_enemy_clear_round: int | None = None

    def reset(self, generation: int) -> None:
        self.observations = 0
        self.late_threat_turns = 0
        self.previous_enemy_base_health = None
        self.enemy_base_damage_events = 0
        self.last_generation = generation
        self.previous_enemy_robot_health = {}
        self.observed_damage = 0
        self.damage_samples = 0
        self.last_enemy_clear_round = None

    def update(self, turn: Turn, generation: int) -> None:
        if generation != self.last_generation:
            self.reset(generation)
        enemy_base = next(
            (unit for unit in turn.team_enemy.roles if unit.role_type == ROLE_STATION),
            None,
        )
        enemy_threats = tuple(
            robot for robot in turn.robots
            if robot.health > 0 and robot.target_team and robot.target_team != turn.team_our.team_type
        )
        if not turn.is_day and enemy_threats:
            self.observations += 1
            if turn.round_in_day >= 110:
                self.late_threat_turns += 1
        current_health = {robot.robot_id: robot.health for robot in enemy_threats}
        if not turn.is_day:
            damage = sum(
                max(0, previous - current_health.get(robot_id, 0))
                for robot_id, previous in self.previous_enemy_robot_health.items()
            )
            if self.previous_enemy_robot_health:
                self.observed_damage += damage
                self.damage_samples += 1
                if not current_health:
                    self.last_enemy_clear_round = turn.round_in_day
        self.previous_enemy_robot_health = current_health
        if enemy_base is not None:
            if (
                self.previous_enemy_base_health is not None
                and enemy_base.health < self.previous_enemy_base_health
            ):
                self.enemy_base_damage_events += 1
            self.previous_enemy_base_health = enemy_base.health

    @property
    def weakness_score(self) -> int:
        return self.late_threat_turns + 2 * self.enemy_base_damage_events

    @property
    def estimated_dps(self) -> float:
        if self.damage_samples <= 0:
            return 0.0
        return self.observed_damage / self.damage_samples


def choose_mode(
    turn: Turn,
    budget: DefenseBudget,
    own_threat_count: int,
    opponent: OpponentModel,
    config: StrategyConfig,
) -> StrategyMode:
    if own_threat_count and budget.margin <= config.critical_defense_margin:
        return StrategyMode.DEFEND
    enemy_base = next(
        (unit for unit in turn.team_enemy.roles if unit.role_type == ROLE_STATION),
        None,
    )
    if enemy_base is not None and 0 < enemy_base.health <= 200 and opponent.weakness_score >= 2:
        return StrategyMode.FINISH
    if (
        opponent.observations >= config.minimum_opponent_observations
        and opponent.weakness_score >= 2
        and budget.offensive >= 200
    ):
        return StrategyMode.PRESSURE
    if turn.team_our.total_score < 100 and turn.day_index >= 6:
        return StrategyMode.SCORE_RACE
    return StrategyMode.DEVELOP


def desired_boss_orders(
    turn: Turn,
    budget: DefenseBudget,
    opponent: OpponentModel,
    config: StrategyConfig,
) -> int:
    if not config.allow_summon_pressure:
        return 0
    if opponent.observations < config.minimum_opponent_observations:
        return 0
    item = next(
        (item for item in turn.weapon_shop if item.name == config.boss_summon_item),
        None,
    )
    if item is None or item.price <= 0 or budget.margin <= config.cautious_defense_margin:
        return 0
    if opponent.weakness_score < 2:
        return 0
    count = 2 if opponent.weakness_score >= 4 else 1
    return min(count, budget.offensive // item.price)
