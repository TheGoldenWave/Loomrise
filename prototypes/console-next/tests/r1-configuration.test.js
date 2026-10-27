import test from 'node:test';
import assert from 'node:assert/strict';
import { createConfigurationClient, createR1ConfigurationWorkspace, ConfigurationApiError } from '../r1-configuration.js';

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
  let loseNextFreezeResponse = false;
  let nextFreezeError = null;
  let nextCandidateListError = null;
  let returnNullFromNextFreeze = false;
  const frozenByKey = new Map();
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
      if (action === 'candidate.list') {
        if (nextCandidateListError) {
          const error = nextCandidateListError;
          nextCandidateListError = null;
          throw error;
        }
        return { items: structuredClone(candidates) };
      }
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
        if (nextFreezeError) {
          const error = nextFreezeError;
          nextFreezeError = null;
          throw error;
        }
        if (validateIssues.length) throw new ConfigurationApiError({ schema_version: 'config-api-v1', ok: false, status: 422, error: { code: 'validation_failed', issues: structuredClone(validateIssues) } });
        const key = payload.idempotency_key;
        let candidate = frozenByKey.get(key);
        if (!candidate) {
          candidate = { candidate_id: `cp_${candidates.length + 1}`, source_revision: draft.revision, config: structuredClone(draft.config), diff: [{ path: '$.persona.goal', before: '旧目标', after: draft.config.persona.goal }], status: 'frozen' };
          candidates.push(candidate);
          frozenByKey.set(key, candidate);
        }
        if (loseNextFreezeResponse) {
          loseNextFreezeResponse = false;
          throw new ConfigurationApiError({ status: 0, error: { code: 'service_unavailable' } });
        }
        if (returnNullFromNextFreeze) {
          returnNullFromNextFreeze = false;
          return null;
        }
        return structuredClone(candidate);
      }
      if (action === 'candidate.get') return structuredClone(candidates[0]);
      throw new Error(`unhandled action ${action}`);
    },
  };
  return { client, calls, setDraft(value) { draft = value; }, setConflict(value) { conflict = value; }, setValidationIssues(value) { validateIssues = value; }, setCandidates(value) { candidates = value; }, loseNextFreezeResponse() { loseNextFreezeResponse = true; }, returnNullFromNextFreeze() { returnNullFromNextFreeze = true; }, rejectNextFreeze(error) { nextFreezeError = error; }, failNextCandidateList(error) { nextCandidateListError = error; } };
}

