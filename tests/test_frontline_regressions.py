from __future__ import annotations

from dataclasses import replace
import time
import unittest

from solution.actions import Action, ActionType
from solution.combat import shot_damage
from solution.engine import AgentEngine
from solution.geometry import Pos
from solution.layout import DefenseLayout, DefenseMemory, WallWork, observe_defense, plan_layout, remaining_wall_sites
from solution.maintenance import rank_wall_work, try_wall_work, try_jobs
from solution.models import Turn
from solution.planning import PlanningContext
from solution.state import WorldState
from tests.helpers import role
from tests.scenarios import arena, robot
from tests.simulation import EconomySimulation
from tests.test_layout import frontline_config


class FrontlineRegressionTests(unittest.TestCase):
    def test_base_does_not_block_combat_or_layout_but_blocks_movement(self):
        from solution.ballistics import projectile_blockers
        from solution.layout import WeaponPlacement, _coverage
        from solution.navigation import occupied_cells
        for kind in ('railgun', 'gatling'):
            for team in ('teamOur', 'teamEnemy'):
                with self.subTest(weapon=kind, team=team):
                    raw = arena(80, armed=True)
                    raw['teamOur']['roles'][4]['roleType'] = kind
                    raw['robot']['roles'] = [robot(100, 10, 14, 40)]
                    turn = Turn.from_raw(raw)
                    expected = shot_damage(turn, turn.team_our.unit(11), Pos(10, 14), frontline_config())
                    raw[team]['roles'].append(role(40, 'station', 7, 15, level=1))
                    turn = Turn.from_raw(raw)
                    weapon = turn.team_our.unit(11)
                    self.assertTrue(expected)
                    self.assertEqual(shot_damage(turn, weapon, Pos(10, 14), frontline_config()), expected)
                    base = turn.team_our.unit(40) if team == 'teamOur' else turn.team_enemy.roles[0]
                    self.assertTrue(set(base.footprint()).issubset(occupied_cells(turn)))
                    self.assertFalse(set(base.footprint()) & projectile_blockers(turn))
                    placement = WeaponPlacement(kind, weapon.pos, (Pos(5, 15),))
                    front_ok, count = _coverage(turn, (placement,), projectile_blockers(turn),
                                                (Pos(10, 14),), frontline_config())
                    self.assertTrue(front_ok)
                    self.assertEqual(count, 1)

    def context(self, raw, state=None, config=None):
        config = config or frontline_config()
        state = state or WorldState()
        turn = Turn.from_raw(raw)
        observe_defense(turn, state.defense, config)
        return PlanningContext(turn, config, state, time.monotonic() + 1)

    def maintenance_raw(self):
        raw = arena(20, armed=True)
        raw['teamOur']['goldNum'] = 400
        raw['teamOur']['roles'].append(role(40, 'wall', 6, 15, health=200, level=1))
        raw['weaponShopList'].append({'name': 'WallFixer', 'price': 10})
        return raw

    def test_walk_to_shop_buy_and_deliver_over_multiple_turns(self):
        raw = self.maintenance_raw()
        state = WorldState()
        work = WallWork('repair', Pos(6, 15), 40, 'WallFixer', 3, 800, 10, 'synthetic')
        actions = []
        for n in range(20, 36):
            raw['roundNo'] = n
            ctx = self.context(raw, state)
            self.assertTrue(try_wall_work(ctx, ctx.turn.team_our.unit(1), work, 20))
            action = ctx.actions[0]
            actions.append(action.action_type)
            worker = raw['teamOur']['roles'][0]
            if action.action_type == ActionType.MOVE:
                self.assertFalse(state.defense.pending_buys)
                worker['pos'] = action.targets[0].to_raw()
            elif action.action_type == ActionType.BUY:
                raw['teamOur']['goldNum'] -= 10
                worker['backpack'].append('WallFixer')
            elif action.action_type == ActionType.USE:
                worker['backpack'].remove('WallFixer')
                break
            raw['lastRoundRoleActionResults'] = {'1': True}
        self.assertEqual(actions.count(ActionType.BUY), 1)
        self.assertEqual(actions[-1], ActionType.USE)
        self.assertEqual(state.defense.wall_spend, 10)

    def test_wall_purchase_keeps_live_medicine_reserve(self):
        raw = self.maintenance_raw()
        raw['teamOur']['roles'][0]['health'] = 50
        raw['teamOur']['roles'][0]['pos'] = {'x': 6, 'y': 18}
        raw['weaponShopList'][-1]['price'] = 30
        state = WorldState()
        self.context(raw, state)
        raw['roundNo'] += 1
        raw['teamOur']['goldNum'] = 30
        ctx = self.context(raw, state)
        work = WallWork('repair', Pos(6, 15), 40, 'WallFixer', 3, 800, 30, 'synthetic')
        self.assertFalse(try_wall_work(ctx, ctx.turn.team_our.unit(1), work, 20))
        self.assertEqual(ctx.gold, 30)

    def test_wall_does_not_block_shot_but_still_blocks_movement(self):
        from solution.navigation import occupied_cells
        for kind in ('railgun', 'gatling'):
            raw = arena(80, armed=True)
            raw['teamOur']['roles'][4]['roleType'] = kind
            raw['robot']['roles'] = [robot(100, 10, 14, 40)]
            turn = Turn.from_raw(raw)
            expected = shot_damage(turn, turn.team_our.unit(11), Pos(10, 14), frontline_config())
            raw['teamOur']['roles'].append(role(40, 'wall', 6, 14, level=1))
            turn = Turn.from_raw(raw)
            self.assertTrue(expected)
            self.assertEqual(shot_damage(turn, turn.team_our.unit(11), Pos(10, 14), frontline_config()), expected)
            self.assertIn(Pos(6, 14), occupied_cells(turn))

    def test_existing_front_wall_keeps_classification_and_maintenance(self):
        raw = arena()
        state = WorldState()
        ctx = self.context(raw, state)
        layout = plan_layout(ctx.turn, state.defense, ctx.config, ctx.deadline)
        wall = layout.front_walls[0]
        for i, weapon in enumerate(layout.weapons):
            raw['teamOur']['roles'].append(role(11+i, weapon.role_type, weapon.pos.x, weapon.pos.y, attack_range=10))
        raw['teamOur']['roles'].append(role(40, 'wall', wall.x, wall.y, health=200, level=1))
        raw['weaponShopList'].append({'name': 'WallFixer', 'price': 10})
        raw['roundNo'] = 2
        ctx = self.context(raw, state)
        layout = plan_layout(ctx.turn, state.defense, ctx.config, ctx.deadline)
        self.assertIn(wall, layout.front_walls)
        self.assertTrue(any(j.target_id == 40 for j in rank_wall_work(ctx, layout)))

    def test_wall_cap_is_global_over_multiple_days(self):
        sim = EconomySimulation()
        engine = AgentEngine(frontline_config(max_walls=4))
        for _ in range(201):
            sim.apply(engine.decide(sim.raw))
            self.assertLessEqual(sum(u['roleType'] == 'wall' for u in sim.raw['teamOur']['roles']), 4)
        self.assertEqual(sum(u['roleType'] == 'wall' for u in sim.raw['teamOur']['roles']), 4)

    def test_price_changes_repair_upgrade_preference(self):
        raw = self.maintenance_raw()
        layout = DefenseLayout((1, 0), 'user_prior', (), (Pos(6, 15),), (), (), 'synthetic')
        selected = []
        for price in (1, 2000):
            raw['weaponShopList'] = [{'name': 'WallFixer', 'price': 10}, {'name': 'WallUpgradeVoucher1', 'price': price}]
            ctx = self.context(raw)
            jobs = [j for j in rank_wall_work(ctx, layout) if j.target_id == 40]
            selected.append(jobs[0].kind)
        self.assertEqual(selected, ['upgrade', 'repair'])

    def test_hot_flank_precedes_less_pressured_front(self):
        raw = arena(20, armed=True)
        ctx = self.context(raw)
        ctx.state.defense.front_robot_count = 6
        ctx.state.defense.flank_pressure = {'neg': 100, 'pos': 0}
        layout = DefenseLayout((1, 0), 'user_prior', (), (Pos(6, 15), Pos(6, 16)), (Pos(5, 13),), (), 'synthetic',
                               wall_order=(Pos(5, 13), Pos(6, 15), Pos(6, 16)))
        self.assertEqual(rank_wall_work(ctx, layout)[0].target, Pos(5, 13))

    def test_failed_purchase_retries_and_missing_feedback_expires(self):
        for feedback in (False, None):
            with self.subTest(feedback=feedback):
                raw = self.maintenance_raw()
                raw['teamOur']['roles'][0]['pos'] = {'x': 6, 'y': 18}
                state = WorldState()
                work = WallWork('repair', Pos(6, 15), 40, 'WallFixer', 3, 800, 10, 'synthetic')
                ctx = self.context(raw, state)
                self.assertTrue(try_wall_work(ctx, ctx.turn.team_our.unit(1), work, 20))
                self.assertEqual(ctx.actions[0].action_type, ActionType.BUY)
                raw['roundNo'] = 21
                raw['lastRoundRoleActionResults'] = {} if feedback is None else {'1': feedback}
                ctx = self.context(raw, state)
                if feedback is False:
                    self.assertFalse(state.defense.pending_buys)
                    self.assertTrue(try_wall_work(ctx, ctx.turn.team_our.unit(1), work, 20))
                else:
                    self.assertFalse(try_wall_work(ctx, ctx.turn.team_our.unit(1), work, 20))
                    for n in range(22, 62):
                        raw['roundNo'] = n
                        ctx = self.context(raw, state)
                    self.assertFalse(state.defense.pending_buys)
                    self.assertEqual(state.defense.wall_reserved, 0)
                    self.assertTrue(try_wall_work(ctx, ctx.turn.team_our.unit(1), work, 20))

    def test_engine_buys_and_repairs_once_in_transition_harness(self):
        sim = EconomySimulation()
        sim.raw = self.maintenance_raw()
        sim.raw['weaponShopList'] = [{'name': 'WallFixer', 'price': 10}]
        engine = AgentEngine(frontline_config(max_walls=1, front_wall_target_count=0))
        for _ in range(22):
            sim.apply(engine.decide(sim.raw))
        wall = next(u for u in sim.raw['teamOur']['roles'] if u['id'] == 40)
        self.assertEqual(wall['health'], 1000)
        self.assertEqual(sim.counts['buy'], 1)
        self.assertEqual(sim.counts['use'], 1)

    def test_station_and_multiple_medicines_are_reserved(self):
        raw = self.maintenance_raw()
        raw['teamOur']['roles'][0]['pos'] = {'x': 6, 'y': 18}
        raw['teamOur']['roles'][0]['health'] = 50
        raw['teamOur']['roles'][1]['health'] = 50
        raw['teamOur']['roles'][3]['health'] = 100
        state = WorldState()
        self.context(raw, state)
        raw['roundNo'] += 1
        raw['teamOur']['goldNum'] = 125  # Base voucher 100 + two medicines 20.
        ctx = self.context(raw, state)
        work = WallWork('repair', Pos(6, 15), 40, 'WallFixer', 3, 800, 10, 'synthetic')
        self.assertFalse(try_wall_work(ctx, ctx.turn.team_our.unit(1), work, 20))

    def test_same_turn_wall_build_reservations_enforce_cap(self):
        raw = arena(20, armed=True)
        raw['teamOur']['roles'][0]['backpack'] = ['stone']
        raw['teamOur']['roles'][1]['backpack'] = ['stone']
        ctx = self.context(raw, config=frontline_config(max_walls=1, front_wall_target_count=1))
        self.assertTrue(ctx.add(Action(1, ActionType.BUILD, targets=(Pos(6, 15),), name='wall')))
        self.assertFalse(ctx.add(Action(2, ActionType.BUILD, targets=(Pos(2, 13),), name='wall')))

    def test_layout_preserves_hot_flank_order_and_executes_it(self):
        from tools.diagnostics.defense_layout import _sample
        for side in ('left', 'right'):
            with self.subTest(side=side):
                raw = _sample(side)
                ctx = self.context(raw)
                first = plan_layout(ctx.turn, ctx.state.defense, ctx.config, ctx.deadline)
                for i, w in enumerate(first.weapons):
                    raw['teamOur']['roles'].append(role(11+i, w.role_type, w.pos.x, w.pos.y, attack_range=10))
                raw['roundNo'] = 2
                ctx = self.context(raw, ctx.state)
                ctx.state.defense.front_robot_count = 1
                ctx.state.defense.flank_pressure = {'neg': 100, 'pos': 80}
                layout = plan_layout(ctx.turn, ctx.state.defense, ctx.config, ctx.deadline)
                remaining = remaining_wall_sites(ctx.turn, layout)
                first_site = remaining[0]
                # Isolated flanks must not skip the edge-connected corner/front joint.
                self.assertNotIn(first_site, layout.flank_walls)
                self.assertTrue(layout.corner_walls)
                self.assertTrue(frozenset(layout.corner_walls).issubset(remaining))
                flank_ranks = [remaining.index(p) for p in remaining if p in layout.flank_walls]
                corner_ranks = [remaining.index(p) for p in layout.corner_walls if p in remaining]
                self.assertTrue(flank_ranks)
                self.assertLess(max(corner_ranks), min(flank_ranks))
                raw['teamOur']['roles'][0]['backpack'] = ['stone']
                raw['teamOur']['roles'][0]['pos'] = {'x': first_site.x + layout.front[0], 'y': first_site.y}
                raw['roundNo'] += 1
                ctx = self.context(raw, ctx.state)
                ctx.layout = layout
                jobs = rank_wall_work(ctx, layout)
                self.assertEqual(jobs[0].target, first_site)
                self.assertTrue(try_jobs(ctx, ctx.turn.team_our.unit(1), jobs, 20, urgent=True))
                self.assertEqual(ctx.actions[0].action_type, ActionType.BUILD)
                self.assertEqual(ctx.actions[0].targets, (first_site,))

    def test_upgrade_precedes_cheaper_repair_when_only_upgrade_covers_loss(self):
        raw = self.maintenance_raw()
        raw['weaponShopList'].append({'name': 'WallUpgradeVoucher1', 'price': 20})
        ctx = self.context(raw)
        ctx.state.defense.front_robot_count = 1
        ctx.state.defense.damage_events.append((19, 40, 'E', 1200))
        layout = DefenseLayout((1, 0), 'user_prior', (), (Pos(6, 15),), (), (), 'synthetic')
        jobs = [j for j in rank_wall_work(ctx, layout) if j.target_id == 40]
        self.assertEqual(jobs[0].kind, 'upgrade')
