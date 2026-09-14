from __future__ import annotations

import json
import unittest

from solution.engine import AgentEngine
from solution.models import Turn
from solution.resources import MiningCalendar
from solution.state import WorldState
from tests.scenarios import arena


class MiningCalendarTests(unittest.TestCase):
    def test_negated_reopening_keeps_mine_closed(self):
        for news in ('合成通知：铁矿今天不能恢复开采。',
                     'Synthetic notice: iron mining will not reopen today.'):
            calendar = MiningCalendar()
            calendar.close('iron', 1, None)
            calendar.observe(131, news)
            calendar.apply_structured([{'resource': 'iron', 'status': 'open',
                'startsRound': 131, 'confidence': 1, 'evidence': news}], [(131, news)])
            self.assertFalse(calendar.available('iron', 131))

    def test_official_only_llm_reply_applies_before_economy_with_shared_quota(self):
        raw = arena(10, armed=True)
        news = 'Synthetic report: iron mining is suspended; repairs end on the second game day.'
        raw['worldNews'] = {'officialNews': news}
        engine = AgentEngine()
        engine.decide(raw)
        self.assertEqual(engine.llm_budget.calls_used, 1)
        nonce = engine.planner.tasks.pending_id
        self.assertTrue(nonce)
        raw['roundNo'] = 11
        raw['llmResp'] = json.dumps({'requestId': nonce, 'confidence': 1,
            'miningRestrictions': [{'resource': 'iron', 'status': 'closed',
                'startsRound': 1, 'endsRound': 260, 'confidence': 1, 'evidence': news}]})
        engine.decide(raw)
        self.assertFalse(engine.state.mining.available('iron', 260))
        self.assertTrue(engine.state.mining.available('iron', 261))
        self.assertEqual(engine.llm_budget.calls_used, 1)
        for round_no in (12, 13, 14):
            raw['roundNo'], raw['llmResp'] = round_no, ''
            raw['worldNews'] = {'officialNews': f'Synthetic update {round_no}: copper prices are unchanged.'}
            engine.decide(raw)
        self.assertEqual(engine.llm_budget.calls_used, 3)

    def test_relative_dates_are_anchored_to_publication_not_repeated_receipt(self):
        calendar = MiningCalendar()
        news = 'Synthetic report: iron mining will be suspended tomorrow for two days.'
        calendar.observe(1, news)
        calendar.observe(131, news)
        self.assertTrue(calendar.available('iron', 130))
        self.assertFalse(calendar.available('iron', 131))
        self.assertFalse(calendar.available('iron', 390))
        self.assertTrue(calendar.available('iron', 391))
        self.assertTrue(calendar.available('copper', 131))

    def test_chinese_closure_duration_and_reopening(self):
        calendar = MiningCalendar()
        calendar.observe(1, '合成通知：铁矿今天照常作业，明日起停工，修整预计需要两天。')
        self.assertTrue(calendar.available('iron', 130))
        self.assertFalse(calendar.available('iron', 131))
        self.assertFalse(calendar.available('iron', 390))
        self.assertTrue(calendar.available('iron', 391))
        calendar.observe(261, '合成通知：铁矿今天恢复开采。')
        self.assertTrue(calendar.available('iron', 261))

    def test_unknown_end_waits_for_explicit_reopening(self):
        calendar = MiningCalendar()
        calendar.observe(131, '合成通知：铜矿暂停开采，复工日期另行通知。')
        self.assertFalse(calendar.available('copper', 200))
        self.assertFalse(calendar.available('copper', 400))
        calendar.observe(391, '合成通知：铜矿明天恢复开采。')
        self.assertFalse(calendar.available('copper', 520))
        self.assertTrue(calendar.available('copper', 521))

    def test_reopening_report_may_mention_previous_closure(self):
        calendar = MiningCalendar()
        calendar.observe(1, '合成通知：铁矿暂停开采。')
        calendar.observe(261, '合成通知：铁矿此前停工，今天恢复开采。')
        self.assertTrue(calendar.available('iron', 261))

    def test_today_and_tomorrow_window(self):
        calendar = MiningCalendar()
        calendar.observe(131, 'Synthetic notice: iron mining is suspended today and tomorrow.')
        self.assertFalse(calendar.available('iron', 131))
        self.assertFalse(calendar.available('iron', 390))
        self.assertTrue(calendar.available('iron', 391))

    def test_price_change_and_negated_closure_do_not_close_mine(self):
        for news in ('Synthetic notice: iron prices increase tomorrow.', '合成通知：铁矿不会停工，今天涨价。'):
            calendar = MiningCalendar()
            calendar.observe(1, news)
            self.assertTrue(calendar.available('iron', 131))

    def test_different_ores_do_not_share_a_closure(self):
        calendar = MiningCalendar()
        calendar.observe(1, '合成通知：铁矿今天停采两天，铜矿正常开采。')
        self.assertFalse(calendar.available('iron', 131))
        self.assertTrue(calendar.available('copper', 131))

    def test_explicit_game_day(self):
        calendar = MiningCalendar()
        calendar.observe(1, '合成通知：铁矿第3天停工，持续两天。')
        self.assertTrue(calendar.available('iron', 260))
        self.assertFalse(calendar.available('iron', 261))
        self.assertFalse(calendar.available('iron', 520))
        self.assertTrue(calendar.available('iron', 521))

    def test_structured_news_requires_evidence_and_can_refine_unknown_end(self):
        calendar = MiningCalendar()
        news = 'Synthetic notice: iron mining is suspended; repairs end on the second game day.'
        calendar.observe(1, news)
        event = {'resource': 'iron', 'startsRound': 1, 'endsRound': 260,
                 'status': 'closed', 'confidence': .95, 'evidence': news}
        calendar.apply_structured([event], [(1, news)])
        self.assertFalse(calendar.available('iron', 260))
        self.assertTrue(calendar.available('iron', 261))
        for bad in ({**event, 'resource': []}, {**event, 'startsRound': True},
                    {**event, 'evidence': 'fabricated source'}, {**event, 'confidence': .1}):
            other = MiningCalendar()
            other.apply_structured([bad], [(1, news)])
            self.assertTrue(other.available('iron', 1))

    def test_match_restart_clears_closure_state(self):
        state = WorldState()
        raw = arena(131)
        raw['worldNews'] = {'officialNews': 'Synthetic notice: iron mining is suspended.'}
        state.ingest(Turn.from_raw(raw))
        self.assertFalse(state.mining.available('iron', 131))
        state.ingest(Turn.from_raw(arena(1)))
        self.assertTrue(state.mining.available('iron', 1))
