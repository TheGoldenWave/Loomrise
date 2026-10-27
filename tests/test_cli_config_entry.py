from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from loomrise.cli import main
from loomrise.configuration import ConfigurationService
from loomrise.durable_store import SqliteStore


def valid_configuration() -> dict:
    return {
        "persona": {
            "name": "课程咨询专家",
            "goal": "按授权资料答疑",
            "audience": "课程访客",
            "fields": {"visitor.name": {"type": "string"}},
            "entry_unit_ids": ["answer"],
        },
        "units": [{
            "unit_id": "answer",
            "version": 1,
            "load_mode": "routed",
            "entry_ports": [{"port": "start", "requires": []}],
            "reads": ["visitor.name"],
            "writes": ["visitor.name"],
            "exit_ports": [{
                "port": "done",
                "completion": {"deterministic": {"fact": {
                    "field": "visitor.name", "op": "exists",
                }}},
                "exits": ["answer"],
            }],
            "on_event": [],
            "fallback": {"kind": "clarify"},
            "max_rounds": 1,
            "body": {},
        }],
        "g0_gates": [],
        "hard_rules": [],
        "task_blueprints": [],
    }


class ConfigCommandEntryTests(unittest.TestCase):
    def test_config_command_routes_to_shared_cli_and_emits_common_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / "config.db"
            principal_file = root / "principal.json"
            principal_file.write_text(json.dumps({
                "tenant_id": "tenant-a",
                "actor_id": "operator-a",
                "role": "editor",
                "agent_ids": ["expert-a"],
            }), encoding="utf-8")
            if os.name == "posix":
                principal_file.chmod(0o600)
            store = SqliteStore(str(database))
            try:
                ConfigurationService(store).register_stable_version(
                    tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
                    config=valid_configuration(),
                )
            finally:
                store.close()

            output = io.StringIO()
            with patch.dict(os.environ, {
                "LOOMRISE_PRINCIPAL_FILE": str(principal_file),
                "LOOMRISE_CONFIGURATION_DB": str(database),
            }), redirect_stdout(output):
                code = main([
                    "config", "draft", "create", "--agent-id", "expert-a",
                    "--base-version-id", "v1", "--json",
                ])

            response = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(set(response), {"schema_version", "ok", "result", "error"})
            self.assertTrue(response["ok"])
            self.assertEqual(response["result"]["revision"], 1)


if __name__ == "__main__":
    unittest.main()
