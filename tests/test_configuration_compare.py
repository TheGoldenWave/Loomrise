from dataclasses import replace

from loomrise.configuration import ConfigurationApplication, ConfigurationPrincipal, field_diff, object_diff
from tests.test_configuration_service import ConfigurationServiceCase, spec


class ConfigurationCompareTests(ConfigurationServiceCase):
    def setUp(self):
        super().setUp()
        self.draft = self.seed()
        self.service.register_stable_version(
            tenant_id='tenant-a', agent_id='expert-a', version_id='v2', config=spec('第二目标'),
        )
        self.candidate = self.service.freeze_candidate(
            tenant_id='tenant-a', agent_id='expert-a', expected_revision=1, idempotency_key='compare',
        )
        self.app = ConfigurationApplication(self.service)
        self.principal = ConfigurationPrincipal('tenant-a', 'reader', 'viewer', ('expert-a',))

    def compare(self, before, after, principal=None):
        return self.app.execute(principal=principal or self.principal, action='configuration.compare',
            payload={'agent_id': 'expert-a', 'before': before, 'after': after})

    def test_compares_immutable_snapshots_in_selected_direction_without_writing(self):
        left = {'kind': 'candidate', 'id': self.candidate['candidate_id']}
        right = {'kind': 'stable', 'id': 'v2'}
        result = self.compare(left, right)
        self.assertTrue(result['ok'], result)
        value = result['result']
        self.assertEqual(value['before']['id'], left['id'])
        self.assertEqual(value['before']['config'], spec('原始目标'))
        self.assertEqual(value['after']['config'], spec('第二目标'))
        self.assertEqual(value['diff'], field_diff(value['before']['config'], value['after']['config']))
        self.assertEqual(value['object_diff'], object_diff(value['before']['config'], value['after']['config']))
        reverse = self.compare(right, left)['result']
        self.assertEqual(reverse['diff'][0]['before'], '第二目标')
        self.assertEqual(self.service.get_draft(tenant_id='tenant-a', agent_id='expert-a'), self.draft)
        self.assertEqual(len(self.service.list_candidates(tenant_id='tenant-a', agent_id='expert-a')), 1)

    def test_comparison_requires_same_authorized_expert_and_tenant(self):
        left, right = {'kind': 'stable', 'id': 'v1'}, {'kind': 'stable', 'id': 'v2'}
        self.assertEqual(self.compare(left, right, replace(self.principal, agent_ids=('other',)))['error']['code'], 'forbidden')
        self.assertEqual(self.compare(left, right, replace(self.principal, tenant_id='other'))['error']['code'], 'not_found')
        self.service.register_stable_version(tenant_id='tenant-a', agent_id='other', version_id='other-only', config=spec())
        self.assertEqual(self.compare(left, {'kind': 'stable', 'id': 'other-only'})['error']['code'], 'not_found')

    def test_only_explicit_stable_and_candidate_references_are_accepted(self):
        right = {'kind': 'stable', 'id': 'v2'}
        for reference in (None, [], {'kind': 'draft', 'id': 'latest'}, {'kind': 'stable', 'id': ''},
                          {'kind': 'stable', 'id': 'v1', 'agent_id': 'other'}):
            with self.subTest(reference=reference):
                self.assertEqual(self.compare(reference, right)['error']['code'], 'invalid_request')
