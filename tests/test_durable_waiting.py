import os
import tempfile
import unittest
import asyncio
import copy
import json
from dataclasses import replace

from loomrise.contracts import Channel, RequestState, Run, ServiceRequest, SubjectScope, new_id
from loomrise.durable_adapter import DurableRunAdapter
from loomrise.durable_store import SqliteStore
from loomrise.service import ExecutionService
from loomrise.service_cycles import ServiceCycleAuthority
from tests.test_graph_service import graph_pack
from tests.test_graph_runtime import config as nested_graph_config


class DurableWaitingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SqliteStore(os.path.join(self.tmp.name, "wait.db"), owner_id="worker-a")
        self.request = ServiceRequest(
            request_id=new_id("req"), tenant_id="tenant_demo", agent_version="av",
            channel=Channel.TEXT, state=RequestState.RUNNING,
        )
        self.run = Run(run_id=new_id("run"), request_id=self.request.request_id,
                       tenant_id="tenant_demo", agent_version="av", owner_id="worker-a")
        self.store.begin_run(self.request, self.run, [])
        self.adapter = DurableRunAdapter(self.store, owner_id="worker-a")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_suspend_persists_wait_and_wake_fences_generation(self):
        parked = self.adapter.suspend_wait(
            self.run, waiting_on="approval.received", timeout_ms=5000,
            timeout_to="handoff", metadata={"cycle_counters": {"u": 1}},
        )
        self.assertEqual(parked["state"], "waiting")
        self.assertEqual(self.store.run_row(self.run.run_id)["status"], "waiting")
        self.assertEqual(self.store.wait_row(self.run.run_id)["waiting_on"], "approval.received")
        with self.assertRaises(RuntimeError):
            self.adapter.wake_wait(self.run.run_id, generation=2)
        woken = self.adapter.wake_wait(self.run.run_id, wake_kind="event")
        self.assertEqual(woken["state"], "woken")
        self.assertEqual(self.store.load_events(self.run.run_id)[-1].event_type, "run.wait_woken")
        self.assertEqual(self.store.run_row(self.run.run_id)["finish_reason"], "wake_superseded")
        with self.assertRaises(RuntimeError):
            self.adapter.wake_wait(self.run.run_id)

    def test_old_generation_cannot_suspend(self):
        self.run.occupancy_generation = 2
        with self.assertRaises(RuntimeError):
            self.adapter.suspend_wait(self.run, waiting_on="approval.received")

    def test_due_waits_are_read_only_and_cancel_is_terminal(self):
        self.adapter.suspend_wait(self.run, waiting_on="approval.received", timeout_ms=0, timeout_to="self.done")
        due = self.store.due_waits(tenant_id="tenant_demo")
        self.assertEqual([item["run_id"] for item in due], [self.run.run_id])
        events = self.adapter.cancel_wait(self.run, reason="user_cancel")
        self.assertEqual([event.event_type for event in events], ["run.cancel_requested", "run.cancel_confirmed"])
        self.assertEqual(self.store.run_row(self.run.run_id)["status"], "cancelled")
        self.assertEqual(self.store.wait_row(self.run.run_id)["state"], "cancelled")


class DurableTimeoutIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_wake_preserves_judge_facts_over_the_original_routing_input(self):
        pack = graph_pack()
        config = copy.deepcopy(pack.agent_version.orchestration)
        config['persona']['fields']['eligible'] = {'type': 'boolean'}
        judge = copy.deepcopy(config['units'][0])
        judge.update(unit_id='judge', writes=['eligible'],
                     body={'kind': 'judge', 'condition': {}, 'result_field': 'eligible'})
        config['units'].append(judge)
        config['units'][0]['waits'] = [{'on': 'approval.received'}]
        config['orchestration']['nodes'].insert(0, {'id': 'judge', 'unit_ref': {'unit_id': 'judge', 'version': 1}})
        config['orchestration']['entry'] = 'judge.from_start'
        config['orchestration']['edges'] = [
            {'id': 'judged', 'from': 'judge.done', 'to': 'booking.from_start', 'condition': {}},
            {'id': 'eligible', 'from': 'booking.done', 'to': 'end', 'condition': {'fact': {'field': 'eligible', 'op': 'eq', 'value': True}}},
            {'id': 'not-eligible', 'from': 'booking.done', 'to': 'end', 'condition': {'fact': {'field': 'eligible', 'op': 'eq', 'value': False}}},
        ]
        pack.agent_version = replace(pack.agent_version, orchestration=config)
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'judge-continuation.db'))
            try:
                service = ExecutionService(pack, store=store)
                parked = await service.handle_text('预约', script=[], routing_state={'eligible': False})
                restored = ExecutionService(pack, store=store)
                completed = await restored.wake_waiting_request(parked.run_id, event='approval.received', script=[])
                route = next(e for e in store.load_events(completed.run_id) if e.event_type == 'route.graph.finished')
                self.assertEqual(route.payload['selected_edges'], ['eligible'])
            finally:
                store.close()

    async def test_restart_and_wake_continue_after_graph_body_without_replaying_its_cycle(self):
        pack = graph_pack()
        config = nested_graph_config()
        config['units'][0]['body']['edges'][0].update(
            to='child.from_start', max_rounds=1, exit='self.done', counter='attempt_count', window='cycle')
        config['units'][0]['waits'] = [{'on': 'approval.received'}, {'on': 'shipping.ready'}]
        pack.agent_version = replace(pack.agent_version, orchestration=config,
                                     unit_skill_bindings={'parent': 'course_consult_booking'})
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'graph-continuation.db')
            store = SqliteStore(path)
            authority = ServiceCycleAuthority(store, tenant_id='tenant_demo', agent_id='booking',
                                              authority_id='fictional-case-source')
            service = ExecutionService(pack, store=store, agent_id='booking', cycle_authority=authority)
            grant = authority.register(subject_id='fictional-alice', matter_ref='fictional-order-1',
                source_event_id='fixture-open-1', agent_version=pack.agent_version.version_id,
                config_hash=service.cycle_config_hash)
            request = ServiceRequest(new_id('req'), 'tenant_demo', pack.agent_version.version_id,
                Channel.TEXT, RequestState.QUEUED, subject_id='fictional-alice', subject_scope=SubjectScope.MAPPED)
            parked = await service.handle_text('预约', request=request, cycle_grant=grant, script=[])
            self.assertEqual(parked.text.splitlines(), ['ok', 'ok'])
            old_counters = store.wait_row(parked.run_id)['metadata']['cycle_counters']
            self.assertEqual(old_counters['["parent","child-done"]'], 2)
            store.close()
            store = SqliteStore(path)
            try:
                restored = ExecutionService(pack, store=store, agent_id='booking')
                approved = await restored.wake_waiting_request(parked.run_id, event='approval.received', script=[])
                self.assertEqual(approved.request.state.value, 'waiting')
                completed = await restored.wake_waiting_request(approved.run_id, event='shipping.ready', script=[{'text': '完成'}])
                self.assertEqual(completed.request.state.value, 'success')
                snapshot = json.loads(store.run_row(completed.run_id)['snapshot_json'])
                self.assertEqual(snapshot['routing_state']['cycle_counters'], old_counters)
                new_cycles = [e for rid in (approved.run_id, completed.run_id) for e in store.load_events(rid)
                              if e.event_type == 'route.graph.cycle']
                self.assertEqual(new_cycles, [])
                self.assertEqual(completed.text, '完成')
                self.assertTrue(store.verify_chain())
            finally:
                store.close()

    async def test_waiting_say_is_emitted_now_and_never_reemitted_after_wake(self):
        pack = graph_pack()
        config = copy.deepcopy(pack.agent_version.orchestration)
        config['units'][0]['body']['text'] = '请确认预约后再继续。'
        config['units'][0]['waits'] = [{'on': 'approval.received'}]
        pack.agent_version = replace(pack.agent_version, orchestration=config)
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'waiting-message.db'))
            try:
                service = ExecutionService(pack, store=store)
                parked = await service.handle_text('预约', script=[])
                self.assertEqual(parked.text, '请确认预约后再继续。')
                outputs = [e for e in store.load_events(parked.run_id) if e.event_type == 'reply.text']
                self.assertEqual([e.payload['text'] for e in outputs], [parked.text])
                restored = ExecutionService(pack, store=store)
                finished = await restored.wake_waiting_request(parked.run_id, event='approval.received', script=[{'text': '完成'}])
                outputs = [e for e in store.load_events(finished.run_id) if e.event_type == 'reply.text']
                self.assertEqual([e.payload['text'] for e in outputs], ['完成'])
                self.assertEqual(finished.text, '完成')
                self.assertTrue(store.verify_chain())
            finally:
                store.close()

    async def test_crash_after_consuming_wait_can_resume_from_durable_wake_evidence(self):
        pack = graph_pack()
        config = copy.deepcopy(pack.agent_version.orchestration)
        config['units'][0]['waits'] = [{'on': 'approval.received'}]
        pack.agent_version = replace(pack.agent_version, orchestration=config)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'crash-after-wake.db')
            store = SqliteStore(path)
            service = ExecutionService(pack, store=store, agent_id='booking')
            parked = await service.handle_text('预约', script=[], routing_state={'cycle_counters': {'cycle': 2}})

            async def crash(*args, **kwargs):
                raise RuntimeError('injected crash after wake commit')

            service._resume_with_routing = crash
            with self.assertRaisesRegex(RuntimeError, 'injected crash'):
                await service.wake_waiting_request(parked.run_id, event='approval.received', script=[])
            store.close()
            restored_store = SqliteStore(path)
            try:
                restored = ExecutionService(pack, store=restored_store, agent_id='booking')
                completed = await restored.resume_recoverable_request(parked.request.request_id, script=[{'text': '完成'}])
                self.assertEqual(completed.request.state.value, 'success')
                snapshot = json.loads(restored_store.run_row(completed.run_id)['snapshot_json'])
                self.assertEqual(snapshot['routing_state']['event'], 'approval.received')
                self.assertEqual(snapshot['routing_state']['cycle_counters']['cycle'], 2)
                wakes = [e for e in restored_store.load_events(parked.run_id) if e.event_type == 'run.wait_woken']
                self.assertEqual(len(wakes), 1)
                self.assertEqual(wakes[0].payload['event'], 'approval.received')
                with self.assertRaises(RuntimeError):
                    await restored.resume_recoverable_request(parked.request.request_id, script=[{'text': '不得重放'}])
                self.assertTrue(restored_store.verify_chain())
            finally:
                restored_store.close()

    async def test_other_agent_or_changed_snapshot_cannot_cancel_a_parked_run(self):
        pack = graph_pack()
        config = copy.deepcopy(pack.agent_version.orchestration)
        config['units'][0]['waits'] = [{'on': 'approval.received'}]
        pack.agent_version = replace(pack.agent_version, orchestration=config)
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'cancel-scope.db'))
            try:
                service = ExecutionService(pack, store=store, agent_id='booking')
                parked = await service.handle_text('预约', script=[])
                other = ExecutionService(pack, store=store, agent_id='different-agent')
                self.assertFalse(other.cancel(parked.request.request_id, run_id=parked.run_id))
                changed_pack = copy.deepcopy(pack)
                changed_pack.agent_version.orchestration['units'][0]['body']['text'] = 'changed'
                changed = ExecutionService(changed_pack, store=store, agent_id='booking')
                self.assertFalse(changed.cancel(parked.request.request_id, run_id=parked.run_id))
                self.assertEqual(store.wait_row(parked.run_id)['state'], 'waiting')
                self.assertTrue(service.cancel(parked.request.request_id, run_id=parked.run_id))
            finally:
                store.close()

    async def test_invalid_wake_preserves_the_wait_for_a_later_valid_event(self):
        pack = graph_pack()
        config = copy.deepcopy(pack.agent_version.orchestration)
        config['units'][0]['waits'] = [{'on': 'approval.received'}]
        pack.agent_version = replace(pack.agent_version, orchestration=config)
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'invalid-wake.db'))
            try:
                service = ExecutionService(pack, store=store)
                parked = await service.handle_text('预约', script=[])
                for options in ({'event': 'wrong.event'}, {}, {'wake_kind': 'unexpected'}, {'wake_kind': 'timeout'}):
                    with self.subTest(options=options):
                        with self.assertRaises((ValueError, RuntimeError)):
                            await service.wake_waiting_request(parked.run_id, script=[], **options)
                        self.assertEqual(store.wait_row(parked.run_id)['state'], 'waiting')
                        self.assertEqual(store.run_row(parked.run_id)['status'], 'waiting')
                result = await service.wake_waiting_request(parked.run_id, event='approval.received', script=[{'text': '完成'}])
                self.assertEqual(result.request.state.value, 'success')
            finally:
                store.close()

    async def test_version_change_cannot_consume_a_wait_or_restart_under_new_configuration(self):
        pack = graph_pack()
        config = copy.deepcopy(pack.agent_version.orchestration)
        config['units'][0]['waits'] = [{'on': 'approval.received'}]
        pack.agent_version = replace(pack.agent_version, orchestration=config)
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'version-wake.db'))
            try:
                service = ExecutionService(pack, store=store)
                parked = await service.handle_text('预约', script=[])
                changed_pack = copy.deepcopy(pack)
                changed_pack.agent_version.version_id += '-changed'
                changed = ExecutionService(changed_pack, store=store)
                with self.assertRaises(RuntimeError):
                    await changed.wake_waiting_request(parked.run_id, event='approval.received', script=[])
                self.assertEqual(store.wait_row(parked.run_id)['state'], 'waiting')
            finally:
                store.close()

    async def test_route_cycle_snapshot_is_persisted_on_the_successor_run(self):
        pack = graph_pack()
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'cycle-snapshot.db'))
            try:
                service = ExecutionService(pack, store=store, owner_id='cycle-worker')
                result = await service.handle_text('预约', script=[])
                snapshot = store.run_row(result.run_id)['snapshot_json']
                self.assertIn('routing_state', snapshot)
                self.assertIn('cycle_counters', snapshot)
            finally:
                store.close()

    async def test_timeout_wake_uses_timeout_to_and_preserves_cycle_snapshot(self):
        pack = graph_pack()
        config = copy.deepcopy(pack.agent_version.orchestration)
        config["units"][0]["waits"] = [{"on": "approval.received", "timeoutMs": 0, "timeoutTo": "self.done"}]
        pack.agent_version = replace(pack.agent_version, orchestration=config)
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, "timeout.db"), owner_id="timeout-worker")
            service = ExecutionService(pack, store=store, owner_id="timeout-worker")
            parked = await service.handle_text("预约", script=[])
            self.assertEqual(parked.run_status.value, "waiting")
            resumed = await service.wake_waiting_request(parked.run_id, wake_kind="timeout", script=[{"text": "timeout handled"}])
            self.assertEqual(resumed.request.state.value, "success")
            self.assertEqual(store.wait_row(parked.run_id)["state"], "woken")
            store.close()

    async def test_due_waits_is_idempotent_when_called_twice(self):
        pack = graph_pack()
        config = copy.deepcopy(pack.agent_version.orchestration)
        config["units"][0]["waits"] = [{"on": "approval.received", "timeoutMs": 0, "timeoutTo": "self.done"}]
        pack.agent_version = replace(pack.agent_version, orchestration=config)
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, "timeout.db"), owner_id="timeout-worker")
            service = ExecutionService(pack, store=store, owner_id="timeout-worker")
            parked = await service.handle_text("预约", script=[])
            first = await service.wake_due_waits(script=[{"text": "timeout handled"}])
            second = await service.wake_due_waits(script=[{"text": "must not replay"}])
            self.assertEqual(len(first), 1)
            self.assertNotEqual(first[0].run_id, parked.run_id)
            self.assertEqual(store.wait_row(parked.run_id)["state"], "woken")
            self.assertEqual(second, [])
            store.close()


if __name__ == "__main__":
    unittest.main()
