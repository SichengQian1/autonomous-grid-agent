"""Match-local source memory and evidence-bound treasure preparation/expedition.

The model interprets narrative effects. The program verifies source membership,
shop binding, multiplicity, geometry, time and action feedback independently.
"""
from collections import Counter
from dataclasses import dataclass, field
import hashlib
import json
import re
from .actions import Action, ActionType
from .geometry import Pos
from .grid import distance_field, interaction_cells, shortest_path
from .movement import MoveIntent
from .route_safety import safe_grid, escape_intent
from .travel import TravelBudget
from .rules import DEFAULT_CONFIG
from .treasure_claims import cited, material_claim, location_claim, window_claim


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
    request_id: int = 0
    responses: int = 0
    request_purpose: str = 'treasure'
    response_id_required: bool = False
    request_catalog_hash: str = ''
    accepted_catalog_hash: str = ''
    accepted_sources: set = field(default_factory=set)
    correction_version: int = 0
    correction_resolved_version: int = 0
    validated_version: int = -1
    retry_version: int = -1
    retry_count: int = 0
    retry_pending: bool = False
    map_bounds: tuple = (0,0)
    vendor_names: set = field(default_factory=set)
    material_claims: dict = field(default_factory=dict)
    last_validation_failure: dict = field(default_factory=dict)
    validation_failures: list = field(default_factory=list)
    inferred_spent: int = 0
    inferred_attempts: int = 0
    inferred_gold_limit: int = 90
    inferred_attempt_limit: int = 2
    rejected_material_sets: set = field(default_factory=set)
    rejected_sites: set = field(default_factory=set)

    def emit(self, stage, **data):
        if len(self.events)<40:self.events.append({'stage':stage,**data})

    def observe(self, turn, config=DEFAULT_CONFIG):
        self.current_round=turn.round_no
        self.map_bounds=(turn.map_info.width,turn.map_info.height)
        self.vendor_names={i.name for i in turn.vendor_shop}
        self.inferred_gold_limit=config.treasure_inferred_gold_limit
        self.inferred_attempt_limit=config.treasure_inferred_attempt_limit
        catalog={i.name:{'description':i.description[:6000].strip(),'price':i.price,'original_length':len(i.description)} for i in turn.weapon_shop[:128]}
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
        if self.sources and re.search(r'correction|instead|retract|cancel|not .{0,40}but|更正|纠正|改为|取消|有误|并非|不是|不再',text,re.I):
            self.correction_version=self.version
        # Keep old evidence, not just the suffix of an ever-growing prompt.
        # Segment boundaries overlap so short requirements survive splits.
        added=[]
        for offset in range(0,len(text),1100):
            segment=text[max(0,offset-100):offset+1100]
            n=len(segment.encode());sid='S'+fingerprint(segment)
            if sid in self.sources:continue
            if self.memory_bytes+n>196608:
                self.omitted+=n;continue
            self.sources[sid]={'id':sid,'day':turn.day_index,'version':self.version,'offset':max(0,offset-100),'text':segment,'fingerprint':fingerprint(segment)}
            self.memory_bytes+=n;added.append(sid)
        self.emit('source',day=turn.day_index,input_length=len(text),segments=added,
                  memory_bytes=self.memory_bytes,omitted_bytes=self.omitted,excerpt=text)
        # New clues may correct old ones. Re-evaluate before buying/sacrificing.
        self.reason='new_evidence_pending'

    def needs_analysis(self):
        return not self.exhausted and bool(self.sources) and (self.version!=self.analyzed_version or bool(self.recall) or self.retry_pending)

    def prompt(self, official='', source_day=1, *, purpose='treasure'):
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
        self.request_id+=1;self.request_purpose=purpose;self.request_catalog_hash=self.catalog_hash
        if purpose=='treasure':self.retry_pending=False
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
        payload={'request_id':self.request_id,'purpose':purpose,'map_bounds':self.map_bounds,'sources':selected,'source_index':index,
                 'omitted_source_count':len(self.sources)-len(selected),'omitted_memory_bytes':self.omitted,
                 'previous_constraints':prior,'validation_failures':self.validation_failures[:12],
                 'pending_correction_sources':[sid for sid,s in self.sources.items() if self.correction_resolved_version<self.correction_version<=s['version']],
                 'last_validation_failure':self.last_validation_failure,'shop':catalog,'catalog_omitted':catalog_omitted,'official':official[:6000],'official_original_length':len(official),'official_day':source_day}
        instruction='''Interpret folk treasure clues separately from official market news and task puzzles. Unknown map/mode stays unknown. Return strict JSON with market:[] and treasure object. Never use past-map answers. Reconcile corrections/exclusions and report unresolved conflicts; a new source can supersede an old conclusion only with explicit evidence. Each evidence is {source:"source ID",quote:"exact source substring"}. If relevant old evidence is omitted, return treasure:{lookup:[source IDs]} first. Do not guess an omitted source.
Treasure schema: {mode:"treasure|unknown|none",materials:[{item:"exact current shop name",quantity:positive integer,effect:"required effect",shop_quote:"exact description substring OR exact item name when directly named by rumor",evidence:[evidence],quantity_evidence:[evidence]}],kind_count:integer|null,total_quantity:integer|null,count_evidence:[evidence],materials_complete:boolean,location:{x:integer,y:integer,evidence:[evidence]}|null,window:{day:integer,end_day:integer,phase:"any|day|night",evidence:[evidence]}|null,conflicts:[],unknown:[],exclusions:[],resolutions:[]}. Evidence must establish each quantity, not assume one per type. "n kinds" is distinct types, not total quantity. Resolve times relative to source day, use actual map coordinates from current clues, include derivation in unknown if not proven. Emit every individually proven material even if the rest, location or time are unknown: partial procurement is useful. Same-day complete clues are valid. Match effects against actual shop descriptions, never a fixed dictionary or self-reported confidence. Set materials_complete only when all requested effects/types/quantities are covered.
Market schema: [{ore:"iron|copper|stone",start_day:integer,end_day:integer,price:number|null,closed:boolean,rising:boolean,recovery:boolean,evidence:"exact official quote",confidence:number}]. No fixed price day; explicit recovery cancels restrictions in its own window.
'''
        instruction += """
Additional mandatory claim fields: materials include object, object_quote and effect_quote (exact cited phrases), plus derivation explaining the proposed object-to-current-item binding. Prefer effect as a short exact phrase. If paraphrasing/translating effect, include effect_relation:{claim:the exact effect value,quote:the exact effect_quote,reason:explanation}; this remains an inference, not semantic verification. Use separate evidence entries for separately arriving objects, effects and quantities. quantity_evidence must actually state the amount for this object or an explicit each/all rule; dates are not material quantities. Empty shop descriptions are allowed: propose exact catalog names with grounded explanations and label uncertainty; never invent shop descriptions. Nonempty descriptions must be cited faithfully. Missing descriptions alone do not mean treasure mode is unknown. Only weapon-shop purchases are supported; vendor-only material availability is unverified.
Location must include precision:"exact|approximate" and derivation:{kind:"coordinate_literal"} for explicitly quoted coordinates, or {kind:"offset",anchor:[x,y],delta:[dx,dy],offset_quote:"source expression such as x+2 y-1"} for checkable arithmetic. Do not turn near/around into an exact sacrifice tile. Unsupported geometric deductions stay unknown. Include source-day-based window dates and phase; distinguish tomorrow from absolute dates. Preserve established facts on unknown; omitted fields are incremental updates. To retract a field provide retractions:[{field,reason,evidence}]. mode:none requires mode_evidence and reason. To resolve previous conflicts provide resolutions:[{reason,evidence}]. Never submit an empty treasure merely because only official news changed. Echo request_id at top level.
"""
        if purpose=='market_only':
            payload={k:v for k,v in payload.items() if k in ('request_id','purpose','official','official_original_length','official_day')}
            instruction='Interpret only official news. Return request_id and market; omit treasure. Market schema: '+instruction.split('Market schema: ')[1].split('Additional mandatory')[0]
        result=instruction+json.dumps(payload,ensure_ascii=False)
        self.last_request_signature=fingerprint(result)
        self.emit('model_request',request_id=self.request_id,purpose=purpose,version=self.request_version,input_length=len(result),omitted_sources=len(self.sources)-len(selected),input=payload)
        return result

    def _evidence(self, values):
        return cited(values,self.sources,self.request_sources)

    def fail(self,reason,**detail):
        self.reason=reason
        self.last_validation_failure={'reason':reason,'request_id':self.request_id,'round':self.current_round,**detail}
        self.emit('validation',**self.last_validation_failure)

    def retry_analysis(self):
        if self.retry_version!=self.request_version:self.retry_version=self.request_version;self.retry_count=0
        if self.retry_count<1:
            self.retry_count+=1;self.retry_pending=True

    def ingest_llm(self, raw, valid_days=None):
        from .tasking import parse_structured_llm
        self.responses+=1
        self.emit('model_response',request_id=self.request_id,response_number=self.responses,
                  snapshot_version=self.request_version,current_version=self.version,output=raw)
        parsed=parse_structured_llm(raw)
        if not isinstance(parsed,dict):
            self.analyzed_version=max(self.analyzed_version,self.request_version)
            self.fail('invalid_json_schema');self.retry_analysis();return
        if self.response_id_required and 'request_id' not in parsed:
            self.fail('request_id_missing_after_timeout');self.retry_analysis();return
        if 'request_id' in parsed and (type(parsed['request_id']) is not int or parsed['request_id']!=self.request_id):
            self.fail('request_id_mismatch');return
        if self.request_purpose=='market_only':
            self.emit('market_only_response',request_id=self.request_id,treasure_ignored='treasure' in parsed);return
        if self.request_catalog_hash!=self.catalog_hash:
            self.analyzed_version=max(self.analyzed_version,self.request_version)
            self.fail('catalog_changed_during_request');self.retry_analysis();return
        data=parsed.get('treasure')
        if not isinstance(data,dict):
            self.analyzed_version=max(self.analyzed_version,self.request_version)
            self.fail('invalid_json_schema');self.retry_analysis();return
        lookup=data.get('lookup')
        if isinstance(lookup,list):
            self.recall=[s for s in lookup[:6] if isinstance(s,str) and s in self.sources and s not in self.request_sources]
            self.analyzed_version=max(self.analyzed_version,self.request_version)
            self.reason='recall_old_evidence' if self.recall else 'invalid_or_redundant_lookup'
            self.emit('recall',request_id=self.request_id,sources=self.recall,reason=self.reason);return
        # Validate against the request's immutable source IDs. Arrivals during
        # latency are queued for another analysis, not grounds to discard facts.
        self.analyzed_version=max(self.analyzed_version,self.request_version)
        if data.get('mode')=='none':
            if not self._evidence(data.get('mode_evidence')) or not data.get('reason'):
                self.fail('unjustified_mode_retraction');return
            self.mode='none';self.materials={};self.material_claims={};self.items=()
            self.position=None;self.opening_day=None;self.complete=False;self.constraints=data
            self.reason='explicit_no_treasure';return
        if data.get('mode')=='treasure':self.mode='treasure'
        # An unknown reply may add a fact, but cannot erase established facts by
        # emitting null defaults. Destructive changes need current-source support.
        fields=('materials','kind_count','total_quantity','count_evidence','materials_complete','location','window','unknown','exclusions')
        meaningful=any(k in data and data[k] not in (None,[],False) for k in fields if k not in ('unknown','materials_complete'))
        if data.get('mode','unknown')=='unknown' and not meaningful:
            self.reason='unknown_preserved';self.emit('validation',request_id=self.request_id,reason=self.reason)
            if self.validated_version!=self.request_version:self.retry_analysis()
            return
        previous=self.constraints
        merged=dict(previous)
        retractions=data.get('retractions',[])
        allowed_retractions={r.get('field') for r in retractions if isinstance(r,dict) and isinstance(r.get('field'),str)
                             and r.get('reason') and self._evidence(r.get('evidence'))} if isinstance(retractions,list) else set()
        failures=[]
        for key in fields:
            if key not in data:continue
            value=data[key]
            if key in ('materials','location','window') and value in (None,[]) and previous.get(key) and key not in allowed_retractions:
                failures.append({'field':key,'reason':'unjustified_field_retraction'});continue
            if key=='materials' and isinstance(value,list) and value:
                prior_materials=previous.get('materials') if isinstance(previous.get('materials'),list) else []
                old={m['item']:m for m in prior_materials if isinstance(m,dict) and isinstance(m.get('item'),str)} if key not in allowed_retractions else {}
                names=[m['item'] for m in value if isinstance(m,dict) and isinstance(m.get('item'),str)]
                if len(names)!=len(set(names)):failures.append({'field':'materials','reason':'duplicate_material'})
                for m in value:
                    if isinstance(m,dict) and isinstance(m.get('item'),str):old[m['item']]=m
                    else:failures.append({'field':'materials','reason':'material_shape'})
                merged[key]=list(old.values())[:40]
            else:merged[key]=[] if key=='materials' and value is None and key in allowed_retractions else value
        incoming_conflicts=data.get('conflicts')
        if incoming_conflicts:
            merged['conflicts']=incoming_conflicts
        elif previous.get('conflicts'):
            resolutions=data.get('resolutions',[])
            valid_resolution=(isinstance(resolutions,list) and bool(resolutions) and all(isinstance(r,dict) and r.get('reason') and self._evidence(r.get('evidence')) for r in resolutions))
            if valid_resolution:merged['conflicts']=[]
        else:merged['conflicts']=[]
        merged['mode']=self.mode
        self.constraints=merged
        allowed=self.accepted_sources|self.request_sources
        self.materials={};self.material_claims={}
        incoming_materials=data.get('materials',[])
        updated={m.get('item') for m in incoming_materials if isinstance(m,dict) and isinstance(m.get('item'),str)} if isinstance(incoming_materials,list) else set()
        material=merged.get('materials',[])
        if not isinstance(material,list):
            failures.append({'field':'materials','reason':'material_shape'});material=[]
        for m in material[:40]:
            name=m.get('item') if isinstance(m,dict) else None
            claim,error=material_claim(m,self.catalog,self.sources,self.request_sources if name in updated else allowed)
            if error:
                failures.append({'field':'materials','item':name,'reason':error,
                                 'vendor_only_unverified':isinstance(name,str) and name in self.vendor_names and name not in self.catalog});continue
            if name in self.materials:
                failures.append({'field':'materials','item':name,'reason':'duplicate_material'});continue
            self.materials[name]=claim['quantity'];self.material_claims[name]=claim
        material_failed=any(f['field']=='materials' for f in failures)
        skipped=[]
        for key,actual in [('kind_count',len(self.materials)),('total_quantity',sum(self.materials.values()))]:
            value=merged.get(key)
            if value is None:continue
            if material_failed:
                skipped.append(key);continue
            if type(value) is not int or value!=actual or not cited(merged.get('count_evidence'),self.sources,allowed):
                failures.append({'field':key,'reason':key+'_mismatch'})
        self.items=tuple(name for name,n in sorted(self.materials.items()) for _ in range(n))
        self.complete=bool(self.materials) and merged.get('materials_complete') is True and not failures and not merged.get('unknown')
        if merged.get('location') is not None:
            location,error=location_claim(merged['location'],self.sources,self.request_sources if 'location' in data else allowed,self.map_bounds)
            if error:failures.append({'field':'location','reason':error})
            else:self.position=location
        elif 'location' in allowed_retractions:self.position=None
        if merged.get('window') is not None:
            days=set(valid_days) if valid_days is not None else {v['day'] for v in self.sources.values()}
            window,error=window_claim(merged['window'],self.sources,self.request_sources if 'window' in data else allowed,days)
            if error:failures.append({'field':'window','reason':error})
            else:self.opening_day,self.end_day,self.phase=window
        elif 'window' in allowed_retractions:self.opening_day=None
        if merged.get('conflicts'):
            failures.insert(0,{'field':'conflicts','reason':'unresolved_conflicts'})
            self.complete=False
        self.validation_failures=failures
        self.accepted_catalog_hash=self.request_catalog_hash
        self.accepted_sources.update(self.request_sources)
        if not failures and self.mode=='treasure':self.validated_version=self.request_version
        if not failures and self.correction_version<=self.request_version:
            resolutions=data.get('resolutions',[])
            if isinstance(resolutions,list) and any(isinstance(r,dict) and r.get('reason') and self._evidence(r.get('evidence'))
                and any(self.sources[e['source']].get('version',0)>=self.correction_version for e in r['evidence']) for r in resolutions):
                self.correction_resolved_version=self.request_version
        self.candidate_version+=1;self.confidence=0.0
        ready=self.complete and self.position and self.opening_day and not failures
        self.reason='candidate_ready' if ready else 'partial_evidence'
        if failures:
            self.fail(failures[0]['reason'],field=failures[0]['field']);self.retry_analysis()
        self.emit('candidate',request_id=self.request_id,response_number=self.responses,candidate_version=self.candidate_version,
                  snapshot_version=self.request_version,current_version=self.version,reason=self.reason,
                  failures=failures,dependent_checks_skipped=skipped,materials=self.materials,
                  material_claims=self.material_claims,complete=self.complete,
                  location=([self.position.x,self.position.y] if self.position else None),window=merged.get('window'),
                  unknown=merged.get('unknown',[]),constraints=merged)

    def apply_result(self,result_code):
        if result_code in (1,4):
            self.exhausted=True;self.reason='opened' if result_code==1 else 'already_taken'
            if result_code==1:
                for claim in self.material_claims.values():claim['platform']='opening_success'
        elif result_code in (2,3):
            self.reason='wrong_location_or_time' if result_code==2 else 'wrong_materials'
            self.complete=False;self.confidence=0
            if self.pending_attempt:self.rejected.add(self.pending_attempt)
            if result_code==3:self.rejected_material_sets.add(self.items)
            if result_code==2:self.rejected_sites.add(self.signature()[:4])
            self.constraints['platform_failure']=self.reason
            # Permit one new analysis of actual feedback; not the same sacrifice.
            self.version+=1
        if result_code==0 and self.pending_attempt:
            self.reason='illegal_or_missing_feedback';self.rejected.add(self.pending_attempt)
            self.constraints['platform_failure']=self.reason;self.version+=1
        if result_code in (0,2,3) and self.pending_attempt:self.fail(self.reason,field='platform')
        if result_code or self.pending_attempt:self.emit('result',code=result_code,reason=self.reason,attempt_round=self.pending_round)
        self.pending_attempt=None

    def signature(self):return (self.position,self.opening_day,self.end_day,self.phase,self.items)

    def available(self,turn):
        return (not self.exhausted and bool(self.materials) and self.mode=='treasure'
                and not self.expired(turn) and self.correction_version<=self.correction_resolved_version
                and self.accepted_catalog_hash==self.catalog_hash and not self.constraints.get('conflicts')
                and not any(f['reason']=='unjustified_field_retraction' for f in self.validation_failures)
                and self.items not in self.rejected_material_sets and self.signature() not in self.rejected)

    def expired(self,turn):
        return self.opening_day is not None and turn.round_no>(self.end_day-1)*130+(70 if self.phase=='day' else 130)

    def inferred(self):
        return {name for name,c in self.material_claims.items() if c['binding']=='inferred'}

    def inference_allowed(self):
        inferred=self.inferred()
        return not inferred or (len(inferred)<=6 and sum(self.materials[n] for n in inferred)<=12
                                and self.inferred_attempts<self.inferred_attempt_limit)

    def window_valid(self,turn):
        return self.opening_day is not None and self.opening_day<=turn.day_index<=self.end_day and (self.phase=='any' or self.phase==('day' if turn.is_day else 'night'))

    def expedition_ready(self,turn,pioneer):
        return bool(self.available(turn) and self.complete and self.position and turn.map_info.contains(self.position)
                    and self.validated_version==self.version and not self.validation_failures and self.inference_allowed()
                    and self.signature()[:4] not in self.rejected_sites
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
                    and pioneer.pos.distance_to(self.position)==1 and self.signature() not in self.attempted)

    def action(self,turn,pioneer,config):
        if not self.can_attempt(turn,pioneer,config):return None
        return Action(pioneer.unit_id,ActionType.SUMMON_TREASURE,targets=(self.position,),items=self.items)

    def issued(self,turn,action):
        if action.action_type==ActionType.BUY and action.name in self.inferred():
            role=turn.team_our.unit(action.actor_id)
            if role and role.role_type=='pioneer':
                # Conservative exposure budget: accepted orders are charged even
                # if feedback is absent, rather than risking endless purchases.
                self.inferred_spent+=next((i.price for i in turn.weapon_shop if i.name==action.name),0)*(action.quantity or 1)
            return
        if action.action_type!=ActionType.SUMMON_TREASURE:return
        if self.inferred():self.inferred_attempts+=1
        self.pending_attempt=self.signature();self.pending_round=turn.round_no;self.attempted.add(self.pending_attempt)
        self.emit('opening',candidate=self.candidate_version,items=self.materials,inferred_attempt=self.inferred_attempts,
                  bindings={n:c['binding'] for n,c in self.material_claims.items()})

    def plan(self,turn,pioneer,config,spending,*,guard_ready=False):
        from .tasking import AdvancedPlan
        def wait(reason):
            self.reason=reason;return AdvancedPlan()
        if turn.phase_task:return wait('active_task')
        if self.expired(turn):return wait('window_expired')
        if not self.available(turn) or not pioneer.pos:return wait('await_evidence' if not self.exhausted else 'exhausted')
        if not self.inference_allowed():return wait('inferred_attempt_or_size_limit')
        grid,danger=safe_grid(turn,config)
        if pioneer.pos in danger:return AdvancedPlan(move=escape_intent(turn,pioneer,config,danger))
        missing=Counter(self.items)-Counter(pioneer.backpack)
        if missing:
            if not turn.is_day and not guard_ready:return wait('purchase_needs_guard')
            from .economy import due_defense_targets, next_development_target, upgrade_item
            target=next_development_target(turn,config)
            prices={i.name:i.price for i in turn.weapon_shop}
            inferred_cost=sum(prices.get(name,self.inferred_gold_limit+1)*n for name,n in missing.items() if name in self.inferred())
            if self.inferred_spent+inferred_cost>self.inferred_gold_limit:return wait('inferred_purchase_budget')
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
