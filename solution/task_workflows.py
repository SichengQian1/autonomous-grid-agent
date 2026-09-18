"""Current-document workflows executed inside the bounded task sandbox."""


def run_workflow(options, info, base, inventory, execute, remaining):
    import json, re, os, hashlib
    from pathlib import Path
    import urllib.request, urllib.parse, urllib.error

    documents=info.get('documents',[])
    current=next((d for d in documents if Path(d['path']).name==options.get('filename')),None)
    if not current:return dict(info,ok=False,status='task_document_missing')
    required,contract=current_contract({current['path']:current['text']})
    result=dict(info,required=required,contract_source=contract,checked=False)
    text=current['text']
    def finish(status, **kw):
        result.update(status=status,**kw);return result
    if not current.get('complete'):return finish('requirement_incomplete',ok=False)
    if not required:return finish('contract_unknown',ok=False)
    files=inventory()
    def read(path):
        remaining()
        p=(base/path).resolve()
        if not p.is_relative_to(base) or not p.is_file() or p.stat().st_size>100000:raise ValueError('workflow_file_scope')
        return p.read_text(errors='replace')[:16000]
    def add_doc(path):
        if path not in [d['path'] for d in documents]:
            value=read(path);size=(base/path).stat().st_size
            documents.append({'path':path,'text':value,'complete':len(value.encode())>=size,'original_bytes':size})

    # A single proof field and a uniquely located checker identify repair work.
    checks=[f for f in files if Path(f).name in ('check','check.py','check.sh')]
    mentioned=[f for f in checks if str(Path(f).parent)!='.' and str(Path(f).parent) in text]
    if mentioned:checks=mentioned
    if options.get('task_type')==1:checks=[]
    if len(required)==1 and len(checks)==1:
        checker=(base/checks[0]).resolve();workspace=checker.parent
        specs=[f for f in files if Path(f).name=='spec.md' and (base/f).parent==workspace]
        if len(specs)!=1:return finish('specification_ambiguous',ok=False)
        spec=read(specs[0]);add_doc(specs[0])
        result['workspace']=str(workspace.relative_to(base))
        operations=[];evidence=[];checks_evidence=[]
        def target(name):
            p=(workspace/name).resolve()
            if not p.is_relative_to(workspace) or p==checker:raise ValueError('workflow_protected_path')
            return p
        def parse_rules(source, feedback=False):
            found=[];section=None
            for line in source.splitlines():
                remaining()
                m=re.search(r'([A-Za-z0-9_./-]+/?)\s*`?\s*(?:必须存在|must exist)[^\n]*?(?:权限\s*[为是]?|mode\s*[:=]?)\s*`?(0?[0-7]{3})',line,re.I)
                if m:found.append({'op':'directory' if m[1].endswith('/') else 'permission','path':m[1],'mode':int(m[2],8)})
                if line.lstrip().startswith('#'):
                    m=re.search(r'([A-Za-z0-9_./-]+\.(?:conf|cfg|yaml|yml|json|ini|toml|properties))',line)
                    section=m[1] if m else None
                m=re.match(r'\s*(?:[-*]\s*)?(?:第\s*(\d+)\s*行|[Ll]ine\s+(\d+))\s*[:：、]\s*(.*)',line)
                if m and section:
                    value=m[3].strip().strip('`')
                    found.append({'op':'line','path':section,'line':int(m[1] or m[2]),'value':value})
                if feedback:
                    m=re.search(r'\[FAIL\]\s+DIR\s+(\S+)\s+[—-]+\s*(?:期望|expected)\s+exists\s*[,，]\s*(0?[0-7]{3})',line,re.I)
                    if m:found.append({'op':'directory','path':m[1],'mode':int(m[2],8)})
                    m=re.search(r'\[FAIL\]\s+LINE\s+([^: ]+):(\d+)\s+[—-]+\s*(?:期望|expected)\s+`([^`]+)`',line,re.I)
                    if m:found.append({'op':'line','path':m[1],'line':int(m[2]),'value':m[3]})
            if len(found)>24:raise ValueError('workflow_operation_limit')
            return found
        def apply(ops):
            # Validate every target before any mutation, including symlink escapes.
            prepared=[(op,target(op['path'])) for op in ops]
            for op,p in prepared:
                remaining();before=p.read_bytes() if p.is_file() and p.stat().st_size<=100000 else None
                old_mode=(p.stat().st_mode & 0o777) if p.exists() else None
                if op['op']=='directory':
                    p.mkdir(parents=True,exist_ok=True);p.chmod(op['mode'])
                elif op['op']=='permission':
                    if not p.is_file():raise FileNotFoundError(op['path'])
                    p.chmod(op['mode'])
                    # Only task-referenced executable project scripts, never checker.
                    if p.suffix in ('.sh','.py') and before is not None and b'\r\n' in before:
                        p.write_bytes(before.replace(b'\r\n',b'\n'))
                elif op['op']=='line':
                    if before is None:raise FileNotFoundError(op['path'])
                    n=op['line'];lines=before.decode().splitlines()
                    if not 1<=n<=len(lines):raise ValueError('line_out_of_range')
                    lines[n-1]=op['value'];p.write_text('\n'.join(lines)+'\n')
                after=p.read_bytes() if p.is_file() and p.stat().st_size<=100000 else None
                evidence.append({'op':op['op'],'path':str(p.relative_to(base)),
                    'line':op.get('line'),'changed':before!=after or old_mode!=(p.stat().st_mode&0o777),
                    'before_hash':hashlib.sha256(before or b'').hexdigest()[:12],
                    'after_hash':hashlib.sha256(after or b'').hexdigest()[:12]})
        try:
            operations=parse_rules(spec)
            if not operations:return finish('specification_unknown',ok=False)
            apply(operations)
            seen=set()
            for attempt in range(3):
                code,output=execute([str(checker)],workspace)
                failures=[line for line in output.splitlines() if re.search(r'\[FAIL\]|\bFAIL(?:ED)?\b',line)][:12]
                checks_evidence.append({'attempt':attempt+1,'exit_code':code,'failures':failures,'output':output[:2500]})
                proof=extract_proof(output,required) if code==0 and not failures and len(output)<=12000 else None
                if proof:
                    return finish('repair_checked',ok=True,checked=True,schema_pass=True,answer=proof,output=output,
                        operations=evidence,checks=checks_evidence,method={'family':'repair','parser':'spec_rules_v1','operations':sorted({o['op'] for o in operations})})
                fixes=parse_rules(output,True)
                signature=json.dumps(fixes,sort_keys=True)
                if not fixes or signature in seen:break
                seen.add(signature);apply(fixes)
            return finish('checker_reported_failure' if failures else 'check_failed' if code else 'proof_missing',
                          ok=False,output=output,operations=evidence,checks=checks_evidence)
        except (OSError,ValueError,TimeoutError) as error:
            return finish('repair_execution_failed',ok=False,error_type=type(error).__name__,
                          detail=str(error)[:400],operations=evidence,checks=checks_evidence)

    # Only this known answer family gets an automatic query workflow. Unknown
    # contracts keep the existing model/script route and current documents.
    if not {'city','total_count'}<=set(required):return finish('workflow_unknown',ok=False)
    docs='\n'.join(d['text'] for d in documents)
    urls=re.findall(r'https?://(?:localhost|127\.0\.0\.1):\d+(?:/[A-Za-z0-9_./?=&%-]*)?',docs)
    urls=list(dict.fromkeys(urls))
    if not urls:return finish('service_not_documented',ok=False)
    url=urls[0];parts=urllib.parse.urlsplit(url)
    if not parts.path or parts.path=='/':
        endpoint=re.search(r'(/api/[A-Za-z0-9_/-]+)',docs)
        if endpoint:parts=parts._replace(path=endpoint[1])
    object_match=re.search(r'(?:查询|统计)\s*[`"“]?([\u4e00-\u9fff]{2,8}?)\s*(?:市|的|文化遗产)',text)
    if not object_match:object_match=re.search(r'(?:city|location|query object)\s*[:=]\s*[`"\']?([\w -]+)',text,re.I)
    obj=object_match[1].strip().rstrip('市') if object_match else ''
    if not obj:return finish('query_object_unknown',ok=False)
    credential=None;documented_header='X-API-Key'
    for line in docs.splitlines():
        if re.search(r'api.?key|authorization|认证|密钥',line,re.I):
            m=re.search(r'(?:Bearer\s+|(?:X-API-Key|api[_ -]?key|密钥)\s*[`"\']?\s*[:：=|]\s*[`"\']?)([A-Za-z0-9_-]{6,})',line,re.I)
            if not m:m=re.search(r'`([A-Za-z0-9_-]{8,})`',line)
            if m:credential=m[1];documented_header='Authorization' if re.search('Bearer',line,re.I) else 'X-API-Key';break
    prior=options.get('method',{})
    auth=prior.get('auth_header',documented_header)
    if auth not in ('Authorization','X-API-Key'):auth=documented_header
    parameter=prior.get('query_parameter') or ('location' if re.search(r'\blocation\b',docs) else 'city')
    if parameter not in ('location','city','q','keyword'):parameter='city'
    attempts=[];records=[];identities=set();total=None;complete=False;offset=0;seen_pages=set();changed_auth=False;changed_parameter=False
    filter_state='unconfirmed';resolved_path='';paging_path='';reason='request_limit';body=None
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):raise ValueError('redirect_refused')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def arrays(value,prefix='',depth=0):
        if depth>4:return []
        if isinstance(value,list) and all(isinstance(v,dict) for v in value):return [(prefix,value)]
        if isinstance(value,dict):return [item for k,v in value.items() for item in arrays(v,'.'.join(filter(None,(prefix,k))),depth+1)]
        return []
    try:
        for number in range(16):
            remaining()
            query=dict(urllib.parse.parse_qsl(parts.query))
            for name in ('city','location','q','keyword'):query.pop(name,None)
            query.update({parameter:obj,'limit':100,'offset':offset})
            headers={auth:('Bearer ' if auth=='Authorization' else '')+credential} if credential else {}
            target_url=urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
            row={'page':len(seen_pages)+1,'method':'GET','parameter_names':sorted(query),'auth_provided':bool(headers),'offset':offset}
            attempts.append(row)
            try:
                with opener.open(urllib.request.Request(target_url,headers=headers),timeout=min(2,remaining())) as response:
                    row['status']=response.status;raw=response.read(256001)
            except urllib.error.HTTPError as error:
                row['status']=error.code;detail=error.read(1000).decode(errors='replace');row['error']=detail
                if error.code in (401,403) and credential and not changed_auth:
                    auth='Authorization' if auth!='Authorization' else 'X-API-Key';changed_auth=True;continue
                if error.code==400 and not changed_parameter:
                    candidates=[p for p in ('location','city','q','keyword') if re.search(r'\b'+p+r'\b',detail) and p!=parameter]
                    if len(candidates)==1:parameter=candidates[0];changed_parameter=True;continue
                    if parameter=='city':parameter='location';changed_parameter=True;continue
                reason='authentication_failed' if error.code in (401,403) else 'request_failed';break
            if len(raw)>256000:reason='response_limit';break
            body=json.loads(raw)
            if isinstance(body,dict) and (body.get('error') or body.get('success') is False or body.get('code') in (401,403)):
                reason='error_response';break
            candidates=arrays(body)
            if len(candidates)!=1:reason='records_ambiguous';break
            resolved_path,page=candidates[0];row['records_path']=resolved_path
            row['record_structure']={k:type(v).__name__ for k,v in (page[0] if page else {}).items()}
            pagination=body.get('data',{}).get('pagination',{}) if isinstance(body,dict) and isinstance(body.get('data'),dict) else {}
            if not pagination and isinstance(body,dict):pagination=body.get('pagination',{})
            reported=pagination.get('total_count',pagination.get('total'))
            if reported is not None:
                if isinstance(reported,bool) or not isinstance(reported,int) or reported<0:reason='total_shape';break
                if total is not None and total!=reported:reason='total_changed';break
                total=reported
            fingerprint=hashlib.sha256(json.dumps(page,sort_keys=True).encode()).hexdigest()
            if page and fingerprint in seen_pages:reason='repeated_page';break
            seen_pages.add(fingerprint);added=0
            actual_fields=[k for k in ('city','location') if page and all(k in r for r in page)]
            if actual_fields:
                if any(str(r[actual_fields[0]]).rstrip('市')!=obj for r in page):reason='filter_not_applied';break
                filter_state='record_field'
            elif page and not records:
                # One negative control distinguishes ignored query parameters from
                # services that intentionally omit the query object from records.
                probe_query=dict(query);probe_query[parameter]='__query_probe_'+hashlib.sha256(obj.encode()).hexdigest()[:10]
                probe_url=urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(probe_query)))
                probe={'kind':'negative_query_control','method':'GET','parameter_names':sorted(query),'auth_provided':bool(headers)}
                attempts.append(probe)
                try:
                    with opener.open(urllib.request.Request(probe_url,headers=headers),timeout=min(2,remaining())) as response:
                        probe['status']=response.status;probe_raw=response.read(256001)
                    if len(probe_raw)>256000:raise ValueError('probe_response_limit')
                    probe_arrays=arrays(json.loads(probe_raw))
                    if len(probe_arrays)==1:
                        probe_page=probe_arrays[0][1];probe['returned']=len(probe_page)
                        if probe_page==page:reason='filter_not_applied';break
                        filter_state='negative_query_discriminated' if not probe_page else 'accepted_parameter_without_record_echo'
                    else:filter_state='accepted_parameter_without_record_echo'
                except urllib.error.HTTPError as error:
                    probe['status']=error.code
                    filter_state='negative_query_rejected' if error.code in (400,404,422) else 'accepted_parameter_without_record_echo'
                except (OSError,ValueError):
                    probe['error']='probe_unavailable';filter_state='accepted_parameter_without_record_echo'
            elif filter_state=='unconfirmed':filter_state='accepted_parameter_without_record_echo'
            for record in page:
                ident=json.dumps(record.get('id',record),sort_keys=True)
                if ident not in identities:identities.add(ident);records.append(record);added+=1
            row.update(returned=len(page),new=added,cumulative=len(records),total=total)
            if len(records)>10000:reason='record_limit';break
            if total is not None and len(records)>total:reason='total_mismatch';break
            if total is not None and len(records)==total:complete=True;reason='total_matched';break
            if pagination.get('has_more') is False and total is None:complete=True;reason='explicit_end';break
            if not page:reason='unconfirmed_empty_page';break
            if 'offset' not in pagination or 'limit' not in pagination:reason='pagination_unknown';break
            if pagination['offset']!=offset:reason='offset_ignored';break
            offset+=len(page);paging_path='offset_limit'
    except (OSError,ValueError,KeyError,TypeError,TimeoutError) as error:
        reason='retrieval_exception';result['error_type']=type(error).__name__;result['detail']=str(error)[:300]
    encoded=json.dumps(records,ensure_ascii=False)
    delivered=records if len(encoded)<=8500 else records[:3]
    retrieval={'object':obj,'records':delivered,'complete':complete,'records_omitted':len(records)-len(delivered),
               'count':len(records),'total':total,'filter_evidence':filter_state,'reason':reason}
    # Real retrieved data is available for model interpretation even when validation
    # is incomplete. The manager distinguishes supported candidates from verified.
    return finish('data_ready' if complete and not retrieval['records_omitted'] else 'retrieval_incomplete',
        ok=bool(records),retrieval=retrieval,evidence={'requests':attempts,'complete':complete,'reason':reason},
        method={'family':'api','auth_header':auth,'query_parameter':parameter,'records_path':resolved_path,'pagination':paging_path or 'offset_limit'})
