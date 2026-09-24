"""Front-wall support with real adjacency, damage headroom and retreat."""
from dataclasses import replace
from .actions import Action,ActionType
from .movement import MoveIntent
from .logistics import LogisticsPlan,estimated_max_health
from .economy import front_walls,upgrade_item,wall_level_goal,due_defense_targets,scheduled_targets,front_wall_number
from .defense import build_defense_layout
from .grid import OccupancyGrid,interaction_cells,shortest_path
from .geometry import Pos
from .combat import ROBOT_ATTACK


def support_plan(turn,role,config,threats,recent_damage=0,claimed=(),committed_id=None):
    if not role.pos:return LogisticsPlan()
    from .wall_supply import wall_use_item, wall_target
    walls=front_walls(turn);due=due_defense_targets(turn,config)
    walls += [w for w in turn.team_our.roles if w.role_type=="wall" and w.alive and wall_target(turn,w)>1 and w not in walls]
    walls+= [w for w in due if w.role_type=='wall' and w not in walls]
    # Upgrade policy is deliberately limited; repair coverage is not. A weak
    # unplanned flank can expose the station despite a healthy front array.
    walls += [w for w in turn.team_our.roles if w.role_type=='wall' and w.alive and w.pos and w not in walls]
    walls = [w for w in walls if w.pos not in claimed]
    layout=build_defense_layout(turn)
    grid=OccupancyGrid.from_turn(turn,ignore_unit_ids=tuple(r.unit_id for r in turn.controllable))
    station=turn.team_our.station()
    if not station:return LogisticsPlan()
    cells=turn.coordinate_frame.normalize_cells(station.footprint())
    post=turn.coordinate_frame.denormalize(Pos(max(p.x for p in cells)+1,max(p.y for p in cells)+1))
    rear=tuple(p for p in layout.controller_sites if p not in {r.pos for r in turn.controllable if r.unit_id!=role.unit_id})
    fallback=tuple(p for p in layout.rear_corridor if p not in {r.pos for r in turn.controllable if r.unit_id!=role.unit_id})
    def retreat(reason='wall_or_role_exposure_retreat'):return LogisticsPlan(move=MoveIntent(role.unit_id,fallback or rear,125),reason=reason,evidence=tuple((w.unit_id,w.health,s,inc) for _,_,s,w,_,_,inc in risks))
    # These are conservative exposure estimates, not engine target predictions.
    risks=[]
    barriers=[w for w in turn.team_our.roles if w.role_type=='wall' and w.alive and w.pos]
    front=max(p.x for p in cells)+2
    def exposed(pos):
        return support_exposed(pos,barriers,threats,config)
    # Evaluate the worker's actual exposure, not a union of every wall's danger.
    # A repair item does not protect a worker after robots have entered the ring.
    if recent_damage>0 and threats:return retreat('support_recent_damage_retreat')
    if exposed(role.pos):return retreat('support_breach_exposure_retreat')
    danger=support_danger_cells(turn,barriers,threats,config)
    grid=replace(grid,blocked=grid.blocked|danger)
    for wall in walls:
        immediate,approaching=wall_damage_risk(wall,config,threats)
        goals=tuple(p for p in interaction_cells(grid,wall.pos)
                    if turn.coordinate_frame.normalize(p).x<front and not exposed(p))
        path=shortest_path(grid,role.pos,goals) if role.pos.distance_to(wall.pos)>1 else [role.pos]
        steps=max(0,len(path)-1) if path else 10000
        item=wall_use_item(turn,wall,role,config,approaching,steps,committed=wall.unit_id==committed_id)
        threshold=max(int(estimated_max_health(wall)*config.wall_heal_fraction),approaching*(steps+2))
        if not item and wall.health>threshold:continue
        headroom=wall.health/max(immediate,approaching,1)
        risks.append((headroom,wall.health,steps,wall,item,goals,approaching))
    endangered=False
    for _,_,steps,wall,item,goals,incoming in sorted(risks,key=lambda x:(x[3].unit_id!=committed_id,*x[:3])):
        if item:
            if role.pos.distance_to(wall.pos)<=1:
                return LogisticsPlan(action=Action(role.unit_id,ActionType.USE,name=item,targets=(wall.pos,)),reason="wall_upgrade_heal" if item.startswith("WallUpgrade") else "wall_low_health_repair",evidence=(wall.unit_id,wall.health,steps,incoming,item))
            if steps<10000 and wall.health>incoming*(steps+1):
                return LogisticsPlan(move=MoveIntent(role.unit_id,goals,122,avoid_cells=danger),reason="reachable_wall_rescue",evidence=(wall.unit_id,wall.health,steps,incoming,item))
        endangered |= wall.health<=max(int(estimated_max_health(wall)*config.wall_retreat_fraction),incoming*2)
    has_goods=any(x=='WallFixer' or x.startswith('WallUpgradeVoucher') for x in role.backpack)
    if not has_goods:return retreat('support_no_repair_goods')
    for _,_,steps,wall,item,_,incoming in risks:
        can_restore=('WallFixer' in role.backpack or
                     (wall.level<wall_target(turn,wall) and f'WallUpgradeVoucher{wall.level}' in role.backpack))
        if steps==0 and not item and incoming>0 and wall.health<=incoming*2 and (not can_restore or wall.health<=incoming):
            return retreat()
    # Stay behind a live barrier while stocked. A remote doomed wall must not
    # make this protected worker bounce between rescue and the rear corridor.
    nearby=any(role.pos.distance_to(w.pos)<=1 for w in walls)
    if nearby and not exposed(role.pos):
        return LogisticsPlan(move=MoveIntent(role.unit_id,(role.pos,),100),reason='support_hold_protected',evidence=(('unreachable_wall_risk',endangered),))
    occupied={r.pos for r in turn.controllable if r.unit_id!=role.unit_id}
    posts=tuple(p for p in (post,)+post.neighbours() if p not in occupied
                and (grid.passable(p) or p==role.pos) and not exposed(p)
                and turn.coordinate_frame.normalize(p).x<front)
    if posts:return LogisticsPlan(move=MoveIntent(role.unit_id,posts,100,avoid_cells=danger),reason="support_wait_with_goods")
    return retreat()


