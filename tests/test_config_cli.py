from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from loomrise.config_cli import main
from loomrise.configuration import (
    CONFIG_SCHEMA_VERSION,
    ConfigurationApplication,
    ConfigurationService,
)
from loomrise.durable_store import SqliteStore


def configuration(goal: str = "收集预约信息") -> dict:
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
        "units": [{
            "unit_id": "collect-contact",
            "version": 1,
            "load_mode": "routed",
            "entry_ports": [{"port": "from_start", "requires": []}],
            "reads": ["customer.name"],
            "writes": ["customer.phone"],
            "exit_ports": [{
                "port": "done",
                "completion": {"deterministic": {
                    "field": "customer.phone", "op": "exists",
                }},
                "exits": ["collect-contact"],
            }],
            "on_event": [],
            "fallback": {"kind": "clarify"},
            "max_rounds": 3,
            "body": {},
        }],
        "g0_gates": [],
        "hard_rules": [],
        "task_blueprints": [],
    }


class ConfigurationCliCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "configuration.db"
        self.principal_file = self.root / "principal.json"
        self.principal_file.write_text(json.dumps({
            "tenant_id": "tenant-a",
            "actor_id": "local-editor",
            "role": "editor",
            "agent_ids": ["expert-a"],
        }), encoding="utf-8")
        if os.name == "posix":
            self.principal_file.chmod(0o600)
        store = SqliteStore(str(self.db))
        self.service = ConfigurationService(store)
        self.service.register_stable_version(
            tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
            config=configuration("原始目标"),
        )
        store.close()
        self.addCleanup(self.temp.cleanup)

    def invoke(self, *args: str) -> tuple[int, dict]:
        output = io.StringIO()
        status = main(
            list(args), principal_path=self.principal_file,
            database_path=self.db, stdout=output,
        )
        return status, json.loads(output.getvalue())

    def test_read_create_patch_validate_and_freeze_use_common_envelope(self):
        code, created = self.invoke(
            "draft", "create", "--agent-id", "expert-a", "--base-version-id", "v1", "--json",
        )
        self.assertEqual(code, 0)
        self.assertEqual(set(created), {"schema_version", "ok", "result", "error"})
        self.assertIsNone(created["error"])
        self.assertEqual(created["schema_version"], CONFIG_SCHEMA_VERSION)
        self.assertEqual(created["result"]["revision"], 1)

        code, read = self.invoke("draft", "read", "--agent-id", "expert-a")
        self.assertEqual(code, 0)
        self.assertEqual(read["result"]["config"]["persona"]["goal"], "原始目标")

        changes = json.dumps([{
            "path": "$.persona.goal", "value": "更新目标",
        }], ensure_ascii=False)
        code, patched = self.invoke(
            "draft", "patch", "--agent-id", "expert-a", "--revision", "1",
            "--changes", changes,
        )
        self.assertEqual(code, 0)
        self.assertEqual(patched["result"]["revision"], 2)
        self.assertEqual(patched["result"]["diff"], [{
            "path": "$.persona.goal", "before": "原始目标", "after": "更新目标",
        }])

        code, valid = self.invoke(
            "draft", "validate", "--agent-id", "expert-a", "--revision", "2",
        )
        self.assertEqual(code, 0)
        self.assertTrue(valid["result"]["valid"])

        code, frozen = self.invoke(
            "candidate", "freeze", "--agent-id", "expert-a", "--revision", "2",
            "--idempotency-key", "cli-freeze-2",
        )
        self.assertEqual(code, 0)
        candidate = frozen["result"]
        self.assertEqual(candidate["status"], "frozen")

        code, listing = self.invoke("candidate", "list", "--agent-id", "expert-a")
        self.assertEqual(code, 0)
        self.assertEqual(listing["result"]["items"], [candidate])
        code, detail = self.invoke(
            "candidate", "read", "--agent-id", "expert-a",
            "--candidate-id", candidate["candidate_id"],
        )
        self.assertEqual(code, 0)
        self.assertEqual(detail["result"], candidate)
        self.assertEqual(set(detail), {"schema_version", "ok", "result", "error"})
        self.assertIsNone(detail["error"])

        code, checklist = self.invoke(
            "release", "checklist", "--agent-id", "expert-a",
            "--candidate-id", candidate["candidate_id"], "--json",
        )
        self.assertEqual(code, 0)
        self.assertEqual(checklist["result"]["progress"], {
            "passed": 4, "failed": 0, "pending": 6, "total": 10,
        })
        self.assertFalse(checklist["result"]["ready"])
        self.assertFalse(checklist["result"]["publish_enabled"])

        owner_file = json.loads(self.principal_file.read_text(encoding="utf-8"))
        owner_file.update(actor_id="local-owner", role="owner")
        self.principal_file.write_text(json.dumps(owner_file), encoding="utf-8")
        if os.name == "posix":
            self.principal_file.chmod(0o600)
        code, blocked = self.invoke(
            "release", "publish", "--agent-id", "expert-a",
            "--candidate-id", candidate["candidate_id"], "--entry-id", "visitor-entry",
            "--version-id", "sandbox-v1",
        )
        self.assertEqual(code, 2)
        self.assertEqual(blocked["error"]["code"], "release_blocked")
        self.assertFalse(blocked["ok"])

    def test_revision_conflict_is_mcp_compatible_and_nonzero(self):
        self.invoke("draft", "create", "--agent-id", "expert-a", "--base-version-id", "v1")
        self.invoke(
            "draft", "patch", "--agent-id", "expert-a", "--revision", "1",
            "--changes", '[{"path":"$.persona.goal","value":"新目标"}]',
        )
        code, conflict = self.invoke(
            "draft", "patch", "--agent-id", "expert-a", "--revision", "1",
            "--changes", '[{"path":"$.persona.goal","value":"过期写入"}]', "--json",
        )
        self.assertEqual(code, 3)
        self.assertEqual(set(conflict), {"schema_version", "ok", "result", "error"})
        self.assertIsNone(conflict["result"])
        self.assertFalse(conflict["ok"])
        self.assertEqual(conflict["error"]["code"], "revision_conflict")
        self.assertEqual(conflict["error"]["current"]["revision"], 2)

    def test_scope_and_principal_file_permissions_are_enforced(self):
        code, denied = self.invoke("draft", "read", "--agent-id", "other-agent")
        self.assertEqual(code, 2)
        self.assertEqual(denied["error"]["code"], "forbidden")

        if os.name == "posix":
            self.principal_file.chmod(0o644)
            code, rejected = self.invoke("draft", "read", "--agent-id", "expert-a")
            self.assertEqual(code, 2)
            self.assertEqual(rejected["error"]["code"], "configuration_error")

    def test_stable_list_and_owner_only_import(self):
        code, listing = self.invoke("stable", "list", "--agent-id", "expert-a")
        self.assertEqual(code, 0)
        self.assertEqual([item["version_id"] for item in listing["result"]["items"]], ["v1"])
        code, stable = self.invoke(
            "stable", "read", "--agent-id", "expert-a", "--version-id", "v1",
        )
        self.assertEqual(code, 0)
        self.assertEqual(stable["result"]["config"]["persona"]["goal"], "原始目标")

        config_path = self.root / "stable.json"
        config_path.write_text(json.dumps(configuration("导入的稳定目标")), encoding="utf-8")
        code, denied = self.invoke(
            "stable", "import", "--agent-id", "expert-a", "--version-id", "v2",
            "--config", str(config_path),
        )
        self.assertEqual(code, 2)
        self.assertEqual(denied["error"]["code"], "forbidden")

        self.principal_file.write_text(json.dumps({
            "tenant_id": "tenant-a", "actor_id": "local-owner", "role": "owner",
            "agent_ids": ["expert-a"],
        }), encoding="utf-8")
        if os.name == "posix":
            self.principal_file.chmod(0o600)
        code, imported = self.invoke(
            "stable", "import", "--agent-id", "expert-a", "--version-id", "v2",
            "--config", str(config_path),
        )
        self.assertEqual(code, 0)
        self.assertEqual(imported["result"]["version_id"], "v2")

    def test_cli_has_no_tenant_or_role_override_and_no_governance_commands(self):
        from loomrise.config_cli import build_parser

        parser = build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["draft", "read", "--agent-id", "expert-a", "--role", "owner"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["publish", "--agent-id", "expert-a"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["candidate", "approve", "--agent-id", "expert-a"])

    def test_mcp_command_uses_the_provisioned_principal_and_shared_database(self):
        with patch("loomrise.adapters.mcp.run_configuration_mcp") as run:
            code = main(
                ["mcp"], principal_path=self.principal_file,
                database_path=self.db, stdout=io.StringIO(),
            )

        self.assertEqual(code, 0)
        application = run.call_args.args[0]
        principal = run.call_args.kwargs["principal"]
        self.assertEqual(principal.tenant_id, "tenant-a")
        self.assertEqual(principal.agent_ids, ("expert-a",))
        self.assertIsInstance(application, ConfigurationApplication)


if __name__ == "__main__":
    unittest.main()
