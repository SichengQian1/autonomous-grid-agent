from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations

from .actions import Action, ActionType
from .geometry import Pos
from .models import Robot, Turn, Unit
from .grid import OccupancyGrid, distance_field, interaction_cells
from .defense import build_defense_layout, _controller_sites
from .rules import ROLE_GATLING, ROLE_RAILGUN, ROLE_ROCKET, DEFAULT_CONFIG, DAY_ROUNDS


ROBOT_SCORE = {
    "smallRobot": 1,
    "middleRobot": 2,
    "largeRobot": 4,
    "bossRobot": 10,
}
ROBOT_ATTACK = {
    "smallRobot": 5,
    "middleRobot": 10,
    "largeRobot": 20,
    "bossRobot": 40,
}


@dataclass(frozen=True, slots=True)
class ControllerAssignment:
    weapon: Unit
    controller: Unit
    control_pos: Pos | None = None


def assign_controllers(turn: Turn, weapons: tuple[Unit, ...], config=DEFAULT_CONFIG) -> tuple[ControllerAssignment, ...]:
    available = tuple(sorted((r for r in turn.controllable if r.pos is not None), key=lambda r:r.unit_id))[:3]
    ordered = tuple(sorted((w for w in weapons if w.pos is not None), key=lambda w:(w.role_type != ROLE_ROCKET,w.unit_id)))[:len(available)]
    if not ordered:
        return ()
    layout = build_defense_layout(turn)
    # A single common legal cell serves all three rear launchers. Prefer the
    # pioneer, but an already present worker covers an absent/blocked pioneer.
    if config.shared_rocket_control and len(weapons)==3 and all(w.role_type==ROLE_ROCKET for w in weapons):
        post=layout.controller_sites[0] if layout.controller_sites else None
        if post and all(w.pos and w.pos.distance_to(post)==1 for w in weapons):
            grid=OccupancyGrid.from_turn(turn,ignore_unit_ids=tuple(r.unit_id for r in available))
            distances=distance_field(grid,(post,))
            pioneer=next((r for r in available if r.role_type=='pioneer'),None)
            present=next((r for r in available if r.pos==post),None)
            reachable=[r for r in available if distances.get(r.pos,10000)<10000]
            selected=(pioneer if pioneer in reachable else None) or present or min(reachable,key=lambda r:(distances[r.pos],r.unit_id),default=None)
            if selected:
                return tuple(ControllerAssignment(w,selected,post) for w in weapons)
    if config.shared_rocket_control and len(weapons)==3 and all(w.role_type==ROLE_ROCKET for w in weapons) and len(available)>=2:
        slots_by_weapon=dict(zip(layout.weapon_sites[:3],layout.controller_sites))
        if all(w.pos in slots_by_weapon for w in weapons) and len(set(slots_by_weapon.values()))==2:
            posts=tuple(dict.fromkeys(slots_by_weapon.values()))
            grid=OccupancyGrid.from_turn(turn,ignore_unit_ids=tuple(r.unit_id for r in available))
            maps={r.unit_id:distance_field(grid,(r.pos,)) for r in available}
            def joint_cost(roles):
                distances=[maps[r.unit_id].get(p,10000) for r,p in zip(roles,posts)]
                support_penalty=(8 if all(r.role_type=="worker" for r in roles) and not turn.phase_task else 0)+sum(12 for r in roles if turn.day_index>=config.night_support_day and any(i=='WallFixer' or i.startswith('WallUpgradeVoucher') for i in r.backpack))
                return (sum(d>=10000 for d in distances),max(distances)+support_penalty,sum(distances),tuple(r.unit_id for r in roles))
            chosen=min(permutations(available,2),key=joint_cost)
            by_post=dict(zip(posts,chosen))
            return tuple(ControllerAssignment(w,by_post[slots_by_weapon[w.pos]],slots_by_weapon[w.pos]) for w in weapons)
    actual=tuple(w.pos for w in ordered)
    controls=_controller_sites(turn,actual,layout.rear_corridor,layout.wall_sites)
    slots=dict(zip(actual,controls)) if len(controls)==len(actual) else {}
    grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=tuple(r.unit_id for r in available))
    maps = {r.unit_id: distance_field(grid, (r.pos,)) for r in available}
    goals = {w.unit_id: ((slots[w.pos],) if w.pos in slots else interaction_cells(grid, w.pos)) for w in ordered}
    def cost(roles):
        distances = [min((maps[r.unit_id].get(p, 10000) for p in goals[w.unit_id]), default=10000)
                     for w,r in zip(ordered,roles)]
        return sum(d >= 10000 for d in distances), max(distances), sum(distances), tuple(r.unit_id for r in roles)
    chosen = min(permutations(available,len(ordered)),key=cost)
    return tuple(ControllerAssignment(w,r,slots.get(w.pos)) for w,r in zip(ordered,chosen))


