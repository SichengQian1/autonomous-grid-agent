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
    backpack_full,
    defense_budget,
    wall_build_objective,
    weapon_build_objectives,
)
from .grid import OccupancyGrid, distance_field, interaction_cells, shortest_path
from .logistics import plan_upgrade_or_repair, LogisticsManager
from .models import Turn, Unit
from .movement import MoveIntent, schedule_moves
from .opponent import OpponentModel, StrategyMode, choose_mode, desired_boss_orders
from .rules import ROLE_PIONEER, ROLE_WORKER, ROUNDS_PER_DAY, StrategyConfig
from .state import LlmBudget, WorldState
from .travel import TravelBudget
from .maintenance import support_plan
from .wall_supply import WallSupplyCycle
from .surplus_bomb import SurplusBomb
from .roles import GuardHandover, wall_goods
from .route_safety import danger_cells, escape_intent
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
    support_id: int | None = None
    guard: GuardHandover = field(default_factory=GuardHandover)
    failure_count: int = 0
    wall_supply_status: dict = field(default_factory=dict)
    wall_supply_cycle: WallSupplyCycle = field(default_factory=WallSupplyCycle)
    surplus_bomb: SurplusBomb = field(default_factory=SurplusBomb)
    support_health: tuple | None = None
    support_damage: int = 0
    raid_status: str = ''

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
            self.support_id = None
            self.guard = GuardHandover()
            self.surplus_bomb = SurplusBomb()
            self.wall_supply_cycle = WallSupplyCycle()
            self.support_health=None
            self.failure_count = 0
            self.news_prompt_source = self.interpreted_news = ""
        self.treasure.observe(turn,config)
        if self.treasure_prompt_pending and turn.llm_response:
            parsed = parse_structured_llm(turn.llm_response)
            background = (parsed is not None and any(k in parsed for k in ("market", "mode"))
                          and not any(k in parsed for k in ("answer", "command", "script", "procedure")))
            if background or not turn.phase_task:
                try:
                    accepted = self.treasure.ingest_llm(turn.llm_response)
                    if accepted and isinstance(parsed,dict):state.market.ingest_interpretation(parsed.get("market"),self.news_prompt_source,self.news_prompt_day)
                    self.interpreted_news = self.news_prompt_source
                except Exception as error:
                    self.treasure.fail('malformed_interpretation',error=type(error).__name__)
                    self.treasure.analyzed_version=self.treasure.request_version
                    self.treasure.emit('validation',reason=self.treasure.reason,error=type(error).__name__)
                    self.interpreted_news = self.news_prompt_source
                turn = replace(turn, llm_response="")
            self.treasure_prompt_pending = False
        elif self.treasure_prompt_pending and turn.round_no-self.treasure_prompt_round > config.task_response_wait:
            self.treasure.fail('model_response_timeout')
            self.treasure.analyzed_version=self.treasure.request_version
            self.treasure.retry_analysis()
            self.treasure_prompt_pending = False
        workers=[r for r in turn.controllable if r.role_type==ROLE_WORKER and r.pos]
        if workers and self.engineer_id not in {w.unit_id for w in workers}:
            sites=build_defense_layout(turn).weapon_sites[:3]
            self.engineer_id=min(workers,key=lambda w:(-wall_goods(w),min((w.pos.distance_to(p) for p in sites),default=0),w.unit_id)).unit_id
        self.support_id=self.engineer_id if workers else None
        support=turn.team_our.unit(self.support_id)
        self.support_damage=max(0,self.support_health[1]-support.health) if support and self.support_health and self.support_health[0]==support.unit_id else 0
        self.support_health=(support.unit_id,support.health) if support else None
        self.logistics.support_id=self.support_id
        pioneer=next((r for r in turn.controllable if r.role_type==ROLE_PIONEER),None)
        self.logistics.weapon_buyer_id=(self.guard.backup_id if self.guard.away or pioneer is None else pioneer.unit_id)
        self.economy.main_miner_id=next((w.unit_id for w in workers if w.unit_id!=self.engineer_id),None)
        self.economy.returning_roles={self.support_id} if turn.day_index>=config.night_support_day else set()
        if turn.day_index>=config.final_defense_day and self.economy.main_miner_id is not None:
            self.economy.returning_roles.add(self.economy.main_miner_id)
        self.economy.reserve_stone={self.engineer_id:config.engineer_stone_reserve}
        self.wall_supply_status={}
        self.surplus_bomb.observe(turn)
        self.surplus_bomb.status={'reason':'engineer_busy_or_not_due'}
        self.economy.activity.clear()
        self.economy.evidence.clear()
        self.opponent.update(turn, state.generation)
        if self.treasure.pending_round and turn.round_no==self.treasure.pending_round+1:
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
        # Shared money must also be consistent in the proposed joint plan, not
        # merely dropped later by the protocol validator.
        cash=turn.team_our.gold;prices={i.name:i.price for i in turn.weapon_shop};funded=[]
        for action in decision.actions:
            cost=prices.get(action.name,0)*(action.quantity or 0) if action.action_type==ActionType.BUY else config.weapon_build_cost if action.action_type==ActionType.BUILD and action.name!='wall' else 0
            if cost>cash:
                self.economy.activity[action.actor_id]='purchase_deferred_shared_cash'
                continue
            cash-=cost;funded.append(action)
        decision=replace(decision,actions=tuple(funded))
        self.economy.previous_robots={r.robot_id:r.pos for r in turn.robots if r.pos}
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
        guard_ready=False
        expedition=bool(pioneer and self.treasure.departure_due(turn,pioneer,config))
        prepare_guard=False
        if pioneer and self.treasure.preceding_night(turn,pioneer):
            miner=turn.team_our.unit(self.economy.main_miner_id)
            if miner:
                grid=OccupancyGrid.from_turn(turn,ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
                path=shortest_path(grid,miner.pos,layout.controller_sites[:1])
                # Includes approaching, vacating and entering the common post.
                prepare_guard=self.guard.away or bool(path and turn.rounds_until_night<=len(path)-1+4)
        long_trip=False
        if expedition:
            trip=TravelBudget.for_role(turn,pioneer,config)
            goals=interaction_cells(trip.grid,self.treasure.position)
            long_trip=not trip.fits(((goals,1),)) or (self.treasure.phase=='night' and self.treasure.opening_day==turn.day_index)
        if prepare_guard or expedition and (long_trip or self.guard.away):
            assignments,handover,guard_ready=self.guard.coordinate(turn,existing_weapons(turn),config,True,preferred_backup=self.economy.main_miner_id)
            intents.extend(handover);used.update(i.actor_id for i in handover)
            if guard_ready:
                backup=turn.team_our.unit(self.guard.backup_id)
                intents.append(MoveIntent(backup.unit_id,(backup.pos,),125,yield_cells=()))
                used.add(backup.unit_id)
        support=next((w for w in workers if w.unit_id==self.support_id and w.unit_id not in used),None)
        if support and len(existing_weapons(turn))>=3:
            stock=self.wall_supply_cycle.plan(turn,support,budget,config)
            self.wall_supply_status={"reason":stock.reason,"needs_and_route":stock.evidence}
            self.economy.activity[support.unit_id]=stock.reason
            self.economy.evidence[support.unit_id]={"supply":stock.evidence}
            if stock.reason=='wall_cycle_return' and any(support.pos.distance_to(p)<=1 for p in turn.zone_positions('weaponShop')):
                bomb=self.surplus_bomb.plan(turn,support,support,budget,config)
                if bomb.action:
                    stock=bomb
                    self.economy.activity[support.unit_id]=bomb.reason
            self._merge_advanced(stock,actions,intents,used)
            if support.unit_id not in used:
                bomb=self.surplus_bomb.plan(turn,support,support,budget,config)
                self._merge_advanced(bomb,actions,intents,used)
                if bomb.action or bomb.move:self.economy.activity[support.unit_id]=bomb.reason
        helper=next((w for w in workers if w.unit_id==self.economy.main_miner_id and w.unit_id not in used),None)
        if helper:
            stock=self.wall_supply_cycle.plan(turn,helper,budget,config,helper=True,engineer=turn.team_our.unit(self.support_id))
            self._merge_advanced(stock,actions,intents,used)
            if stock.action or stock.move:self.economy.activity[helper.unit_id]=stock.reason
        recall_intents = self._individual_recall(turn, state, config, self.support_id)
        if guard_ready:
            recall_intents=[i for i in recall_intents if i.actor_id!=pioneer.unit_id]
        recall_intents=[i for i in recall_intents if i.actor_id not in used]
        # A return reservation must not suppress a one-turn adjacent delivery.
        for intent in tuple(recall_intents):
            role=turn.team_our.unit(intent.actor_id)
            if TravelBudget.for_role(turn,role,config).cost()+1 > turn.rounds_until_night:
                continue
            maintenance=plan_upgrade_or_repair(turn,role,budget,config,allow_move=False,owned_only=True)
            if maintenance.action is not None:
                actions.append(maintenance.action)
                recall_intents.remove(intent)
                used.add(role.unit_id)
        intents.extend(recall_intents)
        used.update(i.actor_id for i in recall_intents)
        if len(used) < len(turn.controllable):
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
                replenishing=wall_count>=wall_target and stones<config.engineer_stone_reserve
                if replenishing:self.stone_batch_goal=config.engineer_stone_reserve
                if (wall_count < wall_target or replenishing) and self.stone_batch_goal:
                    grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
                    distances = distance_field(grid, (worker.pos,))
                    stone_zones = [z for z in turn.map_info.zones if z.neutral_type == "stone" and z.pos is not None
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
                    if stone is not None and (stones == 0 or enough_time) and not backpack_full(worker):
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
            if pioneer is not None and pioneer.unit_id not in used and not turn.phase_task:
                treasure_plan=self.treasure.plan(turn,pioneer,config,budget.offensive,guard_ready=guard_ready)
                self._merge_advanced(treasure_plan,actions,intents,used)
            if pioneer is not None and pioneer.unit_id not in used and not turn.phase_task and (turn.day_index>=2 or turn.rounds_until_night<=config.procurement_lead_rounds):
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

            treasure_prompt=self._background_prompt(turn,state,llm_budget,advanced)

            shop_grid=OccupancyGrid.from_turn(turn,ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
            shop_goals=tuple(p for shop in turn.zone_positions('weaponShop') for p in interaction_cells(shop_grid,shop))
            shop_dist=distance_field(shop_grid,shop_goals) if shop_goals else {}
            for worker in sorted(workers,key=lambda w:shop_dist.get(w.pos,10000)):
                if worker.unit_id not in used:
                    logistics = self.wall_supply_cycle.plan(turn,worker,budget,config) if worker.unit_id==self.support_id else AdvancedPlan()
                    if worker.unit_id==self.support_id:
                        self.wall_supply_status={"reason":getattr(logistics,"reason",""),"needs_and_route":getattr(logistics,"evidence",())}
                    if logistics.action is None and logistics.move is None:
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
        pioneer=next((r for r in turn.controllable if r.role_type==ROLE_PIONEER),None)
        want_away=bool(pioneer and self.treasure.departure_due(turn,pioneer,config)
                       and (self.treasure.window_valid(turn) or self.treasure.opening_day==turn.day_index+1))
        blocked=[actor for actor,count in state.failed_move_counts.items() if count>=3]
        from .combat import raid_targets
        raiders,self.raid_status=raid_targets(turn,config)
        if threats or raiders or want_away or self.guard.away or pioneer is None or pioneer.unit_id in blocked:
            assignments,handover,guard_ready=self.guard.coordinate(turn,combat_weapons,config,want_away,blocked,preferred_backup=self.economy.main_miner_id)
        else:
            assignments=assign_controllers(turn,combat_weapons,config);handover=[];guard_ready=False

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
        needed = len(assignments) if threats or raiders or guard_ready else 0
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
        handover_ids={i.actor_id for i in handover}
        upgrading=set(handover_ids);upgraded_targets=set()
        min_level=min((w.level for w in weapons),default=3)
        for role in turn.controllable:
            if role.unit_id in handover_ids or (role.role_type!=ROLE_PIONEER and role.unit_id not in {a.controller.unit_id for a in active_assignments}):continue
            adjacent=sorted((w for w in weapons if role.pos and w.pos and role.pos.distance_to(w.pos)<=1 and w.level==min_level and w.level<3 and w.unit_id not in upgraded_targets),key=lambda w:w.unit_id)
            for weapon in adjacent:
                item=f'WeaponUpgradeVoucher{weapon.level}'
                if item in role.backpack:
                    actions.append(Action(role.unit_id,ActionType.USE,name=item,targets=(weapon.pos,)))
                    upgrading.add(role.unit_id);upgraded_targets.add(weapon.unit_id);break
        actions.extend(plan_attacks(turn,tuple(a for a in active_assignments if a.controller.unit_id not in upgrading),attack_targets,raiders))
        used_controllers = {action.controller_id for action in actions if action.controller_id is not None} | upgrading
        intents: list[MoveIntent] = list(handover)
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
            elif attack_targets or raiders or guard_ready:
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
            if role.role_type==ROLE_PIONEER:continue
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
            pioneer = next((role for role in released if role.role_type == ROLE_PIONEER and (not threats or guard_ready)), None)
            if pioneer is not None:
                treasure=self.treasure.plan(turn,pioneer,config,budget.offensive,guard_ready=guard_ready)
                self._merge_advanced(treasure,actions,intents,used_controllers)
                if want_away and guard_ready and pioneer.unit_id not in used_controllers:
                    # A temporary route obstruction must not turn a reserved
                    # dawn expedition into another shopping or task round trip.
                    intents.append(MoveIntent(pioneer.unit_id,(pioneer.pos,),96))
                    used_controllers.add(pioneer.unit_id)
                advanced = self._safe_task_plan(turn, state, llm_budget, config, pioneer) if pioneer.unit_id not in used_controllers and not threats else AdvancedPlan()
                self._merge_advanced(advanced, actions, intents, used_controllers)
                if turn.phase_task or advanced.prompt or advanced.execute_command:
                    used_controllers.add(pioneer.unit_id)
                if pioneer.unit_id not in used_controllers:
                    treasure = self.treasure.plan(turn, pioneer, config, budget.offensive)
                    self._merge_advanced(treasure, actions, intents, used_controllers)
            claimed=[]
            for role in sorted(released,key=lambda r:r.unit_id!=self.support_id):
                final_helper=turn.day_index>=config.final_defense_day and role.unit_id==self.economy.main_miner_id
                if turn.day_index>=config.night_support_day and (role.unit_id==self.support_id or final_helper) and role.unit_id not in used_controllers:
                    support=support_plan(turn,role,config,threats,recent_damage=self.support_damage if role.unit_id==self.support_id else 0,claimed=claimed,helper=final_helper)
                    self.economy.activity[role.unit_id]=support.reason
                    self.economy.evidence[role.unit_id]={"wall_risk":support.evidence}
                    if role.unit_id==self.support_id and support.reason in ('support_hold_protected','support_wait_with_goods'):
                        # Avoid spending an item on robots already projected to
                        # die to this turn's rocket salvo. Runtime ordering is
                        # not assumed; this is only a no-duplicate-spend estimate.
                        from .combat import _apply_projected_damage
                        projected={r.robot_id:r.health for r in turn.robots}
                        for shot in actions:
                            if shot.action_type==ActionType.ATTACK:
                                weapon=turn.team_our.unit(shot.actor_id)
                                if weapon:_apply_projected_damage(weapon,shot.targets,turn.robots,projected)
                        bomb_turn=replace(turn,robots=tuple(replace(r,health=projected[r.robot_id]) for r in turn.robots))
                        bomb=self.surplus_bomb.plan(bomb_turn,role,role,budget,config)
                        if bomb.action:
                            support=bomb;self.economy.activity[role.unit_id]=bomb.reason
                    if support.action and support.action.name!='Bomb':claimed.extend(support.action.targets)
                    elif support.reason=='reachable_wall_rescue' and support.evidence:
                        wall=turn.team_our.unit(support.evidence[0])
                        if wall:claimed.append(wall.pos)
                    if threats or final_helper or support.action or support.reason in ("reachable_wall_rescue","support_return_to_post"):
                        self._merge_advanced(support,actions,intents,used_controllers)
            for role in sorted(released,key=lambda r:r.role_type!=ROLE_PIONEER):
                if role.unit_id in used_controllers:
                    continue
                if role.role_type==ROLE_WORKER:continue
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
                if worker.role_type == ROLE_WORKER and worker.unit_id not in used_controllers:
                    self._plan_worker_economy(turn, worker, actions, intents, used_controllers, state, config, budget)

        danger=danger_cells(turn,config,self.economy.previous_robots)
        protected={a.controller.unit_id for a in active_assignments}|handover_ids|({self.support_id} if threats else set())
        if turn.day_index>=config.final_defense_day:protected.add(self.economy.main_miner_id)
        for worker in turn.controllable:
            if worker.role_type!=ROLE_WORKER or worker.unit_id in protected:continue
            if worker.pos in danger:
                actions=[a for a in actions if a.actor_id!=worker.unit_id]
                intents=[i for i in intents if i.actor_id!=worker.unit_id]
                escape=escape_intent(turn,worker,config,danger)
                if escape:intents.append(escape)
                self.economy.activity[worker.unit_id]='night_work_exposure_retreat'
            else:
                intents=[replace(i,avoid_cells=i.avoid_cells|danger) if i.actor_id==worker.unit_id else i for i in intents]
        moves = schedule_moves(turn, intents)
        actions.extend(action for action in moves if action.actor_id not in {item.actor_id for item in actions})
        return Decision(tuple(actions), advanced.prompt or self._background_prompt(turn,state,llm_budget,advanced), advanced.execute_command)

    def _background_prompt(self,turn,state,llm_budget,advanced):
        latest=state.official_news_history[-1] if state.official_news_history else (0,'')
        if (turn.phase_task or advanced.prompt or advanced.execute_command
            or (advanced.action and advanced.action.action_type==ActionType.ACCEPT_TASK)
            or self.treasure_prompt_pending or not llm_budget.can_call(task_active=False)):
            return ''
        if not self.treasure.needs_analysis() and (not latest[1] or latest[1]==self.interpreted_news):return ''
        prompt=self.treasure.prompt(latest[1],max(latest[0]-1,0)//ROUNDS_PER_DAY+1,
                                   purpose='treasure' if self.treasure.needs_analysis() else 'market_only')
        llm_budget.mark_requested(task_active=False,round_no=turn.round_no)
        self.treasure_prompt_pending=True;self.treasure_prompt_round=turn.round_no
        self.news_prompt_source=latest[1];self.news_prompt_day=max(latest[0]-1,0)//ROUNDS_PER_DAY+1
        return prompt

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
            if self.treasure_prompt_pending and not turn.phase_task:return AdvancedPlan()
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
    def _individual_recall(turn: Turn, state: WorldState, config: StrategyConfig, support_id=None) -> list[MoveIntent]:
        state.recalled_roles = {actor: day for actor, day in state.recalled_roles.items() if day == turn.day_index}
        intents = CompetitionPlanner._controller_intents(turn, 120)
        grid = OccupancyGrid.from_turn(turn, ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
        assigned = {intent.actor_id for intent in intents}
        station = turn.team_our.station()
        if station is not None:
            home = tuple(dict.fromkeys(p for cell in station.footprint() for p in interaction_cells(grid,cell)))
            intents.extend(MoveIntent(role.unit_id,TravelBudget.for_role(turn,role,config,wall_support=role.unit_id==support_id).goals or home,110) for role in turn.controllable
                           if role.unit_id not in assigned and role.pos is not None and ((turn.day_index>=config.night_support_day and role.unit_id==support_id) or role.role_type!=ROLE_WORKER))
        result = []
        for intent in intents:
            role = turn.team_our.unit(intent.actor_id)
            travel=TravelBudget.for_role(turn,role,config,wall_support=role.unit_id==support_id)
            distance=travel.cost()
            upgrade_actions=sum(min(role.backpack.count(f"WeaponUpgradeVoucher{level}"),sum(w.level==level for w in existing_weapons(turn))) for level in (1,2)) if role.role_type==ROLE_PIONEER else 0
            if not intent.goals:
                intent = replace(intent, goals=(role.pos,))
            # Static shortest paths omit queued humans and walls built en route.
            # Reserve a separate traffic allowance without recalling other roles.
            if (state.recall_day == turn.day_index or intent.actor_id in state.recalled_roles
                    or distance+travel.margin+upgrade_actions >= turn.rounds_until_night):
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
