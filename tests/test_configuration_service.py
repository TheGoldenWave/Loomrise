from __future__ import annotations

import base64
from copy import deepcopy
import os
import tempfile
import unittest
from unittest.mock import patch

from loomrise.configuration import (
    ConfigurationApplication,
    ConfigurationPrincipal,
    ConfigurationService,
    ConfigurationValidationError,
    RevisionConflict,
    StableVersionError,
    field_diff,
)
from loomrise.durable_store import SqliteStore


def unit(unit_id="collect-contact", *, load_mode="routed"):
    return {
        "unit_id": unit_id,
        "version": 1,
        "load_mode": load_mode,
        "entry_ports": [{"port": "from_start", "requires": []}],
        "reads": ["customer.name"],
        "writes": ["customer.phone"],
        "exit_ports": [{
            "port": "done",
            "completion": {"deterministic": {"field": "customer.phone", "op": "exists"}},
            "exits": [unit_id],
        }],
        "on_event": [],
        "fallback": {"kind": "clarify"},
        "max_rounds": 3,
        "body": {},
    }


def spec(goal="收集预约信息", *, load_mode="routed"):
    return {
        "persona": {
            "name": "课程咨询专家",
            "goal": goal,
            "audience": "课程访客",
            "fields": {
                "customer.name": {"type": "string"},
                "customer.phone": {"type": "string"},
            },
            "entry_unit_ids": ["collect-contact"],
        },
        "units": [unit(load_mode=load_mode)],
        "g0_gates": [],
        "hard_rules": [],
        "task_blueprints": [],
    }


class ConfigurationServiceCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "loomrise.db")
        self.store = SqliteStore(self.path)
        self.service = ConfigurationService(self.store)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.store.close)

    def seed(self):
        self.service.register_stable_version(
            tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
            config=spec("原始目标"),
        )
        return self.service.create_draft(
            tenant_id="tenant-a", agent_id="expert-a", base_version_id="v1",
            config=spec("原始目标"),
        )


