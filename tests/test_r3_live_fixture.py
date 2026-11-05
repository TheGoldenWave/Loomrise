"""Offline checks for the opt-in fictional multi-candidate live fixture."""
import unittest

from loomrise.service import ExecutionService
from tests import r3_model_provider_live_check as live_check


class LiveExecutionFixtureTests(unittest.IsolatedAsyncioTestCase):
    async def test_multi_candidate_fixture_reaches_both_closed_sets_without_business_tools(self):
        self.assertTrue(callable(getattr(live_check, 'execution_fixture', None)),
                        'live check needs a reusable bounded multi-candidate fixture')
        pack = live_check.execution_fixture('scripted-s1', multi_candidate=True)
        self.assertEqual((pack.tools, pack.rules, pack.agent_version.tool_ids), ([], [], []))
        self.assertTrue(all(not skill.tool_ids for skill in pack.skills))
        observed = {'route': [], 'completion': 0, 'recall': []}

        class Provider:
            model = 'scripted-s1'

            def route(self, candidates, state):
                observed['route'].append([candidate['id'] for candidate in candidates])
                return {'edge_id': 'choose-refund',
                        'scores': {candidate['id']: 0.98 if candidate['id'] == 'choose-refund' else 0.02
                                   for candidate in candidates},
                        'evidence': {'fields': [], 'utterance': state['recent_turns'][0]}}

            def completion(self, check, state):
                observed['completion'] += 1
                return {'decision': 'complete', 'scores': {'complete': 0.98, 'incomplete': 0.02},
                        'evidence': {'fields': [], 'utterance': state['recent_turns'][0]}}

            async def recall(self, candidates, context):
                observed['recall'].append([candidate['unit_id'] for candidate in candidates])
                return ['refund-helper']

        service = ExecutionService(pack, model_provider=Provider())
        result = await service.handle_text('我同意继续资料答疑，请说明开课前退费规定。',
                                           script=[{'text': '虚构测试答复。'}])
        self.assertEqual(result.request.state.value, 'success')
        self.assertEqual(observed, {'route': [['choose-refund', 'choose-schedule']],
                                    'completion': 1,
                                    'recall': [['refund-helper', 'schedule-helper']]})
        self.assertEqual(service.ledger.find('request.routed')[-1].payload['unit_id'], 'refund-answer')
        self.assertEqual(service.ledger.find('recall.diagnostic', code='selected')[-1].payload['candidate_count'], 2)
        self.assertEqual([item['fragment_id'] for item in result.context_audit['loaded']
                          if item['stage'] == 'concurrent'], ['ctx.sop.refund'])
        self.assertEqual(result.write_count, 0)
        self.assertIsNone(result.request.result_id)
        self.assertFalse(any(event.event_type.startswith('tool.') for event in service.ledger.events))
        self.assertTrue(service.ledger.verify())


if __name__ == '__main__':
    unittest.main()
