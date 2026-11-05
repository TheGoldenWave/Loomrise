from __future__ import annotations

import json
import base64
import os
from pathlib import Path
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

from loomrise.config_http import APPLICATION_KEY, STORE_KEY, create_configuration_http_app
from loomrise.configuration import ConfigurationPrincipal, ConfigurationService
from loomrise.contracts import Channel, RequestState, Run, RunEvent, ServiceRequest
from loomrise.durable_store import SqliteStore
from loomrise.service import ExecutionService
from tests.test_concurrent_runtime import recall_pack
from tests.test_closed_set_advisory import wide_graph_config


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

    async def test_closed_set_dismissal_http_is_server_derived_and_frozen_into_candidate(self):
        service = self.app[APPLICATION_KEY].service
        service.save_draft(tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
                           config=wide_graph_config())
        dismissed = await self.client.post("/api/configuration", json={
            "action": "advisory.dismiss",
            "payload": {"agent_id": "expert-a", "expected_revision": 2, "layer_path": []},
        })
        self.assertEqual(dismissed.status, 200)
        dismissal = (await dismissed.json())["result"]
        self.assertEqual(dismissal["closed_set_size"], 7)
        self.assertEqual(dismissal["actor_id"], "owner-a")

        candidate_response = await self.client.post("/api/configuration", json={
            "action": "candidate.freeze",
            "payload": {"agent_id": "expert-a", "expected_revision": 2,
                        "idempotency_key": "closed-set-review"},
        })
        self.assertEqual(candidate_response.status, 200)
        candidate = (await candidate_response.json())["result"]
        self.assertEqual(candidate["review_summary"][0]["advisory_key"], "closed-set:[]")
        self.assertEqual(candidate["review_summary"][0]["actor_id"], "owner-a")
        self.assertEqual(candidate["review_summary"][0]["closed_set_size"], 7)
        self.assertEqual(candidate["config"], wide_graph_config())

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

    async def test_published_contact_page_serves_only_after_explicit_enable(self):
        service = self.app[APPLICATION_KEY].service
        candidate = service.freeze_candidate(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            idempotency_key="contact-http",
        )
        store = self.app[STORE_KEY]
        store.approve_release_candidate(
            tenant_id="tenant-a", agent_id="expert-a", candidate_id=candidate["candidate_id"],
            content_hash=candidate["content_hash"], environment="sandbox",
            entry_id="entry-contact", version_id="sandbox-contact", approved_by="owner-a",
        )
        store.publish_sandbox_candidate(
            tenant_id="tenant-a", agent_id="expert-a", candidate_id=candidate["candidate_id"],
            entry_id="entry-contact", version_id="sandbox-contact",
        )
        unavailable = await self.client.get("/contact/expert-a/entry-contact")
        self.assertEqual(unavailable.status, 404)
        store.enable_contact_page(tenant_id="tenant-a", agent_id="expert-a", entry_id="entry-contact")
        response = await self.client.get("/contact/expert-a/entry-contact")
        self.assertEqual(response.status, 200)
        body = await response.text()
        self.assertIn("联系页", body)

    async def test_run_status_is_read_only_redacted_and_agent_scoped(self):
        store = self.app[STORE_KEY]
        request = ServiceRequest(
            request_id="req-status", tenant_id="tenant-a", agent_version="v1",
            channel=Channel.TEXT, state=RequestState.RUNNING,
        )
        run = Run(
            run_id="run-status", request_id=request.request_id, tenant_id="tenant-a",
            agent_version="v1", owner_id="owner-a",
            snapshot={"agent_id": "expert-a"},
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

        service = self.app[APPLICATION_KEY].service
        service.register_stable_version(
            tenant_id="tenant-a", agent_id="expert-b", version_id="v1",
            config=valid_config("另一个专家"),
        )
        other_request = ServiceRequest(
            request_id="req-status-other", tenant_id="tenant-a", agent_version="v1",
            channel=Channel.TEXT, state=RequestState.RUNNING,
        )
        other_run = Run(
            run_id="run-status-other", request_id=other_request.request_id, tenant_id="tenant-a",
            agent_version="v1", owner_id="owner-a", snapshot={"agent_id": "expert-b"},
        )
        store.begin_run(other_request, other_run, [])
        other_agent = await self.client.post("/api/configuration", json={
            "action": "run.status",
            "payload": {"agent_id": "expert-a", "run_id": "run-status-other"},
        })
        self.assertEqual(other_agent.status, 404)

        legacy_request = ServiceRequest(
            request_id="req-status-legacy", tenant_id="tenant-a", agent_version="v1",
            channel=Channel.TEXT, state=RequestState.RUNNING,
        )
        legacy_run = Run(
            run_id="run-status-legacy", request_id=legacy_request.request_id, tenant_id="tenant-a",
            agent_version="v1", owner_id="owner-a",
        )
        store.begin_run(legacy_request, legacy_run, [])
        legacy = await self.client.post("/api/configuration", json={
            "action": "run.status",
            "payload": {"agent_id": "expert-a", "run_id": "run-status-legacy"},
        })
        self.assertEqual(legacy.status, 404)

    async def test_run_diagnostics_projects_only_scoped_recall_and_context_fields(self):
        store = self.app[STORE_KEY]
        request = ServiceRequest(
            request_id="req-diagnostics", tenant_id="tenant-a", agent_version="v1",
            channel=Channel.TEXT, state=RequestState.RUNNING,
        )
        events = [
            RunEvent(
                seq=0, event_type="recall.diagnostic", request_id=request.request_id,
                run_id="run-diagnostics", tenant_id="tenant-a", agent_version="v1", channel="text",
                payload={"code": "selected", "candidate_count": 2, "selected_count": 1,
                         "unit_id": "退款.助手-α", "selected_unit_ids": ["退款.助手-α"],
                         "provider": "deterministic-keyword-v1",
                         "input": "PRIVATE-USER-PROMPT", "source_content": "PRIVATE-SOURCE"},
            ),
            RunEvent(
                seq=1, event_type="context.fragment", request_id=request.request_id,
                run_id="run-diagnostics", tenant_id="tenant-a", agent_version="v1", channel="text",
                payload={"scope": "skill", "stage": "concurrent", "load_status": "loaded",
                         "token_estimate": 24, "source_ref": "PRIVATE-SOURCE-PATH",
                         "activation_reason": "PRIVATE-USER-TEXT", "content": "PRIVATE-CONTEXT"},
            ),
            RunEvent(
                seq=2, event_type="recall.diagnostic", request_id=request.request_id,
                run_id="run-diagnostics", tenant_id="tenant-a", agent_version="v1", channel="text",
                payload={"code": "selected", "unit_id": "x" * 129,
                         "selected_unit_ids": ["x" * 129]},
            ),
        ]
        run = Run(
            run_id="run-diagnostics", request_id=request.request_id, tenant_id="tenant-a",
            agent_version="v1", owner_id="owner-a", snapshot={"agent_id": "expert-a"},
        )
        store.begin_run(request, run, events)

        response = await self.client.post("/api/configuration", json={
            "action": "run.diagnostics",
            "payload": {"agent_id": "expert-a", "run_id": "run-diagnostics", "limit": 1},
        })
        self.assertEqual(response.status, 200)
        result = (await response.json())["result"]
        self.assertEqual(result["run"]["run_id"], "run-diagnostics")

        max_cursor = await self.client.post("/api/configuration", json={
            "action": "run.diagnostics",
            "payload": {"agent_id": "expert-a", "run_id": "run-diagnostics",
                        "after_sequence": (1 << 63) - 1, "limit": 1},
        })
        self.assertEqual(max_cursor.status, 200)
        self.assertEqual((await max_cursor.json())["result"]["events"], [])

        overflow = await self.client.post("/api/configuration", json={
            "action": "run.diagnostics",
            "payload": {"agent_id": "expert-a", "run_id": "run-diagnostics",
                        "after_sequence": 1 << 63, "limit": 1},
        })
        self.assertEqual(overflow.status, 400)
        self.assertEqual((await overflow.json())["error"]["code"], "invalid_request")

        self.assertEqual([event["kind"] for event in result["events"]], ["recall"])
        self.assertEqual(result["events"][0]["unit_id"], "退款.助手-α")
        self.assertEqual(result["events"][0]["selected_unit_ids"], ["退款.助手-α"])
        self.assertTrue(result["has_more"])
        second_page = await self.client.post("/api/configuration", json={
            "action": "run.diagnostics",
            "payload": {"agent_id": "expert-a", "run_id": "run-diagnostics",
                        "after_sequence": result["next_cursor"], "limit": 1},
        })
        self.assertEqual(second_page.status, 200)
        page = (await second_page.json())["result"]
        self.assertEqual([event["kind"] for event in page["events"]], ["context"])
        self.assertEqual(page["events"][0]["token_estimate"], 24)
        self.assertTrue(page["has_more"])
        self.assertNotIn("PRIVATE-", json.dumps(result))
        self.assertNotIn("PRIVATE-", json.dumps(page))

        third_page = await self.client.post("/api/configuration", json={
            "action": "run.diagnostics",
            "payload": {"agent_id": "expert-a", "run_id": "run-diagnostics",
                        "after_sequence": page["next_cursor"], "limit": 1},
        })
        self.assertEqual(third_page.status, 200)
        bounded = (await third_page.json())["result"]
        self.assertEqual(bounded["events"][0]["kind"], "recall")
        self.assertNotIn("unit_id", bounded["events"][0])
        self.assertNotIn("selected_unit_ids", bounded["events"][0])
        self.assertFalse(bounded["has_more"])
        self.assertNotIn("PRIVATE-", json.dumps(bounded))

        viewer = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="viewer-a", role="viewer", agent_ids=("expert-a",),
        )
        forbidden = self.app[APPLICATION_KEY].execute(
            principal=viewer, action="run.diagnostics",
            payload={"agent_id": "expert-a", "run_id": "run-diagnostics"},
        )
        self.assertEqual(forbidden["error"]["code"], "forbidden")

        other = await self.client.post("/api/configuration", json={
            "action": "run.diagnostics",
            "payload": {"agent_id": "expert-a", "run_id": "run-status-other"},
        })
        self.assertEqual(other.status, 404)

    async def test_execution_service_diagnostics_survive_reopen_and_http_pagination(self):
        database_path = Path(self.temp.name) / "diagnostics-e2e.db"
        store = SqliteStore(str(database_path))
        config = ConfigurationService(store)
        config.register_stable_version(
            tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
            config=valid_config(),
        )

        pack = recall_pack()
        pack.agent_version.version_id = "v1"
        unit_id = "退款.助手-α"
        for unit in pack.agent_version.orchestration["units"]:
            if unit["unit_id"] == "refund-helper":
                unit["unit_id"] = unit_id
        pack.agent_version.unit_skill_bindings[unit_id] = pack.agent_version.unit_skill_bindings.pop("refund-helper")
        service = ExecutionService(
            pack, store=store, tenant_id="tenant-a", agent_id="expert-a",
            concurrent_selector=lambda candidates, context: [unit_id],
        )
        run_text = "退费怎么算 PRIVATE-RUN-SOURCE-4821"
        result = await service.handle_text(run_text, script=[{"text": "请参考退费规则。"}])
        self.assertEqual(result.request.state, RequestState.SUCCESS)
        self.assertTrue(store.load_events(result.run_id))
        emitted = store.load_events(result.run_id)
        self.assertTrue(any(event.event_type == "recall.diagnostic" for event in emitted))
        self.assertTrue(any(event.event_type == "context.fragment" for event in emitted))
        self.assertTrue(any(
            event.event_type == "recall.diagnostic"
            and event.payload.get("selected_unit_ids") == [unit_id]
            for event in emitted
        ))
        store.close()

        reopened = SqliteStore(str(database_path))
        try:
            self.assertTrue(reopened.verify_chain(result.run_id))
            self.assertTrue(reopened.load_events(result.run_id))
        finally:
            reopened.close()

        app = create_configuration_http_app(
            principal_path=self.principal_path, database_path=database_path,
        )
        client = TestClient(TestServer(app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        response = await client.post("/api/configuration", json={
            "action": "run.diagnostics",
            "payload": {"agent_id": "expert-a", "run_id": result.run_id, "limit": 1},
        })
        self.assertEqual(response.status, 200)
        pages = []
        body = (await response.json())["result"]
        pages.append(body)
        while body["has_more"]:
            response = await client.post("/api/configuration", json={
                "action": "run.diagnostics",
                "payload": {"agent_id": "expert-a", "run_id": result.run_id,
                            "after_sequence": body["next_cursor"], "limit": 1},
            })
            self.assertEqual(response.status, 200)
            body = (await response.json())["result"]
            pages.append(body)

        flattened = [event for page in pages for event in page["events"]]
        self.assertTrue(pages[0]["has_more"])
        self.assertTrue(all(page["run"]["agent_version"] == "v1" for page in pages))
        self.assertEqual(pages[0]["run"]["run_id"], result.run_id)
        self.assertIn("recall", [event["kind"] for event in flattened])
        self.assertIn("context", [event["kind"] for event in flattened])
        self.assertIn(unit_id, [
            unit for event in flattened for unit in event.get("selected_unit_ids", [])
        ])
        self.assertNotIn("PRIVATE-RUN-SOURCE-4821", json.dumps(pages, ensure_ascii=False))

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


if __name__ == "__main__":
    unittest.main()
