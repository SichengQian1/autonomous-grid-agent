"""Bounded per-task evidence; private text is never emitted to match telemetry."""
from __future__ import annotations
import json
from dataclasses import dataclass,field
from pathlib import PurePosixPath
from .task_answers import answer_fingerprint
from .task_contracts import current_contract
from copy import deepcopy

@dataclass(slots=True)
class TaskContext:
    documents: dict[str,str] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    workspace: str = '.'
    resolved: bool = False
    failed_execution: bool = False
    executed: bool = False
    recent: list[str] = field(default_factory=list)

    programs: list[object] = field(default_factory=list)
    incomplete: dict[str, int] = field(default_factory=dict)
    required: dict[str, str] | str = field(default_factory=dict)
    candidate: object = None
    candidate_checked: bool = False
    schema_pass: bool = False
    recovery: str = ''
    candidate_failure: str = ''
    last_plan: dict = field(default_factory=dict)
    failed_programs: set[str] = field(default_factory=set)
    last_program: str = ''
    contract_source: dict = field(default_factory=dict)
    api_bindings: dict = field(default_factory=dict)
    api_verified: bool = False
    rejected_plans: dict = field(default_factory=dict)
    blocked_plan: dict = field(default_factory=dict)

    def derive_contract(self, task_text=''):
        docs=dict(self.documents)
        if task_text:docs['current_requirement']=task_text
        required,source=current_contract(docs)
        if required:
            self.required=required;self.contract_source=source
        elif source:
            if self.contract_source.get('status')=='document_contract':self.required={}
            self.contract_source=source
        return required

    def keep_api_progress(self, plan, result):
        if plan.get('kind')!='api':return
        requests=result.get('evidence',{}).get('requests',[])
        if result.get('status')=='authentication_failed':self.api_bindings={}
        elif requests and any(r.get('status')==200 for r in requests):
            self.api_bindings={k:deepcopy(plan[k]) for k in ('url','headers','method','query','body') if k in plan}
        self.api_verified=bool(result.get('checked') and result.get('evidence',{}).get('complete')
                               and result.get('evidence',{}).get('filter_confirmed'))

    def restore_api_progress(self, plan):
        plan=deepcopy(plan)
        reset=plan.pop('reset_request',False)
        if not reset and self.api_bindings and plan.get('url')==self.api_bindings.get('url'):
            for key in ('headers','method','body'):
                if key in self.api_bindings:plan[key]=deepcopy(self.api_bindings[key])
            query=deepcopy(self.api_bindings.get('query',{}));query.update(plan.get('query',{}));plan['query']=query
        return plan

    def remember(self, program):
        self.last_plan=program if isinstance(program,dict) else {}
        self.last_program=answer_fingerprint(program)
        self.programs=(self.programs+[json.dumps(program,ensure_ascii=False)[:4000]])[-2:]

    def ingest(self, payload, output: str, ok: bool):
        envelope=payload.get('procedure_result',payload) if isinstance(payload,dict) else {}
        if not isinstance(envelope,dict): envelope={}
        files=envelope.get('files')
        if isinstance(files,list): self.files=[f[:256] for f in files[:100] if isinstance(f,str)]
        workspace=envelope.get('workspace')
        if isinstance(workspace,str) and len(workspace)<512:
            p=PurePosixPath(workspace)
            if not p.is_absolute() and '..' not in p.parts:
                self.workspace=str(p);self.resolved=True
        docs=envelope.get('documents')
        if isinstance(docs,list):
            for doc in docs[:6]:
                if isinstance(doc,dict) and isinstance(doc.get('path'),str) and isinstance(doc.get('text'),str):
                    path=doc['path'][:256]
                    offset=doc.get('offset',0)
                    if not isinstance(offset,int) or offset<0: offset=0
                    old=self.documents.get(path,'')
                    if isinstance(offset,int) and 0<offset<=len(old):
                        self.documents[path]=(old[:offset]+doc['text'])[:14000]
                    else:
                        self.documents[path]=doc['text'][:14000]
                    if doc.get('complete') is False or len(self.documents[path]) < offset+len(doc['text']):
                        self.incomplete[path]=len(self.documents[path])
                    else: self.incomplete.pop(path,None)
            while sum(len(s) for s in self.documents.values())>18000 or len(self.documents)>12:
                # Preserve the original requirement document; evict older supporting evidence.
                keys=list(self.documents)
                removed=keys[1] if len(keys)>1 else keys[0]
                del self.documents[removed]
                self.incomplete.pop(removed,None)
            return
        self.failed_execution=not ok or envelope.get('ok') is False
        self.executed=not self.failed_execution
        if self.failed_execution and self.last_program:
            if len(self.failed_programs)<16: self.failed_programs.add(self.last_program)
        elif self.executed: self.failed_programs.clear()
        self.candidate=None
        self.candidate_checked=self.schema_pass=False
        if (self.executed or envelope.get('computed') is True) and 'answer' in envelope:
            self.candidate=envelope['answer']
            self.candidate_checked=envelope.get('checked') is True
            self.schema_pass=envelope.get('schema_pass') is True
            self.candidate_failure=('business_assertion_failed' if envelope.get('verification_kind')=='assertion' else str(envelope.get('status',''))) if self.failed_execution else ''
        self.recent=(self.recent+[output[:6000]])[-2:]

    def prompt(self):
        return json.dumps({'workspace':self.workspace,'documents':self.documents,'files':self.files,
                           'incomplete_documents':self.incomplete,'required':self.required,'contract_source':self.contract_source,
                           'request_binding_preserved':bool(self.api_bindings),
                           'recovery':self.recovery,
                           'recent_execution':self.recent,'recent_programs':self.programs,
                           'workspace_files':{p:str(PurePosixPath(p).relative_to(self.workspace)) for p in self.files if PurePosixPath(p).is_relative_to(self.workspace)}},ensure_ascii=False)
