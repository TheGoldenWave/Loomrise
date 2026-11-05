from __future__ import annotations

import base64
import asyncio
import os
import tempfile
import unittest

from loomrise.configuration import ConfigurationPrincipal, ConfigurationService, ConfigurationValidationError
from loomrise.customer_service import CustomerService, CustomerServiceApplication
from loomrise.durable_store import SqliteStore
from tests.test_configuration_service import spec

class CustomerServiceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "loomrise.db")
        self.store = SqliteStore(self.path)
        self.configuration = ConfigurationService(self.store)
        self.configuration.register_stable_version(
            tenant_id="tenant-a", agent_id="expert-a", version_id="v1", config=spec(),
        )
        self.configuration.create_draft_from_stable(
            tenant_id="tenant-a", agent_id="expert-a", base_version_id="v1",
        )
        candidate = self.configuration.freeze_candidate(
            tenant_id="tenant-a", agent_id="expert-a", expected_revision=1,
            idempotency_key="test-publish",
        )
        self.store.approve_release_candidate(
            tenant_id="tenant-a", agent_id="expert-a", candidate_id=candidate["candidate_id"],
            content_hash=candidate["content_hash"], environment="sandbox",
            entry_id="entry-a", version_id="sandbox-v1", approved_by="owner",
        )
        self.store.publish_sandbox_candidate(
            tenant_id="tenant-a", agent_id="expert-a", candidate_id=candidate["candidate_id"],
            entry_id="entry-a", version_id="sandbox-v1",
        )
        self.service = CustomerService(self.store, self.configuration)
        self.app = CustomerServiceApplication(self.service)
        self.owner = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="owner", role="owner", agent_ids=("expert-a",),
        )
        self.viewer = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="viewer", role="viewer", agent_ids=("expert-a",),
        )
        self.addCleanup(self.store.close)
        self.addCleanup(self.tmp.cleanup)

    def execute(self, action, payload, principal=None):
        return self.app.execute(principal=principal or self.owner, action=action, payload=payload)

    def test_widget_uses_approved_public_configuration_and_requires_declared_visitor_fields(self):
        value = spec()
        value['widget'] = {'title': '虚构课程客服', 'greeting': '欢迎咨询', 'timezone': 'Asia/Shanghai',
                           'fields': [{'id': 'visitor_name', 'label': '称呼', 'type': 'text', 'required': True}]}
        saved = self.configuration.save_draft(tenant_id='tenant-a', agent_id='expert-a', expected_revision=1, config=value)
        candidate = self.configuration.freeze_candidate(tenant_id='tenant-a', agent_id='expert-a',
            expected_revision=saved['revision'], idempotency_key='widget-config')
        self.store.approve_release_candidate(tenant_id='tenant-a', agent_id='expert-a',
            candidate_id=candidate['candidate_id'], content_hash=candidate['content_hash'], environment='sandbox',
            entry_id='entry-a', version_id='widget-v2', approved_by='owner')
        self.store.publish_sandbox_candidate(tenant_id='tenant-a', agent_id='expert-a',
            candidate_id=candidate['candidate_id'], entry_id='entry-a', version_id='widget-v2')
        view = self.execute('widget.configuration', {'agent_id': 'expert-a', 'entry_id': 'entry-a'})
        self.assertTrue(view['ok'], view)
        self.assertEqual(view['result']['widget']['title'], '虚构课程客服')
        self.assertNotIn('config', view['result'])
        self.assertFalse(self.execute('widget.open', {'agent_id': 'expert-a', 'entry_id': 'entry-a'})['ok'])
        self.assertEqual(self.execute('inbox.list', {'agent_id': 'expert-a'})['result']['items'], [])
        opened = self.execute('widget.open', {'agent_id': 'expert-a', 'entry_id': 'entry-a',
            'expected_version_id': 'widget-v2', 'visitor_fields': {'visitor_name': '虚构小林'}})
        self.assertTrue(opened['ok'], opened)
        conversation = self.execute('inbox.list', {'agent_id': 'expert-a'})['result']['items'][0]
        self.assertEqual(conversation['visitor_fields'], {'visitor_name': '虚构小林'})
        self.assertEqual(conversation['release_version'], 'widget-v2')
        original = next(item for item in self.configuration.list_candidates(tenant_id='tenant-a', agent_id='expert-a')
                        if item['source_revision'] == 1)
        self.store.approve_release_candidate(tenant_id='tenant-a', agent_id='expert-a',
            candidate_id=original['candidate_id'], content_hash=original['content_hash'], environment='sandbox',
            entry_id='entry-a', version_id='widget-v3', approved_by='owner')
        self.store.publish_sandbox_candidate(tenant_id='tenant-a', agent_id='expert-a',
            candidate_id=original['candidate_id'], entry_id='entry-a', version_id='widget-v3')
        session_view = self.execute('widget.configuration', {'agent_id': 'expert-a', 'entry_id': 'entry-a',
            'conversation_id': opened['result']['conversation_id'], 'visitor_token': opened['result']['visitor_token']})
        self.assertEqual(session_view['result']['version_id'], 'widget-v2')
        self.assertEqual(session_view['result']['widget']['title'], '虚构课程客服')
        self.assertFalse(self.execute('widget.open', {'agent_id': 'expert-a', 'entry_id': 'entry-a',
            'expected_version_id': 'widget-v2', 'visitor_fields': {'visitor_name': '虚构小林'}})['ok'])
        self.assertEqual(len(self.execute('inbox.list', {'agent_id': 'expert-a'})['result']['items']), 1)
        backup = os.path.join(self.tmp.name, 'profiles-backup.db')
        self.store.backup_to(backup)
        restored = SqliteStore(backup)
        try:
            self.assertEqual(restored.list_customer_conversations(tenant_id='tenant-a', agent_id='expert-a')[0]['visitor_fields'],
                             {'visitor_name': '虚构小林'})
        finally:
            restored.close()

    def test_widget_projects_bound_faq_questions_without_source_details(self):
        source = self.configuration.create_knowledge_source(
            tenant_id='tenant-a', agent_id='expert-a', kind='faq',
            locator='体验课价格为 19 元。仅供虚构验证。',
            display_name='私有来源标题', authorization='owned',
        )
        ready = self.configuration.ingest_knowledge_source(
            tenant_id='tenant-a', agent_id='expert-a', source_id=source['source_id'],
        )
        source_ref = {'source_id': source['source_id'], 'content_hash': ready['content_hash']}
        config = spec()
        config['widget'] = {'title': '虚构课程客服'}
        config['ai_reception'] = {
            'enabled': True, 'model_id': 'fixture-model', 'sources': [source_ref],
            'faq_suggestions': [{'question': '体验课多少钱？', **source_ref}],
        }
        saved = self.configuration.save_draft(
            tenant_id='tenant-a', agent_id='expert-a', expected_revision=1, config=config,
        )
        try:
            candidate = self.configuration.freeze_candidate(
                tenant_id='tenant-a', agent_id='expert-a', expected_revision=saved['revision'],
                idempotency_key='widget-faq-suggestions',
            )
        except ConfigurationValidationError as exc:
            self.fail(f'valid FAQ suggestions did not pass version validation: {exc}')
        self.store.approve_release_candidate(
            tenant_id='tenant-a', agent_id='expert-a', candidate_id=candidate['candidate_id'],
            content_hash=candidate['content_hash'], environment='sandbox',
            entry_id='entry-a', version_id='widget-faq-v2', approved_by='owner',
        )
        self.store.publish_sandbox_candidate(
            tenant_id='tenant-a', agent_id='expert-a', candidate_id=candidate['candidate_id'],
            entry_id='entry-a', version_id='widget-faq-v2',
        )

        view = self.execute('widget.configuration', {'agent_id': 'expert-a', 'entry_id': 'entry-a'})
        self.assertTrue(view['ok'], view)
        self.assertEqual(view['result']['faq_suggestions'], ['体验课多少钱？'])
        self.assertEqual(view['result']['version_id'], 'widget-faq-v2')
        public = str(view['result'])
        self.assertNotIn(source['source_id'], public)
        self.assertNotIn(ready['content_hash'], public)
        self.assertNotIn('私有来源标题', public)
        self.assertNotIn('体验课价格为 19 元', public)

        self.configuration.revoke_knowledge_source(
            tenant_id='tenant-a', agent_id='expert-a', source_id=source['source_id'],
        )
        stale = self.execute('widget.configuration', {'agent_id': 'expert-a', 'entry_id': 'entry-a'})
        self.assertFalse(stale['ok'])
        self.assertEqual(stale['error']['code'], 'release_blocked')

    def test_widget_auto_response_is_opt_in_and_stops_after_human_request(self):
        opened = self.execute('widget.open', {'agent_id': 'expert-a', 'entry_id': 'entry-a'})['result']
        result = self.service.visitor_send_with_responder(conversation_id=opened['conversation_id'],
            visitor_token=opened['visitor_token'], text='你好', responder=lambda text, config: '模拟自动答复')
        self.assertEqual(result['assistant']['sender'], 'assistant')
        blocked = self.service.visitor_send_with_responder(conversation_id=opened['conversation_id'],
            visitor_token=opened['visitor_token'], text='转人工', request_human=True,
            responder=lambda text, config: '不应生成')
        self.assertEqual(blocked['assistant'], None)
        self.assertEqual(blocked['auto_reply'], 'skipped_human')
        self.assertEqual(len(self.execute('widget.messages', {'conversation_id': opened['conversation_id'],
            'visitor_token': opened['visitor_token']})['result']['items']), 3)

    def test_widget_inbox_round_trip_is_private_and_generation_fenced(self):
        opened = self.execute("widget.open", {"agent_id": "expert-a", "entry_id": "entry-a"})["result"]
        conversation_id = opened["conversation_id"]
        visitor_token = opened["visitor_token"]
        posted = asyncio.run(self.app.execute_async(principal=self.owner, action="widget.send", payload={
            "conversation_id": conversation_id, "visitor_token": visitor_token,
            "text": "请问课程如何报名？", "request_human": True,
        }))
        self.assertTrue(posted["ok"])
        inbound = self.execute('widget.messages', {
            'conversation_id': conversation_id, 'visitor_token': visitor_token,
        })['result']['items'][0]['reception']
        run_id, request_id = inbound['run_id'], inbound['request_id']
        started = self.store.load_events(run_id)
        finished = next(event for event in started if event.event_type == 'customer.reception.finished')
        self.assertTrue(finished.payload.get('handoff_requested'))
        self.assertEqual(self.execute("inbox.list", {"agent_id": "expert-a"})["result"]["items"][0]["state"], "human_requested")
        denied = self.execute("inbox.claim", {"agent_id": "expert-a", "conversation_id": conversation_id}, self.viewer)
        self.assertEqual(denied["error"]["code"], "forbidden")
        claimed = self.execute("inbox.claim", {
            "agent_id": "expert-a", "conversation_id": conversation_id,
        })["result"]
        self.assertEqual(claimed["occupancy_generation"], 1)
        stale = self.execute("inbox.reply", {
            "agent_id": "expert-a", "conversation_id": conversation_id,
            "generation": 0, "text": "迟到回复",
        })
        self.assertEqual(stale["error"]["code"], "state_conflict")
        replied = self.execute("inbox.reply", {
            "agent_id": "expert-a", "conversation_id": conversation_id,
            "generation": 1, "text": "我来协助您报名。",
        })
        self.assertTrue(replied["ok"])
        other_owner = ConfigurationPrincipal(
            tenant_id='tenant-a', actor_id='other-owner', role='owner', agent_ids=('expert-a',),
        )
        wrong_actor = self.execute('inbox.release', {
            'agent_id': 'expert-a', 'conversation_id': conversation_id, 'generation': 1,
        }, other_owner)
        self.assertEqual(wrong_actor['error']['code'], 'state_conflict')
        stale_release = self.execute('inbox.release', {
            'agent_id': 'expert-a', 'conversation_id': conversation_id, 'generation': 0,
        })
        self.assertEqual(stale_release['error']['code'], 'state_conflict')
        viewer_release = self.execute('inbox.release', {
            'agent_id': 'expert-a', 'conversation_id': conversation_id, 'generation': 1,
        }, self.viewer)
        self.assertEqual(viewer_release['error']['code'], 'forbidden')
        released = self.execute('inbox.release', {
            'agent_id': 'expert-a', 'conversation_id': conversation_id, 'generation': 1,
        })
        self.assertTrue(released['ok'], released)
        self.assertEqual((released['result']['state'], released['result']['occupancy_generation']), ('bot', 2))
        events = self.store.load_events(run_id)
        self.assertEqual({event.request_id for event in events}, {request_id})
        self.assertTrue(self.store.verify_chain(run_id))
        self.assertEqual([event.event_type for event in events if event.event_type.startswith('customer.handoff.')], [
            'customer.handoff.claimed', 'customer.handoff.replied', 'customer.handoff.released',
        ])
        self.assertEqual([event.payload['occupancy_generation'] for event in events
                          if event.event_type.startswith('customer.handoff.')], [1, 1, 2])
        reception_stats = self.execute('customer.statistics', {'agent_id': 'expert-a'})['result']['reception']
        self.assertEqual((reception_stats['request_count'], reception_stats['run_count']), (1, 1))
        self.assertEqual(reception_stats['handoff'], {
            'requested_count': 1, 'request_sample_count': 1, 'request_missing_count': 0,
            'claimed_count': 1, 'claim_sample_count': 1, 'claim_missing_count': 0, 'reason': None,
        })
        transcript = self.execute("widget.messages", {
            "conversation_id": conversation_id, "visitor_token": visitor_token,
        })["result"]["items"]
        self.assertEqual([message["sequence"] for message in transcript], [1, 2])
        self.assertEqual([message["sender"] for message in transcript], ["visitor", "operator"])
        forbidden_read = self.execute("widget.messages", {
            "conversation_id": conversation_id, "visitor_token": "wrong-token",
        })
        self.assertEqual(forbidden_read["error"]["code"], "not_found")

    def test_legacy_sync_inbox_transitions_get_independent_audit_runs(self):
        opened = self.execute('widget.open', {'agent_id': 'expert-a', 'entry_id': 'entry-a'})['result']
        self.execute('widget.send', {'conversation_id': opened['conversation_id'],
            'visitor_token': opened['visitor_token'], 'text': '需要人工协助', 'request_human': True})
        self.execute('inbox.claim', {'agent_id': 'expert-a', 'conversation_id': opened['conversation_id']})
        self.execute('inbox.reply', {'agent_id': 'expert-a', 'conversation_id': opened['conversation_id'],
            'generation': 1, 'text': '我来协助您。'})
        self.execute('inbox.release', {'agent_id': 'expert-a', 'conversation_id': opened['conversation_id'],
            'generation': 1})
        transitions = [event for run_id in self.store._conn.execute(
            "SELECT DISTINCT run_id FROM events WHERE event_type='customer.handoff.audit_started'"
        ) for event in self.store.load_events(run_id['run_id']) if event.event_type.startswith('customer.handoff.')
            and event.event_type != 'customer.handoff.audit_started']
        self.assertEqual(sorted(event.event_type for event in transitions), sorted([
            'customer.handoff.claimed', 'customer.handoff.replied', 'customer.handoff.released',
        ]))
        self.assertEqual(len({event.run_id for event in transitions}), 3)
        self.assertTrue(all(self.store.verify_chain(event.run_id) for event in transitions))

    def test_material_versions_backup_read_and_send_revalidation(self):
        original = b"admission guide v1"
        created = self.execute("material.create", {
            "agent_id": "expert-a", "filename": "guide.txt", "display_name": "报名指南",
            "authorization": "licensed", "expires_at": "2099-01-01T00:00:00Z",
            "content_base64": base64.b64encode(original).decode(),
        })["result"]
        asset_id = created["asset_id"]
        version_one = created["current_version_id"]
        downloaded = self.execute("material.download", {
            "agent_id": "expert-a", "asset_id": asset_id,
        })["result"]
        self.assertEqual(base64.b64decode(downloaded["content_base64"]), original)

        opened = self.execute("widget.open", {"agent_id": "expert-a", "entry_id": "entry-a"})["result"]
        self.execute("widget.send", {
            "conversation_id": opened["conversation_id"], "visitor_token": opened["visitor_token"],
            "text": "请人工帮我看看。", "request_human": True,
        })
        self.execute("inbox.claim", {
            "agent_id": "expert-a", "conversation_id": opened["conversation_id"],
        })
        legacy_claim = self.store._conn.execute(
            "SELECT run_id FROM events WHERE event_type='customer.handoff.claimed'"
        ).fetchone()
        self.assertIsNotNone(legacy_claim)
        self.assertTrue(self.store.verify_chain(legacy_claim['run_id']))
        generation = 1
        updated = self.execute("material.create", {
            "agent_id": "expert-a", "asset_id": asset_id, "filename": "guide.txt",
            "display_name": "报名指南", "authorization": "owned",
            "content_base64": base64.b64encode(b"admission guide v2").decode(),
        })["result"]
        old_version_download = self.execute("material.download", {
            "agent_id": "expert-a", "asset_id": asset_id, "version_id": version_one,
        })["result"]
        self.assertEqual(old_version_download["authorization"], "licensed")
        self.assertEqual(old_version_download["filename"], "guide.txt")
        self.assertEqual(old_version_download["expires_at"], "2099-01-01T00:00:00+00:00")
        old_send = self.execute("inbox.send_material", {
            "agent_id": "expert-a", "conversation_id": opened["conversation_id"],
            "generation": generation, "asset_id": asset_id, "version_id": version_one,
        })
        self.assertEqual(old_send["error"]["code"], "release_blocked")
        sent = self.execute("inbox.send_material", {
            "agent_id": "expert-a", "conversation_id": opened["conversation_id"],
            "generation": generation, "asset_id": asset_id,
            "version_id": updated["current_version_id"],
        })
        self.assertTrue(sent["ok"])

        backup = os.path.join(self.tmp.name, "backup.db")
        self.store.backup_to(backup)
        restored = SqliteStore(backup)
        try:
            record = restored.material_version(
                tenant_id="tenant-a", agent_id="expert-a", asset_id=asset_id,
            )
            self.assertEqual(bytes(record["content"]), b"admission guide v2")
        finally:
            restored.close()

        self.execute("material.revoke", {"agent_id": "expert-a", "asset_id": asset_id})
        revoked_send = self.execute("inbox.send_material", {
            "agent_id": "expert-a", "conversation_id": opened["conversation_id"],
            "generation": generation, "asset_id": asset_id,
            "version_id": updated["current_version_id"],
        })
        self.assertEqual(revoked_send["error"]["code"], "release_blocked")

    def test_oversized_material_is_rejected_before_base64_decode(self):
        response = self.execute("material.create", {
            "agent_id": "expert-a", "filename": "guide.txt", "display_name": "指南",
            "authorization": "owned", "content_base64": "A" * 14_000_000,
        })

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_request")

    def test_every_supported_material_format_round_trips_through_backup(self):
        samples = {
            "png": ("guide.png", b"\x89PNG\r\n\x1a\n"),
            "jpg": ("guide.jpg", b"\xff\xd8\xff\xe0"),
            "jpeg": ("guide.jpeg", b"\xff\xd8\xff\xe0"),
            "webp": ("guide.webp", b"RIFF\x04\x00\x00\x00WEBPVP8 "),
            "mp4": ("guide.mp4", b"\x00\x00\x00\x18ftypisom"),
            "webm": ("guide.webm", b"\x1a\x45\xdf\xa3"),
            "pdf": ("guide.pdf", b"%PDF-1.7\n"),
            "txt": ("guide.txt", "报名指南".encode()),
            "md": ("guide.md", "# 报名指南".encode()),
        }
        assets = {}
        for label, (filename, content) in samples.items():
            with self.subTest(format=label):
                created = self.execute("material.create", {
                    "agent_id": "expert-a", "filename": filename, "display_name": label,
                    "authorization": "owned",
                    "content_base64": base64.b64encode(content).decode(),
                })
                self.assertTrue(created["ok"], created)
                asset_id = created["result"]["asset_id"]
                assets[label] = asset_id
                downloaded = self.execute("material.download", {
                    "agent_id": "expert-a", "asset_id": asset_id,
                })
                self.assertEqual(base64.b64decode(downloaded["result"]["content_base64"]), content)

        backup = os.path.join(self.tmp.name, "formats-backup.db")
        self.store.backup_to(backup)
        restored = SqliteStore(backup)
        try:
            for label, (filename, expected) in samples.items():
                with self.subTest(restored_format=label):
                    record = restored.material_version(
                        tenant_id="tenant-a", agent_id="expert-a", asset_id=assets[label],
                    )
                    self.assertEqual(record["version_filename"], filename)
                    self.assertEqual(bytes(record["content"]), expected)
        finally:
            restored.close()

    def test_expired_material_is_rejected_when_operator_sends_it(self):
        created = self.execute("material.create", {
            "agent_id": "expert-a", "filename": "expired.txt", "display_name": "过期资料",
            "authorization": "licensed", "expires_at": "2000-01-01T00:00:00Z",
            "content_base64": base64.b64encode(b"expired").decode(),
        })["result"]
        opened = self.execute("widget.open", {"agent_id": "expert-a", "entry_id": "entry-a"})["result"]
        self.execute("widget.send", {
            "conversation_id": opened["conversation_id"], "visitor_token": opened["visitor_token"],
            "text": "需要人工查看资料。", "request_human": True,
        })
        self.execute("inbox.claim", {
            "agent_id": "expert-a", "conversation_id": opened["conversation_id"],
        })

        response = self.execute("inbox.send_material", {
            "agent_id": "expert-a", "conversation_id": opened["conversation_id"],
            "generation": 1, "asset_id": created["asset_id"],
            "version_id": created["current_version_id"],
        })

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "release_blocked")

    def test_attachment_send_rejects_an_old_occupancy_generation(self):
        created = self.execute("material.create", {
            "agent_id": "expert-a", "filename": "guide.txt", "display_name": "指南",
            "authorization": "owned", "content_base64": base64.b64encode(b"guide").decode(),
        })["result"]
        opened = self.execute("widget.open", {"agent_id": "expert-a", "entry_id": "entry-a"})["result"]
        self.execute("widget.send", {
            "conversation_id": opened["conversation_id"], "visitor_token": opened["visitor_token"],
            "text": "需要人工协助。", "request_human": True,
        })
        self.execute("inbox.claim", {
            "agent_id": "expert-a", "conversation_id": opened["conversation_id"],
        })
        self.execute("widget.send", {
            "conversation_id": opened["conversation_id"], "visitor_token": opened["visitor_token"],
            "text": "请另一位客服接手。", "request_human": True,
        })
        editor = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="editor", role="editor", agent_ids=("expert-a",),
        )
        claimed = self.execute("inbox.claim", {
            "agent_id": "expert-a", "conversation_id": opened["conversation_id"],
        }, principal=editor)
        self.assertEqual(claimed["result"]["occupancy_generation"], 2)

        stale = self.execute("inbox.send_material", {
            "agent_id": "expert-a", "conversation_id": opened["conversation_id"],
            "generation": 1, "asset_id": created["asset_id"],
            "version_id": created["current_version_id"],
        })

        self.assertFalse(stale["ok"])
        self.assertEqual(stale["error"]["code"], "state_conflict")

    def test_visitor_can_download_only_active_material_sent_to_own_conversation(self):
        content = b"visitor handout"
        created = self.execute("material.create", {
            "agent_id": "expert-a", "filename": "handout.txt", "display_name": "资料",
            "authorization": "owned", "content_base64": base64.b64encode(content).decode(),
        })["result"]
        opened = self.execute("widget.open", {"agent_id": "expert-a", "entry_id": "entry-a"})["result"]
        self.execute("widget.send", {
            "conversation_id": opened["conversation_id"], "visitor_token": opened["visitor_token"],
            "text": "请人工发送资料。", "request_human": True,
        })
        self.execute("inbox.claim", {
            "agent_id": "expert-a", "conversation_id": opened["conversation_id"],
        })
        self.execute("inbox.send_material", {
            "agent_id": "expert-a", "conversation_id": opened["conversation_id"],
            "generation": 1, "asset_id": created["asset_id"],
            "version_id": created["current_version_id"],
        })

        downloaded = self.execute("widget.material.download", {
            "conversation_id": opened["conversation_id"], "visitor_token": opened["visitor_token"],
            "asset_id": created["asset_id"], "version_id": created["current_version_id"],
        })
        self.assertTrue(downloaded["ok"])
        self.assertEqual(base64.b64decode(downloaded["result"]["content_base64"]), content)

        other = self.execute("widget.open", {"agent_id": "expert-a", "entry_id": "entry-a"})["result"]
        denied = self.execute("widget.material.download", {
            "conversation_id": other["conversation_id"], "visitor_token": other["visitor_token"],
            "asset_id": created["asset_id"], "version_id": created["current_version_id"],
        })
        self.assertEqual(denied["error"]["code"], "not_found")

        self.execute("material.revoke", {"agent_id": "expert-a", "asset_id": created["asset_id"]})
        revoked = self.execute("widget.material.download", {
            "conversation_id": opened["conversation_id"], "visitor_token": opened["visitor_token"],
            "asset_id": created["asset_id"], "version_id": created["current_version_id"],
        })
        self.assertEqual(revoked["error"]["code"], "not_found")


if __name__ == "__main__":
    unittest.main()
