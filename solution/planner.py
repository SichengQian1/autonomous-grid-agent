from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from .actions import Action, ActionType, Decision
from .combat import assign_controllers, controllers_needed, plan_attacks
from .defense import (
    build_defense_layout,
    estimated_contact_turns,
    existing_weapons,
    own_threats,
)
from .economy import (
    DefenseBudget,
    backpack_full,
    best_resource,
    defense_budget,
    resource_inventory,
    wall_build_objective,
    weapon_build_objectives,
)
from .grid import OccupancyGrid, interaction_cells
from .logistics import plan_upgrade_or_repair
from .models import Turn, Unit
from .movement import MoveIntent, schedule_moves
from .opponent import OpponentModel, StrategyMode, choose_mode, desired_boss_orders
from .rules import ROLE_PIONEER, ROLE_WORKER, StrategyConfig
from .state import LlmBudget, WorldState
from .tasking import AdvancedPlan, TaskManager, TreasureKnowledge


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class CompetitionPlanner:
    opponent: OpponentModel = field(default_factory=OpponentModel)
    tasks: TaskManager = field(default_factory=TaskManager)
    treasure: TreasureKnowledge = field(default_factory=TreasureKnowledge)
    last_generation: int = -1
    treasure_prompt_day: int = -1
    treasure_prompt_pending: bool = False

    def plan(
        self,
        turn: Turn,
        state: WorldState,
        llm_budget: LlmBudget,
        config: StrategyConfig,
        deadline_reached: Callable[[], bool],
    ) -> Decision:
        if state.generation != self.last_generation:
            self.opponent.reset(state.generation)
            self.tasks.reset(state.generation)
            self.treasure = TreasureKnowledge()
            self.treasure_prompt_day = -1
            self.treasure_prompt_pending = False
            self.last_generation = state.generation
        if self.treasure_prompt_pending and turn.llm_response:
            self.treasure.ingest_llm(turn.llm_response)
            self.treasure_prompt_pending = False
        self.opponent.update(turn, state.generation)
        self.treasure.apply_result(turn.last_summon_treasure_result)
        if deadline_reached():
            return Decision()

        threats = own_threats(turn)
        budget = defense_budget(
            turn,
            config,
            sum(robot.health for robot in threats),
            estimated_contact_turns(turn, threats),
        )
        mode = choose_mode(turn, budget, len(threats), self.opponent, config)
        try:
            if turn.is_day:
                decision = self._day(turn, state, llm_budget, config, mode, budget)
            else:
                decision = self._night(turn, state, llm_budget, config, mode, threats)
        except Exception as error:
            LOGGER.warning(
                "primary planner failed (%s); falling back to basic defense",
                type(error).__name__,
            )
            decision = self._basic_defense(turn, threats)
        if deadline_reached():
            return self._basic_defense(turn, threats)
        return decision

    def _day(
        self,
        turn: Turn,
        state: WorldState,
        llm_budget: LlmBudget,
        config: StrategyConfig,
        mode: StrategyMode,
        budget: DefenseBudget,
    ) -> Decision:
        layout = build_defense_layout(turn, conservative=state.rear_threat_observed)
        actions: list[Action] = []
        intents: list[MoveIntent] = []
        used: set[int] = set()
        workers = sorted(turn.team_our.units_of_type(ROLE_WORKER), key=lambda unit: unit.unit_id)
        workers = [worker for worker in workers if worker.alive and worker.pos is not None]
        pioneer = next(
            (unit for unit in turn.team_our.units_of_type(ROLE_PIONEER) if unit.alive),
            None,
        )

        recall = self._recall_needed(turn, layout, config)
        if recall:
            recall_intents = self._controller_intents(turn, priority=120)
            assigned_recall = {intent.actor_id for intent in recall_intents}
            station = turn.team_our.station()
            if station is not None:
                station_cells = station.footprint()
                for role in turn.controllable:
                    if role.unit_id in assigned_recall or role.pos is None:
                        continue
                    grid = OccupancyGrid.from_turn(
                        turn,
                        ignore_unit_ids=(role.unit_id,),
                    )
                    goals = tuple(
                        goal
                        for cell in station_cells
                        for goal in interaction_cells(grid, cell)
                    )
                    recall_intents.append(
                        MoveIntent(role.unit_id, goals, priority=110)
                    )
            intents.extend(recall_intents)
            used.update(intent.actor_id for intent in recall_intents)
        else:
            objectives = weapon_build_objectives(turn, layout, state, config)
            for worker, objective in zip(workers, objectives):
                if worker.pos is None:
                    continue
                if worker.pos.distance_to(objective.site) <= 1 and worker.pos != objective.site:
                    actions.append(
                        Action(
                            worker.unit_id,
                            ActionType.BUILD,
                            targets=(objective.site,),
                            name=objective.name,
                        )
                    )
                else:
                    intents.append(
                        MoveIntent(
                            worker.unit_id,
                            self._interaction_goals(turn, worker, objective.site),
                            priority=objective.priority,
                        )
                    )
                used.add(worker.unit_id)

            reserved_wall_sites = set()
            for worker in workers:
                if worker.unit_id in used:
                    continue
                wall = wall_build_objective(
                    turn,
                    worker,
                    layout,
                    state,
                    config,
                    reserved_wall_sites,
                )
                if wall is not None:
                    reserved_wall_sites.add(wall.site)
                    if worker.pos is not None and worker.pos.distance_to(wall.site) <= 1 and worker.pos != wall.site:
                        actions.append(
                            Action(worker.unit_id, ActionType.BUILD, targets=(wall.site,), name=wall.name)
                        )
                    else:
                        intents.append(
                            MoveIntent(
                                worker.unit_id,
                                self._interaction_goals(turn, worker, wall.site),
                                priority=wall.priority,
                            )
                        )
                    used.add(worker.unit_id)

            advanced = AdvancedPlan()
            if pioneer is not None:
                advanced = self._safe_task_plan(
                    turn,
                    state,
                    llm_budget,
                    config,
                    pioneer,
                )
                self._merge_advanced(advanced, actions, intents, used)
                if pioneer.unit_id not in used:
                    boss_plan = self._boss_plan(turn, pioneer, mode, budget, config)
                    self._merge_advanced(boss_plan, actions, intents, used)
                if pioneer.unit_id not in used:
                    treasure_action = self.treasure.action(turn, pioneer, config)
                    if treasure_action is not None:
                        actions.append(treasure_action)
                        used.add(pioneer.unit_id)
                    elif (
                        not turn.phase_task
                        and self.treasure.position is not None
                        and self.treasure.confidence >= config.treasure_confidence_threshold
                    ):
                        intents.append(
                            MoveIntent(
                                pioneer.unit_id,
                                tuple(self.treasure.position.neighbours()),
                                priority=50,
                            )
                        )
                        used.add(pioneer.unit_id)
                if pioneer.unit_id not in used:
                    logistics = plan_upgrade_or_repair(turn, pioneer, budget)
                    if logistics.action is not None:
                        actions.append(logistics.action)
                        used.add(pioneer.unit_id)
                    elif logistics.move is not None:
                        intents.append(logistics.move)
                        used.add(pioneer.unit_id)

            treasure_prompt = ""
            if (
                pioneer is not None
                and pioneer.unit_id not in used
                and not turn.phase_task
                and self.treasure.position is None
                and state.folk_legend_history
                and not advanced.prompt
                and self.treasure_prompt_day != turn.day_index
                and llm_budget.can_call(task_active=False)
            ):
                legends = "\n".join(text for _, text in state.folk_legend_history)[-6000:]
                treasure_prompt = (
                    "Infer treasure evidence from these legends. Return strict JSON only: "
                    '{"treasure":{"x":0,"y":0,"day":1,"items":[],"confidence":0.0}}. '
                    "Use confidence below 0.95 when any location, day, item, or quantity is uncertain. "
                    f"Legends: {legends}"
                )
                llm_budget.mark_requested(task_active=False, round_no=turn.round_no)
                self.treasure_prompt_day = turn.day_index
                self.treasure_prompt_pending = True

            for worker in workers:
                if worker.unit_id not in used:
                    self._plan_worker_economy(turn, worker, actions, intents, used)

        move_actions = schedule_moves(turn, intents)
        actions.extend(action for action in move_actions if action.actor_id not in {item.actor_id for item in actions})
        prompt = (advanced.prompt or treasure_prompt) if not recall else ""
        execute = advanced.execute_command if not recall else ""
        return Decision(tuple(actions), prompt=prompt, execute_command=execute)

    def _night(
        self,
        turn: Turn,
        state: WorldState,
        llm_budget: LlmBudget,
        config: StrategyConfig,
        mode: StrategyMode,
        threats: tuple,
    ) -> Decision:
        weapons = existing_weapons(turn)
        combat_weapons = tuple(
            weapon
            for weapon in weapons
            if weapon.role_type != "rocket" or weapon.cooldown <= 0
        )
        assignments = assign_controllers(turn, combat_weapons)
        assignments = tuple(
            sorted(
                assignments,
                key=lambda assignment: (
                    0
                    if assignment.weapon.pos is not None
                    and any(
                        robot.pos is not None
                        and assignment.weapon.pos.distance_to(robot.pos)
                        <= assignment.weapon.attack_range
                        for robot in threats
                    )
                    else 1,
                    -max(assignment.weapon.attack_power, 10),
                    assignment.weapon.unit_id,
                ),
            )
        )
        needed = controllers_needed(combat_weapons, threats)
        active_assignments = assignments[:needed]
        attack_targets = threats
        if not attack_targets and config.allow_cross_map_fire and mode == StrategyMode.SCORE_RACE:
            attack_targets = tuple(
                robot for robot in turn.robots
                if robot.health > 0
                and robot.target_team
                and robot.target_team != turn.team_our.team_type
            )
            active_assignments = assignments[: min(len(assignments), 1 if attack_targets else 0)]

        actions = list(plan_attacks(turn, active_assignments, attack_targets))
        used_controllers = {
            action.controller_id for action in actions if action.controller_id is not None
        }
        intents: list[MoveIntent] = []
        for assignment in active_assignments:
            if assignment.controller.unit_id in used_controllers:
                continue
            if assignment.weapon.pos is None or assignment.controller.pos is None:
                continue
            if assignment.controller.pos.distance_to(assignment.weapon.pos) > 1:
                intents.append(
                    MoveIntent(
                        assignment.controller.unit_id,
                        self._interaction_goals(turn, assignment.controller, assignment.weapon.pos),
                        priority=120,
                    )
                )
                used_controllers.add(assignment.controller.unit_id)
            elif attack_targets:
                # A controller stays assigned while a relevant threat exists even
                # before that threat enters range.
                used_controllers.add(assignment.controller.unit_id)

        released = [
            role for role in turn.controllable
            if role.unit_id not in used_controllers
        ]
        advanced = AdvancedPlan()
        if (
            config.allow_unverified_night_economy
            and not state.night_economy_disabled
            and len(active_assignments) < len(assignments)
        ):
            pioneer = next((role for role in released if role.role_type == ROLE_PIONEER), None)
            if pioneer is not None:
                advanced = self._safe_task_plan(
                    turn,
                    state,
                    llm_budget,
                    config,
                    pioneer,
                )
                self._merge_advanced(advanced, actions, intents, used_controllers)
            for worker in released:
                if worker.role_type == ROLE_WORKER and worker.unit_id not in used_controllers:
                    self._plan_worker_economy(turn, worker, actions, intents, used_controllers)

        moves = schedule_moves(turn, intents)
        actions.extend(action for action in moves if action.actor_id not in {item.actor_id for item in actions})
        return Decision(tuple(actions), advanced.prompt, advanced.execute_command)

    def _basic_defense(self, turn: Turn, threats: tuple) -> Decision:
        if turn.is_day or not threats:
            return Decision()
        assignments = assign_controllers(turn, existing_weapons(turn))
        actions = plan_attacks(turn, assignments, threats)
        return Decision(actions)

    def _safe_task_plan(
        self,
        turn: Turn,
        state: WorldState,
        llm_budget: LlmBudget,
        config: StrategyConfig,
        pioneer: Unit,
    ) -> AdvancedPlan:
        try:
            return self.tasks.plan(turn, state, llm_budget, config, pioneer)
        except Exception as error:
            LOGGER.warning("task planner degraded safely (%s)", type(error).__name__)
            return AdvancedPlan()

    @staticmethod
    def _merge_advanced(
        plan: AdvancedPlan,
        actions: list[Action],
        intents: list[MoveIntent],
        used: set[int],
    ) -> None:
        if plan.action is not None and plan.action.actor_id not in used:
            actions.append(plan.action)
            used.add(plan.action.actor_id)
        if plan.move is not None and plan.move.actor_id not in used:
            intents.append(plan.move)
            used.add(plan.move.actor_id)

    def _boss_plan(
        self,
        turn: Turn,
        pioneer: Unit,
        mode: StrategyMode,
        budget: DefenseBudget,
        config: StrategyConfig,
    ) -> AdvancedPlan:
        if mode not in {StrategyMode.PRESSURE, StrategyMode.FINISH}:
            return AdvancedPlan()
        if config.boss_summon_item in pioneer.backpack:
            return AdvancedPlan(
                action=Action(pioneer.unit_id, ActionType.USE, name=config.boss_summon_item)
            )
        quantity = desired_boss_orders(turn, budget, self.opponent, config)
        if quantity <= 0 or pioneer.pos is None:
            return AdvancedPlan()
        shops = turn.zone_positions("weaponShop")
        if any(pioneer.pos.distance_to(shop) <= 1 for shop in shops):
            return AdvancedPlan(
                action=Action(
                    pioneer.unit_id,
                    ActionType.BUY,
                    name=config.boss_summon_item,
                    quantity=quantity,
                )
            )
        goals = tuple(goal for shop in shops for goal in shop.neighbours())
        return AdvancedPlan(move=MoveIntent(pioneer.unit_id, goals, priority=55))

    def _plan_worker_economy(
        self,
        turn: Turn,
        worker: Unit,
        actions: list[Action],
        intents: list[MoveIntent],
        used: set[int],
    ) -> None:
        if worker.pos is None:
            return
        inventory = resource_inventory(worker)
        vendors = turn.zone_positions("vendor")
        should_sell = bool(inventory) and (
            backpack_full(worker)
            or any(name != "stone" for name in inventory)
            or inventory["stone"] >= 8
        )
        if should_sell:
            if any(worker.pos.distance_to(vendor) <= 1 for vendor in vendors):
                name = max(
                    inventory,
                    key=lambda item: (
                        next(
                            (
                                entry.price
                                for entry in turn.vendor_shop
                                if entry.name == item
                            ),
                            0,
                        ),
                        inventory[item],
                        item,
                    ),
                )
                actions.append(
                    Action(worker.unit_id, ActionType.SELL, name=name, quantity=inventory[name])
                )
            else:
                goals = tuple(goal for vendor in vendors for goal in vendor.neighbours())
                intents.append(MoveIntent(worker.unit_id, goals, priority=35))
            used.add(worker.unit_id)
            return
        resource = best_resource(turn, worker)
        if resource is None or resource.pos is None:
            return
        if worker.pos.distance_to(resource.pos) <= 1:
            actions.append(
                Action(worker.unit_id, ActionType.COLLECT, targets=(resource.pos,))
            )
        else:
            intents.append(
                MoveIntent(
                    worker.unit_id,
                    self._interaction_goals(turn, worker, resource.pos),
                    priority=30,
                )
            )
        used.add(worker.unit_id)

    @staticmethod
    def _interaction_goals(turn: Turn, role: Unit, target) -> tuple:
        grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=(role.unit_id,))
        return interaction_cells(grid, target)

    @staticmethod
    def _controller_intents(turn: Turn, priority: int) -> list[MoveIntent]:
        result: list[MoveIntent] = []
        for assignment in assign_controllers(turn, existing_weapons(turn)):
            if assignment.weapon.pos is None or assignment.controller.pos is None:
                continue
            if assignment.controller.pos.distance_to(assignment.weapon.pos) <= 1:
                continue
            grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=(assignment.controller.unit_id,))
            goals = interaction_cells(grid, assignment.weapon.pos)
            result.append(MoveIntent(assignment.controller.unit_id, goals, priority))
        return result

    @staticmethod
    def _recall_needed(turn: Turn, layout, config: StrategyConfig) -> bool:
        if not turn.is_day or turn.rounds_until_night <= 0:
            return False
        weapons = existing_weapons(turn)
        if weapons:
            distances = []
            for role in turn.controllable:
                if role.pos is None:
                    continue
                nearest = min(
                    (role.pos.distance_to(weapon.pos) for weapon in weapons if weapon.pos is not None),
                    default=0,
                )
                distances.append(nearest)
            return bool(distances) and max(distances) + config.recall_safety_buffer >= turn.rounds_until_night
        station = turn.team_our.station()
        if station is None or station.pos is None:
            return False
        max_distance = max(
            (role.pos.distance_to(station.pos) for role in turn.controllable if role.pos is not None),
            default=0,
        )
        return max_distance + config.recall_safety_buffer >= turn.rounds_until_night
