# -*- coding: utf-8 -*-
"""事件接纳的事务、并发、冲突与执行边界；全程本地脚本模型。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loomrise.cli import DEFAULT_CASES, DEFAULT_PACK
from loomrise.contracts import (
    Case, Channel, RequestState,
    ScenarioPack, ServiceRequest, SubjectScope, new_id,
)
from loomrise.durable_adapter import DurableRunAdapter
from loomrise.durable_store import SCHEMA_VERSION, SqliteStore
from loomrise.ledger import load_ledger
from loomrise.service import ExecutionService


def request(event_id="event-1", **changes):
    values = dict(
        request_id=new_id("req"), tenant_id="tenant_demo", agent_version="av_1",
        channel=Channel.TEXT, state=RequestState.QUEUED,
        trigger_event_id=event_id, trigger_ref="仅供审计的文本",
    )
    return ServiceRequest(**(values | changes))


class TestIdentity(unittest.TestCase):
    def test_identity_excludes_version_channel_and_request(self):
        first = request()
        expected = ("tenant_demo", "pack", "inbound_message", "event-1")
        self.assertEqual(first.event_identity("pack"), expected)
        self.assertEqual(request(agent_version="av_2", channel=Channel.VOICE).event_identity("pack"), expected)
        for changed in (
            replace(first, tenant_id="other"),
            replace(first, trigger_kind="another_source"),
            replace(first, trigger_event_id="another_event"),
        ):
            self.assertNotEqual(changed.event_identity("pack"), expected)
        self.assertNotEqual(first.event_identity("other-pack"), expected)

    def test_missing_id_is_not_inferred_and_invalid_id_is_rejected(self):
        self.assertIsNone(request(None).event_identity("pack"))
        for invalid in ("", " \t", 42):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                request(invalid).event_identity("pack")


class StoreBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "loomrise.db")
        self.store = SqliteStore(self.path, owner_id="p1")
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.store.close)
        self.adapter = DurableRunAdapter(self.store, owner_id="p1")

    def begin(self, req=None, *, adapter=None, text="你好", pack="pack", **kwargs):
        return (adapter or self.adapter).begin(
            req or request(), agent_version="av_1", scenario_pack_id=pack,
            input_text=text, **kwargs,
        )

    def counts(self):
        return tuple(self.store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in ("event_receipts", "requests", "runs", "events"))


class TestAdmission(StoreBase):
    def test_process_exit_after_commit_preserves_receipt(self):
        code = """
import os, sys
from loomrise.contracts import ServiceRequest, Channel, RequestState
from loomrise.durable_store import SqliteStore
from loomrise.durable_adapter import DurableRunAdapter
store = SqliteStore(sys.argv[1], owner_id='child')
req = ServiceRequest('req_child', 'tenant_demo', 'av_1', Channel.TEXT,
                     RequestState.QUEUED, trigger_event_id='event-1')
DurableRunAdapter(store, owner_id='child').begin(
    req, agent_version='av_1', scenario_pack_id='pack', input_text='你好')
