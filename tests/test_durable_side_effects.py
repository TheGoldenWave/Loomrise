# -*- coding: utf-8 -*-
"""R2 tool-intent tests: unknown operations are reconciled, never replayed."""

from __future__ import annotations

import os
import tempfile
import threading
import unittest

from loomrise.contracts import Channel, RequestState, Run, ServiceRequest, new_id
from loomrise.durable_store import SqliteStore
from loomrise.reconciliation import (
    DurableToolReconciliation, ProviderOperationResult,
)


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
        settled = self.store.reconcile_tool_attempt(
            "create_booking::k1", outcome="applied", result_id="booking-after-restart",
        )
        self.assertEqual(settled["state"], "succeeded")
        self.assertTrue(self.store.verify_chain(self.run.run_id))
        next_run = Run(
            run_id=new_id("run"), request_id=self.request.request_id,
            tenant_id=self.request.tenant_id, agent_version=self.request.agent_version,
            owner_id="p2", occupancy_generation=2, lineage_parent=self.run.run_id,
        )
        self.store.begin_run(self.request, next_run, [])
        duplicate = self.store.begin_tool_attempt(
            next_run.run_id, attempt_key="create_booking::k1", action="create_booking",
            arguments=args,
        )
        self.assertFalse(duplicate["created"])
        self.assertEqual(duplicate["result_id"], "booking-after-restart")

    def test_external_lookup_can_settle_applied_result_without_replaying_write(self) -> None:
        self.store.begin_tool_attempt(
            self.run.run_id, attempt_key="create_booking::settle-applied",
            action="create_booking", arguments={"course_id": "c1"},
        )
        self.assertTrue(self.store.mark_tool_attempt_unknown(
            "create_booking::settle-applied", run_id=self.run.run_id,
        ))

        settled = self.store.reconcile_tool_attempt(
            "create_booking::settle-applied", outcome="applied", result_id="booking-42",
        )

        self.assertEqual(settled["state"], "succeeded")
        self.assertEqual(settled["result_id"], "booking-42")
        self.assertEqual(self.store.tool_attempt("create_booking::settle-applied")["state"], "succeeded")
        self.assertTrue(self.store.verify_chain(self.run.run_id))
        self.assertEqual(
            [event.event_type for event in self.store.load_events(self.run.run_id)],
            ["tool.reconciled"],
        )
        duplicate = self.store.begin_tool_attempt(
            self.run.run_id, attempt_key="create_booking::settle-applied",
            action="create_booking", arguments={"course_id": "c1"},
        )
        self.assertFalse(duplicate["created"])
        self.assertEqual(duplicate["result_id"], "booking-42")

    def test_external_lookup_not_applied_allows_explicit_retry_and_unknown_stays_blocked(self) -> None:
        key = "create_booking::settle-not-applied"
        self.store.begin_tool_attempt(
            self.run.run_id, attempt_key=key, action="create_booking",
            arguments={"course_id": "c1"},
        )
        self.store.mark_tool_attempt_unknown(key, run_id=self.run.run_id)

        pending = self.store.reconcile_tool_attempt(key, outcome="unknown")
        self.assertEqual(pending["state"], "reconciling")

        not_applied = self.store.reconcile_tool_attempt(key, outcome="not_applied")
        self.assertEqual(not_applied["state"], "failed")
        retry = self.store.begin_tool_attempt(
            self.run.run_id, attempt_key=key, action="create_booking",
            arguments={"course_id": "c1"},
        )
        self.assertTrue(retry["created"])

    def test_provider_reconciliation_queries_only_stable_identity_and_keeps_unknown_blocked(self) -> None:
        key = "create_booking::provider-query"
        self.store.begin_tool_attempt(
            self.run.run_id, attempt_key=key, action="create_booking",
            arguments={"course_id": "c1", "learner_name": "A", "slot": "morning"},
        )
        self.store.mark_tool_attempt_unknown(key, run_id=self.run.run_id)
        queries = []

        class UnknownProvider:
            def lookup_operation(inner_self, *, attempt_key, action):
                queries.append((attempt_key, action))
                return ProviderOperationResult("unknown")

        results = DurableToolReconciliation(self.store).reconcile_pending(UnknownProvider())

        self.assertEqual(queries, [(key, "create_booking")])
        self.assertEqual(results[0]["state"], "reconciling")
        with self.assertRaisesRegex(RuntimeError, "必须先对账"):
            self.store.begin_tool_attempt(
                self.run.run_id, attempt_key=key, action="create_booking",
                arguments={"course_id": "c1", "learner_name": "A", "slot": "morning"},
            )

    def test_provider_applied_lookup_and_late_receipt_share_idempotent_settlement(self) -> None:
        key = "create_booking::late-provider-receipt"
        self.store.begin_tool_attempt(
            self.run.run_id, attempt_key=key, action="create_booking",
            arguments={"course_id": "c1"},
        )
        self.store.mark_tool_attempt_unknown(key, run_id=self.run.run_id)
        coordinator = DurableToolReconciliation(self.store)

        class AppliedProvider:
            def lookup_operation(inner_self, *, attempt_key, action):
                return ProviderOperationResult("applied", "booking-provider-77")

        settled = coordinator.reconcile_pending(AppliedProvider())[0]
        repeated = coordinator.accept_late_receipt(
            attempt_key=key, result_id="booking-provider-77",
        )

        self.assertEqual(settled["state"], "succeeded")
        self.assertEqual(repeated["result_id"], "booking-provider-77")
        self.assertEqual(len(self.store.pending_outbox()), 1)
        self.assertTrue(self.store.verify_chain(self.run.run_id))

    def test_provider_lookup_failure_does_not_authorize_reexecution(self) -> None:
        key = "create_booking::provider-error"
        self.store.begin_tool_attempt(
            self.run.run_id, attempt_key=key, action="create_booking", arguments={"course_id": "c1"},
        )
        self.store.mark_tool_attempt_unknown(key, run_id=self.run.run_id)

        class FailedProvider:
            def lookup_operation(inner_self, *, attempt_key, action):
                raise TimeoutError("provider lookup timed out")

        result = DurableToolReconciliation(self.store).reconcile_pending(FailedProvider())[0]
        self.assertEqual(result["state"], "reconciling")
        self.assertEqual(self.store.reconciling_tool_attempts()[0]["attempt_key"], key)

    def test_reconciliation_rejects_inconsistent_external_result(self) -> None:
        key = "create_booking::settle-invalid"
        self.store.begin_tool_attempt(
            self.run.run_id, attempt_key=key, action="create_booking",
            arguments={"course_id": "c1"},
        )
        self.store.mark_tool_attempt_unknown(key, run_id=self.run.run_id)

        with self.assertRaisesRegex(ValueError, "result_id"):
            self.store.reconcile_tool_attempt(key, outcome="applied")
        self.assertEqual(self.store.tool_attempt(key)["state"], "reconciling")

    def test_reconciliation_commit_is_atomic(self) -> None:
        key = "create_booking::settle-crash"
        self.store.begin_tool_attempt(
            self.run.run_id, attempt_key=key, action="create_booking",
            arguments={"course_id": "c1"},
        )
        self.store.mark_tool_attempt_unknown(key, run_id=self.run.run_id)

        def crash_before_commit():
            raise RuntimeError("injected reconciliation commit crash")

        self.store.before_commit = crash_before_commit
        with self.assertRaisesRegex(RuntimeError, "injected"):
            self.store.reconcile_tool_attempt(
                key, outcome="applied", result_id="booking-atomic",
            )
        self.store.before_commit = None

        self.assertEqual(self.store.tool_attempt(key)["state"], "reconciling")
        self.assertIsNone(self.store._conn.execute(
            "SELECT 1 FROM idempotency WHERE key=?", (key,),
        ).fetchone())
        self.assertEqual(self.store.pending_outbox(), [])
        self.assertEqual(self.store.load_events(self.run.run_id), [])

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
        contenders = 100
        stores = [self.store] + [SqliteStore(self.path, owner_id="p1") for _ in range(contenders - 1)]
        barrier = threading.Barrier(contenders)
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

        threads = [threading.Thread(target=claim, args=(store,)) for store in stores]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        for store in stores[1:]:
            store.close()
        self.assertEqual(results.count("created"), 1)
        self.assertEqual(results.count("rejected"), contenders - 1)


if __name__ == "__main__":
    unittest.main()
