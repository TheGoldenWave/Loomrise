import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from loomrise.model_provider import LocalModelProvider, ModelProviderError


CONFIG = {'model': 'fixed-model', 'base_url': 'https://example.invalid/v1', 'key': 'secret-fixture'}
DECISION = {'decision': 'complete', 'scores': {'complete': 0.9, 'incomplete': 0.1},
            'evidence': {'fields': ['verified'], 'utterance': ''}}


def response(value, **changes):
    return SimpleNamespace(**({'status': 'completed', 'output_text': json.dumps(value), 'id': 'resp-test',
        'model': 'fixed-model', 'usage': SimpleNamespace(input_tokens=10, output_tokens=20, total_tokens=30)} | changes))


def sync_stream(value):
    stream = MagicMock()
    stream.__enter__.return_value = stream
    stream.__iter__.return_value = iter([SimpleNamespace(type='response.completed', response=value)])
    return stream


class CompletionProviderTests(unittest.TestCase):
    def test_invalid_response_identity_never_becomes_model_evidence(self):
        for key in ('model', 'id'):
            for value in (None, False, 42, '', '  ', 'x' * 201, 'bad\x00identity'):
                with self.subTest(key=key, value=value), patch('loomrise.model_provider.OpenAI') as sdk:
                    sdk.return_value.__enter__.return_value.responses.create.return_value = sync_stream(
                        response(DECISION, **{key: value}))
                    with self.assertRaisesRegex(ModelProviderError, 'model_response_invalid_identity'):
                        LocalModelProvider(CONFIG).completion({}, {'verified': True})

    def test_completion_evidence_is_constrained_to_fields_the_runtime_can_read(self):
        from loomrise.graph_runtime import GraphRuntime
        from tests.test_graph_completion import GraphCompletionTests

        with patch('loomrise.model_provider.OpenAI') as sdk:
            client = sdk.return_value.__enter__.return_value
            requests = []

            def create(**request):
                requests.append(request)
                return sync_stream(response({**DECISION,
                    'evidence': {'fields': ['profile.confirmed'], 'utterance': ''}}))

            client.responses.create.side_effect = create
            result = GraphRuntime(GraphCompletionTests().value(),
                completion_evaluator=LocalModelProvider(CONFIG).completion).route({
                    'profile': {'confirmed': True}, 'recent_turns': ['同意'], '__private': 'hidden'})
            self.assertEqual(result.status, 'completed')
            self.assertTrue(result.completion_checks[0]['accepted'])
            schema = requests[0]['text']['format']['schema']['properties']['evidence']
            allowed = schema['properties']['fields']['items'].get('enum', [])
            self.assertIn('profile.confirmed', allowed)
            self.assertIn('recent_turns', allowed)
            self.assertNotIn('recent_turns.0', allowed)
            self.assertNotIn('__private', allowed)

    def test_request_uses_local_connection_no_tools_and_reports_actual_usage(self):
        with patch('loomrise.model_provider.OpenAI') as sdk:
            sdk.return_value.__enter__.return_value.responses.create.side_effect = lambda **kwargs: sync_stream(response(DECISION))
            provider = LocalModelProvider(CONFIG, max_calls=1)
            value = provider.completion({'criterion': 'confirmed'}, {'verified': True})
            arguments = sdk.return_value.__enter__.return_value.responses.create.call_args.kwargs
            self.assertEqual(arguments['model'], CONFIG['model'])
            self.assertEqual(arguments['tools'], [])
            self.assertFalse(arguments['store'])
            self.assertTrue(arguments['text']['format']['strict'])
            self.assertNotIn(CONFIG['key'], json.dumps(arguments))
            self.assertEqual(value['model_evidence']['usage']['total_tokens'], 30)
            self.assertEqual(value['model_evidence']['response_id'], 'resp-test')
            with self.assertRaisesRegex(ModelProviderError, 'budget'):
                provider.completion({'criterion': 'confirmed'}, {'verified': True})
            self.assertEqual(sdk.call_count, 1)
            provider.for_run().completion({'criterion': 'confirmed'}, {'verified': True})
            self.assertEqual(sdk.call_count, 2)

    def test_failure_incomplete_refusal_and_untrusted_output_never_return_a_decision(self):
        for result in (response(DECISION, status='incomplete'), response(DECISION, output_text=''),
                       response(DECISION, output_text='not json'), response(True),
                       response({**DECISION, 'scores': {'complete': 50, 'incomplete': 0}})):
            with self.subTest(result=result), patch('loomrise.model_provider.OpenAI') as sdk:
                sdk.return_value.__enter__.return_value.responses.create.return_value = sync_stream(result)
                with self.assertRaises(ModelProviderError):
                    LocalModelProvider(CONFIG).completion({}, {})
        with patch('loomrise.model_provider.OpenAI', side_effect=RuntimeError('secret-fixture')):
            with self.assertRaises(ModelProviderError) as caught:
                LocalModelProvider(CONFIG).completion({}, {})
            self.assertNotIn('secret-fixture', str(caught.exception))

    def test_input_budget_rejects_before_opening_a_connection(self):
        with patch('loomrise.model_provider.OpenAI') as sdk:
            with self.assertRaisesRegex(ModelProviderError, 'input_budget'):
                LocalModelProvider(CONFIG).completion({}, {'long': 'x' * 65_000})
            sdk.assert_not_called()


