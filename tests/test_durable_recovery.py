# -*- coding: utf-8 -*-
"""重启恢复自检：旧代不复活、中断事实保留、待确认状态与幂等索引跨重启。"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loomrise.cli import DEFAULT_CASES, DEFAULT_PACK  # noqa: E402
from loomrise.contracts import (  # noqa: E402
    Case,
    Channel,
    RequestState,
    RunEvent,
    ScenarioPack,
    ServiceRequest,
    SubjectScope,
    new_id,
)
from loomrise.durable_adapter import DurableRunAdapter, action_key  # noqa: E402
from loomrise.durable_store import SqliteStore  # noqa: E402
from loomrise.service import ExecutionService  # noqa: E402


def confirm_all(calls):
    return [True] * len(calls)


def queued_request(agent_version: str) -> ServiceRequest:
    return ServiceRequest(
        request_id=new_id("req"),
        tenant_id="tenant_demo",
        agent_version=agent_version,
        channel=Channel.TEXT,
        state=RequestState.QUEUED,
    )


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "loomrise.db")
        self.case = Case.load(str(DEFAULT_CASES / "c2_booking_confirmed.json"))
        self.pack = ScenarioPack.load(str(DEFAULT_PACK))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def service(self, owner: str, store: SqliteStore | None = None) -> tuple[ExecutionService, SqliteStore]:
        store = store or SqliteStore(self.path, owner_id=owner)
        svc = ExecutionService(self.pack, store=store, owner_id=owner)
        return svc, store


class TestPersistedRun(Base):
    async def test_scripted_write_persists_run_events_and_outbox(self) -> None:
        svc, store = self.service("p1")
        try:
            r = await svc.handle_text(
                self.case.turns[0]["text"], script=self.case.script,
                ask_confirm=confirm_all,
            )
            self.assertEqual(r.write_count, 1)
            row = store.run_row(r.run_id)
            self.assertEqual(row["status"], "succeeded")
            self.assertEqual(row["request_id"], r.request.request_id)

            events = store.load_events(r.run_id)
            types = [e.event_type for e in events]
            self.assertEqual(types[0], "run.started")
            self.assertEqual(types[-1], "run.finished")
            self.assertIn("tool.outcome", types)
            self.assertTrue(store.verify_chain(), "落库事件链不可验证")

            im = store._conn.execute(
                "SELECT key, result_id FROM idempotency",
            ).fetchall()
            self.assertEqual(len(im), 1)
            self.assertEqual(im[0]["key"], action_key("create_booking", "idem-c2"))
            self.assertEqual(im[0]["result_id"], r.written_result_ids[0])
            self.assertEqual(len(store.pending_outbox()), 1)
        finally:
            store.close()

    async def test_confirmation_wait_is_persisted_before_the_callback(self) -> None:
        svc, store = self.service("p1")
        observed: list[str] = []

        async def confirm(calls):
            request = next(iter(svc.requests.values()))
            persisted = store.request_row(request.request_id)
            observed.append(persisted["state"])
            self.assertEqual(request.state, RequestState.WAITING_CONFIRM)
            return [True] * len(calls)

        try:
            result = await svc.handle_text(
                self.case.turns[0]["text"], script=self.case.script,
                ask_confirm=confirm,
            )
            self.assertEqual(observed, [RequestState.WAITING_CONFIRM.value])
            self.assertEqual(
                store.request_row(result.request.request_id)["state"],
                RequestState.SUCCESS.value,
            )
        finally:
            store.close()

    async def test_no_store_means_no_behavior_change(self) -> None:
        svc = ExecutionService(self.pack)
        r = await svc.handle_text(
            self.case.turns[0]["text"], script=self.case.script, ask_confirm=confirm_all,
        )
        self.assertEqual(r.write_count, 1)
        self.assertIsNone(svc.durable)


class TestRecovery(Base):
    async def test_subject_scope_controls_subject_id_durability(self) -> None:
        store1 = SqliteStore(self.path, owner_id="p1")
        adapter = DurableRunAdapter(store1, owner_id="p1")

        ephemeral = queued_request(self.pack.agent_version.version_id)
        ephemeral.subject_id = "session-only-subject"
        ephemeral.subject_scope = SubjectScope.EPHEMERAL
        mapped = queued_request(self.pack.agent_version.version_id)
        mapped.subject_id = "customer-42"
        mapped.subject_scope = SubjectScope.MAPPED
        adapter.begin(ephemeral, agent_version=self.pack.agent_version.version_id)
        adapter.begin(mapped, agent_version=self.pack.agent_version.version_id)
        store1.close()

        store2 = SqliteStore(self.path, owner_id="p2")
        try:
            self.assertIsNone(store2.request_row(ephemeral.request_id)["subject_id"])
            self.assertEqual(
                store2.request_row(ephemeral.request_id)["subject_scope"],
                SubjectScope.EPHEMERAL.value,
            )
            self.assertEqual(store2.request_row(mapped.request_id)["subject_id"], "customer-42")
            self.assertEqual(
                store2.request_row(mapped.request_id)["subject_scope"],
                SubjectScope.MAPPED.value,
            )
        finally:
            store2.close()

    async def test_local_running_is_interrupted_not_resumed(self) -> None:
        """进程在收尾前消失：旧运行记失败，不续跑（Task §7.1）。"""
        store1 = SqliteStore(self.path, owner_id="p1")
        adapter = DurableRunAdapter(store1, owner_id="p1")
        request = queued_request(self.pack.agent_version.version_id)
        request.state = RequestState.RUNNING
        run = adapter.begin(request, agent_version=self.pack.agent_version.version_id).run
        adapter.persist(
            RunEvent(
                seq=store1.next_seq(run.run_id), event_type="run.started",
                request_id=request.request_id, run_id=run.run_id,
                tenant_id=request.tenant_id,
                agent_version=self.pack.agent_version.version_id, channel="text",
            ).seal(""),
        )
        store1.close()  # 等价于进程退出：没有 finish

        store2 = SqliteStore(self.path, owner_id="p2")
        try:
            svc = ExecutionService(self.pack, store=store2, owner_id="p2")
            self.assertEqual(svc.recovery.interrupted, [run.run_id])
            row = store2.run_row(run.run_id)
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["finish_reason"], "restart_interrupted")
            self.assertEqual(store2.request_row(request.request_id)["state"], RequestState.FAILED.value)
            self.assertEqual(store2.load_events(run.run_id)[-1].event_type, "run.interrupted")
            self.assertTrue(store2.verify_chain())
        finally:
            store2.close()

    async def test_waiting_confirmation_remains_discoverable_without_reviving_old_run(self) -> None:
        store1 = SqliteStore(self.path, owner_id="p1")
        adapter1 = DurableRunAdapter(store1, owner_id="p1")
        request = queued_request(self.pack.agent_version.version_id)
        run = adapter1.begin(request, agent_version=self.pack.agent_version.version_id).run
        store1.set_request_state(request.request_id, RequestState.WAITING_CONFIRM.value)
        store1.close()

        store2 = SqliteStore(self.path, owner_id="p2")
        try:
            store2.recover(owner_id="p2")
            recovered = store2.request_row(request.request_id)
            self.assertEqual(recovered["state"], RequestState.WAITING_CONFIRM.value)
            self.assertEqual(recovered["latest_run_id"], run.run_id)
            self.assertEqual(recovered["latest_run_status"], "failed")
            self.assertEqual(
                [item["request_id"] for item in store2.recoverable_requests(tenant_id="tenant_demo")],
                [request.request_id],
            )
            event_count = len(store2.load_events(run.run_id))
            store2.recover(owner_id="p2")
            self.assertEqual(len(store2.load_events(run.run_id)), event_count)
            self.assertFalse(store2.is_running(run.run_id))
        finally:
            store2.close()

    async def test_cancelled_request_state_does_not_reenter_recovery_list(self) -> None:
        store1 = SqliteStore(self.path, owner_id="p1")
        adapter1 = DurableRunAdapter(store1, owner_id="p1")
        request = queued_request(self.pack.agent_version.version_id)
        adapter1.begin(request, agent_version=self.pack.agent_version.version_id)
        store1.set_request_state(request.request_id, RequestState.CANCELLED.value)
        store1.close()

        store2 = SqliteStore(self.path, owner_id="p2")
        try:
            store2.recover(owner_id="p2")
            self.assertEqual(store2.request_row(request.request_id)["state"], RequestState.CANCELLED.value)
            self.assertNotIn(
                request.request_id,
                [item["request_id"] for item in store2.recoverable_requests(tenant_id="tenant_demo")],
            )
        finally:
            store2.close()

    async def test_old_run_rejects_late_write(self) -> None:
        store1 = SqliteStore(self.path, owner_id="p1")
        adapter = DurableRunAdapter(store1, owner_id="p1")
        request = queued_request(self.pack.agent_version.version_id)
        run = adapter.begin(request, agent_version=self.pack.agent_version.version_id).run
        store1.close()

        store2 = SqliteStore(self.path, owner_id="p2")
        try:
            store2.recover(owner_id="p2")
            late = RunEvent(
                seq=store2.next_seq(run.run_id), event_type="tool.outcome",
                request_id=request.request_id, run_id=run.run_id,
                tenant_id="tenant_demo", agent_version=run.agent_version, channel="text",
            ).seal(store2.last_event(run.run_id).hash)
            with self.assertRaises(RuntimeError):
                store2.commit_write(
                    run.run_id, key=action_key("create_booking", "k-late"),
                    bare_key="k-late", action="create_booking",
                    result_id="res_late", event=late,
                )
        finally:
            store2.close()

    async def test_old_run_rejects_late_finish_after_recovery(self) -> None:
        store1 = SqliteStore(self.path, owner_id="p1")
        adapter = DurableRunAdapter(store1, owner_id="p1")
        request = queued_request(self.pack.agent_version.version_id)
        request.state = RequestState.RUNNING
        run = adapter.begin(request, agent_version=self.pack.agent_version.version_id).run
        adapter.persist(
            RunEvent(
                seq=store1.next_seq(run.run_id), event_type="run.started",
                request_id=request.request_id, run_id=run.run_id,
                tenant_id=request.tenant_id,
                agent_version=run.agent_version, channel="text",
            ).seal(""),
        )

        store2 = SqliteStore(self.path, owner_id="p2")
        try:
            store2.recover(owner_id="p2")
            events_before = store2.load_events(run.run_id)
            with self.assertRaises(RuntimeError):
                adapter.finish(run, request_state=RequestState.SUCCESS.value)

            self.assertEqual(store2.run_row(run.run_id)["status"], "failed")
            self.assertEqual(store2.run_row(run.run_id)["finish_reason"], "restart_interrupted")
            self.assertEqual(
                store2.request_row(request.request_id)["state"], RequestState.FAILED.value,
            )
            self.assertEqual(store2.load_events(run.run_id), events_before)
            self.assertTrue(store2.verify_chain(run.run_id))
        finally:
            store1.close()
            store2.close()

    async def test_recovery_does_not_append_interruption_after_finish_wins(self) -> None:
        store1 = SqliteStore(self.path, owner_id="p1")
        adapter = DurableRunAdapter(store1, owner_id="p1")
        request = queued_request(self.pack.agent_version.version_id)
        request.state = RequestState.RUNNING
        run = adapter.begin(request, agent_version=self.pack.agent_version.version_id).run
        adapter.persist(
            RunEvent(
                seq=store1.next_seq(run.run_id), event_type="run.started",
                request_id=request.request_id, run_id=run.run_id,
                tenant_id=request.tenant_id,
                agent_version=run.agent_version, channel="text",
            ).seal(""),
        )

        store2 = SqliteStore(self.path, owner_id="p2")
        transaction_entered = threading.Event()
        continue_recovery = threading.Event()
        original_tx = store2._tx

        @contextmanager
        def gated_tx():
            transaction_entered.set()
            if not continue_recovery.wait(5):
                raise TimeoutError("recovery transaction was not released")
            with original_tx() as cur:
                yield cur

        store2._tx = gated_tx
        recovery_task = asyncio.create_task(asyncio.to_thread(store2.recover, owner_id="p2"))
        try:
            self.assertTrue(await asyncio.to_thread(transaction_entered.wait, 5))
            adapter.finish(run, request_state=RequestState.SUCCESS.value)
        finally:
            continue_recovery.set()

        try:
            report = await recovery_task
            self.assertEqual(report.interrupted, [])
            self.assertEqual(store2.run_row(run.run_id)["status"], "succeeded")
            self.assertEqual(
                store2.request_row(request.request_id)["state"], RequestState.SUCCESS.value,
            )
            self.assertEqual(
                [event.event_type for event in store2.load_events(run.run_id)],
                ["run.started", "run.finished"],
            )
            self.assertTrue(store2.verify_chain(run.run_id))
        finally:
            store1.close()
            store2.close()

    async def test_idempotent_key_survives_restart_across_channels(self) -> None:
        """重启后换渠道重试同一操作，仍复用原结果且不重复落副作用。"""
        svc1, store1 = self.service("p1")
        r1 = await svc1.handle_text(
            self.case.turns[0]["text"], script=self.case.script, ask_confirm=confirm_all,
        )
        result_id = r1.written_result_ids[0]
        store1.close()

        store2 = SqliteStore(self.path, owner_id="p2")
        try:
            svc2 = ExecutionService(self.pack, store=store2, owner_id="p2")
            self.assertEqual(svc2._writes.get("idem-c2"), result_id)  # noqa: SLF001
            r2 = await svc2.handle_utterance(
                self.case.turns[0]["text"], media_session_id="restart-voice",
                script=self.case.script, ask_confirm=confirm_all,
            )
            self.assertNotEqual(r2.run_id, r1.run_id)
            self.assertEqual(r2.request.channel, Channel.VOICE)
            # 同一幂等键不得产生第二次业务写入
            self.assertEqual(r2.write_count, 0, r2.written_result_ids)
            n = store2._conn.execute("SELECT COUNT(*) AS n FROM idempotency").fetchone()["n"]
            self.assertEqual(n, 1)
            persisted = store2._conn.execute(
                "SELECT result_id FROM idempotency WHERE key=?",
                (action_key("create_booking", "idem-c2"),),
            ).fetchone()
            self.assertEqual(persisted["result_id"], result_id)
            self.assertEqual(len(store2.pending_outbox()), 1)
            self.assertTrue(store2.verify_chain())
        finally:
            store2.close()

    async def test_new_attempt_keeps_lineage_and_own_chain(self) -> None:
        """新尝试是新 Run：有自己的事件链，且指向旧运行，不是复活。"""
        store = SqliteStore(self.path, owner_id="p1")
        adapter = DurableRunAdapter(store, owner_id="p1")
        request = queued_request(self.pack.agent_version.version_id)
        first = adapter.begin(request, agent_version=self.pack.agent_version.version_id).run
        store.recover(owner_id="p2")  # 另一个进程接手：第一条被判中断
        adapter2 = DurableRunAdapter(store, owner_id="p2")
        second = adapter2.begin(
            request, agent_version=self.pack.agent_version.version_id,
            lineage_parent=first.run_id, generation=first.occupancy_generation + 1,
        ).run
        try:
            self.assertNotEqual(second.run_id, first.run_id)
            self.assertEqual(second.lineage_parent, first.run_id)
            self.assertEqual(second.occupancy_generation, 2)
            self.assertEqual(store.next_seq(second.run_id), 0, "新尝试必须从自己的 seq 0 开始")
            self.assertFalse(store.is_running(first.run_id), "旧运行不得被复活")
            self.assertTrue(store.is_running(second.run_id))
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
