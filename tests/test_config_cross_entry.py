from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
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

    async def test_candidate_checklist_is_shared_deterministic_and_read_only(self):
        service = self.http_app[APPLICATION_KEY].service
        candidate = service.freeze_candidate(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            idempotency_key="checklist-candidate",
        )
        before = {
            "draft": service.get_draft(tenant_id="tenant-a", agent_id="expert-a"),
            "stable": service.get_stable_version(
                tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
            ),
            "candidate": service.get_candidate(
                tenant_id="tenant-a", agent_id="expert-a",
                candidate_id=candidate["candidate_id"],
            ),
            "candidates": service.list_candidates(
                tenant_id="tenant-a", agent_id="expert-a",
            ),
        }
        mcp_store = SqliteStore(str(self.database_path))
        self.addCleanup(mcp_store.close)
        mcp_server = create_configuration_mcp_server(
            ConfigurationApplication(ConfigurationService(mcp_store)),
            principal=ConfigurationPrincipal(
                tenant_id="tenant-a", actor_id="owner-a", role="owner",
                agent_ids=("expert-a",),
            ),
        )

        async with create_connected_server_and_client_session(mcp_server) as mcp:
            http_status, http_result = await self.post_http(
                "candidate.checklist", {
                    "agent_id": "expert-a", "candidate_id": candidate["candidate_id"],
                },
            )
            cli_code, cli_result = self.invoke_cli(
                "candidate", "checklist", "--agent-id", "expert-a",
                "--candidate-id", candidate["candidate_id"], "--json",
            )
            mcp_result = await mcp.call_tool("loomrise_candidate_checklist", {
                "agent_id": "expert-a", "candidate_id": candidate["candidate_id"],
            })

        self.assertEqual(http_status, 200)
        self.assertEqual(cli_code, 0)
        self.assertTrue(http_result["ok"])
        self.assertEqual(http_result, cli_result)
        self.assertEqual(http_result, mcp_result.structuredContent)
        self.assertEqual(http_result["schema_version"], CONFIG_SCHEMA_VERSION)
        checklist = http_result["result"]
        self.assertEqual(checklist["candidate_id"], candidate["candidate_id"])
        self.assertEqual(checklist["readiness"], "blocked")
        self.assertEqual(
            checklist["interpretation"],
            "readiness_diagnostic_only_not_publish_authorization",
        )
        checks = {check["id"]: check for check in checklist["checks"]}
        self.assertEqual(set(checks), {
            "frozen_configuration", "source_authorization",
            "candidate_business_permissions", "fixed_samples",
        })
        self.assertEqual(checks["frozen_configuration"]["status"], "pass")
        self.assertFalse(checks["frozen_configuration"]["blocking"])
        for check_id in (
            "source_authorization", "candidate_business_permissions", "fixed_samples",
        ):
            with self.subTest(check=check_id):
                self.assertEqual(checks[check_id]["status"], "not_assessable")
                self.assertTrue(checks[check_id]["blocking"])
                self.assertTrue(checks[check_id]["reason"])
                self.assertEqual(checks[check_id]["evidence"], [])
        self.assertEqual(
            [set(check) for check in checklist["checks"]],
            [{"id", "status", "blocking", "reason", "evidence"}] * 4,
        )

        denied_status, denied_http = await self.post_http(
            "candidate.checklist", {
                "agent_id": "expert-b", "candidate_id": candidate["candidate_id"],
            },
        )
        denied_cli_code, denied_cli = self.invoke_cli(
            "candidate", "checklist", "--agent-id", "expert-b",
            "--candidate-id", candidate["candidate_id"], "--json",
        )
        self.assertEqual(denied_status, 403)
        self.assertEqual(denied_cli_code, 2)
        self.assertEqual(denied_http, denied_cli)
        self.assertFalse(denied_http["ok"])
        self.assertEqual(denied_http["error"]["code"], "forbidden")

        repeated_status, repeated = await self.post_http(
            "candidate.checklist", {
                "agent_id": "expert-a", "candidate_id": candidate["candidate_id"],
            },
        )
        self.assertEqual(repeated_status, 200)
        self.assertEqual(repeated, http_result)
        self.assertEqual(service.get_draft(tenant_id="tenant-a", agent_id="expert-a"), before["draft"])
        self.assertEqual(service.get_stable_version(
            tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
        ), before["stable"])
        self.assertEqual(service.get_candidate(
            tenant_id="tenant-a", agent_id="expert-a",
            candidate_id=candidate["candidate_id"],
        ), before["candidate"])
        self.assertEqual(service.list_candidates(
            tenant_id="tenant-a", agent_id="expert-a",
        ), before["candidates"])

    async def test_candidate_checklist_reports_hash_and_validation_paths(self):
        service = self.http_app[APPLICATION_KEY].service
        candidate = service.freeze_candidate(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            idempotency_key="checklist-corruption",
        )
        invalid = valid_config()
        invalid["units"][0]["load_mode"] = "concurrent"
        encoded = json.dumps(invalid, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        content_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        with contextlib.closing(sqlite3.connect(self.database_path)) as database, database:
            database.execute(
                "UPDATE change_proposals SET config_json=?,content_hash=? "
                "WHERE tenant_id=? AND agent_id=? AND candidate_id=?",
                (encoded, content_hash, "tenant-a", "expert-a", candidate["candidate_id"]),
            )

        status, invalid_result = await self.post_http(
            "candidate.checklist", {
                "agent_id": "expert-a", "candidate_id": candidate["candidate_id"],
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(invalid_result["ok"])
        invalid_check = next(
            check for check in invalid_result["result"]["checks"]
            if check["id"] == "frozen_configuration"
        )
        self.assertEqual(invalid_check["status"], "fail")
        self.assertTrue(invalid_check["blocking"])
        self.assertIn(
            "$.units[0].load_mode",
            next(
                evidence["json_paths"] for evidence in invalid_check["evidence"]
                if evidence["reference"] == "configuration_validation"
            ),
        )
        self.assertEqual(invalid_result["result"]["readiness"], "blocked")

        valid_encoded = json.dumps(
            valid_config(), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        with contextlib.closing(sqlite3.connect(self.database_path)) as database, database:
            database.execute(
                "UPDATE change_proposals SET config_json=?,content_hash=? "
                "WHERE tenant_id=? AND agent_id=? AND candidate_id=?",
                (valid_encoded, "tampered-hash", "tenant-a", "expert-a", candidate["candidate_id"]),
            )
        status, hash_result = await self.post_http(
            "candidate.checklist", {
                "agent_id": "expert-a", "candidate_id": candidate["candidate_id"],
            },
        )
        self.assertEqual(status, 200)
        hash_check = next(
            check for check in hash_result["result"]["checks"]
            if check["id"] == "frozen_configuration"
        )
        self.assertEqual(hash_check["status"], "fail")
        self.assertTrue(hash_check["blocking"])
        self.assertIn("内容哈希", hash_check["reason"])
        self.assertIn(
            "$.content_hash",
            next(
                evidence["json_paths"] for evidence in hash_check["evidence"]
                if evidence["reference"].startswith("candidate:")
            ),
        )

    async def test_candidate_checklist_blocks_non_frozen_status_without_mutation(self):
        service = self.http_app[APPLICATION_KEY].service
        candidate = service.freeze_candidate(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            idempotency_key="checklist-non-frozen",
        )
        with contextlib.closing(sqlite3.connect(self.database_path)) as database, database:
            database.execute(
                "UPDATE change_proposals SET status=? "
                "WHERE tenant_id=? AND agent_id=? AND candidate_id=?",
                ("draft", "tenant-a", "expert-a", candidate["candidate_id"]),
            )

        before = {
            "draft": service.get_draft(tenant_id="tenant-a", agent_id="expert-a"),
            "stable": service.get_stable_version(
                tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
            ),
            "candidate": service.get_candidate(
                tenant_id="tenant-a", agent_id="expert-a",
                candidate_id=candidate["candidate_id"],
            ),
            "candidates": service.list_candidates(
                tenant_id="tenant-a", agent_id="expert-a",
            ),
        }

        payload = {"agent_id": "expert-a", "candidate_id": candidate["candidate_id"]}
        status, first = await self.post_http("candidate.checklist", payload)
        repeated_status, repeated = await self.post_http("candidate.checklist", payload)

        self.assertEqual(status, 200)
        self.assertEqual(repeated_status, 200)
        frozen_check = next(
            check for check in first["result"]["checks"]
            if check["id"] == "frozen_configuration"
        )
        self.assertEqual(frozen_check["status"], "fail")
        self.assertTrue(frozen_check["blocking"])
        self.assertIn("不是 frozen", frozen_check["reason"])
        self.assertEqual(first["result"]["readiness"], "blocked")
        self.assertEqual(repeated, first)
        self.assertEqual(service.get_draft(tenant_id="tenant-a", agent_id="expert-a"), before["draft"])
        self.assertEqual(service.get_stable_version(
            tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
        ), before["stable"])
        self.assertEqual(service.get_candidate(
            tenant_id="tenant-a", agent_id="expert-a",
            candidate_id=candidate["candidate_id"],
        ), before["candidate"])
        self.assertEqual(service.list_candidates(
            tenant_id="tenant-a", agent_id="expert-a",
        ), before["candidates"])

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
