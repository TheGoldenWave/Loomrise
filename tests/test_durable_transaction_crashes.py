# -*- coding: utf-8 -*-
"""Hard process exits at durable transaction write points."""

from __future__ import annotations

from contextlib import closing
import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loomrise.contracts import Channel, RequestState, Run, RunEvent, ServiceRequest
from loomrise.durable_adapter import DurableRunAdapter, action_key
from loomrise.durable_store import SCHEMA_VERSION, SqliteStore


_CRASH_CODE = 29
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONNECT_PATCH = """
import os, sqlite3, sys
real_connect = sqlite3.connect
def connect_with_crashpoint(*args, **kwargs):
    connection = real_connect(*args, **kwargs)
    connection.create_function('crash_after_write', 0, lambda: os._exit(29))
    return connection
sqlite3.connect = connect_with_crashpoint
"""


def _request(request_id: str = "req-matrix", *, state: RequestState = RequestState.RUNNING) -> ServiceRequest:
    return ServiceRequest(
        request_id=request_id, tenant_id="tenant_demo", agent_version="av_test",
        channel=Channel.TEXT, state=state,
    )


def _run(request_id: str = "req-matrix", run_id: str = "run-matrix", *, owner: str = "p1") -> Run:
    return Run(
        run_id=run_id, request_id=request_id, tenant_id="tenant_demo",
        agent_version="av_test", owner_id=owner, occupancy_generation=1,
    )


def _event(
    event_type: str, *, seq: int, request_id: str = "req-matrix", run_id: str = "run-matrix",
) -> RunEvent:
    return RunEvent(
        seq=seq, event_type=event_type, request_id=request_id, run_id=run_id,
        tenant_id="tenant_demo", agent_version="av_test", channel="text", payload={},
    )


def _seed_run(path: str, *, with_start_event: bool = True) -> None:
    store = SqliteStore(path, owner_id="p1")
    try:
        events = [_event("run.started", seq=0)] if with_start_event else []
        if events:
            events[0].seal("")
        store.begin_run(_request(), _run(), events)
    finally:
        store.close()


def _install_trigger(path: str, name: str, table: str, operation: str, condition: str) -> None:
    allowed = {
        "requests", "runs", "events", "event_receipts", "outbox",
        "event_admission_conflicts", "meta", "configuration_stable_versions",
        "configuration_drafts", "change_proposals", "task_items",
    }
    if table not in allowed or operation not in {"INSERT", "UPDATE"}:
        raise ValueError("unsupported crash point")
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            f"CREATE TRIGGER {name} AFTER {operation} ON {table} "
            f"WHEN {condition} BEGIN SELECT crash_after_write(); END",
        )


def _drop_trigger(path: str, name: str) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f"DROP TRIGGER {name}")


def _run_crashing_child(path: str, code: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _CONNECT_PATCH + code, path, *args],
        timeout=15, capture_output=True, text=True, cwd=_ROOT,
    )
    if result.returncode != _CRASH_CODE:
        raise AssertionError(f"child exit={result.returncode}, stderr={result.stderr}")


class DurableTransactionCrashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "loomrise.db")
        SqliteStore(self.path).close()

    def _counts(self, store: SqliteStore, tables: tuple[str, ...]) -> tuple[int, ...]:
        return tuple(
            store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        )

    def test_task_item_cancel_crash_rolls_back_and_can_be_retried(self) -> None:
        store = SqliteStore(self.path)
        store.create_task_item(
            task_id="task-matrix", tenant_id="tenant_demo", agent_id="agent-demo",
            subject_id="subject-demo", service_cycle_id="cycle-1",
            purpose="follow_up", source_agent_version="av_test",
        )
        store.close()
        trigger = "crash_task_item_cancel"
        _install_trigger(
            self.path, trigger, "task_items", "UPDATE", "NEW.state='cancelled'",
        )
        _run_crashing_child(self.path, """
from loomrise.durable_store import SqliteStore
store = SqliteStore(sys.argv[1], owner_id='p1')
store.cancel_task_item('task-matrix')
""")
        recovered = SqliteStore(self.path)
        try:
            task = recovered.task_item("task-matrix")
            self.assertEqual((task["state"], task["revision"]), ("scheduled", 1))
        finally:
            recovered.close()
        _drop_trigger(self.path, trigger)

        replay = SqliteStore(self.path)
        try:
            task = replay.cancel_task_item("task-matrix")
            self.assertEqual((task["state"], task["revision"]), ("cancelled", 2))
            replay.recover(owner_id="p2")
            self.assertEqual(replay.recoverable_task_items(), [])
        finally:
            replay.close()

    def test_task_item_create_crash_rolls_back_and_can_be_retried(self) -> None:
        trigger = "crash_task_item_create"
        _install_trigger(
            self.path, trigger, "task_items", "INSERT", "NEW.task_id='task-matrix'",
        )
        _run_crashing_child(self.path, """
from loomrise.durable_store import SqliteStore
store = SqliteStore(sys.argv[1], owner_id='p1')
store.create_task_item(
    task_id='task-matrix', tenant_id='tenant_demo', agent_id='agent-demo',
    subject_id='subject-demo', service_cycle_id='cycle-1',
    purpose='follow_up', source_agent_version='av_test',
)
""")

        recovered = SqliteStore(self.path)
        try:
            self.assertIsNone(recovered.task_item("task-matrix"))
        finally:
            recovered.close()

        _drop_trigger(self.path, trigger)
        replay = SqliteStore(self.path)
        try:
            created = replay.create_task_item(
                task_id="task-matrix", tenant_id="tenant_demo", agent_id="agent-demo",
                subject_id="subject-demo", service_cycle_id="cycle-1",
                purpose="follow_up", source_agent_version="av_test",
            )
            self.assertEqual((created["state"], created["revision"]), ("scheduled", 1))
            self.assertEqual(replay.recoverable_task_items(), [created])
        finally:
            replay.close()

    def test_begin_run_crashes_at_each_insert_and_can_be_replayed(self) -> None:
        points = (
            ("requests", "NEW.request_id='req-matrix'"),
            ("runs", "NEW.run_id='run-matrix'"),
            ("events", "NEW.event_type='run.started'"),
        )
        for index, (table, condition) in enumerate(points):
            with self.subTest(table=table):
                path = os.path.join(self.tmp.name, f"begin-{index}.db")
                SqliteStore(path).close()
                trigger = f"crash_begin_{index}"
                _install_trigger(path, trigger, table, "INSERT", condition)
                _run_crashing_child(path, """
from loomrise.contracts import Channel, RequestState, Run, RunEvent, ServiceRequest
from loomrise.durable_store import SqliteStore
store = SqliteStore(sys.argv[1], owner_id='p1')
request = ServiceRequest('req-matrix', 'tenant_demo', 'av_test', Channel.TEXT, RequestState.RUNNING)
run = Run('run-matrix', request.request_id, request.tenant_id, request.agent_version,
          owner_id='p1', occupancy_generation=1)
event = RunEvent(seq=0, event_type='run.started', request_id=request.request_id,
                 run_id=run.run_id, tenant_id=request.tenant_id,
                 agent_version=request.agent_version, channel='text', payload={}).seal('')
store.begin_run(request, run, [event])
""")
                store = SqliteStore(path, owner_id="p2")
                try:
                    self.assertEqual(self._counts(store, ("requests", "runs", "events")), (0, 0, 0))
                finally:
                    store.close()
                _drop_trigger(path, trigger)
                replay = SqliteStore(path, owner_id="p2")
                try:
                    event = _event("run.started", seq=0).seal("")
                    replay.begin_run(_request(), _run(), [event])
                    self.assertEqual(self._counts(replay, ("requests", "runs", "events")), (1, 1, 1))
                    self.assertTrue(replay.verify_chain())
                finally:
                    replay.close()

    def test_event_admission_crashes_at_each_record_and_replays_once(self) -> None:
        points = (
            ("requests", "INSERT", "NEW.request_id='req-matrix'"),
            ("runs", "INSERT", "1"),
            ("events", "INSERT", "NEW.event_type='run.started'"),
            ("event_receipts", "INSERT", "NEW.trigger_event_id='event-matrix'"),
        )
        for index, (table, operation, condition) in enumerate(points):
            with self.subTest(table=table):
                path = os.path.join(self.tmp.name, f"admission-{index}.db")
                SqliteStore(path).close()
                trigger = f"crash_admission_{index}"
                _install_trigger(path, trigger, table, operation, condition)
                _run_crashing_child(path, """
from loomrise.contracts import Channel, RequestState, ServiceRequest
from loomrise.durable_adapter import DurableRunAdapter
from loomrise.durable_store import SqliteStore
store = SqliteStore(sys.argv[1], owner_id='p1')
request = ServiceRequest('req-matrix', 'tenant_demo', 'av_test', Channel.TEXT,
                         RequestState.QUEUED, trigger_event_id='event-matrix')
DurableRunAdapter(store, owner_id='p1').begin(
    request, agent_version='av_test', scenario_pack_id='pack', input_text='hello')
""")
                store = SqliteStore(path, owner_id="p2")
                try:
                    self.assertEqual(
                        self._counts(store, ("event_receipts", "requests", "runs", "events")),
                        (0, 0, 0, 0),
                    )
                finally:
                    store.close()
                _drop_trigger(path, trigger)
                replay = SqliteStore(path, owner_id="p2")
                try:
                    request = ServiceRequest(
                        "req-matrix", "tenant_demo", "av_test", Channel.TEXT,
                        RequestState.QUEUED, trigger_event_id="event-matrix",
                    )
                    result = DurableRunAdapter(replay, owner_id="p2").begin(
                        request, agent_version="av_test", scenario_pack_id="pack",
                        input_text="hello",
                    )
                    self.assertEqual(result.status, "created")
                    self.assertEqual(
                        self._counts(replay, ("event_receipts", "requests", "runs", "events")),
                        (1, 1, 1, 1),
                    )
                    self.assertTrue(replay.verify_chain())
                finally:
                    replay.close()

    def test_event_admission_conflict_crash_rolls_back_diagnostic_and_can_be_retried(self) -> None:
        path = os.path.join(self.tmp.name, "admission-conflict.db")
        store = SqliteStore(path, owner_id="p1")
        try:
            request = ServiceRequest(
                "req-original", "tenant_demo", "av_test", Channel.TEXT,
                RequestState.QUEUED, trigger_event_id="event-matrix",
            )
            result = DurableRunAdapter(store, owner_id="p1").begin(
                request, agent_version="av_test", scenario_pack_id="pack", input_text="hello",
            )
            self.assertEqual(result.status, "created")
        finally:
            store.close()

        trigger = "crash_admission_conflict"
        _install_trigger(
            path, trigger, "event_admission_conflicts", "INSERT", "1",
        )
        _run_crashing_child(path, """
from loomrise.contracts import Channel, RequestState, ServiceRequest
from loomrise.durable_adapter import DurableRunAdapter
from loomrise.durable_store import SqliteStore
store = SqliteStore(sys.argv[1], owner_id='p2')
request = ServiceRequest(
    'req-conflicting', 'tenant_demo', 'av_test', Channel.TEXT,
    RequestState.QUEUED, trigger_event_id='event-matrix',
)
DurableRunAdapter(store, owner_id='p2').begin(
    request, agent_version='av_test', scenario_pack_id='pack', input_text='different',
)
""")
        replay = SqliteStore(path, owner_id="p2")
        try:
            self.assertEqual(self._counts(
                replay, ("event_admission_conflicts", "event_receipts", "requests", "runs", "events"),
            ), (0, 1, 1, 1, 1))
        finally:
            replay.close()

        _drop_trigger(path, trigger)
        replay = SqliteStore(path, owner_id="p2")
        try:
            request = ServiceRequest(
                "req-conflicting", "tenant_demo", "av_test", Channel.TEXT,
                RequestState.QUEUED, trigger_event_id="event-matrix",
            )
            result = DurableRunAdapter(replay, owner_id="p2").begin(
                request, agent_version="av_test", scenario_pack_id="pack", input_text="different",
            )
            self.assertEqual(result.status, "conflict")
            self.assertEqual(self._counts(
                replay, ("event_admission_conflicts", "event_receipts", "requests", "runs", "events"),
            ), (1, 1, 1, 1, 1))
        finally:
            replay.close()

    def test_event_batch_crash_rolls_back_all_events_and_can_be_replayed(self) -> None:
        path = os.path.join(self.tmp.name, "append-events.db")
        _seed_run(path, with_start_event=False)
        trigger = "crash_event_batch"
        _install_trigger(path, trigger, "events", "INSERT", "NEW.seq=1")
        _run_crashing_child(path, """
from loomrise.contracts import RunEvent
from loomrise.durable_store import SqliteStore
store = SqliteStore(sys.argv[1], owner_id='p1')
first = RunEvent(seq=0, event_type='run.started', request_id='req-matrix',
                 run_id='run-matrix', tenant_id='tenant_demo', agent_version='av_test',
                 channel='text', payload={}).seal('')
second = RunEvent(seq=1, event_type='request.routed', request_id='req-matrix',
                  run_id='run-matrix', tenant_id='tenant_demo', agent_version='av_test',
                  channel='text', payload={}).seal(first.hash)
store.append_events([first, second])
""")
        store = SqliteStore(path, owner_id="p2")
        try:
            self.assertEqual(store.load_events("run-matrix"), [])
        finally:
            store.close()
        _drop_trigger(path, trigger)
        replay = SqliteStore(path, owner_id="p2")
        try:
            first = _event("run.started", seq=0).seal("")
            second = _event("request.routed", seq=1).seal(first.hash)
            replay.append_events([first, second])
            self.assertEqual(
                [event.event_type for event in replay.load_events("run-matrix")],
                ["run.started", "request.routed"],
            )
            self.assertTrue(replay.verify_chain())
        finally:
            replay.close()

    def test_finish_run_crashes_at_each_update_and_can_be_replayed(self) -> None:
        points = (
            ("runs", "UPDATE", "NEW.status='succeeded'"),
            ("requests", "UPDATE", "NEW.state='success'"),
            ("events", "INSERT", "NEW.event_type='run.finished'"),
        )
        for index, (table, operation, condition) in enumerate(points):
            with self.subTest(table=table):
                path = os.path.join(self.tmp.name, f"finish-{index}.db")
                _seed_run(path)
                trigger = f"crash_finish_{index}"
                _install_trigger(path, trigger, table, operation, condition)
                _run_crashing_child(path, """
from loomrise.durable_store import SqliteStore
from loomrise.contracts import RunEvent
store = SqliteStore(sys.argv[1], owner_id='p1')
event = RunEvent(seq=1, event_type='run.finished', request_id='req-matrix',
                 run_id='run-matrix', tenant_id='tenant_demo', agent_version='av_test',
                 channel='text', payload={'request_state': 'success'}).seal('')
store.finish_run('run-matrix', status='succeeded', request_state='success', event=event)
""")
                store = SqliteStore(path, owner_id="p2")
                try:
                    self.assertEqual(store.run_row("run-matrix")["status"], "running")
                    self.assertEqual(store.request_row("req-matrix")["state"], "running")
                    self.assertEqual(len(store.load_events("run-matrix")), 1)
                finally:
                    store.close()
                _drop_trigger(path, trigger)
                replay = SqliteStore(path, owner_id="p2")
                try:
                    event = _event("run.finished", seq=1)
                    event.payload["request_state"] = "success"
                    replay.finish_run(
                        "run-matrix", status="succeeded", request_state="success", event=event,
                    )
                    self.assertEqual(replay.run_row("run-matrix")["status"], "succeeded")
                    self.assertEqual(replay.request_row("req-matrix")["state"], "success")
                    self.assertEqual(len(replay.load_events("run-matrix")), 2)
                    self.assertTrue(replay.verify_chain())
                finally:
                    replay.close()

    def test_recovery_crashes_at_each_write_and_is_retryable(self) -> None:
        points = (
            ("runs", "UPDATE", "NEW.status='failed'"),
            ("requests", "UPDATE", "NEW.state='failed'"),
            ("events", "INSERT", "NEW.event_type='run.interrupted'"),
        )
        for index, (table, operation, condition) in enumerate(points):
            with self.subTest(table=table):
                path = os.path.join(self.tmp.name, f"recover-{index}.db")
                _seed_run(path)
                trigger = f"crash_recover_{index}"
                _install_trigger(path, trigger, table, operation, condition)
                _run_crashing_child(path, """
from loomrise.durable_store import SqliteStore
store = SqliteStore(sys.argv[1], owner_id='p2')
store.recover(owner_id='p2')
""")
                store = SqliteStore(path, owner_id="p2")
                try:
                    self.assertEqual(store.run_row("run-matrix")["status"], "running")
                    self.assertEqual(store.request_row("req-matrix")["state"], "running")
                    self.assertEqual(len(store.load_events("run-matrix")), 1)
                finally:
                    store.close()
                _drop_trigger(path, trigger)
                replay = SqliteStore(path, owner_id="p2")
                try:
                    report = replay.recover(owner_id="p2")
                    self.assertEqual(report.interrupted, ["run-matrix"])
                    self.assertEqual(replay.run_row("run-matrix")["status"], "failed")
                    self.assertEqual(replay.request_row("req-matrix")["state"], "failed")
                    self.assertEqual(
                        [event.event_type for event in replay.load_events("run-matrix")],
                        ["run.started", "run.interrupted"],
                    )
                    self.assertTrue(replay.verify_chain())
                finally:
                    replay.close()

    def test_set_request_state_crash_rolls_back_and_can_be_retried(self) -> None:
        path = os.path.join(self.tmp.name, "request-state.db")
        _seed_run(path)
        trigger = "crash_request_state"
        _install_trigger(
            path, trigger, "requests", "UPDATE",
            "NEW.request_id='req-matrix' AND NEW.state='cancelled'",
        )
        _run_crashing_child(path, """
from loomrise.durable_store import SqliteStore
store = SqliteStore(sys.argv[1], owner_id='p1')
store.set_request_state('req-matrix', 'cancelled')
""")

        store = SqliteStore(path, owner_id="p2")
        try:
            self.assertEqual(store.request_row("req-matrix")["state"], "running")
            self.assertEqual(store.run_row("run-matrix")["status"], "running")
        finally:
            store.close()

        _drop_trigger(path, trigger)
        replay = SqliteStore(path, owner_id="p2")
        try:
            replay.set_request_state("req-matrix", "cancelled")
            replay.recover(owner_id="p2")
            self.assertEqual(replay.request_row("req-matrix")["state"], "cancelled")
            self.assertNotIn(
                "req-matrix",
                [item["request_id"] for item in replay.recoverable_requests(
                    tenant_id="tenant_demo",
                )],
            )
            self.assertTrue(replay.verify_chain())
        finally:
            replay.close()

    def test_outbox_attempt_and_ack_crashes_leave_retryable_state(self) -> None:
        points = (
            ("attempt", "UPDATE", "NEW.attempts=OLD.attempts+1"),
            ("ack", "UPDATE", "NEW.state='delivered'"),
        )
        for index, (stage, operation, condition) in enumerate(points):
            with self.subTest(stage=stage):
                path = os.path.join(self.tmp.name, f"outbox-{index}.db")
                _seed_run(path)
                store = SqliteStore(path, owner_id="p1")
                try:
                    event = _event("tool.outcome", seq=1)
                    created, _ = store.commit_write(
                        "run-matrix", key=action_key("create_booking", "key-1"),
                        bare_key="key-1", action="create_booking", result_id="result-1",
                        event=event,
                    )
                    self.assertTrue(created)
                    record_id = store.pending_outbox()[0]["id"]
                finally:
                    store.close()

                trigger = f"crash_outbox_{index}"
                _install_trigger(path, trigger, "outbox", operation, condition)
                child_action = "store.note_outbox_attempt(sys.argv[2])" if stage == "attempt" else "store.mark_outbox(sys.argv[2])"
                _run_crashing_child(path, f"""
from loomrise.durable_store import SqliteStore
store = SqliteStore(sys.argv[1], owner_id='p2')
{child_action}
""", record_id)
                current = SqliteStore(path, owner_id="p2")
                try:
                    rows = current._conn.execute(
                        "SELECT state,attempts FROM outbox WHERE id=?", (record_id,),
                    ).fetchone()
                    self.assertEqual((rows["state"], rows["attempts"]), ("pending", 0))
                finally:
                    current.close()
                _drop_trigger(path, trigger)
                replay = SqliteStore(path, owner_id="p2")
                try:
                    if stage == "attempt":
                        self.assertTrue(replay.note_outbox_attempt(record_id))
                        expected = ("pending", 1)
                    else:
                        replay.mark_outbox(record_id)
                        expected = ("delivered", 0)
                    rows = replay._conn.execute(
                        "SELECT state,attempts FROM outbox WHERE id=?", (record_id,),
                    ).fetchone()
                    self.assertEqual((rows["state"], rows["attempts"]), expected)
                finally:
                    replay.close()

    def test_register_stable_config_crash_rolls_back_and_can_be_retried(self) -> None:
        path = os.path.join(self.tmp.name, "stable-config.db")
        SqliteStore(path).close()
        config = {"persona": {"goal": "稳定目标"}}
        digest = hashlib.sha256(SqliteStore._config_json(config).encode("utf-8")).hexdigest()
        trigger = "crash_stable_config"
        _install_trigger(
            path, trigger, "configuration_stable_versions", "INSERT",
            "NEW.version_id='v1'",
        )
        _run_crashing_child(path, """
from loomrise.durable_store import SqliteStore
store = SqliteStore(sys.argv[1], owner_id='p1')
store.register_stable_config(
    tenant_id='tenant-a', agent_id='expert-a', version_id='v1',
    config={'persona': {'goal': '稳定目标'}}, content_hash=sys.argv[2],
)
""", digest)

        store = SqliteStore(path, owner_id="p2")
        try:
            self.assertIsNone(store.get_stable_config(
                tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
            ))
        finally:
            store.close()

        _drop_trigger(path, trigger)
        replay = SqliteStore(path, owner_id="p2")
        try:
            stable = replay.register_stable_config(
                tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
                config=config, content_hash=digest,
            )
            self.assertEqual(stable["config"], config)
            self.assertEqual(
                replay.register_stable_config(
                    tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
                    config=config, content_hash=digest,
                ),
                stable,
            )
        finally:
            replay.close()

    def test_create_config_draft_crash_rolls_back_and_can_be_retried(self) -> None:
        path = os.path.join(self.tmp.name, "config-draft-create.db")
        store = SqliteStore(path, owner_id="p1")
        try:
            store.register_stable_config(
                tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
                config={"persona": {"goal": "稳定目标"}}, content_hash="stable-hash",
            )
        finally:
            store.close()
        config = {"persona": {"goal": "草稿目标"}}
        trigger = "crash_config_draft_create"
        _install_trigger(
            path, trigger, "configuration_drafts", "INSERT",
            "NEW.agent_id='expert-a'",
        )
        _run_crashing_child(path, """
from loomrise.durable_store import SqliteStore
store = SqliteStore(sys.argv[1], owner_id='p1')
store.create_config_draft(
    tenant_id='tenant-a', agent_id='expert-a', base_version_id='v1',
    config={'persona': {'goal': '草稿目标'}},
)
""")

        store = SqliteStore(path, owner_id="p2")
        try:
            self.assertIsNone(store.get_config_draft(tenant_id="tenant-a", agent_id="expert-a"))
            self.assertIsNotNone(store.get_stable_config(
                tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
            ))
        finally:
            store.close()

        _drop_trigger(path, trigger)
        replay = SqliteStore(path, owner_id="p2")
        try:
            draft = replay.create_config_draft(
                tenant_id="tenant-a", agent_id="expert-a", base_version_id="v1",
                config=config,
            )
            self.assertEqual((draft["revision"], draft["config"]), (1, config))
        finally:
            replay.close()

    def test_save_config_draft_crash_preserves_revision_and_can_be_retried(self) -> None:
        path = os.path.join(self.tmp.name, "config-draft-save.db")
        store = SqliteStore(path, owner_id="p1")
        try:
            store.create_config_draft(
                tenant_id="tenant-a", agent_id="expert-a", base_version_id=None,
                config={"persona": {"goal": "旧目标"}},
            )
        finally:
            store.close()
        trigger = "crash_config_draft_save"
        _install_trigger(
            path, trigger, "configuration_drafts", "UPDATE",
            "NEW.agent_id='expert-a' AND NEW.revision=2",
        )
        _run_crashing_child(path, """
from loomrise.durable_store import SqliteStore
store = SqliteStore(sys.argv[1], owner_id='p1')
store.save_config_draft(
    tenant_id='tenant-a', agent_id='expert-a', expected_revision=1,
    config={'persona': {'goal': '新目标'}},
)
""")

        store = SqliteStore(path, owner_id="p2")
        try:
            draft = store.get_config_draft(tenant_id="tenant-a", agent_id="expert-a")
            self.assertEqual((draft["revision"], draft["config"]["persona"]["goal"]), (1, "旧目标"))
        finally:
            store.close()

        _drop_trigger(path, trigger)
        replay = SqliteStore(path, owner_id="p2")
        try:
            saved, conflict = replay.save_config_draft(
                tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
                config={"persona": {"goal": "新目标"}},
            )
            self.assertIsNone(conflict)
            self.assertEqual((saved["revision"], saved["config"]["persona"]["goal"]), (2, "新目标"))
        finally:
            replay.close()

    def test_freeze_config_candidate_crash_rolls_back_and_can_be_retried(self) -> None:
        path = os.path.join(self.tmp.name, "config-candidate-freeze.db")
        config = {"persona": {"goal": "冻结目标"}}
        encoded = SqliteStore._config_json(config)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        store = SqliteStore(path, owner_id="p1")
        try:
            store.create_config_draft(
                tenant_id="tenant-a", agent_id="expert-a", base_version_id=None,
                config=config,
            )
        finally:
            store.close()
        trigger = "crash_config_candidate_freeze"
        _install_trigger(
            path, trigger, "change_proposals", "INSERT",
            "NEW.candidate_id='candidate-1'",
        )
        _run_crashing_child(path, """
from loomrise.durable_store import SqliteStore
store = SqliteStore(sys.argv[1], owner_id='p1')
store.freeze_config_candidate(
    tenant_id='tenant-a', agent_id='expert-a', candidate_id='candidate-1',
    idempotency_key='freeze-v1-r1', expected_revision=1,
    content_hash=sys.argv[2], diff=[{'path': '$.persona.goal'}],
)
""", digest)

        store = SqliteStore(path, owner_id="p2")
        try:
            self.assertIsNone(store.get_config_candidate(
                tenant_id="tenant-a", agent_id="expert-a", candidate_id="candidate-1",
            ))
            self.assertEqual(store.get_config_draft(
                tenant_id="tenant-a", agent_id="expert-a",
            )["config"], config)
        finally:
            store.close()

        _drop_trigger(path, trigger)
        replay = SqliteStore(path, owner_id="p2")
        try:
            candidate, conflict = replay.freeze_config_candidate(
                tenant_id="tenant-a", agent_id="expert-a", candidate_id="candidate-1",
                idempotency_key="freeze-v1-r1", expected_revision=1,
                content_hash=digest, diff=[{"path": "$.persona.goal"}],
            )
            self.assertIsNone(conflict)
            self.assertEqual((candidate["status"], candidate["config"]), ("frozen", config))
            repeated, repeated_conflict = replay.freeze_config_candidate(
                tenant_id="tenant-a", agent_id="expert-a", candidate_id="candidate-2",
                idempotency_key="freeze-v1-r1", expected_revision=1,
                content_hash=digest, diff=[{"path": "$.persona.goal"}],
            )
            self.assertIsNone(repeated_conflict)
            self.assertEqual(repeated["candidate_id"], "candidate-1")
            self.assertEqual(len(replay.list_config_candidates(
                tenant_id="tenant-a", agent_id="expert-a",
            )), 1)
        finally:
            replay.close()

    def test_schema_migration_crash_rolls_back_and_can_be_retried(self) -> None:
        path = os.path.join(self.tmp.name, "schema-migration.db")
        store = SqliteStore(path, owner_id="p1")
        try:
            store.begin_run(_request(), _run(), [])
        finally:
            store.close()
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                "UPDATE requests SET subject_id='legacy-session',subject_scope='ephemeral' "
                "WHERE request_id='req-matrix'",
            )
            connection.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
            connection.commit()

        points = (
            ("legacy_subject", "requests", "NEW.request_id='req-matrix' AND NEW.subject_id IS NULL"),
            (
                "schema_version", "meta",
                f"NEW.key='schema_version' AND NEW.value='{SCHEMA_VERSION}'",
            ),
        )
        for stage, table, condition in points:
            trigger = f"crash_schema_migration_{stage}"
            _install_trigger(path, trigger, table, "UPDATE", condition)
            _run_crashing_child(path, """
from loomrise.durable_store import SqliteStore
SqliteStore(sys.argv[1], owner_id='p2')
""")

            with closing(sqlite3.connect(path)) as connection:
                version = connection.execute(
                    "SELECT value FROM meta WHERE key='schema_version'",
                ).fetchone()[0]
                subject_id = connection.execute(
                    "SELECT subject_id FROM requests WHERE request_id='req-matrix'",
                ).fetchone()[0]
            self.assertEqual((version, subject_id), ("3", "legacy-session"))
            _drop_trigger(path, trigger)

        replay = SqliteStore(path, owner_id="p2")
        try:
            self.assertEqual(
                replay._conn.execute(
                    "SELECT value FROM meta WHERE key='schema_version'",
                ).fetchone()[0],
                str(SCHEMA_VERSION),
            )
            self.assertIsNone(replay.request_row("req-matrix")["subject_id"])
        finally:
            replay.close()

    def test_v4_to_v5_schema_crash_rolls_back_task_table_and_can_be_retried(self) -> None:
        path = os.path.join(self.tmp.name, "schema-v4-to-v5.db")
        store = SqliteStore(path, owner_id="p1")
        store.close()
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("UPDATE meta SET value='4' WHERE key='schema_version'")
            connection.execute("DROP TABLE task_items")
            connection.commit()

        trigger = "crash_schema_v4_to_v5"
        _install_trigger(
            path, trigger, "meta", "UPDATE",
            f"NEW.key='schema_version' AND NEW.value='{SCHEMA_VERSION}'",
        )
        _run_crashing_child(path, """
from loomrise.durable_store import SqliteStore
SqliteStore(sys.argv[1], owner_id='p2')
""")

        with closing(sqlite3.connect(path)) as connection:
            version = connection.execute(
                "SELECT value FROM meta WHERE key='schema_version'",
            ).fetchone()[0]
            task_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_items'",
            ).fetchone()
        self.assertEqual(version, "4")
        self.assertIsNone(task_table)

        _drop_trigger(path, trigger)
        replay = SqliteStore(path, owner_id="p2")
        try:
            self.assertEqual(
                replay._conn.execute(
                    "SELECT value FROM meta WHERE key='schema_version'",
                ).fetchone()[0],
                str(SCHEMA_VERSION),
            )
            self.assertIsNotNone(replay._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_items'",
            ).fetchone())
        finally:
            replay.close()

    def test_schema_bootstrap_crash_rolls_back_ddl_and_can_be_retried(self) -> None:
        path = os.path.join(self.tmp.name, "schema-bootstrap.db")
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.commit()

        trigger = "crash_schema_bootstrap"
        _install_trigger(
            path, trigger, "meta", "INSERT",
            "NEW.key='schema_version'",
        )
        _run_crashing_child(path, """
from loomrise.durable_store import SqliteStore
SqliteStore(sys.argv[1], owner_id='p2')
""")

        with closing(sqlite3.connect(path)) as connection:
            version = connection.execute(
                "SELECT value FROM meta WHERE key='schema_version'",
            ).fetchone()
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'",
                )
            }
        self.assertIsNone(version)
        self.assertEqual(tables, {"meta"})

        _drop_trigger(path, trigger)
        replay = SqliteStore(path, owner_id="p2")
        try:
            self.assertEqual(
                replay._conn.execute(
                    "SELECT value FROM meta WHERE key='schema_version'",
                ).fetchone()[0],
                str(SCHEMA_VERSION),
            )
            self.assertEqual(
                replay._conn.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='requests'",
                ).fetchone()[0],
                1,
            )
        finally:
            replay.close()

    def test_legacy_column_migration_crash_rolls_back_alter_and_can_be_retried(self) -> None:
        path = os.path.join(self.tmp.name, "legacy-column-migration.db")
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO meta VALUES('schema_version', '2')")
            connection.execute("""
                CREATE TABLE requests (
                  request_id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  agent_version TEXT NOT NULL,
                  channel TEXT NOT NULL,
                  state TEXT NOT NULL,
                  subject_id TEXT,
                  trigger_kind TEXT,
                  trigger_ref TEXT,
                  result_id TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
            """)
            connection.execute(
                "INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                ("req-legacy", "tenant-a", "av1", "text", "queued", "session-id",
                 None, None, None, "2026-10-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00"),
            )
            connection.commit()

        trigger = "crash_legacy_columns"
        _install_trigger(
            path, trigger, "requests", "UPDATE",
            "NEW.request_id='req-legacy' AND NEW.subject_id IS NULL",
        )
        _run_crashing_child(path, """
from loomrise.durable_store import SqliteStore
SqliteStore(sys.argv[1], owner_id='p2')
""")

        with closing(sqlite3.connect(path)) as connection:
            version = connection.execute(
                "SELECT value FROM meta WHERE key='schema_version'",
            ).fetchone()[0]
            columns = {row[1] for row in connection.execute("PRAGMA table_info(requests)")}
            subject_id = connection.execute(
                "SELECT subject_id FROM requests WHERE request_id='req-legacy'",
            ).fetchone()[0]
        self.assertEqual(version, "2")
        self.assertNotIn("trigger_event_id", columns)
        self.assertNotIn("subject_scope", columns)
        self.assertEqual(subject_id, "session-id")

        _drop_trigger(path, trigger)
        replay = SqliteStore(path, owner_id="p2")
        try:
            columns = {
                row["name"] for row in replay._conn.execute("PRAGMA table_info(requests)")
            }
            self.assertEqual(
                replay._conn.execute(
                    "SELECT value FROM meta WHERE key='schema_version'",
                ).fetchone()[0],
                    str(SCHEMA_VERSION),
            )
            self.assertIn("trigger_event_id", columns)
            self.assertIn("subject_scope", columns)
            self.assertIsNone(replay.request_row("req-legacy")["subject_id"])
        finally:
            replay.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
