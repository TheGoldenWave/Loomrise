from copy import deepcopy
from dataclasses import replace
import asyncio
import unittest

from loomrise.service import ExecutionService
from tests.test_graph_service import graph_pack


def recall_pack():
    pack = graph_pack()
    graph = deepcopy(pack.agent_version.orchestration)
    helper = deepcopy(graph['units'][0])
    helper.update(unit_id='refund-helper', load_mode='concurrent')
    graph['units'].append(helper)
    graph['concurrent_config'] = {'max_units': 1}
    pack.agent_version = replace(pack.agent_version, orchestration=graph,
        unit_skill_bindings={'booking-entry': 'course_consult_booking', 'refund-helper': 'refund_request'})
    return pack


class ConcurrentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_recalled_write_skill_cannot_expand_the_primary_step_tool_scope(self):
        pack = recall_pack()
        pack.agent_version.unit_skill_bindings = {'booking-entry': 'refund_request', 'refund-helper': 'course_consult_booking'}
        service = ExecutionService(pack, concurrent_selector=lambda candidates, context: ['refund-helper'])
        result = await service.handle_text('帮我预约', ask_confirm=lambda calls: [True] * len(calls), script=[
            {'tool': 'create_booking', 'args': {'course_id': 'data-analysis-101', 'learner_name': '虚构学员', 'slot': '周二', 'idempotency_key': 'scope-test'}},
            {'text': '已处理'},
        ])
        self.assertEqual(result.write_count, 0)
        self.assertFalse(service.ledger.find('tool.outcome', tool='create_booking'))

    async def test_ranked_selection_respects_group_limit_and_context_budget(self):
        pack = recall_pack()
        original_skill = pack.skill('refund_request')
        pack.skills.append(replace(original_skill, skill_id='other-helper'))
        pack.agent_version.skill_ids.append('other-helper')
        pack.fragments.extend([replace(fragment, fragment_id=fragment.fragment_id + '-other', applies_to='other-helper')
            for fragment in pack.fragments if fragment.applies_to == 'refund_request'])
        helper = deepcopy(pack.agent_version.orchestration['units'][1])
        helper['unit_id'] = 'other'
        pack.agent_version.orchestration['units'].append(helper)
        pack.agent_version.unit_skill_bindings['other'] = 'other-helper'
        selector = lambda candidates, context: ['other', 'refund-helper', 'other']
        service = ExecutionService(pack, concurrent_selector=selector)
        result = await service.handle_text('退费', script=[{'text': '答复'}])
        selected = service.ledger.find('recall.diagnostic', code='selected')[-1].payload
        self.assertEqual(selected['selected_unit_ids'], ['other'])
        self.assertTrue([item for item in result.context_audit['loaded'] if item['stage'] == 'concurrent'])

        pack.agent_version.context_budget_tokens = 1
        limited = ExecutionService(pack, concurrent_selector=selector)
        result = await limited.handle_text('退费', script=[{'text': '资料受限'}])
        self.assertFalse([item for item in result.context_audit['loaded'] if item['stage'] == 'concurrent'])
        self.assertTrue(result.context_audit['budget_capped'])

    async def test_async_selector_can_be_cancelled_before_any_business_action(self):
        started = asyncio.Event()
        async def selector(candidates, context):
            started.set()
            await asyncio.Future()
        service = ExecutionService(recall_pack(), concurrent_selector=selector)
        task = asyncio.create_task(service.handle_text('退费', script=[]))
        await asyncio.wait_for(started.wait(), timeout=1)
        start_event = service.ledger.find('run.started')[-1]
        self.assertTrue(service.cancel(start_event.request_id, run_id=start_event.run_id))
        result = await task
        self.assertEqual(result.request.state.value, 'cancelled')
        self.assertEqual(result.write_count, 0)
        self.assertEqual(service._active, {})
        self.assertFalse(service.ledger.find('tool.outcome'))

    async def test_selected_helper_loads_in_same_run_without_changing_primary_route(self):
        observed = []
        def recall(candidates, context):
            observed.extend(candidates)
            return ['refund-helper']
        service = ExecutionService(recall_pack(), concurrent_selector=recall)
        result = await service.handle_text('退费怎么算', script=[{'text': '请参考退费政策。'}])
        self.assertEqual(service.ledger.find('request.routed')[-1].payload['skill_id'], 'course_consult_booking')
        self.assertEqual([item['unit_id'] for item in observed], ['refund-helper'])
        self.assertNotIn('body', observed[0])
        loaded = [item for item in result.context_audit['loaded'] if item['stage'] == 'concurrent']
        self.assertTrue(loaded)
        self.assertEqual(result.write_count, 0)
        self.assertEqual(len(service.requests), 1)
        self.assertTrue(service.ledger.verify())

    async def test_scope_filters_candidates_before_selector_and_does_not_load_excluded_content(self):
        pack = recall_pack()
        pack.agent_version.orchestration['units'][1]['load_scope'] = {'exclude': ['booking-entry']}
        def recall(candidates, context):
            self.assertEqual(candidates, [])
            return ['refund-helper']
        service = ExecutionService(pack, concurrent_selector=recall)
        result = await service.handle_text('退费', script=[{'text': '由人工确认。'}])
        self.assertFalse([item for item in result.context_audit['loaded'] if item['stage'] == 'concurrent'])
        self.assertEqual(result.write_count, 0)

    async def test_default_provider_is_keyword_scoped_and_injected_selector_cannot_invent_units(self):
        for text, selector, expected in (('完全不相关', None, False), ('退费怎么计算', None, True),
            ('退费', lambda candidates, context: ['invented'], False), ('退费', lambda candidates, context: {'units': ['refund-helper']}, False)):
            service = ExecutionService(recall_pack(), concurrent_selector=selector)
            result = await service.handle_text(text, script=[{'text': '由人工确认。'}])
            loaded = [item for item in result.context_audit['loaded'] if item['stage'] == 'concurrent']
            self.assertEqual(bool(loaded), expected)
            self.assertEqual(result.write_count, 0)

    async def test_expired_helper_content_never_enters_model_context(self):
        pack = recall_pack()
        pack.fragments = [replace(fragment, valid_until='2000-01-01T00:00:00Z')
            if fragment.applies_to == 'refund_request' else fragment for fragment in pack.fragments]
        service = ExecutionService(pack, concurrent_selector=lambda candidates, context: ['refund-helper'])
        result = await service.handle_text('退费', script=[{'text': '资料不可用。'}])
        self.assertFalse([item for item in result.context_audit['loaded'] if item['stage'] == 'concurrent'])
        self.assertTrue(service.ledger.find('recall.diagnostic', code='unavailable_skill_context'))


if __name__ == '__main__':
    unittest.main()
