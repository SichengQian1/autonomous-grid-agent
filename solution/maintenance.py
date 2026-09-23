"""Front-wall support with real adjacency, damage headroom and retreat."""
from .actions import Action,ActionType
from .movement import MoveIntent
from .logistics import LogisticsPlan,estimated_max_health
from .economy import front_walls,upgrade_item,wall_level_goal,due_defense_targets,scheduled_targets,front_wall_number
from .defense import build_defense_layout
from .grid import OccupancyGrid,interaction_cells,shortest_path
from .geometry import Pos
from .combat import ROBOT_ATTACK


def support_plan(turn,role,config,threats):
    if not role.pos:return LogisticsPlan()
    from .wall_supply import wall_use_item, wall_target
    walls=front_walls(turn);due=due_defense_targets(turn,config)
    walls += [w for w in turn.team_our.roles if w.role_type=="wall" and w.alive and wall_target(turn,w)>1 and w not in walls]
    walls+= [w for w in due if w.role_type=='wall' and w not in walls]
    layout=build_defense_layout(turn)
    grid=OccupancyGrid.from_turn(turn,ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
    station=turn.team_our.station()
    if not station:return LogisticsPlan()
    cells=turn.coordinate_frame.normalize_cells(station.footprint())
    post=turn.coordinate_frame.denormalize(Pos(max(p.x for p in cells)+1,max(p.y for p in cells)+1))
    rear=tuple(p for p in layout.controller_sites if p not in {r.pos for r in turn.controllable if r.unit_id!=role.unit_id})
    fallback=tuple(p for p in layout.rear_corridor if p not in {r.pos for r in turn.controllable if r.unit_id!=role.unit_id})
    def retreat():return LogisticsPlan(move=MoveIntent(role.unit_id,fallback or rear,125),reason="wall_or_role_exposure_retreat",evidence=tuple((w.unit_id,w.health,s,inc) for _,_,s,w,_,_,inc in risks))
    # These are conservative exposure estimates, not engine target predictions.
    risks=[]
    for wall in walls:
        immediate,approaching=wall_damage_risk(wall,config,threats)
        goals=interaction_cells(grid,wall.pos)
        path=shortest_path(grid,role.pos,goals) if role.pos.distance_to(wall.pos)>1 else [role.pos]
        steps=max(0,len(path)-1) if path else 10000
        item=wall_use_item(turn,wall,role,config,approaching,steps)
        threshold=max(int(estimated_max_health(wall)*config.wall_heal_fraction),approaching*(steps+2))
        if not item and wall.health>threshold:continue
        headroom=wall.health/max(immediate,approaching,1)
        risks.append((headroom,wall.health,steps,wall,item,goals,approaching))
    endangered=False
    for _,_,steps,wall,item,goals,incoming in sorted(risks,key=lambda x:x[:3]):
        if item:
            if role.pos.distance_to(wall.pos)<=1:
                return LogisticsPlan(action=Action(role.unit_id,ActionType.USE,name=item,targets=(wall.pos,)),reason="wall_upgrade_heal" if item.startswith("WallUpgrade") else "wall_low_health_repair",evidence=(wall.unit_id,wall.health,steps,incoming,item))
            if steps<10000 and wall.health>incoming*(steps+1):
                return LogisticsPlan(move=MoveIntent(role.unit_id,goals,122),reason="reachable_wall_rescue",evidence=(wall.unit_id,wall.health,steps,incoming,item))
        endangered |= wall.health<=max(int(estimated_max_health(wall)*config.wall_retreat_fraction),incoming*2)
    if endangered:return retreat()
    if any(r.pos and r.pos.distance_to(role.pos)<=(r.attack_range or config.robot_attack_range_fallback) for r in threats):return retreat()
    has_goods=any(x=='WallFixer' or x.startswith('WallUpgradeVoucher') for x in role.backpack)
    if not has_goods:return retreat()
    if grid.passable(post) or role.pos==post:return LogisticsPlan(move=MoveIntent(role.unit_id,(post,),100),reason="support_wait_with_goods")
    return retreat()


def wall_damage_risk(wall,config,threats):
    """Return in-range and one-step exposure upper estimates (not additive targets)."""
    immediate=approaching=0
    for robot in threats:
        if not robot.pos or robot.health<=0:continue
        reach=robot.attack_range or config.robot_attack_range_fallback
        power=robot.attack_power or ROBOT_ATTACK.get(robot.role_type,5)
        distance=robot.pos.distance_to(wall.pos)
        if distance<=reach:immediate+=power
        if distance<=reach+1:approaching+=power
    return immediate,approaching
