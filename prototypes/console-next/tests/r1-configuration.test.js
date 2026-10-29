import test from 'node:test';
import assert from 'node:assert/strict';
import { createConfigurationClient, createR1ConfigurationWorkspace, ConfigurationApiError } from '../r1-configuration.js';
import { renderR1Configuration } from '../views/r1-configuration.js';

const configuration = () => ({
  persona: { name: '课程客服', goal: '答疑', audience: '访客', greeting: '你好', scope: '授权资料', fallback: '转人工', fields: {} },
  units: [], g0_gates: [], hard_rules: [], task_blueprints: [],
  legacy: { tone: '中性', knowledge: [{ id: 'local-source' }] },
});

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, async json() { return body; } };
}

function harness() {
  const calls = [];
  let draft = { agent_id: 'agent-1', revision: 1, base_version_id: 'v1', config: configuration(), updated_at: 'now' };
  let stable = [{ version_id: 'v1', content_hash: 'hash', created_at: 'then' }];
  let candidates = [];
  let conflict = null;
  let validateIssues = [];
  const client = {
    origin: 'http://127.0.0.1:8766',
    async health() { return { ok: true }; },
    async request(action, payload) {
      calls.push({ action, payload });
      if (action === 'draft.get') {
        if (!draft) throw new ConfigurationApiError({ status: 404, error: { code: 'not_found' } });
        return structuredClone(draft);
      }
      if (action === 'stable.list') return { items: structuredClone(stable) };
      if (action === 'candidate.list') return { items: structuredClone(candidates) };
      if (action === 'stable.get') return { ...stable[0], config: configuration() };
      if (action === 'draft.create') return structuredClone(draft);
      if (action === 'draft.save') {
        if (conflict) throw new ConfigurationApiError({ status: 409, error: { code: 'revision_conflict', current: structuredClone(conflict) } });
        const before = draft.config;
        draft = { ...draft, revision: draft.revision + 1, config: structuredClone(payload.config) };
        return { ...structuredClone(draft), diff: [{ path: '$.persona.goal', before: before.persona.goal, after: draft.config.persona.goal }] };
      }
      if (action === 'draft.validate') return { revision: draft.revision, valid: !validateIssues.length, issues: structuredClone(validateIssues) };
      if (action === 'candidate.freeze') {
        const candidate = { candidate_id: 'cp_1', source_revision: draft.revision, config: structuredClone(draft.config), diff: [{ path: '$.persona.goal', before: '旧目标', after: draft.config.persona.goal }], status: 'frozen' };
        candidates.push(candidate);
        return structuredClone(candidate);
      }
      if (action === 'candidate.get') return structuredClone(candidates[0]);
      if (action === 'release.checklist') return {
        candidate_id: payload.candidate_id,
        checks: [
          { key: 'candidate_frozen', label: '候选已冻结', status: 'passed', detail: '候选状态为 frozen' },
          { key: 'authorization', label: '授权检查', status: 'pending', detail: '授权服务尚未提供可验证证据' },
        ],
        progress: { passed: 1, failed: 0, pending: 1, total: 2 },
        ready: false,
        publish_enabled: false,
      };
      throw new Error(`unhandled action ${action}`);
    },
  };
  return { client, calls, setDraft(value) { draft = value; }, setConflict(value) { conflict = value; }, setValidationIssues(value) { validateIssues = value; }, setCandidates(value) { candidates = value; } };
}

test('configuration client checks API schema and rejects failed envelopes', async () => {
  const client = createConfigurationClient({ fetchImpl: async () => response({ schema_version: 'config-api-v1', ok: false, error: { code: 'revision_conflict', current: { revision: 8 } } }, 409) });
  await assert.rejects(client.request('draft.get', { agent_id: 'agent-1' }), error => error instanceof ConfigurationApiError && error.code === 'revision_conflict' && error.details.current.revision === 8);
  const mismatch = createConfigurationClient({ fetchImpl: async () => response({ schema_version: 'future', ok: true, result: {} }) });
  await assert.rejects(mismatch.request('draft.get', { agent_id: 'agent-1' }), error => error.code === 'schema_mismatch');
});

