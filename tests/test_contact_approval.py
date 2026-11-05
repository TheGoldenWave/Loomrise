"""M-B-05 完整批准/发布/停用/分享路径的本机端到端证据。

判断（见交付报告）：服务端「真实可跑的批准 + 版本绑定」能力确实存在，分两层：

* 策略/编排层：ConfigurationApplication 的 release.approve / release.publish /
  release.entry.resolve，以及 config_cli.py 的 release approve/publish、MCP 的
  loomrise_release_approve。它们经 release_checklist 治理预检，其中 fixed_samples /
  fixed_samples_passed 依赖外部「固定样例执行服务 / 21 类真实模型多样本 + 真人角色基线」，
  本机不可满足，故这两个 action 在本机恒为 release_blocked（fail-closed）。这正是 M-B-05
  把多样本质量与角色基线列为外部缺口的原因，本模块不伪造、不放宽该门禁。
* 执行/存储层：store.approve_release_candidate / publish_sandbox_candidate /
  enable_contact_page 是真实、可执行、带校验的批准-发布-绑定引擎：批准绑定冻结候选的
  content_hash、发布时重验批准存在且版本 ID 不可漂移、启用时同一事务 JOIN
  release_approvals 重验批准与入口版本并校验 expected_version_id。CLI / MCP /
  ConfigurationService.approve_sandbox_release / publish_sandbox_candidate 最终都委托给
  这些方法。

现有 contact-matrix-fixture-v1（r1_configuration_http_fixture.py 第 147/164 行注释：
"Storage-level fixture setup is not evidence that publication checks passed" /
"Explicit fixture approval only; production prechecks remain blocking"）与
tests/test_contact_page.py 的 setUp 都只是「预置批准快照」，只支撑渲染 / enable-get-disable
断言，没有任何测试把「保存草稿→冻结提交→批准→发布→绑定→公开只读→分享→停用→重启用」
作为一条动作序列逐步走完并断言。

因此服务端已有批准能力（走任务 2）：本模块不改任何生产代码、不放宽任何校验、不注入伪造
批准行，只用真实服务/存储动作逐步走完完整路径并断言每个状态跃迁，并显式验证治理层
release.approve/publish 的 owner-only 与 release_blocked fail-closed。
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
import tempfile
import unittest

from loomrise.configuration import (
    ConfigurationApplication,
    ConfigurationPrincipal,
    ConfigurationService,
)
from loomrise.contact_pages import validate_contact
from loomrise.customer_service import CustomerService, CustomerServiceApplication
from loomrise.durable_store import SqliteStore
from tests.test_configuration_service import spec
from tests.test_contact_generation import GenerationProvider

ENTRY_ID = "contact-entry"
VERSION_V1 = "sandbox-v1"
VERSION_V2 = "sandbox-v2"

BASE_CONTACT = {
    "title": "课程咨询",
    "description": "欢迎咨询课程安排。",
    "blocks": [{"id": "intro", "type": "text", "title": "服务介绍", "body": "请留下问题。"}],
}
# 手动结构化编辑后的草稿内容（与初始稳定版本不同）。
EDITED_CONTACT = {
    "title": "结构化编辑后的标题",
    "description": "人工核对后的说明。",
    "blocks": [
        {"id": "intro", "type": "text", "title": "服务介绍", "body": "已人工核对。"},
        {"id": "chat", "type": "chat", "title": "咨询客服", "body": "", "items": []},
    ],
}
# 启用批准版后对草稿的再次修改：用于证明公开页与草稿隔离。
DRAFT_ONLY_CONTACT = {"title": "草稿新标题，不应影响已启用页面", "description": "", "blocks": []}


class ContactApprovalPathTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SqliteStore(os.path.join(self.tmp.name, "contact-approval.db"))
        self.configuration = ConfigurationService(self.store)
        # 只建立稳定版本 + 共享草稿；setUp 不预置任何批准/发布/启用快照。
        self.configuration.register_stable_version(
            tenant_id="tenant-a", agent_id="expert-a", version_id="v1",
            config={**spec(), "contact": deepcopy(BASE_CONTACT)},
        )
        self.configuration.create_draft_from_stable(
            tenant_id="tenant-a", agent_id="expert-a", base_version_id="v1",
        )
        self.config_app = ConfigurationApplication(self.configuration)
        self.provider = GenerationProvider()
        self.service = CustomerService(
            self.store, self.configuration, contact_generation_provider=self.provider,
        )
        self.app = CustomerServiceApplication(self.service)
        self.owner = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="owner", role="owner", agent_ids=("expert-a",),
        )
        self.editor = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="editor", role="editor", agent_ids=("expert-a",),
        )
        self.viewer = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="viewer", role="viewer", agent_ids=("expert-a",),
        )
        self.external = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="agent", role="external_agent", agent_ids=("expert-a",),
        )
        self.foreign = ConfigurationPrincipal(
            tenant_id="tenant-b", actor_id="owner", role="owner", agent_ids=("expert-a",),
        )
        self.other_agent = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="owner", role="owner", agent_ids=("expert-b",),
        )
        self.addCleanup(self.store.close)
        self.addCleanup(self.tmp.cleanup)

    # ---- 测试辅助：一律走真实的服务/存储动作，不注入伪造批准行 ----

    def execute(self, action, payload, principal=None):
        return self.app.execute(principal=principal or self.owner, action=action, payload=payload)

    def config_execute(self, action, payload, principal=None):
        return self.config_app.execute(
            principal=principal or self.owner, action=action, payload=payload,
        )

    def draft(self):
        return self.configuration.get_draft(tenant_id="tenant-a", agent_id="expert-a")

    def freeze(self, expected_revision, idempotency_key, principal=None):
        """通过配置应用真实提交审批：把共享草稿冻结为不可变、内容哈希绑定的候选。"""
        return self.config_execute(
            "candidate.freeze",
            {"agent_id": "expert-a", "expected_revision": expected_revision,
             "idempotency_key": idempotency_key},
            principal,
        )

    def freeze_current_draft(self, idempotency_key):
        response = self.freeze(self.draft()["revision"], idempotency_key)
        self.assertTrue(response["ok"], response)
        return response["result"]

    def approve(self, candidate, *, entry_id=ENTRY_ID, version_id=VERSION_V1, approved_by="owner"):
        """真实的人工批准：绑定冻结候选 content_hash + 入口 + 版本，不可变。"""
        return self.store.approve_release_candidate(
            tenant_id="tenant-a", agent_id="expert-a",
            candidate_id=candidate["candidate_id"], content_hash=candidate["content_hash"],
            environment="sandbox", entry_id=entry_id, version_id=version_id,
            approved_by=approved_by,
        )

    def publish(self, candidate, *, entry_id=ENTRY_ID, version_id=VERSION_V1):
        """真实的发布：重验批准存在、版本 ID 不可漂移、原子化绑定沙盒入口。"""
        return self.store.publish_sandbox_candidate(
            tenant_id="tenant-a", agent_id="expert-a",
            candidate_id=candidate["candidate_id"], entry_id=entry_id, version_id=version_id,
        )

    def publish_live_page(self, *, entry_id=ENTRY_ID, version_id=VERSION_V1, key="live"):
        """反例测试的公共前置：真实跑一遍 freeze→approve→publish→enable。"""
        candidate = self.freeze_current_draft(key)
        self.approve(candidate, entry_id=entry_id, version_id=version_id)
        self.publish(candidate, entry_id=entry_id, version_id=version_id)
        enabled = self.execute(
            "contact.enable",
            {"agent_id": "expert-a", "entry_id": entry_id, "expected_version_id": version_id},
        )
        self.assertTrue(enabled["ok"], enabled)
        return enabled["result"]

    # ---- 正向：完整批准 / 发布 / 停用 / 分享路径 ----

    async def test_full_approval_publish_share_disable_reenable_path(self):
        payload = {"agent_id": "expert-a", "entry_id": ENTRY_ID}

        # 0) 初始：只有共享草稿 r1，没有任何公开页。
        self.assertFalse(self.execute("contact.get", payload)["ok"])
        self.assertEqual(self.draft()["revision"], 1)

        # 1) 草稿保存 / 结构化编辑（revision 1 -> 2）。
        saved = self.execute("contact.save", {
            "agent_id": "expert-a", "expected_revision": 1, "contact": deepcopy(EDITED_CONTACT),
        })
        self.assertTrue(saved["ok"], saved)
        self.assertEqual(saved["result"]["revision"], 2)
        self.assertEqual(self.draft()["config"]["contact"]["title"], EDITED_CONTACT["title"])

        # 2) 生成待审候选：是 proposal，不落盘、不发布、不改动草稿。
        proposal = await self.app.execute_async(
            principal=self.owner, action="contact.generate",
            payload={"agent_id": "expert-a", "expected_revision": 2,
                     "brief": "虚构工坊提供课程咨询，保留客服入口。", "template_id": "support"},
        )
        self.assertTrue(proposal["ok"], proposal)
        self.assertEqual(proposal["result"]["state"], "proposal")
        self.assertEqual(proposal["result"]["base_revision"], 2)
        self.assertEqual(self.draft()["config"]["contact"]["title"], EDITED_CONTACT["title"])
        self.assertFalse(self.execute("contact.get", payload)["ok"])
        expected_contact = validate_contact(proposal["result"]["contact"])

        # 3) 显式采用：候选不会自动保存，必须作为 contact.save 的输入才进入共享草稿。
        adopted = self.execute("contact.save", {
            "agent_id": "expert-a", "expected_revision": 2,
            "contact": deepcopy(proposal["result"]["contact"]),
        })
        self.assertTrue(adopted["ok"], adopted)
        self.assertEqual(adopted["result"]["revision"], 3)
        self.assertEqual(self.draft()["config"]["contact"], expected_contact)

        # 4) 提交批准：冻结为不可变候选，内容哈希绑定当前草稿内容。
        frozen = self.freeze_current_draft("end-to-end")
        self.assertEqual(frozen["status"], "frozen")
        self.assertTrue(frozen["content_hash"])
        frozen_candidate = self.configuration.get_candidate(
            tenant_id="tenant-a", agent_id="expert-a", candidate_id=frozen["candidate_id"],
        )
        self.assertEqual(frozen_candidate["config"]["contact"], expected_contact)
        # 未经批准，启用必须失败（fail-closed）。
        self.assertFalse(self.execute("contact.enable", payload)["ok"])

        # 5) 批准：绑定冻结哈希、入口、版本的不可变人工批准。
        approval = self.approve(frozen)
        self.assertEqual(approval["approved_by"], "owner")
        self.assertEqual(approval["content_hash"], frozen["content_hash"])
        # 仅批准但未发布，仍无沙盒入口，启用依旧被拒。
        self.assertFalse(self.execute("contact.enable", payload)["ok"])

        # 6) 发布：重验批准存在，原子化绑定沙盒入口与版本。
        published = self.publish(frozen)
        self.assertEqual(published["version_id"], VERSION_V1)
        # 工作台「查看入口版本」：配置应用解析已批准的入口，得到 fixed version_id。
        resolved = self.config_execute(
            "release.entry.resolve", {"agent_id": "expert-a", "entry_id": ENTRY_ID},
        )
        self.assertTrue(resolved["ok"], resolved)
        self.assertEqual(resolved["result"]["version_id"], VERSION_V1)

        # 7) 批准版固定绑定：启用必须携带工作台预览过的 expected_version_id。
        drift = self.execute("contact.enable", {**payload, "expected_version_id": "drifted-version"})
        self.assertFalse(drift["ok"])
        self.assertIsNone(self.store.contact_page(
            tenant_id="tenant-a", agent_id="expert-a", entry_id=ENTRY_ID,
        ))
        enabled = self.execute("contact.enable", {**payload, "expected_version_id": VERSION_V1})
        self.assertTrue(enabled["ok"], enabled)
        self.assertEqual(enabled["result"]["state"], "active")
        self.assertEqual(enabled["result"]["version_id"], VERSION_V1)
        self.assertEqual(enabled["result"]["share_path"], "/contact/expert-a/contact-entry")
        self.assertEqual(enabled["result"]["chat_path"],
                         "/contact/expert-a/contact-entry/chat/sandbox-v1")

        # 8) 公开页只读且与草稿隔离：viewer 可读，不泄露 config / persona。
        page = self.execute("contact.get", payload, self.viewer)
        self.assertTrue(page["ok"], page)
        self.assertEqual(page["result"]["version_id"], VERSION_V1)
        self.assertEqual(page["result"]["contact"], expected_contact)
        self.assertNotIn("config", page["result"])
        self.assertNotIn("persona", json.dumps(page["result"]))
        self.assertIn("content_hash", page["result"])

        # 草稿继续修改（revision 3 -> 4），公开页仍固定绑定批准版内容。
        changed = self.execute("contact.save", {
            "agent_id": "expert-a", "expected_revision": 3, "contact": deepcopy(DRAFT_ONLY_CONTACT),
        })
        self.assertTrue(changed["ok"], changed)
        self.assertEqual(self.draft()["revision"], 4)
        preview = self.execute("contact.preview", {"agent_id": "expert-a"})["result"]
        self.assertEqual(preview["contact"]["title"], DRAFT_ONLY_CONTACT["title"])
        live = self.execute("contact.get", payload)["result"]
        self.assertEqual(live["contact"], expected_contact)
        self.assertEqual(live["version_id"], VERSION_V1)

        # 9) 分享：固定版本路径与版本绑定的咨询会话。
        self.assertEqual(live["share_path"], "/contact/expert-a/contact-entry")
        self.assertEqual(live["chat_path"], "/contact/expert-a/contact-entry/chat/sandbox-v1")
        opened = self.execute("contact.open", {**payload, "version_id": VERSION_V1})
        self.assertTrue(opened["ok"], opened)
        self.assertEqual(opened["result"]["version_id"], VERSION_V1)
        self.assertFalse(self.execute("contact.open", {**payload, "version_id": "not-approved"})["ok"])

        # 10) 停用 -> 公开页 404，版本会话也不可用。
        disabled = self.execute("contact.disable", payload)
        self.assertTrue(disabled["ok"], disabled)
        self.assertEqual(disabled["result"]["state"], "disabled")
        self.assertEqual(self.execute("contact.get", payload)["error"]["code"], "not_found")
        self.assertFalse(self.execute("contact.open", {**payload, "version_id": VERSION_V1})["ok"])

        # 11) 重新启用：同一批准版再次可公开读取。
        reenabled = self.execute("contact.enable", {**payload, "expected_version_id": VERSION_V1})
        self.assertTrue(reenabled["ok"], reenabled)
        self.assertEqual(reenabled["result"]["state"], "active")
        self.assertEqual(self.execute("contact.get", payload)["result"]["version_id"], VERSION_V1)
        self.assertEqual(self.execute("contact.get", payload)["result"]["contact"], expected_contact)

    # ---- 反例：revision 冲突 ----

    async def test_revision_conflicts_reject_stale_saves_and_freezes(self):
        stale = self.execute("contact.save", {
            "agent_id": "expert-a", "expected_revision": 0, "contact": {"title": "过期"},
        })
        self.assertEqual(stale["error"]["code"], "revision_conflict")

        saved = self.execute("contact.save", {
            "agent_id": "expert-a", "expected_revision": 1,
            "contact": {"title": "合法保存", "blocks": []},
        })
        self.assertTrue(saved["ok"], saved)
        self.assertEqual(self.draft()["revision"], 2)

        stale_again = self.execute("contact.save", {
            "agent_id": "expert-a", "expected_revision": 1, "contact": {"title": "再次过期", "blocks": []},
        })
        self.assertEqual(stale_again["error"]["code"], "revision_conflict")

        stale_freeze = self.freeze(1, "stale-revision")
        self.assertEqual(stale_freeze["error"]["code"], "revision_conflict")
        self.assertEqual(self.configuration.list_candidates(
            tenant_id="tenant-a", agent_id="expert-a",
        ), [])

    # ---- 反例：viewer / 只读权限不可批准、冻结、启用 ----

    async def test_viewer_read_only_and_non_owner_cannot_approve_publish_or_enable(self):
        candidate = self.freeze_current_draft("roles")
        approve_payload = {
            "agent_id": "expert-a", "candidate_id": candidate["candidate_id"],
            "entry_id": ENTRY_ID, "version_id": VERSION_V1,
        }
        for principal in (self.viewer, self.editor, self.external):
            with self.subTest(role=principal.role, action="release.approve"):
                self.assertEqual(
                    self.config_execute("release.approve", approve_payload, principal)["error"]["code"],
                    "forbidden",
                )
            with self.subTest(role=principal.role, action="release.publish"):
                self.assertEqual(
                    self.config_execute("release.publish", approve_payload, principal)["error"]["code"],
                    "forbidden",
                )
        # viewer 连草稿冻结（提交审批）都不允许。
        self.assertEqual(self.freeze(1, "viewer-freeze", self.viewer)["error"]["code"], "forbidden")

        # 用真实引擎发布后，非 owner 仍不可启用/停用。
        self.approve(candidate)
        self.publish(candidate)
        enable_payload = {"agent_id": "expert-a", "entry_id": ENTRY_ID}
        for principal in (self.viewer, self.editor, self.external):
            with self.subTest(role=principal.role, action="contact.enable"):
                self.assertEqual(self.execute("contact.enable", enable_payload, principal)["error"]["code"], "forbidden")
        # 只读 viewer 也不允许停用。
        self.assertTrue(self.execute("contact.enable", enable_payload)["ok"])
        self.assertEqual(self.execute("contact.disable", enable_payload, self.viewer)["error"]["code"], "forbidden")

    # ---- 反例：治理层批准/发布 action owner-only 且因外部证据缺失 fail-closed ----

    async def test_governance_approve_publish_are_owner_only_and_fail_closed(self):
        candidate = self.freeze_current_draft("governance")
        payload = {
            "agent_id": "expert-a", "candidate_id": candidate["candidate_id"],
            "entry_id": ENTRY_ID, "version_id": VERSION_V1,
        }
        for principal in (self.viewer, self.editor, self.external):
            with self.subTest(role=principal.role):
                self.assertEqual(self.config_execute("release.approve", payload, principal)["error"]["code"], "forbidden")
                self.assertEqual(self.config_execute("release.publish", payload, principal)["error"]["code"], "forbidden")
        # owner 调用：release_checklist 的 fixed_samples / fixed_samples_passed 依赖外部
        # 固定样例执行服务（M-B-05 外部项），本机不可满足 -> 必须 fail-closed。
        approve = self.config_execute("release.approve", payload, self.owner)
        self.assertEqual(approve["error"]["code"], "release_blocked")
        publish = self.config_execute("release.publish", payload, self.owner)
        self.assertEqual(publish["error"]["code"], "release_blocked")
        # 被阻断后没有任何批准/发布/启用副作用。
        self.assertIsNone(self.store.sandbox_entry(
            tenant_id="tenant-a", agent_id="expert-a", entry_id=ENTRY_ID,
        ))
        self.assertIsNone(self.store.contact_page(
            tenant_id="tenant-a", agent_id="expert-a", entry_id=ENTRY_ID,
        ))
        self.assertFalse(self.execute("contact.enable", {"agent_id": "expert-a", "entry_id": ENTRY_ID})["ok"])

    # ---- 反例：版本漂移拒绝 ----

    async def test_version_drift_rejects_stale_expected_version_and_keeps_old_binding(self):
        payload = {"agent_id": "expert-a", "entry_id": ENTRY_ID}
        self.publish_live_page()
        resolved_v1 = self.config_execute(
            "release.entry.resolve", {"agent_id": "expert-a", "entry_id": ENTRY_ID},
        )["result"]
        self.assertEqual(resolved_v1["version_id"], VERSION_V1)

        # 把同一入口发布到新版本 v2。
        changed = self.execute("contact.save", {
            "agent_id": "expert-a", "expected_revision": 1, "contact": deepcopy(DRAFT_ONLY_CONTACT),
        })
        self.assertTrue(changed["ok"], changed)
        candidate_v2 = self.freeze_current_draft("v2")
        self.approve(candidate_v2, version_id=VERSION_V2)
        self.publish(candidate_v2, version_id=VERSION_V2)
        resolved_v2 = self.config_execute(
            "release.entry.resolve", {"agent_id": "expert-a", "entry_id": ENTRY_ID},
        )["result"]
        self.assertEqual(resolved_v2["version_id"], VERSION_V2)

        # 漂移前预览过的 expected_version_id 现在必须被拒。
        drift = self.execute("contact.enable", {**payload, "expected_version_id": VERSION_V1})
        self.assertFalse(drift["ok"])
        self.assertEqual(drift["error"]["code"], "state_conflict")
        # 旧绑定保持不变，直到用当前解析出的版本重新启用。
        self.assertEqual(self.execute("contact.get", payload)["result"]["version_id"], VERSION_V1)
        fresh = self.execute("contact.enable", {**payload, "expected_version_id": VERSION_V2})
        self.assertTrue(fresh["ok"], fresh)
        self.assertEqual(fresh["result"]["version_id"], VERSION_V2)
        self.assertEqual(self.execute("contact.get", payload)["result"]["version_id"], VERSION_V2)

    # ---- 反例：坏 Schema / 未知块拒绝 ----

    async def test_bad_schema_and_unknown_blocks_are_rejected_before_freeze(self):
        bad_block = self.execute("contact.save", {
            "agent_id": "expert-a", "expected_revision": 1,
            "contact": {"title": "X", "blocks": [{"id": "x", "type": "script", "body": "alert(1)"}]},
        })
        self.assertEqual(bad_block["error"]["code"], "invalid_request")
        bad_field = self.execute("contact.save", {
            "agent_id": "expert-a", "expected_revision": 1,
            "contact": {"title": "X", "html": "<script>alert(1)</script>"},
        })
        self.assertEqual(bad_field["error"]["code"], "invalid_request")
        # 坏内容没有落盘。
        self.assertEqual(self.draft()["revision"], 1)

        # 直接把坏 Schema 写进草稿（save_draft 不在保存时做提交校验），提交审批必须拒绝。
        draft = self.draft()
        config = draft["config"]
        config["contact"] = {"blocks": [{"id": "x", "type": "unknown"}]}
        self.configuration.save_draft(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1, config=config,
        )
        frozen = self.freeze(2, "bad-schema")
        self.assertEqual(frozen["error"]["code"], "validation_failed")
        issues = frozen["error"]["issues"]
        self.assertTrue(any(issue["code"] == "invalid_contact_page" for issue in issues))
        self.assertEqual(self.configuration.list_candidates(
            tenant_id="tenant-a", agent_id="expert-a",
        ), [])

    # ---- 反例：缺少审批 / 知识撤回时拒绝公开 ----

    async def test_missing_approval_denies_enable_and_public_read(self):
        payload = {"agent_id": "expert-a", "entry_id": ENTRY_ID}
        self.publish_live_page()
        with self.store._tx() as cur:
            cur.execute("DELETE FROM release_approvals")
        self.assertFalse(self.execute("contact.enable", {**payload, "expected_version_id": VERSION_V1})["ok"])
        self.assertFalse(self.execute("contact.get", payload)["ok"])
        self.assertFalse(self.execute("contact.open", {**payload, "version_id": VERSION_V1})["ok"])

    async def test_knowledge_revocation_denies_public_read_and_entry_resolution(self):
        payload = {"agent_id": "expert-a", "entry_id": ENTRY_ID}
        self.publish_live_page()
        self.store.mark_sandbox_versions_for_revalidation(
            tenant_id="tenant-a", agent_id="expert-a",
        )
        self.assertFalse(self.execute("contact.get", payload)["ok"])
        self.assertFalse(self.execute("contact.open", {**payload, "version_id": VERSION_V1})["ok"])
        resolved = self.config_execute(
            "release.entry.resolve", {"agent_id": "expert-a", "entry_id": ENTRY_ID},
        )
        self.assertEqual(resolved["error"]["code"], "release_blocked")
        # 即便知识待重验，owner 仍可停用（收敛暴露面）。
        self.assertTrue(self.execute("contact.disable", payload)["ok"])

    # ---- 反例：跨专家 / 跨租户拒绝 ----

    async def test_cross_expert_and_cross_tenant_access_are_denied(self):
        payload = {"agent_id": "expert-a", "entry_id": ENTRY_ID}
        self.publish_live_page()
        # 跨专家：principal 授权范围不含 expert-a。
        self.assertEqual(self.execute("contact.get", payload, self.other_agent)["error"]["code"], "forbidden")
        self.assertEqual(self.execute("contact.enable", {**payload, "expected_version_id": VERSION_V1},
                                      self.other_agent)["error"]["code"], "forbidden")
        # 跨租户：tenant-b 下查不到 tenant-a 的数据。
        self.assertEqual(self.execute("contact.get", payload, self.foreign)["error"]["code"], "not_found")
        self.assertEqual(self.execute("contact.enable", {**payload, "expected_version_id": VERSION_V1},
                                      self.foreign)["error"]["code"], "not_found")


if __name__ == "__main__":
    unittest.main()
