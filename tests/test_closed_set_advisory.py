from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from loomrise.configuration import (
    ConfigurationApplication, ConfigurationPrincipal, ConfigurationService, closed_set_advisory,
)
from loomrise.durable_store import SqliteStore


def wide_graph_config(count=6):
    units = []
    nodes = []
    for index in range(count + 1):
        unit_id = f"unit-{index}"
        units.append({
            "unit_id": unit_id, "version": 1, "load_mode": "routed",
            "entry_ports": [{"port": "from_start", "requires": []}],
            "reads": [], "writes": [],
            "exit_ports": [{"port": "done", "completion": {"deterministic": {}}, "exits": ["self.done"]}],
            "on_event": [], "fallback": {"kind": "human"}, "max_rounds": 1,
            "body": {"kind": "say", "text": "测试固定内容", "verbatim_reason": "本机测试"},
        })
        nodes.append({"id": f"node-{index}", "unit_ref": {"unit_id": unit_id, "version": 1}})
    edges = [{"id": f"edge-{index}", "from": "node-0.done", "to": f"node-{index}.from_start", "condition": {}}
             for index in range(1, count + 1)]
    edges.extend({"id": f"finish-{index}", "from": f"node-{index}.done", "to": "end", "condition": {}}
                 for index in range(1, count + 1))
    return {
        "persona": {"fields": {}}, "units": units,
        "g0_gates": [], "hard_rules": [], "task_blueprints": [],
        "orchestration": {
            "schema_version": "unit-graph-v1", "kind": "graph", "routing": {"mode": "llm"},
            "nodes": nodes, "entry": "node-0.from_start", "input_fields": [],
            "edges": edges, "on_event": [], "fallback": {"kind": "human"},
        },
    }


class ClosedSetAdvisoryAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "advisory.db")
        self.store = SqliteStore(self.path)
        self.service = ConfigurationService(self.store)
        self.service.register_stable_version(
            tenant_id="tenant-a", agent_id="expert-a", version_id="v1", config=wide_graph_config(),
        )
        self.service.create_draft_from_stable(
            tenant_id="tenant-a", agent_id="expert-a", base_version_id="v1",
        )
        self.application = ConfigurationApplication(self.service)
        self.addCleanup(self.store.close)
        self.addCleanup(self.temp.cleanup)

    def execute(self, role="editor", actor="operator-1", action="advisory.dismiss", payload=None):
        return self.application.execute(
            principal=ConfigurationPrincipal("tenant-a", actor, role, ("expert-a",)),
            action=action,
            payload={"agent_id": "expert-a", **(payload or {})},
        )

    def test_dismissal_is_server_counted_revision_scoped_and_outside_configuration(self):
        before = self.service.get_draft(tenant_id="tenant-a", agent_id="expert-a")
        response = self.execute(payload={"expected_revision": 1, "layer_path": []})

        self.assertTrue(response["ok"])
        dismissal = response["result"]
        self.assertEqual(dismissal["source_revision"], 1)
        self.assertEqual(dismissal["advisory_key"], "closed-set:[]")
        self.assertEqual(dismissal["closed_set_size"], 7)
        self.assertEqual(dismissal["actor_id"], "operator-1")
        self.assertTrue(dismissal["created_at"])
        after = self.service.get_draft(tenant_id="tenant-a", agent_id="expert-a")
        self.assertEqual(after["config"], before["config"])
        self.assertEqual(after["revision"], before["revision"])

        self.assertFalse(self.execute(role="viewer", actor="viewer")["ok"])

    def test_client_cannot_forge_closed_set_size_and_stale_or_missing_advisory_is_rejected(self):
        forged = self.execute(payload={"expected_revision": 1, "layer_path": [], "closed_set_size": 999})
        self.assertFalse(forged["ok"])

        self.service.save_draft(tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
                                config={"persona": {"fields": {}}, "units": [], "g0_gates": [],
                                        "hard_rules": [], "task_blueprints": [], "orchestration": {
                                            "schema_version": "unit-graph-v1", "kind": "graph",
                                            "routing": {"mode": "llm"}, "nodes": [], "entry": "missing.from_start",
                                            "input_fields": [], "edges": [], "on_event": [],
                                            "fallback": {"kind": "human"}}})
        stale = self.execute(payload={"expected_revision": 1, "layer_path": []})
        self.assertEqual(stale["error"]["code"], "revision_conflict")
        absent = self.execute(payload={"expected_revision": 2, "layer_path": []})
        self.assertFalse(absent["ok"])

    def test_freeze_atomically_snapshots_dismissals_and_idempotent_replay_keeps_them(self):
        self.execute(payload={"expected_revision": 1, "layer_path": []})
        draft = self.service.get_draft(tenant_id="tenant-a", agent_id="expert-a")
        encoded = json.dumps(draft["config"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        content_hash = hashlib.sha256(encoded.encode()).hexdigest()
        candidate, conflict = self.store.freeze_config_candidate(
            tenant_id="tenant-a", agent_id="expert-a", candidate_id="candidate-1",
            idempotency_key="freeze-r1", expected_revision=1, content_hash=content_hash, diff=[],
        )
        self.assertIsNone(conflict)
        self.assertEqual(candidate["review_summary"], [{
            "advisory_key": "closed-set:[]", "layer_path": [], "closed_set_size": 7,
            "actor_id": "operator-1", "created_at": candidate["review_summary"][0]["created_at"],
            "source_revision": 1,
        }])

        replay, conflict = self.store.freeze_config_candidate(
            tenant_id="tenant-a", agent_id="expert-a", candidate_id="candidate-1",
            idempotency_key="freeze-r1", expected_revision=1, content_hash=content_hash, diff=[],
        )
        self.assertIsNone(conflict)
        self.assertEqual(replay["review_summary"], candidate["review_summary"])
        later = self.execute(payload={"expected_revision": 1, "layer_path": []})
        self.assertFalse(later["ok"])

    def test_concurrent_revision_change_between_read_and_dismiss_is_reported_as_conflict(self):
        other = SqliteStore(self.path)
        self.addCleanup(other.close)
        original = closed_set_advisory

        def advance_revision(config, layer_path):
            changed = {**config, "concurrent_edit_marker": "second-connection"}
            saved, conflict = other.save_config_draft(
                tenant_id="tenant-a", agent_id="expert-a", expected_revision=1, config=changed,
            )
            self.assertIsNone(conflict)
            self.assertEqual(saved["revision"], 2)
            return original(config, layer_path)

        with patch("loomrise.configuration.closed_set_advisory", side_effect=advance_revision):
            response = self.execute(payload={"expected_revision": 1, "layer_path": []})

        self.assertEqual(response["error"]["code"], "revision_conflict")
        self.assertEqual(response["error"]["current"]["revision"], 2)
        self.assertEqual(
            response["error"]["current"]["config"]["concurrent_edit_marker"], "second-connection",
        )
        self.assertEqual(self.store.list_config_advisory_dismissals(
            tenant_id="tenant-a", agent_id="expert-a", source_revision=1,
        ), [])

    def test_unexpected_storage_runtime_error_is_not_mapped_to_revision_conflict(self):
        with patch.object(self.store, "dismiss_config_advisory", side_effect=RuntimeError("disk failure")):
            with self.assertRaisesRegex(RuntimeError, "disk failure"):
                self.service.dismiss_graph_advisory(
                    tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
                    layer_path=[], actor_id="operator-1",
                )


if __name__ == "__main__":
    unittest.main()
