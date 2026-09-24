"""Daytime worker passage through two resealable level-one rear walls."""
from dataclasses import dataclass, field, replace
from heapq import heappop, heappush
from .actions import Action, ActionType
from .geometry import Pos
from .grid import OccupancyGrid, shortest_path, interaction_cells, distance_field
from .defense import build_defense_layout, existing_weapons, existing_walls
from .movement import MoveIntent


def gate_sites(turn, config):
    if not config.seal_rear_access or turn.day_index<config.gate_start_day:return ()
    base=turn.team_our.station()
    if not base:return ()
    layout=build_defense_layout(turn);weapons=existing_weapons(turn)
    if len(weapons)!=3 or {w.pos for w in weapons}!=set(layout.weapon_sites[:3]):return ()
    cells=turn.coordinate_frame.normalize_cells(base.footprint())
    x=min(p.x for p in cells)-2;y=max(p.y for p in cells)
    sites=tuple(turn.coordinate_frame.denormalize(Pos(x,yy)) for yy in (y+1,y))
    neutral={z.pos for z in turn.map_info.zones}
    if any(not turn.map_info.contains(p) or p in neutral or p in layout.controller_sites for p in sites):return ()
    return sites


def inside(turn,pos):
    base=turn.team_our.station()
    if not base or pos is None:return False
    cells=turn.coordinate_frame.normalize_cells(base.footprint());p=turn.coordinate_frame.normalize(pos)
    return min(c.x for c in cells)-1<=p.x<=max(c.x for c in cells)+1 and min(c.y for c in cells)-1<=p.y<=max(c.y for c in cells)+1


