"""Disposable approved fixture; replies are deterministic, never a live-model claim."""
import argparse
import json
import os
from pathlib import Path
import tempfile

from aiohttp import web

from loomrise.config_http import create_configuration_http_app
from loomrise.configuration import ConfigurationService
from loomrise.durable_store import SqliteStore
from tests.test_configuration_service import spec


class FixtureProvider:
    model = 'deterministic-browser-fixture'
    async def assist(self, *, persona, sources, history):
        if history and '辅助故障' in history[-1]['text']:
            raise RuntimeError('PRIVATE-ASSISTANCE-FIXTURE-FAILURE')
        return {'summary': '访客咨询体验课。<script>window.__assistanceInjected = true</script>',
            'reply': '体验课价格为 19 元。',
            'citations': [{'source_id': sources[0]['source_id'], 'content_hash': sources[0]['content_hash'],
                           'quote': '体验课价格为 19 元。'}],
            'model_evidence': {'model': self.model, 'response_id': 'fixture-assistance',
                               'usage': {}, 'duration_ms': 0, 'provider': 'fixture'}}

    async def answer(self, *, text, persona, sources, history):
        if '故障' in text:
            raise RuntimeError('synthetic provider failure')
        return {'text': '体验课价格为 19 元。', 'handoff': False,
                'citations': [{'source_id': sources[0]['source_id'], 'content_hash': sources[0]['content_hash'],
                               'quote': '体验课价格为 19 元。'}],
                'model': 'deterministic-browser-fixture', 'provider_response_id': 'fixture-response',
                'usage': {'input_tokens': 0, 'output_tokens': 0}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8788)
    parser.add_argument('--allowed-origin', action='append')
    parser.add_argument('--live-model', action='store_true', help='Use the configured real model with fictional fixture material')
    parser.add_argument('--offline-reception', action='store_true', help='Seed AI reception in offline-only mode')
    args = parser.parse_args()
    if args.live_model:
        from loomrise.model_provider import LocalModelProvider
        provider = LocalModelProvider.from_local_config()
        if provider is None:
            raise RuntimeError('Local model is not configured')
    else:
        provider = FixtureProvider()
    with tempfile.TemporaryDirectory(prefix='loomrise-reception-fixture-') as directory:
        root = Path(directory)
        principal = root / 'principal.json'
        principal.write_text(json.dumps({'tenant_id': 'fixture-tenant', 'actor_id': 'fixture-owner',
                                        'role': 'owner', 'agent_ids': ['course-demo']}), encoding='utf-8')
        os.chmod(principal, 0o600)
        database = root / 'fixture.db'
        store = SqliteStore(str(database))
        service = ConfigurationService(store)
        source = service.create_knowledge_source(tenant_id='fixture-tenant', agent_id='course-demo',
            kind='faq', locator='体验课价格为 19 元。', display_name='虚构课程说明', authorization='owned')
        source = service.ingest_knowledge_source(tenant_id='fixture-tenant', agent_id='course-demo', source_id=source['source_id'])
        config = spec()
        config['widget'] = {'title': '虚构课程接待', 'greeting': '此页面使用真实模型和虚构资料。' if args.live_model else '此页面使用确定性测试答复。'}
        config['ai_reception'] = {'enabled': True, 'mode': 'offline' if args.offline_reception else 'always', 'model_id': provider.model,
            'sources': [{'source_id': source['source_id'], 'content_hash': source['content_hash']}],
            'faq_suggestions': [{'question': '体验课多少钱？', 'source_id': source['source_id'],
                                 'content_hash': source['content_hash']}]}
        service.register_stable_version(tenant_id='fixture-tenant', agent_id='course-demo', version_id='fixture-base', config=config)
        service.create_draft_from_stable(tenant_id='fixture-tenant', agent_id='course-demo', base_version_id='fixture-base')
        candidate = service.freeze_candidate(tenant_id='fixture-tenant', agent_id='course-demo', expected_revision=1, idempotency_key='fixture')
        store.approve_release_candidate(tenant_id='fixture-tenant', agent_id='course-demo', candidate_id=candidate['candidate_id'],
            content_hash=candidate['content_hash'], environment='sandbox', entry_id='widget-entry', version_id='fixture-v1', approved_by='fixture-owner')
        store.publish_sandbox_candidate(tenant_id='fixture-tenant', agent_id='course-demo', candidate_id=candidate['candidate_id'], entry_id='widget-entry', version_id='fixture-v1')
        store.close()
        app = create_configuration_http_app(principal_path=principal, database_path=database,
            reception_provider=provider, allowed_origins=args.allowed_origin)
        web.run_app(app, host='127.0.0.1', port=args.port, handler_cancellation=True)


if __name__ == '__main__':
    main()
