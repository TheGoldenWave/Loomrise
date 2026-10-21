import { clone, initialState, makeAgent, demoSources } from './fixtures.js';
import { LOCAL_CONNECTION, buildSuggestions, configPathEditable, getPath, readiness, setPath, simulateReply, sourceValid, validDate, versionValid } from './domain.js';
import { ensureMaterialState, handleMaterialAction } from './material-domain.js';
import { ensureVisitorState, visitorSession, handleVisitorAction, cancelVisitorSession } from './visitor-domain.js';

export const STORAGE_KEY = 'loomrise:console-next:v1';
let sequence = 0;
const uid = prefix => `${prefix}-${Date.now().toString(36)}-${(++sequence).toString(36)}`;
const now = () => new Date().toISOString();
const yes = value => value === true || value === 'on' || value === 'true';
const WRITE_ACTIONS = new Set(['create', 'update-config', 'update-name', 'source', 'source-stage', 'source-retry', 'source-revoke', 'source-remove', 'load-demo-sources', 'field', 'field-remove', 'flow', 'flow-remove', 'flow-up', 'flow-down', 'skill', 'skill-remove', 'tool', 'tool-remove', 'assistant-accept', 'proposal-apply', 'sandbox-check', 'sandbox-approve', 'sandbox-publish', 'version-restore', 'contact-template', 'contact-add-block', 'contact-remove-block', 'contact-move-block', 'contact-unpublish', 'connection', 'connection-test', 'connection-remove', 'inbox', 'inbox-handoff', 'inbox-release', 'inbox-simulate', 'case', 'case-review', 'case-from-run', 'case-evaluate', 'proposal', 'proposal-reject', 'proposal-from-run', 'proposal-evaluate']);
const SUGGESTIBLE = /^(greeting|tone|scope|fallback|flow\.\d+\.instruction|skills\.\d+\.(description|exit))$/;

