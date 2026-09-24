"""Shared physical route budgets for work, delivery and defensive recall."""
from __future__ import annotations
from dataclasses import dataclass
from .combat import assign_controllers
from .geometry import Pos
from .grid import OccupancyGrid, distance_field, interaction_cells, shortest_path
from .models import Turn, Unit
from .defense import build_defense_layout
from .rules import StrategyConfig
from .wall_access import planning_grid, return_distances, transit_cost, gate_sites

UNREACHABLE = 10000

@dataclass(slots=True)
class TravelBudget:
    grid: OccupancyGrid
    start: Pos
    home: dict[Pos, int]
    remaining: int
    margin: int
    daytime: bool
    goals: tuple[Pos,...] = ()
    turn: Turn | None = None
    config: StrategyConfig | None = None

    @classmethod
    def for_role(cls, turn: Turn, role: Unit, config: StrategyConfig, *, must_return=True, wall_support=False, worker_refuge=False):
        if wall_support and turn.day_index<config.night_support_day:
            worker_refuge=True
        grid=planning_grid(turn,role,config)
        weapons=tuple(u for u in turn.team_our.roles if u.is_weapon and u.alive)
        assignment=next((a for a in assign_controllers(turn,weapons,config) if a.controller.unit_id==role.unit_id),None)
        if assignment is not None:
            goals=(assignment.control_pos,) if assignment.control_pos else interaction_cells(grid,assignment.weapon.pos)
        else:
            station=turn.team_our.station()
            goals=tuple(p for cell in station.footprint() for p in interaction_cells(grid,cell)) if station else (role.pos,)
            if worker_refuge and station:
                layout=build_defense_layout(turn)
                occupied={r.pos for r in turn.controllable if r.unit_id!=role.unit_id}
                refuge=tuple(p for p in layout.rear_corridor if p not in layout.controller_sites
                             and p not in gate_sites(turn,config) and p not in occupied and grid.passable(p))
                if refuge:goals=refuge
            held=next((w for w in weapons if w.level<3 and f'WeaponUpgradeVoucher{w.level}' in role.backpack),None)
            if held is not None and not worker_refuge:goals=interaction_cells(grid,held.pos)
            elif station and turn.day_index>=config.night_support_day and (wall_support or not worker_refuge and any(i=='WallFixer' or i.startswith('WallUpgradeVoucher') for i in role.backpack)):
                cells=turn.coordinate_frame.normalize_cells(station.footprint())
                post=turn.coordinate_frame.denormalize(Pos(max(p.x for p in cells)+1,max(p.y for p in cells)+1))
                occupied={r.pos for r in turn.controllable if r.unit_id!=role.unit_id}
                if grid.passable(post) and post not in occupied:goals=(post,)
                else:
                    from .wall_access import inside
                    alternatives=tuple(p for p in post.neighbours() if grid.passable(p) and p not in occupied and inside(turn,p))
                    if alternatives:goals=alternatives
        queue=config.gate_helper_queue_buffer if wall_support and turn.day_index>=config.final_defense_day and gate_sites(turn,config) else 0
        return cls(grid,role.pos,return_distances(turn,grid,goals,config),turn.rounds_until_night,
                   config.recall_safety_buffer+config.recall_traffic_buffer+queue,turn.is_day and must_return,tuple(goals),turn,config)

    def cost(self, stops=()):
        """Greedy actual paths through each work stop, then home, in turns."""
        pos=self.start; total=0
        for goals, work in stops:
            path=shortest_path(self.grid,pos,goals)
            if not path: return UNREACHABLE
            total+=len(path)-1+work; pos=path[-1]
            if self.turn and self.config:total+=transit_cost(self.turn,path,self.config)
        return total+(self.home.get(pos,UNREACHABLE) if self.daytime else 0)

    def fits(self, stops=()):
        return not self.daytime or self.cost(stops)+self.margin < self.remaining
