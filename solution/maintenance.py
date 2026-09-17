"""Front-wall support with real adjacency, damage headroom and retreat."""
from .actions import Action,ActionType
from .movement import MoveIntent
from .logistics import LogisticsPlan,estimated_max_health
from .economy import front_walls,upgrade_item
from .defense import build_defense_layout
from .grid import OccupancyGrid,interaction_cells,shortest_path
from .geometry import Pos
from .combat import ROBOT_ATTACK


def support_plan(turn,role,config,threats):
    if not role.pos:return LogisticsPlan()
    walls=front_walls(turn);layout=build_defense_layout(turn)
    grid=OccupancyGrid.from_turn(turn,ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
    station=turn.team_our.station()
    if not station:return LogisticsPlan()
    cells=turn.coordinate_frame.normalize_cells(station.footprint())
    post=turn.coordinate_frame.denormalize(Pos(max(p.x for p in cells)+1,max(p.y for p in cells)+1))
    rear=tuple(p for p in layout.controller_sites if p not in {r.pos for r in turn.controllable if r.unit_id!=role.unit_id})
    fallback=tuple(p for p in layout.rear_corridor if p not in {r.pos for r in turn.controllable if r.unit_id!=role.unit_id})
    def retreat():return LogisticsPlan(move=MoveIntent(role.unit_id,rear or fallback,125))
    # At the requested post, wall 4 is two cells away: move to actual adjacency.
    for wall in walls[:4]:
        incoming=sum((r.attack_power or ROBOT_ATTACK.get(r.role_type,5)) for r in threats if r.pos and r.pos.distance_to(wall.pos)<=(r.attack_range or config.robot_attack_range_fallback)+1)
        threshold=max(int(estimated_max_health(wall)*config.wall_heal_fraction),incoming*2)
        if wall.health>threshold:continue
        item=upgrade_item(wall)
        if item not in role.backpack:item='WallFixer' if 'WallFixer' in role.backpack else ''
        if item:
            goals=interaction_cells(grid,wall.pos)
            if role.pos.distance_to(wall.pos)<=1:
                return LogisticsPlan(action=Action(role.unit_id,ActionType.USE,name=item,targets=(wall.pos,)))
            path=shortest_path(grid,role.pos,goals)
            if path and wall.health>incoming*len(path):return LogisticsPlan(move=MoveIntent(role.unit_id,goals,122))
        if wall.health<=max(int(estimated_max_health(wall)*config.wall_retreat_fraction),incoming*2):return retreat()
    if any(r.pos and r.pos.distance_to(role.pos)<=(r.attack_range or config.robot_attack_range_fallback) for r in threats):return retreat()
    has_goods=any(x=='WallFixer' or x.startswith('WallUpgradeVoucher') for x in role.backpack)
    if not has_goods:return retreat()
    if grid.passable(post) or role.pos==post:return LogisticsPlan(move=MoveIntent(role.unit_id,(post,),100))
    return retreat()