export function createStore(storage = null, seed = initialState()) {
  let state = clone(seed);
  let loaded = false;
  let recoveryRaw = null;
  try {
    const stored = storage?.getItem(STORAGE_KEY);
    if (stored) {
      recoveryRaw = stored;
      const parsed = JSON.parse(stored);
      if (Object.hasOwn(parsed, 'materials') && !Array.isArray(parsed.materials)) throw new Error('物料记录格式不兼容');
      if (parsed.schema !== 1 || !Array.isArray(parsed.agents) || !Array.isArray(parsed.connections) || !parsed.ui?.assistant || !Array.isArray(parsed.runs) || !Array.isArray(parsed.cases) || !Array.isArray(parsed.proposals) || parsed.agents.some(agent => !agent.checks || !Array.isArray(agent.versions) || !agent.config?.model || !agent.config?.handoff || !agent.config?.outcome || !agent.config?.widget || !agent.config?.contact || ['goal', 'audience', 'scope', 'fallback'].some(key => typeof agent.config[key] !== 'string') || ['sources', 'fields', 'flow', 'skills', 'rules', 'tools'].some(key => !Array.isArray(agent.config[key])))) throw new Error('数据格式不兼容');
      if (parsed.materials?.some(asset => !asset || typeof asset !== 'object' || ['id', 'filename'].some(key => typeof asset[key] !== 'string' || !asset[key]) || ['tags', 'agentIds', 'variants', 'history'].some(key => asset[key] !== undefined && (!Array.isArray(asset[key]) || (key === 'variants' || key === 'history') && asset[key].some(item => !item || typeof item !== 'object'))) || ['summary', 'original', 'processing'].some(key => asset[key] != null && (typeof asset[key] !== 'object' || Array.isArray(asset[key]))))) throw new Error('物料条目格式不兼容');
      if (['trialMessages', 'widgetTrialMessages'].some(key => Object.hasOwn(parsed.ui, key) && (!Array.isArray(parsed.ui[key]) || parsed.ui[key].some(message => !message || typeof message !== 'object')))) throw new Error('访客消息记录格式不兼容');
      ensureMaterialState(parsed);
      ensureVisitorState(parsed);
      state = parsed;
      loaded = true;
      recoveryRaw = null;
    }
  } catch {
    state.ui.toast = { tone: 'warning', text: '本地记录无法读取，原文已保留且自动保存暂停。点击“重试保存”会先保留恢复副本；当前示例不是原记录。' };
    state.ui.saveStatus = 'error';
  }
  const listeners = new Set();
  ensureMaterialState(state);
  ensureVisitorState(state);
  state.ui.materials.autoResults = [];
  for (const item of state.agents) item.config.materialPolicy = { enabled: false, requireExplicitRequest: true, preferredVariant: 'original', allowOriginalFallback: true, maxCount: 1, ...item.config.materialPolicy };
  state.ui.mobilePanel ||= 'editor';
  state.ui.sourceFilter = ['all', 'ready', 'pending', 'unavailable'].includes(state.ui.sourceFilter) ? state.ui.sourceFilter : 'all';
  state.ui.caseForm ||= false;
  state.ui.proposalForm ||= false;
  const collectionKeys = { runs: 'runs', cases: 'cases', iterations: 'proposals', connections: 'connections' };
  state.ui.collections = Object.fromEntries(Object.keys(collectionKeys).map(page => [page, { query: '', status: 'all', detailId: null, form: false, ...state.ui.collections?.[page] }]));
  state.ui.deployment = { cloud: 'tencent', region: 'demo-east', domain: '', ...state.ui.deployment };
  if (loaded) {
    if (state.ui.materials.uploadStatus === 'saving') { state.ui.materials.uploadStatus = 'idle'; state.ui.materials.upload = null; state.ui.materials.error = '页面刷新中止了文件保存，请重新选择原件。'; }
    state.ui.navOpen = false;
    state.ui.previewVersionId = null;
    for (const surface of ['trial', 'widget']) if (visitorSession(state, surface).status === 'running') cancelVisitorSession(state, surface, { uid, now, reason: '页面刷新中止了本地试用，请重新发送。' });
    if (state.ui.assistant.status === 'running') state.ui.assistant.status = 'cancelled';
  }

  const currentAgent = () => state.agents.find(agent => agent.id === state.selectedAgentId) || null;
  const readonly = () => state.ui.readonly || Boolean(state.ui.previewVersionId);
  function resolveConfigurationSection() {
    if (state.ui.page !== 'configuration' || ['service', 'knowledge', 'flow', 'fields', 'skills', 'rules', 'tools', 'outcome', 'model', 'evidence'].includes(state.ui.section)) return;
    const agent = currentAgent();
    const snapshot = agent?.versions.find(version => version.id === state.ui.previewVersionId);
    const ready = readiness(snapshot ? { ...agent, config: snapshot.config } : agent, state.connections);
    const issue = ready.items.find(item => item.id === 'goal' && item.status === 'missing')?.detail;
    state.ui.section = issue ? /预算/.test(issue) ? 'model' : /字段/.test(issue) ? 'fields' : /步骤/.test(issue) ? 'flow' : /业务写入/.test(issue) ? 'tools' : 'service'
      : ready.items.find(item => item.id === 'knowledge')?.status === 'missing' ? 'knowledge'
        : ready.items.find(item => item.id === 'connection')?.status === 'missing' ? 'model' : 'service';
  }
  resolveConfigurationSection();
  function notify() { listeners.forEach(listener => listener(state)); }
  function save() {
    if (recoveryRaw !== null) { state.ui.saveStatus = 'error'; state.ui.storageRecovery = true; return false; }
    state.ui.savedAt = now();
    state.ui.saveStatus = 'saved';
    try { storage?.setItem(STORAGE_KEY, JSON.stringify(state)); return true; }
    catch { state.ui.saveStatus = 'error'; state.ui.toast = { tone: 'danger', text: '本地保存失败，内容仍在当前页面。请导出草稿或释放浏览器存储后重试。' }; return false; }
  }
  function toast(text, tone = 'neutral') { state.ui.toast = { text, tone }; }
  function changed(agent, path = '', manual = true, evidence = {}) {
    agent.revision += 1;
    state.ui.materials.autoResults = [];
    for (const surface of ['trial', 'widget']) if (visitorSession(state, surface).pending?.agentId === agent.id) cancelVisitorSession(state, surface, { uid, now, reason: '配置已修改，旧试用轮次已中止。' });
    agent.checks = { testedRevision: null, approvedRevision: null };
    if (path && manual) agent.manualPaths[path] = { revision: agent.revision, time: now(), origin: '人工修改' };
    agent.origins ||= {};
    agent.changeLog ||= [];
    agent.origins[path] = { revision: agent.revision, time: now(), origin: manual ? '人工修改' : '助手建议', source: evidence.source || '当前浏览器草稿' };
    const current = path === 'name' ? agent.name : getPath(agent.config, path);
    agent.changeLog.unshift({ id: uid('change'), path, revision: agent.revision, origin: manual ? '人工修改' : '助手建议', time: now(), before: evidence.before ?? null, after: current === undefined ? null : clone(current), source: evidence.source || '' });
    agent.changeLog = agent.changeLog.slice(0, 100);
    for (const item of state.cases.filter(item => item.agentId === agent.id && item.result)) {
      item.lastResult = { result: item.result, revision: item.evaluatedRevision }; item.result = null; item.stale = true;
    }
    for (const item of state.proposals.filter(item => item.agentId === agent.id && item.status === 'pending' && item.evaluation)) {
      item.lastEvaluation = item.evaluation; item.evaluation = null; item.stale = true;
    }
    if (state.ui.assistant.status !== 'running' && state.ui.assistant.suggestions.some(item => item.status === 'pending')) {
      state.ui.assistant.message = '草稿已变化，旧建议需要重新生成；人工内容不会被覆盖。';
    }
  }
  function fail(text) { toast(text, 'danger'); save(); notify(); return { ok: false, message: text }; }
  function selectAgent(id) {
    if (!state.agents.some(agent => agent.id === id)) throw new Error('专家已不存在');
    for (const surface of ['trial', 'widget']) handleVisitorAction(state, surface === 'trial' ? 'trial-clear' : 'widget-trial-clear', {}, { uid, now, readonly: false });
    state.selectedAgentId = id;
    state.ui.trialAgentId = id; state.ui.widgetTrialAgentId = id;
    state.ui.previewVersionId = null;
    state.ui.trialMessages = [];
    state.ui.trialState = 'idle';
    state.ui.assistant = { prompt: '', scope: 'all', status: 'idle', suggestions: [], baseRevision: null, message: '' };
    state.ui.sourceDetail = null;
    state.ui.sourceEdit = null; state.ui.sourceForm = false; state.ui.sourceFileMeta = null; state.ui.sourceFileBody = '';
    state.ui.search = ''; state.ui.sourceFilter = 'all';
    for (const entry of Object.values(state.ui.collections)) Object.assign(entry, { query: '', status: 'all', detailId: null, form: false });
    state.ui.caseEdit = null; state.ui.caseForm = false; state.ui.proposalForm = false; state.ui.runDetail = null;
    state.ui.widgetChecks = [];
    state.ui.activeConversation = currentAgent().conversations[0]?.id || null;
    state.ui.materials.selected = []; state.ui.materials.sendContext = null; state.ui.materials.picker = false;
    Object.assign(state.ui.materials, { form: false, editingId: null, detailId: null, upload: null, uploadStatus: 'idle', error: '', autoQuery: '', autoResults: [], session: state.ui.materials.session + 1 });
  }
  function requireSourceRights(source) {
    if (!source.rights || !source.sourceRef.trim() || !validDate(source.expires) || source.expires < new Date().toISOString().slice(0, 10)) throw new Error('请确认资料授权、来源和有效日期，再进入可用资料');
  }
  function suiteSignature(agentId) {
    return JSON.stringify(state.cases.filter(item => item.agentId === agentId).map(({ id, input, expected, must, forbid, status }) => ({ id, input, expected, must, forbid, status })).sort((a, b) => a.id.localeCompare(b.id)));
  }
  function invalidateSuite(agentId) {
    for (const proposal of state.proposals.filter(item => item.agentId === agentId && item.status === 'pending')) {
      if (proposal.evaluation) proposal.lastEvaluation = proposal.evaluation;
      proposal.evaluation = null; proposal.stale = true;
    }
  }
  function remapArrayMetadata(agent, collection, before) {
    for (const name of ['manualPaths', 'origins']) {
      const metadata = agent[name] || {}; const additions = {};
      for (const [path, evidence] of Object.entries(metadata)) {
        const match = path.match(new RegExp(`^${collection}\\.(\\d+)\\.(.+)$`)); if (!match) continue;
        const stableId = before[Number(match[1])]?.id;
        const index = agent.config[collection].findIndex(item => item.id === stableId);
        delete metadata[path];
        if (index >= 0) additions[`${collection}.${index}.${match[2]}`] = evidence;
      }
      Object.assign(metadata, additions);
    }
  }

  function dispatch(action, data = {}) {
    const agent = currentAgent();
    if (WRITE_ACTIONS.has(action) && readonly()) return fail('当前为只读预览。返回草稿编辑后再修改；这不会改变真实权限。');
    if (['collection-new', 'collection-edit', 'case-create', 'case-edit', 'proposal-create'].includes(action) && readonly()) return fail('当前为只读预览，请返回草稿后编辑。');
    let value = null;
    try {
      const visitor = handleVisitorAction(state, action, data, { uid, now, readonly: readonly() });
      if (visitor.handled) { save(); notify(); return { ok: true, value: visitor.value ?? null }; }
      if (action.startsWith('material-')) {
        const outcome = handleMaterialAction(state, action, data, { agent, readonly: readonly(), uid, now, changed });
        if (!outcome.handled) throw new Error(`物料操作尚未定义：${action}`);
        save(); notify(); return { ok: true, value: outcome.value ?? null };
      }
      switch (action) {
        case 'collection-open':
        case 'collection-back':
        case 'collection-new':
        case 'collection-edit':
        case 'collection-cancel':
        case 'collection-clear': {
          const key = collectionKeys[data.page];
          if (!key) throw new Error('不支持此集合工作面');
          const ui = state.ui.collections[data.page];
          const item = data.id && state[key].find(item => item.id === data.id && (data.page === 'connections' || item.agentId === agent?.id));
          if (['collection-open', 'collection-edit'].includes(action) && !item) throw new Error('当前范围没有这条记录');
          if (action === 'collection-edit' && data.page !== 'cases') throw new Error('此集合不支持编辑');
          if (action === 'collection-new' && data.page === 'runs') throw new Error('请从客服试用创建运行记录');
          state.ui.page = data.page;
          if (action === 'collection-clear') { ui.query = ''; ui.status = 'all'; }
          else if (action === 'collection-open') { ui.detailId = item.id; ui.form = false; }
          else if (action === 'collection-back') { ui.detailId = null; ui.form = false; }
          else if (action === 'collection-new') { ui.detailId = null; ui.form = true; }
          else if (action === 'collection-edit') { ui.detailId = item.id; ui.form = true; }
          else ui.form = false;
          if (data.page === 'cases') { state.ui.caseForm = ui.form; state.ui.caseEdit = ui.form ? ui.detailId : null; }
          if (data.page === 'iterations') state.ui.proposalForm = ui.form;
          if (data.page === 'runs') state.ui.runDetail = ui.detailId;
          break;
        }
        case 'source-clear': state.ui.search = ''; state.ui.sourceFilter = 'all'; break;
        case 'navigate':
          if (data.page && data.page !== state.ui.page) for (const surface of ['trial', 'widget']) if (visitorSession(state, surface).status === 'running') cancelVisitorSession(state, surface, { uid, now, reason: '已离开本次预览，旧轮次已中止。' });
          if (data.page !== state.ui.page) state.ui.search = '';
          state.ui.page = data.page || 'agents'; state.ui.navOpen = false; state.ui.previewVersionId = null;
          if (data.page === 'overview') state.ui.depth = 'overview';
          if (data.section) { state.ui.section = data.section; state.ui.depth = 'business'; }
          break;
        case 'select-agent': selectAgent(data.id); state.ui.page = 'overview'; state.ui.depth = 'overview'; break;
        case 'new-agent': state.ui.page = 'create'; state.ui.createMode = data.mode || 'manual'; state.ui.previewVersionId = null; break;
        case 'create-mode': state.ui.createMode = data.mode; break;
        case 'create': {
          const name = String(data.name || '').trim() || `新客服 ${state.agents.length + 1}`;
          if (name.length > 60) throw new Error('名称请控制在 60 个字符以内');
          const created = makeAgent({ id: uid('agent'), name, goal: String(data.goal || '').trim(), audience: String(data.audience || '').trim() });
          if (data.goal) created.manualPaths.goal = { revision: 1, time: now(), origin: '人工创建' };
          state.agents.push(created); selectAgent(created.id);
          state.ui.page = 'overview'; state.ui.depth = 'overview';
          state.ui.createDraft = { name: '', goal: '', audience: '' };
          state.ui.assistantOpen = false;
          state.ui.sidePanel = 'preview';
          state.ui.mobilePanel = 'editor';
          toast('草稿已创建，继续人工配置即可。后续创作助手候选会进入同一草稿审阅。');
          break;
        }
        case 'set-depth': state.ui.depth = data.depth; state.ui.page = data.depth === 'overview' ? 'overview' : 'configuration'; break;
        case 'set-section': state.ui.section = data.section; state.ui.page = 'configuration'; if (state.ui.depth === 'overview') state.ui.depth = 'business'; break;
        case 'toggle-assistant': state.ui.assistantOpen = !state.ui.assistantOpen; state.ui.sidePanel = state.ui.assistantOpen ? 'assistant' : 'preview'; state.ui.mobilePanel = state.ui.assistantOpen ? 'assistant' : 'editor'; break;
        case 'set-side-panel':
          state.ui.mobilePanel = data.panel === 'editor' ? 'editor' : 'side';
          if (data.panel !== 'editor') { state.ui.sidePanel = data.panel; state.ui.assistantOpen = data.panel === 'assistant'; }
          break;
        case 'toggle-nav': state.ui.navOpen = !state.ui.navOpen; break;
        case 'readonly-toggle': state.ui.readonly = state.ui.previewVersionId ? false : !state.ui.readonly; state.ui.previewVersionId = null; break;
        case 'dismiss-toast': state.ui.toast = null; break;
        case 'visitor-notice': toast(String(data.text || ''), 'warning'); break;
        case 'update-ui': {
          const collectionField = /^collections\.(runs|cases|iterations|connections)\.(query|status)$/.exec(data.path || '');
          if (collectionField) { state.ui.collections[collectionField[1]][collectionField[2]] = String(data.value || ''); break; }
          const allowed = /^(search|filter|sourceFilter|trialInput|widgetTrialInput|assistant\.(prompt|scope)|deployment\.(cloud|region|domain)|createDraft\.(name|goal|audience))$/;
          if (!allowed.test(data.path)) throw new Error('界面字段不支持修改');
          if (data.path === 'sourceFilter' && !['all', 'ready', 'pending', 'unavailable'].includes(data.value)) throw new Error('不支持此资料状态筛选');
          if (data.path.startsWith('createDraft.') && !state.ui.createDraft) state.ui.createDraft = { name: '', goal: '', audience: '' };
          setPath(state.ui, data.path, data.value);
          break;
        }
        case 'update-name': {
          const name = String(data.value).trim(); if (!name || name.length > 60) throw new Error('名称需为 1–60 个字符');
          agent.name = name; changed(agent, 'name'); break;
        }
        case 'update-config': {
          if (!configPathEditable(data.path)) throw new Error('此项不能直接编辑，请查看配置依据或提出待审建议');
          if (JSON.stringify(getPath(agent.config, data.path)) === JSON.stringify(data.value)) break;
          if (/tools\.\d+\.requiresConfirm/.test(data.path)) {
            const tool = agent.config.tools[Number(data.path.split('.')[1])];
            if (tool.sideEffect === 'write' && !data.value) throw new Error('业务写入不能关闭确认要求');
          }
          const previous = clone(getPath(agent.config, data.path));
          setPath(agent.config, data.path, clone(data.value));
          if (/tools\.\d+\.sideEffect/.test(data.path) && data.value === 'write') agent.config.tools[Number(data.path.split('.')[1])].requiresConfirm = true;
          changed(agent, data.path, true, { before: previous }); break;
        }
        case 'assistant-start':
          state.ui.assistant = { ...state.ui.assistant, status: 'running', suggestions: [], baseRevision: agent.revision, agentId: agent.id, prompt: data.prompt ?? state.ui.assistant.prompt, scope: data.scope ?? state.ui.assistant.scope, message: '正在整理本地演示建议…' };
          break;
        case 'assistant-generate': {
          if (data.expectedRevision !== undefined && (state.ui.assistant.status !== 'running' || state.ui.assistant.agentId !== agent.id)) break;
          if (data.expectedRevision !== undefined && agent.revision !== data.expectedRevision) {
            state.ui.assistant.status = 'stale'; state.ui.assistant.message = '整理期间草稿变化，请重新生成；人工修改已保留。'; break;
          }
          const result = buildSuggestions(agent, data.prompt ?? state.ui.assistant.prompt, data.scope ?? state.ui.assistant.scope);
          state.ui.assistant = { ...state.ui.assistant, ...result, status: result.conflict ? 'conflict' : 'ready', baseRevision: agent.revision, agentId: agent.id };
          break;
        }
        case 'assistant-fail': state.ui.assistant.status = 'failed'; state.ui.assistant.message = '模拟助手失败。草稿已保留，可重新整理或继续手动编辑。'; break;
        case 'assistant-cancel': state.ui.assistant.status = 'cancelled'; state.ui.assistant.message = '已取消演示整理，手动编辑仍可继续。'; break;
        case 'assistant-clear': state.ui.assistant.suggestions = []; state.ui.assistant.status = 'idle'; state.ui.assistant.message = ''; break;
        case 'assistant-accept': {
          const item = state.ui.assistant.suggestions.find(suggestion => suggestion.id === data.id);
          if (!item || item.status !== 'pending') throw new Error('这条建议已处理或不存在');
          if (item.risk || item.blocked || !SUGGESTIBLE.test(item.path)) throw new Error('此项受保护或涉及权限与承诺，请由人核实并手动提出变更');
          if (item.baseRevision !== agent.revision || JSON.stringify(getPath(agent.config, item.path)) !== JSON.stringify(item.before)) throw new Error('建议已过期，请重新生成；不会覆盖当前配置');
          setPath(agent.config, item.path, clone(item.after)); changed(agent, item.path, false, { before: item.before, source: item.origin }); item.status = 'accepted';
          for (const sibling of state.ui.assistant.suggestions.filter(suggestion => suggestion.status === 'pending')) {
            if (JSON.stringify(getPath(agent.config, sibling.path)) === JSON.stringify(sibling.before)) sibling.baseRevision = agent.revision;
          }
          state.ui.assistant.baseRevision = agent.revision; toast('建议已写入草稿，旧检查已失效；运行入口没有改变。'); break;
        }
        case 'assistant-reject': {
          const item = state.ui.assistant.suggestions.find(suggestion => suggestion.id === data.id); if (item) item.status = 'rejected'; break;
        }
        case 'source-tab':
          if (!['FAQ', 'URL', 'File'].includes(data.tab)) throw new Error('不支持此资料类型');
          if (state.ui.sourceTab !== data.tab) { state.ui.search = ''; state.ui.sourceFilter = 'all'; }
          state.ui.sourceTab = data.tab; state.ui.sourceDetail = null; state.ui.sourceForm = false; state.ui.sourceEdit = null; state.ui.sourceFileBody = ''; state.ui.sourceFileMeta = null; break;
        case 'source-list': state.ui.sourceDetail = null; state.ui.sourceForm = false; state.ui.sourceEdit = null; state.ui.sourceFileBody = ''; state.ui.sourceFileMeta = null; break;
        case 'source-form-toggle':
          if (!state.ui.sourceForm) state.ui.sourceDetail = null;
          state.ui.sourceForm = !state.ui.sourceForm; state.ui.sourceEdit = null; state.ui.sourceFileBody = ''; state.ui.sourceFileMeta = null; break;
        case 'file-selected': state.ui.sourceFileBody = data.body || ''; state.ui.sourceFileMeta = data.meta; break;
        case 'source-detail':
          state.ui.sourceDetail = state.ui.sourceDetail === data.id ? null : data.id;
          state.ui.sourceForm = false; state.ui.sourceEdit = null; state.ui.sourceFileBody = ''; state.ui.sourceFileMeta = null; break;
        case 'source-edit': {
          const source = agent.config.sources.find(item => item.id === data.id); if (!source) throw new Error('资料已不存在');
          if (source.status === 'revoked') throw new Error('已撤回资料请新建并重新确认授权');
          state.ui.sourceDetail = source.id; state.ui.sourceEdit = source.id; state.ui.sourceForm = true; state.ui.sourceTab = source.type; state.ui.sourceFileMeta = null; state.ui.sourceFileBody = ''; break;
        }
        case 'source-open': {
          const source = agent.config.sources.find(item => item.id === data.id);
          state.ui.page = 'knowledge'; state.ui.sourceTab = source?.type || 'FAQ'; state.ui.sourceDetail = source?.id || null; state.ui.search = ''; state.ui.sourceFilter = 'all';
          state.ui.sourceForm = false; state.ui.sourceEdit = null; state.ui.sourceFileMeta = null; state.ui.sourceFileBody = '';
          if (!source) toast('原来源已移除，运行中的历史引用仍保留；查看当前资料库。', 'warning'); break;
        }
        case 'source': {
          const type = data.type || state.ui.sourceTab;
          if (!['FAQ', 'URL', 'File'].includes(type)) throw new Error('不支持的资料类型');
          if (!data.title?.trim()) throw new Error('请填写资料名称');
          if (type === 'FAQ' && (!data.question?.trim() || !data.answer?.trim())) throw new Error('问答的问题与答案均需填写');
          if (type === 'URL' && !/^https?:\/\//.test(data.url || '')) throw new Error('请输入 http:// 或 https:// 页面地址，仅登记当前页面，不扩大抓取范围');
          const previous = data.id ? agent.config.sources.find(item => item.id === data.id) : null;
          if (data.id && !previous) throw new Error('要编辑的资料已不存在');
          if (previous?.status === 'revoked') throw new Error('已撤回资料需重新登记授权');
          if (String(data.body || '').length > 50000) throw new Error('本地演示最多登记 50000 字文本，请拆分资料，避免隐藏截断');
          const source = { id: previous?.id || uid('source'), type, title: data.title.trim(), question: data.question || '', answer: data.answer || '', body: String(data.body || ''), url: data.url || '', filename: data.filename || previous?.filename || '', status: 'received', rights: yes(data.rights), sourceRef: data.sourceRef || '', expires: data.expires || '', revokeNote: '可在本地资料库撤回', version: (previous?.version || 0) + 1, fictional: previous?.fictional || false, error: '', metadataOnly: Boolean(data.metadataOnly || (previous?.metadataOnly && !data.body) || (type === 'URL' && !data.body)) };
          if (source.rights) requireSourceRights(source);
          if (source.metadataOnly) { source.status = 'failed'; source.error = type === 'URL' ? '网页抓取尚未接入；本轮只登记地址。可以用问答或本地文本试用。' : '此格式的解析尚未接入；本轮只登记文件信息。请使用 TXT/MD/CSV 文本试用。'; }
          if (previous) { Object.assign(previous, source); if (!source.rights) { agent.revokedSourceIds ||= []; agent.revokedSourceIds.push(source.id); } }
          else agent.config.sources.push(source);
          changed(agent, 'sources'); state.ui.sourceForm = false; state.ui.sourceEdit = null; state.ui.sourceDetail = source.id;
          state.ui.sourceFileMeta = null; state.ui.sourceFileBody = '';
          toast(source.metadataOnly ? source.error : '资料已接收。确认来源和内容后再标为可用。', source.metadataOnly ? 'warning' : 'neutral'); break;
        }
        case 'source-stage': {
          const source = agent.config.sources.find(item => item.id === data.id); if (!source) throw new Error('资料已不存在');
          if (source.status === 'revoked' || (agent.revokedSourceIds || []).includes(source.id)) throw new Error('已撤回资料不能重新启用，请重新登记授权资料');
          if (source.metadataOnly) throw new Error(source.error);
          if (!['received', 'parsed', 'review', 'indexed', 'failed'].includes(data.stage)) throw new Error('资料状态不支持');
          if (data.stage === 'indexed') {
            requireSourceRights(source);
            if (source.type === 'File' && !source.body.trim()) throw new Error('本地文本为空，不能标为可用资料');
          }
          source.status = data.stage; source.error = data.stage === 'failed' ? '模拟资料处理失败；可以重试，不会改变已发布知识快照。' : ''; changed(agent, 'sources'); break;
        }
        case 'source-retry': {
          const source = agent.config.sources.find(item => item.id === data.id); if (!source) throw new Error('资料已不存在');
          if (source.metadataOnly) throw new Error(source.error + ' 重试不会伪造解析成功。');
          if (source.status === 'revoked') throw new Error('已撤回资料需重新登记，不能用重试恢复授权');
          source.status = 'received'; source.error = ''; changed(agent, 'sources'); break;
        }
        case 'source-revoke': case 'source-remove': {
          const source = agent.config.sources.find(item => item.id === data.id); if (!source) throw new Error('资料已不存在');
          agent.revokedSourceIds ||= []; if (!agent.revokedSourceIds.includes(source.id)) agent.revokedSourceIds.push(source.id);
          source.status = 'revoked'; source.rights = false;
          if (action === 'source-remove') agent.config.sources = agent.config.sources.filter(item => item.id !== data.id);
          changed(agent, 'sources'); toast('后续试用不再使用此资料；关联历史版本保留，但不能凭回滚恢复授权。'); break;
        }
        case 'load-demo-sources': {
          const sources = demoSources().map(source => ({ ...source, id: uid('demo-source') }));
          agent.config.sources.push(...sources); changed(agent, 'sources'); toast('已加入明确标注虚构的示例资料，不代表已摄入自己的资料。'); break;
        }
        case 'field': {
          agent.nextFieldNumber ||= 1;
          while (agent.config.fields.some(field => field.id === `field_${agent.nextFieldNumber}`)) agent.nextFieldNumber += 1;
          const id = (data.id || `field_${agent.nextFieldNumber++}`).trim();
          if (!/^[a-z][a-z0-9_]{0,47}$/.test(id) || agent.config.fields.some(field => field.id === id)) throw new Error('字段标识需为唯一的小写字母/数字/下划线标识');
          if (!data.label?.trim()) throw new Error('请填写字段业务名称');
          agent.config.fields.push({ id, label: data.label.trim(), source: data.source === 'tool' ? 'tool' : 'visitor', required: yes(data.required) }); changed(agent, 'fields'); break;
        }
        case 'field-remove': {
          const before = [...agent.config.fields]; agent.config.fields = agent.config.fields.filter(item => item.id !== data.id); remapArrayMetadata(agent, 'fields', before); changed(agent, 'fields'); toast('字段已从草稿删除；引用与验收需重新检查，历史版本保持不变。'); break;
        }
        case 'flow':
          if (!data.title?.trim() || !data.instruction?.trim()) throw new Error('请填写步骤标题与处理说明');
          agent.config.flow.push({ id: uid('step'), title: data.title.trim(), instruction: data.instruction.trim() }); changed(agent, `flow.${agent.config.flow.length - 1}.instruction`); break;
        case 'flow-remove': {
          if (agent.config.flow.length === 1) throw new Error('至少保留一个处理步骤');
          const before = [...agent.config.flow]; agent.config.flow = agent.config.flow.filter(item => item.id !== data.id); remapArrayMetadata(agent, 'flow', before); changed(agent, 'flow'); break;
        }
        case 'flow-up': case 'flow-down': {
          const index = agent.config.flow.findIndex(item => item.id === data.id); const destination = index + (action === 'flow-up' ? -1 : 1);
          if (index >= 0 && destination >= 0 && destination < agent.config.flow.length) { const before = [...agent.config.flow]; [agent.config.flow[index], agent.config.flow[destination]] = [agent.config.flow[destination], agent.config.flow[index]]; remapArrayMetadata(agent, 'flow', before); changed(agent, 'flow'); }
          break;
        }
        case 'skill':
          if (!data.title?.trim() || !data.description?.trim() || !data.exit?.trim()) throw new Error('请补齐策略名称、说明与退出条件');
          agent.config.skills.push({ id: uid('skill'), title: data.title, description: data.description, exit: data.exit }); changed(agent, `skills.${agent.config.skills.length - 1}.description`); break;
        case 'skill-remove': { const before = [...agent.config.skills]; agent.config.skills = agent.config.skills.filter(item => item.id !== data.id); remapArrayMetadata(agent, 'skills', before); changed(agent, 'skills'); break; }
        case 'tool':
          if (!data.title?.trim()) throw new Error('请填写动作名称');
          agent.config.tools.push({ id: uid('tool'), title: data.title, sideEffect: data.sideEffect === 'write' ? 'write' : 'read', mode: 'mock', requiresConfirm: true, status: 'mock' }); changed(agent, 'tools'); toast('已登记模拟动作。真实工具合同与授权沙盒仍待后端接入。'); break;
        case 'tool-remove': { const before = [...agent.config.tools]; agent.config.tools = agent.config.tools.filter(item => item.id !== data.id); remapArrayMetadata(agent, 'tools', before); changed(agent, 'tools'); break; }
        case 'rule-propose': toast('确定性规则合同与审批待接后端；此处保留规则依据，不直接修改锁定规则。', 'warning'); break;
        case 'recheck': {
          const result = readiness(agent, state.connections); toast(result.issues.length ? result.issues.join('；') : '草稿结构和资料已具备脚本试用条件，真实模型尚未接入。', result.issues.length ? 'warning' : 'success'); break;
        }
        case 'case-create': return dispatch(state.ui.caseForm ? 'collection-cancel' : 'collection-new', { page: 'cases' });
        case 'case-edit': return dispatch('collection-edit', { page: 'cases', id: data.id });
        case 'case-from-run': {
          const run = state.runs.find(item => item.id === data.id && item.agentId === agent.id); if (!run) throw new Error('当前专家没有这条运行记录');
          if (state.cases.some(item => item.runId === run.id)) throw new Error('这条运行已被提名，避免重复创建');
          state.cases.unshift({ id: uid('case'), agentId: agent.id, runId: run.id, title: run.input.slice(0, 40), input: run.input, expected: run.status === 'answered' ? 'answered' : run.status === 'handoff' ? 'handoff' : 'unknown', must: '', forbid: '不补造事实，不执行业务写入', status: 'draft', result: null }); invalidateSuite(agent.id); toast('已提名案例，需由人核实预期；运行结果不会自动成为真值。'); break;
        }
        case 'case': {
          if (!data.title?.trim() || !data.input?.trim() || !data.must?.trim() || !data.forbid?.trim()) throw new Error('请填写案例、输入、必须及禁止的动作');
          const previous = data.id ? state.cases.find(item => item.id === data.id && item.agentId === agent.id) : null;
          const item = { id: previous?.id || uid('case'), agentId: agent.id, runId: previous?.runId || null, title: data.title, input: data.input, expected: ['answered', 'unknown', 'handoff'].includes(data.expected) ? data.expected : 'unknown', must: data.must, forbid: data.forbid, status: 'draft', result: null };
          if (previous) Object.assign(previous, item); else state.cases.unshift(item);
          invalidateSuite(agent.id); state.ui.caseForm = false; state.ui.caseEdit = null;
          Object.assign(state.ui.collections.cases, { detailId: item.id, form: false }); break;
        }
        case 'case-review': {
          const item = state.cases.find(item => item.id === data.id && item.agentId === agent.id); if (!item) throw new Error('案例不存在');
          if (!item.must.trim() || !item.forbid.trim()) throw new Error('请先在案例编辑中补齐必须与禁止的动作');
          item.status = 'reviewed'; invalidateSuite(agent.id); toast('案例已在本地人工审定；正式真值与角色授权仍待后端。'); break;
        }
        case 'case-evaluate': {
          if (data.id && !state.cases.some(item => item.id === data.id && item.agentId === agent.id && item.status === 'reviewed')) throw new Error('先人工审定这条案例，再执行行级回放');
          const cases = state.cases.filter(item => item.agentId === agent.id && item.status === 'reviewed' && (!data.id || item.id === data.id)); if (!cases.length) throw new Error('先创建并人工审定至少一个案例，再模拟回放');
          for (const item of cases) { item.result = simulateReply(agent.config, item.input, agent.revokedSourceIds || []).status === item.expected ? 'pass' : 'fail'; item.evaluatedRevision = agent.revision; item.stale = false; }
          toast('脚本回放已完成。只比较预期状态，不作为真实模型质量或正式发布 Gate。'); break;
        }
        case 'proposal-create': return dispatch(state.ui.proposalForm ? 'collection-cancel' : 'collection-new', { page: 'iterations' });
        case 'proposal-from-run': {
          const run = state.runs.find(item => item.id === data.id && item.agentId === agent.id); if (!run) throw new Error('运行记录不存在');
          state.proposals.unshift({ id: uid('proposal'), agentId: agent.id, runId: run.id, title: '补充资料不足时的说明', reason: `来自模拟运行：${run.input}`, baseRevision: agent.revision, status: 'pending', diff: [{ path: 'fallback', label: '资料不足回复', before: agent.config.fallback, after: `现有资料暂时无法核实。我会将问题记录给${agent.config.handoff.recipient}，也可以请你补充。` }], evaluation: null }); toast('已创建待审改进提案，尚未修改草稿。'); break;
        }
        case 'proposal': {
          if (!data.title?.trim() || !data.reason?.trim() || !data.after?.trim()) throw new Error('请填写提案名称、原因和建议新值');
          if (!SUGGESTIBLE.test(data.path || '')) throw new Error('仅允许表达与处理策略的候选修改；权限和规则另行审议');
          const before = getPath(agent.config, data.path); if (before === undefined) throw new Error('对应配置不存在');
          state.proposals.unshift({ id: uid('proposal'), agentId: agent.id, runId: null, title: data.title, reason: data.reason, baseRevision: agent.revision, status: 'pending', diff: [{ path: data.path, label: data.path, before, after: data.after }], evaluation: null }); state.ui.proposalForm = false;
          Object.assign(state.ui.collections.iterations, { detailId: state.proposals[0].id, form: false }); break;
        }
        case 'proposal-evaluate': {
          const proposal = state.proposals.find(item => item.id === data.id && item.agentId === agent.id); if (!proposal) throw new Error('提案不存在');
          if (proposal.baseRevision !== agent.revision) throw new Error('提案基准已过期，请重新准备候选');
          const suite = state.cases.filter(item => item.agentId === agent.id && item.status === 'reviewed');
          if (!suite.length) throw new Error('先人工审定至少一个案例，再模拟旧版/候选版配对比较');
          const candidate = clone(agent.config); proposal.diff.forEach(item => setPath(candidate, item.path, item.after));
          proposal.comparison = suite.map(item => ({ caseId: item.id, before: simulateReply(agent.config, item.input, agent.revokedSourceIds || []).status, after: simulateReply(candidate, item.input, agent.revokedSourceIds || []).status, expected: item.expected }));
          proposal.evaluation = proposal.comparison.every(row => row.after === row.expected) ? 'pass' : 'fail'; proposal.evaluatedSuite = suiteSignature(agent.id); proposal.stale = false; toast('已进行脚本配对比较；没有真实质量改善证据，后端阶段另验正式 Gate。'); break;
        }
        case 'proposal-apply': {
          const proposal = state.proposals.find(item => item.id === data.id && item.agentId === agent.id); if (!proposal || proposal.status !== 'pending') throw new Error('提案已处理或不存在');
          if (proposal.baseRevision !== agent.revision || proposal.evaluation !== 'pass') throw new Error('提案需以当前基准通过本地模拟比较后才能采用');
          if (proposal.evaluatedSuite !== suiteSignature(agent.id)) throw new Error('人工案例或真值已变化，需要按当前固定输入重新比较');
          if (proposal.diff.some(item => !SUGGESTIBLE.test(item.path))) throw new Error('此提案包含不能自动采用的范围');
          for (const item of proposal.diff) {
            const before = clone(getPath(agent.config, item.path));
            setPath(agent.config, item.path, clone(item.after));
            changed(agent, item.path, true, { before, source: `人工采用提案 ${proposal.id}：${proposal.reason}` });
          }
          proposal.status = 'applied'; toast('提案已进入草稿，历史入口版本保持不变；需要重新试用和批准。'); break;
        }
        case 'proposal-reject': { const proposal = state.proposals.find(item => item.id === data.id && item.agentId === agent.id); if (proposal) proposal.status = 'rejected'; break; }
        case 'sandbox-check': {
          const ready = readiness(agent, state.connections); if (ready.issues.length) throw new Error(ready.issues.join('；'));
          agent.checks.testedRevision = agent.revision; toast('当前草稿通过结构/来源的本地脚本检查，真实评测 Gate 尚未接入。'); break;
        }
        case 'sandbox-approve':
          if (!readiness(agent, state.connections).canApprove) throw new Error('请补齐资料与配置，并对当前草稿重新试用或检查');
          agent.checks.approvedRevision = agent.revision; toast('已明确批准当前本地演示版本；不构成生产发布批准。'); break;
        case 'sandbox-publish': {
          if (agent.checks.approvedRevision !== agent.revision) throw new Error('当前草稿尚未获得本地沙盒批准');
          if (!readiness(agent, state.connections).canTrial) throw new Error('当前资料或连接不可用，不能绑定');
          let version = agent.versions.find(item => item.revision === agent.revision);
          if (!version) { version = { id: `v${agent.versions.length + 1}`, revision: agent.revision, config: clone(agent.config), createdAt: now(), status: 'published', evidence: ['本地来源/结构检查', '人工模拟批准'], label: '本地演示版本' }; agent.versions.unshift(version); }
          const target = data.target === 'contact' ? 'contact' : 'widget'; agent.bindings[target] = version.id;
          toast(`已把 ${target === 'contact' ? '联系页' : '网页组件'} 的本地入口绑定到 ${version.id}。没有发布到公网。`); break;
        }
        case 'version-preview':
          if (!agent.versions.some(item => item.id === data.id)) throw new Error('历史版本不存在');
          state.ui.previewVersionId = data.id; state.ui.page = 'configuration'; state.ui.depth = 'detailed'; break;
        case 'version-restore': {
          const version = agent.versions.find(item => item.id === data.id); if (!version) throw new Error('版本不存在');
          agent.config = clone(version.config);
          for (const source of agent.config.sources) if ((agent.revokedSourceIds || []).includes(source.id)) { source.status = 'revoked'; source.rights = false; }
          agent.manualPaths = {}; changed(agent, 'version-restore'); toast('历史配置已派生为新草稿，不切换入口，也不恢复已撤回的资料授权。'); state.ui.page = 'overview'; state.ui.depth = 'overview'; break;
        }
        case 'inbox-select':
          if (data.id !== state.ui.activeConversation) { state.ui.materials.selected = []; state.ui.materials.sendContext = null; state.ui.materials.picker = false; }
          state.ui.activeConversation = data.id; break;
        case 'run-open': return dispatch('collection-open', { page: 'runs', id: data.id });
        case 'inbox-simulate': {
          const id = uid('conversation'); agent.conversations.unshift({ id, visitor: `模拟访客 ${agent.conversations.length + 1}`, visitorName: `模拟访客 ${agent.conversations.length + 1}`, subject: '课程咨询', status: 'ai', ownership: 'ai', generation: 1, requestStatus: 'waiting', unread: 1, messages: [{ role: 'visitor', text: '你好，我想了解服务。', time: now(), createdAt: now() }], summary: '本地模拟会话，未执行业务动作。' }); state.ui.activeConversation = id; break;
        }
        case 'inbox-handoff': {
          const conversation = agent.conversations.find(item => item.id === state.ui.activeConversation); if (!conversation) throw new Error('先选择会话');
          conversation.ownership = conversation.status = 'human'; conversation.generation += 1;
          conversation.messages.push({ role: 'system', text: '模拟人工承接已记录，AI 接待暂停；业务请求终态未改变。', time: now() }); break;
        }
        case 'inbox-release': {
          const conversation = agent.conversations.find(item => item.id === state.ui.activeConversation); if (!conversation) throw new Error('先选择会话');
          conversation.ownership = conversation.status = 'ai'; conversation.generation += 1;
          conversation.messages.push({ role: 'system', text: '经本地占用检查恢复 AI 接待；不自动恢复业务写入或旧确认。', time: now() }); break;
        }
        case 'inbox': {
          const conversation = agent.conversations.find(item => item.id === state.ui.activeConversation); if (!conversation || (conversation.ownership || conversation.status) !== 'human') throw new Error('先明确承接会话再回复，避免 AI 与人工同时发送');
          if ((data.agentId && data.agentId !== agent.id) || (data.conversationId && data.conversationId !== conversation.id) || (data.generation !== undefined && Number(data.generation) !== conversation.generation)) throw new Error('会话或占用代次已变化，请核对当前会话后重新发送');
          if (!data.message?.trim()) throw new Error('请填写回复内容');
          conversation.messages.push({ role: 'human', text: data.message, time: now(), createdAt: now(), generation: conversation.generation }); conversation.unread = 0; break;
        }
        case 'widget-check': {
          const version = agent.versions.find(item => item.id === agent.bindings.widget); const valid = versionValid(agent, version, state.connections);
          state.ui.widgetChecks = [
            { id: 'script', label: '脚本加载', status: 'simulation', detail: '仅演示检测步骤，尚未提供真实嵌入 SDK' },
            { id: 'request', label: '请求到达', status: valid ? 'simulation' : 'missing', detail: valid ? `本地绑定 ${version.id} 可用` : '先批准并绑定可用版本' },
            { id: 'event', label: '运行留证', status: state.runs.some(run => run.agentId === agent.id) ? 'simulation' : 'missing', detail: '本地脚本试用记录；不是网站请求证据' },
            { id: 'delivery', label: '结果送达', status: 'missing', detail: '没有真实访客送达回执，待后端和 SDK 联调' },
          ]; break;
        }
        case 'contact-template': {
          const template = data.template || 'support';
          agent.config.contact.blocks = template === 'minimal' ? [{ id: uid('block'), type: 'text', title: '联系我们', body: agent.config.greeting }] : [
            { id: uid('block'), type: 'text', title: template === 'course' ? '了解课程' : '服务与支持', body: agent.config.goal },
            { id: uid('block'), type: 'faq', title: '常见问题', body: '展示当前已审阅资料中的常见问题。' },
            { id: uid('block'), type: 'chat', title: '开始咨询', body: '进入已批准版本的客服入口。' },
          ]; changed(agent, 'contact'); break;
        }
        case 'contact-add-block': {
          const type = ['text', 'faq', 'chat', 'link'].includes(data.type) ? data.type : 'text';
          agent.config.contact.blocks.push({ id: uid('block'), type, title: '新内容', body: type === 'link' ? 'https://example.com' : '编辑这一块的内容。' }); changed(agent, 'contact'); break;
        }
        case 'contact-remove-block': agent.config.contact.blocks = agent.config.contact.blocks.filter(item => item.id !== data.id); changed(agent, 'contact'); break;
        case 'contact-move-block': {
          const blocks = agent.config.contact.blocks; const index = blocks.findIndex(item => item.id === data.id); const destination = index + (data.direction === 'up' ? -1 : 1);
          if (index >= 0 && destination >= 0 && destination < blocks.length) { [blocks[index], blocks[destination]] = [blocks[destination], blocks[index]]; changed(agent, 'contact'); } break;
        }
        case 'contact-preview': state.ui.contactPreview = !state.ui.contactPreview; break;
        case 'contact-unpublish': agent.bindings.contact = null; toast('本地联系页绑定已停用，历史版本仍保留。'); break;
        case 'connection': {
          if (!data.name?.trim() || !data.model?.trim()) throw new Error('填写连接名称与模型标识；本轮无需真实密钥');
          if (data.baseUrl && !/^https?:\/\//.test(data.baseUrl)) throw new Error('地址需以 http:// 或 https:// 开头');
          state.connections.push({ id: uid('connection'), name: data.name, provider: data.provider || '自定义', model: data.model, baseUrl: data.baseUrl || '', status: 'not-tested', streaming: 'not-tested', tools: 'not-tested', cancel: 'not-tested', error: '' });
          Object.assign(state.ui.collections.connections, { detailId: state.connections.at(-1).id, form: false }); toast('连接声明已登记。本轮测试仅模拟，不会请求供应商。'); break;
        }
        case 'connection-test': {
          const connection = state.connections.find(item => item.id === data.id); if (!connection) throw new Error('连接已不存在');
          if (connection.id === LOCAL_CONNECTION) { toast('脚本演示连接本地可用，未测试任何真实模型。'); break; }
          const success = data.result !== 'failure'; connection.status = success ? 'mock-connected' : 'failed'; connection.streaming = success ? 'simulation' : 'failed'; connection.tools = success ? 'mock' : 'not-tested'; connection.cancel = success ? 'simulation' : 'not-tested'; connection.error = success ? '' : '模拟认证失败；检查地址和模型声明，真实验证待后端。'; break;
        }
        case 'connection-remove':
          if (data.id === LOCAL_CONNECTION) throw new Error('内置脚本演示连接不可删除；它不保存真实凭据');
          state.connections = state.connections.filter(item => item.id !== data.id); if (state.ui.collections.connections.detailId === data.id) state.ui.collections.connections.detailId = null;
          for (const item of state.agents) if (item.config.model.connectionId === data.id) item.checks = { testedRevision: null, approvedRevision: null }; toast('连接已撤销；引用它的草稿与历史入口将显示不可用。'); break;
        case 'deployment-next': {
          if (state.ui.deployment.status === 'failed') throw new Error('当前步骤失败，先重试再继续');
          const titles = ['资源与权限预检', '创建资源', '服务就绪检查', '持久化与恢复', '完成交付'];
          state.ui.deployment.history.push({ time: now(), text: `${titles[state.ui.deploymentStep]}：本地模拟，不创建云资源`, status: 'simulation' });
          state.ui.deploymentStep = Math.min(4, state.ui.deploymentStep + 1); state.ui.deployment.status = state.ui.deploymentStep === 4 ? 'complete' : 'idle'; break;
        }
        case 'deployment-back': state.ui.deploymentStep = Math.max(0, state.ui.deploymentStep - 1); state.ui.deployment.status = 'idle'; state.ui.deployment.error = ''; break;
        case 'deployment-fail': state.ui.deployment.status = 'failed'; state.ui.deployment.error = '模拟预检/创建失败。没有创建真实资源，可重试当前步骤。'; break;
        case 'deployment-retry': state.ui.deployment.status = 'idle'; state.ui.deployment.error = ''; toast('模拟重试已恢复当前步骤，不新增云资源。'); break;
        case 'deployment-backup': state.ui.deployment.backup = { time: now(), agentId: agent.id, revision: agent.revision, label: '本地模拟备份清单，非云端备份', checksum: '未生成真实备份哈希' }; break;
        case 'deployment-restore': if (!state.ui.deployment.backup) throw new Error('先模拟生成备份清单'); state.ui.deployment.restore = { time: now(), status: 'simulation', label: '仅演示版本/幂等/授权检查，不恢复实际云数据' }; break;
        case 'deployment-upgrade': state.ui.deployment.upgrade = { time: now(), status: 'simulation', label: '应用版本升级检查；AgentVersion 和外部业务结果不回滚' }; break;
        case 'save-now':
          if (recoveryRaw !== null) {
            const recoveryKey = `${STORAGE_KEY}:recovery:${Date.now()}`;
            try { storage?.setItem(recoveryKey, recoveryRaw); }
            catch { throw new Error('恢复副本保存失败，原始记录仍未覆盖。请释放存储或保留浏览器数据后再重试。'); }
            recoveryRaw = null; state.ui.storageRecovery = false; state.ui.recoveryKey = recoveryKey;
            toast('原始记录已另存浏览器恢复副本；现在可保存本轮草稿，未把示例当作原记录。');
          } else toast('本地草稿已保存；不会改变入口绑定或发布版本。');
          break;
        default: throw new Error(`此操作尚未定义：${action}`);
      }
      resolveConfigurationSection();
      save(); notify(); return { ok: true, value };
    } catch (error) { return fail(error.message); }
  }
  return { get state() { return state; }, currentAgent, readonly, dispatch, save, subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); } };
}
