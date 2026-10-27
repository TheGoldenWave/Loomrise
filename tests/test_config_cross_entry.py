from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer
from mcp.shared.memory import create_connected_server_and_client_session

from loomrise.adapters.mcp import create_configuration_mcp_server
from loomrise.config_cli import main as config_cli_main
from loomrise.config_http import APPLICATION_KEY, create_configuration_http_app
from loomrise.configuration import (
    CONFIG_SCHEMA_VERSION,
    ConfigurationApplication,
    ConfigurationPrincipal,
    ConfigurationService,
)
from loomrise.durable_store import SqliteStore


def valid_config(goal: str = "预约咨询") -> dict:
    return {
        "persona": {
            "name": "服务专家", "goal": goal, "audience": "访客",
            "fields": {"customer.name": {"type": "string"}},
            "entry_unit_ids": ["collect"],
        },
        "units": [{
            "unit_id": "collect", "version": 1, "load_mode": "routed",
            "entry_ports": [{"port": "start", "requires": []}],
            "reads": ["customer.name"], "writes": ["customer.name"],
            "exit_ports": [{
                "port": "done",
                "completion": {"deterministic": {"field": "customer.name", "op": "exists"}},
                "exits": ["collect"],
            }],
            "on_event": [], "fallback": {"kind": "clarify"},
            "max_rounds": 3, "body": {},
        }],
        "g0_gates": [], "hard_rules": [], "task_blueprints": [],
    }


class ConfigurationCrossEntryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database_path = self.root / "configuration.db"
        self.principal_path = self.root / "principal.json"
        self.principal_path.write_text(json.dumps({
            "tenant_id": "tenant-a", "actor_id": "owner-a", "role": "owner",
            "agent_ids": ["expert-a"],
        }), encoding="utf-8")
        if os.name == "posix":
            self.principal_path.chmod(0o600)

        self.client = await self._start_http_client()
        service = self.http_app[APPLICATION_KEY].service
        service.register_stable_version(
            tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
            config=valid_config(),
        )
        service.create_draft_from_stable(
            tenant_id="tenant-a", agent_id="expert-a", base_version_id="v1",
        )
        self.addCleanup(self.temp.cleanup)

    async def _start_http_client(self) -> TestClient:
        app = create_configuration_http_app(
            principal_path=self.principal_path,
            database_path=self.database_path,
        )
        client = TestClient(TestServer(app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        self.http_app = app
        return client

    def invoke_cli(self, *args: str) -> tuple[int, dict]:
        output = io.StringIO()
        code = config_cli_main(
            list(args), principal_path=self.principal_path,
            database_path=self.database_path, stdout=output,
        )
        return code, json.loads(output.getvalue())

    async def post_http(self, action: str, payload: dict) -> tuple[int, dict]:
        response = await self.client.post(
            "/api/configuration",
            headers={"Origin": "http://127.0.0.1:8765"},
            json={"action": action, "payload": payload},
        )
        return response.status, await response.json()

    async def test_http_cli_and_mcp_share_revision_validation_and_restart_state(self):
        principal = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="owner-a", role="owner",
            agent_ids=("expert-a",),
        )
        mcp_store = SqliteStore(str(self.database_path))
        self.addCleanup(mcp_store.close)
        mcp_application = ConfigurationApplication(ConfigurationService(mcp_store))
        mcp_server = create_configuration_mcp_server(
            mcp_application, principal=principal,
        )

        http_status, http_read = await self.post_http(
            "draft.get", {"agent_id": "expert-a"},
        )
        self.assertEqual(http_status, 200)
        self.assertEqual(http_read["schema_version"], CONFIG_SCHEMA_VERSION)
        self.assertEqual(http_read["result"]["revision"], 1)

        async with create_connected_server_and_client_session(mcp_server) as mcp:
            mcp_read = await mcp.call_tool("loomrise_draft_read", {"agent_id": "expert-a"})
            mcp_read_data = mcp_read.structuredContent
            self.assertEqual(mcp_read_data, http_read)

            mcp_patch = await mcp.call_tool("loomrise_draft_patch", {
                "agent_id": "expert-a", "expected_revision": 1,
                "changes": [{"path": "$.persona.goal", "value": "MCP 更新"}],
            })
            self.assertTrue(mcp_patch.structuredContent["ok"])
            self.assertEqual(mcp_patch.structuredContent["result"]["revision"], 2)

            cli_code, cli_read = self.invoke_cli(
                "draft", "read", "--agent-id", "expert-a", "--json",
            )
            self.assertEqual(cli_code, 0)
            self.assertEqual(
                cli_read["result"]["revision"],
                mcp_patch.structuredContent["result"]["revision"],
            )
            self.assertEqual(
                cli_read["result"]["config"],
                mcp_patch.structuredContent["result"]["config"],
            )

            cli_code, cli_patch = self.invoke_cli(
                "draft", "patch", "--agent-id", "expert-a", "--revision", "2",
                "--changes", json.dumps([{
                    "path": "$.persona.goal", "value": "CLI 更新",
                }], ensure_ascii=False), "--json",
            )
            self.assertEqual(cli_code, 0)
            self.assertEqual(cli_patch["schema_version"], mcp_patch.structuredContent["schema_version"])
            self.assertEqual(cli_patch["result"]["revision"], 3)

            http_status, http_read = await self.post_http(
                "draft.get", {"agent_id": "expert-a"},
            )
            self.assertEqual(http_status, 200)
            self.assertEqual(http_read["result"]["revision"], cli_patch["result"]["revision"])
            self.assertEqual(http_read["result"]["config"], cli_patch["result"]["config"])

            cli_code, dotted_field_patch = self.invoke_cli(
                "draft", "patch", "--agent-id", "expert-a", "--revision", "3",
                "--changes", json.dumps([{
                    "path": '$.persona.fields["customer.name"].type', "value": "text",
                }]),
            )
            self.assertEqual(cli_code, 0)
            self.assertEqual(dotted_field_patch["result"]["revision"], 4)
            self.assertEqual(dotted_field_patch["result"]["diff"][0]["path"],
                             '$.persona.fields["customer.name"].type')

            cli_code, invalid_patch = self.invoke_cli(
                "draft", "patch", "--agent-id", "expert-a", "--revision", "4",
                "--changes", '[{"path":"$.units[0].load_mode","value":"concurrent"}]',
            )
            self.assertEqual(cli_code, 0)
            invalid_revision = invalid_patch["result"]["revision"]

            mcp_validation = await mcp.call_tool("loomrise_draft_validate", {
                "agent_id": "expert-a", "expected_revision": invalid_revision,
            })
            http_status, http_validation = await self.post_http(
                "draft.validate", {
                    "agent_id": "expert-a", "expected_revision": invalid_revision,
                },
            )
            cli_code, cli_validation = self.invoke_cli(
                "draft", "validate", "--agent-id", "expert-a",
                "--revision", str(invalid_revision), "--json",
            )
            self.assertEqual(http_status, 200)
            self.assertEqual(cli_code, 0)
            self.assertEqual(mcp_validation.structuredContent, http_validation)
            self.assertEqual(cli_validation, http_validation)
            self.assertFalse(http_validation["result"]["valid"])
            self.assertIn(
                "$.units[0].load_mode",
                [issue["path"] for issue in http_validation["result"]["issues"]],
            )

            rejected_mcp = await mcp.call_tool("loomrise_candidate_freeze", {
                "agent_id": "expert-a", "expected_revision": invalid_revision,
                "idempotency_key": "invalid-candidate",
            })
            http_status, rejected_http = await self.post_http(
                "candidate.freeze", {
                    "agent_id": "expert-a", "expected_revision": invalid_revision,
                    "idempotency_key": "invalid-candidate",
                },
            )
            cli_code, rejected_cli = self.invoke_cli(
                "candidate", "freeze", "--agent-id", "expert-a",
                "--revision", str(invalid_revision),
                "--idempotency-key", "invalid-candidate", "--json",
            )
            self.assertEqual(http_status, 422)
            self.assertEqual(cli_code, 2)
            self.assertEqual(rejected_mcp.structuredContent, rejected_http)
            self.assertEqual(rejected_cli, rejected_http)
            self.assertEqual(rejected_http["error"]["code"], "validation_failed")

            mcp_newer = await mcp.call_tool("loomrise_draft_patch", {
                "agent_id": "expert-a", "expected_revision": invalid_revision,
                "changes": [{"path": "$.persona.goal", "value": "MCP 最新值"}],
            })
            self.assertTrue(mcp_newer.structuredContent["ok"])
            latest_revision = mcp_newer.structuredContent["result"]["revision"]
            cli_code, stale_cli = self.invoke_cli(
                "draft", "patch", "--agent-id", "expert-a",
                "--revision", str(invalid_revision),
                "--changes", '[{"path":"$.persona.goal","value":"过期 CLI 写入"}]',
            )
            self.assertEqual(cli_code, 3)
            self.assertEqual(stale_cli["error"]["code"], "revision_conflict")
            self.assertEqual(stale_cli["error"]["current"]["revision"], latest_revision)

            http_status, latest = await self.post_http(
                "draft.get", {"agent_id": "expert-a"},
            )
            self.assertEqual(http_status, 200)
            self.assertEqual(latest["result"]["revision"], latest_revision)
            self.assertEqual(latest["result"]["config"]["persona"]["goal"], "MCP 最新值")

        await self.client.close()
        mcp_store.close()
        self.client = await self._start_http_client()
        restarted_status, restarted = await self.post_http(
            "draft.get", {"agent_id": "expert-a"},
        )
        self.assertEqual(restarted_status, 200)
        self.assertEqual(restarted["result"], latest["result"])
        stable_status, stable = await self.post_http(
            "stable.get", {"agent_id": "expert-a", "version_id": "v1"},
        )
        self.assertEqual(stable_status, 200)
        self.assertEqual(stable["result"]["config"]["persona"]["goal"], "预约咨询")


if __name__ == "__main__":
    unittest.main()
