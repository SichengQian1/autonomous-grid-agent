"""Bounded, fail-closed task diagnostics. Encoding is never treated as redaction."""
import ast
import hashlib
import io
import json
import re
import secrets
import tokenize
from .rules import WEAPON_BUILD_COST
from collections import Counter
from dataclasses import dataclass,field


def task_category(turn, position):
    if position is None:return 0
    zones=sorted((z for z in turn.map_info.zones if 'taskpoint' in z.neutral_type.lower() and z.pos),
                 key=lambda z:z.pos.distance_to(position))
    if zones and zones[0].pos.distance_to(position)<=1:
        match=re.search(r'([12])$',zones[0].neutral_type)
        if match:return int(match[1])
    task=next((t for t in turn.team_our.player_tasks if t.task_position==position),None)
    match=re.search(r'([12])$',task.task_type) if task else None
    return int(match[1]) if match else 0

@dataclass
class Redactor:
    salt: str = field(default_factory=lambda:secrets.token_hex(16))
    names: dict = field(default_factory=dict)
    sensitive: set = field(default_factory=set)

    def protect(self, value):
        if isinstance(value,dict):
            for v in value.values():self.protect(v)
        elif isinstance(value,list):
            for v in value:self.protect(v)
        elif isinstance(value,(str,int)) and str(value):self.sensitive.add(str(value))

    def scrub(self,value):
        if isinstance(value,dict):return {self.scrub(str(k)):self.scrub(v) for k,v in value.items()}
        if isinstance(value,list):return [self.scrub(v) for v in value]
        if isinstance(value,str):
            for secret in sorted(self.sensitive,key=len,reverse=True):
                if len(secret)>=3:value=value.replace(secret,'<redacted>')
            return value
        if isinstance(value,int) and len(str(value))>=3 and str(value) in self.sensitive:return '<redacted>'
        return value

    def fingerprint(self, value):
        return hashlib.sha256((self.salt+str(value)).encode()).hexdigest()[:16]

    def readable(self, value, limit=2400):
        """Readable local evidence with credential discovery before truncation."""
        # Register labeled credentials before any separate snippet is emitted.
        patterns=[r'(?i)(?:bearer\s+)([A-Za-z0-9_./+=-]{4,})',
                  r'''(?i)(?<![\w-])(?:[\w-]*(?:token|password|secret|credential|api[_-]?key|certificate)[\w-]*|authorization|cookie|session|proof|account|username|teamId|teamName)\s*["'`]?\s*[:=|]\s*["'`]?([^\s"'`,;}|]+)''']
        def learn(v):
            if isinstance(v,dict):
                for key,item in v.items():
                    if str(key).lower()=='headers' and isinstance(item,dict):self.protect(item)
                    if re.search(r'(?i)token|password|secret|credential|api[_-]?key|certificate|authorization|cookie|session|proof|account|username|teamId|teamName|cache_namespace',str(key)) and isinstance(item,str) and item not in ('string','integer','object','array','boolean','number','null'):
                        self.protect(item)
                    learn(item)
            elif isinstance(v,list):
                for item in v:learn(item)
            elif isinstance(v,str):
                for pattern in patterns:
                    for match in re.finditer(pattern,v):
                        if match[1] not in ('string','integer','object','array','boolean','number','null'):self.protect(match[1])
        learn(value)
        text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)
        text=self.scrub(text)
        text=re.sub(r'https?://[^\s"\x27<>`]+',lambda m:'<service:'+self.fingerprint(m[0])[:8]+'>',text)
        text=re.sub(r'(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '<account>',text)
        text=re.sub(r'(?<![\w])(?:[A-Za-z]:)?/(?:[\w.\-]+/?)+',lambda m:self.path(m[0]),text)
        text=re.sub(r'\b[0-9a-fA-F]{12,}\b','<opaque>',text)
        original=len(text.encode())
        raw=text.encode()[:limit];kept=raw.decode(errors='ignore')
        return {'text':kept,'original_bytes':original,'kept_bytes':len(kept.encode()),'truncated':len(raw)<original}

    def path(self, value):
        parts=str(value).replace('\\','/').split('/')
        parent='';mapped=[]
        for part in parts[:12]:
            if part in ('','.','..'):mapped.append(part);continue
            parent+='/'+part
            if parent not in self.names:self.names[parent]='p'+str(len(self.names)+1)
            mapped.append(self.names[parent])
        return '/'.join(mapped)

    def program(self, source, focus=()):
        """Keep executable structure, replacing every string literal and comment."""
        try:
            ast.parse(source[:16000])
            tokens=[]
            for token in tokenize.generate_tokens(io.StringIO(source[:16000]).readline):
                if token.type==tokenize.STRING:token=token._replace(string=repr('<literal>'))
                elif token.type==tokenize.NUMBER:token=token._replace(string='0')
                elif token.type==tokenize.COMMENT:token=token._replace(string='# <comment>')
                tokens.append(token)
            text=tokenize.untokenize(tokens)
            lines=text.splitlines()
            important=[i for i,line in enumerate(lines) if any(w in line for w in ('request','page','assert','raise','open(', 'return','print(', 'answer','check'))]
            chosen=sorted(set(range(min(3,len(lines))))|set(important[-8:])|{i for n in focus for i in (n-2,n-1,n) if 0<=i<len(lines)})
            return '\n'.join(f'{i+1}: {lines[i][:160]}' for i in chosen)[:1800]
        except SyntaxError as error:
            lines=source.splitlines();index=(error.lineno or 1)-1
            return f'line {index+1}: '+self.words(lines[index] if index<len(lines) else '')
        except Exception:return '<non_python_program:'+self.fingerprint(source)+'>'

    def structure(self,value,depth=0):
        if depth>3:return '<depth_limit>'
        if isinstance(value,dict):
            known={'city','total_count','world_heritage_count','types','oldest_era','answer','proof','token',
                   'success','ok','passed','kind','procedure','command','code','script','required','verify',
                   'url','query','headers','filter','fields','records_path','pagination','compatibility','schema','contract',
                   'path','op','value','source','count','parameter','start','step','size','size_parameter','id_path','total_path',
                   'cwd','edits','check','answer_path','answer_format','answer_pattern','submit_result','python','reuse'}
            return {str(k) if k in known else '<key:'+self.fingerprint(k)[:8]+'>':self.structure(v,depth+1)
                    for k,v in list(value.items())[:16]}
        if isinstance(value,list):return {'type':'array','length':len(value),'sample_types':[type(v).__name__ for v in value[:3]]}
        return {'type':type(value).__name__,'length':len(value) if isinstance(value,str) else None}

    def words(self, text):
        allowed=set('city total_count world_heritage_count types oldest_era error expected actual missing file directory permission denied failed invalid not found assertion true false check success failure port version value configuration path line type key index count total page parse syntax returned must equal mismatch exists read write execute timeout'.split())
        def word(match):
            value=match[0]
            return value if value.lower() in allowed else '<v:'+self.fingerprint(value)[:6]+'>'
        return re.sub(r'[\w@./:\\-]+',word,text)[:1500]

    def safe_answer(self,answer,category):
        if category!=1 or not isinstance(answer,dict):return self.structure(answer)
        result={}
        for key in ('city','total_count','world_heritage_count','types','oldest_era'):
            if key not in answer:continue
            value=answer[key]
            if key in ('total_count','world_heritage_count') and isinstance(value,int) and 0<=value<=1000000:result[key]=value
            elif isinstance(value,list):result[key]=['<v:'+self.fingerprint(v)[:6]+'>' for v in value[:12]]
            else:result[key]='<v:'+self.fingerprint(value)[:6]+'>'
        return result

    def trace(self, text):
        # Arbitrary stdout can contain credentials under unknown labels. Emit only
        # traceback location, exception class and allowlisted diagnostic markers.
        result={'length':len(text),'fingerprint':self.fingerprint(text)}
        frames=re.findall(r'File "([^"]+)", line (\d+)',text)
        result['frames']=[{'path':self.path(p),'line':int(n)} for p,n in frames[-4:]]
        result['excerpt']=self.words(text[-2600:])
        result['exceptions']=re.findall(r'\b([A-Za-z]+(?:Error|Exception))\b',text)[-4:]
        return result

@dataclass
class TaskAudit:
    redactor: Redactor = field(default_factory=Redactor)
    counts: Counter = field(default_factory=Counter)
    active: dict | None = None
    previous: dict | None = None
    events: list = field(default_factory=list)
    dropped: int = 0
    used: int = 0
    total_used: int = 0
    repeats: Counter = field(default_factory=Counter)
    task_limit: int = 42000
    match_limit: int = 300000
    sequence: int = 0
    last_result: str = ''
    last_llm: str = ''
    transcript_seen: set = field(default_factory=set)
    settlement: tuple | None = None

    def emit(self, kind, round_no, data, critical=False):
        if not self.active:return
        data=self.redactor.scrub(data)
        event={'event':'task','kind':kind,'r':round_no,'task_id':self.active['task_id'],
               'task_type':self.active['task_type'],'type_ordinal':self.active['type_ordinal'],
               'remaining':max(0,self.active['deadline']-round_no),**data}
        size=len(json.dumps(event,ensure_ascii=False).encode())
        if size>7000 and kind=='execution':
            omitted=[]
            for key in ('plan_structure','program','requirements','paths','documents','output','api','verifier_program','checks','operations'):
                if size<=7000:break
                if key in event:
                    event.pop(key);omitted.append(key)
                    event['omitted_fields']=omitted
                    size=len(json.dumps(event,ensure_ascii=False).encode())
        reserve=3000 if not critical else 1500 if kind!='end' else 0
        if size>7000 or self.used+size>self.task_limit-reserve or self.total_used+size>self.match_limit-reserve:
            self.dropped+=1;return
        self.used+=size;self.total_used+=size;event['dropped']=self.dropped
        self.events.append(event)

    def artifact(self, round_no, kind, value, limit=8000):
        fingerprint=self.redactor.fingerprint(value)
        if fingerprint in self.transcript_seen:return
        self.transcript_seen.add(fingerprint)
        content=self.redactor.readable(value,limit)
        text=content.pop('text');chunks=[text[i:i+1200] for i in range(0,len(text),1200)] or ['']
        for index,chunk in enumerate(chunks):
            self.emit('trace',round_no,{'artifact':kind,'fingerprint':fingerprint,'part':index+1,
                'parts':len(chunks),'text':chunk,**content},True)

    def observe(self,turn,series):
        self.settlement=None
        if self.active and self.previous:
            p=self.previous;delta=turn.team_our.gold-p['gold'];uncertain=turn.round_no!=p['r']+1
            for actor,c in p['commands'].items():
                action=c.get('action');quantity=c.get('num',0);name=c.get('name','')
                if action not in ('sell','buy','build','summonTreasure'):continue
                ok=turn.last_action_results.get(int(actor))
                if ok is False:continue
                if ok is not True:uncertain=True;continue
                if action=='sell':
                    price=p['vendor'].get(name)
                    if price is None:uncertain=True
                    else:delta-=price*quantity
                elif action=='buy':
                    price=p['shop'].get(name)
                    if price is None:uncertain=True
                    else:delta+=price*quantity
                elif action=='build' and name!='wall':delta+=WEAPON_BUILD_COST
                elif action=='summonTreasure':uncertain=True
            if turn.phase_task:self.active['seen']=True
            if self.active['seen'] and not turn.phase_task:
                reward=self.active['reward'];outcome='unknown'
                if not uncertain and reward>0 and 0<=delta<=reward:
                    outcome='full' if delta==reward else 'partial' if delta else 'zero'
                self.emit('end',turn.round_no,{'outcome':outcome,'task_gold':None if uncertain else delta,
                    'gold_delta':turn.team_our.gold-p['gold'],'feedback':{'errors':[e.error_code for e in turn.errors],
                    'attribution':'unknown' if uncertain else 'successful_economic_actions_removed'},
                    'elapsed':turn.round_no-self.active['start'],'submissions':self.active['submissions'],
                    'llm_requests':self.active['llm_requests'],'llm_returns':self.active['llm_returns'],
                    'commands':self.active['commands']},True)
                self.settlement=(self.active['task_id'],outcome);series.settle(*self.settlement);self.active=None
        if self.active and turn.last_command_result and self.redactor.fingerprint(turn.last_command_result)!=self.last_result:
            self.last_result=self.redactor.fingerprint(turn.last_command_result)

    def start(self,turn,position):
        self.sequence+=1;category=task_category(turn,position);self.counts[category]+=1
        task=next((t for t in turn.team_our.player_tasks if t.task_position==position),None)
        self.active={'task_id':f'T{self.sequence:03d}','task_type':category,'type_ordinal':self.counts[category],
                     'start':turn.round_no,'deadline':turn.round_no+(task.timeout_rounds if task else 15),
                     'reward':task.gold_reward if task else 0,'seen':False,'submissions':0,'commands':0,'llm_requests':0,'llm_returns':0}
        self.used=0;self.repeats.clear();self.transcript_seen.clear()
        self.emit('accept',turn.round_no,{'deadline':self.active['deadline'],'reward':self.active['reward']},True)

    def execution(self,turn,plan,result,series):
        if not self.active:return
        self.redactor.protect(plan.get('headers',{}))
        for k,v in plan.get('query',{}).items():
            if any(x in k.lower() for x in ('token','key','password','auth')):self.redactor.protect(v)
        if self.active['task_type']!=1:self.redactor.protect(result.get('answer'))
        if self.active['task_type']!=1:
            from .task_contracts import extract_proof
            proof=extract_proof(result.get('output',''),result.get('required') or plan.get('required') or self.active.get('required'))
            if proof:self.redactor.protect(proof)
        # First register secrets from every source; then produce linked excerpts.
        for source in (result,plan):self.redactor.readable(source,0)
        status=result.get('status','ok' if result.get('ok') else 'unknown')
        repeat_key=self.redactor.fingerprint([status,plan,result.get('output'),result.get('detail')])
        self.repeats[repeat_key]+=1
        if self.repeats[repeat_key]>2:
            self.emit('repeat',turn.round_no,{'reason':status,'count':self.repeats[repeat_key],'fingerprint':repeat_key});return
        safe={'status':status,'command_id':self.active['commands'],'exit_code':result.get('exitCode'),'elapsed_ms':result.get('elapsed_ms'),
              'cwd':self.redactor.path(result.get('cwd','.')),'output':self.redactor.trace(result.get('output','')),
              'verification_kind':result.get('verification_kind'),'answer_structure':self.redactor.structure(result.get('answer')),
              'schema_reason':result.get('reason') if result.get('status')=='answer_schema' else None,
              'schema_details':result.get('schema_details',{}),
              'execution':{k:self.redactor.path(v) if k in ('program','cwd','interpreter','failed_path') else v for k,v in result.get('execution_evidence',{}).items()},
              'requirements':plan.get('required',{}),
              'reason':result.get('reason'),
              'candidate':self.redactor.safe_answer(result.get('answer'),self.active['task_type'])}
        safe['program_fingerprint']=self.redactor.fingerprint(plan)
        source=plan.get('code') or plan.get('script') or ''
        safe['program']=self.redactor.program(source,[f['line'] for f in safe['output']['frames']]) if source else '<declarative>'
        if plan.get('command'):safe['command_excerpt']=self.redactor.words(str(plan['command'])[-1800:])
        safe['plan_kind']=plan.get('kind','shell_or_source')
        safe['program_literals_masked']=True
        if plan.get('verify'):
            safe['verifier_program']=self.redactor.program(plan['verify'],[f['line'] for f in safe['output']['frames']])
        safe['plan_structure']=self.redactor.structure(plan)
        safe['paths']=[{k:self.redactor.path(v) if k in ('requested','base','path','located') else v for k,v in item.items()}
                       for item in result.get('path_evidence',[])[:10]]
        safe['patches']=[{k:self.redactor.path(v) if k=='path' else v for k,v in item.items()}
                         for item in result.get('patch_evidence',[])[:8]]
        if result.get('kind')=='repair':
            safe['checker']={'argv_paths':[self.redactor.path(a) for a in plan.get('check',[])[:6]],
                             'proof_obtained':bool(result.get('checked')),'format':plan.get('answer_format','json')}
        evidence=result.get('evidence',{})
        if isinstance(evidence,dict):
            # Executor evidence contains no request values or raw records.
            safe['api']={k:v for k,v in evidence.items() if k not in ('detail',)}
            safe['api']['requests']=[{k:self.redactor.readable(v,400)['text'] if k=='error' else v for k,v in row.items()}
                                     for row in evidence.get('requests',[])]
        if result.get('documents'):
            safe['documents']=[{'id':self.redactor.path(d.get('path','')),'fingerprint':self.redactor.fingerprint(d.get('text','')),
                'length':len(d.get('text','')),'complete':d.get('complete'), 'offset':d.get('offset',0),
                'next_offset':d.get('next_offset'), 'original_bytes':d.get('original_bytes'),
                'recognized_fields':[k for k in ('city','total_count','world_heritage_count','types','oldest_era') if k in d.get('text','')]} for d in result['documents'][:6]]
        # Avoid repeating bulky type-only plans. Documents and actual plans have
        # separate linked events; failures and settlement retain their own budget.
        safe.pop('plan_structure',None)
        if result.get('evidence',{}).get('detail'):
            safe['api_detail']=self.redactor.readable(result['evidence']['detail'],700)
        for key in ('detail','operations','checks','method'):
            if key in result:safe[key]=self.redactor.readable(result[key],1200)
        if result.get('retrieval'):
            retrieval=result['retrieval'];safe['retrieval']={k:v for k,v in retrieval.items() if k not in ('records','object')}
            safe['record_fields']=sorted({k for row in retrieval.get('records',[]) for k in row})[:24]
        if result.get('output'):safe['readable_output']=self.redactor.readable(result['output'],1800)
        self.emit('execution',turn.round_no,safe,not result.get('ok',True))
        for doc in result.get('documents',[])[:6]:
            self.artifact(turn.round_no,'document:'+self.redactor.path(doc.get('path','')),doc.get('text',''),6000)

    def record(self,turn,response,manager):
        for command in response.get('roleCommandMap',{}).values():
            if command.get('action')=='acceptTask':
                self.start(turn,manager.task_position)
                manager.series.begin(self.active['task_id'],self.active['task_type'])
            elif command.get('action')=='submitAnswer' and self.active:
                self.active['submissions']+=1
                try:answer=json.loads(command.get('taskAnswer',''))
                except ValueError:answer=command.get('taskAnswer','')
                if self.active['task_type']!=1:self.redactor.protect(answer)
                self.emit('submit',turn.round_no,{'structure':self.redactor.structure(answer),
                    'answer':self.redactor.safe_answer(answer,self.active['task_type']),
                    'checked':manager.context.candidate_checked,'strategy':manager.diagnostic,
                    'schema_pass':manager.context.schema_pass},True)
        if self.active:
            returned_request_id=self.active['llm_requests']
            if turn.errors:
                self.emit('platform_feedback',turn.round_no,{'errors':[{'code':e.error_code,'description':self.redactor.words(e.description)} for e in turn.errors]},True)
            if response.get('executeCmd'):self.active['commands']+=1
            if response.get('executeCmd'):
                plan=manager.context.last_plan
                self.emit('command',turn.round_no,{'command_id':self.active['commands'],
                    'fingerprint':self.redactor.fingerprint(plan),'plan':self.redactor.readable(plan,2800)},True)
                self.artifact(turn.round_no,'command:'+str(self.active['commands']),plan)
            if response.get('prompt'):
                self.active['llm_requests']+=1
                self.emit('llm_request',turn.round_no,{'purpose':manager.task_stage,'template':'v012-workflow-1',
                          'request_id':self.active['llm_requests'],'reuse':manager.series.last_reuse,'reason':manager.diagnostic,
                          'prompt':self.redactor.readable(response['prompt'],2400)})
            if turn.llm_response:
                fingerprint=self.redactor.fingerprint(turn.llm_response)
                if fingerprint!=self.last_llm:
                    self.last_llm=fingerprint;self.active['llm_returns']+=1
                    try:
                        parsed=json.loads(turn.llm_response)
                        if self.active['task_type']!=1 and isinstance(parsed,dict):self.redactor.protect(parsed.get('answer'))
                        detail={'structure':self.redactor.structure(parsed),
                            'request_id':returned_request_id,'content':self.redactor.readable(parsed,3200)}
                    except json.JSONDecodeError as error:detail={'parse_error':{'line':error.lineno,'column':error.colno,'position':error.pos}}
                    self.emit('llm_return',turn.round_no,detail)
                    self.artifact(turn.round_no,'llm_return:'+str(returned_request_id),turn.llm_response)
        self.previous={'r':turn.round_no,'gold':turn.team_our.gold,'commands':response.get('roleCommandMap',{}),
                       'vendor':{i.name:i.price for i in turn.vendor_shop},'shop':{i.name:i.price for i in turn.weapon_shop}}

    def drain(self):
        events=self.events;self.events=[];return events
