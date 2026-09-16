"""Synthetic operational regressions; no opponent data or task answers."""
from __future__ import annotations

import unittest
from itertools import permutations

from solution.defense import build_defense_layout
from solution.economy import weapon_build_objectives
from solution.geometry import Pos
from solution.models import Turn
from solution.movement import MoveIntent, schedule_moves
from solution.rules import DEFAULT_CONFIG
from solution.state import WorldState
from tests.helpers import role, synthetic_turn
from solution.planner import CompetitionPlanner
from solution.combat import assign_controllers


def campus(side="challenger"):
    raw = synthetic_turn(round_no=1)
    raw["mapInfo"] = {"width": 20, "height": 18, "zones": []}
    raw["teamOur"].update(type=side, playerTasks=[], roles=[
        role(1, "worker", 4, 9), role(2, "worker", 4, 10),
        role(3, "pioneer", 4, 11), role(10, "station", 5, 10, health=1500, level=1)])
    raw["teamEnemy"] = {"roles": []}
    raw["robot"] = {"roles": []}
    raw["phaseTask"] = ""
    if side == "defender":
        for u in raw["teamOur"]["roles"]:
            u["pos"] = {"x": 19-u["pos"]["x"], "y": 17-u["pos"]["y"]}
            if u["roleType"] == "station":
                u["pos"]["x"] -= 1
                u["pos"]["y"] += 1
    return raw


class LayoutOperationsTests(unittest.TestCase):
    def test_three_roles_reach_separate_controls_after_complete_walls(self):
        for side in ("challenger","defender"):
            for ordering in permutations((Pos(1,7),Pos(1,8),Pos(1,9))):
                with self.subTest(side=side, ordering=ordering):
                    raw=campus(side); layout=build_defense_layout(Turn.from_raw(raw))
                    for i,(kind,pos) in enumerate(zip(("rocket","railgun","rocket"),layout.weapon_sites[:3])):
                        raw['teamOur']['roles'].append(role(20+i,kind,pos.x,pos.y,health=1000,level=1))
                    for i,pos in enumerate(layout.wall_sites):
                        raw['teamOur']['roles'].append(role(50+i,'wall',pos.x,pos.y,health=1000,level=1))
                    for unit,pos in zip(raw['teamOur']['roles'][:3],ordering):
                        unit['pos']=layout.frame.denormalize(pos).to_raw()
                    for _ in range(20):
                        turn=Turn.from_raw(raw)
                        actions=schedule_moves(turn,CompetitionPlanner._controller_intents(turn,120))
                        by_id={u['id']:u for u in raw['teamOur']['roles']}
                        destinations=[a.targets[0] for a in actions]
                        self.assertEqual(len(destinations),len(set(destinations)))
                        self.assertFalse(set(destinations) & {r.pos for r in turn.controllable})
                        for action in actions: by_id[action.actor_id]['pos']=action.targets[0].to_raw()
                    turn=Turn.from_raw(raw)
                    assignments=assign_controllers(turn,tuple(u for u in turn.team_our.roles if u.is_weapon))
                    self.assertEqual(len(assignments),3)
                    self.assertTrue(all(a.controller.pos == a.control_pos for a in assignments))

    def test_all_three_guns_are_behind_whole_base_on_both_sides(self):
        for side in ("challenger", "defender"):
            turn = Turn.from_raw(campus(side))
            layout = build_defense_layout(turn)
            rear = min(layout.frame.normalize(p).x for p in turn.team_our.station().footprint()) - 1
            self.assertEqual(len(layout.weapon_sites[:3]), 3)
            self.assertTrue(all(layout.frame.normalize(p).x == rear for p in layout.weapon_sites[:3]))

    def test_temporary_role_does_not_shift_weapon_slot(self):
        raw = campus()
        layout = build_defense_layout(Turn.from_raw(raw))
        raw["teamOur"]["roles"][0]["pos"] = layout.weapon_sites[0].to_raw()
        objectives = weapon_build_objectives(Turn.from_raw(raw), layout, WorldState(), DEFAULT_CONFIG)
        self.assertEqual(objectives[0].site, layout.weapon_sites[0])

    def test_explicit_hold_intent_can_yield_for_blocked_teammate(self):
        raw = campus()
        raw["mapInfo"] = {"width": 7, "height": 5, "zones": []}
        raw["teamOur"]["roles"] = [role(1,"worker",1,2), role(2,"worker",3,2)]
        raw["teamOur"]["roles"] += [role(20+y,"wall",3,y) for y in (0,1,3,4)]
        # The held role has a safe retreat on the far side of the doorway.
        turn = Turn.from_raw(raw)
        moves = schedule_moves(turn, [MoveIntent(1,(Pos(5,2),),120), MoveIntent(2,(Pos(3,2),),100)])
        self.assertTrue(any(a.actor_id == 2 and a.targets[0].x > 3 for a in moves))


if __name__ == "__main__":
    unittest.main()
