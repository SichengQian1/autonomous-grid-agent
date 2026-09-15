from __future__ import annotations

import unittest

from solution.geometry import Pos
from solution.grid import OccupancyGrid, shortest_path
from solution.models import Turn
from solution.movement import MoveIntent, schedule_moves
from tests.helpers import role, synthetic_turn


class GridTests(unittest.TestCase):
    def test_eight_direction_path(self) -> None:
        grid = OccupancyGrid(5, 5, frozenset())
        path = shortest_path(grid, Pos(0, 0), (Pos(3, 3),))
        self.assertEqual(path, (Pos(0, 0), Pos(1, 1), Pos(2, 2), Pos(3, 3)))

    def test_diagonal_between_two_obstacles_is_allowed(self) -> None:
        grid = OccupancyGrid(3, 3, frozenset({Pos(1, 0), Pos(0, 1)}))
        self.assertEqual(shortest_path(grid, Pos(0, 0), (Pos(1, 1),)), (Pos(0, 0), Pos(1, 1)))

    def test_path_stays_inside_map(self) -> None:
        grid = OccupancyGrid(3, 2, frozenset())
        path = shortest_path(grid, Pos(0, 0), (Pos(2, 1),))
        self.assertTrue(path)
        self.assertTrue(all(grid.contains(pos) for pos in path))

    def test_no_path_returns_empty(self) -> None:
        grid = OccupancyGrid(3, 3, frozenset({Pos(0, 1), Pos(1, 0), Pos(1, 1)}))
        self.assertEqual(shortest_path(grid, Pos(0, 0), (Pos(2, 2),)), ())


def movement_turn(positions: tuple[tuple[int, int, int], ...], robot_pos: Pos | None = None) -> Turn:
    raw = synthetic_turn(round_no=1)
    raw["mapInfo"] = {"width": 8, "height": 8, "zones": []}
    raw["teamOur"]["playerTasks"] = []
    raw["teamOur"]["roles"] = [
        role(unit_id, "worker" if unit_id != 3 else "pioneer", x, y)
        for unit_id, x, y in positions
    ]
    raw["teamEnemy"] = {"roles": []}
    raw["robot"] = {"roles": []}
    if robot_pos is not None:
        raw["robot"]["roles"].append(
            {"id": 90, "pos": robot_pos.to_raw(), "roleType": "smallRobot", "health": 40}
        )
    raw["phaseTask"] = ""
    return Turn.from_raw(raw)


class JointMovementTests(unittest.TestCase):
    def test_two_roles_do_not_enter_same_cell(self) -> None:
        turn = movement_turn(((1, 1, 1), (2, 3, 1)))
        actions = schedule_moves(
            turn,
            (
                MoveIntent(1, (Pos(2, 1),), 10),
                MoveIntent(2, (Pos(2, 1),), 10),
            ),
        )
        targets = [action.targets[0] for action in actions]
        self.assertEqual(len(targets), len(set(targets)))
        self.assertNotIn(Pos(2, 1), targets[1:])

    def test_three_roles_do_not_compete_for_one_cell(self) -> None:
        turn = movement_turn(((1, 1, 1), (2, 3, 1), (3, 2, 3)))
        actions = schedule_moves(
            turn,
            tuple(MoveIntent(role_id, (Pos(2, 2),), 10) for role_id in (1, 2, 3)),
        )
        targets = [action.targets[0] for action in actions]
        self.assertEqual(len(targets), len(set(targets)))

    def test_position_swap_is_not_scheduled(self) -> None:
        turn = movement_turn(((1, 1, 1), (2, 2, 1)))
        actions = schedule_moves(
            turn,
            (MoveIntent(1, (Pos(2, 1),), 10), MoveIntent(2, (Pos(1, 1),), 10)),
        )
        self.assertEqual(actions, ())

    def test_stationary_role_is_an_obstacle(self) -> None:
        turn = movement_turn(((1, 1, 1), (2, 2, 1)))
        actions = schedule_moves(turn, (MoveIntent(1, (Pos(2, 1),), 10),))
        self.assertEqual(actions, ())

    def test_dynamic_robot_causes_replan(self) -> None:
        first = movement_turn(((1, 1, 1),), None)
        second = movement_turn(((1, 1, 1),), Pos(2, 2))
        intent = (MoveIntent(1, (Pos(4, 4),), 10),)
        first_action = schedule_moves(first, intent)[0]
        second_action = schedule_moves(second, intent)[0]
        self.assertNotEqual(first_action.targets, second_action.targets)
        self.assertNotEqual(second_action.targets[0], Pos(2, 2))


if __name__ == "__main__":
    unittest.main()
