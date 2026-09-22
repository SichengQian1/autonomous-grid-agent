"""Match-local source memory and evidence-bound treasure preparation/expedition.

The model interprets narrative effects. The program verifies source membership,
shop binding, multiplicity, geometry, time and action feedback independently.
"""
from collections import Counter
from dataclasses import dataclass, field
import hashlib
import json
from .actions import Action, ActionType
from .geometry import Pos
from .grid import distance_field, interaction_cells, shortest_path
from .movement import MoveIntent
from .route_safety import safe_grid, escape_intent
from .travel import TravelBudget


def fingerprint(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


@dataclass(slots=True)
class TreasureKnowledge:
    position: Pos | None = None
    opening_day: int | None = None
    items: tuple[str,...] = ()
    confidence: float = 0.0  # Compatibility only; never used as execution evidence.
    exhausted: bool = False
    attempted: set = field(default_factory=set)
    phase: str = 'any'
    end_day: int = 10
    evidence_days: tuple = ()
    sources: dict = field(default_factory=dict)
    seen: set = field(default_factory=set)
    memory_bytes: int = 0
    omitted: int = 0
    version: int = 0
    analyzed_version: int = -1
    catalog: dict = field(default_factory=dict)
    catalog_hash: str = ''
    request_version: int = -1
    request_sources: set = field(default_factory=set)
    recall: list = field(default_factory=list)
    constraints: dict = field(default_factory=dict)
    materials: dict = field(default_factory=dict)
    complete: bool = False
    mode: str = 'unknown'
    reason: str = 'no_rumor'
    events: list = field(default_factory=list)
    pending_attempt: tuple | None = None
    pending_round: int = 0
    current_round: int = 0
    candidate_version: int = 0
    rejected: set = field(default_factory=set)
    last_request_signature: str = ''

    def emit(self, stage, **data):
        if len(self.events)<40:self.events.append({'stage':stage,**data})

    def observe(self, turn):
        self.current_round=turn.round_no
        catalog={i.name:{'description':i.description[:6000],'price':i.price,'original_length':len(i.description)} for i in turn.weapon_shop[:128]}
        digest=fingerprint(json.dumps({name:item['description'] for name,item in catalog.items()},sort_keys=True,ensure_ascii=False))
        self.catalog=catalog
        if digest!=self.catalog_hash:
            self.catalog_hash=digest;self.version+=1
            self.emit('catalog',items=len(catalog),described=sum(bool(i['description']) for i in catalog.values()))
        text=turn.world_news.folk_legends
        if not text:return
        h=fingerprint(text)
        if h in self.seen:return
        if len(self.seen)>=256:
            self.omitted+=len(text.encode());self.emit('memory_limit',omitted_bytes=self.omitted);return
        self.seen.add(h);self.version+=1
        # Keep old evidence, not just the suffix of an ever-growing prompt.
        # Segment boundaries overlap so short requirements survive splits.
        added=[]
        for offset in range(0,len(text),1100):
            segment=text[max(0,offset-100):offset+1100]
            n=len(segment.encode());sid='S'+fingerprint(segment)
            if sid in self.sources:continue
            if self.memory_bytes+n>196608:
                self.omitted+=n;continue
            self.sources[sid]={'id':sid,'day':turn.day_index,'offset':max(0,offset-100),'text':segment,'fingerprint':fingerprint(segment)}
            self.memory_bytes+=n;added.append(sid)
        self.emit('source',day=turn.day_index,input_length=len(text),segments=added,
                  memory_bytes=self.memory_bytes,omitted_bytes=self.omitted,excerpt=text)
        # New clues may correct old ones. Re-evaluate before buying/sacrificing.
        self.reason='new_evidence_pending'

    def needs_analysis(self):
        return not self.exhausted and bool(self.sources) and (self.version!=self.analyzed_version or bool(self.recall))

    def prompt(self, official='', source_day=1):
        relevant=[]
        # Explicit backreferences come first, followed by every previously used
        # evidence source, then unseen/new segments. The index enables recall.
        def refs(value):
            if isinstance(value,dict):
                if isinstance(value.get('source'),str):relevant.append(value['source'])
                for v in value.values():refs(v)
            elif isinstance(value,list):
                for v in value:refs(v)
        refs(self.constraints)
        ordered=list(dict.fromkeys(self.recall+relevant+list(reversed(self.sources))))
        selected=[];used=0;self.request_sources=set()
        for sid in ordered:
            source=self.sources.get(sid)
            if not source:continue
            size=len(json.dumps(source,ensure_ascii=False))
            if used+size>14000:continue
            selected.append(source);used+=size;self.request_sources.add(sid)
        self.request_version=self.version;self.recall=[]
        index=[{'id':k,'day':v['day'],'offset':v['offset'],'preview':v['text'][:50]} for k,v in self.sources.items()]
        # All source IDs remain discoverable; previews, catalog and old model prose
        # get independent budgets, so old clue IDs never fall off a suffix slice.
        index_size=len(json.dumps(index,ensure_ascii=False))
        if index_size>9000:index=[{k:v for k,v in row.items() if k!='preview'} for row in index]
        catalog={};catalog_used=0;catalog_omitted=[]
        for name,item in self.catalog.items():
            size=len(json.dumps(item,ensure_ascii=False))+len(name)
            if catalog_used+size>10000:catalog_omitted.append(name);continue
            catalog[name]=item;catalog_used+=size
        prior=self.constraints if len(json.dumps(self.constraints,ensure_ascii=False))<=5000 else {'known_materials':self.materials,'prior_constraints_omitted':True}
        payload={'sources':selected,'source_index':index,
                 'omitted_source_count':len(self.sources)-len(selected),'omitted_memory_bytes':self.omitted,
                 'previous_constraints':prior,'shop':catalog,'catalog_omitted':catalog_omitted,'official':official[:6000],'official_original_length':len(official),'official_day':source_day}
        instruction='''Interpret folk treasure clues separately from official market news and task puzzles. Unknown map/mode stays unknown. Return strict JSON with market:[] and treasure object. Never use past-map answers. Reconcile corrections/exclusions and report unresolved conflicts; a new source can supersede an old conclusion only with explicit evidence. Each evidence is {source:"source ID",quote:"exact source substring"}. If relevant old evidence is omitted, return treasure:{lookup:[source IDs]} first. Do not guess an omitted source.
Treasure schema: {mode:"treasure|unknown|none",materials:[{item:"exact current shop name",quantity:positive integer,effect:"required effect",shop_quote:"exact description substring OR exact item name when directly named by rumor",evidence:[evidence],quantity_evidence:[evidence]}],kind_count:integer|null,total_quantity:integer|null,count_evidence:[evidence],materials_complete:boolean,location:{x:integer,y:integer,evidence:[evidence]}|null,window:{day:integer,end_day:integer,phase:"any|day|night",evidence:[evidence]}|null,conflicts:[],unknown:[],exclusions:[],resolutions:[]}. Evidence must establish each quantity, not assume one per type. "n kinds" is distinct types, not total quantity. Resolve times relative to source day, use actual map coordinates from current clues, include derivation in unknown if not proven. Emit every individually proven material even if the rest, location or time are unknown: partial procurement is useful. Same-day complete clues are valid. Match effects against actual shop descriptions, never a fixed dictionary or self-reported confidence. Set materials_complete only when all requested effects/types/quantities are covered.
Market schema: [{ore:"iron|copper|stone",start_day:integer,end_day:integer,price:number|null,closed:boolean,rising:boolean,recovery:boolean,evidence:"exact official quote",confidence:number}]. No fixed price day; explicit recovery cancels restrictions in its own window.
'''
        result=instruction+json.dumps(payload,ensure_ascii=False)
        self.last_request_signature=fingerprint(result)
        self.emit('model_request',purpose='incremental_constraints',version=self.request_version,input_length=len(result),omitted_sources=len(self.sources)-len(selected),input=payload)
        return result

    def _evidence(self, values):
        if not isinstance(values,list) or not values:return False
        return all(isinstance(e,dict) and isinstance(e.get('quote'),str) and len(e['quote'])>=3
                   and isinstance(e.get('source'),str) and e['source'] in self.request_sources
                   and e['quote'] in self.sources[e['source']]['text'] for e in values)

    def ingest_llm(self, raw, valid_days=None):
        from .tasking import parse_structured_llm
        self.emit('model_response',output=raw)
        parsed=parse_structured_llm(raw);data=parsed.get('treasure') if isinstance(parsed,dict) else None
        if not isinstance(data,dict):
            self.analyzed_version=self.request_version
            self.reason='invalid_json_schema';self.emit('validation',reason=self.reason);return
        lookup=data.get('lookup')
        if isinstance(lookup,list):
            self.recall=[s for s in lookup[:6] if isinstance(s,str) and s in self.sources and s not in self.request_sources]
            self.analyzed_version=self.request_version
            self.reason='recall_old_evidence' if self.recall else 'invalid_or_redundant_lookup'
            self.emit('recall',sources=self.recall,reason=self.reason);return
        if self.request_version!=self.version:
            self.reason='stale_response';self.emit('validation',reason=self.reason);return
        self.analyzed_version=self.request_version
        # Omitted fields mean an incremental update. Explicit null/empty fields
        # remove obsolete conclusions; conflicts stop procurement altogether.
        previous=self.constraints
        if not data.get('conflicts'):
            for key in ('materials','kind_count','total_quantity','count_evidence','materials_complete','location','window','exclusions'):
                if key not in data and key in previous:data[key]=previous[key]
        self.mode=data.get('mode','unknown') if data.get('mode') in ('treasure','none') else 'unknown'
        self.constraints=data;self.materials={};self.items=();self.complete=False;self.position=None;self.opening_day=None
        self.reason='unknown_mode'
        if self.mode!='treasure':self.emit('validation',reason=self.reason,mode=self.mode);return
        if data.get('conflicts'):
            self.reason='unresolved_conflicts';self.emit('validation',reason=self.reason,conflicts=data['conflicts']);return
        failures=[]
        material=data.get('materials',[])
        if not isinstance(material,list):material=[]
        for m in material[:40]:
            if not isinstance(m,dict):failures.append('material_shape');continue
            name=m.get('item');qty=m.get('quantity');quote=m.get('shop_quote')
            shop=self.catalog.get(name) if isinstance(name,str) else None
            exact_name=isinstance(name,str) and isinstance(quote,str) and quote==name and self._evidence(m.get('evidence')) and any(name in e['quote'] for e in m['evidence'])
            matched=shop and isinstance(quote,str) and len(quote)>=3 and (quote in shop['description'] or exact_name)
            if not matched or type(qty) is not int or not 1<=qty<=40 or not self._evidence(m.get('evidence')) or not self._evidence(m.get('quantity_evidence')):
                failures.append('material_effect_or_quantity_evidence');continue
            if name in self.materials:failures.append('duplicate_material');continue
            self.materials[name]=qty
        count=data.get('kind_count');total=data.get('total_quantity')
        if count is not None and (type(count) is not int or count!=len(self.materials) or not self._evidence(data.get('count_evidence'))):failures.append('kind_count')
        if total is not None and (type(total) is not int or total!=sum(self.materials.values()) or not self._evidence(data.get('count_evidence'))):failures.append('total_quantity')
        self.items=tuple(name for name,n in sorted(self.materials.items()) for _ in range(n))
        self.complete=bool(self.materials) and data.get('materials_complete') is True and not failures and not data.get('unknown')
        location=data.get('location');window=data.get('window')
        if isinstance(location,dict) and type(location.get('x')) is int and type(location.get('y')) is int and self._evidence(location.get('evidence')):
            self.position=Pos(location['x'],location['y'])
        if isinstance(window,dict) and type(window.get('day')) is int and type(window.get('end_day')) is int and 1<=window['day']<=window['end_day']<=10 and window.get('phase') in ('any','day','night') and self._evidence(window.get('evidence')):
            self.opening_day=window['day'];self.end_day=window['end_day'];self.phase=window['phase']
        self.candidate_version+=1;self.confidence=1.0 if self.complete else 0.0
        self.reason='candidate_ready' if self.complete and self.position and self.opening_day else 'partial_evidence'
        self.emit('candidate',reason=self.reason,failures=failures,materials=self.materials,complete=self.complete,location=([self.position.x,self.position.y] if self.position else None),window=window,unknown=data.get('unknown',[]),constraints=data)

    def apply_result(self,result_code):
        if result_code in (1,4):self.exhausted=True;self.reason='opened' if result_code==1 else 'already_taken'
        elif result_code in (2,3):
            self.reason='wrong_location_or_time' if result_code==2 else 'wrong_materials'
            self.complete=False;self.confidence=0
            if self.pending_attempt:self.rejected.add(self.pending_attempt)
            self.constraints['platform_failure']=self.reason
            # Permit one new analysis of actual feedback; not the same sacrifice.
            self.version+=1
        if result_code==0 and self.pending_attempt:
            self.reason='illegal_or_missing_feedback';self.rejected.add(self.pending_attempt)
            self.constraints['platform_failure']=self.reason;self.version+=1
        if result_code:self.emit('result',code=result_code,reason=self.reason,attempt_round=self.pending_round)
        self.pending_attempt=None

    def signature(self):return (self.position,self.opening_day,self.end_day,self.phase,self.items)

    def available(self,turn):
        return not self.exhausted and bool(self.materials) and self.analyzed_version==self.version and self.mode=='treasure'

    def window_valid(self,turn):
        return self.opening_day is not None and self.opening_day<=turn.day_index<=self.end_day and (self.phase=='any' or self.phase==('day' if turn.is_day else 'night'))

    def expedition_ready(self,turn,pioneer):
        return bool(self.available(turn) and self.complete and self.position and turn.map_info.contains(self.position)
                    and self.opening_day is not None and turn.day_index<=self.end_day
                    and not Counter(self.items)-Counter(pioneer.backpack) and self.signature() not in self.rejected)

    def departure_due(self,turn,pioneer,config):
        if not self.expedition_ready(turn,pioneer) or not pioneer.pos:return False
        grid,_=safe_grid(turn,config)
        path=shortest_path(grid,pioneer.pos,interaction_cells(grid,self.position))
        if not path:return False
        opening=(self.opening_day-1)*130+(71 if self.phase=='night' else 1)
        if self.phase=='day' and not turn.is_day and turn.day_index>=self.opening_day:
            if turn.day_index>=self.end_day:return False
            opening=turn.day_index*130+1
        return opening-turn.round_no<=len(path)-1+2

    def can_attempt(self,turn,pioneer,config):
        return bool(self.expedition_ready(turn,pioneer) and self.window_valid(turn) and pioneer.pos
                    and pioneer.pos.distance_to(self.position)<=1 and self.signature() not in self.attempted)

    def action(self,turn,pioneer,config):
        if not self.can_attempt(turn,pioneer,config):return None
        return Action(pioneer.unit_id,ActionType.SUMMON_TREASURE,targets=(self.position,),items=self.items)

    def issued(self,turn,action):
        if action.action_type!=ActionType.SUMMON_TREASURE:return
        self.pending_attempt=self.signature();self.pending_round=turn.round_no;self.attempted.add(self.pending_attempt)
        self.emit('opening',candidate=self.candidate_version,items=self.materials)

    def plan(self,turn,pioneer,config,spending,*,guard_ready=False):
        from .tasking import AdvancedPlan
        def wait(reason):
            self.reason=reason;return AdvancedPlan()
        if turn.phase_task:return wait('active_task')
        if not self.available(turn) or not pioneer.pos:return wait('await_evidence' if not self.exhausted else 'exhausted')
        grid,danger=safe_grid(turn,config)
        if pioneer.pos in danger:return AdvancedPlan(move=escape_intent(turn,pioneer,config,danger))
        missing=Counter(self.items)-Counter(pioneer.backpack)
        if missing:
            if not turn.is_day and not guard_ready:return wait('purchase_needs_guard')
            from .economy import due_defense_targets, next_development_target, upgrade_item
            target=next_development_target(turn,config)
            prices={i.name:i.price for i in turn.weapon_shop}
            weapons=[w for w in turn.team_our.roles if w.is_weapon and w.alive]
            basic=max(0,config.max_weapon_count-sum(w.level>=2 for w in weapons)-sum(r.backpack.count('WeaponUpgradeVoucher1') for r in turn.controllable))
            reserve=max(config.treasure_gold_reserve,prices.get(upgrade_item(target),0),basic*prices.get('WeaponUpgradeVoucher1',100))
            if due_defense_targets(turn,config):return wait('defense_deadline_funding')
            affordable=[(name,n) for name,n in missing.items() if name in prices and prices[name]*n<=max(0,spending-reserve)]
            if not affordable:return wait('material_funding_gap')
            goals=tuple(p for shop in turn.zone_positions('weaponShop') for p in interaction_cells(grid,shop))
            trip=TravelBudget.for_role(turn,pioneer,config)
            if turn.is_day and not guard_ready and not trip.fits(((goals,1),)):return wait('purchase_return_deadline')
            if pioneer.pos in goals:
                name,n=affordable[0];n=min(n,max(0,pioneer.backpack_capacity-len(pioneer.backpack)))
                if not n:return wait('material_capacity')
                self.reason='purchase_material';self.emit('purchase',item=name,quantity=n,location_known=self.position is not None)
                return AdvancedPlan(action=Action(pioneer.unit_id,ActionType.BUY,name=name,quantity=n))
            if not shortest_path(grid,pioneer.pos,goals):return wait('unsafe_shop_route')
            self.reason='travel_shop';return AdvancedPlan(move=MoveIntent(pioneer.unit_id,goals,95,avoid_cells=danger))
        if not self.expedition_ready(turn,pioneer):return wait('await_location_window_or_remaining_materials')
        if not self.departure_due(turn,pioneer,config):return wait('future_window_departure_not_due')
        if not turn.is_day and not guard_ready:return wait('await_guard_handover')
        if not guard_ready and turn.is_day:
            trip=TravelBudget.for_role(turn,pioneer,config)
            goals=interaction_cells(grid,self.position)
            if not trip.fits(((goals,1),)):return wait('expedition_needs_guard')
        action=self.action(turn,pioneer,config)
        if action:self.reason='open';return AdvancedPlan(action=action)
        goals=interaction_cells(grid,self.position)
        if pioneer.pos in goals:
            self.reason='at_site_wait_window';return AdvancedPlan(move=MoveIntent(pioneer.unit_id,(pioneer.pos,),96,avoid_cells=danger))
        if not shortest_path(grid,pioneer.pos,goals):return wait('unsafe_treasure_route')
        self.reason='travel_site';return AdvancedPlan(move=MoveIntent(pioneer.unit_id,goals,96,avoid_cells=danger))