def support_exposed(pos,walls,threats,config):
    """A screening heuristic based on movement-blocking walls, not target truth.

    Range alone caused retreat behind intact walls. Nearby robots with no wall
    on their direct approach still count as exposure, including side intrusion.
    Low wall health is handled by rescue headroom separately each turn.
    """
    occupied={w.pos for w in walls if w.health>0}
    for robot in threats:
        if not robot.pos or robot.health<=0:continue
        distance=robot.pos.distance_to(pos)
        if distance>(robot.attack_range or config.robot_attack_range_fallback):continue
        if not _screened(pos,robot.pos,occupied):return True
    return False


def _screened(pos,origin,occupied):
    distance=origin.distance_to(pos)
    return any(Pos(round(origin.x+(pos.x-origin.x)*i/distance),
                   round(origin.y+(pos.y-origin.y)*i/distance)) in occupied
               for i in range(1,distance))


def support_danger_cells(turn,walls,threats,config):
    occupied={w.pos for w in walls if w.health>0};danger=set()
    for robot in threats:
        if not robot.pos or robot.health<=0:continue
        reach=robot.attack_range or config.robot_attack_range_fallback
        for x in range(max(0,robot.pos.x-reach),min(turn.map_info.width,robot.pos.x+reach+1)):
            for y in range(max(0,robot.pos.y-reach),min(turn.map_info.height,robot.pos.y+reach+1)):
                pos=Pos(x,y)
                if not _screened(pos,robot.pos,occupied):danger.add(pos)
    return frozenset(danger)


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
