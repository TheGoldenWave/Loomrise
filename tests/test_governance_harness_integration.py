"""Offline AgentScope diagnosis loop through the durable governance job."""

import json
from pathlib import Path
import tempfile
import unittest

from loomrise.adapters.agentscope_runtime import ScriptedChatModel
from loomrise.adapters.harness import AgentScopeDiagnosisProvider
from loomrise.configuration import ConfigurationPrincipal
from loomrise.diagnostics import DiagnosticsService, REPORT_CATEGORIES, REPORT_SCHEMA_VERSION
from loomrise.durable_store import SqliteStore
from loomrise.governance_jobs import GovernanceJobs


class GovernanceHarnessIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_scripted_agentscope_report_is_committed_by_the_job(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(str(Path(directory) / "integration.db"))
            self.addCleanup(store.close)
            diagnostics = DiagnosticsService(store)
            owner = ConfigurationPrincipal("tenant-a", "owner-a", "owner", ("agent-a",))
            recipient = ConfigurationPrincipal("tenant-a", "editor-a", "editor", ("agent-a",))
            permission = diagnostics.issue(
                principal=owner,
                agent_id="agent-a",
                recipient_actor_id=recipient.actor_id,
                run_ids=[],
                case_ids=["c1_consult_success"],
            )
            snapshot = diagnostics.read_evidence(
                principal=recipient,
                agent_id="agent-a",
                permission_id=permission["permission_id"],
            )
            report = {
                "schema_version": REPORT_SCHEMA_VERSION,
                "status": "proposal",
                "findings": [],
                "insufficient_categories": list(REPORT_CATEGORIES),
                "limitations": snapshot["limitations"],
            }
            model = ScriptedChatModel(
                model_name="scripted-diagnosis-test",
                script=[
                    {"tool": "diagnosis_evidence"},
                    {"text": json.dumps(report, ensure_ascii=False)},
                ],
            )
            provider = AgentScopeDiagnosisProvider(
                {
                    "provider_id": "scripted-integration-test",
                    "model": "scripted-diagnosis-test",
                    "base_url": "https://provider.example.invalid/v1",
                    "key": "test-only-credential",
                    "max_output_tokens": 512,
                },
                model=model,
            )
            jobs = GovernanceJobs(diagnostics, provider=provider)
            job = jobs.create(
                principal=recipient,
                agent_id="agent-a",
                permission_id=permission["permission_id"],
                idempotency_key="agentscope-integration-1",
            )

            result = await jobs.run(
                principal=recipient,
                agent_id="agent-a",
                job_id=job["job_id"],
            )

            self.assertEqual(result["state"], "succeeded")
            self.assertEqual(result["provider_state"], "stopped")
            self.assertEqual(len(model.calls), 2)
            self.assertIsNotNone(result["report_id"])
            # 替身成功只登记为 offline/scripted 证据，绝不写入真实 Provider 分类。
            self.assertEqual(result["frozen"]["provider"]["provider_kind"], "offline_scripted")
            self.assertEqual(result["frozen"]["evidence_class"], "offline_scripted")
            self.assertNotIn("real", result["frozen"]["evidence_class"])
            self.assertNotEqual(result["frozen"]["provider"]["version"],
                                "agentscope-diagnosis-v1")
            saved = diagnostics.read_report(
                principal=recipient,
                agent_id="agent-a",
                report_id=result["report_id"],
            )
            self.assertEqual(saved["report"], report)
            usage = json.loads(result["history"][0]["usage_json"])
            self.assertGreater(usage["input_tokens"], 0)
            self.assertEqual(usage["output_tokens"], 128)


if __name__ == "__main__":
    unittest.main()
