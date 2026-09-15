from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable

from .actions import Action, ActionType
from .ballistics import projectile_blockers
from .defense import base_cells
from .geometry import Pos, footprint_distance, neighbours, ray_entry
from .models import Robot, Turn, Unit
from .rules import DAY_ROUNDS, ROUNDS_PER_DAY, ROLE_GATLING, ROLE_ROCKET, StrategyConfig


def live_robots(turn: Turn) -> tuple[Robot, ...]:
    return tuple(r for r in turn.robots if r.health > 0 and r.pos is not None)


def threatens_us(turn: Turn, robot: Robot) -> bool:
    return (robot.target_team in {"", turn.team_our.team_type}
            or (robot.pos is not None and footprint_distance(robot.pos, base_cells(turn)) <= robot.attack_range + 4))


def threat_weight(turn: Turn, robot: Robot) -> float:
    distance = footprint_distance(robot.pos, base_cells(turn)) if robot.pos else 1000
    eta = max(0, distance - robot.attack_range)
    priority = 1.0 if threatens_us(turn, robot) else 0.05
    return priority * (1.0 + 5.0 / (eta + 1) + robot.attack_power / 10 + robot.kill_score / 4)


def angle_valid(origin: Pos, targets: tuple[Pos, ...]) -> bool:
    vectors = [(p.x - origin.x, p.y - origin.y) for p in targets]
    return all(x or y for x, y in vectors) and all(
        x * u + y * v >= 0 for i, (x, y) in enumerate(vectors) for u, v in vectors[i + 1:])


def shot_damage(turn: Turn, weapon: Unit, target: Pos, config: StrategyConfig) -> dict[int, float]:
    if weapon.pos is None or target == weapon.pos or weapon.attack_power <= 0:
        return {}
    robots = live_robots(turn)
    if weapon.role_type == ROLE_ROCKET:
        return {r.robot_id: weapon.attack_power * (1 if r.pos == target else 0.5)
                for r in robots if r.pos.distance_to(target) <= 1}
    stop = 1.1
    if config.projectile_building_blocking:
        for cell in projectile_blockers(turn, weapon.unit_id):
            entry = ray_entry(weapon.pos, target, cell)
            if entry is not None:
                stop = min(stop, entry)
    hits = []
    for robot in robots:
        entry = ray_entry(weapon.pos, target, robot.pos)
        if entry is not None and entry < stop:
            hits.append((entry, robot.robot_id, robot))
    hits.sort(key=lambda item: (item[0], item[1]))
    energy = float(weapon.attack_power)
    damage: dict[int, float] = {}
    for _, _, robot in hits:
        damage[robot.robot_id] = min(energy, robot.health)
        if weapon.role_type == ROLE_GATLING:
            break
        energy -= damage[robot.robot_id]
        if energy <= 0:
            break
    return damage


@dataclass(frozen=True, slots=True)
class FirePlan:
    actions: tuple[Action, ...]
    damage: dict[int, float]


