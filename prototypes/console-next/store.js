import { clone, initialState, makeAgent, demoSources } from './fixtures.js';
import { LOCAL_CONNECTION, buildSuggestions, configPathEditable, getPath, pendingItems, readiness, setPath, simulateReply, sourceValid, validDate, versionValid } from './domain.js';
import { ensureMaterialState, handleMaterialAction } from './material-domain.js';
import { ensureVisitorState, visitorSession, handleVisitorAction, cancelVisitorSession } from './visitor-domain.js';
import { RULE_TEMPLATES, RULE_FIELDS, RULE_OPERATORS, RULE_ACTIONS, classifyCandidates, detectCandidateConflicts, factReferences, legacyQaItems, normalizeQuestion } from './knowledge-model.js';
import { migrateRouteGraph } from './flow-model.js';
import { routeScope } from './navigation.js';

export const STORAGE_KEY = 'loomrise:console-next:v1';
export const MIGRATION_BACKUP_KEY = `${STORAGE_KEY}:before-config-ui-v2`;
let sequence = 0;
const uid = prefix => `${prefix}-${Date.now().toString(36)}-${(++sequence).toString(36)}`;
const now = () => new Date().toISOString();
const yes = value => value === true || value === 'on' || value === 'true';
const WRITE_ACTIONS = new Set(['create', 'update-config', 'update-name', 'source', 'source-stage', 'source-retry', 'source-revoke', 'source-remove', 'load-demo-sources', 'field', 'field-remove', 'flow', 'flow-remove', 'flow-up', 'flow-down', 'skill', 'skill-remove', 'tool', 'tool-remove', 'assistant-accept', 'proposal-apply', 'sandbox-check', 'sandbox-approve', 'sandbox-publish', 'version-restore', 'contact-template', 'contact-add-block', 'contact-remove-block', 'contact-move-block', 'contact-unpublish', 'connection', 'connection-test', 'connection-remove', 'inbox', 'inbox-handoff', 'inbox-release', 'inbox-simulate', 'case', 'case-review', 'case-from-run', 'case-evaluate', 'case-decide', 'proposal', 'proposal-reject', 'proposal-from-run', 'proposal-evaluate', 'trial-feedback', 'feedback-to-case', 'batch-intake', 'qa-save', 'qa-decision', 'qa-low-confirm', 'fact-save', 'rule-save', 'rule-toggle', 'rule-template', 'undo-batch', 'flow-branch', 'flow-add-fallback', 'flow-node-update', 'flow-node-delete', 'flow-bulk-rule', 'flow-bulk-confirm', 'sandbox-deploy', 'release-request', 'release-approve', 'release-rollback', 'business-try-run']);
const SUGGESTIBLE = /^(greeting|tone|scope|fallback|flow\.\d+\.instruction|skills\.\d+\.(description|exit))$/;
WRITE_ACTIONS.add('fact-decision');
WRITE_ACTIONS.add('flow-edge-update');
WRITE_ACTIONS.add('flow-edge-delete');