class AsyncProviderTests(unittest.IsolatedAsyncioTestCase):
    def sdk(self, value, **changes):
        sdk = MagicMock()
        stream = MagicMock()
        stream.__aenter__ = AsyncMock(return_value=stream)
        stream.__aexit__ = AsyncMock(return_value=None)
        stream.__aiter__.return_value = [SimpleNamespace(type='response.completed', response=response(value, **changes))]
        client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(return_value=stream)))
        sdk.return_value.__aenter__ = AsyncMock(return_value=client)
        sdk.return_value.__aexit__ = AsyncMock(return_value=None)
        return sdk, client

    async def test_contact_generation_uses_one_strict_tool_free_request_and_public_evidence(self):
        from loomrise.contact_pages import BLOCK_LABELS

        contact = {'schema_version': 'contact-page-v1', 'template_id': 'support',
                   'title': '虚构工坊', 'description': '作品咨询', 'blocks': []}
        provider = LocalModelProvider(CONFIG, max_calls=1)
        self.assertTrue(callable(getattr(provider, 'generate_contact', None)))
        sdk, client = self.sdk(contact)
        with patch('loomrise.model_provider.AsyncOpenAI', sdk):
            result = await provider.generate_contact(brief='虚构工坊提供作品咨询。', template_id='support')
        self.assertEqual(result['contact'], contact)
        self.assertEqual(result['model_evidence']['model'], 'fixed-model')
        self.assertEqual(result['model_evidence']['usage']['total_tokens'], 30)
        self.assertNotIn(CONFIG['key'], json.dumps(result))
        self.assertEqual(client.responses.create.call_count, 1)
        self.assertEqual(sdk.call_args.kwargs['max_retries'], 0)
        request = client.responses.create.call_args.kwargs
        self.assertEqual(request['tools'], [])
        self.assertFalse(request['store'])
        self.assertLessEqual(request['max_output_tokens'], 1800)
        self.assertTrue(request['text']['format']['strict'])
        self.assertNotIn(CONFIG['key'], json.dumps(request))
        supplied = json.loads(request['input'][1]['content'])
        self.assertEqual(set(supplied), {'brief', 'templates'})
        self.assertEqual(supplied['brief'], '虚构工坊提供作品咨询。')
        self.assertEqual([template['id'] for template in supplied['templates']], ['support'])
        schema = request['text']['format']['schema']
        variants = schema['properties']['blocks']['items']['anyOf']
        self.assertEqual({variant['properties']['type']['enum'][0] for variant in variants}, set(BLOCK_LABELS))

        def check_closed(value):
            if isinstance(value, dict):
                if value.get('type') == 'object':
                    self.assertFalse(value['additionalProperties'])
                    self.assertEqual(set(value['required']), set(value['properties']))
                for child in value.values():
                    check_closed(child)
            elif isinstance(value, list):
                for child in value:
                    check_closed(child)

        check_closed(schema)
        self.assertEqual(schema['properties']['template_id']['enum'], ['support'])

    async def test_contact_generation_rejects_untrusted_or_incomplete_structured_output(self):
        contact = {'schema_version': 'contact-page-v1', 'template_id': 'support',
                   'title': '虚构工坊', 'description': '', 'blocks': []}
        provider = LocalModelProvider(CONFIG)
        self.assertTrue(callable(getattr(provider, 'generate_contact', None)))
        for value in ({**contact, 'html': '<script>secret-fixture</script>'},
                      {key: value for key, value in contact.items() if key != 'title'},
                      {**contact, 'template_id': 'profile'},
                      {**contact, 'blocks': [{'id': 'bad', 'type': 'link', 'title': '', 'body': '',
                          'items': [{'label': 'bad', 'href': 'javascript:secret-fixture'}]}]}):
            with self.subTest(value=value):
                sdk, client = self.sdk(value)
                with patch('loomrise.model_provider.AsyncOpenAI', sdk), self.assertRaises(ModelProviderError) as caught:
                    await provider.generate_contact(brief='只用授权素材。', template_id='support')
                self.assertNotIn('secret-fixture', str(caught.exception))
                self.assertEqual(client.responses.create.call_count, 1)

    async def test_answer_retains_verifiable_citations_and_rejects_invented_sources(self):
        source = {'source_id': 's1', 'content_hash': 'hash-1', 'title': '虚构课程', 'text': '咨询课程仅提供资料答疑。'}
        answer = {'text': '这里提供资料答疑。', 'handoff': False,
                  'citations': [{'source_id': 's1', 'content_hash': 'hash-1', 'quote': '仅提供资料答疑'}]}
        sdk, _ = self.sdk(answer)
        with patch('loomrise.model_provider.AsyncOpenAI', sdk):
            result = await LocalModelProvider(CONFIG).answer(text='咨询什么', persona={}, sources=[source], history=[])
            self.assertEqual(result['citations'], answer['citations'])
            self.assertEqual(result['provider_response_id'], 'resp-test')
        for citation in ({'source_id': 'other', 'content_hash': 'hash-1', 'quote': '仅提供资料答疑'},
                         {'source_id': 's1', 'content_hash': 'old', 'quote': '仅提供资料答疑'},
                         {'source_id': 's1', 'content_hash': 'hash-1', 'quote': '保证退款'}):
            sdk, _ = self.sdk({**answer, 'citations': [citation]})
            with patch('loomrise.model_provider.AsyncOpenAI', sdk), self.assertRaisesRegex(ModelProviderError, 'citation'):
                await LocalModelProvider(CONFIG).answer(text='咨询什么', persona={}, sources=[source], history=[])

    async def test_assistance_uses_one_bounded_strict_tool_free_request_and_public_evidence(self):
        source = {'source_id': 's1', 'content_hash': 'hash-1', 'title': '虚构课程', 'text': '咨询课程仅提供资料答疑。'}
        value = {'summary': '访客询问课程咨询范围。', 'reply': '这里提供资料答疑。',
                 'citations': [{'source_id': 's1', 'content_hash': 'hash-1', 'quote': '仅提供资料答疑'}]}
        history = [{'role': 'user', 'text': '可以咨询什么？'}]
        sdk, client = self.sdk(value)
        with patch('loomrise.model_provider.AsyncOpenAI', sdk):
            result = await LocalModelProvider(CONFIG).assist(persona={'name': '虚构顾问'}, sources=[source], history=history)
        self.assertEqual({key: result[key] for key in value}, value)
        self.assertEqual(result['model_evidence']['model'], CONFIG['model'])
        self.assertEqual(result['model_evidence']['response_id'], 'resp-test')
        self.assertEqual(result['model_evidence']['usage']['total_tokens'], 30)
        self.assertEqual(client.responses.create.call_count, 1)
        self.assertEqual(sdk.call_args.kwargs['max_retries'], 0)
        request = client.responses.create.call_args.kwargs
        self.assertEqual(request['tools'], [])
        self.assertFalse(request['store'])
        self.assertLessEqual(request['max_output_tokens'], 1800)
        self.assertTrue(request['text']['format']['strict'])
        self.assertEqual(request['text']['format']['name'], 'inbox_assistance')
        supplied = json.loads(request['input'][1]['content'])
        self.assertEqual(supplied, {'persona': {'name': '虚构顾问'}, 'sources': [source], 'history': history})
        schema = request['text']['format']['schema']
        self.assertEqual(set(schema['properties']), {'summary', 'reply', 'citations'})
        self.assertEqual(set(schema['required']), set(schema['properties']))
        self.assertFalse(schema['additionalProperties'])
        self.assertGreater(schema['properties']['summary']['maxLength'], 0)
        self.assertGreater(schema['properties']['reply']['maxLength'], 0)
        citations = schema['properties']['citations']
        self.assertGreaterEqual(citations['minItems'], 1)
        self.assertLessEqual(citations['maxItems'], 16)
        self.assertEqual(set(citations['items']['properties']), {'source_id', 'content_hash', 'quote'})
        self.assertEqual(set(citations['items']['required']), set(citations['items']['properties']))
        self.assertFalse(citations['items']['additionalProperties'])
        self.assertNotIn(CONFIG['key'], json.dumps(request))
        self.assertNotIn(CONFIG['key'], json.dumps(result))

    async def test_assistance_rejects_malformed_shapes_and_unverifiable_citations(self):
        source = {'source_id': 's1', 'content_hash': 'hash-1', 'title': '虚构课程', 'text': '咨询课程仅提供资料答疑。'}
        citation = {'source_id': 's1', 'content_hash': 'hash-1', 'quote': '仅提供资料答疑'}
        value = {'summary': '访客询问课程范围。', 'reply': '这里提供资料答疑。', 'citations': [citation]}
        invalid_values = [
            {**value, 'html': '<script>secret-fixture</script>'},
            {key: item for key, item in value.items() if key != 'summary'},
            {**value, 'summary': None}, {**value, 'summary': '  '},
            {**value, 'summary': 'x' * 6001}, {**value, 'summary': 'bad\x00summary'},
            {**value, 'reply': False}, {**value, 'reply': ''}, {**value, 'reply': 'x' * 16_001},
            {**value, 'citations': None}, {**value, 'citations': []}, {**value, 'citations': [citation] * 17},
            {**value, 'model_evidence': {'model': 'forged'}},
        ]
        invalid_values.extend({**value, 'citations': [bad]} for bad in (
            None, {**citation, 'source_id': 'other'}, {**citation, 'source_id': []},
            {**citation, 'content_hash': 'old'}, {**citation, 'quote': '保证退款'},
            {**citation, 'quote': ''}, {**citation, 'quote': False},
            {**citation, 'extra': 'secret-fixture'},
        ))
        for invalid in invalid_values:
            with self.subTest(fields=list(invalid), citations=invalid.get('citations')):
                sdk, client = self.sdk(invalid)
                with patch('loomrise.model_provider.AsyncOpenAI', sdk), self.assertRaisesRegex(
                        ModelProviderError, '^invalid_model_assistance$') as caught:
                    await LocalModelProvider(CONFIG).assist(persona={}, sources=[source], history=[])
                self.assertNotIn(CONFIG['key'], str(caught.exception))
                self.assertEqual(client.responses.create.call_count, 1)

    async def test_assistance_rejects_a_response_from_a_different_model(self):
        source = {'source_id': 's1', 'content_hash': 'hash-1', 'title': '虚构课程', 'text': '仅提供资料答疑。'}
        value = {'summary': '咨询范围。', 'reply': '仅提供资料答疑。',
                 'citations': [{'source_id': 's1', 'content_hash': 'hash-1', 'quote': '仅提供资料答疑。'}]}
        sdk, client = self.sdk(value, model='unexpected-model')
        with patch('loomrise.model_provider.AsyncOpenAI', sdk), self.assertRaisesRegex(
                ModelProviderError, '^invalid_model_assistance$'):
            await LocalModelProvider(CONFIG).assist(persona={}, sources=[source], history=[])
        self.assertEqual(client.responses.create.call_count, 1)

    async def test_cancelled_assistance_is_not_retried_or_converted_to_success(self):
        sdk, client = self.sdk({})
        client.responses.create.side_effect = asyncio.CancelledError()
        with patch('loomrise.model_provider.AsyncOpenAI', sdk), self.assertRaises(asyncio.CancelledError):
            await LocalModelProvider(CONFIG).assist(persona={}, sources=[], history=[])
        self.assertEqual(client.responses.create.call_count, 1)

    async def test_recall_selects_only_supplied_units_and_empty_pool_makes_no_call(self):
        sdk, client = self.sdk({'unit_ids': ['u1']})
        with patch('loomrise.model_provider.AsyncOpenAI', sdk):
            provider = LocalModelProvider(CONFIG)
            self.assertEqual(await provider.recall([], {'input': 'question'}), [])
            sdk.assert_not_called()
            self.assertEqual(await provider.recall([{'unit_id': 'u1'}], {'input': 'question'}), ['u1'])
            self.assertEqual(client.responses.create.call_count, 1)
        sdk, _ = self.sdk({'unit_ids': ['unknown']})
        with patch('loomrise.model_provider.AsyncOpenAI', sdk), self.assertRaisesRegex(ModelProviderError, 'recall'):
            await LocalModelProvider(CONFIG).recall([{'unit_id': 'u1'}], {})

    async def test_cancelled_answer_is_not_retried_or_converted_to_success(self):
        sdk, client = self.sdk({})
        client.responses.create.side_effect = asyncio.CancelledError()
        with patch('loomrise.model_provider.AsyncOpenAI', sdk), self.assertRaises(asyncio.CancelledError):
            await LocalModelProvider(CONFIG).answer(text='question', persona={}, sources=[], history=[])
        self.assertEqual(client.responses.create.call_count, 1)
