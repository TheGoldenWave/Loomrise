import base64
from dataclasses import replace
import json
import os
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from loomrise.configuration import ConfigurationPrincipal
from loomrise.customer_service import CustomerService, CustomerServiceApplication
from loomrise.durable_store import SqliteStore, SCHEMA_VERSION
from loomrise.material_derivatives import process_media
from tests.test_configuration_service import ConfigurationServiceCase
from tests.test_configuration_service import spec
from tests.test_material_derivatives import png_bytes


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'optional FFmpeg is unavailable')
class MaterialDerivativeStorageTests(ConfigurationServiceCase):
    def setUp(self):
        super().setUp()
        self.owner = ConfigurationPrincipal('tenant-a', 'owner', 'owner', ('expert-a',))
        self.customer = CustomerService(self.store, self.service)
        self.app = CustomerServiceApplication(self.customer)

    def create(self, *, content=None, asset_id=None):
        return self.customer.create_material(principal=self.owner, agent_id='expert-a',
            filename='original.png', display_name='虚构测试图片', authorization='owned',
            content_base64=base64.b64encode(content if content is not None else png_bytes()).decode(), asset_id=asset_id)

    def process(self, asset):
        return self.customer.processing_candidate(principal=self.owner, agent_id='expert-a', asset_id=asset['asset_id'])

    def test_real_derivative_is_downloadable_after_backup_and_isolated_by_scope(self):
        asset = self.create()
        result = self.process(asset)
        self.assertIn(result['status'], {'ready', 'failed', 'unavailable'})
        if not shutil.which('tesseract'):
            self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['review_state'], 'pending')
        self.assertEqual(self.customer.search_material_summaries(
            principal=self.owner, agent_id='expert-a', query='course'), [])
        self.assertEqual(result['derivation']['job']['status'], 'ready')
        derivative = result['derivation']['items'][0]
        original = self.customer.download_material(principal=self.owner, agent_id='expert-a', asset_id=asset['asset_id'])
        self.assertEqual(base64.b64decode(original['content_base64']), png_bytes())
        payload = {'agent_id': 'expert-a', 'asset_id': asset['asset_id'], 'derivative_id': derivative['derivative_id']}
        downloaded = self.app.execute(principal=self.owner, action='material.derivative.download', payload=payload)
        self.assertTrue(downloaded['ok'], downloaded)
        self.assertEqual(downloaded['result']['content_hash'], derivative['content_hash'])
        denied = self.app.execute(principal=replace(self.owner, tenant_id='other'), action='material.derivative.download', payload=payload)
        self.assertFalse(denied['ok'])
        backup = os.path.join(self.temp.name, 'backup.db')
        self.store.backup_to(backup)
        restored = SqliteStore(backup)
        try:
            row = restored.material_derivative(tenant_id='tenant-a', agent_id='expert-a',
                asset_id=asset['asset_id'], derivative_id=derivative['derivative_id'])
            self.assertEqual(row['content'], base64.b64decode(downloaded['result']['content_base64']))
            self.assertEqual(json.loads(row['metadata_json'])['source_hash'], asset['content_hash'])
        finally:
            restored.close()

    def test_failure_retains_original_and_persists_no_fake_file(self):
        original = b'\x89PNG\r\n\x1a\nbroken'
        asset = self.create(content=original)
        result = self.process(asset)
        self.assertEqual(result['derivation']['job']['status'], 'failed')
        self.assertEqual(result['derivation']['items'], [])
        listed = self.customer.list_material_derivatives(principal=self.owner, agent_id='expert-a', asset_id=asset['asset_id'])
        self.assertEqual(listed['jobs'][0]['status'], 'failed')
        self.assertEqual(listed['items'], [])
        source = self.customer.download_material(principal=self.owner, agent_id='expert-a', asset_id=asset['asset_id'])
        self.assertEqual(base64.b64decode(source['content_base64']), original)

    def test_revoke_during_processing_discards_the_late_output(self):
        asset = self.create()
        def revoke_after_transform(**kwargs):
            produced = process_media(**kwargs)
            self.customer.revoke_material(principal=self.owner, agent_id='expert-a', asset_id=asset['asset_id'])
            return produced
        with patch('loomrise.customer_service.process_media', side_effect=revoke_after_transform):
            result = self.process(asset)
        self.assertEqual(result['derivation']['job']['status'], 'discarded')
        self.assertEqual(result['derivation']['job']['error_code'], 'source_changed')
        self.assertEqual(result['derivation']['items'], [])

    def test_replacing_original_invalidates_old_derivative_downloads(self):
        asset = self.create()
        derivative = self.process(asset)['derivation']['items'][0]
        self.create(content=png_bytes(64, 64), asset_id=asset['asset_id'])
        with self.assertRaises(KeyError):
            self.customer.download_material_derivative(principal=self.owner, agent_id='expert-a',
                asset_id=asset['asset_id'], derivative_id=derivative['derivative_id'])

    def test_inbox_sends_only_the_selected_derivative_to_the_authorized_visitor(self):
        configuration = self.customer.configuration
        configuration.register_stable_version(tenant_id='tenant-a', agent_id='expert-a', version_id='v1', config=spec())
        configuration.create_draft_from_stable(tenant_id='tenant-a', agent_id='expert-a', base_version_id='v1')
        candidate = configuration.freeze_candidate(tenant_id='tenant-a', agent_id='expert-a', expected_revision=1, idempotency_key='media')
        self.store.approve_release_candidate(tenant_id='tenant-a', agent_id='expert-a',
            candidate_id=candidate['candidate_id'], content_hash=candidate['content_hash'],
            environment='sandbox', entry_id='entry', version_id='released-v1', approved_by='owner')
        self.store.publish_sandbox_candidate(tenant_id='tenant-a', agent_id='expert-a',
            candidate_id=candidate['candidate_id'], entry_id='entry', version_id='released-v1')
        session = self.customer.open_widget(tenant_id='tenant-a', agent_id='expert-a', entry_id='entry')
        claimed = self.customer.claim(principal=self.owner, agent_id='expert-a', conversation_id=session['conversation_id'])
        asset = self.create()
        derivative = self.process(asset)['derivation']['items'][0]
        request = {'conversation_id': session['conversation_id'], 'visitor_token': session['visitor_token'],
            'asset_id': asset['asset_id'], 'version_id': asset['current_version_id']}
        with self.assertRaises(KeyError):
            self.customer.visitor_download_material(**request, derivative_id=derivative['derivative_id'])
        sent = self.customer.send_material(principal=self.owner, agent_id='expert-a',
            conversation_id=session['conversation_id'], generation=claimed['occupancy_generation'],
            asset_id=asset['asset_id'], version_id=asset['current_version_id'], derivative_id=derivative['derivative_id'])
        self.assertEqual(sent['derivative_id'], derivative['derivative_id'])
        file = self.customer.visitor_download_material(**request, derivative_id=derivative['derivative_id'])
        self.assertEqual(file['content_hash'], derivative['content_hash'])
        with self.assertRaises(KeyError):
            self.customer.visitor_download_material(**request)  # Original was not sent.
        with self.assertRaises(RuntimeError):
            self.customer.send_material(principal=self.owner, agent_id='expert-a',
                conversation_id=session['conversation_id'], generation=claimed['occupancy_generation'] - 1,
                asset_id=asset['asset_id'], version_id=asset['current_version_id'], derivative_id=derivative['derivative_id'])
        self.customer.revoke_material(principal=self.owner, agent_id='expert-a', asset_id=asset['asset_id'])
        with self.assertRaises(KeyError):
            self.customer.visitor_download_material(**request, derivative_id=derivative['derivative_id'])


class MaterialDerivativeMigrationTests(ConfigurationServiceCase):
    def test_schema_13_migrates_without_changing_material_bytes(self):
        self.store.save_material(tenant_id='t', agent_id='a', asset_id='asset', version_id='version',
            display_name='原件', filename='raw.txt', media_type='text/plain', authorization='owned', expires_at=None, content=b'original')
        self.store.close()
        connection = sqlite3.connect(self.path)
        try:
            connection.execute('DROP TABLE material_derivatives')
            connection.execute('DROP TABLE material_derivative_jobs')
            connection.execute('ALTER TABLE customer_messages DROP COLUMN derivative_id')
            connection.execute("UPDATE meta SET value='13' WHERE key='schema_version'")
            connection.commit()
        finally:
            connection.close()
        restored = SqliteStore(self.path)
        try:
            self.assertEqual(restored.material_version(tenant_id='t', agent_id='a', asset_id='asset')['content'], b'original')
            self.assertEqual(restored.material_derivatives(tenant_id='t', agent_id='a', asset_id='asset')['items'], [])
            self.assertEqual(restored._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], str(SCHEMA_VERSION))
        finally:
            restored.close()
