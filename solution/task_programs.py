"""Bounded, declarative task procedures transported into the task sandbox.

No task-specific paths, answers, credentials or API schemas are stored here.
"""
from __future__ import annotations

import base64
import json
import zlib


# Kept self-contained because the task sandbox is separate from the HTTP process.
SANDBOX_PROGRAM = r'''
import json, os, subprocess, time, urllib.request, urllib.parse
from pathlib import Path
started = time.monotonic()
base = Path(options.get("base", "/tmp/selfEvolutionTask")).resolve()
def inside(name):
    p = (base / name).resolve()
    if not p.is_relative_to(base): raise ValueError("path_outside_task")
    return p
def remaining():
    left = 9 - (time.monotonic() - started)
    if left <= 0: raise TimeoutError("procedure_deadline")
    return left
def field(value, path):
    for key in path.split(".") if path else []:
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value
def run():
    kind = options["kind"]
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
        else: nearby = files
        docs += [p for p in nearby if p.name.lower() in ("readme.md", "spec.md", "api_docs.md", "task.md") and p not in docs]
        docs += [inside(p) for p in options.get("paths",[])[:4] if inside(p).is_file() and inside(p) not in docs]
        docs += [p for p in nearby if p.suffix==".py" and p.stat().st_size<6000 and p not in docs][:3]
        if not docs: docs = [p for p in files if p.suffix.lower() in (".md", ".txt", ".json")][:5]
        budget, output = 11000, []
        for p in docs[:6]:
            with p.open(errors="replace") as handle: text = handle.read(min(4000,budget))
            output.append({"path":str(p.relative_to(base)),"text":text})
            budget -= len(text)
            if budget <= 0: break
        return {"documents":output,"files":[str(p.relative_to(base)) for p in nearby[:60]]}
    if kind in ("repair", "script"):
        edits = options.get("edits", []) if kind == "repair" else []
        if not isinstance(edits,list) or len(edits)>8: raise ValueError("edit_limit")
        prepared = {}
        for edit in edits:
            p = inside(edit["path"])
            if p.stat().st_size > 100000: raise ValueError("file_limit")
            old, new = edit["old"], edit["new"]
            text = prepared.get(p, p.read_text())
            if not old or text.count(old)!=1 or len(new)>20000: raise ValueError("non_unique_patch")
            prepared[p] = text.replace(old,new,1)
        for p,text in prepared.items(): p.write_text(text)
        argv = options["check"] if kind == "repair" else ["bash", "-c", options["script"]]
        if not isinstance(argv,list) or not argv or not all(isinstance(a,str) for a in argv): raise ValueError("check_shape")
        if argv[0] not in ("python3","python","bash","sh","make","java"): raise ValueError("check_program")
        # Drain at most the output allowance; kill the process group on excess.
        import threading, signal
        proc = subprocess.Popen(argv,cwd=inside(options.get("cwd",".")),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
        def stop():
            try: os.killpg(proc.pid,signal.SIGKILL) if os.name=="posix" else proc.kill()
            except ProcessLookupError: pass
        chunks=[]
        def read_output():
            chunks.append(proc.stdout.read(12001))
            if len(chunks[0])>12000: stop()
        reader=threading.Thread(target=read_output,daemon=True); reader.start()
        try: code=proc.wait(timeout=min(8,remaining()))
        except subprocess.TimeoutExpired:
            stop(); proc.wait(); raise TimeoutError("check_timeout")
        reader.join(timeout=0.2)
        if reader.is_alive(): stop(); reader.join(timeout=0.2)
        text=(chunks[0] if chunks else b"").decode(errors="replace")
        if len(text)>12000: return {"ok":False,"status":"check_truncated","output":text[:12000]}
        if code: return {"ok":False,"status":"check_failed","exitCode":code,"output":text[:12000]}
        if kind == "script": return {"ok":True,"status":"script_ok","output":text}
        try: result = json.loads(text.strip().splitlines()[-1])
        except (ValueError,IndexError): return {"ok":False,"status":"check_not_structured","output":text}
        return {"ok":True,"checked":True,"answer":field(result,options.get("answer_path",""))}
    if kind == "api":
        url = options["url"]
        parts = urllib.parse.urlsplit(url)
        if parts.scheme!="http" or parts.hostname not in ("localhost","127.0.0.1") or parts.username: raise ValueError("loopback_only")
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs): raise ValueError("redirect_refused")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        pagination = options.get("pagination",{})
        records, seen, pages = [], set(), set()
        complete = False
        start, size = int(pagination.get("start",1)), int(pagination.get("size",100))
        if not 1<=size<=1000: raise ValueError("page_size")
        total_path = pagination.get("total_path")
        for index in range(30):
            query = dict(urllib.parse.parse_qsl(parts.query)); query.update(options.get("query",{}))
            if pagination:
                query[pagination.get("parameter","page")] = start + index * int(pagination.get("step",1))
                if pagination.get("size_parameter"): query[pagination["size_parameter"]] = size
            request = urllib.request.Request(urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query))),headers=options.get("headers",{}))
            with opener.open(request,timeout=min(2,remaining())) as response: raw=response.read(256001)
            if len(raw)>256000: raise ValueError("response_limit")
            data=json.loads(raw); page=field(data,options.get("records_path",""))
            if not isinstance(page,list): raise ValueError("records_shape")
            fingerprint=json.dumps(page,sort_keys=True)
            if page and fingerprint in pages: return {"ok":False,"status":"repeated_page","count":len(records)}
            pages.add(fingerprint)
            for record in page:
                if pagination.get("id_path"):
                    key=json.dumps(field(record,pagination["id_path"]),sort_keys=True)
                    if key not in seen: records.append(record); seen.add(key)
                else: records.append(record)
            if len(records)>10000: raise ValueError("record_limit")
            if total_path:
                if len(records)>=int(field(data,total_path)): complete=True; break
            elif not pagination or not page or len(page)<size:
                complete=True; break
            if index and not page: break
        if not complete: return {"ok":False,"status":"incomplete_pages","count":len(records)}
        answer={}
        for name,spec in options.get("fields",{}).items():
            op=spec["op"]
            if op=="constant": answer[name]=spec["value"]
            elif op=="count": answer[name]=len(records)
            elif op=="count_equal": answer[name]=sum(field(r,spec["path"])==spec["value"] for r in records)
            elif op=="unique":
                values=[field(r,spec["path"]) for r in records]
                if spec.get("flatten"): values=[v for group in values for v in group]
                answer[name]=list(dict.fromkeys(values))
            elif op=="sum": answer[name]=sum(field(r,spec["path"]) for r in records)
            elif op in ("min_by","max_by"):
                selected=(min if op=="min_by" else max)(records,key=lambda r:field(r,spec["path"]))
                answer[name]=field(selected,spec["value_path"])
            else: raise ValueError("unknown_aggregate")
        return {"ok":True,"checked":True,"answer":answer,"count":len(records)}
    raise ValueError("unknown_procedure")
try:
    result=run()
except Exception as error:
    result={"ok":False,"status":type(error).__name__}
print(json.dumps({"procedure_result":result},ensure_ascii=False))
'''


def procedure_command(plan: dict[str, object]) -> str:
    if not isinstance(plan.get("kind"), str) or plan.get("kind") not in {"inspect", "repair", "api", "script"} or "base" in plan:
        return ""
    try:
        raw = json.dumps(plan, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return ""
    if len(raw) > 12000:
        return ""
    payload = base64.b64encode(zlib.compress(SANDBOX_PROGRAM.encode())).decode()
    options = base64.b64encode(raw.encode()).decode()
    code = f"import base64,zlib,json;options=json.loads(base64.b64decode('{options}'));exec(zlib.decompress(base64.b64decode('{payload}')))"
    import shlex
    return "python3 -c " + shlex.quote(code)
