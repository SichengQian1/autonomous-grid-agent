"""Read-only activity counts. Missing turns are unknown, never inferred as idle."""
from collections import Counter


def classify_pioneer(event):
    role=next((r for r in event.get('roles',[]) if len(r)>3 and r[1]=='pioneer'),None)
    if not role:return 'not_observed_alive'
    actor=str(role[0]);diag=event.get('diagnostics',{});signals=event.get('signals',{})
    commands=event.get('commands',[])
    if any(len(c)>5 and c[1]=='attack' and str(c[5])==actor for c in commands):return 'firing'
    command=next((c for c in commands if str(c[0])==actor),None)
    if command:return command[1]
    if signals.get('task'):return 'task_wait_or_compute'
    if signals.get('llm') or signals.get('sandbox'):return 'response_processing'
    if diag.get('treasureStage')=='at_site_wait_window':return 'treasure_window_wait'
    if event.get('phase')=='night':
        reasons=[w[2] for w in diag.get('weapons',[]) if len(w)>2]
        weapons=[r for r in event.get('roles',[]) if r[1] in ('rocket','railgun','gatling') and r[2]]
        adjacent=role[2] and any(max(abs(role[2][i]-w[2][i]) for i in (0,1))<=1 for w in weapons)
        if adjacent and any(r not in ('clear','day') for r in reasons):return 'gun_guard_wait'
    if diag.get('gunHandover') in ('vacate_common_post','replacement_approach','enter_common_post'):
        return 'handover_wait'
    if role[0] in diag.get('recalledRoles',[]):return 'recalled_wait'
    return 'unassigned_no_command'


def summarize_pioneer(events,day=None,detail_limit=24):
    turns={e['r']:e for e in events if e.get('event')=='turn' and isinstance(e.get('r'),int)}
    days={};spans=[]
    last=None
    for r,e in sorted(turns.items()):
        d=e.get('d',(r-1)//130+1)
        if day is not None and d!=day:continue
        counts=days.setdefault(d,Counter());kind=classify_pioneer(e);counts[kind]+=1
        if kind=='unassigned_no_command':
            if last and last['day']==d and last['end']==r-1 and last['phase']==e.get('phase'):
                last['end']=r;last['count']+=1
            else:
                last={'day':d,'phase':e.get('phase'),'start':r,'end':r,'count':1};spans.append(last)
        else:last=None
    return {'days':[{'day':d,'observed_turns':sum(c.values()),'missing_turns':max(0,130-sum(c.values())),
                     'activity':dict(c)} for d,c in sorted(days.items())],
            'unassigned_intervals':spans[:detail_limit],'intervals_omitted':max(0,len(spans)-detail_limit),
            'interpretation':'No command is only a reuse opportunity, not proof of a bug. Missing telemetry is unknown; guard/task/window waits are separate.'}
