"""Read-only summaries of bounded operating and treasure evidence."""
from collections import Counter
import json


def summarize_operations(events,day=None,role=None,stage=None,limit=20):
    selected=[e for e in events if e.get('event')=='operation' and (day is None or e.get('day')==day)
              and (role is None or str(e.get('role'))==str(role)) and (stage is None or e.get('stage')==stage)]
    result={'events':len(selected),'stages':dict(Counter(e.get('stage','unknown') for e in selected)),
            'dropped':max((e.get('dropped',0) for e in selected),default=0),
            'merged_repetitions':max((e.get('repeats',0) for e in selected),default=0),
            'truncated_details':sum(bool(e.get('detail',{}).get('truncated')) for e in selected)}
    treasure_failures=Counter();seen_failures=set();bindings={};semantics=None
    for e in selected:
        if e.get('flow')!='treasure':continue
        try:detail=json.loads(e.get('detail',{}).get('text','{}'))
        except (TypeError,ValueError):continue
        if not isinstance(detail,dict):continue
        if e.get('stage')=='candidate':
            semantics=detail.get('semantics')
            bindings=dict(Counter(c.get('binding','unknown') for c in detail.get('material_claims',{}).values() if isinstance(c,dict)))
        failures=detail.get('failures',[]) if e.get('stage')=='candidate' else [detail] if e.get('stage')=='validation' else []
        for failure in failures:
            reason=failure.get('reason') if isinstance(failure,dict) else failure
            key=(detail.get('request_id',e.get('r')),reason)
            if isinstance(reason,str) and key not in seen_failures:
                seen_failures.add(key);treasure_failures[reason]+=1
    result['treasure_validation_reasons']=dict(treasure_failures)
    result['last_material_bindings']=bindings
    result['last_treasure_semantics']=semantics
    # Turn records keep the production and item-use timeline even when the
    # detailed operation-event budget has been exhausted.
    workers={};timeline=[];bombs=Counter();bomb_reasons=Counter();requests=responses=None;last_failure={};attempts=spent=None
    for e in events:
        if e.get('event')!='turn' or (day is not None and e.get('d')!=day):continue
        commands={str(c[0]):c for c in e.get('commands',[]) if len(c)>=4}
        diagnostics=e.get('diagnostics',{})
        if 'treasureRequest' in diagnostics:requests=max(requests or 0,diagnostics['treasureRequest'])
        if 'treasureResponses' in diagnostics:responses=max(responses or 0,diagnostics['treasureResponses'])
        if diagnostics.get('treasureValidation'):last_failure=diagnostics['treasureValidation']
        if 'treasureAttempts' in diagnostics:attempts=diagnostics['treasureAttempts']
        if 'treasureMaterialSpent' in diagnostics:spent=diagnostics['treasureMaterialSpent']
        bomb=diagnostics.get('surplusBomb',{})
        if role is None or str(bomb.get('actor'))==str(role):bomb_reasons.update([bomb.get('reason','unrecorded')])
        for u in e.get('roles',[]):
            if len(u)<2 or u[1]!='worker' or (role is not None and str(u[0])!=str(role)):continue
            key=(e.get('d'),str(u[0]));entry=workers.setdefault(key,{'actions':Counter(),'idle_reasons':Counter()})
            if len(u)>3 and isinstance(u[3],(int,float)) and u[3]<=0:
                entry['actions']['dead']+=1;continue
            c=commands.get(str(u[0]));entry['actions'][c[1] if c else 'idle']+=1
            if not c:entry['idle_reasons'][diagnostics.get('economy',{}).get(str(u[0]),'recall_or_support_or_unrecorded')]+=1
        for c in commands.values():
            if c[1] not in ('buy','use','build') or (role is not None and str(c[0])!=str(role)):continue
            if c[2]=='Bomb':bombs[c[1]]+=1
            if c[1]!='build' and not (c[2] in ('WallFixer','Bomb') or 'UpgradeVoucher' in c[2]):continue
            if len(timeline)<limit:
                timeline.append({'round':e.get('r'),'day':e.get('d'),'role':c[0],'action':c[1],'item':c[2],'quantity':c[3],
                    'gold':e.get('gold'),'front_walls':e.get('defenseSchedule',{}).get('frontWalls',[]),
                    'supply':diagnostics.get('wallSupply',{})})
    result['worker_days']=[{'day':d,'role':r,**{k:dict(v) for k,v in entry.items()}} for (d,r),entry in list(workers.items())[:20]]
    result['bomb_commands']=dict(bombs);result['bomb_reasons']=dict(bomb_reasons)
    result['treasure_requests']=requests;result['treasure_responses']=responses
    result['last_treasure_validation_failure']=last_failure
    result['treasure_attempts']=attempts;result['treasure_material_spent']=spent
    if day is not None or role is not None:result['maintenance_timeline']=timeline
    if day is not None or role is not None or stage is not None:
        result['details']=selected[:limit];result['omitted_details']=max(0,len(selected)-limit)
    return result
