from unittest.mock import patch

from loomrise.configuration import ConfigurationApplication, ConfigurationPrincipal
from tests.test_configuration_service import ConfigurationServiceCase


class ModelConnectionTests(ConfigurationServiceCase):
    def test_connection_metadata_is_scoped_and_never_includes_secrets_or_claims_a_test(self):
        principal = ConfigurationPrincipal('tenant-a', 'reader', 'viewer', ('expert-a',))
        app = ConfigurationApplication(self.service)
        with patch('loomrise.local_config.load_config', return_value={
            'model': 'fixed-model', 'key': 'secret-fixture', 'base_url': 'https://private.example.invalid/v1'}):
            result = app.execute(principal=principal, action='model.connection', payload={'agent_id': 'expert-a'})
            denied = app.execute(principal=principal, action='model.connection', payload={'agent_id': 'other'})
        self.assertEqual(result['result'], {'configured': True, 'model_id': 'fixed-model', 'status': 'configured', 'tested': False})
        self.assertEqual(denied['error']['code'], 'forbidden')
        self.assertNotIn('secret-fixture', str(result))
        self.assertNotIn('private.example.invalid', str(result))

    def test_invalid_local_configuration_is_reported_without_its_private_error(self):
        principal = ConfigurationPrincipal('tenant-a', 'owner', 'owner', ('expert-a',))
        with patch('loomrise.local_config.load_config', side_effect=RuntimeError('private-path')):
            result = ConfigurationApplication(self.service).execute(principal=principal,
                action='model.connection', payload={'agent_id': 'expert-a'})
        self.assertTrue(result['ok'])
        self.assertEqual(result['result']['status'], 'invalid_local_configuration')
        self.assertNotIn('private-path', str(result))
