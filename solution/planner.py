from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Callable

from .actions import Action, ActionType, Decision
from .combat import assign_controllers, plan_attacks
from .defense import (
    build_defense_layout,
    estimated_contact_turns,
    existing_weapons,
    existing_walls,
    own_threats,
)
from .economy import (
    DefenseBudget,
    EconomyManager,
    defense_budget,
    wall_build_objective,
    weapon_build_objectives,
)
from .grid import OccupancyGrid, distance_field, interaction_cells, shortest_path
from .logistics import plan_upgrade_or_repair, LogisticsManager, plan_repair_stock
from .models import Turn, Unit
from .movement import MoveIntent, schedule_moves
from .opponent import OpponentModel, StrategyMode, choose_mode, desired_boss_orders
from .rules import ROLE_PIONEER, ROLE_WORKER, ROUNDS_PER_DAY, StrategyConfig
from .state import LlmBudget, WorldState
from .travel import TravelBudget
from .maintenance import support_plan
from .tasking import AdvancedPlan, TaskManager, TreasureKnowledge, parse_structured_llm


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class CompetitionPlanner:
    opponent: OpponentModel = field(default_factory=OpponentModel)
    tasks: TaskManager = field(default_factory=TaskManager)
    treasure: TreasureKnowledge = field(default_factory=TreasureKnowledge)
    last_generation: int = -1
    treasure_prompt_day: int = -1
    treasure_prompt_pending: bool = False
    treasure_prompt_round: int = 0
    news_prompt_source: str = ""
    news_prompt_day: int = 0
    interpreted_news: str = ""
    economy: EconomyManager = field(default_factory=EconomyManager)
    logistics: LogisticsManager = field(default_factory=LogisticsManager)
    engineer_id: int | None = None
    stone_batch_goal: int = 0
    failure_count: int = 0

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
            self.economy = EconomyManager()
            self.logistics = LogisticsManager()
            self.engineer_id = None
            self.stone_batch_goal = 0
            self.failure_count = 0
            self.news_prompt_source = self.interpreted_news = ""
        if self.treasure_prompt_pending and turn.llm_response:
            parsed = parse_structured_llm(turn.llm_response)
            background = (parsed is not None and any(k in parsed for k in ("market", "treasure"))
                          and not any(k in parsed for k in ("answer", "command", "script", "procedure")))
            if background:
                self.treasure.ingest_llm(turn.llm_response, {max(r-1,0)//ROUNDS_PER_DAY+1 for r,_ in state.folk_legend_history})
                state.market.ingest_interpretation(parsed.get("market"),self.news_prompt_source,self.news_prompt_day)
                self.interpreted_news = self.news_prompt_source
                turn = replace(turn, llm_response="")
            self.treasure_prompt_pending = False
        elif self.treasure_prompt_pending and turn.round_no-self.treasure_prompt_round > config.task_response_wait:
            self.treasure_prompt_pending = False
        self.economy.activity.clear()
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
                decision = self._night(turn, state, llm_budget, config, mode, threats, budget)
        except Exception as error:
            self.failure_count += 1
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
        if workers and self.engineer_id not in {w.unit_id for w in workers}:
            self.engineer_id = min(workers, key=lambda w: (min((w.pos.distance_to(p) for p in layout.weapon_sites[:3]), default=0),w.unit_id)).unit_id
        pioneer = next(
            (unit for unit in turn.team_our.units_of_type(ROLE_PIONEER) if unit.alive),
            None,
        )

        advanced = AdvancedPlan()
        treasure_prompt = ""
        recall_intents = self._individual_recall(turn, state, config)
        # A return reservation must not suppress a one-turn adjacent delivery.
        for intent in tuple(recall_intents):
            role=turn.team_our.unit(intent.actor_id)
            if TravelBudget.for_role(turn,role,config).cost()+1 >= turn.rounds_until_night:
                continue
            maintenance=plan_upgrade_or_repair(turn,role,budget,config,allow_move=False,owned_only=True)
            if maintenance.action is not None:
                actions.append(maintenance.action)
                recall_intents.remove(intent)
                used.add(role.unit_id)
        intents.extend(recall_intents)
        used.update(i.actor_id for i in recall_intents)
        if len(used) < len(turn.controllable):
            # Deliver carried goods before assigning the engineer another mining trip.
            for worker in workers:
                if worker.unit_id in used:
                    continue
                if self.logistics.carrier_id == worker.unit_id or any(
                    item == "WallFixer" or "UpgradeVoucher" in item for item in worker.backpack
                ):
                    delivery = self.logistics.plan(turn, worker, budget, config)
                    self._merge_advanced(delivery, actions, intents, used)
            objectives = weapon_build_objectives(turn, layout, state, config)
            builders = [worker for worker in workers if worker.unit_id == self.engineer_id and worker.unit_id not in used]
            objectives = sorted(objectives, key=lambda o: min((w.pos.distance_to(o.site) for w in builders), default=0))
            for objective in objectives:
                if not builders:
                    break
                worker = min(builders, key=lambda role: (role.pos.distance_to(objective.site), role.unit_id))
                builders.remove(worker)
                if worker.pos is None:
                    continue
                occupant = next((r for r in turn.controllable if r.pos == objective.site), None)
                if occupant is not None and occupant.unit_id != worker.unit_id and not (occupant.role_type == ROLE_PIONEER and turn.phase_task):
                    grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=(occupant.unit_id,))
                    free = tuple(p for p in grid.neighbours(occupant.pos) if p not in layout.weapon_sites[:3])
                    if free:
                        intents.append(MoveIntent(occupant.unit_id, free, 105))
                        used.add(occupant.unit_id)
                if worker.pos.distance_to(objective.site) <= 1 and worker.pos != objective.site and occupant is None:
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
                if len(workers) > 1 and worker.unit_id != self.engineer_id:
                    continue
                # Ring walls require stone, not whichever ore currently sells best.
                # Reserve a complete batch before walking back from the mine.
                wall_count = len(existing_walls(turn))
                wall_target = min(len(layout.wall_sites), config.max_wall_count)
                stones = worker.backpack.count("stone")
                desired_batch = config.stone_batch_size
                batch = min(desired_batch, max(0, wall_target - wall_count), worker.backpack_capacity)
                if stones == 0 and wall_count < wall_target:
                    self.stone_batch_goal = batch
                self.stone_batch_goal = min(self.stone_batch_goal, max(0, wall_target-wall_count))
                if stones >= self.stone_batch_goal:
                    self.stone_batch_goal = 0
                if wall_count < wall_target and self.stone_batch_goal:
                    grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
                    distances = distance_field(grid, (worker.pos,))
                    stone_zones = [z for z in turn.map_info.zones if z.neutral_type == "stone" and z.pos is not None
                                   and (not config.local_mining_only or layout.frame.normalize(z.pos).x <= (turn.map_info.width-1)//2)
                                   and not state.market.closed("stone", turn.day_index)]
                    def mine_distance(zone):
                        return min((distances.get(p, 10000) for p in interaction_cells(grid, zone.pos)), default=10000)
                    stone = min((z for z in stone_zones if mine_distance(z) < 10000), key=mine_distance, default=None)
                    near_mine = stone is not None and worker.pos.distance_to(stone.pos) <= 1
                    # A depleted mine must not silently cancel an unfinished batch.
                    # Abandon the batch only when travel, collection and building
                    # would run into recall; spend carried stone immediately then.
                    work_left = self.stone_batch_goal-stones
                    enough_time = stone is not None and turn.rounds_until_night > mine_distance(stone)+work_left+self.stone_batch_goal+config.recall_safety_buffer+8
                    if stone is not None and (stones == 0 or enough_time):
                        if near_mine:
                            actions.append(Action(worker.unit_id, ActionType.COLLECT, targets=(stone.pos,)))
                        else:
                            intents.append(MoveIntent(worker.unit_id, self._interaction_goals(turn, worker, stone.pos), 80))
                        used.add(worker.unit_id)
                        continue
                    self.stone_batch_goal = 0
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
            if pioneer is not None and pioneer.unit_id not in used and not turn.phase_task and turn.day_index>=2:
                purchase=plan_repair_stock(turn,pioneer,budget,config)
                if purchase.action is None and purchase.move is None:
                    purchase=self.logistics.plan(turn,pioneer,budget,config)
                self._merge_advanced(purchase,actions,intents,used)
            if pioneer is not None and pioneer.unit_id not in used:
                advanced = self._safe_task_plan(
                    turn,
                    state,
                    llm_budget,
                    config,
                    pioneer,
                )
                self._merge_advanced(advanced, actions, intents, used)
                if turn.phase_task or advanced.prompt or advanced.execute_command:
                    used.add(pioneer.unit_id)
                if pioneer.unit_id not in used:
                    boss_plan = self._boss_plan(turn, pioneer, mode, budget, config)
                    self._merge_advanced(boss_plan, actions, intents, used)
                if pioneer.unit_id not in used:
                    treasure_plan = self.treasure.plan(turn, pioneer, config, budget.offensive)
                    self._merge_advanced(treasure_plan, actions, intents, used)
                if (pioneer.unit_id not in used and (
                    not any(t.is_valid for t in turn.team_our.player_tasks)
                    or not any(w.unit_id != self.engineer_id for w in workers)
                    or self.logistics.carrier_id == pioneer.unit_id
                )):
                    logistics = self.logistics.plan(turn, pioneer, budget, config)
                    if logistics.action is not None:
                        actions.append(logistics.action)
                        used.add(pioneer.unit_id)
                    elif logistics.move is not None:
                        intents.append(logistics.move)
                        used.add(pioneer.unit_id)
                if pioneer.unit_id not in used:
                    self._stage_idle_pioneer(turn,pioneer,config,intents,used)

            treasure_prompt = ""
            latest_news = state.official_news_history[-1] if state.official_news_history else (0, "")
            if (
                pioneer is not None
                and not turn.phase_task
                and not (advanced.action and advanced.action.action_type == ActionType.ACCEPT_TASK)
                and ((not self.treasure.exhausted and self.treasure.confidence < config.treasure_confidence_threshold and state.folk_legend_history)
                     or (latest_news[1] and latest_news[1] != self.interpreted_news))
                and not self.treasure_prompt_pending
                and not advanced.prompt
                and self.treasure_prompt_day != turn.day_index
                and llm_budget.can_call(task_active=False)
            ):
                legends = "\n".join(f"day {max(r-1,0)//ROUNDS_PER_DAY+1}: {text}" for r, text in state.folk_legend_history)[-8000:]
                treasure_prompt = (
                    "Interpret official market news separately from folk treasure clues. Return strict JSON only: "
                    '{"market":[{"ore":"iron","start_day":1,"end_day":1,"closed":false,"rising":false,"price":null,"evidence":"exact source quote","confidence":0.0}],'
                    '"treasure":{"x":0,"y":0,"day":1,"end_day":10,"phase":"any","items":[],"evidence_days":[],"confidence":0.0}}. '
                    "Never infer a fixed day from earlier matches. Resolve relative dates against the source day. "
                    "For narrative closures or price rises cite the actual supporting span; leave unsupported entries empty. "
                    "Use confidence below 0.95 when any location, day, item, or quantity is uncertain. "
                    f"Official source day {max(latest_news[0]-1,0)//ROUNDS_PER_DAY+1}: {latest_news[1][:6000]}\n"
                    f"Legends: {legends}"
                )
                llm_budget.mark_requested(task_active=False, round_no=turn.round_no)
                self.treasure_prompt_day = turn.day_index
                self.treasure_prompt_pending = True
                self.treasure_prompt_round = turn.round_no
                self.news_prompt_source = latest_news[1]
                self.news_prompt_day = max(latest_news[0]-1,0)//ROUNDS_PER_DAY+1

            shop_grid=OccupancyGrid.from_turn(turn,ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
            shop_goals=tuple(p for shop in turn.zone_positions('weaponShop') for p in interaction_cells(shop_grid,shop))
            shop_dist=distance_field(shop_grid,shop_goals) if shop_goals else {}
            for worker in sorted(workers,key=lambda w:shop_dist.get(w.pos,10000)):
                if worker.unit_id not in used:
                    logistics = self.logistics.plan(turn, worker, budget, config)
                    if logistics.action is not None:
                        actions.append(logistics.action)
                        used.add(worker.unit_id)
                    elif logistics.move is not None:
                        intents.append(logistics.move)
                        used.add(worker.unit_id)
                    if worker.unit_id in used:
                        continue
                    self._plan_worker_economy(turn, worker, actions, intents, used, state, config, budget)

        build_cells = tuple(target for action in actions if action.action_type == ActionType.BUILD for target in action.targets)
        for role in turn.controllable:
            if role.unit_id not in used and role.pos is not None:
                intents.append(MoveIntent(role.unit_id,(role.pos,),0))
        move_actions = schedule_moves(turn, intents, occupied_destinations=build_cells)
        actions.extend(action for action in move_actions if action.actor_id not in {item.actor_id for item in actions})
        prompt = advanced.prompt or treasure_prompt
        execute = advanced.execute_command
        return Decision(tuple(actions), prompt=prompt, execute_command=execute)

    def _night(
        self,
        turn: Turn,
        state: WorldState,
        llm_budget: LlmBudget,
        config: StrategyConfig,
        mode: StrategyMode,
        threats: tuple,
        budget: DefenseBudget,
    ) -> Decision:
        weapons = existing_weapons(turn)
        # Keep cooling launchers assigned: otherwise their operators leave to mine
        # and cannot fire when cooldown expires. Release after our wave is clear.
        combat_weapons = weapons
        assignments = assign_controllers(turn, combat_weapons,config)
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
        shared_control=len({a.controller.unit_id for a in assignments})<len(assignments)
        needed = len(assignments) if threats else 0
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

        actions=[]
        upgrading=set();upgraded_targets=set()
        min_level=min((w.level for w in weapons),default=3)
        for role in turn.controllable:
            adjacent=sorted((w for w in weapons if role.pos and w.pos and role.pos.distance_to(w.pos)<=1 and w.level==min_level and w.level<3 and w.unit_id not in upgraded_targets),key=lambda w:w.unit_id)
            for weapon in adjacent:
                item=f'WeaponUpgradeVoucher{weapon.level}'
                if item in role.backpack:
                    actions.append(Action(role.unit_id,ActionType.USE,name=item,targets=(weapon.pos,)))
                    upgrading.add(role.unit_id);upgraded_targets.add(weapon.unit_id);break
        actions.extend(plan_attacks(turn,tuple(a for a in active_assignments if a.controller.unit_id not in upgrading),attack_targets))
        used_controllers = {action.controller_id for action in actions if action.controller_id is not None} | upgrading
        intents: list[MoveIntent] = []
        for assignment in active_assignments:
            if assignment.controller.unit_id in used_controllers:
                continue
            if assignment.weapon.pos is None or assignment.controller.pos is None:
                continue
            if (shared_control and assignment.control_pos is not None and assignment.controller.pos!=assignment.control_pos) or assignment.controller.pos.distance_to(assignment.weapon.pos) > 1:
                intents.append(
                    MoveIntent(
                        assignment.controller.unit_id,
                        (assignment.control_pos,) if assignment.control_pos else self._interaction_goals(turn, assignment.controller, assignment.weapon.pos),
                        priority=120,
                    )
                )
                used_controllers.add(assignment.controller.unit_id)
            elif attack_targets:
                # A controller stays assigned while a relevant threat exists even
                # before that threat enters range.
                used_controllers.add(assignment.controller.unit_id)
                # Cooling/idle operators may yield within the joint move scheduler;
                # firing operators are absent from intents and cannot be borrowed.
                intents.append(MoveIntent(assignment.controller.unit_id,(assignment.controller.pos,),115,
                                          yield_cells=assignment.weapon.pos.neighbours()))

        # An idle operator may use carried maintenance items without leaving control.
        # An available shot always takes priority over this maintenance action.
        firing_controllers={a.controller_id for a in actions if a.action_type==ActionType.ATTACK}
        for assignment in active_assignments:
            if assignment.controller.unit_id in firing_controllers or assignment.controller.unit_id in upgrading:
                continue
            role = assignment.controller
            if role.pos is None or role.pos.distance_to(assignment.weapon.pos)>1:
                continue
            if any(intent.actor_id == role.unit_id and role.pos not in intent.goals for intent in intents):
                continue
            maintenance = plan_upgrade_or_repair(turn, role, budget, config,
                                                 allow_move=False, critical_only=False)
            if maintenance.action is not None and maintenance.action.action_type == ActionType.USE:
                actions.append(maintenance.action)
                intents = [intent for intent in intents if intent.actor_id != role.unit_id]
                break
            if assignment.weapon.cooldown >= 2 and role.pos is not None:
                grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=(role.unit_id,))
                for cell in grid.neighbours(role.pos):
                    if cell.distance_to(assignment.weapon.pos) > 1:
                        continue
                    if any(robot.pos and cell.distance_to(robot.pos) <= robot.attack_range for robot in threats):
                        continue
                    shifted = plan_upgrade_or_repair(turn, replace(role,pos=cell), budget, config,
                                                     allow_move=False, critical_only=False)
                    if shifted.action is not None and shifted.action.action_type == ActionType.USE:
                        intents = [intent for intent in intents if intent.actor_id != role.unit_id]
                        intents.append(MoveIntent(role.unit_id,(cell,),125,yield_cells=assignment.weapon.pos.neighbours()))
                        break

        released = [
            role for role in turn.controllable
            if role.unit_id not in used_controllers
        ]
        advanced = AdvancedPlan()
        if (
            config.allow_unverified_night_economy
            and not state.night_economy_disabled
            and released
        ):
            # Reserve an active task before assigning a cleared-wave shopping trip.
            pioneer = next((role for role in released if role.role_type == ROLE_PIONEER and not threats), None)
            if pioneer is not None:
                advanced = self._safe_task_plan(turn, state, llm_budget, config, pioneer)
                self._merge_advanced(advanced, actions, intents, used_controllers)
                if turn.phase_task or advanced.prompt or advanced.execute_command:
                    used_controllers.add(pioneer.unit_id)
                if pioneer.unit_id not in used_controllers:
                    treasure = self.treasure.plan(turn, pioneer, config, budget.offensive)
                    self._merge_advanced(treasure, actions, intents, used_controllers)
            for role in released:
                if turn.day_index>=config.night_support_day and threats and role.unit_id not in used_controllers:
                    support=support_plan(turn,role,config,threats)
                    self._merge_advanced(support,actions,intents,used_controllers)
            for role in sorted(released,key=lambda r:r.role_type!=ROLE_PIONEER):
                if role.unit_id in used_controllers:
                    continue
                maintenance = (plan_upgrade_or_repair(turn, role, budget, config, allow_move=False, critical_only=True)
                               if threats else self.logistics.plan(turn, role, budget, config))
                if maintenance.action is not None:
                    actions.append(maintenance.action)
                    used_controllers.add(role.unit_id)
                    continue
                if maintenance.move is not None:
                    intents.append(maintenance.move)
                    used_controllers.add(role.unit_id)
                    continue
            if pioneer is not None and pioneer.unit_id not in used_controllers:
                self._stage_idle_pioneer(turn,pioneer,config,intents,used_controllers)
            for worker in released:
                if (not threats or turn.day_index<config.night_support_day) and worker.role_type == ROLE_WORKER and worker.unit_id not in used_controllers:
                    self._plan_worker_economy(turn, worker, actions, intents, used_controllers, state, config, budget)

        moves = schedule_moves(turn, intents)
        actions.extend(action for action in moves if action.actor_id not in {item.actor_id for item in actions})
        return Decision(tuple(actions), advanced.prompt, advanced.execute_command)

    @staticmethod
    def _stage_idle_pioneer(turn, pioneer, config, intents, used):
        # Wait near the shop when no task is available, instead of blocking a gun
        # or forcing a productive miner to handle every future purchase.
        if turn.phase_task or any(t.is_valid for t in turn.team_our.player_tasks):
            return
        if not turn.weapon_shop or len(existing_weapons(turn))<config.max_weapon_count:
            return
        travel=TravelBudget.for_role(turn,pioneer,config)
        goals=tuple(p for shop in turn.zone_positions("weaponShop") for p in interaction_cells(travel.grid,shop))
        if not goals or not travel.fits(((goals,0),)):
            return
        next_task=min((t.cooldown_rounds for t in turn.team_our.player_tasks if t.cooldown_rounds>0),default=10000)
        if travel.cost(((goals,0),))+2>=next_task:
            return
        intents.append(MoveIntent(pioneer.unit_id,goals,20))
        used.add(pioneer.unit_id)

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
        if not config.allow_summon_pressure or mode not in {StrategyMode.PRESSURE, StrategyMode.FINISH}:
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
        self, turn: Turn, worker: Unit, actions: list[Action], intents: list[MoveIntent],
        used: set[int], state: WorldState, config: StrategyConfig, budget: DefenseBudget,
    ) -> None:
        plan = self.economy.plan(turn, worker, state, config, budget)
        if plan.action is not None:
            actions.append(plan.action)
        if plan.move is not None:
            intents.append(plan.move)
        if plan.action is not None or plan.move is not None:
            used.add(worker.unit_id)

    @staticmethod
    def _interaction_goals(turn: Turn, role: Unit, target) -> tuple:
        grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=(role.unit_id,))
        return interaction_cells(grid, target)

    @staticmethod
    def _controller_intents(turn: Turn, priority: int) -> list[MoveIntent]:
        result: list[MoveIntent] = []
        for assignment in assign_controllers(turn, existing_weapons(turn)):
            if any(i.actor_id==assignment.controller.unit_id for i in result):continue
            if assignment.weapon.pos is None or assignment.controller.pos is None:
                continue
            if assignment.control_pos is not None:
                # Fill the inner station before an outside operator holds the gate.
                frame = turn.coordinate_frame
                depth = frame.normalize(assignment.control_pos).x
                result.append(MoveIntent(assignment.controller.unit_id, (assignment.control_pos,), priority + depth))
                continue
            if assignment.controller.pos.distance_to(assignment.weapon.pos) <= 1:
                result.append(MoveIntent(assignment.controller.unit_id, (assignment.controller.pos,), priority))
                continue
            grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
            goals = interaction_cells(grid, assignment.weapon.pos)
            result.append(MoveIntent(assignment.controller.unit_id, goals, priority))
        return result

    @staticmethod
    def _individual_recall(turn: Turn, state: WorldState, config: StrategyConfig) -> list[MoveIntent]:
        state.recalled_roles = {actor: day for actor, day in state.recalled_roles.items() if day == turn.day_index}
        intents = CompetitionPlanner._controller_intents(turn, 120)
        grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
        assigned = {intent.actor_id for intent in intents}
        station = turn.team_our.station()
        if station is not None:
            home = tuple(dict.fromkeys(p for cell in station.footprint() for p in interaction_cells(grid,cell)))
            intents.extend(MoveIntent(role.unit_id,TravelBudget.for_role(turn,role,config).goals or home,110) for role in turn.controllable
                           if role.unit_id not in assigned and role.pos is not None and (turn.day_index>=config.night_support_day or role.role_type!=ROLE_WORKER or any(i.startswith('WeaponUpgradeVoucher') for i in role.backpack)))
        result = []
        for intent in intents:
            role = turn.team_our.unit(intent.actor_id)
            travel=TravelBudget.for_role(turn,role,config)
            distance=travel.cost()
            if not intent.goals:
                intent = replace(intent, goals=(role.pos,))
            # Static shortest paths omit queued humans and walls built en route.
            # Reserve a separate traffic allowance without recalling other roles.
            if (state.recall_day == turn.day_index or intent.actor_id in state.recalled_roles
                    or distance+travel.margin >= turn.rounds_until_night):
                state.recalled_roles[intent.actor_id] = turn.day_index
                result.append(intent)
        return result

    @staticmethod
    def _recall_needed(turn: Turn, layout, config: StrategyConfig) -> bool:
        if not turn.is_day or turn.rounds_until_night <= 0:
            return False
        weapons = existing_weapons(turn)
        if weapons:
            distances = []
            for assignment in assign_controllers(turn, weapons):
                role, weapon = assignment.controller, assignment.weapon
                if (assignment.control_pos is None and role.pos.distance_to(weapon.pos) <= 1) or role.pos == assignment.control_pos:
                    distances.append(0)
                    continue
                grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
                goals = (assignment.control_pos,) if assignment.control_pos is not None else interaction_cells(grid, weapon.pos)
                path = shortest_path(grid, role.pos, goals)
                # Buildings and held controllers can force long detours. A direct
                # distance underestimates the return time through the rear exit.
                distances.append(len(path)-1 if path else turn.rounds_until_night)
            return bool(distances) and max(distances) + config.recall_safety_buffer >= turn.rounds_until_night
        station = turn.team_our.station()
        if station is None or station.pos is None:
            return False
        max_distance = max(
            (role.pos.distance_to(station.pos) for role in turn.controllable if role.pos is not None),
            default=0,
        )
        return max_distance + config.recall_safety_buffer >= turn.rounds_until_night
