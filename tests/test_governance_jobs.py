"""Lifecycle, authority, concurrency, and persistence tests for governance jobs."""

import asyncio
import json
from pathlib import Path
import tempfile
import threading
import unittest

from loomrise.configuration import ConfigurationPrincipal
from loomrise.diagnostics import (
    DiagnosticsService, REPORT_SCHEMA_VERSION, PROVIDER_CONTRACT_HASH,
    PROVIDER_VERSIONS, PROVIDER_KIND_OFFLINE_SCRIPTED, PROVIDER_KIND_REAL_HARNESS,
)
from loomrise.durable_store import SCHEMA_VERSION, SqliteStore
from loomrise.governance_jobs import GovernanceJobs


class Provider:
    def __init__(self, behavior=None):
        self.descriptor = {
            "provider_id": "test-provider",
            "provider_kind": PROVIDER_KIND_OFFLINE_SCRIPTED,
            "version": PROVIDER_VERSIONS[PROVIDER_KIND_OFFLINE_SCRIPTED],
            "contract_hash": PROVIDER_CONTRACT_HASH,
        }
        self.behavior = behavior
        self.calls = 0

    async def run(self, *, snapshot, read_evidence, token_budget, max_output_bytes):
        self.calls += 1
        if self.behavior is not None:
            return await self.behavior(snapshot, read_evidence, token_budget, max_output_bytes)
        return {
            "report": make_report(snapshot),
            "usage": {"input_tokens": 3, "output_tokens": 2},
            "provider_state": "stopped",
        }


def make_report(snapshot):
    item = snapshot["cases"][0]
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "proposal",
        "findings": [{
            "category": "knowledge",
            "summary": "Review the selected evidence.",
            "recommendation": "Have an authorized operator review the evidence.",
            "evidence_ids": [item["evidence_id"]],
        }],
        "insufficient_categories": ["routing", "loading", "policy", "tool", "rule"],
        "limitations": snapshot["limitations"].copy(),
    }


class GovernanceJobsCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "jobs.db")
        self.store = SqliteStore(self.path, owner_id="worker-a")
        self.diagnostics = DiagnosticsService(self.store)
        self.owner = ConfigurationPrincipal("tenant-a", "owner-a", "owner", ("agent-a",))
        self.recipient = ConfigurationPrincipal("tenant-a", "editor-a", "editor", ("agent-a",))
        self.permission = self.diagnostics.issue(
            principal=self.owner,
            agent_id="agent-a",
            recipient_actor_id=self.recipient.actor_id,
            run_ids=[],
            case_ids=["c1_consult_success"],
        )
        self.provider = Provider()
        self.jobs = GovernanceJobs(self.diagnostics, provider=self.provider)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(lambda: getattr(self, "store", None) and self.store.close())

    def create(self, **kwargs):
        return self.jobs.create(
            principal=self.recipient,
            agent_id="agent-a",
            permission_id=self.permission["permission_id"],
            idempotency_key=kwargs.pop("idempotency_key", "job-1"),
            **kwargs,
        )

    def run_job(self, job):
        return asyncio.run(self.jobs.run(
            principal=self.recipient, agent_id="agent-a", job_id=job["job_id"]))

    def cancel(self, jobs=None, principal=None, job=None):
        return (jobs or self.jobs).cancel(
            principal=principal or self.recipient, agent_id="agent-a", job_id=job["job_id"])


