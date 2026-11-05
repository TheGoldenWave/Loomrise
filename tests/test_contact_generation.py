import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

from loomrise.config_http import APPLICATION_KEY, CUSTOMER_APPLICATION_KEY, create_configuration_http_app
from loomrise.configuration import ConfigurationPrincipal, ConfigurationService
from loomrise.contact_pages import contact_generation_schema, validate_generated_contact
from loomrise.customer_service import CustomerService, CustomerServiceApplication
from loomrise.durable_store import SqliteStore
from tests.test_configuration_service import spec


CONTACT = {
    'schema_version': 'contact-page-v1', 'template_id': 'support',
    'title': '虚构工坊联系页', 'description': '提供作品咨询。',
    'blocks': [
        {'id': 'intro', 'type': 'text', 'title': '服务介绍', 'body': '请通过客服咨询作品。', 'items': []},
        {'id': 'chat', 'type': 'chat', 'title': '咨询客服', 'body': '', 'items': []},
    ],
}
EVIDENCE = {'model': 'actual-generation-model', 'response_id': 'resp-contact',
            'usage': {'input_tokens': 10, 'output_tokens': 20, 'total_tokens': 30},
            'duration_ms': 4, 'provider': 'local-responses-v1'}
GENERATION_ITEM_FIELDS = {
    'text': set(), 'chat': set(), 'social': {'label', 'href'},
    'link': {'label', 'href'}, 'portfolio': {'title'},
    'media': {'src', 'alt', 'media_type'}, 'services': {'title'},
    'testimonials': {'quote', 'author'}, 'booking': {'label', 'href'},
    'faq': {'question', 'answer'}, 'metrics': {'label', 'value'},
    'menu': {'title'}, 'hours': {'day', 'hours'},
    'location': {'label', 'address'}, 'skills': {'label'},
    'experience': {'title', 'period'}, 'schedule': {'title', 'time'},
    'jobs': {'title'}, 'community': {'label', 'href'},
    'qr': {'label', 'src', 'alt'}, 'contact': {'label', 'value'},
}


def generation_item(kind):
    fields = GENERATION_ITEM_FIELDS[kind]
    item = {field: '示例内容' for field in fields}
    if 'href' in fields:
        item['href'] = 'https://example.test/contact'
    if 'src' in fields:
        item['src'] = 'https://example.test/media.png'
    if 'media_type' in fields:
        item['media_type'] = 'image'
    return item

class GenerationProvider:
    def __init__(self, contact=None):
        self.contact = deepcopy(CONTACT if contact is None else contact)
        self.calls = []
        self.runs = 0
        self.before_return = None
        self.error = None
        self.evidence = deepcopy(EVIDENCE)

    def for_run(self):
        self.runs += 1
        return self

    async def generate_contact(self, **payload):
        self.calls.append(payload)
        if self.before_return:
            await self.before_return()
        if self.error:
            raise self.error
        return {'contact': deepcopy(self.contact), 'model_evidence': deepcopy(self.evidence)}


class ContactGenerationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SqliteStore(os.path.join(self.tmp.name, 'contact-generation.db'))
        self.configuration = ConfigurationService(self.store)
        config = {**spec('private_prompt: never send this configuration'),
                  'contact': {'title': '当前公开联系页', 'blocks': []}}
        self.configuration.register_stable_version(
            tenant_id='tenant-a', agent_id='expert-a', version_id='v1', config=config)
        self.configuration.create_draft_from_stable(
            tenant_id='tenant-a', agent_id='expert-a', base_version_id='v1')
        candidate = self.configuration.freeze_candidate(
            tenant_id='tenant-a', agent_id='expert-a', expected_revision=1,
            idempotency_key='contact-generation-test')
        self.store.approve_release_candidate(
            tenant_id='tenant-a', agent_id='expert-a', candidate_id=candidate['candidate_id'],
            content_hash=candidate['content_hash'], environment='sandbox',
            entry_id='contact-entry', version_id='sandbox-v1', approved_by='owner')
        self.store.publish_sandbox_candidate(
            tenant_id='tenant-a', agent_id='expert-a', candidate_id=candidate['candidate_id'],
            entry_id='contact-entry', version_id='sandbox-v1')
        self.owner = ConfigurationPrincipal(
            tenant_id='tenant-a', actor_id='owner', role='owner', agent_ids=('expert-a',))
        self.provider = GenerationProvider()
        self.service = CustomerService(self.store, self.configuration, contact_generation_provider=self.provider)
        self.app = CustomerServiceApplication(self.service)
        enabled = self.app.execute(principal=self.owner, action='contact.enable',
                                   payload={'agent_id': 'expert-a', 'entry_id': 'contact-entry'})
        self.assertTrue(enabled['ok'], enabled)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.store.close)

    def draft(self):
        return self.configuration.get_draft(tenant_id='tenant-a', agent_id='expert-a')

    def test_generation_schema_and_validator_cover_the_21_kind_field_matrix(self):
        schema = contact_generation_schema('support')
        variants = schema['properties']['blocks']['items']['anyOf']
        by_kind = {variant['properties']['type']['enum'][0]: variant for variant in variants}
        self.assertEqual(set(by_kind), set(GENERATION_ITEM_FIELDS))
        self.assertEqual(len(by_kind), 21)

        blocks = []
        for index, (kind, expected_fields) in enumerate(GENERATION_ITEM_FIELDS.items()):
            with self.subTest(kind=kind):
                variant = by_kind[kind]
                self.assertEqual(set(variant['required']), set(variant['properties']))
                item_schema = variant['properties']['items']
                if expected_fields:
                    self.assertEqual(item_schema['maxItems'], 50)
                    item = item_schema['items']
                    self.assertEqual(set(item['properties']), expected_fields)
                    self.assertEqual(set(item['required']), expected_fields)
                    self.assertFalse(item['additionalProperties'])
                    for field in expected_fields:
                        if field in {'href', 'src'}:
                            self.assertEqual(item['properties'][field]['maxLength'], 2048)
                    if kind == 'media':
                        self.assertEqual(item['properties']['media_type']['enum'], ['image', 'video', 'audio'])
                    candidate_item = generation_item(kind)
                    self.assertEqual(set(candidate_item), expected_fields)
                else:
                    self.assertEqual(item_schema['maxItems'], 0)
                    self.assertEqual(item_schema['items']['type'], 'string')
                    candidate_item = None

                blocks.append({'id': f'block-{index}', 'type': kind, 'title': kind,
                               'body': '', 'items': [] if candidate_item is None else [candidate_item]})

        candidate = {'schema_version': 'contact-page-v1', 'template_id': 'support',
                     'title': '虚构工坊', 'description': '作品咨询', 'blocks': blocks}
        self.assertEqual(validate_generated_contact(candidate, template_id='support'), candidate)

        for block in candidate['blocks']:
            kind = block['type']
            if not GENERATION_ITEM_FIELDS[kind]:
                continue
            with self.subTest(rejected_optional_field=kind):
                extra = deepcopy(candidate)
                extra_block = next(item for item in extra['blocks'] if item['type'] == kind)
                extra_block['items'][0]['optional_editor_field'] = 'must not be generated'
                with self.assertRaises(ValueError):
                    validate_generated_contact(extra, template_id='support')

    async def generate(self, payload=None, principal=None):
        return await self.app.execute_async(principal=principal or self.owner, action='contact.generate',
            payload={'agent_id': 'expert-a', 'expected_revision': 1,
                     'brief': '虚构工坊提供作品咨询，保留客服入口。', 'template_id': 'support', **(payload or {})})

    async def test_generation_returns_a_proposal_until_explicit_save(self):
        before = self.draft()
        binding = self.store.contact_page(tenant_id='tenant-a', agent_id='expert-a', entry_id='contact-entry')
        response = await self.generate()
        self.assertTrue(response['ok'], response)
        proposal = response['result']
        self.assertEqual(proposal, {'state': 'proposal', 'base_revision': 1,
                                    'contact': CONTACT, 'model_evidence': EVIDENCE})
        self.assertEqual(self.draft(), before)
        self.assertEqual(self.store.contact_page(
            tenant_id='tenant-a', agent_id='expert-a', entry_id='contact-entry'), binding)
        self.assertEqual(self.provider.runs, 1)
        self.assertEqual(self.provider.calls, [
            {'brief': '虚构工坊提供作品咨询，保留客服入口。', 'template_id': 'support'}])
        self.assertNotIn('private_prompt', json.dumps(self.provider.calls))

        saved = self.app.execute(principal=self.owner, action='contact.save', payload={
            'agent_id': 'expert-a', 'expected_revision': proposal['base_revision'], 'contact': proposal['contact']})
        self.assertTrue(saved['ok'], saved)
        after = self.draft()
        self.assertEqual(after['revision'], 2)
        expected_config = deepcopy(before['config'])
        expected_config['contact'] = CONTACT
        self.assertEqual(after['config'], expected_config)
        self.assertEqual(self.store.contact_page(
            tenant_id='tenant-a', agent_id='expert-a', entry_id='contact-entry'), binding)

    async def test_all_21_generated_block_kinds_remain_a_proposal_until_separately_saved(self):
        kinds = list(GENERATION_ITEM_FIELDS)
        contact = {'schema_version': 'contact-page-v1', 'template_id': 'support',
                   'title': '虚构工坊全类型样例', 'description': '仅供测试', 'blocks': [
            {'id': f'block-{index}', 'type': kind, 'title': kind, 'body': '',
             'items': [] if not GENERATION_ITEM_FIELDS[kind] else [generation_item(kind)]}
            for index, kind in enumerate(kinds)
        ]}
        self.provider.contact = contact
        before = self.draft()

        proposal = await self.generate()
        self.assertTrue(proposal['ok'], proposal)
        self.assertEqual(proposal['result']['state'], 'proposal')
        self.assertEqual(proposal['result']['contact'], contact)
        self.assertEqual(self.draft(), before)

        saved = self.app.execute(principal=self.owner, action='contact.save', payload={
            'agent_id': 'expert-a', 'expected_revision': proposal['result']['base_revision'],
            'contact': proposal['result']['contact']})
        self.assertTrue(saved['ok'], saved)
        self.assertEqual(self.draft()['revision'], 2)
        self.assertEqual(self.draft()['config']['contact'], contact)

    async def test_authorization_and_stale_revision_reject_before_model_call(self):
        for principal in (
            ConfigurationPrincipal(tenant_id='tenant-a', actor_id='viewer', role='viewer', agent_ids=('expert-a',)),
            ConfigurationPrincipal(tenant_id='tenant-a', actor_id='external', role='external_agent', agent_ids=('expert-a',)),
            ConfigurationPrincipal(tenant_id='tenant-a', actor_id='owner', role='owner', agent_ids=('expert-b',)),
        ):
            with self.subTest(principal=principal):
                response = await self.generate(principal=principal)
                self.assertEqual(response['error']['code'], 'forbidden', response)
        stale = await self.generate({'expected_revision': 0})
        self.assertEqual(stale['error']['code'], 'revision_conflict', stale)
        self.assertEqual(self.provider.calls, [])

    async def test_invalid_generation_fields_reject_before_model_call(self):
        for update in ({'expected_revision': True}, {'expected_revision': 1.0}, {'expected_revision': -1},
                       {'expected_revision': '1'}, {'brief': ''}, {'brief': '  '}, {'brief': 'x' * 4001},
                       {'brief': None}, {'brief': 'x\x00y'}, {'template_id': 'not-a-template'},
                       {'template_id': None}, {'model': 'browser-override'}, {'config': {}}):
            with self.subTest(update=update):
                result = await self.generate(update)
                self.assertEqual(result['error']['code'], 'invalid_request', result)
        result = await self.app.execute_async(principal=self.owner, action='contact.generate',
            payload={'agent_id': 'expert-a', 'brief': '有授权的资料'})
        self.assertEqual(result['error']['code'], 'invalid_request', result)
        self.assertEqual(self.provider.calls, [])

    async def test_invalid_model_content_and_errors_fail_without_private_details(self):
        invalid = [
            {**CONTACT, 'javascript': 'secret-fixture'},
            {key: value for key, value in CONTACT.items() if key != 'title'},
            {**CONTACT, 'template_id': 'profile'},
            {**CONTACT, 'blocks': [{'id': 'unsafe', 'type': 'script', 'body': 'secret-fixture'}]},
            {**CONTACT, 'blocks': [{'id': 'unsafe', 'type': 'link', 'items': [
                {'label': 'bad', 'href': 'javascript:secret-fixture'}]}]},
        ]
        before = self.draft()
        for content in invalid:
            with self.subTest(content=content):
                self.provider.contact = content
                result = await self.generate()
                self.assertFalse(result['ok'], result)
                self.assertEqual(result['error']['code'], 'generation_failed', result)
                self.assertNotIn('secret-fixture', json.dumps(result))
        self.provider.error = RuntimeError('secret-fixture https://private.invalid/key')
        result = await self.generate()
        self.assertEqual(result['error']['code'], 'generation_failed', result)
        self.assertNotIn('secret-fixture', json.dumps(result))
        self.assertNotIn('private.invalid', json.dumps(result))
        self.assertEqual(self.draft(), before)

    async def test_missing_provider_is_an_explicit_unavailable_result(self):
        self.service.contact_generation_provider = None
        result = await self.generate()
        self.assertEqual(result['error']['code'], 'generation_unavailable', result)
        self.assertEqual(self.provider.calls, [])

    async def test_a_save_during_generation_rejects_the_late_proposal(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def wait_for_save():
            started.set()
            await release.wait()

        self.provider.before_return = wait_for_save
        generation = asyncio.create_task(self.generate())
        self.addAsyncCleanup(self._cancel, generation)
        await asyncio.wait_for(started.wait(), 1)
        saved = self.app.execute(principal=self.owner, action='contact.save', payload={
            'agent_id': 'expert-a', 'expected_revision': 1,
            'contact': {'title': '另一个编辑者保存的联系页', 'blocks': []}})
        self.assertTrue(saved['ok'], saved)
        release.set()
        result = await generation
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['error']['code'], 'revision_conflict', result)
        self.assertEqual(self.draft()['revision'], 2)
        self.assertEqual(self.draft()['config']['contact']['title'], '另一个编辑者保存的联系页')

    async def test_evidence_contains_only_typed_public_metadata(self):
        for evidence in ({**EVIDENCE, 'key': 'secret-fixture'},
                         {**EVIDENCE, 'model': {'key': 'secret-fixture'}},
                         {**EVIDENCE, 'usage': {'key': 'secret-fixture'}},
                         {**EVIDENCE, 'duration_ms': True}):
            with self.subTest(evidence=evidence):
                self.provider.evidence = evidence
                result = await self.generate()
                self.assertFalse(result['ok'], result)
                self.assertEqual(result['error']['code'], 'generation_failed', result)
                self.assertNotIn('secret-fixture', json.dumps(result))

    async def test_untyped_sdk_identity_fails_without_saving_or_exposing_provider_details(self):
        from unittest.mock import patch
        from loomrise.model_provider import LocalModelProvider
        from tests.test_model_provider import AsyncProviderTests, CONFIG

        before = self.draft()
        binding = self.store.contact_page(tenant_id='tenant-a', agent_id='expert-a', entry_id='contact-entry')
        self.service.contact_generation_provider = LocalModelProvider(CONFIG, max_calls=1)
        for key in ('model', 'id'):
            for value in (None, False, 42):
                with self.subTest(key=key, value=value):
                    sdk, client = AsyncProviderTests().sdk(CONTACT, **{key: value})
                    with patch('loomrise.model_provider.AsyncOpenAI', sdk):
                        result = await self.generate()
                    self.assertFalse(result['ok'], result)
                    self.assertEqual(result['error']['code'], 'generation_failed', result)
                    self.assertNotIn(CONFIG['key'], json.dumps(result))
                    self.assertNotIn('model_evidence', result)
                    self.assertEqual(client.responses.create.call_count, 1)
        self.assertEqual(self.draft(), before)
        self.assertEqual(self.store.contact_page(
            tenant_id='tenant-a', agent_id='expert-a', entry_id='contact-entry'), binding)

    async def test_editor_can_generate_without_a_template_and_cancellation_propagates(self):
        editor = ConfigurationPrincipal(tenant_id='tenant-a', actor_id='editor', role='editor', agent_ids=('expert-a',))
        result = await self.app.execute_async(principal=editor, action='contact.generate',
            payload={'agent_id': 'expert-a', 'expected_revision': 1, 'brief': '只含本轮授权素材。'})
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.provider.calls, [{'brief': '只含本轮授权素材。', 'template_id': None}])
        self.provider.error = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.generate()
        self.assertEqual(self.draft()['revision'], 1)

    @staticmethod
    async def _cancel(task):
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class ContactGenerationHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.principal_path = root / 'principal.json'
        self.principal_path.write_text(json.dumps({
            'tenant_id': 'tenant-a', 'actor_id': 'owner', 'role': 'owner', 'agent_ids': ['expert-a'],
        }), encoding='utf-8')
        os.chmod(self.principal_path, 0o600)
        self.provider = GenerationProvider()
        self.app = create_configuration_http_app(
            principal_path=self.principal_path, database_path=root / 'configuration.db',
            reception_provider=None, contact_generation_provider=self.provider)
        self.service = self.app[CUSTOMER_APPLICATION_KEY].service
        self.configuration = self.app[APPLICATION_KEY].service
        self.configuration.register_stable_version(
            tenant_id='tenant-a', agent_id='expert-a', version_id='v1', config=spec())
        self.configuration.create_draft_from_stable(
            tenant_id='tenant-a', agent_id='expert-a', base_version_id='v1')
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addCleanup(self.tmp.cleanup)
        self.addAsyncCleanup(self.client.close)

    async def generate(self, **changes):
        return await self.client.post('/api/customer-service', json={
            'action': 'contact.generate', 'payload': {
                'agent_id': 'expert-a', 'expected_revision': 1,
                'brief': '虚构工坊提供作品咨询。', 'template_id': 'support', **changes}})

    async def test_contact_generation_is_dispatched_asynchronously(self):
        response = await self.generate()
        self.assertEqual(response.status, 200, await response.text())
        body = await response.json()
        self.assertTrue(body['ok'], body)
        self.assertEqual(body['result']['state'], 'proposal')
        self.assertEqual(body['result']['base_revision'], 1)
        self.assertEqual(body['result']['contact'], CONTACT)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.configuration.get_draft(tenant_id='tenant-a', agent_id='expert-a')['revision'], 1)

    async def test_generation_errors_have_explicit_http_status_and_safe_messages(self):
        self.service.contact_generation_provider = None
        missing = await self.generate()
        self.assertEqual(missing.status, 503, await missing.text())
        self.assertEqual((await missing.json())['error']['code'], 'generation_unavailable')
        self.service.contact_generation_provider = self.provider
        self.provider.error = RuntimeError('secret-fixture')
        failed = await self.generate()
        self.assertEqual(failed.status, 502, await failed.text())
        self.assertNotIn('secret-fixture', await failed.text())
        stale = await self.generate(expected_revision=0)
        self.assertEqual(stale.status, 409, await stale.text())
        invalid = await self.generate(model='untrusted-model-override')
        self.assertEqual(invalid.status, 400, await invalid.text())
