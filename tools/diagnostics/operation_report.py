"""Read-only summaries of bounded operating and treasure evidence."""
from collections import Counter


def summarize_operations(events,day=None,role=None,stage=None,limit=20):
    selected=[e for e in events if e.get('event')=='operation' and (day is None or e.get('day')==day)
              and (role is None or str(e.get('role'))==str(role)) and (stage is None or e.get('stage')==stage)]
    result={'events':len(selected),'stages':dict(Counter(e.get('stage','unknown') for e in selected)),
            'dropped':max((e.get('dropped',0) for e in selected),default=0),
            'merged_repetitions':max((e.get('repeats',0) for e in selected),default=0),
            'truncated_details':sum(bool(e.get('detail',{}).get('truncated')) for e in selected)}
    if day is not None or role is not None or stage is not None:
        result['details']=selected[:limit];result['omitted_details']=max(0,len(selected)-limit)
    return result
