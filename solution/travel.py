"""Shared physical route budgets for work, delivery and defensive recall."""
from __future__ import annotations
from dataclasses import dataclass
from .combat import assign_controllers
from .geometry import Pos
from .grid import OccupancyGrid, distance_field, interaction_cells, shortest_path
from .models import Turn, Unit
from .defense import build_defense_layout, wall_support_post
from .rules import StrategyConfig

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

    @classmethod
    def for_role(cls, turn: Turn, role: Unit, config: StrategyConfig, *, must_return=True, wall_support=False, support_helper=False):
        grid=OccupancyGrid.from_turn(turn,ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
        weapons=tuple(u for u in turn.team_our.roles if u.is_weapon and u.alive)
        assignment=next((a for a in assign_controllers(turn,weapons,config) if a.controller.unit_id==role.unit_id),None)
        if assignment is not None:
            goals=(assignment.control_pos,) if assignment.control_pos else interaction_cells(grid,assignment.weapon.pos)
        else:
            station=turn.team_our.station()
            goals=tuple(p for cell in station.footprint() for p in interaction_cells(grid,cell)) if station else (role.pos,)
            held=next((w for w in weapons if w.level<3 and f'WeaponUpgradeVoucher{w.level}' in role.backpack),None)
            if held is not None:goals=interaction_cells(grid,held.pos)
            elif station and turn.day_index>=config.night_support_day and (wall_support or any(i=='WallFixer' or i.startswith('WallUpgradeVoucher') for i in role.backpack)):
                post=wall_support_post(turn,config,helper=support_helper)
                if grid.passable(post):goals=(post,)
        return cls(grid,role.pos,distance_field(grid,goals),turn.rounds_until_night,
                   config.recall_safety_buffer+config.recall_traffic_buffer,turn.is_day and must_return,tuple(goals))

    def cost(self, stops=()):
        """Greedy actual paths through each work stop, then home, in turns."""
        pos=self.start; total=0
        for goals, work in stops:
            path=shortest_path(self.grid,pos,goals)
            if not path: return UNREACHABLE
            total+=len(path)-1+work; pos=path[-1]
        return total+(self.home.get(pos,UNREACHABLE) if self.daytime else 0)

    def fits(self, stops=()):
        return not self.daytime or self.cost(stops)+self.margin < self.remaining
