from copy import deepcopy
from dataclasses import replace
import unittest

from loomrise.config_validation import validate_configuration
from loomrise.graph_runtime import GraphRuntime, GraphRuntimeError
from loomrise.service import ExecutionService
from tests.test_graph_runtime import config
from tests.test_graph_service import graph_pack
from tests.test_graph_validation import graph_spec


def decision(choice='complete', *, scores=None, evidence=None):
    return {'decision': choice, 'scores': scores or {'complete': 0.9, 'incomplete': 0.1},
            'evidence': evidence if evidence is not None else {'fields': ['verified']}}


class GraphCompletionTests(unittest.TestCase):
    def value(self):
        value = config()
        value['units'][1]['exit_ports'][0]['completion'] = {'llm': '用户已明确确认'}
        return value

    def test_validated_completion_uses_one_provider_decision_and_keeps_original_state(self):
        value = self.value()
        observed = []
        def evaluator(check, state):
            observed.append(check)
            state['profile']['name'] = 'must not leak'
            return decision()
        state = {'verified': True, 'profile': {'name': 'original'}}
        before = deepcopy(state)
        result = GraphRuntime(value, completion_evaluator=evaluator).route(state)
        self.assertEqual(result.status, 'completed')
        self.assertEqual(state, before)
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]['unit_ref'], {'unit_id': 'child', 'version': 1})
        self.assertEqual(observed[0]['criterion'], '用户已明确确认')
        self.assertTrue(result.completion_checks[0]['satisfied'])

    def test_missing_provider_invalid_evidence_and_small_margin_cannot_complete(self):
        with self.assertRaisesRegex(GraphRuntimeError, 'completion'):
            GraphRuntime(self.value()).route({'verified': True})
        for response in (decision('invented'), decision(evidence={}), decision(evidence={'fields': ['absent']}),
                         decision(scores={'complete': 0.51, 'incomplete': 0.49}),
                         decision('incomplete', scores={'complete': 0.1, 'incomplete': 0.9}), True):
            with self.subTest(response=response):
                result = GraphRuntime(self.value(), completion_evaluator=lambda check, state: response).route({'verified': True})
                self.assertEqual(result.status, 'fallback')
                self.assertFalse(result.completion_checks[0]['satisfied'])

    def test_deterministic_completion_is_required_before_calling_the_provider(self):
        value = self.value()
        value['units'][1]['exit_ports'][0]['completion']['deterministic'] = {'fact': {'field': 'verified', 'op': 'eq', 'value': True}}
        calls = []
        result = GraphRuntime(value, completion_evaluator=lambda *args: calls.append(args)).route({'verified': False})
        self.assertEqual(result.status, 'fallback')
        self.assertEqual(calls, [])

    def test_text_criterion_is_freezable_but_unresolved_shapes_remain_draft_only(self):
        value = graph_spec()
        value['units'][1]['exit_ports'][0]['completion'] = {'llm': '用户已明确确认'}
        self.assertEqual(validate_configuration(value, submitting=True), [])
        for unsupported in ('', None, {}, {'prompt_ref': 'latest'}):
            value['units'][1]['exit_ports'][0]['completion']['llm'] = unsupported
            self.assertTrue(validate_configuration(value, submitting=True))

    def test_wait_checkpoint_reuses_only_a_verified_decision_for_unchanged_inputs(self):
        value = config()
        value['units'][0]['exit_ports'][0]['completion'] = {'llm': '用户已确认'}
        value['units'][0]['waits'] = [{'on': 'approval.received'}]
        calls = []
        def evaluator(check, state):
            calls.append(check)
            return decision()
        runtime = GraphRuntime(value, completion_evaluator=evaluator)
        parked = runtime.route({'verified': True})
        self.assertEqual(parked.status, 'waiting')
        again = runtime.route({'verified': True}, continuation=parked.continuation)
        self.assertEqual(again.status, 'waiting')
        self.assertEqual(len(calls), 1)
        corrupt = deepcopy(parked.continuation)
        key = next(iter(corrupt['completion_decisions']))
        corrupt['completion_decisions'][key] = True
        with self.assertRaisesRegex(GraphRuntimeError, 'checkpoint'):
            runtime.route({'verified': True}, continuation=corrupt)


class CompletionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_completion_is_audited_inside_the_same_run_without_writes(self):
        pack = graph_pack()
        value = deepcopy(pack.agent_version.orchestration)
        value['units'][0]['exit_ports'][0]['completion'] = {'llm': '允许继续答疑'}
        pack.agent_version = replace(pack.agent_version, orchestration=value)
        service = ExecutionService(pack, completion_evaluator=lambda check, state: decision())
        result = await service.handle_text('确认', routing_state={'verified': True}, script=[{'text': '继续答疑'}])
        self.assertEqual(result.request.state.value, 'success')
        self.assertEqual(result.write_count, 0)
        checks = service.ledger.find('route.graph.completion')
        self.assertEqual(len(checks), 1)
        self.assertTrue(checks[0].payload['satisfied'])
        self.assertEqual(checks[0].run_id, result.run_id)
        self.assertTrue(service.ledger.verify())