def planning_grid(turn,role,config,grid=None):
    """Only route estimates may cross our gates; execution still removes first."""
    grid=grid or OccupancyGrid.from_turn(turn,ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
    if not turn.is_day or role.role_type!='worker' or 'stone' not in role.backpack:return grid
    sites=set(gate_sites(turn,config))
    owned={w.pos for w in existing_walls(turn) if w.pos in sites}
    other={p for u in turn.team_enemy.roles for p in u.footprint()}
    other.update(z.pos for z in turn.map_info.zones)
    return replace(grid,blocked=grid.blocked-(owned-other))


def transit_cost(turn,path,config):
    sites=set(gate_sites(turn,config))
    return 2*sum(p in sites for p in path[1:]) if turn.is_day else 0


def return_distances(turn,grid,goals,config):
    sites=set(gate_sites(turn,config)) if turn.is_day else set()
    if not sites:return distance_field(grid,goals)
    dist={p:0 for p in goals if grid.passable(p)};queue=[(0,p) for p in dist]
    from heapq import heapify
    heapify(queue)
    while queue:
        cost,pos=heappop(queue)
        if cost!=dist.get(pos):continue
        for nxt in grid.neighbours(pos):
            score=cost+1+2*int(nxt in sites)
            if score<dist.get(nxt,10000):dist[nxt]=score;heappush(queue,(score,nxt))
    return dist


@dataclass(slots=True)
class GateAccess:
    actor: int | None = None
    gate: Pos | None = None
    entering: bool = True
    phase: str = ''
    started: int = 0
    signature: tuple = ()
    stalls: int = 0
    retry_after: dict[int,int] = field(default_factory=dict)
    status: dict = field(default_factory=dict)
    established: bool = False

    def clear(self):
        self.actor=None;self.gate=None;self.phase='';self.signature=();self.stalls=0

    def apply(self,turn,actions,intents,config,engineer,emergency=()):
        actions=list(actions);intents=list(intents);sites=gate_sites(turn,config)
        self.status={'phase':'inactive'}
        if not sites:self.clear();return actions,intents
        by_actor={i.actor_id:i for i in intents}
        busy={a.actor_id for a in actions}|{a.controller_id for a in actions if a.controller_id is not None}
        walls={w.pos:w for w in existing_walls(turn)}
        if all(p in walls for p in sites):self.established=True
        occupied={p for u in turn.team_our.roles+turn.team_enemy.roles for p in u.footprint()}
        occupied.update(r.pos for r in turn.robots if r.health>0)
        humans=[u for u in turn.team_enemy.roles if u.is_human and u.alive and u.pos]
        def contested(gate):return any(u.pos.distance_to(gate)<=config.gate_enemy_clearance for u in humans)
        def output(role,action=None,move=None,reason=''):
            self.status={'phase':self.phase or reason,'reason':reason,'actor':role.unit_id,
                         'gate':[self.gate.x,self.gate.y] if self.gate else [],'entering':self.entering}
            kept=[a for a in actions if a.actor_id!=role.unit_id]
            moves=[i for i in intents if i.actor_id!=role.unit_id]
            if self.actor is not None:
                moves=[replace(i,avoid_cells=i.avoid_cells|frozenset(sites)) for i in moves]
            if action:kept.append(action)
            if move:moves.append(move)
            return kept,moves
        if self.actor is not None:
            role=turn.team_our.unit(self.actor)
            if not role or not role.alive or self.actor in {a.controller_id for a in actions}:
                self.clear()
            else:
                sig=(role.pos,self.gate in walls)
                self.stalls=self.stalls+1 if sig==self.signature else 0;self.signature=sig
                if self.stalls>=config.gate_stall_limit or turn.round_no-self.started>config.gate_trip_limit:
                    self.retry_after[self.actor]=turn.round_no+5;self.clear()
                else:
                    grid=OccupancyGrid.from_turn(turn,ignore_unit_ids=(role.unit_id,))
                    if self.phase=='cross' and inside(turn,role.pos)==self.entering and role.pos!=self.gate:
                        self.phase='close'
                    if self.phase=='close':
                        if self.gate in walls:self.clear()
                        elif not turn.is_day:
                            self.clear();self.status={'phase':'reseal_wait_daylight'}
                            return actions,intents
                        elif turn.is_day and 'stone' in role.backpack and self.gate not in occupied and role.pos.distance_to(self.gate)==1:
                            return output(role,Action(role.unit_id,ActionType.BUILD,name='wall',targets=(self.gate,)),reason='reseal_after_crossing')
                        else:
                            reason='reseal_blocked' if turn.is_day else 'reseal_wait_daylight'
                            return output(role,move=MoveIntent(role.unit_id,(role.pos,),126,yield_cells=()),reason=reason)
                    elif self.gate in walls:
                        if (turn.is_day or role.unit_id in emergency) and not contested(self.gate):
                            return output(role,Action(role.unit_id,ActionType.REMOVE,targets=(self.gate,)),reason='open_own_gate')
                        return output(role,move=MoveIntent(role.unit_id,(role.pos,),126,yield_cells=()),reason='gate_open_wait')
                    else:
                        landings=tuple(p for p in interaction_cells(grid,self.gate) if p not in sites and inside(turn,p)==self.entering)
                        # Finish the entire crossing before closing; never build on a role.
                        return output(role,move=MoveIntent(role.unit_id,landings,126,yield_cells=()),reason='cross_open_gate')
        # Serve one crossing at a time. Unscheduled roles cannot race through the gap.
        for intent in sorted(intents,key=lambda i:(-i.priority,i.actor_id)):
            role=turn.team_our.unit(intent.actor_id)
            if not role or role.role_type!='worker' or not role.pos or role.unit_id in busy:continue
            if not turn.is_day and role.unit_id not in emergency:continue
            if self.retry_after.get(role.unit_id,0)>turn.round_no:continue
            if 'stone' not in role.backpack and role.unit_id not in emergency:continue
            grid=planning_grid(turn,role,config)
            if not turn.is_day:grid=replace(grid,blocked=grid.blocked-set(walls).intersection(sites))
            path=shortest_path(grid,role.pos,intent.goals,extra_blocked=intent.avoid_cells)
            gate=next((p for p in path[1:] if p in sites),None)
            if not gate or inside(turn,role.pos)==inside(turn,path[-1]):continue
            if role.pos.distance_to(gate)>1:
                real=OccupancyGrid.from_turn(turn,ignore_unit_ids=(role.unit_id,))
                goals=tuple(p for p in interaction_cells(real,gate) if p not in sites and inside(turn,p)==inside(turn,role.pos))
                intents=[replace(i,goals=goals) if i.actor_id==role.unit_id else i for i in intents]
                self.status={'phase':'approach_rear_gate','actor':role.unit_id,'gate':[gate.x,gate.y]}
                continue
            if contested(gate):
                self.status={'phase':'enemy_near_gate','actor':role.unit_id};continue
            needed=3+int(gate in walls)
            if turn.is_day and turn.rounds_until_night<=needed+config.recall_safety_buffer:
                self.status={'phase':'gate_return_deadline','actor':role.unit_id};continue
            self.actor=role.unit_id;self.gate=gate;self.entering=inside(turn,path[-1]);self.phase='cross';self.started=turn.round_no
            self.signature=();self.stalls=0
            return self.apply(turn,actions,intents,config,engineer,emergency)
        # Complete/rebuild the two shutters after the ordinary ring is established.
        worker=turn.team_our.unit(engineer)
        layout=build_defense_layout(turn)
        ring={w.pos for w in existing_walls(turn)}
        missing=[p for p in sites if p not in ring and p not in occupied]
        if (turn.is_day and worker and worker.alive and worker.pos and worker.unit_id not in busy
                and (self.established or set(layout.wall_sites)<=ring) and missing
                and worker.backpack.count('stone')>=len(missing)+1
                and len(walls)<config.max_wall_count):
            intent=by_actor.get(worker.unit_id)
            if (not intent or intent.priority<95 or inside(turn,worker.pos)):
                grid=OccupancyGrid.from_turn(turn,ignore_unit_ids=(worker.unit_id,))
                # Never enclose a role that cannot reopen its own shutter.
                if not any(inside(turn,r.pos) and (r.role_type!='worker' or 'stone' not in r.backpack) for r in turn.controllable):
                    gate=min(missing,key=lambda p:worker.pos.distance_to(p))
                    goals=interaction_cells(grid,gate);path=shortest_path(grid,worker.pos,goals)
                    if path and len(path)+len(missing)+config.recall_safety_buffer<turn.rounds_until_night:
                        self.gate=gate
                        if worker.pos.distance_to(gate)==1:
                            return output(worker,Action(worker.unit_id,ActionType.BUILD,name='wall',targets=(gate,)),reason='seal_rear_access')
                        return output(worker,move=MoveIntent(worker.unit_id,goals,96),reason='prepare_rear_seal')
        if self.status.get('phase')=='inactive':
            self.status={'phase':'sealed' if all(p in walls for p in sites) else 'open_or_incomplete'}
        self.status.update(closed=sum(p in walls for p in sites),enemy_inside=sum(inside(turn,u.pos) for u in humans))
        return actions,intents
