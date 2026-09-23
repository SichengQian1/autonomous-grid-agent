"""LLM-owned folklore interpretation with bounded, structurally valid execution."""
from collections import Counter
from dataclasses import dataclass, field
import hashlib
import json

from .actions import Action, ActionType
from .geometry import Pos
from .grid import interaction_cells, shortest_path
from .movement import MoveIntent
from .route_safety import safe_grid, escape_intent
from .travel import TravelBudget
from .rules import DEFAULT_CONFIG, DAY_ROUNDS, NIGHT_ROUNDS, ROUNDS_PER_DAY


DAY_TEXT_LIMIT = 6000
MATCH_DAYS = 10
ATTEMPT_LIMIT = 2
# Neutral summaries of public item properties, not a map's offering recipe.
# Used only when an exact current catalog name lacks a runtime description.
TASK_ITEM_HINTS = {
    'AcientTablet': '石质刻文物件；古老符号；接触有振动声。',
    'StarSand': '冷的银色颗粒材料；弱光环境可发亮。',
    'FlameBreath': '瓶装暖色气态材料；活动后释放光与热。',
    'FrostPotion': '蓝色浓稠药液；容器有霜；强烈降温感。',
    'ThornAmulet': '植物编制的带刺环形饰品；有植物气息。',
    'IronWhistle': '锈蚀金属吹奏物；内有可碰响的金属部件。',
}
MARKET_SCHEMA = ('market:[{ore:"iron|copper|stone",start_day:integer,end_day:integer,'
                 'price:number|null,closed:boolean,rising:boolean,recovery:boolean,'
                 'evidence:"exact official quote",confidence:number}]')


