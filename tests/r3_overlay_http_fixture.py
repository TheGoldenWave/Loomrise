"""Disposable graph observation fixture; never a publication-Gate bypass in the app."""
import argparse
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile

from aiohttp import web

from loomrise.config_http import create_configuration_http_app
from loomrise.configuration import ConfigurationService
from loomrise.contracts import sha256
from loomrise.durable_store import SqliteStore
from loomrise.service import ExecutionService
from tests.test_graph_service import graph_pack
from tests.test_graph_validation import graph_spec


async def seed(store):
    config = graph_spec()
    pack = graph_pack()
    version = 'r3-overlay-fixture-v1'
    pack.agent_version = replace(pack.agent_version, version_id=version,
        orchestration=config, unit_skill_bindings={'disclosure': 'course_consult_booking'})
    # This fixture imports a graph snapshot to exercise the read-only observer.
    # The public freeze service still rejects unsupported graph publications.
    store.register_stable_config(tenant_id='overlay-test', agent_id='course-demo',
        version_id=version, config=config, content_hash=sha256(json.dumps(config, sort_keys=True)))
    ConfigurationService(store).create_draft_from_stable(
        tenant_id='overlay-test', agent_id='course-demo', base_version_id=version)
    service = ExecutionService(pack, store=store, tenant_id='overlay-test',
        agent_id='course-demo', owner_id='overlay-fixture')
    await service.handle_text('虚构咨询', script=[{'text': '虚构回答'}])
    await service.handle_utterance('虚构咨询', media_session_id='fixture-media', script=[{'text': '虚构回答'}])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8779)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='loomrise-overlay-') as directory:
        root = Path(directory)
        principal = root / 'principal.json'
        principal.write_text(json.dumps({'tenant_id': 'overlay-test', 'actor_id': 'test-owner',
            'role': 'owner', 'agent_ids': ['course-demo']}))
        os.chmod(principal, 0o600)
        database = root / 'fixture.db'
        store = SqliteStore(str(database))
        try:
            asyncio.run(seed(store))
        finally:
            store.close()
        app = create_configuration_http_app(principal_path=principal, database_path=database,
            allowed_origins={'http://127.0.0.1:18765'})
        web.run_app(app, host='127.0.0.1', port=args.port, print=None)


if __name__ == '__main__':
    main()