def controllers_needed(weapons: tuple[Unit, ...], robots: tuple[Robot, ...]) -> int:
    if not robots:
        return 0
    total_health = sum(max(0, robot.health) for robot in robots)
    ordered_damage = sorted((max(10, weapon.attack_power) for weapon in weapons), reverse=True)
    cumulative = 0
    for count, damage in enumerate(ordered_damage, 1):
        cumulative += damage
        if cumulative >= min(total_health, 80):
            return count
    return len(weapons)


def plan_attacks(
    turn: Turn,
    assignments: tuple[ControllerAssignment, ...],
    robots: tuple[Robot, ...],
    priority_targets: tuple[Robot, ...] = (),
) -> tuple[Action, ...]:
    all_robots = tuple({r.robot_id:r for r in robots + priority_targets}.values())
    projected = {robot.robot_id: robot.health for robot in all_robots}
    actions: list[Action] = []
    used=set()
    for assignment in sorted(assignments, key=lambda item: _weapon_priority(item.weapon)):
        weapon, controller = assignment.weapon, assignment.controller
        if (
            controller.unit_id in used
            or weapon.pos is None
            or controller.pos is None
            or controller.pos.distance_to(weapon.pos) > 1
            or (weapon.role_type == ROLE_ROCKET and weapon.cooldown > 0)
        ):
            continue
        in_range = tuple(
            robot for robot in robots
            if robot.pos is not None
            and projected.get(robot.robot_id, 0) > 0
            and weapon.pos.distance_to(robot.pos) <= weapon.attack_range
        )
        if weapon.role_type == ROLE_ROCKET and weapon.level >= 3:
            preferred = tuple(r for r in priority_targets if r.pos and projected.get(r.robot_id,0)>0
                              and weapon.pos.distance_to(r.pos)<=weapon.attack_range)
            if preferred:
                in_range = preferred
        if not in_range:
            continue
        targets = _targets_for_weapon(weapon, in_range, projected, turn)
        if not targets:
            continue
        actions.append(
            Action(
                weapon.unit_id,
                ActionType.ATTACK,
                controller_id=controller.unit_id,
                targets=targets,
            )
        )
        used.add(controller.unit_id)
        _apply_projected_damage(weapon, targets, all_robots, projected)
    return tuple(actions)


def raid_targets(turn, config):
    """Ten-turn experiment, with a conservative immediate home-danger override."""
    if (turn.is_day or turn.day_index < config.opening_raid_day
            or turn.round_in_day > DAY_ROUNDS + config.opening_raid_turns):
        return (), 'outside_opening_raid'
    if not any(w.is_weapon and w.role_type==ROLE_ROCKET and w.level>=3 and w.alive for w in turn.team_our.roles):
        return (), 'no_level_three_rocket'
    from .defense import own_threats
    from .maintenance import wall_damage_risk
    base=turn.team_our.station()
    threats=own_threats(turn)
    if not base:return (), 'no_base'
    if any(r.pos and min(r.pos.distance_to(p) for p in base.footprint()) <= (r.attack_range or config.robot_attack_range_fallback)
           for r in threats):
        return (), 'home_contact_emergency'
    if any(w.health <= wall_damage_risk(w,config,threats)[1]*2
           for w in turn.team_our.roles if w.role_type=='wall' and w.alive and w.pos):
        return (), 'wall_collapse_emergency'
    from .rules import TEAM_CHALLENGER, TEAM_DEFENDER
    enemy={TEAM_CHALLENGER:TEAM_DEFENDER,TEAM_DEFENDER:TEAM_CHALLENGER}.get(turn.team_our.team_type)
    targets=tuple(r for r in turn.robots if enemy and r.target_team==enemy and r.health>0 and r.pos
                  and r.role_type in ('smallRobot','middleRobot'))
    return targets, 'opening_opponent_raid' if targets else 'no_opponent_small_medium'


def _weapon_priority(weapon: Unit) -> tuple[int, int]:
    order = {ROLE_ROCKET: 0, ROLE_RAILGUN: 1, ROLE_GATLING: 2}
    return (order.get(weapon.role_type, 9), weapon.unit_id)


def _threat_score(turn: Turn, robot: Robot, remaining_health: int) -> float:
    station = turn.team_our.station()
    distance = 99
    if station is not None and robot.pos is not None:
        distance = min(robot.pos.distance_to(cell) for cell in station.footprint())
    attack = robot.attack_power or ROBOT_ATTACK.get(robot.role_type, 5)
    kill = ROBOT_SCORE.get(robot.role_type, 1)
    lethal_bonus = 35 if remaining_health <= 30 else 0
    return 200 / max(distance, 1) + attack * 3 + kill * 8 + lethal_bonus - remaining_health * 0.05


