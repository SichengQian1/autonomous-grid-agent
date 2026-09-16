"""Bounded per-task evidence; private text is never emitted to match telemetry."""
from __future__ import annotations
import json
from dataclasses import dataclass,field
from pathlib import PurePosixPath
from .task_answers import answer_fingerprint

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
    failed_programs: set[str] = field(default_factory=set)
    last_program: str = ''

    def remember(self, program):
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
        if self.executed and 'answer' in envelope:
            self.candidate=envelope['answer']
            self.candidate_checked=envelope.get('checked') is True
            self.schema_pass=envelope.get('schema_pass') is True
        self.recent=(self.recent+[output[:6000]])[-2:]

    def prompt(self):
        return json.dumps({'workspace':self.workspace,'documents':self.documents,'files':self.files,
                           'incomplete_documents':self.incomplete,'required':self.required,
                           'recovery':self.recovery,
                           'recent_execution':self.recent,'recent_programs':self.programs,
                           'workspace_files':{p:str(PurePosixPath(p).relative_to(self.workspace)) for p in self.files if PurePosixPath(p).is_relative_to(self.workspace)}},ensure_ascii=False)
