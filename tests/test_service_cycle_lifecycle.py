"""业务周期生命周期：关闭 / 新周期裁定 / 显式迁移，全部使用虚构本地来源。

覆盖 SQLite 重开、Online Backup 恢复、并发裁定、撤销/取消、旧 generation 拒绝、
无授权迁移被拒、来源换源被拒，并保持 ServiceCycleAuthority 对象身份授权硬边界。
"""
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from loomrise.contracts import RequestState, RunEvent
from loomrise.durable_store import SqliteStore
from loomrise.service import ExecutionService
from loomrise.service_cycles import ServiceCycleAuthority
from tests.test_service_cycles import loop_pack, mapped_request

TENANT = 'tenant_demo'
AGENT = 'fictional-agent'
SOURCE = 'fictional-case-source'
SUBJECT = 'fictional-alice'
MATTER = 'fictional-order-1'
AV = 'av-fixture'
HASH = 'hash-fixture'


def authority(store, *, source=SOURCE):
    return ServiceCycleAuthority(store, tenant_id=TENANT, agent_id=AGENT, authority_id=source)


def plain(store, *, source=SOURCE, event='fixture-open-1', matter=MATTER, subject=SUBJECT):
    auth = authority(store, source=source)
    g = auth.register(subject_id=subject, matter_ref=matter, source_event_id=event,
                      agent_version=AV, config_hash=HASH)
    return auth, g, auth.resolve(g)


def register(auth, *, event, matter=MATTER, subject=SUBJECT, version=AV, config=HASH):
    return auth.register(subject_id=subject, matter_ref=matter, source_event_id=event,
                         agent_version=version, config_hash=config)


def grant(authority_obj, service):
    return authority_obj.register(subject_id=SUBJECT, matter_ref=MATTER, source_event_id='fixture-open-1',
                                  agent_version=service.pack.agent_version.version_id,
                                  config_hash=service.cycle_config_hash)


def admit(service, binding):
    request = mapped_request(service.pack)
    request.state, request.service_cycle = RequestState.RUNNING, binding
    return service.durable.begin(
        request, agent_version=request.agent_version, generation=1, input_text='咨询',
        snapshot={'agent_id': service.agent_id, 'orchestration': service.graph_config,
                  'unit_skill_bindings': service.unit_skill_bindings,
                  'service_cycle': binding.to_dict(), 'cycle_config_hash': service.cycle_config_hash}).run


def reserve(store, run, binding, *, identity='finish-booking'):
    event = RunEvent(seq=store.next_seq(run.run_id), event_type='route.graph.cycle',
                     request_id=run.request_id, run_id=run.run_id, tenant_id=run.tenant_id,
                     agent_version=run.agent_version, channel='text', payload={'counter': 'attempt_count'})
    return store.reserve_service_cycle(
        run.run_id, generation=run.occupancy_generation, binding=binding,
        kind='loop', layer=(), identity=identity, max_rounds=1, event=event)


def task(store, cycle_id, task_id):
    store.create_task_item(task_id=task_id, tenant_id=TENANT, agent_id=AGENT, subject_id=SUBJECT,
                           service_cycle_id=cycle_id, purpose='follow_up', source_agent_version=AV)