test('configuration client checks API schema and rejects failed envelopes', async () => {
  const client = createConfigurationClient({ fetchImpl: async () => response({ schema_version: 'config-api-v1', ok: false, error: { code: 'revision_conflict', current: { revision: 8 } } }, 409) });
  await assert.rejects(client.request('draft.get', { agent_id: 'agent-1' }), error => error instanceof ConfigurationApiError
    && error.code === 'revision_conflict'
    && error.details.current.revision === 8
    && error.schemaVersion === 'config-api-v1'
    && error.envelopeOk === false);
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

test('late save from an old expert cannot overwrite the newly loaded expert', async () => {
  let releaseSave;
  let markSaveStarted;
  const saveStarted = new Promise(resolve => { markSaveStarted = resolve; });
  const draftFor = (agentId, revision = 1, config = null) => ({
    agent_id: agentId,
    revision,
    base_version_id: 'v1',
    config: config || { ...configuration(), persona: { ...configuration().persona, name: agentId, goal: `目标 ${agentId}` } },
  });
  const client = {
    async health() { return { ok: true }; },
    async request(action, payload) {
      if (action === 'draft.get') return draftFor(payload.agent_id);
      if (action === 'stable.list' || action === 'candidate.list') return { items: [] };
      if (action === 'draft.save') {
        const result = { ...draftFor(payload.agent_id, payload.expected_revision + 1, payload.config), diff: [] };
        markSaveStarted();
        return new Promise(resolve => { releaseSave = () => resolve(result); });
      }
      throw new Error(`unhandled action ${action}`);
    },
  };
  const workspace = createR1ConfigurationWorkspace({ client });
  await workspace.load('agent-a');
  workspace.updateField('persona.goal', 'A 的较新目标');
  const save = workspace.save(workspace.state.editorConfig);
  await saveStarted;

  await workspace.load('agent-b');
  releaseSave();
  await save;

  assert.equal(workspace.state.agentId, 'agent-b');
  assert.equal(workspace.state.draft.agent_id, 'agent-b');
  assert.equal(workspace.state.editorConfig.persona.goal, '目标 agent-b');
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
  assert.equal(workspace.state.activeTab, 'history');
  assert.equal(workspace.state.candidates.length, 1);
  await workspace.openCandidate('cp_1');
  const before = structuredClone(workspace.state.selectedCandidate.config);
  workspace.updateField('persona.goal', '不能写');
  assert.deepEqual(workspace.state.selectedCandidate.config, before);
  await workspace.openStable('v1');
  assert.equal(workspace.state.readOnlySnapshot.version_id, 'v1');
});

test('retry after a committed freeze response is lost reuses the idempotency key', async () => {
  const h = harness();
  const workspace = createR1ConfigurationWorkspace({ client: h.client });
  await workspace.load('agent-1');
  h.loseNextFreezeResponse();

  await workspace.freezeCandidate();
  assert.equal(workspace.state.error.code, 'service_unavailable');
  assert.equal(workspace.state.selectedCandidate, null);

  await workspace.freezeCandidate();

  const freezeCalls = h.calls.filter(call => call.action === 'candidate.freeze');
  assert.equal(freezeCalls.length, 2);
  assert.equal(freezeCalls[0].payload.idempotency_key, freezeCalls[1].payload.idempotency_key);
  assert.equal(workspace.state.selectedCandidate.candidate_id, 'cp_1');
  assert.equal(workspace.state.candidates.length, 1);
});

test('retry after frozen candidate history refresh fails reuses the idempotency key', async () => {
  const h = harness();
  const workspace = createR1ConfigurationWorkspace({ client: h.client });
  await workspace.load('agent-1');
  h.failNextCandidateList(new ConfigurationApiError({ status: 0, error: { code: 'service_unavailable' } }));

  await workspace.freezeCandidate();
  assert.equal(workspace.state.error.code, 'service_unavailable');
  assert.equal(workspace.state.selectedCandidate.candidate_id, 'cp_1');
  workspace.closeSnapshot();
  await workspace.freezeCandidate();

  const freezeCalls = h.calls.filter(call => call.action === 'candidate.freeze');
  assert.equal(freezeCalls.length, 2);
  assert.equal(freezeCalls[0].payload.idempotency_key, freezeCalls[1].payload.idempotency_key);
  assert.equal(workspace.state.candidates.length, 1);
  assert.equal(workspace.state.selectedCandidate.candidate_id, 'cp_1');
});

test('authoritative freeze rejection clears its pending idempotency key', async () => {
  const h = harness();
  const workspace = createR1ConfigurationWorkspace({ client: h.client });
  await workspace.load('agent-1');
  h.setValidationIssues([{ path: '$.persona.name', code: 'invalid', message: 'invalid' }]);

  await workspace.freezeCandidate();
  assert.equal(workspace.state.error.code, 'validation_failed');
  h.setValidationIssues([]);
  await workspace.freezeCandidate();

  const freezeCalls = h.calls.filter(call => call.action === 'candidate.freeze');
  assert.equal(freezeCalls.length, 2);
  assert.notEqual(freezeCalls[0].payload.idempotency_key, freezeCalls[1].payload.idempotency_key);
  assert.equal(workspace.state.candidates.length, 1);
});

for (const [label, code] of [['malformed response', 'invalid_response'], ['schema mismatch', 'schema_mismatch']]) {
  test(`${label} on a 4xx freeze response preserves the idempotency key`, async () => {
    const h = harness();
    const workspace = createR1ConfigurationWorkspace({ client: h.client });
    await workspace.load('agent-1');
    h.rejectNextFreeze(new ConfigurationApiError({ status: 422, error: { code } }));

    await workspace.freezeCandidate();
    assert.equal(workspace.state.error.code, code);
    await workspace.freezeCandidate();

    const freezeCalls = h.calls.filter(call => call.action === 'candidate.freeze');
    assert.equal(freezeCalls.length, 2);
    assert.equal(freezeCalls[0].payload.idempotency_key, freezeCalls[1].payload.idempotency_key);
    assert.equal(workspace.state.candidates.length, 1);
  });
}

test('a changed draft revision gets a different freeze idempotency key', async () => {
  const h = harness();
  const workspace = createR1ConfigurationWorkspace({ client: h.client });
  await workspace.load('agent-1');
  h.loseNextFreezeResponse();
  await workspace.freezeCandidate();

  h.setDraft({ ...workspace.state.draft, revision: 2 });
  await workspace.load('agent-1');
  await workspace.freezeCandidate();

  const freezeCalls = h.calls.filter(call => call.action === 'candidate.freeze');
  assert.equal(freezeCalls.length, 2);
  assert.notEqual(freezeCalls[0].payload.idempotency_key, freezeCalls[1].payload.idempotency_key);
  assert.equal(freezeCalls[1].payload.expected_revision, 2);
  assert.equal(workspace.state.candidates.length, 2);
});

test('a malformed freeze success body preserves its idempotency key', async () => {
  const h = harness();
  const workspace = createR1ConfigurationWorkspace({ client: h.client });
  await workspace.load('agent-1');
  h.returnNullFromNextFreeze();

  await workspace.freezeCandidate();
  assert.equal(workspace.state.error?.code, 'invalid_response');
  assert.equal(workspace.state.selectedCandidate, null);
  await workspace.freezeCandidate();

  const freezeCalls = h.calls.filter(call => call.action === 'candidate.freeze');
  assert.equal(freezeCalls.length, 2);
  assert.equal(freezeCalls[0].payload.idempotency_key, freezeCalls[1].payload.idempotency_key);
  assert.equal(workspace.state.selectedCandidate.candidate_id, 'cp_1');
  assert.equal(workspace.state.candidates.length, 1);
});

test('contradictory 4xx error envelope preserves the pending idempotency key', async () => {
  const h = harness();
  const workspace = createR1ConfigurationWorkspace({ client: h.client });
  await workspace.load('agent-1');
  h.rejectNextFreeze(new ConfigurationApiError({
    schema_version: 'config-api-v1', ok: true, status: 422,
    error: { code: 'validation_failed', issues: [{ path: '$.persona.name' }] },
  }));

  await workspace.freezeCandidate();
  assert.equal(workspace.state.error.code, 'validation_failed');
  await workspace.freezeCandidate();

  const freezeCalls = h.calls.filter(call => call.action === 'candidate.freeze');
  assert.equal(freezeCalls.length, 2);
  assert.equal(freezeCalls[0].payload.idempotency_key, freezeCalls[1].payload.idempotency_key);
  assert.equal(workspace.state.candidates.length, 1);
});

test('malformed conflict response from the API preserves the pending freeze key', async () => {
  const freezeCalls = [];
  const candidates = [];
  let malformedConflict = true;
  const candidate = {
    candidate_id: 'cp_1', source_revision: 1, config: configuration(), diff: [], status: 'frozen',
  };
  const client = createConfigurationClient({ fetchImpl: async (_url, options) => {
    if (options.method === 'GET') return response({ schema_version: 'config-api-v1', ok: true });
    const { action, payload } = JSON.parse(options.body);
    if (action === 'draft.get') {
      return response({ schema_version: 'config-api-v1', ok: true, result: {
        agent_id: payload.agent_id, revision: 1, base_version_id: 'v1', config: configuration(),
      } });
    }
    if (action === 'stable.list') return response({ schema_version: 'config-api-v1', ok: true, result: { items: [] } });
    if (action === 'candidate.list') return response({ schema_version: 'config-api-v1', ok: true, result: { items: candidates } });
    if (action === 'candidate.freeze') {
      freezeCalls.push(payload);
      if (malformedConflict) {
        malformedConflict = false;
        return response({ schema_version: 'config-api-v1', ok: false, error: { code: 'revision_conflict' } }, 409);
      }
      candidates.push(candidate);
      return response({ schema_version: 'config-api-v1', ok: true, result: candidate });
    }
    throw new Error(`unhandled action ${action}`);
  } });
  const workspace = createR1ConfigurationWorkspace({ client });
  await workspace.load('agent-1');

  await workspace.freezeCandidate();
  assert.equal(workspace.state.error.code, 'revision_conflict');
  assert.equal(workspace.state.conflict, null);
  await workspace.freezeCandidate();

  assert.equal(freezeCalls.length, 2);
  assert.equal(freezeCalls[0].idempotency_key, freezeCalls[1].idempotency_key);
  assert.equal(workspace.state.selectedCandidate.candidate_id, 'cp_1');
  assert.equal(workspace.state.conflict, null);
});

test('freeze conflicts for another expert or unchanged revision preserve the pending key', async () => {
  const invalidSnapshots = [
    { agent_id: 'agent-2', revision: 2 },
    { agent_id: 'agent-1', revision: 1 },
  ];

  for (const current of invalidSnapshots) {
    const h = harness();
    const workspace = createR1ConfigurationWorkspace({ client: h.client });
    await workspace.load('agent-1');
    h.rejectNextFreeze(new ConfigurationApiError({
      schema_version: 'config-api-v1', ok: false, status: 409,
      error: { code: 'revision_conflict', current: { ...current, config: configuration() } },
    }));

    await workspace.freezeCandidate();
    assert.equal(workspace.state.error.code, 'revision_conflict');
    assert.equal(workspace.state.conflict, null);
    await workspace.freezeCandidate();

    const freezeCalls = h.calls.filter(call => call.action === 'candidate.freeze');
    assert.equal(freezeCalls.length, 2);
    assert.equal(freezeCalls[0].payload.idempotency_key, freezeCalls[1].payload.idempotency_key);
    assert.equal(workspace.state.selectedCandidate.candidate_id, 'cp_1');
    assert.equal(workspace.state.conflict, null);
  }
});

test('malformed validation response from the API does not enter validation state or clear the freeze key', async () => {
  const freezeCalls = [];
  const candidates = [];
  let malformedValidation = true;
  const candidate = {
    candidate_id: 'cp_1', source_revision: 1, config: configuration(), diff: [], status: 'frozen',
  };
  const client = createConfigurationClient({ fetchImpl: async (_url, options) => {
    if (options.method === 'GET') return response({ schema_version: 'config-api-v1', ok: true });
    const { action, payload } = JSON.parse(options.body);
    if (action === 'draft.get') {
      return response({ schema_version: 'config-api-v1', ok: true, result: {
        agent_id: payload.agent_id, revision: 1, base_version_id: 'v1', config: configuration(),
      } });
    }
    if (action === 'stable.list') return response({ schema_version: 'config-api-v1', ok: true, result: { items: [] } });
    if (action === 'candidate.list') return response({ schema_version: 'config-api-v1', ok: true, result: { items: candidates } });
    if (action === 'candidate.freeze') {
      freezeCalls.push(payload);
      if (malformedValidation) {
        malformedValidation = false;
        return response({ schema_version: 'config-api-v1', ok: false, error: {
          code: 'validation_failed', issues: [{ path: '$.persona.name' }],
        } }, 422);
      }
      candidates.push(candidate);
      return response({ schema_version: 'config-api-v1', ok: true, result: candidate });
    }
    throw new Error(`unhandled configuration action: ${action}`);
  } });
  const workspace = createR1ConfigurationWorkspace({ client });
  await workspace.load('agent-1');

  await workspace.freezeCandidate();
  assert.equal(workspace.state.error.code, 'validation_failed');
  assert.equal(workspace.state.validation, null);
  await workspace.freezeCandidate();

  assert.equal(freezeCalls.length, 2);
  assert.equal(freezeCalls[0].idempotency_key, freezeCalls[1].idempotency_key);
  assert.equal(workspace.state.selectedCandidate.candidate_id, 'cp_1');
  assert.equal(workspace.state.candidates.length, 1);
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
