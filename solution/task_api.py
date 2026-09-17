"""Deterministic, bounded API task execution; all bindings come from this task."""

from .task_answers import shape_error

def run_api(options, remaining):
    import json, hashlib, urllib.request, urllib.parse, urllib.error
    import re
    def field(value, path):
        for key in path.split('.') if path else []:
            value=value[int(key)] if isinstance(value,list) else value[key]
        return value
    def shape(value):
        if isinstance(value,dict): return {str(k):type(v).__name__ for k,v in list(value.items())[:24]}
        return type(value).__name__
    evidence={'requests':[], 'fields':{}, 'complete':False, 'reason':'not_started'}
    result={'ok':False,'checked':False,'evidence':evidence}
    def fail(reason, **details):
        evidence.update(reason=reason,**details);result['status']=reason
        return result
    parts=urllib.parse.urlsplit(options.get('url',''))
    if parts.scheme!='http' or parts.hostname not in ('localhost','127.0.0.1') or parts.username:
        return fail('loopback_only')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs): raise ValueError('redirect_refused')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    pagination=options.get('pagination',{})
    records=[];identities=set();pages=set();total=None;complete=False;filter_ok=True
    start=int(pagination.get('start',1));size=int(pagination.get('size',100));cursor=pagination.get('initial_cursor')
    if not 1<=size<=1000:return fail('page_size')
    filter_spec=options.get('filter',{})
    # Binding a query condition is not proof that the server applied it.
    filter_proved=False
    cache=None; cached=None
    if options.get('task_id') and options.get('cache_namespace'):
        from pathlib import Path
        bindings={k:options.get(k) for k in ('url','method','query','body','headers','filter','records_path','pagination','unpaginated')}
        signature=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
        name=hashlib.sha256((options['cache_namespace']+options['task_id']).encode()).hexdigest()
        directory=Path(options.get('base','/tmp/selfEvolutionTask'))/'.agent_task_cache'
        # Never trust a task-provided symlink as the agent's cache directory.
        if not directory.is_symlink():
            directory.mkdir(exist_ok=True)
            cache=directory/(name+'.json')
            if not cache.is_symlink() and cache.is_file() and cache.stat().st_size<2000000:
                try:
                    value=json.loads(cache.read_text())
                    if value.get('signature')==signature and value.get('complete'):
                        cached=value;records=value['records'];complete=True;filter_proved=value['filter_proved'];total=value['total']
                        evidence['cache']='current_task_binding_match'
                except (ValueError,OSError,KeyError):pass
    try:
        for index in range(0 if cached else min(max(int(pagination.get('max_pages',30)),1),30)):
            query=dict(urllib.parse.parse_qsl(parts.query));query.update(options.get('query',{}))
            if pagination:
                parameter=pagination.get('parameter','page')
                if pagination.get('mode')=='cursor':
                    if cursor is not None:query[parameter]=cursor
                else:query[parameter]=start+index*int(pagination.get('step',1))
                if pagination.get('size_parameter'):query[pagination['size_parameter']]=size
            method=options.get('method','GET').upper()
            if method not in ('GET','POST'):return fail('request_method')
            headers=dict(options.get('headers',{}))
            body=None
            if method=='POST':
                body=json.dumps(dict(options.get('body',{}),**query)).encode();headers.setdefault('Content-Type','application/json')
            url=urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query) if method=='GET' else ''))
            request=urllib.request.Request(url,data=body,headers=headers,method=method)
            row={'page':index+1,'method':method,'parameter_names':sorted(query),
                 'auth_provided':any(k.lower() in ('authorization','x-api-key','cookie','x-token','token') for k in headers) or any(k.lower() in ('token','api_key','key','access_token') for k in query),'records_path':options.get('records_path',''),
                 'service_id':hashlib.sha256((parts.netloc+parts.path).encode()).hexdigest()[:12]}
            evidence['requests'].append(row)
            try:
                with opener.open(request,timeout=min(2,remaining())) as response:
                    row['status']=response.status;raw=response.read(256001)
            except urllib.error.HTTPError as error:
                row['status']=error.code
                evidence['detail']=error.read(1200).decode(errors='replace')
                return fail('authentication_failed' if error.code in (401,403) else 'request_failed')
            if len(raw)>256000:return fail('response_limit')
            evidence['stage']='response_parse'
            data=json.loads(raw);row['structure']=shape(data)
            if isinstance(data,dict) and (data.get('code') in (401,403) or data.get('authenticated') is False):return fail('authentication_failed')
            if isinstance(data,dict) and (data.get('error') or data.get('success') is False):return fail('error_response',detail=str(data.get('error','unsuccessful'))[:1200])
            evidence['stage']='records_path'
            page=field(data,options.get('records_path',''))
            if not isinstance(page,list):return fail('records_shape')
            row['returned']=len(page)
            row['record_structure']=shape(page[0]) if page else {}
            fingerprint=hashlib.sha256(json.dumps(page,sort_keys=True).encode()).hexdigest()
            if page and fingerprint in pages:return fail('repeated_page',count=len(records))
            pages.add(fingerprint);added=0
            for record in page:
                if filter_spec.get('path'):
                    actual=field(record,filter_spec['path'])
                    filter_ok &= actual==filter_spec.get('value')
                    if not filter_ok:evidence['detail']={'expected_filter':filter_spec.get('value'),'actual_filter':actual}
                    filter_proved=True
                key=field(record,pagination['id_path']) if pagination.get('id_path') else record
                if key is None:return fail('identity_missing')
                key=json.dumps(key,sort_keys=True)
                if key not in identities:records.append(record);identities.add(key);added+=1
            row.update(new=added,cumulative=len(records),filter_ok=filter_ok)
            if filter_spec.get('echo_path'):
                filter_ok &= field(data,filter_spec['echo_path'])==filter_spec.get('value');filter_proved=True
            if not filter_ok:return fail('filter_not_applied')
            if len(records)>10000:return fail('record_limit')
            if pagination.get('total_path'):
                reported=field(data,pagination['total_path'])
                if isinstance(reported,bool) or not isinstance(reported,int) or reported<0:return fail('total_shape')
                row['total']=reported
                if total is not None and reported!=total:return fail('total_changed')
                total=reported
                if len(records)>total:return fail('total_mismatch')
                if len(records)==total:complete=True;row['end']='total_matched';break
            ended=False
            if pagination.get('end_path'):
                ended=field(data,pagination['end_path'])==pagination.get('end_value',False)
                row['end_marker']=ended
            if pagination.get('next_path'):
                cursor=field(data,pagination['next_path']);ended=cursor is None or cursor == '' or cursor is False
                row['next_present']=not ended
            if not page and pagination.get('empty_is_end') is True:ended=True;row['end']='documented_empty_page'
            if not pagination and options.get('unpaginated') is True:ended=True;row['end']='documented_unpaginated'
            if ended:
                if total is not None and len(records)!=total:return fail('total_mismatch',count=len(records))
                complete=True;break
            if not page:break
            if not pagination:break
        evidence.update(complete=complete,filter_confirmed=filter_proved and filter_ok,count=len(records),total=total)
        if cache and not cache.is_symlink():
            value={'signature':signature,'records':records,'complete':complete,'filter_proved':filter_proved,'total':total}
            serialized=json.dumps(value)
            if len(serialized.encode())<2000000:cache.write_text(serialized)
        answer={};field_evidence={}
        for name,spec in options.get('fields',{}).items():
            evidence.update(stage='calculate',field=name,operation=spec.get('op'))
            op=spec['op'];values=[field(r,spec['path']) for r in records] if spec.get('path') else []
            verified=True
            if op=='constant':answer[name]=spec['value'];verified=bool(spec.get('source')=='requirement')
            elif op=='count':answer[name]=len(records);verified=complete
            elif op=='count_equal':
                if any(type(v)!=type(spec['value']) for v in values):return fail('field_value_type',field=name,actual_types=sorted({type(v).__name__ for v in values}),expected_type=type(spec['value']).__name__)
                answer[name]=sum(v==spec['value'] for v in values);verified=complete
            elif op=='unique':
                if spec.get('flatten'):values=[v for group in values for v in group]
                answer[name]=list(dict.fromkeys(values))
                if spec.get('sort')=='ascending':answer[name].sort()
                elif spec.get('sort')=='descending':answer[name].sort(reverse=True)
                verified=complete
            elif op=='sum':answer[name]=sum(values);verified=complete
            elif op in ('min_by','max_by'):
                mode=spec.get('comparison')
                def key(record):
                    value=field(record,spec['path'])
                    if mode=='numeric':return float(value)
                    if mode=='ordered':return spec['order'].index(value)
                    if mode=='era':
                        # Explicit task-defined regex/rank only; never lexical era ordering.
                        pattern=spec['pattern']
                        if len(pattern)>200 or len(str(value))>120 or re.search(r'\)[+*{]',pattern):raise ValueError('era_pattern_limit')
                        match=re.fullmatch(pattern,str(value))
                        if not match:raise ValueError('era_unparsed')
                        year=int(match.group(spec.get('year_group',1)))
                        label=match.group(spec['era_group']) if spec.get('era_group') else ''
                        return -year if label in spec.get('before_labels',[]) else year
                    if mode=='lexical':return value
                    if isinstance(value,(int,float)) and not isinstance(value,bool):return value
                    raise ValueError('comparison_rule_missing')
                selected=(min if op=='min_by' else max)(records,key=key)
                answer[name]=field(selected,spec['value_path']);verified=complete
            else:return fail('unknown_aggregate')
            field_evidence[name]={'method':op,'path':spec.get('path','requirement'),'verified':verified,
                                  'type':type(answer[name]).__name__,'comparison':spec.get('comparison'),
                                  'source':spec.get('source','records')}
        evidence['fields']=field_evidence
        result.update(answer=answer,computed=True,count=len(records),schema_pass=False)
        # The compatibility layer may use this executor for arbitrary tasks. API
        # task contracts are additionally required by TaskManager before fast-submit.
        from_contract=options.get('required')
        problem=shape_error(answer,from_contract) if from_contract else ''
        result['schema_pass']=bool(from_contract) and not problem
        if problem:return fail('answer_schema',schema_reason=problem)
        if not complete:return fail('incomplete_pages')
        if filter_spec and not filter_proved:return fail('filter_unconfirmed')
        if options.get('require_filter') and not filter_proved:return fail('filter_unconfirmed')
        if not all(v['verified'] for v in field_evidence.values()):return fail('field_unverified')
        result.update(ok=True,checked=True,status='api_checked');evidence['reason']='confirmed'
        return result
    except (KeyError,IndexError,TypeError,ValueError) as error:
        return fail('parse_or_compute_failed',exception=type(error).__name__,
                    detail=str(error)[:200],count=len(records))
    except Exception as error:
        return fail('request_failed',exception=type(error).__name__)