class CombatPlanner:
    def __init__(self, turn: Turn, config: StrategyConfig, deadline: float) -> None:
        self.turn, self.config, self.deadline = turn, config, deadline
        self.robots = live_robots(turn)
        self.weights = {r.robot_id: threat_weight(turn, r) for r in self.robots}
        self.health = {r.robot_id: r.health for r in self.robots}
        self.profiles: dict[tuple[int, Pos], dict[int, float]] = {}

    def _profile(self, weapon: Unit, target: Pos) -> dict[int, float]:
        key = weapon.unit_id, target
        if key not in self.profiles:
            self.profiles[key] = shot_damage(self.turn, weapon, target, self.config)
        return self.profiles[key]

    def _value(self, damage: dict[int, float], assigned: dict[int, float]) -> float:
        value = 0.0
        for robot_id, amount in damage.items():
            remaining = max(0, self.health[robot_id] - assigned.get(robot_id, 0))
            effective = min(remaining, amount)
            value += effective * self.weights[robot_id]
            if 0 < remaining <= amount:
                value += 15 * self.weights[robot_id]
        return value

    def plan(self, assignments: dict[int, Unit], *, excluded: frozenset[int] = frozenset(),
             admissible: Callable[[Action], bool] | None = None) -> FirePlan:
        if self.turn.is_day:
            return FirePlan((), {})
        actions: list[Action] = []
        assigned: dict[int, float] = {}
        # Area damage first; precision weapons consume the remaining useful targets.
        pairs = sorted(assignments.items(), key=lambda pair: (pair[1].role_type != ROLE_ROCKET, -pair[1].attack_power, pair[0]))
        for controller_id, weapon in pairs:
            if time.monotonic() >= self.deadline:
                break
            controller = self.turn.team_our.unit(controller_id)
            if (controller_id in excluded or controller is None or not controller.alive or controller.pos is None
                    or weapon.pos is None or controller.pos.distance_to(weapon.pos) != 1
                    or weapon.cooldown > 0 or weapon.attack_range <= 0 or weapon.attack_power <= 0):
                continue
            candidates = set()
            for robot in sorted(self.robots, key=lambda r: -self.weights[r.robot_id]):
                if not self.config.allow_score_stealing and not threatens_us(self.turn, robot):
                    continue
                points = (robot.pos,) + neighbours(robot.pos) if weapon.role_type == ROLE_ROCKET else (robot.pos,)
                for point in points:
                    if self.turn.map_info.contains(point) and 0 < weapon.pos.distance_to(point) <= weapon.attack_range:
                        candidates.add(point)
                if len(candidates) >= self.config.combat_candidate_limit:
                    break
            candidates = sorted(candidates)[:self.config.combat_candidate_limit]
            count = max(1, weapon.level) if weapon.role_type in {ROLE_GATLING, ROLE_ROCKET} else 1
            if count > 3:
                continue
            chosen: list[Pos] = []
            local = dict(assigned)
            for _ in range(count):
                best: tuple[float, Pos, dict[int, float]] | None = None
                for target in candidates:
                    if time.monotonic() >= self.deadline:
                        break
                    if weapon.role_type == ROLE_GATLING and not angle_valid(weapon.pos, tuple(chosen) + (target,)):
                        continue
                    damage = self._profile(weapon, target)
                    value = self._value(damage, local)
                    if best is None or value > best[0]:
                        best = value, target, damage
                if best is None:
                    break
                # Repeated targets are legal and required to fill upgraded salvos.
                if not chosen and best[0] <= 0:
                    break
                chosen.append(best[1])
                for robot_id, amount in best[2].items():
                    local[robot_id] = local.get(robot_id, 0) + amount
            if len(chosen) == count:
                action = Action(weapon.unit_id, ActionType.ATTACK, controller_id=controller_id, targets=tuple(chosen))
                if admissible is None or admissible(action):
                    actions.append(action)
                    assigned = local
        return FirePlan(tuple(actions), assigned)

    def value(self, fire: FirePlan) -> float:
        return self._value(fire.damage, {})

    def accepted_fire(self, actions: list[Action]) -> FirePlan:
        accepted = tuple(a for a in actions if a.action_type == ActionType.ATTACK)
        damage: dict[int, float] = {}
        for action in accepted:
            weapon = self.turn.team_our.unit(action.actor_id)
            if weapon is not None:
                for target in action.targets:
                    for robot_id, amount in self._profile(weapon, target).items():
                        damage[robot_id] = damage.get(robot_id, 0) + amount
        return FirePlan(accepted, damage)

    def can_release(self, assignments: dict[int, Unit], released: frozenset[int], *,
                    admissible: Callable[[Action], bool] | None = None,
                    committed: FirePlan | None = None) -> bool:
        """Require an already staffed, ready-to-fire, one-turn cleanup proof."""
        if not self.config.night_gathering or not self.turn.robots_observed:
            return False
        if any(r.pos is None or not self.turn.map_info.contains(r.pos) for r in self.turn.robots):
            return False
        # The first nighttime observation may precede the initial spawn.
        if (max(1, self.turn.round_no) - 1) % ROUNDS_PER_DAY <= DAY_ROUNDS:
            return False
        relevant = [r for r in self.robots if threatens_us(self.turn, r)]
        if not relevant:
            return True
        if len(relevant) > self.config.night_small_wave:
            return False
        # Do not release anyone while a robot can already attack the base.
        if any(footprint_distance(r.pos, base_cells(self.turn)) <= r.attack_range + 1 for r in relevant):
            return False
        remaining = committed if committed is not None else self.plan(assignments, excluded=released, admissible=admissible)
        return all(remaining.damage.get(r.robot_id, 0) >= r.health for r in relevant)