class TestGovernanceJobsLifecycle(GovernanceJobsCase):
    def test_explicit_job_persists_valid_report_usage_and_reopens(self):
        job = self.create()
        self.assertEqual(job["state"], "queued")
        result = self.run_job(job)
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["provider_state"], "stopped")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["reserved_tokens"], result["frozen"]["attempt_tokens"])
        self.assertIsNotNone(result["report_id"])
        self.assertEqual(json.loads(result["history"][0]["usage_json"]),
                         {"input_tokens": 3, "output_tokens": 2})
        self.store.close()
        self.store = SqliteStore(self.path, owner_id="worker-a")
        self.diagnostics = DiagnosticsService(self.store)
        self.jobs = GovernanceJobs(self.diagnostics, provider=self.provider)
        reopened = self.jobs.read(principal=self.recipient, agent_id="agent-a", job_id=job["job_id"])
        self.assertEqual(reopened["state"], "succeeded")
        self.assertEqual(reopened["history"][0]["generation"], 1)
        self.assertEqual(self.store._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
                         str(SCHEMA_VERSION))

    def test_explicit_restart_migration_preserves_job_and_attempt_rows(self):
        job = self.create()
        with self.store._tx() as cur:
            cur.execute("UPDATE governance_jobs SET state='running',generation=4,attempts=1,owner_id='old-worker' WHERE job_id=?",
                        (job["job_id"],))
            cur.execute("INSERT INTO governance_attempts(job_id,generation,provider_state,reserved_tokens) VALUES(?,?,?,?)",
                        (job["job_id"], 4, "unknown", 100))
            cur.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION - 1),))
        self.store.close()
        self.store = SqliteStore(self.path, owner_id="worker-b")
        self.diagnostics = DiagnosticsService(self.store)
        self.jobs = GovernanceJobs(self.diagnostics, provider=self.provider)
        recovered = self.jobs.recover(principal=self.recipient, agent_id="agent-a", job_id=job["job_id"])
        self.assertEqual(recovered["state"], "interrupted")
        self.assertEqual(recovered["generation"], 5)
        self.assertEqual(recovered["provider_state"], "unknown")
        self.assertEqual(recovered["history"][0]["provider_state"], "unknown")
        self.assertEqual(self.provider.calls, 0)

    def test_idempotency_freezes_provider_descriptor_and_input(self):
        job = self.create()
        duplicate = self.create()
        self.assertEqual(duplicate["job_id"], job["job_id"])
        self.provider.descriptor = {"provider_id": "changed-provider", "version": "2"}
        with self.assertRaisesRegex(ValueError, "Provider 或工具合同已变化"):
            self.run_job(job)
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.jobs.read(principal=self.recipient, agent_id="agent-a",
                                        job_id=job["job_id"])["state"], "queued")

    def test_creation_rechecks_snapshot_hash_in_same_transaction_as_job_insert(self):
        original_read = self.diagnostics.read_evidence

        def mutate_after_read(**kwargs):
            snapshot = original_read(**kwargs)
            with self.store._tx() as cur:
                cur.execute("UPDATE diagnosis_snapshots SET input_hash=? WHERE permission_id=?",
                            ("f" * 64, self.permission["permission_id"]))
            return snapshot

        self.diagnostics.read_evidence = mutate_after_read
        with self.assertRaises(ValueError):
            self.create(idempotency_key="snapshot-race")
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM governance_jobs").fetchone()[0], 0)

    def test_invalid_usage_is_not_persisted_and_reservation_is_not_refunded(self):
        async def invalid_usage(snapshot, *_):
            return {"report": make_report(snapshot), "usage": {"input_tokens": True, "output_tokens": 1},
                    "provider_state": "stopped"}

        self.provider.behavior = invalid_usage
        job = self.create(max_attempts=2)
        failed = self.run_job(job)
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["provider_state"], "stopped")
        self.assertEqual(failed["reserved_tokens"], job["frozen"]["attempt_tokens"])
        self.assertIsNone(failed["history"][0]["usage_json"])
        self.assertEqual(failed["reason"], "provider_usage_invalid")

    def test_unknown_execution_keeps_full_reservation_and_cannot_retry(self):
        async def unknown(snapshot, *_):
            return {"report": make_report(snapshot), "usage": {"input_tokens": 1, "output_tokens": 1},
                    "provider_state": "unknown"}

        self.provider.behavior = unknown
        job = self.create(max_attempts=3)
        result = self.run_job(job)
        self.assertEqual(result["state"], "interrupted")
        self.assertEqual(result["provider_state"], "unknown")
        self.assertEqual(result["reserved_tokens"], job["frozen"]["attempt_tokens"])
        self.assertIsNone(result["history"][0]["usage_json"])
        with self.assertRaisesRegex(ValueError, "Provider 未确认停止或作业不可重试"):
            self.jobs.retry(principal=self.recipient, agent_id="agent-a", job_id=job["job_id"])

    def test_retry_reserves_another_attempt_before_provider_and_honors_total_budget(self):
        calls = 0

        async def fail_once(snapshot, *_):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"report": {"not": "a report"}, "usage": {"input_tokens": 0, "output_tokens": 0},
                        "provider_state": "stopped"}
            return {"report": make_report(snapshot), "usage": {"input_tokens": 3, "output_tokens": 2},
                    "provider_state": "stopped"}

        self.provider.behavior = fail_once
        job = self.create(max_attempts=2, total_tokens=200, attempt_tokens=100)
        first = self.run_job(job)
        self.assertEqual(first["state"], "failed")
        self.assertEqual(first["provider_state"], "stopped")
        self.assertEqual(json.loads(first["history"][0]["usage_json"]),
                         {"input_tokens": 0, "output_tokens": 0})
        retried = self.jobs.retry(principal=self.recipient, agent_id="agent-a", job_id=job["job_id"])
        self.assertEqual(retried["state"], "queued")
        result = self.run_job(retried)
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["reserved_tokens"], 200)
        self.assertEqual(self.provider.calls, 2)

    def test_retry_exhausts_token_budget_without_refunding_reserved_attempt(self):
        async def invalid_report(snapshot, *_):
            return {"report": {"not": "a report"}, "usage": {"input_tokens": 0, "output_tokens": 0},
                    "provider_state": "stopped"}

        self.provider.behavior = invalid_report
        job = self.create(max_attempts=2, total_tokens=150, attempt_tokens=100)
        failed = self.run_job(job)
        self.assertEqual(failed["state"], "failed")
        with self.assertRaisesRegex(ValueError, "治理作业预算已耗尽"):
            self.jobs.retry(principal=self.recipient, agent_id="agent-a", job_id=job["job_id"])
        exhausted = self.jobs.read(principal=self.recipient, agent_id="agent-a", job_id=job["job_id"])
        self.assertEqual(exhausted["state"], "exhausted")
        self.assertEqual(exhausted["reserved_tokens"], 100)

    def test_revoke_allows_status_and_cancel_but_blocks_retry_and_evidence(self):
        job = self.create(max_attempts=2)
        self.diagnostics.revoke(principal=self.owner, agent_id="agent-a",
                                permission_id=self.permission["permission_id"])
        status = self.jobs.read(principal=self.recipient, agent_id="agent-a", job_id=job["job_id"])
        self.assertEqual(status["state"], "queued")
        cancelled = self.cancel(job=job)
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(cancelled["provider_state"], "not_started")
        with self.assertRaises(PermissionError):
            self.jobs.retry(principal=self.recipient, agent_id="agent-a", job_id=job["job_id"])
        self.assertEqual(self.provider.calls, 0)

    def test_provider_descriptor_change_after_freeze_never_starts_attempt(self):
        job = self.create()
        self.provider.descriptor["version"] = "2"
        with self.assertRaisesRegex(ValueError, "Provider 或工具合同已变化"):
            self.run_job(job)
        current = self.jobs.read(principal=self.recipient, agent_id="agent-a", job_id=job["job_id"])
        self.assertEqual((current["state"], current["attempts"], current["reserved_tokens"]), ("queued", 0, 0))


