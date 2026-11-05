import asyncio
from copy import deepcopy
from dataclasses import replace
import threading
import unittest
from unittest.mock import patch

from loomrise.service import ExecutionService
from tests.test_graph_service import graph_pack
from tests.test_graph_completion import decision


class ProviderWiringTests(unittest.IsolatedAsyncioTestCase):
    def pack(self):
        pack = graph_pack()
        config = deepcopy(pack.agent_version.orchestration)
        config['units'][0]['exit_ports'][0]['completion'] = {'llm': '用户已确认'}
        pack.agent_version = replace(pack.agent_version, orchestration=config)
        return pack

    async def test_scripted_replay_never_auto_loads_local_provider(self):
        with patch('loomrise.model_provider.LocalModelProvider.from_local_config') as factory:
            result = await ExecutionService(self.pack()).handle_text('同意', script=[])
        self.assertEqual(result.request.state.value, 'failed')
        factory.assert_not_called()

    async def test_bad_local_connection_fails_the_run_without_losing_its_terminal_record(self):
        with patch('loomrise.model_provider.LocalModelProvider.from_local_config', side_effect=RuntimeError('private location')):
            service = ExecutionService(self.pack())
            result = await service.handle_text('同意')
        self.assertEqual(result.request.state.value, 'failed')
        self.assertEqual(service._active, {})
        self.assertTrue(service.ledger.find('run.finished'))
        self.assertNotIn('private location', str(service.ledger.events))

    async def test_explicit_provider_wires_completion_and_failure_stays_zero_write(self):
        class Provider:
            model = 'scripted-s1'
            def route(self, candidates, state):
                raise AssertionError('deterministic graph must not call routing provider')
            def completion(self, check, state):
                return decision(evidence={'fields': [], 'utterance': '同意'})
            async def recall(self, candidates, state):
                return []
        service = ExecutionService(self.pack(), model_provider=Provider())
        result = await service.handle_text('同意', script=[{'text': '继续答疑'}])
        self.assertEqual(result.request.state.value, 'success')
        self.assertEqual(result.write_count, 0)
        self.assertTrue(service.ledger.find('route.graph.completion'))

    async def test_cancelled_blocking_provider_cannot_persist_its_late_route_or_start_business(self):
        entered, release = threading.Event(), threading.Event()
        class Provider:
            model = 'scripted-s1'
            def route(self, candidates, state):
                return None
            def completion(self, check, state):
                entered.set()
                release.wait(2)
                return decision(evidence={'fields': [], 'utterance': '同意'})
            async def recall(self, candidates, state):
                raise AssertionError('cancelled route must not recall')
        service = ExecutionService(self.pack(), model_provider=Provider())
        task = asyncio.create_task(service.handle_text('同意', script=[{'text': '不可发送'}]))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            start = service.ledger.find('run.started')[-1]
            self.assertTrue(service.cancel(start.request_id, run_id=start.run_id))
            result = await asyncio.wait_for(task, 1)
            self.assertEqual(result.request.state.value, 'cancelled')
            count = len(service.ledger.events)
        finally:
            release.set()
        await asyncio.sleep(0.05)
        self.assertEqual(len(service.ledger.events), count)
        self.assertFalse(service.ledger.find('route.graph.completion'))
        self.assertFalse(service.ledger.find('request.routed'))
        self.assertFalse(service.ledger.find('tool.outcome'))
        self.assertEqual(service._active, {})