export function createStore(storage = null, seed = initialState()) {
  let state = clone(seed);
  let loaded = false;
  let recoveryRaw = null;
  let migrationRaw = null;
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
      if (parsed.configurationUiVersion !== 2) migrationRaw = stored;
      recoveryRaw = null;
    }
  } catch {
    state.ui.toast = { tone: 'warning', text: '本地记录无法读取，原文已保留且自动保存暂停。点击“重试保存”会先保留恢复副本；当前示例不是原记录。' };
    state.ui.saveStatus = 'error';
  }
  const listeners = new Set();
  state.configurationUiVersion = 2;
  ensureMaterialState(state);
  ensureVisitorState(state);
  state.feedback ||= [];
  for (const item of state.agents) {
    item.config.qaItems ||= [];
    item.config.keyFacts ||= [];
    item.config.businessRules ||= [];
    for (const tool of item.config.tools) {
      tool.input ??= '';
      tool.successField ??= '';
      tool.failureAction ??= 'handoff';
      tool.unknownAction ??= '先查一次是否已经办成，不重复提交';
    }
    if (!item.config.handoffMigrated) {
      for (const [index, phrase] of (item.config.handoff.phrases || []).filter(Boolean).entries()) item.config.businessRules.push({ id: `rule-handoff-legacy-${index + 1}`, title: '客户要求人工', condition: { field: '客户说了', operator: 'exact', value: phrase }, action: 'handoff', recipient: item.config.handoff.recipient, sourceRef: '原转人工配置', enabled: true, legacyHandoff: true });
      item.config.handoffMigrated = true;
    }
    migrateRouteGraph(item.config);
    item.liveBindingsHistory ||= item.bindings?.widget || item.bindings?.contact ? [clone(item.bindings)] : [];
  }
  state.ui.knowledgeTab ||= 'qa';
  state.ui.flowView ||= 'graph';
  state.ui.flowBranchOpen = false;
  state.ui.sidePanel = ['trial', 'evidence'].includes(state.ui.sidePanel) ? state.ui.sidePanel : 'trial';
  state.ui.sideOpen ||= false;
  state.ui.pendingOpen = false;
  state.ui.sidebarCollapsed = state.ui.sidebarCollapsed === true;
  state.ui.undoBatch = null;
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
  function leaveAgentContext() {
    for (const surface of ['trial', 'widget']) if (visitorSession(state, surface).status === 'running') cancelVisitorSession(state, surface, { uid, now, reason: '已返回工作区，旧试用轮次已中止。' });
    state.ui.sideOpen = false; state.ui.pendingOpen = false; state.ui.navOpen = false;
    state.ui.previewVersionId = null; state.ui.readonly = false; state.ui.assistantOpen = false;
    state.ui.mobilePanel = 'editor'; state.ui.focusTarget = null; state.ui.evidenceTarget = null;
    state.ui.materials.preview = null; state.ui.materials.picker = false; state.ui.materials.sendContext = null;
  }
  if (routeScope(state.ui.page) === 'workspace') leaveAgentContext();
  function resolveConfigurationSection() {
    if (state.ui.page !== 'configuration' || ['service', 'knowledge', 'flow', 'fields', 'skills', 'rules', 'tools', 'outcome', 'model', 'evidence', 'r1-server'].includes(state.ui.section)) return;
    const agent = currentAgent();
    const snapshot = agent?.versions.find(version => version.id === state.ui.previewVersionId);
    const ready = readiness(snapshot ? { ...agent, config: snapshot.config } : agent, state.connections);
    const issue = ready.items.find(item => item.id === 'goal' && item.status === 'missing')?.detail;
    state.ui.section = issue ? /预算/.test(issue) ? 'model' : /字段/.test(issue) ? 'fields' : /步骤/.test(issue) ? 'flow' : /业务写入/.test(issue) ? 'tools' : 'service'
      : ready.items.find(item => item.id === 'knowledge')?.status === 'missing' ? 'knowledge'
        : ready.items.find(item => item.id === 'connection')?.status === 'missing' ? 'model' : 'service';
  }
  resolveConfigurationSection();
  function notify(action) { listeners.forEach(listener => listener(state, action)); }
  function save() {
    if (recoveryRaw !== null) { state.ui.saveStatus = 'error'; state.ui.storageRecovery = true; return false; }
    if (migrationRaw !== null) {
      try { storage?.setItem(MIGRATION_BACKUP_KEY, migrationRaw); }
      catch { state.ui.saveStatus = 'error'; state.ui.toast = { tone: 'danger', text: '迁移前副本保存失败，原本地记录未覆盖。当前编辑仍在内存，可释放存储后重试或导出。' }; return false; }
      migrationRaw = null;
      state.ui.migrationBackupKey = MIGRATION_BACKUP_KEY;
    }
    state.ui.savedAt = now();
    state.ui.saveStatus = 'saved';
    try { storage?.setItem(STORAGE_KEY, JSON.stringify(state)); return true; }
    catch { state.ui.saveStatus = 'error'; state.ui.toast = { tone: 'danger', text: '本地保存失败，内容仍在当前页面。请导出草稿或释放浏览器存储后重试。' }; return false; }
  }
  function toast(text, tone = 'neutral') { state.ui.toast = { text, tone }; }
  function changed(agent, path = '', manual = true, evidence = {}) {
    agent.revision += 1;
    state.ui.quickTrial = null;
    if (state.ui.undoBatch?.agentId === agent.id) {
      if (state.ui.undoBatch.appliedRevision == null) state.ui.undoBatch.appliedRevision = agent.revision;
      else state.ui.undoBatch = null;
    }
    state.ui.materials.autoResults = [];
    for (const surface of ['trial', 'widget']) if (visitorSession(state, surface).pending?.agentId === agent.id) cancelVisitorSession(state, surface, { uid, now, reason: '配置已修改，旧试用轮次已中止。' });
    agent.checks = { testedRevision: null, approvedRevision: null };
    if (state.ui.releaseRequest?.agentId === agent.id) state.ui.releaseRequest.status = 'stale';
    if (path && manual) agent.manualPaths[path] = { revision: agent.revision, time: now(), origin: '人工修改' };
    agent.origins ||= {};
    agent.changeLog ||= [];
    agent.origins[path] = { revision: agent.revision, time: now(), origin: manual ? '人工修改' : '助手建议', source: evidence.source || '当前浏览器草稿' };
    const current = path === 'name' ? agent.name : getPath(agent.config, path);
    const [collection, index] = path.split('.');
    const object = /^\d+$/.test(index || '') ? agent.config[collection]?.[Number(index)] : null;
    agent.changeLog.unshift({ id: uid('change'), path, objectId: evidence.objectId || object?.id || '', objectTitle: object?.title || object?.label || '', summary: evidence.summary || '', revision: agent.revision, origin: manual ? '人工修改' : '助手建议', time: now(), before: evidence.before ?? null, after: current === undefined ? null : clone(current), source: evidence.source || '' });
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
    state.ui.quickTrial = null; state.ui.trialInput = ''; state.ui.evidenceTarget = null;
    state.ui.assistant = { prompt: '', scope: 'all', status: 'idle', suggestions: [], baseRevision: null, message: '' };
    state.ui.sourceDetail = null;
    state.ui.sourceEdit = null; state.ui.sourceForm = false; state.ui.sourceFileMeta = null; state.ui.sourceFileBody = '';
    state.ui.search = ''; state.ui.sourceFilter = 'all';
    for (const entry of Object.values(state.ui.collections)) Object.assign(entry, { query: '', status: 'all', detailId: null, form: false });
    state.ui.caseEdit = null; state.ui.caseForm = false; state.ui.proposalForm = false; state.ui.runDetail = null;
    state.ui.widgetChecks = [];
    state.ui.sideOpen = false; state.ui.pendingOpen = false; state.ui.knowledgeTab = 'qa'; state.ui.reviewBatchId = null;
    state.ui.navOpen = false; state.ui.readonly = false;
    state.ui.selectedFlowNode = null; state.ui.flowEditId = null; state.ui.flowSelection = []; state.ui.flowBranchFilter = 'all';
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
  function rememberBatch(agent, label) {
    state.ui.undoBatch = { agentId: agent.id, config: clone(agent.config), expiresAt: Date.now() + 10000, label };
  }
  function syncRouteProjection(agent) {
    const graph = agent.config.routeGraph;
    for (const collection of ['flow', 'skills']) {
      const before = [...agent.config[collection]];
      const byId = new Map(before.map(item => [item.id, item]));
      agent.config[collection] = graph.nodes.filter(node => byId.has(node.legacyId)).map(node => {
        const item = byId.get(node.legacyId);
        return collection === 'flow' ? { ...item, title: node.title, instruction: node.instruction } : { ...item, title: node.title, description: node.instruction.split('\n退出：')[0], exit: node.instruction.split('\n退出：').slice(1).join('\n退出：') || item.exit };
      });
      remapArrayMetadata(agent, collection, before);
    }
  }
  function syncLegacyNode(agent, path) {
    const match = /^(flow|skills)\.(\d+)\.(title|instruction|description|exit)$/.exec(path);
    if (!match) return;
    const item = agent.config[match[1]][Number(match[2])];
    const node = agent.config.routeGraph.nodes.find(entry => entry.legacyId === item?.id);
    if (!node) throw new Error('旧步骤已迁移或删除，请在对话流程中修改');
    node.title = item.title;
    node.instruction = match[1] === 'flow' ? item.instruction : `${item.description}\n退出：${item.exit}`;
  }
  function updateBatchSource(agent, sourceId) {
    const source = agent.config.sources.find(item => item.id === sourceId);
    if (!source || source.status === 'revoked') return;
    const candidates = agent.config.qaItems.filter(item => item.sourceId === sourceId);
    const facts = agent.config.keyFacts.filter(item => item.sourceId === sourceId);
    source.status = source.rights && source.sourceRef && validDate(source.expires) && candidates.every(item => item.reviewStatus !== 'pending') && facts.every(item => item.reviewStatus !== 'pending') ? 'indexed' : 'review';
  }
  function syncLegacyHandoffRules(agent) {
    const prior = new Map(agent.config.businessRules.filter(rule => rule.legacyHandoff).map(rule => [rule.condition.value, rule]));
    agent.config.businessRules = agent.config.businessRules.filter(rule => !rule.legacyHandoff);
    for (const phrase of (agent.config.handoff.phrases || []).filter(Boolean)) {
      const existing = prior.get(phrase);
      agent.config.businessRules.push({ id: existing?.id || uid('legacy-handoff'), title: '客户要求人工', condition: { field: '客户说了', operator: 'exact', value: phrase }, action: 'handoff', recipient: agent.config.handoff.recipient, sourceRef: existing?.sourceRef || '原转人工配置', enabled: existing?.enabled !== false, legacyHandoff: true });
    }
  }

  function dispatch(action, data = {}) {
    const agent = currentAgent();
    const previousScope = routeScope(state.ui.page);
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
        case 'pending-toggle': state.ui.pendingOpen = !state.ui.pendingOpen; break;
        case 'pending-open': {
          const item = pendingItems(agent, state).find(entry => entry.id === data.id);
          if (!item) throw new Error('这件事已处理，待处理队列已更新');
          state.ui.page = item.page; state.ui.pendingOpen = false; state.ui.navOpen = false;
          state.ui.focusTarget = item.target;
          if (item.id.startsWith('fact:')) { state.ui.knowledgeTab = 'facts'; state.ui.factEditId = item.target; }
          else if (item.id.startsWith('review:')) { state.ui.knowledgeTab = 'review'; state.ui.reviewBatchId = item.target; }
          else if (item.id.startsWith('rights:')) { state.ui.knowledgeTab = 'sources'; state.ui.sourceDetail = item.target; }
          else if (item.id.startsWith('knowledge:conflict:')) { state.ui.knowledgeTab = 'review'; state.ui.reviewBatchId = item.target; }
          else if (item.id.startsWith('rule-unused:')) state.ui.ruleEditId = item.target;
          else if (item.id.startsWith('case:')) state.ui.testDetailId = item.target;
          else if (item.id.startsWith('feedback:')) state.ui.focusTarget = `feedback:${item.target}`;
          else if (item.id.startsWith('flow:')) {
            state.ui.selectedFlowNode = item.target.match(/^routeGraph\.nodes\.([^.]+)/)?.[1] || null;
            state.ui.flowBranchFilter = 'all';
          } else if (item.id === 'knowledge:ready') { state.ui.knowledgeTab = 'sources'; state.ui.sourceForm = true; }
          else if (item.id === 'connection:ready') { state.ui.page = 'configuration'; state.ui.section = 'model'; }
          else if (item.target === 'fields') { state.ui.page = 'configuration'; state.ui.section = 'fields'; }
          break;
        }
        case 'open-trial': case 'trial-open':
          if (data.question) state.ui.trialInput = String(data.question);
          state.ui.sidePanel = 'trial'; state.ui.sideOpen = true; state.ui.mobilePanel = 'side'; break;
        case 'quick-trial': {
          const question = String(data.question || state.ui.trialInput || '').trim();
          if (!question) throw new Error('先输入一个问题');
          const result = simulateReply(agent.config, question, agent.revokedSourceIds || []);
          const run = { id: uid('run'), agentId: agent.id, revision: agent.revision, surface: 'quick-trial', createdAt: now(), input: question, answer: result.text, status: result.status, sources: clone(result.sources), ruleHits: clone(result.ruleHits || []), mode: 'simulation', resultEvidence: { generated: true, delivered: false, resolved: 'unknown' } };
          state.runs.unshift(run);
          state.ui.trialInput = question;
          state.ui.quickTrial = { question, answer: result.text, status: result.status, sources: result.sources, ruleHits: result.ruleHits || [], runId: run.id };
          state.ui.sidePanel = 'trial'; state.ui.sideOpen = true; state.ui.mobilePanel = 'side'; break;
        }
        case 'trial-confirm': toast('已记录这次人工查看；脚本答复不会自动成为测试真值。'); break;
        case 'quick-trial-clear': state.ui.quickTrial = null; state.ui.trialInput = ''; break;
        case 'open-evidence': case 'evidence-open':
          state.ui.evidenceTarget = { kind: data.kind || 'change', id: data.id || '' };
          state.ui.sidePanel = 'evidence'; state.ui.sideOpen = true; state.ui.mobilePanel = 'side'; break;
        case 'close-side-panel': state.ui.sideOpen = false; state.ui.mobilePanel = 'editor'; break;
        case 'trial-feedback': {
          if (data.verdict !== 'wrong') break;
          const question = String(data.question || state.ui.trialInput || '').trim();
          if (!question) throw new Error('先提出问题再记录答错了');
          state.feedback.push({ id: uid('feedback'), agentId: agent.id, question, answer: String(data.answer || ''), status: 'open', time: now() });
          toast('已记入待处理，可转为测试题由人核对预期。'); break;
        }
        case 'feedback-to-case': {
          const feedback = state.feedback.find(item => item.id === data.id && item.agentId === agent.id && item.status === 'open');
          if (!feedback) throw new Error('这条反馈已处理或不存在');
          state.cases.unshift({ id: uid('case'), agentId: agent.id, runId: null, title: feedback.question.slice(0, 40), input: feedback.question, expected: 'unknown', must: '', forbid: '不补造事实，不执行业务写入', status: 'draft', result: null, feedbackId: feedback.id });
          feedback.status = 'converted'; invalidateSuite(agent.id); state.ui.page = 'test'; toast('已转为待人工核对的测试题。'); break;
        }
        case 'test-open': state.ui.testDetailId = data.id; state.ui.page = 'test'; break;
        case 'test-back': state.ui.testDetailId = null; break;
        case 'knowledge-tab': state.ui.knowledgeTab = data.tab; state.ui.sourceForm = false; state.ui.sourceDetail = null; break;
        case 'source-review-open': state.ui.knowledgeTab = 'review'; state.ui.reviewBatchId = data.id || state.ui.reviewBatchId || agent.config.qaItems.find(item => item.reviewStatus === 'pending')?.sourceId || null; break;
        case 'qa-edit': state.ui.qaEditId = state.ui.qaEditId === data.id ? null : data.id; break;
        case 'fact-edit': state.ui.factEditId = state.ui.factEditId === data.id ? null : data.id; if (!yes(data.review)) state.ui.knowledgeTab = 'facts'; break;
        case 'rule-edit': state.ui.ruleEditId = state.ui.ruleEditId === data.id ? null : data.id; break;
        case 'batch-intake': {
          if (!Array.isArray(data.candidates) || data.candidates.length < 1 || data.candidates.length > 500) throw new Error('本次没有可核对内容，或超出 500 条上限');
          const title = String(data.title || '').trim(); if (!title) throw new Error('请给这批资料一个文件名');
          const sourceId = uid('batch');
          const source = { id: sourceId, batchId: sourceId, type: 'File', title, question: '', answer: '', body: String(data.body || ''), url: '', filename: title, status: 'review', rights: yes(data.rights), sourceRef: String(data.sourceRef || '').trim(), expires: String(data.expires || ''), revokeNote: '在资料库撤回', version: 1, fictional: false, error: '', metadataOnly: false };
          if (source.rights) requireSourceRights(source);
          agent.config.sources.push(source);
          for (const [index, item] of data.candidates.entries()) {
            if (item.kind === 'fact') agent.config.keyFacts.push({ id: uid('fact'), name: String(item.name || '').trim(), value: String(item.value || '').trim(), unit: String(item.unit || ''), effectiveFrom: '', sourceRef: source.sourceRef, sourceId, sourceRow: item.sourceRow || index + 1, reviewStatus: 'pending' });
            else agent.config.qaItems.push({ id: uid('qa'), question: String(item.question || '').trim(), answer: String(item.answer || '').trim(), sourceId, sourceRow: item.sourceRow || index + 1, reviewStatus: 'pending' });
          }
          changed(agent, 'sources', true, { source: title, objectId: sourceId, summary: `从“${title}”新增 ${data.candidates.filter(item => item.kind !== 'fact').length} 条问答、${data.candidates.filter(item => item.kind === 'fact').length} 条关键信息待核对` });
          state.ui.page = 'knowledge'; state.ui.knowledgeTab = 'review'; state.ui.reviewBatchId = sourceId;
          toast('已拆分为待核对内容；授权和人工核对完成前不会用于答复。'); break;
        }
        case 'qa-decision': {
          let item = agent.config.qaItems.find(entry => entry.id === data.id);
          if (!item) {
            const legacy = agent.config.sources.find(source => source.type === 'FAQ' && `qa-${source.id}` === data.id);
            if (!legacy) throw new Error('这条问答已不存在');
            item = { id: data.id, sourceId: legacy.id, question: legacy.question, answer: legacy.answer, reviewStatus: 'pending' };
            agent.config.qaItems.push(item);
            if (data.decision === 'no-answer') legacy.status = 'review';
          }
          if (!['approve', 'no-answer'].includes(data.decision)) throw new Error('请选择核对结果');
          if (data.decision === 'approve' && detectCandidateConflicts({ ...item, kind: 'qa' }, { qaItems: agent.config.qaItems, sources: agent.config.sources.filter(source => sourceValid(source, agent.revokedSourceIds || [])) }).length) throw new Error('请先明确以哪个说法为准，再确认这条问答');
          item.reviewStatus = data.decision === 'approve' ? 'reviewed' : 'rejected';
          if (agent.config.sources.find(source => source.id === item.sourceId)?.batchId) updateBatchSource(agent, item.sourceId);
          changed(agent, 'qaItems', true, { objectId: item.id, summary: `问答“${item.question}”${item.reviewStatus === 'reviewed' ? '已核对' : '改为不由 AI 答复'}` }); break;
        }
        case 'qa-save': {
          const item = agent.config.qaItems.find(entry => entry.id === data.id) || agent.config.keyFacts.find(entry => entry.id === data.id);
          const alternatives = item && !('name' in item) ? [
            ...agent.config.qaItems.filter(other => other.id !== item.id && other.reviewStatus !== 'rejected' && normalizeQuestion(other.question) === normalizeQuestion(item.question) && normalizeQuestion(other.answer) !== normalizeQuestion(item.answer)),
            ...agent.config.sources.filter(source => source.type === 'FAQ' && source.id !== item.sourceId && normalizeQuestion(source.question) === normalizeQuestion(item.question) && normalizeQuestion(source.answer) !== normalizeQuestion(item.answer) && sourceValid(source, agent.revokedSourceIds || [])),
          ] : [];
          const conflicting = alternatives.find(other => other.id === data.conflictId) || alternatives[0];
          if (data.choice && !conflicting && !(item && 'name' in item)) throw new Error('这条问答当前没有需裁决的不同说法');
          if (item && 'name' in item) {
            if (!['candidate', 'current', 'custom'].includes(data.choice)) throw new Error('请选择以哪个值为准');
            const otherFact = agent.config.keyFacts.find(entry => entry.id !== item.id && entry.name === item.name);
            item.value = data.choice === 'current' ? String(otherFact?.value || item.value) : data.choice === 'custom' ? String(data.answer || '').trim() : item.value;
            if (!item.value) throw new Error('请填写正确数值');
          } else if (item) {
            if (data.choice) {
              if (!['candidate', 'current', 'custom'].includes(data.choice)) throw new Error('请选择以哪个说法为准');
              item.answer = data.choice === 'current' ? String(conflicting.answer) : data.choice === 'custom' ? String(data.answer || '').trim() : item.answer;
            } else { item.question = String(data.question || '').trim(); item.answer = String(data.answer || '').trim(); }
            if (!item.question || !item.answer) throw new Error('问题和标准解答都需填写');
          } else {
            const legacy = agent.config.sources.find(source => `qa-${source.id}` === data.id && source.type === 'FAQ');
            if (!legacy) throw new Error('问答已不存在');
            legacy.question = String(data.question || '').trim(); legacy.answer = String(data.answer || '').trim();
            if (!legacy.question || !legacy.answer) throw new Error('问题和标准解答都需填写');
          }
          if (item && data.choice && conflicting) {
            for (const alternative of alternatives) {
              if (alternative.type === 'FAQ') alternative.status = 'review';
              else { alternative.reviewStatus = 'rejected'; updateBatchSource(agent, alternative.sourceId); }
            }
          }
          if (item) { item.reviewStatus = !data.choice && detectCandidateConflicts({ ...item, kind: 'qa' }, { qaItems: agent.config.qaItems, sources: agent.config.sources.filter(source => sourceValid(source, agent.revokedSourceIds || [])) }).length ? 'pending' : 'reviewed'; updateBatchSource(agent, item.sourceId); }
          state.ui.qaEditId = null; changed(agent, item && 'name' in item ? 'keyFacts' : 'qaItems', true, { objectId: item?.id || data.id, summary: `修改问答“${item?.question || data.question || '当前问题'}”${data.choice ? '，已裁定采用的说法' : ''}` }); break;
        }
        case 'fact-decision': {
          const item = agent.config.keyFacts.find(entry => entry.id === data.id);
          if (!item) throw new Error('这条关键信息已不存在');
          const alternatives = agent.config.keyFacts.filter(other => other.id !== item.id && other.reviewStatus !== 'rejected' && normalizeQuestion(other.name) === normalizeQuestion(item.name));
          if (data.choice) {
            if (!['candidate', 'current', 'custom'].includes(data.choice)) throw new Error('请选择以哪个值为准');
            const current = alternatives.find(other => other.id === data.conflictId) || alternatives[0];
            const next = data.choice === 'current' ? current : data.choice === 'custom' ? { value: String(data.value || '').trim(), unit: String(data.unit || '').trim() } : item;
            if (!next?.value) throw new Error('请填写正确数值');
            item.value = next.value; item.unit = next.unit || '';
            for (const other of alternatives) { other.reviewStatus = 'rejected'; updateBatchSource(agent, other.sourceId); }
            item.reviewStatus = 'reviewed';
          } else {
            if (!['approve', 'no-answer'].includes(data.decision)) throw new Error('请选择核对结果');
            if (data.decision === 'approve' && detectCandidateConflicts({ ...item, kind: 'fact' }, { keyFacts: agent.config.keyFacts }).length) throw new Error('请先明确以哪个值为准');
            item.reviewStatus = data.decision === 'approve' ? 'reviewed' : 'rejected';
          }
          updateBatchSource(agent, item.sourceId);
          changed(agent, 'keyFacts', true, { objectId: item.id, summary: `核对关键信息“${item.name}”：${item.reviewStatus === 'rejected' ? '不用于回答' : `${item.value}${item.unit || ''}`}` }); break;
        }
        case 'qa-low-confirm': {
          const candidates = agent.config.qaItems.filter(item => item.sourceId === data.sourceId && item.reviewStatus === 'pending').map(item => ({ ...item, kind: 'qa' }));
          const facts = agent.config.keyFacts.filter(item => item.sourceId === data.sourceId && item.reviewStatus === 'pending').map(item => ({ ...item, kind: 'fact' }));
          const low = classifyCandidates([...candidates, ...facts], { qaItems: legacyQaItems(agent.config).filter(item => item.sourceId !== data.sourceId), keyFacts: agent.config.keyFacts.filter(item => item.sourceId !== data.sourceId) }).lowRisk;
          if (!low.length) throw new Error('这批没有可整组确认的低风险内容');
          rememberBatch(agent, '整组核对');
          for (const item of low) { const target = agent.config.qaItems.find(entry => entry.id === item.id) || agent.config.keyFacts.find(entry => entry.id === item.id); target.reviewStatus = 'reviewed'; }
          updateBatchSource(agent, data.sourceId); changed(agent, 'qaItems'); toast(`已确认 ${low.length} 条，可在 10 秒内撤销。`); break;
        }
        case 'fact-save': {
          const name = String(data.name || '').trim(), valueText = String(data.value || '').trim();
          if (!name || !valueText) throw new Error('请填写关键信息的名称与当前值');
          const existing = agent.config.keyFacts.find(item => item.id === data.id);
          if (!yes(data.review) && agent.config.keyFacts.some(item => item.id !== existing?.id && item.name === name && item.reviewStatus !== 'rejected' && item.reviewStatus !== 'pending')) throw new Error('关键信息名称不能重复');
          const previous = existing ? clone(existing) : null;
          const impact = existing ? factReferences(agent, existing.name) : [];
          rememberBatch(agent, '关键信息同步');
          if (existing) {
            const old = `${existing.value}${existing.unit ? ` ${existing.unit}` : ''}`;
            for (const reference of impact) {
              const { kind, id } = reference;
              const excluded = (data.excluded || []).includes(`${kind}:${id}`);
              if (!excluded && name === existing.name) continue;
              const replacement = excluded ? old : `{${name}}`;
              const target = kind === 'qa' ? agent.config.qaItems.find(item => item.id === id) || agent.config.sources.find(item => `qa-${item.id}` === id) : kind === 'rule' ? agent.config.businessRules.find(item => item.id === id) : agent.config.tools.find(item => item.id === id);
              if (!target) continue;
              for (const key of kind === 'qa' ? ['answer'] : kind === 'rule' ? ['action', 'title'] : ['title', 'input', 'description']) if (typeof target[key] === 'string') target[key] = target[key].replaceAll(`{${existing.name}}`, replacement);
              if (kind === 'rule' && typeof target.condition?.value === 'string') target.condition.value = target.condition.value.replaceAll(`{${existing.name}}`, replacement);
            }
            Object.assign(existing, { name, value: valueText, unit: String(data.unit || ''), effectiveFrom: String(data.effectiveFrom || ''), sourceRef: String(data.sourceRef || '') });
          } else agent.config.keyFacts.push({ id: uid('fact'), name, value: valueText, unit: String(data.unit || ''), effectiveFrom: String(data.effectiveFrom || ''), sourceRef: String(data.sourceRef || ''), reviewStatus: 'reviewed' });
          if (existing && yes(data.review)) { existing.reviewStatus = detectCandidateConflicts({ ...existing, kind: 'fact' }, { keyFacts: agent.config.keyFacts }).length ? 'pending' : 'reviewed'; updateBatchSource(agent, existing.sourceId); }
          state.ui.factEditId = null; changed(agent, 'keyFacts', true, { before: previous, objectId: existing?.id || agent.config.keyFacts.at(-1).id, summary: `“${name}”${previous ? `从 ${previous.value}${previous.unit || ''} 改为` : '新增为'} ${valueText}${data.unit || ''}，同步 ${impact.length - (data.excluded || []).length} 处`, source: String(data.sourceRef || '') }); toast('关键信息已更新，可在 10 秒内撤销。'); break;
        }
        case 'rule-template': {
          const template = RULE_TEMPLATES.find(item => item.id === data.template); if (!template) throw new Error('常用红线不存在');
          const rule = { ...clone(template), id: uid('business-rule'), title: template.label, recipient: template.action === 'handoff' ? agent.config.handoff.recipient : '', sourceRef: '常用模板，需业务核对', enabled: true };
          agent.config.businessRules.push(rule); state.ui.ruleEditId = rule.id; changed(agent, 'businessRules', true, { objectId: rule.id, summary: `新增红线“${rule.title}”` }); break;
        }
        case 'rule-save': {
          if (!RULE_FIELDS.includes(data.field) || !RULE_OPERATORS.includes(data.operator) || !RULE_ACTIONS.includes(data.action) || !String(data.value || '').trim()) throw new Error('请按可用选项填写红线条件和处理方式');
          const existing = agent.config.businessRules.find(item => item.id === data.id);
          const rule = { id: existing?.id || uid('business-rule'), title: `${data.field} ${data.value}`, condition: { field: data.field, operator: data.operator, value: String(data.value).trim() }, action: data.action, recipient: data.action === 'handoff' ? String(data.recipient || '').trim() : '', sourceRef: String(data.sourceRef || ''), enabled: existing?.enabled !== false };
          if (existing) Object.assign(existing, rule); else agent.config.businessRules.push(rule);
          state.ui.ruleEditId = null; changed(agent, 'businessRules', true, { objectId: rule.id, summary: `${existing ? '修改' : '新增'}红线“${rule.title}”`, source: rule.sourceRef }); break;
        }
        case 'rule-toggle': {
          const rule = agent.config.businessRules.find(item => item.id === data.id); if (!rule) throw new Error('只能修改我的红线，平台底线不能关闭');
          rule.enabled = !rule.enabled; changed(agent, 'businessRules'); break;
        }
        case 'business-try': {
          if (!agent.config.tools.some(item => item.id === data.id)) throw new Error('办理事项已不存在');
          state.ui.businessTryId = state.ui.businessTryId === data.id ? null : data.id; break;
        }
        case 'business-try-run': {
          const tool = agent.config.tools.find(item => item.id === data.id);
          if (!tool) throw new Error('办理事项已不存在');
          if (!['success', 'failed', 'unknown'].includes(data.businessStatus)) throw new Error('请明确选择本地模拟结果');
          if (data.businessStatus === 'success' && tool.sideEffect === 'write' && !tool.successField?.trim()) throw new Error('先设置办成标志，不能凭模型话术记为成功');
          state.runs.unshift({ id: uid('run'), agentId: agent.id, revision: agent.revision, toolId: tool.id, surface: 'business', input: tool.title, answer: `本地模拟：${data.businessStatus === 'success' ? '成功' : data.businessStatus === 'failed' ? '失败' : '结果不明'}`, status: data.businessStatus === 'success' ? 'answered' : 'unknown', businessStatus: data.businessStatus, sources: [], createdAt: now(), mode: 'simulation', resultEvidence: { generated: true, delivered: false, resolved: 'unknown', externalResultId: null } });
          state.ui.businessTryId = null; toast('已记录本地模拟结果，未调用外部业务系统。'); break;
        }
        case 'undo-batch': {
          const snapshot = state.ui.undoBatch;
          if (!snapshot || snapshot.agentId !== agent.id || snapshot.appliedRevision !== agent.revision || Date.now() > snapshot.expiresAt) throw new Error('撤销时间已过或已有后续修改，请核对当前草稿');
          agent.config = clone(snapshot.config); state.ui.undoBatch = null; changed(agent, 'undo-batch'); toast('已恢复批量操作前的值。'); break;
        }
        case 'select-agent':
          selectAgent(data.id);
          if (previousScope === 'workspace') { state.ui.page = 'overview'; state.ui.depth = 'overview'; }
          break;
        case 'agent-next': {
          selectAgent(data.id);
          const pending = pendingItems(currentAgent(), state);
          const next = pending.find(item => item.level === 'block') || pending[0];
          if (next) return dispatch('pending-open', { id: next.id });
          state.ui.page = 'overview'; break;
        }
        case 'new-agent': state.ui.page = 'create'; state.ui.createMode = data.mode || 'manual'; state.ui.previewVersionId = null; break;
        case 'create-mode': state.ui.createMode = data.mode; break;
        case 'create': {
          const name = String(data.name || '').trim() || `新客服 ${state.agents.length + 1}`;
          if (name.length > 60) throw new Error('名称请控制在 60 个字符以内');
          const created = makeAgent({ id: uid('agent'), name, goal: String(data.goal || '').trim(), audience: String(data.audience || '').trim() });
          created.config.businessRules = created.config.handoff.phrases.filter(Boolean).map((phrase, index) => ({ id: `rule-handoff-legacy-${index + 1}`, title: '客户要求人工', condition: { field: '客户说了', operator: 'exact', value: phrase }, action: 'handoff', recipient: created.config.handoff.recipient, sourceRef: '初始转人工配置', enabled: true, legacyHandoff: true }));
          created.config.handoffMigrated = true;
          migrateRouteGraph(created.config);
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
          if (data.panel !== 'editor') { state.ui.sidePanel = data.panel; state.ui.sideOpen = true; }
          break;
        case 'toggle-nav': state.ui.navOpen = !state.ui.navOpen; break;
        case 'toggle-sidebar': state.ui.sidebarCollapsed = !state.ui.sidebarCollapsed; state.ui.navOpen = false; break;
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
          const oldValue = getPath(agent.config, data.path);
          const previous = oldValue === undefined ? null : clone(oldValue);
          setPath(agent.config, data.path, clone(data.value));
          if (data.path === 'handoff.phrases') syncLegacyHandoffRules(agent);
          if (data.path === 'handoff.recipient') for (const rule of agent.config.businessRules.filter(item => item.legacyHandoff)) rule.recipient = data.value;
          if (/tools\.\d+\.sideEffect/.test(data.path) && data.value === 'write') agent.config.tools[Number(data.path.split('.')[1])].requiresConfirm = true;
          syncLegacyNode(agent, data.path);
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
          setPath(agent.config, item.path, clone(item.after)); syncLegacyNode(agent, item.path); changed(agent, item.path, false, { before: item.before, source: item.origin }); item.status = 'accepted';
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
          state.ui.knowledgeTab = 'sources';
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
          const source = { id: previous?.id || uid('source'), batchId: previous?.batchId, type, title: data.title.trim(), question: data.question || '', answer: data.answer || '', body: String(data.body || previous?.batchId && previous.body || ''), url: data.url || '', filename: data.filename || previous?.filename || '', status: 'received', rights: yes(data.rights), sourceRef: data.sourceRef || '', expires: data.expires || '', revokeNote: '可在本地资料库撤回', version: (previous?.version || 0) + 1, fictional: previous?.fictional || false, error: '', metadataOnly: Boolean(!previous?.batchId && (data.metadataOnly || (previous?.metadataOnly && !data.body) || (type === 'URL' && !data.body))) };
          if (source.rights) requireSourceRights(source);
          if (source.metadataOnly) { source.status = 'failed'; source.error = type === 'URL' ? '网页抓取尚未接入；本轮只登记地址。可以用问答或本地文本试用。' : '此格式的解析尚未接入；本轮只登记文件信息。请使用 TXT/MD/CSV 文本试用。'; }
          if (previous) { Object.assign(previous, source); if (!source.rights && !previous.batchId) { agent.revokedSourceIds ||= []; agent.revokedSourceIds.push(source.id); } }
          else agent.config.sources.push(source);
          if (source.batchId) {
            for (const item of [...agent.config.qaItems, ...agent.config.keyFacts].filter(item => item.sourceId === source.id)) item.sourceRef = source.sourceRef;
            updateBatchSource(agent, source.id);
          }
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
            if (source.batchId && [...agent.config.qaItems, ...agent.config.keyFacts].some(item => item.sourceId === source.id && item.reviewStatus === 'pending')) throw new Error('这批还有待核对内容，不能用于答复');
            if (source.type === 'File' && !source.body.trim() && !source.batchId) throw new Error('本地文本为空，不能标为可用资料');
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
        case 'flow-view': state.ui.flowView = data.view === 'list' ? 'list' : 'graph'; break;
        case 'flow-filter': state.ui.flowBranchFilter = data.id || 'all'; break;
        case 'flow-branch-disclosure': state.ui.flowBranchOpen = Boolean(data.open); break;
        case 'flow-branch-cancel': state.ui.flowBranchOpen = false; break;
        case 'flow-toggle-layer': {
          if (!['rules', 'runs'].includes(data.layer)) throw new Error('不支持此流程图图层');
          state.ui.flowLayers ||= { rules: false, runs: false };
          state.ui.flowLayers[data.layer] = !state.ui.flowLayers[data.layer]; break;
        }
        case 'flow-select-node': state.ui.selectedFlowNode = data.id; break;
        case 'flow-edit-node': state.ui.selectedFlowNode = data.id; state.ui.flowEditId = state.ui.flowEditId === data.id ? null : data.id; break;
        case 'flow-select': {
          state.ui.flowSelection ||= [];
          state.ui.flowSelection = state.ui.flowSelection.includes(data.id) ? state.ui.flowSelection.filter(id => id !== data.id) : [...state.ui.flowSelection, data.id]; break;
        }
        case 'flow-branch': {
          const intent = String(data.intent || '').trim();
          const examples = String(data.examples || '').split(/[\n/、]/).map(item => item.trim()).filter(Boolean);
          if (!intent || examples.length < 3) throw new Error('请填写客户想做什么，并提供至少 3 句例句');
          if (!['answer', 'business', 'handoff'].includes(data.then)) throw new Error('请选择知识库回答、办理或转人工');
          const graph = migrateRouteGraph(agent.config);
          let decision = data.decisionId ? graph.nodes.find(node => node.id === data.decisionId && node.type === 'decision') : graph.nodes.find(node => node.id === state.ui.selectedFlowNode && node.type === 'decision') || graph.nodes.find(node => node.type === 'decision');
          if (data.decisionId && !decision) throw new Error('这处判断已不存在，请重新选择');
          if (decision && graph.edges.filter(edge => edge.source === decision.id).length >= 5) throw new Error('这处判断最多 5 个分支，请新建下一层判断');
          if (!decision) {
            decision = { id: uid('route'), type: 'decision', title: '客户想做什么', instruction: '按客户当前意图选择下一步', ruleIds: [] };
            const last = graph.nodes.at(-1);
            graph.nodes.push(decision);
            graph.edges.push({ id: uid('edge'), source: last.id, target: decision.id, label: '', examples: [], ruleIds: [] });
          }
          const tool = agent.config.tools.find(item => item.id === data.toolId);
          if (data.then === 'business' && !tool) throw new Error('先选择一项已登记的业务办理');
          const type = data.then === 'business' ? 'business' : data.then === 'handoff' ? 'handoff' : 'reply';
          const node = { id: uid('route'), type, title: type === 'business' ? tool.title : type === 'handoff' ? agent.config.handoff.recipient || '转人工' : intent, instruction: type === 'reply' ? '使用已核对知识库回答；资料不足时转人工' : '', toolId: tool?.id || null, ruleIds: [] };
          graph.nodes.push(node);
          graph.edges.push({ id: uid('edge'), source: decision.id, target: node.id, label: intent, examples, ruleIds: [] });
          state.ui.selectedFlowNode = node.id; state.ui.flowView = 'graph'; state.ui.flowBranchOpen = false;
          changed(agent, 'routeGraph', true, { objectId: node.id, summary: `流程新增“${intent}”分支` }); toast('分支已写入草稿；上线前请处理流程提示。'); break;
        }
        case 'flow-add-fallback': {
          const graph = migrateRouteGraph(agent.config);
          const decision = graph.nodes.find(node => node.type === 'decision' && node.id === (data.id || state.ui.selectedFlowNode)) || (!data.id && graph.nodes.find(node => node.type === 'decision')); if (!decision) throw new Error('先选择需要出口的判断');
          if (graph.edges.some(edge => edge.source === decision.id && edge.label === '其他')) throw new Error('其他分支已存在');
          const node = { id: uid('route'), type: 'handoff', title: agent.config.handoff.recipient || '转人工', instruction: '没有可回答出口时交人工处理', ruleIds: [] };
          graph.nodes.push(node); graph.edges.push({ id: uid('edge'), source: decision.id, target: node.id, label: '其他', examples: [], ruleIds: [] });
          changed(agent, 'routeGraph'); break;
        }
        case 'flow-edge-update': {
          const edge = agent.config.routeGraph.edges.find(item => item.id === data.id);
          if (!edge) throw new Error('连接已不存在');
          edge.label = String(data.label || '').trim();
          edge.examples = String(data.examples || '').split('\n').map(item => item.trim()).filter(Boolean);
          changed(agent, 'routeGraph', true, { objectId: edge.id, summary: `流程分支改为“${edge.label || '待命名'}”` }); break;
        }
        case 'flow-edge-delete': {
          const graph = agent.config.routeGraph, edge = graph.edges.find(item => item.id === data.id);
          if (!edge) throw new Error('连接已不存在');
          graph.edges = graph.edges.filter(item => item.id !== edge.id);
          if (state.ui.flowBranchFilter === edge.id) state.ui.flowBranchFilter = 'all';
          changed(agent, 'routeGraph', true, { objectId: edge.id, summary: `移除“${edge.label || '步骤之间'}”的连接，保留步骤供继续编辑` }); break;
        }
        case 'flow-node-update': {
          const node = agent.config.routeGraph.nodes.find(item => item.id === data.id); if (!node) throw new Error('步骤已不存在');
          const title = String(data.title || '').trim();
          if (!title) throw new Error('步骤名称不能为空');
          node.title = title; node.instruction = String(data.instruction || '').trim();
          syncRouteProjection(agent);
          changed(agent, 'routeGraph', true, { objectId: node.id, summary: `修改流程步骤“${node.title}”` });
          for (const collection of ['flow', 'skills']) {
            const index = agent.config[collection].findIndex(item => item.id === node.legacyId);
            if (index >= 0) for (const key of collection === 'flow' ? ['title', 'instruction'] : ['title', 'description', 'exit']) agent.manualPaths[`${collection}.${index}.${key}`] = { revision: agent.revision, time: now(), origin: '人工修改' };
          }
          break;
        }
        case 'flow-node-delete': {
          const graph = agent.config.routeGraph, node = graph.nodes.find(item => item.id === data.id);
          if (!node || node.type === 'start') throw new Error('开始节点不能删除');
          const outgoing = graph.edges.filter(edge => edge.source === node.id);
          graph.nodes = graph.nodes.filter(item => item.id !== node.id);
          graph.edges = graph.edges.filter(edge => edge.source !== node.id).flatMap(edge => edge.target !== node.id ? [edge] : node.type !== 'decision' && outgoing.length === 1 && outgoing[0].target !== node.id ? [{ ...edge, target: outgoing[0].target }] : []);
          syncRouteProjection(agent);
          state.ui.selectedFlowNode = null; changed(agent, 'routeGraph'); break;
        }
        case 'flow-bulk-rule': {
          const ids = state.ui.flowSelection || [], graph = agent.config.routeGraph;
          if (!ids.length || ![...agent.config.rules, ...agent.config.businessRules].some(rule => rule.id === data.ruleId)) throw new Error('先选步骤和已有红线');
          rememberBatch(agent, '批量加红线');
          for (const node of graph.nodes.filter(item => ids.includes(item.id))) if (!node.ruleIds.includes(data.ruleId)) node.ruleIds.push(data.ruleId);
          changed(agent, 'routeGraph'); toast('已批量加红线，可在 10 秒内撤销。'); break;
        }
        case 'flow-bulk-confirm': {
          const ids = state.ui.flowSelection || [];
          if (!ids.length) throw new Error('先选择要修改的办理步骤');
          rememberBatch(agent, '批量改确认要求');
          for (const node of agent.config.routeGraph.nodes.filter(item => ids.includes(item.id) && item.type === 'business')) {
            const tool = agent.config.tools.find(item => item.id === node.toolId);
            if (tool) tool.requiresConfirm = true;
          }
          changed(agent, 'routeGraph'); toast('确认要求已批量设置，可在 10 秒内撤销。'); break;
        }
        case 'flow': case 'flow-remove': case 'flow-up': case 'flow-down': {
          const graph = agent.config.routeGraph;
          if (graph.nodes.some(node => node.type === 'decision')) throw new Error('当前已有分支，请在对话流程里选择步骤修改');
          if (action === 'flow') {
            if (!data.title?.trim() || !data.instruction?.trim()) throw new Error('请填写步骤名称和说明');
            const step = { id: uid('step'), title: data.title.trim(), instruction: data.instruction.trim() };
            agent.config.flow.push(step);
            const position = graph.nodes.findIndex(node => agent.config.skills.some(skill => skill.id === node.legacyId));
            graph.nodes.splice(position < 0 ? graph.nodes.length : position, 0, { ...step, id: `route-${step.id}`, legacyId: step.id, type: 'reply', ruleIds: [] });
          } else {
            const index = agent.config.flow.findIndex(item => item.id === data.id);
            if (index < 0) throw new Error('步骤已不存在');
            if (action === 'flow-remove') graph.nodes = graph.nodes.filter(node => node.legacyId !== data.id);
            else {
              const other = index + (action === 'flow-up' ? -1 : 1);
              if (other < 0 || other >= agent.config.flow.length) break;
              const first = graph.nodes.findIndex(node => node.legacyId === data.id), second = graph.nodes.findIndex(node => node.legacyId === agent.config.flow[other].id);
              [graph.nodes[first], graph.nodes[second]] = [graph.nodes[second], graph.nodes[first]];
            }
          }
          graph.edges = graph.nodes.slice(1).map((node, index) => ({ id: uid('edge'), source: graph.nodes[index].id, target: node.id, label: '', examples: [], ruleIds: [] }));
          syncRouteProjection(agent);
          changed(agent, 'routeGraph'); break;
        }
        case 'skill':
          if (!data.title?.trim() || !data.description?.trim() || !data.exit?.trim()) throw new Error('请补齐策略名称、说明与退出条件');
          {
            const skill = { id: uid('skill'), title: data.title, description: data.description, exit: data.exit };
            agent.config.skills.push(skill);
            const graph = agent.config.routeGraph, last = graph.nodes.at(-1);
            const node = { id: `route-${skill.id}`, legacyId: skill.id, title: skill.title, instruction: `${skill.description}\n退出：${skill.exit}`, type: 'reply', ruleIds: [] };
            graph.nodes.push(node); graph.edges.push({ id: uid('edge'), source: last.id, target: node.id, label: '', examples: [], ruleIds: [] });
            changed(agent, `skills.${agent.config.skills.length - 1}.description`); break;
          }
        case 'skill-remove': { const node = agent.config.routeGraph.nodes.find(item => item.legacyId === data.id); if (node) return dispatch('flow-node-delete', { id: node.id }); throw new Error('步骤已不存在'); }
        case 'tool':
          if (!data.title?.trim()) throw new Error('请填写动作名称');
          agent.config.tools.push({ id: uid('tool'), title: data.title, sideEffect: data.sideEffect === 'write' ? 'write' : 'read', mode: 'mock', requiresConfirm: true, status: 'mock', input: String(data.input || ''), successField: String(data.successField || ''), failureAction: 'handoff', unknownAction: '先查一次是否已经办成，不重复提交' }); changed(agent, 'tools'); toast('已登记本地动作。真实工具合同与授权沙盒仍待后端接入。'); break;
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
          for (const item of cases) {
            const reply = simulateReply(agent.config, item.input, agent.revokedSourceIds || []);
            item.result = reply.status === item.expected ? 'pass' : 'fail'; item.evaluatedRevision = agent.revision; item.stale = false;
            item.lastObserved = { answer: reply.text, status: reply.status, time: now() };
            item.history = [...(item.history || []), { result: item.result, time: item.lastObserved.time, revision: agent.revision }].slice(-5);
            if (item.result === 'fail') { if (item.decision !== 'wrong') item.decision = null; }
            else item.decision = 'pass';
          }
          toast('脚本回放已完成。只比较预期状态，不作为真实模型质量或正式发布 Gate。'); break;
        }
        case 'case-decide': {
          const item = state.cases.find(entry => entry.id === data.id && entry.agentId === agent.id && entry.result === 'fail');
          if (!item || !['wrong', 'outdated'].includes(data.decision)) throw new Error('只对当前变差的测试题作人工决定');
          item.truthHistory ||= [];
          item.truthHistory.push({ time: now(), before: item.expected, observed: item.lastObserved?.status, decision: data.decision, revision: agent.revision });
          item.decision = data.decision;
          if (data.decision === 'outdated') {
            item.expected = item.lastObserved.status; item.status = 'draft'; item.result = null; item.stale = true;
            invalidateSuite(agent.id); toast('真值修订已记录，需重新人工复核后再回放。');
          } else toast('答案错了已记录，这条测试题继续阻断上线。');
          break;
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
            syncLegacyNode(agent, item.path);
            changed(agent, item.path, true, { before, source: `人工采用提案 ${proposal.id}：${proposal.reason}` });
          }
          proposal.status = 'applied'; toast('提案已进入草稿，历史入口版本保持不变；需要重新试用和批准。'); break;
        }
        case 'proposal-reject': { const proposal = state.proposals.find(item => item.id === data.id && item.agentId === agent.id); if (proposal) proposal.status = 'rejected'; break; }
        case 'sandbox-deploy': {
          const blockers = pendingItems(agent, state).filter(item => item.level === 'block' && !item.id.startsWith('case:'));
          if (blockers.length) throw new Error(`测试前还有 ${blockers.length} 件必须处理的事：${blockers[0].text}`);
          const suite = state.cases.filter(item => item.agentId === agent.id && item.status === 'reviewed');
          if (!suite.length) throw new Error('至少需要一条已人工复核的测试题，再发到测试环境');
          for (const item of suite) {
            const reply = simulateReply(agent.config, item.input, agent.revokedSourceIds || []);
            item.lastObserved = { answer: reply.text, status: reply.status, time: now() };
            item.result = reply.status === item.expected ? 'pass' : 'fail';
            item.evaluatedRevision = agent.revision; item.stale = false; item.history = [...(item.history || []), { result: item.result, time: item.lastObserved.time, revision: agent.revision }].slice(-5);
            if (item.result === 'fail') { if (item.decision !== 'wrong') item.decision = null; }
            else item.decision = 'pass';
          }
          if (suite.some(item => item.result !== 'pass')) throw new Error(`本轮有 ${suite.filter(item => item.result !== 'pass').length} 条测试题变差；未生成新的测试环境快照`);
          let version = agent.versions.find(item => item.revision === agent.revision && item.status === 'sandbox');
          if (!version) {
            version = { id: uid('test-version'), revision: agent.revision, config: clone(agent.config), createdAt: now(), status: 'sandbox', evidence: ['本地测试环境快照'], label: '测试环境草稿' };
            agent.versions.unshift(version);
          }
          version.evaluatedSuite = suiteSignature(agent.id);
          agent.testVersionId = version.id; agent.checks.testedRevision = agent.revision;
          toast('已发到本地测试环境，未变更线上入口。'); break;
        }
        case 'release-request': {
          const version = agent.versions.find(item => item.id === agent.testVersionId && item.revision === agent.revision);
          if (!version) throw new Error('先把当前草稿发到测试环境');
          if (version.evaluatedSuite !== suiteSignature(agent.id)) throw new Error('测试题或真值已变化，请重新发到测试环境');
          if (agent.checks.testedRevision !== agent.revision || !state.cases.some(item => item.agentId === agent.id && item.status === 'reviewed' && item.result === 'pass' && item.evaluatedRevision === agent.revision)) throw new Error('当前草稿还没有通过已人工复核测试题；先在测试页完成回放');
          const blockers = pendingItems(agent, state).filter(item => item.level === 'block');
          if (blockers.length) throw new Error(`上线前还有 ${blockers.length} 件必须处理的事：${blockers[0].text}`);
          state.ui.releaseRequest = { agentId: agent.id, revision: agent.revision, versionId: version.id, status: 'pending', requestedAt: now() };
          toast('上线申请已记录，等待本地人工确认；没有更新线上入口。'); break;
        }
        case 'release-approve': {
          const request = state.ui.releaseRequest;
          if (!request || request.agentId !== agent.id || request.revision !== agent.revision || request.status !== 'pending') throw new Error('当前草稿没有待人工确认的上线申请');
          if (pendingItems(agent, state).some(item => item.level === 'block')) throw new Error('上线前问题已变化，请先处理并重新申请');
          const version = agent.versions.find(item => item.id === request.versionId);
          if (!version) throw new Error('测试快照已不存在');
          if (!versionValid(agent, version, state.connections)) throw new Error('测试快照的资料授权或模型连接已失效，请重新核对');
          if (version.evaluatedSuite !== suiteSignature(agent.id)) throw new Error('测试题或真值已变化，请重新检查并申请');
          version.status = 'published'; version.label = '本地线上入口版本'; version.evidence.push('人工本地确认');
          agent.checks.approvedRevision = agent.revision;
          agent.bindings.widget = version.id;
          agent.liveBindingsHistory.push(clone(agent.bindings));
          request.status = 'approved'; request.approvedAt = now();
          toast('本地入口已指向批准的冻结版本；未执行公网发布。'); break;
        }
        case 'release-rollback': {
          if ((agent.liveBindingsHistory || []).length < 2) throw new Error('没有更早的线上入口版本可回到');
          const previous = agent.liveBindingsHistory.at(-2);
          for (const versionId of Object.values(previous).filter(Boolean)) if (!versionValid(agent, agent.versions.find(item => item.id === versionId), state.connections)) throw new Error('上一线上版的资料授权或模型连接已失效，不能回到该版本；撤回授权不会因回退恢复');
          agent.liveBindingsHistory.pop();
          agent.bindings = clone(agent.liveBindingsHistory.at(-1));
          toast('本地入口已回到上一线上版；当前草稿未改动。'); break;
        }
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
          agent.config.qaItems ||= []; agent.config.keyFacts ||= []; agent.config.businessRules ||= [];
          if (!agent.config.handoffMigrated) {
            for (const [index, phrase] of (agent.config.handoff.phrases || []).filter(Boolean).entries()) agent.config.businessRules.push({ id: `rule-handoff-legacy-${index + 1}`, title: '客户要求人工', condition: { field: '客户说了', operator: 'exact', value: phrase }, action: 'handoff', recipient: agent.config.handoff.recipient, sourceRef: '原转人工配置', enabled: true, legacyHandoff: true });
            agent.config.handoffMigrated = true;
          }
          migrateRouteGraph(agent.config);
          for (const tool of agent.config.tools) Object.assign(tool, { input: tool.input || '', successField: tool.successField || '', failureAction: tool.failureAction || 'handoff', unknownAction: tool.unknownAction || '先查一次，不重复提交' });
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
      if (previousScope === 'agent' && routeScope(state.ui.page) === 'workspace') leaveAgentContext();
      resolveConfigurationSection();
      save(); notify(action); return { ok: true, value };
    } catch (error) { return fail(error.message); }
  }
  return { get state() { return state; }, currentAgent, readonly, dispatch, save, subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); } };
}
