"""Conservative visible-robot exposure; never a claim of engine target knowledge."""
from dataclasses import replace
from heapq import heappop, heappush
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
    neighbours=grid.neighbours(actor.pos)
    if not neighbours:return None
    # Bounded escape through a plateau, with damage exposure as a cost. Only the
    # first adjacent legal step is returned; re-evaluate live obstacles next turn.
    def exposure(p):
        return sum(max(r.attack_power,1) for r in live
                   if p.distance_to(r.pos)<=(r.attack_range or config.robot_attack_range_fallback)+1)
    queue=[(0,0,actor.pos.x,actor.pos.y,actor.pos,None)]
    costs={actor.pos:(0,0)};candidates=[];visited=0
    while queue and visited<config.escape_search_nodes:
        cost,steps,_,_,pos,first=heappop(queue)
        if costs.get(pos)!=(cost,steps):continue
        visited+=1
        if first is not None:
            if pos not in danger:return MoveIntent(actor.unit_id,(first,),125)
            candidates.append((clearance(pos),-cost,-steps,-pos.x,-pos.y,first))
        if steps>=config.escape_search_depth:continue
        for nxt in grid.neighbours(pos):
            score=(cost+1+exposure(nxt),steps+1)
            if score>=costs.get(nxt,(float('inf'),float('inf'))):continue
            costs[nxt]=score
            heappush(queue,(*score,nxt.x,nxt.y,nxt,first or nxt))
    improving=[c for c in candidates if c[0]>clearance(actor.pos)]
    if not improving:return None
    return MoveIntent(actor.unit_id,(max(improving)[-1],),125)