class TestGovernanceJobsCancellation(GovernanceJobsCase):
    def test_same_loop_cancel_signals_provider_task_and_fences_swallowed_late_result(self):
        started = asyncio.Event()
        after_cancel = asyncio.Event()
        release = asyncio.Event()

        async def swallow_cancel(snapshot, *_):
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                after_cancel.set()
                await release.wait()
            return {"report": make_report(snapshot), "usage": {"input_tokens": 3, "output_tokens": 2},
                    "provider_state": "stopped"}

        self.provider.behavior = swallow_cancel
        job = self.create()

        async def scenario():
            task = asyncio.create_task(self.jobs.run(principal=self.recipient, agent_id="agent-a",
                                                     job_id=job["job_id"]))
            await started.wait()
            first = self.cancel(job=job)
            self.assertEqual(first["state"], "cancel_requested")
            await asyncio.wait_for(after_cancel.wait(), timeout=1)
            release.set()
            return await task

        result = asyncio.run(scenario())
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(result["provider_state"], "stopped")
        self.assertIsNone(result["report_id"])
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM diagnosis_reports").fetchone()[0], 0)

    def test_revoked_permission_blocks_later_evidence_and_report_commit(self):
        started = asyncio.Event()
        release = asyncio.Event()
        denied = []

        async def use_after_revoke(snapshot, read_evidence, *_):
            started.set()
            await release.wait()
            try:
                read_evidence()
            except PermissionError:
                denied.append(True)
            return {"report": make_report(snapshot), "usage": {"input_tokens": 1, "output_tokens": 1},
                    "provider_state": "stopped"}

        self.provider.behavior = use_after_revoke
        job = self.create()

        async def scenario():
            task = asyncio.create_task(self.jobs.run(principal=self.recipient, agent_id="agent-a",
                                                     job_id=job["job_id"]))
            await started.wait()
            self.diagnostics.revoke(principal=self.owner, agent_id="agent-a",
                                    permission_id=self.permission["permission_id"])
            release.set()
            return await task

        result = asyncio.run(scenario())
        self.assertEqual(denied, [True])
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["provider_state"], "stopped")
        self.assertEqual(result["reason"], "authority_revoked")
        self.assertIsNone(result["report_id"])
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM diagnosis_reports").fetchone()[0], 0)

    def test_cross_thread_cancel_signals_task_running_on_event_loop(self):
        started = threading.Event()

        async def wait_until_cancelled(snapshot, *_):
            started.set()
            await asyncio.Event().wait()

        self.provider.behavior = wait_until_cancelled
        job = self.create()

        async def scenario():
            task = asyncio.create_task(self.jobs.run(principal=self.recipient, agent_id="agent-a",
                                                     job_id=job["job_id"]))
            while not started.is_set():
                await asyncio.sleep(0.001)
            result = await asyncio.to_thread(self.cancel, None, None, job)
            self.assertEqual(result["state"], "cancel_requested")
            with self.assertRaises(asyncio.CancelledError):
                await task
            return self.jobs.read(principal=self.recipient, agent_id="agent-a", job_id=job["job_id"])

        result = asyncio.run(scenario())
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(result["provider_state"], "unknown")
        self.assertIsNone(result["history"][0]["usage_json"])

    def test_caller_task_cancellation_that_provider_swallows_still_fences_result(self):
        started = asyncio.Event()
        after_cancel = asyncio.Event()
        release = asyncio.Event()

        async def swallow_cancel(snapshot, *_):
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                after_cancel.set()
                await release.wait()
            return {"report": make_report(snapshot), "usage": {"input_tokens": 1, "output_tokens": 1},
                    "provider_state": "stopped"}

        self.provider.behavior = swallow_cancel
        job = self.create()

        async def scenario():
            task = asyncio.create_task(self.jobs.run(principal=self.recipient, agent_id="agent-a",
                                                     job_id=job["job_id"]))
            await started.wait()
            task.cancel()
            await asyncio.wait_for(after_cancel.wait(), timeout=1)
            release.set()
            return await task

        result = asyncio.run(scenario())
        self.assertEqual(result["state"], "interrupted")
        self.assertEqual(result["provider_state"], "stopped")
        self.assertIsNone(result["report_id"])
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM diagnosis_reports").fetchone()[0], 0)

    def test_timeout_that_provider_swallows_does_not_publish_late_success(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def swallow_timeout(snapshot, *_):
            started.set()
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                await release.wait()
            return {"report": make_report(snapshot), "usage": {"input_tokens": 1, "output_tokens": 1},
                    "provider_state": "stopped"}

        self.provider.behavior = swallow_timeout
        job = self.create(total_seconds=1)

        async def scenario():
            task = asyncio.create_task(self.jobs.run(principal=self.recipient, agent_id="agent-a",
                                                     job_id=job["job_id"]))
            await started.wait()
            await asyncio.sleep(1.05)
            timed_out = self.jobs.read(principal=self.recipient, agent_id="agent-a", job_id=job["job_id"])
            self.assertEqual(timed_out["state"], "interrupted")
            self.assertEqual(timed_out["provider_state"], "unknown")
            release.set()
            return await task

        result = asyncio.run(scenario())
        self.assertIn(result["state"], {"interrupted", "exhausted"}, result)
        self.assertEqual(result["provider_state"], "stopped")
        self.assertIsNone(result["report_id"])
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM diagnosis_reports").fetchone()[0], 0)

    def test_cancel_reports_race_when_update_affects_no_row(self):
        job = self.create()
        # 模拟另一路已推进作业状态；让 _control 仍读到旧的 queued 快照，
        # 制造「读取后状态/代次被并发改变」的 CAS 竞争窗口。
        with self.store._tx() as cur:
            cur.execute("UPDATE governance_jobs SET state='succeeded' WHERE job_id=?", (job["job_id"],))
        original_control = self.jobs._control

        def stale_control(cur, **kwargs):
            row = dict(original_control(cur, **kwargs))
            row["state"] = "queued"
            return row

        self.jobs._control = stale_control
        with self.assertRaisesRegex(ValueError, "取消竞争"):
            self.cancel(job=job)
        # 抛错绝不把真实状态覆盖回 queued/cancelled。
        self.assertEqual(
            self.jobs.read(principal=self.recipient, agent_id="agent-a", job_id=job["job_id"])["state"],
            "succeeded")

    def test_concurrent_cancel_is_never_a_silent_no_op(self):
        second_store = SqliteStore(self.path, owner_id="worker-b")
        second_jobs = GovernanceJobs(DiagnosticsService(second_store), provider=self.provider)
        self.addCleanup(second_store.close)
        job = self.create()
        gate = threading.Barrier(3)
        outcomes = []

        def cancel_with(service):
            gate.wait()
            try:
                result = service.cancel(principal=self.recipient, agent_id="agent-a", job_id=job["job_id"])
                outcomes.append(result["state"])
            except ValueError:
                outcomes.append("race_rejected")

        threads = [threading.Thread(target=cancel_with, args=(s,)) for s in (self.jobs, second_jobs)]
        for thread in threads:
            thread.start()
        gate.wait()
        for thread in threads:
            thread.join(timeout=3)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        # 每个结果都必须明确：取消成功或竞争被拒，绝不静默返回无效果。
        self.assertTrue(all(outcome in {"cancelled", "race_rejected"} for outcome in outcomes), outcomes)
        self.assertEqual(
            self.jobs.read(principal=self.recipient, agent_id="agent-a", job_id=job["job_id"])["state"],
            "cancelled")


class TestGovernanceJobsConcurrency(GovernanceJobsCase):
    def test_two_sqlite_stores_compare_and_swap_only_one_attempt(self):
        second_store = SqliteStore(self.path, owner_id="worker-b")
        second_jobs = GovernanceJobs(DiagnosticsService(second_store), provider=self.provider)
        self.addCleanup(second_store.close)
        job = self.create()
        gate = threading.Barrier(3)
        outcomes = []

        def run_with(service):
            gate.wait()
            try:
                value = asyncio.run(service.run(principal=self.recipient, agent_id="agent-a", job_id=job["job_id"]))
                outcomes.append(value["state"])
            except ValueError:
                outcomes.append("rejected")

        threads = [threading.Thread(target=run_with, args=(service,)) for service in (self.jobs, second_jobs)]
        for thread in threads:
            thread.start()
        gate.wait()
        for thread in threads:
            thread.join(timeout=3)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertCountEqual(outcomes, ["succeeded", "rejected"])
        self.assertEqual(self.provider.calls, 1)
        result = self.jobs.read(principal=self.recipient, agent_id="agent-a", job_id=job["job_id"])
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(len(result["history"]), 1)

    def test_report_insert_and_success_cas_rollback_as_one_transaction(self):
        job = self.create()
        calls = 0

        def fail_before_commit():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("transaction failed")

        async def enable_failure(snapshot, *_):
            self.store.before_commit = fail_before_commit
            return {"report": make_report(snapshot), "usage": {"input_tokens": 1, "output_tokens": 1},
                    "provider_state": "stopped"}

        self.provider.behavior = enable_failure
        result = self.run_job(job)
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM diagnosis_reports").fetchone()[0], 0)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["provider_state"], "stopped")
        self.assertEqual(result["reason"], "result_commit_failed")
        self.assertIsNone(result["report_id"])
        self.assertEqual(result["reserved_tokens"], job["frozen"]["attempt_tokens"])
        self.assertEqual(result["history"][0]["provider_state"], "stopped")


class TestGovernanceProviderRegistration(GovernanceJobsCase):
    """服务端 Provider 登记：替身不得冒充真实 Provider（plan :36/:41）。"""

    @staticmethod
    def _descriptor(**overrides):
        descriptor = {
            "provider_id": "test-provider",
            "provider_kind": PROVIDER_KIND_OFFLINE_SCRIPTED,
            "version": PROVIDER_VERSIONS[PROVIDER_KIND_OFFLINE_SCRIPTED],
            "contract_hash": PROVIDER_CONTRACT_HASH,
        }
        descriptor.update(overrides)
        return descriptor

    def test_missing_provider_kind_is_rejected(self):
        descriptor = self._descriptor()
        del descriptor["provider_kind"]
        self.provider.descriptor = descriptor
        with self.assertRaisesRegex(ValueError, "类别"):
            self.create(idempotency_key="missing-kind")
        self.assertEqual(self.store._conn.execute(
            "SELECT COUNT(*) FROM governance_jobs").fetchone()[0], 0)

    def test_self_reported_real_kind_is_rejected(self):
        self.provider.descriptor = self._descriptor(
            provider_kind=PROVIDER_KIND_REAL_HARNESS,
            version=PROVIDER_VERSIONS[PROVIDER_KIND_REAL_HARNESS],
        )
        with self.assertRaisesRegex(ValueError, "类别"):
            self.create(idempotency_key="self-reported-real")
        self.assertEqual(self.store._conn.execute(
            "SELECT COUNT(*) FROM governance_jobs").fetchone()[0], 0)

    def test_stale_or_wrong_contract_hash_is_rejected(self):
        for bad in ("0" * 64, "governance-provider-contract-v1", "wrong-hash"):
            with self.subTest(bad=bad):
                self.provider.descriptor = self._descriptor(contract_hash=bad)
                with self.assertRaisesRegex(ValueError, "合同"):
                    self.create(idempotency_key=f"bad-hash-{bad[:6]}")
        self.assertEqual(self.store._conn.execute(
            "SELECT COUNT(*) FROM governance_jobs").fetchone()[0], 0)

    def test_version_must_match_declared_kind(self):
        # 替身不得贴用真实 harness 的版本号。
        self.provider.descriptor = self._descriptor(
            version=PROVIDER_VERSIONS[PROVIDER_KIND_REAL_HARNESS])
        with self.assertRaisesRegex(ValueError, "版本"):
            self.create(idempotency_key="version-mismatch")

    def test_offline_scripted_success_is_registered_as_offline_evidence(self):
        job = self.create()
        self.assertEqual(job["frozen"]["provider"]["provider_kind"], PROVIDER_KIND_OFFLINE_SCRIPTED)
        self.assertEqual(job["frozen"]["evidence_class"], "offline_scripted")
        result = self.run_job(job)
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["frozen"]["evidence_class"], "offline_scripted")
        self.assertNotIn("real", result["frozen"]["evidence_class"])
        self.assertNotEqual(result["frozen"]["provider"]["version"],
                            PROVIDER_VERSIONS[PROVIDER_KIND_REAL_HARNESS])


if __name__ == "__main__":
    unittest.main()
