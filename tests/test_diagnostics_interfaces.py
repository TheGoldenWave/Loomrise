"""Same diagnosis permission across application, CLI, HTTP and minimal MCP."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer
from mcp.shared.memory import create_connected_server_and_client_session

from loomrise.adapters.mcp import DIAGNOSIS_SKILL_URI, create_diagnostics_mcp_server
from loomrise.config_cli import main
from loomrise.config_http import create_configuration_http_app
from loomrise.configuration import ConfigurationApplication, ConfigurationPrincipal, ConfigurationService
from loomrise.contracts import Channel, RequestState, Run, ServiceRequest
from loomrise.diagnostics import DiagnosticsService, REPORT_SCHEMA_VERSION
from loomrise.durable_store import SqliteStore
from tests.test_config_http import valid_config


class DiagnosisInterfaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / 'diagnostics.db'
        self.principal_path = self.root / 'principal.json'
        self.owner = ConfigurationPrincipal('tenant-a', 'owner-a', 'owner', ('expert-a',))
        self.recipient = ConfigurationPrincipal('tenant-a', 'diagnostician', 'external_agent', ('expert-a',))
        self._principal_file(self.recipient)
        self.store = SqliteStore(str(self.database))
        self.addCleanup(self.store.close)
        self.configuration = ConfigurationService(self.store)
        self.configuration.register_stable_version(tenant_id='tenant-a', agent_id='expert-a',
                                                   version_id='v1', config=valid_config())
        request = ServiceRequest('request-1', 'tenant-a', 'v1', Channel.TEXT, RequestState.RUNNING)
        run = Run('run-1', request.request_id, 'tenant-a', 'v1', snapshot={'agent_id': 'expert-a'})
        self.store.begin_run(request, run, [])
        self.app = ConfigurationApplication(self.configuration)
        self.permission = DiagnosticsService(self.store).issue(principal=self.owner, agent_id='expert-a',
            recipient_actor_id=self.recipient.actor_id, run_ids=['run-1'])['permission_id']

    def _principal_file(self, principal):
        self.principal_path.write_text(json.dumps({
            'tenant_id': principal.tenant_id, 'actor_id': principal.actor_id,
            'role': principal.role, 'agent_ids': list(principal.agent_ids),
        }), encoding='utf-8')
        os.chmod(self.principal_path, 0o600)

    def _call(self, action, **payload):
        return self.app.execute(principal=self.recipient, action=action,
                                payload={'agent_id': 'expert-a', **payload})

    async def test_cli_mcp_and_http_reuse_exact_snapshot_and_revoke(self):
        evidence = self._call('diagnostics.evidence', permission_id=self.permission)
        self.assertTrue(evidence['ok'], evidence)
        snapshot = evidence['result']
        output = io.StringIO()
        status = main(['diagnostics', 'evidence', '--agent-id', 'expert-a',
                       '--permission-id', self.permission, '--json'],
                      principal_path=self.principal_path, database_path=self.database, stdout=output)
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())['result'], snapshot)

        server = create_diagnostics_mcp_server(self.app, principal=self.recipient)
        async with create_connected_server_and_client_session(server) as client:
            tools = (await client.list_tools()).tools
            self.assertEqual({tool.name for tool in tools}, {
                'loomrise_diagnosis_evidence', 'loomrise_diagnosis_report_submit', 'loomrise_diagnosis_report_read'})
            for tool in tools:
                self.assertFalse({'tenant_id', 'role', 'actor_id'} & tool.inputSchema['properties'].keys())
            resource = await client.read_resource(DIAGNOSIS_SKILL_URI)
            self.assertEqual(resource.contents[0].text,
                (Path(__file__).resolve().parents[1] / 'skills/loomrise-diagnose/SKILL.md').read_text(encoding='utf-8'))
            result = await client.call_tool('loomrise_diagnosis_evidence',
                {'agent_id': 'expert-a', 'permission_id': self.permission})
            self.assertEqual(result.structuredContent['result'], snapshot)

            http_app = create_configuration_http_app(principal_path=self.principal_path,
                database_path=self.database, reception_provider=None)
            http = TestClient(TestServer(http_app))
            await http.start_server()
            try:
                reply = await http.post('/api/configuration', json={'action': 'diagnostics.evidence',
                    'payload': {'agent_id': 'expert-a', 'permission_id': self.permission}})
                self.assertEqual(reply.status, 200)
                self.assertEqual((await reply.json())['result'], snapshot)
                DiagnosticsService(self.store).revoke(principal=self.owner, agent_id='expert-a',
                                                      permission_id=self.permission)
                reply = await http.post('/api/configuration', json={'action': 'diagnostics.evidence',
                    'payload': {'agent_id': 'expert-a', 'permission_id': self.permission}})
                self.assertEqual(reply.status, 403)
                rejected = await client.call_tool('loomrise_diagnosis_evidence',
                    {'agent_id': 'expert-a', 'permission_id': self.permission})
                self.assertEqual(rejected.structuredContent['error']['code'], 'forbidden')
            finally:
                await http.close()

    async def test_report_submission_has_no_business_dml_and_cannot_expand_authority(self):
        snapshot = self._call('diagnostics.evidence', permission_id=self.permission)['result']
        report = {
            'schema_version': REPORT_SCHEMA_VERSION, 'status': 'proposal', 'findings': [],
            'insufficient_categories': ['knowledge', 'routing', 'loading', 'policy', 'tool', 'rule'],
            'limitations': snapshot['limitations'],
        }
        statements = []
        self.store._conn.set_trace_callback(statements.append)
        try:
            saved = self._call('diagnostics.report.submit', permission_id=self.permission,
                snapshot_id=snapshot['snapshot_id'], input_hash=snapshot['snapshot_hash'], report=report)
        finally:
            self.store._conn.set_trace_callback(None)
        self.assertTrue(saved['ok'], saved)
        writes = [sql for sql in statements if sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))]
        self.assertTrue(writes)
        self.assertTrue(all('diagnosis_' in sql for sql in writes), writes)
        for action, payload in [
            ('run.diagnostics', {'run_id': 'run-1'}),
            ('diagnostics.permission.issue', {'recipient_actor_id': 'other', 'run_ids': ['run-1']}),
            ('diagnostics.permission.revoke', {'permission_id': self.permission}),
            ('diagnostics.evidence', {'permission_id': self.permission, 'reviewed': True}),
        ]:
            self.assertFalse(self._call(action, **payload)['ok'])

    async def test_external_agent_diagnostics_whitelist_is_explicit(self):
        # 允许：证据读取、提案提交/读取。
        self.assertTrue(self._call('diagnostics.evidence', permission_id=self.permission)['ok'])
        # 拒绝：许可签发/撤销（owner 专属）与治理作业（仅 CLI）。
        for action in ('diagnostics.permission.issue', 'diagnostics.permission.revoke',
                       'diagnostics.job.create', 'diagnostics.job.run',
                       'diagnostics.job.read', 'diagnostics.job.cancel'):
            with self.subTest(action=action):
                rejected = self._call(action, permission_id=self.permission,
                                      recipient_actor_id='other', run_ids=['run-1'],
                                      job_id='job-x', idempotency_key='k')
                self.assertFalse(rejected['ok'])
                self.assertEqual(rejected['error']['code'], 'forbidden')

    async def test_governance_jobs_are_cli_only_not_exposed_via_http_or_mcp(self):
        # 应用服务合同对所有角色都显式拒绝作业动作，且不落任何作业行。
        for principal in (self.recipient, self.owner):
            with self.subTest(role=principal.role):
                rejected = self.app.execute(
                    principal=principal, action='diagnostics.job.create',
                    payload={'agent_id': 'expert-a', 'permission_id': self.permission,
                             'idempotency_key': 'http-job', 'provider': 'agentscope'})
                self.assertFalse(rejected['ok'])
                self.assertEqual(rejected['error']['code'], 'forbidden')
        self.assertEqual(self.store._conn.execute(
            "SELECT COUNT(*) FROM governance_jobs").fetchone()[0], 0)

        http_app = create_configuration_http_app(principal_path=self.principal_path,
            database_path=self.database, reception_provider=None)
        http = TestClient(TestServer(http_app))
        await http.start_server()
        try:
            reply = await http.post('/api/configuration', json={
                'action': 'diagnostics.job.create',
                'payload': {'agent_id': 'expert-a', 'permission_id': self.permission,
                            'idempotency_key': 'http-job', 'provider': 'agentscope'}})
            self.assertEqual(reply.status, 403)
            self.assertEqual((await reply.json())['error']['code'], 'forbidden')
        finally:
            await http.close()

        # 诊断 MCP server 只披露三个受限工具，不含任何作业入口。
        server = create_diagnostics_mcp_server(self.app, principal=self.recipient)
        async with create_connected_server_and_client_session(server) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            self.assertFalse(any('job' in name for name in names), names)
        self.assertEqual(self.store._conn.execute(
            "SELECT COUNT(*) FROM governance_jobs").fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
