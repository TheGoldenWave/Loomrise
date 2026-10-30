from __future__ import annotations

import json
import base64
import os
from pathlib import Path
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

from loomrise.config_http import APPLICATION_KEY, STORE_KEY, create_configuration_http_app
from loomrise.contracts import Channel, RequestState, Run, ServiceRequest


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


class ConfigurationHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.principal_path = root / "principal.json"
        self.principal_path.write_text(json.dumps({
            "tenant_id": "tenant-a", "actor_id": "owner-a", "role": "owner",
            "agent_ids": ["expert-a"],
        }), encoding="utf-8")
        os.chmod(self.principal_path, 0o600)
        self.database_path = root / "configuration.db"
        self.app = create_configuration_http_app(
            principal_path=self.principal_path, database_path=self.database_path,
        )
        service = self.app[APPLICATION_KEY].service
        service.register_stable_version(
            tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
            config=valid_config(),
        )
        service.create_draft_from_stable(
            tenant_id="tenant-a", agent_id="expert-a", base_version_id="v1",
        )
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.addCleanup(self.temp.cleanup)

    async def test_shared_application_envelope_and_revision_conflict(self):
        headers = {"Origin": "http://127.0.0.1:8765"}
        read = await self.client.post("/api/configuration", headers=headers, json={
            "action": "draft.get", "payload": {"agent_id": "expert-a"},
        })
        self.assertEqual(read.status, 200)
        body = await read.json()
        self.assertEqual(set(body), {"schema_version", "ok", "result", "error"})
        self.assertTrue(body["ok"])
        self.assertEqual(body["result"]["revision"], 1)
        self.assertEqual(read.headers["Access-Control-Allow-Origin"], headers["Origin"])

        stable = await self.client.post("/api/configuration", headers=headers, json={
            "action": "stable.get", "payload": {
                "agent_id": "expert-a", "version_id": "v1",
            },
        })
        self.assertEqual(stable.status, 200)
        self.assertEqual(
            (await stable.json())["result"]["config"]["persona"]["goal"],
            "预约咨询",
        )

        saved = await self.client.post("/api/configuration", headers=headers, json={
            "action": "draft.save", "payload": {
                "agent_id": "expert-a", "expected_revision": 1,
                "config": valid_config("更新目标"),
            },
        })
        self.assertEqual(saved.status, 200)
        self.assertEqual((await saved.json())["result"]["revision"], 2)

        stale = await self.client.post("/api/configuration", headers=headers, json={
            "action": "draft.save", "payload": {
                "agent_id": "expert-a", "expected_revision": 1,
                "config": valid_config("旧写入"),
            },
        })
        self.assertEqual(stale.status, 409)
        conflict = await stale.json()
        self.assertEqual(conflict["error"]["code"], "revision_conflict")
        self.assertEqual(conflict["error"]["current"]["revision"], 2)

    async def test_scope_and_non_loopback_origin_are_rejected(self):
        unauthorized = await self.client.post("/api/configuration", json={
            "action": "draft.get", "payload": {"agent_id": "other-agent"},
        })
        self.assertEqual(unauthorized.status, 403)
        self.assertEqual((await unauthorized.json())["error"]["code"], "forbidden")

        remote = await self.client.post(
            "/api/configuration", headers={"Origin": "https://evil.invalid"}, json={
                "action": "draft.get", "payload": {"agent_id": "expert-a"},
            },
        )
        self.assertEqual(remote.status, 403)

        untrusted_loopback = await self.client.post(
            "/api/configuration", headers={"Origin": "http://127.0.0.1:8767"}, json={
                "action": "draft.get", "payload": {"agent_id": "expert-a"},
            },
        )
        self.assertEqual(untrusted_loopback.status, 403)

    async def test_explicit_workbench_origin_can_use_a_custom_loopback_port(self):
        app = create_configuration_http_app(
            principal_path=self.principal_path,
            database_path=self.database_path,
            allowed_origins={"http://127.0.0.1:8768"},
        )
        client = TestClient(TestServer(app))
        await client.start_server()
        self.addAsyncCleanup(client.close)

        response = await client.post(
            "/api/configuration", headers={"Origin": "http://127.0.0.1:8768"}, json={
                "action": "draft.get", "payload": {"agent_id": "expert-a"},
            },
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"], "http://127.0.0.1:8768",
        )

    async def test_health_is_schema_versioned(self):
        response = await self.client.get("/api/configuration/health")
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["schema_version"], "config-api-v1")

    async def test_run_status_is_read_only_redacted_and_agent_scoped(self):
        store = self.app[STORE_KEY]
        request = ServiceRequest(
            request_id="req-status", tenant_id="tenant-a", agent_version="v1",
            channel=Channel.TEXT, state=RequestState.RUNNING,
        )
        run = Run(
            run_id="run-status", request_id=request.request_id, tenant_id="tenant-a",
            agent_version="v1", owner_id="owner-a",
        )
        store.begin_run(request, run, [])

        response = await self.client.post("/api/configuration", json={
            "action": "run.status",
            "payload": {"agent_id": "expert-a", "run_id": "run-status"},
        })
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["result"]["run_status"], "running")
        self.assertEqual(body["result"]["request_state"], "running")
        self.assertEqual(body["result"]["event_count"], 0)
        self.assertNotIn("snapshot_json", body["result"])
        self.assertNotIn("payload_json", body["result"])
        self.assertTrue(store.is_running(run.run_id))

        forbidden = await self.client.post("/api/configuration", json={
            "action": "run.status",
            "payload": {"agent_id": "expert-b", "run_id": "run-status"},
        })
        self.assertEqual(forbidden.status, 403)

        missing = await self.client.post("/api/configuration", json={
            "action": "run.status",
            "payload": {"agent_id": "expert-a", "run_id": "run-missing"},
        })
        self.assertEqual(missing.status, 404)

    async def test_customer_service_http_uses_shared_authenticated_application(self):
        same_origin = str(self.client.make_url("/").origin())
        response = await self.client.post("/api/customer-service", headers={"Origin": same_origin}, json={
            "action": "material.create",
            "payload": {
                "agent_id": "expert-a", "filename": "faq.txt", "display_name": "FAQ",
                "authorization": "owned",
                "content_base64": base64.b64encode("报名信息".encode()).decode(),
            },
        })
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["schema_version"], "customer-service-v1")
        self.assertEqual(body["result"]["version"], 1)

        widget = await self.client.get("/widget/expert-a/visitor-entry")
        self.assertEqual(widget.status, 200)
        self.assertIn('data-agent-id="expert-a"', await widget.text())
        inbox = await self.client.get("/inbox/expert-a")
        self.assertEqual(inbox.status, 200)
        self.assertIn("客服收件箱", await inbox.text())

    async def test_configuration_http_uploads_and_ingests_text_knowledge_file(self):
        uploaded = await self.client.post("/api/configuration", json={
            "action": "knowledge.source.create",
            "payload": {
                "agent_id": "expert-a", "kind": "file", "filename": "policy.md",
                "display_name": "报名政策", "authorization": "owned",
                "content_base64": base64.b64encode("报名需要提前两天预约。".encode()).decode(),
            },
        })
        self.assertEqual(uploaded.status, 200)
        source = (await uploaded.json())["result"]
        self.assertEqual(source["state"], "queued")
        self.assertNotIn("uploaded_content", source)

        ingested = await self.client.post("/api/configuration", json={
            "action": "knowledge.ingest",
            "payload": {"agent_id": "expert-a", "source_id": source["source_id"]},
        })
        self.assertEqual(ingested.status, 200)
        self.assertEqual((await ingested.json())["result"]["state"], "ready")

        search = await self.client.post("/api/configuration", json={
            "action": "knowledge.search",
            "payload": {"agent_id": "expert-a", "query": "提前两天"},
        })
        self.assertEqual(search.status, 200)
        self.assertEqual(
            (await search.json())["result"]["items"][0]["text"],
            "报名需要提前两天预约。",
        )


if __name__ == "__main__":
    unittest.main()
