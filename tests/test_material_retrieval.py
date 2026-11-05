import base64
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import subprocess

from loomrise.configuration import ConfigurationPrincipal
from loomrise.customer_service import CustomerService, CustomerServiceApplication
from tests.test_configuration_service import ConfigurationServiceCase


class MaterialRetrievalTests(ConfigurationServiceCase):
    def setUp(self):
        super().setUp()
        self.service = CustomerService(self.store, self.service)
        self.app = CustomerServiceApplication(self.service)
        self.owner = ConfigurationPrincipal('tenant-a', 'owner', 'owner', ('expert-a',))
        self.viewer = replace(self.owner, actor_id='viewer', role='viewer')

    def execute(self, action, payload, principal=None):
        return self.app.execute(principal=principal or self.owner, action=action, payload=payload)

    def material(self, *, asset_id=None, expires_at=None, text='课程说明与退款流程'):
        return self.service.create_material(principal=self.owner, agent_id='expert-a',
            filename='guide.txt', display_name='课程手册', authorization='owned', asset_id=asset_id,
            expires_at=expires_at, content_base64=base64.b64encode(text.encode()).decode())

    def candidate(self, material):
        return self.service.processing_candidate(principal=self.owner, agent_id='expert-a',
            asset_id=material['asset_id'])

    def search(self, query='退款', principal=None):
        return self.execute('material.search', {'agent_id': 'expert-a', 'query': query}, principal)

    def test_only_reviewed_current_summaries_are_returned_with_provenance(self):
        asset = self.material()
        candidate = self.candidate(asset)
        self.assertEqual(self.search()['result']['items'], [])
        self.service.review_processing_candidate(principal=self.owner, agent_id='expert-a',
            candidate_id=candidate['candidate_id'], review_state='approved')
        items = self.search()['result']['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['version_id'], asset['current_version_id'])
        self.assertEqual(items[0]['candidate_id'], candidate['candidate_id'])
        self.assertEqual(items[0]['source_hash'], asset['content_hash'])
        self.assertFalse(items[0]['grants_send_permission'])
        self.assertNotIn('content', items[0])
        self.assertEqual(self.search('%')['result']['items'], [])

    def test_pdf_text_candidate_stays_pending_until_explicit_review(self):
        pdf = self.service.create_material(principal=self.owner, agent_id='expert-a',
            filename='refund-policy.pdf', display_name='退款政策', authorization='owned',
            content_base64=base64.b64encode(b'%PDF-1.4 fixture').decode())
        with patch('loomrise.material_processing.shutil.which', return_value='/usr/bin/pdftotext'), \
                patch('loomrise.material_processing._run_bounded_stdout', return_value='退款流程'.encode()):
            candidate = self.candidate(pdf)

        self.assertEqual(candidate['status'], 'ready')
        self.assertEqual(candidate['review_state'], 'pending')
        self.assertEqual(self.search('退款')['result']['items'], [])
        self.service.review_processing_candidate(principal=self.owner, agent_id='expert-a',
            candidate_id=candidate['candidate_id'], review_state='approved')
        self.assertEqual(len(self.search('退款')['result']['items']), 1)

    def test_scanned_pdf_candidate_stays_pending_until_explicit_review(self):
        pdf = self.service.create_material(principal=self.owner, agent_id='expert-a',
            filename='scanned-refund-policy.pdf', display_name='扫描版退款政策', authorization='owned',
            content_base64=base64.b64encode(b'%PDF-1.4 scanned fixture').decode())
        outputs = iter((b'', b'Pages: 1\n', b'chi_sim\n', '退款流程'.encode()))

        def find(binary):
            return {'pdftotext': '/usr/bin/pdftotext', 'pdfinfo': '/usr/bin/pdfinfo',
                    'pdftoppm': '/usr/bin/pdftoppm', 'tesseract': '/usr/bin/tesseract'}.get(binary)

        with patch('loomrise.material_processing.shutil.which', side_effect=find), \
                patch('loomrise.material_processing._run_bounded_stdout', side_effect=lambda *a, **kw: next(outputs)), \
                patch('loomrise.material_processing._check_rendered_page'), \
                patch('loomrise.material_processing.subprocess.run', return_value=SimpleNamespace(returncode=0)) as render:
            candidate = self.candidate(pdf)

        self.assertEqual(candidate['status'], 'ready')
        self.assertEqual(candidate['review_state'], 'pending')
        self.assertEqual(self.search('退款')['result']['items'], [])
        self.service.review_processing_candidate(principal=self.owner, agent_id='expert-a',
            candidate_id=candidate['candidate_id'], review_state='approved')
        items = self.search('退款')['result']['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['source_hash'], pdf['content_hash'])
        self.assertEqual(items[0]['version_id'], pdf['current_version_id'])
        self.assertEqual(render.call_args.kwargs['stdin'], subprocess.DEVNULL)
        self.service.create_material(principal=self.owner, agent_id='expert-a',
            filename='scanned-refund-policy.pdf', display_name='新版扫描版退款政策', authorization='owned',
            asset_id=pdf['asset_id'],
            content_base64=base64.b64encode(b'%PDF-1.4 newer source').decode())
        self.assertEqual(self.search('退款')['result']['items'], [])

    def test_new_version_revocation_and_expiry_invalidate_old_search_results(self):
        for change in ('version', 'revoke', 'expiry'):
            with self.subTest(change=change):
                asset = self.material()
                candidate = self.candidate(asset)
                self.service.review_processing_candidate(principal=self.owner, agent_id='expert-a',
                    candidate_id=candidate['candidate_id'], review_state='approved')
                if change == 'revoke':
                    self.service.revoke_material(principal=self.owner, agent_id='expert-a', asset_id=asset['asset_id'])
                else:
                    self.material(asset_id=asset['asset_id'], expires_at='2000-01-01T00:00:00Z' if change == 'expiry' else None)
                self.assertNotIn(asset['asset_id'], [row['asset_id'] for row in self.search()['result']['items']])

    def test_viewer_cannot_generate_candidates_and_other_scope_cannot_search(self):
        asset = self.material()
        denied = self.execute('material.process', {'agent_id': 'expert-a', 'asset_id': asset['asset_id']}, self.viewer)
        self.assertEqual(denied['error']['code'], 'forbidden')
        self.assertEqual(self.search(principal=replace(self.owner, tenant_id='other'))['result']['items'], [])
        self.assertEqual(self.search(principal=replace(self.owner, agent_ids=('other',)))['error']['code'], 'forbidden')

    def test_stale_or_failed_candidates_cannot_be_approved(self):
        asset = self.material()
        candidate = self.candidate(asset)
        self.material(asset_id=asset['asset_id'], text='新版')
        result = self.execute('material.review_candidate', {'agent_id': 'expert-a',
            'candidate_id': candidate['candidate_id'], 'review_state': 'approved'})
        self.assertFalse(result['ok'])
