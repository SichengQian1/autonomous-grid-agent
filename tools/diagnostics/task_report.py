"""Read-only analysis of sanitized task events and older compact turn records."""
from collections import Counter


def summarize_tasks(events, task_id=None, detail_limit=24):
    if not any(e.get("event")=="task" for e in events):return summarize_legacy(events)
    tasks={};failures=Counter();reuse=Counter();details=[]
    for event in events:
        if event.get('event')!='task':continue
        ident=event.get('task_id');kind=event.get('kind');item=tasks.setdefault(ident,{
            'task_id':ident,'type':event.get('task_type',0),'ordinal':event.get('type_ordinal'),
            'submissions':0,'timeline':[],'outcome':'unknown'})
        if len(item['timeline'])<48:item['timeline'].append([event.get('r'),kind,event.get('status') or event.get('purpose') or event.get('reason')])
        if kind=='accept':item['start']=event.get('r')
        elif kind=='submit':item['submissions']+=1
        elif kind=='end':item.update(end=event.get('r'),elapsed=event.get('elapsed'),outcome=event.get('outcome'),
            task_gold=event.get('task_gold'),commands=event.get('commands'),llm_requests=event.get('llm_requests'))
        if kind=='execution' and not event.get('documents') and event.get('status') not in ('ok','script_ok','api_checked','documents_read',None):
            key=str(event.get('status'))+':'+str(event.get('schema_details',{}).get('field',''))
            failures[key]+=1
        if kind=='plan_rejected':failures['plan_rejected:'+str(event.get('reason'))]+=1
        use=event.get('reuse',{})
        if use:
            reuse[use.get('reason','unknown')]+=1
            if use.get('used'):item['reused_from']=use.get('source');item['reuse_level']=use.get('level')
        if task_id and ident==task_id and len(details)<detail_limit:details.append(event)
    counts={}
    for item in tasks.values():
        count=counts.setdefault(str(item['type']),Counter())
        count[item['outcome']]+=1;count['total']+=1
        if item['submissions']==0:count['unsubmitted']+=1
    by_ordinal={}
    for item in tasks.values():
        if isinstance(item.get('elapsed'),int):
            key=f"{item['type']}:{item['ordinal']}";by_ordinal[key]={'elapsed':item['elapsed'],'commands':item.get('commands'),
                   'outcome':item['outcome'],'reused':bool(item.get('reused_from'))}
    return {'by_type':{k:dict(v) for k,v in counts.items()},'failures':dict(failures),
            'reuse':dict(reuse),'by_type_ordinal':by_ordinal,
            'tasks':list(tasks.values())[:32], 'details':details,
            'details_limited':bool(task_id and len(details)>=detail_limit)}


def summarize_legacy(events):
    """Best-effort old log attribution; missing prices stay explicitly unknown."""
    tasks=[];active=None;previous=None;zones=[];ordinals=Counter()
    for e in events:
        if e.get('event')!='turn':continue
        if e.get('zones'):zones=e['zones']
        if active and previous and e.get('r')==previous.get('r',-2)+1:
            old=previous.get('diagnostics',{});now=e.get('diagnostics',{})
            full=now.get('taskCompleted',0)>old.get('taskCompleted',0)
            ended=full or now.get('taskFailed',0)>old.get('taskFailed',0)
            if ended:
                delta=e.get('gold',0)-previous.get('gold',0);unknown=False
                for c in previous.get('commands',[]):
                    if c[1] not in ('sell','buy','build','summonTreasure'):continue
                    ok=e.get('results',{}).get(str(c[0]))
                    if ok is False:continue
                    if ok is not True:unknown=True;continue
                    if c[1]=='sell' and c[2] in previous.get('prices',{}):delta-=previous['prices'][c[2]]*c[3]
                    elif c[1]=='build':delta+=0 if c[2]=='wall' else 25
                    else:unknown=True
                outcome='full' if full else 'unknown' if unknown else 'partial' if delta>0 else 'zero' if delta==0 else 'unknown'
                active.update(end=e['r'],elapsed=e['r']-active['start'],outcome=outcome,task_gold=None if unknown else delta)
                tasks.append(active);active=None
        for c in e.get('commands',[]):
            if c[1]=='acceptTask':
                position=next((u[2] for u in e.get('roles',[]) if str(u[0])==str(c[0])),None)
                category=0
                if position:
                    matches=[(max(abs(p[0]-position[0]),abs(p[1]-position[1])),k) for k,p in zones if 'taskpoint' in k.lower()]
                    if matches:
                        distance,key=min(matches)
                        if distance<=1 and key[-1:] in ('1','2'):category=int(key[-1])
                ordinals[category]+=1
                active={'task_id':f'T{len(tasks)+1:03d}','type':category,'ordinal':ordinals[category],'start':e['r'],'submissions':0,'outcome':'unknown'}
            elif c[1]=='submitAnswer' and active:active['submissions']+=1
        previous=e
    if active:tasks.append(active)
    counts={}
    for item in tasks:
        counter=counts.setdefault(str(item['type']),Counter());counter[item['outcome']]+=1;counter['total']+=1
        if not item['submissions']:counter['unsubmitted']+=1
    return {'by_type':{k:dict(v) for k,v in counts.items()},'tasks':tasks,'evidence':'legacy_compact; execution details and reuse unavailable'}
