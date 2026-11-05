from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

from loomrise.configuration import ConfigurationPrincipal, ConfigurationService, ConfigurationValidationError
from loomrise.contact_pages import BLOCK_LABELS, contact_schema, render_contact_page, validate_contact
from loomrise.customer_service import CustomerService, CustomerServiceApplication
from loomrise.durable_store import SqliteStore
from loomrise.config_http import APPLICATION_KEY, STORE_KEY, create_configuration_http_app
from tests.test_configuration_service import spec


class ContactPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SqliteStore(os.path.join(self.tmp.name, "contact.db"))
        self.configuration = ConfigurationService(self.store)
        self.configuration.register_stable_version(
            tenant_id="tenant-a", agent_id="expert-a", version_id="v1", config={
                **spec(),
                "contact": {
                    "title": "课程咨询",
                    "description": "欢迎咨询课程安排。",
                    "blocks": [{"id": "intro", "type": "text", "title": "服务介绍", "body": "请留下问题。"}],
                },
            },
        )
        self.configuration.create_draft_from_stable(
            tenant_id="tenant-a", agent_id="expert-a", base_version_id="v1",
        )
        candidate = self.configuration.freeze_candidate(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            idempotency_key="contact-publish",
        )
        self.store.approve_release_candidate(
            tenant_id="tenant-a", agent_id="expert-a", candidate_id=candidate["candidate_id"],
            content_hash=candidate["content_hash"], environment="sandbox",
            entry_id="contact-entry", version_id="sandbox-v1", approved_by="owner",
        )
        self.store.publish_sandbox_candidate(
            tenant_id="tenant-a", agent_id="expert-a", candidate_id=candidate["candidate_id"],
            entry_id="contact-entry", version_id="sandbox-v1",
        )
        self.app = CustomerServiceApplication(CustomerService(self.store, self.configuration))
        self.owner = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="owner", role="owner", agent_ids=("expert-a",),
        )
        self.viewer = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="viewer", role="viewer", agent_ids=("expert-a",),
        )
        self.editor = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="editor", role="editor", agent_ids=("expert-a",),
        )
        self.addCleanup(self.store.close)
        self.addCleanup(self.tmp.cleanup)

    def execute(self, action: str, payload: dict, principal=None):
        return self.app.execute(principal=principal or self.owner, action=action, payload=payload)

    def test_contact_page_binds_to_approved_version_and_can_be_disabled(self):
        enabled = self.execute("contact.enable", {"agent_id": "expert-a", "entry_id": "contact-entry"})
        self.assertTrue(enabled["ok"], enabled)
        self.assertEqual(enabled["result"]["version_id"], "sandbox-v1")
        self.assertEqual(enabled["result"]["state"], "active")

        page = self.execute("contact.get", {"agent_id": "expert-a", "entry_id": "contact-entry"}, self.viewer)
        self.assertTrue(page["ok"], page)
        self.assertEqual(page["result"]["contact"]["title"], "课程咨询")
        self.assertNotIn("config", page["result"])
        self.assertNotIn("persona", json.dumps(page["result"]))
        self.assertEqual(page["result"]["share_path"], "/contact/expert-a/contact-entry")

        disabled = self.execute("contact.disable", {"agent_id": "expert-a", "entry_id": "contact-entry"})
        self.assertTrue(disabled["ok"], disabled)
        self.assertEqual(disabled["result"]["state"], "disabled")
        unavailable = self.execute("contact.get", {"agent_id": "expert-a", "entry_id": "contact-entry"}, self.viewer)
        self.assertEqual(unavailable["error"]["code"], "not_found")
        self.assertEqual(self.execute("contact.disable", {"agent_id": "expert-a", "entry_id": "contact-entry"}), disabled)

    def test_contact_page_never_reads_a_draft_or_another_expert(self):
        self.assertEqual(self.execute("contact.get", {"agent_id": "expert-a", "entry_id": "draft-only"})["error"]["code"], "not_found")
        self.assertEqual(self.execute("contact.get", {"agent_id": "expert-b", "entry_id": "contact-entry"})["error"]["code"], "forbidden")

    def test_publish_controls_require_owner_and_scope(self):
        payload = {"agent_id": "expert-a", "entry_id": "contact-entry"}
        for principal in (self.viewer, self.editor, ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="agent", role="external_agent", agent_ids=("expert-a",),
        )):
            with self.subTest(role=principal.role):
                self.assertEqual(self.execute("contact.enable", payload, principal)["error"]["code"], "forbidden")
        self.execute("contact.enable", payload)
        self.assertEqual(self.execute("contact.disable", payload, self.editor)["error"]["code"], "forbidden")
        foreign = ConfigurationPrincipal(tenant_id="tenant-b", actor_id="owner", role="owner", agent_ids=("expert-a",))
        self.assertEqual(self.execute("contact.get", payload, foreign)["error"]["code"], "not_found")
        self.assertEqual(self.execute("contact.enable", payload, foreign)["error"]["code"], "not_found")

    def test_enable_rechecks_the_version_previewed_by_the_workbench(self):
        payload = {"agent_id": "expert-a", "entry_id": "contact-entry"}
        response = self.execute('contact.enable', {**payload, 'expected_version_id': 'old-version'})
        self.assertFalse(response['ok'])
        self.assertIsNone(self.store.contact_page(tenant_id='tenant-a', agent_id='expert-a', entry_id='contact-entry'))
        self.assertTrue(self.execute('contact.enable', {**payload, 'expected_version_id': 'sandbox-v1'})['ok'])

    def test_stale_and_unapproved_releases_fail_closed(self):
        payload = {"agent_id": "expert-a", "entry_id": "contact-entry"}
        self.execute("contact.enable", payload)
        self.store.mark_sandbox_versions_for_revalidation(tenant_id="tenant-a", agent_id="expert-a")
        self.assertFalse(self.execute("contact.get", payload)["ok"])
        self.assertFalse(self.execute("contact.open", {**payload, "version_id": "sandbox-v1"})["ok"])
        self.assertFalse(self.execute("contact.enable", payload)["ok"])
        self.assertTrue(self.execute("contact.disable", payload)["ok"])

    def test_missing_approval_is_rejected_even_if_binding_exists(self):
        with self.store._tx() as cur:
            cur.execute("DELETE FROM release_approvals")
        self.assertFalse(self.execute("contact.enable", {"agent_id": "expert-a", "entry_id": "contact-entry"})["ok"])

    def test_contact_session_requires_an_explicit_version_and_active_page(self):
        payload = {"agent_id": "expert-a", "entry_id": "contact-entry"}
        for version in (None, "", False, [], {}):
            with self.subTest(version=version):
                response = self.execute("contact.open", {**payload, "version_id": version})
                self.assertFalse(response["ok"], response)
        self.assertEqual(self.execute("inbox.list", {"agent_id": "expert-a"})["result"]["items"], [])
        self.execute("contact.enable", payload)
        self.execute("contact.disable", payload)
        self.assertFalse(self.execute("contact.open", {**payload, "version_id": "sandbox-v1"})["ok"])

    def test_ambiguous_url_identifiers_cannot_enable_a_broken_share_link(self):
        entry = self.store.sandbox_entry(tenant_id="tenant-a", agent_id="expert-a", entry_id="contact-entry")
        for entry_id, version_id in (("..", "sandbox-dots"), ("bad-version", ".")):
            self.store.approve_release_candidate(tenant_id="tenant-a", agent_id="expert-a", candidate_id=entry["candidate_id"], content_hash=entry["content_hash"], environment="sandbox", entry_id=entry_id, version_id=version_id, approved_by="owner")
            self.store.publish_sandbox_candidate(tenant_id="tenant-a", agent_id="expert-a", candidate_id=entry["candidate_id"], entry_id=entry_id, version_id=version_id)
            response = self.execute("contact.enable", {"agent_id": "expert-a", "entry_id": entry_id})
            self.assertFalse(response["ok"], response)
            self.assertIsNone(self.store.contact_page(tenant_id="tenant-a", agent_id="expert-a", entry_id=entry_id))

    def test_rebinding_entry_never_changes_contact_chat_version(self):
        payload = {"agent_id": "expert-a", "entry_id": "contact-entry"}
        self.execute("contact.enable", payload)
        draft = self.configuration.get_draft(tenant_id="tenant-a", agent_id="expert-a")
        changed = deepcopy(draft["config"])
        changed["contact"]["title"] = "新版咨询"
        self.configuration.save_draft(tenant_id="tenant-a", agent_id="expert-a", expected_revision=draft["revision"], config=changed)
        candidate = self.configuration.freeze_candidate(tenant_id="tenant-a", agent_id="expert-a", expected_revision=2, idempotency_key="second")
        self.store.approve_release_candidate(tenant_id="tenant-a", agent_id="expert-a", candidate_id=candidate["candidate_id"], content_hash=candidate["content_hash"], environment="sandbox", entry_id="contact-entry", version_id="sandbox-v2", approved_by="owner")
        self.store.publish_sandbox_candidate(tenant_id="tenant-a", agent_id="expert-a", candidate_id=candidate["candidate_id"], entry_id="contact-entry", version_id="sandbox-v2")
        page = self.execute("contact.get", payload)["result"]
        self.assertEqual(page["version_id"], "sandbox-v1")
        self.assertEqual(page["contact"]["title"], "课程咨询")
        opened = self.execute("contact.open", {**payload, "version_id": "sandbox-v1"})
        self.assertTrue(opened["ok"], opened)
        session = opened["result"]
        self.assertEqual(session["version_id"], "sandbox-v1")
        self.assertTrue(self.execute("widget.send", {"conversation_id": session["conversation_id"], "visitor_token": session["visitor_token"], "text": "请人工联系我", "request_human": True})["ok"])
        inbox = self.execute("inbox.list", {"agent_id": "expert-a"})["result"]["items"]
        self.assertEqual(inbox[0]["release_version"], "sandbox-v1")
        self.execute("contact.enable", payload)
        self.assertFalse(self.execute("contact.open", {**payload, "version_id": "sandbox-v1"})["ok"])
        self.assertEqual(self.execute("contact.get", payload)["result"]["version_id"], "sandbox-v2")

    def test_contact_binding_and_disable_survive_backup_and_restart(self):
        payload = {"agent_id": "expert-a", "entry_id": "contact-entry"}
        self.execute("contact.enable", payload)
        backup = os.path.join(self.tmp.name, "backup.db")
        self.store.backup_to(backup)
        restored = SqliteStore(backup)
        try:
            app = CustomerServiceApplication(CustomerService(restored, ConfigurationService(restored)))
            self.assertEqual(app.execute(principal=self.owner, action="contact.get", payload=payload)["result"]["version_id"], "sandbox-v1")
            app.execute(principal=self.owner, action="contact.disable", payload=payload)
        finally:
            restored.close()
        reopened = SqliteStore(backup)
        try:
            app = CustomerServiceApplication(CustomerService(reopened, ConfigurationService(reopened)))
            self.assertEqual(app.execute(principal=self.owner, action="contact.get", payload=payload)["error"]["code"], "not_found")
            self.assertTrue(app.execute(principal=self.owner, action="contact.disable", payload=payload)["ok"])
        finally:
            reopened.close()

    def test_template_edit_and_preview_use_only_shared_revisioned_draft(self):
        templates = self.execute("contact.templates", {"agent_id": "expert-a"})
        self.assertTrue(templates["ok"], templates)
        template = templates["result"]["items"][0]["contact"]
        template["title"] = "待审核新标题"
        before = self.configuration.get_draft(tenant_id="tenant-a", agent_id="expert-a")
        self.execute("contact.enable", {"agent_id": "expert-a", "entry_id": "contact-entry"})
        saved = self.execute("contact.save", {"agent_id": "expert-a", "expected_revision": before["revision"], "contact": template}, self.editor)
        self.assertTrue(saved["ok"], saved)
        draft = self.configuration.get_draft(tenant_id="tenant-a", agent_id="expert-a")
        self.assertEqual(draft["config"]["contact"]["title"], "待审核新标题")
        self.assertEqual(draft["config"]["persona"], before["config"]["persona"])
        preview = self.execute("contact.preview", {"agent_id": "expert-a"})["result"]
        self.assertEqual(preview["revision"], draft["revision"])
        self.assertEqual(preview["contact"]["title"], "待审核新标题")
        self.assertEqual(preview["state"], "draft")
        self.assertNotIn("share_path", preview)
        self.assertEqual(self.execute("contact.get", {"agent_id": "expert-a", "entry_id": "contact-entry"})["result"]["contact"]["title"], "课程咨询")
        conflict = self.execute("contact.save", {"agent_id": "expert-a", "expected_revision": before["revision"], "contact": template})
        self.assertEqual(conflict["error"]["code"], "revision_conflict")

    def test_incomplete_shared_draft_cannot_freeze_and_can_be_repaired(self):
        draft = self.configuration.get_draft(tenant_id="tenant-a", agent_id="expert-a")
        config = draft["config"]
        config["contact"] = {"blocks": [{"id": "x", "type": "script", "body": "alert(1)"}]}
        self.configuration.save_draft(tenant_id="tenant-a", agent_id="expert-a", expected_revision=1, config=config)
        invalid = self.execute("contact.preview", {"agent_id": "expert-a"})
        self.assertEqual(invalid["error"]["code"], "invalid_request")
        with self.assertRaises(ConfigurationValidationError) as caught:
            self.configuration.freeze_candidate(tenant_id="tenant-a", agent_id="expert-a", expected_revision=2, idempotency_key="invalid-contact")
        self.assertTrue(any(issue["code"] == "invalid_contact_page" for issue in caught.exception.issues))
        repaired = self.execute("contact.save", {"agent_id": "expert-a", "expected_revision": 2, "contact": {"title": "修复后的联系页", "blocks": []}})
        self.assertTrue(repaired["ok"], repaired)
        self.assertEqual(repaired["result"]["revision"], 3)

    def test_generated_content_validation_is_editable_and_does_not_save_or_publish(self):
        content = {"title": "生成候选", "blocks": [{"id": "intro", "type": "text", "body": "<b>文字而非 HTML</b>"}]}
        response = self.execute("contact.validate", {"agent_id": "expert-a", "contact": content})
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"]["state"], "proposal")
        self.assertEqual(response["result"]["contact"]["blocks"][0]["body"], content["blocks"][0]["body"])
        self.assertEqual(self.configuration.get_draft(tenant_id="tenant-a", agent_id="expert-a")["revision"], 1)
        self.assertFalse(self.execute("contact.get", {"agent_id": "expert-a", "entry_id": "contact-entry"})["ok"])

    def test_first_contact_edit_can_add_contact_to_an_existing_configuration(self):
        draft = self.configuration.get_draft(tenant_id="tenant-a", agent_id="expert-a")
        draft["config"].pop("contact")
        self.configuration.save_draft(tenant_id="tenant-a", agent_id="expert-a", expected_revision=1, config=draft["config"])
        saved = self.execute("contact.save", {"agent_id": "expert-a", "expected_revision": 2, "contact": {"title": "首次配置"}})
        self.assertTrue(saved["ok"], saved)
        self.assertEqual(saved["result"]["revision"], 3)


