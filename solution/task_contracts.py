"""Extract answer shapes from current requirements, never example answer values."""
import hashlib
import json
import re
from .task_answers import shape_error

_TYPES={'str':'string','string':'string','字符串':'string','int':'integer','integer':'integer','整数':'integer',
        'number':'number','float':'number','数字':'number','boolean':'boolean','bool':'boolean','布尔':'boolean',
        'array':'array','list':'array','数组':'array','列表':'array','object':'object','dict':'object','对象':'object'}
_MARKER=re.compile(r'answer|submit|output|答案|提交|输出|返回格式',re.I)

def current_contract(documents):
    candidates=[]
    for name,text in list(documents.items())[:12]:
        text=text[:18000]
        # Only JSON explicitly introduced as an answer/output, not request examples.
        consumed=0;json_spans=[]
        for match in list(re.finditer(r'\{',text))[:80]:
            if match.start()<consumed:continue
            prefix=text[max(0,match.start()-100):match.start()]
            if not _MARKER.search(prefix):continue
            if re.search(r'(?:request|请求|输入)\s*(?:JSON|格式|示例)?\s*[:：]?\s*$',prefix,re.I):continue
            try:value,length=json.JSONDecoder().raw_decode(text[match.start():])
            except ValueError:continue
            consumed=match.start()+length
            json_spans.append((match.start(),consumed))
            if not isinstance(value,dict) or not value or len(value)>32:continue
            contract={}
            if value.get('type')=='object' and isinstance(value.get('properties'),dict):
                wanted=value.get('required',list(value['properties']))
                if not isinstance(wanted,list):continue
                contract={k:spec.get('type') for k in wanted if isinstance(k,str) and isinstance(spec:=value['properties'].get(k),dict)}
                if len(contract)!=len(wanted):continue
            else:
                for key,v in value.items():
                    if isinstance(v,str):kind=_TYPES.get(v.strip().lower(),'string')
                    elif isinstance(v,bool):kind='boolean'
                    elif isinstance(v,int):kind='integer'
                    elif isinstance(v,float):kind='number'
                    elif isinstance(v,list):kind='array'
                    elif isinstance(v,dict):kind='object'
                    else:kind='null'
                    contract[key]=kind
            def valid_type(v):
                allowed=set(_TYPES.values())|{'null'}
                return (isinstance(v,str) and v in allowed) or (isinstance(v,list) and 0<len(v)<=8 and all(isinstance(t,str) and t in allowed for t in v))
            if contract and all(isinstance(k,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',k) and valid_type(v) for k,v in contract.items()):
                candidates.append((contract,name,'answer_json',match.start()))
        # Explicit field/type rows are also accepted, only in an answer section.
        markers=list(_MARKER.finditer(text))
        for marker in markers[:12]:
            section=text[marker.end():marker.end()+1600]
            rows={};offset=marker.end()
            for line in section.splitlines(keepends=True)[:18]:
                position=offset;offset+=len(line)
                if any(a<=position<b for a,b in json_spans) or len(line)>200:continue
                match=re.match(r"""\s*[-*|`'"\s]*([A-Za-z_][A-Za-z0-9_]{0,63})[`'"\s]*[:：|]\s*[`'"\s]*([A-Za-z]+|字符串|整数|数字|布尔|数组|列表|对象)\b""",line)
                if match and match[2].lower() in _TYPES:rows[match[1]]=_TYPES[match[2].lower()]
            if rows:candidates.append((rows,name,'field_types',marker.start()))
    if not candidates:return {},{}
    # Conflicting examples require model clarification, never silently choose one.
    merged={}
    for contract,_,_,_ in candidates:
        for key,value in contract.items():
            if key in merged and merged[key]!=value:return {},{'status':'conflicting_document_contracts'}
            merged[key]=value
    largest=max(candidates,key=lambda item:len(item[0]))
    if any(not set(c[0])<=set(largest[0]) for c in candidates):return {},{'status':'ambiguous_document_contracts'}
    contract,name,method,offset=largest
    return contract,{'status':'document_contract','document':name,'method':method,'offset':offset,
                    'fingerprint':hashlib.sha256(json.dumps(contract,sort_keys=True).encode()).hexdigest()[:16]}

def package_proof(answer, required):
    if isinstance(required,dict) and len(required)==1 and isinstance(answer,(str,int,float)):
        key=next(iter(required));wrapped={key:answer}
        if not shape_error(wrapped,required):return wrapped
    return answer

def extract_proof(output, required):
    """Read explicit JSON or a labeled proof from the current successful command."""
    if not isinstance(required,dict) or len(required)!=1:return None
    key=next(iter(required))
    if required[key]!='string':return None
    matches=[]
    for line in output.splitlines()[-24:]:
        try:
            value=json.loads(line)
            if isinstance(value,dict) and any(value.get(k) is False for k in ('success','passed','ok')):return None
            if isinstance(value,dict) and key in value and not shape_error({key:value[key]},required):matches.append({key:value[key]})
        except ValueError:pass
        # Do not treat arbitrary stdout or an unlabeled last line as a credential.
        match=re.fullmatch(r'\s*'+re.escape(key)+r'\s*[:=]\s*([A-Za-z0-9_./+=-]{4,256})\s*',line,re.I)
        if match:matches.append({key:match[1]})
    unique={json.dumps(v,sort_keys=True):v for v in matches}
    return next(iter(unique.values())) if len(unique)==1 else None
