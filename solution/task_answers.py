"""Small answer contracts, not a substitute for task-specific correctness checks."""
import hashlib
import json


def shape_error(answer, required):
    """Validate a bounded top-level field/type contract supplied from task evidence."""
    types = {'string': str, 'integer': int, 'number': (int, float),
             'boolean': bool, 'array': list, 'object': dict, 'null': type(None)}
    if isinstance(required,str):
        if required not in types: return 'contract_type'
        valid=isinstance(answer,types[required]) and not (required in ('integer','number') and isinstance(answer,bool))
        return '' if valid else 'answer_type'
    if not isinstance(required, dict) or not required or len(required) > 64:
        return 'contract_missing'
    if not isinstance(answer, dict):
        return 'answer_not_object'
    for key, kind in required.items():
        if not isinstance(kind, str) or kind not in types:
            return 'contract_type'
        if key not in answer:
            return 'missing_field'
        value = answer[key]
        if not isinstance(value, types[kind]) or (kind in ('integer', 'number') and isinstance(value, bool)):
            return 'field_type'
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
