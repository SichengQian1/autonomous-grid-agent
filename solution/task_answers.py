"""Small answer contracts, not a substitute for task-specific correctness checks."""
import hashlib
import json


def shape_error(answer, required):
    """Validate a bounded top-level field/type contract supplied from task evidence."""
    types = {'string': str, 'integer': int, 'number': (int, float),
             'boolean': bool, 'array': list, 'object': dict, 'null': type(None)}
    aliases={'str':'string','int':'integer','float':'number','bool':'boolean','list':'array','dict':'object','none':'null','nonetype':'null'}
    def valid(value,kind):
        if isinstance(kind,dict):kind=kind.get('type')
        if isinstance(kind,list):
            return any(valid(value,k) is True for k in kind)
        if not isinstance(kind,str):return None
        kind=kind.strip().lower()
        if kind.startswith(('list[','array[')) and kind.endswith(']'):
            inner=kind[kind.index('[')+1:-1]
            return isinstance(value,list) and all(valid(v,inner) is True for v in value)
        kind=aliases.get(kind,kind)
        if kind not in types:return None
        return isinstance(value,types[kind]) and not (kind in ('integer','number') and isinstance(value,bool))
    if isinstance(required,str):
        result=valid(answer,required)
        return 'contract_type' if result is None else '' if result else 'answer_type'
    if not isinstance(required,dict) or not required or len(required)>64:return 'contract_missing'
    if not isinstance(answer,dict):return 'answer_not_object'
    for key,kind in required.items():
        if key not in answer:return 'missing_field'
        result=valid(answer[key],kind)
        if result is None:return 'contract_type'
        if not result:return 'field_type'
    return ''


def answer_fingerprint(answer):
    try:
        if isinstance(answer, str):
            try: answer = json.loads(answer)
            except ValueError: pass
        text = json.dumps(answer, sort_keys=True, ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(text.encode()).hexdigest()
    except (TypeError, ValueError):
        return ''


def shape_details(answer, required):
    """Report the failing field and types without copying field values."""
    problem=shape_error(answer,required)
    if not problem:return {}
    if isinstance(required,dict) and isinstance(answer,dict):
        for key,kind in required.items():
            if key not in answer:return {'reason':'missing_field','field':key,'expected':kind,'actual':'absent'}
            if shape_error({key:answer[key]},{key:kind}):return {'reason':problem,'field':key,'expected':kind,'actual':type(answer[key]).__name__}
    return {'reason':problem,'expected':required if isinstance(required,str) else 'object','actual':type(answer).__name__}
