from __future__ import annotations

import json
import os
import tempfile
import unittest

from mcp.shared.memory import create_connected_server_and_client_session

from loomrise.adapters.mcp import create_configuration_mcp_server
from loomrise.configuration import (
    CONFIG_SCHEMA_VERSION,
    ConfigurationApplication,
    ConfigurationPrincipal,
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


class ConfigurationMcpCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SqliteStore(os.path.join(self.temp.name, "loomrise.db"))
        self.service = ConfigurationService(self.store)
        self.service.register_stable_version(
            tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
            config=configuration("原始目标"),
        )
        self.service.create_draft_from_stable(
            tenant_id="tenant-a", agent_id="expert-a", base_version_id="v1",
        )
        self.app = ConfigurationApplication(self.service)
        self.principal = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="external-agent-1",
            role="external_agent", agent_ids=("expert-a",),
        )
        self.server = create_configuration_mcp_server(
            self.app, principal=self.principal,
        )

    async def asyncTearDown(self):
        self.store.close()
        self.temp.cleanup()

    async def test_tool_contract_shares_application_schema_and_revision(self):
        async with create_connected_server_and_client_session(self.server) as client:
            listed = await client.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            self.assertIn("loomrise_draft_patch", tools)
            self.assertIn("loomrise_candidate_freeze", tools)
            self.assertIn("loomrise_stable_read", tools)
            for tool in tools.values():
                properties = tool.inputSchema["properties"]
                self.assertNotIn("tenant_id", properties)
                self.assertNotIn("role", properties)

            before = await client.call_tool("loomrise_draft_read", {
                "agent_id": "expert-a",
                "tenant_id": "tenant-b",
                "role": "owner",
            })
            before_data = before.structuredContent
            self.assertEqual(before_data["schema_version"], CONFIG_SCHEMA_VERSION)
            self.assertTrue(before_data["ok"])
            self.assertEqual(before_data["result"]["tenant_id"], "tenant-a")
            self.assertEqual(before_data["result"]["revision"], 1)

            patched = await client.call_tool("loomrise_draft_patch", {
                "agent_id": "expert-a",
                "expected_revision": 1,
                "changes": [{"path": "$.persona.goal", "value": "更新后的目标"}],
            })
            patched_data = patched.structuredContent
            self.assertTrue(patched_data["ok"])
            self.assertEqual(patched_data["result"]["revision"], 2)
            self.assertEqual(patched_data["result"]["diff"], [{
                "path": "$.persona.goal",
                "before": "原始目标",
                "after": "更新后的目标",
            }])

            stale = await client.call_tool("loomrise_draft_patch", {
                "agent_id": "expert-a",
                "expected_revision": 1,
                "changes": [{"path": "$.persona.goal", "value": "过期修改"}],
            })
            self.assertFalse(stale.structuredContent["ok"])
            self.assertEqual(stale.structuredContent["error"]["code"], "revision_conflict")
            self.assertEqual(stale.structuredContent["error"]["current"]["revision"], 2)

            frozen = await client.call_tool("loomrise_candidate_freeze", {
                "agent_id": "expert-a",
                "expected_revision": 2,
                "idempotency_key": "mcp-freeze-r2",
            })
            candidate = frozen.structuredContent["result"]
            self.assertEqual(candidate["status"], "frozen")
            self.assertEqual(candidate["source_revision"], 2)

            repeat = await client.call_tool("loomrise_candidate_freeze", {
                "agent_id": "expert-a",
                "expected_revision": 2,
                "idempotency_key": "mcp-freeze-r2",
            })
            self.assertEqual(repeat.structuredContent["result"]["candidate_id"], candidate["candidate_id"])

    async def test_tool_scope_and_field_restrictions_are_server_enforced(self):
        async with create_connected_server_and_client_session(self.server) as client:
            other_expert = await client.call_tool(
                "loomrise_draft_read", {"agent_id": "expert-b"},
            )
            self.assertFalse(other_expert.structuredContent["ok"])
            self.assertEqual(other_expert.structuredContent["error"]["code"], "forbidden")

            protected_field = await client.call_tool("loomrise_draft_patch", {
                "agent_id": "expert-a",
                "expected_revision": 1,
                "changes": [{"path": "$.persona.fields", "value": {}}],
            })
            self.assertFalse(protected_field.structuredContent["ok"])
            self.assertEqual(protected_field.structuredContent["error"]["code"], "forbidden")

    async def test_resources_return_same_authorized_service_snapshot(self):
        async with create_connected_server_and_client_session(self.server) as client:
            templates = await client.list_resource_templates()
            template_uris = {item.uriTemplate for item in templates.resourceTemplates}
            self.assertIn("loomrise://agents/{agent_id}/draft", template_uris)
            self.assertIn("loomrise://agents/{agent_id}/candidates", template_uris)
            self.assertIn("loomrise://agents/{agent_id}/stable/{version_id}", template_uris)

            resources = await client.read_resource("loomrise://agents/expert-a/draft")
            snapshot = json.loads(resources.contents[0].text)
            self.assertTrue(snapshot["ok"])
            self.assertEqual(snapshot["result"]["revision"], 1)

            denied = await client.read_resource("loomrise://agents/expert-b/draft")
            denied_data = json.loads(denied.contents[0].text)
            self.assertEqual(denied_data["error"]["code"], "forbidden")

            stable = await client.call_tool("loomrise_stable_read", {
                "agent_id": "expert-a", "version_id": "v1",
            })
            self.assertTrue(stable.structuredContent["ok"])
            self.assertEqual(
                stable.structuredContent["result"]["config"]["persona"]["goal"],
                "原始目标",
            )


if __name__ == "__main__":
    unittest.main()
