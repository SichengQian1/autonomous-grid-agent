"""Conservative visible-robot exposure; never a claim of engine target knowledge."""
from dataclasses import replace
from .geometry import Pos
from .grid import OccupancyGrid, shortest_path
from .movement import MoveIntent


def danger_cells(turn, config, previous=None):
    if turn.is_day:return frozenset()
    blocked=set()
    for robot in turn.robots:
        if robot.health<=0 or robot.pos is None:continue
        old=(previous or {}).get(robot.robot_id)
        # One movement step plus an extra cell when motion was actually observed.
        reach=(robot.attack_range or config.robot_attack_range_fallback)+1+int(old is not None and old!=robot.pos)
        for x in range(max(0,robot.pos.x-reach),min(turn.map_info.width,robot.pos.x+reach+1)):
            for y in range(max(0,robot.pos.y-reach),min(turn.map_info.height,robot.pos.y+reach+1)):
                blocked.add(Pos(x,y))
    return frozenset(blocked)


def safe_grid(turn, config, previous=None):
    grid=OccupancyGrid.from_turn(turn,ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
    danger=danger_cells(turn,config,previous)
    return replace(grid,blocked=grid.blocked|danger),danger


def safe_intent(actor, goals, grid, danger, priority=30):
    # The joint movement planner must use the same excluded cells as valuation.
    path=shortest_path(grid,actor.pos,goals)
    return MoveIntent(actor.unit_id,tuple(goals),priority,avoid_cells=danger) if path else None


def escape_intent(turn, actor, config, danger):
    grid=OccupancyGrid.from_turn(turn,ignore_unit_ids=(actor.unit_id,))
    live=[r for r in turn.robots if r.health>0 and r.pos]
    def clearance(p):return min((p.distance_to(r.pos)-(r.attack_range or config.robot_attack_range_fallback) for r in live),default=100)
    options=[p for p in grid.neighbours(actor.pos) if clearance(p)>clearance(actor.pos)]
    if not options:return None
    best=max(options,key=lambda p:(p not in danger,clearance(p),-turn.coordinate_frame.normalize(p).x))
    return MoveIntent(actor.unit_id,(best,),125)
