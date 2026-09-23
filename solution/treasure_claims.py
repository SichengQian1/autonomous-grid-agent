"""Structural checks for cited hypotheses; lexical overlap is not semantic proof."""
import re
from .geometry import Pos


def normalized(text):
    return re.sub(r'[^\w\u4e00-\u9fff]+','',str(text).casefold())


def contains(text,fragment):
    return bool(normalized(fragment)) and normalized(fragment) in normalized(text)


def cited(values,sources,allowed):
    return (isinstance(values,list) and 0<len(values)<=16 and
            all(isinstance(e,dict) and isinstance(e.get('source'),str) and e['source'] in allowed
                and isinstance(e.get('quote'),str) and 3<=len(e['quote'])<=6000
                and e['quote'] in sources.get(e['source'],{}).get('text','') for e in values))


def number(text):
    if text.isdigit():return int(text)
    words={'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10,
           '一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
    if text in words:return words[text]
    if '十' in text:
        a,b=text.split('十',1);return words.get(a,1)*10+words.get(b,0)
    return None


def numbers(text):
    return {number(v) for v in re.findall(r'\d+|\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\b|[一二两三四五六七八九十]+',text.casefold())}


def quantity_supported(quantity,quotes,anchors):
    for quote in quotes:
        # Splitting coordinated objects prevents "2 lamps and 1 seal" from
        # validating a claim of two seals merely because both numbers occur.
        for clause in re.split(r'[.;。；\n,，、]|\band\b|以及|和|及',quote,flags=re.I):
            if quantity not in numbers(clause):continue
            if any(contains(clause,a) for a in anchors if a):return True
            atom=r'(\d+|one|two|three|four|five|six|seven|eight|nine|ten|[一二两三四五六七八九十]+)'
            shared=re.findall(r'(?:\beach\b.{0,45}?(?:needs?|requires?|uses?|takes?)\s*|各(?:需|要|取|用)?\s*|每(?:种|样|件)(?:需|要|用)?\s*)'+atom,clause,re.I)
            if quantity in {number(v.casefold()) for v in shared}:return True
    return False


def material_claim(m,catalog,sources,allowed):
    if not isinstance(m,dict):return None,'material_shape'
    name=m.get('item');qty=m.get('quantity');effect=m.get('effect')
    if not isinstance(name,str) or name not in catalog:return None,'out_of_catalog'
    if not cited(m.get('evidence'),sources,allowed):return None,'invalid_source_quote'
    if not cited(m.get('quantity_evidence'),sources,allowed):return None,'invalid_quantity_source_quote'
    if type(qty) is not int or not 1<=qty<=40:return None,'quantity_shape'
    if not isinstance(effect,str) or not effect.strip():return None,'effect_missing'
    quotes=[e['quote'] for e in m['evidence']]
    object_quote=m.get('object_quote',m.get('object',effect))
    effect_quote=m.get('effect_quote',effect)
    if not isinstance(object_quote,str) or not any(contains(q,object_quote) for q in quotes):return None,'object_unsupported'
    if not isinstance(effect_quote,str) or not any(contains(q,effect_quote) for q in quotes):return None,'effect_unsupported'
    # A paraphrase/translation must bind this exact claim to its cited phrase.
    # Changing `effect` cannot leave a prior relation silently verified.
    lexical=contains(effect_quote,effect)
    relation=m.get('effect_relation')
    related=(isinstance(relation,dict) and relation.get('claim')==effect
             and relation.get('quote')==effect_quote and isinstance(relation.get('reason'),str) and bool(relation['reason'].strip()))
    if not lexical and not related:return None,'effect_relation_missing'
    if not quantity_supported(qty,[e['quote'] for e in m['quantity_evidence']],(object_quote,effect_quote,name)):
        return None,'quantity_unsupported'
    description=catalog[name]['description'];shop_quote=m.get('shop_quote','')
    named=any(name in q for q in quotes)
    if named:
        binding='directly_named';warning=''
    elif not description:
        if not isinstance(m.get('derivation'),str) or not m['derivation'].strip():return None,'catalog_missing_description_needs_inference'
        binding='inferred';warning='catalog_missing_description'
    else:
        if not isinstance(shop_quote,str) or len(shop_quote)<3 or shop_quote not in description:return None,'catalog_description_mismatch'
        if not contains(shop_quote,effect) or not lexical:
            if not related or not m.get('derivation'):return None,'catalog_effect_mismatch'
            binding='inferred';warning='semantic_mapping_unverified'
        else:binding='description_matched';warning=''
    return {'quantity':qty,'binding':binding,'warning':warning,
            'semantic_status':'model_inference' if binding=='inferred' else 'lexical_alignment_not_semantic_proof',
            'object_quote':object_quote,'effect':effect,'effect_quote':effect_quote,
            'sources':sorted({e['source'] for e in m['evidence']+m['quantity_evidence']})},''


COORDINATE=re.compile(r'[（(]\s*(-?\d+)\s*[,，]\s*(-?\d+)\s*[)）]')
APPROXIMATE=re.compile(r'\b(?:near|around|approximately|vicinity)\b|附近|大约|一带|周围',re.I)


def location_claim(value,sources,allowed,bounds):
    if not isinstance(value,dict):return None,'location_shape'
    x,y=value.get('x'),value.get('y')
    if type(x) is not int or type(y) is not int:return None,'location_shape'
    if not (0<=x<bounds[0] and 0<=y<bounds[1]):return None,'location_out_of_bounds'
    if not cited(value.get('evidence'),sources,allowed):return None,'invalid_location_source_quote'
    derivation=value.get('derivation')
    if not isinstance(derivation,dict) or not derivation.get('kind'):return None,'location_derivation_missing'
    quotes=[e['quote'] for e in value['evidence']]
    for e in value['evidence']:
        source=sources[e['source']]['text'];start=source.find(e['quote'])
        if value.get('precision')=='approximate':return None,'approximate_location'
        for match in COORDINATE.finditer(e['quote']):
            begin=start+match.start();end=start+match.end()
            before=re.split(r'[.;。；\n]',source[max(0,begin-60):begin])[-1]
            if APPROXIMATE.search(before) or re.match(r'\s*(?:附近|周围|一带)',source[end:end+8]):return None,'approximate_location'
    pairs={(int(x),int(y)) for q in quotes for x,y in COORDINATE.findall(q)}
    if derivation['kind']=='coordinate_literal':
        if (x,y) not in pairs:return None,'location_coordinate_mismatch'
        # Several coordinates require a narrower citation, not arbitrary choice.
        if len(pairs)>1:return None,'location_ambiguous_coordinates'
        return Pos(x,y),''
    if derivation['kind']=='offset':
        anchor=derivation.get('anchor');delta=derivation.get('delta');offset_quote=derivation.get('offset_quote')
        if (not isinstance(anchor,list) or len(anchor)!=2 or not all(type(n) is int for n in anchor)
            or tuple(anchor) not in pairs or not isinstance(delta,list) or len(delta)!=2 or not all(type(n) is int for n in delta)):
            return None,'location_offset_shape'
        if not isinstance(offset_quote,str) or not any(offset_quote in q for q in quotes):return None,'location_offset_evidence'
        # Require explicit axis arithmetic, not an assumed screen compass.
        offsets=re.findall(r'([xy])\s*([+-])\s*(\d+)',offset_quote,re.I)
        computed={'x':0,'y':0}
        if not offsets:return None,'location_offset_evidence'
        for axis,sign,n in offsets:computed[axis.lower()]+=int(n)*(1 if sign=='+' else -1)
        if delta!=[computed['x'],computed['y']] or [x,y]!=[anchor[i]+delta[i] for i in range(2)]:return None,'location_offset_mismatch'
        return Pos(x,y),''
    return None,'location_derivation_unsupported'


def window_claim(value,sources,allowed,valid_days):
    if not isinstance(value,dict):return None,'window_shape'
    start,end,phase=value.get('day'),value.get('end_day'),value.get('phase')
    if type(start) is not int or type(end) is not int or not 1<=start<=end<=10 or phase not in ('any','day','night'):return None,'window_shape'
    if not cited(value.get('evidence'),sources,allowed):return None,'invalid_window_source_quote'
    dates=set();phases=set()
    for e in value['evidence']:
        day=sources[e['source']]['day'];quote=e['quote']
        if day not in valid_days:return None,'window_source_day_invalid'
        explicit=re.findall(r'(?:\bdays?\s*|第)([0-9一二三四五六七八九十]+)(?:\s*[-–至到]\s*([0-9一二三四五六七八九十]+))?',quote,re.I)
        for a,b in explicit:
            first,last=number(a),number(b) if b else number(a)
            if first is not None and last is not None:dates.update(range(first,last+1))
        if re.search(r'tomorrow|明天|明日|次日',quote,re.I):dates.add(day+1)
        if re.search(r'day after tomorrow|后天',quote,re.I):dates.discard(day+1);dates.add(day+2)
        if re.search(r'\btoday\b|\btonight\b|今天|今日|当天|今夜|当晚',quote,re.I):dates.add(day)
        if re.search(r'\bnight\b|\btonight\b|黑夜|夜晚|夜间|晚上|今夜|当晚|当夜',quote,re.I):phases.add('night')
        if re.search(r'\bdaytime\b|\bdaylight\b|\bmorning\b|\bafternoon\b|白天|白昼|上午|下午',quote,re.I):phases.add('day')
    if set(range(start,end+1))!=dates:return None,'window_date_mismatch'
    if len(phases)>1 or (phases and phase not in phases):return None,'window_phase_mismatch'
    if not phases and phase!='any':return None,'window_phase_unsupported'
    return (start,end,phase),''
