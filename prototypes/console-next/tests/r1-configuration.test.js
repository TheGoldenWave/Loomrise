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
      if (action === 'advisory.dismiss') return {
        source_revision: payload.expected_revision,
        advisory_key: `closed-set:${JSON.stringify(payload.layer_path)}`,
        layer_path: structuredClone(payload.layer_path), closed_set_size: 7,
        actor_id: 'operator-1', created_at: '2026-11-03T00:00:00Z',
      };
      if (action === 'run.overlay') return {
        version_id: payload.version_id, time_window: { from: payload.from, to: payload.to },
        channel: payload.channel || null, sample_count: 1, low_sample: true,
        nodes: { 'welcome.from_start': { entered: 1, dwell_ms: 2000, percentage: null } },
        edges: { 'to-booking': { traversed: 1, percentage: null } },
        terminations: { completed: 1 }, termination_targets: {}, channels: { text: 1 },
        average_duration_ms: 2000,
      };
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

test('contact requests use the customer endpoint and its own schema envelope', async () => {
  let sent;
  const client = createConfigurationClient({ baseUrl: 'http://127.0.0.1:8778', fetchImpl: async (url, options) => {
    sent = { url, body: JSON.parse(options.body) };
    return response({ schema_version: 'customer-service-v1', ok: true, result: { revision: 2 } });
  } });
  assert.deepEqual(await client.customerRequest('contact.preview', { agent_id: 'a' }), { revision: 2 });
  assert.equal(sent.url, 'http://127.0.0.1:8778/api/customer-service');
  assert.equal(sent.body.action, 'contact.preview');
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

test('loads a server-aggregated run overlay with its version and time window', async () => {
  const h = harness();
  const workspace = createR1ConfigurationWorkspace({ client: h.client });
  await workspace.load('agent-1');
  await workspace.openStable('v1');
  const overlay = await workspace.loadRunOverlay({
    versionId: 'v1', from: '2026-10-30T00:00:00+00:00', to: '2026-11-01T00:00:00+00:00',
  });
  assert.equal(overlay.sample_count, 1);
  assert.equal(workspace.state.runOverlay.nodes['welcome.from_start'].percentage, null);
  assert.deepEqual(h.calls.at(-1), {
    action: 'run.overlay',
    payload: {
      agent_id: 'agent-1', version_id: 'v1',
      from: '2026-10-30T00:00:00+00:00', to: '2026-11-01T00:00:00+00:00',
    },
  });
});

test('a late run overlay cannot replace data after switching expert or returning to the draft', async () => {
  const h = harness();
  const original = h.client.request;
  let resolveOverlay;
  h.client.request = async (action, payload) => action === 'run.overlay'
    ? new Promise(resolve => { resolveOverlay = resolve; }) : original(action, payload);
  const workspace = createR1ConfigurationWorkspace({ client: h.client });
  await workspace.load('agent-1');
  await workspace.openStable('v1');
  const pending = workspace.loadRunOverlay({ versionId: 'v1', from: '2026-10-30T00:00:00Z', to: '2026-11-01T00:00:00Z' });
  workspace.closeSnapshot();
  resolveOverlay({ version_id: 'v1', nodes: {} });
  await pending;
  assert.equal(workspace.state.runOverlay, null);
  await workspace.openStable('v1');
  const switching = workspace.loadRunOverlay({ versionId: 'v1', from: '2026-10-30T00:00:00Z', to: '2026-11-01T00:00:00Z' });
  await workspace.load('agent-2');
  resolveOverlay({ version_id: 'v1', nodes: {} });
  await switching;
  assert.equal(workspace.state.runOverlay, null);
  assert.equal(workspace.state.status, 'ready');
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

test('object diff labels its baseline, escapes content and excludes unsaved changes', async () => {
  const h = harness();
  const workspace = createR1ConfigurationWorkspace({ client: h.client });
  await workspace.load('agent-1');
  workspace.state.draft.object_diff = { changes: [
    { object_type: 'edge_order', object_id: '$', operation: 'priority', path: '$.orchestration.edges', before: ['b', 'a'], after: ['a', 'b'] },
    { object_type: 'entry_port', object_id: '<img src=x>', operation: 'changed', path: '$.units[unit_id="a"].entry_ports[port="in"].requires', before: null, after: false },
  ], diagnostics: [{ path: '$.units', message: '标识缺失或重复' }] };
  const context = { r1Configuration: workspace };
  let html = renderR1Configuration(context);
  assert.match(html, /边优先级.*优先级变化/);
  assert.match(html, /最近一次保存：r0 → r1/);
  assert.match(html, /<pre>null<\/pre>/);
  assert.match(html, /<pre>false<\/pre>/);
  assert.match(html, /&lt;img src=x&gt;/);
  assert.ok(!html.includes('<img src=x>'));
  workspace.updateField('persona.goal', '尚未保存');
  html = renderR1Configuration(context);
  assert.match(html, /另有未保存修改，不含在本回执中/);
  workspace.state.selectedCandidate = { candidate_id: 'cp-review', config: configuration(), object_diff: workspace.state.draft.object_diff };
  html = renderR1Configuration(context);
  assert.match(html, /冻结候选与其基准稳定版本/);
  assert.ok(!html.includes('最近一次保存：'));
  workspace.state.selectedCandidate = null;
  await workspace.load('agent-1');
  assert.ok(!renderR1Configuration(context).includes('对象级差异'));
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
  workspace.state.selectedCandidate.review_summary = [{ advisory_key: 'closed-set:[]', layer_path: [],
    closed_set_size: 7, actor_id: 'operator-1', source_revision: 1, created_at: '2026-11-03T00:00:00Z' }];
  const html = renderR1Configuration({ r1Configuration: workspace, agent: { name: '测试专家' } });
  assert.match(html, /发布前检查/);
  assert.match(html, /授权检查/);
  assert.match(html, /待验证/);
  assert.match(html, /当前不能批准或发布/);
  assert.match(html, /画布提示忽略记录/);
  assert.match(html, /operator-1/);
  assert.match(html, /2026-11-03T00:00:00Z/);
  await workspace.openCandidate('cp_1');
  const before = structuredClone(workspace.state.selectedCandidate.config);
  workspace.updateField('persona.goal', '不能写');
  assert.deepEqual(workspace.state.selectedCandidate.config, before);
  await workspace.openStable('v1');
  assert.equal(workspace.state.readOnlySnapshot.version_id, 'v1');
  assert.equal(workspace.state.releaseChecklist, null);
});

test('closed-set dismissal uses the trusted draft revision and leaves unsaved config untouched', async () => {
  const h = harness();
  const workspace = createR1ConfigurationWorkspace({ client: h.client });
  await workspace.load('agent-1');

  assert.equal(await workspace.dismissAdvisory([]), true);
  const call = h.calls.find(item => item.action === 'advisory.dismiss');
  assert.deepEqual(call.payload, { agent_id: 'agent-1', expected_revision: 1, layer_path: [] });
  assert.equal(workspace.state.draft.advisory_dismissals[0].actor_id, 'operator-1');

  workspace.updateField('persona.goal', '本地未保存修改');
  assert.equal(workspace.canDismissAdvisory([]), false);
  assert.equal(await workspace.dismissAdvisory([]), false);
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
