# -*- coding: utf-8 -*-
"""At-least-once dispatcher behavior over the durable outbox API."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loomrise.contracts import Channel, Run, RunEvent, RequestState, ServiceRequest, new_id  # noqa: E402
from loomrise.durable_adapter import action_key  # noqa: E402
from loomrise.durable_store import SqliteStore  # noqa: E402
from loomrise.outbox import dispatch_pending  # noqa: E402


class OutboxDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "loomrise.db")
        self.store = SqliteStore(self.path, owner_id="p1")
        request = ServiceRequest(
            request_id=new_id("req"),
            tenant_id="tenant_demo",
            agent_version="av_test",
            channel=Channel.TEXT,
            state=RequestState.RUNNING,
        )
        self.run = Run(
            run_id=new_id("run"),
            request_id=request.request_id,
            tenant_id=request.tenant_id,
            agent_version=request.agent_version,
            owner_id="p1",
            occupancy_generation=1,
        )
        self.store.begin_run(request, self.run, [])
        event = RunEvent(
            seq=0,
            event_type="tool.outcome",
            request_id=request.request_id,
            run_id=self.run.run_id,
            tenant_id=request.tenant_id,
            agent_version=request.agent_version,
            channel="text",
            payload={"tool": "create_booking", "outcome": "success", "result_id": "res_1"},
            idempotency_key="idem-1",
        ).seal("")
        self.store.commit_write(
            self.run.run_id,
            key=action_key("create_booking", "idem-1"),
            bare_key="idem-1",
            action="create_booking",
            result_id="res_1",
            event=event,
            outbox_payload={"key": action_key("create_booking", "idem-1"), "result_id": "res_1"},
        )

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_success_marks_delivered_after_handler_receives_stable_id(self) -> None:
        record = self.store.pending_outbox()[0]
        received: list[tuple[str, str, dict]] = []

        def handler(item: dict, idempotency_key: str) -> None:
            received.append((item["id"], idempotency_key, item))

        delivered = dispatch_pending(self.store, handler)

        self.assertEqual(delivered, [record["id"]])
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][:2], (record["id"], record["id"]))
        self.assertEqual(received[0][2]["attempts"], 1)
        self.assertEqual(self.store.pending_outbox(), [])
        stored = self.store._conn.execute(
            "SELECT state, attempts FROM outbox WHERE id=?", (record["id"],),
        ).fetchone()
        self.assertEqual((stored["state"], stored["attempts"]), ("delivered", 1))
        self.store.mark_outbox(record["id"])
        self.assertEqual(self.store._conn.execute(
            "SELECT attempts FROM outbox WHERE id=?", (record["id"],),
        ).fetchone()["attempts"], 1)

    def test_handler_error_leaves_pending_and_retry_reuses_same_id(self) -> None:
        record_id = self.store.pending_outbox()[0]["id"]
        observed: list[str] = []

        def fail(_item: dict, idempotency_key: str) -> None:
            observed.append(idempotency_key)
            raise RuntimeError("consumer unavailable")

        with self.assertRaisesRegex(RuntimeError, "consumer unavailable"):
            dispatch_pending(self.store, fail)
        pending_after_error = self.store.pending_outbox()
        self.assertEqual([item["id"] for item in pending_after_error], [record_id])
        self.assertEqual(pending_after_error[0]["attempts"], 1)

        retried: list[str] = []
        delivered = dispatch_pending(
            self.store,
            lambda _item, idempotency_key: retried.append(idempotency_key),
        )

        self.assertEqual(observed, [record_id])
        self.assertEqual(retried, [record_id])
        self.assertEqual(delivered, [record_id])
        self.assertEqual(self.store.pending_outbox(), [])
        self.assertEqual(self.store._conn.execute(
            "SELECT attempts FROM outbox WHERE id=?", (record_id,),
        ).fetchone()["attempts"], 2)

    def test_replay_after_consumer_effect_before_ack_deduplicates_by_outbox_id(self) -> None:
        record_id = self.store.pending_outbox()[0]["id"]
        consumer_db = os.path.join(self.tmp.name, "consumer.db")
        consumer = sqlite3.connect(consumer_db, isolation_level=None)
        consumer.execute(
            "CREATE TABLE delivered_effects (outbox_id TEXT PRIMARY KEY, payload TEXT NOT NULL)",
        )

        def consumer_handler(record: dict, idempotency_key: str) -> None:
            self.assertEqual(idempotency_key, record_id)
            consumer.execute(
                "INSERT OR IGNORE INTO delivered_effects VALUES(?,?)",
                (idempotency_key, record["payload_json"]),
            )

        try:
            with patch.object(self.store, "mark_outbox", side_effect=RuntimeError("ack crash")):
                with self.assertRaisesRegex(RuntimeError, "ack crash"):
                    dispatch_pending(self.store, consumer_handler)

            self.assertEqual(
                consumer.execute("SELECT COUNT(*) FROM delivered_effects").fetchone()[0], 1,
            )
            self.assertEqual([item["id"] for item in self.store.pending_outbox()], [record_id])

            self.assertEqual(dispatch_pending(self.store, consumer_handler), [record_id])
            self.assertEqual(
                consumer.execute("SELECT COUNT(*) FROM delivered_effects").fetchone()[0], 1,
            )
            self.assertEqual(self.store.pending_outbox(), [])
            self.assertEqual(self.store._conn.execute(
                "SELECT attempts FROM outbox WHERE id=?", (record_id,),
            ).fetchone()["attempts"], 2)
        finally:
            consumer.close()

    def test_process_exit_after_consumer_effect_before_ack_replays_by_outbox_id(self) -> None:
        record_id = self.store.pending_outbox()[0]["id"]
        consumer_db = os.path.join(self.tmp.name, "consumer-crash.db")
        code = """
