import test from 'node:test';
import assert from 'node:assert/strict';
import { createR1ConfigurationWorkspace, ConfigurationApiError } from '../r1-configuration.js';
import { renderR1Configuration } from '../views/r1-configuration.js';

const config = () => ({ persona: { goal: '答疑', fields: {} }, units: [{ unit_id: 'u', version: 1,
  load_mode: 'routed', entry_ports: [{ port: 'in', requires: [] }], exit_ports: [{ port: 'out' }], body: {} }],
  orchestration: { schema_version: 'unit-graph-v1', kind: 'graph', entry: 'n.in',
    nodes: [{ id: 'n', unit_ref: { unit_id: 'u', version: 1 } }],
    edges: [{ id: 'end', from: 'n.out', to: 'end', condition: {} }] } });

function fixture() {
  const calls = [];
  let revision = 1;
  const client = { origin: 'fixture', health: async () => ({}), async request(action, payload) {
    calls.push({ action, payload });
    if (action === 'draft.get') return { revision, config: config() };
    if (action === 'stable.list') return { items: [{ version_id: 'v1' }, { version_id: 'v2' }] };
    if (action === 'candidate.list') return { items: [{ candidate_id: 'c1', status: 'frozen' }] };
    if (action === 'stable.get') return { version_id: payload.version_id, config: config() };
    if (action === 'candidate.get') return { candidate_id: payload.candidate_id, config: config() };
    if (action === 'release.checklist') return { checks: [], progress: {} };
    if (action === 'draft.save') return { revision: ++revision, config: structuredClone(payload.config) };
    if (action === 'configuration.compare') return {
      before: { ...payload.before, config: config(), content_hash: 'before-hash' },
      after: { ...payload.after, config: { ...config(), persona: { goal: '<script>新值</script>' } }, content_hash: 'after-hash' },
      diff: [{ path: '$.persona.goal', before: false, after: null }],
      object_diff: { changes: [{ object_type: 'entry_port', object_id: 'in', operation: 'changed', path: '$.units[unit_id="u"].entry_ports[port="in"].requires', before: [], after: ['ready'] }], diagnostics: [] },
    };
    throw new Error(action);
  } };
  return { client, calls };
}

test('draft snapshot undo and redo span persona, applied ports and graph edits without changing the server revision', async () => {
  const { client } = fixture();
  const workspace = createR1ConfigurationWorkspace({ client });
  await workspace.load('expert');
  workspace.updateField('persona.goal', '办理');
  workspace.setTab('flow');
  assert.equal(workspace.patchUnit(0, { entry_ports: [{ port: 'checked', requires: ['verified'] }] }), true);
  assert.equal(workspace.patchGraphEdge([], 0, { condition: { fact: { field: 'ready', op: 'eq', value: true } } }), true);
  const applied = structuredClone(workspace.state.editorConfig);
  assert.equal(workspace.undo(), true);
  assert.deepEqual(workspace.state.editorConfig.orchestration.edges[0].condition, {});
  assert.equal(workspace.undo(), true);
  assert.equal(workspace.state.editorConfig.units[0].entry_ports[0].port, 'in');
  workspace.setTab('persona');
  assert.equal(workspace.undo(), true);
  assert.equal(workspace.state.editorConfig.persona.goal, '答疑');
  assert.equal(workspace.undo(), false);
  assert.equal(workspace.redo(), true);
  assert.equal(workspace.redo(), true);
  assert.equal(workspace.redo(), true);
  assert.deepEqual(workspace.state.editorConfig, applied);
  assert.equal(workspace.state.draft.revision, 1);
  assert.deepEqual(workspace.state.draft.config, config());
  workspace.undo();
  workspace.updateField('persona.goal', '新分支');
  assert.equal(workspace.redo(), false);
});

test('raw JSON is retained through snapshot browsing and cannot be discarded by undo or a background refresh', async () => {
  const { client } = fixture();
  const workspace = createR1ConfigurationWorkspace({ client });
  await workspace.load('expert');
  workspace.updateField('persona.goal', '未保存');
  workspace.updateJsonField('units', '[{"unit_id":');
  const before = structuredClone({ config: workspace.state.editorConfig, inputs: workspace.state.jsonInputs, errors: workspace.state.jsonErrors });
  assert.equal(workspace.undo(), false);
  assert.equal(await workspace.refresh(), false);
  await workspace.openStable('v1');
  workspace.setTab('flow');
  assert.ok(!renderR1Configuration({ r1Configuration: workspace }).includes('[{&quot;unit_id&quot;:'));
  assert.equal(workspace.undo(), false);
  const savedCalls = [];
  const request = client.request;
  client.request = (action, payload) => { savedCalls.push(action); return request(action, payload); };
  await workspace.save(config());
  workspace.updateJsonField('units', '[]');
  assert.ok(!savedCalls.includes('draft.save'));
  workspace.closeSnapshot();
  await workspace.openCandidate('c1');
  workspace.closeSnapshot();
  assert.deepEqual({ config: workspace.state.editorConfig, inputs: workspace.state.jsonInputs, errors: workspace.state.jsonErrors }, before);
});