class ServiceCycleLifecycleTests(unittest.TestCase):
    def test_close_is_terminal_and_blocks_silent_reuse_of_closed_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'close.db'))
            try:
                auth, g, gen1 = plain(store)
                closed = auth.close(g)
                self.assertEqual(closed['state'], 'closed')
                self.assertEqual(store.service_cycle_state(gen1.cycle_id)['state'], 'closed')
                self.assertIsNotNone(store.service_cycle_state(gen1.cycle_id)['closed_at'])
                # 新来源不能静默复用已关闭周期，必须显式裁定。
                with self.assertRaisesRegex(ValueError, '关闭|裁定|复用'):
                    register(auth, event='fixture-open-2')
                # 关闭是终态，不能重复关闭。
                with self.assertRaisesRegex(ValueError, 'terminal|终态|关闭'):
                    auth.close(g)
                # 重放已登记来源是幂等的，但旧周期仍为终态。
                self.assertEqual(auth.resolve(register(auth, event='fixture-open-1')), gen1)
                self.assertEqual(store.service_cycle_state(gen1.cycle_id)['state'], 'closed')
            finally:
                store.close()

    def test_adjudicate_opens_fresh_generation_with_lineage_and_pinned_version(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'adjudicate.db'))
            try:
                auth, g, gen1 = plain(store)
                auth.close(g)
                new_grant = auth.adjudicate(g, source_event_id='fixture-open-2')
                gen2 = auth.resolve(new_grant)
                self.assertNotEqual(gen2.cycle_id, gen1.cycle_id)
                self.assertEqual(gen2.source_event_id, 'fixture-open-2')
                self.assertEqual((gen2.subject_id, gen2.matter_ref, gen2.tenant_id, gen2.agent_id),
                                 (SUBJECT, MATTER, TENANT, AGENT))
                # 版本/config 沿用旧周期冻结值，不借裁定换版本。
                self.assertEqual((gen2.agent_version, gen2.config_hash), (AV, HASH))
                first = store.service_cycle_state(gen1.cycle_id)
                second = store.service_cycle_state(gen2.cycle_id)
                self.assertEqual(first['state'], 'closed')
                self.assertEqual(second['state'], 'active')
                self.assertEqual(second['generation'], first['generation'] + 1)
                self.assertEqual(second['predecessor_cycle_id'], gen1.cycle_id)
                # 新来源现在登记到 active 的 gen2，而非旧 gen1。
                self.assertEqual(auth.resolve(register(auth, event='fixture-open-3')).cycle_id, gen2.cycle_id)
                # 旧 grant 不能重复裁定出第二个后继。
                with self.assertRaisesRegex(ValueError, 'successor|generation|后继'):
                    auth.adjudicate(g, source_event_id='fixture-open-4')
            finally:
                store.close()

    def test_sqlite_reopen_preserves_close_adjudication_and_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'reopen.db')
            store = SqliteStore(path)
            auth, g, gen1 = plain(store)
            task(store, gen1.cycle_id, 'task-1')
            auth.close(g)
            new_grant = auth.adjudicate(g, source_event_id='fixture-open-2')
            gen2 = auth.resolve(new_grant)
            migrated = auth.migrate(g, new_grant, task_id='task-1')
            store.close()
            reopened = SqliteStore(path)
            try:
                self.assertEqual(reopened.service_cycle_state(gen1.cycle_id)['state'], 'closed')
                self.assertEqual(reopened.service_cycle_state(gen2.cycle_id)['state'], 'active')
                self.assertEqual(reopened.service_cycle_state(gen2.cycle_id)['predecessor_cycle_id'], gen1.cycle_id)
                self.assertEqual(reopened.task_item('task-1')['state'], 'migrated')
                self.assertEqual(reopened.task_item(migrated['task_id'])['service_cycle_id'], gen2.cycle_id)
                rows = reopened.service_cycle_migration_rows(source_cycle_id=gen1.cycle_id)
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]['source_task_id'], rows[0]['target_task_id'],
                                  rows[0]['root_task_id'], rows[0]['authorized_by']),
                                 ('task-1', migrated['task_id'], 'task-1', SOURCE))
                self.assertTrue(reopened.verify_chain())
            finally:
                reopened.close()

    def test_online_backup_restore_preserves_lifecycle_and_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'live.db')
            backup = os.path.join(directory, 'backup.db')
            store = SqliteStore(path)
            auth, g, gen1 = plain(store)
            task(store, gen1.cycle_id, 'task-1')
            auth.close(g)
            new_grant = auth.adjudicate(g, source_event_id='fixture-open-2')
            gen2 = auth.resolve(new_grant)
            migrated = auth.migrate(g, new_grant, task_id='task-1')
            store.backup_to(backup)
            store.close()
            restored = SqliteStore(backup)
            try:
                self.assertEqual(restored.service_cycle_state(gen1.cycle_id)['state'], 'closed')
                self.assertEqual(restored.service_cycle_state(gen2.cycle_id)['state'], 'active')
                self.assertEqual(restored.task_item('task-1')['state'], 'migrated')
                self.assertEqual(restored.task_item(migrated['task_id'])['service_cycle_id'], gen2.cycle_id)
                self.assertEqual(len(restored.service_cycle_migration_rows()), 1)
                self.assertTrue(restored.verify_chain())
            finally:
                restored.close()

    def test_concurrent_adjudication_from_two_connections_yields_single_successor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'race.db')
            first = SqliteStore(path)
            auth0, g0, gen1 = plain(first)
            auth0.close(g0)
            first.close()
            conn_a, conn_b = SqliteStore(path), SqliteStore(path)
            try:
                auth_a, auth_b = authority(conn_a), authority(conn_b)
                g_a = register(auth_a, event='fixture-open-1')
                g_b = register(auth_b, event='fixture-open-1')
                self.assertEqual(auth_a.resolve(g_a), gen1)
                self.assertEqual(auth_b.resolve(g_b), gen1)
                barrier = threading.Barrier(2)

                def attempt(auth, g, event):
                    barrier.wait(timeout=5)
                    try:
                        return auth.adjudicate(g, source_event_id=event)
                    except ValueError:
                        return None

                with ThreadPoolExecutor(max_workers=2) as pool:
                    jobs = [pool.submit(attempt, auth_a, g_a, 'concurrent-a'),
                            pool.submit(attempt, auth_b, g_b, 'concurrent-b')]
                    outcomes = [job.result(timeout=10) for job in jobs]
                self.assertEqual(sorted(result is not None for result in outcomes), [False, True])
                rows = conn_a._conn.execute(
                    "SELECT state FROM service_cycles WHERE subject_id=? AND matter_ref=?",
                    (SUBJECT, MATTER)).fetchall()
                self.assertEqual(sorted(row['state'] for row in rows), ['active', 'closed'])
            finally:
                conn_a.close()
                conn_b.close()

    def test_cancelled_cycle_and_cancelled_task_are_terminal_and_not_resurrected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'cancel.db'))
            try:
                auth, g, gen1 = plain(store)
                task(store, gen1.cycle_id, 'cancelled-task')
                store.cancel_task_item('cancelled-task')
                cancelled = auth.close(g, reason='cancelled')
                self.assertEqual(cancelled['state'], 'cancelled')
                # 撤销/取消的周期是终态，不能作为新周期的 lineage 父。
                with self.assertRaisesRegex(ValueError, 'closed|completed|generation'):
                    auth.adjudicate(g, source_event_id='fixture-open-2')
                # 已撤销事项不会被复活，也不在可恢复集合中。
                self.assertEqual(store.task_item('cancelled-task')['state'], 'cancelled')
                self.assertNotIn('cancelled-task',
                                 [item['task_id'] for item in store.recoverable_task_items()])
            finally:
                store.close()

    def test_old_generation_binding_cannot_reserve_or_admit_new_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'generation.db')
            store = SqliteStore(path)
            try:
                auth = authority(store)
                service = ExecutionService(loop_pack(), store=store, agent_id=AGENT, cycle_authority=auth)
                g = grant(auth, service)
                gen1 = auth.resolve(g)
                run = admit(service, gen1)  # 周期 active 时受理成功。
                auth.close(g)
                # 旧 generation 的绑定既不能预约计数，也不能受理新请求。
                with self.assertRaisesRegex(ValueError, 'closed|generation|终态'):
                    reserve(store, run, gen1)
                with self.assertRaisesRegex(ValueError, 'closed|generation'):
                    admit(service, gen1)
                self.assertEqual(store.service_cycle_state(gen1.cycle_id)['state'], 'closed')
            finally:
                store.close()

    def test_migration_requires_explicit_dual_grant_and_matching_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'authz.db'))
            try:
                auth, g, gen1 = plain(store)
                task(store, gen1.cycle_id, 'task-1')
                auth.close(g)
                new_grant = auth.adjudicate(g, source_event_id='fixture-open-2')
                gen2 = auth.resolve(new_grant)
                # 伪造/复制的 grant 不产生迁移授权。
                with self.assertRaisesRegex(ValueError, 'grant|授权'):
                    auth.migrate(object(), new_grant, task_id='task-1')
                with self.assertRaisesRegex(ValueError, 'grant|授权'):
                    auth.migrate(g, object(), task_id='task-1')
                # 无直系 lineage 的 store 级调用被拒。
                with self.assertRaisesRegex(ValueError, 'lineage|successor|distinct|closed|active'):
                    store.migrate_task_item(task_id='task-1', source_binding=gen1,
                                            target_binding=gen1, authority_id=SOURCE)
                # 换源（authority 不匹配）被拒。
                with self.assertRaisesRegex(ValueError, 'authority|受信'):
                    store.migrate_task_item(task_id='task-1', source_binding=gen1,
                                            target_binding=gen2, authority_id='another-source')
                # 授权齐备才真正迁移。
                self.assertEqual(auth.migrate(g, new_grant, task_id='task-1')['service_cycle_id'], gen2.cycle_id)
            finally:
                store.close()

    def test_migration_preserves_lineage_and_excludes_cancelled_items(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'lineage.db'))
            try:
                auth, g, gen1 = plain(store)
                task(store, gen1.cycle_id, 'active-task')
                task(store, gen1.cycle_id, 'cancelled-task')
                store.cancel_task_item('cancelled-task')
                auth.close(g)
                new_grant = auth.adjudicate(g, source_event_id='fixture-open-2')
                gen2 = auth.resolve(new_grant)
                # 已撤销事项不能被迁移/复活。
                with self.assertRaisesRegex(ValueError, 'cancelled|terminal|复活'):
                    auth.migrate(g, new_grant, task_id='cancelled-task')
                migrated = auth.migrate(g, new_grant, task_id='active-task')
                self.assertNotEqual(migrated['task_id'], 'active-task')
                self.assertEqual(migrated['service_cycle_id'], gen2.cycle_id)
                self.assertEqual(migrated['state'], 'scheduled')
                self.assertEqual(store.task_item('active-task')['state'], 'migrated')
                self.assertEqual(store.task_item('cancelled-task')['state'], 'cancelled')
                rows = store.service_cycle_migration_rows(source_cycle_id=gen1.cycle_id)
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]['source_task_id'], rows[0]['target_task_id'],
                                  rows[0]['root_task_id'], rows[0]['authorized_by']),
                                 ('active-task', migrated['task_id'], 'active-task', SOURCE))
                # 源事项不自动合并/复活，重复迁移被拒。
                with self.assertRaisesRegex(ValueError, 'already|migrated|复活|terminal'):
                    auth.migrate(g, new_grant, task_id='active-task')
                # 连续两代迁移保留同一 root lineage。
                auth.close(new_grant)
                third_grant = auth.adjudicate(new_grant, source_event_id='fixture-open-3')
                migrated2 = auth.migrate(new_grant, third_grant, task_id=migrated['task_id'])
                self.assertNotEqual(migrated2['task_id'], migrated['task_id'])
                roots = [row['root_task_id'] for row in store.service_cycle_migration_rows()]
                self.assertEqual(roots, ['active-task', 'active-task'])
            finally:
                store.close()

    def test_source_swap_and_registered_event_reuse_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'swap.db'))
            try:
                auth, g, gen1 = plain(store)
                auth.close(g)
                # store 级裁定若换用另一受信来源被拒。
                with self.assertRaisesRegex(ValueError, 'authority|受信'):
                    store.adjudicate_new_service_cycle(gen1, authority_id='another-source',
                                                       source_event_id='fixture-open-swap')
                # 已登记的业务事件 ID 不能换到另一受信来源重新登记。
                with self.assertRaisesRegex(ValueError, '换源|另一受信'):
                    store.register_service_cycle(
                        tenant_id=TENANT, agent_id=AGENT, subject_id=SUBJECT,
                        authority_id='another-source', matter_ref=MATTER, source_event_id='fixture-open-1',
                        agent_version=AV, config_hash=HASH)
                # 同一事件 ID 也不能改绑另一主体/事项。
                with self.assertRaisesRegex(ValueError, 'source|主体|事项'):
                    register(auth, event='fixture-open-1', subject='fictional-bob')
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