test('configuration client reports a recoverable service error when offline', async () => {
  const client = createConfigurationClient({ fetchImpl: async () => { throw new TypeError('Failed to fetch'); } });
  await assert.rejects(client.health(), error => error instanceof ConfigurationApiError
    && error.code === 'service_unavailable'
    && error.message === '无法连接本机配置服务，请确认服务已启动后重试。');
  await assert.rejects(client.request('draft.get', { agent_id: 'agent-1' }), error => error instanceof ConfigurationApiError
    && error.code === 'service_unavailable'
    && !error.message.includes('Failed to fetch'));
});

test('loads shared draft and keeps unknown legacy fields intact through save', async () => {
  const h = harness();
  const workspace = createR1ConfigurationWorkspace({ client: h.client });
  await workspace.load('agent-1');
  assert.equal(workspace.state.status, 'ready');
  assert.equal(workspace.state.draft.revision, 1);
  workspace.updateField('persona.goal', '更新后的目标');
  assert.equal(workspace.state.editorConfig.legacy.tone, '中性');
  await workspace.save(workspace.state.editorConfig);
  assert.equal(workspace.state.draft.revision, 2);
  assert.equal(workspace.state.lastDiff[0].path, '$.persona.goal');
  assert.deepEqual(workspace.state.draft.config.legacy, { tone: '中性', knowledge: [{ id: 'local-source' }] });
  assert.equal(h.calls.at(-1).payload.expected_revision, 1);
});

test('revision conflict retains attempted changes until explicit reload', async () => {
  const h = harness();
  const workspace = createR1ConfigurationWorkspace({ client: h.client });
  await workspace.load('agent-1');
  workspace.updateField('persona.goal', '本地输入');
  h.setConflict({ ...workspace.state.draft, revision: 2, config: { ...configuration(), persona: { ...configuration().persona, goal: '另一入口' } } });
  await workspace.save(workspace.state.editorConfig);
  assert.equal(workspace.state.status, 'conflict');
  assert.equal(workspace.state.conflict.attemptedConfig.persona.goal, '本地输入');
  workspace.reloadConflict();
  assert.equal(workspace.state.editorConfig.persona.goal, '另一入口');
  assert.equal(workspace.state.conflict, null);
});

test('validation errors and frozen candidate history remain server-derived and read-only', async () => {
  const h = harness();
  const workspace = createR1ConfigurationWorkspace({ client: h.client });
  await workspace.load('agent-1');
  h.setValidationIssues([{ path: '$.units[0].body', code: 'body_not_empty', message: 'R1 body must be empty' }]);
  await workspace.validate();
  assert.equal(workspace.state.validation.valid, false);
  assert.equal(workspace.state.validation.issues[0].path, '$.units[0].body');
  h.setValidationIssues([]);
  await workspace.freezeCandidate();
  assert.equal(workspace.state.selectedCandidate.candidate_id, 'cp_1');
  assert.equal(workspace.state.releaseChecklist.progress.pending, 1);
  assert.equal(workspace.state.releaseChecklist.publish_enabled, false);
  assert.equal(workspace.state.activeTab, 'history');
  assert.equal(workspace.state.candidates.length, 1);
  const html = renderR1Configuration({ r1Configuration: workspace, agent: { name: '测试专家' } });
  assert.match(html, /发布前检查/);
  assert.match(html, /授权检查/);
  assert.match(html, /待验证/);
  assert.match(html, /当前不能批准或发布/);
  await workspace.openCandidate('cp_1');
  const before = structuredClone(workspace.state.selectedCandidate.config);
  workspace.updateField('persona.goal', '不能写');
  assert.deepEqual(workspace.state.selectedCandidate.config, before);
  await workspace.openStable('v1');
  assert.equal(workspace.state.readOnlySnapshot.version_id, 'v1');
  assert.equal(workspace.state.releaseChecklist, null);
});

test('syntax errors in JSON blocks saving until repaired', async () => {
  const h = harness();
  const workspace = createR1ConfigurationWorkspace({ client: h.client });
  await workspace.load('agent-1');
  workspace.updateJsonField('units', '{');
  assert.equal(Object.hasOwn(workspace.state.jsonErrors, 'units'), true);
  const before = h.calls.length;
  await workspace.save(workspace.state.editorConfig);
  assert.equal(h.calls.length, before);
  workspace.updateJsonField('units', '[]');
  assert.equal(Object.hasOwn(workspace.state.jsonErrors, 'units'), false);
});
