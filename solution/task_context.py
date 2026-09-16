"""Bounded per-task evidence; private text is never emitted to match telemetry."""
from __future__ import annotations
import json
from dataclasses import dataclass,field
from pathlib import PurePosixPath

@dataclass(slots=True)
class TaskContext:
    documents: dict[str,str] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    workspace: str = '.'
    resolved: bool = False
    failed_execution: bool = False
    executed: bool = False
    recent: list[str] = field(default_factory=list)

    def ingest(self, payload, output: str, ok: bool):
        envelope=payload.get('procedure_result',payload) if isinstance(payload,dict) else {}
        if not isinstance(envelope,dict): envelope={}
        docs=envelope.get('documents')
        if isinstance(docs,list):
            for doc in docs[:6]:
                if isinstance(doc,dict) and isinstance(doc.get('path'),str) and isinstance(doc.get('text'),str):
                    self.documents[doc['path'][:256]]=doc['text'][:6000]
            while sum(len(s) for s in self.documents.values())>18000 or len(self.documents)>12:
                # Preserve the original requirement document; evict older supporting evidence.
                keys=list(self.documents)
                del self.documents[keys[1] if len(keys)>1 else keys[0]]
            files=envelope.get('files')
            if isinstance(files,list): self.files=[f[:256] for f in files[:60] if isinstance(f,str)]
            workspace=envelope.get('workspace')
            if isinstance(workspace,str) and len(workspace)<512:
                p=PurePosixPath(workspace)
                if not p.is_absolute() and '..' not in p.parts:
                    self.workspace=str(p);self.resolved=True
            return
        self.failed_execution=not ok or envelope.get('ok') is False
        self.executed=not self.failed_execution
        self.recent=(self.recent+[output[:6000]])[-2:]

    def prompt(self):
        return json.dumps({'workspace':self.workspace,'documents':self.documents,'files':self.files,
                           'recent_execution':self.recent},ensure_ascii=False)
