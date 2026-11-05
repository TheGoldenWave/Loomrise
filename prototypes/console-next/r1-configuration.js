export const DEFAULT_CONFIGURATION_API = 'http://127.0.0.1:8766';

const FAQ_CASE_FOLD_EXCEPTIONS = new Map([
  [0xB5, '\u03bc'], [0xDF, 'ss'], [0x149, '\u02bcn'],
  [0x17F, 's'], [0x1F0, 'j\u030c'], [0x345, '\u03b9'],
  [0x390, '\u03b9\u0308\u0301'], [0x3B0, '\u03c5\u0308\u0301'], [0x3C2, '\u03c3'],
  [0x3D0, '\u03b2'], [0x3D1, '\u03b8'], [0x3D5, '\u03c6'],
  [0x3D6, '\u03c0'], [0x3F0, '\u03ba'], [0x3F1, '\u03c1'],
  [0x3F5, '\u03b5'], [0x587, '\u0565\u0582'], [0x1C80, '\u0432'],
  [0x1C81, '\u0434'], [0x1C82, '\u043e'], [0x1C83, '\u0441'],
  [0x1C84, '\u0442'], [0x1C85, '\u0442'], [0x1C86, '\u044a'],
  [0x1C87, '\u0463'], [0x1C88, '\ua64b'], [0x1E96, 'h\u0331'],
  [0x1E97, 't\u0308'], [0x1E98, 'w\u030a'], [0x1E99, 'y\u030a'],
  [0x1E9A, 'a\u02be'], [0x1E9B, '\u1e61'], [0x1E9E, 'ss'],
  [0x1F50, '\u03c5\u0313'], [0x1F52, '\u03c5\u0313\u0300'], [0x1F54, '\u03c5\u0313\u0301'],
  [0x1F56, '\u03c5\u0313\u0342'], [0x1F80, '\u1f00\u03b9'], [0x1F81, '\u1f01\u03b9'],
  [0x1F82, '\u1f02\u03b9'], [0x1F83, '\u1f03\u03b9'], [0x1F84, '\u1f04\u03b9'],
  [0x1F85, '\u1f05\u03b9'], [0x1F86, '\u1f06\u03b9'], [0x1F87, '\u1f07\u03b9'],
  [0x1F88, '\u1f00\u03b9'], [0x1F89, '\u1f01\u03b9'], [0x1F8A, '\u1f02\u03b9'],
  [0x1F8B, '\u1f03\u03b9'], [0x1F8C, '\u1f04\u03b9'], [0x1F8D, '\u1f05\u03b9'],
  [0x1F8E, '\u1f06\u03b9'], [0x1F8F, '\u1f07\u03b9'], [0x1F90, '\u1f20\u03b9'],
  [0x1F91, '\u1f21\u03b9'], [0x1F92, '\u1f22\u03b9'], [0x1F93, '\u1f23\u03b9'],
  [0x1F94, '\u1f24\u03b9'], [0x1F95, '\u1f25\u03b9'], [0x1F96, '\u1f26\u03b9'],
  [0x1F97, '\u1f27\u03b9'], [0x1F98, '\u1f20\u03b9'], [0x1F99, '\u1f21\u03b9'],
  [0x1F9A, '\u1f22\u03b9'], [0x1F9B, '\u1f23\u03b9'], [0x1F9C, '\u1f24\u03b9'],
  [0x1F9D, '\u1f25\u03b9'], [0x1F9E, '\u1f26\u03b9'], [0x1F9F, '\u1f27\u03b9'],
  [0x1FA0, '\u1f60\u03b9'], [0x1FA1, '\u1f61\u03b9'], [0x1FA2, '\u1f62\u03b9'],
  [0x1FA3, '\u1f63\u03b9'], [0x1FA4, '\u1f64\u03b9'], [0x1FA5, '\u1f65\u03b9'],
  [0x1FA6, '\u1f66\u03b9'], [0x1FA7, '\u1f67\u03b9'], [0x1FA8, '\u1f60\u03b9'],
  [0x1FA9, '\u1f61\u03b9'], [0x1FAA, '\u1f62\u03b9'], [0x1FAB, '\u1f63\u03b9'],
  [0x1FAC, '\u1f64\u03b9'], [0x1FAD, '\u1f65\u03b9'], [0x1FAE, '\u1f66\u03b9'],
  [0x1FAF, '\u1f67\u03b9'], [0x1FB2, '\u1f70\u03b9'], [0x1FB3, '\u03b1\u03b9'],
  [0x1FB4, '\u03ac\u03b9'], [0x1FB6, '\u03b1\u0342'], [0x1FB7, '\u03b1\u0342\u03b9'],
  [0x1FBC, '\u03b1\u03b9'], [0x1FBE, '\u03b9'], [0x1FC2, '\u1f74\u03b9'],
  [0x1FC3, '\u03b7\u03b9'], [0x1FC4, '\u03ae\u03b9'], [0x1FC6, '\u03b7\u0342'],
  [0x1FC7, '\u03b7\u0342\u03b9'], [0x1FCC, '\u03b7\u03b9'], [0x1FD2, '\u03b9\u0308\u0300'],
  [0x1FD3, '\u03b9\u0308\u0301'], [0x1FD6, '\u03b9\u0342'], [0x1FD7, '\u03b9\u0308\u0342'],
  [0x1FE2, '\u03c5\u0308\u0300'], [0x1FE3, '\u03c5\u0308\u0301'], [0x1FE4, '\u03c1\u0313'],
  [0x1FE6, '\u03c5\u0342'], [0x1FE7, '\u03c5\u0308\u0342'], [0x1FF2, '\u1f7c\u03b9'],
  [0x1FF3, '\u03c9\u03b9'], [0x1FF4, '\u03ce\u03b9'], [0x1FF6, '\u03c9\u0342'],
  [0x1FF7, '\u03c9\u0342\u03b9'], [0x1FFC, '\u03c9\u03b9'], [0xFB00, 'ff'],
  [0xFB01, 'fi'], [0xFB02, 'fl'], [0xFB03, 'ffi'],
  [0xFB04, 'ffl'], [0xFB05, 'st'], [0xFB06, 'st'],
  [0xFB13, '\u0574\u0576'], [0xFB14, '\u0574\u0565'], [0xFB15, '\u0574\u056b'],
  [0xFB16, '\u057e\u0576'], [0xFB17, '\u0574\u056d'],
]);

