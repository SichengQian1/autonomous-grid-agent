"""Bounded, redacted operations trace, separate from successful task audit."""
from dataclasses import dataclass,field
import json
from .task_audit import Redactor
from .rules import WEAPON_BUILD_COST


@dataclass(slots=True)
class OperationAudit:
    redactor: Redactor = field(default_factory=Redactor)
    used: int = 0
    dropped: int = 0
    repeats: int = 0
    flow_bytes: dict = field(default_factory=dict)
    previous_keys: dict = field(default_factory=dict)
    previous: dict | None = None
    events: list = field(default_factory=list)
    match_limit: int = 360000
    flow_limit: int = 180000

    def emit(self,turn,stage,data,role=None,flow='operations',critical=False):
        try:
            key=(flow,stage,role)
            encoded=json.dumps(data,sort_keys=True,ensure_ascii=False,default=str)
            signature=self.redactor.fingerprint(encoded)
            if self.previous_keys.get(key)==signature and not critical:
                self.repeats+=1;return
            self.previous_keys[key]=signature
            # Discovery precedes all excerpts, including nested source/LLM text.
            clean=self.redactor.readable(data,4600 if critical else 3500)
            event={'event':'operation','r':turn.round_no,'day':turn.day_index,'role':role,
                   'flow':flow,'stage':stage,'detail':clean,'dropped':self.dropped,'repeats':self.repeats}
            size=len(json.dumps(event,ensure_ascii=False).encode())
            reserve=0 if critical else 16000
            if self.used+size>self.match_limit-reserve or self.flow_bytes.get(flow,0)+size>self.flow_limit-reserve:
                self.dropped+=1;return
            self.used+=size;self.flow_bytes[flow]=self.flow_bytes.get(flow,0)+size
            self.events.append(event)
        except Exception:self.dropped+=1

    def record(self,turn,response,planner):
        try:
            previous=self.previous
            if previous and any(c.get('action')=='summonTreasure' for c in previous['commands'].values()):
                delta=turn.team_our.gold-previous['gold'];unknown=turn.round_no!=previous['r']+1
                for actor,c in previous['commands'].items():
                    action=c.get('action');ok=turn.last_action_results.get(int(actor))
                    if action=='summonTreasure':continue
                    if action=='submitAnswer':unknown=True
                    if action not in ('sell','buy','build'):continue
                    if ok is False:continue
                    if ok is not True:unknown=True;continue
                    price=previous['vendor' if action=='sell' else 'shop'].get(c.get('name'))
                    if action=='build':delta+=WEAPON_BUILD_COST if c.get('name')!='wall' else 0
                    elif price is None:unknown=True
                    elif action=='sell':delta-=price*c.get('num',0)
                    else:delta+=price*c.get('num',0)
                self.emit(turn,'settlement',{'code':turn.last_summon_treasure_result,'gold':None if unknown else delta,
                          'attribution':'uncertain' if unknown else 'successful_economic_actions_removed'},flow='treasure',critical=True)
            for e in planner.treasure.events:
                # Model inputs/outputs are chunked after redaction. A useful trace
                # must not consist solely of the beginning of the prompt.
                content=e.get('input') if e['stage']=='model_request' else e.get('output') if e['stage']=='model_response' else None
                if content is not None:
                    clean=self.redactor.readable(content,14000)
                    text=clean.pop('text');parts=[text[i:i+1600] for i in range(0,len(text),1600)] or ['']
                    for n,part in enumerate(parts):
                        self.emit(turn,'model_trace',{'artifact':e['stage'],'part':n+1,'parts':len(parts),'text':part,**clean},flow='treasure')
                self.emit(turn,e['stage'],{k:v for k,v in e.items() if k!='stage'},flow='treasure',critical=e['stage'] in ('result','opening','validation','memory_limit'))
            planner.treasure.events.clear()
            self.emit(turn,'waiting',{'reason':planner.treasure.reason,'mode':planner.treasure.mode,'version':planner.treasure.version,
                     'analyzed':planner.treasure.analyzed_version,'complete':planner.treasure.complete},flow='treasure')
            self.emit(turn,'handover',{'phase':planner.guard.phase,'backup':planner.guard.backup_id,'confirmed':planner.guard.away})
            for role in turn.controllable:
                duty='pioneer' if role.role_type=='pioneer' else 'support' if role.unit_id==planner.support_id else 'miner'
                if role.unit_id==planner.engineer_id and turn.is_day:duty='engineer'
                data={'duty':duty,'activity':planner.economy.activity.get(role.unit_id),
                      'mining':planner.economy.evidence.get(role.unit_id,{}),'goods':[i for i in role.backpack if 'Voucher' in i or i=='WallFixer']}
                command=response['roleCommandMap'].get(str(role.unit_id),{})
                important=command.get('action') in ('buy','use','build','sell')
                if important or turn.round_no%8==1 or self.previous_keys.get(('duty',role.unit_id))!=(duty,data['activity']):
                    self.emit(turn,'role',data,role.unit_id)
                self.previous_keys[('duty',role.unit_id)]=(duty,data['activity'])
            from .economy import due_defense_targets,scheduled_targets,upgrade_item
            from .rules import DEFAULT_CONFIG
            config=getattr(planner,'audit_config',DEFAULT_CONFIG)
            targets=due_defense_targets(turn,config);ahead=scheduled_targets(turn,config)
            prices={i.name:i.price for i in turn.weapon_shop}
            changed=any(c.get('action') in ('buy','use','build','sell') for c in response['roleCommandMap'].values())
            target_key=tuple((w.unit_id,w.level) for w in targets)
            if changed or turn.round_no%8==1 or self.previous_keys.get(('targets',))!=target_key:
                self.emit(turn,'wall_supply',getattr(planner,'wall_supply_status',{}),planner.support_id)
                self.emit(turn,'upgrade_plan',{'due':[{'id':w.unit_id,'level':w.level,'health':w.health,'item':upgrade_item(w),'deadline_night':turn.day_index} for w in targets],
                    'ahead':[w.unit_id for w in ahead],'gold':turn.team_our.gold,'gap':max(0,sum(prices.get(upgrade_item(w),0) for w in targets)-turn.team_our.gold),
                    'carrier':planner.logistics.carrier_id,'stage':planner.logistics.stage})
            self.previous_keys[('targets',)]=target_key
            self.previous={'r':turn.round_no,'gold':turn.team_our.gold,'commands':response['roleCommandMap'],
                           'vendor':{i.name:i.price for i in turn.vendor_shop},'shop':prices}
        except Exception:self.dropped+=1

    def drain(self):
        events=self.events;self.events=[];return events
