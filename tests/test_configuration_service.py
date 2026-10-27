from __future__ import annotations

from copy import deepcopy
import os
import tempfile
import unittest

from loomrise.configuration import (
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
