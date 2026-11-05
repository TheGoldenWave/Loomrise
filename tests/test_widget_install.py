from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

from loomrise.config_http import APPLICATION_KEY, CUSTOMER_APPLICATION_KEY, PRINCIPAL_KEY, STORE_KEY, create_configuration_http_app
from tests.test_config_http import valid_config


class WidgetInstallHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        principal_path = root / "principal.json"
        principal_path.write_text(json.dumps({
            "tenant_id": "tenant-a", "actor_id": "owner-a", "role": "owner",
            "agent_ids": ["expert-a"],
        }), encoding="utf-8")
        os.chmod(principal_path, 0o600)
        self.allowed_origin = "http://127.0.0.1:8799"
        self.app = create_configuration_http_app(
            principal_path=principal_path,
            database_path=root / "widget-install.db",
            allowed_origins={self.allowed_origin},
        )
        service = self.app[APPLICATION_KEY].service
        service.register_stable_version(
            tenant_id="tenant-a", agent_id="expert-a", version_id="v1", config=valid_config(),
        )
        service.create_draft_from_stable(
            tenant_id="tenant-a", agent_id="expert-a", base_version_id="v1",
        )
        candidate = service.freeze_candidate(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            idempotency_key="widget-install-fixture",
        )
        store = self.app[STORE_KEY]
        store.approve_release_candidate(
            tenant_id="tenant-a", agent_id="expert-a", candidate_id=candidate["candidate_id"],
            content_hash=candidate["content_hash"], environment="sandbox", entry_id="entry-a",
            version_id="sandbox-v1", approved_by="owner-a",
        )
        store.publish_sandbox_candidate(
            tenant_id="tenant-a", agent_id="expert-a", candidate_id=candidate["candidate_id"],
            entry_id="entry-a", version_id="sandbox-v1",
        )
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.addCleanup(self.temp.cleanup)

    async def test_loader_is_served_only_for_known_public_instance_and_allowed_origin(self):
        response = await self.client.get(
            "/widget.js?agent_id=expert-a&entry_id=entry-a",
            headers={"Origin": self.allowed_origin},
        )
        self.assertEqual(response.status, 200)
        self.assertTrue(response.content_type in {"application/javascript", "text/javascript"})
        script = await response.text()
        self.assertIn("expert-a", script)
        self.assertIn("entry-a", script)
        self.assertIn(self.allowed_origin, script)
        self.assertNotIn("tenant-a", script)
        self.assertNotIn("owner-a", script)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], self.allowed_origin)

        denied = await self.client.get(
            "/widget.js?agent_id=expert-a&entry_id=entry-a",
            headers={"Origin": "http://127.0.0.1:8800"},
        )
        self.assertEqual(denied.status, 403)

    async def test_loader_rejects_malformed_or_unknown_public_instance_ids(self):
        for query, expected in (
            ("agent_id=expert-a&entry_id=missing", 404),
            ("agent_id=../other&entry_id=entry-a", 400),
            ("agent_id=expert-a&entry_id=entry-a&entry_id=other", 400),
            ("tenant=tenant-a", 400),
        ):
            with self.subTest(query=query):
                response = await self.client.get(f"/widget.js?{query}")
                self.assertEqual(response.status, expected)

    async def test_widget_frame_policy_contains_only_self_and_configured_local_sources(self):
        response = await self.client.get("/widget/expert-a/entry-a")
        self.assertEqual(response.status, 200)
        policy = response.headers["Content-Security-Policy"]
        self.assertIn("frame-ancestors 'self'", policy)
        self.assertIn(self.allowed_origin, policy)
        self.assertNotIn("http://127.0.0.1:8800", policy)

    async def test_loader_origin_and_instance_errors_do_not_open_a_visitor_session(self):
        store = self.app[STORE_KEY]
        with store._lock:
            before = store._conn.execute(
                "SELECT COUNT(*) FROM customer_conversations WHERE tenant_id=? AND agent_id=?",
                ("tenant-a", "expert-a"),
            ).fetchone()[0]
        unknown = await self.client.get("/widget.js?agent_id=expert-a&entry_id=missing")
        denied = await self.client.get(
            "/widget.js?agent_id=expert-a&entry_id=entry-a",
            headers={"Origin": "https://not-allowed.invalid"},
        )
        self.assertIn(unknown.status, {400, 404})
        self.assertEqual(denied.status, 403)
        with store._lock:
            after = store._conn.execute(
                "SELECT COUNT(*) FROM customer_conversations WHERE tenant_id=? AND agent_id=?",
                ("tenant-a", "expert-a"),
            ).fetchone()[0]
        self.assertEqual(after, before)

    async def test_widget_api_roundtrip_persists_inbox_event_and_human_reply(self):
        async def invoke(action, payload):
            response = await self.client.post("/api/customer-service", json={
                "action": action, "payload": payload,
            })
            self.assertEqual(response.status, 200, await response.text())
            value = await response.json()
            self.assertTrue(value["ok"], value["error"])
            return value["result"]

        session = await invoke("widget.open", {"agent_id": "expert-a", "entry_id": "entry-a"})
        posted = await invoke("widget.send", {
            "conversation_id": session["conversation_id"], "visitor_token": session["visitor_token"],
            "text": "请人工客服联系我", "request_human": True,
        })
        self.assertEqual(posted["reception"]["status"], "human_requested")

        principal = self.app[PRINCIPAL_KEY]
        customer = self.app[CUSTOMER_APPLICATION_KEY]
        events = customer.execute(principal=principal, action="inbox.events", payload={
            "agent_id": "expert-a", "after_sequence": 0,
        })["result"]["events"]
        self.assertIn("visitor.message", [event["event_type"] for event in events])

        claim = await invoke("inbox.claim", {
            "agent_id": "expert-a", "conversation_id": session["conversation_id"],
        })
        await invoke("inbox.reply", {
            "agent_id": "expert-a", "conversation_id": session["conversation_id"],
            "generation": claim["occupancy_generation"], "text": "您好，人工已接管。",
        })
        messages = await invoke("widget.messages", {
            "conversation_id": session["conversation_id"], "visitor_token": session["visitor_token"],
        })
        self.assertEqual(messages["items"][-1]["text"], "您好，人工已接管。")


if __name__ == "__main__":
    unittest.main()
