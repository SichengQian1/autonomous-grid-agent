"""Stable support ownership and arrival-confirmed shared gun handovers."""
from dataclasses import dataclass,field,replace
from .combat import ControllerAssignment,assign_controllers
from .defense import build_defense_layout
from .grid import OccupancyGrid,distance_field,shortest_path
from .movement import MoveIntent


def wall_goods(role):
    return sum(i=='WallFixer' or i.startswith('WallUpgradeVoucher') for i in role.backpack)


@dataclass(slots=True)
class GuardHandover:
    backup_id: int | None = None
    away: bool = False
    phase: str = 'pioneer'
    reason: str = ''
    waiting_since: int = 0

    def coordinate(self,turn,weapons,config,want_away=False,blocked_ids=(),preferred_backup=None):
        default=assign_controllers(turn,weapons,config)
        layout=build_defense_layout(turn)
        if len(weapons)!=3 or not layout.controller_sites:return default,[],False
        post=layout.controller_sites[0]
        if not all(w.pos and w.pos.distance_to(post)==1 for w in weapons):return default,[],False
        humans=[r for r in turn.controllable if r.pos]
        pioneer=next((r for r in humans if r.role_type=='pioneer'),None)
        workers=[r for r in humans if r.role_type=='worker']
        grid=OccupancyGrid.from_turn(turn,ignore_unit_ids=tuple(r.unit_id for r in humans))
        danger=frozenset()
        if not turn.is_day:
            from .maintenance import support_danger_cells
            walls=[r for r in turn.team_our.roles if r.role_type=='wall' and r.alive and r.pos]
            danger=support_danger_cells(turn,walls,turn.robots,config)
            grid=replace(grid,blocked=grid.blocked|danger)
        distances=distance_field(grid,(post,))
        impossible=pioneer is None or pioneer.unit_id in blocked_ids or distances.get(pioneer.pos,10000)>=10000
        want_away=want_away or impossible
        if want_away:
            if not self.away and preferred_backup in {r.unit_id for r in workers}:
                self.backup_id=preferred_backup
            if self.backup_id not in {r.unit_id for r in workers}:
                backup=min(workers,key=lambda r:(distances.get(r.pos,10000),-wall_goods(r),r.unit_id),default=None)
                self.backup_id=backup.unit_id if backup else None
            target=next((r for r in workers if r.unit_id==self.backup_id),None)
        else:target=pioneer
        if not target:
            self.phase='no_living_replacement';return default,[],False
        incumbent=next((r for r in humans if r.pos==post),None)
        intents=[]
        occupied={r.pos for r in humans}
        stages=tuple(p for p in layout.rear_corridor if p!=post and p.distance_to(post)==1 and grid.passable(p))
        if target.pos==post:
            self.away=target.role_type=='worker';self.phase='worker_confirmed' if self.away else 'pioneer_confirmed'
            return tuple(ControllerAssignment(w,target,post) for w in weapons),[],self.away
        if incumbent and incumbent.unit_id!=target.unit_id:
            if target.pos not in stages:
                available=tuple(p for p in stages if p not in occupied)
                if available:intents.append(MoveIntent(target.unit_id,available,130,avoid_cells=danger))
                self.phase='replacement_approach'
            else:
                vacate=tuple(p for p in stages if p not in occupied)
                if vacate:intents.append(MoveIntent(incumbent.unit_id,vacate,131,avoid_cells=danger))
                self.phase='vacate_common_post'
        else:
            intents.append(MoveIntent(target.unit_id,(post,),131,avoid_cells=danger));self.phase='enter_common_post'
        # During the two physical moves the other human still covers launchers.
        # Never assume a requested move arrived; post ownership comes from input.
        moving={i.actor_id for i in intents}
        assignments=[]
        for w in weapons:
            adjacent=[r for r in humans if r.unit_id not in moving and r.pos.distance_to(w.pos)<=1]
            controller=min(adjacent,key=lambda r:(r.unit_id!=getattr(incumbent,'unit_id',None),r.unit_id!=target.unit_id,r.unit_id),default=None)
            if controller:assignments.append(ControllerAssignment(w,controller,controller.pos))
        self.away=False
        return tuple(assignments),intents,False