function faqCaseFold(value) {
  return Array.from(value, character => {
    const codePoint = character.codePointAt(0);
    if (codePoint >= 0x13A0 && codePoint <= 0x13F5) return character;
    if (codePoint >= 0x13F8 && codePoint <= 0x13FD) return String.fromCodePoint(codePoint - 8);
    if (codePoint >= 0xAB70 && codePoint <= 0xABBF) return String.fromCodePoint(codePoint - 0x97D0);
    return FAQ_CASE_FOLD_EXCEPTIONS.get(codePoint) ?? character.toLowerCase();
  }).join('');
}

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

  async function invoke(action, payload, endpoint, schema) {
    const response = await fetchResponse(`${origin}${endpoint}`, {
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
    if (envelope?.schema_version !== schema) {
      throw new ConfigurationApiError({ status: response.status, error: { code: 'schema_mismatch', message: '配置服务 Schema 版本不匹配' } });
    }
    if (!response.ok || envelope?.ok !== true) {
      throw new ConfigurationApiError({ ...envelope, status: response.status });
    }
    return envelope.result;
  }

  const request = (action, payload = {}) => invoke(action, payload, '/api/configuration', 'config-api-v1');
  const customerRequest = (action, payload = {}) => invoke(action, payload, '/api/customer-service', 'customer-service-v1');

  async function health() {
    const response = await fetchResponse(`${origin}/api/configuration/health`, {
      method: 'GET', mode: 'cors', credentials: 'omit', cache: 'no-store',
    });
    if (!response.ok) throw new Error(`配置服务状态检查失败 (${response.status})`);
    const value = await response.json();
    if (value?.schema_version !== 'config-api-v1' || value?.ok !== true) throw new Error('配置服务 Schema 版本不匹配');
    return value;
  }

  return { origin, request, customerRequest, health };
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
    releaseChecklist: null,
    receptionOptions: { status: 'idle', model: null, sources: [], error: null },
    runOverlay: null,
    runOverlayStatus: 'idle',
    runOverlayError: null,
    comparison: null,
    comparisonStatus: 'idle',
    comparisonError: null,
    comparisonSelection: { before: '', after: '' },
    refreshPending: false,
    history: { past: [], future: [], agentId: null, revision: null },
    busy: false,
    orchestration: { view: 'graph', selected: null },
  };
  let generation = 0;
  let overlayGeneration = 0;
  let snapshotGeneration = 0;
  let comparisonGeneration = 0;
  let snapshotLoading = false;
  let historyGroup = null;
  const changed = () => onChange(state);
  const writable = () => state.editorConfig && state.status === 'ready' && !state.busy
    && !state.readOnlySnapshot && !state.selectedCandidate && !state.comparison;
  const editingSnapshot = () => structuredClone({ editorConfig: state.editorConfig, jsonInputs: state.jsonInputs, jsonErrors: state.jsonErrors });
  const historyCurrent = () => state.history.agentId === state.agentId && state.history.revision === state.draft?.revision;
  const resetHistory = () => {
    state.history = { past: [], future: [], agentId: state.agentId, revision: state.draft?.revision };
    state.orchestration.deletedEdge = null;
    historyGroup = null;
  };
  const recordEdit = (before, group = null) => {
    if (JSON.stringify(before) === JSON.stringify(editingSnapshot())) return false;
    if (!historyCurrent()) resetHistory();
    if (!group || historyGroup !== group || !state.history.past.length) {
      state.history.past.push(before);
      if (state.history.past.length > 100) state.history.past.shift();
    }
    state.history.future = [];
    historyGroup = group;
    state.validation = null;
    state.refreshPending = false;
    return true;
  };
  const hasUnsavedInput = () => Boolean(state.draft && state.editorConfig
    && (JSON.stringify(state.draft.config) !== JSON.stringify(state.editorConfig) || Object.keys(state.jsonInputs).length));
  function restoreHistory(direction) {
    if (!writable() || Object.keys(state.jsonErrors).length) return false;
    if (!historyCurrent()) { resetHistory(); changed(); return false; }
    const source = direction === 'undo' ? state.history.past : state.history.future;
    const target = direction === 'undo' ? state.history.future : state.history.past;
    if (!source.length) return false;
    target.push(editingSnapshot());
    Object.assign(state, source.pop());
    state.orchestration.deletedEdge = null;
    state.validation = null;
    historyGroup = null;
    changed();
    return true;
  }
  const undo = () => restoreHistory('undo');
  const redo = () => restoreHistory('redo');
  const clearComparison = () => {
    comparisonGeneration += 1;
    state.comparison = null;
    state.comparisonStatus = 'idle';
    state.comparisonError = null;
  };
  const clearRunOverlay = () => {
    overlayGeneration += 1;
    state.runOverlay = null;
    state.runOverlayStatus = 'idle';
    state.runOverlayError = null;
  };

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
    clearRunOverlay();
    clearComparison();
    snapshotGeneration += 1;
    snapshotLoading = false;
    state.busy = false;
    state.agentId = agentId;
    state.orchestration = { view: 'graph', selected: null };
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
    state.releaseChecklist = null;
    state.receptionOptions = { status: 'idle', model: null, sources: [], error: null };
    state.runOverlay = null;
    state.validation = null;
    state.refreshPending = false;
    state.comparisonSelection = { before: '', after: '' };
    resetHistory();
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
        resetHistory();
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

  async function refresh({ discard = false } = {}) {
    if (state.busy) return false;
    if (!discard && hasUnsavedInput()) {
      state.refreshPending = true;
      changed();
      return false;
    }
    return load(state.agentId);
  }

  function cancelRefresh() { state.refreshPending = false; changed(); }

  async function createDraft(baseVersionId) {
    if (!state.agentId || !baseVersionId || state.busy || state.draft) return;
    const currentGeneration = generation;
    state.busy = true;
    state.error = null;
    changed();
    try {
      const draft = await client.request('draft.create', {
        agent_id: state.agentId, base_version_id: baseVersionId,
      });
      if (currentGeneration !== generation) return;
      state.draft = draft;
      state.editorConfig = structuredClone(state.draft.config);
      state.jsonInputs = {};
      state.jsonErrors = {};
      state.status = 'ready';
      state.activeTab = 'persona';
      state.validation = null;
      state.lastDiff = [];
      resetHistory();
    } catch (error) {
      if (currentGeneration !== generation) return;
      state.error = error;
      state.status = error.code === 'revision_conflict' ? 'conflict' : 'no-draft';
    } finally {
      if (currentGeneration === generation) { state.busy = false; changed(); }
    }
  }

  async function save(config) {
    if (!state.draft || !state.agentId || !writable()) return;
    if (Object.keys(state.jsonErrors).length) {
      state.error = new Error('请先修正 JSON 格式错误，再保存草稿');
      changed();
      return;
    }
    const attemptedConfig = structuredClone(config);
    const currentGeneration = generation;
    state.busy = true;
    state.error = null;
    state.validation = null;
    changed();
    try {
      const draft = await client.request('draft.save', {
        agent_id: state.agentId,
        expected_revision: state.draft.revision,
        config: attemptedConfig,
      });
      if (currentGeneration !== generation) return;
      state.draft = draft;
      state.editorConfig = structuredClone(state.draft.config);
      state.jsonInputs = {};
      state.jsonErrors = {};
      state.lastDiff = state.draft.diff || [];
      state.status = 'ready';
      state.conflict = null;
      resetHistory();
    } catch (error) {
      if (currentGeneration !== generation) return;
      state.error = error;
      if (error.code === 'revision_conflict') {
        state.conflict = { current: error.details.current, attemptedConfig };
        state.status = 'conflict';
        resetHistory();
      } else state.status = 'ready';
    } finally {
      if (currentGeneration === generation) { state.busy = false; changed(); }
    }
  }

  async function validate() {
    if (!state.draft || !state.agentId || !writable() || hasUnsavedInput()) return;
    const currentGeneration = generation;
    state.busy = true;
    state.error = null;
    changed();
    try {
      const validation = await client.request('draft.validate', {
        agent_id: state.agentId, expected_revision: state.draft.revision,
      });
      if (currentGeneration !== generation) return;
      state.validation = validation;
      state.status = 'ready';
    } catch (error) {
      if (currentGeneration !== generation) return;
      state.error = error;
      if (error.code === 'revision_conflict') {
        state.conflict = { current: error.details.current, attemptedConfig: null };
        state.status = 'conflict';
        resetHistory();
      }
    } finally {
      if (currentGeneration === generation) { state.busy = false; changed(); }
    }
  }

  async function loadRunOverlay({ versionId, from, to, channel } = {}) {
    if (!state.agentId || !versionId || !from || !to
      || state.readOnlySnapshot?.version_id !== versionId) throw new TypeError('请先打开要查看实际走向的稳定版本');
    const currentGeneration = ++overlayGeneration;
    const agentId = state.agentId;
    state.runOverlayStatus = 'loading';
    state.runOverlayError = null;
    state.runOverlay = null;
    changed();
    try {
      const payload = { agent_id: agentId, version_id: versionId, from, to };
      if (channel) payload.channel = channel;
      const result = await client.request('run.overlay', payload);
      if (currentGeneration !== overlayGeneration || state.agentId !== agentId) return null;
      if (result.version_id !== versionId) throw new Error('返回版本与所选版本不一致，请重新载入');
      state.runOverlay = result;
      state.runOverlayStatus = 'ready';
      return state.runOverlay;
    } catch (error) {
      if (currentGeneration !== overlayGeneration) return null;
      state.runOverlayError = error.message;
      state.runOverlayStatus = 'error';
      return null;
    } finally {
      if (currentGeneration === overlayGeneration) changed();
    }
  }

  async function freezeCandidate() {
    if (!state.draft || !state.agentId || !writable() || hasUnsavedInput()) return;
    const currentGeneration = generation;
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
      if (currentGeneration !== generation) return;
      state.selectedCandidate = candidate;
      state.validation = { revision: state.draft.revision, valid: true, issues: [] };
      const checklist = await client.request('release.checklist', {
        agent_id: state.agentId, candidate_id: candidate.candidate_id,
      });
      if (currentGeneration !== generation) return;
      state.releaseChecklist = checklist;
      const listed = await client.request('candidate.list', { agent_id: state.agentId });
      if (currentGeneration !== generation) return;
      state.candidates = listed.items || [];
      state.activeTab = 'history';
      state.status = 'ready';
    } catch (error) {
      if (currentGeneration !== generation) return;
      state.error = error;
      if (error.code === 'validation_failed') state.validation = { revision: state.draft.revision, valid: false, issues: error.details.issues || [] };
      if (error.code === 'revision_conflict') {
        state.conflict = { current: error.details.current, attemptedConfig: null };
        state.status = 'conflict';
        resetHistory();
      }
    } finally {
      if (currentGeneration === generation) { state.busy = false; changed(); }
    }
  }

  function canDismissAdvisory() {
    return writable() && !hasUnsavedInput() && !Object.keys(state.jsonErrors || {}).length
      && !state.advisoryBusyKey;
  }

  async function dismissAdvisory(layerPath) {
    if (!canDismissAdvisory() || !Array.isArray(layerPath)) return false;
    const agentId = state.agentId, revision = state.draft.revision;
    const advisoryKey = `closed-set:${JSON.stringify(layerPath)}`;
    state.advisoryBusyKey = advisoryKey;
    state.error = null;
    changed();
    try {
      const dismissal = await client.request('advisory.dismiss', {
        agent_id: agentId, expected_revision: revision, layer_path: layerPath,
      });
      if (state.agentId === agentId && state.draft?.revision === revision) {
        const prior = state.draft.advisory_dismissals || [];
        state.draft.advisory_dismissals = [
          ...prior.filter(item => item.advisory_key !== dismissal.advisory_key), dismissal,
        ];
      }
      return true;
    } catch (error) {
      state.error = error;
      return false;
    } finally {
      state.advisoryBusyKey = null;
      changed();
    }
  }

  async function retryConflict() {
    if (!state.conflict?.current || !state.conflict.attemptedConfig) return;
    const attempted = state.conflict.attemptedConfig;
    state.draft = state.conflict.current;
    state.status = 'ready';
    state.conflict = null;
    resetHistory();
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
    resetHistory();
    changed();
  }

  async function openStable(versionId) {
    if (!state.agentId || !versionId || state.busy) return;
    clearRunOverlay();
    clearComparison();
    const currentGeneration = generation, currentSnapshot = ++snapshotGeneration;
    const current = () => currentGeneration === generation && currentSnapshot === snapshotGeneration;
    snapshotLoading = true;
    state.busy = true;
    state.error = null;
    changed();
    try {
      const snapshot = await client.request('stable.get', {
        agent_id: state.agentId, version_id: versionId,
      });
      if (!current()) return;
      state.readOnlySnapshot = snapshot;
      state.selectedCandidate = null;
      state.releaseChecklist = null;
      state.activeTab = 'history';
    } catch (error) {
      if (current()) state.error = error;
    } finally {
      if (current()) { snapshotLoading = false; state.busy = false; changed(); }
    }
  }

  async function openCandidate(candidateId) {
    if (!state.agentId || !candidateId || state.busy) return;
    clearRunOverlay();
    clearComparison();
    const currentGeneration = generation, currentSnapshot = ++snapshotGeneration;
    const current = () => currentGeneration === generation && currentSnapshot === snapshotGeneration;
    snapshotLoading = true;
    state.busy = true;
    state.error = null;
    changed();
    try {
      const candidate = await client.request('candidate.get', {
        agent_id: state.agentId, candidate_id: candidateId,
      });
      if (!current()) return;
      const checklist = await client.request('release.checklist', {
        agent_id: state.agentId, candidate_id: candidateId,
      });
      if (!current()) return;
      state.selectedCandidate = candidate;
      state.releaseChecklist = checklist;
      state.readOnlySnapshot = null;
      state.activeTab = 'history';
    } catch (error) {
      if (current()) state.error = error;
    } finally {
      if (current()) { snapshotLoading = false; state.busy = false; changed(); }
    }
  }

  function closeSnapshot() {
    snapshotGeneration += 1;
    if (snapshotLoading) { snapshotLoading = false; state.busy = false; }
    clearRunOverlay();
    clearComparison();
    state.readOnlySnapshot = null;
    state.selectedCandidate = null;
    state.releaseChecklist = null;
    state.activeTab = 'persona';
    changed();
  }

  function setComparisonSelection(side, value) {
    if (!['before', 'after'].includes(side)) return false;
    clearComparison();
    state.comparisonSelection[side] = value;
    changed();
    return true;
  }

  function selectionRef(value) {
    const split = typeof value === 'string' ? value.indexOf(':') : -1;
    return split > 0 ? { kind: value.slice(0, split), id: value.slice(split + 1) } : null;
  }

  async function compareVersions(before = selectionRef(state.comparisonSelection.before), after = selectionRef(state.comparisonSelection.after)) {
    if (!state.agentId || state.busy || !['ready', 'no-draft', 'conflict'].includes(state.status)) return false;
    const validRef = ref => ref && ['stable', 'candidate'].includes(ref.kind) && typeof ref.id === 'string' && ref.id.trim();
    if (!validRef(before) || !validRef(after)) {
      state.comparisonError = '请选择比较前后的稳定版本或冻结候选。';
      changed();
      return false;
    }
    clearRunOverlay();
    const currentGeneration = generation, currentComparison = ++comparisonGeneration;
    const current = () => currentGeneration === generation && currentComparison === comparisonGeneration;
    state.comparison = null;
    state.comparisonStatus = 'loading';
    state.comparisonError = null;
    state.comparisonSelection = { before: `${before.kind}:${before.id}`, after: `${after.kind}:${after.id}` };
    historyGroup = null;
    changed();
    try {
      const result = await client.request('configuration.compare', { agent_id: state.agentId, before, after });
      if (!current()) return false;
      if (result.before?.kind !== before.kind || result.before?.id !== before.id
        || result.after?.kind !== after.kind || result.after?.id !== after.id
        || !result.before.config || !result.after.config || !Array.isArray(result.diff) || !result.object_diff) {
        throw new Error('比较结果与所选版本不一致，请重新读取。');
      }
      state.comparison = result;
      state.comparisonStatus = 'ready';
      state.readOnlySnapshot = null;
      state.selectedCandidate = null;
      state.releaseChecklist = null;
      state.orchestration = { view: 'graph', selected: null, layerPath: [] };
      state.activeTab = 'flow';
      return true;
    } catch (error) {
      if (!current()) return false;
      state.comparisonStatus = 'error';
      state.comparisonError = error.message;
      return false;
    } finally {
      if (current()) changed();
    }
  }

  function closeComparison() {
    clearComparison();
    state.activeTab = 'history';
    state.orchestration = { view: 'graph', selected: null, layerPath: [] };
    changed();
  }

  function updateField(path, value) {
    if (!writable()) return false;
    const before = editingSnapshot();
    const phraseInput = path === 'ai_reception.handoff_phrases' && typeof value === 'string' ? value : null;
    if (path === 'ai_reception.handoff_phrases') {
      if (phraseInput !== null) value = phraseInput.split('\n').map(phrase => phrase.trim()).filter(Boolean);
      if (!Array.isArray(value) || value.length > 20
        || value.some(phrase => typeof phrase !== 'string' || !phrase.trim() || phrase.includes('\0')
          || Array.from(phrase.trim()).length > 100)
        || new Set(value.map(phrase => faqCaseFold(phrase.trim()))).size !== value.length) {
        state.jsonInputs[path] = phraseInput ?? JSON.stringify(value);
        state.jsonErrors[path] = '最多 20 条，每条不超过 100 个字符，不能含空字符或重复短语。';
        recordEdit(before, `field:${path}`);
        changed();
        return false;
      }
      value = value.map(phrase => phrase.trim());
    }
    const faqQuestionPath = typeof path === 'string'
      ? /^ai_reception\.faq_suggestions\.(\d+)\.question$/.exec(path) : null;
    if (faqQuestionPath) {
      const index = Number(faqQuestionPath[1]);
      const suggestions = state.editorConfig.ai_reception?.faq_suggestions;
      if (!Number.isSafeInteger(index) || !Array.isArray(suggestions) || index >= suggestions.length
        || typeof value !== 'string' || !value.trim() || value.includes('\0') || Array.from(value).length > 160
        || suggestions.some((item, itemIndex) => itemIndex !== index && typeof item?.question === 'string'
          && faqCaseFold(item.question.trim()) === faqCaseFold(value.trim()))) return false;
    }
    const config = fieldConfig(path, value);
    if (!config) return false;
    state.editorConfig = config;
    delete state.jsonInputs[path];
    if (phraseInput !== null) state.jsonInputs[path] = phraseInput;
    delete state.jsonErrors[path];
    recordEdit(before, `field:${path}`);
    changed();
    return true;
  }

  function fieldConfig(path, value) {
    if (typeof path !== 'string') return null;
    const parts = path.split('.');
    if (parts.some(part => !part || ['__proto__', 'constructor', 'prototype'].includes(part))) return null;
    const config = structuredClone(state.editorConfig);
    let target = config;
    for (const part of parts.slice(0, -1)) {
      if (!target || typeof target !== 'object') return null;
      if (!(part in target)) target[part] = {};
      target = target[part];
    }
    if (!target || typeof target !== 'object') return null;
    target[parts.at(-1)] = structuredClone(value);
    return config;
  }

  function updateJsonField(path, raw) {
    if (!writable()) return false;
    const before = editingSnapshot();
    state.jsonInputs[path] = raw;
    try {
      const config = fieldConfig(path, JSON.parse(raw));
      if (!config) return false;
      state.editorConfig = config;
      delete state.jsonErrors[path];
      for (const inputs of [state.jsonInputs, state.jsonErrors]) {
        for (const child of Object.keys(inputs)) if (child.startsWith(`${path}.`)) delete inputs[child];
      }
    } catch (error) {
      state.jsonErrors[path] = error.message;
    }
    recordEdit(before, `json:${path}`);
    changed();
    return true;
  }

  function setTab(tab) {
    if (!['persona', 'flow', 'boundary', 'task', 'history', 'reception'].includes(tab)) return;
    state.activeTab = tab;
    historyGroup = null;
    changed();
    if (tab === 'reception' && state.receptionOptions.status === 'idle') void loadReceptionOptions();
  }

  async function loadReceptionOptions() {
    if (!state.agentId || state.receptionOptions.status === 'loading') return;
    const currentGeneration = generation, agentId = state.agentId;
    state.receptionOptions = { ...state.receptionOptions, status: 'loading', error: null };
    changed();
    const results = await Promise.allSettled([
      client.request('model.connection', { agent_id: agentId }),
      client.request('knowledge.source.list', { agent_id: agentId }),
    ]);
    if (generation !== currentGeneration || state.agentId !== agentId) return;
    state.receptionOptions = {
      status: results.every(result => result.status === 'fulfilled') ? 'ready' : 'error',
      model: results[0].status === 'fulfilled' ? results[0].value : null,
      sources: results[1].status === 'fulfilled' ? results[1].value.items || [] : [],
      error: results.some(result => result.status === 'rejected') ? '模型或资料列表读取失败，当前配置仍保留，可重试。' : null,
    };
    changed();
  }

  function setReceptionSource(sourceId, selected) {
    if (!writable()) return false;
    const source = state.receptionOptions.sources.find(item => item.source_id === sourceId && item.state === 'ready');
    const current = state.editorConfig.ai_reception?.sources ?? [];
    if (!Array.isArray(current) || (selected && (!source?.content_hash || !/^[a-f0-9]{64}$/.test(source.content_hash)))) return false;
    const updated = current.filter(item => item.source_id !== sourceId);
    if (selected) updated.push({ source_id: sourceId, content_hash: source.content_hash });
    return updateField('ai_reception.sources', updated);
  }

  function addReceptionFaqSuggestion(question, sourceId) {
    if (!writable() || typeof question !== 'string' || typeof sourceId !== 'string') return false;
    if (Array.from(question).length > 160 || question.includes('\0')) return false;
    const normalized = question.trim();
    if (!normalized) return false;
    const policy = state.editorConfig.ai_reception;
    const suggestions = policy?.faq_suggestions ?? [];
    if (!Array.isArray(suggestions) || suggestions.length >= 8 || !Array.isArray(policy?.sources)) return false;
    const reference = policy.sources.find(item => item?.source_id === sourceId);
    const source = state.receptionOptions.sources.find(item => item?.source_id === sourceId
      && item.state === 'ready' && item.content_hash === reference?.content_hash);
    if (!reference || !source || !/^[a-f0-9]{64}$/.test(reference.content_hash)) return false;
    const questionKey = faqCaseFold(normalized);
    if (suggestions.some(item => typeof item?.question === 'string' && faqCaseFold(item.question.trim()) === questionKey)) return false;
    const next = [...suggestions, { question: normalized, source_id: sourceId, content_hash: reference.content_hash }];
    return updateField('ai_reception.faq_suggestions', next);
  }

  function removeReceptionFaqSuggestion(index) {
    if (!writable()) return false;
    const suggestions = state.editorConfig.ai_reception?.faq_suggestions ?? [];
    if (!Array.isArray(suggestions) || !Number.isSafeInteger(index) || index < 0 || index >= suggestions.length) return false;
    return updateField('ai_reception.faq_suggestions', suggestions.filter((_, itemIndex) => itemIndex !== index));
  }

  function patchUnit(index, patch) {
    if (!writable()) return false;
    if (!Number.isSafeInteger(index) || index < 0 || !Array.isArray(state.editorConfig?.units)
      || !state.editorConfig.units[index] || typeof state.editorConfig.units[index] !== 'object'
      || Array.isArray(state.editorConfig.units[index]) || state.jsonErrors.units) return false;
    const allowed = new Set(['entry_ports', 'exit_ports', 'on_event', 'waits', 'max_rounds', 'body', 'load_scope']);
    if (!patch || typeof patch !== 'object' || Array.isArray(patch) || Object.keys(patch).some(key => !allowed.has(key))) return false;
    if (Object.hasOwn(patch, 'load_scope') && state.editorConfig.units[index].load_mode !== 'concurrent') return false;
    if (Object.hasOwn(patch, 'body')) {
      // This inspector edits a tool reference only, not arbitrary executable content.
      const previous = state.editorConfig.units[index].body;
      const next = patch.body;
      if (state.editorConfig.orchestration?.schema_version !== 'unit-graph-v1'
        || previous?.kind !== 'tool' || next?.kind !== 'tool') return false;
      const ref = next.tool_ref;
      if (!ref || typeof ref !== 'object' || Array.isArray(ref)
        || !['tool_id', 'version'].every(key => typeof ref[key] === 'string' && ref[key].trim())) return false;
      const withoutRef = body => Object.fromEntries(Object.entries(body).filter(([key]) => key !== 'tool_ref'));
      if (JSON.stringify(withoutRef(previous)) !== JSON.stringify(withoutRef(next))) return false;
    }
    const units = structuredClone(state.editorConfig.units);
    units[index] = { ...units[index], ...structuredClone(patch) };
    if (Object.hasOwn(patch, 'load_scope') && patch.load_scope === undefined) delete units[index].load_scope;
    historyGroup = null;
    updateField('units', units);
    historyGroup = null;
    return true;
  }

  function graphAtPath(config, layerPath) {
    let graph = config?.orchestration;
    const units = Array.isArray(config?.units) ? config.units : [];
    if (graph?.schema_version !== 'unit-graph-v1' || graph.kind !== 'graph') return null;
    for (const localId of layerPath) {
      const matches = Array.isArray(graph.nodes) ? graph.nodes.filter(node => node?.id === localId) : [];
      if (matches.length !== 1) return null;
      const ref = matches[0].unit_ref;
      const unitsFound = units.filter(unit => unit?.unit_id === ref?.unit_id && unit?.version === ref?.version);
      if (unitsFound.length !== 1 || unitsFound[0].load_mode !== 'routed' || unitsFound[0].body?.kind !== 'graph') return null;
      graph = unitsFound[0].body;
    }
    return graph;
  }

  function patchGraphEdge(layerPath, index, patch) {
    if (!writable()
      || state.jsonErrors.units || state.jsonErrors.orchestration || !Array.isArray(layerPath)
      || !Number.isSafeInteger(index) || index < 0 || !patch || typeof patch !== 'object' || Array.isArray(patch)) return false;
    const allowed = new Set(['id', 'from', 'to', 'condition', 'max_rounds', 'exit', 'counter', 'window']);
    if (Object.keys(patch).some(key => !allowed.has(key))) return false;
    const editorConfig = structuredClone(state.editorConfig);
    const graph = graphAtPath(editorConfig, layerPath);
    if (!graph || !Array.isArray(graph.edges) || !graph.edges[index] || typeof graph.edges[index] !== 'object') return false;
    const edges = structuredClone(graph.edges);
    const edge = { ...edges[index] };
    for (const [key, value] of Object.entries(patch)) {
      if (value === undefined) delete edge[key];
      else edge[key] = structuredClone(value);
    }
    edges[index] = edge;
    graph.edges = edges;
    const before = editingSnapshot();
    state.editorConfig = editorConfig;
    delete state.jsonInputs.orchestration;
    if (layerPath.length) delete state.jsonInputs.units;
    delete state.jsonErrors.orchestration;
    recordEdit(before);
    changed();
    return true;
  }

  function moveGraphEdge(layerPath, index, offset) {
    if (!writable()
      || state.jsonErrors.units || state.jsonErrors.orchestration || !Array.isArray(layerPath)
      || !Number.isSafeInteger(index) || index < 0 || !Number.isSafeInteger(offset) || Math.abs(offset) !== 1) return false;
    const editorConfig = structuredClone(state.editorConfig);
    const graph = graphAtPath(editorConfig, layerPath);
    const target = index + offset;
    if (!graph || !Array.isArray(graph.edges) || index >= graph.edges.length || target < 0 || target >= graph.edges.length) return false;
    const edges = structuredClone(graph.edges);
    [edges[index], edges[target]] = [edges[target], edges[index]];
    graph.edges = edges;
    const before = editingSnapshot();
    state.editorConfig = editorConfig;
    delete state.jsonInputs.orchestration;
    if (layerPath.length) delete state.jsonInputs.units;
    delete state.jsonErrors.orchestration;
    recordEdit(before);
    changed();
    return true;
  }

  function editGraphEdges(layerPath, edit) {
    if (!writable()
      || state.jsonErrors.units || state.jsonErrors.orchestration || !Array.isArray(layerPath)) return false;
    if (!historyCurrent()) resetHistory();
    const config = structuredClone(state.editorConfig);
    const graph = graphAtPath(config, layerPath);
    if (!graph || !Array.isArray(graph.edges) || !edit(graph, config)) return false;
    const before = editingSnapshot();
    state.editorConfig = config;
    delete state.jsonInputs.orchestration;
    if (layerPath.length) delete state.jsonInputs.units;
    recordEdit(before);
    changed();
    return true;
  }

  function addGraphEdge(layerPath, edge) {
    return editGraphEdges(layerPath, (graph, config) => {
      if (!edge || typeof edge !== 'object' || Array.isArray(edge)
        || Object.keys(edge).some(key => !['id', 'from', 'to', 'condition', 'max_rounds', 'exit', 'counter', 'window'].includes(key))
        || typeof edge.id !== 'string' || !edge.id.trim() || edge.id.includes('.')
        || graph.edges.some(item => item?.id === edge.id)
        || typeof edge.from !== 'string' || typeof edge.to !== 'string'
        || !edge.condition || typeof edge.condition !== 'object' || Array.isArray(edge.condition)) return false;
      const localPort = (value, ports) => {
        const parts = value.split('.');
        if (parts.length !== 2) return false;
        const nodes = Array.isArray(graph.nodes) ? graph.nodes.filter(node => node?.id === parts[0]) : [];
        if (nodes.length !== 1) return false;
        const ref = nodes[0].unit_ref;
        const units = config.units.filter(unit => unit?.unit_id === ref?.unit_id && unit?.version === ref?.version && unit?.load_mode === 'routed');
        return units.length === 1 && Array.isArray(units[0][ports]) && units[0][ports].some(port => port?.port === parts[1]);
      };
      const targetPort = value => {
        if (value === 'end') return layerPath.length === 0;
        if (value.startsWith('self.')) {
          const owner = config.units.find(unit => unit?.body === graph);
          return Array.isArray(owner?.exit_ports) && owner.exit_ports.some(port => value === `self.${port?.port}`);
        }
        return localPort(value, 'entry_ports');
      };
      if (!localPort(edge.from, 'exit_ports') || !targetPort(edge.to)
        || (edge.exit !== undefined && (typeof edge.exit !== 'string' || !targetPort(edge.exit)))) return false;
      graph.edges.push(structuredClone(edge));
      state.orchestration.selected = `${JSON.stringify(layerPath)}:edge-key:${edge.id}`;
      state.orchestration.deletedEdge = null;
      return true;
    });
  }

  function removeGraphEdge(layerPath, index, expectedId) {
    return editGraphEdges(layerPath, graph => {
      if (!Number.isSafeInteger(index) || index < 0 || index >= graph.edges.length
        || graph.edges[index]?.id !== expectedId) return false;
      const [edge] = graph.edges.splice(index, 1);
      state.orchestration.deletedEdge = {
        layerPath: [...layerPath], index, edge, after: JSON.stringify(graph.edges),
      };
      state.orchestration.selected = null;
      return true;
    });
  }

  function restoreGraphEdge() {
    const deleted = state.orchestration.deletedEdge;
    if (!deleted) return false;
    return editGraphEdges(deleted.layerPath, graph => {
      if (JSON.stringify(graph.edges) !== deleted.after) return false;
      graph.edges.splice(deleted.index, 0, structuredClone(deleted.edge));
      state.orchestration.selected = `${JSON.stringify(deleted.layerPath)}:edge-key:${deleted.edge.id}`;
      state.orchestration.deletedEdge = null;
      return true;
    });
  }

  return {
    client, state, load, refresh, createDraft, save, validate, freezeCandidate,
    retryConflict, reloadConflict, openStable, openCandidate, closeSnapshot, setTab, loadRunOverlay,
    updateField, updateJsonField, patchUnit, patchGraphEdge, moveGraphEdge,
    addGraphEdge, removeGraphEdge, restoreGraphEdge, undo, redo, cancelRefresh,
    setComparisonSelection, compareVersions, closeComparison, loadReceptionOptions, setReceptionSource,
    addReceptionFaqSuggestion, removeReceptionFaqSuggestion,
    canDismissAdvisory, dismissAdvisory,
  };
}