class TestDraftLifecycle(ConfigurationServiceCase):
    def test_draft_creation_is_idempotent_for_the_same_base(self):
        draft = self.seed()

        repeated = self.service.create_draft_from_stable(
            tenant_id="tenant-a", agent_id="expert-a", base_version_id="v1",
        )

        self.assertEqual(repeated, draft)
        self.service.register_stable_version(
            tenant_id="tenant-a", agent_id="expert-a", version_id="v2",
            config=spec("第二版"),
        )
        with self.assertRaisesRegex(ValueError, "已有基于其他稳定版本"):
            self.service.create_draft_from_stable(
                tenant_id="tenant-a", agent_id="expert-a", base_version_id="v2",
            )
        self.assertEqual(self.service.get_draft(
            tenant_id="tenant-a", agent_id="expert-a",
        )["config"]["persona"]["goal"], "原始目标")

    def test_service_rejects_non_object_config_and_invalid_revisions(self):
        with self.assertRaisesRegex(ValueError, "JSON 对象"):
            self.service.register_stable_version(
                tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
                config=[],
            )
        draft = self.seed()
        with self.assertRaisesRegex(ValueError, "JSON 对象"):
            self.service.save_draft(
                tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
                config=[],
            )
        with self.assertRaisesRegex(ValueError, "正整数"):
            self.service.save_draft(
                tenant_id="tenant-a", agent_id="expert-a", expected_revision=True,
                config=spec("不应写入"),
            )
        with self.assertRaisesRegex(ValueError, "对象数组"):
            self.service.patch_draft(
                tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
                changes="not-an-array",
            )
        self.assertEqual(self.service.get_draft(
            tenant_id="tenant-a", agent_id="expert-a",
        ), draft)

    def test_draft_revision_conflict_and_frozen_candidate_survive_restart(self):
        draft = self.seed()
        self.assertEqual(draft["revision"], 1)

        updated = spec("更新后的目标")
        saved = self.service.save_draft(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            config=updated,
        )
        self.assertEqual(saved["revision"], 2)
        self.assertEqual(saved["diff"], [{
            "path": "$.persona.goal", "before": "原始目标", "after": "更新后的目标",
        }])

        with self.assertRaises(RevisionConflict) as caught:
            self.service.save_draft(
                tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
                config=spec("过期写入"),
            )
        self.assertEqual(caught.exception.current["revision"], 2)
        self.assertEqual(caught.exception.current["config"]["persona"]["goal"], "更新后的目标")

        candidate = self.service.freeze_candidate(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=2,
            idempotency_key="freeze-v1-r2",
        )
        self.assertEqual(candidate["source_revision"], 2)
        self.assertEqual(candidate["status"], "frozen")
        self.assertEqual(candidate["diff"], [{
            "path": "$.persona.goal", "before": "原始目标", "after": "更新后的目标",
        }])

        self.service.save_draft(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=2,
            config=spec("继续修改草稿"),
        )
        self.assertEqual(candidate["config"]["persona"]["goal"], "更新后的目标")
        self.assertEqual(self.service.freeze_candidate(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=2,
            idempotency_key="freeze-v1-r2",
        ), candidate)

        self.store.close()
        reopened = SqliteStore(self.path)
        try:
            service = ConfigurationService(reopened)
            persisted = service.get_draft(tenant_id="tenant-a", agent_id="expert-a")
            replayed = service.get_candidate(
                tenant_id="tenant-a", agent_id="expert-a", candidate_id=candidate["candidate_id"],
            )
            self.assertEqual(persisted["revision"], 3)
            self.assertEqual(persisted["config"]["persona"]["goal"], "继续修改草稿")
            self.assertEqual(replayed, candidate)
        finally:
            reopened.close()

    def test_freeze_rejects_invalid_config_without_creating_candidate(self):
        self.seed()
        self.service.save_draft(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            config=spec("不支持并发", load_mode="concurrent"),
        )

        with self.assertRaises(ConfigurationValidationError) as caught:
            self.service.freeze_candidate(
                tenant_id="tenant-a", agent_id="expert-a", expected_revision=2,
                idempotency_key="invalid-freeze",
            )
        self.assertIn("$.units[0].load_mode", [issue["path"] for issue in caught.exception.issues])
        self.assertEqual(self.service.list_candidates(tenant_id="tenant-a", agent_id="expert-a"), [])

    def test_candidate_idempotency_rejects_key_reuse_with_different_source(self):
        self.seed()
        first = self.service.freeze_candidate(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            idempotency_key="freeze-once",
        )
        changed = self.service.save_draft(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            config=spec("其他目标"),
        )
        with self.assertRaises(ValueError):
            self.service.freeze_candidate(
                tenant_id="tenant-a", agent_id="expert-a", expected_revision=changed["revision"],
                idempotency_key="freeze-once",
            )
        self.assertEqual(len(self.service.list_candidates(tenant_id="tenant-a", agent_id="expert-a")), 1)

    def test_release_checklist_runs_and_keeps_unimplemented_evidence_pending(self):
        self.seed()
        candidate = self.service.freeze_candidate(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            idempotency_key="release-checklist",
        )

        checklist = self.service.release_checklist(
            tenant_id="tenant-a", agent_id="expert-a",
            candidate_id=candidate["candidate_id"],
        )

        self.assertEqual(checklist["progress"], {
            "passed": 2, "failed": 0, "pending": 8, "total": 10,
        })
        self.assertFalse(checklist["ready"])
        self.assertFalse(checklist["publish_enabled"])
        self.assertEqual(
            [item["key"] for item in checklist["checks"]],
            [
                "candidate_frozen", "configuration_valid", "sources_identified",
                "source_permissions", "knowledge_ready", "fixed_samples",
                "fixed_samples_passed", "sandbox_selected", "entry_version_bound",
                "human_approval",
            ],
        )

    def test_release_checklist_requires_authorized_candidate_scope(self):
        self.seed()
        candidate = self.service.freeze_candidate(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            idempotency_key="release-scope",
        )
        app = ConfigurationApplication(self.service)
        external = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="agent", role="external_agent",
            agent_ids=("expert-b",),
        )

        response = app.execute(
            principal=external, action="release.checklist",
            payload={"agent_id": "expert-a", "candidate_id": candidate["candidate_id"]},
        )

        self.assertEqual(response["error"]["code"], "forbidden")

    def test_release_approval_and_publish_are_owner_only_and_prechecks_block_them(self):
        self.seed()
        candidate = self.service.freeze_candidate(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            idempotency_key="release-owner-blocked",
        )
        app = ConfigurationApplication(self.service)
        editor = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="editor", role="editor",
            agent_ids=("expert-a",),
        )
        owner = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="owner", role="owner",
            agent_ids=("expert-a",),
        )
        payload = {
            "agent_id": "expert-a", "candidate_id": candidate["candidate_id"],
            "entry_id": "visitor-entry", "version_id": "sandbox-v1",
        }

        denied = app.execute(principal=editor, action="release.approve", payload=payload)
        self.assertEqual(denied["error"]["code"], "forbidden")
        approval = app.execute(principal=owner, action="release.approve", payload=payload)
        self.assertEqual(approval["error"]["code"], "release_blocked")
        published = app.execute(principal=owner, action="release.publish", payload=payload)
        self.assertEqual(published["error"]["code"], "release_blocked")
        missing = app.execute(
            principal=owner, action="release.entry.get",
            payload={"agent_id": "expert-a", "entry_id": "visitor-entry"},
        )
        self.assertEqual(missing["error"]["code"], "not_found")

    def test_sandbox_publish_binds_immutable_candidate_not_later_draft(self):
        self.seed()
        candidate = self.service.freeze_candidate(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            idempotency_key="release-storage-binding",
        )
        self.store.approve_release_candidate(
            tenant_id="tenant-a", agent_id="expert-a",
            candidate_id=candidate["candidate_id"], content_hash=candidate["content_hash"],
            environment="sandbox", entry_id="visitor-entry", version_id="sandbox-v1",
            approved_by="owner",
        )

        binding = self.store.publish_sandbox_candidate(
            tenant_id="tenant-a", agent_id="expert-a",
            candidate_id=candidate["candidate_id"], entry_id="visitor-entry",
            version_id="sandbox-v1",
        )
        self.assertEqual(binding["version_id"], "sandbox-v1")
        self.service.save_draft(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            config=spec("后续草稿"),
        )
        entry = self.service.get_sandbox_entry(
            tenant_id="tenant-a", agent_id="expert-a", entry_id="visitor-entry",
        )
        self.assertEqual(entry["version_id"], "sandbox-v1")
        self.assertEqual(entry["config"]["persona"]["goal"], "原始目标")

    def test_faq_ingest_retry_revoke_and_cache_invalidation(self):
        source = self.service.create_knowledge_source(
            tenant_id="tenant-a", agent_id="expert-a", kind="faq",
            locator="退费规则：开课前可申请。\n\n改期规则：提前三天联系。",
            display_name="FAQ", authorization="owned",
        )
        ready = self.service.ingest_knowledge_source(
            tenant_id="tenant-a", agent_id="expert-a", source_id=source["source_id"],
        )
        self.assertEqual(ready["state"], "ready", ready)
        self.assertEqual(len(self.service.search_ingested_knowledge(
            tenant_id="tenant-a", agent_id="expert-a", query="退费规则",
        )), 1)

        revoked = self.service.revoke_knowledge_source(
            tenant_id="tenant-a", agent_id="expert-a", source_id=source["source_id"],
        )
        self.assertEqual(revoked["state"], "revoked")
        self.assertEqual(self.service.search_ingested_knowledge(
            tenant_id="tenant-a", agent_id="expert-a", query="退费规则",
        ), [])

    def test_knowledge_actions_enforce_roles_and_revoke_blocks_runtime_resolution(self):
        app = ConfigurationApplication(self.service)
        viewer = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="viewer", role="viewer", agent_ids=("expert-a",),
        )
        editor = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="editor", role="editor", agent_ids=("expert-a",),
        )
        external = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="agent", role="external_agent", agent_ids=("expert-a",),
        )
        created = app.execute(principal=viewer, action="knowledge.source.create", payload={
            "agent_id": "expert-a", "kind": "faq", "locator": "退费规则：开课前可退。",
            "display_name": "FAQ", "authorization": "owned",
        })
        self.assertEqual(created["error"]["code"], "forbidden")
        created = app.execute(principal=editor, action="knowledge.source.create", payload={
            "agent_id": "expert-a", "kind": "faq", "locator": "退费规则：开课前可退。",
            "display_name": "FAQ", "authorization": "owned",
        })["result"]
        denied = app.execute(principal=external, action="knowledge.revoke", payload={
            "agent_id": "expert-a", "source_id": created["source_id"],
        })
        self.assertEqual(denied["error"]["code"], "forbidden")
        ingested = app.execute(principal=editor, action="knowledge.ingest", payload={
            "agent_id": "expert-a", "source_id": created["source_id"],
        })
        self.assertTrue(ingested["ok"])

        self.seed()
        candidate = self.service.freeze_candidate(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            idempotency_key="stale-runtime-check",
        )
        self.store.approve_release_candidate(
            tenant_id="tenant-a", agent_id="expert-a", candidate_id=candidate["candidate_id"],
            content_hash=candidate["content_hash"], environment="sandbox",
            entry_id="visitor-entry", version_id="sandbox-v1", approved_by="owner",
        )
        self.store.publish_sandbox_candidate(
            tenant_id="tenant-a", agent_id="expert-a", candidate_id=candidate["candidate_id"],
            entry_id="visitor-entry", version_id="sandbox-v1",
        )
        revoked = app.execute(principal=editor, action="knowledge.revoke", payload={
            "agent_id": "expert-a", "source_id": created["source_id"],
        })
        self.assertEqual(revoked["result"]["affected_versions"], ["sandbox-v1"])
        audit_read = app.execute(principal=viewer, action="release.entry.get", payload={
            "agent_id": "expert-a", "entry_id": "visitor-entry",
        })
        self.assertEqual(audit_read["result"]["knowledge_state"], "stale")
        runtime = app.execute(principal=viewer, action="release.entry.resolve", payload={
            "agent_id": "expert-a", "entry_id": "visitor-entry",
        })
        self.assertEqual(runtime["error"]["code"], "release_blocked")

    def test_failed_file_ingest_is_distinct_and_retryable(self):
        source = self.service.create_knowledge_source(
            tenant_id="tenant-a", agent_id="expert-a", kind="file",
            locator=os.path.join(self.temp.name, "missing.txt"),
            display_name="missing.txt", authorization="licensed",
        )
        failed = self.service.ingest_knowledge_source(
            tenant_id="tenant-a", agent_id="expert-a", source_id=source["source_id"],
        )
        self.assertEqual(failed["state"], "failed")
        retried = self.service.retry_knowledge_source(
            tenant_id="tenant-a", agent_id="expert-a", source_id=source["source_id"],
        )
        self.assertEqual(retried["state"], "failed")
        self.assertEqual(retried["attempt_count"], 2)

    def test_uploaded_text_file_ingests_retries_and_revokes_without_exposing_source_bytes(self):
        self.seed()
        app = ConfigurationApplication(self.service)
        editor = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="editor", role="editor", agent_ids=("expert-a",),
        )
        payload = {
            "agent_id": "expert-a", "kind": "file", "filename": "policy.md",
            "display_name": "报名政策", "authorization": "licensed",
            "content_base64": base64.b64encode("报名需提前两天预约。".encode()).decode(),
        }

        created = app.execute(
            principal=editor, action="knowledge.source.create", payload=payload,
        )["result"]

        self.assertNotIn("uploaded_content", created)
        self.assertEqual(created["locator"], "policy.md")
        ready = app.execute(principal=editor, action="knowledge.ingest", payload={
            "agent_id": "expert-a", "source_id": created["source_id"],
        })["result"]
        self.assertEqual(ready["state"], "ready", ready)
        self.assertEqual(self.service.search_ingested_knowledge(
            tenant_id="tenant-a", agent_id="expert-a", query="提前两天",
        )[0]["text"], "报名需提前两天预约。")
        persisted = self.store.knowledge_source(
            tenant_id="tenant-a", agent_id="expert-a", source_id=created["source_id"],
        )
        self.assertNotIn("uploaded_content", persisted)
        stored_bytes = self.store._conn.execute(
            "SELECT uploaded_content FROM knowledge_sources WHERE source_id=?",
            (created["source_id"],),
        ).fetchone()[0]
        self.assertIsNone(stored_bytes)

        revoked = app.execute(principal=editor, action="knowledge.revoke", payload={
            "agent_id": "expert-a", "source_id": created["source_id"],
        })["result"]
        self.assertEqual(revoked["state"], "revoked")
        self.assertEqual(self.service.search_ingested_knowledge(
            tenant_id="tenant-a", agent_id="expert-a", query="提前两天",
        ), [])

    def test_failed_uploaded_file_retains_private_bytes_for_explicit_retry(self):
        source = self.service.create_knowledge_source(
            tenant_id="tenant-a", agent_id="expert-a", kind="file", locator="bad.txt",
            display_name="bad.txt", authorization="owned", uploaded_content=bytes([255]),
        )
        failed = self.service.ingest_knowledge_source(
            tenant_id="tenant-a", agent_id="expert-a", source_id=source["source_id"],
        )
        self.assertEqual(failed["state"], "failed")
        public_record = self.store.knowledge_source(
            tenant_id="tenant-a", agent_id="expert-a", source_id=source["source_id"],
        )
        self.assertNotIn("uploaded_content", public_record)
        self.assertEqual(self.store._conn.execute(
            "SELECT uploaded_content FROM knowledge_sources WHERE source_id=?",
            (source["source_id"],),
        ).fetchone()[0], bytes([255]))
        retried = self.service.retry_knowledge_source(
            tenant_id="tenant-a", agent_id="expert-a", source_id=source["source_id"],
        )
        self.assertEqual(retried["state"], "failed")
        self.assertEqual(retried["attempt_count"], 2)

    def test_non_file_knowledge_source_cannot_carry_uploaded_bytes(self):
        with self.assertRaisesRegex(ValueError, "只有文件来源"):
            self.service.create_knowledge_source(
                tenant_id="tenant-a", agent_id="expert-a", kind="faq", locator="FAQ",
                display_name="FAQ", authorization="owned", uploaded_content=b"not a file",
            )

    def test_uploaded_file_rejects_oversize_payload_before_decoding(self):
        self.seed()
        app = ConfigurationApplication(self.service)
        editor = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="editor", role="editor", agent_ids=("expert-a",),
        )
        response = app.execute(principal=editor, action="knowledge.source.create", payload={
            "agent_id": "expert-a", "kind": "file", "filename": "policy.txt",
            "display_name": "政策", "authorization": "owned",
            "content_base64": "A" * 7_000_000,
        })
        self.assertEqual(response["error"]["code"], "invalid_request")
        self.assertEqual(self.store.list_knowledge_sources(
            tenant_id="tenant-a", agent_id="expert-a",
        ), [])

    def test_url_ingest_records_network_failure_and_can_be_retried(self):
        source = self.service.create_knowledge_source(
            tenant_id="tenant-a", agent_id="expert-a", kind="url",
            locator="https://example.test/faq", display_name="FAQ URL",
            authorization="licensed",
        )
        with patch("loomrise.configuration.fetch_https_text", side_effect=OSError("fixture DNS failure")):
            result = self.service.ingest_knowledge_source(
                tenant_id="tenant-a", agent_id="expert-a", source_id=source["source_id"],
            )
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "parse_failed")

    def test_stable_version_cannot_be_modified_or_deleted(self):
        self.seed()

        with self.assertRaises(StableVersionError):
            self.service.update_stable_version(
                tenant_id="tenant-a", agent_id="expert-a", version_id="v1", config=spec("覆盖"),
            )
        with self.assertRaises(StableVersionError):
            self.service.delete_stable_version(
                tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
            )
        self.assertEqual(self.service.get_stable_version(
            tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
        )["config"]["persona"]["goal"], "原始目标")

    def test_config_is_copied_at_service_boundary(self):
        original = spec()
        self.service.create_draft(
            tenant_id="tenant-a", agent_id="expert-a", config=original,
        )
        original["persona"] = {"goal": "外部修改"}
        self.assertEqual(self.service.get_draft(
            tenant_id="tenant-a", agent_id="expert-a",
        )["config"]["persona"]["goal"], "收集预约信息")


