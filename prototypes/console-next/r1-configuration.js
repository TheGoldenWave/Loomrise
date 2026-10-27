export const DEFAULT_CONFIGURATION_API = 'http://127.0.0.1:8766';

export class ConfigurationApiError extends Error {
  constructor(response) {
    const error = response?.error || {};
    super(error.message || error.code || '配置服务请求失败');
    this.name = 'ConfigurationApiError';
    this.code = error.code || 'configuration_error';
    this.details = error;
    this.status = response?.status || 0;
  }
}

export function createConfigurationClient({
  fetchImpl = globalThis.fetch?.bind(globalThis),
  baseUrl = globalThis.__LOOMRISE_CONFIG_API__ || DEFAULT_CONFIGURATION_API,
} = {}) {
  if (typeof fetchImpl !== 'function') throw new TypeError('fetch is required');
  const origin = String(baseUrl).replace(/\/$/, '');
  const fetchResponse = async (url, options) => {
    try { return await fetchImpl(url, options); }
    catch {
      throw new ConfigurationApiError({
        status: 0,
        error: {
          code: 'service_unavailable',
          message: '无法连接本机配置服务，请确认服务已启动后重试。',
        },
      });
    }
  };

  async function request(action, payload = {}) {
    const response = await fetchResponse(`${origin}/api/configuration`, {
      method: 'POST',
      mode: 'cors',
      credentials: 'omit',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, payload }),
    });
    let envelope;
    try { envelope = await response.json(); }
    catch { throw new ConfigurationApiError({ status: response.status, error: { code: 'invalid_response', message: '配置服务返回了无效响应' } }); }
    if (envelope?.schema_version !== 'config-api-v1') {
      throw new ConfigurationApiError({ status: response.status, error: { code: 'schema_mismatch', message: '配置服务 Schema 版本不匹配' } });
    }
    if (!response.ok || envelope?.ok !== true) {
      throw new ConfigurationApiError({ ...envelope, status: response.status });
    }
    return envelope.result;
  }

  async function health() {
    const response = await fetchResponse(`${origin}/api/configuration/health`, {
      method: 'GET', mode: 'cors', credentials: 'omit', cache: 'no-store',
    });
    if (!response.ok) throw new Error(`配置服务状态检查失败 (${response.status})`);
    const value = await response.json();
    if (value?.schema_version !== 'config-api-v1' || value?.ok !== true) throw new Error('配置服务 Schema 版本不匹配');
    return value;
  }

  return { origin, request, health };
}

