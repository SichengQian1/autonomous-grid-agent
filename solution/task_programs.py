"""Bounded, declarative task procedures transported into the task sandbox.

No task-specific paths, answers, credentials or API schemas are stored here.
"""
from __future__ import annotations

import base64
import json
import zlib
import inspect
from .task_answers import shape_error, shape_details
from .task_api import run_api
from .task_contracts import package_proof, extract_proof, current_contract, _TYPES, _MARKER
from .task_workflows import run_workflow


# Kept self-contained because the task sandbox is separate from the HTTP process.
SANDBOX_PROGRAM = ('import re, json, hashlib\n_TYPES='+repr(_TYPES)+'\n_MARKER=re.compile('+repr(_MARKER.pattern)+',re.I)\n' +
                  '\n'.join(inspect.getsource(f) for f in (shape_error,shape_details,run_api,package_proof,extract_proof,current_contract,run_workflow))) + r'''
import json, os, subprocess, time, urllib.request, urllib.parse, hashlib, shutil, shlex
from pathlib import Path
started = time.monotonic()
base = Path(options.get("base", "/tmp/selfEvolutionTask")).resolve()
def inside(name):
    p = (base / name).resolve()
    if not p.is_relative_to(base): raise ValueError("path_outside_task")
    return p
execution_evidence={}
path_evidence=[]
patch_evidence=[]
def resolve_file(name, cwd="."):
    candidates=list(dict.fromkeys((inside(str(Path(cwd)/name)),inside(name))))
    for p in candidates:
        path_evidence.append({"requested":name,"base":cwd,"path":str(p.relative_to(base)),"exists":p.exists(),"is_file":p.is_file()})
        if p.is_file():return p
    matches=[inside(f) for f in inventory() if Path(f).name==Path(name).name]
    if len(matches)==1:
        path_evidence.append({"located":str(matches[0].relative_to(base)),"method":"unique_basename"})
        return matches[0]
    raise FileNotFoundError(name)
def remaining():
    left = 9 - (time.monotonic() - started)
    if left <= 0: raise TimeoutError("procedure_deadline")
    return left
def field(value, path):
    for key in path.split(".") if path else []:
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value
def inventory():
    files = []
    for directory, dirs, names in os.walk(base):
        remaining()
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(directory)/d).is_symlink())
        if len(Path(directory).relative_to(base).parts) >= 5: dirs[:] = []
        for name in sorted(names):
            p = Path(directory)/name
            if p.is_file() and not p.is_symlink(): files.append(str(p.relative_to(base)))
            if len(files) >= 100: return files
    return files
def execute(argv, cwd, extra_env=None):
    import threading, signal
    env = dict(os.environ)
    if extra_env: env.update(extra_env)
    execution_evidence.update(cwd=str(cwd.relative_to(base)),stream='combined_stdout_stderr',program=argv[0],cwd_exists=cwd.is_dir(),stage='launch',argument_count=len(argv))
    argv=list(argv)
    if '/' in argv[0] and Path(argv[0]).is_file():
        entry=Path(argv[0])
        with entry.open('rb') as stream:first=stream.read(256).split(b'\n',1)[0]
        execution_evidence.update(entry_exists=True,entry_executable=os.access(entry,os.X_OK),
                                  shebang=first.startswith(b'#!'),shebang_crlf=first.endswith(b'\r'))
        if first.startswith(b'#!'):
            try:parts=shlex.split(first[2:].decode(errors='replace').strip())
            except ValueError:parts=[]
            if parts and Path(parts[0]).name=='env':parts=parts[1:]
            if parts and len(parts)<=3 and not any(x.startswith('-') for x in parts):
                name=Path(parts[0]).name
                family='python3' if name.startswith('python3') else name if name in ('bash','sh') else ''
                interpreter=shutil.which(family) if family else None
                execution_evidence.update(interpreter=parts[0],interpreter_available=bool(interpreter))
                if interpreter and (first.endswith(b'\r') or not Path(parts[0]).is_file() or not os.access(entry,os.X_OK)):
                    argv=[interpreter,*parts[1:],str(entry),*argv[1:]]
                    execution_evidence['invocation']='explicit_interpreter'
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True)
    def stop():
        try: os.killpg(proc.pid,signal.SIGKILL) if os.name=='posix' else proc.kill()
        except ProcessLookupError: pass
    chunks=[]
    def read_output():
        chunks.append(proc.stdout.read(12001))
        if len(chunks[0])>12000: stop()
    reader=threading.Thread(target=read_output,daemon=True); reader.start()
    try: code=proc.wait(timeout=min(8,remaining()))
    except (subprocess.TimeoutExpired, TimeoutError):
        stop(); proc.wait(); raise TimeoutError('check_timeout')
    reader.join(timeout=0.2)
    if reader.is_alive(): stop(); reader.join(timeout=0.2)
    text=(chunks[0] if chunks else b'').decode(errors='replace')
    execution_evidence.update(stage='completed',exit_code=code,output_length=len(text))
    return code,text
def run():
    import re
    kind = options["kind"]
    if kind == 'bootstrap':
        options['kind']='inspect'
        try: info=run()
        finally: options['kind']='bootstrap'
        return run_workflow(options,info,base,inventory,execute,remaining)
    if kind == "inspect":
        files = []
        for directory, dirs, names in os.walk(base):
            remaining()
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(directory)/d).is_symlink())
            if len(Path(directory).relative_to(base).parts) >= 5: dirs[:] = []
            for name in sorted(names):
                p = Path(directory) / name
                if not p.is_symlink() and p.is_file(): files.append(p)
                if len(files) >= 500: break
            if len(files) >= 500: break
        files.sort(key=lambda p:(-p.stat().st_mtime,str(p)))
        requested = options.get("filename", "")
        docs = [p for p in files if p.name == requested] if requested else []
        if docs:
            parent = docs[0].parent
            docs = docs[:1]
            nearby = [p for p in files if p.is_relative_to(parent)]
        else:
            if requested: return {"ok":False,"status":"task_document_missing","files":inventory(),"workspace":".","root":str(base)}
            parent=inside(options.get("cwd","."))
            nearby = [p for p in files if p.is_relative_to(parent)]
        explicit = []
        for name in options.get('paths',[])[:4]:
            p=resolve_file(name,str(parent.relative_to(base)))
            if p.is_file() and p not in explicit: explicit.append(p)
        docs = explicit + [p for p in docs if p not in explicit]
        docs += [p for p in nearby if p.name.lower() in ("readme.md", "spec.md", "api_docs.md", "task.md") and p not in docs]
        docs += [p for p in nearby if p.suffix==".py" and p.stat().st_size<6000 and p not in docs][:3]
        if not docs: docs = [p for p in files if p.suffix.lower() in (".md", ".txt", ".json")][:5]
        budget, output = 11000, []
        for p in docs[:6]:
            name = str(p.relative_to(base))
            offset = max(0, min(100000, int(options.get('offsets',{}).get(name,0))))
            with p.open(errors="replace") as handle:
                handle.read(offset)
                chunk = handle.read(min(6000,budget)+1)
            text = chunk[:min(6000,budget)]
            output.append({"path":name,"text":text,"offset":offset,
                           "next_offset":offset+len(text),"original_bytes":p.stat().st_size,"complete":len(chunk)==len(text)})
            budget -= len(text)
            if budget <= 0: break
        return {"documents":output,"files":inventory(),
                "workspace":str(parent.relative_to(base)),"document_directory":str(parent.relative_to(base)),"root":str(base)}
    if kind in ("repair", "script", "python"):
        edits = options.get("edits", []) if kind == "repair" else []
        if not isinstance(edits,list) or len(edits)>8: raise ValueError("edit_limit")
        prepared = {}
        receipts={};receipt_path=None;receipt_edits=[]
        if options.get('task_id'):
            directory=inside('.agent_task_cache')
            if not (base/'.agent_task_cache').is_symlink():
                directory.mkdir(exist_ok=True)
                ident=hashlib.sha256((str(options.get('cache_namespace',''))+options['task_id']).encode()).hexdigest()
                receipt_path=directory/('repair-'+ident+'.json')
                if receipt_path.is_symlink():receipt_path=None
                elif receipt_path.is_file() and receipt_path.stat().st_size<32000:
                    try:receipts=json.loads(receipt_path.read_text())
                    except (ValueError,OSError):pass
                if not isinstance(receipts,dict):receipts={}
        checker_files=set()
        checker_cwd=inside(options.get('cwd','.'))
        check_argv=list(options.get('check',[])) if kind=='repair' else []
        if check_argv:
            script_index=0 if '/' in check_argv[0] else 1 if len(check_argv)>1 and not check_argv[1].startswith('-') and Path(check_argv[1]).suffix in ('.py','.sh','.jar') else None
            if script_index is not None:
                requested=check_argv[script_index]
                existed=(checker_cwd/requested).is_file()
                checker=resolve_file(requested,str(checker_cwd.relative_to(base)))
                checker_files.add(checker)
                check_argv[script_index]=str(checker)
                if not existed:checker_cwd=checker.parent
        for edit in edits:
            p = resolve_file(edit["path"],str(checker_cwd.relative_to(base)))
            if p in checker_files:raise ValueError("checker_edit_forbidden")
            for argument in options.get("check",[]):
                if isinstance(argument,str) and argument and not argument.startswith("-"):
                    candidate=inside(str(Path(options.get("cwd","."))/argument))
                    if candidate==p:raise ValueError("checker_edit_forbidden")
            if p.stat().st_size > 100000: raise ValueError("file_limit")
            old, new = edit["old"], edit["new"]
            text = prepared.get(p, p.read_text())
            relative=str(p.relative_to(base))
            stamp=hashlib.sha256(json.dumps([relative,old,new]).encode()).hexdigest()
            digest=hashlib.sha256(text.encode()).hexdigest()
            item={'path':relative,'matches':text.count(old),'old_length':len(old),'new_length':len(new),
                  'changed':False,'applied':False,'before_length':len(text)}
            patch_evidence.append(item)
            if receipts.get(stamp)==digest:
                item.update(already_applied=True,applied=True,after_length=len(text));continue
            if not old or text.count(old)!=1 or len(new)>20000: raise ValueError("non_unique_patch")
            prepared[p] = text.replace(old,new,1)
            item.update(after_length=len(prepared[p]),changed=text!=prepared[p])
            receipt_edits.append((stamp,p,item))
        for p,text in prepared.items():
            p.write_text(text)
            for stamp,changed,item in receipt_edits:
                if changed==p:
                    item['applied']=True
                    receipts[stamp]=hashlib.sha256(text.encode()).hexdigest()
            if receipt_path:receipt_path.write_text(json.dumps(dict(list(receipts.items())[-32:])))
        if kind == "repair": argv=check_argv
        elif kind == "python":
            compile(options["code"],"<solver>","exec")
            argv=["python3","-c",options["code"]]
        else: argv=["bash","-c",options["script"]]
        if not isinstance(argv,list) or not argv or not all(isinstance(a,str) for a in argv): raise ValueError("check_shape")
        if any("\x00" in a for a in argv): raise ValueError("check_program")
        if "/" in argv[0]:
            executable=inside(str(Path(options.get("cwd","."))/argv[0]))
            if not executable.is_file():raise FileNotFoundError(argv[0])
        cwd = checker_cwd if kind=='repair' else inside(options.get('cwd','.'))
        code,text = execute(argv,cwd)
        if len(text)>12000: return {"ok":False,"status":"check_truncated","output":text[:12000]}
        if kind=='repair' and re.search(r'\[FAIL\]|\bFAILED\b',text):
            return {'ok':False,'status':'checker_reported_failure','exitCode':code,'output':text}
        if code:
            result={"ok":False,"status":"check_failed","exitCode":code,"output":text[:8000]}
            if 'FileNotFoundError' in text or 'No such file' in text:
                result.update(files=inventory(),workspace=str(cwd.relative_to(base)),root=str(base))
            return result
        if kind != "repair" and options.get("submit_result") is not True:
            return {"ok":True,"status":"script_ok","output":text}
        try:
            if options.get('answer_format') == 'text' and kind == 'repair':
                import re
                pattern=options.get('answer_pattern','')
                if not isinstance(pattern,str) or not 0<len(pattern)<=300: raise ValueError('answer_pattern')
                matches=re.findall(pattern,text)
                if len(matches)!=1 or not isinstance(matches[0],str): raise ValueError('ambiguous_answer')
                result=matches[0]
            else:
                result=json.loads(text.strip().splitlines()[-1],parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
            if kind=='repair' and isinstance(result,dict) and any(result.get(k) is False for k in ('success','passed','ok')):
                return {'ok':False,'status':'checker_reported_failure','output':text}
            answer=field(result,options.get('answer_path',''))
        except (ValueError,IndexError,KeyError,TypeError):
            return {"ok":False,"status":"check_not_structured","output":text}
        required=options.get('required')
        if kind=='repair':answer=package_proof(answer,required)
        problem=shape_error(answer,required) if required is not None else ''
        if problem: return {'ok':False,'status':'answer_schema','reason':problem,'answer':answer,'computed':True,'schema_pass':False,'output':text}
        verified=False
        if kind != 'repair' and options.get('verify'):
            verifier=options['verify']
            if not isinstance(verifier,str) or len(verifier)>6000: raise ValueError('verify_shape')
            import ast
            tree=ast.parse(verifier)
            checks=[node for node in ast.walk(tree) if isinstance(node,ast.Assert)
                    and any(isinstance(n,ast.Name) and n.id=='answer' for n in ast.walk(node.test))]
            if not checks:
                return {'ok':False,'status':'verification_missing_assert','answer':answer,'computed':True,'schema_pass':bool(required) and not problem}
            class CountChecks(ast.NodeTransformer):
                def visit_Assert(self,node):
                    if node in checks:
                        return [ast.parse('_task_checks[0] += 1').body[0],node]
                    return node
            tree=ast.fix_missing_locations(CountChecks().visit(tree))
            prelude='import json,os\nanswer=json.loads(os.environ["TASK_CANDIDATE_JSON"])\n_task_checks=[0]\n'
            source=prelude+ast.unparse(tree)+'\nprint(json.dumps({"executed_checks":_task_checks[0]}))\n'
            status,output=execute(['python3','-c',source],cwd,
                                  {'TASK_CANDIDATE_JSON':json.dumps(answer,allow_nan=False)})
            if status or len(output)>12000:
                return {'ok':False,'status':'verification_failed','verification_kind':'assertion' if 'AssertionError' in output else 'verifier_exception','exitCode':status,'output':output[:6000], 'answer':answer,'computed':True,'schema_pass':bool(required) and not problem}
            try: check_count=json.loads(output.strip().splitlines()[-1])['executed_checks']
            except (ValueError,IndexError,KeyError,TypeError): check_count=0
            if not isinstance(check_count,int) or check_count<1:
                return {'ok':False,'status':'verification_missing_assert','answer':answer,'computed':True,'schema_pass':bool(required) and not problem}
            verified=not shape_error(answer,required)
        return {'ok':True,'checked':kind=='repair' or verified,'computed':kind!='repair',
                'answer':answer,'schema_pass':bool(required) and not problem}
    if kind == "api":
        return run_api(options, remaining)
    raise ValueError("unknown_procedure")
try:
    result=run()
except Exception as error:
    result={"ok":False,"status":type(error).__name__}
    if isinstance(error,OSError):
        execution_evidence['errno']=error.errno
        if error.filename:execution_evidence['failed_path']=str(error.filename)
    if isinstance(error,FileNotFoundError):
        try: result.update(files=inventory(),workspace=str(options.get('cwd','.')),root=str(base))
        except TimeoutError: pass
    if str(error) in {"path_outside_task","file_limit","non_unique_patch","check_shape","check_program","check_timeout","procedure_deadline","loopback_only","edit_limit","unknown_aggregate","checker_edit_forbidden","era_pattern_limit"}:
        result["reason"]=str(error)
if result.get('documents') and result.get('ok') is not False and 'status' not in result:result['status']='documents_read'
if result.get('status')=='answer_schema':result['schema_details']=shape_details(result.get('answer'),options.get('required'))
result['execution_evidence']=execution_evidence
result['path_evidence']=path_evidence[:12]
result['patch_evidence']=patch_evidence[:8]
result['elapsed_ms']=int((time.monotonic()-started)*1000)
result['cwd']=execution_evidence.get('cwd',str(options.get('cwd','.')))
result['kind']=options.get('kind')
if options.get('task_id'):result['task_id']=options['task_id']
def render(): return json.dumps({'procedure_result':result},ensure_ascii=False)
# Keep the envelope parseable; mark omitted document tails for a targeted read.
while len(render())>15000:
    if len(result.get('evidence',{}).get('requests',[]))>4:
        result['evidence']['requests'].pop(1);result['evidence']['omitted_requests']=result['evidence'].get('omitted_requests',0)+1
    elif result.get('files'):
        result['files'].pop(); result['files_truncated']=True
    elif result.get('documents') and any(len(d['text'])>256 for d in result['documents']):
        doc=max(result['documents'],key=lambda d:len(d['text']))
        doc['text']=doc['text'][:len(doc['text'])//2]
        doc['complete']=False; doc['next_offset']=doc.get('offset',0)+len(doc['text'])
    elif len(result.get('output',''))>256:
        result['output']=result['output'][:len(result['output'])//2]; result['output_truncated']=True
    else:
        result={'ok':False,'status':'check_truncated'}; break
print(render())
'''


_PAYLOADS = {}


def procedure_command(plan: dict[str, object]) -> str:
    if not isinstance(plan.get("kind"), str) or plan.get("kind") not in {"bootstrap", "inspect", "repair", "api", "script", "python"} or "base" in plan:
        return ""
    try:
        raw = json.dumps(plan, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return ""
    if len(raw) > 12000:
        return ""
    family='bootstrap' if plan['kind']=='bootstrap' else 'procedure'
    if family not in _PAYLOADS:
        unused=(run_api,) if family=='bootstrap' else (run_workflow,current_contract)
        program=SANDBOX_PROGRAM
        for function in unused:program=program.replace(inspect.getsource(function),'')
        _PAYLOADS[family]=base64.b64encode(zlib.compress(program.encode(),9)).decode()
    payload = _PAYLOADS[family]
    options = base64.b64encode(raw.encode()).decode()
    code = f"import base64,zlib,json;options=json.loads(base64.b64decode('{options}'));exec(zlib.decompress(base64.b64decode('{payload}')))"
    import shlex
    return "python3 -c " + shlex.quote(code)
