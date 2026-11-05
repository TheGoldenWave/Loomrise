"""Run a disposable loopback configuration service for browser acceptance."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import nullcontext
import json
import os
from pathlib import Path
import tempfile

from aiohttp import web

from loomrise.config_http import create_configuration_http_app
from loomrise.configuration import ConfigurationService
from loomrise.contact_pages import contact_schema, validate_contact
from loomrise.durable_store import SqliteStore


class FixtureContactGenerator:
    """Deterministic browser fixture; never loads or calls a remote model."""

    def for_run(self):
        return FixtureContactGenerator()

    async def generate_contact(self, *, brief, template_id=None):
        await asyncio.sleep(0.7)
        if 'FIXTURE-FAIL' in brief:
            raise RuntimeError('PRIVATE-PROVIDER-DETAIL-NOT-FOR-UI')
        return {
            'contact': {
                'schema_version': 'contact-page-v1', 'template_id': template_id or 'support',
                'title': '虚构课程联系候选', 'description': '请人工核对后采用。',
                'blocks': [
                    {'id': 'generated-intro', 'type': 'text', 'title': '课程介绍',
                     'body': '<script>window.__contactInjected = true</script>', 'items': []},
                    {'id': 'generated-faq', 'type': 'faq', 'title': '常见问题', 'body': '',
                     'items': [{'question': '如何联系？', 'answer': '请联系人工客服核对课程。'}]},
                    {'id': 'generated-contact', 'type': 'contact', 'title': '联系信息', 'body': '',
                     'items': [{'label': '邮箱', 'value': 'hello@example.test'}]},
                ],
            },
            'model_evidence': {'model': 'deterministic-browser-fixture', 'response_id': 'fixture-only',
                               'usage': {}, 'duration_ms': 700, 'provider': 'fixture'},
        }


def contact_matrix() -> dict:
    """Original fictional values for the approved rendering matrix, not a release Gate."""
    blocks = []
    for kind in contact_schema()['block_types']:
        name = kind['type']
        values = {field: f'{name}-{field}-fixture' for field in kind['item_fields']}
        for field in ('href', 'src', 'alt', 'media_type'):
            if field not in values:
                continue
            values[field] = {
                'href': 'mailto:help@example.test' if name == 'contact' else f'https://example.test/{name}',
                'src': 'https://example.test/course-preview.png' if name == 'media' else f'https://example.test/{name}-fixture.png',
                'alt': '虚构课程示意图片' if name == 'media' else f'虚构{kind["label"]}图片',
                'media_type': 'image',
            }[field]
        if name == 'faq':
            values.update(question='如何报名？', answer='请联系人工客服。')
        items = [values] if values else []
        if name == 'media':
            items.extend([{**values, 'src': 'https://example.test/course-preview.webm',
                           'alt': '虚构课程预览视频', 'media_type': 'video'},
                          {**values, 'src': 'https://example.test/course-preview.wav',
                           'alt': '虚构课程预览音频', 'media_type': 'audio'}])
        blocks.append({'id': f'matrix-{name}', 'type': name, 'title': f'{kind["label"]}矩阵标题',
                       'body': f'{name}-block-body-fixture', 'items': items})
    return validate_contact({'title': '已批准 21 类矩阵页面', 'description': '全部使用本机虚构 fixture。', 'blocks': blocks})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--allowed-origin", action="append")
    parser.add_argument('--seed-contact-release', action='store_true', help='Seed an approved fixture release for Contact Page browser tests only')
    parser.add_argument('--seed-widget-release', action='store_true', help='Seed an approved Widget with a required visitor form for browser tests only')
    parser.add_argument('--contact-generation-fixture', action='store_true', help='Inject deterministic Contact generation; no remote model calls')
    args = parser.parse_args()

    if args.data_dir:
        args.data_dir.mkdir(parents=True, exist_ok=True)
        context = nullcontext(str(args.data_dir))
    else:
        context = tempfile.TemporaryDirectory(prefix="loomrise-r1-config-")
    with context as directory:
        root = Path(directory)
        principal_path = root / "principal.json"
        principal_path.write_text(json.dumps({
            "tenant_id": "r1-browser-test-tenant",
            "actor_id": "r1-browser-test-owner",
            "role": "owner",
            "agent_ids": ["course-demo"],
        }), encoding="utf-8")
        os.chmod(principal_path, 0o600)

        database_path = root / "configuration.db"
        store = SqliteStore(str(database_path))
        service = ConfigurationService(store)
        config = {
            "persona": {
                "name": "课程咨询客服",
                "goal": "依据授权资料回答课程问题。",
                "audience": "网站访客",
                "greeting": "你好，有什么可以帮你？",
                "scope": "仅回答有效授权资料中的信息。",
                "fallback": "资料不足时转交人工。",
                "fields": {},
                "entry_unit_ids": [],
            },
            "units": [],
            "g0_gates": [],
            "hard_rules": [],
            "task_blueprints": [],
            "legacy_local_fields": {
                "tone": "中性",
                "knowledge_source_count": 3,
            },
        }
        if args.seed_contact_release:
            config['contact'] = {'title': '已批准测试页面', 'description': '虚构资料，仅用于本机测试。',
                                 'blocks': [{'id': 'chat', 'type': 'chat', 'title': '客服入口', 'body': ''}]}
        if args.seed_widget_release:
            config['widget'] = {'schema_version': 'widget-v1', 'title': '虚构课程客服', 'greeting': '欢迎咨询虚构课程。',
                'color': '#2250aa', 'language': 'zh-CN', 'timezone': 'Asia/Shanghai', 'hours': [],
                'offline_message': '当前不在接待时段，可在此留言。',
                'fields': [
                    {'id': 'visitor_name', 'label': '称呼', 'type': 'text', 'required': True},
                    {'id': 'visitor_email', 'label': '邮箱', 'type': 'email', 'required': False},
                    {'id': 'visitor_phone', 'label': '电话', 'type': 'tel', 'required': False},
                ]}
        service.register_stable_version(
            tenant_id="r1-browser-test-tenant", agent_id="course-demo",
            version_id="r1-fixture-v1", config=config,
        )
        service.create_draft_from_stable(
            tenant_id="r1-browser-test-tenant", agent_id="course-demo",
            base_version_id="r1-fixture-v1",
        )
        if args.seed_contact_release or args.seed_widget_release:
            # Storage-level fixture setup is not evidence that publication checks passed.
            entry_id = 'widget-entry' if args.seed_widget_release else 'contact-entry'
            version_id = 'widget-fixture-v1' if args.seed_widget_release else 'contact-fixture-v1'
            candidate = service.freeze_candidate(tenant_id='r1-browser-test-tenant', agent_id='course-demo',
                                                 expected_revision=1, idempotency_key='contact-fixture')
            store.approve_release_candidate(tenant_id='r1-browser-test-tenant', agent_id='course-demo',
                candidate_id=candidate['candidate_id'], content_hash=candidate['content_hash'], environment='sandbox',
                entry_id=entry_id, version_id=version_id, approved_by='r1-browser-test-owner')
            store.publish_sandbox_candidate(tenant_id='r1-browser-test-tenant', agent_id='course-demo',
                candidate_id=candidate['candidate_id'], entry_id=entry_id, version_id=version_id)
        if args.seed_contact_release:
            matrix = {**config, 'persona': {**config['persona'], 'goal': 'INTERNAL-CONTACT-MATRIX-PROMPT-NOT-PUBLIC'},
                      'contact': contact_matrix()}
            saved = service.save_draft(tenant_id='r1-browser-test-tenant', agent_id='course-demo',
                                       expected_revision=1, config=matrix)
            candidate = service.freeze_candidate(tenant_id='r1-browser-test-tenant', agent_id='course-demo',
                expected_revision=saved['revision'], idempotency_key='contact-matrix-fixture')
            # Explicit fixture approval only; production prechecks remain blocking.
            store.approve_release_candidate(tenant_id='r1-browser-test-tenant', agent_id='course-demo',
                candidate_id=candidate['candidate_id'], content_hash=candidate['content_hash'], environment='sandbox',
                entry_id='contact-matrix-entry', version_id='contact-matrix-fixture-v1', approved_by='r1-browser-test-owner')
            store.publish_sandbox_candidate(tenant_id='r1-browser-test-tenant', agent_id='course-demo',
                candidate_id=candidate['candidate_id'], entry_id='contact-matrix-entry', version_id='contact-matrix-fixture-v1')
            service.save_draft(tenant_id='r1-browser-test-tenant', agent_id='course-demo',
                               expected_revision=saved['revision'], config=config)
        store.close()

        app = create_configuration_http_app(
            principal_path=principal_path, database_path=database_path,
            allowed_origins=args.allowed_origin,
            **({'reception_provider': None, 'contact_generation_provider': FixtureContactGenerator()}
               if args.contact_generation_fixture else {}),
        )
        print(f"R1 fixture data: {root}", flush=True)
        print(f"R1 fixture principal: {principal_path}", flush=True)
        print(f"R1 fixture database: {database_path}", flush=True)
        web.run_app(app, host="127.0.0.1", port=args.port, print=None)


if __name__ == "__main__":
    main()