def fingerprint(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


@dataclass(slots=True)
class TreasureKnowledge:
    position: Pos | None = None
    opening_day: int | None = None
    end_day: int = MATCH_DAYS
    phase: str = 'any'
    materials: dict = field(default_factory=dict)
    mode: str = 'unknown'
    exhausted: bool = False
    reason: str = 'no_rumor'
    folk_legends: dict = field(default_factory=dict)
    folklore_limits: dict = field(default_factory=dict)
    seen: dict = field(default_factory=dict)
    memory_bytes: int = 0
    omitted: int = 0
    catalog: dict = field(default_factory=dict)
    catalog_hash: str = ''
    map_bounds: tuple = (0, 0)
    current_day: int = 1
    current_round: int = 0
    version: int = 0
    analyzed_version: int = -1
    request_version: int = -1
    request_id: int = 0
    request_purpose: str = 'treasure'
    request_signature: str = ''
    responses: int = 0
    retry_version: int = -1
    retry_count: int = 0
    retry_pending: bool = False
    candidate_version: int = 0
    pending_attempt: tuple | None = None
    pending_round: int = 0
    attempted: set = field(default_factory=set)
    rejected: set = field(default_factory=set)
    rejected_material_sets: set = field(default_factory=set)
    rejected_sites: set = field(default_factory=set)
    attempt_count: int = 0
    material_spent: int = 0
    platform_feedback: list = field(default_factory=list)
    validation_failures: list = field(default_factory=list)
    last_validation_failure: dict = field(default_factory=dict)
    events: list = field(default_factory=list)

    @property
    def items(self):
        return tuple(name for name, count in sorted(self.materials.items()) for _ in range(count))

    @property
    def complete(self):
        return bool(self.materials) and self.position is not None and self.opening_day is not None

    def result(self):
        return {'materials': [{'item': name, 'quantity': count} for name, count in self.materials.items()],
                'location': self.position.to_raw() if self.position else None,
                'window': {'day': self.opening_day, 'end_day': self.end_day, 'phase': self.phase}
                          if self.opening_day is not None else None}

    def emit(self, stage, **data):
        if len(self.events) < 40:
            self.events.append({'stage': stage, **data})

    def fail(self, reason, **detail):
        self.reason = reason
        self.last_validation_failure = {'reason': reason, 'request_id': self.request_id,
                                        'round': self.current_round, **detail}
        self.emit('validation', **self.last_validation_failure)

    def observe(self, turn, config=DEFAULT_CONFIG):
        self.current_round = turn.round_no
        self.current_day = turn.day_index
        self.map_bounds = (turn.map_info.width, turn.map_info.height)
        self.catalog = {i.name: {'description': i.description.strip(), 'price': i.price} for i in turn.weapon_shop}
        digest = fingerprint(json.dumps({n: i['description'] for n, i in self.catalog.items()}, sort_keys=True))
        if digest != self.catalog_hash:
            self.catalog_hash = digest
            self.version += 1
            removed = sorted(set(self.materials) - self.catalog.keys())
            if removed:
                self.materials.clear()
                self.fail('catalog_item_removed', items=removed)
            self.emit('catalog', items=len(self.catalog), described=sum(bool(i['description']) for i in self.catalog.values()))
        day = self.current_day
        if not 1 <= day <= MATCH_DAYS:
            return
        self.folk_legends.setdefault(day, '')
        limits = self.folklore_limits.setdefault(day, {'input_chars': 0, 'kept_chars': 0, 'omitted_chars': 0, 'truncated': False})
        text = turn.world_news.folk_legends
        if not text:
            return
        digest = fingerprint(text)
        # A broadcast persisting into another day keeps its original source day.
        if digest in self.seen:
            return
        if len(self.seen) >= 2048:
            self.emit('memory_limit', reason='source_count_limit', day=day)
            return
        self.seen[digest] = day
        previous = self.folk_legends[day]
        separator = '\n' if previous else ''
        addition = separator + text
        kept = addition[:max(0, DAY_TEXT_LIMIT - len(previous))]
        self.folk_legends[day] = previous + kept
        lost = len(addition) - len(kept)
        self.omitted += lost
        limits['input_chars'] += len(text)
        limits['kept_chars'] = len(self.folk_legends[day])
        limits['omitted_chars'] += lost
        limits['truncated'] = bool(limits['omitted_chars'])
        self.memory_bytes = sum(len(v.encode('utf-8')) for v in self.folk_legends.values())
        if kept or (lost and limits['omitted_chars'] == lost):
            self.version += 1
        self.emit('source', day=day, fingerprint=digest, **limits, memory_bytes=self.memory_bytes,
                  excerpt=kept, omitted_chars_total=self.omitted)
        self.reason = 'new_information_pending'

    def needs_analysis(self):
        return (not self.exhausted and self.attempt_count < ATTEMPT_LIMIT
                and any(self.folk_legends.values())
                and (self.version != self.analyzed_version or self.retry_pending))

    def prompt(self, official='', source_day=1, *, purpose='treasure'):
        self.request_id += 1
        self.request_version = self.version
        self.request_purpose = purpose
        if purpose == 'treasure':
            self.retry_pending = False
        payload = {'request_id': self.request_id, 'purpose': purpose, 'current_day': self.current_day,
                   'official': official[:6000], 'official_day': source_day, 'official_original_length': len(official)}
        instruction = ('官方新闻与民间传闻分开处理，新闻只影响市场预测。返回严格 JSON，回显 request_id。'
                       '市场返回 ' + MARKET_SCHEMA + '。恢复消息覆盖自身窗口的旧限制，不猜固定价格日期。\n')
        if purpose == 'market_only':
            instruction += '本次只解读官方新闻，返回 request_id 与 market，不输出或修改宝藏结论。\n'
        else:
            catalog = []
            for name, item in list(self.catalog.items())[:128]:
                description = item['description'] or TASK_ITEM_HINTS.get(name, '')
                catalog.append({'name': name, 'price': item['price'], 'description': description[:1000],
                                'description_source': 'runtime' if item['description'] else 'public_rule_hint' if description else 'unavailable',
                                'description_omitted_chars': max(0, len(description) - 1000)})
            payload.update(folk_legends=self.folk_legends.copy(), folklore_limits={d: v.copy() for d, v in self.folklore_limits.items()},
                           shop_catalog=catalog, catalog_omitted_count=max(0, len(self.catalog) - len(catalog)),
                           map={'width': self.map_bounds[0], 'height': self.map_bounds[1]}, previous_result=self.result(),
                           platform_feedback=list(self.platform_feedback), validation_failures=self.validation_failures,
                           attempts_remaining=max(0, ATTEMPT_LIMIT - self.attempt_count))
            instruction += f'''你负责从按来源天累积的中文传闻推断全部宝藏语义：物品及各自数量、祭坛坐标、开放日期与昼夜。自行结合故事上下文理解物体形态和效果，与当前货架描述或公开属性摘要匹配；不要要求中文故事出现英文货架名。祭品应为任务用品，不使用升级券、修补品或战斗道具。物品名必须精确选自 shop_catalog，不复用历史地图答案。
自行判断更正、矛盾、模糊方位和信息是否充分。没有描述的物品也可根据名称和上下文推断；不要把没有程序可验证的引文当作放弃原因。不确定的字段留 null，不为凑齐结果而猜。每个已知物品的数量由语义决定，不默认全为一件。
坐标原点在左下，x 向东/右增加，y 向北/上增加；尺寸使用输入 map。把自然语言方位自行换算成具体坐标。一天白天 {DAY_ROUNDS} 回合、夜晚 {NIGHT_ROUNDS} 回合，全局 {MATCH_DAYS} 天。相对日期一律按那条传闻的来源日换算，不按本次请求日；仅来自今天的“明天”才等于 current_day+1。区分未来开放与当前可开启。
宝藏输出为顶层字段：{{request_id:整数,mode:"treasure|unknown|none",materials:[{{item:"当前货架名",quantity:1至40整数}}]|null,location:{{x:整数,y:整数}}|null,window:{{day:1至10整数,end_day:1至10整数,phase:"any|day|night"}}|null}}。需要时可同时给出 market。
省略/null 保留 previous_result 中已有值；materials 非空列表完整替换此前材料集合，应包含仍有效的旧材料；materials:[] 明确清空。确定无宝藏才用 mode:none 并附 reason；unknown 不删除旧结论，已知材料仍可先采购，但要等你判断为 treasure 才出发开启。不要输出引文证明、推导校验或置信度字段。已知材料可以先采购，不必等位置与时间。mode 为 treasure 且材料、地点、窗口结构齐全时程序将安排出发，务必自行判断完整性。
平台失败记录不可忽略：result_code=2 表示位置或时机有误，3 表示材料组合有误；避免再次建议对应失败条件。只有两次开启机会，按反馈修订；失败后物品可能已被消耗。\n'''
        result = instruction + json.dumps(payload, ensure_ascii=False)
        self.request_signature = fingerprint(result)
        self.emit('model_request', request_id=self.request_id, purpose=purpose, version=self.request_version,
                  input_length=len(result), fingerprint=self.request_signature, input=payload.copy())
        return result

    def retry_analysis(self):
        if self.retry_version != self.request_version:
            self.retry_version = self.request_version
            self.retry_count = 0
        if self.retry_count < 1:
            self.retry_count += 1
            self.retry_pending = True

    def ingest_llm(self, raw):
        from .tasking import parse_structured_llm
        self.responses += 1
        self.emit('model_response', request_id=self.request_id, response_number=self.responses,
                  snapshot_version=self.request_version, current_version=self.version, output=raw)
        parsed = parse_structured_llm(raw)
        self.analyzed_version = max(self.analyzed_version, self.request_version) if self.request_purpose == 'treasure' else self.analyzed_version
        if not isinstance(parsed, dict):
            self.fail('invalid_json_schema'); self.retry_analysis(); return False
        if self.request_id <= 0 or type(parsed.get('request_id')) is not int or parsed['request_id'] != self.request_id:
            self.fail('request_id_mismatch'); self.retry_analysis(); return False
        if self.request_purpose == 'market_only':
            self.emit('market_only_response', request_id=self.request_id)
            return True
        mode = parsed.get('mode', 'unknown')
        self.mode = mode if isinstance(mode, str) and mode in ('treasure', 'unknown', 'none') else 'unknown'
        failures = []
        if self.mode == 'none':
            self.materials.clear(); self.position = None; self.opening_day = None
        else:
            material = parsed.get('materials')
            if material is not None:
                if not isinstance(material, list):
                    failures.append({'field': 'materials', 'reason': 'material_shape'})
                else:
                    accepted = {}
                    for index, entry in enumerate(material):
                        error = ''
                        name = entry.get('item') if isinstance(entry, dict) else None
                        count = entry.get('quantity') if isinstance(entry, dict) else None
                        if not isinstance(entry, dict): error = 'material_shape'
                        elif not isinstance(name, str) or name not in self.catalog: error = 'out_of_catalog'
                        elif type(count) is not int or not 1 <= count <= 40: error = 'quantity_shape'
                        elif name in accepted: error = 'duplicate_material'
                        if error:
                            failures.append({'field': 'materials', 'index': index, 'reason': error})
                        else:
                            accepted[name] = count
                    self.materials = accepted
            location = parsed.get('location')
            if location is not None:
                x = location.get('x') if isinstance(location, dict) else None
                y = location.get('y') if isinstance(location, dict) else None
                if type(x) is int and type(y) is int and 0 <= x < self.map_bounds[0] and 0 <= y < self.map_bounds[1]:
                    self.position = Pos(x, y)
                else:
                    self.position = None
                    failures.append({'field': 'location', 'reason': 'location_shape_or_bounds'})
            window = parsed.get('window')
            if window is not None:
                start = window.get('day') if isinstance(window, dict) else None
                end = window.get('end_day') if isinstance(window, dict) else None
                phase = window.get('phase') if isinstance(window, dict) else None
                if (type(start) is int and type(end) is int and 1 <= start <= end <= MATCH_DAYS
                        and isinstance(phase, str) and phase in ('any', 'day', 'night')):
                    self.opening_day, self.end_day, self.phase = start, end, phase
                else:
                    self.opening_day = None
                    failures.append({'field': 'window', 'reason': 'window_shape'})
        self.validation_failures = failures
        self.candidate_version += 1
        self.reason = 'explicit_no_treasure' if self.mode == 'none' else 'candidate_ready' if self.complete else 'partial_information'
        if failures:
            self.fail(failures[0]['reason'], field=failures[0]['field'])
            self.retry_analysis()
        self.emit('candidate', request_id=self.request_id, response_number=self.responses,
                  candidate_version=self.candidate_version, snapshot_version=self.request_version,
                  current_version=self.version, reason=self.reason, failures=failures, complete=self.complete,
                  mode=self.mode, semantics='llm_inferred', material_spent=self.material_spent,
                  attempts=self.attempt_count, model_reason=str(parsed.get('reason', ''))[:500], **self.result())
        return True

    def apply_result(self, result_code):
        if result_code in (1, 4):
            self.exhausted = True
            self.reason = 'opened' if result_code == 1 else 'already_taken'
        attempt = self.pending_attempt
        if attempt is None:
            return
        position, start, end, phase, items = attempt
        feedback = {'result_code': result_code, 'attempt_round': self.pending_round,
                    'location': position.to_raw() if position else None,
                    'window': {'day': start, 'end_day': end, 'phase': phase},
                    'materials': [{'item': n, 'quantity': q} for n, q in Counter(items).items()]}
        self.platform_feedback.append(feedback)
        self.platform_feedback = self.platform_feedback[-ATTEMPT_LIMIT:]
        if result_code in (0, 2, 3):
            self.rejected.add(attempt)
            if result_code == 3: self.rejected_material_sets.add(items)
            if result_code == 2: self.rejected_sites.add(attempt[:4])
            self.version += 1
            reason = {0: 'illegal_or_missing_feedback', 2: 'wrong_location_or_time', 3: 'wrong_materials'}[result_code]
            self.fail(reason, field='platform')
        self.emit('result', reason=self.reason, attempts=self.attempt_count, **feedback)
        self.pending_attempt = None

    def signature(self):
        return (self.position, self.opening_day, self.end_day, self.phase, self.items)

    def available(self, turn):
        return (not self.exhausted and self.attempt_count < ATTEMPT_LIMIT and bool(self.materials)
                and self.mode != 'none' and not self.expired(turn)
                and self.items not in self.rejected_material_sets and self.signature() not in self.rejected
                and self.signature()[:4] not in self.rejected_sites)

    def expired(self, turn):
        return (self.opening_day is not None
                and turn.round_no > (self.end_day - 1) * ROUNDS_PER_DAY + (DAY_ROUNDS if self.phase == 'day' else ROUNDS_PER_DAY))

    def window_valid(self, turn):
        return (self.opening_day is not None and self.opening_day <= turn.day_index <= self.end_day
                and (self.phase == 'any' or self.phase == ('day' if turn.is_day else 'night')))

    def expedition_ready(self, turn, pioneer):
        return bool(self.available(turn) and self.mode == 'treasure' and self.complete and turn.map_info.contains(self.position)
                    and not Counter(self.items) - Counter(pioneer.backpack))

    def departure_due(self, turn, pioneer, config):
        if not self.expedition_ready(turn, pioneer) or not pioneer.pos:
            return False
        grid, _ = safe_grid(turn, config)
        path = shortest_path(grid, pioneer.pos, interaction_cells(grid, self.position))
        if not path:
            return False
        opening = (self.opening_day - 1) * ROUNDS_PER_DAY + (DAY_ROUNDS + 1 if self.phase == 'night' else 1)
        if self.phase == 'day' and not turn.is_day and turn.day_index >= self.opening_day:
            if turn.day_index >= self.end_day:
                return False
            opening = turn.day_index * ROUNDS_PER_DAY + 1
        return opening - turn.round_no <= len(path) - 1 + 2

    def can_attempt(self, turn, pioneer, config):
        return bool(self.expedition_ready(turn, pioneer) and self.window_valid(turn) and pioneer.pos
                    and pioneer.pos.distance_to(self.position) == 1 and self.signature() not in self.attempted)

    def action(self, turn, pioneer, config):
        if not self.can_attempt(turn, pioneer, config):
            return None
        return Action(pioneer.unit_id, ActionType.SUMMON_TREASURE, targets=(self.position,), items=self.items)

    def issued(self, turn, action):
        if action.action_type == ActionType.BUY and action.name in self.materials:
            role = turn.team_our.unit(action.actor_id)
            if role and role.role_type == 'pioneer':
                # Charge accepted orders conservatively even with missing feedback.
                self.material_spent += next((i.price for i in turn.weapon_shop if i.name == action.name), 0) * action.quantity
            return
        if action.action_type != ActionType.SUMMON_TREASURE:
            return
        self.attempt_count += 1
        self.pending_attempt = self.signature()
        self.pending_round = turn.round_no
        self.attempted.add(self.pending_attempt)
        self.emit('opening', candidate=self.candidate_version, items=self.materials.copy(), attempts=self.attempt_count)

    def plan(self,turn,pioneer,config,spending,*,guard_ready=False):
        from .tasking import AdvancedPlan
        def wait(reason):
            self.reason=reason;return AdvancedPlan()
        if turn.phase_task:return wait('active_task')
        if self.exhausted:return wait('exhausted')
        if self.expired(turn):return wait('window_expired')
        if self.attempt_count>=ATTEMPT_LIMIT:return wait('attempt_limit')
        if self.items in self.rejected_material_sets:return wait('rejected_material_set')
        if self.signature()[:4] in self.rejected_sites:return wait('rejected_location_window')
        if not self.available(turn) or not pioneer.pos:return wait('await_information')
        grid,danger=safe_grid(turn,config)
        if pioneer.pos in danger:return AdvancedPlan(move=escape_intent(turn,pioneer,config,danger))
        missing=Counter(self.items)-Counter(pioneer.backpack)
        if missing:
            if not turn.is_day and not guard_ready:return wait('purchase_needs_guard')
            from .economy import due_defense_targets, next_development_target, upgrade_item
            target=next_development_target(turn,config)
            prices={i.name:i.price for i in turn.weapon_shop}
            material_cost=sum(prices.get(name,config.treasure_material_gold_cap+1)*n for name,n in missing.items())
            if self.material_spent+material_cost>config.treasure_material_gold_cap:return wait('material_gold_cap')
            weapons=[w for w in turn.team_our.roles if w.is_weapon and w.alive]
            basic=max(0,config.max_weapon_count-sum(w.level>=2 for w in weapons)-sum(r.backpack.count('WeaponUpgradeVoucher1') for r in turn.controllable))
            reserve=max(config.treasure_gold_reserve,prices.get(upgrade_item(target),0),basic*prices.get('WeaponUpgradeVoucher1',100))
            if due_defense_targets(turn,config):return wait('defense_deadline_funding')
            affordable=[(name,n) for name,n in missing.items() if name in prices and prices[name]*n<=max(0,spending-reserve)]
            if not affordable:return wait('material_funding_gap')
            goals=tuple(p for shop in turn.zone_positions('weaponShop') for p in interaction_cells(grid,shop))
            trip=TravelBudget.for_role(turn,pioneer,config)
            if turn.is_day and not guard_ready and not trip.fits(((goals,1),)):return wait('purchase_return_deadline')
            if pioneer.pos in goals:
                name,n=affordable[0];n=min(n,max(0,pioneer.backpack_capacity-len(pioneer.backpack)))
                if not n:return wait('material_capacity')
                self.reason='purchase_material';self.emit('purchase',item=name,quantity=n,location_known=self.position is not None)
                return AdvancedPlan(action=Action(pioneer.unit_id,ActionType.BUY,name=name,quantity=n))
            if not shortest_path(grid,pioneer.pos,goals):return wait('unsafe_shop_route')
            self.reason='travel_shop';return AdvancedPlan(move=MoveIntent(pioneer.unit_id,goals,95,avoid_cells=danger))
        if self.mode!='treasure':return wait('model_information_incomplete')
        if not self.expedition_ready(turn,pioneer):return wait('await_location_window_or_remaining_materials')
        if not self.departure_due(turn,pioneer,config):return wait('future_window_departure_not_due')
        if not turn.is_day and not guard_ready:return wait('await_guard_handover')
        if not guard_ready and turn.is_day:
            trip=TravelBudget.for_role(turn,pioneer,config)
            goals=interaction_cells(grid,self.position)
            if not trip.fits(((goals,1),)):return wait('expedition_needs_guard')
        action=self.action(turn,pioneer,config)
        if action:self.reason='open';return AdvancedPlan(action=action)
        goals=interaction_cells(grid,self.position)
        if pioneer.pos in goals:
            self.reason='at_site_wait_window';return AdvancedPlan(move=MoveIntent(pioneer.unit_id,(pioneer.pos,),96,avoid_cells=danger))
        if not shortest_path(grid,pioneer.pos,goals):return wait('unsafe_treasure_route')
        self.reason='travel_site';return AdvancedPlan(move=MoveIntent(pioneer.unit_id,goals,96,avoid_cells=danger))
