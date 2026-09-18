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
        self.last_reuse={'used':False,'reason':'new_task'}
        self.pending[task_id]={'type':task_type,'plan':{},'executed':False}

    def workflow_hint(self, task_type):
        prior=self.methods.get((task_type,'bootstrap'))
        return deepcopy(prior['template']) if prior else {}

    def record_script_proof(self, task_id, required, plan, submitted=None):
        from .task_answers import shape_error
        if not isinstance(required,dict) or len(required)!=1:return
        if submitted is not None and shape_error(submitted,required):return
        pending=self.pending.setdefault(task_id,{'type':2,'plan':{},'executed':False})
        if pending['type']!=2:return
        # Retain a workflow, not source, file names, patch values or proof values.
        text=str(plan.get('command',plan.get('script',plan.get('code',''))))
        launcher='python3' if 'python' in text else 'shell'
        pending['workflow']={'kind':'repair_workflow','required':deepcopy(required),
                             'extraction':'current_output_json_or_labeled_field','launcher':launcher,
                             'steps':['confirm_current_workspace','read_current_spec_and_files','apply_unique_or_receipted_patch','run_real_checker','package_current_proof']}
        pending['executed']=True

    def workflow_for(self, task_type, required):
        prior=self.methods.get((task_type,'repair_workflow'))
        if prior and prior['template'].get('required')==required:
            return prior
        return None

    def prepare(self, plan, task_id, task_type):
        plan=deepcopy(plan);kind=plan.get('kind')
        self.last_reuse={'used':False,'reason':'fresh_plan'}
        if kind in ('api','repair') and not plan.get('compatibility') and plan.get('required'):
            plan['compatibility']={'contract':deepcopy(plan['required']),
                                   'schema':{'kind':kind,'records_path':plan.get('records_path','')}}
        prior=self.methods.get((task_type,kind))
        if prior and 'reuse' not in plan and plan.get('compatibility')==prior['compatibility']:
            needed=('url','query','filter','fields','required') if kind=='api' else ('cwd','check','edits')
            mappings_current=kind!='api' or set(prior['template'].get('fields',{}))<=set(plan.get('fields',{}))
            if mappings_current and all(k in plan for k in needed):plan['reuse']=True
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
        method=result.get('method')
        if isinstance(method,dict) and result.get('ok') and (result.get('checked') or result.get('retrieval',{}).get('complete')):
            pending['workflow_method']=deepcopy(method)
            self._save(task_id,'observed')
        if result.get('documents') and result.get('files'):
            self.observations[pending['type']]={'level':'observed','task_id':task_id,
                'method':'bounded_inventory_then_document_project_resolution','scope':'current_match_task_category',
                'invalidates_on':'new_task_requires_fresh_inventory_and_cwd_confirmation'}
        if result.get('ok') and (result.get('checked') or result.get('computed')):
            pending['executed']=True
            pending['answer']=result.get('answer')
            self._save(task_id,'executed')
        elif (result.get('reason') or result.get('status')) in ('filter_not_applied','records_shape','parse_or_compute_failed','authentication_failed','check_not_structured','FileNotFoundError','non_unique_patch','checker_reported_failure'):
            key=(pending['type'],pending['plan'].get('kind'))
            if key in self.methods:
                self.methods.pop(key);self.invalidations+=1

    def settle(self, task_id, outcome):
        pending=self.pending.get(task_id)
        if pending and (pending['executed'] or pending.get('workflow_method')):
            self._save(task_id,'platform_full' if outcome=='full' else 'executed')
        self.pending.pop(task_id,None)

    def _save(self, task_id, level):
        pending=self.pending[task_id];plan=pending['plan'];kind=plan.get('kind')
        if pending.get('workflow_method'):
            self.methods[(pending['type'],'bootstrap')]={'template':deepcopy(pending['workflow_method']),
                'task_id':task_id,'level':level,'invalidates_on':['current_document_or_response_change']}
        if pending.get('workflow'):
            self.methods[(pending['type'],'repair_workflow')]={'template':deepcopy(pending['workflow']),
                'compatibility':{'contract':deepcopy(pending['workflow']['required'])},'task_id':task_id,'level':level,
                'invalidates_on':['contract_change','current_workspace_or_checker_failure']}

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
