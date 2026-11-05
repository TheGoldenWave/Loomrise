import unittest
import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

from loomrise.channel_sandbox import ChannelSandbox
from loomrise.configuration import ConfigurationPrincipal
from loomrise.customer_service import CustomerService, CustomerServiceApplication
from loomrise.durable_store import SqliteStore
import os, tempfile


class ChannelSandboxTests(unittest.TestCase):
    scope = {'tenant_id': 'tenant', 'agent_id': 'agent', 'channel': 'telegram', 'external_account': 'bot'}

    def test_delimiters_do_not_alias_connection_scopes_or_message_ids(self):
        for durable in (False, True):
            with self.subTest(durable=durable), tempfile.TemporaryDirectory() as directory:
                store = SqliteStore(os.path.join(directory, 'scope.db')) if durable else None
                try:
                    adapter = ChannelSandbox(store=store)
                    first_scope = {**self.scope, 'tenant_id': 'a:b', 'agent_id': 'c'}
                    second_scope = {**self.scope, 'tenant_id': 'a', 'agent_id': 'b:c'}
                    adapter.authorize(**first_scope)
                    with self.assertRaises(PermissionError):
                        adapter.send(**second_scope, message_id='m', thread_id='t', text='private')
                    adapter.authorize(**second_scope)
                    first = adapter.send(**first_scope, message_id='m', thread_id='t', text='one')
                    second = adapter.send(**second_scope, message_id='m', thread_id='t', text='two')
                    self.assertFalse(first['duplicate'])
                    self.assertFalse(second['duplicate'])
                    adapter.send(**first_scope, message_id='c', thread_id='a:b', text='same')
                    separated = adapter.send(**first_scope, message_id='b:c', thread_id='a', text='same')
                    self.assertFalse(separated['duplicate'])
                finally:
                    if store is not None:
                        store.close()

    def test_missing_durable_connection_cannot_fall_back_to_cached_authorization(self):
        store = SqliteStore(':memory:')
        try:
            adapter = ChannelSandbox(store=store)
            adapter.authorize(**self.scope)
            with store._tx() as cur:
                cur.execute('DELETE FROM channel_connections')
            with self.assertRaises(PermissionError):
                adapter.send(**self.scope, message_id='m', thread_id='t', text='private')
        finally:
            store.close()

    def test_revoke_and_reauthorize_use_durable_revision_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'restart.db')
            store = SqliteStore(path)
            self.assertEqual(ChannelSandbox(store=store).authorize(**self.scope)['revision'], 1)
            store.close()
            reopened = SqliteStore(path)
            try:
                revoked = ChannelSandbox(store=reopened).revoke(**self.scope)
                self.assertEqual(revoked['revision'], 2)
                self.assertEqual(revoked['state'], 'revoked')
                authorized = ChannelSandbox(store=reopened).authorize(**self.scope)
                self.assertEqual(authorized['revision'], 3)
                self.assertEqual(authorized['environment'], 'sandbox')
                self.assertEqual(ChannelSandbox(store=reopened).authorize(**self.scope)['revision'], 4)
            finally:
                reopened.close()

    def test_inbound_changed_body_conflicts_and_restored_duplicate_retains_sandbox(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'inbound.db')
            store = SqliteStore(path)
            adapter = ChannelSandbox(store=store)
            adapter.authorize(**self.scope)
            adapter.receive(**self.scope, message_id='m', thread_id='t', text='original')
            with self.assertRaises(ValueError):
                adapter.receive(**self.scope, message_id='m', thread_id='t', text='changed')
            store.close()
            reopened = SqliteStore(path)
            try:
                restored = ChannelSandbox(store=reopened)
                duplicate = restored.receive(**self.scope, message_id='m', thread_id='t', text='original')
                self.assertTrue(duplicate['duplicate'])
                self.assertEqual(duplicate['environment'], 'sandbox')
                self.assertEqual(duplicate['delivery'], 'simulated')
                with self.assertRaises(ValueError):
                    restored.receive(**self.scope, message_id='m', thread_id='t', text='changed')
            finally:
                reopened.close()

    def test_inbound_requires_nonempty_thread_and_bounded_text(self):
        adapter = ChannelSandbox()
        adapter.authorize(**self.scope)
        for index, patch in enumerate(({'thread_id': ''}, {'thread_id': 7}, {'text': ' '}, {'text': None}, {'text': 'x' * 20001})):
            with self.subTest(case=index), self.assertRaises(ValueError):
                adapter.receive(**self.scope, **({'message_id': 'm', 'thread_id': 't', 'text': 'valid'} | patch))

    def test_attachments_must_be_a_list_of_nonempty_string_ids(self):
        adapter = ChannelSandbox()
        adapter.authorize(**self.scope)
        for attachments in ('asset', {'asset': True}, [1], [' '], [['asset']], ('asset',)):
            with self.subTest(attachments=attachments), self.assertRaises(ValueError):
                adapter.send(**self.scope, message_id='m', thread_id='t', text='hello', attachment_ids=attachments)

    def test_concurrent_authorizations_increment_without_lost_updates(self):
        store = SqliteStore(':memory:')
        try:
            barrier = Barrier(6)
            def authorize(_):
                barrier.wait(timeout=5)
                return ChannelSandbox(store=store).authorize(**self.scope)['revision']
            with ThreadPoolExecutor(max_workers=6) as pool:
                revisions = list(pool.map(authorize, range(6)))
            self.assertEqual(sorted(revisions), list(range(1, 7)))
            self.assertEqual(store.channel_connection(**self.scope)['revision'], 6)
        finally:
            store.close()

    def test_concurrent_messages_record_one_message_and_one_event(self):
        store = SqliteStore(':memory:')
        try:
            ChannelSandbox(store=store).authorize(**self.scope)
            barrier = Barrier(8)
            def send(_):
                barrier.wait(timeout=5)
                return ChannelSandbox(store=store).send(**self.scope, message_id='m', thread_id='t', text='hello')
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(send, range(8)))
            self.assertEqual(sum(not item['duplicate'] for item in results), 1)
            self.assertEqual(store._conn.execute('SELECT COUNT(*) FROM channel_messages').fetchone()[0], 1)
            self.assertEqual(store._conn.execute("SELECT COUNT(*) FROM channel_events WHERE event_type='channel.message_sent'").fetchone()[0], 1)
        finally:
            store.close()

    def test_revoke_between_authorization_read_and_send_blocks_message_and_event(self):
        store = SqliteStore(':memory:')
        try:
            sending = ChannelSandbox(store=store)
            sending.authorize(**self.scope)
            revoking = ChannelSandbox(store=store)
            read = Event()
            resume = Event()
            original_auth = sending._auth
            def paused_auth(*args, **kwargs):
                result = original_auth(*args, **kwargs)
                read.set()
                self.assertTrue(resume.wait(timeout=5))
                return result
            sending._auth = paused_auth
            def send():
                try:
                    sending.send(**self.scope, message_id='m', thread_id='t', text='private')
                except Exception as exc:
                    return exc
                return None
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(send)
                self.assertTrue(read.wait(timeout=5))
                try:
                    revoking.revoke(**self.scope)
                finally:
                    resume.set()
                self.assertIsInstance(future.result(timeout=5), PermissionError)
            self.assertEqual(store._conn.execute('SELECT COUNT(*) FROM channel_messages').fetchone()[0], 0)
            self.assertEqual(store._conn.execute("SELECT COUNT(*) FROM channel_events WHERE event_type='channel.message_sent'").fetchone()[0], 0)
        finally:
            store.close()

    def test_event_insert_failure_rolls_back_message_and_allows_clean_retry(self):
        store = SqliteStore(':memory:')
        try:
            adapter = ChannelSandbox(store=store)
            adapter.authorize(**self.scope)
            store._conn.execute("CREATE TRIGGER fail_channel_event BEFORE INSERT ON channel_events WHEN NEW.event_type='channel.message_sent' BEGIN SELECT RAISE(ABORT, 'event failure'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                adapter.send(**self.scope, message_id='m', thread_id='t', text='hello')
            self.assertEqual(store._conn.execute('SELECT COUNT(*) FROM channel_messages').fetchone()[0], 0)
            self.assertFalse(any(event['type'] == 'channel.message_sent' for event in adapter.events))
            store._conn.execute('DROP TRIGGER fail_channel_event')
            self.assertFalse(adapter.send(**self.scope, message_id='m', thread_id='t', text='hello')['duplicate'])
        finally:
            store.close()

    def test_connection_event_failure_rolls_back_revision_and_authorization(self):
        store = SqliteStore(':memory:')
        try:
            adapter = ChannelSandbox(store=store)
            store._conn.execute("CREATE TRIGGER fail_channel_event BEFORE INSERT ON channel_events BEGIN SELECT RAISE(ABORT, 'event failure'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                adapter.authorize(**self.scope)
            self.assertIsNone(store.channel_connection(**self.scope))
            self.assertEqual(adapter.events, [])
            store._conn.execute('DROP TRIGGER fail_channel_event')
            self.assertEqual(adapter.authorize(**self.scope)['revision'], 1)
        finally:
            store.close()

    def test_previous_dedupe_format_is_reused_only_for_the_exact_scoped_identity(self):
        store = SqliteStore(':memory:')
        try:
            adapter = ChannelSandbox(store=store)
            first_scope = {**self.scope, 'tenant_id': 'a:b', 'agent_id': 'c'}
            second_scope = {**self.scope, 'tenant_id': 'a', 'agent_id': 'b:c'}
            adapter.authorize(**first_scope)
            adapter.authorize(**second_scope)
            legacy = hashlib.sha256(b'a:b:c:telegram:bot:inbound:t:m:1').hexdigest()
            with store._tx() as cur:
                cur.execute('INSERT INTO channel_messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                            (legacy, 'a:b', 'c', 'telegram', 'bot', 'inbound', 'm', 't', 'old', '[]', 'simulated', '2026-11-01T00:00:00+00:00'))
            different_scope = adapter.receive(**second_scope, message_id='m', thread_id='t', text='new')
            self.assertFalse(different_scope['duplicate'])
            restored = adapter.receive(**first_scope, message_id='m', thread_id='t', text='old')
            self.assertTrue(restored['duplicate'])
            self.assertEqual(restored['environment'], 'sandbox')
            self.assertEqual(store._conn.execute('SELECT COUNT(*) FROM channel_messages').fetchone()[0], 2)
            self.assertEqual(store._conn.execute("SELECT COUNT(*) FROM channel_events WHERE event_type='channel.message_received'").fetchone()[0], 1)
        finally:
            store.close()

    def test_authorization_revoke_and_duplicate_delivery_are_explicit(self):
        adapter = ChannelSandbox()
        adapter.authorize(tenant_id='t1', agent_id='a1', channel='telegram', external_account='bot-test')
        first = adapter.send(tenant_id='t1', agent_id='a1', channel='telegram', external_account='bot-test', message_id='m1', thread_id='t1', text='hello')
        second = adapter.send(tenant_id='t1', agent_id='a1', channel='telegram', external_account='bot-test', message_id='m1', thread_id='t1', text='hello')
        self.assertFalse(first['duplicate']); self.assertTrue(second['duplicate']); self.assertEqual(second['delivery'], 'simulated')
        adapter.revoke(tenant_id='t1', agent_id='a1', channel='telegram', external_account='bot-test')
        with self.assertRaises(PermissionError):
            adapter.send(tenant_id='t1', agent_id='a1', channel='telegram', external_account='bot-test', message_id='m2', thread_id='t1', text='late')

    def test_email_notify_only_does_not_leak_content_or_attachments(self):
        adapter = ChannelSandbox()
        adapter.authorize(tenant_id='t1', agent_id='a1', channel='email', external_account='support@example.invalid', mode='full')
        adapter.revoke(tenant_id='t1', agent_id='a1', channel='email', external_account='support@example.invalid')
        adapter.authorize(tenant_id='t1', agent_id='a1', channel='email', external_account='support@example.invalid', mode='notify_only')
        with self.assertRaises(PermissionError):
            adapter.send(tenant_id='t1', agent_id='a1', channel='email', external_account='support@example.invalid', message_id='m1', thread_id='t1', text='private')
        with self.assertRaises(ValueError):
            adapter.receive(tenant_id='t1', agent_id='a1', channel='email', external_account='support@example.invalid', message_id=' ', thread_id='t1', text='customer')
        received = adapter.receive(tenant_id='t1', agent_id='a1', channel='email', external_account='support@example.invalid', message_id='m2', thread_id='t1', text='customer')
        self.assertEqual(received['direction'], 'inbound')
        self.assertTrue(any(event['type'] == 'channel.message_received' for event in adapter.events))

    def test_customer_service_application_exposes_authorized_sandbox_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'channel.db'))
            try:
                principal = ConfigurationPrincipal(tenant_id='t', actor_id='owner', role='owner', agent_ids=('a',))
                app = CustomerServiceApplication(CustomerService(store, None))
                self.assertTrue(app.execute(principal=principal, action='channel.authorize', payload={
                    'agent_id': 'a', 'channel': 'telegram', 'external_account': 'bot'} )['ok'])
                sent = app.execute(principal=principal, action='channel.send', payload={
                    'agent_id': 'a', 'channel': 'telegram', 'external_account': 'bot', 'message_id': 'm', 'thread_id': 't1', 'text': 'hello'})
                self.assertTrue(sent['ok'])
                self.assertTrue(app.execute(principal=principal, action='channel.revoke', payload={
                    'agent_id': 'a', 'channel': 'telegram', 'external_account': 'bot'})['ok'])
            finally: store.close()

    def test_channel_connection_and_dedupe_survive_service_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'persistent-channel.db')
            store = SqliteStore(path)
            principal = ConfigurationPrincipal(tenant_id='t', actor_id='owner', role='owner', agent_ids=('a',))
            CustomerServiceApplication(CustomerService(store, None)).execute(principal=principal, action='channel.authorize', payload={'agent_id': 'a', 'channel': 'telegram', 'external_account': 'bot'})
            CustomerServiceApplication(CustomerService(store, None)).execute(principal=principal, action='channel.send', payload={'agent_id': 'a', 'channel': 'telegram', 'external_account': 'bot', 'message_id': 'm', 'thread_id': 't1', 'text': 'hello'})
            store.close()
            reopened = SqliteStore(path)
            try:
                app = CustomerServiceApplication(CustomerService(reopened, None))
                duplicate = app.execute(principal=principal, action='channel.send', payload={'agent_id': 'a', 'channel': 'telegram', 'external_account': 'bot', 'message_id': 'm', 'thread_id': 't1', 'text': 'hello'})
                self.assertTrue(duplicate['ok']); self.assertTrue(duplicate['result']['duplicate'])
            finally: reopened.close()

    def test_channel_scope_and_thread_conflicts_are_rejected(self):
        adapter = ChannelSandbox()
        adapter.authorize(tenant_id='t1', agent_id='a1', channel='telegram', external_account='same')
        with self.assertRaises(PermissionError):
            adapter.send(tenant_id='t2', agent_id='a2', channel='telegram', external_account='same', message_id='m', thread_id='t', text='leak')
        adapter.send(tenant_id='t1', agent_id='a1', channel='telegram', external_account='same', message_id='m', thread_id='t1', text='one')
        with self.assertRaises(ValueError):
            adapter.send(tenant_id='t1', agent_id='a1', channel='telegram', external_account='same', message_id='m', thread_id='t1', text='changed')
        second = adapter.send(tenant_id='t1', agent_id='a1', channel='telegram', external_account='same', message_id='m', thread_id='t2', text='two')
        self.assertFalse(second['duplicate'])


if __name__ == '__main__': unittest.main()
