# -*- coding: utf-8 -*-
"""R2 tool-intent tests: unknown operations are reconciled, never replayed."""

from __future__ import annotations

import os
import tempfile
import threading
import unittest

from loomrise.contracts import Channel, RequestState, Run, ServiceRequest, new_id
from loomrise.durable_store import SqliteStore


class DurableToolIntentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "loomrise.db")
        self.store = SqliteStore(self.path, owner_id="p1")
        self.request = ServiceRequest(
            request_id=new_id("req"), tenant_id="tenant_demo", agent_version="av1",
            channel=Channel.TEXT, state=RequestState.QUEUED,
        )
        self.run = Run(
            run_id=new_id("run"), request_id=self.request.request_id,
            tenant_id=self.request.tenant_id, agent_version=self.request.agent_version,
            owner_id="p1",
        )
        self.store.begin_run(self.request, self.run, [])

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_repeated_intent_with_same_arguments_is_rejected(self) -> None:
        args = {"course_id": "c1", "learner_name": "A", "slot": "morning"}
        first = self.store.begin_tool_attempt(
            self.run.run_id, attempt_key="create_booking::k1", action="create_booking",
            arguments=args,
        )
        self.assertTrue(first["created"])
        with self.assertRaisesRegex(RuntimeError, "必须先对账"):
            self.store.begin_tool_attempt(
                self.run.run_id, attempt_key="create_booking::k1", action="create_booking",
                arguments=args,
            )

    def test_unknown_intent_survives_restart_and_is_not_replayed(self) -> None:
        args = {"course_id": "c1", "learner_name": "A", "slot": "morning"}
        self.store.begin_tool_attempt(
            self.run.run_id, attempt_key="create_booking::k1", action="create_booking",
            arguments=args,
        )
        self.store.close()
        self.store = SqliteStore(self.path, owner_id="p2")
        report = self.store.recover(owner_id="p2")
        self.assertEqual(report.interrupted, [self.run.run_id])
        attempt = self.store.tool_attempt("create_booking::k1")
        self.assertEqual(attempt["state"], "reconciling")
        next_run = Run(
            run_id=new_id("run"), request_id=self.request.request_id,
            tenant_id=self.request.tenant_id, agent_version=self.request.agent_version,
            owner_id="p2", occupancy_generation=2, lineage_parent=self.run.run_id,
        )
        self.store.begin_run(self.request, next_run, [])
        with self.assertRaisesRegex(RuntimeError, "必须先对账"):
            self.store.begin_tool_attempt(
                next_run.run_id, attempt_key="create_booking::k1", action="create_booking",
                arguments=args,
            )

    def test_operation_key_cannot_be_rebound_to_other_arguments(self) -> None:
        self.store.begin_tool_attempt(
            self.run.run_id, attempt_key="create_booking::k1", action="create_booking",
            arguments={"course_id": "c1"},
        )
        with self.assertRaisesRegex(ValueError, "不同的动作或参数"):
            self.store.begin_tool_attempt(
                self.run.run_id, attempt_key="create_booking::k1", action="create_booking",
                arguments={"course_id": "c2"},
            )

    def test_independent_connections_grant_only_one_execution_intent(self) -> None:
        other = SqliteStore(self.path, owner_id="p1")
        barrier = threading.Barrier(2)
        results: list[str] = []
        lock = threading.Lock()

        def claim(store: SqliteStore) -> None:
            barrier.wait()
            try:
                store.begin_tool_attempt(
                    self.run.run_id,
                    attempt_key="create_booking::race",
                    action="create_booking",
                    arguments={"course_id": "c1"},
                )
                value = "created"
            except RuntimeError:
                value = "rejected"
            with lock:
                results.append(value)

        threads = [
            threading.Thread(target=claim, args=(self.store,)),
            threading.Thread(target=claim, args=(other,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        other.close()
        self.assertCountEqual(results, ["created", "rejected"])


if __name__ == "__main__":
    unittest.main()
