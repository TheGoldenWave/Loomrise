# -*- coding: utf-8 -*-
"""代表性进程崩溃下的事务与 outbox 持久化语义。"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loomrise.contracts import Channel, Run, RunEvent, RequestState, ServiceRequest, new_id  # noqa: E402
from loomrise.durable_adapter import action_key  # noqa: E402
from loomrise.durable_store import SqliteStore  # noqa: E402


def make_run_fixture(path: str) -> tuple[str, str]:
    store = SqliteStore(path, owner_id="p1")
    request = ServiceRequest(
        request_id=new_id("req"),
        tenant_id="tenant_demo",
        agent_version="av_test",
        channel=Channel.TEXT,
        state=RequestState.RUNNING,
    )
    run = Run(
        run_id=new_id("run"),
        request_id=request.request_id,
        tenant_id=request.tenant_id,
        agent_version=request.agent_version,
        owner_id="p1",
        occupancy_generation=1,
    )
    store.begin_run(request, run, [])
    store.close()
    return request.request_id, run.run_id


def exit_child_during_write(path: str, request_id: str, run_id: str, *, before_commit: bool) -> int:
    hook = "store.before_commit = lambda: os._exit(23); " if before_commit else ""
    exit_code = 23 if before_commit else 17
    code = (
        "import os,sys; from loomrise.contracts import RunEvent; "
        "from loomrise.durable_store import SqliteStore; "
        "store=SqliteStore(sys.argv[1], owner_id='p1'); "
        f"{hook}"
        "event=RunEvent(seq=store.next_seq(sys.argv[3]), event_type='tool.outcome', "
        "request_id=sys.argv[2], run_id=sys.argv[3], tenant_id='tenant_demo', "
        "agent_version='av_test', channel='text', "
        "payload={'tool':'create_booking','outcome':'success','result_id':'res_1'}, "
        "idempotency_key='idem-1').seal(store.last_event(sys.argv[3]).hash "
        "if store.last_event(sys.argv[3]) else ''); "
        "created,result_id=store.commit_write(sys.argv[3], key='create_booking::idem-1', "
        "bare_key='idem-1', action='create_booking', result_id='res_1', event=event, "
        "outbox_payload={'key':'create_booking::idem-1','result_id':'res_1'}); "
        "assert created and result_id=='res_1'; "
        f"os._exit({exit_code})"
    )
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, "-c", code, path, request_id, run_id],
        timeout=10,
        capture_output=True,
        text=True,
        cwd=root,
    )
    if result.returncode != exit_code:
        raise AssertionError(f"child exit={result.returncode}, stderr={result.stderr}")
    return result.returncode


def exit_child_after_insert(path: str, request_id: str, run_id: str, table: str) -> None:
    if table not in {"idempotency", "events", "outbox"}:
        raise ValueError(f"unsupported crash point: {table}")
    trigger = f"crash_after_{table}"
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            f"CREATE TRIGGER {trigger} AFTER INSERT ON {table} "
            "BEGIN SELECT crash_after_write(); END;"
        )

    code = """
import os
import sqlite3
import sys
from loomrise.contracts import RunEvent
from loomrise.durable_store import SqliteStore

connect = sqlite3.connect
def connect_with_crashpoint(*args, **kwargs):
    connection = connect(*args, **kwargs)
    connection.create_function("crash_after_write", 0, lambda: os._exit(29))
    return connection
sqlite3.connect = connect_with_crashpoint
store = SqliteStore(sys.argv[1], owner_id="p1")
event = RunEvent(
    seq=store.next_seq(sys.argv[3]), event_type="tool.outcome",
    request_id=sys.argv[2], run_id=sys.argv[3], tenant_id="tenant_demo",
    agent_version="av_test", channel="text",
    payload={"tool": "create_booking", "outcome": "success", "result_id": "res_1"},
    idempotency_key="idem-1",
).seal(store.last_event(sys.argv[3]).hash if store.last_event(sys.argv[3]) else "")
store.commit_write(
    sys.argv[3], key="create_booking::idem-1", bare_key="idem-1",
    action="create_booking", result_id="res_1", event=event,
    outbox_payload={"key": "create_booking::idem-1", "result_id": "res_1"},
)
os._exit(17)
"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, "-c", code, path, request_id, run_id],
        timeout=10,
        capture_output=True,
        text=True,
        cwd=root,
    )
    if result.returncode != 29:
        raise AssertionError(f"child exit={result.returncode}, stderr={result.stderr}")
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f"DROP TRIGGER {trigger}")


class DurableOutboxCrashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "loomrise.db")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_process_exit_inside_write_transaction_leaves_no_partial_records(self) -> None:
        request_id, run_id = make_run_fixture(self.path)
        exit_child_during_write(self.path, request_id, run_id, before_commit=True)

        recovered = SqliteStore(self.path, owner_id="p2")
        try:
            report = recovered.recover(owner_id="p2")
            self.assertEqual(report.interrupted, [run_id])
            self.assertEqual(recovered.run_row(run_id)["status"], "failed")
            self.assertEqual(recovered.request_row(request_id)["state"], "failed")
            self.assertEqual(
                recovered._conn.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0], 0,
            )
            self.assertEqual(
                recovered._conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0,
            )
            self.assertEqual(
                [event.event_type for event in recovered.load_events(run_id)],
                ["run.interrupted"],
            )
            self.assertTrue(recovered.verify_chain())
        finally:
            recovered.close()

    def test_process_exit_after_each_side_effect_insert_rolls_back_write_unit(self) -> None:
        for table in ("idempotency", "events", "outbox"):
            with self.subTest(after=table):
                path = os.path.join(self.tmp.name, f"crash-after-{table}.db")
                request_id, run_id = make_run_fixture(path)
                exit_child_after_insert(path, request_id, run_id, table)

                recovered = SqliteStore(path, owner_id="p2")
                try:
                    report = recovered.recover(owner_id="p2")
                    self.assertEqual(report.interrupted, [run_id])
                    self.assertEqual(recovered._conn.execute(
                        "SELECT COUNT(*) FROM idempotency",
                    ).fetchone()[0], 0)
                    self.assertEqual(recovered._conn.execute(
                        "SELECT COUNT(*) FROM outbox",
                    ).fetchone()[0], 0)
                    self.assertEqual(
                        [event.event_type for event in recovered.load_events(run_id)],
                        ["run.interrupted"],
                    )
                    self.assertTrue(recovered.verify_chain())
                finally:
                    recovered.close()

    def test_committed_outbox_survives_exit_and_duplicate_key_reuses_result(self) -> None:
        request_id, run_id = make_run_fixture(self.path)
        exit_child_during_write(self.path, request_id, run_id, before_commit=False)

        recovered = SqliteStore(self.path, owner_id="p2")
        try:
            recovered.recover(owner_id="p2")
            first_read = recovered.pending_outbox()
            self.assertEqual(len(first_read), 1)
            self.assertEqual(recovered.pending_outbox(), first_read)
            self.assertEqual(first_read[0]["id"], f"ob_{action_key('create_booking', 'idem-1')}")
            self.assertEqual(first_read[0]["state"], "pending")
            self.assertEqual(first_read[0]["attempts"], 0)

            retry_request = ServiceRequest(
                request_id=new_id("req"),
                tenant_id="tenant_demo",
                agent_version="av_test",
                channel=Channel.TEXT,
                state=RequestState.QUEUED,
            )
            retry_run = Run(
                run_id=new_id("run"),
                request_id=retry_request.request_id,
                tenant_id=retry_request.tenant_id,
                agent_version=retry_request.agent_version,
                owner_id="p2",
                occupancy_generation=1,
            )
            recovered.begin_run(retry_request, retry_run, [])
            retry_event = RunEvent(
                seq=0,
                event_type="tool.outcome",
                request_id=retry_request.request_id,
                run_id=retry_run.run_id,
                tenant_id=retry_request.tenant_id,
                agent_version=retry_request.agent_version,
                channel="text",
                payload={"tool": "create_booking", "outcome": "success", "result_id": "res_retry"},
                idempotency_key="idem-1",
            ).seal("")
            created, result_id = recovered.commit_write(
                retry_run.run_id,
                key=action_key("create_booking", "idem-1"),
                bare_key="idem-1",
                action="create_booking",
                result_id="res_retry",
                event=retry_event,
            )
            self.assertFalse(created)
            self.assertEqual(result_id, "res_1")
            self.assertEqual(recovered.pending_outbox(), first_read)
            self.assertEqual(
                recovered._conn.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0], 1,
            )
            self.assertEqual(
                recovered._conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1,
            )
            self.assertEqual(recovered.load_events(retry_run.run_id), [])
        finally:
            recovered.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