def _targets_for_weapon(
    weapon: Unit,
    robots: tuple[Robot, ...],
    projected: dict[int, int],
    turn: Turn,
) -> tuple[Pos, ...]:
    if weapon.role_type == ROLE_RAILGUN:
        best = max(
            robots,
            key=lambda robot: _railgun_value(weapon, robot, robots, projected, turn),
        )
        return (best.pos,) if best.pos is not None else ()
    count = max(weapon.level, 1)
    if weapon.role_type == ROLE_ROCKET:
        centers: list[Pos] = []
        working = dict(projected)
        for _ in range(count):
            candidates = {
                candidate
                for robot in robots
                if robot.pos is not None
                for candidate in (robot.pos,) + robot.pos.neighbours()
                if turn.map_info.contains(candidate)
                and weapon.pos is not None
                and weapon.pos.distance_to(candidate) <= weapon.attack_range
            }
            if not candidates:
                break
            best = max(candidates, key=lambda pos: _rocket_value(pos, robots, working, turn, weapon))
            centers.append(best)
            _apply_rocket_projection(best, robots, working, weapon)
        return tuple(centers)
    ordered = sorted(
        robots,
        key=lambda robot: -_threat_score(turn, robot, projected[robot.robot_id]),
    )
    if not ordered or ordered[0].pos is None:
        return ()
    # Repeated aim is a conservative way to satisfy upgraded target count and the
    # 90-degree cone while concentrating bullets on a high-value target.
    return tuple(ordered[0].pos for _ in range(count))


def _railgun_value(
    weapon: Unit,
    target: Robot,
    robots: tuple[Robot, ...],
    projected: dict[int, int],
    turn: Turn,
) -> float:
    if weapon.pos is None or target.pos is None:
        return float("-inf")
    dx = target.pos.x - weapon.pos.x
    dy = target.pos.y - weapon.pos.y
    value = 0.0
    for robot in robots:
        if robot.pos is None or projected[robot.robot_id] <= 0:
            continue
        rx = robot.pos.x - weapon.pos.x
        ry = robot.pos.y - weapon.pos.y
        if dx * ry == dy * rx and dx * rx + dy * ry > 0:
            value += _threat_score(turn, robot, projected[robot.robot_id])
    return value


def _rocket_value(
    center: Pos,
    robots: tuple[Robot, ...],
    projected: dict[int, int],
    turn: Turn,
    weapon: Unit | None = None,
) -> float:
    value = 0.0
    for robot in robots:
        if robot.pos is None or projected[robot.robot_id] <= 0:
            continue
        distance = center.distance_to(robot.pos)
        if distance <= 1:
            power=(weapon.attack_power if weapon.attack_power>0 else 20) if weapon else 20
            damage=power if distance==0 else max(1,power//2)
            hp=projected[robot.robot_id]
            station=turn.team_our.station()
            urgent=bool(station and robot.pos and station.health<500 and min(robot.pos.distance_to(p) for p in station.footprint())<=(robot.attack_range or DEFAULT_CONFIG.robot_attack_range_fallback)+1)
            small=robot.role_type in ('smallRobot','middleRobot')
            value+=min(damage,hp)*(5 if small else 1)
            value+=(140 if small else 45) if hp<=damage else 0
            value+=_threat_score(turn,robot,hp)*(3 if urgent else 0.12)
            value-=max(0,damage-hp)*0.5
    return value


def _apply_projected_damage(
    weapon: Unit,
    targets: tuple[Pos, ...],
    robots: tuple[Robot, ...],
    projected: dict[int, int],
) -> None:
    if weapon.role_type == ROLE_ROCKET:
        for target in targets:
            _apply_rocket_projection(target, robots, projected, weapon)
        return
    if weapon.role_type == ROLE_RAILGUN and weapon.pos is not None:
        energy = max(weapon.attack_power, 10 * max(weapon.level, 1))
        target = targets[0]
        dx, dy = target.x - weapon.pos.x, target.y - weapon.pos.y
        aligned = sorted(
            (
                robot for robot in robots
                if robot.pos is not None
                and dx * (robot.pos.y - weapon.pos.y) == dy * (robot.pos.x - weapon.pos.x)
                and dx * (robot.pos.x - weapon.pos.x) + dy * (robot.pos.y - weapon.pos.y) > 0
            ),
            key=lambda robot: weapon.pos.distance_to(robot.pos),
        )
        for robot in aligned:
            damage = min(energy, projected.get(robot.robot_id, 0))
            projected[robot.robot_id] = max(0, projected.get(robot.robot_id, 0) - damage)
            energy -= damage
            if energy <= 0:
                break
        return
    damage = max(weapon.attack_power, 10)
    for target in targets:
        hit = next((robot for robot in robots if robot.pos == target and projected[robot.robot_id] > 0), None)
        if hit is not None:
            projected[hit.robot_id] = max(0, projected[hit.robot_id] - damage)


def _apply_rocket_projection(
    center: Pos,
    robots: tuple[Robot, ...],
    projected: dict[int, int],
    weapon: Unit,
) -> None:
    center_damage = weapon.attack_power if weapon.attack_power>0 else 20
    splash_damage = max(1, center_damage // 2)
    for robot in robots:
        if robot.pos is None:
            continue
        distance = center.distance_to(robot.pos)
        if distance <= 1:
            damage = center_damage if distance == 0 else splash_damage
            projected[robot.robot_id] = max(0, projected.get(robot.robot_id, 0) - damage)