test('save, explicit reload, revision conflict and expert changes fence draft history', async () => {
  const { client } = fixture();
  const workspace = createR1ConfigurationWorkspace({ client });
  await workspace.load('expert');
  workspace.updateField('persona.goal', '已保存');
  await workspace.save(workspace.state.editorConfig);
  assert.equal(workspace.undo(), false);
  workspace.updateField('persona.goal', '修改');
  await workspace.refresh({ discard: true });
  assert.equal(workspace.undo(), false);
  workspace.updateField('persona.goal', '本地');
  const request = client.request;
  client.request = async (action, payload) => {
    if (action === 'draft.save') throw new ConfigurationApiError({ status: 409, error: { code: 'revision_conflict', current: { revision: 4, config: config() } } });
    return request(action, payload);
  };
  await workspace.save(workspace.state.editorConfig);
  assert.equal(workspace.undo(), false);
  assert.equal(workspace.state.editorConfig.persona.goal, '本地');
  await workspace.openStable('v1');
  workspace.closeSnapshot();
  assert.equal(workspace.state.status, 'conflict');
  assert.equal(workspace.updateField('persona.goal', '绕过冲突'), false);
  workspace.reloadConflict();
  assert.equal(workspace.redo(), false);
  workspace.updateField('persona.goal', '另一次');
  await workspace.load('other');
  assert.equal(workspace.undo(), false);
  assert.equal(workspace.state.editorConfig.persona.goal, '答疑');
});

test('late save and read-only snapshot responses do not replace another expert or a closed view', async () => {
  const { client } = fixture();
  const workspace = createR1ConfigurationWorkspace({ client });
  await workspace.load('expert');
  const request = client.request;
  let resolveSave, resolveStable;
  client.request = (action, payload) => action === 'draft.save' ? new Promise(resolve => { resolveSave = resolve; })
    : action === 'stable.get' ? new Promise(resolve => { resolveStable = resolve; }) : request(action, payload);
  workspace.updateField('persona.goal', 'old');
  const pendingSave = workspace.save(workspace.state.editorConfig);
  await workspace.load('other');
  resolveSave({ revision: 99, config: { persona: { goal: '迟到' } } });
  await pendingSave;
  assert.equal(workspace.state.draft.revision, 1);
  assert.equal(workspace.state.busy, false);
  const pendingView = workspace.openStable('v1');
  workspace.closeSnapshot();
  resolveStable({ version_id: 'v1', config: { persona: { goal: '关闭后到达' } } });
  await pendingView;
  assert.equal(workspace.state.readOnlySnapshot, null);
  assert.equal(workspace.state.editorConfig.persona.goal, '答疑');
});

test('arbitrary stable and candidate comparison is API-derived, read-only and preserves the draft', async () => {
  const { client, calls } = fixture();
  const workspace = createR1ConfigurationWorkspace({ client });
  await workspace.load('expert');
  workspace.updateField('persona.goal', '保留草稿');
  const before = { kind: 'stable', id: 'v2' }, after = { kind: 'candidate', id: 'c1' };
  await workspace.compareVersions(before, after);
  assert.deepEqual(calls.at(-1), { action: 'configuration.compare', payload: { agent_id: 'expert', before, after } });
  assert.equal(workspace.state.comparison.after.id, 'c1');
  workspace.updateField('persona.goal', '禁止覆盖');
  workspace.patchGraphEdge([], 0, { to: 'elsewhere' });
  assert.equal(workspace.undo(), false);
  assert.equal(workspace.state.editorConfig.persona.goal, '保留草稿');
  assert.equal(workspace.state.editorConfig.orchestration.edges[0].to, 'end');
  workspace.setTab('history');
  const html = renderR1Configuration({ r1Configuration: workspace });
  assert.match(html, /v2.*c1/s);
  assert.match(html, /入口端口 in · 修改/);
  assert.match(html, /<pre>false<\/pre>/);
  assert.match(html, /<pre>null<\/pre>/);
  assert.ok(!html.includes('<script>新值</script>'));
  workspace.closeComparison();
  assert.equal(workspace.undo(), true);
  assert.equal(workspace.state.editorConfig.persona.goal, '答疑');
  assert.ok(calls.every(call => !['candidate.freeze', 'release.approve', 'draft.save'].includes(call.action)));
});

test('comparison request selection and closing fence stale results and errors', async () => {
  const { client } = fixture();
  const workspace = createR1ConfigurationWorkspace({ client });
  await workspace.load('expert');
  const request = client.request;
  const pending = [];
  client.request = (action, payload) => action === 'configuration.compare'
    ? new Promise((resolve, reject) => pending.push({ resolve, reject, payload })) : request(action, payload);
  const before = { kind: 'stable', id: 'v1' }, after = { kind: 'candidate', id: 'c1' };
  const first = workspace.compareVersions(before, after);
  workspace.closeComparison();
  pending[0].resolve(await request('configuration.compare', { before, after }));
  await first;
  assert.equal(workspace.state.comparison, null);
  const second = workspace.compareVersions(before, after);
  await workspace.load('other');
  pending[1].reject(new Error('旧请求失败'));
  await second;
  assert.equal(workspace.state.error, null);
  assert.equal(workspace.state.comparison, null);
});