export function createR1ConfigurationWorkspace({
  client = createConfigurationClient(),
  onChange = () => {},
} = {}) {
  const state = {
    agentId: null,
    status: 'idle',
    error: null,
    draft: null,
    editorConfig: null,
    jsonInputs: {},
    jsonErrors: {},
    stableVersions: [],
    candidates: [],
    validation: null,
    activeTab: 'persona',
    lastDiff: [],
    conflict: null,
    readOnlySnapshot: null,
    selectedCandidate: null,
    busy: false,
  };
  let generation = 0;
  const changed = () => onChange(state);

  async function collect(agentId) {
    const [draftResult, stableResult, candidateResult] = await Promise.allSettled([
      client.request('draft.get', { agent_id: agentId }),
      client.request('stable.list', { agent_id: agentId }),
      client.request('candidate.list', { agent_id: agentId }),
    ]);
    return { draftResult, stableResult, candidateResult };
  }

  async function load(agentId) {
    if (!agentId) return;
    const currentGeneration = ++generation;
    state.agentId = agentId;
    state.status = 'loading';
    state.error = null;
    state.draft = null;
    state.editorConfig = null;
    state.stableVersions = [];
    state.candidates = [];
    state.jsonInputs = {};
    state.jsonErrors = {};
    state.lastDiff = [];
    state.activeTab = 'persona';
    state.conflict = null;
    state.readOnlySnapshot = null;
    state.selectedCandidate = null;
    state.validation = null;
    changed();
    try {
      await client.health();
      const { draftResult, stableResult, candidateResult } = await collect(agentId);
      if (currentGeneration !== generation) return;
      if (stableResult.status === 'fulfilled') state.stableVersions = stableResult.value.items || [];
      if (candidateResult.status === 'fulfilled') state.candidates = candidateResult.value.items || [];
      if (stableResult.status === 'rejected') throw stableResult.reason;
      if (candidateResult.status === 'rejected') throw candidateResult.reason;
      if (draftResult.status === 'fulfilled') {
        state.draft = draftResult.value;
        state.editorConfig = structuredClone(state.draft.config);
        state.jsonInputs = {};
        state.jsonErrors = {};
        state.status = 'ready';
      } else if (draftResult.reason?.code === 'not_found') {
        state.draft = null;
        state.editorConfig = null;
        state.jsonInputs = {};
        state.jsonErrors = {};
        state.activeTab = 'history';
        state.status = 'no-draft';
      } else {
        throw draftResult.reason;
      }
    } catch (error) {
      if (currentGeneration !== generation) return;
      state.status = 'error';
      state.error = error;
    }
    changed();
  }

  async function refresh() {
    return load(state.agentId);
  }

  async function createDraft(baseVersionId) {
    if (!state.agentId || !baseVersionId) return;
    state.busy = true;
    state.error = null;
    changed();
    try {
      state.draft = await client.request('draft.create', {
        agent_id: state.agentId, base_version_id: baseVersionId,
      });
      state.editorConfig = structuredClone(state.draft.config);
      state.jsonInputs = {};
      state.jsonErrors = {};
      state.status = 'ready';
      state.activeTab = 'persona';
      state.validation = null;
      state.lastDiff = [];
    } catch (error) {
      state.error = error;
      state.status = error.code === 'revision_conflict' ? 'conflict' : 'no-draft';
    } finally {
      state.busy = false;
      changed();
    }
  }

  async function save(config) {
    if (!state.draft || !state.agentId) return;
    if (Object.keys(state.jsonErrors).length) {
      state.error = new Error('请先修正 JSON 格式错误，再保存草稿');
      changed();
      return;
    }
    const attemptedConfig = structuredClone(config);
    state.busy = true;
    state.error = null;
    state.validation = null;
    changed();
    try {
      state.draft = await client.request('draft.save', {
        agent_id: state.agentId,
        expected_revision: state.draft.revision,
        config: attemptedConfig,
      });
      state.editorConfig = structuredClone(state.draft.config);
      state.jsonInputs = {};
      state.jsonErrors = {};
      state.lastDiff = state.draft.diff || [];
      state.status = 'ready';
      state.conflict = null;
    } catch (error) {
      state.error = error;
      if (error.code === 'revision_conflict') {
        state.conflict = { current: error.details.current, attemptedConfig };
        state.status = 'conflict';
      } else state.status = 'ready';
    } finally {
      state.busy = false;
      changed();
    }
  }

  async function validate() {
    if (!state.draft || !state.agentId) return;
    state.busy = true;
    state.error = null;
    changed();
    try {
      state.validation = await client.request('draft.validate', {
        agent_id: state.agentId, expected_revision: state.draft.revision,
      });
      state.status = 'ready';
    } catch (error) {
      state.error = error;
      if (error.code === 'revision_conflict') {
        state.conflict = { current: error.details.current, attemptedConfig: null };
        state.status = 'conflict';
      }
    } finally {
      state.busy = false;
      changed();
    }
  }

  async function freezeCandidate() {
    if (!state.draft || !state.agentId) return;
    state.busy = true;
    state.error = null;
    changed();
    const key = globalThis.crypto?.randomUUID?.() || `console-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    try {
      const candidate = await client.request('candidate.freeze', {
        agent_id: state.agentId,
        expected_revision: state.draft.revision,
        idempotency_key: key,
      });
      state.selectedCandidate = candidate;
      state.validation = { revision: state.draft.revision, valid: true, issues: [] };
      const listed = await client.request('candidate.list', { agent_id: state.agentId });
      state.candidates = listed.items || [];
      state.activeTab = 'history';
      state.status = 'ready';
    } catch (error) {
      state.error = error;
      if (error.code === 'validation_failed') state.validation = { revision: state.draft.revision, valid: false, issues: error.details.issues || [] };
      if (error.code === 'revision_conflict') {
        state.conflict = { current: error.details.current, attemptedConfig: null };
        state.status = 'conflict';
      }
    } finally {
      state.busy = false;
      changed();
    }
  }

  async function retryConflict() {
    if (!state.conflict?.current || !state.conflict.attemptedConfig) return;
    const attempted = state.conflict.attemptedConfig;
    state.draft = state.conflict.current;
    state.status = 'ready';
    state.conflict = null;
    await save(attempted);
  }

  function reloadConflict() {
    if (!state.conflict?.current) return;
    state.draft = state.conflict.current;
    state.editorConfig = structuredClone(state.draft.config);
    state.jsonInputs = {};
    state.jsonErrors = {};
    state.status = 'ready';
    state.error = null;
    state.conflict = null;
    state.validation = null;
    state.lastDiff = [];
    changed();
  }

  async function openStable(versionId) {
    if (!state.agentId || !versionId) return;
    state.busy = true;
    state.error = null;
    changed();
    try {
      state.readOnlySnapshot = await client.request('stable.get', {
        agent_id: state.agentId, version_id: versionId,
      });
      state.selectedCandidate = null;
      state.editorConfig = structuredClone(state.readOnlySnapshot.config);
      state.activeTab = 'history';
      state.status = state.draft ? 'ready' : 'no-draft';
    } catch (error) {
      state.error = error;
    } finally {
      state.busy = false;
      changed();
    }
  }

  async function openCandidate(candidateId) {
    if (!state.agentId || !candidateId) return;
    state.busy = true;
    state.error = null;
    changed();
    try {
      state.selectedCandidate = await client.request('candidate.get', {
        agent_id: state.agentId, candidate_id: candidateId,
      });
      state.readOnlySnapshot = null;
      state.editorConfig = structuredClone(state.selectedCandidate.config);
      state.activeTab = 'history';
      state.status = state.draft ? 'ready' : 'no-draft';
    } catch (error) {
      state.error = error;
    } finally {
      state.busy = false;
      changed();
    }
  }

  function closeSnapshot() {
    state.readOnlySnapshot = null;
    state.selectedCandidate = null;
    if (state.draft) state.editorConfig = structuredClone(state.draft.config);
    state.activeTab = 'persona';
    changed();
  }

  function updateField(path, value) {
    if (!state.editorConfig || state.readOnlySnapshot || state.selectedCandidate) return;
    const parts = path.split('.');
    let target = state.editorConfig;
    for (const part of parts.slice(0, -1)) {
      if (!target || typeof target !== 'object') return;
      if (!(part in target)) target[part] = {};
      target = target[part];
    }
    if (!target || typeof target !== 'object') return;
    target[parts.at(-1)] = value;
    state.jsonErrors = { ...state.jsonErrors };
    delete state.jsonErrors[path];
    changed();
  }

  function updateJsonField(path, raw) {
    state.jsonInputs[path] = raw;
    try {
      updateField(path, JSON.parse(raw));
      delete state.jsonErrors[path];
    } catch (error) {
      state.jsonErrors[path] = error.message;
    }
    changed();
  }

  function setTab(tab) {
    if (!['persona', 'flow', 'boundary', 'task', 'history'].includes(tab)) return;
    state.activeTab = tab;
    changed();
  }

  return {
    client, state, load, refresh, createDraft, save, validate, freezeCandidate,
    retryConflict, reloadConflict, openStable, openCandidate, closeSnapshot, setTab,
    updateField, updateJsonField,
  };
}
