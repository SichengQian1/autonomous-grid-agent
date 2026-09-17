"""Match-local methods, never cached answers, credentials or sandbox files."""
from dataclasses import dataclass, field
from copy import deepcopy
import hashlib
import json

@dataclass
class TaskSeries:
    methods: dict = field(default_factory=dict)
    pending: dict = field(default_factory=dict)
    observations: dict = field(default_factory=dict)
    hits: int = 0
    invalidations: int = 0
    last_reuse: dict = field(default_factory=dict)

    def begin(self,task_id,task_type):
        self.pending[task_id]={'type':task_type,'plan':{},'executed':False}

    def prepare(self, plan, task_id, task_type):
        plan=deepcopy(plan);kind=plan.get('kind')
        self.last_reuse={'used':False,'reason':'fresh_plan'}
        prior=self.methods.get((task_type,kind))
        if plan.pop('reuse',False):
            if not prior:
                self.last_reuse={'used':False,'reason':'no_compatible_method'}
                raise ValueError('reuse_unavailable')
            # Explicit fresh bindings are mandatory, even when the service appears unchanged.
            needed=('url','query','filter','fields','required') if kind=='api' else ('cwd','check','edits')
            if any(k not in plan for k in needed):raise ValueError('reuse_needs_fresh_bindings')
            signature=plan.get('compatibility')
            if not isinstance(signature,dict) or not signature or signature!=prior['compatibility']:
                self.invalidations+=1;self.last_reuse={'used':False,'reason':'contract_changed','source':prior['task_id']}
                raise ValueError('reuse_contract_changed')
            merged=deepcopy(prior['template'])
            if kind=='api':
                fields=merged.get('fields',{});fields.update(plan['fields']);plan['fields']=fields
            merged.update(plan);plan=merged
            self.hits+=1
            self.last_reuse={'used':True,'source':prior['task_id'],'level':prior['level'],'reason':'fresh_bindings_checked'}
        plan['task_id']=task_id
        self.pending[task_id]={'plan':deepcopy(plan),'type':task_type,'executed':False}
        return plan

    def observe(self, task_id, result):
        pending=self.pending.get(task_id)
        if not pending:return
        if result.get('documents') and result.get('files'):
            self.observations[pending['type']]={'level':'observed','task_id':task_id,
                'method':'bounded_inventory_then_document_project_resolution','scope':'current_match_task_category',
                'invalidates_on':'new_task_requires_fresh_inventory_and_cwd_confirmation'}
        if result.get('ok') and (result.get('checked') or result.get('computed')):
            pending['executed']=True
            pending['answer']=result.get('answer')
            self._save(task_id,'executed')
        elif result.get('status') in ('filter_not_applied','records_shape','parse_or_compute_failed','authentication_failed','check_not_structured','FileNotFoundError','non_unique_patch','checker_reported_failure'):
            key=(pending['type'],pending['plan'].get('kind'))
            if key in self.methods:
                self.methods.pop(key);self.invalidations+=1

    def settle(self, task_id, outcome):
        pending=self.pending.get(task_id)
        if pending and pending['executed']:
            self._save(task_id,'platform_full' if outcome=='full' else 'executed')
        self.pending.pop(task_id,None)

    def _save(self, task_id, level):
        pending=self.pending[task_id];plan=pending['plan'];kind=plan.get('kind')
        if kind not in ('api','repair'):return
        compatibility=plan.get('compatibility',{})
        if not isinstance(compatibility,dict) or not compatibility:return
        if kind=='api':
            template={k:deepcopy(plan[k]) for k in ('kind','records_path','pagination','fields','required','require_filter','unpaginated') if k in plan}
            # Cursor values and query-object constants are always task-local.
            template.get('pagination',{}).pop('initial_cursor',None)
            template['fields']={k:v for k,v in template.get('fields',{}).items() if v.get('op')!='constant'}
        else:
            template={k:deepcopy(plan[k]) for k in ('kind','answer_path','answer_format','answer_pattern') if k in plan}
        if kind=='repair':
            def proof_strings(value):
                if isinstance(value,dict):return [s for v in value.values() for s in proof_strings(v)]
                if isinstance(value,list):return [s for v in value for s in proof_strings(v)]
                return [value] if isinstance(value,str) else []
            if any(len(v)>3 and v in template.get('answer_pattern','') for v in proof_strings(pending.get('answer'))):
                template.pop('answer_pattern',None)
        key=(pending['type'],kind)
        # A later partial result must not inherit a full-success label.
        self.methods[key]={'template':template,'compatibility':deepcopy(compatibility),'task_id':task_id,'level':level,
                           'invalidates_on':['contract_change','fresh_binding_missing','runtime_schema_or_filter_failure']}

    def prompt(self, task_type):
        values=([self.observations[task_type]] if task_type in self.observations else [])+[v for (t,k),v in self.methods.items() if t==task_type]
        return json.dumps(values,ensure_ascii=False)[:6500]
