"""Per-operator read positions and preferences, separate from human occupancy."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import asyncio
import hashlib
import json
import sqlite3
import unittest
from unittest import mock

from loomrise.configuration import ConfigurationPrincipal
from loomrise.durable_store import SCHEMA_VERSION, SqliteStore
from tests import test_customer_service as fixture


class InboxReadStateTests(unittest.TestCase):
    setUp = fixture.CustomerServiceCase.setUp
    execute = fixture.CustomerServiceCase.execute

    def open(self):
        return self.execute('widget.open', {'agent_id': 'expert-a', 'entry_id': 'entry-a'})['result']

    def send(self, session, text='虚构访客消息', *, request_human=False):
        return self.service.visitor_send(**{key: session[key] for key in ('conversation_id', 'visitor_token')},
                                         text=text, request_human=request_human)

    def item(self, principal=None):
        return self.execute('inbox.list', {'agent_id': 'expert-a'}, principal)['result']['items'][0]

    def read(self, conversation_id, sequence, principal=None):
        return self.execute('inbox.read', {'agent_id': 'expert-a', 'conversation_id': conversation_id,
                                         'through_sequence': sequence}, principal)

    def events(self, after_sequence=0, limit=50, principal=None):
        return self.execute('inbox.events', {'agent_id': 'expert-a', 'after_sequence': after_sequence,
                                           'limit': limit}, principal)

    def test_unread_is_visitor_only_and_read_does_not_claim_or_change_another_operator(self):
        session = self.open()
        self.send(session)
        self.store.add_assistant_message(conversation_id=session['conversation_id'],
            visitor_token_hash=self.item()['visitor_token_hash'], text='虚构答复', version_id='sandbox-v1')
        self.send(session, '第二条')
        before = self.item()
        self.assertEqual((before['unread_count'], before['latest_sequence'], before['last_visitor_sequence'],
                          before['read_sequence']), (2, 3, 3, 0))
        self.assertTrue(self.read(session['conversation_id'], 1)['ok'])
        after = self.item()
        self.assertEqual((after['unread_count'], after['read_sequence']), (1, 1))
        self.assertEqual((after['state'], after['occupancy_generation'], after['assigned_to']),
                         (before['state'], before['occupancy_generation'], before['assigned_to']))
        other = ConfigurationPrincipal(tenant_id='tenant-a', actor_id='other', role='editor', agent_ids=('expert-a',))
        self.assertEqual(self.item(other)['unread_count'], 2)
        self.assertTrue(self.read(session['conversation_id'], 3)['ok'])
        self.assertEqual(self.item()['unread_count'], 0)
        self.send(session, '读后新消息')
        self.assertEqual(self.item()['unread_count'], 1)
        self.assertEqual(self.item(other)['unread_count'], 3)

    def test_read_cursor_is_monotonic_and_cannot_ack_future_or_invalid_positions(self):
        session = self.open()
        for _ in range(3):
            self.send(session)
        self.assertTrue(self.read(session['conversation_id'], 2)['ok'])
        self.assertEqual(self.read(session['conversation_id'], 1)['result']['read_sequence'], 2)
        for value in (True, False, -1, 1.5, '2', None, 4):
            with self.subTest(value=value):
                self.assertEqual(self.read(session['conversation_id'], value)['error']['code'], 'invalid_request')
        self.assertEqual(self.item()['read_sequence'], 2)
        self.assertEqual(self.item()['unread_count'], 1)

    def test_permissions_scope_and_actor_are_derived_from_principal(self):
        session = self.open()
        self.send(session)
        self.assertEqual(self.read(session['conversation_id'], 1, self.viewer)['error']['code'], 'forbidden')
        stranger = ConfigurationPrincipal(tenant_id='tenant-b', actor_id='owner', role='owner', agent_ids=('expert-a',))
        self.assertEqual(self.read(session['conversation_id'], 1, stranger)['error']['code'], 'not_found')
        outside = ConfigurationPrincipal(tenant_id='tenant-a', actor_id='owner', role='owner', agent_ids=('other',))
        self.assertEqual(self.read(session['conversation_id'], 1, outside)['error']['code'], 'forbidden')
        spoof = self.execute('inbox.read', {'agent_id': 'expert-a', 'conversation_id': session['conversation_id'],
            'through_sequence': 1, 'actor_id': 'other'})
        self.assertEqual(spoof['error']['code'], 'invalid_request')
        self.assertEqual(self.item()['read_sequence'], 0)

    def test_preferences_default_off_are_strict_and_isolated(self):
        get = lambda principal=None: self.execute('inbox.preferences', {'agent_id': 'expert-a'}, principal)
        self.assertEqual(get()['result'], {'new_messages': False, 'handoff': False, 'can_edit': True})
        saved = self.execute('inbox.preferences.save', {'agent_id': 'expert-a', 'new_messages': True, 'handoff': False})
        self.assertTrue(saved['ok'], saved)
        self.assertTrue(get()['result']['new_messages'])
        self.assertFalse(get(self.viewer)['result']['new_messages'])
        self.assertFalse(get(self.viewer)['result']['can_edit'])
        denied = self.execute('inbox.preferences.save', {'agent_id': 'expert-a', 'new_messages': True, 'handoff': True}, self.viewer)
        self.assertEqual(denied['error']['code'], 'forbidden')
        for change in ({'new_messages': 1, 'handoff': True}, {'new_messages': True},
                       {'new_messages': True, 'handoff': True, 'actor_id': 'other'}):
            result = self.execute('inbox.preferences.save', {'agent_id': 'expert-a', **change})
            self.assertEqual(result['error']['code'], 'invalid_request')

    def test_two_connections_cannot_move_read_position_backwards_and_rollback_is_atomic(self):
        session = self.open()
        for _ in range(4):
            self.send(session)
        second = SqliteStore(self.path)
        self.addCleanup(second.close)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(store.mark_customer_read, tenant_id='tenant-a', agent_id='expert-a', actor_id='owner',
                conversation_id=session['conversation_id'], through_sequence=sequence)
                for store, sequence in ((self.store, 4), (second, 2))]
            for future in futures:
                future.result()
        self.assertEqual(self.item()['read_sequence'], 4)
        def fail():
            raise RuntimeError('before commit')
        self.store.before_commit = fail
        try:
            with self.assertRaisesRegex(RuntimeError, 'before commit'):
                self.store.save_inbox_preferences(tenant_id='tenant-a', agent_id='expert-a', actor_id='owner',
                                                  new_messages=True, handoff=True)
        finally:
            self.store.before_commit = None
        self.assertFalse(self.execute('inbox.preferences', {'agent_id': 'expert-a'})['result']['new_messages'])

    def test_v15_upgrade_reopen_and_backup_keep_messages_and_operator_state(self):
        session = self.open()
        self.send(session)
        self.store.close()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('DROP TABLE IF EXISTS customer_inbox_reads')
            connection.execute('DROP TABLE IF EXISTS customer_inbox_preferences')
            connection.execute("UPDATE meta SET value='15' WHERE key='schema_version'")
        upgraded = SqliteStore(self.path)
        try:
            self.assertGreater(SCHEMA_VERSION, 15)
            self.assertEqual(upgraded.list_customer_conversations(tenant_id='tenant-a', agent_id='expert-a', actor_id='owner')[0]['unread_count'], 1)
            upgraded.mark_customer_read(tenant_id='tenant-a', agent_id='expert-a', actor_id='owner',
                conversation_id=session['conversation_id'], through_sequence=1)
            upgraded.save_inbox_preferences(tenant_id='tenant-a', agent_id='expert-a', actor_id='owner', new_messages=True, handoff=True)
            backup = self.path + '.backup'
            upgraded.backup_to(backup)
        finally:
            upgraded.close()
        for path in (self.path, backup):
            restored = SqliteStore(path)
            try:
                self.assertEqual(restored.list_customer_conversations(tenant_id='tenant-a', agent_id='expert-a', actor_id='owner')[0]['read_sequence'], 1)
                self.assertEqual(restored.inbox_preferences(tenant_id='tenant-a', agent_id='expert-a', actor_id='owner'),
                                 {'new_messages': True, 'handoff': True})
            finally:
                restored.close()

    def test_failed_cursor_commit_does_not_mark_messages_read(self):
        session = self.open()
        self.send(session)
        def fail():
            raise RuntimeError('before commit')
        self.store.before_commit = fail
        try:
            with self.assertRaisesRegex(RuntimeError, 'before commit'):
                self.store.mark_customer_read(tenant_id='tenant-a', agent_id='expert-a', actor_id='owner',
                    conversation_id=session['conversation_id'], through_sequence=1)
        finally:
            self.store.before_commit = None
        self.assertEqual((self.item()['read_sequence'], self.item()['unread_count']), (0, 1))

    def test_inbox_event_feed_replays_ordered_redacted_pages_and_scoped_cursor(self):
        session = self.open()
        self.send(session, 'private visitor body')
        self.store.add_assistant_message(conversation_id=session['conversation_id'],
            visitor_token_hash=self.item()['visitor_token_hash'], text='private assistant body', version_id='sandbox-v1')

        first = self.events(limit=1)
        self.assertTrue(first['ok'], first)
        self.assertEqual(first['result'], {'events': [{
            'sequence': 1, 'event_type': 'visitor.message', 'conversation_id': session['conversation_id'],
            'message_sequence': 1, 'state': 'bot', 'occupancy_generation': 0,
        }], 'next_cursor': 1, 'has_more': True})
        second = self.events(after_sequence=first['result']['next_cursor'], limit=1)
        self.assertTrue(second['ok'], second)
        self.assertEqual(second['result']['events'][0]['event_type'], 'assistant.response')
        self.assertEqual(second['result']['events'][0]['sequence'], 2)
        self.assertEqual(second['result']['next_cursor'], 2)
        self.assertFalse(second['result']['has_more'])
        self.assertNotIn('private visitor body', repr(first['result']))
        self.assertNotIn('private assistant body', repr(second['result']))
        self.assertFalse({'actor_id', 'text', 'visitor_token', 'visitor_fields'} & set(second['result']['events'][0]))
        empty = self.events(after_sequence=2)
        self.assertEqual((empty['result']['events'], empty['result']['next_cursor'], empty['result']['has_more']), ([], 2, False))

        other_tenant = ConfigurationPrincipal(tenant_id='tenant-b', actor_id='owner', role='owner', agent_ids=('expert-a',))
        self.assertEqual(self.events(principal=other_tenant)['result']['events'], [])

    def test_inbox_event_feed_covers_handoff_lifecycle_and_rejects_invalid_pages(self):
        session = self.open()
        self.send(session, 'please transfer', request_human=True)
        claim = self.execute('inbox.claim', {'agent_id': 'expert-a', 'conversation_id': session['conversation_id']})
        self.assertTrue(claim['ok'], claim)
        generation = claim['result']['occupancy_generation']
        reply = self.execute('inbox.reply', {'agent_id': 'expert-a', 'conversation_id': session['conversation_id'],
            'generation': generation, 'text': 'private operator body'})
        self.assertTrue(reply['ok'], reply)
        release = self.execute('inbox.release', {'agent_id': 'expert-a', 'conversation_id': session['conversation_id'],
            'generation': generation})
        self.assertTrue(release['ok'], release)

        result = self.events(limit=100)
        self.assertTrue(result['ok'], result)
        feed = result['result']['events']
        self.assertEqual([item['event_type'] for item in feed], [
            'visitor.message', 'handoff.requested', 'handoff.claimed', 'handoff.replied', 'handoff.released',
        ])
        self.assertEqual([item['sequence'] for item in feed], [1, 2, 3, 4, 5])
        self.assertTrue(all('private operator body' not in repr(item) for item in feed))

        for after, limit in ((True, 10), (-1, 10), (1.5, 10), ('1', 10), (None, 10), (6, 10),
                             (2**63, 10), (0, True),
                             (0, 0), (0, 101), (0, 1.5), (0, '1')):
            with self.subTest(after=after, limit=limit):
                self.assertEqual(self.events(after, limit)['error']['code'], 'invalid_request')
        self.assertEqual(self.events(limit=100, principal=self.viewer)['result']['events'], feed)

    def test_consumer_cursor_baselines_silently_and_isolated_by_tab_and_actor(self):
        session = self.open()
        self.send(session, 'before consumer baseline')
        payload = {'agent_id': 'expert-a', 'consumer_id': 'tab-a'}
        first = self.execute('inbox.consumer.cursor', payload)
        peer = self.execute('inbox.consumer.cursor', {'agent_id': 'expert-a', 'consumer_id': 'tab-b'})
        other_actor = ConfigurationPrincipal(tenant_id='tenant-a', actor_id='other', role='editor',
                                             agent_ids=('expert-a',))
        other_scope = self.execute('inbox.consumer.cursor', payload, other_actor)
        self.assertEqual((first['result']['cursor'], peer['result']['cursor'], other_scope['result']['cursor']),
                         (1, 1, 1))
        self.assertEqual(self.events(after_sequence=1)['result']['events'], [])

        self.send(session, 'after consumer baseline')
        acknowledged = self.execute('inbox.consumer.ack', {**payload, 'through_sequence': 2})
        self.assertTrue(acknowledged['ok'], acknowledged)
        self.assertEqual(acknowledged['result']['cursor'], 2)
        self.assertEqual(self.execute('inbox.consumer.cursor', payload)['result']['cursor'], 2)
        self.assertEqual(self.execute('inbox.consumer.cursor', {'agent_id': 'expert-a', 'consumer_id': 'tab-b'})
                         ['result']['cursor'], 1)
        self.assertEqual(self.execute('inbox.consumer.cursor', payload, other_actor)['result']['cursor'], 1)
        self.assertEqual(self.item()['read_sequence'], 0, 'event consumption must not mark messages read')
        spoofed = self.execute('inbox.consumer.ack', {**payload, 'through_sequence': 2, 'actor_id': 'other'})
        self.assertEqual(spoofed['error']['code'], 'invalid_request')

    def test_consumer_ack_is_monotonic_idempotent_and_rejects_invalid_or_future_positions(self):
        session = self.open()
        payload = {'agent_id': 'expert-a', 'consumer_id': 'tab-a'}
        self.assertTrue(self.execute('inbox.consumer.cursor', payload)['ok'])
        self.send(session)
        self.send(session)
        self.assertEqual(self.execute('inbox.consumer.ack', {**payload, 'through_sequence': 1})
                         ['result']['cursor'], 1)
        self.assertEqual(self.execute('inbox.consumer.ack', {**payload, 'through_sequence': 2})
                         ['result']['cursor'], 2)
        self.assertEqual(self.execute('inbox.consumer.ack', {**payload, 'through_sequence': 2})
                         ['result']['cursor'], 2)
        self.assertEqual(self.execute('inbox.consumer.ack', {**payload, 'through_sequence': 1})
                         ['result']['cursor'], 2)
        for value in (True, False, -1, 1.5, '2', None, 3, 2**63):
            with self.subTest(value=value):
                result = self.execute('inbox.consumer.ack', {**payload, 'through_sequence': value})
                self.assertEqual(result['error']['code'], 'invalid_request')
        for consumer_id in ('', 'tab/unsafe', '访客', 'x' * 129):
            with self.subTest(consumer_id=consumer_id[:12]):
                result = self.execute('inbox.consumer.cursor', {'agent_id': 'expert-a',
                                                                'consumer_id': consumer_id})
                self.assertEqual(result['error']['code'], 'invalid_request')
        self.assertEqual(self.execute('inbox.consumer.cursor', payload)['result']['cursor'], 2)

    def test_ack_without_cursor_row_never_skips_events_after_the_acknowledged_sequence(self):
        session = self.open()
        self.send(session, 'first event')
        self.send(session, 'second event')
        payload = {'agent_id': 'expert-a', 'consumer_id': 'tab-no-cursor', 'through_sequence': 1}
        result = self.execute('inbox.consumer.ack', payload)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['result']['cursor'], 1)
        self.assertEqual(self.execute('inbox.consumer.cursor', {
            'agent_id': 'expert-a', 'consumer_id': 'tab-no-cursor',
        })['result']['cursor'], 1)
        self.assertEqual([event['sequence'] for event in self.events(after_sequence=1)['result']['events']], [2])

    def test_v19_upgrade_consumer_cursor_reopen_and_backup_are_durable(self):
        session = self.open()
        self.send(session, 'durable event before upgrade')
        self.store.close()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('DROP TABLE IF EXISTS customer_inbox_consumers')
            connection.execute("UPDATE meta SET value='19' WHERE key='schema_version'")

        self.store = SqliteStore(self.path)
        self.addCleanup(self.store.close)
        self.assertGreater(SCHEMA_VERSION, 19)
        cursor = self.store.get_or_create_customer_inbox_consumer_cursor(
            tenant_id='tenant-a', agent_id='expert-a', actor_id='owner', consumer_id='tab-a',
        )
        self.assertEqual(cursor['cursor'], 1)
        self.store.ack_customer_inbox_consumer(
            tenant_id='tenant-a', agent_id='expert-a', actor_id='owner', consumer_id='tab-a',
            through_sequence=1,
        )
        backup_path = self.path + '.backup'
        self.store.backup_to(backup_path)
        for path in (self.path, backup_path):
            restored = SqliteStore(path)
            try:
                self.assertEqual(restored.get_or_create_customer_inbox_consumer_cursor(
                    tenant_id='tenant-a', agent_id='expert-a', actor_id='owner', consumer_id='tab-a',
                )['cursor'], 1)
            finally:
                restored.close()

    def test_inbox_message_and_event_commit_or_rollback_together(self):
        session = self.open()
        def fail():
            raise RuntimeError('before commit')
        self.store.before_commit = fail
        try:
            with self.assertRaisesRegex(RuntimeError, 'before commit'):
                self.send(session, 'rolled back')
        finally:
            self.store.before_commit = None
        messages = self.store.customer_messages(conversation_id=session['conversation_id'],
            tenant_id='tenant-a', agent_id='expert-a')
        self.assertEqual(messages, [])
        self.assertEqual(self.events()['result']['events'], [])

    def test_v17_upgrade_and_failed_migration_create_event_feed_atomically(self):
        session = self.open()
        self.store.close()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('DROP TABLE IF EXISTS customer_inbox_events')
            connection.execute("UPDATE meta SET value='17' WHERE key='schema_version'")
        upgraded = SqliteStore(self.path)
        try:
            self.assertGreater(SCHEMA_VERSION, 17)
            upgraded.add_visitor_message(conversation_id=session['conversation_id'],
                visitor_token_hash=hashlib.sha256(session['visitor_token'].encode()).hexdigest(), text='after upgrade')
            replay = upgraded.list_customer_inbox_events(tenant_id='tenant-a', agent_id='expert-a', after_sequence=0, limit=10)
            self.assertEqual([item['event_type'] for item in replay['events']], ['visitor.message'])
            upgraded.backup_to(self.path + '.backup')
        finally:
            upgraded.close()
        backup = SqliteStore(self.path + '.backup')
        try:
            self.assertEqual(backup.list_customer_inbox_events(tenant_id='tenant-a', agent_id='expert-a', after_sequence=0, limit=10)['events'][0]['sequence'], 1)
        finally:
            backup.close()

        self.store = SqliteStore(self.path)
        self.addCleanup(self.store.close)
        self.store._conn.execute('DROP TABLE customer_inbox_events')
        self.store._conn.execute("UPDATE meta SET value='17' WHERE key='schema_version'")
        def fail():
            raise RuntimeError('migration commit')
        self.store.before_commit = fail
        try:
            with self.assertRaisesRegex(RuntimeError, 'migration commit'):
                self.store.migrate()
        finally:
            self.store.before_commit = None
        self.assertEqual(self.store._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], '17')
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='customer_inbox_events'").fetchone()[0], 0)
        self.store.migrate()
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='customer_inbox_events'").fetchone()[0], 1)

    def test_failed_v15_migration_leaves_no_half_created_tables(self):
        self.store._conn.execute('DROP TABLE customer_inbox_reads')
        self.store._conn.execute('DROP TABLE customer_inbox_preferences')
        self.store._conn.execute("UPDATE meta SET value='15' WHERE key='schema_version'")
        def fail():
            raise RuntimeError('migration commit')
        self.store.before_commit = fail
        try:
            with self.assertRaisesRegex(RuntimeError, 'migration commit'):
                self.store.migrate()
        finally:
            self.store.before_commit = None
        self.assertEqual(self.store._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], '15')
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name IN ('customer_inbox_reads','customer_inbox_preferences')").fetchone()[0], 0)
        self.store.migrate()
        self.assertEqual(self.execute('inbox.preferences', {'agent_id': 'expert-a'})['result']['new_messages'], False)


from tests import test_config_http as http_fixture


class InboxReadHttpTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = http_fixture.ConfigurationHttpTests.asyncSetUp

    async def test_loopback_http_read_preferences_and_request_validation(self):
        from loomrise.config_http import APPLICATION_KEY, STORE_KEY
        service = self.app[APPLICATION_KEY].service
        store = self.app[STORE_KEY]
        candidate = service.freeze_candidate(tenant_id='tenant-a', agent_id='expert-a',
            expected_revision=1, idempotency_key='inbox-http')
        store.approve_release_candidate(tenant_id='tenant-a', agent_id='expert-a', candidate_id=candidate['candidate_id'],
            content_hash=candidate['content_hash'], environment='sandbox', entry_id='entry-a', version_id='sandbox-v1', approved_by='owner-a')
        store.publish_sandbox_candidate(tenant_id='tenant-a', agent_id='expert-a', candidate_id=candidate['candidate_id'],
            entry_id='entry-a', version_id='sandbox-v1')
        async def call(action, payload):
            response = await self.client.post('/api/customer-service', json={'action': action, 'payload': payload})
            return response.status, await response.json()
        status, opened = await call('widget.open', {'agent_id': 'expert-a', 'entry_id': 'entry-a'})
        self.assertEqual(status, 200)
        session = opened['result']
        status, sent = await call('widget.send', {'conversation_id': session['conversation_id'],
            'visitor_token': session['visitor_token'], 'text': '虚构 HTTP 消息', 'request_human': True})
        self.assertEqual(status, 200, sent)
        status, inbox = await call('inbox.list', {'agent_id': 'expert-a'})
        self.assertEqual((status, inbox['result']['items'][0]['unread_count']), (200, 1))
        self.assertTrue(inbox['result']['can_mark_read'])
        self.assertEqual(len(inbox['result']['notification_scope']), 64)
        status, events = await call('inbox.events', {'agent_id': 'expert-a', 'after_sequence': 0, 'limit': 10})
        self.assertEqual(status, 200)
        self.assertEqual([event['event_type'] for event in events['result']['events']], ['visitor.message', 'handoff.requested'])
        self.assertEqual((await call('inbox.events', {'agent_id': 'expert-a', 'after_sequence': True}))[0], 400)
        status, read = await call('inbox.read', {'agent_id': 'expert-a', 'conversation_id': session['conversation_id'], 'through_sequence': 1})
        self.assertEqual((status, read['result']['read_sequence']), (200, 1))
        self.assertEqual((await call('inbox.read', {'agent_id': 'expert-a', 'conversation_id': session['conversation_id'], 'through_sequence': 2}))[0], 400)
        self.assertEqual((await call('inbox.read', {'agent_id': 'other', 'conversation_id': session['conversation_id'], 'through_sequence': 1}))[0], 403)
        status, preferences = await call('inbox.preferences.save', {'agent_id': 'expert-a', 'new_messages': True, 'handoff': False})
        self.assertEqual((status, preferences['result']['new_messages']), (200, True))
        self.assertEqual((await call('inbox.preferences.save', {'agent_id': 'expert-a', 'new_messages': True, 'handoff': True, 'actor_id': 'other'}))[0], 400)

    async def test_inbox_sse_replays_redacted_events_and_resumes_by_cursor(self):
        from loomrise.config_http import APPLICATION_KEY, STORE_KEY

        service = self.app[APPLICATION_KEY].service
        store = self.app[STORE_KEY]
        candidate = service.freeze_candidate(tenant_id='tenant-a', agent_id='expert-a',
            expected_revision=1, idempotency_key='inbox-sse')
        store.approve_release_candidate(tenant_id='tenant-a', agent_id='expert-a', candidate_id=candidate['candidate_id'],
            content_hash=candidate['content_hash'], environment='sandbox', entry_id='entry-a', version_id='sandbox-v1', approved_by='owner-a')
        store.publish_sandbox_candidate(tenant_id='tenant-a', agent_id='expert-a', candidate_id=candidate['candidate_id'],
            entry_id='entry-a', version_id='sandbox-v1')
        opened = await self.client.post('/api/customer-service', json={
            'action': 'widget.open', 'payload': {'agent_id': 'expert-a', 'entry_id': 'entry-a'},
        })
        session = (await opened.json())['result']
        sent = await self.client.post('/api/customer-service', json={
            'action': 'widget.send', 'payload': {
                'conversation_id': session['conversation_id'], 'visitor_token': session['visitor_token'],
                'text': 'SSE stream test', 'request_human': True,
            },
        })
        self.assertEqual(sent.status, 200)
        consumer = {'agent_id': 'expert-a', 'consumer_id': 'sse-tab'}
        initialized = await self.client.post('/api/customer-service', json={
            'action': 'inbox.consumer.cursor', 'payload': consumer,
        })
        self.assertEqual((initialized.status, (await initialized.json())['result']['cursor']), (200, 2))
        sent = await self.client.post('/api/customer-service', json={
            'action': 'widget.send', 'payload': {
                'conversation_id': session['conversation_id'], 'visitor_token': session['visitor_token'],
                'text': 'unacknowledged SSE event', 'request_human': False,
            },
        })
        self.assertEqual(sent.status, 200)

        async with self.client.get('/api/customer-service/inbox/events', headers={
            'Origin': 'http://127.0.0.1:8765',
            'Last-Event-ID': '999',
        }, params=consumer) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_type, 'text/event-stream')
            self.assertEqual(response.headers['X-Accel-Buffering'], 'no')
            self.assertEqual(response.headers['Access-Control-Allow-Origin'], 'http://127.0.0.1:8765')
            lines = [await response.content.readline() for _ in range(3)]
            self.assertEqual(lines[0], b'id: 3\n')
            self.assertEqual(lines[1], b'event: inbox\n')
            event = json.loads(lines[2].removeprefix(b'data: ').strip())
            self.assertEqual(event['sequence'], 3)
            self.assertNotIn('text', event)
        self.assertEqual(
            self.app[STORE_KEY].list_customer_conversations(
                tenant_id='tenant-a', agent_id='expert-a', actor_id='owner-a',
            )[0]['read_sequence'],
            0,
        )

        async with self.client.get('/api/customer-service/inbox/events',
                                   headers={'Last-Event-ID': '999'}, params=consumer) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.content.readline(), b'id: 3\n')
        acknowledged = await self.client.post('/api/customer-service', json={
            'action': 'inbox.consumer.ack', 'payload': {**consumer, 'through_sequence': 3},
        })
        self.assertEqual((acknowledged.status, (await acknowledged.json())['result']['cursor']), (200, 3))

        live = await self.client.get('/api/customer-service/inbox/events', params={
            **consumer,
        })
        peer = await self.client.get('/api/customer-service/inbox/events', params={
            **consumer,
        })
        try:
            live.close()
            sent = await self.client.post('/api/customer-service', json={
                'action': 'widget.send', 'payload': {
                    'conversation_id': session['conversation_id'], 'visitor_token': session['visitor_token'],
                    'text': 'SSE incremental test', 'request_human': False,
                },
            })
            self.assertEqual(sent.status, 200)
            self.assertEqual(
                await asyncio.wait_for(peer.content.readline(), timeout=2),
                b'id: 4\n',
            )
        finally:
            live.close()
            peer.close()

        self.assertEqual((await self.client.get(
            '/api/customer-service/inbox/events', params={**consumer, 'after_sequence': '999'},
        )).status, 400)
        self.assertEqual((await self.client.get(
            '/api/customer-service/inbox/events',
            params={'agent_id': 'other', 'consumer_id': consumer['consumer_id']},
        )).status, 403)
        for params in ({'agent_id': 'expert-a'}, {'agent_id': 'expert-a', 'consumer_id': '访客'},
                       {'agent_id': 'expert-a', 'consumer_id': 'x' * 129}):
            with self.subTest(params=params):
                self.assertEqual(
                    (await self.client.get('/api/customer-service/inbox/events', params=params)).status,
                    400,
                )
        self.assertEqual(
            (await self.client.get('/api/customer-service/inbox/events?agent_id=expert-a&agent_id=expert-a')).status,
            400,
        )
        async with self.client.get('/api/customer-service/inbox/events', params=consumer,
                                   headers={'Last-Event-ID': 'not-a-sequence'}) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.content.readline(), b'id: 4\n')

    async def test_inbox_sse_replays_from_durable_ack_and_ignores_last_event_id(self):
        from loomrise.config_http import APPLICATION_KEY, STORE_KEY

        service = self.app[APPLICATION_KEY].service
        store = self.app[STORE_KEY]
        candidate = service.freeze_candidate(tenant_id='tenant-a', agent_id='expert-a',
            expected_revision=1, idempotency_key='inbox-durable-ack')
        store.approve_release_candidate(tenant_id='tenant-a', agent_id='expert-a', candidate_id=candidate['candidate_id'],
            content_hash=candidate['content_hash'], environment='sandbox', entry_id='entry-a', version_id='sandbox-v1', approved_by='owner-a')
        store.publish_sandbox_candidate(tenant_id='tenant-a', agent_id='expert-a', candidate_id=candidate['candidate_id'],
            entry_id='entry-a', version_id='sandbox-v1')

        async def call(action, payload):
            response = await self.client.post('/api/customer-service', json={'action': action, 'payload': payload})
            return response.status, await response.json()

        opened = await self.client.post('/api/customer-service', json={
            'action': 'widget.open', 'payload': {'agent_id': 'expert-a', 'entry_id': 'entry-a'},
        })
        session = (await opened.json())['result']
        async def send(text):
            response = await self.client.post('/api/customer-service', json={
                'action': 'widget.send', 'payload': {
                    'conversation_id': session['conversation_id'], 'visitor_token': session['visitor_token'],
                    'text': text, 'request_human': False,
                },
            })
            self.assertEqual(response.status, 200)

        await send('before consumer baseline')
        consumer = {'agent_id': 'expert-a', 'consumer_id': 'tab-a'}
        status, baseline = await call('inbox.consumer.cursor', consumer)
        self.assertEqual((status, baseline['result']['cursor']), (200, 1))
        await send('first not-yet-acknowledged event')
        await send('second not-yet-acknowledged event')

        async def first_stream_sequence(last_event_id):
            async with self.client.get('/api/customer-service/inbox/events', params=consumer,
                                       headers={'Last-Event-ID': last_event_id}) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(await response.content.readline(), b'id: 2\n')
                await response.content.readline()
                payload = json.loads((await response.content.readline()).removeprefix(b'data: ').strip())
                self.assertEqual(payload['sequence'], 2)
                self.assertNotIn('text', payload)

        await first_stream_sequence('3')
        await first_stream_sequence('3')
        status, acknowledged = await call('inbox.consumer.ack', {**consumer, 'through_sequence': 2})
        self.assertEqual((status, acknowledged['result']['cursor']), (200, 2))
        async with self.client.get('/api/customer-service/inbox/events', params=consumer,
                                   headers={'Last-Event-ID': '999'}) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.content.readline(), b'id: 3\n')
        self.assertEqual(store.list_customer_conversations(
            tenant_id='tenant-a', agent_id='expert-a', actor_id='owner-a',
        )[0]['read_sequence'], 0, 'event receipt is not message read state')

        self.assertEqual((await call('inbox.consumer.ack', {
            **consumer, 'through_sequence': 4,
        }))[0], 400)
        self.assertEqual((await call('inbox.consumer.cursor', {
            **consumer, 'actor_id': 'other',
        }))[0], 400)

    async def test_inbox_sse_cors_and_host_boundaries(self):
        headers = {'Origin': 'http://127.0.0.1:8765'}
        response = await self.client.options('/api/customer-service/inbox/events', headers=headers)
        self.assertEqual(response.status, 204)
        self.assertIn('GET', response.headers['Access-Control-Allow-Methods'])
        self.assertIn('Last-Event-ID', response.headers['Access-Control-Allow-Headers'])
        self.assertEqual((await self.client.head('/api/customer-service/inbox/events')).status, 405)
        blocked = await self.client.get('/api/customer-service/inbox/events',
                                        params={'agent_id': 'expert-a', 'consumer_id': 'cors-tab'},
                                        headers={'Origin': 'https://evil.invalid'})
        self.assertEqual(blocked.status, 403)
        remote = await self.client.get('/api/customer-service/inbox/events',
                                       params={'agent_id': 'expert-a', 'consumer_id': 'remote-tab'},
                                       headers={'Host': 'example.test'})
        self.assertEqual(remote.status, 403)

    async def test_inbox_sse_idle_connection_sends_keep_alive_without_reading(self):
        from loomrise import config_http
        from loomrise.config_http import APPLICATION_KEY, STORE_KEY

        service = self.app[APPLICATION_KEY].service
        candidate = service.freeze_candidate(tenant_id='tenant-a', agent_id='expert-a',
            expected_revision=1, idempotency_key='inbox-sse-idle')
        store = self.app[STORE_KEY]
        store.approve_release_candidate(tenant_id='tenant-a', agent_id='expert-a', candidate_id=candidate['candidate_id'],
            content_hash=candidate['content_hash'], environment='sandbox', entry_id='entry-a', version_id='sandbox-v1', approved_by='owner-a')
        store.publish_sandbox_candidate(tenant_id='tenant-a', agent_id='expert-a', candidate_id=candidate['candidate_id'],
            entry_id='entry-a', version_id='sandbox-v1')
        opened = await self.client.post('/api/customer-service', json={
            'action': 'widget.open', 'payload': {'agent_id': 'expert-a', 'entry_id': 'entry-a'},
        })
        session = (await opened.json())['result']
        await self.client.post('/api/customer-service', json={
            'action': 'widget.send', 'payload': {
                'conversation_id': session['conversation_id'], 'visitor_token': session['visitor_token'],
                'text': 'keep alive fixture', 'request_human': False,
            },
        })
        latest = store.list_customer_inbox_events(tenant_id='tenant-a', agent_id='expert-a',
                                                   after_sequence=0, limit=100)['next_cursor']
        with mock.patch.object(config_http, '_SSE_KEEPALIVE_SECONDS', 0):
            async with self.client.get('/api/customer-service/inbox/events', params={
                'agent_id': 'expert-a', 'consumer_id': 'idle-tab',
            }) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(await response.content.readline(), b': keep-alive\n')
        self.assertEqual(store.list_customer_conversations(
            tenant_id='tenant-a', agent_id='expert-a', actor_id='owner-a',
        )[0]['read_sequence'], 0)


if __name__ == '__main__':
    unittest.main()
