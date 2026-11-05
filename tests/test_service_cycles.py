"""可信业务周期的 admission、防环与恢复，全部使用虚构本地业务来源。"""
import asyncio
import json
import importlib.util
import os
import sqlite3
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from unittest.mock import patch
import unittest
from copy import deepcopy
from dataclasses import replace

from loomrise.contracts import Channel, RequestState, Run, RunEvent, ServiceRequest, SubjectScope, new_id
from loomrise.durable_adapter import DurableRunAdapter
from loomrise.durable_store import SCHEMA_VERSION, SqliteStore
from loomrise.service import ExecutionService
from loomrise.ledger import EventLedger
from tests.test_graph_service import graph_pack
from tests.test_graph_runtime import config as nested_graph_config, unit


def loop_pack():
    pack = graph_pack()
    config = deepcopy(pack.agent_version.orchestration)
    config['orchestration']['edges'][0].update(
        to='booking.from_start', max_rounds=1, exit='end', counter='attempt_count', window='cycle')
    pack.agent_version = replace(pack.agent_version, orchestration=config)
    return pack


def fallback_pack(*, nested=False):
    pack = graph_pack()
    config = nested_graph_config() if nested else deepcopy(pack.agent_version.orchestration)
    config['units'].append(unit('safe'))
    owner = config['units'][0] if nested else config['orchestration']
    graph = owner['body'] if nested else owner
    graph['nodes'].append({'id': 'safe', 'unit_ref': {'unit_id': 'safe', 'version': 1}})
    owner['fallback'] = {'kind': 'default_unit', 'target': 'safe.from_start'}
    graph['edges'][0]['condition'] = {'fact': {'field': 'verified', 'op': 'eq', 'value': True}}
    graph['edges'].append({'id': 'safe-end', 'from': 'safe.done',
                           'to': 'self.done' if nested else 'end', 'condition': {}})
    config['units'][-1]['max_rounds'] = 1
    bindings = {'parent': 'course_consult_booking'} if nested else {'booking-entry': 'course_consult_booking', 'safe': 'refund_request'}
    pack.agent_version = replace(pack.agent_version, orchestration=config, unit_skill_bindings=bindings)
    return pack


def mapped_request(pack, *, subject='fictional-alice'):
    return ServiceRequest(new_id('req'), 'tenant_demo', pack.agent_version.version_id,
                          Channel.TEXT, RequestState.QUEUED,
                          subject_id=subject, subject_scope=SubjectScope.MAPPED)


class ServiceCycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_admission_and_worker_reservation_keep_both_event_chains_valid(self):
        selector_entered, allow_reserve = threading.Event(), threading.Event()
        cycle_recorded, second_recorded = threading.Event(), threading.Event()
        local, selections = threading.local(), Counter()
        original_seal = RunEvent.seal
        def interleaved_seal(event, previous_hash):
            if getattr(local, 'pause_admission', False):
                local.pause_admission = False
                allow_reserve.set()
                # The old unlocked path lets the real worker project here.
                # The fixed path serializes it until admission finishes.
                cycle_recorded.wait(0.04)
            return original_seal(event, previous_hash)
        class InterleavedLedger(EventLedger):
            starts = 0
            def record(self, event, *, persist=True):
                second = event.event_type == 'run.started' and self.starts == 1
                if event.event_type == 'run.started':
                    self.starts += 1
                if second:
                    local.pause_admission = True
                super().record(event, persist=persist)
                if event.event_type == 'route.graph.cycle':
                    cycle_recorded.set()
                if second:
                    second_recorded.set()
        def selector(candidates, state):
            selections[state['input']] += 1
            if state['input'] == 'first':
                if selections['first'] == 1:
                    selector_entered.set()
                    allow_reserve.wait(3)
                else:
                    second_recorded.wait(3)
            edge_id = candidates[0]['id']
            return {'edge_id': edge_id, 'scores': {edge_id: 0.95}, 'evidence': {'fields': ['input']}}
        with tempfile.TemporaryDirectory() as directory, patch.object(RunEvent, 'seal', interleaved_seal):
            store = SqliteStore(os.path.join(directory, 'parallel.db'))
            try:
                pack, ledger = loop_pack(), InterleavedLedger()
                pack.agent_version.orchestration['orchestration']['routing']['mode'] = 'llm'
                authority = self.authority(store)
                service = ExecutionService(pack, store=store, agent_id='fictional-agent',
                    cycle_authority=authority, ledger=ledger, graph_selector=selector)
                grant = self.grant(authority, service)
                first = asyncio.create_task(service.handle_text('first', request=mapped_request(pack),
                                                              cycle_grant=grant, script=[]))
                self.assertTrue(await asyncio.to_thread(selector_entered.wait, 3))
                second = asyncio.create_task(service.handle_text('second', request=mapped_request(pack),
                                                               cycle_grant=grant, script=[]))
                results = await asyncio.wait_for(asyncio.gather(first, second), 8)
                self.assertEqual([result.request.state for result in results], [RequestState.SUCCESS] * 2)
                self.assertTrue(store.verify_chain())
                self.assertTrue(ledger.verify())
                self.assertEqual([event.seq for event in ledger.events], list(range(len(ledger.events))))
            finally:
                allow_reserve.set()
                second_recorded.set()
                store.close()

    def authority(self, store, *, agent='fictional-agent', tenant='tenant_demo', source='fictional-case-source'):
        self.assertIsNotNone(importlib.util.find_spec('loomrise.service_cycles'),
                             'trusted server-side cycle authority is missing')
        from loomrise.service_cycles import ServiceCycleAuthority
        return ServiceCycleAuthority(store, tenant_id=tenant, agent_id=agent, authority_id=source)

    def grant(self, authority, service, *, subject='fictional-alice', matter='fictional-order-1', event='fixture-open-1'):
        return authority.register(subject_id=subject, matter_ref=matter, source_event_id=event,
            agent_version=service.pack.agent_version.version_id, config_hash=service.cycle_config_hash)

    def admitted(self, service, binding, *, generation=1):
        request = mapped_request(service.pack)
        request.state, request.service_cycle = RequestState.RUNNING, binding
        admission = service.durable.begin(request, agent_version=request.agent_version, generation=generation,
            input_text='咨询',
            snapshot={'agent_id': service.agent_id, 'orchestration': service.graph_config,
                      'unit_skill_bindings': service.unit_skill_bindings,
                      'service_cycle': binding.to_dict(), 'cycle_config_hash': service.cycle_config_hash})
        return admission.run

    def reserve(self, store, run, binding, *, generation=None, identity='finish-booking', kind='loop',
                layer=(), limit=1):
        event = RunEvent(seq=store.next_seq(run.run_id), event_type='route.graph.cycle',
            request_id=run.request_id, run_id=run.run_id, tenant_id=run.tenant_id,
            agent_version=run.agent_version, channel='text', payload={'counter': 'attempt_count'})
        return store.reserve_service_cycle(run.run_id,
            generation=run.occupancy_generation if generation is None else generation, binding=binding,
            kind=kind, layer=layer, identity=identity, max_rounds=limit, event=event)

    async def test_reservation_revalidates_pinned_graph_identity_limit_and_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'identity.db'))
            try:
                authority = self.authority(store)
                service = ExecutionService(loop_pack(), store=store, agent_id='fictional-agent', cycle_authority=authority)
                binding = authority.resolve(self.grant(authority, service))
                run = self.admitted(service, binding)
                for change in ({'identity': 'invented-edge'}, {'limit': 999}, {'layer': ('other-layer',)},
                               {'kind': 'fallback', 'identity': 'booking.from_start'}):
                    with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'pinned|graph|identity|contract'):
                        self.reserve(store, run, binding, **change)
                with self.assertRaisesRegex(RuntimeError, 'generation|stale'):
                    self.reserve(store, run, binding, generation=2)
                self.assertEqual(store.service_cycle_counts(binding.cycle_id), {})
                self.assertEqual(len(store.load_events(run.run_id)), 1)
            finally:
                store.close()

    async def test_bound_request_rejects_parallel_new_generation_until_explicit_wait_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'generation.db'))
            try:
                authority = self.authority(store)
                service = ExecutionService(loop_pack(), store=store, agent_id='fictional-agent', cycle_authority=authority)
                binding = authority.resolve(self.grant(authority, service))
                run = self.admitted(service, binding)
                request = mapped_request(service.pack)
                request.request_id, request.service_cycle = run.request_id, binding
                for generation in (1, 2):
                    with self.assertRaisesRegex(RuntimeError, 'active|waiting|generation|running'):
                        service.durable.begin(request, agent_version=binding.agent_version, generation=generation,
                            snapshot={'agent_id': service.agent_id, 'orchestration': service.graph_config,
                                      'unit_skill_bindings': service.unit_skill_bindings,
                                      'service_cycle': binding.to_dict(), 'cycle_config_hash': service.cycle_config_hash})
                self.assertTrue(self.reserve(store, run, binding)['allowed'])
            finally:
                store.close()

    async def test_caller_cannot_inject_checkpoint_or_counter_snapshot_for_a_bound_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'spoof-checkpoint.db'))
            try:
                authority = self.authority(store)
                service = ExecutionService(loop_pack(), store=store, agent_id='fictional-agent', cycle_authority=authority)
                grant = self.grant(authority, service)
                # A fake terminal checkpoint would bypass every reservation.
                spoof = {'frames': {'[]': {'current': 'end'}}, 'cycle_counters': {},
                         'completion_decisions': {}, 'messages': []}
                result = await service.handle_text('咨询', request=mapped_request(service.pack), cycle_grant=grant,
                    routing_state={'__graph_continuation': spoof, 'cycle_counters': {'caller': 500}}, script=[])
                cycles = [event for event in store.load_events(result.run_id) if event.event_type == 'route.graph.cycle']
                self.assertEqual([event.payload['allowed'] for event in cycles], [True, False])
                finished = next(event for event in store.load_events(result.run_id) if event.event_type == 'route.graph.finished')
                self.assertEqual(finished.payload['cycle_counters'], {'["finish-booking"]': 2})
            finally:
                store.close()

    async def test_two_sqlite_connections_cannot_both_take_the_last_round(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'race.db')
            first_store, second_store = SqliteStore(path), SqliteStore(path)
            try:
                authority = self.authority(first_store)
                service = ExecutionService(loop_pack(), store=first_store, agent_id='fictional-agent',
                                           cycle_authority=authority, owner_id='race-owner')
                binding = authority.resolve(self.grant(authority, service))
                first, second = self.admitted(service, binding), self.admitted(service, binding)
                barrier = threading.Barrier(2)
                def take(store, run):
                    barrier.wait(timeout=5)
                    return self.reserve(store, run, binding)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    jobs = [pool.submit(take, first_store, first), pool.submit(take, second_store, second)]
                    outcomes = [job.result(timeout=10) for job in jobs]
                self.assertEqual(sorted(result['allowed'] for result in outcomes), [False, True])
                self.assertEqual(sorted(result['count'] for result in outcomes), [1, 2])
                self.assertEqual(sum(len(first_store.load_events(run.run_id)) for run in (first, second)), 4)
                self.assertTrue(first_store.verify_chain())
            finally:
                first_store.close()
                second_store.close()

    async def test_counter_and_audit_rollback_together_and_interruption_never_refunds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'crash.db')
            store = SqliteStore(path)
            authority = self.authority(store)
            service = ExecutionService(loop_pack(), store=store, agent_id='fictional-agent',
                                       cycle_authority=authority, owner_id='before-crash')
            binding = authority.resolve(self.grant(authority, service))
            run = self.admitted(service, binding)
            def crash():
                raise RuntimeError('injected commit failure')
            store.before_commit = crash
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                self.reserve(store, run, binding)
            store.before_commit = None
            self.assertEqual(store.service_cycle_counts(binding.cycle_id), {})
            self.assertEqual([event.event_type for event in store.load_events(run.run_id)], ['run.started'])
            self.assertTrue(self.reserve(store, run, binding)['allowed'])
            # Existing explicit queued recovery protocol; active unqueued runs
            # remain failed after restart and are not automatically resurrected.
            store.set_request_state(run.request_id, 'queued')
            store.close()
            restored_store = SqliteStore(path)
            try:
                restored_authority = self.authority(restored_store)
                restored = ExecutionService(loop_pack(), store=restored_store, agent_id='fictional-agent',
                    cycle_authority=restored_authority, owner_id='after-crash')
                self.assertIn(run.run_id, restored.recovery.interrupted)
                with self.assertRaisesRegex(RuntimeError, 'stale|inactive'):
                    self.reserve(restored_store, run, binding)
                resumed = await restored.resume_recoverable_request(run.request_id, script=[])
                events = restored_store.load_events(resumed.run_id)
                cycles = [event for event in events if event.event_type == 'route.graph.cycle']
                self.assertEqual([event.payload['allowed'] for event in cycles], [False])
                self.assertEqual(resumed.request.service_cycle, binding)
                self.assertEqual(restored_store.service_cycle_counts(binding.cycle_id),
                                 {'["loop","finish-booking"]': 2})
                self.assertTrue(restored_store.verify_chain())
            finally:
                restored_store.close()

    async def test_version_or_config_change_cannot_open_a_fresh_budget_for_the_same_source(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'version.db'))
            try:
                authority = self.authority(store)
                service = ExecutionService(loop_pack(), store=store, agent_id='fictional-agent', cycle_authority=authority)
                grant = self.grant(authority, service)
                binding = authority.resolve(grant)
                for same_version in (False, True):
                    pack = loop_pack()
                    if same_version:
                        pack.agent_version.orchestration['units'][0]['body']['text'] = 'changed config'
                    else:
                        pack.agent_version = replace(pack.agent_version, version_id='new-version')
                    changed = ExecutionService(pack, store=store, agent_id='fictional-agent', cycle_authority=authority)
                    with self.assertRaisesRegex(ValueError, 'version|config|pinned'):
                        self.grant(authority, changed)
                    with self.assertRaisesRegex(ValueError, 'version|config'):
                        await changed.handle_text('咨询', request=mapped_request(pack), cycle_grant=grant, script=[])
                self.assertEqual(authority.resolve(self.grant(authority, service)), binding)
                self.assertEqual(store.service_cycle_counts(binding.cycle_id), {})
            finally:
                store.close()

    async def test_root_nested_and_deeper_same_name_edges_have_separate_durable_budgets(self):
        pack = graph_pack()
        config = nested_graph_config()
        child = config['units'][1]
        child['body'] = {'kind': 'graph', 'routing': {'mode': 'deterministic'},
            'nodes': [{'id': 'leaf', 'unit_ref': {'unit_id': 'leaf', 'version': 1}}],
            'edges': [{'id': 'repeat', 'from': 'leaf.done', 'to': 'leaf.from_start', 'condition': {},
                       'max_rounds': 1, 'exit': 'self.done', 'counter': 'attempt_count', 'window': 'cycle'}]}
        child['entry_ports'][0]['goto'] = 'leaf.from_start'
        config['units'].append(unit('leaf'))
        for graph, source, target, exit_target in (
            (config['orchestration'], 'parent.done', 'parent.from_start', 'end'),
            (config['units'][0]['body'], 'child.done', 'child.from_start', 'self.done')):
            graph['edges'][0].update(id='repeat', **{'from': source}, to=target, max_rounds=1,
                                     exit=exit_target, counter='attempt_count', window='cycle')
        pack.agent_version = replace(pack.agent_version, orchestration=config,
                                     unit_skill_bindings={'parent': 'course_consult_booking'})
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'nested.db'))
            try:
                authority = self.authority(store)
                service = ExecutionService(pack, store=store, agent_id='fictional-agent', cycle_authority=authority)
                grant = self.grant(authority, service)
                first = await service.handle_text('咨询', request=mapped_request(pack), cycle_grant=grant, script=[])
                second = await service.handle_text('继续', request=mapped_request(pack), cycle_grant=grant, script=[])
                counts = store.service_cycle_counts(first.request.service_cycle.cycle_id)
                self.assertEqual(counts, {'["loop","repeat"]': 3, '["loop","parent","repeat"]': 4,
                                         '["loop","parent","child","repeat"]': 5})
                all_cycles = [event for result in (first, second) for event in store.load_events(result.run_id)
                              if event.event_type == 'route.graph.cycle']
                self.assertEqual(sum(event.payload['allowed'] for event in all_cycles), 3)
                self.assertTrue(store.verify_chain())
            finally:
                store.close()

    async def test_root_and_nested_default_unit_budgets_survive_new_requests(self):
        for nested in (False, True):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory() as directory:
                pack = fallback_pack(nested=nested)
                store = SqliteStore(os.path.join(directory, 'fallback.db'))
                try:
                    authority = self.authority(store)
                    service = ExecutionService(pack, store=store, agent_id='fictional-agent', cycle_authority=authority)
                    grant = self.grant(authority, service)
                    first = await service.handle_text('咨询', request=mapped_request(pack), cycle_grant=grant,
                                                      routing_state={'verified': False}, script=[])
                    second = await service.handle_text('继续', request=mapped_request(pack), cycle_grant=grant,
                        routing_state={'verified': False, '__graph_continuation': {'fallback_counts': {}}}, script=[])
                    self.assertEqual((first.request.state, second.request.state), (RequestState.SUCCESS, RequestState.FAILED))
                    events = [event for result in (first, second) for event in store.load_events(result.run_id)
                              if event.event_type == 'route.graph.fallback_cycle']
                    self.assertEqual([event.payload['allowed'] for event in events], [True, False])
                    key = '["fallback","parent","safe.from_start"]' if nested else '["fallback","safe.from_start"]'
                    self.assertEqual(store.service_cycle_counts(first.request.service_cycle.cycle_id), {key: 1})
                    self.assertTrue(store.verify_chain())
                finally:
                    store.close()

    async def test_wait_wake_restart_preserve_binding_budget_and_fence_old_generation(self):
        pack = loop_pack()
        pack.agent_version.orchestration['units'][0]['waits'] = [{'on': 'approval.received'}]
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'wait.db')
            store = SqliteStore(path)
            authority = self.authority(store)
            service = ExecutionService(pack, store=store, agent_id='fictional-agent', cycle_authority=authority)
            grant = self.grant(authority, service)
            first = await service.handle_text('咨询', request=mapped_request(pack), cycle_grant=grant, script=[])
            binding = first.request.service_cycle
            self.assertEqual(first.request.state, RequestState.WAITING)
            second = await service.wake_waiting_request(first.run_id, event='approval.received', script=[])
            self.assertEqual(second.request.state, RequestState.WAITING)
            self.assertEqual(store.service_cycle_counts(binding.cycle_id), {'["loop","finish-booking"]': 1})
            old = service.durable.store.run_row(first.run_id)
            old_run = Run(run_id=first.run_id, request_id=first.request.request_id, tenant_id='tenant_demo',
                          agent_version=pack.agent_version.version_id, owner_id=old['owner_id'])
            with self.assertRaisesRegex(RuntimeError, 'stale|inactive'):
                self.reserve(store, old_run, binding)
            store.close()
            store = SqliteStore(path)
            try:
                # Recovery must use the admitted source, without issuing a new grant.
                restored = ExecutionService(pack, store=store, agent_id='fictional-agent')
                completed = await restored.wake_waiting_request(second.run_id, event='approval.received', script=[])
                self.assertEqual(completed.request.state, RequestState.SUCCESS)
                self.assertEqual(completed.request.service_cycle, binding)
                self.assertEqual(store.service_cycle_counts(binding.cycle_id), {'["loop","finish-booking"]': 2})
                self.assertEqual(store.run_row(completed.run_id)['occupancy_generation'], 3)
                with self.assertRaisesRegex(RuntimeError, '唤醒|结束'):
                    await restored.wake_waiting_request(second.run_id, event='approval.received', script=[])
                self.assertTrue(store.verify_chain())
            finally:
                store.close()

    async def test_cancelled_or_failing_provider_keeps_committed_reservations(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel), tempfile.TemporaryDirectory() as directory:
                pack = loop_pack()
                pack.agent_version.orchestration['orchestration']['routing']['mode'] = 'llm'
                entered, release = threading.Event(), threading.Event()
                calls = []
                def selector(candidates, state):
                    calls.append(True)
                    if len(calls) == 2:
                        entered.set()
                        if cancel:
                            release.wait(timeout=5)
                        raise RuntimeError('fictional provider interruption')
                    edge_id = candidates[0]['id']
                    return {'edge_id': edge_id, 'scores': {edge_id: 0.95}, 'evidence': {'fields': ['input']}}
                store = SqliteStore(os.path.join(directory, 'cancel.db'))
                try:
                    authority = self.authority(store)
                    service = ExecutionService(pack, store=store, agent_id='fictional-agent',
                                               cycle_authority=authority, graph_selector=selector)
                    grant = self.grant(authority, service)
                    binding = authority.resolve(grant)
                    request = mapped_request(pack)
                    task = asyncio.create_task(service.handle_text('咨询', request=request, cycle_grant=grant, script=[]))
                    if cancel:
                        self.assertTrue(await asyncio.to_thread(entered.wait, 3))
                        run_id = service.ledger.find('run.started')[-1].run_id
                        self.assertTrue(service.cancel(request.request_id, run_id=run_id))
                        result = await task
                        release.set()
                        self.assertEqual(result.request.state, RequestState.CANCELLED)
                    else:
                        result = await task
                        self.assertEqual(result.request.state, RequestState.FAILED)
                    self.assertEqual(result.write_count, 0)
                    self.assertEqual(store.service_cycle_counts(binding.cycle_id), {'["loop","finish-booking"]': 1})
                    self.assertEqual(len([event for event in store.load_events(result.run_id)
                                          if event.event_type == 'route.graph.cycle']), 1)
                    ended = Run(run_id=result.run_id, request_id=result.request.request_id,
                        tenant_id='tenant_demo', agent_version=pack.agent_version.version_id,
                        owner_id=service.durable.owner_id)
                    with self.assertRaisesRegex(RuntimeError, 'inactive|stale'):
                        self.reserve(store, ended, binding)
                    self.assertTrue(store.verify_chain())
                    self.assertTrue(service.ledger.verify())
                finally:
                    release.set()
                    store.close()

    async def test_reopen_backup_and_schema16_upgrade_preserve_old_unbound_requests_and_inbox(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'schema16.db')
            store = SqliteStore(path)
            pack = graph_pack()
            legacy = ExecutionService(pack, store=store)
            old = await legacy.handle_text('咨询', script=[])
            store.save_inbox_preferences(tenant_id='tenant_demo', agent_id='fictional-agent', actor_id='owner',
                                         new_messages=True, handoff=True)
            store.close()
            connection = sqlite3.connect(path)
            try:
                with connection:
                    connection.execute('DROP TABLE service_cycle_counters')
                    connection.execute('DROP TABLE service_cycle_sources')
                    connection.execute('DROP TABLE service_cycles')
                    connection.execute('ALTER TABLE requests DROP COLUMN service_cycle_json')
                    connection.execute("UPDATE meta SET value='16' WHERE key='schema_version'")
            finally:
                connection.close()
            store = SqliteStore(path)
            authority = self.authority(store)
            service = ExecutionService(loop_pack(), store=store, agent_id='fictional-agent', cycle_authority=authority)
            grant = self.grant(authority, service)
            result = await service.handle_text('咨询', request=mapped_request(service.pack), cycle_grant=grant, script=[])
            binding = result.request.service_cycle
            backup = os.path.join(directory, 'backup.db')
            store.backup_to(backup)
            store.close()
            for filename in (path, backup):
                restored = SqliteStore(filename)
                try:
                    self.assertIsNone(restored.request_row(old.request.request_id)['service_cycle_json'])
                    self.assertEqual(restored.request_row(old.request.request_id)['state'], 'success')
                    self.assertEqual(restored.inbox_preferences(tenant_id='tenant_demo', agent_id='fictional-agent', actor_id='owner'),
                                     {'new_messages': True, 'handoff': True})
                    self.assertEqual(restored.service_cycle_counts(binding.cycle_id), {'["loop","finish-booking"]': 2})
                    authority = self.authority(restored)
                    service = ExecutionService(loop_pack(), store=restored, agent_id='fictional-agent', cycle_authority=authority)
                    self.assertEqual(authority.resolve(self.grant(authority, service)), binding)
                    self.assertTrue(restored.verify_chain())
                finally:
                    restored.close()

    async def test_failed_schema16_migration_rolls_back_cycle_and_inbox_tables_column_and_version(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'migration.db'))
            try:
                store._conn.execute('DROP TABLE service_cycle_counters')
                store._conn.execute('DROP TABLE service_cycle_sources')
                store._conn.execute('DROP TABLE service_cycle_migrations')
                store._conn.execute('DROP TABLE service_cycles')
                store._conn.execute('DROP TABLE customer_inbox_events')
                store._conn.execute('ALTER TABLE requests DROP COLUMN service_cycle_json')
                store._conn.execute("UPDATE meta SET value='16' WHERE key='schema_version'")
                def fail():
                    raise RuntimeError('cycle migration commit failure')
                store.before_commit = fail
                with self.assertRaisesRegex(RuntimeError, 'migration'):
                    store.migrate()
                self.assertEqual(store._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], '16')
                self.assertFalse(store._conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'service_cycle%'").fetchall())
                self.assertNotIn('service_cycle_json', [row['name'] for row in store._conn.execute('PRAGMA table_info(requests)')])
                self.assertIsNotNone(store._conn.execute("SELECT name FROM sqlite_master WHERE name='customer_inbox_preferences'").fetchone())
                self.assertIsNone(store._conn.execute("SELECT name FROM sqlite_master WHERE name='customer_inbox_events'").fetchone())
                store.before_commit = None
                store.migrate()
                self.assertEqual(store._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], str(SCHEMA_VERSION))
                self.assertIsNotNone(store._conn.execute("SELECT name FROM sqlite_master WHERE name='customer_inbox_events'").fetchone())
            finally:
                store.before_commit = None
                store.close()

    async def test_trusted_source_reuses_one_cycle_across_requests_and_channels(self):
        pack = loop_pack()
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'cycles.db'))
            try:
                authority = self.authority(store)
                service = ExecutionService(pack, store=store, agent_id='fictional-agent', cycle_authority=authority)
                grant = self.grant(authority, service)
                first = await service.handle_text('咨询', request=mapped_request(pack), cycle_grant=grant, script=[])
                second = await service.handle_utterance('继续', media_session_id='new-phone-call',
                    request=mapped_request(pack), cycle_grant=self.grant(authority, service),
                    routing_state={'cycle_counters': {}}, script=[])
                binding = first.request.service_cycle
                self.assertTrue(binding.cycle_id.startswith('cycle_'))
                self.assertEqual(binding, second.request.service_cycle)
                self.assertEqual(authority.resolve(self.grant(authority, service, event='fixture-open-1-repeated')), binding)
                self.assertNotIn(binding.cycle_id, (first.request.request_id, first.run_id, 'new-phone-call'))
                cycles = [e for e in store.load_events(first.run_id) + store.load_events(second.run_id)
                          if e.event_type == 'route.graph.cycle']
                self.assertEqual([e.payload['allowed'] for e in cycles], [True, False, False])
                self.assertEqual([e.payload['cycle_count'] for e in cycles], [1, 2, 3])
                for result in (first, second):
                    snapshot = json.loads(store.run_row(result.run_id)['snapshot_json'])
                    self.assertEqual(snapshot['service_cycle'], binding.to_dict())
                    start = store.load_events(result.run_id)[0]
                    self.assertEqual(start.payload['service_cycle'], binding.to_dict())
                self.assertTrue(store.verify_chain())
                self.assertTrue(service.ledger.verify())
            finally:
                store.close()

    async def test_grant_identity_scope_and_new_authorized_matter_are_enforced(self):
        pack = loop_pack()
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'cycles.db'))
            try:
                authority = self.authority(store)
                service = ExecutionService(pack, store=store, agent_id='fictional-agent', cycle_authority=authority)
                grant = self.grant(authority, service)
                other = self.authority(store)
                for forged in (object(), authority.resolve(grant), self.grant(other, service)):
                    with self.assertRaisesRegex(ValueError, 'grant|授权'):
                        await service.handle_text('咨询', request=mapped_request(pack), cycle_grant=forged, script=[])
                with self.assertRaisesRegex(ValueError, 'scope|主体'):
                    await service.handle_text('咨询', request=mapped_request(pack, subject='fictional-bob'),
                                              cycle_grant=grant, script=[])
                with self.assertRaisesRegex(ValueError, 'mapped|主体'):
                    await service.handle_text('咨询', cycle_grant=grant, script=[])
                with self.assertRaisesRegex(ValueError, 'source|来源'):
                    self.grant(authority, service, matter='fictional-order-2')
                first = await service.handle_text('咨询', request=mapped_request(pack), cycle_grant=grant, script=[])
                new_grant = self.grant(authority, service, matter='fictional-order-2', event='fixture-open-2')
                second = await service.handle_text('咨询', request=mapped_request(pack), cycle_grant=new_grant, script=[])
                self.assertNotEqual(first.request.service_cycle.cycle_id, second.request.service_cycle.cycle_id)
                self.assertTrue(next(e for e in store.load_events(second.run_id)
                                     if e.event_type == 'route.graph.cycle').payload['allowed'])
            finally:
                store.close()

    async def test_bound_request_cannot_change_matter_and_event_hash_contains_cycle(self):
        pack = loop_pack()
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'cycles.db'))
            try:
                authority = self.authority(store)
                service = ExecutionService(pack, store=store, agent_id='fictional-agent', cycle_authority=authority)
                grant = self.grant(authority, service)
                request = mapped_request(pack)
                first = await service.handle_text('咨询', request=request, cycle_grant=grant,
                                                   trigger_event_id='fictional-inbound-1', script=[])
                duplicate = await service.handle_text('咨询', request=mapped_request(pack), cycle_grant=grant,
                                                       trigger_event_id='fictional-inbound-1', script=[])
                self.assertEqual((duplicate.admission_status, duplicate.run_id), ('duplicate', first.run_id))
                other_grant = self.grant(authority, service, matter='fictional-order-2', event='fixture-open-2')
                conflict = await service.handle_text('咨询', request=mapped_request(pack), cycle_grant=other_grant,
                                                      trigger_event_id='fictional-inbound-1', script=[])
                self.assertEqual(conflict.admission_status, 'conflict')
                with self.assertRaisesRegex(ValueError, 'immutable|不可变|binding'):
                    await service.handle_text('继续', request=request, cycle_grant=other_grant, script=[])
                self.assertEqual(store.service_cycle_counts(first.request.service_cycle.cycle_id),
                                 {'["loop","finish-booking"]': 2})
            finally:
                store.close()

    async def test_missing_trusted_cycle_fails_closed_even_with_caller_counter_reset(self):
        pack = loop_pack()
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'cycles.db'))
            try:
                service = ExecutionService(pack, store=store, agent_id='fictional-agent')
                result = await service.handle_text('咨询', request=mapped_request(pack),
                    routing_state={'cycle_counters': {}, 'service_cycle_id': 'caller-cycle'},
                    script=[{'text': '不应执行'}])
                self.assertEqual(result.request.state, RequestState.FAILED)
                self.assertEqual(result.write_count, 0)
                self.assertFalse(service.ledger.find('request.routed'))
                self.assertIn('trusted service cycle', service.ledger.find('request.route_failed')[-1].payload['reason'])
                self.assertTrue(store.verify_chain())
            finally:
                store.close()

    async def test_non_durable_cycle_graph_does_not_claim_authoritative_limits(self):
        service = ExecutionService(loop_pack())
        result = await service.handle_text('咨询', script=[{'text': '不应执行'}])
        self.assertEqual(result.request.state, RequestState.FAILED)
        self.assertFalse(service.ledger.find('request.routed'))


if __name__ == '__main__':
    unittest.main()