class TestFieldDiff(unittest.TestCase):
    def test_boolean_and_number_are_distinct_json_values(self):
        self.assertEqual(field_diff({"enabled": True}, {"enabled": 1}), [{
            "path": "$.enabled", "before": True, "after": 1,
        }])
        self.assertEqual(field_diff({"enabled": 0}, {"enabled": False}), [{
            "path": "$.enabled", "before": 0, "after": False,
        }])

    def test_missing_fields_are_distinct_from_json_values_and_report_presence(self):
        marker = {"$missing": True}
        self.assertEqual(field_diff({}, {"x": marker}), [{
            "path": "$.x", "before": None, "after": marker,
            "before_exists": False, "after_exists": True,
        }])
        self.assertEqual(field_diff({"x": marker}, {}), [{
            "path": "$.x", "before": marker, "after": None,
            "before_exists": True, "after_exists": False,
        }])
        self.assertEqual(field_diff({"x": None}, {}), [{
            "path": "$.x", "before": None, "after": None,
            "before_exists": True, "after_exists": False,
        }])

    def test_nested_object_and_array_additions_and_removals_keep_json_paths(self):
        self.assertEqual(field_diff(
            {"object": {"kept": 1, "removed": 2}},
            {"object": {"kept": 1}},
        ), [{
            "path": "$.object.removed", "before": 2, "after": None,
            "before_exists": True, "after_exists": False,
        }])
        self.assertEqual(field_diff(
            {"items": ["kept"]}, {"items": ["kept", {"$missing": True}]},
        ), [{
            "path": "$.items[1]", "before": None, "after": {"$missing": True},
            "before_exists": False, "after_exists": True,
        }])


if __name__ == "__main__":
    unittest.main()
