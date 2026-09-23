"""Read-only summaries of bounded operating and treasure evidence."""
from collections import Counter


def summarize_operations(events,day=None,role=None,stage=None,limit=20):
    selected=[e for e in events if e.get('event')=='operation' and (day is None or e.get('day')==day)
              and (role is None or str(e.get('role'))==str(role)) and (stage is None or e.get('stage')==stage)]
    result={'events':len(selected),'stages':dict(Counter(e.get('stage','unknown') for e in selected)),
            'dropped':max((e.get('dropped',0) for e in selected),default=0),
            'merged_repetitions':max((e.get('repeats',0) for e in selected),default=0),
            'truncated_details':sum(bool(e.get('detail',{}).get('truncated')) for e in selected)}
    # Turn records keep the production and item-use timeline even when the
    # detailed operation-event budget has been exhausted.
    workers={};timeline=[]
    for e in events:
        if e.get('event')!='turn' or (day is not None and e.get('d')!=day):continue
        commands={str(c[0]):c for c in e.get('commands',[]) if len(c)>=4}
        diagnostics=e.get('diagnostics',{})
        for u in e.get('roles',[]):
            if len(u)<2 or u[1]!='worker' or (role is not None and str(u[0])!=str(role)):continue
            key=(e.get('d'),str(u[0]));entry=workers.setdefault(key,{'actions':Counter(),'idle_reasons':Counter()})
            if len(u)>3 and isinstance(u[3],(int,float)) and u[3]<=0:
                entry['actions']['dead']+=1;continue
            c=commands.get(str(u[0]));entry['actions'][c[1] if c else 'idle']+=1
            if not c:entry['idle_reasons'][diagnostics.get('economy',{}).get(str(u[0]),'recall_or_support_or_unrecorded')]+=1
        for c in commands.values():
            if c[1] not in ('buy','use','build') or (role is not None and str(c[0])!=str(role)):continue
            if c[1]!='build' and not (c[2]=='WallFixer' or 'UpgradeVoucher' in c[2]):continue
            if len(timeline)<limit:
                timeline.append({'round':e.get('r'),'day':e.get('d'),'role':c[0],'action':c[1],'item':c[2],'quantity':c[3],
                    'gold':e.get('gold'),'front_walls':e.get('defenseSchedule',{}).get('frontWalls',[]),
                    'supply':diagnostics.get('wallSupply',{})})
    result['worker_days']=[{'day':d,'role':r,**{k:dict(v) for k,v in entry.items()}} for (d,r),entry in list(workers.items())[:20]]
    if day is not None or role is not None:result['maintenance_timeline']=timeline
    if day is not None or role is not None or stage is not None:
        result['details']=selected[:limit];result['omitted_details']=max(0,len(selected)-limit)
    return result