import os, sqlite3, sys
from loomrise.durable_store import SqliteStore
from loomrise.outbox import dispatch_pending
store = SqliteStore(sys.argv[1], owner_id='p2')
consumer = sqlite3.connect(sys.argv[2])
consumer.execute('CREATE TABLE delivered_effects (outbox_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
consumer.commit()
def handler(record, idempotency_key):
    consumer.execute('INSERT OR IGNORE INTO delivered_effects VALUES(?,?)',
                     (idempotency_key, record['payload_json']))
    consumer.commit()
    os._exit(29)
dispatch_pending(store, handler)
os._exit(17)
"""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        child = subprocess.run(
            [sys.executable, "-c", code, self.path, consumer_db],
            timeout=10, capture_output=True, text=True, cwd=root,
        )
        self.assertEqual(child.returncode, 29, child.stderr)

        with closing(sqlite3.connect(consumer_db)) as consumer:
            self.assertEqual(consumer.execute("SELECT COUNT(*) FROM delivered_effects").fetchone()[0], 1)
        pending = self.store.pending_outbox()
        self.assertEqual([item["id"] for item in pending], [record_id])
        self.assertEqual(pending[0]["attempts"], 1)

        with closing(sqlite3.connect(consumer_db)) as consumer:
            def deduplicating_handler(record: dict, idempotency_key: str) -> None:
                consumer.execute(
                    "INSERT OR IGNORE INTO delivered_effects VALUES(?,?)",
                    (idempotency_key, record["payload_json"]),
                )
                consumer.commit()

            self.assertEqual(dispatch_pending(self.store, deduplicating_handler), [record_id])
            self.assertEqual(consumer.execute("SELECT COUNT(*) FROM delivered_effects").fetchone()[0], 1)
        self.assertEqual(self.store.pending_outbox(), [])
        stored = self.store._conn.execute(
            "SELECT state, attempts FROM outbox WHERE id=?", (record_id,),
        ).fetchone()
        self.assertEqual((stored["state"], stored["attempts"]), ("delivered", 2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