os._exit(17)
"""
        child = subprocess.run([sys.executable, "-c", code, self.path], timeout=10,
                               capture_output=True, text=True,
                               cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.assertEqual(child.returncode, 17, child.stderr)
        result = self.begin()
        self.assertEqual(result.status, "duplicate")
        self.assertEqual(result.request.request_id, "req_child")
        self.assertEqual(result.run.owner_id, "child")
        self.assertEqual(self.counts(), (1, 1, 1, 1))
        self.assertTrue(self.store.verify_chain())

    def test_atomic_first_duplicate_and_conflict(self):
        first = self.begin()
        self.assertEqual(first.status, "created")
        self.assertEqual(self.counts(), (1, 1, 1, 1))
        self.assertEqual(self.store.load_events(first.run.run_id)[0].event_type, "run.started")
        for text, status in (("你好", "duplicate"), ("不同内容", "conflict")):
            result = self.begin(text=text)
            self.assertEqual(result.status, status)
            self.assertEqual(result.run.run_id, first.run.run_id)
            self.assertEqual(result.request.request_id, first.request.request_id)
            self.assertEqual(self.counts(), (1, 1, 1, 1))
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM event_admission_conflicts").fetchone()[0], 1)
        self.assertEqual(self.store.load_events(first.run.run_id)[0].payload["input"], "你好")
        self.assertTrue(self.store.verify_chain())

    def test_failed_commit_rolls_back_all_four_records(self):
        def fail():
            raise RuntimeError("提交前故障")
        self.store.before_commit = fail
        with self.assertRaises(RuntimeError):
            self.begin()
        self.store.before_commit = None
        self.assertEqual(self.counts(), (0, 0, 0, 0))
        self.assertEqual(self.begin().status, "created")

    def test_independent_connections_compete_for_one_receipt(self):
        other = SqliteStore(self.path, owner_id="p2")
        self.addCleanup(other.close)
        adapter2 = DurableRunAdapter(other, owner_id="p2")
        ready = threading.Barrier(2)

        def deliver(adapter):
            ready.wait(timeout=5)
            return self.begin(adapter=adapter)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(deliver, adapter) for adapter in (self.adapter, adapter2)]
            results = [f.result(timeout=10) for f in futures]
        self.assertCountEqual([r.status for r in results], ["created", "duplicate"])
        self.assertEqual(results[0].run.run_id, results[1].run.run_id)
        self.assertEqual(self.counts(), (1, 1, 1, 1))

    def test_scope_components_are_independent_and_no_id_has_no_receipt(self):
        self.begin()
        self.begin(request(tenant_id="other"), adapter=DurableRunAdapter(self.store, owner_id="p1", tenant_id="other"))
        self.begin(pack="other-pack")
        self.begin(request(trigger_kind="another_source"))
        self.begin(request("another_event"))
        self.assertEqual(self.counts(), (5, 5, 5, 5))
        first = self.begin(request(None))
        second = self.begin(request(None))
        self.assertEqual(first.status, "created")
        self.assertNotEqual(first.run.run_id, second.run.run_id)
        self.assertEqual(self.counts()[:3], (5, 7, 7))

    def test_same_request_new_events_are_new_runs(self):
        req = request()
        first = self.begin(req)
        second = self.begin(replace(req, trigger_event_id="event-2"), text="第二轮")
        self.assertNotEqual(first.run.run_id, second.run.run_id)
        self.assertEqual(self.counts(), (2, 1, 2, 2))

    def test_committed_but_unanswered_admission_survives_reopen(self):
        first = self.begin()
        reopened = SqliteStore(self.path, owner_id="p2")
        self.addCleanup(reopened.close)
        adapter = DurableRunAdapter(reopened, owner_id="p2")
        # 关闭/重开连接模拟响应丢失；没有 owner 接管、没有执行重试。
        duplicate = self.begin(adapter=adapter)
        self.assertEqual(duplicate.status, "duplicate")
        self.assertEqual(duplicate.run.run_id, first.run.run_id)
        self.assertEqual(duplicate.run.owner_id, "p1")
        self.assertEqual(str(duplicate.run.status), "running")
        adapter.recover()
        after_recovery = self.begin(adapter=adapter)
        self.assertEqual(after_recovery.status, "duplicate")
        self.assertEqual(after_recovery.run.run_id, first.run.run_id)
        self.assertEqual(str(after_recovery.run.status), "failed")
        self.assertEqual(self.counts()[:3], (1, 1, 1))
        self.assertTrue(self.store.verify_chain())


class TestExecution(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SqliteStore(os.path.join(self.tmp.name, "loomrise.db"), owner_id="p1")
        self.addCleanup(self.store.close)
        self.pack = ScenarioPack.load(str(DEFAULT_PACK))
        self.svc = ExecutionService(self.pack, store=self.store, owner_id="p1")
        self.case = Case.load(str(DEFAULT_CASES / "c2_booking_confirmed.json"))

    async def test_duplicate_and_conflict_never_reenter_execution(self):
        text = self.case.turns[0]["text"]
        first = await self.svc.handle_text(text, trigger_event_id="booking-1", script=self.case.script,
                                           ask_confirm=lambda calls: [True] * len(calls))
        self.assertEqual(first.write_count, 1)
        events = [e.to_dict() for e in self.store.load_events(first.run_id)]
        with patch("loomrise.service.build_model", side_effect=AssertionError("重复投递不得调用模型")), \
             patch("loomrise.service.ContextLedger", side_effect=AssertionError("重复投递不得加载上下文")), \
             patch("loomrise.service.Sandbox", side_effect=AssertionError("重复投递不得调用工具")):
            duplicate = await self.svc.handle_text(text, trigger_event_id="booking-1", request=request("unrelated"))
            self.assertEqual(duplicate.admission_status, "duplicate")
            self.assertEqual(duplicate.run_id, first.run_id)
            self.assertEqual(duplicate.request.request_id, first.request.request_id)
            self.assertEqual(duplicate.run_status, "succeeded")
            self.assertEqual(duplicate.write_count, 0)
            conflict = await self.svc.handle_text("另一项业务输入", trigger_event_id="booking-1")
            self.assertEqual(conflict.admission_status, "conflict")
            self.assertEqual(conflict.run_id, first.run_id)
            self.assertEqual(conflict.write_count, 0)
        self.assertEqual([e.to_dict() for e in self.store.load_events(first.run_id)], events)
        self.assertEqual(len(self.store.pending_outbox()), 1)
        self.assertTrue(self.store.verify_chain())

    async def test_version_and_channel_changes_return_first_frozen_run(self):
        first = await self.svc.handle_text("你好", trigger_event_id="message-1", script=[{"text": "你好"}])
        original_version = self.pack.agent_version.version_id
        self.pack.agent_version = replace(self.pack.agent_version, version_id="av_new")
        duplicate = await self.svc.handle_utterance("你好", media_session_id="new-media", trigger_event_id="message-1")
        self.assertEqual(duplicate.run_id, first.run_id)
        self.assertEqual(duplicate.request.agent_version, original_version)
        self.assertEqual(duplicate.request.channel, Channel.TEXT)
        self.assertEqual(len(self.store.load_events(first.run_id)), len(self.svc.ledger.events))

    async def test_followup_with_new_or_missing_event_id_is_not_swallowed(self):
        path = os.path.join(self.tmp.name, "events.jsonl")
        self.svc.ledger.path = path
        first = await self.svc.handle_text("你好", trigger_event_id="message-1", script=[{"text": "你好"}])
        second = await self.svc.handle_text("第二轮", request=first.request, trigger_event_id="message-2", script=[{"text": "继续"}])
        third = await self.svc.handle_text("没有事件凭据的第三轮", request=second.request, script=[{"text": "继续"}])
        self.assertEqual(len({first.run_id, second.run_id, third.run_id}), 3)
        self.assertEqual(first.request.request_id, second.request.request_id)
        self.assertEqual(second.request.request_id, third.request.request_id)
        self.assertEqual(third.admission_status, "created")
        third_start = self.store.load_events(third.run_id)[0]
        self.assertIs(third_start.payload["event_deduplication"], False)
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM event_receipts").fetchone()[0], 2)
        self.assertTrue(self.store.verify_chain())
        self.assertTrue(self.svc.ledger.verify())
        self.assertTrue(load_ledger(path).verify())
        fourth = await self.svc.handle_text("再次有事件 ID", request=third.request,
                                            trigger_event_id="message-4", script=[{"text": "继续"}])
        self.assertEqual(fourth.admission_status, "created")
        self.assertTrue(self.svc.ledger.verify())
        self.assertTrue(load_ledger(path).verify())
        self.assertTrue(self.store.verify_chain())

    async def test_claiming_event_dedup_without_store_fails_closed(self):
        svc = ExecutionService(self.pack)
        with self.assertRaises(ValueError):
            await svc.handle_text("你好", trigger_event_id="message-1", script=[{"text": "你好"}])
        self.assertEqual(svc.ledger.events, [])

    async def test_inflight_duplicate_does_not_execute_or_take_ownership(self):
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def delayed_reply(*args, **kwargs):
            calls.append("reply")
            started.set()
            await release.wait()
            if False:
                yield None

        with patch("loomrise.service.drive_reply", delayed_reply):
            running = asyncio.create_task(self.svc.handle_text("你好", trigger_event_id="pending", script=[{"text": "你好"}]))
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                duplicate = await self.svc.handle_text("你好", trigger_event_id="pending")
                self.assertEqual(duplicate.admission_status, "duplicate")
                self.assertEqual(duplicate.run_status, "running")
                self.assertEqual(self.store.run_row(duplicate.run_id)["owner_id"], "p1")
                self.assertEqual(calls, ["reply"])
                self.assertEqual(len(self.svc.ledger.find("run.started")), 1)
            finally:
                release.set()
                first = await asyncio.wait_for(running, timeout=5)
        self.assertEqual(first.run_id, duplicate.run_id)
        self.assertTrue(self.store.verify_chain())

    async def test_subject_change_is_a_payload_conflict(self):
        req = request(subject_id="subject-1", subject_scope=SubjectScope.MAPPED)
        first = await self.svc.handle_text("你好", request=req, trigger_event_id="same", script=[{"text": "你好"}])
        changed = replace(req, subject_id="subject-2")
        result = await self.svc.handle_text("你好", request=changed, trigger_event_id="same")
        self.assertEqual(result.admission_status, "conflict")
        self.assertEqual(result.run_id, first.run_id)


class TestMigration(unittest.TestCase):
    def test_v1_request_survives_additive_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "v1.db")
            with sqlite3.connect(path) as old:
                old.executescript("""
                    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    INSERT INTO meta VALUES ('schema_version', '1');
                    CREATE TABLE requests (
                        request_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                        agent_version TEXT NOT NULL, channel TEXT NOT NULL,
                        state TEXT NOT NULL, subject_id TEXT, subject_scope TEXT,
                        trigger_kind TEXT, trigger_ref TEXT, result_id TEXT,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    INSERT INTO requests VALUES (
                        'req_old', 'tenant_demo', 'av_old', 'text', 'success',
                        NULL, 'ephemeral', 'inbound_message', '旧输入', 'res_old',
                        '2026-10-23T00:00:00+00:00', '2026-10-23T00:00:01+00:00'
                    );
                """)
                before = old.execute("SELECT * FROM requests").fetchone()
            store = SqliteStore(path)
            try:
                after = tuple(store._conn.execute("SELECT * FROM requests").fetchone())
                self.assertEqual(after[:-1], before)
                self.assertIsNone(after[-1])
                self.assertEqual(int(store._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]), SCHEMA_VERSION)
                store.migrate()
                self.assertEqual(tuple(store._conn.execute("SELECT * FROM requests").fetchone()), after)
                adapter = DurableRunAdapter(store, owner_id="p1")
                accepted = adapter.begin(request(), agent_version="av_1", scenario_pack_id="pack", input_text="你好")
                self.assertEqual(accepted.status, "created")
                self.assertTrue(store.verify_chain())
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
