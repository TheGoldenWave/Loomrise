import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from loomrise.configuration import ConfigurationPrincipal
from tests import test_customer_reception as reception


class AssistanceProvider(reception.AnswerProvider):
    async def assist(self, **payload):
        self.payloads.append(payload)
        self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.failure:
            raise self.failure
        source = payload['sources'][0]
        return self.response or {'summary': '访客询问体验课价格，待人工处理。', 'reply': '体验课价格为 19 元。',
            'citations': [{'source_id': source['source_id'], 'content_hash': source['content_hash'],
                           'quote': '体验课价格为 19 元。'}],
            'model_evidence': {'model': self.model, 'response_id': 'fixture-assist',
                'provider': 'fixture', 'usage': {}, 'duration_ms': 1}}


class DisconnectProvider(AssistanceProvider):
    def __init__(self):
        super().__init__()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.finished = asyncio.Event()

    async def assist(self, **payload):
        try:
            return await super().assist(**payload)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        finally:
            self.finished.set()

    async def answer(self, **payload):
        try:
            return await super().answer(**payload)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        finally:
            self.finished.set()


class InboxAssistanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.case = reception.CustomerReceptionCase()
        await self.case.asyncSetUp()
        self.addCleanup(self.case.tmp.cleanup)
        self.addCleanup(self.case.store.close)
        self.case.service.reception.provider = AssistanceProvider()
        self.provider = self.case.service.reception.provider
        await self.case.send(request_human=True)
        self.claim = self.case.service.claim(principal=self.case.owner, agent_id='expert-a',
            conversation_id=self.case.session['conversation_id'])
        self.payload = {'agent_id': 'expert-a', 'conversation_id': self.case.session['conversation_id'],
            'generation': self.claim['occupancy_generation'], 'through_sequence': 1}

    async def generate(self, **changes):
        return await self.case.app.execute_async(principal=self.case.owner, action='inbox.assistance.generate',
            payload={**self.payload, **changes})

    def check(self, proposal, **changes):
        return self.case.app.execute(principal=self.case.owner, action='inbox.assistance.check',
            payload={**self.payload, 'snapshot_hash': proposal['snapshot_hash'], **changes})

    def retained_state(self):
        tables = ('customer_messages', 'customer_conversations', 'customer_inbox_reads',
                  'events', 'runs', 'requests', 'customer_inbox_events')
        return {table: [dict(row) for row in self.case.store._conn.execute(f'SELECT * FROM {table}')]
                for table in tables}

    async def disconnect_request(self, provider, action, payload):
        from aiohttp import web
        from loomrise.config_http import create_configuration_http_app

        principal_path = Path(self.case.tmp.name) / 'principal.json'
        principal_path.write_text(json.dumps({'tenant_id': 'tenant-a', 'actor_id': 'owner',
            'role': 'owner', 'agent_ids': ['expert-a']}), encoding='utf-8')
        principal_path.chmod(0o600)
        app = create_configuration_http_app(principal_path=principal_path,
            database_path=self.case.store.path, reception_provider=provider,
            contact_generation_provider=None)
        # Ordinary AppRunner defaults must work; TestServer enables cancellation itself.
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=0.1)
        self.addAsyncCleanup(runner.cleanup)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        port = runner.addresses[0][1]
        _, writer = await asyncio.open_connection('127.0.0.1', port)
        body = json.dumps({'action': action, 'payload': payload}).encode()
        request = (f'POST /api/customer-service HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n'
                   f'Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n').encode() + body
        try:
            writer.write(request)
            await writer.drain()
            await asyncio.wait_for(provider.started.wait(), 1)
            writer.close()
            await writer.wait_closed()
            try:
                await asyncio.wait_for(provider.cancelled.wait(), 1)
                cancelled = True
            except TimeoutError:
                cancelled = False
        finally:
            writer.close()
            await writer.wait_closed()
            provider.release.set()
            await asyncio.wait_for(provider.finished.wait(), 1)
        self.assertTrue(cancelled, 'ordinary AppRunner did not cancel the provider after HTTP disconnect')
        return app

    async def test_native_http_disconnect_cancels_assistance_without_writes(self):
        before = self.retained_state()
        provider = DisconnectProvider()
        await self.disconnect_request(provider, 'inbox.assistance.generate', self.payload)
        self.assertEqual(self.retained_state(), before)
        self.assertEqual(len(provider.payloads), 1)

    async def test_native_http_disconnect_keeps_reception_interrupted_and_retry_idempotent(self):
        from loomrise.config_http import CUSTOMER_APPLICATION_KEY

        session = self.case.service.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry-a')
        payload = {'conversation_id': session['conversation_id'], 'visitor_token': session['visitor_token'],
                   'text': '体验课多少钱？', 'message_id': 'disconnect-input'}
        provider = DisconnectProvider()
        app = await self.disconnect_request(provider, 'widget.send', payload)
        messages = self.case.service.visitor_messages(conversation_id=session['conversation_id'],
                                                      visitor_token=session['visitor_token'])
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['reception']['status'], 'interrupted')
        retry = await app[CUSTOMER_APPLICATION_KEY].execute_async(principal=self.case.owner,
            action='widget.send', payload=payload)
        self.assertEqual(retry['result']['reception']['status'], 'interrupted')
        self.assertIsNone(retry['result']['assistant'])
        self.assertEqual(len(provider.payloads), 1)

    async def test_local_model_provider_timeout_and_invalid_output_keep_public_error_categories(self):
        from loomrise.model_provider import LocalModelProvider
        from tests.test_model_provider import AsyncProviderTests

        config = {'model': 'test-model', 'base_url': 'https://example.invalid/v1',
                  'key': 'PRIVATE-CONNECTION-SECRET'}
        before = self.retained_state()
        for failure, expected in ((TimeoutError('PRIVATE-CONNECTION-SECRET'), 'assistance_timeout'),
                                  (None, 'assistance_invalid_response')):
            with self.subTest(expected=expected):
                sdk, client = AsyncProviderTests().sdk({'summary': '摘要', 'reply': '未经引用的答复', 'citations': []})
                if failure:
                    client.responses.create.side_effect = failure
                self.case.service.reception.provider = LocalModelProvider(config)
                with patch('loomrise.model_provider.AsyncOpenAI', sdk):
                    result = await self.generate()
                self.assertEqual(result['error']['code'], expected, result)
                self.assertNotIn(config['key'], str(result))
                self.assertEqual(client.responses.create.call_count, 1)
        self.assertEqual(self.retained_state(), before)

    async def test_only_exact_model_provider_codes_receive_specific_public_errors(self):
        from loomrise.model_provider import ModelProviderError

        for error in (RuntimeError('model_request_timeout'),
                      ModelProviderError('model_request_timeout PRIVATE-CONNECTION-SECRET'),
                      ModelProviderError('invalid_model_assistance PRIVATE-CONNECTION-SECRET'),
                      ModelProviderError('model_response_invalid_json')):
            with self.subTest(error=type(error).__name__):
                self.provider.failure = error
                result = await self.generate()
                self.assertEqual(result['error']['code'], 'assistance_failed', result)
                self.assertNotIn('PRIVATE-CONNECTION-SECRET', str(result))

    async def test_candidate_is_grounded_and_never_sends_or_marks_read(self):
        before = self.retained_state()
        result = await self.generate()
        self.assertTrue(result['ok'], result)
        proposal = result['result']
        self.assertEqual(proposal['state'], 'proposal')
        self.assertEqual(proposal['reply'], '体验课价格为 19 元。')
        self.assertEqual(len(self.case.messages()), 1)
        current = self.case.service.inbox_list(principal=self.case.owner, agent_id='expert-a')[0]
        self.assertEqual(current['read_sequence'], 0)
        self.assertEqual(current['occupancy_generation'], self.payload['generation'])
        checked = self.case.app.execute(principal=self.case.owner, action='inbox.assistance.check',
            payload={**self.payload, 'snapshot_hash': proposal['snapshot_hash']})
        self.assertTrue(checked['ok'], checked)
        self.assertTrue(checked['result']['valid'])
        self.assertEqual(self.retained_state(), before)
        self.assertEqual(proposal['version_id'], self.case.session['version_id'])
        self.assertEqual(proposal['citations'][0]['title'], self.case.source['display_name'])

    async def test_ownership_and_message_sequence_are_checked_before_model(self):
        viewer = ConfigurationPrincipal(tenant_id='tenant-a', actor_id='owner', role='viewer', agent_ids=('expert-a',))
        forbidden = await self.case.app.execute_async(principal=viewer, action='inbox.assistance.generate', payload=self.payload)
        self.assertEqual(forbidden['error']['code'], 'forbidden')
        other = ConfigurationPrincipal(tenant_id='tenant-a', actor_id='other', role='editor', agent_ids=('expert-a',))
        denied = await self.case.app.execute_async(principal=other, action='inbox.assistance.generate', payload=self.payload)
        self.assertFalse(denied['ok'])
        stale = await self.generate(through_sequence=0)
        self.assertFalse(stale['ok'])
        self.assertEqual(self.provider.payloads, [])

    async def test_late_model_candidate_is_rejected_after_a_new_message(self):
        self.provider.release = asyncio.Event()
        pending = asyncio.create_task(self.generate())
        await self.provider.started.wait()
        await self.case.send('有新的问题', message_id='new-input')
        self.provider.release.set()
        result = await pending
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'], 'state_conflict')
        self.assertEqual(len(self.case.messages()), 2)

    async def test_adoption_check_revalidates_source_and_human_ownership(self):
        result = await self.generate()
        self.assertTrue(result['ok'], result)
        payload = {**self.payload, 'snapshot_hash': result['result']['snapshot_hash']}
        self.case.configuration.revoke_knowledge_source(tenant_id='tenant-a', agent_id='expert-a', source_id=self.case.source['source_id'])
        result = self.case.app.execute(principal=self.case.owner, action='inbox.assistance.check', payload=payload)
        self.assertFalse(result['ok'])

    async def test_provider_failure_is_redacted_and_invalid_citations_are_rejected(self):
        self.provider.failure = RuntimeError('PRIVATE-CONNECTION-SECRET')
        result = await self.generate()
        self.assertFalse(result['ok'])
        self.assertNotIn('PRIVATE-CONNECTION-SECRET', str(result))
        self.provider.failure = None
        self.provider.response = {'summary': '摘要', 'reply': '不可信答复', 'citations': [], 'model_evidence': {}}
        invalid = await self.generate()
        self.assertFalse(invalid['ok'])
        self.assertEqual(len(self.case.messages()), 1)

    async def test_check_requires_the_same_actor_tenant_agent_and_role(self):
        proposal = (await self.generate())['result']
        for tenant, actor, role, agents, agent in (
            ('tenant-a', 'owner', 'viewer', ('expert-a',), 'expert-a'),
            ('tenant-a', 'someone-else', 'editor', ('expert-a',), 'expert-a'),
            ('other-tenant', 'owner', 'owner', ('expert-a',), 'expert-a'),
            ('tenant-a', 'owner', 'owner', ('other-agent',), 'other-agent'),
            ('tenant-a', 'owner', 'owner', ('other-agent',), 'expert-a'),
        ):
            principal = ConfigurationPrincipal(tenant_id=tenant, actor_id=actor, role=role, agent_ids=agents)
            with self.subTest(tenant=tenant, actor=actor, role=role, agent=agent):
                payload = {**self.payload, 'agent_id': agent, 'snapshot_hash': proposal['snapshot_hash']}
                checked = self.case.app.execute(principal=principal, action='inbox.assistance.check', payload=payload)
                generated = await self.case.app.execute_async(principal=principal,
                    action='inbox.assistance.generate', payload={key: value for key, value in payload.items()
                                                               if key != 'snapshot_hash'})
                self.assertFalse(checked['ok'])
                self.assertFalse(generated['ok'])
        self.assertEqual(len(self.provider.payloads), 1)

    async def test_release_and_new_claim_invalidate_the_previous_generation(self):
        proposal = (await self.generate())['result']
        self.case.service.release(principal=self.case.owner, agent_id='expert-a',
            conversation_id=self.payload['conversation_id'], generation=self.payload['generation'])
        claim = self.case.service.claim(principal=self.case.owner, agent_id='expert-a',
            conversation_id=self.payload['conversation_id'])
        self.assertFalse(self.check(proposal)['ok'])
        self.assertFalse(self.check(proposal, generation=claim['occupancy_generation'])['ok'])
        self.assertFalse((await self.generate())['ok'])
        self.assertEqual(len(self.provider.payloads), 1)

    async def test_new_message_invalidates_adoption_even_with_updated_sequence(self):
        proposal = (await self.generate())['result']
        await self.case.send('新问题', message_id='new-input')
        self.assertFalse(self.check(proposal)['ok'])
        self.assertFalse(self.check(proposal, through_sequence=2)['ok'])

    async def test_existing_conversation_keeps_its_frozen_version_after_entry_republish(self):
        proposal = (await self.generate())['result']
        self.case.publish(self.case.config, 'sandbox-v2')
        self.assertTrue(self.check(proposal)['ok'])
        result = await self.generate()
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['result']['version_id'], 'sandbox-v1')

    async def test_per_run_provider_is_used_and_draft_changes_do_not_rebind_the_conversation(self):
        provider = AssistanceProvider()
        self.provider.for_run = lambda: provider
        current = self.case.configuration.get_draft(tenant_id='tenant-a', agent_id='expert-a')
        config = deepcopy(current['config'])
        config['persona']['name'] = '尚未发布的修改'
        self.case.configuration.save_draft(tenant_id='tenant-a', agent_id='expert-a',
            expected_revision=current['revision'], config=config)
        result = await self.generate()
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.provider.payloads, [])
        self.assertEqual(len(provider.payloads), 1)
        self.assertNotEqual(provider.payloads[0]['persona']['name'], config['persona']['name'])

    async def test_authorized_source_changes_and_document_tampering_invalidate_proposals(self):
        proposal = (await self.generate())['result']
        source_id = self.case.source['source_id']
        changes = (
            ('UPDATE knowledge_sources SET authorization=? WHERE source_id=?', ('licensed', source_id)),
            ('UPDATE knowledge_sources SET content_hash=? WHERE source_id=?', ('0' * 64, source_id)),
            ('UPDATE knowledge_documents SET content=? WHERE source_id=?', ('篡改正文', source_id)),
        )
        for sql, parameters in changes:
            with self.subTest(sql=sql), self.case.store._tx() as cursor:
                cursor.execute(sql, parameters)
            self.assertFalse(self.check(proposal)['ok'])
            with self.case.store._tx() as cursor:
                cursor.execute('UPDATE knowledge_sources SET authorization=?,content_hash=? WHERE source_id=?',
                               ('owned', self.case.source['content_hash'], source_id))
                cursor.execute('UPDATE knowledge_documents SET content=? WHERE source_id=?',
                               ('体验课价格为 19 元。', source_id))

    async def test_sources_ownership_and_release_change_while_generating_are_rejected(self):
        changes = ('revoke', 'content', 'authorization', 'ownership', 'version')
        for change in changes:
            with self.subTest(change=change):
                self.provider.started.clear()
                self.provider.release = asyncio.Event()
                pending = asyncio.create_task(self.generate())
                await self.provider.started.wait()
                with self.case.store._tx() as cursor:
                    if change == 'revoke':
                        cursor.execute("UPDATE knowledge_sources SET state='revoked' WHERE source_id=?",
                                       (self.case.source['source_id'],))
                    elif change == 'content':
                        cursor.execute('UPDATE knowledge_documents SET content=? WHERE source_id=?',
                                       ('篡改正文', self.case.source['source_id']))
                    elif change == 'authorization':
                        cursor.execute("UPDATE knowledge_sources SET authorization='licensed' WHERE source_id=?",
                                       (self.case.source['source_id'],))
                    elif change == 'ownership':
                        cursor.execute('UPDATE customer_conversations SET assigned_to=? WHERE conversation_id=?',
                                       ('other', self.payload['conversation_id']))
                    else:
                        cursor.execute('UPDATE customer_conversations SET release_version=? WHERE conversation_id=?',
                                       ('other-version', self.payload['conversation_id']))
                self.provider.release.set()
                result = await pending
                self.assertFalse(result['ok'])
                self.assertIn(result['error']['code'], {'state_conflict', 'not_found'})
                with self.case.store._tx() as cursor:
                    cursor.execute("UPDATE knowledge_sources SET state='ready',authorization='owned' WHERE source_id=?",
                                   (self.case.source['source_id'],))
                    cursor.execute('UPDATE knowledge_documents SET content=? WHERE source_id=?',
                                   ('体验课价格为 19 元。', self.case.source['source_id']))
                    cursor.execute('UPDATE customer_conversations SET assigned_to=?,release_version=? WHERE conversation_id=?',
                                   ('owner', self.case.session['version_id'], self.payload['conversation_id']))
        self.assertEqual(len(self.case.messages()), 1)

    async def test_missing_assist_frozen_model_and_for_run_mismatch_are_unavailable(self):
        before = self.retained_state()
        for provider in (None, reception.AnswerProvider(), type('WrongModel', (), {
                'model': 'different-model', 'assist': AssistanceProvider.assist})(),
                type('Factory', (), {'assist': AssistanceProvider.assist,
                     'for_run': lambda self: reception.AnswerProvider()})()):
            self.case.service.reception.provider = provider
            result = await self.generate()
            self.assertEqual(result['error']['code'], 'assistance_unavailable', result)
        self.case.service.reception.provider = self.provider
        with self.case.store._tx() as cursor:
            row = cursor.execute('SELECT release_id,config_json FROM sandbox_releases').fetchone()
            config = json.loads(row['config_json'])
            config['ai_reception']['enabled'] = False
            config['ai_reception']['model_id'] = ''
            encoded = json.dumps(config, ensure_ascii=False)
            cursor.execute('UPDATE sandbox_releases SET config_json=?,content_hash=? WHERE release_id=?',
                (encoded, hashlib.sha256(encoded.encode()).hexdigest(), row['release_id']))
        result = await self.generate()
        self.assertEqual(result['error']['code'], 'assistance_unavailable', result)
        self.assertEqual(self.retained_state(), before)
        self.assertEqual(self.provider.payloads, [])

    async def test_timeout_and_cancellation_never_write_or_send(self):
        before = self.retained_state()
        self.provider.failure = TimeoutError('PRIVATE-CONNECTION-SECRET')
        timed_out = await self.generate()
        self.assertEqual(timed_out['error']['code'], 'assistance_timeout')
        self.assertNotIn('PRIVATE-CONNECTION-SECRET', str(timed_out))
        self.provider.failure = None
        self.provider.release = asyncio.Event()
        self.provider.started.clear()
        pending = asyncio.create_task(self.generate())
        await self.provider.started.wait()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertEqual(self.retained_state(), before)

    async def test_service_enforces_a_timeout_even_for_a_noncompliant_provider(self):
        before = self.retained_state()
        self.provider.release = asyncio.Event()
        timeout = asyncio.timeout
        with patch('loomrise.customer_service.asyncio.timeout', side_effect=lambda _: timeout(0.01)) as deadline:
            result = await self.generate()
        deadline.assert_called_once_with(65)
        self.assertEqual(result['error']['code'], 'assistance_timeout')
        self.assertEqual(self.retained_state(), before)

    async def test_invalid_inputs_never_call_the_provider(self):
        for key in ('generation', 'through_sequence'):
            for value in (True, False, 1.0, '1', [], {}, None, -1, 2**63):
                with self.subTest(key=key, value=value):
                    result = await self.generate(**{key: value})
                    self.assertEqual(result['error']['code'], 'invalid_request', result)
        for key in ('agent_id', 'conversation_id'):
            for value in (None, 5, [], {}, '', 'x' * 129, 'bad\x00identity'):
                with self.subTest(key=key, value=value):
                    self.assertFalse((await self.generate(**{key: value}))['ok'])
        for value in (None, 5, [], {}, '', 'x' * 64, 'a' * 65):
            with self.subTest(snapshot_hash=value):
                result = self.case.app.execute(principal=self.case.owner, action='inbox.assistance.check',
                    payload={**self.payload, 'snapshot_hash': value})
                self.assertEqual(result['error']['code'], 'invalid_request', result)
        self.assertEqual(self.provider.payloads, [])

    async def test_untrusted_output_shape_evidence_and_citations_fail_closed(self):
        valid = (await self.generate())['result']
        valid = {key: valid[key] for key in ('summary', 'reply', 'citations', 'model_evidence')}
        for citation in valid['citations']:
            citation.pop('title')
        bad_values = [None, [], {}, {**valid, 'send': True}, {**valid, 'summary': ''},
            {**valid, 'summary': '\x00'}, {**valid, 'summary': '文' * 2001},
            {**valid, 'reply': ''}, {**valid, 'reply': '文' * 5334},
            {**valid, 'citations': []}, {**valid, 'citations': valid['citations'] * 17},
            {**valid, 'model_evidence': {}}, {**valid, 'model_evidence': {
                **valid['model_evidence'], 'model': 'different-model'}},
            {**valid, 'model_evidence': {**valid['model_evidence'], 'usage': {'input_tokens': True}}}]
        for citation in ({'source_id': [], 'content_hash': 'x', 'quote': 'x'},
                         {**valid['citations'][0], 'content_hash': '0' * 64},
                         {**valid['citations'][0], 'quote': '未经授权的承诺'},
                         {**valid['citations'][0], 'extra': 'not allowed'}):
            bad_values.append({**valid, 'citations': [citation]})
        before = self.retained_state()
        for value in bad_values:
            with self.subTest(value=value):
                # The fixture's default response uses `or`; use an explicit result for falsey invalid values.
                async def invalid(**payload):
                    return deepcopy(value)
                with patch.object(self.provider, 'assist', side_effect=invalid):
                    result = await self.generate()
                self.assertEqual(result['error']['code'], 'assistance_invalid_response', result)
        self.assertEqual(self.retained_state(), before)

    async def test_model_payload_is_bounded_and_older_messages_still_invalidate_the_hash(self):
        for number in range(30):
            self.case.service.visitor_send(conversation_id=self.payload['conversation_id'],
                visitor_token=self.case.session['visitor_token'], text=f'{number} ' + '文' * 5000)
        self.payload['through_sequence'] = 31
        proposal = (await self.generate())['result']
        supplied = self.provider.payloads[-1]
        self.assertLessEqual(len(supplied['history']), 20)
        self.assertLessEqual(len(json.dumps(supplied, ensure_ascii=False).encode()), 60_000)
        self.assertNotIn('config', supplied)
        with self.case.store._tx() as cursor:
            cursor.execute('UPDATE customer_messages SET text=? WHERE conversation_id=? AND sequence=1',
                           ('修改窗口外历史', self.payload['conversation_id']))
        self.assertFalse(self.check(proposal)['ok'])


if __name__ == '__main__':
    unittest.main()