class ContactSchemaTests(unittest.TestCase):
    def test_all_baseline_blocks_have_data_and_empty_rendering(self):
        samples = {
            "text": None, "chat": None,
            "social": {"label": "社区", "href": "https://example.test/community"},
            "link": {"label": "主页", "href": "https://example.test"},
            "portfolio": {"title": "案例", "description": "虚构作品"},
            "media": {"src": "https://example.test/a.png", "alt": "虚构图片", "media_type": "image"},
            "services": {"title": "咨询服务"}, "testimonials": {"quote": "体验良好", "author": "虚构客户"},
            "booking": {"label": "预约", "href": "https://example.test/book"},
            "faq": {"question": "如何咨询？", "answer": "点击客服入口。"},
            "metrics": {"label": "服务项目", "value": "3"}, "menu": {"title": "示例商品", "price": "请咨询"},
            "hours": {"day": "周一至周五", "hours": "09:00–18:00 Asia/Shanghai"},
            "location": {"label": "咨询中心", "address": "虚构地址"},
            "skills": {"label": "课程咨询"}, "experience": {"title": "示例经历", "period": "2025–2026"},
            "schedule": {"title": "咨询日", "time": "2026-11-01 10:00 Asia/Shanghai"},
            "jobs": {"title": "示例岗位", "location": "线上"},
            "community": {"label": "开发者社区", "href": "https://example.test/dev"},
            "qr": {"label": "联系二维码", "src": "https://example.test/qr.png", "alt": "联系二维码"},
            "contact": {"label": "邮箱", "value": "hello@example.test", "href": "mailto:hello@example.test"},
        }
        self.assertEqual(set(samples), set(BLOCK_LABELS))
        self.assertEqual({item["type"] for item in contact_schema()["block_types"]}, set(samples))
        for kind, item in samples.items():
            with self.subTest(kind=kind):
                block = {"id": kind, "type": kind, "items": [item] if item else []}
                if kind == "text":
                    block["body"] = "__BLOCKS__ </script><img src=x onerror=alert(1)>"
                content = validate_contact({"title": "展示", "blocks": [block]})
                rendered = render_contact_page({"contact": content, "chat_path": "/contact/e/p/chat/v1", "version_id": "v1"})
                self.assertIn(f'data-block-type="{kind}"', rendered)
                self.assertNotIn("<script", rendered)
                self.assertNotIn("<img src=x", rendered)
                if item:
                    self.assertNotIn("暂无内容", rendered)
                if kind == "booking":
                    self.assertIn("不代表预约成功", rendered)
                empty = render_contact_page({"contact": {"blocks": [{"id": kind, "type": kind}]}}, preview=True)
                self.assertIn("预览中不会创建访客会话" if kind == "chat" else "暂无内容", empty)

    def test_malformed_and_executable_candidate_shapes_are_rejected(self):
        invalid = [None, [], "text", {"schema_version": "future"}, {"title": []},
                   {"html": "<script>alert(1)</script>"}, {"blocks": {}},
                   {"blocks": [{"id": "x", "type": "unknown"}]},
                   {"blocks": [{"id": "x", "type": "text"}, {"id": "x", "type": "chat"}]},
                   {"blocks": [{"id": "x", "type": "faq", "items": [{"question": "Q"}]}]},
                   {"blocks": [{"id": "x", "type": "link", "items": [{"label": "x", "href": "javascript:alert(1)"}]}]},
                   {"blocks": [{"id": "x", "type": "media", "items": [{"src": "data:text/html,<script>x</script>", "alt": "x", "media_type": "image"}]}]},
                   {"blocks": [{"id": "x", "type": "social", "items": [{"label": "x", "href": "https://example.test", "onclick": "alert(1)"}]}]}]
        for content in invalid:
            with self.subTest(content=content):
                with self.assertRaises(ValueError):
                    validate_contact(content)

    def test_media_audio_video_and_safe_links_remain_constrained(self):
        for media_type in ("audio", "video"):
            contact = {"blocks": [{"id": "m", "type": "media", "items": [{"src": "https://example.test/media", "alt": "示例", "media_type": media_type}]}]}
            html = render_contact_page({"contact": contact}, preview=True)
            self.assertIn(f"<{media_type} controls", html)
            self.assertIn('preload="none"', html)
        for url in ("//example.test", "https://user:pass@example.test", "https://example.test\\@evil.test", "https://example.test\npath", "http://example.test"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_contact({"blocks": [{"id": "l", "type": "link", "items": [{"label": "L", "href": url}]}]})


class ContactHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        principal = root / "principal.json"
        principal.write_text(json.dumps({"tenant_id": "tenant-a", "actor_id": "owner", "role": "owner", "agent_ids": ["expert-a"]}), encoding="utf-8")
        principal.chmod(0o600)
        self.app = create_configuration_http_app(principal_path=principal, database_path=root / "contact.db")
        service = self.app[APPLICATION_KEY].service
        service.register_stable_version(tenant_id="tenant-a", agent_id="expert-a", version_id="v1", config={**spec(), "contact": {"title": "</script><img src=x onerror=alert(1)>", "blocks": [{"id": "chat", "type": "chat", "title": "咨询"}]}})
        service.create_draft_from_stable(tenant_id="tenant-a", agent_id="expert-a", base_version_id="v1")
        candidate = service.freeze_candidate(tenant_id="tenant-a", agent_id="expert-a", expected_revision=1, idempotency_key="http")
        store = self.app[STORE_KEY]
        store.approve_release_candidate(tenant_id="tenant-a", agent_id="expert-a", candidate_id=candidate["candidate_id"], content_hash=candidate["content_hash"], environment="sandbox", entry_id="contact-entry", version_id="sandbox-v1", approved_by="owner")
        store.publish_sandbox_candidate(tenant_id="tenant-a", agent_id="expert-a", candidate_id=candidate["candidate_id"], entry_id="contact-entry", version_id="sandbox-v1")
        store.enable_contact_page(tenant_id="tenant-a", agent_id="expert-a", entry_id="contact-entry")
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def test_public_page_escapes_content_and_links_to_fixed_version_chat(self):
        response = await self.client.get("/contact/expert-a/contact-entry")
        self.assertEqual(response.status, 200)
        body = await response.text()
        self.assertNotIn("</script><img", body)
        self.assertNotIn("/widget/expert-a/contact-entry", body)
        self.assertIn("sandbox-v1", body)
        self.assertNotIn("persona", body)
        self.assertIn("no-store", response.headers["Cache-Control"])

    async def test_stale_http_page_and_chat_are_unavailable(self):
        self.app[STORE_KEY].mark_sandbox_versions_for_revalidation(tenant_id="tenant-a", agent_id="expert-a")
        page = await self.client.get("/contact/expert-a/contact-entry")
        self.assertEqual(page.status, 409)
        self.assertNotIn("onerror", await page.text())
        chat = await self.client.get("/contact/expert-a/contact-entry/chat/sandbox-v1")
        self.assertEqual(chat.status, 409)

    async def test_preview_is_a_draft_without_a_live_chat_link(self):
        preview = await self.client.get("/contact-preview/expert-a")
        self.assertEqual(preview.status, 200)
        body = await preview.text()
        self.assertIn("草稿预览", body)
        self.assertNotIn('class="chat" href=', body)
        self.assertIsNotNone(preview.headers.get("Content-Security-Policy"))
        forbidden = await self.client.get("/contact-preview/expert-b")
        self.assertEqual(forbidden.status, 403)

    async def test_disabled_or_wrong_version_cannot_open_chat(self):
        wrong = await self.client.get("/contact/expert-a/contact-entry/chat/not-approved")
        self.assertEqual(wrong.status, 409)
        self.app[STORE_KEY].disable_contact_page(tenant_id="tenant-a", agent_id="expert-a", entry_id="contact-entry")
        disabled = await self.client.get("/contact/expert-a/contact-entry/chat/sandbox-v1")
        self.assertEqual(disabled.status, 404)

    async def test_contact_chat_reuses_widget_with_an_explicit_version(self):
        chat = await self.client.get("/contact/expert-a/contact-entry/chat/sandbox-v1")
        self.assertEqual(chat.status, 200)
        self.assertIn('data-contact-version="sandbox-v1"', await chat.text())
        widget = await self.client.get("/widget/expert-a/contact-entry")
        self.assertIn('data-contact-version=""', await widget.text())

    async def test_malformed_persisted_contact_returns_recoverable_error(self):
        with self.app[STORE_KEY]._tx() as cur:
            row = cur.execute("SELECT config_json FROM sandbox_releases").fetchone()
            config = json.loads(row["config_json"])
            config["contact"] = ["not-an-object"]
            cur.execute("UPDATE sandbox_releases SET config_json=?", (json.dumps(config),))
        response = await self.client.get("/contact/expert-a/contact-entry")
        self.assertEqual(response.status, 400)
        self.assertIn("联系页", await response.text())


if __name__ == "__main__":
    unittest.main()
